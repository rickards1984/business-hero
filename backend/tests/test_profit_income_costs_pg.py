"""PROFIT-2 on real PostgreSQL (Codex review 1): an invoice reached by the
webhook and a refresh at once is counted once; two first edits of a month's
bills never overwrite each other. Synchronised on PostgreSQL itself."""
import threading
import time
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlmodel import Session

from test_outreach_send_rls import DATABASE_URL

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="RLS_LOCAL_DATABASE_URL is not set")

BID = "6a1d2b0e-0000-4000-8000-00000000p2a1".replace("p2a1", "0a21")
NOW = datetime(2026, 10, 27, 9, tzinfo=timezone.utc)


@pytest.fixture
def pg():
    e = create_engine(DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1), pool_size=6)
    with e.begin() as c:
        if not c.execute(text("SELECT to_regclass('public.platform_meters')")).scalar():
            pytest.skip("039 is not replayed in the local harness")
        c.execute(text("DELETE FROM usage_meters WHERE business_id = :b"), {"b": BID})
        c.execute(text("DELETE FROM businesses WHERE id = :b"), {"b": BID})
        c.execute(text("DELETE FROM platform_meters WHERE meter LIKE 'fixed_cost%' AND period IN ('2026-09', '2026-10')"))
        c.execute(text("INSERT INTO businesses (id, name, api_key, plan_tier, subscription_status, is_active, "
                       "feature_flags, stripe_customer_id, stripe_subscription_id) VALUES (:b, 'P2', :k, 'pro', "
                       "'active', true, '{}'::jsonb, 'cus_p2', 'sub_p2')"), {"b": BID, "k": f"p2-{BID}"})
    yield e
    with e.begin() as c:
        c.execute(text("DELETE FROM usage_meters WHERE business_id = :b"), {"b": BID})
        c.execute(text("DELETE FROM businesses WHERE id = :b"), {"b": BID})
        c.execute(text("DELETE FROM platform_meters WHERE meter LIKE 'fixed_cost%' AND period IN ('2026-09', '2026-10')"))
    e.dispose()


def blocked_behind(engine, pid) -> None:
    deadline = time.monotonic() + 10
    with engine.connect() as watch:
        while time.monotonic() < deadline:
            if watch.execute(text("SELECT count(*) FROM pg_stat_activity WHERE :p = ANY(pg_blocking_pids(pid))"),
                             {"p": pid}).scalar():
                return
            watch.rollback()
            time.sleep(0.05)
    pytest.fail("the second transaction never waited for the first")


def test_an_invoice_recorded_twice_at_once_counts_once(pg):
    from services import stripe_income
    inv = {"id": "in_p2_race", "customer": "cus_p2", "subscription": "sub_p2", "amount_paid": 12900, "tax": 0,
           "currency": "gbp", "billing_reason": "subscription_cycle", "status": "paid",
           "status_transitions": {"paid_at": int(NOW.timestamp())}}
    with pg.begin() as c:                  # the month's cash row already exists
        c.execute(text("INSERT INTO usage_meters (business_id, meter, period, value, updated_at) "
                       "VALUES (:b, 'stripe_paid_pence', '2026-10', 100, now())"), {"b": BID})
    first = Session(pg)
    assert stripe_income.record_invoice(first, inv) is True
    pid = first.execute(text("SELECT pg_backend_pid()")).scalar()
    result = {}

    def second():
        with Session(pg) as s:
            result["recorded"] = stripe_income.record_invoice(s, inv)
            s.commit()
    worker = threading.Thread(target=second)
    worker.start()
    try:
        blocked_behind(pg, pid)
    finally:
        first.commit()
        first.close()
        worker.join(20)
    assert result["recorded"] is False
    with pg.connect() as c:
        assert float(c.execute(text("SELECT value FROM usage_meters WHERE business_id = :b AND "
                                    "meter = 'stripe_paid_pence' AND period = '2026-10'"), {"b": BID}).scalar()) == 13000


def test_two_first_edits_of_a_month_never_overwrite_each_other(pg):
    from services import running_costs
    with Session(pg) as s:
        running_costs.set_item(s, "2026-09", "Railway", 2000, moment=NOW)
        running_costs.set_item(s, "2026-09", "Vercel", 1600, moment=NOW)
        s.commit()
    first = Session(pg)
    running_costs.set_item(first, "2026-10", "Railway", 2350, moment=NOW)
    pid = first.execute(text("SELECT pg_backend_pid()")).scalar()
    done = {}

    def second():
        with Session(pg) as s:
            running_costs.set_item(s, "2026-10", "Vercel", 1700, moment=NOW)
            s.commit()
            done["ok"] = True
    worker = threading.Thread(target=second)
    worker.start()
    try:
        blocked_behind(pg, pid)
    finally:
        first.commit()
        first.close()
        worker.join(20)
    assert done.get("ok")
    with Session(pg) as s:
        assert {i["name"]: i["pence"] for i in running_costs.items(s, "2026-10")} == {"Railway": 2350, "Vercel": 1700}


def test_a_rolled_back_recording_leaves_nothing_on_postgres(pg):
    from services import stripe_income
    inv = {"id": "in_p2_rollback", "customer": "cus_p2", "subscription": "sub_p2", "amount_paid": 12900, "tax": 0,
           "currency": "gbp", "billing_reason": "subscription_cycle", "status": "paid",
           "status_transitions": {"paid_at": int(NOW.timestamp())}}
    with Session(pg) as s:
        assert stripe_income.record_invoice(s, inv) is True
        s.rollback()
    with Session(pg) as s:
        assert stripe_income.record_invoice(s, inv) is True
        s.commit()
    with pg.connect() as c:
        assert float(c.execute(text("SELECT coalesce(sum(value), 0) FROM usage_meters WHERE business_id = :b AND "
                                    "meter = 'stripe_paid_pence'"), {"b": BID}).scalar()) == 12900
