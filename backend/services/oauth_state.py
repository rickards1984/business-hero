"""TRADE-0 §3: OAuth state that is single-use, expiring, and bound to who
started the connection (docs/TRADE-0-TICKET.md).

Before: the accounting providers put the encrypted business id in `state` (no
expiry, no person); email signed a payload valid for ten minutes and reusable.
Neither rechecked, at the callback, that the person who started the
connection still owned the business. Now `issue` stores a random token's hash
with the person, business, provider and operation; `consume` claims it once,
atomically, and rechecks the person's CURRENT owner authority before the
caller saves any credential.
"""
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text

TTL = timedelta(minutes=10)
PROVIDERS = {"google", "microsoft", "xero", "freeagent", "quickbooks"}


class StateRejected(Exception):
    """The callback's state is unknown, used, expired, for another provider,
    or its initiator no longer owns the business."""


def now() -> datetime:
    return datetime.now(timezone.utc)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _session(session):
    if session is not None:
        return session, False
    from sqlmodel import Session
    from db import engine
    return Session(engine), True


def issue(*, user_id: str, business_id: str, provider: str, operation: str, session=None) -> str:
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider {provider!r}")
    token = secrets.token_urlsafe(32)
    s, own = _session(session)
    try:
        moment = now()
        s.execute(text("DELETE FROM oauth_states WHERE expires_at < :old"), {"old": moment - timedelta(days=1)})
        s.execute(text(
            "INSERT INTO oauth_states (id, token_hash, user_id, business_id, provider, operation, created_at, expires_at) "
            "VALUES (:i, :h, :u, :b, :p, :o, :c, :e)"),
            {"i": str(uuid.uuid4()), "h": _hash(token), "u": str(user_id), "b": str(business_id), "p": provider,
             "o": operation, "c": moment, "e": moment + TTL})
        s.commit()
    finally:
        if own:
            s.close()
    return token


def consume(token: Optional[str], provider: str, *, session=None) -> dict:
    """{user_id, business_id, operation}, once. Raises StateRejected."""
    if not token or provider not in PROVIDERS:
        raise StateRejected("missing state")
    s, own = _session(session)
    try:
        row = s.execute(text(
            "UPDATE oauth_states SET consumed_at = :n WHERE token_hash = :h AND provider = :p "
            "AND consumed_at IS NULL AND expires_at > :n RETURNING user_id, business_id, operation"),
            {"n": now(), "h": _hash(token), "p": provider}).fetchone()
        s.commit()
    finally:
        if own:
            s.close()
    if row is None:
        raise StateRejected("This connection link is invalid, already used or expired. Please start again.")
    claim = {"user_id": str(row[0]), "business_id": str(row[1]), "operation": row[2]}
    from assistant_chat import get_business_for_user
    try:
        get_business_for_user(claim["user_id"], claim["business_id"])
    except Exception as exc:
        raise StateRejected("Whoever started this connection no longer owns the business.") from exc
    return claim
