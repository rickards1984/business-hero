"""OUT-13 core on real PostgreSQL (the local harness, migrations 037-041
replayed): the deletion order against the real foreign keys, the guard and
the exceptions tables, and the business lock. Skips without the harness."""
# ruff: noqa: F811 - the pg fixture is a parameter by design
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlmodel import Session

from test_outreach_send_rls import DATABASE_URL, OWNER, _approve, _count, _propose, pg  # noqa: F401
from test_outreach_send import A, NOW, PROSPECT

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="RLS_LOCAL_DATABASE_URL is not set")


@pytest.fixture
def erasable(pg):
    with pg.engine.connect() as c:
        if not c.execute(text("SELECT to_regclass('public.outreach_recently_erased')")).scalar():
            pytest.skip("migration 041 is not applied in the local harness")
    yield pg
    with pg.engine.begin() as c:
        for table in ("outreach_recently_erased", "outreach_erasure_exceptions"):
            c.execute(text(f"DELETE FROM {table} WHERE business_id = :b"), {"b": A})


def _past_deadline(pg):
    with pg.engine.begin() as c:
        c.execute(text("UPDATE outreach_prospects SET captured_at = :c, notice_due_at = :n, notice_provided_at = NULL "
                       "WHERE business_id = :b AND id = :p"),
                  {"c": NOW - timedelta(days=40), "n": NOW - timedelta(days=10), "b": A, "p": PROSPECT})


def test_a_refused_first_email_is_erased_in_foreign_key_order(erasable):
    """The provider refused the first email: a failed message, a failed job,
    a released usage event and a failed card all point at each other. All go
    (the usage fact stays, unlinked); nothing about the person remains."""
    from services import outreach_erasure
    pg = erasable
    pg.p.outcome = "definitely_not_accepted"
    card = _propose(pg)
    _approve(pg, card)
    assert _count(pg, "SELECT state FROM outreach_messages WHERE business_id = :b", b=A) == "failed"
    _past_deadline(pg)
    with Session(pg.engine) as s:
        assert outreach_erasure.erase_never_contacted(s, A, PROSPECT, NOW)["erased"] is True
    for table in ("outreach_prospects", "outreach_evidence", "outreach_enrolments", "outreach_messages",
                  "outreach_dispatch_jobs", "outreach_unsubscribe_tokens"):
        assert _count(pg, f"SELECT count(*) FROM {table} WHERE business_id = :b", b=A) == 0, table
    assert _count(pg, "SELECT count(*) FROM aria_actions WHERE business_id = :b AND action_type = 'send_outreach'",
                  b=A) == 0
    assert _count(pg, "SELECT count(*) FROM outreach_usage_events WHERE business_id = :b AND message_id IS NULL "
                      "AND state = 'released'", b=A) == 1
    assert _count(pg, "SELECT count(*) FROM outreach_recently_erased WHERE business_id = :b", b=A) == 2


def test_an_accepted_first_email_is_never_erased(erasable):
    from services import outreach_erasure
    pg = erasable
    card = _propose(pg)
    _approve(pg, card)
    _past_deadline(pg)
    with pg.engine.begin() as c:     # even with the notice date missing
        c.execute(text("UPDATE outreach_prospects SET notice_provided_at = NULL WHERE business_id = :b"), {"b": A})
    with Session(pg.engine) as s:
        assert outreach_erasure.erase_never_contacted(s, A, PROSPECT, NOW) == {"erased": False, "reason": "contacted"}
    assert _count(pg, "SELECT count(*) FROM outreach_prospects WHERE business_id = :b", b=A) == 1


def test_an_uncertain_send_is_kept_and_listed(erasable):
    from services import outreach_erasure
    pg = erasable
    pg.p.outcome = "unknown"
    card = _propose(pg)
    _approve(pg, card)
    _past_deadline(pg)
    with Session(pg.engine) as s:
        out = outreach_erasure.run_due(s, NOW)
    assert out["exceptions"] == {"may_have_sent": 1}
    assert _count(pg, "SELECT count(*) FROM outreach_prospects WHERE business_id = :b", b=A) == 1
    assert _count(pg, "SELECT reason FROM outreach_erasure_exceptions WHERE business_id = :b", b=A) == "may_have_sent"


def test_the_new_tables_are_backend_only(erasable):
    pg = erasable
    with pg.engine.connect() as c:
        for table in ("outreach_recently_erased", "outreach_erasure_exceptions"):
            rls = c.execute(text("SELECT relrowsecurity FROM pg_class WHERE relname = :t"), {"t": table}).scalar()
            grants = c.execute(text("SELECT count(*) FROM information_schema.role_table_grants WHERE table_name = :t "
                                    "AND grantee IN ('anon', 'authenticated', 'service_role')"), {"t": table}).scalar()
            assert rls is True and grants == 0, table
