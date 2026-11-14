"""
Evaluation harness — replays recorded utterances through the real pipeline and
reports how well each stage did.

    python -m eval.make_audio          # once: create eval/audio/*.wav
    python -m eval.run_eval            # full run (uses the Groq API)
    python -m eval.run_eval --no-llm   # speech + retrieval only, no API calls

Metrics
  WER               word error rate of speech-to-text against the reference text
  Order numbers     spoken order number recovered as digits ("one zero zero two" → 1002)
  Retrieval hit     the expected FAQ is among the retrieved articles
  Intent accuracy   the turn was filed under the expected intent
  Tool accuracy     the agent called the expected tool
  STT time          average transcription time per utterance

Each case runs as the first turn of a fresh call, against a temporary copy of
the sample database, so the run changes nothing. Results are also written to
eval/report.json.
"""
import argparse
import asyncio
import json
import os
import re
import sys
import tempfile
import time
import wave
from math import gcd
from pathlib import Path
import numpy as np
from scipy.signal import resample_poly

EVAL_DIR = Path(__file__).parent
AUDIO_DIR = EVAL_DIR / "audio"

# Use a throwaway database so tool calls made during the run touch nothing real.
# Must be set before any app module reads the settings.
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(prefix="voiceiq-eval-"), "eval.db")

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# ── Scoring helpers ──────────────────────────────────────────────────────────

def _words(text: str) -> list[str]:
    from app.agent.text import normalize_transcript
    text = normalize_transcript(text).lower()
    return re.sub(r"[^a-z0-9\s]", " ", text).split()


def word_errors(reference: str, hypothesis: str) -> tuple[int, int]:
    """(edit distance in words, reference length) — numbers are compared as digits."""
    ref, hyp = _words(reference), _words(hypothesis)
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i]
        for j, h in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h)))
        prev = cur
    return prev[-1], len(ref)


def load_pcm16k(path: Path) -> bytes:
    with wave.open(str(path)) as w:
        rate, channels = w.getframerate(), w.getnchannels()
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    if channels > 1:
        pcm = pcm.reshape(-1, channels).mean(axis=1).astype(np.int16)
    if rate != 16000:
        g = gcd(rate, 16000)
        pcm = np.clip(resample_poly(pcm.astype(np.float32), 16000 // g, rate // g), -32768, 32767).astype(np.int16)
    pad = np.zeros(4000, dtype=np.int16)          # a little silence either side, like a live call
    return np.concatenate([pad, pcm, pad]).tobytes()


def _rate(hits: int, total: int) -> float | None:
    return round(hits / total, 3) if total else None


def _pct(value: float | None) -> str:
    return "   n/a" if value is None else f"{value * 100:5.1f}%"


# ── Run ──────────────────────────────────────────────────────────────────────

async def run(args) -> dict:
    from app.agent.context import CallContext
    from app.agent.text import normalize_transcript
    from app.db import store
    from app.rag.retriever import get_retriever
    from app.stt.pipeline import get_stt

    cases = json.loads((EVAL_DIR / "cases.json").read_text(encoding="utf-8"))
    if args.only:
        cases = [c for c in cases if args.only in c["id"]]

    store.init_db()
    stt = get_stt()
    retriever = get_retriever()
    if not args.no_llm:
        from app.agent.graph import run_agent

    rows = []
    for case in cases:
        row = {"id": case["id"], "reference": case["text"]}
        audio = AUDIO_DIR / f"{case['id']}.wav"

        # 1. Speech to text
        if audio.exists():
            started = time.perf_counter()
            result = await stt.transcribe(load_pcm16k(audio), "en")
            row["stt_ms"] = round((time.perf_counter() - started) * 1000)
            row["transcript"] = result["transcript"]
            row["word_errors"], row["ref_words"] = word_errors(case["text"], result["transcript"])
        else:
            row["transcript"] = case["text"]        # no recording: score the later stages on the text
            row["no_audio"] = True
        heard = row["transcript"]

        # 2. Order number recovered from speech
        if case.get("order_id"):
            row["order_ok"] = case["order_id"] in re.findall(r"\d+", normalize_transcript(heard))

        # 3. Retrieval
        if case.get("faq_id"):
            _, distance, ids = await asyncio.to_thread(retriever.search, heard)
            row["retrieval_ok"] = case["faq_id"] in ids
            row["distance"] = None if distance is None else round(distance, 2)

        # 4. Agent: intent and tool choice
        if not args.no_llm and heard:
            try:
                out = await run_agent(heard, CallContext(call_id=f"eval-{case['id']}"))
                row["intent"] = out["intent"]
                row["intent_ok"] = out["intent"] == case["intent"]
                row["tools"] = out["tools"]
                if case.get("tool"):
                    row["tool_ok"] = case["tool"] in out["tools"]
                row["response"] = out["response"]
            except Exception as e:
                row["error"] = f"{type(e).__name__}: {e}"[:200]
            await asyncio.sleep(args.delay)         # stay under the API's tokens-per-minute limit

        rows.append(row)
        mark = "ok " if row.get("intent_ok", True) and row.get("retrieval_ok", True) and row.get("order_ok", True) else "MISS"
        print(f"  [{mark}] {case['id']:<16} heard: {heard!r}"
              + (f" → {row['intent']}" if "intent" in row else "")
              + (f"  ERROR {row['error']}" if "error" in row else ""))

    def count(key):
        scored = [r for r in rows if key in r]
        return sum(bool(r[key]) for r in scored), len(scored)

    with_audio = [r for r in rows if "word_errors" in r]
    ref_words = sum(r["ref_words"] for r in with_audio)
    summary = {
        "cases": len(rows),
        "cases_with_audio": len(with_audio),
        "wer": round(sum(r["word_errors"] for r in with_audio) / ref_words, 3) if ref_words else None,
        "order_number_accuracy": _rate(*count("order_ok")),
        "retrieval_hit_rate": _rate(*count("retrieval_ok")),
        "intent_accuracy": _rate(*count("intent_ok")),
        "tool_accuracy": _rate(*count("tool_ok")),
        "avg_stt_ms": round(sum(r["stt_ms"] for r in with_audio) / len(with_audio)) if with_audio else None,
        "errors": sum("error" in r for r in rows),
    }
    return {"summary": summary, "cases": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the VoiceIQ pipeline on recorded utterances.")
    parser.add_argument("--no-llm", action="store_true", help="skip the agent (no API calls): speech and retrieval only")
    parser.add_argument("--only", help="run only cases whose id contains this text")
    parser.add_argument("--delay", type=float, default=10.0, help="seconds to wait between agent calls (default 10)")
    args = parser.parse_args()

    print("Running evaluation...")
    report = asyncio.run(run(args))
    s = report["summary"]

    print("\n── Results " + "─" * 40)
    print(f"  Cases                  {s['cases']} ({s['cases_with_audio']} with audio)")
    if s["cases_with_audio"] == 0:
        print("  No audio found — run `python -m eval.make_audio` to score speech recognition.")
    print(f"  Word error rate        {_pct(s['wer'])}   (lower is better)")
    print(f"  Order numbers heard    {_pct(s['order_number_accuracy'])}")
    print(f"  Retrieval hit rate     {_pct(s['retrieval_hit_rate'])}")
    print(f"  Intent accuracy        {_pct(s['intent_accuracy'])}")
    print(f"  Tool accuracy          {_pct(s['tool_accuracy'])}")
    print(f"  Avg speech-to-text     {s['avg_stt_ms'] if s['avg_stt_ms'] is not None else 'n/a'} ms")
    if s["errors"]:
        print(f"  Cases that errored     {s['errors']}")

    out = EVAL_DIR / "report.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nFull report: {out}")


if __name__ == "__main__":
    main()
