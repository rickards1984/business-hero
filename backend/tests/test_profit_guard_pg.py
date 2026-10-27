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
