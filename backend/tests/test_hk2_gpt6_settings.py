"""HK-2 (22 Nov 2026): the gpt-6 family was not recognised as reasoning models.

`ai_models.is_reasoning` knew gpt-5 and the o-series only, so a gpt-6 model
chosen on the admin page (AI-1c) was sent `max_tokens` and a temperature,
which reasoning models refuse (BM-1). Outreach's own router already sends
them `max_completion_tokens` and no temperature. A refused request is not an
outage, so each job fell back to its plain version, quietly, every time.
"""
import pytest

from services import ai_models


@pytest.mark.parametrize("model,reasoning", [
    ("gpt-5", True), ("gpt-5.4", True), ("gpt-5.5", True), ("gpt-5-mini", True),
    ("gpt-6-luna", True), ("gpt-6.1-sol", True), ("gpt-6.1", True), ("gpt-7", True),
    ("ft:gpt-6-luna:org::abc", True), ("o3", True), ("o4-mini", True),
    ("gpt-4o", False), ("gpt-4o-mini", False), ("gpt-4.1", False), ("gpt-4.1-mini", False),
    ("gpt-5-chat-latest", False), ("gpt-6-chat-latest", False),
    ("gpt-realtime-2", False), ("gpt-4o-mini-tts", False), ("omni-moderation", False),
])
def test_every_reasoning_family_is_recognised(model, reasoning):
    assert ai_models.is_reasoning(model) is reasoning


@pytest.mark.parametrize("model", ["gpt-6-luna", "gpt-6.1-sol"])
def test_a_gpt_6_model_gets_settings_it_accepts(model):
    params = ai_models.chat_params(model, max_tokens=400, temperature=0.3)
    assert "max_tokens" not in params and "temperature" not in params
    assert params["max_completion_tokens"] >= 400


@pytest.mark.parametrize("model", ["gpt-6-luna", "gpt-6.1-sol"])
def test_the_adapter_sends_a_gpt_6_model_what_it_accepts(model, monkeypatch):
    """Through the adapter every text job and "Test this model" use."""
    from types import SimpleNamespace
    from services import ai_chat
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    sent = []

    def factory(**kw):
        def create(**request):
            sent.append(request)
            if "max_tokens" in request or "temperature" in request:
                raise RuntimeError("Unsupported parameter")
            msg = SimpleNamespace(content="ok", tool_calls=None)
            return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")], usage=None)
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    reply, _ = ai_chat._openai_compatible("openai", model, [{"role": "user", "content": "hi"}], None, 5, factory,
                                          max_tokens=400, temperature=0.3)
    assert reply.content == "ok"
    reply, _ = ai_chat._openai_compatible("openai", model, [{"role": "user", "content": "hi"}], None, 5, factory)
    assert reply.content == "ok"                                   # chat's own call too


@pytest.mark.parametrize("model", ["gpt-6-luna", "gpt-6.1-sol"])
def test_the_board_meeting_sends_a_gpt_6_model_what_it_accepts(model):
    from services import executive_meeting_orchestrator as orch
    settings = orch._openai_settings(0.4, 1200)(model, False)
    assert "temperature" not in settings and settings["reasoning_effort"] == "low"
    assert settings["max_completion_tokens"] == 1200 + orch.REASONING_HEADROOM


def test_the_meeting_and_the_switchboard_agree_on_every_model():
    from services import executive_meeting_orchestrator as orch
    for model in ["gpt-4o", "gpt-5", "gpt-5.5", "gpt-6-luna", "gpt-6.1-sol", "o4-mini", "gpt-5-chat-latest",
                  "ft:gpt-6-luna:o::x", "gpt-realtime-2"]:
        assert orch._is_reasoning_model(model) is ai_models.is_reasoning(model), model
