"""OUT-19 D — the guards on paid research that outlived its sizing rule.
RED: paid research and the collection of personal data.

OUT-23 replaced "research only what can be emailed today" with the prospect
bank: sizing, the daily bounds and their accounting are now tested in
test_outreach_bank.py. What stays here: no search without a ready campaign on
a healthy inbox, one paid search per business at a time, the claim, the pilot
setting and the warm-up limit. Every adapter is faked.
"""
# ruff: noqa: F811 - pytest fixtures imported from test_outreach_setup are parameters by design

from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlmodel import Session

from test_outreach_setup import A, OWNER, WORKSPACE, _insert, db  # noqa: F401
from test_outreach_research import NOW, World, full_inbox, person, research, run, started
from test_outreach_research_brands import second_brand


@pytest.fixture(autouse=True)
def no_pilot_limit(monkeypatch):
    monkeypatch.setenv("OUTREACH_PILOT_ENROLMENTS", "0")


def kept(out):
    return len(out["accepted"])


# ------------------------------------------- nothing that cannot be emailed ---

def test_no_paid_search_for_a_brand_with_no_ready_campaign(db):
    biz, brand, lia, campaign = started(db)
    fit, fit_lia = second_brand(db, biz, inbox=False)
    world = World([[person(i) for i in range(10)]])
    out = run(db, biz, fit_lia, world)
    assert world.briefs == [] and kept(out) == 0 and "no ready campaign" in out["stopped"]


@pytest.mark.parametrize("change", ["health_status = 'fail'", "enabled = 0", "pause_reason = 'DNS'"])
def test_no_paid_search_while_the_inbox_cannot_send(db, change):
    biz, brand, lia, campaign = started(db)
    with Session(db) as s:
        s.execute(text(f"UPDATE outreach_mailboxes SET {change} WHERE mailbox_id = :m"), {"m": WORKSPACE})
        s.commit()
    world = World([[person(i) for i in range(10)]])
    assert kept(run(db, biz, lia, world)) == 0 and world.briefs == []


@pytest.mark.parametrize("raw,expected", [("", 5), ("0", 0), ("12", 12), ("-1", 5), ("lots", 5)])
def test_the_pilot_limit_setting(monkeypatch, raw, expected):
    monkeypatch.setenv("OUTREACH_PILOT_ENROLMENTS", raw)
    assert research().pilot_enrolments() == expected


def test_research_plans_with_the_send_paths_own_warm_up_limit(db):
    """One number for the warm-up limit: the send path asserts it agrees."""
    import inspect
    from services import metering
    # OUT-19 G: the same function, now given the inbox's boost as well.
    assert "mailbox_daily_cap(box, health, boost=boost)" in inspect.getsource(metering.reserve_outreach_usage)
    biz, brand, lia, campaign = started(db, full=False)
    with Session(db) as s:
        box = s.execute(text("SELECT * FROM outreach_mailboxes WHERE mailbox_id = :m"), {"m": WORKSPACE}).mappings().one()
        assert metering.mailbox_daily_cap(box) == 5
    full_inbox(db)
    with Session(db) as s:
        box = s.execute(text("SELECT * FROM outreach_mailboxes WHERE mailbox_id = :m"), {"m": WORKSPACE}).mappings().one()
        assert metering.mailbox_daily_cap(box) == 20


# ------------------------------------------ Codex OUT-19 D review 1 findings ---

def test_another_audiences_campaign_gives_this_audience_no_room(db):
    """P1 2: only campaigns for this audience count."""
    from test_outreach_setup import draft_lia, setup_module_or_missing
    m = setup_module_or_missing()
    from test_outreach_research import setup_clock
    biz, brand, lia, campaign = started(db)
    with setup_clock(), Session(db) as s:
        other = m.draft_audience(s, biz, OWNER, {"brand_id": brand["id"], "description": "Schools in Kent",
                                                "segments": ["school"], "regions": ["Kent"]}, draft=draft_lia)
        m.approve_audience(s, biz, OWNER, other["id"], {})
    world = World([[person(i) for i in range(10)]])
    out = run(db, biz, other, world)
    assert world.briefs == [] and kept(out) == 0 and "no ready campaign" in out["stopped"]


def test_a_second_run_during_a_search_waits_and_pays_nothing(db):
    """P1 4/5: one paid search per business at a time, so two runs (another
    audience, or another brand on the same inbox) never pay for the same places."""
    biz, brand, lia, campaign = started(db)
    fit, fit_lia = second_brand(db, biz)
    seen = {}
    first = World([[person(i) for i in range(5)]])
    real_search = first.search

    def search_while_another_runs(brief):
        second = World([[person(100 + i) for i in range(5)]])
        seen["out"] = run(db, biz, fit_lia, second)
        seen["briefs"] = second.briefs
        return real_search(brief)
    first.search = search_while_another_runs
    assert kept(run(db, biz, lia, first)) == 5
    assert seen["briefs"] == [] and "Another search" in seen["out"]["stopped"] and seen["out"]["spend_pence"] == 0
    assert kept(run(db, biz, fit_lia, World([[person(200 + i) for i in range(5)]]))) == 5, "free again afterwards"


def test_room_is_checked_under_the_lock_before_paying(db, monkeypatch):
    """P1 5: the room is read again under the lock, so a change just before paying stops the search."""
    biz, brand, lia, campaign = started(db)
    r = research()
    real = r._lock
    calls = []

    def lock(session, bid):
        if not calls:                                  # another session pauses the campaign first
            with db.begin() as c:
                c.execute(text("UPDATE outreach_campaigns SET status = 'paused' WHERE id = :c"), {"c": campaign["id"]})
        calls.append(1)
        return real(session, bid)
    monkeypatch.setattr(r, "_lock", lock)
    world = World([[person(i) for i in range(10)]])
    out = run(db, biz, lia, world)
    assert world.briefs == [] and out["spend_pence"] == 0 and kept(out) == 0


def test_manual_enrolment_follows_the_same_pilot_setting():
    """P2: one setting for every enrolment path."""
    import inspect
    from services import outreach_manage
    assert "pilot_enrolments()" in inspect.getsource(outreach_manage.enrol)
    assert "<= 5" not in inspect.getsource(outreach_manage.enrol)


# ------------------------------------------ Codex OUT-19 D review 2 findings ---

def test_a_search_that_outlives_its_claim_stores_nothing_once_another_took_over(db, monkeypatch):
    """P1 2: the claim runs on the real clock; a run that went quiet for more
    than 15 minutes loses it, and checks before storing."""
    biz, brand, lia, campaign = started(db)
    fit, fit_lia = second_brand(db, biz)
    r = research()
    clock = [NOW]
    monkeypatch.setattr(r, "now", lambda: clock[0])
    first = World([[person(i) for i in range(5)]])
    real_search, seen = first.search, {}

    def slow_search(brief):
        clock[0] = NOW + timedelta(minutes=16)
        seen["second"] = run(db, biz, fit_lia, World([[person(100 + i) for i in range(5)]]))
        return real_search(brief)
    first.search = slow_search
    out = run(db, biz, lia, first)
    assert kept(seen["second"]) == 5, "the claim had lapsed, so the second run searched"
    assert kept(out) == 0 and "took over" in out["stopped"]
    assert len(first.briefs) == 1, "and the first run never takes the claim back"


def test_a_claim_is_renewed_while_its_owner_works(db, monkeypatch):
    biz, brand, lia, campaign = started(db)
    r = research()
    clock = [NOW]
    monkeypatch.setattr(r, "now", lambda: clock[0])
    with Session(db) as s:
        r._lock(s, A)
        token = r._claim_search(s, A)
        s.commit()
        clock[0] = NOW + timedelta(minutes=10)
        r._lock(s, A)
        assert r._claim_search(s, A, token) == token          # renewed by its owner
        s.commit()
        clock[0] = NOW + timedelta(minutes=20)                 # 10 after the renewal: still held
        r._lock(s, A)
        assert r._claim_search(s, A) is None
        s.rollback()


def test_a_run_that_fails_gives_its_claim_back(db):
    """P2: whatever fails, the claim is released."""
    biz, brand, lia, campaign = started(db)
    world = World([[person(i) for i in range(5)]])

    def broken(url):
        raise RuntimeError("verification crashed")
    world.fetch = broken
    with pytest.raises(RuntimeError):
        run(db, biz, lia, world)
    with Session(db) as s:
        assert research().SEARCH_KEY not in research()._doc(s, A)
    assert kept(run(db, biz, lia, World([[person(50 + i) for i in range(5)]]))) == 5


@pytest.mark.parametrize("limit,allowed", [("0", True), ("7", True), ("6", False)])
def test_manual_enrolment_follows_the_pilot_setting(db, monkeypatch, limit, allowed):
    """P2, behaviourally: the owner's own enrolment obeys the same setting."""
    from services import outreach_manage
    from services.aria_actions import ActionRefused
    biz, brand, lia, campaign = started(db)
    out = run(db, biz, lia, World([[person(i) for i in range(7)]]))
    with Session(db) as s:
        s.execute(text("DELETE FROM outreach_enrolments WHERE business_id = :b"), {"b": A})
        s.commit()
    monkeypatch.setenv("OUTREACH_PILOT_ENROLMENTS", limit)
    from test_outreach_research import run_clock
    with run_clock(), Session(db) as s:
        if allowed:
            assert len(outreach_manage.enrol(s, biz, OWNER, campaign["id"], {"prospect_ids": out["accepted"]})["items"]) == 7
        else:
            with pytest.raises(ActionRefused) as exc:
                outreach_manage.enrol(s, biz, OWNER, campaign["id"], {"prospect_ids": out["accepted"]})
            assert "6" in exc.value.detail
