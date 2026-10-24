"""OUT-18 part A — research per brand (docs/OUT-18-TICKET.md). RED: spend
caps and the daily limits on collecting personal data.

Mike, 24 Oct 2026: 20 new contacts a day PER BRAND, and a research budget
per brand, £20 a month by default and never lower, raised whenever needed.
Every adapter is faked; no network or model call happens here.
"""
# ruff: noqa: F811 - pytest fixtures imported from test_outreach_setup are parameters by design

import json

import pytest
from sqlalchemy import text
from sqlmodel import Session

from test_outreach_setup import A, OWNER, STAFF, db, draft_lia, setup_module_or_missing  # noqa: F401
from test_outreach_research import NOW, World, count, gatekeeper, person, research, run, started


def meter(brand):
    return f"outreach_research_pence:{brand['id']}"


def second_brand(db, biz, *, name="FitFutures", enabled=True, cap=2000):
    """A second brand with its own approved audience (no campaign needed to research)."""
    m = setup_module_or_missing()
    with Session(db) as s:
        brand = m.save_brand(s, biz, OWNER, {"name": name, "sender_identity": f"{name} by New Body"})
        lia = m.draft_audience(s, biz, OWNER, {"brand_id": brand["id"], "description": "Gyms that could host interns",
                                              "segments": ["gym"], "regions": ["Kent"]}, draft=draft_lia)
        m.approve_audience(s, biz, OWNER, lia["id"], {})
        research().configure(s, biz, OWNER, {"brand_id": brand["id"], "enabled": enabled, "monthly_cap_pence": cap})
    return brand, lia


def spent(db, brand):
    return int(float(count(db, "SELECT coalesce(sum(value), 0) FROM usage_meters WHERE business_id = :b AND meter = :m",
                           m=meter(brand))))


def batch(start):
    return [person(start + i) for i in range(15)] + [gatekeeper(start + 100 + i) for i in range(10)]


# -------------------------------------------------------- 20 a day per brand ---

def test_each_brand_gets_its_own_twenty_a_day(db):
    biz, brand, lia, campaign = started(db)
    fit, fit_lia = second_brand(db, biz)
    first = run(db, biz, lia, World([batch(0)]))
    second = run(db, biz, fit_lia, World([batch(1000)]))
    assert len(first["accepted"]) == 20 and len(second["accepted"]) == 20
    assert count(db, "SELECT count(*) FROM outreach_prospects WHERE business_id = :b AND eligibility = 'eligible'") == 40


def test_each_brand_has_at_most_ten_gatekeepers_a_day(db):
    biz, brand, lia, campaign = started(db)
    fit, fit_lia = second_brand(db, biz)
    run(db, biz, lia, World([[gatekeeper(i) for i in range(12)]]))
    out = run(db, biz, fit_lia, World([[gatekeeper(500 + i) for i in range(12)]]))
    assert out["gatekeepers"] == 10


def test_a_brands_audiences_still_share_its_twenty(db):
    m = setup_module_or_missing()
    biz, brand, lia, campaign = started(db)
    with Session(db) as s:
        lia2 = m.draft_audience(s, biz, OWNER, {"brand_id": brand["id"], "description": "Schools in Essex",
                                               "segments": ["school"], "regions": ["Essex"]}, draft=draft_lia)
        m.approve_audience(s, biz, OWNER, lia2["id"], {})
    run(db, biz, lia, World([batch(0)]))
    assert run(db, biz, lia2, World([batch(2000)]))["accepted"] == []


# ---------------------------------------------------------- budget per brand ---

def test_spend_is_metered_per_brand(db):
    biz, brand, lia, campaign = started(db)
    fit, fit_lia = second_brand(db, biz)
    run(db, biz, lia, World([batch(0)], cost=37))          # a full day in one search
    run(db, biz, fit_lia, World([batch(1000)], cost=11))
    assert spent(db, brand) == 37 and spent(db, fit) == 11


def test_one_brand_at_its_budget_never_stops_another(db):
    biz, brand, lia, campaign = started(db)
    fit, fit_lia = second_brand(db, biz)
    with db.begin() as c:
        c.execute(text("INSERT INTO usage_meters (business_id, meter, period, value, updated_at) VALUES "
                       "(:b, :m, '2026-10', 1995, :at)"), {"b": A, "m": meter(brand), "at": NOW.isoformat()})
    stopped = World([[person(1)]])
    assert "budget" in run(db, biz, lia, stopped)["stopped"] and stopped.briefs == []
    assert len(run(db, biz, fit_lia, World([[person(2)]]))["accepted"]) == 1


def test_a_new_brand_starts_at_twenty_pounds_and_the_owner_can_raise_it(db):
    biz, brand, lia, campaign = started(db)
    m = setup_module_or_missing()
    with Session(db) as s:
        fit = m.save_brand(s, biz, OWNER, {"name": "FitFutures", "sender_identity": "FitFutures"})
        r = research()
        row = next(b for b in r.status(s, biz)["brands"] if b["brand_id"] == fit["id"])
        assert row["monthly_cap_pence"] == 2000
        r.configure(s, biz, OWNER, {"brand_id": fit["id"], "monthly_cap_pence": 7500})
        row = next(b for b in r.status(s, biz)["brands"] if b["brand_id"] == fit["id"])
        assert row["monthly_cap_pence"] == 7500


@pytest.mark.parametrize("cap", [0, 1999, 100001, -5])
def test_a_brand_budget_is_never_below_twenty_pounds_or_above_a_thousand(db, cap):
    biz, brand, lia, campaign = started(db)
    with Session(db) as s:
        with pytest.raises(Exception) as caught:
            research().configure(s, biz, OWNER, {"brand_id": brand["id"], "monthly_cap_pence": cap})
    assert getattr(caught.value, "status_code", None) == 422


def test_budget_and_switch_are_owner_only_and_for_this_business_brands_only(db):
    biz, brand, lia, campaign = started(db)
    r = research()
    with Session(db) as s:
        with pytest.raises(Exception):
            r.configure(s, biz, STAFF, {"brand_id": brand["id"], "monthly_cap_pence": 5000})
        with pytest.raises(Exception) as caught:
            r.configure(s, biz, OWNER, {"brand_id": "00000000-0000-0000-0000-000000000000", "enabled": True})
    assert getattr(caught.value, "status_code", None) == 404


def test_an_overspend_pauses_only_that_brand(db):
    biz, brand, lia, campaign = started(db)
    fit, fit_lia = second_brand(db, biz)
    r = research()
    out = run(db, biz, lia, World([[person(1)]], cost=r.MAX_SEARCH_PENCE + 9))
    assert "paused" in out["stopped"]
    with Session(db) as s:
        rows = {b["brand_id"]: b for b in r.status(s, biz)["brands"]}
    assert rows[brand["id"]]["enabled"] is False and rows[brand["id"]]["paused_reason"]
    assert rows[fit["id"]]["enabled"] is True
    assert len(run(db, biz, fit_lia, World([[person(2)]]))["accepted"]) == 1


def test_lowering_one_brand_budget_mid_run_stops_its_next_search(db):
    biz, brand, lia, campaign = started(db)
    world = World([[person(1)], [person(2)], [person(3)]])
    real = world.search

    def search_then_lower(brief):
        out = real(brief)
        with db.begin() as c:
            doc = json.loads(c.execute(text("SELECT settings FROM business_settings WHERE business_id = :b"),
                                       {"b": A}).scalar())
            doc["outreach_research"]["brands"][brand["id"]]["monthly_cap_pence"] = 0
            c.execute(text("UPDATE business_settings SET settings = :s WHERE business_id = :b"),
                      {"s": json.dumps(doc), "b": A})
        return out
    world.search = search_then_lower
    run(db, biz, lia, world)
    assert len(world.briefs) == 1


def test_legacy_business_spend_this_month_counts_against_every_brand(db):
    """Fail closed: spend from before OUT-18 is not forgotten mid-month."""
    biz, brand, lia, campaign = started(db)
    fit, fit_lia = second_brand(db, biz)
    with db.begin() as c:
        c.execute(text("INSERT INTO usage_meters (business_id, meter, period, value, updated_at) VALUES "
                       "(:b, 'outreach_research_pence', '2026-10', 1995, :at)"), {"b": A, "at": NOW.isoformat()})
    for target in (lia, fit_lia):
        world = World([[person(1)]])
        assert "budget" in run(db, biz, target, world)["stopped"] and world.briefs == []


def test_a_legacy_business_setting_becomes_each_brand_starting_value_never_below_twenty(db):
    biz, brand, lia, campaign = started(db)
    with db.begin() as c:
        doc = json.loads(c.execute(text("SELECT settings FROM business_settings WHERE business_id = :b"), {"b": A}).scalar())
        doc["outreach_research"] = {"enabled": True, "monthly_cap_pence": 500, "rotation": {}, "lessons": []}
        c.execute(text("UPDATE business_settings SET settings = :s WHERE business_id = :b"), {"s": json.dumps(doc), "b": A})
    with Session(db) as s:
        row = next(b for b in research().status(s, biz)["brands"] if b["brand_id"] == brand["id"])
    assert row["enabled"] is True and row["monthly_cap_pence"] == 2000


# ------------------------------------------------------------ switch per brand ---

def test_a_brand_switched_off_never_researches(db):
    biz, brand, lia, campaign = started(db)
    fit, fit_lia = second_brand(db, biz, enabled=False)
    world = World([[person(1)]])
    out = run(db, biz, fit_lia, world)
    assert world.briefs == [] and out["stopped"] and spent(db, fit) == 0


def test_the_daily_pass_runs_only_switched_on_brands(db):
    biz, brand, lia, campaign = started(db)
    fit, fit_lia = second_brand(db, biz, enabled=False)
    seen = []
    with Session(db) as s:
        research().run_due(s, moment=NOW, runner=lambda s, b, cid, moment: seen.append(cid))
    assert seen == [lia["id"]]


def test_a_business_with_any_brand_switched_on_is_picked_up_daily(db):
    biz, brand, lia, campaign = started(db)
    fit, fit_lia = second_brand(db, biz)
    with Session(db) as s:
        research().configure(s, biz, OWNER, {"brand_id": brand["id"], "enabled": False})
    seen = []
    with Session(db) as s:
        research().run_due(s, moment=NOW, runner=lambda s, b, cid, moment: seen.append(cid))
    assert seen == [fit_lia["id"]]


# ------------------------------------------------------------ lessons per brand ---

def test_the_brief_names_the_brand_and_carries_only_its_own_notes(db):
    biz, brand, lia, campaign = started(db)
    fit, fit_lia = second_brand(db, biz)
    r = research()
    with Session(db) as s:
        r.save_lessons(s, biz, OWNER, ["Independent gyms reply; chains don't."], brand_id=fit["id"])
        r.save_lessons(s, biz, OWNER, ["Heads of PE answer quickly."], brand_id=brand["id"])
        fit_brief = r.plan(s, biz, fit_lia["id"], moment=NOW)["brief"]
        gym_brief = r.plan(s, biz, lia["id"], moment=NOW)["brief"]
    assert "FitFutures" in fit_brief and "Independent gyms reply" in fit_brief and "Heads of PE" not in fit_brief
    assert "New Body Gym" in gym_brief and "Heads of PE" in gym_brief and "Independent gyms reply" not in gym_brief


def test_lessons_from_results_count_only_that_brands_contacts(db):
    biz, brand, lia, campaign = started(db)
    fit, fit_lia = second_brand(db, biz)
    run(db, biz, fit_lia, World([[person(i, segment="gym", region="Kent") for i in range(6)]]))
    with db.begin() as c:
        for (pid,) in c.execute(text("SELECT id FROM outreach_prospects WHERE business_id = :b"), {"b": A}).fetchall():
            c.execute(text("INSERT INTO outreach_messages (id, business_id, prospect_id, direction, state) "
                           "VALUES (:id, :b, :p, 'outbound', 'accepted')"),
                      {"id": f"m-{pid}", "b": A, "p": pid})
    r = research()
    with Session(db) as s:
        assert any("gym in Kent" in line for line in r.lessons(s, biz, brand_id=fit["id"]))
        assert not any("gym in Kent" in line for line in r.lessons(s, biz, brand_id=brand["id"]))


def test_lesson_notes_are_owner_only_per_brand(db):
    biz, brand, lia, campaign = started(db)
    with Session(db) as s:
        with pytest.raises(Exception):
            research().save_lessons(s, biz, STAFF, ["x"], brand_id=brand["id"])


def test_status_lists_every_brand_with_its_budget_and_spend(db):
    biz, brand, lia, campaign = started(db)
    fit, fit_lia = second_brand(db, biz, cap=5000)
    run(db, biz, fit_lia, World([batch(0)], cost=23))
    with Session(db) as s:
        rows = {b["brand_id"]: b for b in research().status(s, biz)["brands"]}
    assert rows[fit["id"]] == {**rows[fit["id"]], "name": "FitFutures", "enabled": True,
                               "monthly_cap_pence": 5000, "spent_pence": 23}
    assert rows[brand["id"]]["name"] == "New Body Gym" and rows[brand["id"]]["spent_pence"] == 0


@pytest.mark.parametrize("body,ok", [
    ({"enabled": True}, False),                                              # no brand
    ({"brand_id": "8b1d0f4e-1c1a-4a8e-9f0e-2b9b8a2c1d11", "monthly_cap_pence": 1999}, False),
    ({"brand_id": "8b1d0f4e-1c1a-4a8e-9f0e-2b9b8a2c1d11", "monthly_cap_pence": 2000}, True),
    ({"brand_id": "8b1d0f4e-1c1a-4a8e-9f0e-2b9b8a2c1d11", "enabled": False}, True),
])
def test_the_research_api_needs_a_brand_and_at_least_twenty_pounds(body, ok):
    from pydantic import ValidationError
    from outreach_setup_api import Lessons, ResearchConfig
    if ok:
        ResearchConfig(**body)
    else:
        with pytest.raises(ValidationError):
            ResearchConfig(**body)
    with pytest.raises(ValidationError):
        Lessons(lessons=["x"])
