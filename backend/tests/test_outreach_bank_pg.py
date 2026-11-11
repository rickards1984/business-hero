"""OUT-23 bank on real PostgreSQL (the local harness): the sizing, ledger,
drain and card-preparation SQL against the real schema, types and foreign
keys. Skips without the harness; a skip is not a pass."""
# ruff: noqa: F811 - the pg fixture is a parameter by design
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlmodel import Session

from test_outreach_send_rls import DATABASE_URL, _count, pg  # noqa: F401
from test_outreach_send import A, CAMPAIGN, ENROLMENT, LIA, NOW, PROSPECT

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="RLS_LOCAL_DATABASE_URL is not set")


def bank():
    from services import outreach_bank
    return outreach_bank


@pytest.fixture
def banked(pg, monkeypatch):
    """The seeded contact, never emailed, back in the bank."""
    monkeypatch.setenv("OUTREACH_PILOT_ENROLMENTS", "0")
    with pg.engine.begin() as c:
        c.execute(text("DELETE FROM outreach_enrolments WHERE business_id = :b AND id = :e"), {"b": A, "e": ENROLMENT})
        c.execute(text("UPDATE outreach_prospects SET captured_at = :c, notice_due_at = NULL, notice_provided_at = NULL "
                       "WHERE business_id = :b AND id = :p"), {"c": NOW - timedelta(days=1), "b": A, "p": PROSPECT})
    return pg


def _hash(pg):
    return _count(pg, "SELECT audience_hash FROM outreach_compliance WHERE business_id = :b AND id = :l", b=A, l=LIA)


def test_sizing_and_stock_run_on_postgres(banked):
    pg = banked
    brand = _count(pg, "SELECT brand_id FROM outreach_compliance WHERE business_id = :b AND id = :l", b=A, l=LIA)
    with Session(pg.engine) as s:
        b = bank().bank(s, A, brand, _hash(pg), NOW)
        shown = bank().audiences(s, pg.b, brand, NOW)
        settings = s.execute(text("SELECT * FROM outreach_settings WHERE business_id = :b"), {"b": A}).mappings().one()
        ledger = bank()._ledger(s, A, settings, bank()._ready(s, A), NOW)
    assert b["drainable"] == 1 and b["held"] == 0 and b["oldest_days_left"] == 27
    assert shown and shown[0]["banked"] == 1
    assert set(ledger) == {"campaign", "cold", "total", "brand_day", "brand_month", "pilot", "blocked"}


def test_the_drain_enrols_the_banked_contact_and_cards_follow(banked):
    pg = banked
    with Session(pg.engine) as s:
        business = bank()._business(s, A)
        out = bank().drain_business(s, business, NOW)
    if out["skipped"]:
        pytest.fail(f"the seeded business could not drain: {out['skipped']}")
    assert out["enrolled"] == [PROSPECT]
    assert _count(pg, "SELECT count(*) FROM outreach_enrolments WHERE business_id = :b AND prospect_id = :p "
                      "AND campaign_id = :c AND next_step = 0", b=A, p=PROSPECT, c=CAMPAIGN) == 1
    with Session(pg.engine) as s:
        bank().prepare_all_due(s, NOW + timedelta(minutes=1))
    assert _count(pg, "SELECT count(*) FROM aria_actions WHERE business_id = :b AND action_type = 'send_outreach' "
                      "AND status = 'proposed'", b=A) == 1


def test_drain_due_finds_the_business_on_postgres(banked):
    with Session(banked.engine) as s:
        assert bank().drain_due(s, NOW)["businesses"] == 1
