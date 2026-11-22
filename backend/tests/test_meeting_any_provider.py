"""AI-1d part 2 — the board meeting on any provider.

The meeting's calls (typed turns with ledger look-ups, the opening, the
summary and the action-item extraction) used the OpenAI client directly. They
now go through services.ai_text for the "meeting" task: the models chosen on
the admin page, in order, with failover, each attempt costed to the business
as "meeting", the kill switch checked before every attempt, and OpenAI asked
exactly as before (test_board_meeting_ai keeps proving BM-1 and BM-5).
"""
import asyncio
import json
from types import SimpleNamespace

import pytest

from services import executive_meeting_orchestrator as orch

TOOLS = [{"type": "function", "function": {"name": "ledger_summary", "description": "Totals",
                                           "parameters": {"type": "object", "properties": {}}}}]
ANTHROPIC = ("anthropic", "claude-opus-5-5")
GPT5 = ("openai", "gpt-5")


@pytest.fixture
def env(monkeypatch):
    from services import ai_chat, ai_models, ai_router, profit_guard
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.setattr(orch, "EXECUTIVE_MEETING_AI_MODEL", None)
    ai_router._down.clear()
    state = SimpleNamespace(chain=[ANTHROPIC, GPT5], recorded=[], calls=[], script={}, permits=lambda p: True)
    monkeypatch.setattr(ai_models, "resolve", lambda task: list(state.chain))
    monkeypatch.setattr(ai_chat, "_record", lambda business_id, **kw: state.recorded.append((business_id, kw)) or True)
    monkeypatch.setattr(profit_guard, "permits", lambda purpose: state.permits(purpose))

    def adapter(provider, model, messages, tools, timeout, factory, **opts):
        state.calls.append(SimpleNamespace(provider=provider, model=model, messages=list(messages),
                                           tools=tools, opts=opts))
        answers = state.script[model]
        answer = answers.pop(0) if isinstance(answers, list) else answers
        if isinstance(answer, Exception):
            raise answer
        content, calls, truncated = answer if isinstance(answer, tuple) else (answer, [], False)
        return SimpleNamespace(content=content, tool_calls=calls, truncated=truncated), \
            SimpleNamespace(input_tokens=300, output_tokens=50)
    monkeypatch.setattr(ai_chat, "_ADAPTERS", {"openai": adapter, "anthropic": adapter, "xai": adapter})
    yield state
    ai_router._down.clear()


def lookup(id_="t1"):
    return {"id": id_, "name": "ledger_summary", "arguments": "{}"}


async def ledger(name, arguments):
    return json.dumps({"income": "£12,600"})


def ask(**kw):
    return asyncio.run(orch._gpt_chat_completion(
        messages=[{"role": "system", "content": "You are Aria."}, {"role": "user", "content": "How was the month?"}],
        business_id="biz-1", **kw))


# ------------------------------------------------------- a typed turn ---

def test_claude_looks_things_up_then_answers_and_is_costed_to_the_business(env):
    env.script = {"claude-opus-5-5": [("", [lookup()], False), "Income was £12,600."]}
    content, tokens = ask(tools=TOOLS, run_tool=ledger)
    assert content == "Income was £12,600." and tokens == 700
    first, second = env.calls
    assert first.provider == "anthropic" and first.tools == TOOLS
    assert second.messages[-2]["tool_calls"][0]["function"]["name"] == "ledger_summary"
    assert second.messages[-1] == {"role": "tool", "tool_call_id": "t1", "content": json.dumps({"income": "£12,600"})}
    assert [(b, kw["purpose"], kw["provider"]) for b, kw in env.recorded] == [("biz-1", "meeting", "anthropic")] * 2


def test_claude_gets_the_meeting_s_limit_and_no_openai_settings(env):
    env.script = {"claude-opus-5-5": "Fine."}
    ask(max_tokens=1200, temperature=0.4)
    opts = env.calls[0].opts
    assert opts["max_tokens"] == 1200 and "settings" not in opts and "json_object" not in opts


def test_openai_gets_the_meeting_s_own_settings(env):
    env.chain = [GPT5]
    env.script = {"gpt-5": "Fine."}
    ask(tools=TOOLS, run_tool=ledger, max_tokens=1200)
    assert env.calls[0].opts["settings"] == {"max_completion_tokens": 1200 + orch.REASONING_HEADROOM,
                                             "reasoning_effort": "low"}


def test_an_outage_mid_loop_fails_over_with_the_look_ups_so_far(env):
    """Round 1 on Claude looks something up; round 2's Claude is down (twice:
    its own retry), so GPT-5 answers from the same conversation."""
    from services import ai_router
    env.script = {"claude-opus-5-5": [("", [lookup()], False), ai_router.ProviderError("anthropic: HTTP 529"),
                                      ai_router.ProviderError("anthropic: HTTP 529")],
                  "gpt-5": "Income was £12,600."}
    content, _ = ask(tools=TOOLS, run_tool=ledger)
    assert content == "Income was £12,600."
    assert [c.provider for c in env.calls] == ["anthropic", "anthropic", "anthropic", "openai"]
    assert env.calls[-1].messages[-1]["role"] == "tool"           # GPT-5 saw what Claude looked up


def test_the_last_round_offers_no_tools(env):
    env.script = {"claude-opus-5-5": [("", [lookup(f"t{i}")], False) for i in range(orch.MAX_TOOL_ROUNDS)] + ["Done."]}
    content, _ = ask(tools=TOOLS, run_tool=ledger)
    assert content == "Done." and env.calls[-1].tools is None
    assert all(c.tools == TOOLS for c in env.calls[:-1])


# ------------------------------------------------------------ JSON ---

def test_the_summary_on_claude_is_asked_for_json_and_its_fence_removed(env):
    env.script = {"claude-opus-5-5": '```json\n{"summary": "A good month.", "key_takeaways": ["Chase INV-101"], '
                                     '"sentiment": "positive"}\n```'}
    out = asyncio.run(orch._run_summary("Owner: hello", business_id="biz-1"))
    assert out["summary"] == "A good month." and out["key_takeaways"] == ["Chase INV-101"]
    assert env.calls[0].opts["json_object"] is True


def test_json_mode_reaches_the_openai_adapter(monkeypatch):
    """Through the real adapter: response_format is sent for OpenAI and xAI."""
    from services import ai_chat
    sent = []

    def factory(**kw):
        def create(**request):
            sent.append(request)
            msg = SimpleNamespace(content='{"a": 1}', tool_calls=None)
            return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")], usage=None)
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    ai_chat._openai_compatible("openai", "gpt-5", [{"role": "user", "content": "json"}], None, 5, factory,
                               max_tokens=800, json_object=True, settings={"max_completion_tokens": 2800})
    ai_chat._openai_compatible("xai", "grok-4.7", [{"role": "user", "content": "json"}], None, 5, factory,
                               max_tokens=800, json_object=True)
    assert all(r["response_format"] == {"type": "json_object"} for r in sent)
    assert sent[0]["max_completion_tokens"] == 2800 and "max_tokens" not in sent[0]


def test_claude_is_told_to_reply_in_json(monkeypatch):
    """Through the real adapter: Claude has no JSON mode; its system prompt asks."""
    from services import ai_chat
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    sent = []

    def post(url, json=None, timeout=None, headers=None):
        sent.append(json)
        return SimpleNamespace(status_code=200, json=lambda: {
            "content": [{"type": "text", "text": "{}"}], "stop_reason": "end_turn",
            "usage": {"input_tokens": 3, "output_tokens": 2}})
    monkeypatch.setattr(ai_chat._http, "post", post)
    ai_chat._anthropic("anthropic", "claude-opus-5-5", [{"role": "system", "content": "Summarise."},
                                                        {"role": "user", "content": "x"}], None, 5, None,
                       max_tokens=800, json_object=True)
    assert sent[0]["system"].startswith("Summarise.") and ai_chat.JSON_ONLY in sent[0]["system"]


def test_json_cut_off_is_no_answer(env):
    env.script = {"claude-opus-5-5": ('{"summary": "We agreed to', [], True)}
    content, _ = ask(response_format={"type": "json_object"})
    assert content is None


def test_a_spoken_reply_cut_off_is_still_shown(env):
    env.script = {"claude-opus-5-5": ("Revenue is up and", [], True)}
    assert ask()[0] == "Revenue is up and"


# ---------------------------------------------- the guard and the keys ---

def test_the_kill_switch_closing_mid_loop_stops_the_next_round(env):
    """The first round's cost crosses the threshold: no second call."""
    env.permits = lambda purpose: not env.recorded
    env.script = {"claude-opus-5-5": [("", [lookup()], False), "never"]}
    content, tokens = ask(tools=TOOLS, run_tool=ledger)
    assert content is None and tokens == 350 and len(env.calls) == 1


def test_no_key_for_any_chosen_model_makes_no_call(env, monkeypatch, caplog):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.delenv("OPENAI_API_KEY")
    assert ask() == (None, 0) and env.calls == [] and "no key" in caplog.text


def test_the_prep_records_the_first_model_chosen(env):
    from services import ai_models, executive_meeting_prep as prep
    assert prep.EXECUTIVE_MEETING_AI_MODEL is None
    assert ai_models.resolve("meeting")[0][1] == "claude-opus-5-5"
    from pathlib import Path
    source = (Path(prep.__file__)).read_text()
    assert 'ai_models.resolve("meeting")[0][1]' in source


# --------------------------------------------------------------- guard ---

def test_the_meeting_no_longer_builds_its_own_openai_client():
    import re
    from pathlib import Path
    source = Path(orch.__file__).read_text()
    assert not re.search(r"AsyncOpenAI|chat\.completions\.create|_get_async_client", source)
    assert source.count("ai_text.acomplete(") == 1          # one wrapper, every meeting call goes through it


def test_the_meeting_can_be_given_any_provider_on_the_admin_page():
    from services import ai_models
    task = ai_models.TASKS["meeting"]
    assert task.max_chain == 6 and "anthropic" in task.providers and not task.openai_only
