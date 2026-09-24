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

### The cancellation policy IS decided, and these tests assert it exactly

ENTITLEMENT-SPEC DECISION 3 (27 Aug 2026), confirmed by Mike 12 Sep 2026:

  - `plan_tier` is unchanged by any payment event. It records what was
    purchased. A cancellation is NOT a downgrade to `starter`.
  - `subscription_status` drives access: `past_due` keeps full access with a
    banner; `unpaid` / `canceled` are read-only (log in, view quotes,
    invoices and accounting, export quotes and invoices as PDF/CSV; no
    create, no edit, no AI, no outbound; the Twilio number releases).

Earlier versions of this file left the stored tier open as "P0-6". That was
a hedge the spec had already closed. What remains open is the read-only
RESOLVER and the Twilio release — see NOT_PINNED at the bottom.
"""

import asyncio
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import select

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


_UNSET = object()


class UnsupportedQuery(AssertionError):
    """The fake was asked something it cannot answer truthfully.

    Raised rather than guessed. Codex's review of the first version found the
    fake returning the fixture business for ANY non-stripe_events query,
    regardless of its predicates — which meant an implementation that looked
    up the wrong business still passed.
    """


class WebhookSession:
    """A session honest enough that a wrong implementation fails.

    It understands exactly two queries and refuses everything else:

      businesses     -> returns the fixture business ONLY if the query's bound
                        parameters actually match its customer or subscription
                        id. A lookup for an unknown customer returns None, as
                        the real table would.
      stripe_events  -> returns a recorded event only if it was COMMITTED and
                        its event_id matches. Uncommitted or rolled-back audit
                        rows are invisible, so "record without committing"
                        cannot pass for de-duplication.
    """

    def __init__(self, business):
        self.business = business
        self.committed_events = []
        self._uncommitted_events = []
        self.business_commits = 0
        self._pending_business = False

    @staticmethod
    def _evaluate(clause, row):
        """Evaluate the query's real WHERE clause against a candidate row.

        The first version compared the set of BOUND VALUES against the row's
        identifiers, which is not predicate evaluation: Codex demonstrated
        that `Business.name == customer_id`, and a correct customer with an
        incorrect subscription, both returned the fixture business. An
        implementation looking up the wrong COLUMN would have passed.

        This walks the clause instead, so the fake answers what was actually
        asked — and anything it does not understand raises rather than
        guessing.
        """
        from sqlalchemy.sql import operators
        from sqlalchemy.sql.elements import BinaryExpression, BooleanClauseList

        if isinstance(clause, BooleanClauseList):
            parts = [WebhookSession._evaluate(c, row) for c in clause.clauses]
            if clause.operator is operators.or_:
                return any(parts)
            if clause.operator is operators.and_:
                return all(parts)
            raise UnsupportedQuery(f"unsupported boolean operator: {clause.operator}")

        if isinstance(clause, BinaryExpression):
            if clause.operator is not operators.eq:
                raise UnsupportedQuery(
                    f"only equality is supported, got {clause.operator}")
            column = getattr(clause.left, "key", None)
            if column is None:
                raise UnsupportedQuery(f"cannot identify column in {clause}")
            if not hasattr(row, column):
                raise UnsupportedQuery(
                    f"query filters on {column!r}, which this row does not have")
            expected = getattr(clause.right, "value", _UNSET)
            if expected is _UNSET:
                raise UnsupportedQuery(f"cannot read bound value in {clause}")
            return getattr(row, column) == expected

        raise UnsupportedQuery(f"unsupported clause: {clause!r}")

    def exec(self, statement):
        entity = statement.column_descriptions[0]["entity"]
        where = statement.whereclause
        if where is None:
            raise UnsupportedQuery("an unfiltered query would match anything")

        if entity is StripeEvent:
            for recorded in self.committed_events:
                if self._evaluate(where, recorded):
                    return FakeResult(recorded)
            return FakeResult(None)

        if entity is Business:
            if self._evaluate(where, self.business):
                return FakeResult(self.business)
            return FakeResult(None)

        raise UnsupportedQuery(
            f"the webhook queried {entity!r}, which this fake cannot answer "
            "truthfully — extend the fake rather than loosening the test"
        )

    def add(self, obj):
        if isinstance(obj, StripeEvent):
            self._uncommitted_events.append(obj)
        else:
            self._pending_business = True

    def commit(self):
        if self._pending_business:
            self.business_commits += 1
            self._pending_business = False
        self.committed_events.extend(self._uncommitted_events)
        self._uncommitted_events = []

    def rollback(self):
        self._pending_business = False
        self._uncommitted_events = []


# DECISION 3 (ENTITLEMENT-SPEC, resolved 27 Aug 2026), confirmed by Mike
# 12 Sep 2026. The separation is the whole point of that decision:
#
#   | column                | meaning                | changed by a payment event? |
#   | plan_tier             | what was purchased     | NEVER                       |
#   | subscription_status   | whether it is paid for | yes — Stripe's field        |
#
# The damage the decision exists to prevent is concrete: writing a payment
# state into `plan_tier` destroys the record of what the customer bought, and
# restoring them after they pay becomes guesswork. "A payment blip would
# permanently lose the sale."
#
# Access by status, from the same decision:
#   active, trialing  -> full access to everything plan_tier includes
#   past_due          -> FULL access, plus a warning banner
#   unpaid, canceled  -> read-only
#
# READ-ONLY STATUSES THAT MUST NOT MOVE THE TIER.
READ_ONLY_STATUSES = ("unpaid", "canceled")
FULL_ACCESS_STATUSES = ("active", "trialing", "past_due")


def assert_tier_unchanged(business, before, what):
    """`plan_tier` must be EXACTLY what it was. No exceptions, no floor.

    Three earlier versions of this helper were all wrong, and the history is
    worth keeping because each failure was a different way of being vague:

      `!= "pro"`                  too weak — `business`, `None` or garbage passed
      `== "business"`             right shape, but asserted in only one test
      rank(after) <= rank(before) too weak — `business` -> `pro` is a descent
      `in {before, starter}`      too PERMISSIVE — it preserved a
                                  downgrade-to-starter option that DECISION 3
                                  had already ruled out on 27 Aug. That hedge
                                  was mine, not the spec's.

    DECISION 3 is decided: `plan_tier` is only ever changed by an actual plan
    change — an upgrade, a downgrade, or an admin acting deliberately. A
    payment event is none of those.
    """
    assert business.plan_tier == before, (
        f"{what}: plan_tier changed from {before!r} to {business.plan_tier!r}. "
        "DECISION 3: plan_tier records what was purchased and is NEVER "
        "changed by a payment event — subscription_status carries the payment "
        "state."
    )


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
                       item_period_end=None, subscription_period_end=None,
                       previous_attributes=None):
    """A Stripe subscription event, shaped as Stripe actually sends one.

    `previous_attributes` is Stripe's own account of WHAT CHANGED on an
    `.updated` event (`data.previous_attributes`). It is the only signal in
    the event that distinguishes "the customer changed plan" (`items` moved)
    from "the payment state changed" (`status` moved). DECISION 3 says the
    tier may follow the former and never the latter, so the tests below
    carry it explicitly rather than letting the handler infer intent from a
    price that happens to be on the object.
    """
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
    data = {"object": obj}
    if previous_attributes is not None:
        data["previous_attributes"] = previous_attributes
    return {"id": event_id, "type": event_type, "data": data}


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
def test_a_cancellation_leaves_the_tier_exactly_as_purchased(deliver):
    """DECISION 3: plan_tier is never changed by a payment event."""
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
    assert_tier_unchanged(business, "starter",
                          "cancellation carrying a Pro price")


@pytest.mark.xfail(
    strict=True,
    reason="BH-006 defect 1: same root cause, from a higher tier.",
)
def test_a_cancellation_leaves_a_business_tier_exactly_as_purchased(deliver):
    business = a_business(plan_tier="business")
    session = WebhookSession(business)

    deliver(
        subscription_event(
            "customer.subscription.deleted", PRICE_PRO,
            event_id="evt_cancel_2", status="canceled",
        ),
        session,
    )

    assert_tier_unchanged(business, "business",
                          "cancellation of a Business plan")


def test_a_cancellation_still_records_the_status_it_carries(deliver):
    """Closes the "just ignore every cancellation" bypass.

    Skipping the tier assignment is not enough: the cancellation still has to
    land its own facts, or the business stays `active` forever and access
    gating (RC1 P0-6) reads stale state. Not xfail — this passes today and
    must keep passing.
    """
    business = a_business(plan_tier="pro", subscription_status="active")
    session = WebhookSession(business)

    deliver(
        subscription_event(
            "customer.subscription.deleted", PRICE_PRO,
            event_id="evt_cancel_status", status="canceled",
        ),
        session,
    )

    assert business.subscription_status == "canceled", (
        "the cancellation was ignored wholesale — status was not updated"
    )
    # Deliberately NOT asserted: `is_active`. DECISION 3 separates
    # `is_active` (the admin's manual switch) from `subscription_status`
    # (Stripe's), and names the webhook writing one from the other as the
    # conflation it removes. An earlier version asserted `is_active is False`
    # here, which would have pinned that conflation in place. Codex caught it.


@pytest.mark.xfail(
    strict=True,
    reason="BH-006 defect 1: on a cancellation the handler still calls "
           "strip_plan_defaults with the CANCELLED plan's price, so genuine "
           "per-business feature exceptions can be stripped on the way out.",
)
def test_a_cancellation_does_not_strip_a_genuine_feature_exception(deliver):
    """A hand-granted exception must survive a cancellation.

    THE FIXTURE MATTERS, and the first version of this test got it wrong. It
    started from Pro with `receptionist: True` — but Pro GRANTS receptionist,
    so that flag is a redundant default and `strip_plan_defaults` removing it
    is exactly its documented job (`auth.py:330`). The test observed correct
    behaviour and called it a defect. Codex caught it.

    The real defect needs a flag that genuinely contradicts the business's own
    plan: a STARTER business hand-granted `receptionist: True`. Verified
    directly against the helper —

        strip_plan_defaults({"receptionist": True}, "starter") -> kept
        strip_plan_defaults({"receptionist": True}, "pro")     -> {}

    — so when a cancellation carrying a Pro price makes the handler strip
    against Pro rather than the business's actual tier, the genuine exception
    is destroyed and nothing announces it.

    Under DECISION 3 this follows directly: since `plan_tier` must not change
    on a payment event, the strip must run against the tier the business
    already has. Stripping against the event's price is the same mistake as
    writing the event's price into the tier, one layer down.
    """
    business = a_business(plan_tier="starter",
                          feature_flags={"receptionist": True})
    session = WebhookSession(business)

    deliver(
        subscription_event(
            "customer.subscription.deleted", PRICE_PRO,
            event_id="evt_cancel_flags", status="canceled",
        ),
        session,
    )

    assert business.feature_flags.get("receptionist") is True, (
        "a cancellation stripped a hand-granted feature exception"
    )


def test_a_genuine_plan_change_still_applies(deliver):
    """The guard that stops "ignore everything" passing. Passes today.

    DECISION 3 allows exactly one webhook-driven write to `plan_tier`: "when
    the subscription's PRICE changes — a genuine plan change". In Stripe's
    vocabulary that is an `.updated` event whose `previous_attributes`
    carries `items` — the customer moved from one price to another. That is
    what this fixture sends, and it is the only fixture in this file that
    expects the tier to move.

    Contrast `test_a_status_transition_does_not_move_the_tier` below: the
    same event type, a price that also differs from the stored tier, but
    `previous_attributes` says only `status` moved. There the tier must hold.
    """
    business = a_business(plan_tier="starter")
    session = WebhookSession(business)

    deliver(
        subscription_event(
            "customer.subscription.updated", PRICE_PRO,
            event_id="evt_upgrade_1", status="active",
            previous_attributes={
                "items": {"data": [{"price": {"id": PRICE_STARTER}}]},
            },
        ),
        session,
    )

    assert business.plan_tier == "pro"


# A status transition, as Stripe reports one: `previous_attributes.status`
# is set and `items` is not. The price on the object DIFFERS from the stored
# tier in every case — because Stripe sends the whole subscription on every
# event, and a stored tier can legitimately differ from the live price (an
# admin acting deliberately is one of DECISION 3's three permitted writers).
# A handler that "resolves the tier from the price" on every event, as the
# current one does, moves the tier on all three of these.
STATUS_TRANSITIONS = [
    pytest.param("active", "past_due", id="recovers_to_active"),
    pytest.param("trialing", "incomplete", id="trial_starts"),
    pytest.param("past_due", "active", id="falls_past_due"),
]


@pytest.mark.xfail(
    strict=True,
    reason="BH-006 defect 1, reached through a status transition: the "
           "handler resolves the tier from the object's price on every "
           "event, so a status-only update carrying a mismatched price "
           "rewrites the tier. Remove this marker in the commit that fixes "
           "defect 1.",
)
@pytest.mark.parametrize("status,previous_status", STATUS_TRANSITIONS)
def test_a_status_transition_does_not_move_the_tier(deliver, status,
                                                   previous_status):
    """DECISION 3: never "in response to ... a status transition"."""
    business = a_business(plan_tier="business",
                          subscription_status=previous_status)
    session = WebhookSession(business)

    deliver(
        subscription_event(
            "customer.subscription.updated", PRICE_PRO,
            event_id=f"evt_transition_{previous_status}_{status}",
            status=status,
            previous_attributes={"status": previous_status},
        ),
        session,
    )

    assert business.subscription_status == status
    assert_tier_unchanged(business, "business",
                          f"status transition {previous_status} -> {status}")


# ── Defect 5 — status must drive access, and past_due must keep it ──────────
#
# DECISION 3: `past_due` gets FULL access plus a banner. "Stripe is still
# retrying — the customer has usually not done anything wrong, and a card that
# expired on Tuesday should not take the receptionist off the phones on
# Wednesday."


class GateSession:
    """Enough session for `require_feature`, which is where access is decided.

    It answers the two queries that dependency makes: the platform_admins
    probe (raw SQL via .execute) and the Business lookup (via .exec).
    """

    def __init__(self, business, user_id, admin_user_ids=()):
        self.business = business
        self.user_id = user_id
        self.admin_user_ids = set(admin_user_ids)

    def execute(self, statement, params=None):
        """The platform_admins probe. Answered for the user actually asked
        about — a probe for someone else is not this user's admin status."""
        sql = str(statement).lower()
        if "platform_admins" not in sql:
            raise UnsupportedQuery(f"unexpected raw SQL in the gate: {sql[:160]}")
        asked_about = (params or {}).get("user_id", _UNSET)
        if asked_about is _UNSET:
            raise UnsupportedQuery("the admin probe did not bind :user_id")
        return FakeResult((1,) if asked_about in self.admin_user_ids else None)

    def exec(self, statement):
        """The Business lookup. Same predicate walk as WebhookSession, so a
        gate that looked up the wrong business, or no business, gets None."""
        entity = statement.column_descriptions[0]["entity"]
        if entity is not Business:
            raise UnsupportedQuery(f"the gate queried {entity!r}")
        where = statement.whereclause
        if where is None:
            raise UnsupportedQuery("an unfiltered gate lookup would match anything")
        if WebhookSession._evaluate(where, self.business):
            return FakeResult(self.business)
        return FakeResult(None)


def has_access(business, feature_name="email"):
    """Run the REAL access gate and report whether it permits the feature."""
    import auth
    from fastapi import HTTPException as _HTTPException

    dependency = auth.require_feature(feature_name)
    user_id = "user-synthetic"
    # `business.id` itself, not `str(business.id)`: the fake evaluates the
    # gate's `Business.id == …` predicate by strict equality against the
    # row, as the first version's `str()` would have silently failed.
    auth_ctx = {"user_id": user_id, "business_id": business.id}
    try:
        asyncio.run(dependency(auth_ctx=auth_ctx,
                               session=GateSession(business, user_id)))
        return True
    except _HTTPException:
        return False


def test_the_gate_fake_refuses_a_business_it_was_not_asked_about():
    """Self-check on GateSession: the fake must not hand the fixture business
    to a gate that asked for a different one. Without this, `has_access`
    could pass on a gate that never actually found the business."""
    business = a_business(plan_tier="pro", trial_ends_at=None)
    stranger = a_business(plan_tier="pro", trial_ends_at=None)
    session = GateSession(business, "user-synthetic",
                          admin_user_ids={"an-admin"})

    assert session.exec(
        select(Business).where(Business.id == business.id)).first() is business
    assert session.exec(
        select(Business).where(Business.id == stranger.id)).first() is None

    probe = text("SELECT 1 FROM platform_admins WHERE user_id = :user_id LIMIT 1")
    assert session.execute(probe, {"user_id": "an-admin"}).first() is not None
    assert session.execute(probe, {"user_id": "someone-else"}).first() is None


@pytest.mark.parametrize("status", FULL_ACCESS_STATUSES)
def test_the_status_the_event_carries_is_recorded(deliver, status):
    """Whatever Stripe says the status is, that is what we must store.

    Not xfail: this passes today. It is the half of DECISION 3 the handler
    already gets right, and it must survive the fix to the other half.
    """
    business = a_business(plan_tier="pro", subscription_status="active")
    session = WebhookSession(business)

    deliver(subscription_event(
        "customer.subscription.updated", PRICE_PRO,
        event_id=f"evt_status_{status}", status=status), session)

    assert business.subscription_status == status


@pytest.mark.xfail(
    strict=True,
    reason="BH-006 defect 1, reached through the read-only statuses: the "
           "tier is taken from the event's price regardless of status. Remove "
           "this marker in the commit that fixes defect 1.",
)
@pytest.mark.parametrize("status", READ_ONLY_STATUSES)
def test_a_read_only_status_does_not_move_the_tier(deliver, status):
    """DECISION 3: unpaid and canceled are read-only — a STATUS, not a tier."""
    business = a_business(plan_tier="business", subscription_status="active")
    session = WebhookSession(business)

    deliver(subscription_event(
        "customer.subscription.deleted", PRICE_PRO,
        event_id=f"evt_readonly_{status}", status=status), session)

    assert_tier_unchanged(business, "business", f"status {status!r}")
    assert business.subscription_status == status


def test_a_past_due_business_keeps_full_access(deliver):
    """The one that takes the receptionist off the phones.

    A paying Pro customer whose card expires. Stripe sends past_due and keeps
    retrying. Per DECISION 3 nothing should change for them except a banner.

    Today this is reachable on `email`, the single endpoint `require_feature`
    gates. Once P0-1 gates every paid feature, a past_due card takes the whole
    product offline for that customer — so this is an interaction between P0-1
    and P0-6, not a bug in either alone.
    """
    business = a_business(plan_tier="pro", subscription_status="active",
                          trial_ends_at=None)
    session = WebhookSession(business)

    assert has_access(business), "fixture must start with access"

    deliver(subscription_event(
        "customer.subscription.updated", PRICE_PRO,
        event_id="evt_past_due", status="past_due"), session)

    assert business.subscription_status == "past_due"
    assert has_access(business), (
        "a past_due business lost feature access. DECISION 3: past_due gets "
        "FULL access plus a banner — a card that expired on Tuesday must not "
        "take the receptionist off the phones on Wednesday."
    )


def test_a_cancelled_business_still_reaches_the_read_only_surface(deliver):
    """Read-only is not lockout.

    DECISION 3 is explicit: a cancelled customer can still log in, view quotes
    and invoices, and export them — VAT records are a six-year statutory
    obligation and GDPR Art. 20 portability does not lapse with payment.

    This asserts only the webhook's part: cancelling records the status and
    leaves the purchased tier intact, so a read-only resolver has something
    truthful to read. Enforcing read-only is P0-6's resolver, not the
    webhook's job — see NOT_PINNED.
    """
    business = a_business(plan_tier="business", subscription_status="active")
    session = WebhookSession(business)

    deliver(subscription_event(
        "customer.subscription.deleted", PRICE_BUSINESS,
        event_id="evt_readonly_surface", status="canceled"), session)

    assert business.subscription_status == "canceled"
    assert business.plan_tier == "business", (
        "the tier a read-only export must be scoped by was destroyed"
    )


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
    """The consequence that costs money.

    Upgrade to Pro, customer downgrades to Starter, Stripe redelivers the
    original event. Without de-duplication they are silently back on Pro while
    being billed for Starter.
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


def test_deduplication_must_key_on_the_event_id_alone(deliver):
    """Closes the "de-duplicate by payload or subscription+price" bypass.

    These two events are IDENTICAL apart from their event ids — same
    subscription, same price, same status. Both are real and both must apply.
    Keying de-duplication on anything but the event id suppresses the second.
    Passes today (nothing de-duplicates); it exists to constrain the fix.
    """
    business = a_business(plan_tier="starter")
    session = WebhookSession(business)

    for event_id in ("evt_same_a", "evt_same_b"):
        deliver(subscription_event(
            "customer.subscription.updated", PRICE_PRO,
            event_id=event_id, status="active"), session)

    assert session.business_commits == 2, (
        "two distinct events with identical payloads must both apply — "
        "de-duplication is keyed on something other than the event id"
    )


def test_two_different_events_both_apply(deliver):
    """De-duplication must not suppress everything. Passes today."""
    business = a_business(plan_tier="starter")
    session = WebhookSession(business)

    deliver(subscription_event("customer.subscription.updated", PRICE_PRO,
                               event_id="evt_one", status="active"), session)
    deliver(subscription_event("customer.subscription.updated", PRICE_BUSINESS,
                               event_id="evt_two", status="active"), session)

    assert business.plan_tier == "business"
    assert session.business_commits == 2


def test_an_event_for_an_unknown_customer_touches_nothing(deliver):
    """The fake answers the business lookup honestly, so this is meaningful.

    An event for a customer we do not have must not mutate the business we do
    have. Passes today; it exists so a fix cannot start writing to whichever
    business the query happens to return.
    """
    business = a_business(plan_tier="starter")
    session = WebhookSession(business)

    event = subscription_event(
        "customer.subscription.updated", PRICE_BUSINESS,
        event_id="evt_stranger", status="active",
    )
    event["data"]["object"]["customer"] = "cus_someone_else"
    event["data"]["object"]["id"] = "sub_someone_else"

    response = deliver(event, session)

    assert response.status_code == 200
    assert business.plan_tier == "starter", "an unrelated event mutated us"
    assert session.business_commits == 0


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
def test_an_event_without_a_period_preserves_the_exact_stored_value(deliver):
    """Exact equality, not merely non-null.

    The first version asserted only `is not None`, which an implementation
    could satisfy by writing any date at all.
    """
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
    assert int(business.current_period_end.timestamp()) == int(known.timestamp()), (
        "the stored period was replaced with a different date rather than "
        "left alone"
    )


def test_the_subscription_level_period_is_still_honoured(deliver):
    """Older API versions put it on the subscription. Both must work."""
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


# ─────────────────────────────────────────────────────────────────────────────
# NOT PINNED HERE — named so the implementer knows what is still open.
# From Codex's review of the first version of this file.
# ─────────────────────────────────────────────────────────────────────────────

NOT_PINNED = {
    "atomicity and durability": (
        "These tests use one in-process fake session. They do not prove the "
        "business write and the audit write are ATOMIC, that de-duplication "
        "survives a new process, or that two concurrent deliveries of the "
        "same event apply once. That needs a real database and is the single "
        "biggest gap — a fix passing this file could still lose or double an "
        "event under a crash or a race."
    ),
    "out-of-order delivery of a previously unseen event": (
        "The stale-replay test covers an event id already seen. An OLDER "
        "event arriving after a NEWER one, never seen before, is not covered "
        "— de-duplication by id will not help, and the handler has no event "
        "ordering metadata. Needs a product decision before it can be pinned."
    ),
    "cancel_at_period_end": (
        "A subscription scheduled to cancel at the end of the period is not a "
        "deleted one — the customer keeps access until the period ends. The "
        "handler stores the flag but nothing asserts the two are treated "
        "differently, so a fix could collapse them."
    ),
    "checkout.session.completed": (
        "Shares the same audit-after-commit problem and links the customer "
        "and subscription ids, but has no coverage here at all."
    ),
    "ENFORCEMENT of read-only (P0-6's resolver, not the webhook)": (
        "DECISION 3 is now fully pinned on the webhook side: the tier never "
        "moves and the status is recorded faithfully. What is NOT tested here "
        "is the resolver that turns `unpaid`/`canceled` into an actually "
        "read-only surface — refusing every create, edit, AI call and "
        "outbound send while still permitting login, viewing and export. That "
        "is P0-6 and it needs its own tests; a faithful status with no "
        "resolver behind it enforces nothing."
    ),
    "releasing the Twilio number on cancellation": (
        "DECISION 3 says the number releases when a business goes read-only. "
        "Nothing here or anywhere else tests that, and it is the one "
        "read-only consequence that costs real money every month if missed."
    ),
    "unknown price ids and empty items": (
        "An event whose price maps to no plan, or which carries no items at "
        "all. Today `plan_tier` is simply left alone, which is probably "
        "right, but nothing asserts it — so a fix that defaults an unknown "
        "price to a tier would pass. Cheap to pin once the policy is stated."
    ),
}


def test_the_not_pinned_registry_explains_itself():
    for area, reason in NOT_PINNED.items():
        assert len(reason) > 80, f"NOT_PINNED['{area}'] must say why"
