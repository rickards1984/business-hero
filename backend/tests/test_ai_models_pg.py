"""AI-1a on real PostgreSQL: migration 045's table, read by the switchboard.
Loopback harness only (scripts/rls-local.sh); synthetic rows, removed after."""
import json
import os
from urllib.parse import urlparse

import pytest

DATABASE_URL = os.getenv("RLS_LOCAL_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="RLS_LOCAL_DATABASE_URL is not set. A skip is not a pass.")
if DATABASE_URL and urlparse(DATABASE_URL).hostname not in ("127.0.0.1", "localhost", "::1"):
    raise RuntimeError("REFUSING TO RUN: loopback only")

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.exc import DBAPIError  # noqa: E402


@pytest.fixture
def pg(monkeypatch):
    from services import ai_models
    engine = create_engine(DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1))
    with engine.connect() as c:
        if not c.execute(text("SELECT to_regclass('public.ai_model_choices')")).scalar():
            pytest.skip("045 is not applied in the local harness")
    with engine.begin() as c:
        c.execute(text("DELETE FROM public.ai_model_choices"))
    monkeypatch.setattr(ai_models, "_engine", lambda: engine)
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.setenv(key, "test-key")
    ai_models.invalidate()
    yield engine, ai_models
    with engine.begin() as c:
        c.execute(text("DELETE FROM public.ai_model_choices"))
    ai_models.invalidate()
    engine.dispose()


def test_an_empty_table_changes_nothing(pg):
    _, m = pg
    assert m.resolve("chat_complex") == [("openai", "gpt-5")]


def test_a_saved_jsonb_choice_is_read(pg):
    engine, m = pg
    with engine.begin() as c:
        c.execute(text("INSERT INTO public.ai_model_choices (task, chain) VALUES ('chat_complex', CAST(:c AS jsonb))"),
                  {"c": json.dumps([{"provider": "anthropic", "model": "claude-opus-5-5"},
                                    {"provider": "openai", "model": "gpt-5"}])})
    m.invalidate()
    assert m.resolve("chat_complex") == [("anthropic", "claude-opus-5-5"), ("openai", "gpt-5")]


@pytest.mark.parametrize("task,chain", [
    ("Chat", '[{"provider": "openai", "model": "gpt-5"}]'),            # task names are lower case
    ("chat", '{"provider": "openai"}'),                                # not a list
    ("chat", "[]"),                                                    # empty
    ("chat", json.dumps([{"provider": "openai", "model": "m"}] * 7)),  # too long
])
def test_the_table_refuses_a_malformed_row(pg, task, chain):
    engine, _ = pg
    with pytest.raises(DBAPIError):
        with engine.begin() as c:
            c.execute(text("INSERT INTO public.ai_model_choices (task, chain) VALUES (:t, CAST(:c AS jsonb))"),
                      {"t": task, "c": chain})


def test_no_browser_role_can_reach_it(pg):
    engine, _ = pg
    with engine.connect() as c:
        grants = c.execute(text(
            "SELECT count(*) FROM information_schema.role_table_grants WHERE table_schema = 'public' "
            "AND table_name = 'ai_model_choices' AND grantee IN ('anon', 'authenticated', 'service_role')")).scalar()
        rls = c.execute(text("SELECT relrowsecurity FROM pg_class WHERE oid = 'public.ai_model_choices'::regclass")).scalar()
    assert grants == 0 and rls is True


def test_the_admin_page_saves_reverts_and_resets_on_postgres(pg):
    """AI-1c: jsonb writes, the advisory lock and Revert on the real table."""
    from sqlmodel import Session
    from services import ai_model_admin
    engine, m = pg
    mike = "11111111-1111-4111-8111-111111111111"
    with Session(engine) as s:
        ai_model_admin.choose(s, "chat_complex", [{"provider": "anthropic", "model": "claude-opus-5-5"},
                                                  {"provider": "openai", "model": "gpt-5"}], mike)
    assert m.resolve("chat_complex") == [("anthropic", "claude-opus-5-5"), ("openai", "gpt-5")]
    with Session(engine) as s:
        ai_model_admin.reset(s, "chat_complex", mike)
    assert m.resolve("chat_complex") == [("openai", "gpt-5")]
    with Session(engine) as s:
        ai_model_admin.revert(s, "chat_complex", mike)
        rows = {r["task"]: r for r in ai_model_admin.overview(s)["tasks"]}
    assert rows["chat_complex"]["choice"][0] == {"provider": "anthropic", "model": "claude-opus-5-5"}
    assert rows["chat_complex"]["changed_by"] == mike
