"""OUT-19 part A on real PostgreSQL (Codex OUT-19 review 1, findings 4 and 5):
concurrent ledger writes never lose a charge, and the alarm fires exactly once
when two calls cross it together. SQLite's single writer cannot show either."""
# ruff: noqa: F811 - the pg fixture is a parameter by design
import logging
import threading

import pytest
from sqlalchemy import text
from sqlmodel import Session

from test_outreach_send_rls import DATABASE_URL, pg  # noqa: F401
from test_outreach_send import A, B, NOW

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="RLS_LOCAL_DATABASE_URL is not set")


def together(pg, *jobs):
    gate, errors = threading.Barrier(len(jobs)), []

    def run(job):
        try:
            with Session(pg.engine) as s:
                s.execute(text("SELECT 1"))
                gate.wait(10)
                job(s)
                s.commit()
        except BaseException as exc:  # noqa: BLE001 - any failure fails the test
            errors.append(exc)
    threads = [threading.Thread(target=run, args=(j,)) for j in jobs]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert not any(t.is_alive() for t in threads), "a ledger write never finished"
    assert not errors, errors


def value(pg, bid, meter):
    with pg.engine.connect() as c:
        return float(c.execute(text("SELECT coalesce(sum(value), 0) FROM usage_meters WHERE business_id = :b "
                                    "AND meter = :m AND period = '2026-10'"), {"b": bid, "m": meter}).scalar())


def test_two_first_writes_to_a_months_meter_both_count(pg):
    from services import ai_costs
    record = lambda s: ai_costs.record(s, A, purpose="draft", provider="openai", model="gpt-4o",  # noqa: E731
                                        pence=7, moment=NOW)
    together(pg, record, record)
    assert value(pg, A, "ai_pence") == 14
    assert value(pg, A, "ai_calls:draft:-:openai/gpt-4o") == 2


def test_two_calls_crossing_the_alarm_together_raise_it_once(pg, monkeypatch, caplog):
    from services import ai_costs
    monkeypatch.setenv("AI_MONTHLY_ALARM_PENCE", "50")
    with pg.engine.begin() as c:
        c.execute(text("INSERT INTO usage_meters (business_id, meter, period, value, updated_at) "
                       "VALUES (:b, 'ai_pence', '2026-10', 40, now())"), {"b": B})
    with caplog.at_level(logging.ERROR):
        together(pg, *(lambda s, bid=bid: ai_costs.record(s, bid, purpose="research", provider="openai",
                                                           model="gpt-4.1", pence=6, moment=NOW) for bid in (A, B)))
    assert caplog.text.count("AI spend alarm") == 1
    assert value(pg, A, "ai_pence") + value(pg, B, "ai_pence") == 52   # 40 seeded on B, then 6 each
