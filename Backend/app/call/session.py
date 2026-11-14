"""
CallSession — one caller, on any channel.

The browser WebSocket and the Twilio phone bridge both feed 16 kHz PCM audio
into a CallSession and give it a Transport to talk back through. Everything
else is shared: turn-taking, barge-in, the streaming STT → agent → TTS
pipeline, timing, persistence, and supervisor handoff.

Turn-taking:
  Audio is buffered until the speaker stops (Silero VAD finds no speech in the
  trailing ~0.8 s), then the utterance runs as one background task. Because the
  turn is a task, the caller can interrupt at any stage (barge-in).

Streaming:
  The agent emits each sentence as soon as the LLM has written it. Sentences go
  straight to a TTS worker, so the caller hears the first sentence while the
  model is still producing the rest.
"""
import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from app.agent.context import CallContext
from app.agent.graph import run_agent
from app.agent.i18n import SUPPORTED_LANGUAGES, language_name, phrase
from app.agent.llm import fast_llm
from app.agent.text import parse_json
from app.call.registry import registry
from app.config import get_settings
from app.db import store
from app.stt.pipeline import get_stt
from app.stt.prosody import arousal_from_prosody
from app.tts.pipeline import get_tts
from langchain_core.messages import SystemMessage, HumanMessage

logger = logging.getLogger(__name__)
settings = get_settings()

SAMPLE_RATE = 16000
BYTES_PER_SECOND = SAMPLE_RATE * 2

# Endpointing
TAIL_SECONDS = 0.8                                  # silence that ends an utterance
TAIL_BYTES = int(BYTES_PER_SECOND * TAIL_SECONDS)
PREROLL_BYTES = BYTES_PER_SECOND * 1                # audio kept while waiting for speech
MAX_UTTERANCE_BYTES = BYTES_PER_SECOND * 15         # force a turn after 15 s of speech
MIN_FLUSH_BYTES = 4000
TAIL_MIN_SPEECH_MS = 150

# Tasks that must outlive their connection (post-call analysis after a hang-up)
_background: set[asyncio.Task] = set()


def _spawn(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _background.add(task)
    task.add_done_callback(_background.discard)
    return task


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Transport:
    """How a CallSession reaches its caller. Implemented per channel."""

    async def send_event(self, event: dict) -> None:
        """A JSON-style event (transcript, response, status...)."""

    async def send_audio(self, wav: bytes, turn_id: int) -> None:
        """One sentence of speech as a complete WAV file."""

    async def clear_audio(self, turn_id: int) -> None:
        """Barge-in: stop anything still playing for turns up to turn_id."""


class CallSession:
    def __init__(self, transport: Transport, channel: str = "web"):
        self.transport = transport
        self.channel = channel
        self.stt = get_stt()
        self.tts = get_tts()
        self.vad = self.stt.vad

        self.buffer = bytearray()
        self.in_speech = False          # True between speech start and end of utterance
        self.turn_id = 0
        self.turn_task: asyncio.Task | None = None

        # "" in settings = detect the language from the caller's first words
        self.auto_language = settings.whisper_language == ""
        self._new_call()

    def _new_call(self) -> None:
        self.call_id = uuid.uuid4().hex[:10]
        self.ctx = CallContext(
            call_id=self.call_id,
            channel=self.channel,
            language=settings.whisper_language or "en",
        )
        self.language_locked = not self.auto_language
        self.mode = "ai"                # "ai" | "human" (a supervisor has taken over)
        self.escalated = False
        self.escalate_reason: str | None = None
        self.handed_off = False
        self.handoff_summary: str | None = None
        self.turns: list[dict] = []
        self.started_at = _now_iso()
        self.call_started = False       # becomes True on the first real utterance
        self.ended = False
        self.analysis: dict | None = None

    # ── Sending ──────────────────────────────────────────────────────────────

    async def send(self, event: dict) -> None:
        await self.transport.send_event(event)

    # ── Audio in: endpointing and barge-in ───────────────────────────────────

    async def feed_audio(self, pcm: bytes) -> None:
        """pcm: int16 mono at 16 kHz."""
        self.buffer.extend(pcm)

        tail = bytes(self.buffer[-TAIL_BYTES:])
        loop = asyncio.get_running_loop()
        tail_has_speech = await loop.run_in_executor(
            None, self.vad.is_speech, tail, TAIL_MIN_SPEECH_MS, 100
        )

        if not self.in_speech:
            if tail_has_speech:
                # Speech started. If the agent is thinking or talking, this is a
                # barge-in: stop that turn and tell the caller's side to stop
                # playback (it may still be playing audio already delivered).
                self.in_speech = True
                self.cancel_turn()
                await self.transport.clear_audio(self.turn_id)
            elif len(self.buffer) > PREROLL_BYTES:
                del self.buffer[:-PREROLL_BYTES]      # still silence — keep a short pre-roll
        elif not tail_has_speech or len(self.buffer) >= MAX_UTTERANCE_BYTES:
            # Speaker stopped (or hit the cap) → process the utterance
            raw_audio = bytes(self.buffer)
            self.buffer.clear()
            self.in_speech = False
            self._start(self._run_turn(raw_audio, self.turn_id + 1, time.perf_counter()))

    def cancel_turn(self) -> bool:
        if self.turn_task and not self.turn_task.done():
            self.turn_task.cancel()
            return True
        return False

    def _start(self, coro) -> None:
        """Run `coro` as the current turn, replacing any turn still running."""
        self.cancel_turn()
        self.turn_id += 1
        self.turn_task = asyncio.create_task(coro)

    # ── Control messages from the caller's client ────────────────────────────

    async def handle_control(self, control: dict) -> None:
        action = control.get("action")

        if action == "end_session":
            # Mic turned off: process whatever was being said as a normal turn
            if self.in_speech and len(self.buffer) > MIN_FLUSH_BYTES:
                self._start(self._run_turn(bytes(self.buffer), self.turn_id + 1, time.perf_counter()))
            self.buffer.clear()
            self.in_speech = False
            await self.send({"type": "status", "message": "Mic off — tap to speak"})

        elif action == "clear_buffer":
            self.buffer.clear()
            self.in_speech = False
            await self.send({"type": "status", "message": "Buffer cleared"})

        elif action == "barge_in":
            self.cancel_turn()
            self.buffer.clear()
            self.in_speech = False
            await self.transport.clear_audio(self.turn_id)

        elif action == "set_language":
            await self.set_language(str(control.get("language") or "en"))

        elif action == "end_call":
            await self.end_call()

    async def set_language(self, language: str) -> None:
        if language == "auto":
            self.auto_language, self.language_locked = True, False
            await self.send({"type": "language", "language": "auto", "locked": False})
            return
        if language not in SUPPORTED_LANGUAGES:
            await self.send({"type": "error", "message": f"Language '{language}' is not supported"})
            return
        self.auto_language, self.language_locked = False, True
        self.ctx.language = language
        await self._announce_language()

    async def _announce_language(self) -> None:
        language = self.ctx.language
        has_voice = await asyncio.to_thread(self.tts.has_voice, language)
        await self.send({
            "type": "language",
            "language": language,
            "name": language_name(language),
            "locked": self.language_locked,
            "has_voice": has_voice,
        })

    # ── One turn: STT → agent (streaming) → TTS ──────────────────────────────

    async def _run_turn(self, raw_audio: bytes, turn_id: int, speech_end: float) -> None:
        """A failure here must never close the connection."""
        tts_task: asyncio.Task | None = None
        try:
            # 1. Speech to text (+ how it was said)
            stt_language = None if (self.auto_language and not self.language_locked) else self.ctx.language
            result = await self.stt.transcribe(raw_audio, stt_language)
            if not (result["is_speech"] and result["transcript"]):
                await self.send({"type": "status", "message": "Listening...", "turn_id": turn_id})
                return
            stt_done = time.perf_counter()
            transcript = result["transcript"]
            logger.info("STT: '%s' (lang=%s)", transcript, result["language"])

            # Auto mode: lock onto the first language we are confident about
            if self.auto_language and not self.language_locked:
                detected = result["language"]
                if detected in SUPPORTED_LANGUAGES and result["language_probability"] >= 0.7:
                    self.ctx.language = detected
                    self.language_locked = True
                    await self._announce_language()

            await self.send({
                "type": "transcript",
                "text": transcript,
                "language": self.ctx.language,
                "turn_id": turn_id,
            })
            await self._ensure_call_started()

            prosody = result.get("prosody") or {}
            arousal = arousal_from_prosody(prosody, self.ctx)

            # A human agent is on the call: pass the caller's words on, don't answer
            if self.mode == "human":
                await self._record_turn({"speaker": "caller", "transcript": transcript})
                return

            # 2 + 3. Agent and TTS run side by side, joined by a queue of sentences
            timings = {
                "endpoint_ms": int(TAIL_SECONDS * 1000),
                "stt_ms": round((stt_done - speech_end) * 1000),
            }
            sentences: asyncio.Queue = asyncio.Queue()
            tts_task = asyncio.create_task(self._tts_worker(sentences, turn_id, timings, speech_end))
            spoken: list[str] = []

            async def emit(event: dict) -> None:
                if event["type"] == "sentence":
                    if not spoken:
                        timings["llm_ms"] = max(0, round(
                            (time.perf_counter() - stt_done) * 1000 - timings.get("triage_ms", 0)
                        ))
                    spoken.append(event["text"])
                    await self.send({"type": "partial", "text": " ".join(spoken), "turn_id": turn_id})
                    await sentences.put(event["text"])
                elif event["type"] == "triage":
                    timings["triage_ms"] = event["triage_ms"]
                elif event["type"] == "tool":
                    await self.send({"type": "tool", "name": event["name"], "turn_id": turn_id})

            agent_result = await run_agent(transcript, self.ctx, emit, arousal)

            if agent_result["verified_now"] and self.ctx.verified_customer:
                await self.send({"type": "verified", "name": self.ctx.verified_customer["name"]})

            await self.send({
                "type": "response",
                "speaker": "ai",
                "text": agent_result["response"],
                "intent": agent_result["intent"],
                "confidence": agent_result["confidence"],
                "should_escalate": agent_result["should_escalate"],
                "summary": agent_result["summary"],
                "sentiment_score": agent_result["sentiment"],
                "sentiment_text": agent_result["sentiment_text"],
                "arousal": arousal,
                "prosody": prosody,
                "tools": agent_result["tools"],
                "pending_question": agent_result["pending_question"],
                "turn_id": turn_id,
            })

            turn = {
                "speaker": "ai",
                "transcript": transcript,
                "response": agent_result["response"],
                "intent": agent_result["intent"],
                "confidence": agent_result["confidence"],
                "sentiment": agent_result["sentiment"],
                "sentiment_text": agent_result["sentiment_text"],
                "arousal": arousal,
                "tools": agent_result["tools"],
                "kb_miss": agent_result["kb_miss"],
                "timings": timings,
            }
            row_id = await self._record_turn(turn)
            if agent_result["kb_miss"]:
                question = (agent_result["kb_queries"] or [transcript])[-1]
                await asyncio.to_thread(store.add_knowledge_gap, self.call_id, question)

            if agent_result["should_escalate"] and not self.escalated:
                self.escalated = True
                self.escalate_reason = agent_result["escalate_reason"]
                await registry.publish(self)
                _spawn(self._write_handoff_summary())

            # Let the TTS worker finish what is queued, then report timings
            await sentences.put(None)
            await tts_task
            timings["total_ms"] = timings["endpoint_ms"] + round((time.perf_counter() - speech_end) * 1000)
            await self.send({"type": "tts_end", "turn_id": turn_id})
            await self.send({"type": "metrics", "timings": timings, "turn_id": turn_id})
            await asyncio.to_thread(store.update_turn_timings, row_id, timings)

        except asyncio.CancelledError:
            # Barge-in or disconnect — the client is told separately
            raise
        except Exception:
            # LLM rate limit, network error, TTS failure... fail this turn only
            logger.exception("Turn %d failed", turn_id)
            try:
                await self.send({
                    "type": "error",
                    "message": "Sorry, I had trouble with that. Please try again.",
                    "turn_id": turn_id,
                })
            except Exception:
                pass
        finally:
            if tts_task and not tts_task.done():
                tts_task.cancel()

    async def _tts_worker(self, sentences: asyncio.Queue, turn_id: int, timings: dict, speech_end: float) -> None:
        """Turn queued sentences into audio, in order, as they arrive."""
        language = self.ctx.language
        if not await asyncio.to_thread(self.tts.has_voice, language):
            await self.send({
                "type": "status",
                "message": f"No {language_name(language)} voice installed — showing text only",
                "turn_id": turn_id,
            })
            while await sentences.get() is not None:
                pass
            return

        first = True
        while True:
            sentence = await sentences.get()
            if sentence is None:
                return
            started = time.perf_counter()
            wav = await self.tts.synthesize(sentence, language)
            if not wav:
                continue
            if first:
                await self.send({"type": "tts_start", "turn_id": turn_id})
                timings["tts_ms"] = round((time.perf_counter() - started) * 1000)
            await self.transport.send_audio(wav, turn_id)
            if first:
                # Time from the caller going quiet to the first audio leaving the server
                timings["ttfa_ms"] = timings["endpoint_ms"] + round((time.perf_counter() - speech_end) * 1000)
                first = False

    async def _speak(self, text: str, turn_id: int) -> None:
        """Speak a fixed line (no LLM)."""
        async for wav in self.tts.synthesize_stream(text, self.ctx.language):
            await self.transport.send_audio(wav, turn_id)
        await self.send({"type": "tts_end", "turn_id": turn_id})

    # ── Persistence and the supervisor board ─────────────────────────────────

    async def _ensure_call_started(self) -> None:
        if not self.call_started:
            self.call_started = True
            await asyncio.to_thread(store.create_call, self.call_id, self.channel, self.ctx.language)

    async def _record_turn(self, turn: dict) -> int:
        await self._ensure_call_started()
        turn = {"idx": len(self.turns), "ts": _now_iso(), **turn}
        self.turns.append(turn)
        row_id = await asyncio.to_thread(store.add_turn, self.call_id, turn["idx"], turn)
        await registry.publish(self)
        return row_id

    def _transcript_text(self) -> str:
        lines = []
        for t in self.turns:
            if t.get("transcript"):
                lines.append(f"Customer: {t['transcript']}")
            if t.get("response"):
                who = "Human agent" if t["speaker"] == "human" else "Assistant"
                lines.append(f"{who}: {t['response']}")
        return "\n".join(lines)

    def snapshot(self) -> dict:
        """Everything the supervisor console shows about this call."""
        status = ("ended" if self.ended else "human" if self.mode == "human"
                  else "escalated" if self.escalated else "active")
        return {
            "call_id": self.call_id,
            "channel": self.channel,
            "started_at": self.started_at,
            "language": self.ctx.language,
            "status": status,
            "mode": self.mode,
            "escalated": self.escalated,
            "escalate_reason": self.escalate_reason,
            "handoff_summary": self.handoff_summary,
            "verified_customer": self.ctx.verified_customer["name"] if self.ctx.verified_customer else None,
            "turns": list(self.turns),
            "analysis": self.analysis,
        }

    async def _write_handoff_summary(self) -> None:
        """A short briefing for the human who picks the call up."""
        call_id = self.call_id
        try:
            reply = await fast_llm.ainvoke([
                SystemMessage(content=(
                    "You brief a human support agent who is about to take over a customer call. "
                    "From the transcript write exactly three short lines, plain text, no markdown:\n"
                    "Wants: what the customer is trying to do\n"
                    "So far: what the assistant already did or found out\n"
                    "Next: the most useful next step for the human agent"
                )),
                HumanMessage(content=(
                    f"Escalation reason: {self.escalate_reason}\n"
                    f"Identity verified: {'yes' if self.ctx.verified_customer else 'no'}\n\n"
                    f"{self._transcript_text()}"
                )),
            ])
            summary = str(reply.content).strip()
        except Exception:
            logger.exception("Handoff summary failed")
            summary = f"Escalated: {self.escalate_reason}. Read the transcript for details."
        if self.call_id == call_id:          # the caller may have started a new call meanwhile
            self.handoff_summary = summary
            if not self.ended:
                await registry.publish(self)
            else:
                await registry.update_ended(call_id, {"handoff_summary": summary})

    # ── Supervisor actions ───────────────────────────────────────────────────

    async def takeover(self) -> None:
        """A human agent takes the call. The AI stops answering."""
        if self.mode == "human":
            return
        self.mode = "human"
        self.handed_off = True
        self.ctx.pending_action = None
        await self.send({"type": "handoff", "mode": "human"})
        await self.human_say(phrase("human_joined", self.ctx.language), speaker="system")

    async def release(self) -> None:
        """Hand the call back to the AI."""
        if self.mode != "human":
            return
        self.mode = "ai"
        await self.send({"type": "handoff", "mode": "ai"})
        await self.human_say(phrase("human_left", self.ctx.language), speaker="system")

    async def human_say(self, text: str, speaker: str = "human") -> None:
        """Speak a line typed by the supervisor (or a system line) to the caller."""
        text = text.strip()
        if not text:
            return
        turn_id = self.turn_id + 1

        async def run() -> None:
            await self.send({
                "type": "response", "speaker": speaker, "text": text,
                "intent": "human_agent", "turn_id": turn_id,
            })
            if speaker == "human":
                self.ctx.remember("(human agent on the call)", text)
            await self._record_turn({"speaker": speaker, "response": text, "intent": "human_agent"})
            await self._speak(text, turn_id)

        await self.transport.clear_audio(self.turn_id)
        self._start(run())

    # ── Ending a call ────────────────────────────────────────────────────────

    async def end_call(self) -> None:
        """The caller pressed "End call": summarise, then get ready for a new one."""
        self.cancel_turn()
        self.buffer.clear()
        self.in_speech = False
        await self.transport.clear_audio(self.turn_id)
        if not self.call_started:
            await self.send({"type": "status", "message": "No call to end yet"})
            return
        await self.send({"type": "status", "message": "Wrapping up the call..."})
        analysis = await self._finalize()
        await self.send({"type": "call_summary", "call_id": self.call_id, **(analysis or {})})
        self._new_call()
        await self.send({"type": "status", "message": "Call ended — tap the mic to start a new one"})

    async def close(self) -> None:
        """The connection dropped. Analysis continues in the background."""
        self.cancel_turn()
        if self.call_started and not self.ended:
            _spawn(self._finalize())

    async def _finalize(self) -> dict | None:
        if not self.call_started or self.ended:
            return None
        self.ended = True
        call_id = self.call_id
        await registry.end(self)

        analysis = await self._analyse_call()
        self.analysis = analysis
        await asyncio.to_thread(store.end_call, call_id, {
            "language": self.ctx.language,
            "escalated": self.escalated,
            "handed_off": self.handed_off,
            **analysis,
        })
        await registry.update_ended(call_id, {"analysis": analysis})
        return analysis

    async def _analyse_call(self) -> dict:
        """Post-call analysis: summary, outcome, estimated satisfaction, topics."""
        sentiments = [t["sentiment"] for t in self.turns if t.get("sentiment") is not None]
        avg = sum(sentiments) / len(sentiments) if sentiments else 0.0
        # Used if the LLM is unavailable: satisfaction from average sentiment
        fallback = {
            "summary": f"{len(self.turns)}-turn call." + (" Escalated to a human agent." if self.escalated else ""),
            "resolution": "escalated" if self.escalated else "unresolved",
            "csat": max(1, min(5, round(3 + 2 * avg))),
            "topics": sorted({t["intent"] for t in self.turns if t.get("intent")}),
        }
        try:
            reply = await fast_llm.ainvoke([
                SystemMessage(content=(
                    "You review a finished customer-service call. Respond ONLY with JSON, no markdown:\n"
                    '{"summary": "<two sentences: what the customer wanted and what happened>", '
                    '"resolution": "resolved" | "unresolved" | "escalated", '
                    '"csat": <1-5, your estimate of how satisfied the customer was>, '
                    '"topics": ["<short topic>", ...]}\n'
                    "resolved = the customer got what they needed from the assistant. "
                    "escalated = the call was handed to a human. Write the summary in English."
                )),
                HumanMessage(content=(
                    f"Escalated: {'yes' if self.escalated else 'no'}\n"
                    f"Average sentiment (-1..1): {avg:.2f}\n\n{self._transcript_text()}"
                )),
            ])
            parsed = parse_json(reply.content)
            resolution = str(parsed.get("resolution") or "").lower()
            if resolution not in ("resolved", "unresolved", "escalated"):
                resolution = fallback["resolution"]
            if self.escalated:
                resolution = "escalated"
            return {
                "summary": str(parsed.get("summary") or fallback["summary"]).strip(),
                "resolution": resolution,
                "csat": max(1, min(5, int(round(float(parsed.get("csat", fallback["csat"])))))),
                "topics": [str(t) for t in (parsed.get("topics") or [])][:6],
            }
        except Exception:
            logger.exception("Post-call analysis failed — using fallback")
            return fallback
