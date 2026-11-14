"""
SQLite store — orders the agent can act on, plus the call history used by
the analytics dashboard.

Everything here is synchronous (stdlib sqlite3). Async code calls it through
asyncio.to_thread so the event loop is never blocked.

Reset the demo data:  python -m app.db.store --reset
"""
import json
import os
import sqlite3
import sys
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from app.config import get_settings

settings = get_settings()

SEED_PATH = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../data/orders_db.json")
)

RETURN_WINDOW_DAYS = 30

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL,
    email   TEXT,
    phone   TEXT
);
CREATE TABLE IF NOT EXISTS orders (
    order_id            TEXT PRIMARY KEY,
    customer_id         INTEGER NOT NULL REFERENCES customers(id),
    status              TEXT NOT NULL,
    items               TEXT NOT NULL,
    total               REAL NOT NULL,
    placed_on           TEXT,
    delivered_on        TEXT,
    estimated_delivery  TEXT,
    cancelled_on        TEXT,
    tracking            TEXT,
    shipping_address    TEXT,
    refund_status       TEXT
);
CREATE TABLE IF NOT EXISTS returns (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id    TEXT NOT NULL REFERENCES orders(order_id),
    reason      TEXT,
    status      TEXT NOT NULL DEFAULT 'Return started',
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS order_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id    TEXT NOT NULL,
    call_id     TEXT,
    action      TEXT NOT NULL,
    detail      TEXT,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS calls (
    id              TEXT PRIMARY KEY,
    channel         TEXT NOT NULL,
    started_at      TEXT NOT NULL,
    ended_at        TEXT,
    language        TEXT,
    turns           INTEGER NOT NULL DEFAULT 0,
    escalated       INTEGER NOT NULL DEFAULT 0,
    handed_off      INTEGER NOT NULL DEFAULT 0,
    avg_sentiment   REAL,
    min_sentiment   REAL,
    avg_ttfa_ms     REAL,
    resolution      TEXT,
    csat            INTEGER,
    summary         TEXT,
    topics          TEXT
);
CREATE TABLE IF NOT EXISTS turns (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id         TEXT NOT NULL REFERENCES calls(id),
    idx             INTEGER NOT NULL,
    ts              TEXT NOT NULL,
    speaker         TEXT NOT NULL DEFAULT 'ai',
    transcript      TEXT,
    response        TEXT,
    intent          TEXT,
    confidence      REAL,
    sentiment_text  REAL,
    arousal         REAL,
    sentiment       REAL,
    tools           TEXT,
    kb_miss         INTEGER NOT NULL DEFAULT 0,
    timings         TEXT
);
CREATE TABLE IF NOT EXISTS knowledge_gaps (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id     TEXT,
    question    TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_turns_call ON turns(call_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def db():
    conn = sqlite3.connect(settings.db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# ── Setup ────────────────────────────────────────────────────────────────────

def init_db(reset: bool = False) -> None:
    """Create tables; seed the sample customers and orders if there are none."""
    os.makedirs(os.path.dirname(settings.db_path) or ".", exist_ok=True)
    if reset and os.path.exists(settings.db_path):
        os.remove(settings.db_path)
    with db() as conn:
        conn.executescript(SCHEMA)
        if conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0:
            _seed(conn)


def _seed(conn: sqlite3.Connection) -> None:
    with open(SEED_PATH, encoding="utf-8") as f:
        seed = json.load(f)
    today = date.today()

    def ago(days):
        return None if days is None else (today - timedelta(days=days)).isoformat()

    for c in seed["customers"]:
        conn.execute(
            "INSERT OR REPLACE INTO customers (id, name, email, phone) VALUES (?, ?, ?, ?)",
            (c["id"], c["name"], c.get("email"), c.get("phone")),
        )
    for o in seed["orders"]:
        eta = o.get("eta_in_days")
        conn.execute(
            """INSERT OR REPLACE INTO orders (order_id, customer_id, status, items, total, placed_on,
               delivered_on, estimated_delivery, cancelled_on, tracking, shipping_address, refund_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                o["order_id"], o["customer_id"], o["status"], json.dumps(o["items"]), o["total"],
                ago(o.get("placed_days_ago")), ago(o.get("delivered_days_ago")),
                None if eta is None else (today + timedelta(days=eta)).isoformat(),
                ago(o.get("cancelled_days_ago")), o.get("tracking"),
                o.get("shipping_address"), o.get("refund_status"),
            ),
        )
    print(f"Seeded {len(seed['orders'])} sample orders into {settings.db_path}")


# ── Orders ───────────────────────────────────────────────────────────────────

def get_order(order_id: str) -> dict | None:
    with db() as conn:
        row = conn.execute(
            """SELECT o.*, c.name AS customer_name, c.phone AS customer_phone
               FROM orders o JOIN customers c ON c.id = o.customer_id WHERE o.order_id = ?""",
            (str(order_id),),
        ).fetchone()
        if not row:
            return None
        order = dict(row)
        order["items"] = json.loads(order["items"])
        ret = conn.execute(
            "SELECT status FROM returns WHERE order_id = ? ORDER BY id DESC LIMIT 1", (str(order_id),)
        ).fetchone()
        order["return_status"] = ret["status"] if ret else None
        return order


def phone_matches(order: dict, last4: str) -> bool:
    phone = "".join(ch for ch in (order.get("customer_phone") or "") if ch.isdigit())
    return len(last4) == 4 and phone.endswith(last4)


def describe_order(order: dict) -> str:
    """One line of facts the LLM can turn into a spoken answer."""
    parts = [
        f"ORDER {order['order_id']} for {order['customer_name']}",
        f"status: {order['status']}",
        f"items: {', '.join(order['items'])}",
        f"total: ${order['total']:.2f}",
        f"placed on {order['placed_on']}",
    ]
    if order["status"] == "Delivered":
        parts.append(f"delivered on {order['delivered_on']}")
    elif order["status"] in ("In Transit", "Processing"):
        parts.append(f"estimated delivery {order['estimated_delivery']}")
    elif order["status"] == "Cancelled":
        parts.append(f"cancelled on {order['cancelled_on']}; {order.get('refund_status') or 'refund pending'}")
    if order.get("tracking"):
        parts.append(f"tracking number {order['tracking']}")
    if order.get("shipping_address"):
        parts.append(f"ships to {order['shipping_address']}")
    if order.get("return_status"):
        parts.append(f"return: {order['return_status']}")
    return "; ".join(parts) + "."


# Each action has a check (can it be done?) and an apply (do it). The agent
# runs the check, asks the caller to confirm, and only then the apply runs.

def can_cancel(order: dict) -> tuple[bool, str]:
    if order["status"] == "Processing":
        return True, ""
    if order["status"] == "Cancelled":
        return False, "the order is already cancelled"
    if order["status"] == "In Transit":
        return False, "the order has already shipped, so it cannot be cancelled; it can be returned after delivery"
    return False, "the order was already delivered; a return can be started instead"


def can_return(order: dict) -> tuple[bool, str]:
    if order.get("return_status"):
        return False, "a return has already been started for this order"
    if order["status"] != "Delivered":
        return False, f"only delivered orders can be returned and this one is {order['status'].lower()}"
    delivered = date.fromisoformat(order["delivered_on"])
    days = (date.today() - delivered).days
    if days > RETURN_WINDOW_DAYS:
        return False, f"it was delivered {days} days ago, which is outside the {RETURN_WINDOW_DAYS}-day return window"
    return True, ""


def can_change_address(order: dict) -> tuple[bool, str]:
    if order["status"] == "Processing":
        return True, ""
    return False, f"the address can only be changed before the order ships and this one is {order['status'].lower()}"


def _log_event(conn, order_id: str, call_id: str | None, action: str, detail: str) -> None:
    conn.execute(
        "INSERT INTO order_events (order_id, call_id, action, detail, created_at) VALUES (?, ?, ?, ?, ?)",
        (order_id, call_id, action, detail, _now()),
    )


def apply_action(action: dict, call_id: str | None = None) -> str:
    """
    Carry out a confirmed action. Re-checks eligibility, because the order may
    have changed between the question and the caller's "yes".
    Returns a line starting with DONE or FAILED.
    """
    order = get_order(action["order_id"])
    if not order:
        return f"FAILED: order {action['order_id']} no longer exists."
    kind = action["type"]

    with db() as conn:
        if kind == "cancel_order":
            ok, why = can_cancel(order)
            if not ok:
                return f"FAILED: {why}."
            refund = "Refund issued; it reaches the original payment method in 3-5 business days"
            conn.execute(
                "UPDATE orders SET status = 'Cancelled', cancelled_on = ?, refund_status = ? WHERE order_id = ?",
                (date.today().isoformat(), refund, order["order_id"]),
            )
            _log_event(conn, order["order_id"], call_id, kind, "cancelled by voice agent")
            return (f"DONE: order {order['order_id']} is cancelled. A refund of ${order['total']:.2f} "
                    "will reach the original payment method in 3-5 business days.")

        if kind == "start_return":
            ok, why = can_return(order)
            if not ok:
                return f"FAILED: {why}."
            conn.execute(
                "INSERT INTO returns (order_id, reason, created_at) VALUES (?, ?, ?)",
                (order["order_id"], action.get("reason") or "", _now()),
            )
            _log_event(conn, order["order_id"], call_id, kind, action.get("reason") or "")
            return (f"DONE: a return is started for order {order['order_id']}. A prepaid return label "
                    "will be emailed, and the refund is issued once the item is received.")

        if kind == "update_shipping_address":
            ok, why = can_change_address(order)
            if not ok:
                return f"FAILED: {why}."
            conn.execute(
                "UPDATE orders SET shipping_address = ? WHERE order_id = ?",
                (action["new_address"], order["order_id"]),
            )
            _log_event(conn, order["order_id"], call_id, kind, action["new_address"])
            return f"DONE: order {order['order_id']} will now ship to {action['new_address']}."

    return f"FAILED: unknown action {kind}."


# ── Call history (analytics) ─────────────────────────────────────────────────

def create_call(call_id: str, channel: str, language: str) -> None:
    with db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO calls (id, channel, started_at, language) VALUES (?, ?, ?, ?)",
            (call_id, channel, _now(), language),
        )


def add_turn(call_id: str, idx: int, turn: dict) -> int:
    with db() as conn:
        cur = conn.execute(
            """INSERT INTO turns (call_id, idx, ts, speaker, transcript, response, intent, confidence,
               sentiment_text, arousal, sentiment, tools, kb_miss, timings)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                call_id, idx, _now(), turn.get("speaker", "ai"), turn.get("transcript"),
                turn.get("response"), turn.get("intent"), turn.get("confidence"),
                turn.get("sentiment_text"), turn.get("arousal"), turn.get("sentiment"),
                json.dumps(turn.get("tools") or []), 1 if turn.get("kb_miss") else 0,
                json.dumps(turn.get("timings") or {}),
            ),
        )
        conn.execute("UPDATE calls SET turns = turns + 1 WHERE id = ?", (call_id,))
        return int(cur.lastrowid or 0)


def update_turn_timings(turn_row_id: int, timings: dict) -> None:
    with db() as conn:
        conn.execute("UPDATE turns SET timings = ? WHERE id = ?", (json.dumps(timings), turn_row_id))


def add_knowledge_gap(call_id: str, question: str) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO knowledge_gaps (call_id, question, created_at) VALUES (?, ?, ?)",
            (call_id, question, _now()),
        )


def end_call(call_id: str, fields: dict) -> None:
    """Close a call and store its post-call analysis."""
    with db() as conn:
        rows = conn.execute(
            "SELECT sentiment, timings FROM turns WHERE call_id = ? AND speaker = 'ai'", (call_id,)
        ).fetchall()
        sentiments = [r["sentiment"] for r in rows if r["sentiment"] is not None]
        ttfas = [t for t in (json.loads(r["timings"] or "{}").get("ttfa_ms") for r in rows) if t]
        conn.execute(
            """UPDATE calls SET ended_at = ?, language = COALESCE(?, language), escalated = ?, handed_off = ?,
               avg_sentiment = ?, min_sentiment = ?, avg_ttfa_ms = ?, resolution = ?, csat = ?,
               summary = ?, topics = ? WHERE id = ?""",
            (
                _now(), fields.get("language"), 1 if fields.get("escalated") else 0,
                1 if fields.get("handed_off") else 0,
                sum(sentiments) / len(sentiments) if sentiments else None,
                min(sentiments) if sentiments else None,
                sum(ttfas) / len(ttfas) if ttfas else None,
                fields.get("resolution"), fields.get("csat"), fields.get("summary"),
                json.dumps(fields.get("topics") or []), call_id,
            ),
        )


def _call_row(row: sqlite3.Row) -> dict:
    call = dict(row)
    call["topics"] = json.loads(call.get("topics") or "[]")
    call["escalated"] = bool(call["escalated"])
    call["handed_off"] = bool(call["handed_off"])
    return call


def list_calls(limit: int = 50) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM calls WHERE turns > 0 ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_call_row(r) for r in rows]


def get_call(call_id: str) -> dict | None:
    with db() as conn:
        row = conn.execute("SELECT * FROM calls WHERE id = ?", (call_id,)).fetchone()
        if not row:
            return None
        call = _call_row(row)
        turns = conn.execute("SELECT * FROM turns WHERE call_id = ? ORDER BY idx", (call_id,)).fetchall()
        call["turn_list"] = [
            {**dict(t), "tools": json.loads(t["tools"] or "[]"),
             "timings": json.loads(t["timings"] or "{}"), "kb_miss": bool(t["kb_miss"])}
            for t in turns
        ]
        return call


def analytics_summary() -> dict:
    with db() as conn:
        k = conn.execute(
            """SELECT COUNT(*) AS calls,
                      SUM(escalated) AS escalated,
                      SUM(CASE WHEN resolution = 'resolved' THEN 1 ELSE 0 END) AS resolved,
                      SUM(CASE WHEN ended_at IS NOT NULL THEN 1 ELSE 0 END) AS ended,
                      AVG(csat) AS avg_csat, AVG(avg_sentiment) AS avg_sentiment,
                      AVG(avg_ttfa_ms) AS avg_ttfa_ms, SUM(turns) AS turns
               FROM calls WHERE turns > 0"""
        ).fetchone()
        intents = conn.execute(
            """SELECT intent, COUNT(*) AS n FROM turns
               WHERE speaker = 'ai' AND intent IS NOT NULL AND intent != ''
               GROUP BY intent ORDER BY n DESC"""
        ).fetchall()
        per_day = conn.execute(
            """SELECT substr(started_at, 1, 10) AS day, COUNT(*) AS calls, SUM(escalated) AS escalated
               FROM calls WHERE turns > 0 GROUP BY day ORDER BY day DESC LIMIT 14"""
        ).fetchall()
        gaps = conn.execute(
            """SELECT question, COUNT(*) AS n, MAX(created_at) AS last_seen FROM knowledge_gaps
               GROUP BY lower(question) ORDER BY n DESC, last_seen DESC LIMIT 15"""
        ).fetchall()
        actions = conn.execute(
            "SELECT action, COUNT(*) AS n FROM order_events GROUP BY action ORDER BY n DESC"
        ).fetchall()

    calls = k["calls"] or 0
    ended = k["ended"] or 0
    return {
        "calls": calls,
        "turns": k["turns"] or 0,
        "escalation_rate": (k["escalated"] or 0) / calls if calls else None,
        "resolution_rate": (k["resolved"] or 0) / ended if ended else None,
        "avg_csat": k["avg_csat"],
        "avg_sentiment": k["avg_sentiment"],
        "avg_ttfa_ms": k["avg_ttfa_ms"],
        "intents": [dict(r) for r in intents],
        "per_day": [dict(r) for r in reversed(per_day)],
        "knowledge_gaps": [dict(r) for r in gaps],
        "actions": [dict(r) for r in actions],
    }


if __name__ == "__main__":
    init_db(reset="--reset" in sys.argv)
    print("Database ready:", settings.db_path)
