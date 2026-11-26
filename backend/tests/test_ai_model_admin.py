"""AI-1c — the admin page for Aria's models (docs/AI-1-TICKET.md, M2 and M5).

Mike chooses each task's model and fallbacks; every change records who and
when and can be reverted; a model that can't serve the task is refused with
the reason; "Test this model" runs the evaluation set on the candidate and the
current model side by side, records its own cost, and saves nothing.
"""
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlmodel import Session

MIKE = "11111111-1111-4111-8111-111111111111"


@pytest.fixture
def db(tmp_path, monkeypatch):
    from services import ai_models
    engine = create_engine("sqlite:///" + str(tmp_path / "admin.sqlite"))
    with engine.begin() as c:
        c.execute(text("CREATE TABLE ai_model_choices (task TEXT PRIMARY KEY, chain TEXT, changed_by TEXT, "
                       "changed_at TEXT, previous TEXT)"))
        c.execute(text("CREATE TABLE usage_meters (business_id TEXT, meter TEXT, period TEXT, value NUMERIC)"))
        c.execute(text("CREATE TABLE platform_meters (meter TEXT, period TEXT, value NUMERIC)"))
    monkeypatch.setattr(ai_models, "_engine", lambda: engine)
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.setenv(key, "test-key")
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    from services import ai_eval, profit_guard
    monkeypatch.setattr(profit_guard, "permits", lambda purpose: True)
    monkeypatch.setattr(ai_eval, "_recent", [])
    ai_models.invalidate()
    yield engine
    ai_models.invalidate()


def admin():
    from services import ai_model_admin
    return ai_model_admin


def chain(*pairs):
    return [{"provider": p, "model": m} for p, m in pairs]


def saved(engine, task):
    with engine.connect() as c:
        row = c.execute(text("SELECT chain, changed_by, previous FROM ai_model_choices WHERE task = :t"),
                        {"t": task}).first()
    return None if row is None else (json.loads(row[0]), row[1], json.loads(row[2]) if row[2] else None)


# ------------------------------------------------------------- the reasons ---

@pytest.mark.parametrize("task,provider,model,reason", [
    ("chat_complex", "anthropic", "claude-opus-5-5", None),
    ("chat_complex", "xai", "grok-4.7", "no key"),
    ("chat_complex", "openai", "gpt-made-up", "no price"),
    ("voice_aria", "openai", "gpt-5", "not one this task can use"),
    ("voice_aria", "anthropic", "claude-opus-5-5", "can't serve"),
    ("support", "openai", "gpt-5-pro", "Responses API"),
])
def test_each_refusal_names_its_reason(db, task, provider, model, reason):
    from services import ai_models
    why = ai_models.why_unusable(task, provider, model)
    assert (why is None) if reason is None else (why and reason in why), why


# ---------------------------------------------------------- the overview ---

def test_the_overview_lists_every_task_with_its_default_and_choice(db):
    with Session(db) as s:
        admin().choose(s, "chat_complex", chain(("anthropic", "claude-opus-5-5"), ("openai", "gpt-5")), MIKE)
        rows = {r["task"]: r for r in admin().overview(s)["tasks"]}
    from services import ai_models
    assert set(rows) == set(ai_models.TASKS)
    complex_row = rows["chat_complex"]
    assert complex_row["default"] == chain(*ai_models.default("chat_complex"))
    assert complex_row["choice"] == chain(("anthropic", "claude-opus-5-5"), ("openai", "gpt-5"))
    assert complex_row["changed_by"] == MIKE and complex_row["changed_at"]
    assert complex_row["effective"] == chain(("anthropic", "claude-opus-5-5"), ("openai", "gpt-5"))
    assert rows["chat"]["choice"] is None and rows["chat"]["effective"] == chain(*ai_models.default("chat"))


def test_the_overview_offers_each_task_only_what_it_can_use_with_prices(db):
    with Session(db) as s:
        rows = {r["task"]: r for r in admin().overview(s)["tasks"]}
    opts = {(o["provider"], o["model"]): o for o in rows["chat_complex"]["options"]}
    opus = opts[("anthropic", "claude-opus-5-5")]
    assert opus["usable"] is True and opus["price_in_pence"] == 315 and opus["price_out_pence"] == 1575
    assert opts[("xai", "grok-4.7")]["usable"] is False and "no key" in opts[("xai", "grok-4.7")]["reason"]
    voice = {(o["provider"], o["model"]) for o in rows["voice_aria"]["options"] if o["usable"]}
    assert voice == {("openai", "gpt-realtime-2")}


def test_the_overview_says_which_providers_have_keys_but_never_the_keys(db):
    with Session(db) as s:
        out = admin().overview(s)
    assert out["providers"] == {"openai": True, "anthropic": True, "xai": False}
    assert "test-key" not in json.dumps(out)


def test_the_overview_shows_this_month_s_spend_per_task(db):
    from datetime import datetime, timezone
    from services.metering import period_for
    period = period_for(datetime.now(timezone.utc))
    rows_in = [("b1", "ai_pence:chat_complex:-:anthropic/claude-opus-5-5", period, 120),
               ("b2", "ai_pence:chat_complex:-:openai/gpt-5", period, 30),
               ("b1", "ai_pence:chat_complex:-:x", "2020-01", 999),           # another month
               ("b1", "ai_pence:chat:-:openai/gpt-5", period, 77)]            # another task
    with db.begin() as c:
        for b, m, p_, v in rows_in:
            c.execute(text("INSERT INTO usage_meters VALUES (:b, :m, :p, :v)"), {"b": b, "m": m, "p": p_, "v": v})
        c.execute(text("INSERT INTO platform_meters VALUES (:m, :p, 5)"),
                  {"m": "ai_pence:chat_complex:-:openai/gpt-5", "p": period})
    with Session(db) as s:
        rows = {r["task"]: r for r in admin().overview(s)["tasks"]}
    assert rows["chat_complex"]["spent_pence"] == pytest.approx(155)
    assert rows["chat"]["spent_pence"] == pytest.approx(77)
    assert rows["chat"]["recorded_as"] == ["chat"] and "Help assistant" in rows["chat"]["shared_with"]


# ------------------------------------------------------------- choosing ---

def test_a_choice_is_saved_with_who_and_takes_effect_at_once(db):
    from services import ai_models
    assert ai_models.resolve("chat_complex") == ai_models.default("chat_complex")   # the choices are now cached
    with Session(db) as s:
        admin().choose(s, "chat_complex", chain(("anthropic", "claude-opus-5-5"), ("openai", "gpt-5")), MIKE)
    assert saved(db, "chat_complex") == (chain(("anthropic", "claude-opus-5-5"), ("openai", "gpt-5")), MIKE, None)
    assert ai_models.resolve("chat_complex")[0] == ("anthropic", "claude-opus-5-5")     # no minute's wait


@pytest.mark.parametrize("bad,reason", [
    (chain(("xai", "grok-4.7")), "no key"),
    (chain(("openai", "gpt-made-up")), "no price"),
    ([], "at least one"),
    (chain(*[("openai", "gpt-5")] * 7), "at most 6"),
    (chain(("openai", "gpt-5"), ("openai", "gpt-5")), "twice"),
    ([{"provider": "openai"}], "provider and a model"),
])
def test_a_choice_that_can_t_work_is_refused_with_its_reason(db, bad, reason):
    from services.aria_actions import ActionRefused
    with Session(db) as s, pytest.raises(ActionRefused) as exc:
        admin().choose(s, "chat_complex", bad, MIKE)
    assert exc.value.status_code == 422 and reason in exc.value.detail
    assert saved(db, "chat_complex") is None


def test_an_unknown_task_is_refused(db):
    from services.aria_actions import ActionRefused
    with Session(db) as s, pytest.raises(ActionRefused) as exc:
        admin().choose(s, "no_such_task", chain(("openai", "gpt-5")), MIKE)
    assert exc.value.status_code == 404


# ------------------------------------------------------- revert and reset ---

def test_revert_restores_the_choice_before(db):
    with Session(db) as s:
        admin().choose(s, "chat_complex", chain(("openai", "gpt-5")), MIKE)
        admin().choose(s, "chat_complex", chain(("anthropic", "claude-opus-5-5")), MIKE)
        admin().revert(s, "chat_complex", MIKE)
    assert saved(db, "chat_complex")[0] == chain(("openai", "gpt-5"))


def test_revert_of_a_first_choice_goes_back_to_the_default(db):
    from services import ai_models
    with Session(db) as s:
        admin().choose(s, "chat_complex", chain(("anthropic", "claude-opus-5-5")), MIKE)
        admin().revert(s, "chat_complex", MIKE)
    assert saved(db, "chat_complex") is None and ai_models.resolve("chat_complex") == ai_models.default("chat_complex")


def test_revert_with_nothing_to_revert_is_refused(db):
    from services.aria_actions import ActionRefused
    with Session(db) as s, pytest.raises(ActionRefused) as exc:
        admin().revert(s, "chat_complex", MIKE)
    assert exc.value.status_code == 409


def test_reset_goes_back_to_the_default_and_can_be_reverted(db):
    from services import ai_models
    with Session(db) as s:
        admin().choose(s, "chat_complex", chain(("anthropic", "claude-opus-5-5")), MIKE)
        admin().reset(s, "chat_complex", MIKE)
        assert admin().overview(s)["tasks"][0]  # still readable
    assert saved(db, "chat_complex") == (chain(*ai_models.default("chat_complex")), MIKE,
                                         chain(("anthropic", "claude-opus-5-5")))
    with Session(db) as s:
        admin().revert(s, "chat_complex", MIKE)
    assert saved(db, "chat_complex")[0] == chain(("anthropic", "claude-opus-5-5"))


# ------------------------------------------------------- test this model ---

class Fake:
    """Answers the evaluation cases by a script, per model."""
    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def __call__(self, provider, model, messages, tools, timeout, _factory):
        self.calls.append((provider, model))
        content, calls = self.answers[(provider, model)](messages, tools)
        return SimpleNamespace(content=content, tool_calls=calls, truncated=False), \
            SimpleNamespace(prompt_tokens=100, completion_tokens=20)


def good(messages, tools):
    last = messages[-1]
    if last["role"] == "tool":
        return "You're owed £1,250 across two overdue invoices.", []
    text_ = last["content"].lower()
    if "overdue" in text_:
        return "", [{"id": "c1", "name": "get_invoices", "arguments": '{"status": "overdue"}'}]
    if "calendar" in text_:
        return "", [{"id": "c2", "name": "get_calendar_events", "arguments": "{}"}]
    if "charge" in text_:
        return "I don't have your prices yet: tell me your day rate and materials and I'll work it out.", []
    return "Hello!", []


def poor(messages, tools):
    text_ = messages[-1]["content"].lower() if messages[-1]["role"] != "tool" else ""
    if "charge" in text_:
        return "You should charge £4,500.", []          # an invented price
    return "I'm not sure.", []


def test_testing_a_model_compares_it_with_the_current_one_and_saves_nothing(db, monkeypatch):
    from services import ai_chat, ai_eval
    fake = Fake({("openai", "gpt-5.4"): good, ("anthropic", "claude-opus-5-5"): poor})
    monkeypatch.setattr(ai_chat, "_ADAPTERS", {"openai": fake, "anthropic": fake, "xai": fake})
    recorded = []
    monkeypatch.setattr(ai_chat, "_record", lambda business_id, **kw: recorded.append((business_id, kw)) or True)
    with Session(db) as s:                       # HK-3: the default is Claude Opus, then GPT-5.4
        out = admin().test(s, "chat_complex", "openai", "gpt-5.4")
    assert out["candidate"]["model"] == "openai/gpt-5.4" and out["current"]["model"] == "anthropic/claude-opus-5-5"
    assert out["candidate"]["passed"] == out["candidate"]["cases"] == len(ai_eval.CASES["chat"])
    assert out["current"]["passed"] < out["current"]["cases"]
    failed = [c for c in out["current"]["results"] if not c["passed"]]
    assert any("price" in c["why"] for c in failed)
    assert all(r[0] is None and r[1]["purpose"] == "eval" for r in recorded)     # platform cost, as eval
    assert out["candidate"]["pence"] > 0
    assert saved(db, "chat_complex") is None                                    # nothing chosen


def test_a_model_that_can_t_serve_the_task_isn_t_tested(db):
    from services.aria_actions import ActionRefused
    with Session(db) as s, pytest.raises(ActionRefused) as exc:
        admin().test(s, "chat_complex", "xai", "grok-4.7")
    assert exc.value.status_code == 422 and "no key" in exc.value.detail


def test_tasks_without_an_evaluation_set_say_so(db):
    from services.aria_actions import ActionRefused
    with Session(db) as s, pytest.raises(ActionRefused) as exc:
        admin().test(s, "voice_aria", "openai", "gpt-realtime-2")
    assert exc.value.status_code == 422 and "no test set" in exc.value.detail


def test_a_failing_provider_counts_as_failed_cases_not_a_crash(db, monkeypatch):
    from services import ai_chat, ai_router

    def down(*a, **k):
        raise ai_router.ProviderError("anthropic: HTTP 529")
    monkeypatch.setattr(ai_chat, "_ADAPTERS", {"openai": Fake({("openai", "gpt-5"): good}), "anthropic": down,
                                               "xai": down})
    monkeypatch.setattr(ai_chat, "_record", lambda *a, **k: True)
    with Session(db) as s:
        out = admin().test(s, "chat_complex", "anthropic", "claude-opus-5-5")
    assert out["candidate"]["passed"] == 0 and all("529" in c["why"] for c in out["candidate"]["results"])
    assert not ai_router._is_down("anthropic")          # a test never switches a provider off for everyone


# ---------------------------------------------------------------- the API ---

def test_every_route_is_for_platform_admins_only():
    import admin_ai_api
    import auth
    for route in admin_ai_api.router.routes:
        deps = [d.call for d in route.dependant.dependencies]
        assert auth.get_platform_admin_context in deps, route.path


def test_the_api_turns_refusals_into_http_errors(db, monkeypatch):
    import admin_ai_api
    with Session(db) as s, pytest.raises(HTTPException) as exc:
        admin_ai_api.admin_ai_choose("chat_complex", admin_ai_api.Choice(chain=chain(("xai", "grok-4.7"))),
                                     auth_ctx={"user_id": MIKE}, session=s)
    assert exc.value.status_code == 422 and "no key" in exc.value.detail



# ------------------------------------------------ Codex AI-1c review 1 ---

@pytest.mark.parametrize("task", ["quote", "quote_chat"])      # AI-1d moved the rest onto ai_text
def test_a_one_openai_task_can_t_be_given_another_provider_or_fallbacks(db, task):
    """Finding 1: support accepted Claude and showed it as used, while its
    code still called gpt-4o; fallbacks were offered that it ignores."""
    from services.aria_actions import ActionRefused
    with Session(db) as s, pytest.raises(ActionRefused) as exc:
        admin().choose(s, task, chain(("anthropic", "claude-opus-5-5")), MIKE)
    assert "OpenAI only" in exc.value.detail
    with Session(db) as s, pytest.raises(ActionRefused) as exc:
        admin().choose(s, task, chain(("openai", "gpt-4o"), ("openai", "gpt-4o-mini")), MIKE)
    assert "one model and no fallbacks" in exc.value.detail


@pytest.mark.parametrize("task,model,site", [
    ("quote", "gpt-4.1", "quoting_api.py"),
])
def test_what_the_page_says_is_used_is_what_the_code_sends(db, monkeypatch, task, model, site):
    """Finding 1: compare an accepted choice with the call site's request."""
    from services import ai_models
    with Session(db) as s:
        admin().choose(s, task, chain(("openai", model)), MIKE)
        effective = {r["task"]: r for r in admin().overview(s)["tasks"]}[task]["effective"]
    assert effective == chain(("openai", model))
    assert ai_models.openai_model(task) == model
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / site).read_text()
    assert f'ai_models.openai_model("{task}")' in source          # and that is how the site asks


def test_the_overview_tells_the_page_how_many_models_each_task_takes(db):
    with Session(db) as s:
        rows = {r["task"]: r for r in admin().overview(s)["tasks"]}
    assert rows["chat_complex"]["max_chain"] == 6 and rows["quote"]["max_chain"] == 1
    assert rows["voice_preview"]["max_chain"] == 3 and rows["support"]["max_chain"] == 6     # AI-1d
    assert rows["meeting"]["max_chain"] == 6                                                # AI-1d part 2
    assert {o["provider"] for o in rows["quote"]["options"] if o["usable"]} == {"openai"}
    assert {o["provider"] for o in rows["support"]["options"] if o["usable"]} == {"openai", "anthropic"}


def test_a_held_test_makes_no_provider_call(db, monkeypatch):
    """Finding 2: tests ignored the profit guard."""
    from services import ai_chat, profit_guard
    from services.aria_actions import ActionRefused
    monkeypatch.setattr(profit_guard, "permits", lambda purpose: purpose != "eval")
    calls = []
    monkeypatch.setattr(ai_chat, "_ADAPTERS", {p: lambda *a: calls.append(a) for p in ("openai", "anthropic", "xai")})
    with Session(db) as s, pytest.raises(ActionRefused) as exc:
        admin().test(s, "chat_complex", "anthropic", "claude-opus-5-5")
    assert exc.value.status_code == 409 and "paused" in exc.value.detail and calls == []


def test_a_test_that_could_cost_too_much_is_refused_before_any_call(db, monkeypatch):
    from services import ai_chat, ai_eval
    from services.aria_actions import ActionRefused
    monkeypatch.setattr(ai_eval, "MAX_RUN_PENCE", 1)
    calls = []
    monkeypatch.setattr(ai_chat, "_ADAPTERS", {p: lambda *a: calls.append(a) for p in ("openai", "anthropic", "xai")})
    with Session(db) as s, pytest.raises(ActionRefused) as exc:
        admin().test(s, "chat_complex", "anthropic", "claude-opus-5-5")
    assert "could cost up to" in exc.value.detail and calls == []


def test_only_one_test_runs_at_a_time(db, monkeypatch):
    from services import ai_eval
    from services.aria_actions import ActionRefused
    ai_eval.admit("chat_complex", [("openai", "gpt-5")])
    try:
        with Session(db) as s, pytest.raises(ActionRefused) as exc:
            admin().test(s, "chat_complex", "anthropic", "claude-opus-5-5")
        assert exc.value.status_code == 409 and "already running" in exc.value.detail
    finally:
        ai_eval.done()


def test_at_most_ten_tests_an_hour(db, monkeypatch):
    import time
    from services import ai_eval
    from services.aria_actions import ActionRefused
    monkeypatch.setattr(ai_eval, "_recent", [time.monotonic()] * ai_eval.RUNS_PER_HOUR)
    with Session(db) as s, pytest.raises(ActionRefused) as exc:
        admin().test(s, "chat_complex", "anthropic", "claude-opus-5-5")
    assert exc.value.status_code == 429


def test_a_test_stops_at_its_deadline(db, monkeypatch):
    """Finding 3: ten slow calls could hold a worker for ten minutes."""
    import time
    from services import ai_chat, ai_eval
    slow = Fake({("anthropic", "claude-opus-5-5"): good, ("openai", "gpt-5"): good})

    def slowly(*a):
        time.sleep(0.15)
        return slow(*a)
    monkeypatch.setattr(ai_chat, "_ADAPTERS", {"openai": slowly, "anthropic": slowly, "xai": slowly})
    monkeypatch.setattr(ai_chat, "_record", lambda *a, **k: True)
    monkeypatch.setattr(ai_eval, "DEADLINE_SECONDS", 0.4)
    monkeypatch.setattr(ai_eval, "MIN_CALL_SECONDS", 0.01)      # scaled with the deadline (review 3)
    with Session(db) as s:
        out = admin().test(s, "chat_complex", "anthropic", "claude-opus-5-5")
    skipped = [c for c in out["candidate"]["results"] + out["current"]["results"] if "ran out of time" in c["why"]]
    assert 0 < len(slow.calls) < 10 and skipped                   # some ran, then it stopped, and said so
    from services.aria_actions import ActionRefused
    try:
        ai_eval.admit("chat_complex", [("openai", "gpt-5")])      # and the slot was freed
    except ActionRefused:
        pytest.fail("the test slot was not released")
    finally:
        ai_eval.done()


def r(content="", calls=()):
    return SimpleNamespace(content=content, tool_calls=list(calls), truncated=False)


@pytest.mark.parametrize("reply", [
    r("You should charge £4,500.", [{"id": "x", "name": "get_invoices", "arguments": "{}"}]),
    r("Charge 4500 GBP."),
    r("About 4,500 pounds."),
    r(""),
])
def test_the_price_check_catches_every_invented_price(reply):
    """Finding 4: a tool call excused '£4,500'; 'GBP' and empty answers passed."""
    from services import ai_eval
    assert ai_eval._no_invented_price(reply)[0] is False


def test_the_price_check_passes_an_honest_answer():
    from services import ai_eval
    assert ai_eval._no_invented_price(r("I don't have your prices yet: what's your day rate?"))[0] is True


@pytest.mark.parametrize("content,ok", [
    ("You're owed £1,250 across two invoices.", True),
    ("You're owed £1,250: £750 from Harbour and £500 from Northgate.", True),
    ("You're owed £91,250, not £1,250.", False),                   # finding 4
    ("You're owed 1250 GBP and also £3,000 from last year.", False),
    ("", False),
])
def test_the_grounding_check_allows_only_amounts_in_the_data(content, ok):
    from services import ai_eval
    assert ai_eval._uses_the_result(r(content))[0] is ok


def test_the_lookup_check_wants_the_right_arguments():
    from services import ai_eval
    check = ai_eval._calls("get_invoices", {"status": "overdue"})
    assert check(r(calls=[{"id": "1", "name": "get_invoices", "arguments": '{"status": "overdue"}'}]))[0] is True
    assert check(r(calls=[{"id": "1", "name": "get_invoices", "arguments": '{"status": "paid"}'}]))[0] is False
    assert check(r(calls=[{"id": "1", "name": "get_invoices", "arguments": "not json"}]))[0] is False


def test_a_cut_off_answer_fails_its_case(db, monkeypatch):
    from services import ai_chat, ai_eval

    def cut(*a):
        return SimpleNamespace(content="Hello", tool_calls=[], truncated=True), SimpleNamespace(prompt_tokens=1, completion_tokens=1)
    monkeypatch.setattr(ai_chat, "_ADAPTERS", {"openai": cut, "anthropic": cut, "xai": cut})
    monkeypatch.setattr(ai_chat, "_record", lambda *a, **k: True)
    out = ai_eval.run("chat", "openai", "gpt-5")
    assert out["passed"] == 0 and all("cut off" in c["why"] for c in out["results"])



# ------------------------------------------------ Codex AI-1c review 2 ---

def test_a_chain_saved_before_the_limit_shows_and_uses_only_what_the_site_takes(db):
    """Finding 1: a [gpt-4o, gpt-4o-mini] row from before max_chain showed a
    fallback the call site never uses (quotes still call OpenAI once)."""
    from services import ai_models
    with db.begin() as c:
        c.execute(text("INSERT INTO ai_model_choices (task, chain) VALUES ('quote', :c)"),
                  {"c": json.dumps(chain(("openai", "gpt-4o"), ("openai", "gpt-4o-mini")))})
    ai_models.invalidate()
    assert ai_models.resolve("quote") == [("openai", "gpt-4o")]
    with Session(db) as s:
        row = {r["task"]: r for r in admin().overview(s)["tasks"]}["quote"]
    assert row["effective"] == chain(("openai", "gpt-4o"))


def test_concurrent_admissions_never_exceed_the_hourly_limit(db, monkeypatch):
    """Finding 2: the hourly list was read and replaced outside any lock."""
    import threading
    import time
    from services import ai_eval
    from services.aria_actions import ActionRefused
    monkeypatch.setattr(ai_eval, "_recent", [time.monotonic()] * (ai_eval.RUNS_PER_HOUR - 1))
    admitted, start = [], threading.Barrier(8)

    def go():
        start.wait()
        try:
            ai_eval.admit("chat", [("openai", "gpt-5")])
            admitted.append(1)
            time.sleep(0.05)
            ai_eval.done()
        except ActionRefused:
            pass
    threads = [threading.Thread(target=go) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(admitted) == 1 and len(ai_eval._recent) == ai_eval.RUNS_PER_HOUR


def test_a_test_stops_when_the_guard_holds_spending_part_way(db, monkeypatch):
    """Finding 2: the guard was checked once; later cases still ran."""
    from services import ai_chat, ai_eval, profit_guard
    fake = Fake({("openai", "gpt-5"): good})
    monkeypatch.setattr(ai_chat, "_ADAPTERS", {"openai": fake, "anthropic": fake, "xai": fake})
    monkeypatch.setattr(ai_chat, "_record", lambda *a, **k: True)
    monkeypatch.setattr(profit_guard, "permits", lambda purpose: len(fake.calls) < 2)
    out = ai_eval.run("chat", "openai", "gpt-5")
    assert len(fake.calls) == 2
    assert sum("held by the profit guard" in c["why"] for c in out["results"]) == len(ai_eval.CASES["chat"]) - 2


def test_every_call_ends_by_the_deadline(db, monkeypatch):
    """Finding 3: a call starting just before the deadline got its full 25s."""
    import time
    from services import ai_chat, ai_eval
    timeouts = []

    def note(provider, model, messages, tools, timeout, _f):
        timeouts.append(timeout)
        return good_reply(messages, tools)
    monkeypatch.setattr(ai_chat, "_ADAPTERS", {"openai": note, "anthropic": note, "xai": note})
    monkeypatch.setattr(ai_chat, "_record", lambda *a, **k: True)
    out = ai_eval.run("chat", "openai", "gpt-5", deadline=time.monotonic() + 10)
    assert timeouts and all(t <= 10 for t in timeouts)
    out = ai_eval.run("chat", "openai", "gpt-5", deadline=time.monotonic() + 1)    # too little left to start
    assert all("ran out of time" in c["why"] for c in out["results"])


def good_reply(messages, tools):
    content, calls = good(messages, tools)
    return SimpleNamespace(content=content, tool_calls=calls, truncated=False), \
        SimpleNamespace(prompt_tokens=10, completion_tokens=5)


@pytest.mark.parametrize("arguments", ["{}", "[]", "null", '{"status": null}'])
def test_the_lookup_check_fails_missing_or_odd_arguments_without_crashing(arguments):
    """Finding 4: {} passed; [] and null raised AttributeError."""
    from services import ai_eval
    check = ai_eval._calls("get_invoices", {"status": "overdue"})
    ok, why = check(r(calls=[{"id": "1", "name": "get_invoices", "arguments": arguments}]))
    assert ok is False and why


def test_a_lookup_with_an_invented_amount_beside_it_fails():
    from services import ai_eval
    check = ai_eval._calls("get_invoices", {"status": "overdue"})
    reply = r("You are owed £91,250.", [{"id": "1", "name": "get_invoices", "arguments": '{"status": "overdue"}'}])
    assert check(reply)[0] is False


@pytest.mark.parametrize("content", [
    "£1,250 total; Harbour £500; Northgate £750.",
    "You're owed £1,250. Harbour Lettings owes £500 and Northgate Estates owes £750.",
])
def test_swapped_customer_balances_fail(content):
    from services import ai_eval
    assert ai_eval._uses_the_result(r(content))[0] is False


@pytest.mark.parametrize("content", [
    "You're owed £1,250.00 on INV-101 and INV-104, due since 10 November 2026.",
    "£1,250 in total: Harbour Lettings £750 (12 days late), Northgate Estates £500 (5 days).",
    "You're owed £1,250 — £750 from Harbour Lettings and £500 from Northgate Estates.",
    "Harbour Lettings owes £750.00; Northgate Estates owes £500.00; £1,250.00 altogether.",
])
def test_honest_grounded_answers_pass(content):
    """No false positives on dates, invoice numbers or pence (review 2)."""
    from services import ai_eval
    assert ai_eval._uses_the_result(r(content)) == (True, "")


@pytest.mark.parametrize("task,purposes", [
    ("reply_draft", ("draft",)), ("email_briefing", ("briefing",)), ("wording", ("accountancy_pack",)),
    ("support", ("chat", "support_draft")), ("briefing", ("briefing",)),
])
def test_each_task_counts_the_purposes_its_code_records(task, purposes):
    """Finding 5: checked against the attribution in the code itself."""
    from services import ai_models
    assert ai_models.TASKS[task].ledger == purposes


def test_the_ledger_list_matches_the_attributions_in_the_code():
    from pathlib import Path
    from services import accountancy_pack
    root = Path(__file__).resolve().parents[1]
    assert accountancy_pack.WORDING_PURPOSE == "accountancy_pack"
    router = (root / "app/email/router.py").read_text()
    assert 'attributed(business.id, "draft")' in router and 'attributed(business.id, "briefing")' in router
    support = (root / "support_api.py").read_text()
    assert 'attributed(None, "chat")' in support and 'attributed(None, "support_draft")' in support


class SlowList(list):
    """Reading it takes a while, from a copy taken at the start, so two
    admissions overlap every time and the later one holds a stale copy."""
    def __iter__(self):
        for item in list(list.__iter__(self)):
            __import__("time").sleep(0.01)
            yield item


def test_a_refused_admission_never_loses_another_s_timestamp(db, monkeypatch):
    """Finding 2, Codex's probe: a refused request rewrote the hourly list
    from a stale copy, dropping the run just admitted."""
    import threading
    import time
    from services import ai_eval
    from services.aria_actions import ActionRefused
    monkeypatch.setattr(ai_eval, "_recent", SlowList([time.monotonic()] * (ai_eval.RUNS_PER_HOUR - 1)))
    outcomes = []

    def go(delay):
        time.sleep(delay)
        try:
            ai_eval.admit("chat", [("openai", "gpt-5")])
            outcomes.append("admitted")
        except ActionRefused:
            outcomes.append("refused")
    a, b = threading.Thread(target=go, args=(0,)), threading.Thread(target=go, args=(0.005,))
    a.start(); b.start(); a.join(); b.join()
    try:
        assert sorted(outcomes) == ["admitted", "refused"]
        assert len(ai_eval._recent) == ai_eval.RUNS_PER_HOUR       # the admitted run still counts
    finally:
        ai_eval.done()
