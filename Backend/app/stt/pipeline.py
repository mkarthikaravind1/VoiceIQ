"""
STT Pipeline using Faster-Whisper.
Accepts raw PCM audio bytes, returns transcription text.
Runs in a thread pool to avoid blocking the async event loop.
"""

import asyncio
import numpy as np
from faster_whisper import WhisperModel
from app.config import get_settings
from app.stt.vad import get_vad

settings = get_settings()

SAMPLE_RATE = 16000


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

    def _transcribe_sync(self, audio_bytes: bytes) -> dict:
        """
        Synchronous transcription — runs in thread pool.
        Returns dict with transcript text, language, and confidence.
        """
        # Step 1: VAD — extract only speech portions
        assert self.vad is not None
        speech_bytes = self.vad.extract_speech(audio_bytes)
        if speech_bytes is None:
            return {"transcript": "", "language": "en", "confidence": 0.0, "is_speech": False}

        # Step 2: Convert PCM bytes → float32 numpy array for Whisper
        audio_np = np.frombuffer(speech_bytes, dtype=np.float32)

        # Step 3: Transcribe
        assert self.model is not None
        segments, info = self.model.transcribe(
            audio_np,
            beam_size=5,
            language=None,        # auto-detect language
            vad_filter=False,     # we already ran VAD above
            word_timestamps=False,
        )

        # Collect all segment texts
        transcript_parts = [seg.text.strip() for seg in segments]
        transcript = " ".join(transcript_parts).strip()

        # Filter out noise — too short or no real words
        if len(transcript) < 3 or len(transcript.split()) < 2:
            return {"transcript": "", "language": "en", "confidence": 0.0, "is_speech": False}

        # Faster-Whisper gives avg log prob per segment; convert to 0-1 confidence
        #confidence = min(1.0, max(0.0, info.transcription_options.beam_size / 10))     
        confidence = round(info.language_probability, 3)

        return {
            "transcript": transcript,
            "language": info.language,
            "language_probability": round(info.language_probability, 3),
            "confidence": confidence,
            "is_speech": True,
        }

    async def transcribe(self, audio_bytes: bytes) -> dict:
        """
        Async wrapper — offloads CPU-heavy transcription to thread pool
        so the FastAPI event loop stays unblocked.
        """
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, self._transcribe_sync, audio_bytes)
        return result


# Singleton
_stt_instance: STTPipeline | None = None


def get_stt() -> STTPipeline:
    global _stt_instance
    if _stt_instance is None:
        _stt_instance = STTPipeline()
    return _stt_instance