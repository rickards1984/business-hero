"""Usage metering — BH-012 (RC1 P0-2).

The receptionist's minutes are counted, capped and shown, so a plan's
allowance means something. Rules: ENTITLEMENT-SPEC PART E and DECISION 2;
Mike's decisions of 10 Oct 2026 (ADR 0001 D19):

  * allowances: Starter 0, Pro 120, Business 350, beta 350 minutes a month;
  * minutes counted to the second (stored 4dp, shown 1dp);
  * the month is the UK calendar month (`usage_meters.period`, YYYY-MM);
  * a call is never longer than 20 minutes; a call that exhausts the
    allowance completes, and the NEXT is refused;
  * opt-in overage at £0.45/min, on its own meter, up to an owner-set cap
    (£100 if they switch metering on without choosing);
  * the owner is told once a month per state (allowance used up; cap
    reached), by email + in-app banner (+ WhatsApp when switched on).

The meter is generic (`meter` is a name); the receptionist is metered first.
Aria voice gets its own meter in the ticket that repairs it.

`usage_meters` has UNIQUE (business_id, meter, period); every increment is a
single upsert on it, so two calls ending at once both count.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from types import SimpleNamespace
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy import text

logger = logging.getLogger(__name__)

LONDON = ZoneInfo("Europe/London")

RECEPTIONIST_METER = "receptionist_minutes"
OVERAGE_METER = "receptionist_overage_minutes"
# "Told this month" markers live in the same table, so they reset with it.
_NOTIFIED_PREFIX = "notified:"

CALL_HARD_CAP_SECONDS = 1200
OVERAGE_RATE_GBP = Decimal("0.45")
DEFAULT_SPEND_CAP_GBP = Decimal("100")
MAX_SPEND_CAP_GBP = Decimal("10000")

_ALLOWANCES = {"starter": Decimal("0"), "pro": Decimal("120"),
               "business": Decimal("350"), "beta": Decimal("350")}

STATE_OK = "ok"
STATE_ALLOWANCE = "allowance_exhausted"
STATE_CAP = "spend_cap_reached"

_FOUR_DP = Decimal("0.0001")
_TWO_DP = Decimal("0.01")


def now() -> datetime:
    """The current time, aware. A function so tests can pin the clock."""
    return datetime.now(LONDON)


def period_for(moment: datetime) -> str:
    """The UK calendar month a moment falls in, as YYYY-MM."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=ZoneInfo("UTC"))
    return moment.astimezone(LONDON).strftime("%Y-%m")


def allowance_minutes(plan_tier: Optional[str]) -> Decimal:
    """Unknown or missing tiers get nothing: an allowance is never guessed."""
    return _ALLOWANCES.get((plan_tier or "").strip().lower(), Decimal("0"))


def minutes_from_seconds(seconds: Optional[int]) -> Decimal:
    if not seconds or seconds < 0:
        return Decimal("0.0000")
    return (Decimal(int(seconds)) / Decimal(60)).quantize(_FOUR_DP, rounding=ROUND_HALF_UP)


def call_time_limit_seconds(configured: Optional[int]) -> int:
    """A business's own setting may shorten a call, never lengthen it past 20
    minutes (DECISION 2: an AI talking to a voicemail loop can burn a day's
    budget unnoticed)."""
    if configured and 0 < int(configured) < CALL_HARD_CAP_SECONDS:
        return int(configured)
    return CALL_HARD_CAP_SECONDS


def load_business(session, business_id: str) -> Optional[SimpleNamespace]:
    """Read the metering fields straight from `businesses`: the ORM model does
    not declare metered_usage_enabled or monthly_spend_cap_gbp, so reading
    them off it would always look 'off'."""
    row = session.execute(
        text("SELECT id, name, plan_tier, metered_usage_enabled, monthly_spend_cap_gbp "
             "FROM businesses WHERE id = :business_id"),
        {"business_id": business_id},
    ).fetchone()
    if row is None:
        return None
    return SimpleNamespace(id=str(row[0]), name=row[1], plan_tier=row[2],
                           metered_usage_enabled=bool(row[3]),
                           monthly_spend_cap_gbp=_dec(row[4]))


def _dec(value) -> Optional[Decimal]:
    if value is None:
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _read(session, business_id: str, meter: str, period: str) -> Decimal:
    row = session.execute(
        text("SELECT value FROM usage_meters WHERE business_id = :business_id "
             "AND meter = :meter AND period = :period"),
        {"business_id": business_id, "meter": meter, "period": period},
    ).fetchone()
    return _dec(row[0]) if row is not None else Decimal("0")


def _add(session, business_id: str, meter: str, period: str, amount: Decimal) -> None:
    """One atomic upsert on UNIQUE (business_id, meter, period)."""
    if amount <= 0:
        return
    session.execute(
        text("""
            INSERT INTO usage_meters (business_id, meter, period, value, updated_at)
            VALUES (:business_id, :meter, :period, :amount, CURRENT_TIMESTAMP)
            ON CONFLICT (business_id, meter, period)
            DO UPDATE SET value = usage_meters.value + excluded.value,
                          updated_at = CURRENT_TIMESTAMP
        """),
        {"business_id": business_id, "meter": meter, "period": period,
         "amount": amount},
    )


def _spend_cap(business) -> Decimal:
    cap = _dec(getattr(business, "monthly_spend_cap_gbp", None))
    return cap if cap is not None else DEFAULT_SPEND_CAP_GBP


def _state(used, allowance, metered, spend, cap) -> str:
    if used < allowance:
        return STATE_OK
    if metered and spend < cap:
        return STATE_OK
    return STATE_CAP if metered else STATE_ALLOWANCE


def usage(session, business) -> dict:
    period = period_for(now())
    bid = str(business.id)
    used = _read(session, bid, RECEPTIONIST_METER, period)
    overage = _read(session, bid, OVERAGE_METER, period)
    allowance = allowance_minutes(getattr(business, "plan_tier", None))
    metered = bool(getattr(business, "metered_usage_enabled", False))
    spend = (overage * OVERAGE_RATE_GBP).quantize(_TWO_DP, rounding=ROUND_HALF_UP)
    cap = _spend_cap(business)
    return {
        "period": period,
        "allowance_minutes": allowance,
        "used_minutes": used,
        "remaining_minutes": max(allowance - used, Decimal("0")),
        "overage_minutes": overage,
        "overage_spend_gbp": spend,
        "metered_usage_enabled": metered,
        "spend_cap_gbp": cap,
        "overage_rate_gbp": OVERAGE_RATE_GBP,
        "state": _state(used, allowance, metered, spend, cap),
    }


def admit_call(session, business) -> Tuple[bool, Optional[str]]:
    """May a NEW call be answered? A call already in progress is never cut
    off for running past the allowance — only by the 20-minute cap."""
    state = usage(session, business)["state"]
    return (True, None) if state == STATE_OK else (False, state)


def notify_owner(business, state: str, current_usage: dict) -> None:
    """Tell the owner (email + in-app banner, + WhatsApp when on). The banner
    is the `state` that GET /v1/usage returns; this sends the messages."""
    try:
        from services.metering_notify import send_usage_notice
        send_usage_notice(business, state, current_usage)
    except Exception as exc:  # a failed notice must never fail a call record
        logger.error("[Metering] owner notice failed for %s (%s): %s",
                     getattr(business, "id", "?"), state, exc)


def _notify_once(session, business, state: str, period: str) -> None:
    marker = f"{_NOTIFIED_PREFIX}{state}"
    if _read(session, str(business.id), marker, period) > 0:
        return
    _add(session, str(business.id), marker, period, Decimal("1"))
    notify_owner(business, state, usage(session, business))


def record_call(session, business, duration_seconds: Optional[int]) -> dict:
    """Accrue a finished call from its actual duration. Inside the allowance
    it counts there; past it, with metering on, the rest goes to overage;
    with metering off, it still counts as used (the call was allowed to
    finish). Then tell the owner if a limit has just been reached."""
    period = period_for(now())
    bid = str(business.id)
    minutes = minutes_from_seconds(duration_seconds)
    before = usage(session, business)
    allowance = before["allowance_minutes"]
    remaining = max(allowance - before["used_minutes"], Decimal("0"))

    if before["metered_usage_enabled"]:
        inside = min(minutes, remaining)
        _add(session, bid, RECEPTIONIST_METER, period, inside)
        _add(session, bid, OVERAGE_METER, period, minutes - inside)
    else:
        _add(session, bid, RECEPTIONIST_METER, period, minutes)

    after = usage(session, business)
    if after["state"] != STATE_OK:
        _notify_once(session, business, after["state"], period)
    return after
