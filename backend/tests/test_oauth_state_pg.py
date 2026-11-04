"""TRADE-0 §3 on real PostgreSQL (migration 040): oauth_states is backend-only,
its constraints hold, and two callbacks racing on one state succeed once."""
# ruff: noqa: F811 - the pg fixture is a parameter by design
import threading
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import exc as sa_exc
from sqlalchemy import text

from test_outreach_send_rls import DATABASE_URL, pg  # noqa: F401
from test_outreach_send import A, OWNER

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="RLS_LOCAL_DATABASE_URL is not set")


@pytest.fixture
def st(pg, monkeypatch):
    with pg.engine.connect() as c:
        if not c.execute(text("SELECT to_regclass('public.oauth_states')")).scalar():
            pytest.skip("040 is not applied in the local harness")
    with pg.engine.begin() as c:
        c.execute(text("DELETE FROM oauth_states"))
    import assistant_chat
    import db
    from services import oauth_state
    monkeypatch.setattr(db, "engine", pg.engine)
    monkeypatch.setattr(assistant_chat, "get_business_for_user",
                        lambda uid, bid=None: SimpleNamespace(id=bid) if (uid, bid) == (OWNER, A) else
                        (_ for _ in ()).throw(ValueError("FORBIDDEN", "no")))
    yield oauth_state
    with pg.engine.begin() as c:
        c.execute(text("DELETE FROM oauth_states"))


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_no_client_role_can_read_or_write_states(pg, st, role):
    st.issue(user_id=OWNER, business_id=A, provider="xero", operation="accounting")
    for sql in ("SELECT count(*) FROM oauth_states",
                "INSERT INTO oauth_states (token_hash, user_id, business_id, provider, operation, expires_at) "
                "VALUES (repeat('a', 64), gen_random_uuid(), gen_random_uuid(), 'xero', 'x', now() + interval '1 hour')"):
        with pg.engine.connect() as c:
            c.execute(text(f"SET ROLE {role}"))
            with pytest.raises(sa_exc.ProgrammingError):
                c.execute(text(sql))


@pytest.mark.parametrize("column,value", [("provider", "'dropbox'"), ("token_hash", "'not-a-hash'"),
                                          ("expires_at", "now() - interval '1 hour'")])
def test_the_constraints_refuse_bad_rows(pg, st, column, value):
    values = {"token_hash": "repeat('b', 64)", "provider": "'xero'", "expires_at": "now() + interval '1 hour'"}
    values[column] = value
    with pytest.raises(sa_exc.IntegrityError):
        with pg.engine.begin() as c:
            c.execute(text(f"INSERT INTO oauth_states (token_hash, user_id, business_id, provider, operation, expires_at) "
                           f"VALUES ({values['token_hash']}, :u, :b, {values['provider']}, 'accounting', {values['expires_at']})"),
                      {"u": OWNER, "b": A})


def test_a_state_for_a_business_that_does_not_exist_is_refused(pg, st):
    with pytest.raises(sa_exc.IntegrityError):
        st.issue(user_id=OWNER, business_id=str(uuid.uuid4()), provider="xero", operation="accounting")


def test_two_callbacks_racing_on_one_state_succeed_once(pg, st):
    token = st.issue(user_id=OWNER, business_id=A, provider="xero", operation="accounting")
    gate, wins, losses = threading.Barrier(2), [], []

    def callback():
        gate.wait(10)
        try:
            wins.append(st.consume(token, "xero"))
        except st.StateRejected:
            losses.append(True)
    threads = [threading.Thread(target=callback) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)
    assert len(wins) == 1 and len(losses) == 1 and wins[0]["business_id"] == A
