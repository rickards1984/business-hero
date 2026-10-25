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
              "OPENAI_API_KEY", "XAI_API_KEY", "ANTHROPIC_API_KEY", "RESEARCH_SEARCH_RESERVE_PENCE", "ARIA_REPLY_MODEL"):
        monkeypatch.delenv(k, raising=False)


def test_the_default_models_are_gpt_6_1_sol_then_grok_4_7(monkeypatch):
    """Mike, 25 Oct 2026: Grok 4.7, xAI's most capable model, is the research
    and drafting fallback (an earlier Grok failed at research for him)."""
    from services import ai_router
    monkeypatch.setenv("OPENAI_API_KEY", "a")
    monkeypatch.setenv("XAI_API_KEY", "b")
    for purpose in ("research", "draft"):
        assert ai_router.chain(purpose) == [("openai", "gpt-6.1-sol"), ("xai", "grok-4.7")]
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


# ------------------------------------------- Codex OUT-19 H review 2 ---

@pytest.mark.parametrize("model,base,high", [("gpt-6.1-sol", (157, 787), (314, 1181)), ("gpt-6-luna", (8, 39), (16, 59))])
def test_openai_long_context_costs_double_input_and_half_again_output_above_272k(model, base, high):
    """P1 1: 2x input and 1.5x output above 272k input tokens (OpenAI's model pages)."""
    from services import ai_costs
    below = ai_costs.cost("openai", model, 271_999, 1000)
    above = ai_costs.cost("openai", model, 300_000, 1000)
    assert below == pytest.approx((271_999 * base[0] + 1000 * base[1]) / 1e6)
    assert above == pytest.approx((300_000 * high[0] + 1000 * high[1]) / 1e6)
    assert ai_costs.price_max("openai", model)[:2] == high


@pytest.mark.parametrize("entry", [[100, 200, 0, 200000, 50, 100], [100, 200, 0, 200000, 150, 100],
                                   [100, 200, 0, 0, 200, 400]])
def test_a_cheaper_or_sizeless_higher_tier_is_rejected(monkeypatch, entry):
    """P2 5: the maximum rate must really be the maximum."""
    from services import ai_costs
    monkeypatch.setenv("AI_PRICES_JSON", json.dumps({"openai/gpt-6.1-sol": entry}))
    assert ai_costs.price_max("openai", "gpt-6.1-sol") == (314, 1181, 1)     # the setting is ignored as a whole


def test_a_claude_reply_with_malformed_content_keeps_its_reported_usage(monkeypatch):
    """P2 2: 500k reported input tokens and two searches must be charged, not estimated."""
    import httpx
    from types import SimpleNamespace
    from services import ai_router
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    body = {"content": "not a list of blocks",
            "usage": {"input_tokens": 500_000, "output_tokens": 10, "server_tool_use": {"web_search_requests": 2}}}
    monkeypatch.setattr(httpx, "post", lambda url, **kw: SimpleNamespace(status_code=200, json=lambda: body))
    with pytest.raises(ai_router.ProviderError) as caught:
        ai_router._anthropic_search("anthropic", "claude-sonnet-4-5", "brief")
    assert caught.value.usage.input_tokens == 500_000 and caught.value.searches == 2


def test_a_research_reply_without_its_envelope_is_a_provider_failure(monkeypatch):
    import openai
    from types import SimpleNamespace
    from services import ai_router
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    reply = SimpleNamespace(usage=SimpleNamespace(input_tokens=900, output_tokens=5))     # no output list
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: SimpleNamespace(responses=SimpleNamespace(create=lambda **k: reply)))
    with pytest.raises(ai_router.ProviderError) as caught:
        ai_router._openai_compatible_search("openai", "gpt-6.1-sol", "brief")
    assert caught.value.usage.input_tokens == 900


def test_a_search_whose_every_failed_attempt_costs_more_than_is_possible_pauses_the_brand(db):
    """P2 3: the impossible-cost pause applies on the all-failed path too."""
    from services import ai_router
    from test_outreach_research import World, person, research, run, started
    from test_outreach_setup import OWNER
    r = research()
    biz, brand, lia, campaign = started(db)
    with Session(db) as s:
        r.configure(s, biz, OWNER, {"brand_id": brand["id"], "monthly_cap_pence": 100000})
    world = World([[person(1)]])
    world.search_error = ai_router._AllFailedWithCost([{"provider": "openai", "model": "gpt-6.1-sol",
                                                        "pence": r.impossible_search_pence() + 5, "estimated": False,
                                                        "usage": {}}])
    out = run(db, biz, lia, world)
    assert "paused" in out["stopped"]
    with Session(db) as s:
        assert r.status(s, biz)["brands"][0]["enabled"] is False


def test_replies_are_sorted_by_gpt_6_luna_through_the_router_with_failover(monkeypatch):
    """P2 4: the production reply reader uses the approved model."""
    import openai
    from types import SimpleNamespace
    from services import chase_replies
    monkeypatch.setenv("OPENAI_API_KEY", "a")
    monkeypatch.setenv("XAI_API_KEY", "b")
    seen = []

    def client(**kw):
        def create(**k):
            seen.append((kw.get("base_url"), k["model"], k["messages"][1]["content"]))
            if not kw.get("base_url"):
                raise TimeoutError("OpenAI down")
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"category": "paid"}'))],
                                   usage=SimpleNamespace(prompt_tokens=50, completion_tokens=5))
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(openai, "OpenAI", client)
    assert chase_replies.classify_with_model("We paid yesterday, thanks") == {"category": "paid"}
    assert seen[0][1] == "gpt-6-luna" and seen[0][2] == "We paid yesterday, thanks"
    assert seen[1][0] == "https://api.x.ai/v1" and seen[1][1] == "grok-4.20-0309-non-reasoning"


def test_the_older_reply_model_setting_still_chooses_openais(monkeypatch):
    from services import ai_router
    monkeypatch.setenv("OPENAI_API_KEY", "a")
    monkeypatch.setenv("ARIA_REPLY_MODEL", "gpt-4o-mini")
    assert ai_router.chain("classify") == [("openai", "gpt-4o-mini")]
