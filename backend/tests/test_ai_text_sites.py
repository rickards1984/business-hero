"""AI-1d — each moved site really asks ai_text for its own task, is costed
where it was before, uses what any provider answers (Claude chosen here), and
still falls back to its plain version when nothing answers.
"""
import asyncio
import json
from types import SimpleNamespace

import pytest


@pytest.fixture
def ai(monkeypatch):
    """Claude chosen for every task; each call captured; costs captured."""
    from services import ai_chat, ai_models, ai_router, profit_guard
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    ai_router._down.clear()
    monkeypatch.setattr(ai_models, "resolve", lambda task: [("anthropic", "claude-opus-5-5")])
    state = SimpleNamespace(calls=[], recorded=[], answer="ok", fail=False)

    def adapter(provider, model, messages, tools, timeout, factory, **opts):
        state.calls.append(SimpleNamespace(provider=provider, model=model, messages=messages, opts=opts,
                                           attribution=profit_guard._attribution.get()))
        if state.fail:
            raise ai_router.ProviderError("anthropic: HTTP 529")
        return SimpleNamespace(content=state.answer, tool_calls=[], truncated=False), \
            SimpleNamespace(input_tokens=50, output_tokens=20)
    monkeypatch.setattr(ai_chat, "_ADAPTERS", {"openai": adapter, "anthropic": adapter, "xai": adapter})
    monkeypatch.setattr(ai_chat, "_record", lambda business_id, **kw: state.recorded.append((business_id, kw)) or True)
    monkeypatch.setattr(profit_guard, "permits", lambda purpose: True)
    resolved = []
    real = ai_models.resolve

    def resolve(task):
        resolved.append(task)
        return real(task)
    monkeypatch.setattr(ai_models, "resolve", resolve)
    state.tasks = resolved
    yield state
    ai_router._down.clear()


def costed(state):
    return [(b, kw["purpose"], kw["provider"]) for b, kw in state.recorded]


# ------------------------------------------------------------- briefings ---

def test_the_daily_pulse_uses_the_briefing_models(ai):
    from services import briefing_generator as bg
    ai.answer = "🌅 Good morning, Mike! All quiet."
    out = asyncio.run(bg.generate_daily_pulse("New Body", "Mike", {"calls": 3}, business_id="b1"))
    assert out == "🌅 Good morning, Mike! All quiet."
    assert set(ai.tasks) == {"briefing"} and costed(ai) == [("b1", "briefing", "anthropic")]
    assert ai.calls[0].opts["max_tokens"] == 400


def test_the_weekly_briefing_reads_claude_s_answer_and_its_json(ai):
    from services import briefing_generator as bg
    ai.answer = ('📊 Week in brief\n===JSON===\n```json\n{"observations": [], "suggestions": [], '
                 '"action_options": [{"number": 1, "label": "Chase INV-101", "type": "chase", "config": {}}]}\n```')
    text, options, analysis = asyncio.run(bg.generate_weekly_briefing("New Body", "Mike", {}, business_id="b1"))
    assert text == "📊 Week in brief" and options[0]["label"] == "Chase INV-101"
    assert costed(ai) == [("b1", "briefing", "anthropic")]


def test_a_briefing_still_goes_when_no_model_answers(ai):
    from services import briefing_generator as bg
    ai.fail = True
    out = asyncio.run(bg.generate_daily_pulse("New Body", "Mike", {}, business_id="b1"))
    assert out == bg.generate_fallback_pulse("New Body", {})


def test_a_briefing_with_no_key_for_its_models_makes_no_call(ai, monkeypatch):
    from services import briefing_generator as bg
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    out = asyncio.run(bg.generate_daily_pulse("New Body", "Mike", {}, business_id="b1"))
    assert ai.calls == [] and out == bg.generate_fallback_pulse("New Body", {})


# ------------------------------------------------------ help assistant ---

def test_a_customer_s_support_chat_uses_the_help_models_as_essential_chat(ai, monkeypatch):
    import support_api
    from services import profit_guard
    monkeypatch.setattr(profit_guard, "permits", lambda purpose: purpose in profit_guard.ESSENTIAL)
    ai.answer = "Go to Settings → Email.\n[CATEGORY: how-to] [CONFIDENCE: 0.8]"
    text, escalate, category, confidence = asyncio.run(
        support_api._get_ai_support_response("How do I connect Gmail?", [], "New Body", []))
    assert text == "Go to Settings → Email." and category == "how-to" and confidence == 0.8
    assert set(ai.tasks) == {"support"} and costed(ai) == [(None, "chat", "anthropic")]


def test_the_admin_s_support_draft_is_costed_as_a_support_draft(ai):
    """Calls the endpoint's body with a session holding one conversation."""
    import support_api
    from sqlalchemy import create_engine, text
    from sqlmodel import Session
    engine = create_engine("sqlite://")
    with engine.begin() as c:
        c.execute(text("CREATE TABLE support_messages (conversation_id TEXT, sender_type TEXT, content TEXT, created_at TEXT)"))
        c.execute(text("CREATE TABLE support_conversations (id TEXT, category TEXT, subject TEXT, business_id TEXT)"))
        c.execute(text("CREATE TABLE businesses (id TEXT, name TEXT)"))
        c.execute(text("CREATE TABLE support_articles (id TEXT, title TEXT, content TEXT, summary TEXT, category TEXT, "
                       "tags TEXT, is_published BOOLEAN, sort_order INT)"))
        c.execute(text("INSERT INTO support_messages VALUES ('c1', 'user', 'My invoices are missing', '1')"))
        c.execute(text("INSERT INTO support_conversations VALUES ('c1', 'bug', 'Invoices', 'b1')"))
        c.execute(text("INSERT INTO businesses VALUES ('b1', 'New Body')"))
    ai.answer = "Thanks for flagging this: a resync from Xero should bring them back."
    with Session(engine) as s:
        out = asyncio.run(support_api.admin_ai_draft_response("c1", auth_ctx={"user_id": "u"}, session=s))
    assert out == {"draft": "Thanks for flagging this: a resync from Xero should bring them back."}
    assert costed(ai) == [(None, "support_draft", "anthropic")]


# ------------------------------------------------------- call summaries ---

def test_a_call_summary_uses_the_call_summary_models_off_the_event_loop(ai):
    import openai_utils
    ai.answer = "- Asked about prices\n- Wants a callback"
    out = asyncio.run(openai_utils.generate_call_summary("Caller asked about prices."))
    assert out == "- Asked about prices\n- Wants a callback"
    assert set(ai.tasks) == {"call_summary"} and costed(ai) == [(None, "call_summary", "anthropic")]


def test_a_call_summary_is_none_when_nothing_answers(ai):
    import openai_utils
    ai.fail = True
    assert asyncio.run(openai_utils.generate_call_summary("Caller asked about prices.")) is None


# ---------------------------------------------------------------- email ---

def message(**kw):
    base = dict(id="m1", subject="Quote for a roof", from_name="Sam", from_email="sam@example.com",
                snippet="Can you quote?", body_text="Can you quote for a roof repair?", received_at=None,
                ai_category="action_required", ai_priority=4, ai_summary="Wants a roof quote",
                ai_suggested_action="Reply with a quote")
    base.update(kw)
    return SimpleNamespace(**base)


BUSINESS = SimpleNamespace(id="b1", name="New Body")


def test_inbox_sorting_reads_claude_s_fenced_json(ai):
    from app.email import service
    from services import profit_guard
    ai.answer = ('```json\n[{"message_id": "m1", "category": "action_required", "priority": 4, '
                 '"summary": "Wants a roof quote", "suggested_action": "Reply with a quote"}]\n```')
    with profit_guard.attributed("b1", "classify"):
        out = service.analyze_email_batch([message()])
    assert [(r.message_id, r.category, r.priority) for r in out] == [("m1", "customer", 4)]   # ARIA-1a: Mike's categories
    assert set(ai.tasks) == {"inbox_classify"} and costed(ai) == [("b1", "classify", "anthropic")]


def test_inbox_sorting_leaves_mail_unsorted_when_nothing_answers(ai):
    from app.email import service
    ai.fail = True
    assert service.analyze_email_batch([message()]) == []


def test_the_email_briefing_uses_its_models(ai):
    from app.email import service
    from services import profit_guard
    ai.answer = "## Today\n- Reply to Sam about the roof"
    with profit_guard.attributed("b1", "briefing"):
        out = service.generate_email_briefing_markdown([message()], BUSINESS)
    assert out.startswith("## Today\n- Reply to Sam about the roof")
    assert set(ai.tasks) == {"email_briefing"} and costed(ai) == [("b1", "briefing", "anthropic")]


def test_one_reply_draft_reads_claude_s_fenced_json_not_the_fences(ai):
    from app.email import service
    from services import profit_guard
    ai.answer = '```json\n{"subject": "Re: Quote for a roof", "body_text": "Hi Sam, happy to quote.", "body_html": ""}\n```'
    with profit_guard.attributed("b1", "draft"):
        out = service.generate_email_reply_draft(message(), BUSINESS)
    assert out["body_text"] == "Hi Sam, happy to quote." and "```" not in out["body_html"]
    assert set(ai.tasks) == {"reply_draft"} and costed(ai) == [("b1", "draft", "anthropic")]


def test_three_reply_drafts_use_their_models(ai):
    from app.email import service
    from services import profit_guard
    ai.answer = json.dumps([{"tone": t, "subject": "Re: Quote for a roof", "body_text": f"{t} reply"}
                            for t in ("professional", "friendly", "brief")])
    with profit_guard.attributed("b1", "draft"):
        out = service.generate_email_reply_drafts(message(), BUSINESS, user_name="Mike")
    assert [d["tone"] for d in out] == ["professional", "friendly", "brief"]
    assert set(ai.tasks) == {"reply_drafts"} and costed(ai) == [("b1", "draft", "anthropic")]


def test_a_reply_draft_falls_back_when_nothing_answers(ai):
    from app.email import service
    ai.fail = True
    out = service.generate_email_reply_drafts(message(), BUSINESS, user_name="Mike")
    assert len(out) == 1 and out[0]["body_text"]


# ------------------------------------------------- Aria's draft tool ---

def test_aria_s_reply_drafts_tool_reads_claude_s_answer(ai):
    import assistant_tools
    from sqlalchemy import create_engine, text
    engine = create_engine("sqlite://")
    with engine.begin() as c:
        c.execute(text("CREATE TABLE email_messages (id TEXT, business_id TEXT, provider_message_id TEXT, from_email TEXT, "
                       "from_name TEXT, subject TEXT, snippet TEXT, body_text TEXT, received_at TEXT)"))
        c.execute(text("CREATE TABLE businesses (id TEXT, name TEXT)"))
        c.execute(text("INSERT INTO email_messages VALUES ('m1', 'b1', 'abc123', 'sam@example.com', 'Sam', "
                       "'Quote for a roof', 'Can you quote?', 'Can you quote for a roof repair?', NULL)"))
        c.execute(text("INSERT INTO businesses VALUES ('b1', 'New Body')"))
    ai.answer = "```json\n" + json.dumps([{"tone": "brief", "subject": "Re: roof", "body": "Yes, Thursday."}]) + "\n```"
    out = assistant_tools._draft_email_reply(engine, "b1", {"email_id": "abc123"})
    assert out["drafts"] == [{"tone": "brief", "subject": "Re: roof", "body": "Yes, Thursday."}]
    assert set(ai.tasks) == {"reply_drafts"} and costed(ai) == [("b1", "draft", "anthropic")]


# ---------------------------------------------------------------- guard ---

MOVED = {
    "services/briefing_generator.py": 2, "support_api.py": 2, "openai_utils.py": 1,
    "assistant_tools.py": 1, "app/email/service.py": 4,
}


@pytest.mark.parametrize("path,count", MOVED.items())
def test_no_moved_site_builds_its_own_openai_client_any_more(path, count):
    """AI-1d: every text call in these files goes through ai_text."""
    import re
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / path).read_text()
    assert not re.search(r"\bOpenAI\(|AsyncOpenAI\(|chat\.completions\.create", source), path
    assert len(re.findall(r"ai_text\.complete\(|ai_text\.acomplete\(|\bacomplete\(", source)) == count


@pytest.mark.parametrize("fn", ["generate_email_briefing_markdown", "analyze_email_batch",
                                "generate_email_reply_drafts", "generate_email_reply_draft"])
def test_the_email_endpoints_never_wait_on_a_model_on_the_event_loop(fn):
    """AI-1d: each is a sync model call made from an async endpoint. Called
    directly, a 30-second answer froze every request; in a worker thread
    (asyncio.to_thread copies the attribution) it freezes none."""
    import re
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "app/email/router.py").read_text()
    direct = re.findall(rf"(?<![\w.]){fn}\(", source)
    assert direct == [], f"{fn} is called directly on the event loop"
    assert f"asyncio.to_thread({fn}," in source


def test_an_attribution_survives_the_worker_thread():
    from services import profit_guard

    async def go():
        with profit_guard.attributed("b1", "draft"):
            return await asyncio.to_thread(profit_guard._attribution.get)
    assert asyncio.run(go()) == ("b1", "draft")


# ------------------------------------------------ Codex AI-1d review 3 ---
# Every wrapper the sites' own stripping accepted before AI-1d still reads,
# at every site that parses JSON (review 3, finding 1).

def wrappers(payload):
    return {
        "bare": payload,
        "fenced": f"```json\n{payload}\n```",
        "closing fence only": f"{payload}\n```",
        "opening fence, cut off": f"```json\n{payload}",
        "json label": f"json\n{payload}",
        "stray backticks": f"`{payload}`",
        "fenced, then a remark": f"```json\n{payload}\n```\nLet me know if you'd like changes.",
        "prose, then fenced": f"Here you go:\n```json\n{payload}\n```",
    }


CLASSIFY = json.dumps([{"message_id": "m1", "category": "action_required", "priority": 4,
                        "summary": "Wants a roof quote", "suggested_action": "Reply"}])
THREE = json.dumps([{"tone": t, "subject": "Re: roof", "body_text": f"{t} reply", "body": f"{t} reply"}
                    for t in ("professional", "friendly", "brief")])


@pytest.mark.parametrize("form", wrappers("x"))
def test_inbox_sorting_reads_every_wrapper_it_read_before(ai, form):
    from app.email import service
    ai.answer = wrappers(CLASSIFY)[form]
    assert [r.category for r in service.analyze_email_batch([message()])] == ["customer"], form   # ARIA-1a


@pytest.mark.parametrize("form", wrappers("x"))
def test_three_drafts_read_every_wrapper_they_read_before(ai, form):
    from app.email import service
    ai.answer = wrappers(THREE)[form]
    out = service.generate_email_reply_drafts(message(), BUSINESS, user_name="Mike")
    assert [d["tone"] for d in out] == ["professional", "friendly", "brief"], form


@pytest.mark.parametrize("form", wrappers("x"))
def test_aria_s_draft_tool_reads_every_wrapper_it_read_before(ai, form):
    import assistant_tools
    from sqlalchemy import create_engine, text
    engine = create_engine("sqlite://")
    with engine.begin() as c:
        c.execute(text("CREATE TABLE email_messages (id TEXT, business_id TEXT, provider_message_id TEXT, from_email TEXT, "
                       "from_name TEXT, subject TEXT, snippet TEXT, body_text TEXT, received_at TEXT)"))
        c.execute(text("CREATE TABLE businesses (id TEXT, name TEXT)"))
        c.execute(text("INSERT INTO email_messages VALUES ('m1', 'b1', 'abc123', 'sam@example.com', 'Sam', "
                       "'Quote for a roof', 'Can you quote?', 'Can you quote for a roof repair?', NULL)"))
        c.execute(text("INSERT INTO businesses VALUES ('b1', 'New Body')"))
    ai.answer = wrappers(THREE)[form]
    out = assistant_tools._draft_email_reply(engine, "b1", {"email_id": "abc123"})
    assert [d["tone"] for d in out["drafts"]] == ["professional", "friendly", "brief"], form


@pytest.mark.parametrize("form", wrappers("x"))
def test_one_draft_reads_every_wrapper(ai, form):
    from app.email import service
    ai.answer = wrappers(json.dumps({"subject": "Re: roof", "body_text": "Hi Sam, Thursday works."}))[form]
    assert service.generate_email_reply_draft(message(), BUSINESS)["body_text"] == "Hi Sam, Thursday works.", form


def test_inbox_sorting_keeps_a_summary_that_quotes_a_fence(ai):
    """Codex review 4, finding 2: a summary quoting ```[]```, then a lone
    closing fence: the embedded [] replaced the classification."""
    from app.email import service
    ai.answer = json.dumps([{"message_id": "m1", "category": "action_required", "priority": 4,
                             "summary": "Customer quoted ```[]```", "suggested_action": "Reply"}]) + "\n```"
    out = service.analyze_email_batch([message()])
    assert [(r.message_id, r.summary) for r in out] == [("m1", "Customer quoted ```[]```")]
