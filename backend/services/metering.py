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
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from types import SimpleNamespace
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy import text

logger = logging.getLogger(__name__)

LONDON = ZoneInfo("Europe/London")

RECEPTIONIST_METER = "receptionist_minutes"
OVERAGE_METER = "receptionist_overage_minutes"
# NS-V1 / Mike's V1 (14 Oct 2026): Aria's voice draws on the SAME pool of
# voice minutes as the receptionist. Its own meters keep the split visible;
# the allowance, the overage and the cap are judged on the total.
ARIA_VOICE_METER = "aria_voice_minutes"
ARIA_VOICE_OVERAGE_METER = "aria_voice_overage_minutes"
_SOURCES = {
    "receptionist": (RECEPTIONIST_METER, OVERAGE_METER),
    "aria_voice": (ARIA_VOICE_METER, ARIA_VOICE_OVERAGE_METER),
}
# "Told this month" markers live in the same table, so they reset with it.
_NOTIFIED_PREFIX = "notified:"
# One row per metered call ("accrued:<calls.id>"), so a call is counted once.
_ACCRUED_PREFIX = "accrued:"
# The notice outbox: "pending:<state>" is written when a limit is reached and
# cleared only when a delivery is acknowledged (Codex BH-012 review 2).
_PENDING_PREFIX = "pending:"
RECONCILE_BATCH = 500

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
    return _usage_for(session, business, period_for(now()))


def _usage_for(session, business, period: str) -> dict:
    bid = str(business.id)
    by_source = {}
    used = overage = Decimal("0")
    for source, (inside_meter, over_meter) in _SOURCES.items():
        inside = _read(session, bid, inside_meter, period)
        over = _read(session, bid, over_meter, period)
        used += inside
        overage += over
        by_source[source] = inside + over
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
        "by_source": by_source,
    }


def seconds_left_in_call(limit_seconds: int, started_at: datetime,
                         at: Optional[datetime] = None) -> int:
    """Seconds a call may still run. The limit counts from the moment the
    call STARTED, so call setup is inside the 20 minutes, not added to it
    (Codex BH-012 review 1)."""
    current = at or datetime.now(ZoneInfo("UTC"))
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=ZoneInfo("UTC"))
    elapsed = (current - started_at).total_seconds()
    return max(0, int(limit_seconds - elapsed))


def _lock(session, business_id: str, period: str) -> None:
    """Serialise allowance allocation per business and month. Without it, two
    calls ending together each read the same 'remaining' and both spend it
    (Codex BH-012 review 1: 122 included + 6 overage instead of 120 + 8).
    A transaction advisory lock is released at commit. SQLite, used by the
    tests, has no concurrent writers to lock against."""
    dialect = getattr(getattr(session, "bind", None), "dialect", None)
    if getattr(dialect, "name", "") != "postgresql":
        return
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"metering:{business_id}:{period}"},
    )


def _claim(session, business_id: str, meter: str, period: str) -> bool:
    """Atomically take a once-only marker. True if THIS caller took it."""
    row = session.execute(
        text("""
            INSERT INTO usage_meters (business_id, meter, period, value, updated_at)
            VALUES (:business_id, :meter, :period, 1, CURRENT_TIMESTAMP)
            ON CONFLICT (business_id, meter, period) DO NOTHING
            RETURNING meter
        """),
        {"business_id": business_id, "meter": meter, "period": period},
    ).fetchone()
    return row is not None


def _release(session, business_id: str, meter: str, period: str) -> None:
    session.execute(
        text("DELETE FROM usage_meters WHERE business_id = :business_id "
             "AND meter = :meter AND period = :period"),
        {"business_id": business_id, "meter": meter, "period": period},
    )


def _notices_apply(business) -> bool:
    """A plan with no minutes and no extra minutes switched on has nothing to
    be warned about (the same rule as the in-app banner)."""
    return (allowance_minutes(getattr(business, "plan_tier", None)) > 0
            or bool(getattr(business, "metered_usage_enabled", False)))


def notify_owner(business, state: str, current_usage: dict) -> bool:
    """Send the notice (email + WhatsApp when on). Returns False if nothing
    was delivered, so it stays pending and is tried again. Called only by
    the delivery worker, never inside a call or the incoming-call request."""
    try:
        from services.metering_notify import send_usage_notice
        return send_usage_notice(business, state, current_usage)
    except Exception as exc:
        logger.error("[Metering] owner notice failed for %s (%s): %s",
                     getattr(business, "id", "?"), state, exc)
        return False


def _queue_notice(session, business, state: str, period: str) -> None:
    """Record that the owner must be told — a durable pending marker, cheap
    and local. Nothing is sent here: the scheduler's worker delivers it, so a
    crash cannot lose it and the call path is never held up by email."""
    if not _notices_apply(business):
        return
    bid = str(business.id)
    if _read(session, bid, f"{_NOTIFIED_PREFIX}{state}", period) > 0:
        return
    _claim(session, bid, f"{_PENDING_PREFIX}{state}", period)


def deliver_pending_notices(session, lookup=None) -> int:
    """The worker: send this month's pending notices. A notice is marked
    sent only when a channel ACKNOWLEDGES it; otherwise it stays pending
    for the next run. Returns how many were delivered."""
    lookup = lookup or load_business
    period = period_for(now())
    rows = session.execute(
        text("SELECT business_id, meter FROM usage_meters "
             "WHERE period = :period AND meter LIKE :prefix"),
        {"period": period, "prefix": f"{_PENDING_PREFIX}%"},
    ).fetchall()
    delivered = 0
    for business_id, meter in rows:
        bid = str(business_id)
        state = meter[len(_PENDING_PREFIX):]
        business = lookup(session, bid)
        if business is None:
            continue
        if _read(session, bid, f"{_NOTIFIED_PREFIX}{state}", period) > 0:
            _release(session, bid, meter, period)
            session.commit()
            continue
        current = usage(session, business)
        if current["state"] != state:
            # No longer true — e.g. the cap was raised or extra minutes were
            # switched on before delivery (Codex BH-012 review 3). Dropped
            # without marking the month notified, so a later limit is told.
            _release(session, bid, meter, period)
            session.commit()
            continue
        if notify_owner(business, state, current) is False:
            continue  # stays pending; the next run tries again
        _claim(session, bid, f"{_NOTIFIED_PREFIX}{state}", period)
        _release(session, bid, meter, period)
        session.commit()
        delivered += 1
    return delivered


def display(u: dict) -> dict:
    """The figures as the app and Aria show them: minutes to one decimal
    place, money to the penny. One formatter, so the two cannot disagree."""
    return {
        "period": u["period"],
        "allowance_minutes": f"{u['allowance_minutes']:.0f}",
        "used_minutes": f"{u['used_minutes']:.1f}",
        "remaining_minutes": f"{u['remaining_minutes']:.1f}",
        "overage_minutes": f"{u['overage_minutes']:.1f}",
        "overage_spend_gbp": f"{u['overage_spend_gbp']:.2f}",
        "overage_rate_gbp": f"{u['overage_rate_gbp']:.2f}",
        "metered_usage_enabled": u["metered_usage_enabled"],
        "spend_cap_gbp": f"{u['spend_cap_gbp']:.2f}",
        "state": u["state"],
        "by_source": {k: f"{v:.1f}" for k, v in (u.get("by_source") or {}).items()},
    }


def admit_call(session, business) -> Tuple[bool, Optional[str]]:
    """May a NEW call be answered? A call already in progress is never cut
    off for running past the allowance — only by the 20-minute cap. A refusal
    queues a notice (e.g. a cap lowered below what is already spent), but
    nothing is sent here, and a failure recording that notice NEVER turns the
    refusal into an answer (Codex BH-012 review 2)."""
    state = usage(session, business)["state"]
    if state == STATE_OK:
        return True, None
    try:
        _queue_notice(session, business, state, period_for(now()))
        session.commit()
    except Exception as exc:
        logger.error("[Metering] could not queue notice for %s: %s",
                     getattr(business, "id", "?"), exc)
        try:
            session.rollback()
        except Exception:
            pass
    return False, state


def record_call(session, business, duration_seconds: Optional[int],
                call_id: Optional[str] = None, at: Optional[datetime] = None,
                source: str = "receptionist") -> dict:
    """Accrue a finished call from its actual duration, in the month it
    happened. Inside the allowance it counts there; past it, with metering
    on, the rest goes to overage; with metering off it still counts as used
    (the call was allowed to finish). With a `call_id` it is counted ONCE,
    however often it is recorded — so a failed accrual can be retried
    (reconcile_unmetered_calls). Commits. Queues a notice only for the
    CURRENT month: a past month's limit says nothing about today's calls."""
    period = period_for(at or now())
    bid = str(business.id)
    _lock(session, bid, period)
    if call_id and not _claim(session, bid, f"{_ACCRUED_PREFIX}{call_id}", period):
        current = _usage_for(session, business, period)
        session.commit()  # end the transaction: release the advisory lock
        return current

    inside_meter, over_meter = _SOURCES[source]
    minutes = minutes_from_seconds(duration_seconds)
    before = _usage_for(session, business, period)
    remaining = max(before["allowance_minutes"] - before["used_minutes"], Decimal("0"))
    if before["metered_usage_enabled"]:
        inside = min(minutes, remaining)
        _add(session, bid, inside_meter, period, inside)
        _add(session, bid, over_meter, period, minutes - inside)
    else:
        _add(session, bid, inside_meter, period, minutes)

    after = _usage_for(session, business, period)
    if after["state"] != STATE_OK and period == period_for(now()):
        _queue_notice(session, business, after["state"], period)
    session.commit()
    return after


def reconcile_unmetered_calls(session) -> int:
    """Meter finished receptionist calls that never reached the meter (the
    accrual at call end failed, or the process stopped). The calls table is
    the durable record; each call is counted once by its id. This month and
    last only, missing markers found in SQL, at most RECONCILE_BATCH per run
    (Codex BH-012 review 2: no full-history fetch every 15 minutes)."""
    current = now()
    first_of_month = current.astimezone(LONDON).replace(day=1, hour=0, minute=0,
                                                        second=0, microsecond=0)
    since = (first_of_month - timedelta(days=1)).replace(day=1)
    periods = {period_for(current), period_for(since)}
    rows = session.execute(
        text("""
            SELECT c.id, c.business_id, c.ended_at, c.started_at, c.duration_seconds
              FROM calls c
             WHERE c.source = 'receptionist'
               AND c.duration_seconds > 0
               AND COALESCE(c.ended_at, c.started_at) >= :since
               AND NOT EXISTS (
                     SELECT 1 FROM usage_meters m
                      WHERE m.business_id = c.business_id
                        AND m.meter = 'accrued:' || CAST(c.id AS TEXT))
             ORDER BY COALESCE(c.ended_at, c.started_at)
             LIMIT :batch
        """),
        {"since": since.astimezone(ZoneInfo("UTC")), "batch": RECONCILE_BATCH},
    ).fetchall()
    metered = 0
    for call_id, business_id, ended_at, started_at, seconds in rows:
        moment = _parse_moment(ended_at or started_at)
        if moment is None or period_for(moment) not in periods:
            continue
        business = load_business(session, str(business_id))
        if business is None:
            continue
        record_call(session, business, int(seconds), call_id=str(call_id), at=moment)
        metered += 1
    return metered


async def call_watchdog(seconds: float, closers) -> None:
    """End a call when its time is up, whatever it is doing — including
    still setting up (Codex BH-012 review 2). `closers` close the call's
    sockets; closing them ends every loop that reads them."""
    import asyncio
    await asyncio.sleep(max(0.0, seconds))
    logger.warning("[Metering] call reached its time limit; closing it")
    for close in closers:
        try:
            await close()
        except Exception:
            pass


def _parse_moment(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=ZoneInfo("UTC"))
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=ZoneInfo("UTC"))
