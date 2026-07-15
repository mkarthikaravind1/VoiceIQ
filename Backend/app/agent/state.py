"""
LangGraph agent state — shared across all nodes in the graph.
"""
from typing import TypedDict, Optional, Any


class AgentState(TypedDict):
    # Input
    transcript: str
    language: str

    # Intent detection
    intent: str                  # "faq" | "order_lookup" | "escalate" | "unknown"
    confidence: float            # 0.0 – 1.0
    order_id: Optional[str]      # extracted if intent == order_lookup

    # RAG / DB result
    retrieved_context: str

    # Final output
    response: str
    should_escalate: bool
    summary: Optional[dict]    
    _start_time: Optional[float]
    sentiment_score: Optional[float]       # ← add: -1.0 (angry) to 1.0 (happy)
    sentiment_history: Optional[list]      # ← add: scores across turns
    conversation_history: list 