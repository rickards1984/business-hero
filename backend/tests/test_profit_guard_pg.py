"""PROFIT-1 on real PostgreSQL (Codex PROFIT-1 review 1): platform-level costs
and the once-a-month alert markers live in platform_meters (migration 039), the
UUID-keyed usage_meters is never given a fake business id, and the check runs
inside the ledger's advisory lock and a connection savepoint."""
# ruff: noqa: F811 - the pg fixture is a parameter by design
import pytest
from sqlalchemy import text
from sqlmodel import Session

from test_outreach_send_rls import DATABASE_URL, pg  # noqa: F401
from test_outreach_send import A, NOW
from test_ai_costs_pg import together

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="RLS_LOCAL_DATABASE_URL is not set")


@pytest.fixture
def clean(pg, monkeypatch):
    with pg.engine.connect() as c:
        if not c.execute(text("SELECT to_regclass('public.platform_meters')")).scalar():
            pytest.skip("039 is not applied in the local harness")
    for name in ("AI_MONTHLY_KILL_PENCE", "PROFIT_TRIAL_BUDGET_PENCE", "PLATFORM_FIXED_COSTS_PENCE"):
        monkeypatch.delenv(name, raising=False)
    with pg.engine.begin() as c:
        c.execute(text("DELETE FROM platform_meters WHERE period = '2026-10'"))
    from services import ai_costs, profit_guard
    ai_costs._PLATFORM_TABLE.clear()
    monkeypatch.setattr(profit_guard, "_engine", lambda: pg.engine)
    sent = []
    monkeypatch.setattr(profit_guard, "send_alert", lambda subject, body: sent.append(subject))
    yield sent
    with pg.engine.begin() as c:
        c.execute(text("DELETE FROM platform_meters WHERE period = '2026-10'"))


def platform(pg, meter):
    with pg.engine.connect() as c:
        return float(c.execute(text("SELECT coalesce(sum(value), 0) FROM platform_meters WHERE period = '2026-10' "
                                    "AND meter = :m"), {"m": meter}).scalar())


def test_an_ai_call_with_no_business_is_kept_in_platform_meters(pg, clean):
    from services import ai_costs
    with Session(pg.engine) as s:
        ai_costs.record(s, None, purpose="briefing", provider="openai", model="gpt-4o-mini", pence=12, moment=NOW)
        s.commit()
    assert platform(pg, "ai_pence") == 12
    with Session(pg.engine) as s:
        assert ai_costs.platform_total(s, "2026-10") >= 12


def test_the_alarm_is_marked_once_and_sent_after_commit_on_postgres(pg, clean):
    from services import ai_costs
    # The harness's two active Business subscriptions: £538 of income; 40% is £215.20.
    with Session(pg.engine) as s:
        ai_costs.record(s, A, purpose="draft", provider="openai", model="gpt-4o-mini", pence=21600, moment=NOW)
        assert clean == [], "nothing is sent before the commit"
        s.commit()
    with Session(pg.engine) as s:
        ai_costs.record(s, A, purpose="draft", provider="openai", model="gpt-4o-mini", pence=100, moment=NOW)
        s.commit()
    assert len(clean) == 1 and "40%" in clean[0]
    assert platform(pg, "profit_alerted:alarm") == 1


def test_two_calls_crossing_the_kill_together_alert_once(pg, clean):
    from services import ai_costs
    with Session(pg.engine) as s:
        ai_costs.record(s, A, purpose="draft", provider="openai", model="gpt-4o-mini", pence=40000, moment=NOW)
        s.commit()
    clean.clear()
    record = lambda s: ai_costs.record(s, A, purpose="draft", provider="openai", model="gpt-4o-mini",  # noqa: E731
                                        pence=2000, moment=NOW)
    together(pg, record, record)
    assert sum("80%" in subject for subject in clean) == 1
    assert platform(pg, "profit_alerted:kill") == 1


def test_a_rolled_back_crossing_leaves_no_marker_and_sends_nothing(pg, clean):
    from services import ai_costs
    with Session(pg.engine) as s:
        ai_costs.record(s, A, purpose="draft", provider="openai", model="gpt-4o-mini", pence=30000, moment=NOW)
        s.rollback()
    assert clean == [] and platform(pg, "profit_alerted:alarm") == 0


# ------------------------------------------------------ Codex PROFIT-1 review 2 ---

def test_migration_039_is_backend_only_and_constrained(pg, clean):
    """RLS on with no policies; no client role can touch it; bad rows refused."""
    from sqlalchemy.exc import DBAPIError
    with pg.engine.connect() as c:
        assert c.execute(text("SELECT relrowsecurity FROM pg_class WHERE oid = 'public.platform_meters'::regclass")).scalar()
        assert c.execute(text("SELECT count(*) FROM pg_policies WHERE tablename = 'platform_meters'")).scalar() == 0
        assert c.execute(text("SELECT count(*) FROM information_schema.role_table_grants WHERE table_name = 'platform_meters' "
                              "AND grantee IN ('anon', 'authenticated', 'service_role', 'PUBLIC')")).scalar() == 0
    for role in ("anon", "authenticated"):
        with pg.engine.connect() as c, pytest.raises(DBAPIError):
            c.execute(text(f"SET ROLE {role}"))
            c.execute(text("SELECT * FROM public.platform_meters"))
    for bad in ("('2026-13', 'm', 1)", "('26-10', 'm', 1)", "('2026-10', '', 1)", "('2026-10', 'm', -1)"):
        with pg.engine.connect() as c, pytest.raises(DBAPIError):
            c.execute(text(f"INSERT INTO public.platform_meters (period, meter, value) VALUES {bad}"))


def test_the_rollback_step_drops_only_this_table(pg, clean):
    """The runbook's rollback, rehearsed inside a transaction that is undone."""
    with pg.engine.connect() as c:   # one transaction (autobegun), undone at the end
        tables_before = c.execute(text("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")).scalar()
        c.execute(text("DROP TABLE IF EXISTS public.platform_meters"))
        assert c.execute(text("SELECT to_regclass('public.platform_meters')")).scalar() is None
        assert c.execute(text("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")).scalar() == tables_before - 1
        c.rollback()
        assert c.execute(text("SELECT to_regclass('public.platform_meters')")).scalar() is not None


def test_a_scheduled_check_racing_a_cost_alerts_once(pg, clean):
    """Review 2 P2, deterministically: a cost crossing the alarm is recorded but
    not yet committed when the scheduled check starts. With the ledger lock,
    the check waits, then sees the marker; without it, both would claim."""
    import threading
    import time
    from services import ai_costs, profit_guard
    # Already over 40% from voice minutes (committed directly: nothing has
    # checked yet), so both the ledger writer and the check see the crossing.
    with pg.engine.begin() as c:
        c.execute(text("DELETE FROM usage_meters WHERE business_id = :b AND meter = 'receptionist_minutes' "
                       "AND period = '2026-10'"), {"b": A})
        c.execute(text("INSERT INTO usage_meters (business_id, meter, period, value) VALUES "
                       "(:b, 'receptionist_minutes', '2026-10', 1400)"), {"b": A})   # 1,400 × 16p = £224, 42% of £538
    clean.clear()
    first = Session(pg.engine)
    ai_costs.record(first, A, purpose="draft", provider="openai", model="gpt-4o-mini", pence=1000, moment=NOW)
    mine = first.execute(text("SELECT pg_backend_pid()")).scalar()
    result = {}
    check = threading.Thread(target=lambda: result.setdefault("ran", profit_guard.periodic_check(NOW)))
    check.start()
    # Synchronised on the database itself: wait until another backend is
    # blocked behind this uncommitted transaction (on the ledger lock, or,
    # without it, on the marker row), so the interleaving is the contested one.
    deadline, blocked = time.monotonic() + 10, 0
    try:
        with pg.engine.connect() as watch:
            while time.monotonic() < deadline:
                blocked = watch.execute(text("SELECT count(*) FROM pg_stat_activity WHERE :me = ANY(pg_blocking_pids(pid))"),
                                        {"me": mine}).scalar()
                if blocked:
                    break
                watch.rollback()    # pg_stat_activity is one snapshot per transaction: a fresh one each poll
                time.sleep(0.05)
    finally:
        first.commit()      # always release the writer and the worker, even when the assertion below fails
        first.close()
        check.join(15)
    assert blocked, "the scheduled check never reached the contested step"
    assert not check.is_alive() and result.get("ran") is True, "the scheduled check ran to completion"
    assert sum("40%" in subject for subject in clean) == 1, clean
    assert platform(pg, "profit_alerted:alarm") == 1
    with pg.engine.begin() as c:
        c.execute(text("DELETE FROM usage_meters WHERE business_id = :b AND meter = 'receptionist_minutes' "
                       "AND period = '2026-10'"), {"b": A})
