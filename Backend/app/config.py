from pydantic_settings import BaseSettings
from functools import lru_cache


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

    # TTS
    #tts_model: str = "tts_models/en/ljspeech/tacotron2-DDC"
    tts_model: str = "en_US-lessac-medium"   # Piper voice model name

    # RAG
    chroma_persist_dir: str = "./data/chroma_db"
    embedding_model: str = "all-MiniLM-L6-v2"
    rag_top_k: int = 3

    # Agent
    confidence_threshold: float = 0.6

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: str = "http://localhost:5173"

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings()