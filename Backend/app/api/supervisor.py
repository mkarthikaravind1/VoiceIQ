"""
Supervisor console — /ws/supervisor and GET /api/calls/live

A supervisor sees every call in progress, with escalated calls flagged, and
can take one over: the AI stops answering, the supervisor's typed replies are
spoken to the caller, and the caller's words keep arriving as text.

Server → supervisor:
  { type: "snapshot", calls: [...] }     once, on connect
  { type: "call", call: {...} }          whenever a call changes
  { type: "error", message }

Supervisor → server:
  { "action": "takeover", "call_id": "..." }
  { "action": "say",      "call_id": "...", "text": "..." }
  { "action": "release",  "call_id": "..." }      hand back to the AI

There is no login on this endpoint — it is a demo. Put it behind real
authentication before exposing the server beyond your own machine.
"""
import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.api.websocket import origin_allowed
from app.call.registry import registry

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/calls/live")
async def live_calls():
    return {"calls": registry.snapshot_all()}


@router.websocket("/ws/supervisor")
async def supervisor_websocket(websocket: WebSocket):
    if not origin_allowed(websocket):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    registry.supervisors.add(websocket)
    await websocket.send_text(json.dumps({"type": "snapshot", "calls": registry.snapshot_all()}))

    try:
        while True:
            try:
                msg = json.loads(await websocket.receive_text())
            except json.JSONDecodeError:
                continue
            if not isinstance(msg, dict):
                continue

            session = registry.get(str(msg.get("call_id") or ""))
            if session is None:
                await websocket.send_text(json.dumps({"type": "error", "message": "That call has ended"}))
                continue

            action = msg.get("action")
            if action == "takeover":
                await session.takeover()
            elif action == "release":
                await session.release()
            elif action == "say":
                if session.mode != "human":
                    await session.takeover()
                await session.human_say(str(msg.get("text") or ""))
            await registry.publish(session)

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Supervisor socket error")
    finally:
        registry.supervisors.discard(websocket)
