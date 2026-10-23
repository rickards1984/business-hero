"""MAIL-1 — several mailboxes per business, with a dependable default.

docs/MAIL-1-TICKET.md. A business may connect any number of mailboxes. The
default (invoice chases and general email go from it — AUTO-2) is chosen
deliberately and changed in ONE transaction, so a business is never left with
none by a half-finished switch. Every change to the default takes a
per-business transaction lock first, so two at once queue rather than both
winning; this does not depend on migration 037's one-default index (Codex
review 1), which is a second line of defence where it exists.
"""

import logging
import uuid
from typing import Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)

LABEL_MAX = 60


def _is_postgres(session) -> bool:
    return session.get_bind().dialect.name == "postgresql"


def _lock(session, business_id: str) -> None:
    """Serialise every change to this business's default (Postgres)."""
    if _is_postgres(session):
        session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
                        {"k": f"mailbox-default:{business_id}"})


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
        _lock(session, business_id)
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


def mailboxes_before(session, business_id: str) -> list:
    """The business's mailboxes as they were BEFORE an OAuth callback saves
    its connection: what AUTO-2 was sending from, and each mailbox's label."""
    rows = session.execute(text(
        "SELECT id, email_address, provider, is_default, display_name FROM email_accounts "
        "WHERE business_id = :b"), {"b": str(business_id)}).fetchall()
    session.rollback()
    return [{"id": str(r[0]), "email_address": r[1], "provider": r[2],
             "is_default": bool(r[3]), "display_name": r[4]} for r in rows]


def _same(row: dict, email_address: str, provider: str) -> bool:
    return (str(row.get("email_address") or "").strip().lower()
            == str(email_address or "").strip().lower() and row.get("provider") == provider)


def ensure_default_after_connect(session, business_id: str, email_address: str,
                                 provider: str, before: list) -> Optional[str]:
    """After an OAuth connection is saved, settle the default in one
    transaction under the business's lock, and return the id marked (or None).

    The mailbox marked is the one AUTO-2 was ALREADY sending from: the sole
    mailbox before this connection (usually unmarked — nothing ever marked
    one before MAIL-1), or the new one if there was none. With two or more
    and none marked, the owner has a choice to make and it is left to them.
    A label the reconnect wiped is put back. Never raises: the connection
    stands, and the owner can still press Make default."""
    try:
        _lock(session, business_id)
        rows = session.execute(text(
            "SELECT id, email_address, provider, is_default, display_name FROM email_accounts "
            "WHERE business_id = :b"), {"b": str(business_id)}).fetchall()
        now = [{"id": str(r[0]), "email_address": r[1], "provider": r[2],
                "is_default": bool(r[3]), "display_name": r[4]} for r in rows]
        mine = next((r for r in now if _same(r, email_address, provider)), None)
        earlier = next((r for r in before if _same(r, email_address, provider)), None)
        if mine and earlier and earlier.get("display_name") and \
                mine.get("display_name") != earlier["display_name"]:
            session.execute(text(
                "UPDATE email_accounts SET display_name = :n WHERE id = :id AND business_id = :b"),
                {"n": earlier["display_name"], "id": mine["id"], "b": str(business_id)})
        target = None
        if mine and not any(r["is_default"] for r in now):
            if not before:
                target = mine["id"]
            elif len(before) == 1:
                target = before[0]["id"]
            if target is not None and not any(r["id"] == target for r in now):
                target = None  # disconnected meanwhile
            if target is not None:
                session.execute(text(
                    "UPDATE email_accounts SET is_default = :t WHERE id = :id AND business_id = :b"),
                    {"t": True, "id": target, "b": str(business_id)})
        session.commit()
        return target
    except Exception as exc:  # the connection stands; Make default still works
        try:
            session.rollback()
        except Exception:  # noqa: BLE001
            pass
        logger.warning("[Mailboxes] could not settle the default for %s: %s",
                       business_id, type(exc).__name__)
        return None
