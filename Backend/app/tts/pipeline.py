"""
TTS Pipeline using Piper.

One sentence is synthesized at a time, so audio for the first sentence can be
sent while the LLM is still writing the rest of the reply.

Voices are per language. English is loaded at startup; other voices listed in
TTS_VOICES are loaded the first time that language is spoken. A language with
no downloaded voice simply has no audio — the reply is still shown as text.
"""
import io
import re
import asyncio
import threading
import wave
from pathlib import Path
import numpy as np
from piper.voice import PiperVoice
from app.config import get_settings

settings = get_settings()

# Folder holding downloaded Piper models (<name>.onnx + <name>.onnx.json)
MODEL_DIR = Path(settings.tts_model_dir)

# Sentence splitter regex
SENTENCE_RE = re.compile(r'(?<=[.!?।])\s+')


def _voice_table() -> dict[str, str]:
    """language code → Piper model name, from settings."""
    table = {"en": settings.tts_model}
    for pair in settings.tts_voices.split(","):
        if ":" in pair:
            lang, model = pair.split(":", 1)
            if lang.strip() and model.strip():
                table[lang.strip()] = model.strip()
    return table


class TTSPipeline:
    def __init__(self):
        self.voice_names = _voice_table()
        self._voices: dict[str, PiperVoice | None] = {}
        self._load_lock = threading.Lock()
        self._get_voice("en")      # warm the default voice at startup

    def _get_voice(self, language: str) -> PiperVoice | None:
        """Load (once) and return the voice for a language, or None if not installed."""
        if language in self._voices:
            return self._voices[language]
        with self._load_lock:
            if language in self._voices:
                return self._voices[language]
            voice = None
            name = self.voice_names.get(language)
            path = MODEL_DIR / f"{name}.onnx" if name else None
            if path is None:
                print(f"⚠️  No Piper voice configured for '{language}' — replies will be text only")
            elif not path.exists():
                print(f"⚠️  Piper model not found at {path}")
                print("   Download it with the curl command in the README (Setup, Backend).")
            else:
                print(f"🔈 Loading Piper TTS voice [{name}] for '{language}'...")
                voice = PiperVoice.load(str(path), config_path=str(path) + ".json")
                print("✅ Piper TTS ready")
            self._voices[language] = voice
            return voice

    # Kept for older callers: the default (English) voice
    @property
    def voice(self) -> PiperVoice | None:
        return self._get_voice("en")

    def has_voice(self, language: str) -> bool:
        return self._get_voice(language) is not None

    def _split_sentences(self, text: str) -> list[str]:
        """Split response text into sentences for streaming."""
        sentences = SENTENCE_RE.split(text.strip())
        return [s.strip() for s in sentences if s.strip()]

    def _synthesize_sentence(self, sentence: str, language: str = "en") -> bytes:
        """
        Synthesize a single sentence. Returns a complete WAV file as bytes
        (16-bit mono at the voice's sample rate), or b"" if there is no voice.
        """
        voice = self._get_voice(language)
        if voice is None:
            return b""

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(voice.config.sample_rate)

            for chunk in voice.synthesize(sentence):
                samples = (chunk.audio_float_array * 32767).astype(np.int16)
                wav_file.writeframes(samples.tobytes())

        return buf.getvalue()

    async def synthesize(self, sentence: str, language: str = "en") -> bytes:
        """One sentence → WAV bytes, without blocking the event loop."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._synthesize_sentence, sentence, language)

    async def synthesize_stream(self, text: str, language: str = "en"):
        """Async generator — yields WAV audio bytes sentence by sentence."""
        if not self.has_voice(language):
            return
        for sentence in self._split_sentences(text):
            audio_bytes = await self.synthesize(sentence, language)
            if audio_bytes:
                yield audio_bytes


# Singleton
_tts_instance: TTSPipeline | None = None


def get_tts() -> TTSPipeline:
    global _tts_instance
    if _tts_instance is None:
        _tts_instance = TTSPipeline()
    return _tts_instance
