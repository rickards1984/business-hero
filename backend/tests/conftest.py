"""Shared test hygiene."""
import sys

import pytest


@pytest.fixture(autouse=True)
def _fresh_ai_failover_state():
    """OUT-19 H keeps "this provider just failed" per process; one test's
    failure must never make the next test skip a provider."""
    router = sys.modules.get("services.ai_router")
    if router:
        router.reset_breakers()
    yield
    router = sys.modules.get("services.ai_router")
    if router:
        router.reset_breakers()


@pytest.fixture(autouse=True)
def _models_on_a_fixed_date(monkeypatch):
    """HK-3: a model OpenAI retires is refused from its shutdown date. Tests
    use gpt-5 and others as sample data, so they run on a fixed date before
    any shutdown; otherwise they would all fail by themselves on 11 Dec 2026.
    The retirement tests set their own dates."""
    from datetime import date
    from services import ai_models
    monkeypatch.setattr(ai_models, "_today", lambda: date(2026, 11, 25))
