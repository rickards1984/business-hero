"""BRIEF-1: Aria's weekly and monthly WhatsApp briefings (Mike, 5-6 Nov 2026).

The daily pulse was mostly zeros, every weekday, and paid for an AI write-up it
threw away. It is replaced by:

- WEEKLY, Fridays from 16:00 (the business's time zone), covering Monday to
  Friday: calls (answered by Aria, missed), emails, money in and out, invoices,
  quotes.
- MONTHLY, the 1st from 08:00, covering the month just ended: the result
  (profit or loss, against the month before), money in, money out, the biggest
  costs, what is owed.

Both are built from data Business Hero already holds: no AI call, no Xero call
(speed and cost). The monthly figures come from the same ledger as the
accountancy pack (accountancy_pack._ledger), so the two always agree.

Each is sent through its own approved WhatsApp template. Until the template's
Content SID is configured, nothing is attempted and nothing is logged as sent:
an unsolicited WhatsApp without a template is refused by WhatsApp.
"""
import calendar
import logging
import os
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)

WEEKLY = "weekly_summary"
MONTHLY = "monthly_financial"
WEEKLY_SID_ENV = "TWILIO_WEEKLY_SUMMARY_CONTENT_SID"
MONTHLY_SID_ENV = "TWILIO_MONTHLY_FINANCIAL_CONTENT_SID"
WEEKLY_AT = time(16, 0)        # Fridays (Mike, 6 Nov)
MONTHLY_AT = time(8, 0)        # the 1st (Mike, 6 Nov)
ANSWERED = ("handled", "appointment_booked", "transferred")   # explicit outcomes only
MISSED = ("missed", "error")
# Not owed (Codex BRIEF-1 review 1: partly paid and "overdue" invoices ARE owed);
# statuses arrive in either case (app: "paid"; Xero: "PAID").
NOT_OWED = {"paid", "cancelled", "voided", "deleted", "draft"}
TOP_COSTS = 3
SEND_ATTEMPTS = 3          # per briefing per day: retry a failed send, never hammer Twilio


def configured(kind: str) -> bool:
    return bool(os.environ.get(WEEKLY_SID_ENV if kind == WEEKLY else MONTHLY_SID_ENV, "").strip())


# ------------------------------------------------------------------ timing ---

def weekly_due(now_local: datetime) -> Optional[tuple]:
    """(Monday, Friday) of this week from Friday 16:00, else None."""
    if now_local.weekday() != 4 or now_local.time() < WEEKLY_AT:
        return None
    friday = now_local.date()
    return friday - timedelta(days=4), friday


def monthly_due(now_local: datetime) -> Optional[tuple]:
    """(first, last) of the month just ended from 08:00 on the 1st, else None."""
    if now_local.day != 1 or now_local.time() < MONTHLY_AT:
        return None
    last = now_local.date() - timedelta(days=1)
    return last.replace(day=1), last


# ----------------------------------------------------------------- wording ---

def money(value) -> str:
    v = Decimal(str(value or 0)).quantize(Decimal("1"))
    return f"£{abs(v):,}" if v >= 0 else f"-£{abs(v):,}"


def _span(start: date, end: date) -> str:
    """'Mon 2 – Fri 6 Nov' (both months named when they differ)."""
    left = f"{start:%a} {start.day}" + ("" if start.month == end.month else f" {start:%b}")
    return f"{left} – {end:%a} {end.day} {end:%b}"


def _plural(n: int, one: str, many: Optional[str] = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


# -------------------------------------------------------------------- data ---

def _range(start: date, end: date, tz: str = "Europe/London") -> dict:
    """Inclusive local dates as zone-aware instants (Codex BRIEF-1 review 1:
    naive bounds against timestamptz were read in the database's zone, an hour
    out in British Summer Time)."""
    from zoneinfo import ZoneInfo
    zone = ZoneInfo(tz or "Europe/London")
    return {"s": datetime.combine(start, time.min, zone), "e": datetime.combine(end + timedelta(days=1), time.min, zone)}


def _calls(session, bid: str, start: date, end: date, tz: str = "Europe/London") -> str:
    rows = session.execute(text(
        "SELECT source, outcome FROM calls WHERE business_id = :b AND started_at >= :s AND started_at < :e"),
        {"b": bid, **_range(start, end, tz)}).fetchall()
    if not rows:
        return "No calls"
    aria = [r for r in rows if r[0] == "receptionist"]
    answered = sum(1 for r in aria if r[1] in ANSWERED)
    booked = sum(1 for r in aria if r[1] == "appointment_booked")
    missed = sum(1 for r in rows if r[1] in MISSED)
    parts = [_plural(len(rows), "call")]
    if aria:
        parts.append(f"{answered} answered by Aria" + (f" ({_plural(booked, 'booking')})" if booked else ""))
    parts.append(f"{missed} missed")
    return ", ".join(parts)


def _emails(session, bid: str, start: date, end: date, tz: str = "Europe/London") -> str:
    rows = session.execute(text(
        "SELECT ai_category FROM email_messages WHERE business_id = :b AND received_at >= :s AND received_at < :e"),
        {"b": bid, **_range(start, end, tz)}).fetchall()
    if not rows:
        return "None received"
    action = sum(1 for r in rows if r[0] == "Action Required")
    return f"{len(rows)} received, {action} need{'s' if action == 1 else ''} action"


def _ledger(session, bid: str, start: date, end: date) -> dict:
    from services import accountancy_pack as pack
    return pack.ledger_pnl(pack._ledger(session, bid, start, end))


def _week_money(session, bid: str, start: date, end: date) -> str:
    p = _ledger(session, bid, start, end)
    if not p["total_income"] and not p["total_expense"]:
        return "No transactions recorded yet"
    net = p["net"]
    return (f"{money(p['total_income'])} in, {money(p['total_expense'])} out, "
            + (f"{money(net)} ahead" if net >= 0 else f"{money(-net)} behind"))


def _owed(session, bid: str, today: date) -> tuple:
    """(count, total, overdue count, overdue total) still owed. The balance is
    what's left after the larger recorded payment: Xero keeps amount_due and
    amount_paid, a manual part-payment only paid_amount (Codex BRIEF-1 review 1)."""
    rows = session.execute(text(
        "SELECT status, amount, amount_due, amount_paid, paid_amount, due_date FROM invoices "
        "WHERE business_id = :b AND (archived IS NULL OR archived = :no)"), {"b": bid, "no": False}).fetchall()

    def dec(v):
        return Decimal(str(v)) if v is not None else None

    def day(v):
        return v if isinstance(v, date) else date.fromisoformat(str(v)[:10]) if v else None
    owed = []
    for status, amount, due, paid_x, paid_m, due_date in rows:
        if str(status or "").lower() in NOT_OWED:
            continue
        amount = dec(amount) or Decimal(0)
        paid = max(dec(paid_x) or Decimal(0), dec(paid_m) or Decimal(0))
        balance = min(x for x in (dec(due), amount - paid) if x is not None)
        if balance > 0:
            late = str(status or "").lower() == "overdue" or bool(day(due_date) and day(due_date) < today)
            owed.append((balance, late))
    late = [b for b, is_late in owed if is_late]
    return len(owed), sum((b for b, _ in owed), Decimal(0)), len(late), sum(late, Decimal(0))


def _invoices(session, bid: str, today: date) -> str:
    n, total, late, late_total = _owed(session, bid, today)
    if not n:
        return "None unpaid"
    return f"{n} unpaid ({money(total)}), {late} overdue" + (f" ({money(late_total)})" if late else "")


def _quotes(session, bid: str, start: date, end: date, tz: str = "Europe/London") -> str:
    rng = _range(start, end, tz)
    sent = session.execute(text(
        "SELECT count(*), coalesce(sum(total), 0) FROM quotes WHERE business_id = :b AND sent_at >= :s AND sent_at < :e"),
        {"b": bid, **rng}).one()
    won = session.execute(text(
        "SELECT count(*), coalesce(sum(total), 0) FROM quotes WHERE business_id = :b "
        "AND accepted_at >= :s AND accepted_at < :e"), {"b": bid, **rng}).one()
    if not sent[0] and not won[0]:
        return "None sent this week"
    parts = []
    if sent[0]:
        parts.append(f"{sent[0]} sent ({money(sent[1])})")
    if won[0]:
        parts.append(f"{won[0]} accepted ({money(won[1])})")
    return ", ".join(parts)


def _greeting(owner_name: str, business_name: str) -> str:
    first = (owner_name or "").strip().split(" ")[0]
    return first or (business_name or "there")


def weekly_variables(session, bid: str, owner_name: str, business_name: str, start: date, end: date,
                     tz: str = "Europe/London") -> dict:
    return {"1": _greeting(owner_name, business_name), "2": _span(start, end),
            "3": _calls(session, bid, start, end, tz), "4": _emails(session, bid, start, end, tz),
            "5": _week_money(session, bid, start, end), "6": _invoices(session, bid, end),
            "7": _quotes(session, bid, start, end, tz)}


def monthly_variables(session, bid: str, owner_name: str, business_name: str, start: date, end: date,
                      tz: str = "Europe/London") -> dict:
    this = _ledger(session, bid, start, end)
    prev_end = start - timedelta(days=1)
    before = _ledger(session, bid, prev_end.replace(day=1), prev_end)
    net = this["net"]
    result = f"Profit of {money(net)}" if net >= 0 else f"Loss of {money(-net)}"
    if before["total_income"] or before["total_expense"]:
        change = net - before["net"]
        if change:
            result += f" ({'up' if change > 0 else 'down'} {money(abs(change))} on {calendar.month_name[prev_end.month]})"
        else:
            result += f" (the same as {calendar.month_name[prev_end.month]})"
    costs = sorted(this["expense"], key=lambda kv: kv[1], reverse=True)[:TOP_COSTS]
    n, total, late, late_total = _owed(session, bid, end + timedelta(days=1))
    return {"1": _greeting(owner_name, business_name), "2": calendar.month_name[start.month],
            "3": result if (this["total_income"] or this["total_expense"]) else "No transactions recorded for the month",
            "4": money(this["total_income"]), "5": money(this["total_expense"]),
            "6": ", ".join(f"{name} {money(v)}" for name, v in costs) or "None recorded",
            "7": (f"{money(total)} unpaid, {money(late_total)} overdue" if n else "Nothing outstanding")}


# -------------------------------------------------------------------- send ---

SCHEDULED = "scheduled_briefing"   # related_entity_type of a scheduled send; a test send is "test_briefing"
CLAIM_KEY = "whatsapp_briefings"
IN_FLIGHT = timedelta(minutes=5)   # a send that crashed mid-way may be retried after this


def _locked_doc(session, bid: str) -> dict:
    """The business's settings document, its row locked for this transaction
    (created first if missing: settings_row, OUT-22)."""
    import json
    from services import settings_row
    settings_row.ensure(session, bid)
    pg = session.get_bind().dialect.name == "postgresql"
    if not pg:   # SQLite: take the writer lock before reading
        session.execute(text("UPDATE business_settings SET business_id = business_id WHERE business_id = :b"), {"b": bid})
    raw = session.execute(text("SELECT settings FROM business_settings WHERE business_id = :b"
                               + (" FOR UPDATE" if pg else "")), {"b": bid}).scalar()
    return dict(raw if isinstance(raw, dict) else json.loads(raw or "{}"))


def _save_doc(session, bid: str, doc: dict) -> None:
    import json
    cast = "CAST(:s AS jsonb)" if session.get_bind().dialect.name == "postgresql" else ":s"
    session.execute(text(f"UPDATE business_settings SET settings = {cast} WHERE business_id = :b"),
                    {"s": json.dumps(doc), "b": bid})


def _claim(session, bid: str, kind: str, day: date, moment: datetime) -> Optional[str]:
    """Under the settings lock (Codex BRIEF-1 review 2): may this briefing be
    sent now? Not if delivered today, not while another attempt is in flight,
    not after SEND_ATTEMPTS. A granted claim is recorded before the send, so
    two schedulers can never both send, and nothing depends on the message log."""
    doc = _locked_doc(session, bid)
    claims = dict(doc.get(CLAIM_KEY) or {})
    c = dict(claims.get(kind) or {})
    if c.get("day") != day.isoformat():
        c = {"day": day.isoformat(), "attempts": 0, "delivered": False}
    busy = c.get("busy_until")
    if c["delivered"] or c["attempts"] >= SEND_ATTEMPTS or (busy and datetime.fromisoformat(busy) > moment):
        session.rollback()
        return None
    import uuid
    token = uuid.uuid4().hex   # whose attempt this is (Codex BRIEF-1 review 3)
    c["attempts"] += 1
    c["busy_until"] = (moment + IN_FLIGHT).isoformat()
    c["token"] = token
    claims[kind] = c
    doc[CLAIM_KEY] = claims
    _save_doc(session, bid, doc)
    session.commit()
    return token


def _settle(session, bid: str, kind: str, day: date, delivered: bool, token: str) -> None:
    """A delivery always counts; only the attempt that holds the claim may
    release it (an expired attempt finishing late never frees its successor's)."""
    doc = _locked_doc(session, bid)
    claims = dict(doc.get(CLAIM_KEY) or {})
    c = dict(claims.get(kind) or {})
    if c.get("day") == day.isoformat():
        c["delivered"] = bool(c.get("delivered")) or delivered
        if c.get("token") == token:
            c.pop("busy_until", None)
            c.pop("token", None)
        claims[kind] = c
        doc[CLAIM_KEY] = claims
        _save_doc(session, bid, doc)
    session.commit()


async def run_for(config: dict, now_local: datetime, *, session_factory, send) -> list:
    """Send whichever briefing is due for one business; returns what was sent.
    `send` is whatsapp_service.send_whatsapp_message; sessions come from the
    caller (one short read per briefing, never held across the send)."""
    import json
    if not (config.get("weekly_briefing_enabled") or config.get("daily_pulse_enabled")):
        return []   # either switch, so nobody who had the daily pulse silently loses Aria (BRIEF-1)
    bid = str(config["business_id"])
    sent = []
    for kind, due, build in ((WEEKLY, weekly_due(now_local), weekly_variables),
                             (MONTHLY, monthly_due(now_local), monthly_variables)):
        if not due:
            continue
        if not configured(kind):
            logger.info("[Briefings] %s for %s not sent: its WhatsApp template isn't configured yet", kind, bid)
            continue
        today = now_local.date()
        with session_factory() as session:
            token = _claim(session, bid, kind, today, now_local)
            if not token:
                continue
            variables = build(session, bid, config.get("owner_name") or "", config.get("business_name") or "",
                              *due, tz=config.get("timezone") or "Europe/London")
            session.rollback()
        sid = None
        try:
            sid = await send(to_number=config["phone_number"], body=json.dumps(variables), business_id=bid,
                             message_type=kind, related_entity_type=SCHEDULED)
        finally:
            with session_factory() as session:
                _settle(session, bid, kind, today, bool(sid), token)
        if sid:
            sent.append(kind)
        else:
            logger.warning("[Briefings] %s for %s not accepted by WhatsApp; it will be retried", kind, bid)
    return sent


async def send_test(session, bid: str, kind: str, today: date, *, send, tz: str = "Europe/London") -> dict:
    """The owner's "Send test" buttons: this week so far (Monday to today) or
    last month, through the real template. Refused, not faked, without it."""
    import json
    row = session.execute(text(
        "SELECT wc.phone_number, wc.owner_name, b.name FROM whatsapp_configs wc "
        "LEFT JOIN businesses b ON b.id = wc.business_id WHERE wc.business_id = :b"), {"b": bid}).first()
    if not row or not row[0]:
        return {"sent": False, "detail": "WhatsApp isn't set up for this business yet."}
    if not configured(kind):
        return {"sent": False, "detail": "This briefing's WhatsApp template isn't approved and configured yet."}
    if kind == WEEKLY:
        start, end = today - timedelta(days=today.weekday()), today
        variables = weekly_variables(session, bid, row[1] or "", row[2] or "", start, end, tz)
    else:
        last = today.replace(day=1) - timedelta(days=1)
        variables = monthly_variables(session, bid, row[1] or "", row[2] or "", last.replace(day=1), last)
    session.rollback()
    sid = await send(to_number=row[0], body=json.dumps(variables), business_id=bid, message_type=kind,
                     related_entity_type="test_briefing")
    return {"sent": bool(sid), "message_sid": sid} if sid else {"sent": False, "detail": "WhatsApp didn't accept it; try again shortly."}
