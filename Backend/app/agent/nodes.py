"""
LangGraph nodes — each handles one step in the pipeline.
"""
import os
import re
import json
import time
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, BaseMessage
from pydantic import SecretStr
from app.config import get_settings
from app.agent.state import AgentState
from app.rag.retriever import get_retriever

settings = get_settings()

# Shared LLM instance
llm = ChatGroq(
    api_key=SecretStr(settings.groq_api_key),
    model=settings.llm_model,
    temperature=settings.llm_temperature,
)

# How many past turns are sent to the LLM / kept in memory
MAX_HISTORY_TURNS = 6

VALID_INTENTS = {"faq", "order_lookup", "escalate", "unknown"}


def _parse_json(content) -> dict:
    """Parse an LLM JSON reply, tolerating code fences or text around the object."""
    text = str(content or "")
    match = re.search(r"\{.*\}", text, re.DOTALL)
    parsed = json.loads(match.group(0) if match else text)
    if not isinstance(parsed, dict):
        raise ValueError("LLM reply is not a JSON object")
    return parsed


def _append_history(state: AgentState, response: str) -> list:
    """Return conversation history with this turn added (bounded, not mutated)."""
    history = state.get("conversation_history") or []
    turn = {"user": state["transcript"], "agent": response}
    return (history + [turn])[-MAX_HISTORY_TURNS:]


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

_DIGIT_WORDS = {
    "zero": 0, "oh": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_NUM_WORD = r"(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|hundred|thousand)"
# A spoken number: a number word followed by more number words ("oh"/"and" allowed inside)
_SPOKEN_NUMBER_RE = re.compile(rf"\b{_NUM_WORD}(?:[\s-]+(?:{_NUM_WORD}|oh|and))*\b")


def _spoken_number_to_digits(match: re.Match) -> str:
    words = re.split(r"[\s-]+", match.group(0))

    # "one and ..." — a trailing "and"/"oh" belongs to the sentence, not the number
    trailing = []
    while words and words[-1] in ("and", "oh"):
        trailing.insert(0, words.pop())
    suffix = (" " + " ".join(trailing)) if trailing else ""

    number_words = [w for w in words if w != "and"]
    # A lone "one"/"two" is ordinary speech ("no one", "this one") — leave it alone
    if len(number_words) < 2:
        return match.group(0)

    if "hundred" in number_words or "thousand" in number_words:
        # "one thousand and two" → 1002, "two hundred" → 200
        total, current = 0, 0
        for w in number_words:
            if w == "hundred":
                current = max(current, 1) * 100
            elif w == "thousand":
                total += max(current, 1) * 1000
                current = 0
            else:
                current += _DIGIT_WORDS[w]
        return str(total + current) + suffix

    # "one zero zero three" → 1003, "ten oh two" → 1002
    return "".join(str(_DIGIT_WORDS[w]) for w in number_words) + suffix


def normalize_transcript(text: str) -> str:
    """
    Turn spoken numbers into digits so order IDs can be found.
    Used ONLY for intent detection / order-ID extraction — the original
    transcript is what gets stored, retrieved against and answered.
    """
    text = text.lower().strip()

    # Remove commas inside numbers: "1,003" → "1003"
    text = re.sub(r"(\d),(\d)", r"\1\2", text)

    # STT artifact: "1000-3" → "1003"
    text = re.sub(r"\b(1000)-(\d)\b", lambda m: str(1000 + int(m.group(2))), text)

    # Spoken numbers → digits
    text = _SPOKEN_NUMBER_RE.sub(_spoken_number_to_digits, text)

    # Collapse spaced digits: "1 0 0 3" → "1003"
    text = re.sub(r"\b(\d)\s+(\d)\s+(\d)\s+(\d)\b", r"\1\2\3\4", text)
    text = re.sub(r"\b(\d)\s+(\d)\s+(\d)\b", r"\1\2\3", text)

    # Remove trailing period after a number: "1003." → "1003"
    text = re.sub(r"(\d)\.$", r"\1", text)

    return text


def _clean_order_id(value) -> str | None:
    """LLM may return 1002, "1002", "#1002", "null" or None."""
    if value is None:
        return None
    digits = re.sub(r"\D", "", str(value))
    return digits or None


def detect_intent(state: AgentState) -> AgentState:
    normalized = normalize_transcript(state["transcript"])

    # Regex fallback for the order number in case the LLM misses it
    order_match = re.search(r"\b(\d{3,6})\b", normalized)

    response = llm.invoke([
        SystemMessage(content=INTENT_PROMPT),
        HumanMessage(content=normalized),
    ])

    try:
        parsed = _parse_json(response.content)
        intent = str(parsed.get("intent") or "unknown").strip().lower()
        if intent not in VALID_INTENTS:
            intent = "unknown"
        confidence = max(0.0, min(1.0, float(parsed.get("confidence", 0.5))))
        order_id = _clean_order_id(parsed.get("order_id"))
    except Exception:
        # Not JSON, wrong shape, null confidence, etc. — fall back, don't crash the call
        intent = "unknown"
        confidence = 0.0
        order_id = None

    # An order ID only means something for an order lookup
    if intent == "order_lookup":
        if not order_id and order_match:
            order_id = order_match.group(1)
    else:
        order_id = None

    print(f"[Agent] Intent={intent} Confidence={confidence:.2f} OrderID={order_id}")

    return {
        **state,
        "intent": intent,
        "confidence": confidence,
        "order_id": order_id,
    }


# ── Node 2: Order Lookup ──────────────────────────────────────────────────────

ORDERS_DB_PATH = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../data/orders_db.json")
)


def lookup_order(state: AgentState) -> AgentState:
    order_id = state.get("order_id")

    if not order_id:
        context = (
            "The customer wants to check an order but did not give an order number. "
            "Ask them to say their order number."
        )
        return {**state, "retrieved_context": context}

    try:
        with open(ORDERS_DB_PATH) as f:
            orders = json.load(f)
        order = orders.get(str(order_id))
        if order:
            context = (
                f"Order #{order['order_id']} for {order['customer']}: "
                f"Status is '{order['status']}'. "
                f"Items: {', '.join(order['items'])}. "
                f"Total: ${order['total']:.2f}. "
            )
            if order["status"] == "Delivered":
                context += f"Delivered on {order.get('delivered_on', 'N/A')}."
            elif order["status"] in ("In Transit", "Processing"):
                context += f"Estimated delivery: {order.get('estimated_delivery', 'N/A')}."
            elif order["status"] == "Cancelled":
                context += order.get("refund_status", "")
        else:
            context = f"No order found with ID {order_id}. Ask the customer to check the number."
    except Exception as e:
        context = f"Order lookup failed: {e}"

    return {**state, "retrieved_context": context}


# ── Node 3: Escalation ───────────────────────────────────────────────────────

def escalate(state: AgentState) -> AgentState:
    response = "Connecting you to a human agent now — please hold."
    return {
        **state,
        # Auto-escalation (from sentiment) skips detect_intent, so set it here
        "intent": "escalate",
        "confidence": state.get("confidence") or 1.0,
        "response": response,
        "should_escalate": True,
        "conversation_history": _append_history(state, response),
    }

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

    messages: list[BaseMessage] = [SystemMessage(content=RESPONSE_PROMPT)]

    for turn in history[-MAX_HISTORY_TURNS:]:
        messages.append(HumanMessage(content=turn["user"]))
        messages.append(AIMessage(content=turn["agent"]))

    messages.append(HumanMessage(content=f"Context: {context}\n\nCustomer asked: {transcript}"))

    response = llm.invoke(messages)
    response_content = (str(response.content) if response.content else "").strip()

    return {
        **state,
        "response": response_content,
        "should_escalate": False,
        "conversation_history": _append_history(state, response_content),
    }

# ── Node 5: Low Confidence Fallback ─────────────────────────────────────────

def low_confidence_fallback(state: AgentState) -> AgentState:
    response = "I didn't catch that — could you please rephrase?"
    return {
        **state,
        "response": response,
        "should_escalate": False,
        "conversation_history": _append_history(state, response),
    }

# ── Node 6: Per-turn Summary ────────────────────────────────────────────────

def generate_summary(state: AgentState) -> AgentState:
    duration = round(time.time() - (state.get("_start_time") or time.time()), 1)
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

# ── Node 0: Sentiment ───────────────────────────────────────────────────────

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
    try:
        response = llm.invoke([
            SystemMessage(content=SENTIMENT_PROMPT),
            HumanMessage(content=state["transcript"]),
        ])
        parsed = _parse_json(response.content)
        score = float(parsed.get("sentiment", 0.0))
        score = max(-1.0, min(1.0, score))
    except Exception:
        # Sentiment is optional — an LLM/parse failure must not fail the turn
        score = 0.0

    history = state.get("sentiment_history") or []
    history = history + [score]                    # append, don't mutate

    print(f"[Sentiment] score={score:.2f} history={history}")
    return {**state, "sentiment_score": score, "sentiment_history": history}
