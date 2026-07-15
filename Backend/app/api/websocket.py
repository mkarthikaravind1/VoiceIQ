"""
WebSocket endpoint — main real-time voice pipeline.

Message protocol (server → client):
  { type: "transcript",  text: "...", language: "en" }
  { type: "response",    text: "...", intent: "...", confidence: 0.9, should_escalate: false }
  { type: "audio",       data: <base64> }
  { type: "status",      message: "..." }
  { type: "error",       message: "..." }

Client → server:
  Binary frames : raw PCM audio (int16, 16kHz, mono)
  Text frames   : JSON control e.g. { "action": "end_session" }
"""

import json
import base64
import asyncio
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.config import get_settings
from app.stt.pipeline import get_stt
from app.agent.graph import run_agent
from app.tts.pipeline import get_tts

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
BYTES_PER_SAMPLE = 2
PROCESS_THRESHOLD = SAMPLE_RATE * BYTES_PER_SAMPLE * 2  # 64000 — ~2s
MIN_FLUSH_THRESHOLD = 4000

router = APIRouter()
settings = get_settings()

_stt = None
_tts = None

def _get_stt_lazy():
    global _stt
    if _stt is None:
        _stt = get_stt()
    return _stt

def _get_tts_lazy():
    global _tts
    if _tts is None:
        _tts = get_tts()
    return _tts

async def _send(ws: WebSocket, msg: dict):
    await ws.send_text(json.dumps(msg))

# Issue 9 fix (optional but clean): _stream_tts defined at module level
async def _stream_tts(websocket: WebSocket, tts, response_text: str):
    try:
        async for audio_chunk in tts.synthesize_stream(response_text):
            await _send(websocket, {
                "type": "audio",
                "data": base64.b64encode(audio_chunk).decode()
            })
        await _send(websocket, {"type": "tts_end"})
    except asyncio.CancelledError:
        # Issue 3 fix: send tts_end then re-raise to preserve cancellation semantics
        try:
            await _send(websocket, {"type": "tts_end"})
        except Exception:
            pass
        raise
    except Exception:
        # Issue 6 fix: guard _send in case socket already closed
        logger.exception("TTS stream failed")
        try:
            await _send(websocket, {"type": "error", "message": "TTS stream failed"})
            await _send(websocket, {"type": "tts_end"})
        except Exception:
            pass


@router.websocket("/ws/voice")
async def voice_websocket(websocket: WebSocket):
    await websocket.accept()
    logger.info("WebSocket client connected")  # Issue 5 fix

    audio_buffer = bytearray()
    sentiment_history = []
    conversation_history = []
    stt = _get_stt_lazy()
    tts = _get_tts_lazy()
    is_processing = False
    tts_task: asyncio.Task | None = None  # Issue 4 fix: declared local

    await _send(websocket, {"type": "status", "message": "Connected — speak now"})

    try:
        while True:
            message = await websocket.receive()

            # ── Binary frame: audio chunk from browser mic ──
            if "bytes" in message and message["bytes"]:
                chunk = message["bytes"]
                audio_buffer.extend(chunk)
                logger.debug("Buffer size=%d", len(audio_buffer))  # Issue 5 fix

                if len(audio_buffer) >= PROCESS_THRESHOLD:
                    if is_processing:
                        audio_buffer.clear()
                        continue

                    is_processing = True

                    try:
                        raw_audio = bytes(audio_buffer)
                        audio_buffer.clear()

                        result = await stt.transcribe(raw_audio)

                        if result["is_speech"] and result["transcript"]:
                            logger.info("STT: '%s' (lang=%s)", result["transcript"], result["language"])  # Issue 5 fix

                            await _send(websocket, {
                                "type": "transcript",
                                "text": result["transcript"],
                                "language": result["language"],
                                "language_probability": result.get("language_probability", 1.0),
                            })

                            agent_result = await run_agent(
                                result["transcript"],
                                result["language"],
                                sentiment_history,
                                conversation_history
                            )
                            sentiment_history = agent_result.get("sentiment_history", [])
                            conversation_history = agent_result.get("conversation_history", [])

                            await _send(websocket, {
                                "type": "response",
                                "text": agent_result["response"],
                                "intent": agent_result["intent"],
                                "confidence": agent_result["confidence"],
                                "should_escalate": agent_result["should_escalate"],
                                "summary": agent_result.get("summary"),
                                "sentiment_score": agent_result.get("sentiment_score"),
                            })

                            await _send(websocket, {"type": "tts_start"})

                            # Issue 1 fix: cancel previous task before creating new one
                            if tts_task and not tts_task.done():
                                tts_task.cancel()

                            tts_task = asyncio.create_task(
                                _stream_tts(websocket, tts, agent_result["response"])
                            )

                        else:
                            await _send(websocket, {"type": "status", "message": "Listening..."})

                    finally:
                        is_processing = False

            # ── Text frame: control messages ──
            elif "text" in message and message["text"]:
                try:
                    control = json.loads(message["text"])
                    action = control.get("action")

                    if action == "end_session":
                        if len(audio_buffer) > MIN_FLUSH_THRESHOLD:
                            result = await stt.transcribe(bytes(audio_buffer))
                            if result["is_speech"] and result["transcript"]:
                                await _send(websocket, {
                                    "type": "transcript",
                                    "text": result["transcript"],
                                    "language": result["language"],
                                    "language_probability": result.get("language_probability", 1.0),
                                })
                                agent_result = await run_agent(
                                    result["transcript"],
                                    result["language"],
                                    sentiment_history,
                                    conversation_history
                                )
                                sentiment_history = agent_result.get("sentiment_history", [])
                                conversation_history = agent_result.get("conversation_history", [])
                                await _send(websocket, {
                                    "type": "response",
                                    "text": agent_result["response"],
                                    "intent": agent_result["intent"],
                                    "confidence": agent_result["confidence"],
                                    "should_escalate": agent_result["should_escalate"],
                                })
                        audio_buffer.clear()
                        conversation_history.clear()
                        sentiment_history.clear()
                        await _send(websocket, {"type": "status", "message": "Session ended"})

                    elif action == "clear_buffer":
                        audio_buffer.clear()
                        await _send(websocket, {"type": "status", "message": "Buffer cleared"})

                    elif action == "barge_in":
                        if tts_task and not tts_task.done():
                            tts_task.cancel()
                        audio_buffer.clear()
                        await _send(websocket, {"type": "status", "message": "Interrupted"})

                except json.JSONDecodeError:
                    await _send(websocket, {"type": "error", "message": "Invalid JSON control message"})

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")  # Issue 5 fix
    except Exception:
        logger.exception("WebSocket error")  # Issue 5 fix: logger.exception captures traceback
        try:
            await _send(websocket, {"type": "error", "message": "Internal server error"})
        except Exception:
            pass
    finally:
        # Issue 4 + 8 fix: always clean up task on exit regardless of reason
        if tts_task and not tts_task.done():
            tts_task.cancel()
        try:
            await websocket.close()
        except Exception:
            pass