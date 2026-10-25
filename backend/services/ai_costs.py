"""OUT-19 part A — the AI cost ledger.

Every outreach AI call records what it cost, for its business, its purpose
(research, draft, classify, answer) and its brand, in `usage_meters` (the
meter name is free text, so no migration). Mike sees each business's cost and
margin; a platform-wide monthly alarm and kill switch stop runaway spend.

Mike, 25 Oct 2026: outreach must cover every AI cost with a net profit and
never become "a money losing monster".

Prices are pence per million tokens (input, output) and pence per tool call,
from provider list prices at about £1 = $1.27. Provider prices move: check
them, and override any of them with AI_PRICES_JSON
({"provider/model": [in, out, per_tool_call]}) without a deploy. A model with
no price is charged at the dearest known rate, never as free.
"""
import json
import logging
import os
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text

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

_collecting: ContextVar[Optional[list]] = ContextVar("ai_costs_collecting", default=None)


def _prices() -> dict:
    table = dict(DEFAULT_PRICES)
    raw = os.environ.get("AI_PRICES_JSON")
    if raw:
        try:
            for key, value in json.loads(raw).items():
                table[str(key)] = tuple(float(v) for v in value)
        except (ValueError, TypeError, AttributeError):
            logger.error("AI_PRICES_JSON is not valid; using the built-in prices")
    return table


def known_models() -> list:
    return [tuple(k.split("/", 1)) for k in _prices()]


def price(provider: str, model: str) -> tuple:
    table = _prices()
    found = table.get(f"{provider}/{model}")
    if found is None:
        logger.warning("Unpriced AI model %s/%s: charged at the dearest known rate", provider, model)
        found = max(table.values(), key=lambda p: p[0] + p[1])
    return tuple(found)


def cost(provider: str, model: str, input_tokens: int = 0, output_tokens: int = 0, tool_calls: int = 0) -> float:
    p_in, p_out, p_tool = price(provider, model)
    return (input_tokens * p_in + output_tokens * p_out) / 1_000_000 + tool_calls * p_tool


def _add(session, bid: str, meter: str, period: str, amount: float, at: datetime) -> None:
    params = {"b": bid, "m": meter, "p": period, "v": amount, "at": at}
    updated = session.execute(text("UPDATE usage_meters SET value = value + :v, updated_at = :at "
                                   "WHERE business_id = :b AND meter = :m AND period = :p"), params)
    if not updated.rowcount:
        session.execute(text("INSERT INTO usage_meters (business_id, meter, period, value, updated_at) "
                             "VALUES (:b, :m, :p, :v, :at)"), params)


def platform_total(session, period: str) -> float:
    return float(session.execute(text("SELECT coalesce(sum(value), 0) FROM usage_meters WHERE meter = :m AND period = :p"),
                                 {"m": TOTAL, "p": period}).scalar() or 0)


def record(session, business_id, *, purpose: str, provider: str, model: str, brand_id=None,
           input_tokens: int = 0, output_tokens: int = 0, tool_calls: int = 0,
           pence: Optional[float] = None, moment: Optional[datetime] = None) -> float:
    """Add one call's cost to the ledger in the caller's transaction (no commit)."""
    moment = moment or datetime.now(timezone.utc)
    amount = float(pence) if pence is not None else cost(provider, model, input_tokens, output_tokens, tool_calls)
    period, bid = period_for(moment), str(business_id)
    before = platform_total(session, period)
    _add(session, bid, TOTAL, period, amount, moment)
    _add(session, bid, f"{TOTAL}:{purpose}:{brand_id or '-'}", period, amount, moment)
    _add(session, bid, f"ai_calls:{provider}/{model}", period, 1, moment)
    alarm = os.environ.get("AI_MONTHLY_ALARM_PENCE")
    if alarm and before < float(alarm) <= before + amount:
        logger.error("AI spend alarm: the platform's AI spend for %s has reached %.0fp (alarm %sp)",
                     period, before + amount, alarm)
    return amount


def allowed(session, *, moment: Optional[datetime] = None) -> bool:
    """False once the platform's AI spend this month reaches AI_MONTHLY_KILL_PENCE."""
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


def note(provider: str, model: str, usage) -> None:
    """Called by a model adapter after a call; kept only inside collect()."""
    spent = _collecting.get()
    if spent is None:
        return
    spent.append({"provider": provider, "model": model,
                  "input_tokens": int(getattr(usage, "prompt_tokens", None) or getattr(usage, "input_tokens", 0) or 0),
                  "output_tokens": int(getattr(usage, "completion_tokens", None) or getattr(usage, "output_tokens", 0) or 0)})


def save(session, business_id, spent: list, *, purpose: str, brand_id=None, moment: Optional[datetime] = None) -> float:
    return sum(record(session, business_id, purpose=purpose, brand_id=brand_id, moment=moment, **call) for call in spent)


def economics(session, *, period: str) -> dict:
    """Each business's AI cost this period, by purpose, brand and model."""
    rows = session.execute(text("SELECT business_id, meter, value FROM usage_meters WHERE period = :p "
                                "AND (meter = :t OR meter LIKE 'ai_pence:%' OR meter LIKE 'ai_calls:%')"),
                           {"p": period, "t": TOTAL}).fetchall()
    out: dict = {}
    for bid, meter, value in rows:
        b = out.setdefault(str(bid), {"total_pence": 0.0, "by_purpose": {}, "by_brand": {}, "calls": {}})
        value = float(value or 0)
        if meter == TOTAL:
            b["total_pence"] += value
        elif meter.startswith("ai_calls:"):
            b["calls"][meter[len("ai_calls:"):]] = int(value)
        else:
            _, purpose, brand = meter.split(":", 2)
            b["by_purpose"][purpose] = b["by_purpose"].get(purpose, 0) + value
            if brand != "-":
                b["by_brand"][brand] = b["by_brand"].get(brand, 0) + value
    return {"period": period, "businesses": out, "platform_pence": sum(b["total_pence"] for b in out.values()),
            "alarm_pence": os.environ.get("AI_MONTHLY_ALARM_PENCE"), "kill_pence": os.environ.get("AI_MONTHLY_KILL_PENCE")}
