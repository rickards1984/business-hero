"""BH-014 Stage 2: last attempt visibility, real admin gate, no network."""
from datetime import timedelta
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from test_stripe_reconciliation import NOW, run
from test_stripe_reconciliation import rig as rig


@pytest.fixture
def admin_client(monkeypatch):
    import auth
    import main
    from db import get_session
    from services import stripe_reconciliation as reconciliation
    monkeypatch.setattr(reconciliation, "_last_result", None)
    monkeypatch.setattr(auth, "is_platform_admin_user", lambda uid, session: uid == "admin")
    previous = main.app.dependency_overrides.copy()
    main.app.dependency_overrides[get_session] = lambda: object()
    main.app.dependency_overrides[auth.get_user_context_no_business] = lambda: {"user_id": "admin"}
    # No lifespan: never boot schedulers or create database tables.
    yield TestClient(main.app)
    main.app.dependency_overrides = previous


URL = "/v1/admin/stripe-reconciliation"


def test_normal_business_user_cannot_read_last_run(admin_client):
    import auth
    import main
    main.app.dependency_overrides[auth.get_user_context_no_business] = lambda: {"user_id": "business-owner"}
    assert admin_client.get(URL).status_code in (403, 404)


def test_admin_sees_not_run_since_restart(admin_client):
    response = admin_client.get(URL)
    assert response.status_code == 200
    assert response.json() == {"status": "not_run", "age_seconds": None, "result": None}
    assert admin_client.post(URL).status_code == 405


def test_last_result_has_age_completeness_and_each_divergence(admin_client, rig):
    from sqlalchemy import text
    rig[1].execute(text("UPDATE businesses SET subscription_status='past_due', plan_tier='starter'"))
    result = run(rig)
    payload = admin_client.get(URL).json()
    assert payload["status"] == "attention"
    assert payload["age_seconds"] >= 0
    assert payload["result"] == result
    assert result["complete"] is True
    assert {d["kind"] for d in result["divergences"]} == {"subscription_status", "plan_tier"}


@pytest.mark.parametrize("complete,errors", [(False, []), (True, [{"scope": "inventory", "code": "api_error", "business_id": None}])])
def test_incomplete_or_errored_result_is_never_healthy(admin_client, monkeypatch, complete, errors):
    from services import stripe_reconciliation as mod
    monkeypatch.setattr(mod, "_last_result", {
        "finished_at": NOW.isoformat(), "complete": complete, "errors": errors, "divergences": [],
    })
    assert admin_client.get(URL).json()["status"] == "incomplete"


def test_clean_result_becomes_stale_and_snapshot_is_defensive(rig):
    result = run(rig)
    mod = rig[0]
    assert mod.last_run(now=NOW)["status"] == "healthy"
    payload = mod.last_run(now=NOW + timedelta(hours=25))
    assert payload["status"] == "stale"
    assert payload["age_seconds"] == 90000
    result["complete"] = False
    payload["result"]["complete"] = False
    assert mod.last_run(now=NOW)["result"]["complete"] is True


def test_scheduler_session_failure_replaces_previous_green(monkeypatch):
    import asyncio
    import db
    from services import briefing_scheduler as scheduler, stripe_reconciliation as mod
    monkeypatch.setattr(scheduler, "_last_stripe_reconcile", None)
    monkeypatch.setattr(db, "get_session_context", Mock(side_effect=RuntimeError("secret database URL")))
    monkeypatch.setattr(mod, "alert", Mock())
    async def exercise():
        await scheduler._reconcile_stripe_if_due()
        await scheduler._stripe_reconcile_task
    asyncio.run(exercise())
    result = mod.last_run()
    assert result["status"] == "incomplete"
    assert result["result"]["errors"]
    assert "secret database URL" not in str(result)


def test_unplanned_sdk_request_is_refused(rig):
    import stripe
    with pytest.raises(AssertionError, match="Network forbidden"):
        stripe.Customer.retrieve("cus_unplanned", api_key="sk_test_fake")
    stripe.default_http_client.request_with_retries.assert_called_once()


def test_requests_use_configured_key_and_bounded_retries(rig, monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_reconciliation")
    run(rig)
    for method in (rig[3], rig[4]):
        for call in method.call_args_list:
            assert call.kwargs["api_key"] == "sk_test_reconciliation"
            assert call.kwargs["max_network_retries"] == 2
    # Constructing the installed SDK's default client does not send a request.
    from stripe._http_client import new_default_http_client
    client = new_default_http_client()
    assert 0 < client._timeout <= 80
    client.close()


def test_partial_inventory_keeps_findings_and_reports_failure(rig):
    from test_stripe_reconciliation import subscription
    class PartialPage:
        def auto_paging_iter(self):
            yield subscription("sub_lost", "cus_lost", "missing")
            raise RuntimeError("secret transport details")
    rig[4].side_effect = lambda **kw: PartialPage()
    result = run(rig)
    assert result["complete"] is False
    assert any(d["kind"] == "orphan_subscription" for d in result["divergences"])
    assert "secret transport details" not in str(result)


def test_customer_ambiguity_never_compares_arbitrary_subscription(rig):
    from sqlalchemy import text
    from test_stripe_reconciliation import subscription
    rig[1].execute(text("UPDATE businesses SET stripe_subscription_id=NULL"))
    rig[2]["sub_second"] = subscription("sub_second", "cus_a", "a", status="past_due")
    result = run(rig)
    assert {d["kind"] for d in result["divergences"]} == {"identity_conflict"}


def test_logging_failure_preserves_last_attempt(rig):
    from sqlalchemy import text
    rig[1].execute(text("UPDATE businesses SET subscription_status='past_due'"))
    rig[-1].side_effect = RuntimeError("broken handler")
    result = run(rig)
    assert rig[0].last_run(now=NOW)["result"] == result


def test_anonymous_user_cannot_read_last_run(admin_client):
    import auth
    import main
    main.app.dependency_overrides.pop(auth.get_user_context_no_business)
    assert admin_client.get(URL).status_code in (401, 403)
