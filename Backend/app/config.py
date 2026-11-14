from pydantic_settings import BaseSettings
from functools import lru_cache
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BACKEND_DIR.parent


class Settings(BaseSettings):
    # Groq
    groq_api_key: str = ""

    # LLM
    llm_model: str = "llama-3.1-8b-instant"
    llm_temperature: float = 0.3

    # STT
    whisper_model: str = "base"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    # Language Whisper should expect. The voice, prompts and FAQ are English,
    # so this defaults to "en". Set to "" to let Whisper auto-detect.
    whisper_language: str = "en"

    # TTS
    #tts_model: str = "tts_models/en/ljspeech/tacotron2-DDC"
    tts_model: str = "en_US-lessac-medium"   # Piper voice model name

    # RAG
    chroma_persist_dir: str = str(_BACKEND_DIR / "data" / "chroma_db")
    embedding_model: str = "all-MiniLM-L6-v2"
    rag_top_k: int = 3
    # Cosine distance above which an FAQ is treated as unrelated (0 = identical)
    rag_max_distance: float = 0.8

    # Agent
    confidence_threshold: float = 0.6

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