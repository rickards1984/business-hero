"""MAIL-1 — several mailboxes per business, with a dependable default.

docs/MAIL-1-TICKET.md. A business may connect any number of mailboxes. The
default (invoice chases and general email go from it — AUTO-2) is chosen
deliberately and changed in ONE transaction, so a business is never left with
none by a half-finished switch. Migration 037's partial unique index enforces
at most one default per business underneath.
"""

import logging
import uuid
from typing import Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)

LABEL_MAX = 60


def _is_postgres(session) -> bool:
    return session.get_bind().dialect.name == "postgresql"


def _owned(session, business_id: str, account_id: str, lock: bool = False):
    """This business's mailbox, or None. Never looks at another business."""
    if _is_postgres(session):
        try:
            uuid.UUID(str(account_id))
        except ValueError:
            return None
    suffix = " FOR UPDATE" if lock and _is_postgres(session) else ""
    return session.execute(text(
        "SELECT id, is_default FROM email_accounts WHERE id = :id AND business_id = :b" + suffix),
        {"id": str(account_id), "b": str(business_id)}).fetchone()


def set_default(session, business_id: str, account_id: str) -> dict:
    """Make `account_id` the business's default mailbox. Checks ownership
    FIRST; clearing and setting are one transaction."""
    try:
        if _owned(session, business_id, account_id, lock=True) is None:
            session.rollback()
            raise LookupError("Email account not found")
        session.execute(text(
            "UPDATE email_accounts SET is_default = :f WHERE business_id = :b AND is_default = :t "
            "AND id <> :id"),
            {"f": False, "t": True, "b": str(business_id), "id": str(account_id)})
        session.execute(text(
            "UPDATE email_accounts SET is_default = :t WHERE id = :id AND business_id = :b"),
            {"t": True, "id": str(account_id), "b": str(business_id)})
        session.commit()
    except LookupError:
        raise
    except Exception:
        session.rollback()
        raise
    return {"id": str(account_id), "is_default": True}


def rename(session, business_id: str, account_id: str, label: str) -> dict:
    """Label a mailbox (stored as its display name), e.g. "FitFutures outreach"."""
    cleaned = str(label or "").strip()
    if not cleaned or len(cleaned) > LABEL_MAX:
        raise ValueError(f"A label must be 1-{LABEL_MAX} characters.")
    if _owned(session, business_id, account_id) is None:
        session.rollback()
        raise LookupError("Email account not found")
    session.execute(text(
        "UPDATE email_accounts SET display_name = :n WHERE id = :id AND business_id = :b"),
        {"n": cleaned, "id": str(account_id), "b": str(business_id)})
    session.commit()
    return {"id": str(account_id), "display_name": cleaned}


def needs_default(session, business_id: str) -> bool:
    """Two or more mailboxes and none is the default: invoice chasing waits
    until the owner chooses (AUTO-2), so the screen asks."""
    row = session.execute(text(
        "SELECT COUNT(*), SUM(CASE WHEN is_default THEN 1 ELSE 0 END) FROM email_accounts "
        "WHERE business_id = :b"), {"b": str(business_id)}).fetchone()
    total, defaults = int(row[0] or 0), int(row[1] or 0)
    return total >= 2 and defaults == 0


async def ensure_default_after_connect(admin, business_id: str, email_address: str,
                                       provider: str) -> None:
    """After an OAuth connection: the first mailbox a business connects
    becomes its default; a later one never takes it; reconnecting keeps
    whatever the mailbox was. Losing a race to another connection is fine —
    037's index lets exactly one win — and never fails the connection."""
    try:
        if await admin.fetch_email_account(business_id=business_id, fields="id", is_default=True):
            return
        rows = await admin.fetch_email_accounts(business_id, fields="id,email_address,provider") or []
        wanted = str(email_address or "").strip().lower()
        target: Optional[dict] = next(
            (r for r in rows if str(r.get("email_address") or "").strip().lower() == wanted
             and r.get("provider") == provider), None)
        if target is None:
            return
        await admin._update("email_accounts", {"is_default": True},
                            filters={"id": target["id"], "business_id": business_id})
    except Exception as exc:  # lost the race, or a transient error: the connection stands
        logger.warning("[Mailboxes] could not set the first default for %s: %s",
                       business_id, type(exc).__name__)
