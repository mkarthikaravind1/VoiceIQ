"""
Create the audio for the evaluation cases.

    python -m eval.make_audio

Each case in eval/cases.json is spoken with the project's own Piper voice and
saved as eval/audio/<id>.wav (16 kHz mono). Synthetic speech is clean, so it
gives a best-case baseline. For a realistic score, record the same sentences
yourself (any sample rate, mono) and drop them in eval/audio/ under the same
file names — existing files are never overwritten.
"""
import io
import json
import wave
from math import gcd
from pathlib import Path
import numpy as np
from scipy.signal import resample_poly

EVAL_DIR = Path(__file__).parent
AUDIO_DIR = EVAL_DIR / "audio"
TARGET_RATE = 16000


def main() -> None:
    from app.tts.pipeline import get_tts

    tts = get_tts()
    if not tts.has_voice("en"):
        raise SystemExit("No English Piper voice found — see the README for the download command.")

    AUDIO_DIR.mkdir(exist_ok=True)
    cases = json.loads((EVAL_DIR / "cases.json").read_text(encoding="utf-8"))
    made = 0
    for case in cases:
        path = AUDIO_DIR / f"{case['id']}.wav"
        if path.exists():
            continue
        with wave.open(io.BytesIO(tts._synthesize_sentence(case["text"], "en"))) as w:
            rate = w.getframerate()
            pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        g = gcd(rate, TARGET_RATE)
        pcm = np.clip(resample_poly(pcm.astype(np.float32), TARGET_RATE // g, rate // g), -32768, 32767).astype(np.int16)
        with wave.open(str(path), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(TARGET_RATE)
            out.writeframes(pcm.tobytes())
        made += 1
    print(f"Created {made} file(s) in {AUDIO_DIR} ({len(cases) - made} already there)")


if __name__ == "__main__":
    main()
