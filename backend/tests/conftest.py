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
