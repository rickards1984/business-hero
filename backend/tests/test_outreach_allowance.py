"""OUT-19 B + C — each brand's hidden AI allowance, and the owner's monthly
budget (docs/OUT-19-TICKET.md). RED: money.

Mike, 27 Oct 2026 ("go with the recommendations; review when live"):
  * B: a brand's AI spend is capped at 25% of what it pays (£79 → £19.75,
    the Pro add-on £99 → £24.75); a Business plan's included brand has a
    fixed £20. All of a brand's AI spend counts (research, drafting, reply
    sorting). At the allowance research stops until next month or a top-up;
    Aria's drafting carries on within a small reserve; reply sorting never
    stops (an unsubscribe must always be understood). The owner's research
    budget can only lower it, never raise it.
  * C: one £ figure for what outreach may charge each month beyond the plan
    (add-on brands and top-ups). Aria suggests one; nothing is charged beyond it.

Tests first, for Mike's approval: strict xfail until services.outreach_allowance
exists. Every adapter is faked; no network, no model, no payment.
"""
# ruff: noqa: F811 - pytest fixtures imported from the research harness are parameters by design

import importlib
import importlib.util

import pytest
from sqlalchemy import text
from sqlmodel import Session

from test_outreach_setup import A, OWNER, STAFF, db  # noqa: F401
from test_outreach_research import NOW, World, person, research, run, run_clock, started
from test_outreach_research_brands import second_brand
from test_outreach_replies import r  # noqa: F401
from test_outreach_send import database, h  # noqa: F401


class MissingAllowance(AssertionError):
    """Only the intentional absence of the module may be xfailed."""


# Mike approved these tests on 27 Oct 2026; the strict-xfail marker is removed.


@pytest.fixture(autouse=True)
def no_pilot_limit(monkeypatch):
    monkeypatch.setenv("OUTREACH_PILOT_ENROLMENTS", "0")


def allowance():
    if importlib.util.find_spec("services.outreach_allowance") is None:
        raise MissingAllowance("backend/services/outreach_allowance.py does not exist yet")
    return importlib.import_module("services.outreach_allowance")


PERIOD = "2026-10"
CURRENT = [{"subject": f"Step {i}", "body": f"Body {i}"} for i in range(3)]


def spend(db, brand, pence, purpose="draft"):
    """AI spend already recorded this month for a brand, as the ledger records it."""
    from services import ai_costs
    with Session(db) as s:
        ai_costs.record(s, A, purpose=purpose, brand_id=brand["id"], provider="openai", model="gpt-6.1-sol",
                        pence=pence, moment=NOW)
        s.commit()


def plan(db, tier):
    with db.begin() as c:
        c.execute(text("UPDATE businesses SET plan_tier = :p WHERE id = :b"), {"p": tier, "b": A})


# ------------------------------------------------------------ B: the allowance ---

def test_a_brand_may_spend_a_quarter_of_what_it_pays():
    """£99 add-on → £24.75; each extra brand £79 → £19.75; Business plan's included brand → £20."""
    m = allowance()
    assert m.allowance_for_price(9900, included=False) == 2475
    assert m.allowance_for_price(7900, included=False) == 1975
    assert m.allowance_for_price(0, included=True) == 2000


def test_each_brands_allowance_follows_its_place_and_the_plan(db):
    m = allowance()
    biz, brand, lia, campaign = started(db)          # business A is on Pro: its first brand is the £99 add-on
    fit, fit_lia = second_brand(db, biz)              # an extra brand: £79
    with db.begin() as c:                             # made after the first (the fixtures share one pinned clock)
        c.execute(text("UPDATE outreach_brands SET created_at = :t WHERE id = :b"), {"t": NOW.isoformat(), "b": fit["id"]})
    with Session(db) as s:
        assert m.allowance_pence(s, A, brand["id"], PERIOD) == 2475
        assert m.allowance_pence(s, A, fit["id"], PERIOD) == 1975
    plan(db, "business")
    with Session(db) as s:
        assert m.allowance_pence(s, A, brand["id"], PERIOD) == 2000     # included in Business
        assert m.allowance_pence(s, A, fit["id"], PERIOD) == 1975


def test_all_of_a_brands_ai_spend_counts_and_only_its_own(db):
    m = allowance()
    biz, brand, lia, campaign = started(db)
    fit, fit_lia = second_brand(db, biz)
    spend(db, brand, 300, "draft")
    spend(db, brand, 40, "classify")
    spend(db, fit, 999, "draft")
    with Session(db) as s:
        assert m.spent_pence(s, A, brand["id"], PERIOD) == 340


def test_research_stops_at_the_allowance(db):
    """Spend from any purpose brings research to a stop before it pays for a search."""
    allowance()
    biz, brand, lia, campaign = started(db)
    spend(db, brand, 2450)                            # £24.50 of £24.75 used: no room for a search's reserve
    world = World([[person(i) for i in range(5)]])
    out = run(db, biz, lia, world)
    assert world.briefs == [] and out["spend_pence"] == 0
    assert "allowance" in out["stopped"] and "next month" in out["stopped"]
    assert "top-up" in out["stopped"].lower(), "since part F a top-up is offered"


def test_research_runs_while_the_allowance_has_room(db):
    allowance()
    biz, brand, lia, campaign = started(db)
    spend(db, brand, 1000)
    out = run(db, biz, lia, World([[person(i) for i in range(5)]], cost=30))
    assert len(out["accepted"]) == 5


def test_the_owners_research_budget_can_lower_the_allowance_but_never_raise_it(db):
    allowance()
    biz, brand, lia, campaign = started(db)
    with Session(db) as s:                            # a budget above the allowance changes nothing
        research().configure(s, biz, OWNER, {"brand_id": brand["id"], "monthly_cap_pence": 100000})
    spend(db, brand, 2450)
    world = World([[person(i) for i in range(5)]])
    run(db, biz, lia, world)
    assert world.briefs == []


def test_an_owners_lower_research_budget_still_applies(db):
    allowance()
    biz, brand, lia, campaign = started(db)
    with Session(db) as s:
        research().configure(s, biz, OWNER, {"brand_id": brand["id"], "monthly_cap_pence": 2000})
    with Session(db) as s:                            # research spend alone, as before
        research()._spend(s, A, NOW, 1990, brand["id"])
        s.commit()
    world = World([[person(i) for i in range(5)]])
    run(db, biz, lia, world)
    assert world.briefs == []


def test_one_brand_at_its_allowance_never_stops_another(db):
    allowance()
    biz, brand, lia, campaign = started(db)
    fit, fit_lia = second_brand(db, biz)
    spend(db, brand, 2475)
    assert len(run(db, biz, fit_lia, World([[person(100 + i) for i in range(5)]], cost=30))["accepted"]) == 5


def test_drafting_carries_on_within_a_small_reserve_then_stops(db):
    """At the allowance Aria can still draft (a little), so a campaign is never
    stranded; beyond the reserve she asks the owner to top up or write it."""
    m = allowance()
    from test_outreach_setup import setup_module_or_missing
    setup = setup_module_or_missing()
    biz, brand, lia, campaign = started(db)

    def drafter(context):
        return [{"subject": f"S{i}", "body": f"B{i}"} for i in range(3)]
    spend(db, brand, 2475 + m.DRAFT_RESERVE_PENCE - m.draft_hold_pence())   # exactly room for one draft's hold
    with run_clock(), Session(db) as s:
        assert len(setup.redraft_emails(s, biz, OWNER, campaign["id"], {"notes": "shorter", "current": CURRENT}, draft=drafter)["emails"]) == 3
    spend(db, brand, 1)
    from services.aria_actions import ActionRefused
    with run_clock(), Session(db) as s, pytest.raises(ActionRefused) as exc:
        setup.redraft_emails(s, biz, OWNER, campaign["id"], {"notes": "shorter", "current": CURRENT}, draft=drafter)
    assert "allowance" in exc.value.detail


def test_reply_sorting_is_never_stopped_by_the_allowance():
    """An unsubscribe or a question must always be understood: the reply
    classifier has no allowance check, and its cost is still recorded."""
    import inspect
    allowance()
    from services import chase_replies, outreach_replies
    for source in (inspect.getsource(chase_replies.classify_with_model), inspect.getsource(outreach_replies.scan)):
        assert "outreach_allowance" not in source and "may_research" not in source and "may_draft" not in source


def test_the_owner_sees_how_much_of_the_allowance_is_used_not_the_figure(db):
    allowance()
    biz, brand, lia, campaign = started(db)
    spend(db, brand, 1238)                            # half of £24.75
    with run_clock(), Session(db) as s:
        row = next(b for b in research().status(s, biz)["brands"] if b["brand_id"] == brand["id"])
    assert row["allowance_used_percent"] == 50
    assert "allowance_pence" not in row


def test_the_allowance_starts_again_each_month(db):
    m = allowance()
    biz, brand, lia, campaign = started(db)
    spend(db, brand, 2475)
    with Session(db) as s:
        assert m.spent_pence(s, A, brand["id"], "2026-11") == 0


# ----------------------------------------------------------- C: the budget ---

def test_aria_suggests_a_budget_from_the_brands(db):
    """Each paid brand's price, plus room for one £25 top-up per brand."""
    m = allowance()
    biz, brand, lia, campaign = started(db)            # Pro: first brand £99
    fit, fit_lia = second_brand(db, biz)               # extra brand £79
    with run_clock(), Session(db) as s:
        out = m.budget_status(s, biz, moment=NOW)
    assert out["committed_pence"] == 9900 + 7900
    assert out["suggested_pence"] == 9900 + 7900 + 2 * 2500
    assert out["budget_pence"] is None


def test_only_the_owner_sets_the_budget_and_never_below_what_is_already_committed(db):
    m = allowance()
    biz, brand, lia, campaign = started(db)
    with run_clock(), Session(db) as s:
        with pytest.raises(Exception) as exc:
            m.set_budget(s, biz, STAFF, {"monthly_pence": 20000})
        assert getattr(exc.value, "status_code", None) == 403
        s.rollback()
        with pytest.raises(Exception) as exc:
            m.set_budget(s, biz, OWNER, {"monthly_pence": 5000})     # below the £99 already committed
        assert getattr(exc.value, "status_code", None) == 422
        s.rollback()
        assert m.set_budget(s, biz, OWNER, {"monthly_pence": 15000})["budget_pence"] == 15000


def test_nothing_is_charged_beyond_the_budget(db):
    """The check every future charge (an extra brand, a top-up) must pass."""
    m = allowance()
    biz, brand, lia, campaign = started(db)
    with run_clock(), Session(db) as s:
        m.set_budget(s, biz, OWNER, {"monthly_pence": 15000})
    with run_clock(), Session(db) as s:
        assert m.can_charge(s, biz, 5100, moment=NOW) is True        # 9900 + 5100 = 15000
        assert m.can_charge(s, biz, 5101, moment=NOW) is False


def test_without_a_budget_charges_wait_for_the_owner(db):
    """No budget set: nothing beyond what is already committed is charged
    until the owner chooses one (Aria's suggestion is one tap)."""
    m = allowance()
    biz, brand, lia, campaign = started(db)
    with run_clock(), Session(db) as s:
        assert m.can_charge(s, biz, 1000, moment=NOW) is False


@pytest.mark.parametrize("who,code", [(OWNER, 200), (STAFF, 403)])
def test_the_budget_over_http(db, monkeypatch, who, code):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import auth
    import outreach_setup_api as api
    from auth import get_user_business_context
    from db import get_session
    allowance()
    biz, brand, lia, campaign = started(db)
    monkeypatch.setattr(auth, "_load_business", lambda session, bid: biz)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[get_user_business_context] = lambda: {"business_id": A, "user_id": who}
    app.dependency_overrides[get_session] = lambda: Session(db)
    with run_clock(), TestClient(app) as client:
        assert client.get("/v1/outreach/setup/budget").json()["suggested_pence"] == 9900 + 2500
        assert client.put("/v1/outreach/setup/budget", json={"monthly_pence": 15000}).status_code == code
        assert client.put("/v1/outreach/setup/budget", json={"monthly_pence": "lots"}).status_code == 422



# ------------------------------------------------------ Codex OUT-19 B+C review 1 ---

def test_a_draft_holds_its_cost_before_aria_starts_so_two_at_once_cannot_overrun(db):
    """P1: a second draft started while the first is still running sees the
    first one's hold, so together they never pass the allowance + reserve."""
    m = allowance()
    from test_outreach_setup import setup_module_or_missing
    from services.aria_actions import ActionRefused
    setup = setup_module_or_missing()
    biz, brand, lia, campaign = started(db)
    spend(db, brand, 2475 + m.DRAFT_RESERVE_PENCE - m.draft_hold_pence())   # room for exactly one hold
    seen = {}

    def first_drafter(context):
        with run_clock(), Session(db) as other:          # a second request arrives mid-draft
            try:
                setup.redraft_emails(other, biz, OWNER, campaign["id"], {"notes": "again", "current": CURRENT},
                                     draft=lambda c: [{"subject": "x", "body": "y"}] * 3)
                seen["second"] = "drafted"
            except ActionRefused as exc:
                seen["second"] = exc.detail
        return [{"subject": f"S{i}", "body": f"B{i}"} for i in range(3)]
    with run_clock(), Session(db) as s:
        assert len(setup.redraft_emails(s, biz, OWNER, campaign["id"], {"notes": "x", "current": CURRENT},
                                        draft=first_drafter)["emails"]) == 3
    assert "allowance" in seen["second"]


def held(db, m):
    with Session(db) as s:
        return float(s.execute(text("SELECT coalesce(sum(value), 0) FROM usage_meters WHERE meter LIKE :m"),
                               {"m": m.DRAFT_HOLD_METER + "%"}).scalar() or 0)


def test_a_finished_draft_releases_its_hold_and_keeps_its_real_cost(db):
    m = allowance()
    from test_outreach_setup import setup_module_or_missing
    from services import ai_costs
    setup = setup_module_or_missing()
    biz, brand, lia, campaign = started(db)
    during = {}

    def costly(context):
        during["held"] = held(db, m)
        ai_costs.note("openai", "gpt-6.1-sol", None, fallback=(1000, 1000), estimated=True)
        return [{"subject": f"S{i}", "body": f"B{i}"} for i in range(3)]
    with run_clock(), Session(db) as s:
        setup.redraft_emails(s, biz, OWNER, campaign["id"], {"notes": "x", "current": CURRENT}, draft=costly)
    assert during["held"] == m.draft_hold_pence(), "held while Aria drafted"
    assert held(db, m) == 0, "released once the real cost was recorded"
    with Session(db) as s:
        assert m.spent_pence(s, A, brand["id"], PERIOD) == int(ai_costs.cost("openai", "gpt-6.1-sol", 1000, 1000))


def test_a_draft_that_fails_without_reporting_its_cost_stays_held(db):
    """Review 2: an unknown failure may still have been billed: fail closed."""
    m = allowance()
    from test_outreach_setup import setup_module_or_missing
    setup = setup_module_or_missing()
    biz, brand, lia, campaign = started(db)

    def crashes(context):
        raise RuntimeError("connection reset")
    with run_clock(), Session(db) as s, pytest.raises(RuntimeError):
        setup.redraft_emails(s, biz, OWNER, campaign["id"], {"notes": "x", "current": CURRENT}, draft=crashes)
    assert held(db, m) == m.draft_hold_pence()


def failing_chain(monkeypatch):
    """Two priced providers that both fail without reporting usage, so each
    attempt is charged at its worst case, as json_chat does."""
    import json as _json
    from services import ai_router
    # Expensive on purpose: a fixed 50p hold would not cover one worst case here.
    monkeypatch.setenv("AI_PRICES_JSON", _json.dumps({"openai/gpt-6.1-sol": [20000, 20000, 0], "xai/grok-4.7": [20000, 20000, 0]}))
    monkeypatch.setattr(ai_router, "chain", lambda purpose, include_down=False: [("openai", "gpt-6.1-sol"), ("xai", "grok-4.7")])

    def fail(provider, model, system, user, max_tokens):
        raise ai_router.ProviderError("down")
    monkeypatch.setattr(ai_router, "_openai_compatible_chat", fail)
    monkeypatch.setattr(ai_router, "_anthropic_chat", fail)
    monkeypatch.setattr(ai_router, "_trip", lambda provider: None)


def test_a_model_drafts_hold_is_its_real_worst_case_over_the_whole_chain(db, monkeypatch):
    """Review 2 P1: for Aria's real drafters the hold is the provider chain's
    worst case for this request, so what is recorded never exceeds it."""
    m = allowance()
    from test_outreach_setup import setup_module_or_missing
    from services.aria_actions import ActionRefused
    setup = setup_module_or_missing()
    biz, brand, lia, campaign = started(db)
    failing_chain(monkeypatch)
    during = {}
    real = setup.ai_router.json_chat

    def watching(*args, **kwargs):
        during["held"] = held(db, m)
        return real(*args, **kwargs)
    monkeypatch.setattr(setup.ai_router, "json_chat", watching)
    with run_clock(), Session(db) as s, pytest.raises(ActionRefused):
        setup.redraft_emails(s, biz, OWNER, campaign["id"], {"notes": "x", "current": CURRENT})
    with Session(db) as s:
        recorded = m.spent_pence(s, A, brand["id"], PERIOD) - int(held(db, m))
    assert recorded > 0 and recorded <= during["held"], (recorded, during["held"])
    assert held(db, m) == 0, "every provider reported its failure and was recorded: fully accounted, released (review 4)"


def test_overlapping_model_drafts_never_pass_the_allowance_and_reserve(db, monkeypatch):
    """Review 2 P1: three drafts at once, each failing at its worst case."""
    m = allowance()
    from test_outreach_setup import setup_module_or_missing
    from services.aria_actions import ActionRefused
    setup = setup_module_or_missing()
    biz, brand, lia, campaign = started(db)
    failing_chain(monkeypatch)
    spend(db, brand, 2475 + m.DRAFT_RESERVE_PENCE - 600)            # room for one worst-case hold, not three drafts
    real, depth = setup.ai_router.json_chat, {"n": 0}

    def nested(*args, **kwargs):
        if depth["n"] < 2:                                          # another draft starts mid-draft, twice
            depth["n"] += 1
            with run_clock(), Session(db) as other:
                try:
                    setup.redraft_emails(other, biz, OWNER, campaign["id"], {"notes": "x", "current": CURRENT})
                except ActionRefused:
                    pass
        return real(*args, **kwargs)
    monkeypatch.setattr(setup.ai_router, "json_chat", nested)
    with run_clock(), Session(db) as s:
        try:
            setup.redraft_emails(s, biz, OWNER, campaign["id"], {"notes": "x", "current": CURRENT})
        except ActionRefused:
            pass
    with Session(db) as s:   # real recorded spend (failed drafts' holds also stay counted, on top)
        real = m.spent_pence(s, A, brand["id"], PERIOD) - int(held(db, m))
    assert real <= 2475 + m.DRAFT_RESERVE_PENCE


def test_a_draft_that_fails_part_way_keeps_its_whole_hold(db, monkeypatch):
    """Review 3: the first provider's failure was recorded, the fallback was
    interrupted after dispatch: its cost is unknown, so the hold stays."""
    m = allowance()
    from test_outreach_setup import setup_module_or_missing
    from services import ai_router
    setup = setup_module_or_missing()
    biz, brand, lia, campaign = started(db)
    failing_chain(monkeypatch)
    calls = {"n": 0}

    def first_fails_then_interrupted(provider, model, system, user, max_tokens):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ai_router.ProviderError("down")
        raise KeyboardInterrupt   # dispatched, never answered
    monkeypatch.setattr(ai_router, "_openai_compatible_chat", first_fails_then_interrupted)
    hold = {}
    real = setup._draft_hold

    def remember(draft, context):
        hold["p"] = real(draft, context)
        return hold["p"]
    monkeypatch.setattr(setup, "_draft_hold", remember)
    with run_clock(), Session(db) as s, pytest.raises(KeyboardInterrupt):
        setup.redraft_emails(s, biz, OWNER, campaign["id"], {"notes": "x", "current": CURRENT})
    assert held(db, m) == hold["p"]


def test_a_provider_counting_framing_tokens_stays_within_the_hold(db, monkeypatch):
    """Review 3: reported usage a little above the characters sent (message
    framing) is covered by the overhead margin."""
    m = allowance()
    from types import SimpleNamespace
    from test_outreach_setup import setup_module_or_missing
    from services import ai_router
    setup = setup_module_or_missing()
    biz, brand, lia, campaign = started(db)
    failing_chain(monkeypatch)
    captured = {}

    def answers(provider, model, system, user, max_tokens):
        tokens_in = len(system) + len(user) + setup.PROVIDER_OVERHEAD_TOKENS   # every character a token, plus framing
        captured["usage"] = SimpleNamespace(prompt_tokens=tokens_in, completion_tokens=max_tokens)
        return '{"emails": [{"subject": "s", "body": "b"}, {"subject": "s", "body": "b"}, {"subject": "s", "body": "b"}]}', captured["usage"]
    monkeypatch.setattr(ai_router, "_openai_compatible_chat", answers)
    during = {}
    real = setup.ai_router.json_chat

    def watching(*args, **kwargs):
        during["held"] = held(db, m)
        return real(*args, **kwargs)
    monkeypatch.setattr(setup.ai_router, "json_chat", watching)
    with run_clock(), Session(db) as s:
        setup.redraft_emails(s, biz, OWNER, campaign["id"], {"notes": "x", "current": CURRENT})
    with Session(db) as s:
        assert 0 < m.spent_pence(s, A, brand["id"], PERIOD) <= during["held"]


def test_every_draft_prompt_fits_the_bound(monkeypatch):
    """The bound assumes Aria's instructions are at most SYSTEM_PROMPT_MAX_CHARS."""
    allowance()
    from test_outreach_setup import setup_module_or_missing
    setup = setup_module_or_missing()
    seen = []

    def capture(system, context, *, purpose, max_tokens):
        seen.append(len(system))
        assert max_tokens == setup.DRAFT_MAX_TOKENS
        return {"emails": [{"subject": "s", "body": "b"}] * 3, "purpose": "p", "necessity": "n",
                "balancing_test": "b", "safeguards": "s", "notice": "n", "text": "t"}
    monkeypatch.setattr(setup.ai_router, "json_chat", capture)
    for drafter in setup.MODEL_DRAFTS:
        try:
            drafter({"brand": "x", "current_emails": CURRENT, "owner_notes": "n"})
        except Exception:
            pass
    assert seen and max(seen) <= setup.SYSTEM_PROMPT_MAX_CHARS


def test_a_draft_in_progress_holds_room_research_cannot_use(db):
    """Draft/research overlap: research started mid-draft sees the hold."""
    m = allowance()
    from test_outreach_setup import setup_module_or_missing
    setup = setup_module_or_missing()
    biz, brand, lia, campaign = started(db)
    reserve = research().search_reserve_pence()
    spend(db, brand, 2475 - reserve - m.draft_hold_pence() + 1)    # room for the search OR the hold, not both
    seen = {}

    def drafter(context):
        world = World([[person(i) for i in range(3)]])
        run(db, biz, lia, world)
        seen["briefs"] = world.briefs
        return [{"subject": f"S{i}", "body": f"B{i}"} for i in range(3)]
    with run_clock(), Session(db) as s:
        setup.redraft_emails(s, biz, OWNER, campaign["id"], {"notes": "x", "current": CURRENT}, draft=drafter)
    assert seen["briefs"] == []


def test_research_spend_from_before_brands_still_counts_against_every_brand(db):
    """P2: the business-wide research meter from before OUT-18 counts (fail closed)."""
    m = allowance()
    biz, brand, lia, campaign = started(db)
    with Session(db) as s:
        research()._add_meter(s, A, research().METER, NOW, 1900)
        research()._spend(s, A, NOW, 100, brand["id"])
        s.commit()
    with Session(db) as s:
        assert m.spent_pence(s, A, brand["id"], PERIOD) == 2000


def test_meter_names_are_matched_literally(db):
    """Backlog: '_' is a LIKE wildcard; a look-alike meter must not count."""
    m = allowance()
    biz, brand, lia, campaign = started(db)
    with Session(db) as s:
        s.execute(text("INSERT INTO usage_meters (business_id, meter, period, value, updated_at) VALUES "
                       "(:b, :m, :p, 500, :at)"), {"b": A, "m": f"aiXpence:draft:{brand['id']}:x/y", "p": PERIOD,
                                                  "at": NOW.isoformat()})
        s.commit()
        assert m.spent_pence(s, A, brand["id"], PERIOD) == 0


def test_reply_sorting_still_runs_above_the_allowance(r):
    """Backlog, behaviourally: with the brand far over its allowance, a reply
    is still classified (an unsubscribe must always be understood)."""
    from services import ai_costs
    from test_outreach_replies import incoming, scan
    from test_outreach_send import A as BIZ, BRAND, NOW as SEND_NOW
    allowance()
    ai_costs.record(r.s, BIZ, purpose="draft", brand_id=BRAND, provider="openai", model="gpt-6.1-sol",
                    pence=100000, moment=SEND_NOW)
    r.s.commit()
    incoming(r)

    def classify(_):
        ai_costs.note("openai", "gpt-6-luna", None, fallback=(500, 100), estimated=True)
        return {"category": "unsubscribe", "confidence": 100, "classification_version": 1}
    scan(r, classify=classify)
    assert r.s.execute(text("SELECT category FROM outreach_replies")).scalar() == "unsubscribe"
    recorded = r.s.execute(text("SELECT coalesce(sum(value), 0) FROM usage_meters WHERE meter LIKE 'ai_pence:classify:%'")).scalar()
    assert float(recorded or 0) > 0, "its cost is still recorded"



# ------------------------------------------------------ Codex OUT-19 B+C review 4 ---

def test_a_draft_tried_while_every_provider_is_down_releases_its_hold(db, monkeypatch):
    """P2: nothing was dispatched, so nothing can have been billed: retries in
    an outage never use up the brand's month."""
    m = allowance()
    from test_outreach_setup import setup_module_or_missing
    from services import ai_router
    from services.aria_actions import ActionRefused
    setup = setup_module_or_missing()
    biz, brand, lia, campaign = started(db)
    failing_chain(monkeypatch)
    every = [("openai", "gpt-6.1-sol"), ("xai", "grok-4.7")]
    monkeypatch.setattr(ai_router, "chain", lambda purpose, include_down=False: every if include_down else [])
    for _ in range(3):
        with run_clock(), Session(db) as s, pytest.raises(ActionRefused):
            setup.redraft_emails(s, biz, OWNER, campaign["id"], {"notes": "x", "current": CURRENT})
    assert held(db, m) == 0
    with Session(db) as s:
        assert m.spent_pence(s, A, brand["id"], PERIOD) == 0


def test_the_framing_margin_is_what_keeps_a_full_answer_within_its_hold(db, monkeypatch):
    """P2: at the boundary (one provider, the longest instructions, the full
    output, the text plus framing counted) the cost equals the hold, and only
    the framing margin makes it fit."""
    import json as _json
    m = allowance()
    from types import SimpleNamespace
    from test_outreach_setup import setup_module_or_missing
    from services import ai_router
    setup = setup_module_or_missing()
    biz, brand, lia, campaign = started(db)
    monkeypatch.setenv("AI_PRICES_JSON", _json.dumps({"openai/gpt-6.1-sol": [20000, 20000, 0]}))
    monkeypatch.setattr(ai_router, "chain", lambda purpose, include_down=False: [("openai", "gpt-6.1-sol")])
    seen = {}

    def answers(provider, model, system, user, max_tokens):
        seen["system"] = len(system)
        usage = SimpleNamespace(prompt_tokens=len(system) + len(user) + setup.PROVIDER_OVERHEAD_TOKENS,
                                completion_tokens=max_tokens)
        return _json.dumps({"emails": [{"subject": "s", "body": "b"}] * 3}), usage
    monkeypatch.setattr(ai_router, "_openai_compatible_chat", answers)
    with run_clock(), Session(db) as s:        # learn the instructions' real length, then leave no slack
        setup.redraft_emails(s, biz, OWNER, campaign["id"], {"notes": "x", "current": CURRENT})
    monkeypatch.setattr(setup, "SYSTEM_PROMPT_MAX_CHARS", seen["system"])
    before = None
    with Session(db) as s:
        before = m.spent_pence(s, A, brand["id"], PERIOD)
    during = {}
    real = setup.ai_router.json_chat

    def watching(*args, **kwargs):
        during["held"] = held(db, m)
        return real(*args, **kwargs)
    monkeypatch.setattr(setup.ai_router, "json_chat", watching)
    with run_clock(), Session(db) as s:
        setup.redraft_emails(s, biz, OWNER, campaign["id"], {"notes": "x", "current": CURRENT})
    with Session(db) as s:
        cost = m.spent_pence(s, A, brand["id"], PERIOD) - before
    assert 0 < cost <= during["held"], (cost, during["held"])
