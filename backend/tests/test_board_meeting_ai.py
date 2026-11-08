"""BM-1: every board-meeting reply failed (Mike's logs, 6 Nov 19:13-19:15).

OpenAI refused each request with 400 "Unsupported parameter: 'max_tokens' is
not supported with this model. Use 'max_completion_tokens' instead." The
default model is gpt-5, which also accepts only its default temperature. The
reply Mike then saw, "I'm having trouble accessing the data", was the failure
fallback: the business data was in the prompt every time, the request never
reached the model.
"""
import asyncio
from types import SimpleNamespace

import pytest

from services import executive_meeting_orchestrator as orch
from services import profit_guard


class StrictReasoningModel:
    """Refuses what gpt-5 refuses, records what it was sent."""

    def __init__(self):
        self.sent = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **kwargs):
        self.sent.append(kwargs)
        if "max_tokens" in kwargs:
            raise RuntimeError("Unsupported parameter: 'max_tokens'")
        if "temperature" in kwargs and kwargs["temperature"] != 1:
            raise RuntimeError("Unsupported value: 'temperature'")
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Revenue is up 4%."))],
                               usage=SimpleNamespace(total_tokens=42))


@pytest.fixture
def model(monkeypatch):
    fake = StrictReasoningModel()
    monkeypatch.setattr(orch, "_get_async_client", lambda: fake)
    monkeypatch.setattr(profit_guard, "permits", lambda purpose: True)
    return fake


@pytest.mark.parametrize("name", ["gpt-5", "gpt-5.5", "gpt-5-mini", "o4-mini"])
def test_a_reasoning_model_is_asked_in_a_form_it_accepts(model, monkeypatch, name):
    monkeypatch.setattr(orch, "EXECUTIVE_MEETING_AI_MODEL", name)
    content, tokens = asyncio.run(orch._gpt_chat_completion(
        messages=[{"role": "user", "content": "How are we doing?"}], temperature=0.4, max_tokens=1200,
        business_id="b"))
    assert (content, tokens) == ("Revenue is up 4%.", 42)
    sent = model.sent[-1]
    assert sent["max_completion_tokens"] == 1200 + orch.REASONING_HEADROOM and "max_tokens" not in sent and "temperature" not in sent


def test_an_older_chat_model_keeps_its_temperature(model, monkeypatch):
    monkeypatch.setattr(orch, "EXECUTIVE_MEETING_AI_MODEL", "gpt-4o")
    model.chat.completions.create = _lenient(model)
    asyncio.run(orch._gpt_chat_completion(messages=[{"role": "user", "content": "x"}], temperature=0.2,
                                          max_tokens=800))
    sent = model.sent[-1]
    assert sent["temperature"] == 0.2 and sent["max_completion_tokens"] == 800 and "max_tokens" not in sent
    assert "reasoning_effort" not in sent


def _lenient(model):
    async def create(**kwargs):
        model.sent.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
                               usage=SimpleNamespace(total_tokens=1))
    return create


def test_reasoning_is_kept_short_so_the_reply_fits_the_budget(model, monkeypatch):
    """Reasoning tokens count against max_completion_tokens; unbounded, they
    can use the whole budget and return an empty reply."""
    monkeypatch.setattr(orch, "EXECUTIVE_MEETING_AI_MODEL", "gpt-5")
    asyncio.run(orch._gpt_chat_completion(messages=[{"role": "user", "content": "x"}]))
    assert model.sent[-1].get("reasoning_effort") == "low"


def test_the_failure_reply_does_not_claim_the_data_is_missing(model, monkeypatch):
    assert "data" not in orch.ARIA_ERROR_FALLBACK.lower()


def test_the_closing_summary_is_charged_to_the_business(model, monkeypatch):
    """The summary call carried no business, so its cost was unattributed."""
    seen = []
    real = profit_guard.attributed

    def spy(business_id, purpose):
        seen.append((business_id, purpose))
        return real(business_id, purpose)
    monkeypatch.setattr(profit_guard, "attributed", spy)
    asyncio.run(orch._run_summary("Owner: hello", business_id="biz-1"))
    assert ("biz-1", "meeting") in seen


# ---- Codex BM-1 review 1 ---------------------------------------------------

def _replying(model, content, finish_reason="stop"):
    async def create(**kwargs):
        model.sent.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content),
                                                        finish_reason=finish_reason)],
                               usage=SimpleNamespace(total_tokens=9))
    return create


def test_a_reasoning_model_gets_headroom_beyond_the_reply_budget(model, monkeypatch):
    """Finding 2: reasoning is charged to the same allowance as the reply."""
    monkeypatch.setattr(orch, "EXECUTIVE_MEETING_AI_MODEL", "gpt-5")
    asyncio.run(orch._gpt_chat_completion(messages=[{"role": "user", "content": "x"}], max_tokens=800))
    assert model.sent[-1]["max_completion_tokens"] == 800 + orch.REASONING_HEADROOM


def test_truncated_json_is_treated_as_no_answer(model, monkeypatch):
    model.chat.completions.create = _replying(model, '{"summary": "We agreed to', "length")
    content, _ = asyncio.run(orch._gpt_chat_completion(messages=[{"role": "user", "content": "x"}],
                                                       response_format={"type": "json_object"}))
    assert content is None


def test_a_budget_spent_on_reasoning_is_no_answer(model, monkeypatch, caplog):
    model.chat.completions.create = _replying(model, "", "length")
    content, _ = asyncio.run(orch._gpt_chat_completion(messages=[{"role": "user", "content": "x"}]))
    assert content is None and "length" in caplog.text


def test_a_long_spoken_reply_cut_short_is_still_shown(model):
    model.chat.completions.create = _replying(model, "Revenue is up and", "length")
    content, _ = asyncio.run(orch._gpt_chat_completion(messages=[{"role": "user", "content": "x"}]))
    assert content == "Revenue is up and"


@pytest.mark.parametrize("name", ["o3-pro", "gpt-5-pro", "o1-pro"])
def test_a_responses_only_model_is_refused_without_a_paid_call(model, monkeypatch, caplog, name):
    """Finding 3: these models do not serve Chat Completions; every call would fail."""
    monkeypatch.setattr(orch, "EXECUTIVE_MEETING_AI_MODEL", name)
    content, _ = asyncio.run(orch._gpt_chat_completion(messages=[{"role": "user", "content": "x"}]))
    assert content is None and model.sent == [] and "EXECUTIVE_MEETING_AI_MODEL" in caplog.text


@pytest.mark.parametrize("name,reasoning", [
    ("ft:gpt-5-mini:acme::abc", True), ("ft:gpt-4o-mini:acme::abc", False),
    ("gpt-5-chat-latest", False), ("gpt-4.1", False), ("omni-moderation", False), ("o4-mini", True)])
def test_model_family_is_read_from_the_base_model(name, reasoning):
    assert orch._is_reasoning_model(name) is reasoning


def test_end_meeting_charges_the_summary_to_the_business(model, monkeypatch):
    """The attribution, through end_meeting itself rather than the helper."""
    seen = []
    monkeypatch.setattr(orch, "_load_meeting", lambda mid, s: {"business_id": "biz-9", "status": "in_progress"})
    monkeypatch.setattr(orch, "_load_message_history", lambda mid, s: [])
    monkeypatch.setattr(orch, "_build_transcript", lambda h: "Owner: hi")

    async def extraction(**kw):
        return {"action_items_count": 0, "goals_count": 0, "decisions_count": 0, "tokens_used": 0}

    async def summary(transcript, business_id=None):
        seen.append(business_id)
        raise RuntimeError("stop here")
    monkeypatch.setattr(orch, "_run_extraction", extraction)
    monkeypatch.setattr(orch, "_run_summary", summary)
    try:
        asyncio.run(orch.end_meeting("m1", session=None))
    except Exception:
        pass
    assert seen == ["biz-9"]


# ---- BM-5: gpt-5.5 refuses tools with a reasoning effort (8 Nov 17:42) -----

class ToolStrictModel(StrictReasoningModel):
    """gpt-5.5's 400: function tools with a reasoning effort other than none."""

    def __init__(self, refuse=True):
        super().__init__()
        self.refuse = refuse

    async def create(self, **kwargs):
        self.sent.append(dict(kwargs))
        if self.refuse and kwargs.get("tools") and kwargs.get("reasoning_effort") not in (None, "none"):
            raise RuntimeError("Error code: 400 - Function tools with reasoning_effort are not supported for "
                               "gpt-5.5 in /v1/chat/completions. To use function tools, use /v1/responses "
                               "or set reasoning_effort to 'none'.")
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Here it is."),
                                                        finish_reason="stop")],
                               usage=SimpleNamespace(total_tokens=7))


async def _no_tool(name, arguments):
    return "{}"


def _ask(fake, monkeypatch, name):
    monkeypatch.setattr(orch, "_get_async_client", lambda: fake)
    monkeypatch.setattr(profit_guard, "permits", lambda purpose: True)
    monkeypatch.setattr(orch, "EXECUTIVE_MEETING_AI_MODEL", name)
    monkeypatch.setattr(orch, "_TOOLS_REFUSE_REASONING", set())
    return asyncio.run(orch._gpt_chat_completion(
        messages=[{"role": "user", "content": "What came in last week?"}], business_id="b",
        tools=[{"type": "function", "function": {"name": "ledger_summary", "parameters": {}}}],
        run_tool=_no_tool))


@pytest.mark.parametrize("name", ["gpt-5.5", "gpt-5.1", "ft:gpt-5.5:org::x"])
def test_a_typed_turn_with_look_ups_is_answered_on_gpt_5_5(monkeypatch, name):
    fake = ToolStrictModel()
    assert _ask(fake, monkeypatch, name) == ("Here it is.", 7)
    assert len(fake.sent) == 1, "asked correctly first time: no wasted call"
    assert fake.sent[0]["reasoning_effort"] == "none" and fake.sent[0]["tools"]


def test_gpt_5_keeps_its_low_reasoning_with_look_ups(monkeypatch):
    fake = ToolStrictModel(refuse=False)
    _ask(fake, monkeypatch, "gpt-5")
    assert fake.sent[0]["reasoning_effort"] == "low"


def test_another_model_that_refuses_is_asked_again_and_remembered(monkeypatch):
    fake = ToolStrictModel()
    assert _ask(fake, monkeypatch, "o4-mini")[0] == "Here it is."
    assert [s["reasoning_effort"] for s in fake.sent] == ["low", "none"]
    fake.sent.clear()
    asyncio.run(orch._gpt_chat_completion(
        messages=[{"role": "user", "content": "And the week before?"}], business_id="b",
        tools=[{"type": "function", "function": {"name": "ledger_summary", "parameters": {}}}],
        run_tool=_no_tool))
    assert [s["reasoning_effort"] for s in fake.sent] == ["none"]


def test_other_failures_are_not_retried(monkeypatch):
    fake = ToolStrictModel(refuse=False)

    async def broken(**kwargs):
        fake.sent.append(kwargs)
        raise RuntimeError("Error code: 429 - rate limit")
    fake.chat.completions.create = broken
    assert _ask(fake, monkeypatch, "gpt-5")[0] is None
    assert len(fake.sent) == 1


def test_the_final_answer_round_without_tools_keeps_its_reasoning(monkeypatch):
    """Once the look-ups are used up the last call offers no tools; it may reason."""
    fake = ToolStrictModel()
    calls = iter([True] * orch.MAX_TOOL_ROUNDS + [False])

    async def create(**kwargs):
        fake.sent.append(dict(kwargs))
        call = SimpleNamespace(id="c", function=SimpleNamespace(name="ledger_summary", arguments="{}"))
        message = SimpleNamespace(content="Done.", tool_calls=[call] if next(calls) else None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason="stop")],
                               usage=SimpleNamespace(total_tokens=1))
    fake.chat.completions.create = create
    _ask(fake, monkeypatch, "gpt-5.5")
    assert [s["reasoning_effort"] for s in fake.sent] == ["none"] * orch.MAX_TOOL_ROUNDS + ["low"]
    assert "tools" not in fake.sent[-1]
