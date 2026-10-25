"""OUT-19 part H, Mike's decisions of 25 Oct 2026 after checking the real
provider prices:
  * research and Aria's drafts use GPT-6.1 Sol (near-top capability at about
    GPT-4.1's price); Grok 4.20 reasoning is the background fallback (about
    40% cheaper); reply sorting uses GPT-6 Luna;
  * option B: each search attempt reserves a realistic amount (not the
    theoretical worst case of an agentic search); an overrun is recorded and
    the brand stops naturally once its budget is used; only a search costing
    more than is theoretically possible (a bug or a price change) pauses it;
  * at most 4 web searches per call.
"""
# ruff: noqa: F811 - pytest fixtures imported from test_outreach_setup are parameters by design
import json

import pytest
from sqlalchemy import text
from sqlmodel import Session

from test_outreach_setup import db  # noqa: F401


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for k in ("AI_PROVIDER_ORDER", "AI_MODELS_JSON", "ARIA_DRAFT_MODEL", "ARIA_RESEARCH_MODEL", "AI_PRICES_JSON",
              "OPENAI_API_KEY", "XAI_API_KEY", "ANTHROPIC_API_KEY", "RESEARCH_SEARCH_RESERVE_PENCE"):
        monkeypatch.delenv(k, raising=False)


def test_the_default_models_are_gpt_6_1_sol_then_grok_4_20_reasoning(monkeypatch):
    from services import ai_router
    monkeypatch.setenv("OPENAI_API_KEY", "a")
    monkeypatch.setenv("XAI_API_KEY", "b")
    for purpose in ("research", "draft"):
        assert ai_router.chain(purpose) == [("openai", "gpt-6.1-sol"), ("xai", "grok-4.20-0309-reasoning")]
    assert ai_router.chain("classify")[0] == ("openai", "gpt-6-luna")


def test_prices_follow_the_providers_pages():
    """$ list prices at about £1 = $1.27, in pence per million tokens."""
    from services import ai_costs
    assert ai_costs.price("openai", "gpt-6.1-sol") == (157, 787, 1)
    assert ai_costs.price("openai", "gpt-6-luna") == (8, 39, 1)
    assert ai_costs.price("xai", "grok-4.20-0309-reasoning")[:2] == (98, 197)


def test_grok_doubles_its_price_above_200k_tokens():
    from services import ai_costs
    small = ai_costs.cost("xai", "grok-4.20-0309-reasoning", 100_000, 1000)
    large = ai_costs.cost("xai", "grok-4.20-0309-reasoning", 300_000, 1000)
    assert small == pytest.approx((100_000 * 98 + 1000 * 197) / 1e6)
    assert large == pytest.approx((300_000 * 197 + 1000 * 394) / 1e6)
    assert ai_costs.price_max("xai", "grok-4.20-0309-reasoning")[:2] == (197, 394)


def test_a_tiered_price_can_be_set_without_a_deploy(monkeypatch):
    from services import ai_costs
    monkeypatch.setenv("AI_PRICES_JSON", json.dumps({"xai/grok-4.7": [157, 472, 0.4, 200000, 315, 945]}))
    assert ai_costs.price_max("xai", "grok-4.7")[:2] == (315, 945)


def test_at_most_four_searches_per_call():
    from services import ai_router
    assert ai_router.SEARCH_MAX_TOOL_CALLS == 4


def test_each_search_attempt_reserves_a_realistic_amount_for_every_provider_it_might_try(monkeypatch):
    from services import ai_router
    monkeypatch.setenv("OPENAI_API_KEY", "a")
    monkeypatch.setenv("XAI_API_KEY", "b")
    monkeypatch.setenv("RESEARCH_SEARCH_RESERVE_PENCE", "60")
    assert ai_router.search_reserve_pence() == 60
    assert ai_router.reserve_pence() == 120


def test_the_theoretical_maximum_counts_every_search_iteration_at_the_higher_price(monkeypatch):
    """Each of the 4 searches can trigger another pass over a full context."""
    from services import ai_costs, ai_router
    p_in, p_out, p_tool = ai_costs.price_max("xai", "grok-4.20-0309-reasoning")
    window = ai_router.CONTEXT_TOKENS["xai/grok-4.20-0309-reasoning"]
    worst = (5 * window * p_in + ai_router.SEARCH_MAX_OUTPUT_TOKENS * p_out) / 1e6 + 4 * p_tool
    assert ai_router.max_search_pence("xai", "grok-4.20-0309-reasoning") == pytest.approx(worst, abs=1)


def test_a_search_that_overruns_its_reserve_is_recorded_and_research_carries_on(db):
    from test_outreach_research import World, person, research, run, started
    from test_outreach_setup import A
    r = research()
    biz, brand, lia, campaign = started(db)
    out = run(db, biz, lia, World([[person(i) for i in range(20)]], cost=r.SEARCH_RESERVE_PENCE + 40))
    assert not out["stopped"] or "paused" not in out["stopped"]
    with Session(db) as s:
        assert r.status(s, biz)["brands"][0]["enabled"] is True
    with db.connect() as c:
        assert float(c.execute(text("SELECT value FROM usage_meters WHERE business_id = :b AND meter = :m"),
                               {"b": A, "m": f"outreach_research_pence:{brand['id']}"}).scalar()) == r.SEARCH_RESERVE_PENCE + 40


def test_a_brand_stops_naturally_once_an_overrun_uses_its_budget(db):
    from test_outreach_research import World, person, run, started
    biz, brand, lia, campaign = started(db)            # £20 budget
    world = World([[person(1)], [person(2)], [person(3)]], cost=1990)
    out = run(db, biz, lia, world)
    assert len(world.briefs) == 1 and "budget" in out["stopped"]


def test_a_search_costing_more_than_is_possible_pauses_the_brand(db):
    """Only an impossible cost — a bug or a price change — pauses research."""
    from test_outreach_research import World, person, research, run, started
    r = research()
    biz, brand, lia, campaign = started(db)
    with Session(db) as s:
        from test_outreach_setup import OWNER
        r.configure(s, biz, OWNER, {"brand_id": brand["id"], "monthly_cap_pence": 100000})
    out = run(db, biz, lia, World([[person(1)]], cost=r.impossible_search_pence() + 1))
    assert "paused" in out["stopped"]
    with Session(db) as s:
        assert r.status(s, biz)["brands"][0]["enabled"] is False


def test_openai_reasoning_models_get_max_completion_tokens_and_grok_gets_max_tokens(monkeypatch):
    import openai
    from types import SimpleNamespace
    from services import ai_router
    monkeypatch.setenv("OPENAI_API_KEY", "a")
    monkeypatch.setenv("XAI_API_KEY", "b")
    seen = []

    def client(**kw):
        def create(**k):
            seen.append(k)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))],
                                   usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1))
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(openai, "OpenAI", client)
    ai_router._openai_compatible_chat("openai", "gpt-6.1-sol", "s", "u", 100)
    ai_router._openai_compatible_chat("xai", "grok-4.20-0309-reasoning", "s", "u", 100)
    assert seen[0].get("max_completion_tokens") == 100 and "max_tokens" not in seen[0]
    assert seen[1].get("max_tokens") == 100 and "max_completion_tokens" not in seen[1]
