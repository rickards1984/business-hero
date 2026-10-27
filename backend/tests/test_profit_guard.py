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
    ai_spend(engine, "platform", 30, "briefing")
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
        assert c.execute(text("SELECT value FROM usage_meters WHERE business_id = 'platform' AND meter = 'ai_pence'")).scalar()


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
        rows = dict(c.execute(text("SELECT meter, value FROM usage_meters WHERE business_id = 'platform'")).fetchall())
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


def test_chat_costs_are_attributed_to_the_business():
    import inspect
    guard()
    import assistant_chat
    assert 'profit_guard.label("chat", business.id)' in inspect.getsource(assistant_chat.process_chat_message)
