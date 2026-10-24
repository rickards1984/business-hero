"""AUTO-2 — Aria watches for replies to invoice chases.

docs/AUTO-2-TICKET.md; Mike, 19 Oct 2026: flag the owner on any reply; when a
customer says they've paid, show it and close chasing.

A reply is an email in the business's synced inbox from the exact address of
a customer it chased (automatically or by a tapped card) in the last 60 days,
received after that chase. Any reply pauses automatic chasing of that
customer until the owner decides: "resume" or "stop" (stop that invoice for
good). Aria labels the reply, but the label never sends anything and never
marks an invoice paid — money stays with the owner and the accounts software.

Replies are found by SEARCHING the mailboxes themselves (Gmail search,
Microsoft Graph filter) for mail from chased customers since their chase —
complete by construction, not inferred from the general inbox sync (Codex
AUTO-2 review 1). Every automatic chase does its own search of every mailbox
that chased that customer, plus the one it will send from, immediately
before sending; if any search fails, it does not send.
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
SENDERS_PER_SEARCH = 20
CATEGORIES = ("paid", "promise", "dispute", "question", "other", "unknown")
DECISIONS = {"resume": "resumed", "stop": "stopped"}


class ReplyCheckFailed(Exception):
    """A mailbox could not be searched: nothing may be chased on the strength
    of it."""


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


# ------------------------------------------------------------- searching ---

def lookup_with_provider(session, account_id: str, senders: list, since: datetime) -> list:
    """Search one connected mailbox for mail from `senders` since `since`.
    Returns the provider's messages; raises if the search is incomplete."""
    from sqlmodel import select
    from models import EmailAccount
    from app.email.service import get_provider_for_account
    account = session.exec(select(EmailAccount).where(
        EmailAccount.id == uuid.UUID(str(account_id)))).first()
    if account is None:
        raise ReplyCheckFailed("mailbox not found")
    return get_provider_for_account(account).search_from(
        account=account, senders=list(senders), since=since)


def _mailboxes(session, business) -> tuple:
    """(every connected mailbox, the default or None)."""
    rows = session.execute(text(
        "SELECT id FROM email_accounts WHERE business_id = :b "
        "AND provider IN ('google', 'microsoft')"), {"b": str(business.id)}).fetchall()
    return [str(r[0]) for r in rows], default_mailbox(session, business.id)


# OUT-7 matches replies by thread, so these headers are kept, verbatim and
# bounded; nothing else from the provider's header map is stored.
_THREAD_HEADERS = ("Message-ID", "In-Reply-To", "References")
_HEADER_LIMIT = 4000


def _thread_headers(raw) -> dict:
    if not isinstance(raw, dict):
        return {}
    lower = {str(k).lower(): v for k, v in raw.items()}
    return {name: str(lower[name.lower()])[:_HEADER_LIMIT]
            for name in _THREAD_HEADERS if lower.get(name.lower())}


def _store(session, business, account_id: str, messages) -> None:
    """Keep what the search found, once per mailbox and provider message.
    Then, once committed, tell outreach that storage completed (OUT-7). That
    notification can never break chasing."""
    moment = now()
    pg = _is_postgres(session)
    for m in messages:
        exists = session.execute(text(
            "SELECT 1 FROM email_messages WHERE business_id = :b AND email_account_id = :a "
            "AND provider_message_id = :m"),
            {"b": str(business.id), "a": str(account_id), "m": m.provider_message_id}).fetchone()
        if exists:
            continue
        to = [str(x) for x in (getattr(m, "to_emails", None) or [])]
        cc = [str(x) for x in (getattr(m, "cc_emails", None) or [])]
        headers = json.dumps(_thread_headers(getattr(m, "raw_headers", None)))
        session.execute(text(
            "INSERT INTO email_messages (id, business_id, email_account_id, provider_message_id, "
            "provider_thread_id, folder, from_email, from_name, to_emails, cc_emails, raw_headers, "
            "subject, snippet, body_text, received_at, created_at, updated_at) VALUES (:id, :b, :a, "
            ":m, :t, 'INBOX', :f, :fn, :to, :cc, "
            + ("CAST(:h AS jsonb)" if pg else ":h") +
            ", :s, :sn, :body, :at, :now, :now)"),
            {"id": str(uuid.uuid4()), "b": str(business.id), "a": str(account_id),
             "m": m.provider_message_id, "t": getattr(m, "provider_thread_id", None),
             "f": getattr(m, "from_email", None), "fn": getattr(m, "from_name", None),
             "to": to if pg else json.dumps(to), "cc": cc if pg else json.dumps(cc), "h": headers,
             "s": getattr(m, "subject", None), "sn": getattr(m, "snippet", None),
             "body": getattr(m, "body_text", None), "at": getattr(m, "received_at", None),
             "now": moment})
    session.commit()
    try:
        from app.email import service
        service.outreach_storage_completed(session, business)
    except Exception as exc:  # outreach must never stop a chase decision
        try:
            session.rollback()
        except Exception:  # noqa: BLE001
            pass
        logger.warning("[ChaseReplies] outreach notification failed for %s: %s",
                       business.id, type(exc).__name__)


def find_replies(session, business, *, lookup: Callable, classify: Callable,
                 customers: Optional[Iterable[str]] = None) -> list:
    """Search the mailboxes for mail from chased customers (or only
    `customers`), store it, and record the replies. Each customer's search
    covers every mailbox any of their recent chases went from — all
    mailboxes when a chase did not record one — and the default mailbox,
    which the next chase would go from. Raises ReplyCheckFailed if any
    needed search fails."""
    moment = now()
    window = moment - timedelta(days=REPLY_WINDOW_DAYS)
    chases = [c for c in _chases(session, business, window) if c[0] and c[3]]
    accounts = _chase_accounts(session, business, window)
    everything, default = _mailboxes(session, business)
    wanted = [_address(c) for c in customers] if customers is not None else \
        sorted({c[0] for c in chases})
    plan: dict = {}
    for who in wanted:
        if not who:
            continue
        mine = [c for c in chases if c[0] == who]
        since = min((c[3] for c in mine), default=window)
        # Every mailbox their chases went from, KNOWN OR NOT — a mailbox since
        # disconnected stays in the plan and fails it below (Codex AUTO-2
        # review 2) — plus every connected mailbox when a chase recorded none,
        # plus the default the next chase goes from.
        history = set(accounts.get(who, set()))
        boxes = {b for b in history if b}
        if None in history:
            boxes |= set(everything)
        if default:
            boxes.add(default)
        for acct in boxes:
            entry = plan.setdefault(acct, {"senders": [], "since": since})
            entry["senders"].append(who)
            entry["since"] = min(entry["since"], since)
    failures = []
    connected = set(everything)
    for acct, entry in sorted(plan.items()):
        if acct not in connected:
            # Not this business's connected mailbox (disconnected, or never
            # its own): its coverage is unavailable, and it is never searched.
            failures.append(f"mailbox {acct} is not connected")
            continue
        senders = sorted(set(entry["senders"]))
        for i in range(0, len(senders), SENDERS_PER_SEARCH):
            try:
                found = lookup(session, acct, senders[i:i + SENDERS_PER_SEARCH], entry["since"])
            except Exception as exc:
                session.rollback()
                failures.append(f"mailbox {acct} could not be searched: {exc}")
                break
            _store(session, business, acct, found or [])
    # Replies that WERE found are recorded before any failure is reported, so
    # they pause chasing and reach the owner either way.
    new = scan(session, business, classify=classify)
    if failures:
        raise ReplyCheckFailed("; ".join(failures))
    return new


def _chase_accounts(session, business, since: datetime) -> dict:
    """customer -> the mailboxes their chases went from (None: not recorded)."""
    rows = session.execute(text(
        "SELECT payload FROM aria_actions WHERE business_id = :b "
        "AND action_type = 'send_invoice_chase' AND status IN ('done', 'executing') "
        "AND created_at >= :since"), {"b": str(business.id), "since": since}).fetchall()
    out: dict = {}
    for (payload,) in rows:
        p = _loads(payload)
        out.setdefault(_address(p.get("to")), set()).add(
            str(p["account_id"]) if p.get("account_id") else None)
    return out


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
