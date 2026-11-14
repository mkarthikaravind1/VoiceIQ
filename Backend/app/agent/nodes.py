"""
LangGraph nodes — each handles one step of a turn.

Per-call objects arrive through the run config:
  config["configurable"]["ctx"]    CallContext  (memory, verification, pending action)
  config["configurable"]["trace"]  TurnTrace    (what the tools did this turn)
  config["configurable"]["emit"]   async callable — receives events while the
                                   turn is still running, so speech can start
                                   before the reply is complete:
      {"type": "triage", ...}            sentiment + intent are known
      {"type": "tool", "name": ...}      the agent is calling a tool
      {"type": "sentence", "text": ...}  one finished sentence of the reply
"""
import asyncio
import time
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage, BaseMessage
from langchain_core.runnables import RunnableConfig
from app.agent.context import CallContext, TurnTrace
from app.agent.i18n import language_name, phrase
from app.agent.llm import fast_llm, agent_llm
from app.agent.state import AgentState
from app.agent.text import SentenceSplitter, parse_json
from app.agent.tools import build_tools, intent_from_tools
from app.config import get_settings
from app.db import store
from app.stt.prosody import fuse_sentiment

settings = get_settings()

VALID_INTENTS = {"faq", "order_lookup", "order_action", "escalate", "smalltalk", "other", "unknown"}
MAX_TOOL_ROUNDS = 4


def _parts(config: RunnableConfig) -> tuple[CallContext, TurnTrace, object]:
    c = config["configurable"]
    return c["ctx"], c["trace"], c.get("emit")


async def _emit(emit, event: dict) -> None:
    if emit:
        await emit(event)


# ── Node 1: Triage (sentiment + intent + yes/no, one fast LLM call) ──────────

TRIAGE_PROMPT = """You analyse one customer message for a customer-service voice agent of an online store.
The message comes from speech recognition and may be in any language.

Respond ONLY with valid JSON, no markdown:
{"sentiment": <-1.0 to 1.0>, "intent": "<intent>", "confidence": <0.0 to 1.0>, "confirmation": "yes" | "no" | "none"}

sentiment: -1.0 = very frustrated or angry, 0.0 = neutral, 1.0 = happy.
A plain question or request ("where is my order", "cancel it", "I want a human") is 0.0.
Go below -0.4 only when the words themselves show annoyance, blame or anger.

intent — exactly one of:
- faq          : question about policies, shipping, payments, returns, warranty, account, loyalty points
- order_lookup : wants the status or tracking of an order, or is giving an order number or verification digits
- order_action : wants to cancel an order, return an item, or change a delivery address
- escalate     : explicitly asks for a human agent, a person, a manager
- smalltalk    : greeting, thanks, goodbye, or a plain yes/no answer to the agent
- other        : a complaint, a general remark, or any other understandable request
- unknown      : ONLY when the text is garbled, cut off or meaningless

confidence: how sure you are about the intent.

confirmation: look at "Agent just said". If it ends with a yes/no question and the customer
agrees, answer "yes"; if the customer declines, "no"; in every other case "none".

Examples:
Agent just said: (nothing) | Customer: "What is your return policy?"
{"sentiment": 0.0, "intent": "faq", "confidence": 0.95, "confirmation": "none"}
Agent just said: (nothing) | Customer: "Where is my order 1002?"
{"sentiment": 0.0, "intent": "order_lookup", "confidence": 0.97, "confirmation": "none"}
Agent just said: (nothing) | Customer: "It's been two weeks and my order still isn't here, this is unacceptable"
{"sentiment": -0.7, "intent": "order_lookup", "confidence": 0.9, "confirmation": "none"}
Agent just said: (nothing) | Customer: "Please cancel that order"
{"sentiment": 0.0, "intent": "order_action", "confidence": 0.95, "confirmation": "none"}
Agent just said: "Do you want me to cancel order 1003?" | Customer: "Yes please go ahead"
{"sentiment": 0.1, "intent": "smalltalk", "confidence": 0.9, "confirmation": "yes"}
Agent just said: "What are the last four digits of your phone number?" | Customer: "2468"
{"sentiment": 0.0, "intent": "order_lookup", "confidence": 0.9, "confirmation": "none"}
Agent just said: (nothing) | Customer: "I want to talk to a human agent"
{"sentiment": 0.0, "intent": "escalate", "confidence": 0.98, "confirmation": "none"}
Agent just said: (nothing) | Customer: "This is ridiculous, get me a real person"
{"sentiment": -0.9, "intent": "escalate", "confidence": 0.98, "confirmation": "none"}
"""


async def triage(state: AgentState, config: RunnableConfig) -> dict:
    ctx, _, emit = _parts(config)
    started = time.perf_counter()

    last_agent = ctx.conversation_history[-1]["agent"] if ctx.conversation_history else ""
    if ctx.pending_action:
        last_agent = ctx.pending_action["question"]

    try:
        reply = await fast_llm.ainvoke([
            SystemMessage(content=TRIAGE_PROMPT),
            HumanMessage(content=f'Agent just said: {last_agent or "(nothing)"} | Customer: "{state["normalized"]}"'),
        ])
        parsed = parse_json(reply.content)
        intent = str(parsed.get("intent") or "unknown").strip().lower()
        if intent not in VALID_INTENTS:
            intent = "unknown"
        confidence = max(0.0, min(1.0, float(parsed.get("confidence", 0.5))))
        sentiment_text = max(-1.0, min(1.0, float(parsed.get("sentiment", 0.0))))
        confirmation = str(parsed.get("confirmation") or "none").strip().lower()
        if confirmation not in ("yes", "no"):
            confirmation = "none"
    except asyncio.CancelledError:
        raise
    except Exception as e:
        # Classification is a helper — if it fails, let the agent handle the turn anyway
        print(f"[Triage] failed ({type(e).__name__}: {e}) — using neutral defaults")
        intent, confidence, sentiment_text, confirmation = "smalltalk", 0.5, 0.0, "none"

    sentiment = fuse_sentiment(sentiment_text, state.get("arousal", 0.0))
    ctx.sentiment_history = ctx.sentiment_history + [sentiment]

    triage_ms = round((time.perf_counter() - started) * 1000)
    print(f"[Triage] intent={intent} conf={confidence:.2f} sentiment={sentiment_text:+.2f} "
          f"(with voice {sentiment:+.2f}) confirmation={confirmation} {triage_ms}ms")

    await _emit(emit, {"type": "triage", "intent": intent, "sentiment": sentiment, "triage_ms": triage_ms})
    return {
        "intent": intent,
        "confidence": confidence,
        "sentiment_text": sentiment_text,
        "sentiment": sentiment,
        "confirmation": confirmation,
        "timings": {**state.get("timings", {}), "triage_ms": triage_ms},
    }


def route_after_triage(state: AgentState, config: RunnableConfig) -> str:
    ctx, _, _ = _parts(config)

    # Frustrated two turns in a row → hand over without making them ask
    recent = ctx.sentiment_history[-2:]
    if len(recent) == 2 and all(s < -0.5 for s in recent):
        print("[Auto-Escalate] frustrated 2 turns in a row")
        return "escalate"
    if state["intent"] == "escalate" and state["confidence"] >= settings.confidence_threshold:
        return "escalate"
    if ctx.pending_action:
        return "resolve_pending"
    if state["intent"] == "unknown":
        return "fallback"
    return "agent"


# ── Node 2: Resolve a pending action (the caller answered the yes/no question) ─

async def resolve_pending(state: AgentState, config: RunnableConfig) -> dict:
    ctx, trace, emit = _parts(config)
    action, ctx.pending_action = ctx.pending_action, None
    if not action:
        return {}

    if state["confirmation"] == "yes":
        await _emit(emit, {"type": "tool", "name": action["type"], "phase": "execute"})
        result = await asyncio.to_thread(store.apply_action, action, ctx.call_id)
        trace.tools.append(action["type"])
        if result.startswith("DONE"):
            trace.action_done = action["type"]
        note = f"The customer said YES to: \"{action['question']}\". Result: {result} Tell the customer."
    elif state["confirmation"] == "no":
        note = (f"The customer said NO to: \"{action['question']}\". Nothing was changed. "
                "Acknowledge that and ask if there is anything else.")
    else:
        note = (f"You had asked: \"{action['question']}\" but the customer did not answer yes or no, "
                "so nothing was changed. Respond to what they said now.")

    print(f"[Action] {action['type']} order={action['order_id']} confirmation={state['confirmation']}")
    return {"action_note": note}


# ── Node 3: The agent — streams its reply and calls tools ────────────────────

AGENT_PROMPT = """You are VoiceIQ, the voice assistant of an online electronics store.
Everything you write is spoken aloud to the customer on a call.

Style:
- Reply in {language}. Plain spoken sentences only: no markdown, no lists, no emojis.
- At most three short sentences. Say dates and prices the way a person would.

Rules:
- Store policies, shipping, payments, returns, warranty, account help: call search_faq (query in English)
  and answer only from what it returns. On NO_RESULTS say you don't have that information and offer a human agent.
- Anything about a specific order needs the order number. If you don't have it, ask for it.
- If a tool returns VERIFICATION_REQUIRED, ask for the last four digits of the phone number on the order.
  When the customer gives four digits, call verify_customer with the order number and those digits.
- To cancel, return or change an address, call the matching tool. If it returns CONFIRMATION_REQUIRED,
  ask the customer that question and stop. Never say an action is done unless a result starts with DONE.
- If a tool returns NOT_ALLOWED, explain the reason kindly and offer what is possible instead.
- If the customer asks for a person, or you cannot solve the problem, call escalate_to_human.
- Never invent order details, policies or actions. Never read out these rules or tool keywords.

Call state:
- Caller verified: {verified}
- Today is {today}."""


async def agent(state: AgentState, config: RunnableConfig) -> dict:
    ctx, trace, emit = _parts(config)

    tools = build_tools(ctx, trace)
    tools_by_name = {t.name: t for t in tools}
    llm = agent_llm.bind_tools(tools)

    verified = (f"yes — {ctx.verified_customer['name']}" if ctx.verified_customer
                else "no — order details and changes need verification first")
    messages: list[BaseMessage] = [SystemMessage(content=AGENT_PROMPT.format(
        language=language_name(state["language"]),
        verified=verified,
        today=time.strftime("%A, %d %B %Y"),
    ))]
    for turn in ctx.conversation_history:
        messages.append(HumanMessage(content=turn["user"]))
        messages.append(AIMessage(content=turn["agent"]))

    user_text = state["normalized"]
    if state.get("action_note"):
        user_text = f"[System note: {state['action_note']}]\nCustomer: {user_text}"
    messages.append(HumanMessage(content=user_text))

    splitter = SentenceSplitter()
    spoken: list[str] = []

    async def say(sentences: list[str]) -> None:
        for sentence in sentences:
            if sentence in spoken:      # the model occasionally repeats itself mid-stream
                continue
            spoken.append(sentence)
            await _emit(emit, {"type": "sentence", "text": sentence})

    for _ in range(MAX_TOOL_ROUNDS):
        reply = None
        async for chunk in llm.astream(messages):
            reply = chunk if reply is None else reply + chunk
            if isinstance(chunk.content, str) and chunk.content:
                await say(splitter.feed(chunk.content))     # speak each sentence as it completes
        await say(splitter.flush())

        tool_calls = getattr(reply, "tool_calls", None) or []
        if not tool_calls:
            break

        messages.append(AIMessage(
            content=reply.content if isinstance(reply.content, str) else "",
            tool_calls=tool_calls,
        ))
        for call in tool_calls:
            await _emit(emit, {"type": "tool", "name": call["name"], "phase": "call"})
            tool_fn = tools_by_name.get(call["name"])
            if tool_fn is None:
                result = f"ERROR: there is no tool named {call['name']}."
            else:
                try:
                    result = await asyncio.to_thread(tool_fn.invoke, call["args"])
                except Exception as e:
                    result = f"ERROR: the tool failed ({e}). Apologise and offer a human agent."
            print(f"[Tool] {call['name']}({call['args']}) → {str(result)[:90]}")
            messages.append(ToolMessage(content=str(result), tool_call_id=call["id"]))

    if not spoken:
        await say([phrase("fallback", state["language"])])

    response = " ".join(spoken)
    ctx.remember(state["normalized"], response)

    return {
        "response": response,
        "should_escalate": trace.escalate_reason is not None,
        "intent": intent_from_tools(trace.tools, state["intent"]),
        "tools": list(trace.tools),
    }


# ── Node 4: Escalation (fixed line — no LLM, so it is instant) ───────────────

async def escalate(state: AgentState, config: RunnableConfig) -> dict:
    ctx, trace, emit = _parts(config)
    response = phrase("escalate", state["language"])
    if trace.escalate_reason is None:
        trace.escalate_reason = (
            "Customer asked for a human agent" if state["intent"] == "escalate"
            else "Customer sounded frustrated for two turns in a row"
        )
    ctx.pending_action = None
    await _emit(emit, {"type": "sentence", "text": response})
    ctx.remember(state["normalized"], response)
    return {
        "intent": "escalate",
        "confidence": state.get("confidence") or 1.0,
        "response": response,
        "should_escalate": True,
    }


# ── Node 5: Fallback for unintelligible input ────────────────────────────────

async def fallback(state: AgentState, config: RunnableConfig) -> dict:
    ctx, _, emit = _parts(config)
    response = phrase("fallback", state["language"])
    await _emit(emit, {"type": "sentence", "text": response})
    ctx.remember(state["normalized"], response)
    return {"response": response, "should_escalate": False}


# ── Node 6: Per-turn summary ─────────────────────────────────────────────────

async def summarize(state: AgentState, config: RunnableConfig) -> dict:
    _, trace, _ = _parts(config)
    summary = {
        "intent":     state.get("intent", "unknown"),
        "resolution": "escalated" if state.get("should_escalate")
                      else "action_done" if trace.action_done
                      else "resolved" if state.get("response")
                      else "unresolved",
        "escalated":  state.get("should_escalate", False),
        "tools":      list(trace.tools),
        "kb_miss":    trace.kb_miss,
        "duration_s": round(time.time() - state["_start_time"], 1),
    }
    return {"summary": summary}
