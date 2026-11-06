"""OUT-22: every business has exactly one `business_settings` row.

Several features each created the row themselves, the first time they needed
it, and outreach assumed it already existed (MSC had none: "Outreach record
unavailable"). Production proves no UNIQUE on business_id
(audits/live-schema-public.txt lists columns only), so a NOT EXISTS insert is
not enough on its own: two first-time writers could both pass it and leave two
rows, after which every exactly-one lookup fails (Codex OUT-22 review 1).

`ensure` is the one way to create it. On PostgreSQL it first takes a
transaction-scoped advisory lock on the business, so creators queue; the row is
then created only if still missing. Every settings LOCK helper calls it first,
so no writer ever locks, reads or writes a business with no row. It runs in the CALLER'S transaction and never
commits: a request refused later in the same transaction (an owner removed
mid-request) leaves nothing behind (Codex OUT-22 review 1).
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import text


def _pg(session) -> bool:
    try:
        return session.get_bind().dialect.name == "postgresql"
    except Exception:          # a session without a bind (test stand-ins): the portable form
        return False


def ensure(session, business_id) -> None:
    bid = str(business_id)
    pg = _pg(session)
    # The lock is taken ONLY when the row is missing (Codex OUT-22 review 2):
    # while it is missing nobody can hold a lock on it, so this can never
    # invert the order of a caller that already locked the row.
    if session.execute(text("SELECT 1 FROM business_settings WHERE business_id = :b"), {"b": bid}).first():
        return
    if pg:
        session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
                        {"k": f"business_settings:{bid}"})
    if session.execute(text("SELECT 1 FROM business_settings WHERE business_id = :b"), {"b": bid}).first():
        return
    # The live table has no default for id or the (zone-less) timestamps.
    stamp = datetime.now(timezone.utc).replace(tzinfo=None)
    session.execute(text(
        "INSERT INTO business_settings (id, business_id, settings, created_at, updated_at) "
        "SELECT :i, :b, " + ("CAST(:s AS jsonb)" if pg else ":s") + ", :at, :at "
        "WHERE NOT EXISTS (SELECT 1 FROM business_settings WHERE business_id = :b)"),
        {"i": str(uuid.uuid4()), "b": bid, "s": "{}", "at": stamp})
