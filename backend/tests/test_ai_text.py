"""AI-1d — one plain text request on any provider (services/ai_text.py).

The briefings, the help assistant, email (briefing, sorting, reply drafts) and
call summaries used to build their own OpenAI client. They now ask
`ai_text.complete` for the task: the task's chosen models in order, failing
over when one is down, each attempt costed under the same business and
purpose as before, and refused at the kill switch exactly as the SDK hook
refused them.
"""
import asyncio
import json
from types import SimpleNamespace

import pytest

ANTHROPIC = ("anthropic", "claude-opus-5-5")
GPT5 = ("openai", "gpt-5")
GPT4O = ("openai", "gpt-4o")


@pytest.fixture
def env(monkeypatch):
    """Keys for OpenAI and Anthropic; recording and the guard captured."""
    from services import ai_chat, ai_router, profit_guard
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.setenv(key, "test-key")
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    ai_router._down.clear()
    recorded = []
    monkeypatch.setattr(ai_chat, "_record", lambda business_id, **kw: recorded.append((business_id, kw)) or True)
    monkeypatch.setattr(profit_guard, "permits", lambda purpose: True)
    yield SimpleNamespace(recorded=recorded)
    ai_router._down.clear()


def use(monkeypatch, *pairs):
    from services import ai_models
    monkeypatch.setattr(ai_models, "resolve", lambda task: list(pairs))


class Fake:
    """An adapter answering by a script per (provider, model)."""
    def __init__(self, **by_model):
        self.by_model, self.calls = by_model, []

    def __call__(self, provider, model, messages, tools, timeout, factory, **opts):
        self.calls.append(SimpleNamespace(provider=provider, model=model, messages=messages, tools=tools,
                                          timeout=timeout, opts=opts))
        answer = self.by_model[model]
        if isinstance(answer, Exception):
            raise answer
        return SimpleNamespace(content=answer, tool_calls=[], truncated=False), \
            SimpleNamespace(prompt_tokens=120, completion_tokens=40)


def adapters(monkeypatch, fake):
    from services import ai_chat
    monkeypatch.setattr(ai_chat, "_ADAPTERS", {"openai": fake, "anthropic": fake, "xai": fake})


MSGS = [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "Summarise the week."}]


# --------------------------------------------------------- the happy path ---

def test_the_task_s_first_choice_answers_and_is_costed_where_the_site_said(env, monkeypatch):
    from services import ai_text, profit_guard
    fake = Fake(**{"claude-opus-5-5": "  A good week.  "})
    adapters(monkeypatch, fake)
    use(monkeypatch, ANTHROPIC, GPT5)
    with profit_guard.attributed("b1", "briefing"):
        out = ai_text.complete("briefing", MSGS, max_tokens=400, temperature=0.3)
    assert (out.content, out.provider, out.model) == ("A good week.", "anthropic", "claude-opus-5-5")
    assert [(c.provider, c.model) for c in fake.calls] == [ANTHROPIC]
    assert fake.calls[0].tools is None and fake.calls[0].messages == MSGS
    business, kw = env.recorded[0]
    assert business == "b1" and kw["purpose"] == "briefing" and kw["provider"] == "anthropic"
    assert (kw["input_tokens"], kw["output_tokens"], kw["estimated"]) == (120, 40, False)


def test_an_explicit_business_and_purpose_win(env, monkeypatch):
    from services import ai_text
    adapters(monkeypatch, Fake(**{"gpt-5": "ok"}))
    use(monkeypatch, GPT5)
    ai_text.complete("support", MSGS, max_tokens=100, business_id="b9", purpose="support_draft")
    assert env.recorded[0][0] == "b9" and env.recorded[0][1]["purpose"] == "support_draft"


def test_with_no_attribution_it_is_a_platform_cost_under_the_task_s_ledger_purpose(env, monkeypatch):
    from services import ai_text
    adapters(monkeypatch, Fake(**{"gpt-5": "ok"}))
    use(monkeypatch, GPT5)
    ai_text.complete("call_summary", MSGS, max_tokens=100)
    assert env.recorded[0][0] is None and env.recorded[0][1]["purpose"] == "call_summary"


# ------------------------------------------------------------- failover ---

def test_an_outage_fails_over_and_switches_that_provider_off_for_a_while(env, monkeypatch):
    from services import ai_router, ai_text
    fake = Fake(**{"claude-opus-5-5": ai_router.ProviderError("anthropic: HTTP 529"), "gpt-5": "from GPT"})
    adapters(monkeypatch, fake)
    use(monkeypatch, ANTHROPIC, GPT5)
    out = ai_text.complete("briefing", MSGS, max_tokens=400)
    assert out.content == "from GPT" and out.provider == "openai"
    assert ai_router._is_down("anthropic")
    assert [kw["provider"] for _, kw in env.recorded] == ["anthropic", "openai"]      # the failure is costed too
    assert env.recorded[0][1]["estimated"] is True


def test_a_refused_request_fails_over_without_switching_the_provider_off_or_billing(env, monkeypatch):
    from services import ai_chat, ai_router, ai_text
    adapters(monkeypatch, Fake(**{"claude-opus-5-5": ai_chat.Rejected("anthropic: HTTP 400"), "gpt-5": "ok"}))
    use(monkeypatch, ANTHROPIC, GPT5)
    assert ai_text.complete("briefing", MSGS, max_tokens=400).provider == "openai"
    assert not ai_router._is_down("anthropic")
    assert [kw["provider"] for _, kw in env.recorded] == ["openai"]


def test_an_empty_answer_tries_the_next_model_but_is_not_an_outage(env, monkeypatch):
    from services import ai_router, ai_text
    adapters(monkeypatch, Fake(**{"claude-opus-5-5": "   ", "gpt-5": "ok"}))
    use(monkeypatch, ANTHROPIC, GPT5)
    assert ai_text.complete("briefing", MSGS, max_tokens=400).content == "ok"
    assert not ai_router._is_down("anthropic")
    assert len(env.recorded) == 2                        # the empty answer was still billed


def test_when_nothing_answers_the_site_gets_an_error_to_fall_back_on(env, monkeypatch):
    from services import ai_router, ai_text
    adapters(monkeypatch, Fake(**{"claude-opus-5-5": "", "gpt-5": ai_router.ProviderError("openai: Timeout")}))
    use(monkeypatch, ANTHROPIC, GPT5)
    with pytest.raises(ai_router.AllProvidersFailed):
        ai_text.complete("briefing", MSGS, max_tokens=400)


def test_a_provider_without_a_key_or_switched_off_is_skipped(env, monkeypatch):
    from services import ai_router, ai_text
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    ai_router._trip("xai")                              # switched off after an outage
    fake = Fake(**{"gpt-5": "ok", "grok-4.7": "never"})
    adapters(monkeypatch, fake)
    use(monkeypatch, ("xai", "grok-4.7"), ANTHROPIC, GPT5)
    assert ai_text.complete("briefing", MSGS, max_tokens=400).model == "gpt-5"
    assert [c.model for c in fake.calls] == ["gpt-5"]


# ------------------------------------------------------ the kill switch ---

def test_at_the_kill_switch_a_non_essential_job_is_refused_before_any_call(env, monkeypatch):
    from services import ai_text, profit_guard
    monkeypatch.setattr(profit_guard, "permits", lambda purpose: purpose in profit_guard.ESSENTIAL)
    fake = Fake(**{"gpt-5": "ok"})
    adapters(monkeypatch, fake)
    use(monkeypatch, GPT5)
    with profit_guard.attributed("b1", "briefing"), pytest.raises(profit_guard.Paused):
        ai_text.complete("briefing", MSGS, max_tokens=400)
    assert fake.calls == [] and env.recorded == []


def test_an_essential_job_still_answers_at_the_kill_switch(env, monkeypatch):
    from services import ai_text, profit_guard
    monkeypatch.setattr(profit_guard, "permits", lambda purpose: False)
    adapters(monkeypatch, Fake(**{"gpt-5": "ok"}))
    use(monkeypatch, GPT5)
    with profit_guard.attributed(None, "chat"):            # a customer's support chat
        assert ai_text.complete("support", MSGS, max_tokens=400).content == "ok"


# ------------------------------------------------ settings per provider ---

def test_the_site_s_limit_and_temperature_reach_every_adapter(env, monkeypatch):
    from services import ai_text
    fake = Fake(**{"gpt-4o": "ok"})
    adapters(monkeypatch, fake)
    use(monkeypatch, GPT4O)
    ai_text.complete("briefing", MSGS, max_tokens=400, temperature=0.3, timeout=12.0)
    assert fake.calls[0].opts == {"max_tokens": 400, "temperature": 0.3, "retries": 1}
    assert fake.calls[0].timeout == 12.0


def test_openai_gets_the_settings_its_model_accepts(monkeypatch):
    """A reasoning model refuses temperature and max_tokens (BM-1)."""
    from services import ai_chat
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    sent = []

    def factory(**kw):
        sent.append(("client", kw))

        def create(**request):
            sent.append(("request", request))
            msg = SimpleNamespace(content="ok", tool_calls=None)
            return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")],
                                   usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1))
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    ai_chat._openai_compatible("openai", "gpt-4o", MSGS, None, 30.0, factory,
                               max_tokens=400, temperature=0.3, retries=1)
    ai_chat._openai_compatible("openai", "gpt-5", MSGS, None, 30.0, factory,
                               max_tokens=400, temperature=0.3, retries=1)
    clients = [kw for k, kw in sent if k == "client"]
    requests = [kw for k, kw in sent if k == "request"]
    assert all(c["max_retries"] == 1 for c in clients)
    assert requests[0]["max_tokens"] == 400 and requests[0]["temperature"] == 0.3
    assert "temperature" not in requests[1] and requests[1]["max_completion_tokens"] >= 1600
    assert "tools" not in requests[0]


def test_anthropic_gets_the_limit_and_no_temperature(monkeypatch):
    """Claude's newest models may refuse sampling settings; the site's
    temperature is a style hint, not worth a refused briefing."""
    from services import ai_chat
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    sent = []

    def post(url, json=None, timeout=None, headers=None):
        sent.append(json)
        return SimpleNamespace(status_code=200, json=lambda: {
            "content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn",
            "usage": {"input_tokens": 3, "output_tokens": 2}})
    monkeypatch.setattr(ai_chat._http, "post", post)
    reply, usage = ai_chat._anthropic("anthropic", "claude-opus-5-5", MSGS, None, 30.0, None,
                                      max_tokens=400, temperature=0.3, retries=1)
    assert reply.content == "ok"
    assert sent[0]["max_tokens"] == 400 and "temperature" not in sent[0]
    assert sent[0]["system"] == "Be brief." and "tools" not in sent[0]


def test_chat_s_own_calls_are_unchanged(monkeypatch):
    """turn() passes no settings: chat keeps its 8,192-token limit."""
    from services import ai_chat
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    sent = []

    def post(url, json=None, timeout=None, headers=None):
        sent.append(json)
        return SimpleNamespace(status_code=200, json=lambda: {
            "content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn",
            "usage": {"input_tokens": 3, "output_tokens": 2}})
    monkeypatch.setattr(ai_chat._http, "post", post)
    ai_chat._anthropic("anthropic", "claude-opus-5-5", MSGS, None, 30.0, None)
    assert sent[0]["max_tokens"] == ai_chat.OUTPUT_TOKENS


def test_the_most_possible_cost_uses_the_site_s_limit(env, monkeypatch):
    """A failure with no usage is charged at most what that request could
    have cost, not chat's 8,192-token limit."""
    from services import ai_router, ai_text
    adapters(monkeypatch, Fake(**{"gpt-4o": ai_router.ProviderError("openai: Timeout"), "claude-opus-5-5": "ok"}))
    use(monkeypatch, GPT4O, ANTHROPIC)          # an outage switches all of OpenAI off for a while
    ai_text.complete("briefing", MSGS, max_tokens=400)
    assert env.recorded[0][1]["output_tokens"] == 400 and env.recorded[0][1]["estimated"] is True


# --------------------------------------------------------------- async ---

def test_the_async_form_runs_off_the_event_loop_and_keeps_the_attribution(env, monkeypatch):
    import threading
    from services import ai_text, profit_guard
    seen = []

    def fake(provider, model, messages, tools, timeout, factory, **opts):
        seen.append((threading.current_thread() is threading.main_thread(), profit_guard._attribution.get()))
        return SimpleNamespace(content="ok", tool_calls=[], truncated=False), None
    adapters(monkeypatch, fake)
    use(monkeypatch, GPT5)

    async def go():
        with profit_guard.attributed("b1", "briefing"):
            return await ai_text.acomplete("briefing", MSGS, max_tokens=400)
    assert asyncio.run(go()).content == "ok"
    assert seen == [(False, ("b1", "briefing"))]
    assert env.recorded[0][0] == "b1" and env.recorded[0][1]["estimated"] is True     # no usage reported


# -------------------------------------------------------------- helpers ---

@pytest.mark.parametrize("raw,expected", [
    ('{"a": 1}', '{"a": 1}'),
    ('```json\n{"a": 1}\n```', '{"a": 1}'),
    ('```\n[1, 2]\n```', '[1, 2]'),
    ('  ```JSON\n{"a": 1}```  ', '{"a": 1}'),
    ('Here you go:\n```json\n{"a": 1}\n```', '{"a": 1}'),
])
def test_json_is_read_with_or_without_fences(raw, expected):
    from services import ai_text
    assert json.loads(ai_text.strip_fences(raw)) == json.loads(expected)
