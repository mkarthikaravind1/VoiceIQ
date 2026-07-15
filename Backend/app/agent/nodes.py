"""
LangGraph nodes — each handles one step in the pipeline.
"""
import re
import json
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage
from app.config import get_settings
from app.agent.state import AgentState
from pydantic import SecretStr
from app.rag.retriever import get_retriever
import time
from langchain_core.messages import SystemMessage, HumanMessage, BaseMessage

settings = get_settings()

# Shared LLM instance
llm = ChatGroq(
    api_key=SecretStr(settings.groq_api_key),
    model=settings.llm_model,
    temperature=settings.llm_temperature,
)

# ── Node 1: Intent Detection ─────────────────────────────────────────────────

INTENT_PROMPT = """You are an intent classifier for a customer service voice agent.
Classify the user's message into exactly one intent and give a confidence score.

Intents:
- faq         : General questions about policies, shipping, payments, returns, etc.
- order_lookup: User wants to check/find/track/look up a specific order (ANY mention of an order number = this intent)
- escalate    : User explicitly wants a human agent or is very frustrated
- unknown     : Cannot determine intent

RULE: If the message contains ANY number that could be an order ID, intent MUST be order_lookup.

Respond ONLY with valid JSON, no markdown:
{"intent": "<intent>", "confidence": <0.0-1.0>, "order_id": "<id or null>"}

Examples:
"What is your return policy?"      → {"intent": "faq", "confidence": 0.95, "order_id": null}
"Check order 1002"                 → {"intent": "order_lookup", "confidence": 0.98, "order_id": "1002"}
"Look for my order 1003"           → {"intent": "order_lookup", "confidence": 0.97, "order_id": "1003"}
"Where is order number 1001?"      → {"intent": "order_lookup", "confidence": 0.99, "order_id": "1001"}
"Find order 1004 for me"           → {"intent": "order_lookup", "confidence": 0.98, "order_id": "1004"}
"I want to talk to a human"        → {"intent": "escalate", "confidence": 0.99, "order_id": null}
"""

# Add at top of nodes.py
WORD_TO_NUM = {
    "zero":"0","one":"1","two":"2","three":"3","four":"4",
    "five":"5","six":"6","seven":"7","eight":"8","nine":"9",
    "thousand":"1000","hundred":"100",
}

def normalize_transcript(text: str) -> str:
    text = text.lower().strip()

    # Remove commas inside numbers: "1,003" → "1003", "1,000" → "1000"
    text = re.sub(r'(\d),(\d)', r'\1\2', text)
    
    # Remove hyphens between digits: "1000-3" → "10003" (wrong) 
    # Instead: "1,000-3" → after comma fix → "1000-3" → interpret as "1003"
    # Pattern: 4-digit number hyphen 1-digit → concat last digit
    text = re.sub(r'\b(1000)-(\d)\b', lambda m: str(1000 + int(m.group(2))), text)
    
    # Handle "thousand X" → 100X
    text = re.sub(
        r'\bthousand\s+(one|two|three|four|five|six|seven|eight|nine)\b',
        lambda m: str(1000 + int(WORD_TO_NUM[m.group(1)])),
        text
    )
    
    # Replace word numbers
    for word, digit in WORD_TO_NUM.items():
        text = re.sub(rf'\b{word}\b', digit, text)
    
    # Collapse spaced digits: "1 0 0 3" → "1003"
    text = re.sub(r'\b(\d)\s+(\d)\s+(\d)\s+(\d)\b', r'\1\2\3\4', text)
    text = re.sub(r'\b(\d)\s+(\d)\s+(\d)\b', r'\1\2\3', text)
    
    # Remove trailing punctuation like "1,03." → "103" (STT artifact)
    text = re.sub(r'(\d)\.$', r'\1', text)
    
    return text

def detect_intent(state: AgentState) -> AgentState:
    raw = state["transcript"]
    transcript = normalize_transcript(raw)
    
    # Quick regex check for order numbers before hitting LLM
    order_match = re.search(r'\b(\d{3,6})\b', transcript)

    response = llm.invoke([
        SystemMessage(content=INTENT_PROMPT),
        HumanMessage(content=transcript),
    ])

    try:
        content_str = str(response.content) if response.content else ""
        parsed = json.loads(content_str.strip())
        intent = parsed.get("intent", "unknown")
        confidence = float(parsed.get("confidence", 0.5))
        order_id = parsed.get("order_id") or (order_match.group(1) if order_match else None)
    except (json.JSONDecodeError, ValueError):
        intent = "unknown"
        confidence = 0.0
        order_id = None

    print(f"[Agent] Intent={intent} Confidence={confidence:.2f} OrderID={order_id}")

    return {
        **state,
        "transcript": transcript,       # Newly added line
        "intent": intent,
        "confidence": confidence,
        "order_id": order_id,
    }


# ── Node 2: Order Lookup ──────────────────────────────────────────────────────

def lookup_order(state: AgentState) -> AgentState:
    import json, os
    order_id = state.get("order_id")

    base = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.normpath(os.path.join(base, "../../data/orders_db.json"))
    # db_path = os.path.join(os.path.dirname(__file__), "../../data/faq/orders_db.json")
    # db_path = os.path.normpath(db_path)
    print(f"[DEBUG] db_path={db_path}, exists={os.path.exists(db_path)}")

    try:
        with open(db_path) as f:
            orders = json.load(f)
        order = orders.get(str(order_id))
        if order:
            context = (
                f"Order #{order['order_id']} for {order['customer']}: "
                f"Status is '{order['status']}'. "
                f"Items: {', '.join(order['items'])}. "
                f"Total: ${order['total']}. "
            )
            if order["status"] == "Delivered":
                context += f"Delivered on {order.get('delivered_on', 'N/A')}."
            elif order["status"] in ("In Transit", "Processing"):
                context += f"Estimated delivery: {order.get('estimated_delivery', 'N/A')}."
            elif order["status"] == "Cancelled":
                context += order.get("refund_status", "")
        else:
            context = f"No order found with ID {order_id}."
    except Exception as e:
        context = f"Order lookup failed: {e}"

    return {**state, "retrieved_context": context}


# ── Node 3: Escalation ───────────────────────────────────────────────────────

def escalate(state: AgentState) -> AgentState:
    response = "Connecting you to a human agent now — please hold."
    return {**state, "response": response, "should_escalate": True}

# ── Node: FAQ RAG Retrieval ──────────────────────────────────────────────────

def faq_retrieve(state: AgentState) -> AgentState:
    retriever = get_retriever()
    context = retriever.retrieve(state["transcript"])
    print(f"[RAG] Retrieved {len(context)} chars of context")
    return {**state, "retrieved_context": context}


# ── Node 4: Generate Response (FAQ + Order) ──────────────────────────────────

RESPONSE_PROMPT = """You are a friendly, concise customer service voice agent.
Answer the user's question using ONLY the provided context.
Keep responses under 3 sentences. Speak naturally — this will be converted to speech.
If context is empty, say you don't have that information and offer to escalate."""

def generate_response(state: AgentState) -> AgentState:
    context = state.get("retrieved_context", "")
    transcript = state["transcript"]
    history = state.get("conversation_history") or []
    
    messages: list[BaseMessage] = [SystemMessage(content=RESPONSE_PROMPT)]  # ← add type hint

    for turn in history:
        messages.append(HumanMessage(content=turn["user"]))
        messages.append(SystemMessage(content=turn["agent"]))

    messages.append(HumanMessage(content=f"Context: {context}\n\nCustomer asked: {transcript}"))
    
    response = llm.invoke(messages)
    response_content = str(response.content) if response.content else ""
    updated_history = history + [{"user": transcript, "agent": response_content.strip()}]
    
    return {**state, "response": response_content.strip(), "should_escalate": False, "conversation_history": updated_history}

# ── Node 5: Low Confidence Fallback ─────────────────────────────────────────

def low_confidence_fallback(state: AgentState) -> AgentState:
    response = "I didn't catch that — could you please rephrase?"
    return {**state, "response": response, "should_escalate": False}

# Add at bottom of nodes.py
def generate_summary(state: AgentState) -> AgentState:
    duration = round(time.time() - state.get("_start_time", time.time()), 1)   # type: ignore
    summary = {
        "intent":     state.get("intent", "unknown"),
        "order_id":   state.get("order_id"),
        "resolution": "escalated" if state.get("should_escalate")
                      else "resolved" if state.get("response")
                      else "unresolved",
        "escalated":  state.get("should_escalate", False),
        "duration_s": duration,
    }
    print(f"[Summary] {summary}")
    return {**state, "summary": summary}

SENTIMENT_PROMPT = """You are a sentiment analyzer for a customer service agent.
Score the customer's message sentiment from -1.0 (very frustrated/angry) to 1.0 (happy/positive).
Neutral is 0.0.

Respond ONLY with valid JSON, no markdown:
{"sentiment": <-1.0 to 1.0>}

Examples:
"What is your return policy?"           → {"sentiment": 0.0}
"This is ridiculous, I'm so angry!"     → {"sentiment": -0.9}
"Thanks, that was helpful"              → {"sentiment": 0.8}
"Where is my order, it's been 2 weeks!" → {"sentiment": -0.7}
"""

def analyze_sentiment(state: AgentState) -> AgentState:
    response = llm.invoke([
        SystemMessage(content=SENTIMENT_PROMPT),
        HumanMessage(content=state["transcript"]),
    ])
    try:
        parsed = json.loads(str(response.content).strip())
        score = float(parsed.get("sentiment", 0.0))
        score = max(-1.0, min(1.0, score))
    except (json.JSONDecodeError, ValueError):
        score = 0.0

    history = state.get("sentiment_history") or []
    history = history + [score]                    # append, don't mutate

    print(f"[Sentiment] score={score:.2f} history={history}")
    return {**state, "sentiment_score": score, "sentiment_history": history}