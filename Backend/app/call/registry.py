"""
Live call registry — the link between calls and the supervisor console.

Every call that has had at least one turn is listed here. Whenever a call
changes (new turn, escalation, takeover, end) its snapshot is pushed to every
connected supervisor. Supervisors act on a call through its session:
take over, speak to the caller, hand back to the AI.

In-memory and single-process: fine for a demo server, not for several workers.
"""
import json
from collections import OrderedDict

MAX_ENDED = 20      # ended calls kept on the supervisor board


class CallRegistry:
    def __init__(self):
        self.sessions: dict[str, object] = {}                 # call_id → live CallSession
        self.ended: OrderedDict[str, dict] = OrderedDict()    # call_id → final snapshot
        self.supervisors: set = set()                         # supervisor WebSockets

    def snapshot_all(self) -> list[dict]:
        live = [s.snapshot() for s in self.sessions.values()]
        return live + list(reversed(self.ended.values()))

    def get(self, call_id: str):
        return self.sessions.get(call_id)

    async def _broadcast(self, event: dict) -> None:
        text = json.dumps(event)
        for ws in list(self.supervisors):
            try:
                await ws.send_text(text)
            except Exception:
                self.supervisors.discard(ws)

    async def publish(self, session) -> None:
        """A call started or changed."""
        self.sessions[session.call_id] = session
        await self._broadcast({"type": "call", "call": session.snapshot()})

    async def end(self, session) -> None:
        if self.sessions.pop(session.call_id, None) is None:
            return
        snapshot = session.snapshot()
        self.ended[session.call_id] = snapshot
        while len(self.ended) > MAX_ENDED:
            self.ended.popitem(last=False)
        await self._broadcast({"type": "call", "call": snapshot})

    async def update_ended(self, call_id: str, fields: dict) -> None:
        """Attach the post-call analysis once it is ready."""
        if call_id in self.ended:
            self.ended[call_id].update(fields)
            await self._broadcast({"type": "call", "call": self.ended[call_id]})


registry = CallRegistry()
