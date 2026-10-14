"""BH-014 Stage 1 contract; no network, no implementation.

run(session, *, now, silence_threshold) -> JSON-safe dict with counts
(businesses_checked, subscriptions_checked, divergences, errors), divergences
(list of {kind, business_id, subscription_id, ...}), errors and complete.
The service calls alert(result) once for any divergence/error, never writes.
Only absence of services.stripe_reconciliation may xfail. Remove the marker
when implementation begins; imports, assertions and runtime errors fail normally.
"""
import asyncio
import importlib
import importlib.util
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
import stripe
from sqlalchemy import create_engine, text
from sqlmodel import Session


class MissingReconciliation(AssertionError):
    """The sole permitted expected failure."""


pytestmark = pytest.mark.xfail(
    strict=True, raises=MissingReconciliation,
    reason="BH-014 Stage 1: module absent pending Mike's decisions/test review",
)
NOW = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)
END = int((NOW + timedelta(days=20)).timestamp())


def service():
    if importlib.util.find_spec("services.stripe_reconciliation") is None:
        raise MissingReconciliation("services.stripe_reconciliation is not implemented")
    return importlib.import_module("services.stripe_reconciliation")


def subscription(sid="sub_a", customer="cus_a", bid="a", **changes):
    data = dict(id=sid, customer=customer, metadata={"business_id": bid},
                status="active", items={"data": [
                    {"price": {"id": "price_pro"}, "current_period_end": END}]})
    data.update(changes)
    return stripe.StripeObject.construct_from(data, "sk_test_fake")


class Page:
    def __init__(self, rows):
        self.rows = rows

    def auto_paging_iter(self):
        yield from self.rows


@pytest.fixture
def rig(monkeypatch):
    mod = service()
    # Patch the official SDK, not an internal fetch helper. Any unplanned HTTP
    # request fails even if future code uses a different SDK resource.
    monkeypatch.setattr(stripe.http_client.RequestsClient, "request",
                        Mock(side_effect=AssertionError("Network forbidden")))
    rows = {"sub_a": subscription()}
    retrieve = Mock(side_effect=lambda sid, **kw: rows[sid])
    listing = Mock(side_effect=lambda **kw: Page([
        s for s in rows.values()
        if not kw.get("customer") or s.customer == kw["customer"]]))
    monkeypatch.setattr(stripe.Subscription, "retrieve", retrieve)
    monkeypatch.setattr(stripe.Subscription, "list", listing)
    import main
    resolver = Mock(side_effect=lambda price: {"price_pro": "pro"}.get(price))
    monkeypatch.setattr(main, "_resolve_plan_from_price", resolver)
    alert = Mock()
    monkeypatch.setattr(mod, "alert", alert)
    engine = create_engine("sqlite://")
    with Session(engine) as session:
        session.execute(text("""CREATE TABLE businesses (
            id TEXT PRIMARY KEY, stripe_subscription_id TEXT,
            stripe_customer_id TEXT, subscription_status TEXT,
            plan_tier TEXT, current_period_end TIMESTAMP)"""))
        session.execute(text("CREATE TABLE stripe_events (created_at TIMESTAMP)"))
        session.execute(text("INSERT INTO businesses VALUES "
                             "('a','sub_a','cus_a','active','pro',:end)"),
                        {"end": datetime.fromtimestamp(END, timezone.utc).replace(tzinfo=None)})
        session.execute(text("INSERT INTO stripe_events VALUES (:at)"),
                        {"at": NOW.replace(tzinfo=None)})
        session.commit()
        yield mod, session, rows, retrieve, listing, resolver, alert
    engine.dispose()


def run(rig):
    mod, session, *_ = rig
    before = session.execute(text("SELECT * FROM businesses ORDER BY id")).all()
    result = mod.run(session, now=NOW, silence_threshold=timedelta(hours=48))
    assert session.execute(text("SELECT * FROM businesses ORDER BY id")).all() == before
    import json
    json.dumps(result)  # structured log/result must serialize without custom encoder
    assert result["counts"]["divergences"] == len(result["divergences"])
    assert result["counts"]["errors"] == len(result["errors"])
    if result["divergences"] or result["errors"]:
        rig[-1].assert_called_once_with(result)
    else:
        rig[-1].assert_not_called()
    return result


def kinds(result):
    return {d["kind"] for d in result["divergences"]}


def test_all_in_agreement_no_alert_and_shared_resolver(rig):
    result = run(rig)
    assert result["complete"] is True
    assert result["counts"] == dict(businesses_checked=1, subscriptions_checked=1,
                                    divergences=0, errors=0)
    rig[-2].assert_any_call("price_pro")


@pytest.mark.parametrize("field,value,kind", [
    ("subscription_status", "canceled", "subscription_status"),
    ("plan_tier", "starter", "plan_tier"),
    ("current_period_end", "2026-10-15 12:00:00", "current_period_end"),
    ("current_period_end", None, "current_period_end"),
])
def test_each_field_divergence_reported_without_correction(rig, field, value, kind):
    rig[1].execute(text(f"UPDATE businesses SET {field}=:value"), {"value": value})
    result = run(rig)
    assert kinds(result) == {kind}
    assert result["divergences"][0]["business_id"] == "a"
    assert result["divergences"][0]["subscription_id"] == "sub_a"


def test_unknown_price_is_unresolved_not_a_guessed_plan(rig):
    rig[2]["sub_a"] = subscription(items={"data": [{"price": {"id": "unknown"},
                                                   "current_period_end": END}]})
    assert kinds(run(rig)) == {"unresolved_price"}


def test_missing_period_is_unresolved_not_a_null_correction(rig):
    rig[2]["sub_a"] = subscription(items={"data": [{"price": {"id": "price_pro"}}]})
    assert kinds(run(rig)) == {"unresolved_period"}


@pytest.mark.parametrize("hours,active,expected", [
    (49, True, True), (48, True, False), (47, True, False),
    (49, False, False), (None, True, True),
])
def test_webhook_silence_boundary_and_no_events(rig, hours, active, expected):
    rig[1].execute(text("DELETE FROM stripe_events"))
    if hours is not None:
        rig[1].execute(text("INSERT INTO stripe_events VALUES (:at)"),
                       {"at": (NOW - timedelta(hours=hours)).replace(tzinfo=None)})
    if not active:
        rig[2]["sub_a"] = subscription(status="canceled")
        rig[1].execute(text("UPDATE businesses SET subscription_status='canceled'"))
    assert ("webhook_silence" in kinds(run(rig))) is expected


def test_missing_stripe_subscription_is_orphan(rig):
    rig[3].side_effect = stripe.InvalidRequestError(
        "No such subscription", "id", code="resource_missing", http_status=404)
    rig[2].clear()
    assert "missing_subscription" in kinds(run(rig))


def test_unmapped_live_subscription_is_orphan(rig):
    rig[2]["sub_lost"] = subscription("sub_lost", "cus_lost", "missing")
    result = run(rig)
    assert "orphan_subscription" in kinds(result)
    assert any(d["subscription_id"] == "sub_lost" for d in result["divergences"])


def test_customer_only_business_is_checked(rig):
    rig[1].execute(text("UPDATE businesses SET stripe_subscription_id=NULL"))
    assert not kinds(run(rig))
    assert rig[4].called


def test_customer_without_subscription_is_reported(rig):
    rig[1].execute(text("UPDATE businesses SET stripe_subscription_id=NULL"))
    rig[2].clear()
    assert "missing_subscription" in kinds(run(rig))


def add_b(rig):
    rig[1].execute(text("INSERT INTO businesses SELECT 'b','sub_b','cus_b',"
                       "subscription_status,plan_tier,current_period_end FROM businesses WHERE id='a'"))
    rig[2]["sub_b"] = subscription("sub_b", "cus_b", "b")


def test_api_failure_does_not_stop_other_businesses(rig):
    add_b(rig)
    def retrieve(sid, **kw):
        if sid == "sub_a":
            raise stripe.APIConnectionError("offline")
        return rig[2][sid]
    rig[3].side_effect = retrieve
    rig[2]["sub_b"] = subscription("sub_b", "cus_b", "b", status="past_due")
    result = run(rig)
    assert result["complete"] is False
    assert any(e["business_id"] == "a" for e in result["errors"])
    assert any(d["business_id"] == "b" and d["kind"] == "subscription_status"
               for d in result["divergences"])


def test_tenant_conflict_never_compares_a_against_b(rig):
    add_b(rig)
    rig[1].execute(text("UPDATE businesses SET stripe_subscription_id='sub_b' WHERE id='a'"))
    rig[2]["sub_b"] = subscription("sub_b", "cus_b", "b", status="past_due")
    result = run(rig)
    assert "identity_conflict" in kinds(result)
    assert not any(d["business_id"] == "a" and d["kind"] in
                   {"subscription_status", "plan_tier", "current_period_end"}
                   for d in result["divergences"])


def test_inventory_failure_marks_run_incomplete(rig):
    rig[4].side_effect = stripe.APIConnectionError("offline")
    result = run(rig)
    assert result["complete"] is False
    assert result["errors"]


def test_scheduler_runs_in_worker_and_only_when_due(monkeypatch):
    mod = service()
    from services import briefing_scheduler as scheduler
    from contextlib import nullcontext
    import db
    import threading
    monkeypatch.setattr(scheduler, "_last_stripe_reconcile", None)
    monkeypatch.setattr(db, "get_session_context", lambda: nullcontext(object()))
    threads = []
    monkeypatch.setattr(mod, "run", lambda *a, **kw: threads.append(threading.get_ident()))
    async def exercise():
        await scheduler._reconcile_stripe_if_due()
        await scheduler._reconcile_stripe_if_due()
    asyncio.run(exercise())
    assert len(threads) == 1
    assert threads[0] != threading.get_ident()


def test_scheduler_failure_preserves_other_checks_and_next_tick(monkeypatch):
    service()
    from services import briefing_scheduler as scheduler
    calls = []
    async def fail():
        calls.append("stripe")
        raise RuntimeError("Stripe unavailable")
    async def record():
        calls.append("other")
    ticks = 0
    async def sleep(_):
        nonlocal ticks
        ticks += 1
        if ticks == 3:
            raise asyncio.CancelledError
    monkeypatch.setattr(scheduler.asyncio, "sleep", sleep)
    monkeypatch.setattr(scheduler, "_reconcile_stripe_if_due", fail)
    for name in ("_check_and_send_scheduled_messages", "_reconcile_metering_if_due",
                 "_deliver_metering_notices", "_check_and_prep_executive_meetings"):
        monkeypatch.setattr(scheduler, name, record)
    monkeypatch.setattr(scheduler, "_run_background_sync_jobs_nonblocking", lambda: None)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(scheduler._scheduler_loop())
    assert calls.count("stripe") == 2
    assert calls.count("other") == 8


def test_plan_item_after_addon_and_legacy_period(rig):
    rig[2]["sub_a"] = subscription(items={"data": [
        {"price": {"id": "addon"}, "current_period_end": END + 100},
        {"price": {"id": "price_pro"}, "current_period_end": END},
    ]})
    assert not kinds(run(rig))
    rig[-1].reset_mock()
    rig[2]["sub_a"] = subscription(
        items={"data": [{"price": {"id": "price_pro"}}]}, current_period_end=END)
    assert not kinds(run(rig))


def test_inventory_iterator_consumed_beyond_first_subscription(rig):
    consumed = []
    class MultiplePages:
        def auto_paging_iter(self):
            yield rig[2]["sub_a"]
            consumed.append("next_page")
            yield subscription("sub_lost", "cus_lost", "missing")
    rig[4].side_effect = lambda **kw: MultiplePages()
    result = run(rig)
    assert consumed
    assert any(d["kind"] == "orphan_subscription" and
               d["subscription_id"] == "sub_lost" for d in result["divergences"])


def test_no_stripe_identifiers_excluded(rig):
    rig[1].execute(text("INSERT INTO businesses VALUES "
                       "('local',NULL,NULL,NULL,'starter',NULL)"))
    assert run(rig)["counts"]["businesses_checked"] == 1
