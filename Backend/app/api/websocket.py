"""
WebSocket endpoint — main real-time voice pipeline.

Turn-taking:
  Audio is buffered until the speaker stops (Silero VAD finds no speech in the
  trailing ~0.8s), then the whole utterance runs as one background turn:
  STT → agent → TTS. Because the turn runs as a task, the receive loop keeps
  reading, so new speech can interrupt (barge-in) at any stage.

Message protocol (server → client) — turn messages carry "turn_id":
  { type: "transcript",  text: "...", language: "en" }
  { type: "response",    text: "...", intent: "...", confidence: 0.9, should_escalate: false }
  { type: "tts_start" } / { type: "tts_end" }
  { type: "audio",       data: <base64 WAV> }
  { type: "barge_in",    turn_id: N }   user started speaking; drop audio for turns <= N
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
from dataclasses import dataclass, field
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.config import get_settings
from app.stt.pipeline import get_stt
from app.agent.graph import run_agent
from app.tts.pipeline import get_tts

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
BYTES_PER_SAMPLE = 2
BYTES_PER_SECOND = SAMPLE_RATE * BYTES_PER_SAMPLE

# Endpointing
TAIL_BYTES = int(BYTES_PER_SECOND * 0.8)     # trailing window checked for speech
PREROLL_BYTES = BYTES_PER_SECOND * 1         # audio kept while waiting for speech
MAX_UTTERANCE_BYTES = BYTES_PER_SECOND * 15  # force a turn after 15s of speech
MIN_FLUSH_THRESHOLD = 4000
TAIL_MIN_SPEECH_MS = 150

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


@dataclass
class _Session:
    """Per-connection state."""
    websocket: WebSocket
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    sentiment_history: list = field(default_factory=list)
    conversation_history: list = field(default_factory=list)
    turn_id: int = 0
    turn_task: asyncio.Task | None = None

    async def send(self, msg: dict):
        # The receive loop and the turn task both send; serialise them.
        async with self.send_lock:
            await self.websocket.send_text(json.dumps(msg))

    def cancel_turn(self) -> bool:
        """Cancel the running turn, if any. Returns True if one was cancelled."""
        if self.turn_task and not self.turn_task.done():
            self.turn_task.cancel()
            return True
        return False


async def _run_turn(session: _Session, raw_audio: bytes, turn_id: int, stt, tts):
    """One full turn: STT → agent → TTS. A failure here must never close the socket."""
    try:
        result = await stt.transcribe(raw_audio)

        if not (result["is_speech"] and result["transcript"]):
            await session.send({"type": "status", "message": "Listening...", "turn_id": turn_id})
            return

        logger.info("STT: '%s' (lang=%s)", result["transcript"], result["language"])
        await session.send({
            "type": "transcript",
            "text": result["transcript"],
            "language": result["language"],
            "language_probability": result.get("language_probability", 1.0),
            "turn_id": turn_id,
        })

        agent_result = await run_agent(
            result["transcript"],
            result["language"],
            list(session.sentiment_history),
            list(session.conversation_history),
        )
        session.sentiment_history = agent_result.get("sentiment_history", [])
        session.conversation_history = agent_result.get("conversation_history", [])

        await session.send({
            "type": "response",
            "text": agent_result["response"],
            "intent": agent_result["intent"],
            "confidence": agent_result["confidence"],
            "should_escalate": agent_result["should_escalate"],
            "summary": agent_result.get("summary"),
            "sentiment_score": agent_result.get("sentiment_score"),
            "turn_id": turn_id,
        })

        await session.send({"type": "tts_start", "turn_id": turn_id})
        async for audio_chunk in tts.synthesize_stream(agent_result["response"]):
            await session.send({
                "type": "audio",
                "data": base64.b64encode(audio_chunk).decode(),
                "turn_id": turn_id,
            })
        await session.send({"type": "tts_end", "turn_id": turn_id})

    except asyncio.CancelledError:
        # Barge-in or disconnect — the client is told separately via "barge_in".
        raise
    except Exception:
        # LLM rate limit, network error, bad model output, TTS failure...
        # Report it and keep the call alive for the next utterance.
        logger.exception("Turn %d failed", turn_id)
        try:
            await session.send({
                "type": "error",
                "message": "Sorry, I had trouble with that. Please try again.",
                "turn_id": turn_id,
            })
        except Exception:
            pass


def _start_turn(session: _Session, raw_audio: bytes, stt, tts):
    session.cancel_turn()
    session.turn_id += 1
    session.turn_task = asyncio.create_task(
        _run_turn(session, raw_audio, session.turn_id, stt, tts)
    )


@router.websocket("/ws/voice")
async def voice_websocket(websocket: WebSocket):
    await websocket.accept()
    logger.info("WebSocket client connected")

    session = _Session(websocket)
    audio_buffer = bytearray()
    in_speech = False          # True between speech start and end of utterance
    stt = _get_stt_lazy()
    tts = _get_tts_lazy()
    vad = stt.vad
    loop = asyncio.get_running_loop()

    await session.send({"type": "status", "message": "Connected — speak now"})

    try:
        while True:
            message = await websocket.receive()

            if message.get("type") == "websocket.disconnect":
                break

            # ── Binary frame: audio chunk from browser mic ──
            if message.get("bytes"):
                audio_buffer.extend(message["bytes"])

                tail = bytes(audio_buffer[-TAIL_BYTES:])
                tail_has_speech = await loop.run_in_executor(
                    None, vad.is_speech, tail, TAIL_MIN_SPEECH_MS, 100
                )

                if not in_speech:
                    if tail_has_speech:
                        # Speech started. If the agent is thinking or talking,
                        # this is a barge-in: stop that turn and tell the client
                        # to stop playback (it may still be playing queued audio
                        # even after the server finished streaming).
                        in_speech = True
                        session.cancel_turn()
                        await session.send({"type": "barge_in", "turn_id": session.turn_id})
                    else:
                        # Still silence — keep only a short pre-roll.
                        if len(audio_buffer) > PREROLL_BYTES:
                            del audio_buffer[:-PREROLL_BYTES]
                else:
                    if not tail_has_speech or len(audio_buffer) >= MAX_UTTERANCE_BYTES:
                        # Speaker stopped (or hit the cap) → process the utterance.
                        raw_audio = bytes(audio_buffer)
                        audio_buffer.clear()
                        in_speech = False
                        _start_turn(session, raw_audio, stt, tts)

            # ── Text frame: control messages ──
            elif message.get("text"):
                try:
                    control = json.loads(message["text"])
                except json.JSONDecodeError:
                    await session.send({"type": "error", "message": "Invalid JSON control message"})
                    continue

                action = control.get("action") if isinstance(control, dict) else None

                if action == "end_session":
                    # Mic turned off: process whatever was being said as a normal turn.
                    if in_speech and len(audio_buffer) > MIN_FLUSH_THRESHOLD:
                        _start_turn(session, bytes(audio_buffer), stt, tts)
                    audio_buffer.clear()
                    in_speech = False
                    await session.send({"type": "status", "message": "Mic off — tap to speak"})

                elif action == "clear_buffer":
                    audio_buffer.clear()
                    in_speech = False
                    await session.send({"type": "status", "message": "Buffer cleared"})

                elif action == "barge_in":
                    session.cancel_turn()
                    audio_buffer.clear()
                    in_speech = False
                    await session.send({"type": "barge_in", "turn_id": session.turn_id})

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception:
        logger.exception("WebSocket error")
        try:
            await session.send({"type": "error", "message": "Internal server error"})
        except Exception:
            pass
    finally:
        session.cancel_turn()
        try:
            await websocket.close()
        except Exception:
            pass
