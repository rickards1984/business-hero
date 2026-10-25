"""OUT-19 part A — the AI cost ledger.

Every outreach AI call records what it cost in `usage_meters` (the meter name
is free text, so no migration), aggregated per UK month for its business,
purpose (research, draft, classify, answer), brand and provider/model, with
call, token and tool-call counts beside the pence:

    ai_pence                                        the business's total
    ai_pence:<purpose>:<brand|->:<provider/model>   cost
    ai_calls:<purpose>:<brand|->:<provider/model>   calls (estimated ones included)
    ai_estimated:<purpose>:<brand|->:<provider/model>  calls whose cost was estimated
    ai_tokens_in:… / ai_tokens_out:… / ai_tools:…   usage

A call whose real usage is unknown (a timeout that may still be billed) is
recorded at a conservative estimate and counted as estimated, never as free.

Mike, 25 Oct 2026: outreach must cover every AI cost with a net profit and
never become "a money losing monster". A platform-wide monthly alarm and kill
switch stop runaway spend. The kill switch checks RECORDED spend: a call
already in flight when the limit is reached still completes and is recorded,
so the limit can be exceeded by at most the calls in flight at that moment.

Prices are pence per million tokens (input, output) and pence per tool call,
from provider list prices at about £1 = $1.27. They must be checked against
the providers' current pages; AI_PRICES_JSON ({"provider/model": [in, out,
per_tool_call]}) overrides them without a deploy. A configuration with any
invalid entry is ignored as a whole. A model with no price is refused before
any spend (`require_priced`).
"""
import json
import logging
import math
import os
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import event, text

from services.metering import period_for

logger = logging.getLogger(__name__)

TOTAL = "ai_pence"
DEFAULT_PRICES = {
    "openai/gpt-4.1": (160, 640, 2),
    "openai/gpt-4o": (200, 790, 2),
    "openai/gpt-4o-mini": (12, 47, 2),
    "xai/grok-4": (240, 1190, 2),
    "anthropic/claude-sonnet-4-5": (240, 1190, 1),
}
LEDGER_LOCK = 0x4F555431   # one advisory lock serialises ledger writes platform-wide (PostgreSQL)

_collecting: ContextVar[Optional[list]] = ContextVar("ai_costs_collecting", default=None)


class Unpriced(Exception):
    """A model with no known price: refused before any spend."""


def _valid(value) -> Optional[tuple]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    try:
        out = tuple(float(v) for v in value)
    except (TypeError, ValueError):
        return None
    return out if all(math.isfinite(v) and v >= 0 for v in out) else None


def _prices() -> dict:
    table = dict(DEFAULT_PRICES)
    raw = os.environ.get("AI_PRICES_JSON")
    if not raw:
        return table
    try:
        parsed = json.loads(raw)
        overrides = {str(k): _valid(v) for k, v in parsed.items()}
    except (ValueError, TypeError, AttributeError):
        overrides = None
    if not overrides or any(v is None or "/" not in k for k, v in overrides.items()):
        logger.error("AI_PRICES_JSON is not valid; all of it is ignored and the built-in prices are used")
        return table
    table.update(overrides)
    return table


def known_models() -> list:
    return [tuple(k.split("/", 1)) for k in _prices()]


def price(provider: str, model: str) -> tuple:
    found = _prices().get(f"{provider}/{model}")
    if found is None:
        raise Unpriced(f"No price is set for {provider}/{model}")
    return tuple(found)


def require_priced(provider: str, model: str) -> None:
    """Call before spending: an unpriced model is never used."""
    price(provider, model)


def cost(provider: str, model: str, input_tokens: int = 0, output_tokens: int = 0, tool_calls: int = 0) -> float:
    p_in, p_out, p_tool = price(provider, model)
    return (input_tokens * p_in + output_tokens * p_out) / 1_000_000 + tool_calls * p_tool


def _add(session, bid: str, meter: str, period: str, amount: float, at: datetime) -> None:
    # One atomic upsert: concurrent first writes to a month's meter never collide.
    session.execute(text(
        "INSERT INTO usage_meters (business_id, meter, period, value, updated_at) VALUES (:b, :m, :p, :v, :at) "
        "ON CONFLICT (business_id, meter, period) DO UPDATE SET value = usage_meters.value + excluded.value, "
        "updated_at = excluded.updated_at"), {"b": bid, "m": meter, "p": period, "v": amount, "at": at})


def platform_total(session, period: str) -> float:
    return float(session.execute(text("SELECT coalesce(sum(value), 0) FROM usage_meters WHERE meter = :m AND period = :p"),
                                 {"m": TOTAL, "p": period}).scalar() or 0)


def _serialise(session) -> None:
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": LEDGER_LOCK})


def _alarm_after_commit(session, period: str, total: float, alarm: str) -> None:
    def fire(_session):
        logger.error("AI spend alarm: the platform's AI spend for %s has reached %.0fp (alarm %sp)", period, total, alarm)
    event.listen(session, "after_commit", fire, once=True)


def record(session, business_id, *, purpose: str, provider: str, model: str, brand_id=None,
           input_tokens: int = 0, output_tokens: int = 0, tool_calls: int = 0,
           pence: Optional[float] = None, estimated: bool = False, moment: Optional[datetime] = None) -> float:
    """Add one call's cost to the ledger in the caller's transaction (no commit).
    Always the last lock a transaction takes, so it cannot deadlock."""
    moment = moment or datetime.now(timezone.utc)
    amount = float(pence) if pence is not None else cost(provider, model, input_tokens, output_tokens, tool_calls)
    period, bid = period_for(moment), str(business_id)
    key = f"{purpose}:{brand_id or '-'}:{provider}/{model}"
    _serialise(session)
    before = platform_total(session, period)
    _add(session, bid, TOTAL, period, amount, moment)
    for name, value in ((f"ai_pence:{key}", amount), (f"ai_calls:{key}", 1), (f"ai_tokens_in:{key}", input_tokens),
                        (f"ai_tokens_out:{key}", output_tokens), (f"ai_tools:{key}", tool_calls),
                        (f"ai_estimated:{key}", 1 if estimated else 0)):
        if value:
            _add(session, bid, name, period, value, moment)
    alarm = os.environ.get("AI_MONTHLY_ALARM_PENCE")
    if alarm and before < float(alarm) <= before + amount:
        _alarm_after_commit(session, period, before + amount, alarm)
    return amount


def allowed(session, *, moment: Optional[datetime] = None) -> bool:
    """False once the platform's recorded AI spend this month reaches AI_MONTHLY_KILL_PENCE."""
    kill = os.environ.get("AI_MONTHLY_KILL_PENCE")
    if not kill:
        return True
    return platform_total(session, period_for(moment or datetime.now(timezone.utc))) < float(kill)


@contextmanager
def collect():
    """Gather the usage of model calls made inside the block, so the caller can
    record them once it holds a transaction (no lock is held while a model runs)."""
    spent: list = []
    token = _collecting.set(spent)
    try:
        yield spent
    finally:
        _collecting.reset(token)


def note(provider: str, model: str, usage, *, estimated: bool = False, tool_calls: int = 0) -> None:
    """Called by a model adapter after every attempt; kept only inside collect()."""
    spent = _collecting.get()
    if spent is None:
        return
    spent.append({"provider": provider, "model": model, "estimated": estimated, "tool_calls": tool_calls,
                  "input_tokens": int(getattr(usage, "prompt_tokens", None) or getattr(usage, "input_tokens", 0) or 0),
                  "output_tokens": int(getattr(usage, "completion_tokens", None) or getattr(usage, "output_tokens", 0) or 0)})


def save(session, business_id, spent: list, *, purpose: str, brand_id=None, moment: Optional[datetime] = None) -> float:
    return sum(record(session, business_id, purpose=purpose, brand_id=brand_id, moment=moment, **call) for call in spent)


def economics(session, *, period: str) -> dict:
    """Each business's AI cost this period, by purpose, brand and model, with usage."""
    rows = session.execute(text("SELECT business_id, meter, value FROM usage_meters WHERE period = :p "
                                "AND (meter = :t OR meter LIKE 'ai\\_%' ESCAPE '\\')"),
                           {"p": period, "t": TOTAL}).fetchall()
    out: dict = {}
    for bid, meter, value in rows:
        b = out.setdefault(str(bid), {"total_pence": 0.0, "by_purpose": {}, "by_brand": {}, "models": {}})
        value = float(value or 0)
        if meter == TOTAL:
            b["total_pence"] += value
            continue
        kind, _, rest = meter.partition(":")
        parts = rest.split(":", 2)
        if len(parts) != 3:
            continue
        purpose, brand, model = parts
        m = b["models"].setdefault(model, {"pence": 0.0, "calls": 0, "estimated_calls": 0, "tokens_in": 0,
                                           "tokens_out": 0, "tool_calls": 0})
        if kind == "ai_pence":
            m["pence"] += value
            b["by_purpose"][purpose] = b["by_purpose"].get(purpose, 0) + value
            if brand != "-":
                b["by_brand"][brand] = b["by_brand"].get(brand, 0) + value
        else:
            field = {"ai_calls": "calls", "ai_estimated": "estimated_calls", "ai_tokens_in": "tokens_in",
                     "ai_tokens_out": "tokens_out", "ai_tools": "tool_calls"}.get(kind)
            if field:
                m[field] += int(value)
    return {"period": period, "businesses": out, "platform_pence": sum(b["total_pence"] for b in out.values()),
            "alarm_pence": os.environ.get("AI_MONTHLY_ALARM_PENCE"), "kill_pence": os.environ.get("AI_MONTHLY_KILL_PENCE")}
