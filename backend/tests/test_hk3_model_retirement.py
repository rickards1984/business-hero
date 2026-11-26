"""HK-3 (25 Nov 2026): OpenAI retires gpt-5 on 11 December 2026.

OpenAI's deprecations page (developers.openai.com/api/docs/deprecations):
- 11 Dec 2026: gpt-5, gpt-5-mini, gpt-5-nano, gpt-5-pro, o3 and o3-pro;
- 14 Jan 2027: the gpt-4o, gpt-4o-mini, gpt-4.1 and gpt-4.1-mini snapshots.

gpt-5.4, gpt-5.5 and gpt-5.6 are not on it. Mike chose (25 Nov):
- text-only jobs: gpt-6.1-sol (OpenAI's named replacement), then Claude Sonnet 5.5;
- jobs that use tools (Aria chat and the board meeting): Claude first, then
  gpt-5.4, because gpt-6.1-sol's tool calls need the Responses API (AI-1e);
- the old gpt-4o-mini fallbacks become Claude Sonnet 5.5.

A retired model is never sent from its shutdown date, so a job falls to its
next model, rather than failing every time. The admin page warns in advance.
"""
from datetime import date

import pytest

from services import ai_models

SONNET, OPUS = ("anthropic", "claude-sonnet-5-5"), ("anthropic", "claude-opus-5-5")
SOL, LUNA, G54 = ("openai", "gpt-6.1-sol"), ("openai", "gpt-6-luna"), ("openai", "gpt-5.4")


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "XAI_API_KEY"):
        monkeypatch.setenv(key, "test-key")


@pytest.mark.parametrize("task,chain", [
    ("chat", [SONNET, G54]),
    ("chat_complex", [OPUS, G54]),
    ("meeting", [OPUS, G54]),
    ("briefing", [SOL, SONNET]),
    ("support", [SOL, SONNET]),
    ("email_briefing", [SOL, SONNET]),
    ("reply_drafts", [SOL, SONNET]),
    ("inbox_classify", [LUNA, SONNET]),
    ("reply_draft", [LUNA, SONNET]),
    ("call_summary", [LUNA, SONNET]),
    ("quote", [G54]), ("quote_chat", [SOL]),
])
def test_the_defaults_mike_chose(task, chain):
    assert list(ai_models.TASKS[task].default) == chain


def test_no_default_uses_a_model_that_is_retiring():
    for name, task in ai_models.TASKS.items():
        for provider, model in task.default:
            assert ai_models.retires_on(provider, model) is None, (name, model)


@pytest.mark.parametrize("model,on", [
    ("gpt-5", date(2026, 12, 11)), ("gpt-5-2025-08-07", date(2026, 12, 11)), ("gpt-5-mini", date(2026, 12, 11)),
    ("gpt-5-nano", date(2026, 12, 11)), ("gpt-5-pro", date(2026, 12, 11)), ("o3", date(2026, 12, 11)),
    ("o3-pro", date(2026, 12, 11)), ("ft:gpt-5:acme::x", date(2026, 12, 11)),
    ("gpt-4o", date(2027, 1, 14)), ("gpt-4o-mini", date(2027, 1, 14)), ("gpt-4.1", date(2027, 1, 14)),
    ("gpt-4.1-mini", date(2027, 1, 14)), ("gpt-4o-2024-11-20", date(2027, 1, 14)),
    ("gpt-5.4", None), ("gpt-5.5", None), ("gpt-6.1-sol", None), ("gpt-6-luna", None), ("gpt-4o-mini-tts", None),
    ("gpt-5-chat-latest", None),
])
def test_the_shutdown_dates_are_openai_s(model, on):
    assert ai_models.retires_on("openai", model) == on


def test_another_provider_s_model_never_retires_by_openai_s_list():
    assert ai_models.retires_on("anthropic", "gpt-5") is None


def test_a_retired_model_is_never_used_from_its_date(monkeypatch):
    monkeypatch.setattr(ai_models, "_today", lambda: date(2026, 12, 10))
    assert ai_models.why_unusable("briefing", "openai", "gpt-5") is None
    monkeypatch.setattr(ai_models, "_today", lambda: date(2026, 12, 11))
    why = ai_models.why_unusable("briefing", "openai", "gpt-5")
    assert why and "stopped working on 11 December 2026" in why


def test_a_saved_choice_of_a_retired_model_falls_to_the_next(monkeypatch):
    """Mike's saved briefing choice was gpt-5 alone: from 11 Dec it falls to
    the default rather than failing every time."""
    monkeypatch.setattr(ai_models, "_today", lambda: date(2026, 12, 11))
    monkeypatch.setattr(ai_models, "_choices", lambda: {"briefing": [("openai", "gpt-5"), ("anthropic", "claude-sonnet-5-5")]})
    assert ai_models.resolve("briefing") == [SONNET]
    monkeypatch.setattr(ai_models, "_choices", lambda: {"briefing": [("openai", "gpt-5")]})
    assert ai_models.resolve("briefing") == [SOL, SONNET]


def test_gpt_5_4_is_priced_at_openai_s_published_rate():
    """$2.50 input and $15 output per million tokens (OpenAI model page)."""
    from services import ai_costs
    p_in, p_out, _ = ai_costs.price("openai", "gpt-5.4")
    gpt5_in, gpt5_out, _ = ai_costs.price("openai", "gpt-5")         # $1.25 / $10: the table's exchange rate
    assert abs(p_in / gpt5_in - 2.0) < 0.02 and abs(p_out / gpt5_out - 1.5) < 0.02   # the table's pence are rounded


def test_gpt_5_4_can_drive_tools_in_the_meeting_without_the_bm5_retry():
    """Its reasoning effort defaults to none, which tools need."""
    from services import executive_meeting_orchestrator as orch
    assert orch._openai_settings(0.4, 1200)("gpt-5.4", True)["reasoning_effort"] == "none"


# ------------------------------------------------------------ admin page ---

def test_the_admin_page_warns_about_a_choice_that_is_retiring(tmp_path, monkeypatch):
    from sqlalchemy import create_engine, text
    from sqlmodel import Session
    from services import ai_model_admin
    engine = create_engine("sqlite:///" + str(tmp_path / "a.sqlite"))
    with engine.begin() as c:
        c.execute(text("CREATE TABLE ai_model_choices (task TEXT PRIMARY KEY, chain TEXT, changed_by TEXT, "
                       "changed_at TEXT, previous TEXT)"))
        c.execute(text("INSERT INTO ai_model_choices VALUES ('briefing', '[{\"provider\": \"openai\", \"model\": \"gpt-5\"}]', "
                       "'mike', '2026-11-22', NULL)"))
    monkeypatch.setattr(ai_models, "_engine", lambda: engine)
    monkeypatch.setattr(ai_models, "_today", lambda: date(2026, 11, 25))
    ai_models.invalidate()
    try:
        with Session(engine) as s:
            rows = {r["task"]: r for r in ai_model_admin.overview(s)["tasks"]}
    finally:
        ai_models.invalidate()
    assert rows["briefing"]["retiring"] == [{"provider": "openai", "model": "gpt-5", "retires_on": "2026-12-11"}]
    assert rows["support"]["retiring"] == []
    gpt5 = next(o for o in rows["briefing"]["options"] if o["model"] == "gpt-5")
    assert gpt5["retires_on"] == "2026-12-11"
    g54 = next(o for o in rows["chat"]["options"] if o["model"] == "gpt-5.4")
    assert g54["retires_on"] is None and g54["usable"] is True


def test_the_admin_page_shows_the_warning():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2] / "frontend/client/src/pages/AdminAIModels.tsx").read_text()
    assert "retires_on" in src and "Stops working" in src


def test_a_retired_model_set_in_the_environment_is_dropped_too(monkeypatch):
    """EXECUTIVE_MEETING_AI_MODEL=gpt-5 replaces the meeting's first default;
    from 11 Dec the meeting goes straight to the next model."""
    monkeypatch.setattr(ai_models, "_choices", lambda: {})
    monkeypatch.setenv("EXECUTIVE_MEETING_AI_MODEL", "gpt-5")
    monkeypatch.setattr(ai_models, "_today", lambda: date(2026, 12, 10))
    assert ai_models.resolve("meeting") == [("openai", "gpt-5"), G54]
    monkeypatch.setattr(ai_models, "_today", lambda: date(2026, 12, 11))
    assert ai_models.resolve("meeting") == [G54]
