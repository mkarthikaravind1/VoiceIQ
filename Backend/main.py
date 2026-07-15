import os
os.environ["PYTORCH_NO_CUDA_MEMORY_CACHING"] = "1"

import torch
torch.multiprocessing.set_sharing_strategy("file_system")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import get_settings
from app.api import health, websocket
from app.agent.graph import get_agent
from app.rag.retriever import get_retriever
from app.tts.pipeline import get_tts

settings = get_settings()

app = FastAPI(
    title="VoiceIQ API",
    description="Open-Source Customer Service Voice Agent",
    version="1.0.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(health.router, prefix="/api", tags=["Health"])
app.include_router(websocket.router, tags=["WebSocket"])


@app.on_event("startup")
async def startup_event():
    print("🚀 VoiceIQ backend starting up...")
    get_agent()
    get_retriever()
    get_tts()
    print(f"   Whisper model : {settings.whisper_model}")
    print(f"   LLM model     : {settings.llm_model}")
    print(f"   TTS model     : {settings.tts_model}")
    print("✅ VoiceIQ ready!")