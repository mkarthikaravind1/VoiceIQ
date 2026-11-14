"""
Browser WebSocket endpoint — /ws/voice

A thin transport: it moves bytes between the browser and a CallSession
(app/call/session.py), which holds all the call logic.

Server → client (turn messages carry "turn_id"):
  { type: "transcript",  text, language }
  { type: "tool",        name }                      the agent is using a tool
  { type: "partial",     text }                      reply so far, grows sentence by sentence
  { type: "response",    text, intent, sentiment_score, tools, ... }   the finished reply
  { type: "tts_start" } / { type: "audio", data: <base64 WAV> } / { type: "tts_end" }
  { type: "metrics",     timings: { stt_ms, triage_ms, llm_ms, tts_ms, ttfa_ms, ... } }
  { type: "barge_in",    turn_id: N }                caller started speaking; drop audio for turns <= N
  { type: "verified",    name }                      caller passed identity verification
  { type: "language",    language, has_voice }
  { type: "handoff",     mode: "human" | "ai" }      a supervisor took over / handed back
  { type: "call_summary", summary, resolution, csat, topics }
  { type: "status" | "error", message }

Client → server:
  Binary frames : raw PCM audio (int16, 16kHz, mono)
  Text frames   : { "action": "end_session" | "barge_in" | "clear_buffer" | "end_call" }
                  { "action": "set_language", "language": "en" | "hi" | ... | "auto" }
"""

import json
import base64
import asyncio
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.call.session import CallSession, Transport
from app.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter()
settings = get_settings()

# CORS middleware does not cover WebSockets, so check the browser Origin here.
_ALLOWED_ORIGINS = {o.strip() for o in settings.cors_origins.split(",") if o.strip()}


def origin_allowed(websocket: WebSocket) -> bool:
    """Browsers always send Origin; non-browser clients (tests, Twilio) send none."""
    origin = websocket.headers.get("origin")
    return not origin or "*" in _ALLOWED_ORIGINS or origin in _ALLOWED_ORIGINS


class BrowserTransport(Transport):
    def __init__(self, websocket: WebSocket):
        self.websocket = websocket
        # The receive loop and the turn task both send; serialise them.
        self._lock = asyncio.Lock()

    async def send_event(self, event: dict) -> None:
        async with self._lock:
            await self.websocket.send_text(json.dumps(event))

    async def send_audio(self, wav: bytes, turn_id: int) -> None:
        await self.send_event({
            "type": "audio",
            "data": base64.b64encode(wav).decode(),
            "turn_id": turn_id,
        })

    async def clear_audio(self, turn_id: int) -> None:
        await self.send_event({"type": "barge_in", "turn_id": turn_id})


@router.websocket("/ws/voice")
async def voice_websocket(websocket: WebSocket):
    if not origin_allowed(websocket):
        logger.warning("Rejected WebSocket from origin %s", websocket.headers.get("origin"))
        await websocket.close(code=1008)
        return

    await websocket.accept()
    logger.info("WebSocket client connected")

    session = CallSession(BrowserTransport(websocket), channel="web")
    await session.send({"type": "status", "message": "Connected — speak now"})
    await session._announce_language()

    try:
        while True:
            message = await websocket.receive()

            if message.get("type") == "websocket.disconnect":
                break

            if message.get("bytes"):
                await session.feed_audio(message["bytes"])

            elif message.get("text"):
                try:
                    control = json.loads(message["text"])
                except json.JSONDecodeError:
                    control = None
                if not isinstance(control, dict):
                    await session.send({"type": "error", "message": "Invalid JSON control message"})
                    continue
                await session.handle_control(control)

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception:
        logger.exception("WebSocket error")
        try:
            await session.send({"type": "error", "message": "Internal server error"})
        except Exception:
            pass
    finally:
        await session.close()
        try:
            await websocket.close()
        except Exception:
            pass
