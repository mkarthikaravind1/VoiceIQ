from pydantic_settings import BaseSettings
from functools import lru_cache
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BACKEND_DIR.parent


class Settings(BaseSettings):
    # Groq
    groq_api_key: str = ""

    # LLM
    # Fast model: classification (sentiment/intent) and post-call analysis
    llm_model: str = "openai/gpt-oss-20b"
    # Stronger model: the tool-calling agent that talks to the caller
    agent_model: str = "openai/gpt-oss-120b"
    # Only sent to reasoning models (gpt-oss); "low" keeps replies fast
    llm_reasoning_effort: str = "low"
    llm_temperature: float = 0.3

    # STT
    whisper_model: str = "base"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    # Language a call starts in. "" = auto-detect from the caller's first words.
    whisper_language: str = "en"
    # Languages the agent may answer in (the caller can switch in the UI)
    supported_languages: str = "en,hi,ta"

    # TTS
    #tts_model: str = "tts_models/en/ljspeech/tacotron2-DDC"
    tts_model: str = "en_US-lessac-medium"   # Piper voice model name (English)
    # Extra Piper voices as lang:model pairs. A language without a downloaded
    # voice still works — the reply is shown as text only.
    tts_voices: str = "hi:hi_IN-pratham-medium"
    # Folder holding the downloaded Piper models (<name>.onnx + <name>.onnx.json)
    tts_model_dir: str = str(_BACKEND_DIR / "data" / "tts_models")

    # RAG
    chroma_persist_dir: str = str(_BACKEND_DIR / "data" / "chroma_db")
    embedding_model: str = "all-MiniLM-L6-v2"
    rag_top_k: int = 3
    # Cosine distance above which an FAQ is treated as unrelated (0 = identical)
    rag_max_distance: float = 0.8
    # Above this the best match is only loosely related: the agent is warned
    # not to guess, and the question is logged as a knowledge gap
    rag_weak_distance: float = 0.6

    # Agent
    confidence_threshold: float = 0.6

    # Database (orders + call history)
    db_path: str = str(_BACKEND_DIR / "data" / "voiceiq.db")

    # Phone bridge: public host Twilio can reach, e.g. "abc123.ngrok-free.app"
    public_host: str = ""

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    class Config:
        # Resolved from this file, not the current directory, so the key loads
        # whether the server is started from the repo root or from Backend/.
        # Backend/.env (if present) overrides the repo-root .env.
        env_file = (str(_REPO_ROOT / ".env"), str(_BACKEND_DIR / ".env"))
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()