"""PROFIT-1 — never spend more running Business Hero than comes in.

Mike, 27 Oct 2026: "a net profit for all transactions ... with the alarm and
'kill switch' ensuring we don't lose money". See docs/PROFIT-1-TICKET.md.

This month's running costs are compared with monthly recurring income:
  * costs  = every AI call in the ledger (outreach through ai_router, the rest
             through the OpenAI SDK hook below) + voice minutes in pounds +
             fixed hosting costs (PLATFORM_FIXED_COSTS_PENCE);
  * income = the plan price of every active, paying subscription (recurring,
             not payments so far this month, so a customer billed on the 28th
             never makes the 2nd look like a loss) + top-ups paid this month.
             Before launch PROFIT_TRIAL_BUDGET_PENCE stands in; with neither,
             only the absolute AI_MONTHLY_KILL_PENCE applies.
At PROFIT_ALARM_PERCENT (40) Mike is alerted once a month (email + admin
banner); at PROFIT_KILL_PERCENT (80) non-essential AI pauses. Live calls,
reply sorting, unsubscribes and the owner's own chat are essential and never
stop.
"""
import contextlib
import logging
import os
import re
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import event, text

from services.metering import ARIA_VOICE_METER, RECEPTIONIST_METER, period_for

logger = logging.getLogger(__name__)

PLAN_PRICE_PENCE = {"starter": 6900, "pro": 12900, "business": 26900}
ESSENTIAL = frozenset({"classify", "receptionist", "unsubscribe", "chat", "voice", "answer"})
PLATFORM = "platform"                          # ledger rows no business is known for
VOICE_DEFAULT_PENCE = 16                       # $0.20 a minute with Twilio folded in (PRICING-MODEL §2)
TOPUP_METER = "outreach_topup_pence"           # OUT-19 F: paid top-ups
ALERTED_METER = "profit_alerted"               # once per month per threshold
# A model the price table doesn't know is charged at this (pence per million
# tokens in, out): above every text model Business Hero uses, so never free.
UNPRICED_PENCE = (1600, 6400)


def _int_env(name: str, default: Optional[int] = None) -> Optional[int]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        logger.error("%s is not a whole number; using %s", name, default)
        return default


def alarm_percent() -> int:
    return _int_env("PROFIT_ALARM_PERCENT", 40)


def kill_percent() -> int:
    return _int_env("PROFIT_KILL_PERCENT", 80)


def _sum(session, sql: str, params: dict) -> float:
    return float(session.execute(text(sql), params).scalar() or 0)


def income(session, period: str) -> tuple:
    """(pence, basis) for the month."""
    total = 0
    for plan, in session.execute(text(
            "SELECT plan_tier FROM businesses WHERE subscription_status = 'active' AND is_active = :t"), {"t": True}):
        total += PLAN_PRICE_PENCE.get((plan or "").lower(), 0)
    total += int(_sum(session, "SELECT coalesce(sum(value), 0) FROM usage_meters WHERE period = :p "
                               "AND meter LIKE :m ESCAPE '\\'", {"p": period, "m": TOPUP_METER.replace("_", "\\_") + ":%"}))
    if total:
        return total, "subscriptions"
    trial = _int_env("PROFIT_TRIAL_BUDGET_PENCE")
    if trial:
        return trial, "trial budget"
    return 0, "none"


def costs(session, period: str) -> dict:
    ai = _sum(session, "SELECT coalesce(sum(value), 0) FROM usage_meters WHERE period = :p AND meter = 'ai_pence'",
              {"p": period})
    voice_minutes = _sum(session, "SELECT coalesce(sum(value), 0) FROM usage_meters WHERE period = :p "
                                  "AND meter IN (:r, :v)", {"p": period, "r": RECEPTIONIST_METER, "v": ARIA_VOICE_METER})
    voice = voice_minutes * _int_env("VOICE_COST_PENCE_PER_MINUTE", VOICE_DEFAULT_PENCE)
    fixed = _int_env("PLATFORM_FIXED_COSTS_PENCE", 0)
    out = {"ai_pence": int(round(ai)), "voice_pence": int(round(voice)), "fixed_pence": int(fixed)}
    out["total_pence"] = out["ai_pence"] + out["voice_pence"] + out["fixed_pence"]
    return out


def _percent(spent: int, earned: int) -> Optional[int]:
    return None if earned <= 0 else int(100 * spent // earned)


def status(session, *, moment: Optional[datetime] = None) -> dict:
    moment = moment or datetime.now(timezone.utc)
    period = period_for(moment)
    earned, basis = income(session, period)
    spent = costs(session, period)
    pct = _percent(spent["total_pence"], earned)
    out = {"period": period, "income_pence": earned, "income_basis": basis, "costs": spent, "percent": pct,
           "alarm_percent": alarm_percent(), "kill_percent": kill_percent(),
           "alarm": pct is not None and pct >= alarm_percent(), "kill": pct is not None and pct >= kill_percent(),
           "losing": _losing(session, period),
           "alerts": {"email": bool(os.environ.get("PROFIT_ALERT_FROM_ACCOUNT") and os.environ.get("PROFIT_ALERT_TO"))},
           "note": ""}
    if basis == "none":
        out["note"] = ("No income yet and no trial budget set: only the absolute AI limit (AI_MONTHLY_KILL_PENCE) "
                       "protects spend. Set PROFIT_TRIAL_BUDGET_PENCE before launch.")
    elif basis == "trial budget":
        out["note"] = "Before launch: the trial budget stands in for income."
    if not out["alerts"]["email"]:
        out["note"] = (out["note"] + " Email alerts aren't set up (PROFIT_ALERT_FROM_ACCOUNT, PROFIT_ALERT_TO).").strip()
    return out


def _losing(session, period: str) -> list:
    rate = _int_env("VOICE_COST_PENCE_PER_MINUTE", VOICE_DEFAULT_PENCE)
    rows = []
    for bid, name, plan, sub, active in session.execute(text(
            "SELECT id, name, plan_tier, subscription_status, is_active FROM businesses")):
        paying = sub == "active" and bool(active)
        price = PLAN_PRICE_PENCE.get((plan or "").lower(), 0) if paying else 0
        ai = _sum(session, "SELECT coalesce(sum(value), 0) FROM usage_meters WHERE business_id = :b AND period = :p "
                           "AND meter = 'ai_pence'", {"b": str(bid), "p": period})
        voice = _sum(session, "SELECT coalesce(sum(value), 0) FROM usage_meters WHERE business_id = :b AND period = :p "
                              "AND meter IN (:r, :v)", {"b": str(bid), "p": period, "r": RECEPTIONIST_METER,
                                                         "v": ARIA_VOICE_METER}) * rate
        cost = int(round(ai + voice))
        if cost > price:
            rows.append({"business_id": str(bid), "name": name, "pays_pence": price, "costs_pence": cost,
                         "paying": paying})
    return rows


def allowed(session, *, purpose: Optional[str], moment: Optional[datetime] = None) -> bool:
    """False for non-essential AI once this month's costs reach the kill
    threshold of income. Essential work is never stopped here."""
    if purpose in ESSENTIAL:
        return True
    period = period_for(moment or datetime.now(timezone.utc))
    earned, _ = income(session, period)
    pct = _percent(costs(session, period)["total_pence"], earned)
    return pct is None or pct < kill_percent()


# ---------------------------------------------------------------- alerts ---

def send_alert(subject: str, body: str) -> None:
    """Email Mike from the mailbox he named. Never raises."""
    account_id, to = os.environ.get("PROFIT_ALERT_FROM_ACCOUNT"), os.environ.get("PROFIT_ALERT_TO")
    if not (account_id and to):
        logger.error("Profit guard: %s (email alerts not set up)", subject)
        return
    try:
        from sqlmodel import Session
        from main import send_email_oauth
        from models import EmailAccount
        with Session(_engine()) as s:
            account = s.get(EmailAccount, account_id)
            if account is None:
                raise LookupError("PROFIT_ALERT_FROM_ACCOUNT is not a connected mailbox")
            send_email_oauth(s, account, to, subject, body)
    except Exception:
        logger.exception("Profit guard: could not email the alert %r", subject)


def _fire(session) -> None:
    for subject, body in session.info.pop("profit_alerts", []):
        send_alert(subject, body)


def _drop(session, *_args) -> None:
    session.info.pop("profit_alerts", None)


def check_after_record(session, moment: datetime) -> None:
    """Called by ai_costs.record in the recording transaction: a threshold
    crossed for the first time this month is marked in that transaction and
    alerted after it commits (dropped if it rolls back)."""
    period = period_for(moment)
    earned, basis = income(session, period)
    spent = costs(session, period)
    pct = _percent(spent["total_pence"], earned)
    if pct is None:
        return
    for name, threshold in (("alarm", alarm_percent()), ("kill", kill_percent())):
        if pct < threshold:
            continue
        meter = f"{ALERTED_METER}:{name}"
        if _sum(session, "SELECT coalesce(sum(value), 0) FROM usage_meters WHERE business_id = :b AND meter = :m "
                         "AND period = :p", {"b": PLATFORM, "m": meter, "p": period}):
            continue
        session.execute(text("INSERT INTO usage_meters (business_id, meter, period, value, updated_at) "
                             "VALUES (:b, :m, :p, 1, :at)"), {"b": PLATFORM, "m": meter, "p": period, "at": moment})
        what = ("non-essential AI is now paused" if name == "kill"
                else "Business Hero's running costs are getting close to its income")
        subject = f"Business Hero: costs have reached {threshold}% of this month's income — {what}"
        body = (f"This month ({period}) costs are £{spent['total_pence'] / 100:.2f} against income of "
                f"£{earned / 100:.2f} ({basis}): {pct}%.\n\nAI £{spent['ai_pence'] / 100:.2f} · voice "
                f"£{spent['voice_pence'] / 100:.2f} · fixed £{spent['fixed_pence'] / 100:.2f}.\n\n"
                "See the admin panel for which businesses cost more than they pay.")
        if not session.info.get("profit_hooks"):
            event.listen(session, "after_commit", _fire)
            event.listen(session, "after_rollback", _drop)
            event.listen(session, "after_soft_rollback", _drop)
            session.info["profit_hooks"] = True
        session.info.setdefault("profit_alerts", []).append((subject, body))


# ------------------------------------------------- every AI call recorded ---

_attribution: ContextVar = ContextVar("profit_attribution", default=None)


@contextlib.contextmanager
def attributed(business_id, purpose: str):
    """AI calls inside the block are recorded for this business and purpose."""
    token = _attribution.set((str(business_id) if business_id else PLATFORM, purpose))
    try:
        yield
    finally:
        _attribution.reset(token)


def label(purpose: str, business_id=None) -> None:
    """Attribute the rest of this request or task's AI calls (a function-wide
    attributed(); the context is the caller's own copy, so it ends with it)."""
    _attribution.set((str(business_id) if business_id else PLATFORM, purpose))


def permits(purpose: str) -> bool:
    """allowed(), in its own short session, for code without one. A failure
    holds non-essential AI (fail closed)."""
    try:
        from sqlmodel import Session
        with Session(_engine()) as s:
            return allowed(s, purpose=purpose)
    except Exception:
        logger.exception("Profit guard unavailable: %s held (fail closed)", purpose)
        return purpose in ESSENTIAL


def _engine():
    from db import engine
    return engine


def _tokens(usage) -> tuple:
    def first(*names):
        for n in names:
            v = getattr(usage, n, None)
            if isinstance(v, int):
                return v
        return None
    return first("prompt_tokens", "input_tokens"), first("completion_tokens", "output_tokens")


def _record_response(result, kwargs) -> None:
    from services import ai_costs
    if ai_costs._collecting.get() is not None:
        return   # inside ai_router: the router records it (never twice)
    from sqlmodel import Session
    business_id, purpose = _attribution.get() or (PLATFORM, "unattributed")
    model = str(getattr(result, "model", None) or kwargs.get("model") or "unknown")
    tokens_in, tokens_out = _tokens(getattr(result, "usage", None))
    estimated = tokens_in is None or tokens_out is None
    tokens_in, tokens_out = tokens_in or 0, tokens_out or 0
    pence, priced = None, False
    for name in (model, re.sub(r"-\d{4}-\d{2}-\d{2}$", "", model)):
        try:
            pence = ai_costs.cost("openai", name, tokens_in, tokens_out)
            model, priced = name, True
            break
        except ai_costs.Unpriced:
            continue
    if not priced:
        pence = (tokens_in * UNPRICED_PENCE[0] + tokens_out * UNPRICED_PENCE[1]) / 1_000_000
        estimated = True
    with Session(_engine()) as s:
        ai_costs.record(s, business_id, purpose=purpose, provider="openai", model=model, input_tokens=tokens_in,
                        output_tokens=tokens_out, pence=max(pence, 0.000001), estimated=estimated)
        s.commit()


def wrap_create(fn):
    """The SDK's create, recording each call's cost; recording never breaks the call."""
    import functools
    import inspect

    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def awrapped(*args, **kwargs):
            result = await fn(*args, **kwargs)
            try:
                _record_response(result, kwargs)
            except Exception:
                logger.exception("Could not record an AI call's cost")
            return result
        awrapped._profit_wrapped = True
        return awrapped

    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        result = fn(*args, **kwargs)
        try:
            _record_response(result, kwargs)
        except Exception:
            logger.exception("Could not record an AI call's cost")
        return result
    wrapped._profit_wrapped = True
    return wrapped


def install_openai_hook() -> None:
    """Wrap the OpenAI SDK's text-call entry points once, at startup."""
    try:
        from openai.resources.chat import completions
        from openai.resources import responses
    except ImportError:
        return
    for owner, attr in ((completions.Completions, "create"), (completions.AsyncCompletions, "create"),
                        (responses.Responses, "create"), (responses.AsyncResponses, "create")):
        current = getattr(owner, attr, None)
        if current is not None and not getattr(current, "_profit_wrapped", False):
            setattr(owner, attr, wrap_create(current))
