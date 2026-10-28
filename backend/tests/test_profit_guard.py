"""PROFIT-1 — never spend more running Business Hero than comes in
(docs/PROFIT-1-TICKET.md). RED: a platform-wide kill switch.

Mike, 27 Oct 2026: "a net profit for all transactions ... with the alarm and
'kill switch' ensuring we don't lose money". Costs this month (every AI call,
voice minutes in pounds, fixed hosting costs) are compared with monthly
recurring income: an alarm at 40% (email + admin banner), non-essential AI
paused at 80%; live calls, reply sorting, unsubscribes and the owner's chat
never stop.

Tests first: strict xfail until services.profit_guard exists. No network, no
model, no email is sent: every adapter is faked.
"""
import importlib
import importlib.util
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlmodel import Session

NOW = datetime(2026, 10, 27, 9, tzinfo=timezone.utc)
PERIOD = "2026-10"


class MissingGuard(AssertionError):
    """Only the intentional absence of the module may be xfailed."""


# Mike approved PROFIT-1 on 27 Oct 2026; the strict-xfail marker is removed.


def guard():
    if importlib.util.find_spec("services.profit_guard") is None:
        raise MissingGuard("backend/services/profit_guard.py does not exist yet")
    return importlib.import_module("services.profit_guard")


@pytest.fixture
def engine(tmp_path, monkeypatch):
    for name in ("AI_MONTHLY_KILL_PENCE", "AI_MONTHLY_ALARM_PENCE", "PLATFORM_FIXED_COSTS_PENCE",
                 "PROFIT_TRIAL_BUDGET_PENCE", "PROFIT_ALARM_PERCENT", "PROFIT_KILL_PERCENT",
                 "VOICE_COST_PENCE_PER_MINUTE", "PROFIT_ALERT_FROM_ACCOUNT", "PROFIT_ALERT_TO"):
        monkeypatch.delenv(name, raising=False)
    e = create_engine("sqlite:///" + str(tmp_path / "profit.sqlite"))
    with e.begin() as c:
        c.execute(text("CREATE TABLE usage_meters (business_id TEXT, meter TEXT, period TEXT, value NUMERIC, "
                       "updated_at TEXT, UNIQUE (business_id, meter, period))"))
        c.execute(text("CREATE TABLE businesses (id TEXT PRIMARY KEY, name TEXT, plan_tier TEXT, "
                       "subscription_status TEXT, is_active BOOLEAN, feature_flags TEXT)"))
        # Migration 039's table (its PostgreSQL text: tested on the local harness).
        c.execute(text("CREATE TABLE platform_meters (period TEXT NOT NULL, meter TEXT NOT NULL, "
                       "value NUMERIC NOT NULL DEFAULT 0, updated_at TEXT, PRIMARY KEY (period, meter))"))
    from services import ai_costs
    ai_costs._PLATFORM_TABLE.clear()
    yield e
    e.dispose()


def business(engine, bid, plan, status="active", active=True):
    with engine.begin() as c:
        c.execute(text("INSERT INTO businesses VALUES (:b, :n, :p, :s, :a, '{}')"),
                  {"b": bid, "n": bid, "p": plan, "s": status, "a": active})


def ai_spend(engine, bid, pence, purpose="chat"):
    from services import ai_costs
    with Session(engine) as s:
        ai_costs.record(s, bid, purpose=purpose, provider="openai", model="gpt-6.1-sol", pence=pence, moment=NOW)
        s.commit()


def minutes(engine, bid, meter, value):
    with engine.begin() as c:
        c.execute(text("INSERT INTO usage_meters VALUES (:b, :m, :p, :v, :at)"),
                  {"b": bid, "m": meter, "p": PERIOD, "v": value, "at": NOW.isoformat()})


def status(engine):
    with Session(engine) as s:
        return guard().status(s, moment=NOW)


# ------------------------------------------------------------- income ---

def test_income_is_the_monthly_plan_price_of_every_active_subscription(engine):
    g = guard()
    business(engine, "a", "starter")
    business(engine, "b", "pro")
    business(engine, "c", "business")
    business(engine, "d", "pro", status="trialing")       # not paying yet
    business(engine, "e", "business", status="canceled")
    business(engine, "f", "pro", active=False)            # suspended
    out = status(engine)
    assert out["income_pence"] == 6900 + 12900 + 26900 and out["income_basis"] == "subscriptions"
    assert g.PLAN_PRICE_PENCE == {"starter": 6900, "pro": 12900, "business": 26900}


def test_before_launch_a_trial_budget_stands_in_for_income(engine, monkeypatch):
    business(engine, "mike", "business", status="trialing")
    monkeypatch.setenv("PROFIT_TRIAL_BUDGET_PENCE", "10000")
    out = status(engine)
    assert out["income_pence"] == 10000 and out["income_basis"] == "trial budget"


def test_with_no_income_and_no_trial_budget_only_the_absolute_limit_applies(engine):
    g = guard()
    ai_spend(engine, "mike", 100000)
    out = status(engine)
    assert out["income_pence"] == 0 and out["income_basis"] == "none" and out["kill"] is False
    with Session(engine) as s:
        assert g.allowed(s, purpose="research", moment=NOW) is True
    assert "no income" in out["note"].lower()


# --------------------------------------------------------------- costs ---

def test_costs_are_every_ai_call_voice_minutes_in_pounds_and_fixed_costs(engine, monkeypatch):
    business(engine, "a", "pro")
    ai_spend(engine, "a", 120, "chat")
    ai_spend(engine, None, 30, "briefing")          # no business: the platform's own (migration 039)
    minutes(engine, "a", "receptionist_minutes", 10)
    minutes(engine, "a", "aria_voice_minutes", 5)
    monkeypatch.setenv("PLATFORM_FIXED_COSTS_PENCE", "4000")
    out = status(engine)
    assert out["costs"] == {"ai_pence": 150, "voice_pence": 15 * 16, "fixed_pence": 4000,
                            "total_pence": 150 + 240 + 4000}


def test_the_voice_rate_is_a_setting(engine, monkeypatch):
    business(engine, "a", "pro")
    minutes(engine, "a", "receptionist_minutes", 10)
    monkeypatch.setenv("VOICE_COST_PENCE_PER_MINUTE", "20")
    assert status(engine)["costs"]["voice_pence"] == 200


# --------------------------------------------------------------- guard ---

def test_below_the_alarm_nothing_happens(engine):
    business(engine, "a", "business")                    # £269
    ai_spend(engine, "a", 10000)                          # 37%
    out = status(engine)
    assert out["percent"] == 37 and not out["alarm"] and not out["kill"]


def test_the_alarm_is_raised_once_at_forty_percent_after_the_commit(engine, monkeypatch):
    g = guard()
    business(engine, "a", "business")
    sent = []
    monkeypatch.setattr(g, "send_alert", lambda subject, body: sent.append((subject, body)))
    ai_spend(engine, "a", 10000)
    ai_spend(engine, "a", 1000)                           # crosses 40% (11000 of 26900)
    ai_spend(engine, "a", 100)                            # still above: no second alarm this month
    assert len(sent) == 1 and "40%" in sent[0][0]
    assert status(engine)["alarm"] is True


def test_a_rolled_back_cost_raises_no_alarm(engine, monkeypatch):
    g = guard()
    from services import ai_costs
    business(engine, "a", "business")
    sent = []
    monkeypatch.setattr(g, "send_alert", lambda subject, body: sent.append(subject))
    with Session(engine) as s:
        ai_costs.record(s, "a", purpose="chat", provider="openai", model="gpt-6.1-sol", pence=20000, moment=NOW)
        s.rollback()
    assert sent == []


def test_at_eighty_percent_non_essential_ai_pauses_and_essential_work_never_does(engine):
    g = guard()
    business(engine, "a", "business")
    ai_spend(engine, "a", 21600)                          # 80.3%
    with Session(engine) as s:
        for purpose in ("research", "draft", "briefing", "meeting"):
            assert g.allowed(s, purpose=purpose, moment=NOW) is False, purpose
        for purpose in ("classify", "receptionist", "unsubscribe", "chat"):
            assert g.allowed(s, purpose=purpose, moment=NOW) is True, purpose
    assert status(engine)["kill"] is True


def test_the_existing_research_and_drafting_checks_obey_the_guard(engine):
    """ai_costs.allowed (used by outreach research and drafting) now also
    answers for the profit guard, by purpose."""
    from services import ai_costs
    guard()
    business(engine, "a", "business")
    ai_spend(engine, "a", 21600)
    with Session(engine) as s:
        assert ai_costs.allowed(s, moment=NOW, purpose="research") is False
        assert ai_costs.allowed(s, moment=NOW, purpose="classify") is True


def test_the_thresholds_are_settings(engine, monkeypatch):
    business(engine, "a", "business")
    ai_spend(engine, "a", 16140)                          # 60%
    monkeypatch.setenv("PROFIT_ALARM_PERCENT", "70")
    monkeypatch.setenv("PROFIT_KILL_PERCENT", "95")
    out = status(engine)
    assert not out["alarm"] and not out["kill"]


def test_a_new_month_starts_clean(engine):
    business(engine, "a", "business")
    ai_spend(engine, "a", 30000)
    with Session(engine) as s:
        assert guard().allowed(s, purpose="research", moment=datetime(2026, 11, 2, 9, tzinfo=timezone.utc)) is True


def test_businesses_costing_more_than_they_pay_are_flagged(engine):
    business(engine, "a", "starter")                      # pays £69
    business(engine, "b", "business")
    ai_spend(engine, "a", 7000)
    ai_spend(engine, "b", 100)
    flagged = {b["business_id"] for b in status(engine)["losing"]}
    assert flagged == {"a"}


# ----------------------------------------------- every AI call is recorded ---

def response(model="gpt-4o-mini", prompt=1000, completion=200):
    return SimpleNamespace(model=model, usage=SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion))


def test_an_sdk_call_is_recorded_for_its_business_and_purpose(engine, monkeypatch):
    g = guard()
    from services import ai_costs
    monkeypatch.setattr(g, "_engine", lambda: engine)
    wrapped = g.wrap_create(lambda *a, **k: response())
    with g.attributed("a", "chat"):
        wrapped(model="gpt-4o-mini", messages=[])
    with engine.connect() as c:
        rows = dict(c.execute(text("SELECT meter, value FROM usage_meters WHERE business_id = 'a'")).fetchall())
    assert rows["ai_pence"] > 0 and any(k.startswith("ai_pence:chat:-:openai/gpt-4o-mini") for k in rows)
    assert ai_costs  # the same ledger


def test_an_unattributed_sdk_call_is_recorded_against_the_platform(engine, monkeypatch):
    g = guard()
    monkeypatch.setattr(g, "_engine", lambda: engine)
    g.wrap_create(lambda *a, **k: response())(model="gpt-4o-mini", messages=[])
    with engine.connect() as c:
        assert c.execute(text("SELECT value FROM platform_meters WHERE meter = 'ai_pence'")).scalar()
        assert c.execute(text("SELECT count(*) FROM usage_meters")).scalar() == 0, "never a fake business id"


def test_a_call_already_recorded_by_the_router_is_not_counted_twice(engine, monkeypatch):
    g = guard()
    from services import ai_costs
    monkeypatch.setattr(g, "_engine", lambda: engine)
    wrapped = g.wrap_create(lambda *a, **k: response())
    with ai_costs.collect():
        wrapped(model="gpt-4o-mini", messages=[])
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM usage_meters")).scalar() == 0


def test_a_model_without_a_price_is_recorded_at_a_conservative_estimate_never_free(engine, monkeypatch):
    g = guard()
    monkeypatch.setattr(g, "_engine", lambda: engine)
    g.wrap_create(lambda *a, **k: response(model="some-new-model"))(model="some-new-model", messages=[])
    with engine.connect() as c:
        rows = dict(c.execute(text("SELECT meter, value FROM platform_meters")).fetchall())
    assert rows["ai_pence"] > 0 and any(k.startswith("ai_estimated:") for k in rows)


def test_recording_never_breaks_the_call(engine, monkeypatch):
    """A ledger failure is logged; the customer's answer still arrives."""
    g = guard()
    monkeypatch.setattr(g, "_engine", lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    assert g.wrap_create(lambda *a, **k: response())(model="gpt-4o-mini", messages=[]).model == "gpt-4o-mini"


def test_the_hook_is_installed_on_the_openai_sdk_at_startup():
    import inspect
    guard()
    import main
    assert "install_openai_hook" in inspect.getsource(main)


# --------------------------------------------------------------- admin ---

def test_the_admin_panel_shows_the_guard_and_only_to_platform_admins(engine, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    guard()
    import admin_profit_api as api
    from auth import get_platform_admin_context
    from db import get_session
    business(engine, "a", "business")
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[get_session] = lambda: Session(engine)
    app.dependency_overrides[get_platform_admin_context] = lambda: {"user_id": "mike"}
    out = TestClient(app).get("/v1/admin/profit").json()
    assert out["income_pence"] == 26900 and "costs" in out and "percent" in out


# ----------------------------------------------------- the switch, wired in ---

def killed(engine, monkeypatch):
    g = guard()
    business(engine, "a", "business")
    ai_spend(engine, "a", 21600)
    monkeypatch.setattr(g, "_engine", lambda: engine)
    return g


def test_at_the_kill_switch_a_briefing_still_goes_without_ai(engine, monkeypatch):
    import asyncio
    killed(engine, monkeypatch)
    from services import briefing_generator as bg
    monkeypatch.setattr(bg, "OPENAI_API_KEY", "key")
    made = []
    monkeypatch.setattr(bg, "AsyncOpenAI", lambda **k: made.append(1))
    out = asyncio.run(bg.generate_daily_pulse("New Body", "Mike", {}))
    assert made == [] and isinstance(out, str) and out


def test_at_the_kill_switch_an_executive_meeting_turn_makes_no_ai_call(engine, monkeypatch):
    import asyncio
    killed(engine, monkeypatch)
    from services import executive_meeting_orchestrator as em
    monkeypatch.setattr(em, "_get_async_client", lambda: (_ for _ in ()).throw(AssertionError("no AI call")))
    assert asyncio.run(em._gpt_chat_completion([{"role": "user", "content": "hi"}])) == (None, 0)


def test_a_guard_that_cannot_read_holds_non_essential_ai_but_never_essential(monkeypatch):
    g = guard()
    monkeypatch.setattr(g, "_engine", lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    assert g.permits("briefing") is False and g.permits("classify") is True


def test_chat_costs_are_attributed_to_the_business_within_the_call_only():
    import inspect
    guard()
    import assistant_chat
    source = inspect.getsource(assistant_chat.process_chat_message)
    assert source.count('with profit_guard.attributed(business.id, "chat"):') == 2 and "label(" not in source



# ------------------------------------------------------ Codex PROFIT-1 review 1 ---

def completion_json(model="gpt-4o-mini", prompt=1200, completion=300):
    return {"id": "x", "object": "chat.completion", "created": 1, "model": model,
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "{}"}}],
            "usage": {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion}}


def hooked_sdk(monkeypatch, engine):
    """The REAL OpenAI SDK, its transport mocked, with the hook installed on its classes."""
    import httpx
    import openai
    from openai.resources.chat import completions
    g = guard()
    monkeypatch.setattr(g, "_engine", lambda: engine)
    monkeypatch.setattr(completions.Completions, "create", g.wrap_create(completions.Completions.create))
    monkeypatch.setattr(completions.AsyncCompletions, "create", g.wrap_create(completions.AsyncCompletions.create))
    handler = lambda request: httpx.Response(200, json=completion_json())
    sync = openai.OpenAI(api_key="k", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    aio = openai.AsyncOpenAI(api_key="k", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return g, sync, aio


def tokens_recorded(engine, business_id):
    with engine.connect() as c:
        return c.execute(text("SELECT coalesce(sum(value), 0) FROM usage_meters WHERE business_id = :b "
                              "AND meter LIKE 'ai_tokens_in:%'"), {"b": business_id}).scalar()


def test_the_real_async_sdk_call_is_recorded_with_its_real_usage(engine, monkeypatch):
    """P1 2: the async client's create isn't a coroutine function; its reply is still recorded."""
    import asyncio
    g, sync, aio = hooked_sdk(monkeypatch, engine)

    async def call():
        with g.attributed("biz-1", "briefing"):
            return await aio.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}])
    assert asyncio.run(call()).usage.prompt_tokens == 1200
    assert tokens_recorded(engine, "biz-1") == 1200


def test_the_real_sync_sdk_call_is_recorded(engine, monkeypatch):
    g, sync, aio = hooked_sdk(monkeypatch, engine)
    with g.attributed("biz-1", "chat"):
        sync.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}])
    assert tokens_recorded(engine, "biz-1") == 1200


def test_attribution_ends_with_its_block_even_across_async_tasks(engine, monkeypatch):
    """P2: scoped, never leaking into the caller or a sibling task."""
    import asyncio
    g, sync, aio = hooked_sdk(monkeypatch, engine)

    async def one(bid):
        with g.attributed(bid, "meeting"):
            await asyncio.sleep(0)
            await aio.chat.completions.create(model="gpt-4o-mini", messages=[])

    async def both():
        await asyncio.gather(one("biz-1"), one("biz-2"))
    asyncio.run(both())
    assert tokens_recorded(engine, "biz-1") == 1200 and tokens_recorded(engine, "biz-2") == 1200
    assert g._attribution.get() is None


def test_router_and_research_calls_are_never_recorded_twice(engine, monkeypatch):
    """P1 6: calls the router records itself are suppressed in the hook."""
    g, sync, aio = hooked_sdk(monkeypatch, engine)
    with g.accounted():
        sync.chat.completions.create(model="gpt-4o-mini", messages=[])
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM usage_meters")).scalar() == 0
        assert c.execute(text("SELECT count(*) FROM platform_meters")).scalar() == 0


def test_the_router_marks_its_own_sdk_calls_as_accounted():
    import inspect
    guard()
    from services import ai_router
    for fn in (ai_router._openai_compatible_chat, ai_router._openai_compatible_search):
        assert "with _accounted():" in inspect.getsource(fn)


def test_a_call_that_raises_is_recorded_at_its_requests_maximum(engine, monkeypatch):
    """P2: a timeout may still be billed."""
    g = guard()
    monkeypatch.setattr(g, "_engine", lambda: engine)

    def times_out(*a, **k):
        raise TimeoutError("read timed out")
    with g.attributed("biz-1", "briefing"), pytest.raises(TimeoutError):
        g.wrap_create(times_out)(model="gpt-4o-mini", messages=[{"role": "user", "content": "x" * 500}], max_tokens=800)
    with engine.connect() as c:
        rows = dict(c.execute(text("SELECT meter, value FROM usage_meters WHERE business_id = 'biz-1'")).fetchall())
    assert rows["ai_pence"] > 0 and any(k.startswith("ai_estimated:") for k in rows)
    assert next(v for k, v in rows.items() if k.startswith("ai_tokens_out:")) == 800


def test_a_reply_without_usage_is_estimated_from_the_request_never_free(engine, monkeypatch):
    g = guard()
    monkeypatch.setattr(g, "_engine", lambda: engine)
    no_usage = SimpleNamespace(model="gpt-4o-mini", usage=None)
    with g.attributed("biz-1", "chat"):
        g.wrap_create(lambda *a, **k: no_usage)(model="gpt-4o-mini", messages=[{"role": "user", "content": "y" * 300}])
    assert tokens_recorded(engine, "biz-1") >= 300


def test_voice_overage_minutes_count(engine):
    """P1 4: overage is metered separately and must count."""
    business(engine, "a", "pro")
    minutes(engine, "a", "receptionist_overage_minutes", 100)
    minutes(engine, "a", "aria_voice_overage_minutes", 10)
    assert status(engine)["costs"]["voice_pence"] == 110 * 16


def test_briefings_and_meetings_also_obey_the_absolute_limit(engine, monkeypatch):
    """P1 5: permits() is ai_costs.allowed: the absolute limit and the guard."""
    g = guard()
    monkeypatch.setattr(g, "_engine", lambda: engine)
    monkeypatch.setenv("AI_MONTHLY_KILL_PENCE", "100")
    ai_spend(engine, "a", 150)
    assert g.permits("briefing") is False and g.permits("meeting") is False and g.permits("classify") is True


def test_a_failed_savepoint_drops_the_alert_it_queued(engine, monkeypatch):
    """P2: the marker rolled back, so its email must not go."""
    g = guard()
    from services import ai_costs
    business(engine, "a", "business")
    sent = []
    monkeypatch.setattr(g, "send_alert", lambda subject, body: sent.append(subject))
    real = g.check_after_record

    def queues_then_fails(session, moment):
        real(session, moment)
        raise RuntimeError("marker write failed")
    monkeypatch.setattr(g, "check_after_record", queues_then_fails)
    with Session(engine) as s:
        ai_costs.record(s, "a", purpose="chat", provider="openai", model="gpt-6.1-sol", pence=20000, moment=NOW)
        s.commit()
    assert sent == []


def test_voice_alone_crossing_the_alarm_is_noticed_by_the_scheduled_check(engine, monkeypatch):
    """P2: no AI call needed for the alarm to go."""
    g = guard()
    monkeypatch.setattr(g, "_engine", lambda: engine)
    business(engine, "a", "business")
    minutes(engine, "a", "receptionist_minutes", 800)     # 800 × 16p = £128, 47% of £269
    sent = []
    monkeypatch.setattr(g, "send_alert", lambda subject, body: sent.append(subject))
    g.periodic_check(NOW)
    g.periodic_check(NOW)
    assert len(sent) == 1 and "40%" in sent[0]


def test_the_scheduler_runs_the_check():
    import inspect
    guard()
    from services import briefing_scheduler
    assert "_run_profit_check_if_due" in inspect.getsource(briefing_scheduler)


def test_an_email_draft_at_the_kill_switch_is_the_plain_one_without_ai(engine, monkeypatch):
    """P1 3: gated at the SDK itself. The router labels the call "draft"; the
    hook refuses it before the provider; the draft code's own fallback answers."""
    import httpx
    g, sync, aio = hooked_sdk(monkeypatch, engine)
    from app.email import service
    calls = []
    sync_client = __import__("openai").OpenAI(api_key="k", http_client=httpx.Client(transport=httpx.MockTransport(
        lambda request: calls.append(1) or httpx.Response(200, json=completion_json()))))
    monkeypatch.setattr(service, "OPENAI_API_KEY", "k")
    monkeypatch.setattr(service, "OpenAI", lambda **k: sync_client)
    monkeypatch.setattr(g, "permits", lambda purpose: purpose in g.ESSENTIAL)
    message = SimpleNamespace(subject="Hello", from_name="Sam", from_email="s@x", snippet="", body_text="hi")
    business_row = SimpleNamespace(id="biz-1", name="New Body")
    with g.attributed("biz-1", "draft"):
        out = service.generate_email_reply_draft(message, business_row)
    assert "get back to you" in out["body_text"] and calls == [], "no AI call was made"


def test_an_essential_call_is_never_refused_at_the_sdk(engine, monkeypatch):
    g, sync, aio = hooked_sdk(monkeypatch, engine)
    monkeypatch.setattr(g, "permits", lambda purpose: purpose in g.ESSENTIAL)
    with g.attributed("biz-1", "classify"):
        assert sync.chat.completions.create(model="gpt-4o-mini", messages=[]).usage.prompt_tokens == 1200


def test_the_email_router_labels_each_ai_feature():
    import inspect
    guard()
    from app.email import router
    source = inspect.getsource(router)
    assert source.count('profit_guard.attributed(business.id, "draft")') == 2
    assert 'profit_guard.attributed(business.id, "briefing")' in source
    assert 'profit_guard.attributed(business.id, "classify")' in source


def test_quote_drafting_is_gated_and_recorded():
    import inspect
    guard()
    import quoting_api
    source = inspect.getsource(quoting_api)
    assert 'profit_guard.permits("quote")' in source and "profit_guard.record_direct(" in source


# ------------------------------------------------------ Codex PROFIT-1 review 2 ---

def test_every_named_ai_feature_is_labelled_for_the_guard():
    """P1: assistant email drafting and support drafting are non-essential;
    receptionist call summaries are essential. All are recorded."""
    import inspect
    g = guard()
    import assistant_tools
    import openai_utils
    import support_api
    assert 'profit_guard.attributed(business_id, "draft")' in inspect.getsource(assistant_tools)
    assert 'profit_guard.attributed(None, "support_draft")' in inspect.getsource(support_api)
    assert 'profit_guard.attributed(None, "call_summary")' in inspect.getsource(openai_utils.generate_call_summary)
    assert 'profit_guard.attributed(None, "chat")' in inspect.getsource(support_api)   # a customer's support chat
    for purpose in ("support_draft", "draft", "call_summary", "voice_preview", "quote"):
        assert purpose not in g.ESSENTIAL


def test_a_finished_calls_summary_is_skipped_at_the_kill_switch(engine, monkeypatch):
    """Review 3 P1: the summary is non-essential; its existing None fallback stands."""
    import asyncio
    g, sync, aio = hooked_sdk(monkeypatch, engine)
    monkeypatch.setattr(g, "permits", lambda purpose: purpose in g.ESSENTIAL)
    import openai_utils
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    calls = []
    monkeypatch.setattr("openai.OpenAI", lambda **k: calls.append(1) or sync)
    assert asyncio.run(openai_utils.generate_call_summary("Caller asked about prices.")) is None and calls == []
    with g.attributed(None, "support_draft"), pytest.raises(g.Paused):
        sync.chat.completions.create(model="gpt-4o-mini", messages=[])


def test_quote_drafting_in_arias_chat_is_gated_and_recorded(engine, monkeypatch):
    """Review 3 P1: the chat tool's direct HTTP quote path."""
    import asyncio
    import httpx
    g = guard()
    monkeypatch.setattr(g, "_engine", lambda: engine)
    import assistant_chat
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    sent = []
    content = '{"job_title": "Fence", "groups": [{"name": "Work", "items": [{"quantity": 1, "unit_cost": 100}]}]}'
    reply = {"model": "gpt-4o", "usage": {"prompt_tokens": 900, "completion_tokens": 200},
             "choices": [{"message": {"content": content}}]}
    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **k: real_client(transport=httpx.MockTransport(
        lambda request: sent.append(1) or httpx.Response(200, json=reply))))
    args = {"description": "Replace a 10m garden fence"}
    monkeypatch.setattr(g, "permits", lambda purpose: purpose in g.ESSENTIAL)
    paused = asyncio.run(assistant_chat._execute_tool_async("generate_ai_quote", args, "biz-1"))
    assert "paused" in paused["error"] and sent == []
    monkeypatch.setattr(g, "permits", lambda purpose: True)
    done = asyncio.run(assistant_chat._execute_tool_async("generate_ai_quote", args, "biz-1"))
    assert done["subtotal"] == 100 and sent == [1]
    assert tokens_recorded(engine, "biz-1") == 900


def test_voice_previews_are_paused_at_the_kill_switch(monkeypatch):
    """Review 4: behaviourally, both endpoints: 503 and no provider call on an
    uncached request at the kill."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    g = guard()
    import openai
    import receptionist_api as api
    from rate_limiting import limiter
    from services.voice_presets import VOICE_PRESETS
    monkeypatch.setattr(limiter, "enabled", False)
    monkeypatch.setattr(g, "permits", lambda purpose: purpose in g.ESSENTIAL)
    monkeypatch.setattr(api, "assert_feature_access", lambda *a, **k: None)
    calls = []
    monkeypatch.setattr(openai, "OpenAI", lambda **k: calls.append(1))
    api._voice_preview_cache.clear()
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.get_current_user_business] = lambda: SimpleNamespace(id="biz-1")
    client = TestClient(app)
    voice = api.AVAILABLE_VOICES[0]["id"]
    preset = VOICE_PRESETS[0]["id"]
    first = client.get(f"{api.router.prefix}/voices/{voice}/preview")
    second = client.post(f"{api.router.prefix}/voice-preview",
                         json={"voice_preset_id": preset, "sample_text": "A fresh sample, never cached " + str(id(calls))})
    assert (first.status_code, second.status_code) == (503, 503) and calls == []


def test_a_cancelled_chat_quote_is_still_recorded(engine, monkeypatch):
    """Review 4 P2: cancellation after the request was sent may be billed."""
    import asyncio
    import httpx
    g = guard()
    monkeypatch.setattr(g, "_engine", lambda: engine)
    monkeypatch.setattr(g, "permits", lambda purpose: True)
    import assistant_chat
    monkeypatch.setenv("OPENAI_API_KEY", "k")

    def cancelled(request):
        raise asyncio.CancelledError()
    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **k: real_client(transport=httpx.MockTransport(cancelled)))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(assistant_chat._execute_tool_async("generate_ai_quote", {"description": "A fence"}, "biz-1"))
    with engine.connect() as c:
        rows = dict(c.execute(text("SELECT meter, value FROM usage_meters WHERE business_id = 'biz-1'")).fetchall())
    assert rows.get("ai_pence", 0) > 0 and any(k.startswith("ai_estimated:quote:") for k in rows)


def test_the_estimate_counts_tools_and_the_models_own_output_maximum():
    """P2: a request with tools and no output limit (owner chat)."""
    g = guard()
    tools = [{"type": "function", "function": {"name": "x", "description": "d" * 100000}}]
    with_tools = g._request_estimate({"model": "gpt-5", "messages": [{"role": "user", "content": "hi"}], "tools": tools})
    without = g._request_estimate({"model": "gpt-5", "messages": [{"role": "user", "content": "hi"}]})
    assert with_tools[0] > without[0] + 100000
    assert with_tools[1] == 128000 and g._request_estimate({"model": "gpt-4o-mini", "messages": []})[1] == 16384



def test_before_launch_the_trial_budget_is_a_floor_a_small_subscription_never_replaces(engine, monkeypatch):
    """Seen 28 Oct 2026: Mike's own Pro subscription (£129) displaced his £200
    trial budget, and fixed costs alone raised the alarm."""
    business(engine, "mike", "pro")
    monkeypatch.setenv("PROFIT_TRIAL_BUDGET_PENCE", "20000")
    monkeypatch.setenv("PLATFORM_FIXED_COSTS_PENCE", "8500")
    out = status(engine)
    assert out["income_pence"] == 20000 and out["income_basis"] == "trial budget"
    assert out["percent"] == 42
    monkeypatch.setenv("PROFIT_TRIAL_BUDGET_PENCE", "5000")      # subscriptions now larger: they count
    assert status(engine)["income_pence"] == 12900 and status(engine)["income_basis"] == "subscriptions"
