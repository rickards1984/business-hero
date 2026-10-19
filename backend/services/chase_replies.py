"""AUTO-2 — Aria watches for replies to invoice chases.

docs/AUTO-2-TICKET.md; Mike, 19 Oct 2026: flag the owner on any reply; when a
customer says they've paid, show it and close chasing.

A reply is an email in the business's synced inbox from the exact address of
a customer it chased (automatically or by a tapped card) in the last 60 days,
received after that chase. Any reply pauses automatic chasing of that
customer until the owner decides: "resume" or "stop" (stop that invoice for
good). Aria labels the reply, but the label never sends anything and never
marks an invoice paid — money stays with the owner and the accounts software.

Automatic chasing also waits until the sending mailbox's inbox has been read
completely in the last three hours (`inbox_ready`), so an unseen reply cannot
be chased over.
"""

import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
from typing import Callable, Iterable, Optional

from sqlalchemy import bindparam, text

logger = logging.getLogger(__name__)

REPLY_WINDOW_DAYS = 60
FRESH_WITHIN = timedelta(hours=3)
GMAIL_PAGE = 50
CATEGORIES = ("paid", "promise", "dispute", "question", "other", "unknown")
DECISIONS = {"resume": "resumed", "stop": "stopped"}


def now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _loads(value):
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}


def _address(value) -> str:
    return parseaddr(str(value or ""))[1].strip().lower()


def _is_postgres(session) -> bool:
    return session.get_bind().dialect.name == "postgresql"


# ------------------------------------------------------------- mailboxes ---

def default_mailbox(session, business_id: str) -> Optional[str]:
    """The business's default sending mailbox: the one marked default, or the
    only one connected. Never chosen by recency (OUT-2 §3). None when there
    is no mailbox, or several and none marked default."""
    rows = session.execute(text(
        "SELECT id, is_default FROM email_accounts WHERE business_id = :b "
        "AND provider IN ('google', 'microsoft')"), {"b": str(business_id)}).fetchall()
    marked = [str(r[0]) for r in rows if r[1]]
    if len(marked) == 1:
        return marked[0]
    if not marked and len(rows) == 1:
        return str(rows[0][0])
    return None


def sync_complete(provider: str, listed_ids: Iterable[str], fetched_ids: Iterable[str],
                  known_ids: Iterable[str], page_size: int = GMAIL_PAGE) -> bool:
    """Could this sync have missed a message? Microsoft's delta is complete by
    construction. Gmail lists only the newest `page_size`: it is complete only
    if every listed message was fetched AND either the inbox fitted in one
    page or the page reached a message already stored before this sync."""
    listed, fetched, known = list(listed_ids), set(fetched_ids), set(known_ids)
    if any(mid not in fetched for mid in listed):
        return False
    if provider == "microsoft":
        return True
    if provider != "google":
        return False
    return len(listed) < page_size or any(mid in known for mid in listed)


def completed_cursor(session, account, result, started_at: datetime) -> dict:
    """The cursor to store after a sync, with an honest `complete` flag. Called
    after the messages are stored: a listed message whose row was created
    before this sync started was already known."""
    cursor = {k: v for k, v in (result.cursor or {}).items() if k != "complete"}
    fetched = [m.provider_message_id for m in result.messages]
    listed = list(getattr(result, "listed_ids", None) or fetched)
    known: set = set()
    if listed:
        rows = session.execute(text(
            "SELECT provider_message_id, created_at FROM email_messages "
            "WHERE email_account_id = :a AND provider_message_id IN :ids"
        ).bindparams(bindparam("ids", expanding=True)),
            {"a": str(account.id), "ids": listed}).fetchall()
        start = _parse(started_at)
        known = {mid for mid, created in rows if _parse(created) and _parse(created) < start}
    cursor["complete"] = sync_complete(getattr(account, "provider", ""), listed, fetched, known)
    return cursor


def inbox_ready(session, business, account_id: str, moment: datetime) -> Optional[str]:
    """None when the mailbox's inbox was read completely and without error
    within FRESH_WITHIN of `moment`; otherwise "inbox_not_fresh"."""
    row = session.execute(text(
        "SELECT s.cursor, s.last_synced_at, s.sync_status, s.last_error "
        "FROM email_sync_states s JOIN email_accounts a ON a.id = s.email_account_id "
        "WHERE s.email_account_id = :a AND a.business_id = :b"),
        {"a": str(account_id), "b": str(business.id)}).fetchone()
    if row is None:
        return "inbox_not_fresh"
    cursor, synced, status, error = row
    synced = _parse(synced)
    if (synced is None or moment - synced > FRESH_WITHIN or error
            or (status or "").lower() == "error" or _loads(cursor).get("complete") is not True):
        return "inbox_not_fresh"
    return None


# ------------------------------------------------------------- matching ---

def _chases(session, business, since: datetime) -> list:
    """Every chase that went (or may have) since `since`:
    (customer, invoice_id, invoice_number, sent_at, thread_id)."""
    rows = session.execute(text(
        "SELECT a.payload, a.result, a.created_at, a.approved_at, a.executed_at, i.invoice_number "
        "FROM aria_actions a LEFT JOIN invoices i ON i.business_id = a.business_id "
        "AND CAST(i.id AS TEXT) = " + ("a.payload->>'invoice_id' " if _is_postgres(session)
                                       else "json_extract(a.payload, '$.invoice_id') ") +
        "WHERE a.business_id = :b AND a.action_type = 'send_invoice_chase' "
        "AND a.status IN ('done', 'executing') AND a.created_at >= :since"),
        {"b": str(business.id), "since": since}).fetchall()
    out = []
    for payload, result, created, approved, executed, number in rows:
        p, r = _loads(payload), _loads(result)
        sent_at = _parse(executed) or _parse(approved) or _parse(created)
        out.append((_address(p.get("to")), str(p.get("invoice_id") or ""), number, sent_at,
                    r.get("gmail_thread_id")))
    return out


def _which_invoices(chases: list, thread, words: str) -> list:
    """Same thread first; then an invoice number named in the subject or
    preview; otherwise every invoice of theirs that was chased."""
    ordered: list = []
    for _, iid, _, _, _ in chases:
        if iid and iid not in ordered:
            ordered.append(iid)
    if thread:
        by_thread = [iid for _, iid, _, _, t in chases if t and t == thread]
        if by_thread:
            return list(dict.fromkeys(by_thread))
    named = [iid for _, iid, number, _, _ in chases
             if number and re.search(rf"(?<![\w-]){re.escape(str(number))}(?![\w-])", words, re.I)]
    if named:
        return list(dict.fromkeys(named))
    return ordered


def _read(classify: Callable, text_: str) -> tuple:
    try:
        verdict = classify(text_) or {}
        category = str(verdict.get("category") or "").strip().lower()
        summary = str(verdict.get("summary") or "").strip()[:300] or None
    except Exception as exc:  # the reply is still flagged; it still pauses
        logger.warning("[ChaseReplies] could not read a reply: %s", exc)
        return "unknown", None
    return (category if category in CATEGORIES else "unknown"), summary


def scan(session, business, *, classify: Callable) -> list:
    """Find replies to chases in the synced inbox, label and record them.
    Returns only the replies new in this scan."""
    moment = now()
    since = moment - timedelta(days=REPLY_WINDOW_DAYS)
    chases = [c for c in _chases(session, business, since) if c[0] and c[3]]
    if not chases:
        return []
    by_customer: dict = {}
    for chase in chases:
        by_customer.setdefault(chase[0], []).append(chase)
    own = {_address(r[0]) for r in session.execute(text(
        "SELECT email_address FROM email_accounts WHERE business_id = :b"),
        {"b": str(business.id)}).fetchall()}
    earliest = min(c[3] for c in chases)
    rows = session.execute(text(
        "SELECT m.id, m.from_email, m.subject, m.snippet, m.body_text, m.provider_thread_id, "
        "m.received_at FROM email_messages m WHERE m.business_id = :b AND m.received_at >= :since "
        "AND NOT EXISTS (SELECT 1 FROM chase_replies r WHERE r.business_id = m.business_id "
        "AND r.email_message_id = m.id)"),
        {"b": str(business.id), "since": earliest}).fetchall()
    new = []
    for mid, sender, subject, snippet, body, thread, received in rows:
        who = _address(sender)
        received = _parse(received)
        mine = by_customer.get(who)
        if not who or who in own or not mine or received is None:
            continue
        before = [c for c in mine if c[3] <= received]
        if not before:
            continue
        words = " ".join(x for x in (subject, snippet) if x)
        invoices = _which_invoices(before, thread, words)
        category, summary = _read(classify, "\n".join(x for x in (subject, snippet, body) if x))
        rid = str(uuid.uuid4())
        jsonb = "CAST(:inv AS jsonb)" if _is_postgres(session) else ":inv"
        inserted = session.execute(text(
            "INSERT INTO chase_replies (id, business_id, email_message_id, customer_email, "
            f"invoice_ids, category, summary, status, created_at, updated_at) VALUES (:id, :b, "
            f":m, :c, {jsonb}, :cat, :sum, 'open', :now, :now) "
            "ON CONFLICT (business_id, email_message_id) DO NOTHING RETURNING id"),
            {"id": rid, "b": str(business.id), "m": str(mid), "c": who,
             "inv": json.dumps(invoices), "cat": category, "sum": summary,
             "now": moment}).fetchone()
        session.commit()
        if inserted is not None:
            new.append(_get(session, business, rid))
    if new:
        logger.info("[ChaseReplies] %s: %d new repl%s", business.id, len(new),
                    "y" if len(new) == 1 else "ies")
    return new


# ------------------------------------------------------------- the owner ---

_COLUMNS = ("id, email_message_id, customer_email, invoice_ids, category, summary, status, "
            "resolved_at, created_at")


def _view(session, business, row) -> dict:
    rid, mid, who, invoices, category, summary, status, resolved_at, created = row
    ids = [str(i) for i in (_loads(invoices) or [])]
    numbers = []
    if ids:
        found = dict(session.execute(text(
            "SELECT CAST(id AS TEXT), invoice_number FROM invoices WHERE business_id = :b "
            "AND CAST(id AS TEXT) IN :ids").bindparams(bindparam("ids", expanding=True)),
            {"b": str(business.id), "ids": ids}).fetchall())
        numbers = [found[i] for i in ids if found.get(i)]
    iso = lambda v: _parse(v).isoformat() if _parse(v) else None  # noqa: E731
    return {"id": str(rid), "email_message_id": str(mid) if mid else None,
            "customer_email": who, "invoice_ids": ids, "invoice_numbers": numbers,
            "category": category, "summary": summary, "status": status,
            "resolved_at": iso(resolved_at), "created_at": iso(created)}


def _get(session, business, reply_id: str) -> dict:
    row = session.execute(text(
        f"SELECT {_COLUMNS} FROM chase_replies WHERE id = :id AND business_id = :b"),
        {"id": str(reply_id), "b": str(business.id)}).fetchone()
    return _view(session, business, row) if row else None


def open_replies(session, business) -> list:
    rows = session.execute(text(
        f"SELECT {_COLUMNS} FROM chase_replies WHERE business_id = :b AND status = 'open' "
        "ORDER BY created_at DESC"), {"b": str(business.id)}).fetchall()
    return [_view(session, business, r) for r in rows]


def blocked(session, business) -> tuple:
    """(customers with a reply awaiting the owner, invoices the owner stopped)."""
    rows = session.execute(text(
        "SELECT customer_email, invoice_ids, status FROM chase_replies WHERE business_id = :b "
        "AND status IN ('open', 'stopped')"), {"b": str(business.id)}).fetchall()
    customers, invoices = set(), set()
    for who, ids, status in rows:
        if status == "open":
            customers.add(_address(who))
        else:
            invoices.update(str(i) for i in (_loads(ids) or []))
    session.rollback()
    return customers, invoices


def resolve(session, business, reply_id: str, user_id, decision: str) -> dict:
    """The owner's decision on an open reply: "resume" or "stop"."""
    if decision not in DECISIONS:
        raise ValueError(f"Unknown decision: {decision}")
    try:
        uuid.UUID(str(reply_id))
    except ValueError:
        raise LookupError("Reply not found")
    lock = " FOR UPDATE" if _is_postgres(session) else ""
    row = session.execute(text(
        "SELECT status FROM chase_replies WHERE id = :id AND business_id = :b" + lock),
        {"id": str(reply_id), "b": str(business.id)}).fetchone()
    if row is None:
        session.rollback()
        raise LookupError("Reply not found")
    if row[0] != "open":
        session.rollback()
        raise ValueError(f"This reply was already dealt with ({row[0]}).")
    moment = now()
    session.execute(text(
        "UPDATE chase_replies SET status = :s, resolved_by = :u, resolved_at = :now, "
        "updated_at = :now WHERE id = :id AND business_id = :b AND status = 'open'"),
        {"s": DECISIONS[decision], "u": str(user_id) if user_id else None, "now": moment,
         "id": str(reply_id), "b": str(business.id)})
    session.commit()
    return _get(session, business, reply_id)


# ------------------------------------------------------------- reading ---

_PROMPT = (
    "You read a customer's reply to an invoice payment reminder for a small UK business. "
    "Answer ONLY with JSON: {\"category\": one of \"paid\" (they say they have already paid), "
    "\"promise\" (they say they will pay, maybe with a date), \"dispute\" (they dispute the "
    "invoice or the amount), \"question\" (they ask something), \"other\"; \"summary\": one "
    "short sentence for the business owner, in British English}. Never invent facts that "
    "are not in the email.")


def classify_with_model(text_: str) -> dict:
    """The production reader. Any failure raises, and the reply is then
    flagged as "unknown" (it still pauses chasing)."""
    import os
    from openai import OpenAI
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("no model key configured")
    client = OpenAI(api_key=key, timeout=30.0, max_retries=1)
    response = client.chat.completions.create(
        model=os.getenv("ARIA_REPLY_MODEL", "gpt-4o-mini"),
        messages=[{"role": "system", "content": _PROMPT},
                  {"role": "user", "content": text_[:4000]}],
        response_format={"type": "json_object"}, temperature=0)
    return json.loads(response.choices[0].message.content or "{}")
