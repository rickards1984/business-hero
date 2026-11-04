"""TRADE-0 §3: OAuth state is single-use, expiring, and bound to the person,
business, provider and operation; the callback rechecks CURRENT ownership."""
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, text

BIZ, USER = str(uuid.uuid4()), str(uuid.uuid4())


@pytest.fixture
def st(tmp_path, monkeypatch):
    from services import oauth_state
    import assistant_chat
    from types import SimpleNamespace
    e = create_engine("sqlite:///" + str(tmp_path / "o.sqlite"))
    with e.begin() as c:
        c.execute(text("""CREATE TABLE oauth_states (id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE,
            user_id TEXT NOT NULL, business_id TEXT NOT NULL, provider TEXT NOT NULL, operation TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL, expires_at TIMESTAMP NOT NULL, consumed_at TIMESTAMP)"""))
    import db
    monkeypatch.setattr(db, "engine", e)
    owners = {(USER, BIZ)}

    def resolver(uid, bid=None):
        if (uid, bid) not in owners:
            raise ValueError("FORBIDDEN", "not an owner")
        return SimpleNamespace(id=bid)
    monkeypatch.setattr(assistant_chat, "get_business_for_user", resolver)
    oauth_state.owners = owners
    oauth_state.engine = e
    return oauth_state


def issue(st, provider="xero", operation="accounting"):
    return st.issue(user_id=USER, business_id=BIZ, provider=provider, operation=operation)


def test_a_state_is_consumed_once_and_returns_who_started_it(st):
    token = issue(st)
    assert st.consume(token, "xero") == {"user_id": USER, "business_id": BIZ, "operation": "accounting"}
    with pytest.raises(st.StateRejected):
        st.consume(token, "xero")                      # replayed


def test_the_token_itself_is_never_stored(st):
    token = issue(st)
    with st.engine.connect() as c:
        stored = c.execute(text("SELECT token_hash FROM oauth_states")).scalar()
    assert token not in stored and len(stored) == 64


@pytest.mark.parametrize("case", ["forged", "wrong_provider", "empty"])
def test_forged_wrong_provider_or_missing_state_is_rejected(st, case):
    token = issue(st)
    with pytest.raises(st.StateRejected):
        st.consume({"forged": "x" + token, "wrong_provider": token, "empty": ""}[case],
                   "google" if case == "wrong_provider" else "xero")


def test_an_expired_state_is_rejected(st, monkeypatch):
    token = issue(st)
    real = st.now
    monkeypatch.setattr(st, "now", lambda: real() + st.TTL + timedelta(seconds=1))
    with pytest.raises(st.StateRejected):
        st.consume(token, "xero")


def test_an_initiator_who_lost_ownership_between_start_and_callback_is_rejected(st):
    token = issue(st)
    st.owners.discard((USER, BIZ))
    with pytest.raises(st.StateRejected):
        st.consume(token, "xero")


def test_an_unknown_provider_cannot_be_issued(st):
    with pytest.raises(ValueError):
        issue(st, provider="dropbox")


def test_two_callbacks_racing_on_one_state_succeed_once(st):
    token = issue(st)
    results = []
    for _ in range(2):
        try:
            results.append(st.consume(token, "xero"))
        except st.StateRejected:
            results.append(None)
    assert sum(r is not None for r in results) == 1


# ---------------------------------- the callbacks refuse before any exchange ---

def test_the_xero_callback_refuses_a_bad_state_before_exchanging_any_code(st, monkeypatch):
    import asyncio
    from fastapi import HTTPException
    import main
    exchanged = []

    async def exchange(**kw):
        exchanged.append(kw)
        return {"access_token": "x"}
    monkeypatch.setattr(main, "exchange_code_for_tokens", exchange)
    import email_utils
    from cryptography.fernet import Fernet
    monkeypatch.setattr(email_utils, "_EMAIL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    for bad in ("not-a-state", email_utils.encrypt_str(BIZ)):   # the old format no longer works
        with pytest.raises(HTTPException) as caught:
            asyncio.run(main.oauth_xero_callback(code="c", state=bad, session=None))
        assert caught.value.status_code == 400
    assert exchanged == []


@pytest.mark.parametrize("name,provider", [("google_oauth_callback", "google"), ("microsoft_oauth_callback", "microsoft")])
def test_the_email_callbacks_refuse_a_state_for_someone_no_longer_an_owner(st, monkeypatch, name, provider):
    import asyncio
    import httpx
    from fastapi import HTTPException
    from app.email import router
    token = st.issue(user_id=USER, business_id=BIZ, provider=provider, operation="email:read_full")
    st.owners.discard((USER, BIZ))
    posted = []
    monkeypatch.setattr(httpx.AsyncClient, "post", lambda *a, **k: posted.append(a))
    with pytest.raises(HTTPException) as caught:
        asyncio.run(getattr(router, name)(code="c", state=token, error=None, admin=None))
    assert caught.value.status_code == 400 and posted == []
