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
    assert meter(engine, "biz-a", "ai_pence:research:brand-1") == 37
    assert meter(engine, "biz-a", "ai_calls:openai/gpt-4.1") == 1


def test_costs_add_up_across_calls_and_stay_in_their_month(engine):
    with Session(engine) as s:
        for p in (10, 15):
            costs().record(s, "biz-a", purpose="draft", provider="openai", model="gpt-4o", pence=p, moment=NOW)
        costs().record(s, "biz-a", purpose="draft", provider="openai", model="gpt-4o", pence=99,
                       moment=datetime(2026, 11, 2, 9, tzinfo=timezone.utc))
        s.commit()
    assert meter(engine, "biz-a", "ai_pence") == 25
    assert meter(engine, "biz-a", "ai_pence:draft:-") == 25
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


def test_an_unpriced_model_is_charged_at_the_dearest_known_rate_never_free(engine, caplog):
    """Fail closed: a cost the ledger can't price is never recorded as zero."""
    c = costs()
    dearest = max(c.price(p, m)[0] + c.price(p, m)[1] for p, m in c.known_models())
    with caplog.at_level(logging.WARNING):
        with Session(engine) as s:
            got = c.record(s, "biz-a", purpose="draft", provider="mystery", model="x-1",
                           input_tokens=1_000_000, output_tokens=1_000_000, moment=NOW)
            s.commit()
    assert got == pytest.approx(dearest)
    assert "unpriced" in caplog.text.lower()


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
    assert meter(db, A, f"ai_pence:draft:{brand['id']}", period) == pytest.approx(expected, abs=0.01)
    assert meter(db, A, "ai_pence", period) == pytest.approx(expected, abs=0.01)


def test_a_research_search_is_recorded_against_its_brand(db):
    from test_outreach_research import World, person, run, started
    biz, brand, lia, campaign = started(db)
    run(db, biz, lia, World([[person(i) for i in range(20)]], cost=37))
    from test_outreach_setup import A
    assert meter(db, A, f"ai_pence:research:{brand['id']}") == 37
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


def test_crossing_the_alarm_is_logged_once_a_month(engine, monkeypatch, caplog):
    monkeypatch.setenv("AI_MONTHLY_ALARM_PENCE", "50")
    c = costs()
    with caplog.at_level(logging.ERROR):
        with Session(engine) as s:
            for _ in range(3):
                c.record(s, "biz-a", purpose="research", provider="openai", model="gpt-4.1", pence=30, moment=NOW)
            s.commit()
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
    assert a["calls"] == {"openai/gpt-4.1": 2, "openai/gpt-4o": 1}
    assert out["platform_pence"] == 207


# ------------------------------------------ the admin economics report ---

@pytest.fixture
def report_db(engine):
    with engine.begin() as c:
        c.execute(text("CREATE TABLE businesses (id TEXT PRIMARY KEY, name TEXT, plan_tier TEXT, feature_flags TEXT)"))
        c.execute(text("CREATE TABLE outreach_brands (id TEXT PRIMARY KEY, business_id TEXT, name TEXT, created_at TEXT)"))
        c.execute(text("INSERT INTO businesses VALUES ('nb', 'New Body', 'business', '{}'), "
                       "('msc', 'MSC', 'pro', '{\"outreach\": true}'), ('gym2', 'Other', 'starter', '{}')"))
        c.execute(text("INSERT INTO outreach_brands VALUES ('fit', 'nb', 'FitFutures', '1'), ('gym', 'nb', 'New Body Gym', '2'), "
                       "('msc-b', 'msc', 'MSC', '1')"))
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
