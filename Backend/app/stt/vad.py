"""
Voice Activity Detection using Silero VAD.
Buffers incoming audio chunks and only returns speech segments,
filtering out silence — reduces STT calls and improves accuracy.
"""

import numpy as np
import torch
from silero_vad import load_silero_vad, get_speech_timestamps
from app.config import get_settings

settings = get_settings()

# Silero VAD expects 16kHz mono audio
SAMPLE_RATE = 16000
# Minimum speech duration to bother transcribing (seconds)
MIN_SPEECH_DURATION = 0.3


class VADProcessor:
    def __init__(self):
        self.model = None
        self._load_model()

    def _load_model(self):
        print("🔊 Loading Silero VAD model...")
        self.model = load_silero_vad()
        #self.model.eval()
        print("✅ Silero VAD ready")

    def is_speech(self, audio_bytes: bytes) -> bool:
        """
        Quick check: does this audio chunk contain speech?
        Used for real-time gating before sending to Whisper.
        """
        audio_np = self._bytes_to_tensor(audio_bytes)
        if audio_np is None:
            return False

        timestamps = get_speech_timestamps(
            audio_np,
            self.model,
            sampling_rate=SAMPLE_RATE,
            min_speech_duration_ms=int(MIN_SPEECH_DURATION * 1000),
            min_silence_duration_ms=300,
        )
        return len(timestamps) > 0

    def extract_speech(self, audio_bytes: bytes) -> bytes | None:
        """
        Extract only the speech portions from an audio buffer.
        Returns concatenated speech audio as bytes, or None if no speech found.
        """
        audio_tensor = self._bytes_to_tensor(audio_bytes)
        if audio_tensor is None:
            return None

        timestamps = get_speech_timestamps(
            audio_tensor,
            self.model,
            sampling_rate=SAMPLE_RATE,
            min_speech_duration_ms=int(MIN_SPEECH_DURATION * 1000),
            min_silence_duration_ms=300,
            return_seconds=False,
        )

        if not timestamps:
            return None

        # Concatenate all speech segments
        speech_segments = []
        for ts in timestamps:
            segment = audio_tensor[ts["start"]: ts["end"]]
            speech_segments.append(segment)

        speech_audio = torch.cat(speech_segments)
        return speech_audio.numpy().tobytes()

    def _bytes_to_tensor(self, audio_bytes: bytes) -> torch.Tensor | None:
        """Convert raw PCM bytes (int16, 16kHz) to float32 tensor."""
        if len(audio_bytes) < 512:
            return None
        try:
            audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32)
            audio_np /= 32768.0  # normalize to [-1, 1]
            return torch.from_numpy(audio_np)
        except Exception as e:
            print(f"[VAD] Audio conversion error: {e}")
            return None


# Singleton
_vad_instance: VADProcessor | None = None


def get_vad() -> VADProcessor:
    global _vad_instance
    if _vad_instance is None:
        _vad_instance = VADProcessor()
    return _vad_instance