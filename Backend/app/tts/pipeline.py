"""
TTS Pipeline using Piper.
Splits LLM response into sentences and synthesizes each one immediately,
streaming audio chunks back to the client as they're ready.
This reduces perceived latency from ~4s to ~1s.
"""
import re
import io
import asyncio
import wave
from pathlib import Path
from piper.voice import PiperVoice
from app.config import get_settings

settings = get_settings()

# Path to downloaded Piper model
MODEL_DIR = Path(__file__).parent.parent.parent / "data" / "tts_models"
MODEL_PATH = MODEL_DIR / f"{settings.tts_model}.onnx"
CONFIG_PATH = MODEL_DIR / f"{settings.tts_model}.onnx.json"

# Sentence splitter regex
SENTENCE_RE = re.compile(r'(?<=[.!?])\s+')


class TTSPipeline:
    def __init__(self):
        self.voice: PiperVoice | None = None
        self._load_model()

    def _load_model(self):
        if not MODEL_PATH.exists():
            print(f"⚠️  Piper model not found at {MODEL_PATH}")
            print("   Run the curl commands in Phase 5 instructions to download it.")
            return
        print(f"🔈 Loading Piper TTS model [{settings.tts_model}]...")
        self.voice = PiperVoice.load(str(MODEL_PATH), config_path=str(CONFIG_PATH))
        print("✅ Piper TTS ready")

    def _split_sentences(self, text: str) -> list[str]:
        """Split response text into sentences for streaming."""
        sentences = SENTENCE_RE.split(text.strip())
        # Filter out empty strings, strip whitespace
        return [s.strip() for s in sentences if s.strip()]

    def _synthesize_sentence(self, sentence: str) -> bytes:
        """
        Synthesize a single sentence to raw WAV bytes.
        Returns the WAV file as bytes (including header).
        """
        assert self.voice is not None
        buf = io.BytesIO()
        
        import numpy as np

        voice = self.voice
        assert voice is not None

        with wave.open(buf, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(voice.config.sample_rate)

            for chunk in voice.synthesize(sentence):
                samples = (chunk.audio_float_array * 32767).astype(np.int16)
                wav_file.writeframes(samples.tobytes())
        
        # with wave.open(buf, "wb") as wav_file:
        #     self.voice.synthesize(sentence, wav_file)
        return buf.getvalue()

    async def synthesize_stream(self, text: str):
        """
        Async generator — yields WAV audio bytes sentence by sentence.
        Each yield = one sentence worth of audio, ready to play immediately.

        Usage in websocket.py:
            async for audio_chunk in tts.synthesize_stream(response_text):
                await _send(ws, {"type": "audio", "data": base64.b64encode(audio_chunk).decode()})
        """
        if self.voice is None:
            print("[TTS] Model not loaded — skipping synthesis")
            return

        sentences = self._split_sentences(text)
        if not sentences:
            return

        loop = asyncio.get_event_loop()

        for sentence in sentences:
            # Run CPU-heavy synthesis in thread pool to not block event loop
            audio_bytes = await loop.run_in_executor(
                None, self._synthesize_sentence, sentence
            )
            print(f"[TTS] Synthesized: '{sentence[:50]}...' → {len(audio_bytes)} bytes")
            yield audio_bytes

    async def synthesize_full(self, text: str) -> bytes:
        """Returns first sentence audio — for short single-sentence responses only."""
        async for chunk in self.synthesize_stream(text):
            return chunk
        return b""


# Singleton
_tts_instance: TTSPipeline | None = None


def get_tts() -> TTSPipeline:
    global _tts_instance
    if _tts_instance is None:
        _tts_instance = TTSPipeline()
    return _tts_instance