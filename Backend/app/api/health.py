from fastapi import APIRouter
from app.config import get_settings

router = APIRouter()
settings = get_settings()


@router.get("/health")
async def health_check():
    return {
        "status": "ok",
        "version": "1.0.0",
        "config": {
            "whisper_model": settings.whisper_model,
            "llm_model": settings.llm_model,
            "tts_model": settings.tts_model,
        },
    }