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


# The cancellation invariant. `beta` is deliberately absent from the ladder:
# it is not a paid rung and a cancellation should never produce it.
TIER_RANK = {"starter": 0, "pro": 1, "business": 2}
CANCELLED_FLOOR = "starter"


def assert_tier_not_taken_from_the_event(business, before, what):
    """After a cancellation the tier must be the one we had, or the floor.

    Getting this invariant right took two attempts and both failures are
    instructive:

      `!= "pro"`            too weak — `business`, `None` or garbage passed.
      `== "business"`       too strong — it forbade downgrading to starter,
                            silently choosing the policy the file claimed to
                            leave open.
      rank(after) <= rank(before)
                            still too weak — `business` -> `pro` is a
                            *descent* in rank, so the tier being rewritten
                            from the cancelled subscription's price passed.

    What is actually wrong is narrower than any of those: the tier must not be
    DERIVED FROM THE EVENT at all. So the only acceptable outcomes are the
    tier we already had, or the defined cancelled floor. Which of those two is
    right remains Mike's decision (RC1 P0-6); this permits either and forbids
    "whatever price the cancellation happened to carry".
    """
    after = business.plan_tier
    allowed = {before, CANCELLED_FLOOR}
    assert after in allowed, (
        f"{what}: plan_tier became {after!r}. A cancellation may leave the "
        f"tier at {before!r} or drop it to {CANCELLED_FLOOR!r} — anything "
        f"else means it was taken from the event's price."
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
def test_a_cancellation_does_not_take_the_tier_from_the_event(deliver):
    """Unchanged or dropped to the floor both pass; the event's price fails."""
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
    assert_tier_not_taken_from_the_event(
        business, "starter", "cancellation carrying a Pro price")


@pytest.mark.xfail(
    strict=True,
    reason="BH-006 defect 1: same root cause, from a higher tier.",
)
def test_a_cancellation_does_not_take_the_tier_from_the_event_at_business(deliver):
    business = a_business(plan_tier="business")
    session = WebhookSession(business)

    deliver(
        subscription_event(
            "customer.subscription.deleted", PRICE_PRO,
            event_id="evt_cancel_2", status="canceled",
        ),
        session,
    )

    assert_tier_not_taken_from_the_event(
        business, "business", "cancellation of a Business plan")


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
    assert business.is_active is False


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


def test_a_genuine_upgrade_still_applies(deliver):
    """The guard that stops "ignore everything" passing. Passes today."""
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
    "the cancelled-state ACCESS policy": (
        "docs/RC1_SCOPE.md:86 already specifies it — past_due keeps access, "
        "unpaid and canceled go read-only. What is undecided is the stored "
        "TIER on cancellation, not access. The first version of this file "
        "wrongly implied the whole policy was open."
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
