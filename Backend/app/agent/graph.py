"""
LangGraph agent graph.
Flow:
  detect_intent
      ├─ confidence < threshold  → low_confidence_fallback
      ├─ intent == escalate      → escalate
      ├─ intent == order_lookup  → lookup_order → generate_response
      └─ intent == faq           → [RAG node in Phase 4] → generate_response
"""
from langgraph.graph import StateGraph, END
from app.agent.state import AgentState
from app.agent.nodes import (
    detect_intent,
    lookup_order,
    escalate,
    generate_response,
    low_confidence_fallback,
    generate_summary,
    analyze_sentiment,
    
)
from app.config import get_settings
from langgraph.graph.state import CompiledStateGraph
from typing import Any
from app.agent.nodes import faq_retrieve
import time

settings = get_settings()


def route_after_intent(state: AgentState) -> str:
    """Conditional edge: decide next node based on intent + confidence."""
    if state["confidence"] < settings.confidence_threshold:
        return "low_confidence_fallback"
    if state["intent"] == "escalate":
        return "escalate"
    if state["intent"] == "order_lookup":
        return "lookup_order"
    if state["intent"] == "faq":
        return "faq_retrieve"       # Phase 4 will register this node
    return "low_confidence_fallback"

def route_after_sentiment(state: AgentState) -> str:
    """Auto-escalate if frustrated 2+ turns in a row."""
    history = state.get("sentiment_history") or []
    if len(history) >= 2 and all(s < -0.5 for s in history[-2:]):
        print(f"[Auto-Escalate] Frustrated {len(history[-2:])} turns → escalating")
        return "escalate"
    return "detect_intent"

def build_graph() -> Any:
    graph = StateGraph(AgentState)

    # Register nodes
    graph.add_node("analyze_sentiment",       analyze_sentiment)
    graph.add_node("detect_intent", detect_intent)
    graph.add_node("lookup_order", lookup_order)
    graph.add_node("escalate", escalate)
    graph.add_node("generate_response", generate_response)
    graph.add_node("low_confidence_fallback", low_confidence_fallback)

    # Phase 4 will add "faq_retrieve" node here
    # For now, route faq → generate_response directly (no RAG yet)
    graph.add_node("faq_retrieve", faq_retrieve)  
    graph.add_node("generate_summary", generate_summary)  

    # Edges
    graph.set_entry_point("analyze_sentiment")
    graph.add_conditional_edges("analyze_sentiment", route_after_sentiment)
    graph.add_conditional_edges("detect_intent", route_after_intent)
    graph.add_edge("lookup_order", "generate_response")
    graph.add_edge("faq_retrieve", "generate_response")
    graph.add_edge("generate_response", "generate_summary")
    graph.add_edge("escalate", "generate_summary")
    graph.add_edge("low_confidence_fallback", "generate_summary")
    graph.add_edge("generate_summary",        END)

    return graph.compile()


# Singleton compiled graph
_graph = None

def get_agent():
    global _graph
    if _graph is None:
        _graph = build_graph()
        print("✅ LangGraph agent ready")
    return _graph


async def run_agent(transcript: str, language: str = "en", sentiment_history: list = [], conversation_history: list = []) -> dict:
    """
    Main entry point called from WebSocket handler.
    Returns dict with response text and escalation flag.
    """
    agent = get_agent()
    initial_state: AgentState = {
        "transcript": transcript,
        "language": language,
        "intent": "",
        "confidence": 0.0,
        "order_id": None,
        "retrieved_context": "",
        "response": "",
        "should_escalate": False,
        "summary":None,
        "_start_time":time.time(),
         "sentiment_score":   None,
        "sentiment_history": sentiment_history,
        "conversation_history": conversation_history,  
    }
    result = await agent.ainvoke(initial_state)
    return {
        "response": result["response"],
        "intent": result["intent"],
        "confidence": result["confidence"],
        "should_escalate": result["should_escalate"],
        "summary":        result.get("summary"),
        "sentiment_score":   result.get("sentiment_score"),
        "sentiment_history": result.get("sentiment_history", []),
        "conversation_history": result.get("conversation_history", []),
    }