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


def _won_claim(session, business, mine: str, customer: str, moment: datetime,
               s: dict) -> Optional[str]:
    """Insert-then-check (Codex AUTO-1 review 1, finding 2): our proposal is
    already stored, so a rival run — another process — can see it, and we
    can see theirs. Of two in-flight claims, the earlier (created_at, id)
    wins and the other stands down; anything already sent or unresolved wins
    outright. Returns None if we may send, else the reason we may not."""
    key = None
    rows = _attempts(session, business, min(moment - timedelta(days=s["customer_gap_days"]),
                                            _day_start(moment)))
    for aid, _, _, created_at, _, _ in rows:
        if aid == mine:
            key = (created_at, aid)
    gap_start = moment - timedelta(days=s["customer_gap_days"])
    for aid, who, status, created_at, automatic, approved_by in rows:
        if aid == mine or who != customer or created_at < gap_start:
            continue
        if status in ("executing", "done"):
            return "customer_chased_recently"
        if status == "proposed" and automatic and key and (created_at, aid) < key:
            return "customer_chased_recently"
    today = _day_start(moment)
    used = sum(1 for aid, _, status, created_at, automatic, _ in rows
               if aid != mine and automatic and created_at >= today and (
                   status in ("executing", "done", "failed")
                   or (status == "proposed" and key and (created_at, aid) < key)))
    if used >= s["daily_cap"]:
        return "daily_cap"
    return None


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

    today = uk_today(moment)
    waiting = _open_cards(session, business)
    unresolved = _unresolved_customers(session, business)
    last_by_customer = _last_chase_by_customer(session, business)
    for _, who, status, created_at, _, _ in _attempts(
            session, business, moment - timedelta(days=s["customer_gap_days"])):
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
            is_due = (today - due_day).days >= s["first_after_days"]
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

        # Re-read authority before acting on THIS invoice.
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

        proposed = aria_actions.propose(session, business, None, "send_invoice_chase",
                                        {"invoice_id": iid, "chase_stage": next_stage},
                                        owner_name=owner_name, automation=KIND)
        if "proposal" not in proposed:
            result["skipped"][iid] = proposed.get("error") or "not_proposed"
            continue
        card = proposed["proposal"]
        lost = _won_claim(session, business, card["id"], customer, moment, s)
        if lost:
            try:
                aria_actions.dismiss(session, business, card["id"])
            except aria_actions.ActionRefused:
                pass
            result["skipped"][iid] = lost
            if lost == "daily_cap":
                break
            continue
        try:
            outcome = aria_actions.approve(session, business, card["id"], None, card["version"])
        except aria_actions.ActionRefused as exc:
            result["skipped"][iid] = exc.detail
            continue
        # Sent, failed or unconfirmed: this customer is done for this run.
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
