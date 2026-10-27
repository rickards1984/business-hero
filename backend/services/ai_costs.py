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
from provider list prices at about £1 = $1.27, checked on 25 Oct 2026 against
OpenAI's and xAI's pricing pages (Anthropic's are still estimates). A model
priced higher above a context size (xAI above 200k tokens) adds
[threshold, input_above, output_above]. AI_PRICES_JSON ({"provider/model":
[in, out, per_tool_call(, threshold, in_above, out_above)]}) overrides them
without a deploy. A configuration with any invalid entry is ignored as a
whole. A model with no price is refused before any spend (`require_priced`).
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
    # OpenAI (developers.openai.com/api/docs/pricing). Web search $10/1k calls
    # (reasoning models also pay search content at the model's input rate),
    # $25/1k for non-reasoning models.
    # GPT-6.1 Sol and GPT-6 Luna: 2× input and 1.5× output above 272k input tokens.
    "openai/gpt-6.1-sol": (157, 787, 1, 272_000, 314, 1181),
    "openai/gpt-6-luna": (8, 39, 1, 272_000, 16, 59),
    "openai/gpt-4.1": (157, 630, 2),
    "openai/gpt-4o": (197, 787, 2),
    "openai/gpt-4o-mini": (12, 47, 2),
    # xAI (docs.x.ai/developers/pricing): doubles above 200k tokens; web search $5/1k.
    "xai/grok-4.20-0309-reasoning": (98, 197, 0.4, 200_000, 197, 394),
    "xai/grok-4.20-0309-non-reasoning": (98, 197, 0.4, 200_000, 197, 394),
    "xai/grok-4.7": (157, 472, 0.4, 200_000, 315, 945),
    # Anthropic: an estimate, to be checked against its pricing page.
    "anthropic/claude-sonnet-4-5": (240, 1190, 1),
}
LEDGER_LOCK = 0x4F555431   # one advisory lock serialises ledger writes platform-wide (PostgreSQL)

_collecting: ContextVar[Optional[list]] = ContextVar("ai_costs_collecting", default=None)


class Unpriced(Exception):
    """A model with no known price: refused before any spend."""


def _valid(value) -> Optional[tuple]:
    if not isinstance(value, (list, tuple)) or len(value) not in (3, 6):
        return None
    try:
        out = tuple(float(v) for v in value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not all(math.isfinite(v) and v >= 0 for v in out):
        return None
    if len(out) == 6 and (out[3] <= 0 or out[4] < out[0] or out[5] < out[1]):
        return None      # a higher tier must start somewhere and never be cheaper (Codex OUT-19 H review 2)
    return out


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


def _entry(provider: str, model: str) -> tuple:
    found = _prices().get(f"{provider}/{model}")
    if found is None:
        raise Unpriced(f"No price is set for {provider}/{model}")
    return tuple(found)


def price(provider: str, model: str) -> tuple:
    """(input, output, per tool call) at the ordinary rate."""
    return _entry(provider, model)[:3]


def price_max(provider: str, model: str) -> tuple:
    """(input, output, per tool call) at the model's highest rate."""
    e = _entry(provider, model)
    return (max(e[0], e[4]), max(e[1], e[5]), e[2]) if len(e) == 6 else e[:3]


def require_priced(provider: str, model: str) -> None:
    """Call before spending: an unpriced model is never used."""
    price(provider, model)


def cost(provider: str, model: str, input_tokens: int = 0, output_tokens: int = 0, tool_calls: int = 0) -> float:
    e = _entry(provider, model)
    p_in, p_out, p_tool = (e[4], e[5], e[2]) if len(e) == 6 and input_tokens >= e[3] else e[:3]
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


def _fire_alarms(session) -> None:
    for period, total, alarm in session.info.pop("ai_alarms", []):
        logger.error("AI spend alarm: the platform's AI spend for %s has reached %.0fp (alarm %sp)", period, total, alarm)


def _drop_alarms(session, *_args) -> None:
    session.info.pop("ai_alarms", None)


def _alarm_after_commit(session, period: str, total: float, alarm: str) -> None:
    """Pending alarms belong to the transaction: raised after its commit,
    discarded if it rolls back (Codex OUT-19 review 2)."""
    if not session.info.get("ai_alarm_hooks"):
        event.listen(session, "after_commit", _fire_alarms)
        event.listen(session, "after_rollback", _drop_alarms)
        event.listen(session, "after_soft_rollback", _drop_alarms)
        session.info["ai_alarm_hooks"] = True
    session.info.setdefault("ai_alarms", []).append((period, total, alarm))


def record(session, business_id, *, purpose: str, provider: str, model: str, brand_id=None,
           input_tokens: int = 0, output_tokens: int = 0, tool_calls: int = 0,
           pence: Optional[float] = None, estimated: bool = False, moment: Optional[datetime] = None) -> float:
    """Add one call's cost to the ledger in the caller's transaction (no commit).
    The platform ledger lock is taken after any business lock the caller holds
    and is followed only by this function's own meter-row writes, so no
    business lock is ever requested while holding it."""
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
    # PROFIT-1: costs against income, alerted once a month per threshold. In a
    # savepoint, so a failure here never loses the cost just recorded.
    # (A connection-level savepoint: a session-level one would fire the
    # session's after_commit hooks, raising alarms before the real commit.)
    try:
        from services import profit_guard
        with session.connection().begin_nested():
            profit_guard.check_after_record(session, moment)
    except Exception:
        logger.exception("Profit guard check failed after recording an AI cost")
    return amount


def allowed(session, *, moment: Optional[datetime] = None, purpose: Optional[str] = None) -> bool:
    """False once the platform's recorded AI spend this month reaches
    AI_MONTHLY_KILL_PENCE, or (PROFIT-1) once this month's running costs reach
    the kill threshold of income, for non-essential purposes. A purpose not
    given counts as non-essential (fail closed)."""
    moment = moment or datetime.now(timezone.utc)
    kill = os.environ.get("AI_MONTHLY_KILL_PENCE")
    if kill and platform_total(session, period_for(moment)) >= float(kill):
        return False
    from services import profit_guard
    try:
        with session.connection().begin_nested():
            return profit_guard.allowed(session, purpose=purpose, moment=moment)
    except Exception:
        logger.exception("Profit guard unavailable: non-essential AI held (fail closed)")
        return purpose in profit_guard.ESSENTIAL


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


def usage_tokens(usage) -> Optional[tuple]:
    """(input, output) tokens a provider reported, or None when either is missing."""
    tokens_in = getattr(usage, "prompt_tokens", None)
    tokens_in = getattr(usage, "input_tokens", None) if tokens_in is None else tokens_in
    tokens_out = getattr(usage, "completion_tokens", None)
    tokens_out = getattr(usage, "output_tokens", None) if tokens_out is None else tokens_out
    if not isinstance(tokens_in, int) or not isinstance(tokens_out, int):
        return None
    return tokens_in, tokens_out


def note(provider: str, model: str, usage, *, fallback: tuple, estimated: bool = False, tool_calls: int = 0) -> None:
    """Called by a model adapter after every attempt; kept only inside collect().
    `fallback` is the call's conservative (input, output) maximum, used — and
    marked estimated — whenever the provider did not report usage (Codex
    OUT-19 review 2: unknown usage is never recorded as free)."""
    spent = _collecting.get()
    if spent is None:
        return
    reported = None if estimated else usage_tokens(usage)
    tokens = reported or fallback
    spent.append({"provider": provider, "model": model, "estimated": reported is None, "tool_calls": tool_calls,
                  "input_tokens": int(tokens[0]), "output_tokens": int(tokens[1])})


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
