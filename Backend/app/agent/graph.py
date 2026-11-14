"""
LangGraph agent graph — one run per caller turn.

  triage  (sentiment + intent + yes/no, one fast LLM call)
     ├─ frustrated twice, or asks for a person → escalate
     ├─ an action is waiting for confirmation  → resolve_pending → agent
     ├─ unintelligible                         → fallback
     └─ everything else                        → agent  (streams, calls tools)
  every path ends in summarize
"""
import time
from typing import Any, Awaitable, Callable
from langgraph.graph import StateGraph, END
from app.agent.context import CallContext, TurnTrace
from app.agent.nodes import (
    triage,
    route_after_triage,
    resolve_pending,
    agent,
    escalate,
    fallback,
    summarize,
)
from app.agent.state import AgentState
from app.agent.text import normalize_transcript


def build_graph() -> Any:
    graph = StateGraph(AgentState)

    graph.add_node("triage", triage)
    graph.add_node("resolve_pending", resolve_pending)
    graph.add_node("agent", agent)
    graph.add_node("escalate", escalate)
    graph.add_node("fallback", fallback)
    graph.add_node("summarize", summarize)

    graph.set_entry_point("triage")
    graph.add_conditional_edges(
        "triage",
        route_after_triage,
        ["escalate", "resolve_pending", "fallback", "agent"],
    )
    graph.add_edge("resolve_pending", "agent")
    graph.add_edge("agent", "summarize")
    graph.add_edge("escalate", "summarize")
    graph.add_edge("fallback", "summarize")
    graph.add_edge("summarize", END)

    return graph.compile()


# Singleton compiled graph
_graph = None

def get_agent():
    global _graph
    if _graph is None:
        _graph = build_graph()
        print("✅ LangGraph agent ready")
    return _graph


async def run_agent(
    transcript: str,
    ctx: CallContext,
    emit: Callable[[dict], Awaitable[None]] | None = None,
    arousal: float = 0.0,
) -> dict:
    """
    Run one turn. `emit` receives events (triage, tool, sentence) while the turn
    is still running; the returned dict is the finished turn.
    """
    trace = TurnTrace()
    initial_state: AgentState = {
        "transcript": transcript,
        "normalized": normalize_transcript(transcript),
        "language": ctx.language,
        "arousal": arousal,
        "intent": "",
        "confidence": 0.0,
        "confirmation": "none",
        "sentiment_text": 0.0,
        "sentiment": 0.0,
        "action_note": "",
        "response": "",
        "should_escalate": False,
        "tools": [],
        "summary": None,
        "timings": {},
        "_start_time": time.time(),
    }
    result = await get_agent().ainvoke(
        initial_state,
        config={"configurable": {"ctx": ctx, "trace": trace, "emit": emit}},
    )
    return {
        "response": result["response"],
        "intent": result["intent"],
        "confidence": result["confidence"],
        "should_escalate": result["should_escalate"],
        "escalate_reason": trace.escalate_reason,
        "summary": result.get("summary"),
        "sentiment": result["sentiment"],
        "sentiment_text": result["sentiment_text"],
        "arousal": arousal,
        "tools": list(trace.tools),
        "kb_miss": trace.kb_miss,
        "kb_queries": list(trace.kb_queries),
        "verified_now": trace.verified_now,
        "action_done": trace.action_done,
        "pending_question": ctx.pending_action["question"] if ctx.pending_action else None,
        "timings": result.get("timings", {}),
    }
