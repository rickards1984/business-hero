"""ARIA-1a — Aria sorts the inbox (docs/ARIA-PROACTIVE-TICKETS.md, ARIA-1 §1–2).

One sorting pass, used by the background sync and by "Sort now":

1. **Free filters** first, with no AI: mailing lists, promotions, social,
   spam, automated mail and the owner's own mail are stamped straight away,
   at no cost. A reply to the business's outreach is left to the outreach
   scanner. **A money email is never filtered away:** a bank notice or an
   invoice often comes from a no-reply sender with a list header, so anything
   that looks like money goes to the AI.
2. **The AI** sorts the rest, in batches, into Mike's categories, costed to
   the business as `classify` (essential: never paused).

The categories are Mike's (19 Nov). Every value ever written, including the
old ones (action_required, finance, ...), reads as one of them through
`normalise`, so nothing needs migrating. `is_important` and `IMPORTANT_SQL`
are the one definition of "needs the owner" for the dashboard, the WhatsApp
briefing and the automation trigger.
"""
import json
import logging
import re
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

# What the sorter wrote before ARIA-1, and the capitalised labels some readers
# expected but nothing ever wrote.
LEGACY = {
    "action_required": "customer", "awaiting_reply": "customer", "finance": "money", "marketing": "junk",
    "spam": "junk", "newsletter": "fyi",
}


def normalise(value) -> str:
    """Any stored or answered category, as one of Mike's (FYI if unknown)."""
    key = re.sub(r"[\s\-]+", "_", str(value or "").strip().lower())
    if key in CATEGORIES:
        return key
    return LEGACY.get(key, "fyi")


def is_important(category, priority) -> bool:
    if category is None and priority is None:
        return False
    try:
        high = priority is not None and int(priority) >= IMPORTANT_PRIORITY
    except (TypeError, ValueError):
        high = False
    return normalise(category) in IMPORTANT or (high and category is not None and normalise(category) != "junk")


def stored_values(categories) -> list:
    """Every raw value that reads as one of these categories."""
    out = set(categories)
    out.update(k for k, v in LEGACY.items() if v in categories)
    return sorted(out)


_JUNK_VALUES = ", ".join(f"'{v}'" for v in stored_values({"junk"}))
_IMPORTANT_VALUES = ", ".join(f"'{v}'" for v in stored_values(IMPORTANT))
# A SQL condition on email_messages: the same rule as is_important.
IMPORTANT_SQL = (f"(ai_category IN ({_IMPORTANT_VALUES}) OR (ai_priority >= {IMPORTANT_PRIORITY} "
                 f"AND ai_category IS NOT NULL AND ai_category NOT IN ({_JUNK_VALUES})))")


# ---------------------------------------------------------- free filters ---

_MONEY = re.compile(r"\b(invoice|payment|paid|pay\b|payout|remittance|receipt|statement|overdue|refund|"
                    r"direct debit|bank|transfer|bacs|credit note|purchase order|£\s?\d)", re.I)
_AUTOMATED_SENDER = re.compile(r"^(no[-_.]?reply|do[-_.]?not[-_.]?reply|mailer-daemon|postmaster|notifications?|"
                               r"alerts?|bounce)[^@]*@", re.I)


def _load(value, default):
    if isinstance(value, str):
        try:
            return json.loads(value or "null") or default
        except ValueError:
            return default
    return value or default


def skip(row, own_addresses: set, outreach_threads: set) -> Optional[tuple]:
    """(category, priority, why) when this mail needs no AI, else None."""
    labels = {str(x).upper() for x in _load(row.labels, [])}
    headers = {str(k).lower(): str(v) for k, v in _load(row.raw_headers, {}).items()}
    sender = (row.from_email or "").strip().lower()
    subject = row.subject or ""
    if sender and sender in own_addresses:
        return "fyi", 1, "Sent from your own address"
    if row.provider_thread_id and row.provider_thread_id in outreach_threads:
        return "fyi", 1, "A reply to your outreach: see Outreach → Replies"
    if "SPAM" in labels:
        return "junk", 1, "Marked as spam"
    if "CATEGORY_PROMOTIONS" in labels:
        return "junk", 1, "A promotion"
    if _MONEY.search(subject):
        return None                       # never filtered away: the AI sorts it
    if "CATEGORY_SOCIAL" in labels or "CATEGORY_FORUMS" in labels:
        return "fyi", 1, "A social or forum notification"
    if "list-unsubscribe" in headers or "list-id" in headers or \
            headers.get("precedence", "").lower() in ("bulk", "list", "junk"):
        return "fyi", 1, "A newsletter or mailing list"
    if headers.get("auto-submitted", "no").lower() != "no" or _AUTOMATED_SENDER.match(sender):
        return "fyi", 1, "An automated message"
    return None


# ------------------------------------------------------------- the pass ---

def _now():
    return datetime.now(timezone.utc)


def _stamp(session, business_id, mid, category, priority, summary, action=None):
    session.execute(text("""
        UPDATE email_messages
        SET ai_category = :category, ai_priority = :priority, ai_summary = :summary,
            ai_suggested_action = :action, ai_analyzed_at = :now
        WHERE id = :id AND business_id = :business_id
    """), {"category": category, "priority": priority, "summary": summary, "action": action, "now": _now(),
           "id": str(mid), "business_id": str(business_id)})


def _waiting(session, business_id) -> int:
    return int(session.execute(text(
        "SELECT COUNT(*) FROM email_messages WHERE business_id = :b AND ai_analyzed_at IS NULL"),
        {"b": str(business_id)}).scalar() or 0)


def sort_pending(session, business_id, *, limit: int = 30, batch_size: int = 10) -> dict:
    """Sort up to `limit` of the business's unsorted mail, newest first.
    Returns {"sorted", "skipped", "waiting", "failed"}: what the AI sorted,
    what the free filters sorted, what is still unsorted, and whether an AI
    batch failed (its mail is left unsorted, to be tried again next pass)."""
    from app.email import service
    from services import profit_guard
    bid = str(business_id)
    rows = session.execute(text("""
        SELECT id, from_email, from_name, subject, snippet, received_at, labels, raw_headers, provider_thread_id
        FROM email_messages
        WHERE business_id = :b AND ai_analyzed_at IS NULL
        ORDER BY received_at DESC
        LIMIT :limit
    """), {"b": bid, "limit": int(limit)}).fetchall()
    if not rows:
        return {"sorted": 0, "skipped": 0, "waiting": 0, "failed": False}
    own = {str(r[0]).strip().lower() for r in session.execute(text(
        "SELECT email_address FROM email_accounts WHERE business_id = :b AND email_address IS NOT NULL"),
        {"b": bid})}
    threads = sorted({r.provider_thread_id for r in rows if r.provider_thread_id})
    outreach = set()
    if threads:
        outreach = {str(r[0]) for r in session.execute(text(
            "SELECT provider_thread_id FROM outreach_messages WHERE business_id = :b AND provider_thread_id IN :t"
        ).bindparams(bindparam("t", expanding=True)), {"b": bid, "t": threads})}

    skipped, for_ai = 0, []
    for row in rows:
        free = skip(row, own, outreach)
        if free:
            _stamp(session, bid, row.id, *free)
            skipped += 1
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
        ids = {str(m.id) for m in batch}
        for r in results:
            if str(r.message_id) not in ids:
                continue
            _stamp(session, bid, r.message_id, normalise(r.category), max(1, min(5, int(r.priority or 2))),
                   r.summary, r.suggested_action)
            sorted_ += 1
        session.commit()
    return {"sorted": sorted_, "skipped": skipped, "waiting": _waiting(session, bid), "failed": failed}
