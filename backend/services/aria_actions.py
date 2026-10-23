"""Aria's approval cards — NS-B10 (ADR 0001 D9, D11, D12, D15, D18).

Aria drafts an email, an invoice chase, a calendar booking or a task. The
server stores EXACTLY what would be done (`aria_actions.payload`) and does
nothing else. The owner sees it as a card; one tap approves it; the server
then does what was stored, once. A "yes" typed or spoken to Aria is never an
approval — only `approve()`, reached from the card's button, is.

Once only (Mike's decision 4, 13 Oct 2026): approval CLAIMS the action
(`status: proposed -> executing`) and commits that claim before anything is
sent. A second tap, or a tap arriving mid-send, finds nothing to claim. An
action interrupted mid-send stays `executing` and is never retried: for
customer contact a missing chase is cheaper than a double one.

Execution goes through assistant_tools' existing senders, looked up at call
time, never through `execute_tool` (which still refuses all five actions to
any caller that is not this approval path).
"""

import asyncio
import hashlib
import json
import re
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import text

logger = logging.getLogger(__name__)

# What Aria may raise in chat or voice. Outreach is deliberately absent: an
# outreach card is raised only by its campaign (OUT-6), never by the model.
CHAT_ACTION_TYPES = ("send_email", "send_invoice_chase", "create_calendar_event", "create_task")
ACTION_TYPES = CHAT_ACTION_TYPES + ("send_outreach",)
EXPIRY = timedelta(hours=72)
RECENT_CHASE = timedelta(days=7)   # Mike: "the usual rule" for asking before re-chasing
DEFAULT_ASSISTANT_NAME = "Aria"

# Every action needs Aria; each then needs the feature it touches
# (auth.CANONICAL_FEATURES).
_FEATURES = {
    "send_email": ("aria_chat", "email"),
    "send_invoice_chase": ("aria_chat", "invoicing", "email"),
    "create_calendar_event": ("aria_chat", "calendar_sync"),
    "create_task": ("aria_chat",),
    "send_outreach": ("outreach",),  # rechecked from the database at the claim
}

# What the owner may change on a card before approving it. The sign-off is
# never editable; neither is a chase's recipient or invoice.
_EDITABLE = {
    "send_email": {"to", "subject", "body"},
    "send_invoice_chase": {"subject", "body"},
    "create_calendar_event": {"title", "date", "start_time", "duration_minutes",
                              "description", "calendar_id"},
    "create_task": {"title", "description", "due_at"},
    # Recipient, mailbox, footer, unsubscribe headers and threading are bound
    # to the campaign and rechecked at the claim (OUT-6).
    "send_outreach": {"subject", "body"},
}

SENT_MESSAGE = ("Shown to the owner as an approval card. Nothing has been sent or "
                "done yet: it happens only if they tap Approve on the card.")


class ActionRefused(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def now() -> datetime:
    return datetime.now(timezone.utc)


def sign_off(assistant_name: str, owner_name: Optional[str], business_name: Optional[str]) -> str:
    """Mike's decision 2 (option A). Every line is true: Aria sends from the
    owner's own connected mailbox, so a reply reaches them."""
    assistant = assistant_name or DEFAULT_ASSISTANT_NAME
    business = business_name or "the business"
    if owner_name:
        return (f"{assistant}\n"
                f"AI assistant to {owner_name} at {business}\n"
                f"I pass every message straight to {owner_name}. "
                f"Reply to this email and it reaches {owner_name}.")
    return (f"{assistant}\n"
            f"AI assistant at {business}\n"
            f"I pass every message straight to the team. "
            f"Reply to this email and it reaches them.")


def load_business(session, business_id: str):
    from auth import _load_business
    return _load_business(session, business_id)


# ------------------------------------------------------------- plumbing ---

def _is_postgres(session) -> bool:
    return session.get_bind().dialect.name == "postgresql"


def _json_param(session) -> str:
    return "CAST(:payload AS jsonb)" if _is_postgres(session) else ":payload"


def version_of(payload: dict) -> str:
    """A short fingerprint of exactly what a card will do. Approval carries
    the version the owner saw; a different stored version is refused (Codex
    NS-B10 review 1, finding 1)."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def _loads(value):
    if value is None or isinstance(value, (dict, list)):
        return value
    return json.loads(value)


def _iso(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value.replace(" ", "T", 1)
    return value.isoformat()


def _feature_problem(business, action_type: str) -> Optional[str]:
    from auth import assert_feature_access
    for feature in _FEATURES[action_type]:
        try:
            assert_feature_access(business, feature)
        except HTTPException as exc:
            return str(exc.detail)
    return None


def _valid_address(address: str) -> Optional[str]:
    if not address:
        return "An email address for the recipient is required."
    if "@" not in address:
        return f"'{address}' is not an email address."
    local, _, domain = address.rpartition("@")
    if not local or "." not in domain or " " in address:
        return f"'{address}' is not a valid email address."
    return None


# ------------------------------------------------------- building payloads ---

def _email_payload(args: dict, owner_name, business) -> dict:
    to = str(args.get("to") or "").strip()
    subject = str(args.get("subject") or "").strip()
    body = str(args.get("body") or "").replace("\\n", "\n").strip()
    problem = _valid_address(to)
    if problem:
        raise ActionRefused(422, problem)
    if not subject or not body:
        raise ActionRefused(422, "An email needs a subject and a body.")
    return {"to": to, "subject": subject, "body": body,
            "sign_off": args.get("sign_off") or sign_off(
                DEFAULT_ASSISTANT_NAME, owner_name, getattr(business, "name", None))}


def _owed_amount(session, business_id: str, invoice_id: str):
    """What the customer still owes on this invoice (AUTO-3 decision C):
    a part-paid invoice is chased for the balance, never its full amount."""
    from services.home_summary import _BALANCE
    row = session.execute(text(
        f"SELECT {_BALANCE} FROM invoices WHERE id = :invoice_id AND business_id = :business_id"),
        {"invoice_id": str(invoice_id), "business_id": str(business_id)}).fetchone()
    return None if row is None or row[0] is None else row[0]


def _money(value) -> str:
    return f"{float(value):.2f}"


def _chase_marks(session, business_id: str, invoice_id: str):
    """(customer address, stage, last chased) as they are NOW, normalised so a
    card can record them and approval can see any change since (Codex AUTO-3
    review 1)."""
    from services.chase_replies import _address
    row = session.execute(text(
        "SELECT customer_email, chase_stage, last_chased_at FROM invoices "
        "WHERE id = :id AND business_id = :b"), {"id": str(invoice_id), "b": str(business_id)}).fetchone()
    if row is None:
        return None
    when = row[2]
    if isinstance(when, str) and when:
        when = datetime.fromisoformat(when.replace(" ", "T").replace("Z", "+00:00"))
    if isinstance(when, datetime) and when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return _address(row[0]), int(row[1] or 0), (when.astimezone(timezone.utc).isoformat() if when else None)


def _drifted(session, business_id: str, invoice_id: str, *, to: str, amount: str,
             stage_was: int, last_chased_was) -> Optional[str]:
    """Why a drafted chase no longer matches this invoice, or None.
    Codex AUTO-3 review 1: the amount still owed, the customer and the chase
    marks must all be exactly as drafted."""
    from services.chase_replies import _address
    marks = _chase_marks(session, business_id, invoice_id)
    if marks is None:
        return "no longer exists"
    customer, stage, last = marks
    if customer != _address(to):
        return "now belongs to a different customer"
    owed = _owed_amount(session, business_id, invoice_id)
    if owed is None or _money(owed) != amount:
        return "has a different amount owed now"
    if stage != int(stage_was) or last != last_chased_was:
        return "has been chased since this was drafted"
    return None


def _invoice(session, business_id: str, invoice_id: str):
    return session.execute(text(
        "SELECT id, invoice_number, customer_name, customer_email, amount, status, "
        "chase_stage, due_date FROM invoices "
        "WHERE id = :invoice_id AND business_id = :business_id "
        "AND (archived IS NULL OR archived = false)"),
        {"invoice_id": str(invoice_id), "business_id": str(business_id)}).fetchone()


def _chase_payload(session, business, args: dict, owner_name) -> dict:
    from email_templates import get_chase_email_template
    if args.get("invoice_ids") is not None:
        ids = args.get("invoice_ids")
        if isinstance(ids, list) and len(ids) == 1:
            args = {**{k: v for k, v in args.items() if k != "invoice_ids"}, "invoice_id": ids[0]}
        else:
            return _combined_chase_payload(session, business, args, owner_name)
    invoice_id = str(args.get("invoice_id") or "").strip()
    if not invoice_id:
        raise ActionRefused(422, "invoice_id is required. Use list_invoices to find it.")
    try:
        uuid.UUID(invoice_id)
    except ValueError:
        raise ActionRefused(422, f"Invoice {invoice_id} not found.")
    row = _invoice(session, business.id, invoice_id)
    if row is None:
        raise ActionRefused(422, f"Invoice {invoice_id} not found.")
    _, number, customer, customer_email, amount, status, current_stage, due = row
    if (status or "").lower() == "paid":
        raise ActionRefused(422, f"Invoice {number} is already paid. No chase needed.")
    if not customer_email:
        raise ActionRefused(422, f"Invoice {number} has no customer email address.")
    requested = args.get("chase_stage")
    stage = min(max(int(requested), 1), 4) if requested else min((current_stage or 0) + 1, 4)
    due_text = due.isoformat() if hasattr(due, "isoformat") else (str(due) if due else "N/A")
    owed = _owed_amount(session, business.id, invoice_id)
    marks = _chase_marks(session, business.id, invoice_id)
    template = get_chase_email_template(
        stage, {"customer_name": customer, "invoice_number": number,
                "amount": owed if owed is not None else amount,
                "due_date": due_text}, getattr(business, "name", None))
    # AUTO-2: the chase goes from the business's default mailbox, fixed here,
    # so replies land in the inbox Aria reads. Never "the newest account".
    from services.chase_replies import default_mailbox
    account_id = default_mailbox(session, business.id)
    if account_id is None:
        raise ActionRefused(422, "Choose which mailbox chases are sent from: mark one as the "
                                 "default in Email settings.")
    return {"invoice_id": invoice_id, "account_id": account_id, "invoice_number": number, "customer_name": customer,
            "to": customer_email, "subject": template["subject"], "body": template["body"],
            "chase_stage": stage,
            # What approval checks again (Codex AUTO-3 review 1).
            "amount_owed": _money(owed if owed is not None else amount),
            "stage_was": marks[1], "last_chased_was": marks[2],
            "sign_off": args.get("sign_off") or sign_off(
                DEFAULT_ASSISTANT_NAME, owner_name, getattr(business, "name", None))}


def _combined_chase_payload(session, business, args: dict, owner_name) -> dict:
    """AUTO-3: one chase listing several of ONE customer's invoices, at one
    stage. Each invoice records the stage it was at and the stage it moves to,
    so approval can refuse a card that is out of date."""
    from email_templates import get_combined_chase_email_template
    from services.chase_replies import _address, default_mailbox
    ids = args.get("invoice_ids")
    if not isinstance(ids, list) or len(ids) < 2 or len(set(map(str, ids))) != len(ids):
        raise ActionRefused(422, "A combined chase needs two or more different invoices.")
    rows = []
    for iid in ids:
        try:
            uuid.UUID(str(iid))
        except ValueError:
            raise ActionRefused(422, f"Invoice {iid} not found.")
        row = _invoice(session, business.id, str(iid))
        if row is None:
            raise ActionRefused(422, f"Invoice {iid} not found.")
        if (row[5] or "").lower() == "paid" or not _still_owed(session, business.id, str(iid)):
            raise ActionRefused(422, f"Invoice {row[1]} is no longer owed.")
        rows.append(row)
    customers = {_address(r[3]) for r in rows}
    if len(customers) != 1 or not next(iter(customers)):
        raise ActionRefused(422, "A combined chase is for one customer's invoices only.")

    def due_key(r):
        return (str(r[7]) if r[7] is not None else "9999", str(r[0]))
    rows.sort(key=due_key)
    invoices = []
    for r in rows:
        was = int(r[6] or 0)
        due = r[7].isoformat() if hasattr(r[7], "isoformat") else (str(r[7]) if r[7] else "N/A")
        invoices.append({"invoice_id": str(r[0]), "invoice_number": r[1],
                         "amount": _money(_owed_amount(session, business.id, str(r[0])) or 0),
                         "due_date": due, "stage_was": was, "stage": min(was + 1, 4),
                         "last_chased_was": _chase_marks(session, business.id, str(r[0]))[2]})
    requested = args.get("chase_stage")
    stage = min(max(int(requested), 1), 4) if requested else invoices[0]["stage"]
    lead = rows[0]
    template = get_combined_chase_email_template(stage, lead[2], invoices, getattr(business, "name", None))
    account_id = default_mailbox(session, business.id)
    if account_id is None:
        raise ActionRefused(422, "Choose which mailbox chases are sent from: mark one as the "
                                 "default in Email settings.")
    return {"invoice_id": str(lead[0]), "invoice_ids": [i["invoice_id"] for i in invoices],
            "invoices": invoices, "total": _money(sum(float(i["amount"]) for i in invoices)),
            "account_id": account_id, "invoice_number": lead[1], "customer_name": lead[2],
            "to": lead[3], "subject": template["subject"], "body": template["body"],
            "chase_stage": stage,
            "sign_off": args.get("sign_off") or sign_off(
                DEFAULT_ASSISTANT_NAME, owner_name, getattr(business, "name", None))}


def _recently_chased(session, business, args: dict) -> Optional[str]:
    """Mike, 23 Oct 2026: the owner asks in chat to chase an invoice that was
    already chased in the last 7 days; Aria says so and asks first."""
    ids = args.get("invoice_ids") if args.get("invoice_ids") is not None else [args.get("invoice_id")]
    for iid in ids or []:
        try:
            uuid.UUID(str(iid))
        except ValueError:
            continue
        row = session.execute(text(
            "SELECT invoice_number, last_chased_at, chase_stage FROM invoices "
            "WHERE id = :id AND business_id = :b"), {"id": str(iid), "b": str(business.id)}).fetchone()
        if row is None or not row[1]:
            continue
        when = row[1]
        if isinstance(when, str):
            when = datetime.fromisoformat(when.replace(" ", "T").replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if now() - when < RECENT_CHASE:
            from zoneinfo import ZoneInfo
            local = when.astimezone(ZoneInfo("Europe/London"))
            return (f"Invoice {row[0]} was already chased on {local.day} {local:%B} "
                    f"(stage {row[2] or 0}). Tell the owner and ask whether to chase it again. "
                    "Only if they say yes, call send_invoice_chase again with chase_again set "
                    "to true. Nothing has been drafted or sent.")
    return None


def _event_payload(args: dict, tz_name: str) -> dict:
    from zoneinfo import ZoneInfo
    from services import booking
    title = str(args.get("title") or "").strip()
    if not title:
        raise ActionRefused(422, "A booking needs a title.")
    try:
        day = date.fromisoformat(str(args.get("date")))
        hour, minute = (int(p) for p in str(args.get("start_time")).split(":")[:2])
        minutes = int(args.get("duration_minutes") or 60)
    except (TypeError, ValueError):
        raise ActionRefused(422, "A booking needs a date (YYYY-MM-DD) and a start time (HH:MM).")
    if minutes <= 0 or minutes > 24 * 60:
        raise ActionRefused(422, "A booking must last between 1 minute and 24 hours.")
    tz = ZoneInfo(tz_name or "Europe/London")
    start = booking.local_time(day, hour, minute, tz)
    if start is None:
        raise ActionRefused(422, f"{args.get('start_time')} on {day.isoformat()} does not "
                                 "exist or happens twice because the clocks change. "
                                 "Pick another time.")
    end = booking.slot_end(start, minutes)
    return {"title": title, "date": day.isoformat(), "start_time": f"{hour:02d}:{minute:02d}",
            "duration_minutes": minutes, "start": start.isoformat(), "end": end.isoformat(),
            "timezone": tz_name or "Europe/London",
            "calendar_id": str(args.get("calendar_id") or "primary"),
            "description": str(args.get("description") or ""),
            "attendee_email": args.get("attendee_email") or None}


def _task_payload(args: dict) -> dict:
    title = str(args.get("title") or "").strip()
    if not title:
        raise ActionRefused(422, "A task needs a title.")
    return {"title": title, "description": args.get("description") or None,
            "due_at": args.get("due_at") or None}


def _build(session, business, action_type: str, args: dict, owner_name, tz_name) -> dict:
    if action_type == "send_email":
        return _email_payload(args, owner_name, business)
    if action_type == "send_invoice_chase":
        return _chase_payload(session, business, args, owner_name)
    if action_type == "create_calendar_event":
        return _event_payload(args, tz_name)
    if action_type == "send_outreach":
        from services import outreach_send
        return outreach_send.build_payload(session, business, args, owner_name=owner_name)
    return _task_payload(args)


def _view(row) -> dict:
    (aid, action_type, payload, status, expires_at, error, result, created_at) = row
    preview = _loads(payload)
    return {"id": str(aid), "action_type": action_type, "status": status,
            "preview": preview, "version": version_of(preview), "expires_at": _iso(expires_at),
            "error": error, "result": _loads(result), "created_at": _iso(created_at)}


_COLUMNS = "id, action_type, payload, status, expires_at, error, result, created_at"


# ------------------------------------------------------------- the API ---

def propose(session, business, user_id, action_type: str, args: dict, *,
            owner_name: Optional[str] = None, timezone: Optional[str] = None,
            automation: Optional[str] = None, raised_by: Optional[str] = None) -> dict:
    """Store a card. Acts on nothing. Returns {"proposal": ...} or {"error": ...}.
    `automation` marks a card raised by a standing permission (AUTO-1), so the
    audit trail can tell it from one Aria proposed in conversation."""
    if action_type not in ACTION_TYPES:
        return {"error": f"{action_type} cannot be proposed."}
    if action_type == "send_outreach" and (automation or raised_by):
        # OUT-6: every outreach email is a card the owner taps. No standing
        # permission sends one, and none raises one.
        return {"error": "Outreach is sent only when the owner approves each email."}
    problem = _feature_problem(business, action_type)
    if problem:
        return {"error": f"This can't be done on your current plan: {problem}"}
    tz_name = timezone or getattr(business, "timezone", None) or "Europe/London"
    args = {k: v for k, v in dict(args or {}).items() if k != "sign_off"}
    chase_again = bool(args.pop("chase_again", False))
    if (action_type == "send_invoice_chase" and not automation and not raised_by
            and not chase_again):
        recent = _recently_chased(session, business, args)
        if recent:
            session.rollback()
            return {"error": recent}
    try:
        payload = _build(session, business, action_type, args, owner_name, tz_name)
    except ActionRefused as exc:
        session.rollback()  # never leave half a proposal (an outreach token) pending
        return {"error": exc.detail}
    if automation:
        payload["automation"] = automation  # to be SENT by a standing permission
    if raised_by:
        payload["raised_by"] = raised_by    # a card an automation raised for a tap
    moment = now()
    aid = str(uuid.uuid4())
    session.execute(text(
        f"INSERT INTO aria_actions (id, business_id, proposed_by, action_type, payload, "
        f"status, expires_at, created_at, updated_at) VALUES (:id, :business_id, "
        f":user_id, :action_type, {_json_param(session)}, 'proposed', :expires_at, "
        f":now, :now)"),
        {"id": aid, "business_id": str(business.id),
         "user_id": str(user_id) if user_id else None, "action_type": action_type,
         "payload": json.dumps(payload), "expires_at": moment + EXPIRY, "now": moment})
    session.commit()
    return {"proposal": {"id": aid, "action_type": action_type, "status": "proposed",
                         "preview": payload, "version": version_of(payload),
                         "expires_at": (moment + EXPIRY).isoformat(),
                         "error": None, "result": None, "created_at": moment.isoformat()}}


def _paused_by_reply(session, business, payload) -> bool:
    from services.chase_replies import _address, blocked
    replied, stopped = blocked(session, business)
    to = _address(payload.get("to"))  # "Name <address>" and "address" alike (review 2)
    listed = {str(i) for i in (payload.get("invoice_ids") or [payload.get("invoice_id")])}
    return to in replied or bool(listed & stopped)


def _still_owed(session, business_id, invoice_id) -> bool:
    from services.home_summary import invoice_owed
    return invoice_owed(session, str(business_id), str(invoice_id))


def _scoped(session, business, action_id: str):
    try:
        uuid.UUID(str(action_id))
    except ValueError:
        raise ActionRefused(404, "Not found")
    row = session.execute(text(
        f"SELECT {_COLUMNS} FROM aria_actions WHERE id = :id AND business_id = :business_id"),
        {"id": str(action_id), "business_id": str(business.id)}).fetchone()
    if row is None:
        raise ActionRefused(404, "Not found")
    return row


def _is_expired(expires_at) -> bool:
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at.replace(" ", "T"))
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= now()


def _set(session, business, action_id: str, **fields) -> None:
    fields["updated_at"] = now()
    result_sql = "CAST(:result AS jsonb)" if _is_postgres(session) else ":result"
    assignments = ", ".join(
        f"result = {result_sql}" if k == "result" else f"{k} = :{k}" for k in fields)
    params = {k: (json.dumps(v, default=str) if k == "result" and v is not None else v)
              for k, v in fields.items()}
    session.execute(text(f"UPDATE aria_actions SET {assignments} "
                         "WHERE id = :action_id AND business_id = :business_id"),
                    {**params, "action_id": str(action_id), "business_id": str(business.id)})


def _refuse_unclaimable(session, business, row):
    status, expires_at = row[3], row[4]
    if status == "proposed" and _is_expired(expires_at):
        _set(session, business, row[0], status="expired")
        session.commit()
        raise ActionRefused(409, "This card has expired. Ask Aria again.")
    if status == "proposed":
        session.rollback()
        raise ActionRefused(409, CHANGED)
    session.rollback()
    if status == "executing":
        raise ActionRefused(409, "This is already being sent.")
    raise ActionRefused(409, f"This card is already {status}.")


CHANGED = "This card has changed since you saw it. Check it again before approving."

_STATUS_IN_ERROR = re.compile(r"Failed to create event: (\d{3})")


def _unknown_outcome(action_type: str, error: str) -> bool:
    """True when the provider may have acted although we have no
    confirmation (Codex review 1, finding 2). Only a definite rejection, or a
    failure before anything was sent, may be called a failure: calling an
    unconfirmed send 'not done' invites a second chase."""
    if action_type in ("send_email", "send_invoice_chase"):
        return error.startswith("Send failed") or "did not confirm" in error
    if action_type == "create_calendar_event":
        status = _STATUS_IN_ERROR.search(error)
        return bool(status) and (int(status.group(1)) >= 500 or status.group(1) == "429")
    return False


def _succeeded(result) -> bool:
    return isinstance(result, dict) and result.get("success") is not False \
        and not result.get("error")


def approve(session, business, action_id: str, user_id, version: Optional[str] = None) -> dict:
    """The tap. Executes exactly the stored payload — the version the owner
    saw, when they say which — at most once."""
    row = _scoped(session, business, action_id)
    action_type = row[1]
    problem = _feature_problem(business, action_type)
    if problem:
        session.rollback()
        raise ActionRefused(403, problem)
    if action_type == "send_outreach":
        return _approve_outreach(session, business, action_id, row, user_id, version)
    stored = row[2] if isinstance(row[2], str) else json.dumps(row[2])
    if version is not None and version != version_of(_loads(row[2])):
        session.rollback()
        raise ActionRefused(409, CHANGED)
    seen = "CAST(:seen AS jsonb)" if _is_postgres(session) else ":seen"

    moment = now()
    claimed = session.execute(text(
        "UPDATE aria_actions SET status = 'executing', approved_by = :user_id, "
        "approved_at = :now, updated_at = :now "
        "WHERE id = :id AND business_id = :business_id AND status = 'proposed' "
        f"AND expires_at > :now AND payload = {seen} RETURNING payload"),
        {"id": str(action_id), "business_id": str(business.id),
         "user_id": str(user_id) if user_id else None, "now": moment,
         "seen": stored}).fetchone()
    if claimed is None:
        session.rollback()
        _refuse_unclaimable(session, business, _scoped(session, business, action_id))
    # The claim is durable BEFORE anything leaves the building.
    session.commit()
    payload = _loads(claimed[0])

    if action_type == "send_invoice_chase" and payload.get("invoices"):
        reason = _combined_out_of_date(session, business, payload)
        if reason:
            _set(session, business, action_id, status="failed", error=reason, executed_at=now())
            session.commit()
            raise ActionRefused(409, reason)
    elif action_type == "send_invoice_chase":
        invoice = _invoice(session, business.id, payload["invoice_id"])
        reason = None
        if invoice is None:
            reason = "The invoice no longer exists; nothing was sent."
        elif (invoice[5] or "").lower() == "paid":
            reason = "Invoice already paid; nothing was sent."
        elif payload.get("automation") and _paused_by_reply(session, business, payload):
            # AUTO-2 (Codex review 1, P1 4): an automatic chase never goes to a
            # customer whose reply is waiting for the owner, however late the
            # pause was recorded. A card the owner taps is their decision.
            reason = "The customer has replied; automatic chasing is paused. Nothing was sent."
        elif not _still_owed(session, business.id, payload["invoice_id"]):
            # The FULL receivables rule, not only a literal "paid" status: a
            # recorded payment, a synced zero balance or a cancellation since
            # the card was drafted all stop it (Codex AUTO-1 review 1).
            reason = "This invoice is no longer owed; nothing was sent."
        elif "stage_was" in payload and _drifted(
                session, business.id, payload["invoice_id"], to=payload["to"],
                amount=payload["amount_owed"], stage_was=payload["stage_was"],
                last_chased_was=payload.get("last_chased_was")):
            reason = (f"This chase is out of date: invoice {invoice[1]} " + _drifted(
                session, business.id, payload["invoice_id"], to=payload["to"],
                amount=payload["amount_owed"], stage_was=payload["stage_was"],
                last_chased_was=payload.get("last_chased_was"))
                + ". Nothing was sent; ask Aria for a fresh one.")
        elif (invoice[6] or 0) >= int(payload["chase_stage"]) and not (
                int(payload["chase_stage"]) == 4 and payload.get("stage_was") == 4):
            # A final demand may be sent again (the owner said yes in chat);
            # the unchanged marks above prove this card is not a stale copy.
            # Codex review 1, finding 6: never resend an earlier stage or
            # move the invoice's stage backwards.
            reason = (f"This chase is out of date: the invoice has already had stage "
                      f"{invoice[6]}. Nothing was sent; ask Aria for a fresh one.")
        if reason:
            _set(session, business, action_id, status="failed", error=reason, executed_at=now())
            session.commit()
            raise ActionRefused(409, reason)

    try:
        result = _execute(session, business, action_type, payload)
    except Exception as exc:
        # We do not know whether the provider acted. Leave it `executing`
        # (never retried) and say so — not "failed" (review 1, finding 2).
        # A crash (BaseException) skips this and also leaves `executing`.
        logger.error("[AriaActions] %s %s outcome unknown: %s", action_type, action_id, exc)
        _set(session, business, action_id, error=f"Outcome unknown: {exc}")
        session.commit()
        return _view(_scoped(session, business, action_id))

    if not _succeeded(result):
        error = str(result.get("error") if isinstance(result, dict) else result) or "Failed"
        if _unknown_outcome(action_type, error):
            _set(session, business, action_id, error=f"Outcome unknown: {error}",
                 result=result if isinstance(result, dict) else None)
        else:
            _set(session, business, action_id, status="failed", error=error,
                 executed_at=now(), result=result if isinstance(result, dict) else None)
        session.commit()
        return _view(_scoped(session, business, action_id))

    if action_type in ("send_email", "send_invoice_chase"):
        _bookkeep_email(session, business, action_type, payload, result)
    _set(session, business, action_id, status="done", executed_at=now(), result=result)
    session.commit()
    return _view(_scoped(session, business, action_id))


def _is_active_owner(session, business, user_id, lock: bool = False) -> bool:
    """An active OWNER of this business (Codex OUT-6 hook review 1, P1):
    staff members and platform admins can see a card but never send outreach."""
    try:
        uuid.UUID(str(user_id))
    except ValueError:
        return False
    suffix = " FOR SHARE" if lock and _is_postgres(session) else ""
    return session.execute(text(
        "SELECT 1 FROM business_members WHERE business_id = :b AND user_id = :u "
        "AND role = 'owner' AND is_active = :t" + suffix),
        {"b": str(business.id), "u": str(user_id), "t": True}).fetchone() is not None


def _approve_outreach(session, business, action_id: str, row, user_id, version) -> dict:
    """OUT-6 (docs/OUT-6-TICKET.md, the agreed hook). Only an active owner's
    tap on the exact version they saw; never staff, a platform admin or a
    standing permission. Order:

      1. reply search in the campaign mailbox, outside any transaction;
      2. ONE transaction: every eligibility recheck and reservation
         (prepare_claim, which locks the action row last), then the
         proposed -> executing claim; any refusal or a lost claim rolls the
         whole of it back;
      3. commit, then the outreach dispatcher, which settles usage, the
         message and this card itself. Generic email sending and its
         bookkeeping are never used.
    """
    from services import outreach_send
    if not user_id or not _is_active_owner(session, business, user_id):
        session.rollback()
        raise ActionRefused(403, "Only the business owner can approve outreach.")
    payload = _loads(row[2])
    if not version or version != version_of(payload):
        session.rollback()
        raise ActionRefused(409, CHANGED)
    if payload.get("automation") or payload.get("authority_snapshot") or payload.get("raised_by"):
        session.rollback()
        raise ActionRefused(403, "Outreach is sent only when the owner approves it.")
    if row[3] != "proposed" or _is_expired(row[4]):
        _refuse_unclaimable(session, business, row)
    stored = row[2] if isinstance(row[2], str) else json.dumps(row[2])
    session.rollback()  # no transaction or pending write may span the search
    outreach_send.search_before_claim(session, business, action_id=str(action_id), payload=payload)
    try:
        moment = outreach_send.now()
        outreach_send.prepare_claim(session, business, action_id=str(action_id), payload=payload,
                                    user_id=str(user_id), version=version, moment=moment)
        # Again inside the claim, holding the membership row until commit, so
        # ownership removed during the search stops it.
        if not _is_active_owner(session, business, user_id, lock=True):
            raise ActionRefused(403, "Only the business owner can approve outreach.")
        seen = "CAST(:seen AS jsonb)" if _is_postgres(session) else ":seen"
        claimed = session.execute(text(
            "UPDATE aria_actions SET status = 'executing', approved_by = :user_id, "
            "approved_at = :now, updated_at = :now "
            "WHERE id = :id AND business_id = :business_id AND status = 'proposed' "
            f"AND expires_at > :now AND payload = {seen} RETURNING id"),
            {"id": str(action_id), "business_id": str(business.id), "user_id": str(user_id),
             "now": moment, "seen": stored}).fetchone()
        if claimed is None:
            raise ActionRefused(409, CHANGED)
        session.commit()  # claim + reservations durable before anything is sent
    except Exception:
        session.rollback()
        session.info.get("outreach_dispatch", {}).pop(str(action_id), None)
        raise
    outreach_send.dispatch(session, business, action_id=str(action_id), payload=payload)
    return _view(_scoped(session, business, action_id))


def _combined_out_of_date(session, business, payload) -> Optional[str]:
    """AUTO-3: the email must be exactly what was drafted. If ANY listed
    invoice is gone, settled or chased since, nothing is sent; the next run
    drafts a fresh one."""
    if payload.get("automation") and _paused_by_reply(session, business, payload):
        return "The customer has replied; automatic chasing is paused. Nothing was sent."
    for item in payload["invoices"]:
        invoice = _invoice(session, business.id, item["invoice_id"])
        if invoice is None:
            return f"Invoice {item['invoice_number']} no longer exists; nothing was sent."
        if (invoice[5] or "").lower() == "paid" or not _still_owed(session, business.id, item["invoice_id"]):
            return f"Invoice {item['invoice_number']} is no longer owed; nothing was sent."
        drift = _drifted(session, business.id, item["invoice_id"], to=payload["to"],
                         amount=item["amount"], stage_was=item["stage_was"],
                         last_chased_was=item.get("last_chased_was"))
        if drift:
            return (f"This chase is out of date: invoice {item['invoice_number']} {drift}. "
                    "Nothing was sent; ask Aria for a fresh one.")
    return None


def _execute(session, business, action_type: str, payload: dict) -> dict:
    import assistant_tools
    engine = session.get_bind()
    business_id = str(business.id)
    if action_type in ("send_email", "send_invoice_chase"):
        body = payload["body"] + "\n\n" + payload["sign_off"]
        args = {"to": payload["to"], "subject": payload["subject"], "body": body}
        if payload.get("account_id"):
            args["account_id"] = payload["account_id"]
        return assistant_tools._send_email(engine, business_id, args)
    if action_type == "create_calendar_event":
        return _run(assistant_tools.create_calendar_event(
            business_id, payload["title"], payload["start"], payload["end"],
            description=payload.get("description") or "",
            attendee_email=payload.get("attendee_email"),
            timezone=payload["timezone"], calendar_id=payload.get("calendar_id") or "primary"))
    return assistant_tools._create_task(
        engine, business_id, {"title": payload["title"],
                              "description": payload.get("description"),
                              "due_at": payload.get("due_at")})


def _run(coroutine):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    raise RuntimeError("approve() must run outside the event loop (the API runs it in a thread)")


def _bookkeep_email(session, business, action_type: str, payload: dict, result: dict) -> None:
    """Record the send in email_outbox and, for a chase, advance the invoice.
    The email has gone: a failure here is logged, never turned into a
    'failed' card that invites a second send."""
    try:
        if payload.get("account_id"):
            # The mailbox the card was bound to is the one that sent (AUTO-2).
            account = session.execute(text(
                "SELECT id FROM email_accounts WHERE business_id = :business_id AND id = :id"),
                {"business_id": str(business.id), "id": payload["account_id"]}).fetchone()
        else:
            account = session.execute(text(
                "SELECT id FROM email_accounts WHERE business_id = :business_id "
                "AND provider IN ('google', 'microsoft') ORDER BY created_at DESC LIMIT 1"),
                {"business_id": str(business.id)}).fetchone()
        sent_at = now()
        if account is not None:
            to_sql = "ARRAY[:to_email]" if _is_postgres(session) else ":to_email"
            session.execute(text(
                f"INSERT INTO email_outbox (id, business_id, email_account_id, to_emails, "
                f"subject, body_preview, status, invoice_id, chase_stage, "
                f"provider_message_id, sent_at) VALUES (:id, :business_id, :account_id, "
                f"{to_sql}, :subject, :preview, 'sent', :invoice_id, :chase_stage, "
                f":provider_id, :sent_at)"),
                {"id": str(uuid.uuid4()), "business_id": str(business.id),
                 "account_id": str(account[0]), "to_email": payload["to"],
                 "subject": payload["subject"], "preview": payload["body"][:200],
                 "invoice_id": payload.get("invoice_id"),
                 "chase_stage": payload.get("chase_stage"),
                 "provider_id": result.get("gmail_message_id"), "sent_at": sent_at})
        if action_type == "send_invoice_chase" and payload.get("invoices"):
            # AUTO-3: every listed invoice moves to its own next stage, never
            # backwards, and is marked chased now.
            for item in payload["invoices"]:
                session.execute(text(
                    "UPDATE invoices SET chase_stage = CASE WHEN COALESCE(chase_stage, 0) < :stage "
                    "THEN :stage ELSE chase_stage END, last_chased_at = :now, "
                    "updated_at = :now WHERE id = :invoice_id AND business_id = :business_id"),
                    {"stage": item["stage"], "now": sent_at,
                     "invoice_id": item["invoice_id"], "business_id": str(business.id)})
        elif action_type == "send_invoice_chase":
            # Never backwards (review 1, finding 6).
            session.execute(text(
                "UPDATE invoices SET chase_stage = CASE WHEN COALESCE(chase_stage, 0) < :stage "
                "THEN :stage ELSE chase_stage END, last_chased_at = :now, "
                "updated_at = :now WHERE id = :invoice_id AND business_id = :business_id"),
                {"stage": payload["chase_stage"], "now": sent_at,
                 "invoice_id": payload["invoice_id"], "business_id": str(business.id)})
        session.commit()
    except Exception as exc:
        session.rollback()
        logger.error("[AriaActions] sent, but recording it failed for %s: %s",
                     business.id, exc)


def edit(session, business, action_id: str, changes: dict) -> dict:
    row = _scoped(session, business, action_id)
    action_type, payload, status = row[1], _loads(row[2]), row[3]
    if status != "proposed" or _is_expired(row[4]):
        session.rollback()
        raise ActionRefused(409, f"Only a card awaiting approval can be edited (this one is {status}).")
    changes = dict(changes or {})
    if "sign_off" in changes:
        raise ActionRefused(422, "The sign-off cannot be changed.")
    unknown = set(changes) - _EDITABLE[action_type]
    if unknown:
        raise ActionRefused(422, f"These cannot be changed: {', '.join(sorted(unknown))}.")
    merged = {**payload, **changes}
    tz_name = payload.get("timezone") or getattr(business, "timezone", None) or "Europe/London"
    if action_type == "send_invoice_chase":
        subject = str(merged.get("subject") or "").strip()
        body = str(merged.get("body") or "").strip()
        if not subject or not body:
            raise ActionRefused(422, "A chase needs a subject and a body.")
        new_payload = {**payload, "subject": subject, "body": body}
    elif action_type == "send_outreach":
        # Never rebuilt: a rebuild would mint a new unsubscribe link and
        # rebind the recipient. Only the words change; the claim rechecks.
        subject = str(merged.get("subject") or "").strip()
        body = str(merged.get("body") or "").strip()
        if not subject or "\r" in subject or "\n" in subject or len(subject) > 998:
            raise ActionRefused(422, "An outreach email needs a one-line subject.")
        if not body or len(body) > 20000:
            raise ActionRefused(422, "An outreach email needs a body (at most 20,000 characters).")
        new_payload = {**payload, "subject": subject, "body": body}
    else:
        new_payload = _build(session, business, action_type, merged, None, tz_name)
        if "sign_off" in payload:
            new_payload["sign_off"] = payload["sign_off"]
    session.execute(text(
        f"UPDATE aria_actions SET payload = {_json_param(session)}, updated_at = :now "
        "WHERE id = :id AND business_id = :business_id AND status = 'proposed'"),
        {"payload": json.dumps(new_payload), "now": now(), "id": str(action_id),
         "business_id": str(business.id)})
    session.commit()
    return _view(_scoped(session, business, action_id))


def dismiss(session, business, action_id: str) -> dict:
    """Conditional on `proposed`: if approval won the race, this is a
    conflict and the action carries on (Codex review 1, finding 4)."""
    _scoped(session, business, action_id)
    gone = session.execute(text(
        "UPDATE aria_actions SET status = 'dismissed', updated_at = :now "
        "WHERE id = :id AND business_id = :business_id AND status = 'proposed' RETURNING id"),
        {"now": now(), "id": str(action_id), "business_id": str(business.id)}).fetchone()
    if gone is None:
        session.rollback()
        current = _scoped(session, business, action_id)[3]
        raise ActionRefused(409, f"This card is already {current}.")
    session.commit()
    return _view(_scoped(session, business, action_id))


def get(session, business, action_id: str) -> dict:
    return _view(_scoped(session, business, action_id))


def list_open(session, business) -> list:
    rows = session.execute(text(
        f"SELECT {_COLUMNS} FROM aria_actions WHERE business_id = :business_id "
        "AND status = 'proposed' AND expires_at > :now ORDER BY created_at DESC"),
        {"business_id": str(business.id), "now": now()}).fetchall()
    return [_view(r) for r in rows]


def propose_from_chat(business_id: str, user_id, action_type: str, args: dict, *,
                      owner_name: Optional[str] = None,
                      timezone: Optional[str] = None) -> dict:
    """The chat boundary: what the model's tool call becomes."""
    if action_type not in CHAT_ACTION_TYPES:
        return {"error": f"{action_type} cannot be proposed from chat."}
    from db import get_session_context
    with get_session_context() as session:
        business = load_business(session, business_id)
        if business is None:
            return {"error": "Business not found."}
        result = propose(session, business, user_id, action_type, args,
                         owner_name=owner_name, timezone=timezone)
    if "proposal" not in result:
        return result
    return {"proposal": result["proposal"], "message": SENT_MESSAGE}
