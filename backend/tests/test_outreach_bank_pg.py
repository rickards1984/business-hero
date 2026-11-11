"""OUT-23 bank on real PostgreSQL (the local harness): the sizing, ledger,
drain and card-preparation SQL against the real schema, types and foreign
keys. Skips without the harness; a skip is not a pass."""
# ruff: noqa: F811 - the pg fixture is a parameter by design
import threading
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlmodel import Session

from test_outreach_send_rls import DATABASE_URL, OWNER, _approve, _count, _propose, pg  # noqa: F401
from test_outreach_send import A, CAMPAIGN, EMAIL, ENROLMENT, LIA, NOW, PROSPECT

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
    yield pg
    with pg.engine.begin() as c:                 # erasure's own rows, which the shared teardown does not know
        for table in ("outreach_recently_erased", "outreach_erasure_exceptions"):
            c.execute(text(f"DELETE FROM {table} WHERE business_id = :b"), {"b": A})


def _hash(pg):
    return _count(pg, "SELECT audience_hash FROM outreach_compliance WHERE business_id = :b AND id = :l", b=A, l=LIA)


def test_sizing_and_stock_run_on_postgres(banked):
    pg = banked
    brand = _count(pg, "SELECT brand_id FROM outreach_compliance WHERE business_id = :b AND id = :l", b=A, l=LIA)
    with Session(pg.engine) as s:
        b = bank().bank(s, A, brand, _hash(pg), NOW)
        shown = bank().audiences(s, pg.b, brand, NOW)
        settings = s.execute(text("SELECT * FROM outreach_settings WHERE business_id = :b"), {"b": A}).mappings().one()
        ledger = bank()._ledger(s, A, settings, NOW)
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


# ------------------------------------------------- interleavings (R4.7, B7) ---

def _held_drain(pg, monkeypatch, other):
    """Run the drain, hold it inside its transaction (locks taken, ledger
    read), start `other` in a second session, then let the drain finish.
    Returns (drain result, other's result or exception, whether other had
    finished before the drain was released)."""
    inside, release = threading.Event(), threading.Event()
    real = bank()._ledger

    def held(*a, **k):
        out = real(*a, **k)
        inside.set()
        release.wait(10)
        return out
    monkeypatch.setattr(bank(), "_ledger", held)
    got = {}

    def drain():
        with Session(pg.engine) as s:
            got["drain"] = bank().drain_business(s, bank()._business(s, A), NOW)

    def run_other():
        try:
            with Session(pg.engine) as s:
                got["other"] = other(s)
        except Exception as exc:          # noqa: BLE001 - reported to the test
            got["other"] = exc
    t1 = threading.Thread(target=drain)
    t1.start()
    assert inside.wait(10), "the drain never reached its ledger"
    t2 = threading.Thread(target=run_other)
    t2.start()
    t2.join(1.5)
    early = not t2.is_alive()
    release.set()
    t1.join(10)
    t2.join(10)
    assert not t1.is_alive() and not t2.is_alive(), "deadlock"
    return got["drain"], got.get("other"), early


def test_manual_enrolment_waits_for_the_drain_and_never_doubles(banked, monkeypatch):
    from services import outreach_manage
    pg = banked
    drained, other, early = _held_drain(
        pg, monkeypatch, lambda s: outreach_manage.enrol(s, pg.b, OWNER, CAMPAIGN, {"prospect_ids": [PROSPECT]}))
    assert not early, "the owner's enrolment waited on the drain's lock"
    assert drained["enrolled"] == [PROSPECT]
    assert _count(pg, "SELECT count(*) FROM outreach_enrolments WHERE business_id = :b AND prospect_id = :p",
                  b=A, p=PROSPECT) == 1


def test_an_unsubscribe_waits_and_the_contact_is_then_stopped(banked, monkeypatch):
    from services import outreach_manage
    pg = banked
    drained, other, early = _held_drain(
        pg, monkeypatch, lambda s: outreach_manage.suppress(s, pg.b, OWNER, {"email": EMAIL}))
    assert not early and not isinstance(other, Exception), other
    # Whichever came first, the contact is suppressed and no live enrolment is left.
    assert _count(pg, "SELECT count(*) FROM outreach_suppressions WHERE business_id = :b", b=A) >= 1
    assert _count(pg, "SELECT count(*) FROM outreach_enrolments WHERE business_id = :b AND prospect_id = :p "
                      "AND state IN ('pending', 'active')", b=A, p=PROSPECT) == 0


def test_a_suppressed_contact_is_never_drained(banked):
    from services import outreach_manage
    pg = banked
    with Session(pg.engine) as s:
        outreach_manage.suppress(s, pg.b, OWNER, {"email": EMAIL})
    with Session(pg.engine) as s:
        assert bank().drain_business(s, bank()._business(s, A), NOW)["enrolled"] == []


def test_erasure_and_the_drain_serialise(banked, monkeypatch):
    """Erasure takes outreach_settings, as the drain does: it waits, then
    erases the (never emailed) contact the drain enrolled."""
    from services import outreach_erasure
    pg = banked
    later = NOW + timedelta(days=29)
    drained, other, early = _held_drain(
        pg, monkeypatch, lambda s: outreach_erasure.erase_never_contacted(s, A, PROSPECT, later))
    assert not early
    assert drained["enrolled"] == [PROSPECT] and other["erased"] is True, other
    assert _count(pg, "SELECT count(*) FROM outreach_prospects WHERE business_id = :b", b=A) == 0


def test_an_approval_during_the_drain_neither_deadlocks_nor_fails(banked, monkeypatch):
    """The seeded contact back in a campaign with a card; the owner approves
    it while the drain holds its lock."""
    pg = banked
    with pg.engine.begin() as c:
        seq = c.execute(text("SELECT sequence_version FROM outreach_campaigns WHERE id = :c"), {"c": CAMPAIGN}).scalar()
        c.execute(text("INSERT INTO outreach_enrolments (id, business_id, prospect_id, campaign_id, sequence_version, "
                       "state, next_step, next_due_at) VALUES (:e, :b, :p, :c, :v, 'active', 0, :t)"),
                  {"e": ENROLMENT, "b": A, "p": PROSPECT, "c": CAMPAIGN, "v": seq, "t": NOW})
    card = _propose(pg)
    drained, other, early = _held_drain(pg, monkeypatch, lambda s: _approve(pg, card))
    assert not isinstance(other, Exception), other
    assert drained["skipped"] is None and drained["enrolled"] == []      # nothing banked: it was enrolled
    assert _count(pg, "SELECT state FROM outreach_messages WHERE business_id = :b", b=A) == "accepted"
