"""
STT Pipeline using Faster-Whisper.
Accepts raw PCM audio bytes, returns the transcript plus prosody features
(loudness, pitch) of the same audio.
Runs in a thread pool to avoid blocking the async event loop.
"""

import asyncio
import numpy as np
from faster_whisper import WhisperModel
from app.config import get_settings
from app.stt.prosody import extract_prosody
from app.stt.vad import get_vad

settings = get_settings()

SAMPLE_RATE = 16000

_NO_SPEECH = {"transcript": "", "language": "en", "language_probability": 0.0,
              "confidence": 0.0, "is_speech": False, "prosody": {}}


class STTPipeline:
    def __init__(self):
        self.model: WhisperModel | None = None
        self.vad = None
        self._load_model()

    def _load_model(self):
        print(f"🎙️  Loading Faster-Whisper [{settings.whisper_model}] on {settings.whisper_device}...")
        self.model = WhisperModel(
            settings.whisper_model,
            device=settings.whisper_device,
            compute_type=settings.whisper_compute_type,
        )
        self.vad = get_vad()
        print("✅ Faster-Whisper ready")

    def _transcribe_sync(self, audio_bytes: bytes, language: str | None) -> dict:
        """
        Synchronous transcription — runs in thread pool.
        language: ISO code to force, or None to let Whisper detect it.
        """
        # Step 1: VAD — extract only speech portions
        assert self.vad is not None
        speech_bytes = self.vad.extract_speech(audio_bytes)
        if speech_bytes is None:
            return dict(_NO_SPEECH)

        # Step 2: Convert PCM bytes → float32 numpy array for Whisper
        audio_np = np.frombuffer(speech_bytes, dtype=np.float32)

        # Step 3: Transcribe
        assert self.model is not None
        segments, info = self.model.transcribe(
            audio_np,
            beam_size=5,
            language=language or None,
            vad_filter=False,     # we already ran VAD above
            word_timestamps=False,
        )

        # Skip segments Whisper itself thinks are not speech (this is where
        # "Thank you." hallucinations on background noise come from)
        transcript_parts = [
            seg.text.strip()
            for seg in segments
            if not (seg.no_speech_prob > 0.6 and seg.avg_logprob < -1.0)
        ]
        transcript = " ".join(p for p in transcript_parts if p).strip()

        # One-word answers like "Yes" or "No" are valid and kept
        if len(transcript) < 2:
            return dict(_NO_SPEECH)

        return {
            "transcript": transcript,
            "language": info.language,
            "language_probability": round(info.language_probability, 3),
            "confidence": round(info.language_probability, 3),
            "is_speech": True,
            "prosody": extract_prosody(audio_np, transcript),
        }

    async def transcribe(self, audio_bytes: bytes, language: str | None = None) -> dict:
        """
        Async wrapper — offloads CPU-heavy transcription to thread pool
        so the FastAPI event loop stays unblocked.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._transcribe_sync, audio_bytes, language)


# Singleton
_stt_instance: STTPipeline | None = None


def get_stt() -> STTPipeline:
    global _stt_instance
    if _stt_instance is None:
        _stt_instance = STTPipeline()
    return _stt_instance
