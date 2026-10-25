"""OUT-19 part A — the AI cost ledger (docs/OUT-19-TICKET.md). RED: AI spend.

Mike, 25 Oct 2026: outreach must cover every AI cost with a net profit, and
never become "a money losing monster". Every outreach AI call records what it
cost, per business and brand; Mike sees cost and margin; a platform-wide
monthly alarm and kill switch stop runaway spend. No network or model call
happens here: the model client is faked.
"""
# ruff: noqa: F811 - pytest fixtures imported from test_outreach_setup are parameters by design

import json
import logging
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlmodel import Session

from test_outreach_setup import db  # noqa: F401

NOW = datetime(2026, 10, 27, 9, tzinfo=timezone.utc)


def costs():
    from services import ai_costs
    return ai_costs


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.delenv("AI_MONTHLY_KILL_PENCE", raising=False)
    monkeypatch.delenv("AI_MONTHLY_ALARM_PENCE", raising=False)
    e = create_engine("sqlite:///" + str(tmp_path / "ledger.sqlite"))
    with e.begin() as c:
        c.execute(text("CREATE TABLE usage_meters (business_id TEXT, meter TEXT, period TEXT, value NUMERIC, "
                       "updated_at TEXT, UNIQUE (business_id, meter, period))"))
    yield e
    e.dispose()


def meter(engine, bid, name, period="2026-10"):
    with engine.connect() as c:
        v = c.execute(text("SELECT value FROM usage_meters WHERE business_id = :b AND meter = :m AND period = :p"),
                      {"b": bid, "m": name, "p": period}).scalar()
    return float(v or 0)


# ------------------------------------------------------------ recording ---

def test_a_call_is_recorded_for_the_business_its_purpose_its_brand_and_its_model(engine):
    with Session(engine) as s:
        costs().record(s, "biz-a", purpose="research", brand_id="brand-1", provider="openai", model="gpt-4.1",
                       pence=37, moment=NOW)
        s.commit()
    assert meter(engine, "biz-a", "ai_pence") == 37
    assert meter(engine, "biz-a", "ai_pence:research:brand-1:openai/gpt-4.1") == 37
    assert meter(engine, "biz-a", "ai_calls:research:brand-1:openai/gpt-4.1") == 1


def test_costs_add_up_across_calls_and_stay_in_their_month(engine):
    with Session(engine) as s:
        for p in (10, 15):
            costs().record(s, "biz-a", purpose="draft", provider="openai", model="gpt-4o", pence=p, moment=NOW)
        costs().record(s, "biz-a", purpose="draft", provider="openai", model="gpt-4o", pence=99,
                       moment=datetime(2026, 11, 2, 9, tzinfo=timezone.utc))
        s.commit()
    assert meter(engine, "biz-a", "ai_pence") == 25
    assert meter(engine, "biz-a", "ai_pence:draft:-:openai/gpt-4o") == 25
    assert meter(engine, "biz-a", "ai_pence", period="2026-11") == 99


def test_cost_is_priced_from_tokens_when_not_given(engine):
    """gpt-4o at the default table: 1M input + 1M output tokens."""
    c = costs()
    p_in, p_out, _ = c.price("openai", "gpt-4o")
    with Session(engine) as s:
        got = c.record(s, "biz-a", purpose="draft", provider="openai", model="gpt-4o",
                       input_tokens=1_000_000, output_tokens=1_000_000, moment=NOW)
        s.commit()
    assert got == pytest.approx(p_in + p_out)
    assert meter(engine, "biz-a", "ai_pence") == pytest.approx(p_in + p_out)


def test_an_unpriced_model_is_refused_never_recorded_as_free(engine):
    c = costs()
    with pytest.raises(c.Unpriced):
        c.require_priced("mystery", "x-1")
    with Session(engine) as s:
        with pytest.raises(c.Unpriced):
            c.record(s, "biz-a", purpose="draft", provider="mystery", model="x-1", input_tokens=10, moment=NOW)


@pytest.mark.parametrize("bad", [
    {"openai/gpt-4o": [-1, 400, 0]}, {"openai/gpt-4o": [float("nan"), 1, 1]}, {"openai/gpt-4o": [1, 2]},
    {"openai/gpt-4o": "cheap"}, {"no-slash": [1, 1, 1]},
    {"openai/gpt-4o": [100, 400, 0], "openai/gpt-4.1": [1, -2, 0]},     # one bad entry spoils the lot
])
def test_an_invalid_price_setting_is_ignored_as_a_whole(monkeypatch, bad, caplog):
    monkeypatch.setenv("AI_PRICES_JSON", json.dumps(bad).replace("NaN", "NaN"))
    with caplog.at_level(logging.ERROR):
        assert costs().price("openai", "gpt-4o") == costs().DEFAULT_PRICES["openai/gpt-4o"]
    assert "ignored" in caplog.text


def test_usage_is_kept_per_purpose_brand_and_model(engine):
    with Session(engine) as s:
        costs().record(s, "biz-a", purpose="research", brand_id="b1", provider="openai", model="gpt-4.1",
                       input_tokens=1200, output_tokens=300, tool_calls=4, moment=NOW)
        costs().record(s, "biz-a", purpose="research", brand_id="b1", provider="openai", model="gpt-4.1",
                       pence=189, estimated=True, moment=NOW)
        s.commit()
        out = costs().economics(s, period="2026-10")
    m = out["businesses"]["biz-a"]["models"]["openai/gpt-4.1"]
    assert (m["calls"], m["estimated_calls"], m["tokens_in"], m["tokens_out"], m["tool_calls"]) == (2, 1, 1200, 300, 4)


def test_prices_can_be_changed_by_setting_without_a_deploy(engine, monkeypatch):
    monkeypatch.setenv("AI_PRICES_JSON", json.dumps({"openai/gpt-4o": [100, 400, 0]}))
    assert costs().price("openai", "gpt-4o") == (100, 400, 0)


# ------------------------------------------- collecting a model call's cost ---

class FakeChat:
    def __init__(self, content, prompt_tokens, completion_tokens):
        self.content, self.usage = content, SimpleNamespace(prompt_tokens=prompt_tokens,
                                                             completion_tokens=completion_tokens)

    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))],
                               usage=self.usage)


def fake_openai(monkeypatch, chat):
    import openai
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: SimpleNamespace(chat=SimpleNamespace(completions=chat)))


def test_a_drafting_call_reports_what_it_cost(engine, monkeypatch):
    from services import outreach_setup
    chat = FakeChat('{"purpose": "p"}', prompt_tokens=2000, completion_tokens=500)
    fake_openai(monkeypatch, chat)
    with costs().collect() as spent:
        outreach_setup._model_json("Draft", {"x": 1})
    assert len(spent) == 1 and spent[0]["provider"] == "openai" and spent[0]["model"] == chat.kwargs["model"]
    assert spent[0]["input_tokens"] == 2000 and spent[0]["output_tokens"] == 500


def test_aria_drafting_a_legal_basis_is_recorded_against_the_business_and_brand(db, monkeypatch):
    """Through the real setup step, with only the model client faked."""
    from test_outreach_setup import A, OWNER, grant, setup_module_or_missing
    m = setup_module_or_missing()
    biz = grant(db)
    chat = FakeChat(json.dumps({k: f"{k} text" for k in ("purpose", "necessity", "balancing_test", "safeguards")}),
                    prompt_tokens=3000, completion_tokens=800)
    fake_openai(monkeypatch, chat)
    with Session(db) as s:
        m.begin(s, biz, OWNER)
        brand = m.save_brand(s, biz, OWNER, {"name": "FitFutures", "sender_identity": "FitFutures"})
        m.draft_audience(s, biz, OWNER, {"brand_id": brand["id"], "description": "Gyms", "segments": ["gym"],
                                         "regions": ["Kent"]})
    expected = costs().cost("openai", chat.kwargs["model"], 3000, 800)
    period = datetime.now(timezone.utc).strftime("%Y-%m")
    assert meter(db, A, f"ai_pence:draft:{brand['id']}:openai/{chat.kwargs['model']}", period) == pytest.approx(expected, abs=0.01)
    assert meter(db, A, "ai_pence", period) == pytest.approx(expected, abs=0.01)


def test_a_research_search_is_recorded_against_its_brand(db):
    from test_outreach_research import World, person, run, started
    biz, brand, lia, campaign = started(db)
    run(db, biz, lia, World([[person(i) for i in range(20)]], cost=37))
    from test_outreach_setup import A
    assert meter(db, A, f"ai_pence:research:{brand['id']}:openai/gpt-4.1") == 37
    assert meter(db, A, "ai_pence") == 37


def test_the_kill_switch_stops_research_before_it_spends(db, monkeypatch):
    from test_outreach_research import World, person, run, started
    from test_outreach_setup import A
    biz, brand, lia, campaign = started(db)
    monkeypatch.setenv("AI_MONTHLY_KILL_PENCE", "100")
    with db.begin() as c:
        c.execute(text("INSERT INTO usage_meters (business_id, meter, period, value, updated_at) "
                       "VALUES ('another-business', 'ai_pence', '2026-10', 100, '2026-10-01')"))
    world = World([[person(1)]])
    out = run(db, biz, lia, world)
    assert world.briefs == [] and "paused" in out["stopped"].lower()
    assert meter(db, A, f"outreach_research_pence:{brand['id']}") == 0


def test_the_kill_switch_stops_aria_drafting(db, monkeypatch):
    from test_outreach_setup import OWNER, grant, setup_module_or_missing
    m = setup_module_or_missing()
    biz = grant(db)
    monkeypatch.setenv("AI_MONTHLY_KILL_PENCE", "1")
    period = datetime.now(timezone.utc).strftime("%Y-%m")
    with db.begin() as c:
        c.execute(text("INSERT INTO usage_meters (business_id, meter, period, value, updated_at) "
                       "VALUES ('another-business', 'ai_pence', :p, 5, '2026-10-01')"), {"p": period})
    with Session(db) as s:
        m.begin(s, biz, OWNER)
        brand = m.save_brand(s, biz, OWNER, {"name": "FitFutures", "sender_identity": "FitFutures"})
        with pytest.raises(Exception) as caught:
            m.draft_audience(s, biz, OWNER, {"brand_id": brand["id"], "description": "Gyms"},
                             draft=lambda ctx: pytest.fail("drafted while AI spend is paused"))
    assert getattr(caught.value, "status_code", None) == 503


# ------------------------------------------------------- platform limits ---

def test_the_platform_kill_switch_stops_ai_spend_once_the_month_reaches_it(engine, monkeypatch):
    monkeypatch.setenv("AI_MONTHLY_KILL_PENCE", "100")
    c = costs()
    with Session(engine) as s:
        assert c.allowed(s, moment=NOW) is True
        c.record(s, "biz-a", purpose="research", provider="openai", model="gpt-4.1", pence=60, moment=NOW)
        c.record(s, "biz-b", purpose="research", provider="openai", model="gpt-4.1", pence=40, moment=NOW)
        s.commit()
        assert c.allowed(s, moment=NOW) is False              # the platform total, across businesses


def test_without_a_kill_setting_spend_is_never_blocked_by_the_platform_check(engine):
    with Session(engine) as s:
        costs().record(s, "biz-a", purpose="research", provider="openai", model="gpt-4.1", pence=10 ** 7, moment=NOW)
        s.commit()
        assert costs().allowed(s, moment=NOW) is True


def test_crossing_the_alarm_is_logged_once_a_month_and_only_after_commit(engine, monkeypatch, caplog):
    monkeypatch.setenv("AI_MONTHLY_ALARM_PENCE", "50")
    c = costs()
    with caplog.at_level(logging.ERROR):
        with Session(engine) as s:
            c.record(s, "biz-a", purpose="research", provider="openai", model="gpt-4.1", pence=60, moment=NOW)
            s.rollback()                                   # never committed: no alarm
        assert "AI spend alarm" not in caplog.text
        with Session(engine) as s:
            c.record(s, "biz-a", purpose="research", provider="openai", model="gpt-4.1", pence=60, moment=NOW)
            s.rollback()                                   # rolled back on THIS session ...
            s.commit()                                     # ... and a later empty commit raises nothing
        assert "AI spend alarm" not in caplog.text
        with Session(engine) as s:
            for _ in range(3):
                c.record(s, "biz-a", purpose="research", provider="openai", model="gpt-4.1", pence=30, moment=NOW)
            assert "AI spend alarm" not in caplog.text     # not before the commit
            s.commit()
            s.commit()                                     # a second commit never repeats it
    assert caplog.text.count("AI spend alarm") == 1


# ------------------------------------------------------------ economics ---

def test_economics_shows_each_business_cost_by_purpose_and_brand(engine):
    c = costs()
    with Session(engine) as s:
        c.record(s, "biz-a", purpose="research", brand_id="b1", provider="openai", model="gpt-4.1", pence=120, moment=NOW)
        c.record(s, "biz-a", purpose="draft", brand_id="b1", provider="openai", model="gpt-4o", pence=30, moment=NOW)
        c.record(s, "biz-a", purpose="research", brand_id="b2", provider="openai", model="gpt-4.1", pence=50, moment=NOW)
        c.record(s, "biz-b", purpose="research", provider="openai", model="gpt-4.1", pence=7, moment=NOW)
        s.commit()
        out = c.economics(s, period="2026-10")
    a = out["businesses"]["biz-a"]
    assert a["total_pence"] == 200
    assert a["by_purpose"] == {"research": 170, "draft": 30}
    assert a["by_brand"] == {"b1": 150, "b2": 50}
    assert {k: v["calls"] for k, v in a["models"].items()} == {"openai/gpt-4.1": 2, "openai/gpt-4o": 1}
    assert out["platform_pence"] == 207


# ------------------------------------------ the admin economics report ---

@pytest.fixture
def report_db(engine):
    with engine.begin() as c:
        c.execute(text("CREATE TABLE businesses (id TEXT PRIMARY KEY, name TEXT, plan_tier TEXT, feature_flags TEXT)"))
        c.execute(text("CREATE TABLE outreach_brands (id TEXT PRIMARY KEY, business_id TEXT, name TEXT, created_at TEXT)"))
        c.execute(text("INSERT INTO businesses VALUES ('nb', 'New Body', 'business', '{}'), "
                       "('msc', 'MSC', 'pro', '{\"outreach\": true}'), ('gym2', 'Other', 'starter', '{}')"))
        c.execute(text("INSERT INTO outreach_brands VALUES ('fit', 'nb', 'FitFutures', '2026-09-01T09:00:00+00:00'), "
                       "('gym', 'nb', 'New Body Gym', '2026-09-02T09:00:00+00:00'), "
                       "('msc-b', 'msc', 'MSC', '2026-09-01T09:00:00+00:00')"))
    return engine


def test_the_report_sets_each_business_cost_against_its_outreach_revenue(report_db):
    """Mike's prices (25 Oct 2026): the first brand is included in Business,
    each extra brand £79, the Pro add-on £99 for its first brand."""
    from services import outreach_pricing
    c = costs()
    with Session(report_db) as s:
        c.record(s, "nb", purpose="research", brand_id="fit", provider="openai", model="gpt-4.1", pence=900, moment=NOW)
        c.record(s, "nb", purpose="research", brand_id="gym", provider="openai", model="gpt-4.1", pence=400, moment=NOW)
        c.record(s, "msc", purpose="research", brand_id="msc-b", provider="openai", model="gpt-4.1", pence=2500, moment=NOW)
        s.commit()
        rows = {r["business_id"]: r for r in outreach_pricing.report(s, period="2026-10")["businesses"]}
    nb, msc = rows["nb"], rows["msc"]
    assert nb["brands"] == [{"id": "fit", "name": "FitFutures", "cost_pence": 900, "price_pence": 0, "included": True},
                            {"id": "gym", "name": "New Body Gym", "cost_pence": 400, "price_pence": 7900, "included": False}]
    assert nb["revenue_pence"] == 7900 and nb["cost_pence"] == 1300 and nb["margin_pence"] == 6600
    assert msc["revenue_pence"] == 9900 and msc["margin_pence"] == 7400
    assert "gym2" not in rows, "a business with no outreach and no AI cost is not listed"


def test_a_business_costing_more_than_it_pays_is_flagged(report_db):
    from services import outreach_pricing
    with Session(report_db) as s:
        costs().record(s, "msc", purpose="research", brand_id="msc-b", provider="openai", model="gpt-4.1",
                       pence=12000, moment=NOW)
        s.commit()
        out = outreach_pricing.report(s, period="2026-10")
    msc = next(r for r in out["businesses"] if r["business_id"] == "msc")
    assert msc["margin_pence"] == -2100 and msc["losing_money"] is True
    assert out["losing_money"] == ["msc"]


def test_the_economics_route_is_platform_admin_only():
    from auth import get_platform_admin_context
    import admin_outreach_api
    route = next(r for r in admin_outreach_api.router.routes if r.path.endswith("/economics"))
    deps = [d.call for d in route.dependant.dependencies]
    assert get_platform_admin_context in deps



# ------------------------------------------------ Codex OUT-19 review 1 ---

def _setup_brand(db):
    from test_outreach_setup import OWNER, grant, setup_module_or_missing
    m = setup_module_or_missing()
    biz = grant(db)
    with Session(db) as s:
        m.begin(s, biz, OWNER)
        brand = m.save_brand(s, biz, OWNER, {"name": "FitFutures", "sender_identity": "FitFutures"})
    return m, biz, brand


def _draft_cost(db, brand):
    from test_outreach_setup import A
    period = datetime.now(timezone.utc).strftime("%Y-%m")
    return meter(db, A, f"ai_pence:draft:{brand['id']}:openai/gpt-4o", period)


@pytest.mark.parametrize("content", ["not json at all", json.dumps({"purpose": ""})])
def test_a_paid_draft_that_is_then_rejected_is_still_recorded(db, monkeypatch, content):
    """P1 1: invalid model output, or output the step refuses, was paid for."""
    from test_outreach_setup import OWNER
    m, biz, brand = _setup_brand(db)
    fake_openai(monkeypatch, FakeChat(content, prompt_tokens=1000, completion_tokens=200))
    with Session(db) as s:
        with pytest.raises(Exception):
            m.draft_audience(s, biz, OWNER, {"brand_id": brand["id"], "description": "Gyms"})
    assert _draft_cost(db, brand) == pytest.approx(costs().cost("openai", "gpt-4o", 1000, 200), abs=0.01)


def test_a_model_call_that_fails_is_recorded_at_an_estimate(db, monkeypatch):
    from test_outreach_setup import OWNER
    m, biz, brand = _setup_brand(db)
    class Broken:
        def create(self, **kwargs):
            raise TimeoutError("timed out after the provider started work")
    fake_openai(monkeypatch, Broken())
    with Session(db) as s:
        with pytest.raises(Exception):
            m.draft_audience(s, biz, OWNER, {"brand_id": brand["id"], "description": "Gyms"})
    from services import outreach_setup
    assert _draft_cost(db, brand) >= costs().cost("openai", "gpt-4o", 0, outreach_setup.DRAFT_MAX_TOKENS)


def test_a_campaign_whose_drafted_emails_are_refused_is_still_recorded(db, monkeypatch):
    from test_outreach_setup import OWNER, ready, setup_module_or_missing, WORKSPACE
    m = setup_module_or_missing()
    from test_outreach_setup import grant
    biz = grant(db)
    brand, lia, _ = ready(m, db, biz)
    fake_openai(monkeypatch, FakeChat(json.dumps({"emails": [{"subject": "only one", "body": "b"}]}),
                                      prompt_tokens=500, completion_tokens=100))
    with Session(db) as s:
        with pytest.raises(Exception):
            m.create_first_campaign(s, biz, OWNER, {"name": "Two", "brand_id": brand["id"], "mailbox_id": WORKSPACE,
                                                    "compliance_id": lia["id"], "daily_cap": 5})
    assert _draft_cost(db, brand) > 0


def test_the_drafting_client_never_retries_on_its_own(db, monkeypatch):
    import openai
    seen = {}
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    def client(**kw):
        seen.update(kw)
        return SimpleNamespace(chat=SimpleNamespace(completions=FakeChat("{}", 1, 1)))
    monkeypatch.setattr(openai, "OpenAI", client)
    from services import outreach_setup
    outreach_setup._model_json("x", {})
    assert seen["max_retries"] == 0


def test_an_unpriced_draft_model_is_refused_before_the_model_runs(db, monkeypatch):
    from test_outreach_setup import OWNER
    m, biz, brand = _setup_brand(db)
    monkeypatch.setenv("ARIA_DRAFT_MODEL", "brand-new-model")
    with Session(db) as s:
        with pytest.raises(Exception) as caught:
            m.draft_audience(s, biz, OWNER, {"brand_id": brand["id"], "description": "Gyms"},
                             draft=lambda ctx: pytest.fail("ran an unpriced model"))
    assert getattr(caught.value, "status_code", None) == 503


def test_a_failed_search_is_recorded_at_its_reserve_as_an_estimate(db):
    """P1 2: billable timeouts were invisible to the platform limit."""
    from test_outreach_research import World, person, research, run, started
    from test_outreach_setup import A
    biz, brand, lia, campaign = started(db)
    world = World([[person(1)]])
    world.search_error = TimeoutError("provider timeout")
    run(db, biz, lia, world)
    key = f"research:{brand['id']}:openai/gpt-4.1"
    assert meter(db, A, f"ai_pence:{key}") == research().MAX_SEARCH_PENCE
    assert meter(db, A, f"ai_estimated:{key}") == 1


def test_an_unpriced_research_model_stops_before_reserving(db, monkeypatch):
    from test_outreach_research import World, person, run, started
    from test_outreach_setup import A
    biz, brand, lia, campaign = started(db)
    monkeypatch.setenv("ARIA_RESEARCH_MODEL", "unknown-model")
    world = World([[person(1)]])
    out = run(db, biz, lia, world)
    assert world.briefs == [] and "no price" in out["stopped"]
    assert meter(db, A, f"outreach_research_pence:{brand['id']}") == 0


def test_research_reserves_from_the_one_price_table(monkeypatch):
    from test_outreach_research import research
    r = research()
    monkeypatch.setenv("AI_PRICES_JSON", json.dumps({"openai/gpt-4.1": [320, 1280, 4]}))
    assert r.max_search_pence() > r.MAX_SEARCH_PENCE * 1.9


def test_a_past_month_counts_only_brands_that_existed_then(report_db):
    """Review 1 P2 7: a brand made in November never adds £79 to October."""
    from services import outreach_pricing
    with report_db.begin() as c:
        c.execute(text("INSERT INTO outreach_brands VALUES ('late', 'nb', 'Later Brand', '2026-11-05T10:00:00+00:00')"))
    with Session(report_db) as s:
        oct_ = next(r for r in outreach_pricing.report(s, period="2026-10")["businesses"] if r["business_id"] == "nb")
        nov = next(r for r in outreach_pricing.report(s, period="2026-11")["businesses"] if r["business_id"] == "nb")
        out = outreach_pricing.report(s, period="2026-10")
    assert [b["id"] for b in oct_["brands"]] == ["fit", "gym"] and oct_["revenue_pence"] == 7900
    assert nov["revenue_pence"] == 2 * 7900
    assert "Projected" in out["revenue_basis"] and "Incremental" in out["margin_basis"]



# ------------------------------------------------ Codex OUT-19 review 2 ---

@pytest.mark.parametrize("usage", [None, SimpleNamespace(prompt_tokens=100), SimpleNamespace(completion_tokens=5)])
def test_a_successful_draft_without_reported_usage_is_charged_at_its_most_and_marked(db, monkeypatch, usage):
    from test_outreach_setup import A, OWNER
    from services import outreach_setup
    m, biz, brand = _setup_brand(db)
    chat = FakeChat(json.dumps({k: "x" for k in ("purpose", "necessity", "balancing_test", "safeguards")}), 1, 1)
    chat.usage = usage
    fake_openai(monkeypatch, chat)
    with Session(db) as s:
        m.draft_audience(s, biz, OWNER, {"brand_id": brand["id"], "description": "Gyms"})
    period = datetime.now(timezone.utc).strftime("%Y-%m")
    key = f"draft:{brand['id']}:openai/gpt-4o"
    assert _draft_cost(db, brand) >= costs().cost("openai", "gpt-4o", 0, outreach_setup.DRAFT_MAX_TOKENS)
    assert meter(db, A, f"ai_estimated:{key}", period) == 1


def test_a_search_without_reported_usage_is_charged_its_full_reserve(monkeypatch):
    import openai
    from test_outreach_research import research
    r = research()
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    response = SimpleNamespace(usage=None, output=[], output_text='{"candidates": []}')
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: SimpleNamespace(responses=SimpleNamespace(create=lambda **k: response)))
    out = r.web_search("brief")
    assert out["cost_pence"] == r.max_search_pence() and out["estimated"] is True


def test_a_brand_made_just_after_midnight_bst_belongs_to_its_new_month(report_db):
    """00:30 BST on 1 October is 23:30 UTC on 30 September."""
    from services import outreach_pricing
    with report_db.begin() as c:
        c.execute(text("INSERT INTO outreach_brands VALUES ('oct', 'nb', 'October Brand', '2026-09-30T23:30:00+00:00')"))
    with Session(report_db) as s:
        sep = next(r for r in outreach_pricing.report(s, period="2026-09")["businesses"] if r["business_id"] == "nb")
        oct_ = next(r for r in outreach_pricing.report(s, period="2026-10")["businesses"] if r["business_id"] == "nb")
    assert "oct" not in [b["id"] for b in sep["brands"]]
    assert "oct" in [b["id"] for b in oct_["brands"]]


def test_a_huge_number_in_the_price_setting_is_rejected_not_a_crash(monkeypatch):
    monkeypatch.setenv("AI_PRICES_JSON", '{"openai/gpt-4o": [' + "9" * 400 + ', 1, 1]}')
    assert costs().price("openai", "gpt-4o") == costs().DEFAULT_PRICES["openai/gpt-4o"]


def test_a_failure_to_record_a_successful_draft_never_hands_the_draft_out(db, monkeypatch):
    from test_outreach_setup import OWNER
    m, biz, brand = _setup_brand(db)
    fake_openai(monkeypatch, FakeChat(json.dumps({k: "x" for k in ("purpose", "necessity", "balancing_test",
                                                                     "safeguards")}), 10, 10))
    def broken(*a, **k):
        raise RuntimeError("ledger unavailable")
    monkeypatch.setattr(costs(), "save", broken)
    with Session(db) as s:
        with pytest.raises(RuntimeError):
            m.draft_audience(s, biz, OWNER, {"brand_id": brand["id"], "description": "Gyms"})


def test_a_failed_draft_keeps_its_own_error_when_recording_also_fails(db, monkeypatch):
    from test_outreach_setup import OWNER
    m, biz, brand = _setup_brand(db)
    fake_openai(monkeypatch, FakeChat("not json", 10, 10))
    monkeypatch.setattr(costs(), "save", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("ledger unavailable")))
    with Session(db) as s:
        with pytest.raises(ValueError):          # the model's bad JSON, not the ledger
            m.draft_audience(s, biz, OWNER, {"brand_id": brand["id"], "description": "Gyms"})
