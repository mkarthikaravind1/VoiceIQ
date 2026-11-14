import os
import sys
os.environ["PYTORCH_NO_CUDA_MEMORY_CACHING"] = "1"

# Startup logs use emoji; a Windows console or piped log on cp1252 would crash on them.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:
        pass

import torch
torch.multiprocessing.set_sharing_strategy("file_system")

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import get_settings
from app.api import analytics, health, supervisor, twilio, websocket
from app.db import store
from app.agent.graph import get_agent
from app.rag.retriever import get_retriever
from app.stt.pipeline import get_stt
from app.tts.pipeline import get_tts

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load every model before the first call, so no caller waits on (or blocks
    # the event loop with) a model load.
    print("🚀 VoiceIQ backend starting up...")
    if not settings.groq_api_key:
        print("⚠️  GROQ_API_KEY is not set — copy .env.example to .env and add your key.")
    store.init_db()
    get_agent()
    get_retriever()
    get_stt()
    get_tts()
    print(f"   Whisper model : {settings.whisper_model}")
    print(f"   LLM models    : {settings.agent_model} (agent), {settings.llm_model} (triage)")
    print(f"   TTS model     : {settings.tts_model}")
    print("✅ VoiceIQ ready!")
    yield


app = FastAPI(
    title="VoiceIQ API",
    description="Open-Source Customer Service Voice Agent",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(health.router, prefix="/api", tags=["Health"])
app.include_router(websocket.router, tags=["WebSocket"])
app.include_router(supervisor.router, tags=["Supervisor"])
app.include_router(analytics.router, tags=["Analytics"])
app.include_router(twilio.router, tags=["Phone"])
