"""
State that lives for a whole call (CallContext) and for a single turn (TurnTrace).

LangGraph state is rebuilt every turn; these objects are passed in through the
run config so tools can read and update what must survive between turns:
who has been verified, which action is waiting for a "yes", and so on.
"""
from dataclasses import dataclass, field

# How many past turns are sent to the LLM / kept in memory
MAX_HISTORY_TURNS = 8


@dataclass
class CallContext:
    call_id: str
    channel: str = "web"                 # "web" | "phone"
    language: str = "en"                 # language the agent replies in

    conversation_history: list = field(default_factory=list)   # [{"user", "agent"}]
    sentiment_history: list = field(default_factory=list)      # combined score per turn

    # Caller verification: set once the caller proves they own an order
    verified_customer: dict | None = None        # {"id", "name"}
    verify_attempts: int = 0

    # An action the agent has asked the caller to confirm, e.g.
    # {"type": "cancel_order", "order_id": "1003", "question": "..."}
    pending_action: dict | None = None

    # Running average of the caller's voice, to tell "louder than usual" apart
    # from "naturally loud"
    baseline_energy_db: float | None = None
    baseline_pitch_hz: float | None = None

    def remember(self, user: str, agent: str) -> None:
        self.conversation_history = (
            self.conversation_history + [{"user": user, "agent": agent}]
        )[-MAX_HISTORY_TURNS:]


@dataclass
class TurnTrace:
    """What happened inside one turn — filled in by the tools."""
    tools: list = field(default_factory=list)          # tool names, in call order
    kb_queries: list = field(default_factory=list)
    kb_miss: bool = False                              # an FAQ search found nothing
    escalate_reason: str | None = None
    verified_now: bool = False
    action_done: str | None = None                     # type of action executed this turn
