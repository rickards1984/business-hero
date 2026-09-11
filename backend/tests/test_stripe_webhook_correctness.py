"""BH-006 — the Stripe subscription webhook: three defects, encoded as tests.

READ THIS BEFORE THE CODE. These tests are written FIRST, per `AGENTS.md` §2:
money is RED, so the failing test that encodes correct behaviour comes first
and Mike reviews the test, not the implementation.

All three defects are in one handler, `stripe_webhook` in `backend/main.py`
(~:989-1023), and all three are the same class of bug: the handler reads a
field off the event and writes it to the business without asking whether this
event means what the field says.

  1. `customer.subscription.deleted` is handled identically to `.created` and
     `.updated` (`main.py:989`), and the tier is taken from whatever price the
     event carries (`:1001-1004`). A cancellation carrying an old Pro price
     therefore SETS the business to Pro. Cancelling upgrades you.

  2. The `StripeEvent` audit row is written at `:1026`, AFTER the business
     mutation has already been committed at `:1023`, and nothing ever reads it
     back to ask "have I seen this event?". A redelivered event — which Stripe
     does routinely, and did for two months in 2026 — applies twice.

  3. `current_period_end` is read from the subscription object (`:1008`).
     In current Stripe API versions it lives on the subscription ITEM,
     `items.data[0].current_period_end`. The top-level read yields None, so
     every subscription event WIPES the stored billing period.

### Why these are marked xfail(strict=True) rather than left red

The pre-push hook refuses a red tree, so a genuinely failing test cannot be
pushed or reviewed. `xfail(strict=True)` keeps the gate honest in both
directions: while the defect exists the suite is green and the test documents
it; the moment the behaviour is fixed the test XPASSes, and `strict=True`
turns an unexpected pass into a FAILURE.

**That is deliberate.** The implementer cannot quietly satisfy these tests —
they must delete the `xfail` marker in the same commit that fixes the
behaviour, which is the point at which a reviewer sees both.

### What these tests deliberately do NOT decide

Test 1 asserts only that a cancellation must not RAISE the tier. Whether a
cancelled business should drop to `starter`, keep its tier with
`subscription_status='canceled'` doing the gating, or something else, is a
product decision (RC1 P0-6) and is not encoded here. The minimum correct
property is asserted; the policy is left to Mike.
"""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import main
from db import get_session
from models import Business, StripeEvent

PRICE_STARTER = "price_test_starter"
PRICE_PRO = "price_test_pro"
PRICE_BUSINESS = "price_test_business"

STRIPE_ENV = {
    "STRIPE_SECRET_KEY": "sk_test_not_a_real_key",
    "STRIPE_WEBHOOK_SECRET": "whsec_test_not_a_real_secret",
    "APP_BASE_URL": "https://example.invalid",
    "STRIPE_PRICE_STARTER": PRICE_STARTER,
    "STRIPE_PRICE_PRO": PRICE_PRO,
    "STRIPE_PRICE_BUSINESS": PRICE_BUSINESS,
}


class FakeResult:
    def __init__(self, row=None):
        self._row = row

    def first(self):
        return self._row


class WebhookSession:
    """Enough session for the webhook, and honest about what it is asked.

    It answers the StripeEvent lookup truthfully — if an event id has already
    been recorded, a query for it finds it. The current handler never asks;
    a correct one must, and this session lets it.
    """

    def __init__(self, business):
        self.business = business
        self.recorded_events = []
        self.business_commits = 0
        self._pending_business = False

    def exec(self, statement):
        sql = str(statement).lower()
        if "stripe_events" in sql:
            wanted = None
            params = getattr(statement, "compile", lambda: None)()
            if params is not None:
                wanted = getattr(params, "params", {}).get("event_id_1")
            for recorded in self.recorded_events:
                if wanted is None or recorded.event_id == wanted:
                    return FakeResult(recorded)
            return FakeResult(None)
        return FakeResult(self.business)

    def add(self, obj):
        if isinstance(obj, StripeEvent):
            self.recorded_events.append(obj)
        else:
            self._pending_business = True

    def commit(self):
        if self._pending_business:
            self.business_commits += 1
            self._pending_business = False

    def rollback(self):
        self._pending_business = False


def a_business(**overrides):
    fields = dict(
        name="Synthetic Ltd",
        plan_tier="starter",
        subscription_status="active",
        stripe_customer_id="cus_synthetic",
        stripe_subscription_id="sub_synthetic",
        feature_flags={},
        is_active=True,
    )
    fields.update(overrides)
    return Business(**fields)


def subscription_event(event_type, price_id, *, event_id, status,
                       item_period_end=None, subscription_period_end=None):
    """A Stripe subscription event, shaped as Stripe actually sends one."""
    item = {"price": {"id": price_id}}
    if item_period_end is not None:
        item["current_period_end"] = item_period_end
    obj = {
        "id": "sub_synthetic",
        "customer": "cus_synthetic",
        "status": status,
        "cancel_at_period_end": False,
        "items": {"data": [item]},
    }
    if subscription_period_end is not None:
        obj["current_period_end"] = subscription_period_end
    return {"id": event_id, "type": event_type, "data": {"object": obj}}


@pytest.fixture
def deliver(monkeypatch):
    """Deliver an event to the real endpoint, with signature check stubbed."""
    for key, value in STRIPE_ENV.items():
        monkeypatch.setenv(key, value)

    state = {"event": None}
    monkeypatch.setattr(
        main.stripe.Webhook, "construct_event",
        lambda payload, sig, secret: state["event"],
    )

    def _deliver(event, session):
        state["event"] = event
        main.app.dependency_overrides[get_session] = lambda: session
        try:
            client = TestClient(main.app)
            return client.post(
                "/v1/billing/webhook",
                content=b"{}",
                headers={"stripe-signature": "t=0,v1=stub"},
            )
        finally:
            main.app.dependency_overrides.pop(get_session, None)

    return _deliver


# ── Defect 1 — a cancellation must not raise the tier ────────────────────────

@pytest.mark.xfail(
    strict=True,
    reason="BH-006 defect 1: main.py:989 handles .deleted like .updated and "
           "takes the tier from the event's price, so cancelling a Pro "
           "subscription SETS plan_tier='pro'. Remove this marker in the "
           "commit that fixes it.",
)
def test_a_cancellation_carrying_a_pro_price_must_not_upgrade_the_tier(deliver):
    business = a_business(plan_tier="starter")
    session = WebhookSession(business)

    response = deliver(
        subscription_event(
            "customer.subscription.deleted", PRICE_PRO,
            event_id="evt_cancel_1", status="canceled",
        ),
        session,
    )

    assert response.status_code == 200
    assert business.plan_tier != "pro", (
        "a cancellation carrying the old Pro price upgraded the business to Pro"
    )


@pytest.mark.xfail(
    strict=True,
    reason="BH-006 defect 1: same root cause — a cancellation must not change "
           "the tier at all on the strength of the price it carries.",
)
def test_a_cancellation_does_not_rewrite_the_tier_from_the_events_price(deliver):
    business = a_business(plan_tier="business")
    session = WebhookSession(business)

    deliver(
        subscription_event(
            "customer.subscription.deleted", PRICE_PRO,
            event_id="evt_cancel_2", status="canceled",
        ),
        session,
    )

    assert business.plan_tier == "business", (
        "a cancellation carrying a Pro price rewrote the tier of a Business "
        "customer"
    )


def test_a_genuine_upgrade_still_applies(deliver):
    """The guard must not break the case the handler exists for.

    Not xfail: this passes today and must keep passing.
    """
    business = a_business(plan_tier="starter")
    session = WebhookSession(business)

    deliver(
        subscription_event(
            "customer.subscription.updated", PRICE_PRO,
            event_id="evt_upgrade_1", status="active",
        ),
        session,
    )

    assert business.plan_tier == "pro"
    assert business.is_active is True


# ── Defect 2 — a redelivered event must apply once ───────────────────────────

@pytest.mark.xfail(
    strict=True,
    reason="BH-006 defect 2: the StripeEvent row is written at main.py:1026, "
           "after the business commit at :1023, and is never read back. A "
           "redelivered event applies twice. Remove this marker in the commit "
           "that fixes it.",
)
def test_a_redelivered_event_applies_exactly_once(deliver):
    business = a_business(plan_tier="starter")
    session = WebhookSession(business)
    event = subscription_event(
        "customer.subscription.updated", PRICE_PRO,
        event_id="evt_replayed", status="active",
    )

    first = deliver(event, session)
    second = deliver(event, session)

    assert first.status_code == 200
    assert second.status_code == 200, "a replay must be accepted, not errored"
    assert session.business_commits == 1, (
        f"the same event applied {session.business_commits} times; Stripe "
        "redelivers routinely and did so for two months in 2026"
    )


@pytest.mark.xfail(
    strict=True,
    reason="BH-006 defect 2: with no de-duplication, a stale replay overwrites "
           "state that moved on after the first delivery.",
)
def test_a_replay_does_not_overwrite_state_that_moved_on(deliver):
    """The consequence that actually costs money.

    First delivery upgrades to Pro. The customer then downgrades to Starter.
    Stripe redelivers the original event. Without de-duplication the stale
    event silently puts them back on Pro — and they are billed for Starter.
    """
    business = a_business(plan_tier="starter")
    session = WebhookSession(business)
    event = subscription_event(
        "customer.subscription.updated", PRICE_PRO,
        event_id="evt_stale", status="active",
    )

    deliver(event, session)
    business.plan_tier = "starter"          # a later, legitimate downgrade
    deliver(event, session)                 # Stripe redelivers the old event

    assert business.plan_tier == "starter", (
        "a redelivered stale event resurrected a plan the customer had left"
    )


def test_two_different_events_both_apply(deliver):
    """De-duplication must key on the event id, not suppress everything.

    Not xfail: this passes today and must keep passing.
    """
    business = a_business(plan_tier="starter")
    session = WebhookSession(business)

    deliver(subscription_event("customer.subscription.updated", PRICE_PRO,
                               event_id="evt_one", status="active"), session)
    deliver(subscription_event("customer.subscription.updated", PRICE_BUSINESS,
                               event_id="evt_two", status="active"), session)

    assert business.plan_tier == "business"
    assert session.business_commits == 2


# ── Defect 3 — current_period_end lives on the item ──────────────────────────

@pytest.mark.xfail(
    strict=True,
    reason="BH-006 defect 3: main.py:1008 reads current_period_end from the "
           "subscription object. Current Stripe API versions put it on the "
           "item, items.data[0].current_period_end, so the read yields None "
           "and every event wipes the stored period. Remove this marker in "
           "the commit that fixes it.",
)
def test_current_period_end_is_read_from_the_subscription_item(deliver):
    period_end = int(datetime(2026, 12, 1, tzinfo=timezone.utc).timestamp())
    business = a_business()
    session = WebhookSession(business)

    deliver(
        subscription_event(
            "customer.subscription.updated", PRICE_PRO,
            event_id="evt_period_1", status="active",
            item_period_end=period_end,
        ),
        session,
    )

    assert business.current_period_end is not None, (
        "current_period_end was read from the subscription object, which no "
        "longer carries it, so the stored billing period was wiped"
    )
    assert int(business.current_period_end.timestamp()) == period_end


@pytest.mark.xfail(
    strict=True,
    reason="BH-006 defect 3: an event carrying no period anywhere must leave "
           "the stored value alone rather than nulling it.",
)
def test_an_event_without_a_period_does_not_wipe_the_stored_one(deliver):
    known = datetime(2026, 11, 1, tzinfo=timezone.utc)
    business = a_business(current_period_end=known)
    session = WebhookSession(business)

    deliver(
        subscription_event(
            "customer.subscription.updated", PRICE_PRO,
            event_id="evt_period_2", status="active",
        ),
        session,
    )

    assert business.current_period_end is not None, (
        "an event with no period field nulled the period we already knew"
    )


def test_the_subscription_level_period_is_still_honoured(deliver):
    """Older API versions put it on the subscription. Both must work.

    Not xfail: this passes today and must keep passing.
    """
    period_end = int(datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp())
    business = a_business()
    session = WebhookSession(business)

    deliver(
        subscription_event(
            "customer.subscription.updated", PRICE_PRO,
            event_id="evt_period_3", status="active",
            subscription_period_end=period_end,
        ),
        session,
    )

    assert business.current_period_end is not None
    assert int(business.current_period_end.timestamp()) == period_end
