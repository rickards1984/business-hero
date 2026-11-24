"""ARIA-1a — Aria sorts the inbox (docs/ARIA-PROACTIVE-TICKETS.md, ARIA-1 §1–2).

One sorting pass, used by the background sync and by "Sort now":

1. **Free filters** first, with no AI, for **bulk mail only**: spam, Gmail
   promotions, social and forum notifications, mailing lists and out-of-office
   replies. A reply to the business's outreach is left to the outreach scanner.
   - **Never on the sender alone** (Codex ARIA-1a review 1, finding 1). A
     booking form's no-reply address, a contact-form plugin sending from the
     business's own address, or the owner forwarding "Fwd: Complaint" into
     the inbox are real mail.
   - **Never anything that might matter** (finding 2). A subject or preview
     with a money, enquiry, complaint, booking or account signal always goes
     to the AI, even when Gmail calls it a promotion.
2. **The AI** sorts the rest, in batches, into Mike's categories, costed to
   the business as `classify` (essential: never paused).

**One pass at a time per business** (finding 3). On PostgreSQL that's a
session advisory lock held on its own connection for the pass, so two app
instances, or the background and "Sort now", never both pay for the same mail.
And a stamp never overwrites mail already sorted.

**One rule for categories** (finding 4). `normalise` (Python), `NORM_SQL`
(any database) and the page's copy read the same stored value the same way:
trimmed, lower case, spaces and hyphens as underscores, older values through
`LEGACY`, anything else as FYI. Empty or NULL means not sorted, and is never
important.
"""
import json
import logging
import re
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import bindparam, text

logger = logging.getLogger(__name__)

CATEGORIES = {
    "money": "Money",
    "new_enquiry": "New enquiry",
    "customer": "Customer",
    "complaint": "Complaint",
    "supplier": "Supplier",
    "scheduling": "Scheduling",
    "fyi": "FYI",
    "junk": "Junk",
}
IMPORTANT = frozenset({"money", "new_enquiry", "customer", "complaint"})
IMPORTANT_PRIORITY = 4

# What the sorter wrote before ARIA-1, and the labels some readers expected.
LEGACY = {
    "action_required": "customer", "awaiting_reply": "customer", "finance": "money", "marketing": "junk",
    "spam": "junk", "newsletter": "fyi",
}


def _key(value) -> str:
    return re.sub(r"[ \-]", "_", str(value if value is not None else "").strip().lower())


def normalise(value) -> str:
    """Any stored or answered category, as one of Mike's (FYI if unknown)."""
    key = _key(value)
    if key in CATEGORIES:
        return key
    return LEGACY.get(key, "fyi")


def is_sorted_value(value) -> bool:
    return bool(_key(value))


def is_important(category, priority) -> bool:
    """Money, New enquiry, Customer or Complaint, or priority 4 and above;
    never Junk; never mail not sorted (NULL or empty category)."""
    if not is_sorted_value(category):
        return False
    cat = normalise(category)
    if cat in IMPORTANT:
        return True
    try:
        return cat != "junk" and priority is not None and int(priority) >= IMPORTANT_PRIORITY
    except (TypeError, ValueError):
        return False


# The same reading in SQL (SQLite and PostgreSQL both have lower, trim, replace).
NORM_SQL = "replace(replace(lower(trim(ai_category)), ' ', '_'), '-', '_')"


def _values_reading_as(categories) -> list:
    out = set(categories)
    out.update(k for k, v in LEGACY.items() if v in categories)
    return sorted(out)


def _quoted(values) -> str:
    return ", ".join(f"'{v}'" for v in values)


def category_sql(category: str) -> str:
    """A SQL condition on email_messages: the stored category reads as this
    one, exactly as `normalise` reads it (unknown values read as FYI)."""
    cat = normalise(category)
    sorted_ = f"(ai_category IS NOT NULL AND {NORM_SQL} <> '')"
    if cat != "fyi":
        return f"({sorted_} AND {NORM_SQL} IN ({_quoted(_values_reading_as({cat}))}))"
    others = _values_reading_as(set(CATEGORIES) - {"fyi"})
    return f"({sorted_} AND {NORM_SQL} NOT IN ({_quoted(others)}))"


IMPORTANT_SQL = (f"(ai_category IS NOT NULL AND {NORM_SQL} <> '' AND ("
                 f"{NORM_SQL} IN ({_quoted(_values_reading_as(IMPORTANT))}) OR "
                 f"(coalesce(ai_priority, 0) >= {IMPORTANT_PRIORITY} AND "
                 f"{NORM_SQL} NOT IN ({_quoted(_values_reading_as({'junk'}))}))))")


# ---------------------------------------------------------- free filters ---

# Anything that might need the owner: never filtered free, whatever the sender
# or Gmail's label (review 1, finding 2). Read in the subject and the preview.
_MATTERS = re.compile(
    r"(£\s?\d|\b(invoice|invoices|payment|payments|paid|payout|remittance|receipt|statement|overdue|refund|"
    r"direct debit|mandate|bank(?!\s+holiday)|transfer|bacs|credit note|purchase order|account|tax|vat|hmrc|"
    r"action required|urgent|enquiry|enquiries|inquiry|quote|quotation|estimate|complaint|unhappy|"
    r"booking|appointment|order|contract|deposit|balance)\b)", re.I)
# Senders whose mail is always money or tax, whatever its wording.
_MONEY_SENDERS = re.compile(r"@([a-z0-9-]+\.)*(hmrc\.gov\.uk|gov\.uk|gocardless\.com|stripe\.com|paypal\.(com|co\.uk)|"
                            r"xero\.com|quickbooks\.com|intuit\.com|sumup\.com|squareup\.com|wise\.com|"
                            r"starlingbank\.com|monzo\.com|tide\.co|barclays\.(com|co\.uk)|hsbc\.(com|co\.uk)|"
                            r"natwest\.com|lloydsbank\.(com|co\.uk)|santander\.co\.uk)$", re.I)


def _load(value, default):
    if isinstance(value, str):
        try:
            return json.loads(value or "null") or default
        except ValueError:
            return default
    return value or default


def skip(row, outreach_threads: set) -> Optional[tuple]:
    """(category, priority, why) when this mail is bulk and needs no AI,
    else None. Conservative: an unsure case goes to the AI."""
    labels = {str(x).upper() for x in _load(row.labels, [])}
    headers = {str(k).lower(): str(v) for k, v in _load(row.raw_headers, {}).items()}
    sender = (row.from_email or "").strip().lower()
    if row.provider_thread_id and row.provider_thread_id in outreach_threads:
        return "fyi", 1, "A reply to your outreach: see Outreach → Replies"
    if "SPAM" in labels:
        return "junk", 1, "Marked as spam by your email provider"
    if _MONEY_SENDERS.search(sender) or _MATTERS.search(f"{row.subject or ''}\n{row.snippet or ''}"):
        return None                       # might matter: the AI sorts it
    if "CATEGORY_PROMOTIONS" in labels:
        return "junk", 1, "A promotion"
    if "CATEGORY_SOCIAL" in labels or "CATEGORY_FORUMS" in labels:
        return "fyi", 1, "A social or forum notification"
    if "list-unsubscribe" in headers or "list-id" in headers or \
            headers.get("precedence", "").lower() in ("bulk", "list", "junk"):
        return "fyi", 1, "A newsletter or mailing list"
    if headers.get("auto-submitted", "").lower() == "auto-replied":
        return "fyi", 1, "An automatic reply (out of office)"
    return None


# ------------------------------------------------- one pass per business ---

_local_locks: dict = {}
_local_guard = threading.Lock()


@contextmanager
def _one_pass(session, business_id: str):
    """Yields True when this pass may run, False when another is already
    sorting this business's mail (here, or in another app instance)."""
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        conn = bind.connect()           # its own connection: the lock outlives the pass's commits
        try:
            got = conn.execute(text("SELECT pg_try_advisory_lock(hashtext('inbox_sort:' || :b))"),
                               {"b": business_id}).scalar()
            try:
                yield bool(got)
            finally:
                if got:
                    conn.execute(text("SELECT pg_advisory_unlock(hashtext('inbox_sort:' || :b))"),
                                 {"b": business_id})
        finally:
            conn.close()
        return
    with _local_guard:
        lock = _local_locks.setdefault(business_id, threading.Lock())
    got = lock.acquire(blocking=False)
    try:
        yield got
    finally:
        if got:
            lock.release()


# ------------------------------------------------------------- the pass ---

def _now():
    return datetime.now(timezone.utc)


def _stamp(session, business_id, mid, category, priority, summary, action=None) -> bool:
    """Only mail still unsorted: never overwrites a classification."""
    done = session.execute(text("""
        UPDATE email_messages
        SET ai_category = :category, ai_priority = :priority, ai_summary = :summary,
            ai_suggested_action = :action, ai_analyzed_at = :now
        WHERE id = :id AND business_id = :business_id AND ai_analyzed_at IS NULL
    """), {"category": category, "priority": priority, "summary": summary, "action": action, "now": _now(),
           "id": str(mid), "business_id": str(business_id)})
    return bool(done.rowcount)


def _waiting(session, business_id) -> int:
    return int(session.execute(text(
        "SELECT COUNT(*) FROM email_messages WHERE business_id = :b AND ai_analyzed_at IS NULL"),
        {"b": str(business_id)}).scalar() or 0)


def sort_pending(session, business_id, *, limit: int = 30, batch_size: int = 10) -> dict:
    """Sort up to `limit` of the business's unsorted mail, newest first.

    Returns {"sorted", "skipped", "waiting", "failed", "busy"}:
    - `sorted`: what the AI sorted;
    - `skipped`: what the free filters sorted;
    - `waiting`: what is still unsorted;
    - `failed`: an AI batch failed or left some of its mail out; that mail
      stays unsorted and is tried again next pass;
    - `busy`: another pass was already sorting this business's mail, so this
      one did nothing.
    """
    bid = str(business_id)
    with _one_pass(session, bid) as mine:
        if not mine:
            return {"sorted": 0, "skipped": 0, "waiting": _waiting(session, bid), "failed": False, "busy": True}
        out = _sort(session, bid, limit=limit, batch_size=batch_size)
        out["busy"] = False
        return out


def _sort(session, bid: str, *, limit: int, batch_size: int) -> dict:
    from app.email import service
    from services import profit_guard
    rows = session.execute(text("""
        SELECT id, from_email, from_name, subject, snippet, received_at, labels, raw_headers, provider_thread_id
        FROM email_messages
        WHERE business_id = :b AND ai_analyzed_at IS NULL
        ORDER BY received_at DESC
        LIMIT :limit
    """), {"b": bid, "limit": int(limit)}).fetchall()
    if not rows:
        return {"sorted": 0, "skipped": 0, "waiting": 0, "failed": False}
    threads = sorted({r.provider_thread_id for r in rows if r.provider_thread_id})
    outreach = set()
    if threads:
        outreach = {str(r[0]) for r in session.execute(text(
            "SELECT provider_thread_id FROM outreach_messages WHERE business_id = :b AND provider_thread_id IN :t"
        ).bindparams(bindparam("t", expanding=True)), {"b": bid, "t": threads})}

    skipped, for_ai = 0, []
    for row in rows:
        free = skip(row, outreach)
        if free:
            skipped += _stamp(session, bid, row.id, *free)
        else:
            for_ai.append(row)
    session.commit()

    sorted_, failed = 0, False
    for i in range(0, len(for_ai), batch_size):
        batch = for_ai[i:i + batch_size]
        with profit_guard.attributed(bid, "classify"):        # essential: recorded, never paused
            results = service.analyze_email_batch(batch)
        if not results:
            failed = True                                      # left unsorted: tried again next pass
            logger.warning("[Inbox] sorting failed for business %s (%d emails left for next pass)", bid, len(batch))
            break
        ids, done = {str(m.id) for m in batch}, set()
        for r in results:
            mid = str(r.message_id)
            if mid not in ids or mid in done:
                continue                                       # not this batch's, or answered twice
            done.add(mid)
            try:
                priority = max(1, min(5, int(r.priority or 2)))
            except (TypeError, ValueError):
                priority = 2
            sorted_ += _stamp(session, bid, mid, normalise(r.category), priority, r.summary, r.suggested_action)
        session.commit()
        if done != ids:                                        # some left out: say so, try again next pass
            failed = True
            logger.warning("[Inbox] the model left %d of %d emails unsorted for business %s",
                           len(ids - done), len(ids), bid)
    return {"sorted": sorted_, "skipped": skipped, "waiting": _waiting(session, bid), "failed": failed}
