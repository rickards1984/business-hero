"""AI-1b — Aria's chat on the switchboard (docs/AI-1-TICKET.md, M3 and M4).

  M3  each message goes to `chat` or `chat_complex` by rules, never another AI
      call: money, analysis, a long conversation, three or more tool rounds,
      or the owner's "Think harder". A held chat_complex falls back to chat and
      says so.
  M4  a provider failure hands the round to the next provider; a tool that has
      already acted is never run again. Costs are recorded for every attempt.
"""
import asyncio
import json
from types import SimpleNamespace

import pytest

TOOLS = [{"type": "function", "function": {"name": "get_invoices", "description": "List invoices",
                                           "parameters": {"type": "object", "properties": {"status": {"type": "string"}}}}}]


@pytest.fixture
def chat(monkeypatch):
    from services import ai_chat, ai_models, ai_router
    ai_router.reset_breakers()
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "XAI_API_KEY"):
        monkeypatch.setenv(key, "test-key")
    recorded = []
    monkeypatch.setattr(ai_chat, "_record", lambda business_id, **kw: recorded.append(kw))
    monkeypatch.setattr(ai_models, "_choices", lambda: {})
    yield SimpleNamespace(m=ai_chat, recorded=recorded, models=ai_models, router=ai_router)
    ai_router.reset_breakers()


def choose(chat, monkeypatch, task, pairs):
    monkeypatch.setattr(chat.models, "_choices", lambda: {task: list(pairs)})


class FakeOpenAI:
    """An OpenAI client whose create() follows a script."""
    def __init__(self, script):
        self.calls, self.script = [], list(script)

    def __call__(self, *a, **k):          # used as the client factory
        self.base_url = k.get("base_url")
        return self

    @property
    def chat(self):
        return SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def oa_reply(content=None, tool_calls=None, tokens=(100, 20)):
    calls = [SimpleNamespace(id=c["id"], function=SimpleNamespace(name=c["name"], arguments=json.dumps(c["args"])))
             for c in (tool_calls or [])] or None
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=calls))],
                           usage=SimpleNamespace(prompt_tokens=tokens[0], completion_tokens=tokens[1]))


class FakeAnthropic:
    def __init__(self, replies):
        self.sent, self.replies = [], list(replies)

    def post(self, url, *, json=None, headers=None, timeout=None):
        self.sent.append(json)
        step = self.replies.pop(0)
        if isinstance(step, Exception):
            raise step
        status, body = step
        return SimpleNamespace(status_code=status, json=lambda: body)


# --------------------------------------------------------------- M3 rules ---

@pytest.mark.parametrize("message,task", [
    ("what's on today?", "chat"),
    ("thanks!", "chat"),
    ("who is my next appointment with", "chat"),
    ("which invoices are overdue and how much am I owed?", "chat_complex"),
    ("can you analyse my cash flow for the quarter", "chat_complex"),
    ("compare this month's profit with last month", "chat_complex"),
    ("draft a quote for a full bathroom refit", "chat_complex"),
    ("plan my outreach for next month", "chat_complex"),
    ("What's my VAT bill likely to be?", "chat_complex"),
])
def test_each_message_goes_to_the_right_task(chat, message, task):
    assert chat.m.pick_task(message, history=[]) == task


def test_think_harder_always_uses_the_stronger_model(chat):
    assert chat.m.pick_task("what's on today?", history=[], think_harder=True) == "chat_complex"


def test_a_long_conversation_uses_the_stronger_model(chat):
    history = [{"role": "user", "content": "x" * 130_000}]          # about 32,000 tokens
    assert chat.m.pick_task("and?", history=history) == "chat_complex"


def test_three_tool_rounds_move_the_turn_to_the_stronger_model(chat):
    assert chat.m.pick_task("ok", history=[], tool_rounds=2) == "chat"
    assert chat.m.pick_task("ok", history=[], tool_rounds=3) == "chat_complex"


# ------------------------------------------------------- the OpenAI path ---

def test_openai_answers_with_the_settings_its_model_takes(chat, monkeypatch):
    fake = FakeOpenAI([oa_reply("Hello")])
    reply = chat.m.turn("chat", business_id="b1", messages=[{"role": "user", "content": "hi"}], tools=TOOLS,
                        openai_client=fake)
    assert reply.content == "Hello" and reply.tool_calls == [] and (reply.provider, reply.model) == ("openai", "gpt-5")
    sent = fake.calls[0]
    assert sent["model"] == "gpt-5" and "temperature" not in sent and "max_tokens" not in sent
    assert sent["tools"] == TOOLS and sent["tool_choice"] == "auto"
    assert chat.recorded == [{"purpose": "chat", "provider": "openai", "model": "gpt-5", "input_tokens": 100,
                              "output_tokens": 20, "estimated": False}]


def test_a_tool_call_comes_back_in_one_shape(chat):
    fake = FakeOpenAI([oa_reply(tool_calls=[{"id": "call_1", "name": "get_invoices", "args": {"status": "overdue"}}])])
    reply = chat.m.turn("chat", business_id="b1", messages=[{"role": "user", "content": "overdue?"}], tools=TOOLS,
                        openai_client=fake)
    assert reply.tool_calls == [{"id": "call_1", "name": "get_invoices", "arguments": '{"status": "overdue"}'}]


# ---------------------------------------------------- the Anthropic path ---

def test_anthropic_receives_the_conversation_in_its_own_shape(chat, monkeypatch):
    choose(chat, monkeypatch, "chat_complex", [("anthropic", "claude-opus-5-5")])
    http = FakeAnthropic([(200, {"content": [{"type": "text", "text": "Done."}],
                                 "usage": {"input_tokens": 300, "output_tokens": 40}})])
    monkeypatch.setattr(chat.m, "_http", http)
    messages = [
        {"role": "system", "content": "You are Aria."},
        {"role": "user", "content": "which are overdue?"},
        {"role": "assistant", "content": "Let me look.", "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "get_invoices", "arguments": '{"status": "overdue"}'}},
            {"id": "call_2", "type": "function", "function": {"name": "get_invoices", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": '{"invoices": [1]}'},
        {"role": "tool", "tool_call_id": "call_2", "content": '{"invoices": [1, 2]}'},
    ]
    reply = chat.m.turn("chat_complex", business_id="b1", messages=messages, tools=TOOLS)
    body = http.sent[0]
    assert body["model"] == "claude-opus-5-5" and body["system"] == "You are Aria." and body["max_tokens"] > 0
    assert body["tools"] == [{"name": "get_invoices", "description": "List invoices",
                              "input_schema": TOOLS[0]["function"]["parameters"]}]
    assert body["messages"] == [
        {"role": "user", "content": "which are overdue?"},
        {"role": "assistant", "content": [
            {"type": "text", "text": "Let me look."},
            {"type": "tool_use", "id": "call_1", "name": "get_invoices", "input": {"status": "overdue"}},
            {"type": "tool_use", "id": "call_2", "name": "get_invoices", "input": {}}]},
        {"role": "user", "content": [                                   # both results in one user turn
            {"type": "tool_result", "tool_use_id": "call_1", "content": '{"invoices": [1]}'},
            {"type": "tool_result", "tool_use_id": "call_2", "content": '{"invoices": [1, 2]}'}]},
    ]
    assert (reply.content, reply.provider, reply.model) == ("Done.", "anthropic", "claude-opus-5-5")
    assert chat.recorded[0]["provider"] == "anthropic" and chat.recorded[0]["input_tokens"] == 300


def test_an_anthropic_tool_call_comes_back_in_the_same_shape(chat, monkeypatch):
    choose(chat, monkeypatch, "chat_complex", [("anthropic", "claude-opus-5-5")])
    monkeypatch.setattr(chat.m, "_http", FakeAnthropic([(200, {
        "content": [{"type": "text", "text": "Checking."},
                    {"type": "tool_use", "id": "toolu_9", "name": "get_invoices", "input": {"status": "overdue"}}],
        "usage": {"input_tokens": 10, "output_tokens": 5}})]))
    reply = chat.m.turn("chat_complex", business_id="b1", messages=[{"role": "user", "content": "x"}], tools=TOOLS)
    assert reply.content == "Checking."
    assert reply.tool_calls == [{"id": "toolu_9", "name": "get_invoices", "arguments": '{"status": "overdue"}'}]


def test_a_conversation_started_on_one_provider_continues_on_another(chat, monkeypatch):
    """OpenAI's call ids are valid Anthropic tool_use ids and back again."""
    choose(chat, monkeypatch, "chat_complex", [("anthropic", "claude-opus-5-5")])
    http = FakeAnthropic([(200, {"content": [{"type": "text", "text": "ok"}], "usage": {}})])
    monkeypatch.setattr(chat.m, "_http", http)
    chat.m.turn("chat_complex", business_id="b1", messages=[
        {"role": "user", "content": "x"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_AbC-1_x", "type": "function", "function": {"name": "get_invoices", "arguments": "not json"}}]},
        {"role": "tool", "tool_call_id": "call_AbC-1_x", "content": "{}"}], tools=TOOLS)
    sent = http.sent[0]["messages"]
    assert sent[1]["content"] == [{"type": "tool_use", "id": "call_AbC-1_x", "name": "get_invoices", "input": {}}]


# --------------------------------------------------------------- M4 failover ---

def test_a_provider_failure_hands_the_round_to_the_next(chat, monkeypatch):
    choose(chat, monkeypatch, "chat_complex", [("anthropic", "claude-opus-5-5"), ("openai", "gpt-5")])
    monkeypatch.setattr(chat.m, "_http", FakeAnthropic([(529, {"error": "overloaded"})]))
    fake = FakeOpenAI([oa_reply("From OpenAI")])
    reply = chat.m.turn("chat_complex", business_id="b1", messages=[{"role": "user", "content": "hi"}], tools=TOOLS,
                        openai_client=fake)
    assert (reply.content, reply.provider) == ("From OpenAI", "openai")
    assert [r["provider"] for r in chat.recorded] == ["anthropic", "openai"]
    assert chat.recorded[0]["estimated"] is True                   # the failed attempt, at its maximum


def test_a_failed_provider_is_skipped_while_it_cools_down(chat, monkeypatch):
    choose(chat, monkeypatch, "chat_complex", [("anthropic", "claude-opus-5-5"), ("openai", "gpt-5")])
    http = FakeAnthropic([(500, {}), (200, {"content": [{"type": "text", "text": "x"}], "usage": {}})])
    monkeypatch.setattr(chat.m, "_http", http)
    fake = FakeOpenAI([oa_reply("one"), oa_reply("two")])
    chat.m.turn("chat_complex", business_id="b1", messages=[{"role": "user", "content": "a"}], tools=TOOLS, openai_client=fake)
    chat.m.turn("chat_complex", business_id="b1", messages=[{"role": "user", "content": "b"}], tools=TOOLS, openai_client=fake)
    assert len(http.sent) == 1 and len(fake.calls) == 2


def test_when_every_provider_fails_the_owner_is_told(chat, monkeypatch):
    fake = FakeOpenAI([RuntimeError("down")])
    with pytest.raises(chat.router.AllProvidersFailed):
        chat.m.turn("chat", business_id="b1", messages=[{"role": "user", "content": "hi"}], tools=TOOLS,
                    openai_client=fake)


def test_a_malformed_reply_is_a_provider_failure(chat, monkeypatch):
    choose(chat, monkeypatch, "chat_complex", [("anthropic", "claude-opus-5-5"), ("openai", "gpt-5")])
    monkeypatch.setattr(chat.m, "_http", FakeAnthropic([(200, {"content": "not a list", "usage": {"input_tokens": 9}})]))
    fake = FakeOpenAI([oa_reply("fine")])
    reply = chat.m.turn("chat_complex", business_id="b1", messages=[{"role": "user", "content": "hi"}], tools=TOOLS,
                        openai_client=fake)
    # Only the input was reported: the attempt is recorded at its maximum,
    # marked estimated, never with output taken as zero (review 1, finding 5).
    assert reply.provider == "openai" and chat.recorded[0]["estimated"] is True
    assert chat.recorded[0]["output_tokens"] == chat.m.OUTPUT_TOKENS


def test_xai_is_reached_through_its_openai_compatible_api(chat, monkeypatch):
    choose(chat, monkeypatch, "chat_complex", [("xai", "grok-4.7")])
    fake = FakeOpenAI([oa_reply("Grok here")])
    reply = chat.m.turn("chat_complex", business_id="b1", messages=[{"role": "user", "content": "hi"}], tools=TOOLS,
                        openai_client=fake)
    assert reply.provider == "xai" and fake.base_url == "https://api.x.ai/v1"
    assert fake.calls[0]["max_tokens"] > 0                         # xAI takes max_tokens


# ------------------------------------------------- the chat loop (assistant_chat) ---

@pytest.fixture
def loop(chat, monkeypatch):
    import assistant_chat
    ctx = assistant_chat.BusinessContext(id="b1", name="Biz", timezone="Europe/London")
    monkeypatch.setattr(assistant_chat, "OPENAI_API_KEY", "test")
    monkeypatch.setattr(assistant_chat, "is_platform_admin", lambda *a, **k: False)
    monkeypatch.setattr(assistant_chat, "resolve_conversation", lambda *a, **k: ("c1", "b1"))
    monkeypatch.setattr(assistant_chat, "get_business_for_user", lambda *a, **k: ctx)
    monkeypatch.setattr(assistant_chat, "load_conversation_history", lambda *a, **k: [])
    monkeypatch.setattr(assistant_chat, "save_message", lambda *a, **k: "m1")
    monkeypatch.setattr(assistant_chat, "get_user_display_name", lambda *a, **k: "Mike")
    monkeypatch.setattr(assistant_chat, "build_system_prompt", lambda *a, **k: "system")
    held = {}
    checks = []

    def refusal(business_id):
        checks.append(business_id)
        return held.get("why")
    monkeypatch.setattr(chat.m, "complex_refusal", refusal)
    tools_run = []

    async def tool(name, args, *a, **k):
        tools_run.append(name)
        return {"invoices": []}
    monkeypatch.setattr(assistant_chat, "_execute_tool_async", tool)
    return SimpleNamespace(ac=assistant_chat, held=held, tools_run=tools_run, checks=checks)


def run_chat(loop, message, **kw):
    return asyncio.run(loop.ac.process_chat_message(user=SimpleNamespace(id="u1", email=None), message=message, **kw))


def test_a_money_question_goes_to_the_stronger_model(chat, loop, monkeypatch):
    choose(chat, monkeypatch, "chat_complex", [("openai", "gpt-5.4")])
    monkeypatch.setenv("AI_PRICES_JSON", '{"openai/gpt-5.4": [200, 1000, 1]}')
    fake = FakeOpenAI([oa_reply("You're owed £1,200.")])
    monkeypatch.setattr(loop.ac, "OpenAI", fake)
    out = run_chat(loop, "how much am I owed on overdue invoices?")
    assert fake.calls[0]["model"] == "gpt-5.4" and out["reply"] == "You're owed £1,200."
    assert out["model"] == "openai/gpt-5.4"


def test_an_everyday_question_uses_the_fast_model(chat, loop, monkeypatch):
    fake = FakeOpenAI([oa_reply("Two meetings.")])
    monkeypatch.setattr(loop.ac, "OpenAI", fake)
    out = run_chat(loop, "what's on today?")
    assert fake.calls[0]["model"] == "gpt-5" and out["model"] == "openai/gpt-5"


def test_think_harder_reaches_the_chat_loop(chat, loop, monkeypatch):
    choose(chat, monkeypatch, "chat_complex", [("openai", "gpt-5.4")])
    monkeypatch.setenv("AI_PRICES_JSON", '{"openai/gpt-5.4": [200, 1000, 1]}')
    fake = FakeOpenAI([oa_reply("Thought hard.")])
    monkeypatch.setattr(loop.ac, "OpenAI", fake)
    run_chat(loop, "what's on today?", think_harder=True)
    assert fake.calls[0]["model"] == "gpt-5.4"


@pytest.mark.parametrize("why,words", [("budget", "allowance for deeper thinking is used up"),
                                       ("paused", "paused for a short while")])
def test_when_the_stronger_model_is_held_aria_says_why(chat, loop, monkeypatch, why, words):
    loop.held["why"] = why
    fake = FakeOpenAI([oa_reply("Here it is.")])
    monkeypatch.setattr(loop.ac, "OpenAI", fake)
    out = run_chat(loop, "analyse my cash flow")
    assert fake.calls[0]["model"] == "gpt-5" and words in out["reply"]


def test_moving_up_after_tool_rounds_also_respects_the_budget(chat, loop, monkeypatch):
    """Codex AI-1b review 1, finding 1: the escalation after three tool
    rounds, and the final answer, skipped the check."""
    choose(chat, monkeypatch, "chat_complex", [("openai", "gpt-5.4")])
    monkeypatch.setenv("AI_PRICES_JSON", '{"openai/gpt-5.4": [200, 1000, 1]}')
    loop.held["why"] = "budget"
    call = lambda n: oa_reply(tool_calls=[{"id": f"c{n}", "name": "get_invoices", "args": {}}])
    fake = FakeOpenAI([call(1), call(2), call(3), oa_reply("Done.")])
    monkeypatch.setattr(loop.ac, "OpenAI", fake)
    out = run_chat(loop, "ok go")
    assert [c["model"] for c in fake.calls] == ["gpt-5"] * 4 and loop.checks == ["b1"]
    assert "used up" in out["reply"]


def test_the_budget_is_checked_before_the_stronger_model_is_used(chat, loop, monkeypatch):
    fake = FakeOpenAI([oa_reply("Fine."), oa_reply("A lot.")])
    monkeypatch.setattr(loop.ac, "OpenAI", fake)
    run_chat(loop, "what's on today?")
    assert loop.checks == []                     # the everyday model needs no check
    run_chat(loop, "how much did we make this month?")
    assert loop.checks == ["b1"]


def test_a_failover_after_a_tool_has_run_never_runs_it_again(chat, loop, monkeypatch):
    choose(chat, monkeypatch, "chat", [("openai", "gpt-5"), ("anthropic", "claude-sonnet-5-5")])
    fake = FakeOpenAI([oa_reply(tool_calls=[{"id": "call_1", "name": "get_invoices", "args": {}}]),
                       RuntimeError("openai down")])
    monkeypatch.setattr(loop.ac, "OpenAI", fake)
    http = FakeAnthropic([(200, {"content": [{"type": "text", "text": "None overdue."}], "usage": {}})])
    monkeypatch.setattr(chat.m, "_http", http)
    out = run_chat(loop, "anything new for me?")
    assert out["reply"] == "None overdue." and loop.tools_run == ["get_invoices"]
    sent = http.sent[0]["messages"]
    assert sent[-1]["content"][0]["type"] == "tool_result"         # Claude saw the tool's result, not a re-run


def test_three_tool_rounds_move_the_rest_of_the_turn_up(chat, loop, monkeypatch):
    choose(chat, monkeypatch, "chat_complex", [("openai", "gpt-5.4")])
    monkeypatch.setenv("AI_PRICES_JSON", '{"openai/gpt-5.4": [200, 1000, 1]}')
    call = lambda n: oa_reply(tool_calls=[{"id": f"c{n}", "name": "get_invoices", "args": {}}])
    fake = FakeOpenAI([call(1), call(2), call(3), oa_reply("Done.")])
    monkeypatch.setattr(loop.ac, "OpenAI", fake)
    run_chat(loop, "ok go")
    assert [c["model"] for c in fake.calls] == ["gpt-5", "gpt-5", "gpt-5", "gpt-5.4"]


def test_when_every_provider_fails_the_chat_says_so(chat, loop, monkeypatch):
    fake = FakeOpenAI([RuntimeError("down")])
    monkeypatch.setattr(loop.ac, "OpenAI", fake)
    out = run_chat(loop, "hi")
    assert out.get("status") == 500 and "AI service" in out["error"]


# ------------------------------------------------------ who sees the model ---

@pytest.mark.parametrize("admin,shown", [(True, "anthropic/claude-opus-5-5"), (False, None)])
def test_only_platform_admins_see_which_model_answered(monkeypatch, admin, shown):
    import main
    monkeypatch.setattr(main, "is_platform_admin_user", lambda uid, session: admin)
    assert main._model_for_admins(None, "u1", {"model": "anthropic/claude-opus-5-5"}) == shown


def test_the_chat_request_carries_think_harder():
    from schemas import ChatRequest
    assert ChatRequest(message="hi", thinkHarder=True).think_harder is True
    assert ChatRequest(message="hi").think_harder is False



# ------------------------------------------------ Codex AI-1b review 1 ---

def test_a_refused_request_is_not_an_outage_and_is_not_billed(chat, monkeypatch):
    """Finding 3: a 400 caused by our request tripped OpenAI for everyone for
    five minutes and recorded a charge that was never made."""
    choose(chat, monkeypatch, "chat_complex", [("anthropic", "claude-opus-5-5"), ("openai", "gpt-5")])
    monkeypatch.setattr(chat.m, "_http", FakeAnthropic([(400, {"error": "bad request"})]))
    fake = FakeOpenAI([oa_reply("Fine")])
    reply = chat.m.turn("chat_complex", business_id="b1", messages=[{"role": "user", "content": "hi"}], tools=TOOLS,
                        openai_client=fake)
    assert reply.provider == "openai"
    assert [r["provider"] for r in chat.recorded] == ["openai"]       # the refusal cost nothing
    assert not chat.router._is_down("anthropic")                      # and switched nothing off


class StatusError(Exception):
    def __init__(self, code):
        super().__init__(f"HTTP {code}")
        self.status_code = code


@pytest.mark.parametrize("code,outage", [(400, False), (404, False), (422, False), (429, True), (500, True),
                                         (503, True)])
def test_openai_errors_are_told_apart(chat, code, outage):
    fake = FakeOpenAI([StatusError(code)])
    with pytest.raises(chat.router.AllProvidersFailed):
        chat.m.turn("chat", business_id="b1", messages=[{"role": "user", "content": "hi"}], tools=TOOLS,
                    openai_client=fake)
    assert chat.router._is_down("openai") is outage
    assert bool(chat.recorded) is outage


def test_a_tool_call_cut_off_at_the_limit_is_never_run(chat, loop, monkeypatch):
    """Finding 4: a truncated tool_use came back as an ordinary call."""
    choose(chat, monkeypatch, "chat", [("anthropic", "claude-sonnet-5-5"), ("openai", "gpt-5")])
    monkeypatch.setattr(chat.m, "_http", FakeAnthropic([(200, {
        "stop_reason": "max_tokens", "content": [{"type": "tool_use", "id": "t1", "name": "get_invoices", "input": {}}],
        "usage": {"input_tokens": 5, "output_tokens": 8192}})]))
    fake = FakeOpenAI([oa_reply("All clear.")])
    monkeypatch.setattr(loop.ac, "OpenAI", fake)
    out = run_chat(loop, "anything new for me?")
    assert loop.tools_run == [] and out["reply"] == "All clear."
    assert not chat.router._is_down("anthropic")                      # our limit, not their outage


def test_a_cut_off_answer_says_so(chat, loop, monkeypatch):
    reply = oa_reply("Here is the first half")
    reply.choices[0].finish_reason = "length"
    monkeypatch.setattr(loop.ac, "OpenAI", FakeOpenAI([reply]))
    out = run_chat(loop, "tell me a long story")
    assert out["reply"].startswith("Here is the first half") and "ran out of room" in out["reply"]


def test_an_empty_answer_is_never_saved_empty(chat, loop, monkeypatch):
    """Finding 6: an empty end_turn after tool results was saved, and poisoned
    the next request to Claude."""
    monkeypatch.setattr(loop.ac, "OpenAI", FakeOpenAI([
        oa_reply(tool_calls=[{"id": "c1", "name": "get_invoices", "args": {}}]), oa_reply(""), oa_reply("All done.")]))
    out = run_chat(loop, "anything new for me?")
    assert out["reply"] == "All done."


def test_an_empty_assistant_message_is_left_out_for_claude(chat):
    body = chat.m.to_anthropic([{"role": "user", "content": "a"}, {"role": "assistant", "content": ""},
                                {"role": "user", "content": "b"}], None)
    assert body["messages"] == [{"role": "user", "content": "a"}, {"role": "user", "content": "b"}]


def test_chat_works_with_only_another_provider_s_key(chat, loop, monkeypatch):
    """Finding 7: the old OpenAI-key check refused chat before the switchboard."""
    monkeypatch.delenv("OPENAI_API_KEY")
    monkeypatch.setattr(loop.ac, "OPENAI_API_KEY", None)
    choose(chat, monkeypatch, "chat", [("anthropic", "claude-sonnet-5-5")])
    monkeypatch.setattr(chat.m, "_http", FakeAnthropic([(200, {"content": [{"type": "text", "text": "Hi from Claude"}],
                                                                "usage": {}})]))
    out = run_chat(loop, "hello")
    assert out["reply"] == "Hi from Claude"


def test_with_no_provider_at_all_chat_says_so(chat, loop, monkeypatch):
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "XAI_API_KEY"):
        monkeypatch.delenv(key)
    out = run_chat(loop, "hello")
    assert out["status"] == 500 and "No AI provider" in out["error"]


@pytest.mark.parametrize("message,task", [                          # finding 8, Codex's examples
    ("How much did we make this month?", "chat_complex"),
    ("Can we afford another employee?", "chat_complex"),
    ("Change my account name", "chat"),
    ("Why is the button grey?", "chat"),
    ("Can you review my calendar for tomorrow?", "chat"),
    ("Should we hire someone for the busy season?", "chat_complex"),
])
def test_routing_reads_meaning_not_just_words(chat, message, task):
    assert chat.m.pick_task(message, history=[]) == task


def test_a_short_follow_up_keeps_its_money_topic(chat):
    history = [{"role": "user", "content": "how much profit did we make in October?"},
               {"role": "assistant", "content": "About £4,200."}]
    assert chat.m.pick_task("What about last month?", history=history) == "chat_complex"
    assert chat.m.pick_task("What about last month?", history=[{"role": "user", "content": "what's on today?"}]) == "chat"


def test_each_round_is_recorded_under_its_task(chat, monkeypatch):
    choose(chat, monkeypatch, "chat_complex", [("openai", "gpt-5")])
    chat.m.turn("chat_complex", business_id="b1", messages=[{"role": "user", "content": "x"}],
                openai_client=FakeOpenAI([oa_reply("y")]))
    assert chat.recorded[0]["purpose"] == "chat_complex"


def test_a_failed_attempt_is_estimated_at_its_own_request_limit(chat, monkeypatch):
    """Finding 5: the OpenAI request had no limit while failures were
    estimated at 8,192 tokens."""
    fake = FakeOpenAI([RuntimeError("timeout")])
    with pytest.raises(chat.router.AllProvidersFailed):
        chat.m.turn("chat", business_id="b1", messages=[{"role": "user", "content": "x" * 1000}], tools=TOOLS,
                    openai_client=fake)
    sent = fake.calls[0]
    assert sent["max_completion_tokens"] == chat.recorded[0]["output_tokens"] == 32768
    assert chat.recorded[0]["input_tokens"] >= 1000


# ------------------------------------------------- the monthly budget itself ---

@pytest.fixture
def ledger(tmp_path, monkeypatch):
    from sqlalchemy import create_engine, text
    from services import profit_guard
    engine = create_engine("sqlite:///" + str(tmp_path / "ledger.sqlite"))
    with engine.begin() as c:
        c.execute(text("CREATE TABLE businesses (id TEXT PRIMARY KEY, plan_tier TEXT)"))
        c.execute(text("CREATE TABLE usage_meters (business_id TEXT, meter TEXT, period TEXT, value NUMERIC)"))
        c.execute(text("INSERT INTO businesses VALUES ('b1', 'pro'), ('b2', 'starter')"))
    monkeypatch.setattr(profit_guard, "_engine", lambda: engine)
    monkeypatch.setattr(profit_guard, "permits", lambda purpose: True)
    from services.metering import period_for
    from datetime import datetime, timezone
    return SimpleNamespace(engine=engine, period=period_for(datetime.now(timezone.utc)))


def spend(ledger, bid, pence, purpose="chat_complex", period=None):
    from sqlalchemy import text
    with ledger.engine.begin() as c:
        c.execute(text("INSERT INTO usage_meters VALUES (:b, :m, :p, :v)"),
                  {"b": bid, "m": f"ai_pence:{purpose}:-:anthropic/claude-opus-5-5", "p": period or ledger.period,
                   "v": pence})


@pytest.mark.parametrize("plan,pence", [("starter", 500), ("pro", 1200), ("business", 3000), ("unknown", 500)])
def test_mike_s_monthly_budgets(plan, pence):
    from services import ai_chat
    assert ai_chat.complex_budget_pence(plan) == pence


def test_a_business_under_its_budget_may_think_harder(ledger):
    from services import ai_chat
    spend(ledger, "b1", 1199)
    assert ai_chat.complex_refusal("b1") is None


def test_a_business_at_its_budget_drops_to_the_everyday_model(ledger):
    from services import ai_chat
    spend(ledger, "b1", 700)
    spend(ledger, "b1", 500)
    assert ai_chat.complex_refusal("b1") == ai_chat.BUDGET_USED


def test_only_this_month_s_deeper_thinking_counts(ledger):
    from services import ai_chat
    spend(ledger, "b1", 5000, period="2020-01")
    spend(ledger, "b1", 5000, purpose="chat")                       # everyday chat never counts
    spend(ledger, "b2", 5000)                                       # nor another business's
    assert ai_chat.complex_refusal("b1") is None


def test_the_platform_guard_still_pauses_it(ledger, monkeypatch):
    from services import ai_chat, profit_guard
    monkeypatch.setattr(profit_guard, "permits", lambda purpose: False)
    assert ai_chat.complex_refusal("b1") == ai_chat.PAUSED


def test_a_budget_that_cannot_be_checked_is_never_treated_as_allowed(ledger, monkeypatch):
    from services import ai_chat, profit_guard

    def broken():
        raise RuntimeError("db down")
    monkeypatch.setattr(profit_guard, "_engine", broken)
    assert ai_chat.complex_refusal("b1") == ai_chat.PAUSED


def test_the_budgets_can_be_changed_without_a_release(monkeypatch):
    from services import ai_chat
    monkeypatch.setenv("AI_COMPLEX_MONTHLY_PENCE_JSON", '{"pro": 2000}')
    assert ai_chat.complex_budget_pence("pro") == 2000 and ai_chat.complex_budget_pence("starter") == 500
    monkeypatch.setenv("AI_COMPLEX_MONTHLY_PENCE_JSON", '{"pro": -1}')
    assert ai_chat.complex_budget_pence("pro") == 1200
