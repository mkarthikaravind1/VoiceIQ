"""
LangGraph agent state — rebuilt for every turn and shared across the nodes.
Anything that must outlive the turn lives in CallContext (context.py).
"""
from typing import TypedDict, Optional


class AgentState(TypedDict):
    # Input
    transcript: str              # what the caller said, as transcribed
    normalized: str              # same, with spoken numbers turned into digits
    language: str                # language to reply in
    arousal: float               # voice arousal for this utterance (-1..1), from prosody

    # Triage
    intent: str                  # faq | order_lookup | order_action | escalate | smalltalk | unknown
    confidence: float            # 0.0 – 1.0
    confirmation: str            # yes | no | none — answer to a pending yes/no question
    sentiment_text: float        # sentiment of the words alone (-1..1)
    sentiment: float             # words + voice combined (-1..1)

    # Result of a confirmed/declined action, passed to the agent as a note
    action_note: str

    # Output
    response: str
    should_escalate: bool
    tools: list
    summary: Optional[dict]
    timings: dict
    _start_time: float
