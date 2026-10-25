"""OUT-19 part H — AI provider failover (docs/OUT-19-TICKET.md, decision 6).

Mike, 25 Oct 2026: if one provider goes down, runs out of credit or fails
unexpectedly, outreach switches to another nearly as capable — e.g. OpenAI →
xAI Grok → Anthropic Claude — set by configuration, not code. Every attempt's
cost is recorded (a failed one at its conservative maximum). No network call
happens here: every provider is faked.
"""
# ruff: noqa: F811 - pytest fixtures imported from test_outreach_setup are parameters by design
import json
import logging
from types import SimpleNamespace

import pytest

from test_outreach_setup import db  # noqa: F401


def router():
    from services import ai_router
    return ai_router


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for k in ("AI_PROVIDER_ORDER", "AI_MODELS_JSON", "ARIA_DRAFT_MODEL", "ARIA_RESEARCH_MODEL",
              "OPENAI_API_KEY", "XAI_API_KEY", "ANTHROPIC_API_KEY", "AI_PRICES_JSON", "AI_FAILOVER_COOLDOWN_SECONDS"):
        monkeypatch.delenv(k, raising=False)
    router().reset_breakers()
    yield
    router().reset_breakers()


def keys(monkeypatch, *providers):
    env = {"openai": "OPENAI_API_KEY", "xai": "XAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
    for p in providers:
        monkeypatch.setenv(env[p], f"test-{p}")


class Fakes:
    """Records which provider was called; each provider either answers or fails."""

    def __init__(self, monkeypatch, behaviour):
        self.calls, self.behaviour = [], behaviour
        r = router()
        monkeypatch.setattr(r, "_openai_compatible_chat", self.chat("openai/xai"))
        monkeypatch.setattr(r, "_anthropic_chat", self.chat("anthropic"))

    def chat(self, family):
        def call(provider, model, system, user, max_tokens):
            self.calls.append(provider)
            outcome = self.behaviour.get(provider)
            if isinstance(outcome, Exception):
                # The real adapters turn every provider failure into ProviderError.
                raise router().ProviderError(str(outcome)) from outcome
            return outcome if isinstance(outcome, str) else json.dumps({"from": provider}), \
                SimpleNamespace(prompt_tokens=1000, completion_tokens=200)
        return call


# --------------------------------------------------------- configuration ---

def test_the_default_order_is_openai_then_grok_then_claude():
    assert router().order() == ["openai", "xai", "anthropic"]


def test_the_order_and_models_are_set_by_configuration(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER_ORDER", "anthropic, openai, nonsense")
    monkeypatch.setenv("AI_MODELS_JSON", json.dumps({"draft": {"anthropic": "claude-sonnet-4-5", "openai": "gpt-4o-mini"}}))
    keys(monkeypatch, "openai", "anthropic")
    assert router().order() == ["anthropic", "openai"]
    assert router().chain("draft") == [("anthropic", "claude-sonnet-4-5"), ("openai", "gpt-4o-mini")]


def test_the_older_draft_and_research_model_settings_still_apply(monkeypatch):
    monkeypatch.setenv("ARIA_DRAFT_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("ARIA_RESEARCH_MODEL", "gpt-4.1")
    keys(monkeypatch, "openai")
    assert router().chain("draft") == [("openai", "gpt-4o-mini")]
    assert router().chain("research") == [("openai", "gpt-4.1")]


def test_a_provider_without_a_key_or_with_an_unpriced_model_is_left_out(monkeypatch):
    keys(monkeypatch, "openai", "xai")
    monkeypatch.setenv("AI_MODELS_JSON", json.dumps({"draft": {"xai": "grok-unknown"}}))
    assert router().chain("draft") == [("openai", "gpt-4o")]


def test_invalid_model_configuration_is_ignored_as_a_whole(monkeypatch, caplog):
    keys(monkeypatch, "openai")
    monkeypatch.setenv("AI_MODELS_JSON", "{not json")
    with caplog.at_level(logging.ERROR):
        assert router().chain("draft") == [("openai", "gpt-4o")]
    assert "ignored" in caplog.text


# --------------------------------------------------------------- failover ---

def test_a_failing_provider_hands_over_to_the_next(monkeypatch, caplog):
    keys(monkeypatch, "openai", "xai", "anthropic")
    fakes = Fakes(monkeypatch, {"openai": RuntimeError("insufficient_quota")})
    from services import ai_costs
    with caplog.at_level(logging.WARNING):
        with ai_costs.collect() as spent:
            out = router().json_chat("system", {"x": 1}, purpose="draft", max_tokens=500)
    assert out == {"from": "xai"} and fakes.calls == ["openai", "xai"]
    assert [(c["provider"], c["estimated"]) for c in spent] == [("openai", True), ("xai", False)]
    assert "failover" in caplog.text.lower() and "openai" in caplog.text


def test_a_failed_provider_is_skipped_until_its_cooldown_ends(monkeypatch):
    keys(monkeypatch, "openai", "xai")
    r = router()
    clock = {"t": 1000.0}
    monkeypatch.setattr(r, "_now", lambda: clock["t"])
    fakes = Fakes(monkeypatch, {"openai": TimeoutError("down")})
    r.json_chat("s", {}, purpose="draft", max_tokens=10)
    fakes.behaviour = {}
    r.json_chat("s", {}, purpose="draft", max_tokens=10)
    assert fakes.calls == ["openai", "xai", "xai"], "while cooling down, OpenAI is not tried"
    clock["t"] += r.cooldown() + 1
    r.json_chat("s", {}, purpose="draft", max_tokens=10)
    assert fakes.calls[-1] == "openai", "after the cooldown, the first choice is tried again"


def test_when_every_provider_fails_the_call_says_so(monkeypatch):
    keys(monkeypatch, "openai", "anthropic")
    Fakes(monkeypatch, {"openai": RuntimeError("a"), "anthropic": RuntimeError("b")})
    with pytest.raises(router().AllProvidersFailed):
        router().json_chat("s", {}, purpose="draft", max_tokens=10)


def test_with_no_provider_available_nothing_is_called(monkeypatch):
    fakes = Fakes(monkeypatch, {})
    with pytest.raises(router().AllProvidersFailed):
        router().json_chat("s", {}, purpose="draft", max_tokens=10)
    assert fakes.calls == []


def test_a_bad_answer_is_not_a_provider_failure_and_is_not_paid_for_twice(monkeypatch):
    """Invalid JSON is the model's answer, not an outage: no second provider is charged."""
    keys(monkeypatch, "openai", "xai")
    fakes = Fakes(monkeypatch, {"openai": "this is not json"})
    with pytest.raises(ValueError):
        router().json_chat("s", {}, purpose="draft", max_tokens=10)
    assert fakes.calls == ["openai"]


# -------------------------------------------------------------- adapters ---

def test_grok_uses_the_openai_library_pointed_at_xai(monkeypatch):
    import openai
    keys(monkeypatch, "xai")
    seen = {}

    class Completions:
        def create(self, **kw):
            seen.update(kw)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": 1}'))],
                                   usage=SimpleNamespace(prompt_tokens=5, completion_tokens=2))

    def client(**kw):
        seen["client"] = kw
        return SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    monkeypatch.setattr(openai, "OpenAI", client)
    text, usage = router()._openai_compatible_chat("xai", "grok-4", "s", "u", 100)
    assert seen["client"]["base_url"] == "https://api.x.ai/v1" and seen["client"]["api_key"] == "test-xai"
    assert seen["client"]["max_retries"] == 0 and seen["model"] == "grok-4" and json.loads(text) == {"ok": 1}


def test_claude_is_called_directly_and_its_usage_read(monkeypatch):
    keys(monkeypatch, "anthropic")
    seen = {}

    def post(url, **kw):
        seen.update(kw, url=url)
        return SimpleNamespace(status_code=200, json=lambda: {
            "content": [{"type": "text", "text": 'Here you go: {"ok": 2}'}],
            "usage": {"input_tokens": 7, "output_tokens": 3}})
    import httpx
    monkeypatch.setattr(httpx, "post", post)
    text, usage = router()._anthropic_chat("anthropic", "claude-sonnet-4-5", "sys", "user", 100)
    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["headers"]["x-api-key"] == "test-anthropic" and seen["json"]["model"] == "claude-sonnet-4-5"
    assert json.loads(router().extract_json(text)) == {"ok": 2}
    assert (usage.input_tokens, usage.output_tokens) == (7, 3)


def test_a_claude_error_response_is_a_provider_failure(monkeypatch):
    keys(monkeypatch, "anthropic")
    import httpx
    monkeypatch.setattr(httpx, "post", lambda url, **kw: SimpleNamespace(status_code=529, json=lambda: {}, text="overloaded"))
    with pytest.raises(router().ProviderError):
        router()._anthropic_chat("anthropic", "claude-sonnet-4-5", "s", "u", 10)


# ------------------------------------------------------------ research ---

def test_research_fails_over_and_reports_every_attempt(monkeypatch):
    keys(monkeypatch, "openai", "anthropic")
    r = router()
    attempts = []

    def openai_search(provider, model, brief):
        attempts.append(provider)
        raise r.ProviderError("rate limited")

    def claude_search(provider, model, brief):
        attempts.append(provider)
        return '{"candidates": [{"company": "Studio 1 Ltd"}]}', SimpleNamespace(input_tokens=3000, output_tokens=500), 4
    monkeypatch.setattr(r, "_openai_compatible_search", openai_search)
    monkeypatch.setattr(r, "_anthropic_search", claude_search)
    out = r.web_search("find gyms")
    assert attempts == ["openai", "anthropic"]
    assert out["candidates"] == [{"company": "Studio 1 Ltd"}]
    assert [(c["provider"], c["estimated"]) for c in out["calls"]] == [("openai", True), ("anthropic", False)]
    assert out["cost_pence"] == sum(c["pence"] for c in out["calls"])


def test_research_reserves_enough_for_every_provider_it_might_try(monkeypatch):
    keys(monkeypatch, "openai", "anthropic")
    r = router()
    one = r.max_search_pence("openai", "gpt-4.1")
    both = r.reserve_pence()
    assert both == one + r.max_search_pence("anthropic", "claude-sonnet-4-5")


def test_a_research_run_records_each_attempt_in_the_ledger(db):
    """A search that failed over: the failed attempt's estimate and the
    successful attempt's cost are both recorded against the brand."""
    from sqlalchemy import text
    from test_outreach_research import World, person, run, started
    from test_outreach_setup import A
    biz, brand, lia, campaign = started(db)
    world = World([[person(i) for i in range(20)]], cost=0)
    real = world.search

    def failed_over(brief):
        out = real(brief)
        out["calls"] = [{"provider": "openai", "model": "gpt-4.1", "pence": 40, "estimated": True, "usage": {}},
                        {"provider": "anthropic", "model": "claude-sonnet-4-5", "pence": 25, "estimated": False,
                         "usage": {"input_tokens": 3000, "output_tokens": 500, "tool_calls": 4}}]
        out["cost_pence"] = 65
        return out
    world.search = failed_over
    run(db, biz, lia, world)
    with db.connect() as c:
        got = dict(c.execute(text("SELECT meter, value FROM usage_meters WHERE business_id = :b AND meter LIKE 'ai_%'"),
                             {"b": A}).fetchall())
    key = f"research:{brand['id']}"
    assert float(got[f"ai_pence:{key}:openai/gpt-4.1"]) == 40 and float(got[f"ai_estimated:{key}:openai/gpt-4.1"]) == 1
    assert float(got[f"ai_pence:{key}:anthropic/claude-sonnet-4-5"]) == 25
    assert float(got["ai_pence"]) == 65
