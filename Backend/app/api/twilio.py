"""
Phone bridge — Twilio Media Streams.

  POST /twilio/voice   Twilio calls this when the phone number rings. It answers
                       with TwiML telling Twilio to open a media stream to us.
  WS   /ws/twilio      The media stream: 8 kHz mu-law audio in both directions.

A phone call runs through the same CallSession as a browser call. This module
only converts audio (8 kHz mu-law ⇄ 16 kHz PCM) and speaks Twilio's protocol.

Setup (see README): point your Twilio number's voice webhook at
https://<PUBLIC_HOST>/twilio/voice, with PUBLIC_HOST set in .env.

Note: requests are not signature-checked. Before using a real number in
production, validate the X-Twilio-Signature header.
"""
import asyncio
import base64
import io
import json
import logging
import wave
from math import gcd
import numpy as np
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from scipy.signal import resample_poly
from app.call.session import CallSession, Transport
from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()
settings = get_settings()

TWILIO_RATE = 8000
SESSION_RATE = 16000
FRAME_BYTES = 160          # 20 ms of 8 kHz mu-law — the frame size Twilio uses


# ── G.711 mu-law (the phone network's audio format) ──────────────────────────

_BIAS, _CLIP = 0x84, 32635


def _build_decode_table() -> np.ndarray:
    table = np.zeros(256, dtype=np.int16)
    for i in range(256):
        u = ~i & 0xFF
        sample = (((u & 0x0F) << 3) + _BIAS) << ((u & 0x70) >> 4)
        sample -= _BIAS
        table[i] = -sample if u & 0x80 else sample
    return table


_DECODE = _build_decode_table()


def mulaw_decode(data: bytes) -> np.ndarray:
    """mu-law bytes → int16 PCM samples."""
    return _DECODE[np.frombuffer(data, dtype=np.uint8)]


def mulaw_encode(pcm: np.ndarray) -> bytes:
    """int16 PCM samples → mu-law bytes."""
    x = pcm.astype(np.int32)
    sign = np.where(x < 0, 0x80, 0).astype(np.int32)
    x = np.minimum(np.abs(x), _CLIP) + _BIAS
    exponent = np.floor(np.log2(x)).astype(np.int32) - 7
    mantissa = (x >> (exponent + 3)) & 0x0F
    return (~(sign | (exponent << 4) | mantissa) & 0xFF).astype(np.uint8).tobytes()


def _resample(pcm: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst or len(pcm) == 0:
        return pcm
    g = gcd(src, dst)
    out = resample_poly(pcm.astype(np.float32), dst // g, src // g)
    return np.clip(out, -32768, 32767).astype(np.int16)


def wav_to_mulaw(wav: bytes) -> bytes:
    """A WAV file from the TTS pipeline → 8 kHz mu-law for the phone line."""
    with wave.open(io.BytesIO(wav)) as w:
        rate = w.getframerate()
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return mulaw_encode(_resample(pcm, rate, TWILIO_RATE))


# ── Transport ────────────────────────────────────────────────────────────────

class TwilioTransport(Transport):
    def __init__(self, websocket: WebSocket):
        self.websocket = websocket
        self.stream_sid: str | None = None
        self._lock = asyncio.Lock()

    async def _send(self, message: dict) -> None:
        async with self._lock:
            await self.websocket.send_text(json.dumps(message))

    async def send_event(self, event: dict) -> None:
        # A phone has no screen: text events are only logged
        if event.get("type") in ("transcript", "response", "error"):
            logger.info("[phone] %s: %s", event["type"], event.get("text") or event.get("message"))

    async def send_audio(self, wav: bytes, turn_id: int) -> None:
        if not self.stream_sid:
            return
        mulaw = await asyncio.to_thread(wav_to_mulaw, wav)
        for i in range(0, len(mulaw), FRAME_BYTES * 50):        # ~1 s per message
            await self._send({
                "event": "media",
                "streamSid": self.stream_sid,
                "media": {"payload": base64.b64encode(mulaw[i:i + FRAME_BYTES * 50]).decode()},
            })

    async def clear_audio(self, turn_id: int) -> None:
        # Barge-in: drop whatever Twilio has buffered but not yet played
        if self.stream_sid:
            await self._send({"event": "clear", "streamSid": self.stream_sid})


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/twilio/voice")
async def twilio_voice(request: Request):
    """TwiML: connect the phone call to our media-stream WebSocket."""
    host = settings.public_host or request.headers.get("host", "")
    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response><Connect>"
        f'<Stream url="wss://{host}/ws/twilio" />'
        "</Connect></Response>"
    )
    return Response(content=twiml, media_type="application/xml")


@router.websocket("/ws/twilio")
async def twilio_stream(websocket: WebSocket):
    await websocket.accept()
    transport = TwilioTransport(websocket)
    session = CallSession(transport, channel="phone")
    logger.info("Twilio stream connected")

    try:
        while True:
            message = json.loads(await websocket.receive_text())
            event = message.get("event")

            if event == "start":
                transport.stream_sid = message["start"]["streamSid"]
                logger.info("Phone call started (stream %s)", transport.stream_sid)

            elif event == "media":
                if message["media"].get("track", "inbound") != "inbound":
                    continue
                pcm8k = mulaw_decode(base64.b64decode(message["media"]["payload"]))
                pcm16k = _resample(pcm8k, TWILIO_RATE, SESSION_RATE)
                await session.feed_audio(pcm16k.tobytes())

            elif event == "stop":
                break

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Twilio stream error")
    finally:
        await session.close()
        try:
            await websocket.close()
        except Exception:
            pass
