"""Aria's standing permissions — AUTO-1: chasing overdue invoices on autopilot.

docs/AUTO-1-TICKET.md; Mike's decisions of 19 Oct 2026. North Star P4:
autonomy is earned one action type at a time, so this is OFF until the
owner switches it on, and bounded by rules and limits when it is on.

A chase on autopilot is an NS-B10 action that the system approves: it goes
through `aria_actions.propose()` then `approve(user_id=None)`. So it has the
same guarantees as a tapped card — exactly the stored template is sent, once,
recorded in `email_outbox`, the invoice's stage moves forward — and the audit
trail shows it was a standing permission (`payload.automation`, no approver).
Stage 4 is never sent automatically: it is proposed as a card for a tap.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import text

from services import aria_actions
from services.home_summary import _BALANCE, _NOT_OWED, uk_today

logger = logging.getLogger(__name__)
LONDON = ZoneInfo("Europe/London")
KIND = "invoice_chasing"

# Mike's defaults, 19 Oct 2026.
CHASE_DEFAULTS = {
    "enabled": False,
    "first_after_days": 7,     # stage 1 once this many days overdue
    "every_days": 7,           # then the next stage after this many days
    "max_auto_stage": 3,       # stages above this are proposed as cards
    "start_hour": 9,           # UK, inclusive
    "end_hour": 17,            # UK, exclusive
    "weekdays_only": True,
    "customer_gap_days": 7,    # at most one chase per customer per this many days
    "daily_cap": 20,
    "paused_customers": [],    # email addresses, any case
}

# Settings can reach business_settings by more than one route (the generic
# PUT /v1/business/settings replaces the whole document), so every value is
# clamped HERE, wherever it came from.
_BOUNDS = {
    "first_after_days": (1, 90), "every_days": (3, 60), "max_auto_stage": (1, 3),
    "start_hour": (0, 23), "end_hour": (1, 24), "customer_gap_days": (1, 30),
    "daily_cap": (1, 50),
}


def now() -> datetime:
    return datetime.now(timezone.utc)


def chase_settings(raw: Optional[dict]) -> dict:
    """The defaults, overridden by whatever was saved — clamped and cleaned."""
    merged = dict(CHASE_DEFAULTS)
    for key, value in (raw or {}).items():
        if key in CHASE_DEFAULTS:
            merged[key] = value
    merged["enabled"] = merged["enabled"] is True
    merged["weekdays_only"] = merged["weekdays_only"] is not False
    for key, (low, high) in _BOUNDS.items():
        try:
            value = int(merged[key])
        except (TypeError, ValueError):
            value = CHASE_DEFAULTS[key]
        merged[key] = min(max(value, low), high)
    if merged["end_hour"] <= merged["start_hour"]:
        merged["start_hour"], merged["end_hour"] = CHASE_DEFAULTS["start_hour"], CHASE_DEFAULTS["end_hour"]
    paused = merged.get("paused_customers") or []
    merged["paused_customers"] = sorted({str(p).strip().lower() for p in paused
                                         if isinstance(p, str) and p.strip()})
    return merged


def _in_window(moment: datetime, s: dict) -> bool:
    local = moment.astimezone(LONDON)
    if s["weekdays_only"] and local.weekday() >= 5:
        return False
    return s["start_hour"] <= local.hour < s["end_hour"]


def _parse(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _loads(value):
    return value if isinstance(value, dict) else json.loads(value or "{}")


_IN_FLIGHT = ("proposed", "executing", "done")


def _attempts(session, business, since: datetime):
    """Every chase attempt for this business since `since`, from the action
    record itself (not only invoices.last_chased_at, which a failed
    bookkeeping step may not have moved — Codex AUTO-1 review 1):
    (id, customer, status, created_at, automatic_send, approved_by)."""
    rows = session.execute(text(
        "SELECT id, payload, status, created_at, approved_by FROM aria_actions "
        "WHERE business_id = :b AND action_type = 'send_invoice_chase' AND created_at >= :since"),
        {"b": str(business.id), "since": since}).fetchall()
    out = []
    for aid, payload, status, created_at, approved_by in rows:
        p = _loads(payload)
        out.append((str(aid), str(p.get("to") or "").strip().lower(), status,
                    _parse(created_at), p.get("automation") == KIND, approved_by))
    return out


def _unresolved_customers(session, business) -> set:
    """Customers with a chase whose outcome is unknown (left `executing`):
    never chased automatically again until the owner has looked."""
    rows = session.execute(text(
        "SELECT payload FROM aria_actions WHERE business_id = :b "
        "AND action_type = 'send_invoice_chase' AND status = 'executing'"),
        {"b": str(business.id)}).fetchall()
    return {str(_loads(p).get("to") or "").strip().lower() for (p,) in rows}


def _day_start(moment: datetime) -> datetime:
    return datetime.combine(moment.astimezone(LONDON).date(), datetime.min.time(),
                            tzinfo=LONDON).astimezone(timezone.utc)


def _open_cards(session, business) -> set:
    rows = session.execute(text(
        "SELECT payload FROM aria_actions WHERE business_id = :b "
        "AND action_type = 'send_invoice_chase' AND status = 'proposed'"),
        {"b": str(business.id)}).fetchall()
    return {str(_loads(p).get("invoice_id")) for (p,) in rows}


def _last_chase_by_customer(session, business) -> dict:
    """Latest chase per customer email, across ALL their invoices (a chase
    sent by hand counts too)."""
    rows = session.execute(text(
        "SELECT customer_email, last_chased_at FROM invoices WHERE business_id = :b "
        "AND last_chased_at IS NOT NULL AND customer_email IS NOT NULL"),
        {"b": str(business.id)}).fetchall()
    latest: dict = {}
    for email, at in rows:
        key, when = email.strip().lower(), _parse(at)
        if key and when and (key not in latest or when > latest[key]):
            latest[key] = when
    return latest


def _candidates(session, business):
    not_owed = ", ".join(f"'{s}'" for s in _NOT_OWED)
    return session.execute(text(f"""
        SELECT id, customer_email, chase_stage, last_chased_at, due_date FROM (
          SELECT id, customer_email, chase_stage, last_chased_at, due_date, {_BALANCE} AS bal
          FROM invoices
          WHERE business_id = :b AND (archived IS NULL OR archived = false)
            AND LOWER(status) NOT IN ({not_owed})
        ) owed
        WHERE bal > 0
        ORDER BY due_date, id
    """), {"b": str(business.id)}).fetchall()


_INFLIGHT_PERIOD = "2000-01"          # in-progress tickets are not tied to a month
_INFLIGHT_STALE = timedelta(hours=1)   # a chase takes seconds; older means a crashed run


def _take(session, bid: str, meter: str, period: str, moment: datetime) -> bool:
    row = session.execute(text("""
        INSERT INTO usage_meters (business_id, meter, period, value, updated_at)
        VALUES (:b, :m, :p, 1, :now)
        ON CONFLICT (business_id, meter, period) DO NOTHING
        RETURNING meter
    """), {"b": bid, "m": meter, "p": period, "now": moment}).fetchone()
    return row is not None


def _live_automatic_draft(session, business, customer: str) -> bool:
    """An automatic chase for this customer that a run has proposed and not
    yet finished (proposed or executing). While one exists, its run may be
    alive though paused, so its in-progress ticket is never reclaimed
    (Codex AUTO-1 review 4). A run that truly crashed leaves this draft on
    the owner's home as a normal card, to approve or dismiss."""
    rows = session.execute(text(
        "SELECT payload FROM aria_actions WHERE business_id = :b "
        "AND action_type = 'send_invoice_chase' AND status IN ('proposed', 'executing')"),
        {"b": str(business.id)}).fetchall()
    for (payload,) in rows:
        p = _loads(payload)
        if p.get("automation") == KIND and str(p.get("to") or "").strip().lower() == customer:
            return True
    return False


def _still_holds(session, business, customer: str, stamp: datetime) -> bool:
    """Fencing: does THIS run still hold the customer's in-progress ticket?"""
    row = session.execute(text(
        "SELECT 1 FROM usage_meters WHERE business_id = :b AND meter = :m AND period = :p "
        "AND updated_at = :stamp"),
        {"b": str(business.id), "m": f"autochase-inflight:{customer}",
         "p": _INFLIGHT_PERIOD, "stamp": stamp}).fetchone()
    session.rollback()
    return row is not None


def _reserve(session, business, customer: str, moment: datetime, s: dict, unresolved_now):
    """Durable, unique tickets for one automatic chase. usage_meters'
    UNIQUE (business_id, meter, period) lets exactly one run hold each:
    * `autochase-inflight:<customer>` — held only while a chase is under way,
      not tied to a date, so a run either side of midnight still excludes the
      customer (Codex AUTO-1 review 3); one over an hour old with nothing
      sent or unresolved is a crashed run's and is reclaimed;
    * `autochase:<customer>:<UK date>` — one automatic chase per customer
      per day;
    * a numbered cap slot — but only if fewer slots than the CURRENT cap are
      already used today (a lowered cap counts every slot used — review 3).
    Returns (reason or None, tickets as (meter, period) pairs)."""
    bid = str(business.id)
    day = moment.astimezone(LONDON).date()
    period = day.strftime("%Y-%m")
    inflight = f"autochase-inflight:{customer}"
    if not _take(session, bid, inflight, _INFLIGHT_PERIOD, moment):
        held = session.execute(text(
            "SELECT updated_at FROM usage_meters WHERE business_id = :b AND meter = :m AND period = :p"),
            {"b": bid, "m": inflight, "p": _INFLIGHT_PERIOD}).fetchone()
        session.rollback()
        stamp = _parse(held[0]) if held else None
        if (stamp is None or moment - stamp < _INFLIGHT_STALE or customer in unresolved_now()
                or _live_automatic_draft(session, business, customer)):
            return "chase_in_progress", []
        session.execute(text(
            "DELETE FROM usage_meters WHERE business_id = :b AND meter = :m AND period = :p "
            "AND updated_at = :u"), {"b": bid, "m": inflight, "p": _INFLIGHT_PERIOD, "u": held[0]})
        if not _take(session, bid, inflight, _INFLIGHT_PERIOD, moment):
            session.rollback()
            return "chase_in_progress", []
    held = [(inflight, _INFLIGHT_PERIOD)]
    daily = f"autochase:{customer}:{day.isoformat()}"
    if not _take(session, bid, daily, period, moment):
        session.rollback()
        return "customer_chased_recently", []
    held.append((daily, period))
    used = session.execute(text(
        "SELECT COUNT(*) FROM usage_meters WHERE business_id = :b AND period = :p AND meter LIKE :slots"),
        {"b": bid, "p": period, "slots": f"autochase-slot:{day.isoformat()}:%"}).scalar() or 0
    if used < s["daily_cap"]:
        for n in range(1, s["daily_cap"] + 1):
            slot = f"autochase-slot:{day.isoformat()}:{n}"
            if _take(session, bid, slot, period, moment):
                session.commit()
                return None, held + [(slot, period)]
    session.rollback()  # gives back the in-progress and daily tickets with it
    return "daily_cap", []


def _give_back(session, business, tickets: list) -> None:
    """Nothing was sent: free every ticket for a later run."""
    for meter, period in tickets:
        session.execute(text(
            "DELETE FROM usage_meters WHERE business_id = :b AND meter = :m AND period = :p"),
            {"b": str(business.id), "m": meter, "p": period})
    session.commit()


def _finished(session, business, tickets: list) -> None:
    """A chase went (or may have): keep the daily and cap tickets; end the
    in-progress one — the action record now spaces the customer."""
    _give_back(session, business, [t for t in tickets if t[0].startswith("autochase-inflight:")])


def _attempt_status(session, business, action_id: str) -> Optional[str]:
    row = session.execute(text(
        "SELECT status FROM aria_actions WHERE id = :id AND business_id = :b"),
        {"id": action_id, "b": str(business.id)}).fetchone()
    return row[0] if row else None


def _authority(business, s: dict, moment: datetime) -> Optional[str]:
    """Why the autopilot may NOT act right now, or None."""
    if not s["enabled"]:
        return "switched_off"
    if not _in_window(moment, s):
        return "outside_hours"
    from auth import ACCESS_FULL, resolve_access_level
    if resolve_access_level(business) != ACCESS_FULL:
        return "account_not_active"
    if aria_actions._feature_problem(business, "send_invoice_chase"):
        return "plan"
    return None


def run_invoice_autopilot(session, business, settings: Optional[dict], *,
                          owner_name: Optional[str] = None, refresh=None) -> dict:
    """One pass of the autopilot for one business. Returns what it did.

    `refresh()` returns the CURRENT (settings, business). It is called before
    every send, so switching off, pausing a customer, a suspension or the end
    of the window take effect mid-run (Codex AUTO-1 review 1, finding 3)."""
    result: dict = {"sent": [], "cards": [], "skipped": {}}
    refresh = refresh or (lambda: (settings, business))
    s = chase_settings(settings)
    moment = now()
    if _authority(business, s, moment):
        return result

    waiting = _open_cards(session, business)
    unresolved = _unresolved_customers(session, business)
    last_by_customer = _last_chase_by_customer(session, business)
    for _, who, status, created_at, _, _ in _attempts(session, business, moment - timedelta(days=31)):
        if status in ("executing", "done") and who and created_at and (
                who not in last_by_customer or created_at > last_by_customer[who]):
            last_by_customer[who] = created_at
    chased_now: set = set()

    for invoice_id, email, stage, last_chased, due in _candidates(session, business):
        iid = str(invoice_id)
        customer = (email or "").strip().lower()
        if not customer:
            result["skipped"][iid] = "no_customer_email"
            continue

        # Re-read authority and rules FIRST, and decide everything below with
        # them (Codex AUTO-1 review 1 finding 3; review 2 finding 3).
        current_settings, business = refresh()
        s = chase_settings(current_settings)
        moment = now()
        stop = _authority(business, s, moment)
        if stop:
            result["skipped"][iid] = stop
            break
        if customer in s["paused_customers"]:
            result["skipped"][iid] = "customer_paused"
            continue
        if customer in unresolved:
            result["skipped"][iid] = "unresolved_attempt"
            continue
        if iid in waiting:
            result["skipped"][iid] = "card_waiting"
            continue
        due_day = due if hasattr(due, "year") and not isinstance(due, str) else \
            datetime.fromisoformat(str(due)[:10]).date()
        stage = int(stage or 0)
        if stage == 0:
            is_due = (uk_today(moment) - due_day).days >= s["first_after_days"]
        else:
            last = _parse(last_chased)
            is_due = last is None or moment - last >= timedelta(days=s["every_days"])
        if not is_due:
            result["skipped"][iid] = "not_due"
            continue
        recent = last_by_customer.get(customer)
        if customer in chased_now or (recent and moment - recent < timedelta(days=s["customer_gap_days"])):
            result["skipped"][iid] = "customer_chased_recently"
            continue
        next_stage = min(stage + 1, 4)

        if next_stage > s["max_auto_stage"]:
            # A later stage is the owner's call: a card, never a send.
            card = aria_actions.propose(session, business, None, "send_invoice_chase",
                                        {"invoice_id": iid, "chase_stage": next_stage},
                                        owner_name=owner_name, raised_by=KIND)
            if "proposal" in card:
                result["cards"].append(iid)
                waiting.add(iid)
            else:
                result["skipped"][iid] = card.get("error") or "not_proposed"
            continue

        lost, tickets = _reserve(session, business, customer, moment, s,
                                 lambda: _unresolved_customers(session, business))
        if lost:
            result["skipped"][iid] = lost
            if lost == "daily_cap":
                break
            continue
        proposed = aria_actions.propose(session, business, None, "send_invoice_chase",
                                        {"invoice_id": iid, "chase_stage": next_stage},
                                        owner_name=owner_name, automation=KIND)
        if "proposal" not in proposed:
            _give_back(session, business, tickets)
            result["skipped"][iid] = proposed.get("error") or "not_proposed"
            continue
        card = proposed["proposal"]
        if not _still_holds(session, business, customer, moment):
            # Another run holds this customer now: send nothing, free only OUR
            # daily and cap tickets, and leave theirs alone (review 4).
            try:
                aria_actions.dismiss(session, business, card["id"])
            except aria_actions.ActionRefused:
                pass
            _give_back(session, business, [t for t in tickets
                                           if not t[0].startswith("autochase-inflight:")])
            result["skipped"][iid] = "lost_reservation"
            continue
        try:
            outcome = aria_actions.approve(session, business, card["id"], None, card["version"])
        except aria_actions.ActionRefused as exc:
            # A refusal does NOT prove nothing went: someone (the owner) may
            # have approved this very card first (Codex AUTO-1 review 3). Give
            # the tickets back only if the action shows no send.
            status = _attempt_status(session, business, card["id"])
            if status in ("done", "executing"):
                _finished(session, business, tickets)
                chased_now.add(customer)
                if status == "executing":
                    unresolved.add(customer)
            else:
                _give_back(session, business, tickets)
            result["skipped"][iid] = exc.detail
            continue
        _finished(session, business, tickets)
        # Sent, failed or unconfirmed: this customer is done for this run, and
        # the tickets stay used.
        chased_now.add(customer)
        if outcome.get("status") == "done":
            result["sent"].append(iid)
        else:
            result["skipped"][iid] = f"send_{outcome.get('status')}"
            if outcome.get("status") == "executing":
                unresolved.add(customer)
    if result["sent"] or result["cards"]:
        logger.info("[Autopilot] %s: chased %s, carded %s", business.id,
                    len(result["sent"]), len(result["cards"]))
    return result


def owner_first_name(session, business_id: str) -> Optional[str]:
    """For the sign-off ("AI assistant to Mike"): the owner's first name if
    the business has one on record; otherwise the sign-off names the team."""
    try:
        row = session.execute(text(
            "SELECT owner_name FROM whatsapp_configs WHERE business_id = :b"),
            {"b": str(business_id)}).fetchone()
        if row and row[0]:
            return str(row[0]).split()[0]
    except Exception:
        session.rollback()
    return None


def run_all_due(session) -> int:
    """The scheduler's pass: every business that switched the autopilot on."""
    rows = session.execute(text("SELECT business_id, settings FROM business_settings")).fetchall()
    total = 0
    for business_id, raw in rows:
        settings = (_loads(raw).get("automations") or {}).get(KIND)
        if not chase_settings(settings)["enabled"]:
            continue
        business = aria_actions.load_business(session, str(business_id))
        if business is None:
            continue
        def refresh(bid=str(business_id)):
            # A real re-read: without this the ORM hands back the instance it
            # already holds, with a stale is_active (Codex AUTO-1 review 2).
            session.expire_all()
            row = session.execute(text(
                "SELECT settings FROM business_settings WHERE business_id = :b"),
                {"b": bid}).fetchone()
            fresh = (_loads(row[0]).get("automations") or {}).get(KIND) if row else None
            return fresh, aria_actions.load_business(session, bid)

        try:
            done = run_invoice_autopilot(session, business, settings,
                                         owner_name=owner_first_name(session, business_id),
                                         refresh=refresh)
            total += len(done["sent"])
        except Exception as exc:  # one business never stops the others
            session.rollback()
            logger.error("[Autopilot] %s failed: %s", business_id, exc)
    return total
