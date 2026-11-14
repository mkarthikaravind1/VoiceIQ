"""
Tools the agent can call.

Tools are built per turn so they can close over the call's context:
  - order tools refuse to reveal anything until the caller is verified
  - actions that change an order are never executed here. They are checked,
    parked in ctx.pending_action, and only run after the caller says yes
    (see resolve_pending in nodes.py).

Tool results are short English lines for the LLM, with a leading keyword
(VERIFICATION_REQUIRED, CONFIRMATION_REQUIRED, DONE, ...) it is told to obey.
"""
import re
from langchain_core.tools import tool
from app.agent.context import CallContext, TurnTrace
from app.config import get_settings
from app.db import store
from app.rag.retriever import get_retriever

settings = get_settings()

MAX_VERIFY_ATTEMPTS = 3

# Which intent a turn is filed under, by the tools it used (strongest first)
TOOL_INTENTS = [
    ("escalate_to_human", "escalate"),
    ("cancel_order", "order_action"),
    ("start_return", "order_action"),
    ("update_shipping_address", "order_action"),
    ("get_order_status", "order_lookup"),
    ("verify_customer", "order_lookup"),
    ("search_faq", "faq"),
]

VERIFY_PROMPT = (
    "VERIFICATION_REQUIRED: do not share or change anything about this order yet. "
    "Ask the customer for the last four digits of the phone number on the order, "
    "then call verify_customer."
)


def _digits(value) -> str:
    return re.sub(r"\D", "", str(value or ""))


def build_tools(ctx: CallContext, trace: TurnTrace) -> list:

    def _load(order_id: str):
        """Return (order, error). Error is set if the order is missing or the caller is unverified."""
        order_id = _digits(order_id)
        if not order_id:
            return None, "MISSING_ORDER_NUMBER: ask the customer for their order number."
        order = store.get_order(order_id)
        if not order:
            return None, f"NOT_FOUND: there is no order {order_id}. Ask the customer to repeat the number."
        verified = ctx.verified_customer
        if not verified or verified["id"] != order["customer_id"]:
            return None, VERIFY_PROMPT
        return order, None

    def _park(action: dict, question: str) -> str:
        ctx.pending_action = {**action, "question": question}
        return (
            f'CONFIRMATION_REQUIRED: nothing has been changed yet. Ask the customer: "{question}" '
            "and wait for their answer. Do not say it is done."
        )

    @tool
    def search_faq(query: str) -> str:
        """Search the store's policies and help articles: returns, exchanges, shipping, payments,
        warranty, loyalty points, account help. The query MUST be written in English."""
        trace.tools.append("search_faq")
        trace.kb_queries.append(query)
        context, best_distance, _ = get_retriever().search(query)
        if not context:
            trace.kb_miss = True
            return ("NO_RESULTS: the knowledge base has nothing on this. Say you don't have that "
                    "information and offer to connect a human agent.")
        if best_distance is not None and best_distance > settings.rag_weak_distance:
            # Loosely related articles only — log it as a gap and stop the model guessing
            trace.kb_miss = True
            return (context + "\n\nWARNING: these articles are only loosely related. If they do not "
                    "directly answer the question, say you don't have that information and offer "
                    "a human agent. Do not guess.")
        return context

    @tool
    def verify_customer(order_id: str, phone_last4: str) -> str:
        """Verify the caller owns an order, using the last four digits of the phone number on it.
        Call this after the customer tells you those four digits."""
        trace.tools.append("verify_customer")
        order = store.get_order(_digits(order_id))
        if not order:
            return f"NOT_FOUND: there is no order {_digits(order_id)}. Ask the customer to repeat the order number."
        last4 = _digits(phone_last4)
        if len(last4) != 4:
            return "INVALID: exactly four digits are needed. Ask the customer to repeat the last four digits."

        if store.phone_matches(order, last4):
            ctx.verified_customer = {"id": order["customer_id"], "name": order["customer_name"]}
            ctx.verify_attempts = 0
            trace.verified_now = True
            return f"VERIFIED: the caller is {order['customer_name']}. " + store.describe_order(order)

        ctx.verify_attempts += 1
        if ctx.verify_attempts >= MAX_VERIFY_ATTEMPTS:
            trace.escalate_reason = "Caller failed identity verification three times"
            return ("LOCKED: too many failed attempts. Tell the customer you are connecting them "
                    "to a human agent who can help verify their identity.")
        return "MISMATCH: those digits do not match the order. Ask the customer to try again."

    @tool
    def get_order_status(order_id: str) -> str:
        """Get the status, items, delivery date and tracking of an order. Needs the order number."""
        trace.tools.append("get_order_status")
        order, error = _load(order_id)
        return error or store.describe_order(order)

    @tool
    def cancel_order(order_id: str) -> str:
        """Cancel an order that has not shipped yet and refund it."""
        trace.tools.append("cancel_order")
        order, error = _load(order_id)
        if error:
            return error
        ok, why = store.can_cancel(order)
        if not ok:
            return f"NOT_ALLOWED: {why}."
        return _park(
            {"type": "cancel_order", "order_id": order["order_id"]},
            f"Do you want me to cancel order {order['order_id']} for {', '.join(order['items'])} "
            f"and refund ${order['total']:.2f}?",
        )

    @tool
    def start_return(order_id: str, reason: str = "") -> str:
        """Start a return for a delivered order (allowed within 30 days of delivery)."""
        trace.tools.append("start_return")
        order, error = _load(order_id)
        if error:
            return error
        ok, why = store.can_return(order)
        if not ok:
            return f"NOT_ALLOWED: {why}."
        return _park(
            {"type": "start_return", "order_id": order["order_id"], "reason": reason},
            f"Do you want me to start a return for order {order['order_id']}, {', '.join(order['items'])}?",
        )

    @tool
    def update_shipping_address(order_id: str, new_address: str) -> str:
        """Change the delivery address of an order that has not shipped yet.
        new_address must be the full address the customer said."""
        trace.tools.append("update_shipping_address")
        order, error = _load(order_id)
        if error:
            return error
        new_address = (new_address or "").strip()
        if len(new_address) < 8:
            return "INVALID: ask the customer for the full new address."
        ok, why = store.can_change_address(order)
        if not ok:
            return f"NOT_ALLOWED: {why}."
        return _park(
            {"type": "update_shipping_address", "order_id": order["order_id"], "new_address": new_address},
            f"Do you want me to change the delivery address of order {order['order_id']} to {new_address}?",
        )

    @tool
    def escalate_to_human(reason: str) -> str:
        """Hand the call to a human agent. Use when the customer asks for a person,
        or when you cannot solve their problem."""
        trace.tools.append("escalate_to_human")
        trace.escalate_reason = reason or "Customer asked for a human agent"
        return "ESCALATED: tell the customer you are connecting them to a human agent now."

    return [
        search_faq, verify_customer, get_order_status,
        cancel_order, start_return, update_shipping_address, escalate_to_human,
    ]


def intent_from_tools(tool_names: list, default: str) -> str:
    for name, intent in TOOL_INTENTS:
        if name in tool_names:
            return intent
    return default
