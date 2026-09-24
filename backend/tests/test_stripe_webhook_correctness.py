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

### The xfail markers are gone, and that is the record of the fix

Every test here was written first, as `xfail(strict=True)`: while the defect
existed the suite was green and the test documented it, and the moment the
behaviour was fixed `strict=True` turned the unexpected pass into a FAILURE —
so the marker had to come off in the same commit as the fix. That is what
happened; `git log` for this file shows one commit per defect, each removing
its own markers next to the change that earned it.

Two things changed in this file DURING implementation rather than before it,
and both are called out where they happen rather than here:

  * `test_two_different_events_both_apply` asserted that an `.updated`
    carrying a price moves the tier — which is defect 1, and contradicted
    `test_a_status_transition_does_not_move_the_tier` in the same file. Its
    fixture now carries `previous_attributes`, as a real Stripe event does.
  * Two tests were ADDED because the fix would otherwise have introduced a
    worse bug than it closed: `.created` must set the tier, or no new
    subscriber ever gets one.

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
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import literal, text
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
    def _column_of(entity, side):
        """The real mapped column this expression refers to, or raise.

        THIS IS CODEX'S REMAINING BLOCKER, CLOSED. Review 2 accepted the file
        with one hole open: the evaluator read `.key` off whatever was on the
        left of the comparison, and `.key` is set by anything with a label —
        so `literal("wrong").label("stripe_customer_id")` claimed to be the
        `stripe_customer_id` column and matched. A lookup that never touched
        the table could pass for one that did.

        The fix is identity, not naming: resolve the expression against the
        SELECTED ENTITY's own mapper and require that it IS one of that
        entity's columns. A label, a literal, a function call, a column of
        some other table, or a name the entity does not map all raise.
        """
        from sqlalchemy import inspect as sa_inspect
        from sqlalchemy.schema import Column

        mapper = sa_inspect(entity)
        # `Business.stripe_customer_id` arrives as an InstrumentedAttribute;
        # `.expression` is the Column the mapper owns — but in an ORM query it
        # is an ANNOTATED copy, so `is` against the mapper's own object fails.
        # `_deannotate()` returns the original, which makes identity exact.
        expression = getattr(side, "expression", side)
        if not isinstance(expression, Column):
            raise UnsupportedQuery(
                f"{side!r} is not a table column, so it cannot be a column of "
                f"{entity.__name__} (a label over a literal lands here)")
        target = expression._deannotate()

        for attribute in mapper.column_attrs:
            for mapped in attribute.columns:
                if mapped._deannotate() is target:
                    return attribute.key
        raise UnsupportedQuery(
            f"{expression!r} is not a mapped column of {entity.__name__} — a "
            f"label, a literal or another table's column cannot stand in for "
            f"one")

    @staticmethod
    def _evaluate(clause, row, entity):
        """Evaluate the query's real WHERE clause against a candidate row.

        The first version compared the set of BOUND VALUES against the row's
        identifiers, which is not predicate evaluation: Codex demonstrated
        that `Business.name == customer_id`, and a correct customer with an
        incorrect subscription, both returned the fixture business. An
        implementation looking up the wrong COLUMN would have passed.

        This walks the clause instead, so the fake answers what was actually
        asked — and anything it does not understand raises rather than
        guessing. `entity` is the selected entity, so each side of a
        comparison can be checked for being one of ITS columns rather than
        merely having a matching name (`_column_of`).
        """
        from sqlalchemy.sql import operators
        from sqlalchemy.sql.elements import BinaryExpression, BooleanClauseList

        if isinstance(clause, BooleanClauseList):
            parts = [WebhookSession._evaluate(c, row, entity) for c in clause.clauses]
            if clause.operator is operators.or_:
                return any(parts)
            if clause.operator is operators.and_:
                return all(parts)
            raise UnsupportedQuery(f"unsupported boolean operator: {clause.operator}")

        if isinstance(clause, BinaryExpression):
            if clause.operator is not operators.eq:
                raise UnsupportedQuery(
                    f"only equality is supported, got {clause.operator}")
            column = WebhookSession._column_of(entity, clause.left)
            if not hasattr(row, column):
                raise UnsupportedQuery(
                    f"query filters on {column!r}, which this row does not have")
            expected = getattr(clause.right, "value", _UNSET)
            if expected is _UNSET:
                raise UnsupportedQuery(f"cannot read bound value in {clause}")
            actual = getattr(row, column)
            # Postgres coerces a string literal to uuid when comparing against a
            # uuid column, and the handler relies on it:
            # `checkout.session.completed` reads `metadata.business_id` as a
            # STRING and compares it to `Business.id`, a UUID. Python's `==`
            # says False, so a fake comparing strictly reported "no such
            # business" for a query the database answers — a false negative in
            # the fake, not a defect in the handler. Modelled explicitly rather
            # than loosening the comparison in general.
            if isinstance(actual, uuid.UUID) and isinstance(expected, str):
                return str(actual) == expected
            if isinstance(expected, uuid.UUID) and isinstance(actual, str):
                return actual == str(expected)
            return actual == expected

        raise UnsupportedQuery(f"unsupported clause: {clause!r}")

    def exec(self, statement):
        entity = statement.column_descriptions[0]["entity"]
        where = statement.whereclause
        if where is None:
            raise UnsupportedQuery("an unfiltered query would match anything")

        if entity is StripeEvent:
            for recorded in self.committed_events:
                if self._evaluate(where, recorded, entity):
                    return FakeResult(recorded)
            return FakeResult(None)

        if entity is Business:
            if self._evaluate(where, self.business, entity):
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
        if WebhookSession._evaluate(where, self.business, Business):
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


class TestTheFakeCannotBeFooledIntoMatching:
    """Codex's remaining blocker from review 2, now closed and proven closed.

    Review 2 shipped with one hole open and said so: the evaluator read `.key`
    off the left-hand side of the comparison, and `.key` is set by anything
    carrying a label — so a predicate that never touched the table could claim
    to be a column of it and match. Codex's own example is the first test
    below. `WebhookSession._column_of` now resolves each side against the
    selected entity's mapper and requires column IDENTITY, so a name is no
    longer enough.
    """

    def _business(self):
        return a_business(plan_tier="starter")

    def test_a_labelled_literal_claiming_a_column_name_is_refused(self):
        """`literal("wrong").label("stripe_customer_id")` — Codex's example,
        verbatim. It used to match; it must now raise."""
        session = WebhookSession(self._business())
        statement = select(Business).where(
            literal("cus_synthetic").label("stripe_customer_id") == "cus_synthetic")
        with pytest.raises(UnsupportedQuery, match="not a table column"):
            session.exec(statement)

    def test_another_tables_column_of_the_same_name_is_refused(self):
        """A query filtering on `StripeEvent.business_id` while selecting
        `Business` is not a lookup of the business, however familiar the name
        looks."""
        session = WebhookSession(self._business())
        statement = select(Business).where(
            StripeEvent.business_id == self._business().id)
        with pytest.raises(UnsupportedQuery, match="not a mapped column"):
            session.exec(statement)

    def test_a_real_column_still_matches(self):
        """The control. Tightening the fake must not make it refuse the real
        query the handler makes."""
        business = self._business()
        session = WebhookSession(business)
        found = session.exec(select(Business).where(
            (Business.stripe_customer_id == "cus_synthetic")
            | (Business.stripe_subscription_id == "sub_synthetic"))).first()
        assert found is business

    def test_the_wrong_column_still_fails_to_match(self):
        """Review 1's finding, still closed: a correct VALUE against the wrong
        COLUMN must not match."""
        business = self._business()
        session = WebhookSession(business)
        assert session.exec(select(Business).where(
            Business.name == "cus_synthetic")).first() is None


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


def test_a_replay_does_not_overwrite_state_that_moved_on(deliver):
    """The consequence that costs money.

    Upgrade to Pro, customer downgrades to Starter, Stripe redelivers the
    original event. Without de-duplication they are silently back on Pro while
    being billed for Starter.

    FIXTURE STRENGTHENED while fixing defect 1. The event carried no
    `previous_attributes`, so once defect 1 was fixed the first delivery no
    longer moved the tier either — and the test passed while proving nothing
    about de-duplication. It now sends a genuine plan change, so the first
    delivery really does set Pro and the replay really is the thing under
    test.
    """
    business = a_business(plan_tier="starter")
    session = WebhookSession(business)
    event = subscription_event(
        "customer.subscription.updated", PRICE_PRO,
        event_id="evt_stale", status="active",
        previous_attributes={"items": {"data": [{"price": {"id": PRICE_STARTER}}]}},
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
    """De-duplication must not suppress everything.

    FIXTURE CORRECTED DURING IMPLEMENTATION, and the correction matters
    enough to record here. Both events originally carried no
    `previous_attributes` at all, and the test asserted the tier ended at
    `business` — i.e. it asserted that an `.updated` moves the tier purely
    because it carries a price. That is defect 1, and it contradicted
    `test_a_status_transition_does_not_move_the_tier` fifteen lines earlier
    in the same file. A real Stripe `.updated` ALWAYS carries
    `previous_attributes` (it is the list of what changed), so an event
    without one is not a thing Stripe sends.

    Both events are now genuine plan changes, which keeps what this test is
    FOR — two distinct event ids must both apply, de-duplication must not
    swallow the second — and stops it asserting the defect.
    """
    business = a_business(plan_tier="starter")
    session = WebhookSession(business)

    deliver(subscription_event(
        "customer.subscription.updated", PRICE_PRO,
        event_id="evt_one", status="active",
        previous_attributes={"items": {"data": [{"price": {"id": PRICE_STARTER}}]}},
    ), session)
    deliver(subscription_event(
        "customer.subscription.updated", PRICE_BUSINESS,
        event_id="evt_two", status="active",
        previous_attributes={"items": {"data": [{"price": {"id": PRICE_PRO}}]}},
    ), session)

    assert business.plan_tier == "business"
    assert session.business_commits == 2


def test_a_new_subscription_sets_the_tier_it_was_bought_at(deliver):
    """`.created` is a purchase, and the only path that sets a new
    customer's tier.

    `checkout.session.completed` writes the Stripe ids and nothing else
    (`main.py`, the branch above this one), so if `.created` did not write
    `plan_tier` every new paying customer would sit on `starter` while being
    billed for Pro. Added during implementation: gating the tier behind
    `previous_attributes.items` alone would have caused exactly that, and
    nothing in the file would have failed.
    """
    business = a_business(plan_tier="starter", subscription_status=None)
    session = WebhookSession(business)

    deliver(subscription_event(
        "customer.subscription.created", PRICE_BUSINESS,
        event_id="evt_created", status="active"), session)

    assert business.plan_tier == "business", (
        "a brand-new subscription did not set the tier it was bought at"
    )
    assert business.subscription_status == "active"


def test_a_deleted_event_never_sets_the_tier_even_without_previous_attributes(deliver):
    """The companion to the above: `.created` may write the tier, `.deleted`
    may not, and neither carries `previous_attributes`. So the rule cannot be
    "no previous_attributes means treat it as a purchase" — it is keyed on
    the event type."""
    business = a_business(plan_tier="starter")
    session = WebhookSession(business)

    deliver(subscription_event(
        "customer.subscription.deleted", PRICE_BUSINESS,
        event_id="evt_deleted_no_prev", status="canceled"), session)

    assert_tier_unchanged(business, "starter", "cancellation with no previous_attributes")


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


# ── Codex's review of the implementation: seven more ways to get it wrong ────
#
# Every test below exists because the FIRST implementation passed this file
# while getting something material wrong. They are grouped by what was wrong.


class TestOnlyARealPriceChangeMovesTheTier:
    """`items` in previous_attributes is not proof the PRICE changed.

    Stripe puts `items` in `previous_attributes` on a billing-period renewal,
    and on a quantity or other item-attribute change. The first implementation
    treated any of those as a purchase, so a renewal carrying Pro would
    overwrite a tier an admin had deliberately set — and strip the feature
    exceptions against the wrong plan on the way through.
    """

    def test_a_renewal_carrying_the_same_price_does_not_move_the_tier(self, deliver):
        """The one that would have hurt: an admin set Business by hand, Stripe
        still bills Pro, and the monthly renewal quietly demotes them."""
        business = a_business(plan_tier="business", subscription_status="active",
                              feature_flags={"receptionist": True})
        session = WebhookSession(business)

        deliver(subscription_event(
            "customer.subscription.updated", PRICE_PRO,
            event_id="evt_renewal", status="active",
            previous_attributes={"items": {"data": [{"price": {"id": PRICE_PRO}}]}},
        ), session)

        assert_tier_unchanged(business, "business", "a renewal")
        assert business.feature_flags.get("receptionist") is True, (
            "a renewal stripped a hand-granted feature exception")

    def test_a_quantity_change_does_not_move_the_tier(self, deliver):
        business = a_business(plan_tier="business")
        session = WebhookSession(business)

        deliver(subscription_event(
            "customer.subscription.updated", PRICE_PRO,
            event_id="evt_quantity", status="active",
            previous_attributes={"items": {"data": [
                {"price": {"id": PRICE_PRO}, "quantity": 1}]}},
        ), session)

        assert_tier_unchanged(business, "business", "a quantity change")

    def test_a_real_price_change_still_moves_the_tier(self, deliver):
        """The control: prices differ, so this IS a purchase."""
        business = a_business(plan_tier="starter")
        session = WebhookSession(business)

        deliver(subscription_event(
            "customer.subscription.updated", PRICE_BUSINESS,
            event_id="evt_real_change", status="active",
            previous_attributes={"items": {"data": [{"price": {"id": PRICE_STARTER}}]}},
        ), session)

        assert business.plan_tier == "business"

    def test_an_update_whose_previous_price_is_unknown_does_not_move_the_tier(self, deliver):
        """Fails closed. If we cannot resolve what they were on, we cannot know
        the price changed, so we do not touch the record of what they bought."""
        business = a_business(plan_tier="business")
        session = WebhookSession(business)

        deliver(subscription_event(
            "customer.subscription.updated", PRICE_PRO,
            event_id="evt_unknown_prev", status="active",
            previous_attributes={"items": {"data": [{"price": {"id": "price_retired"}}]}},
        ), session)

        assert_tier_unchanged(business, "business", "an unresolvable previous price")


class TestTheTierIsReadFromTheRightSubscriptionItem:
    """`items.data[0]` is not necessarily the plan.

    A subscription can carry several items — a metered add-on, a seat charge —
    and the plan need not be first. The first implementation read `[0]`.
    """

    def _multi_item_event(self, event_id, plan_price, *, previous=None):
        event = subscription_event(
            "customer.subscription.created", plan_price,
            event_id=event_id, status="active", previous_attributes=previous)
        # An add-on whose price maps to no plan, placed FIRST.
        event["data"]["object"]["items"]["data"].insert(
            0, {"price": {"id": "price_metered_addon"}})
        return event

    def test_the_plan_item_is_found_behind_an_add_on(self, deliver):
        business = a_business(plan_tier="starter", subscription_status=None)
        session = WebhookSession(business)

        deliver(self._multi_item_event("evt_multi", PRICE_BUSINESS), session)

        assert business.plan_tier == "business", (
            "the tier was read from the add-on item instead of the plan item")

    def test_the_period_is_read_from_the_plan_item_not_the_first(self, deliver):
        plan_period = int(datetime(2026, 12, 1, tzinfo=timezone.utc).timestamp())
        event = self._multi_item_event("evt_multi_period", PRICE_BUSINESS)
        event["data"]["object"]["items"]["data"][0]["current_period_end"] = 1
        event["data"]["object"]["items"]["data"][1]["current_period_end"] = plan_period

        business = a_business(subscription_status=None)
        session = WebhookSession(business)
        deliver(event, session)

        assert int(business.current_period_end.timestamp()) == plan_period


class TestThePeriodIsStoredInUTC:
    """`datetime.fromtimestamp(x)` with no tzinfo is NAIVE LOCAL time.

    Under Europe/London that is an hour out for half the year. The original
    assertion round-tripped through `.timestamp()`, which re-applies the same
    local offset and hides it — so this asserts the WALL CLOCK, in UTC.
    """

    def test_the_stored_period_is_the_right_instant_in_utc(self, deliver):
        # 2026-07-01 00:00:00 UTC — inside British Summer Time, so a local
        # reading of this timestamp is 01:00, and the bug is visible.
        period_end = int(datetime(2026, 7, 1, tzinfo=timezone.utc).timestamp())
        business = a_business()
        session = WebhookSession(business)

        deliver(subscription_event(
            "customer.subscription.updated", PRICE_PRO,
            event_id="evt_utc", status="active", item_period_end=period_end), session)

        stored = business.current_period_end
        assert stored.tzinfo is not None, "the period was stored without a timezone"
        assert stored.astimezone(timezone.utc).replace(tzinfo=None) == \
            datetime(2026, 7, 1, 0, 0, 0), (
            f"stored {stored!r}; a naive local parse gives 01:00 in BST")

    @pytest.mark.parametrize("raw", [True, False, "not-a-number", "", 0, -1, 1.5, None])
    def test_a_nonsense_period_leaves_the_stored_value_alone(self, deliver, raw):
        """`int(True)` is 1, so a boolean used to become 1970-01-01, and a
        float was silently truncated."""
        known = datetime(2026, 11, 1, tzinfo=timezone.utc)
        business = a_business(current_period_end=known)
        session = WebhookSession(business)

        event = subscription_event(
            "customer.subscription.updated", PRICE_PRO,
            event_id=f"evt_bad_period_{raw!r}", status="active")
        event["data"]["object"]["items"]["data"][0]["current_period_end"] = raw

        deliver(event, session)

        assert business.current_period_end == known, (
            f"a period of {raw!r} overwrote a known date")


class TestCheckoutIsDeduplicatedToo:
    """`checkout.session.completed` used to commit ABOVE the de-duplication
    check, in its own transaction — so the handler's two headline claims were
    both false for it, and a replayed checkout re-applied."""

    def _checkout(self, event_id, business_id):
        return {
            "id": event_id,
            "type": "checkout.session.completed",
            "created": 1_780_000_000,
            "data": {"object": {
                "metadata": {"business_id": str(business_id)},
                "customer": "cus_checkout", "subscription": "sub_checkout",
            }},
        }

    def test_a_replayed_checkout_applies_once(self, deliver):
        business = a_business(stripe_customer_id=None, stripe_subscription_id=None)
        session = WebhookSession(business)
        event = self._checkout("evt_checkout", business.id)

        first = deliver(event, session)
        second = deliver(event, session)

        assert first.status_code == 200 and second.status_code == 200
        assert session.business_commits == 1, (
            f"the checkout applied {session.business_commits} times")
        assert business.stripe_customer_id == "cus_checkout"

    def test_a_checkout_is_recorded_in_the_audit_table(self, deliver):
        business = a_business(stripe_customer_id=None)
        session = WebhookSession(business)
        deliver(self._checkout("evt_checkout_audit", business.id), session)
        assert [e.event_id for e in session.committed_events] == ["evt_checkout_audit"]


class TestAStaleEventDoesNotResurrectAnOldPlan:
    """Stripe does not guarantee delivery ORDER, and de-duplication by event id
    cannot help with two DIFFERENT events arriving backwards."""

    def test_an_older_plan_change_arriving_late_is_ignored(self, deliver):
        business = a_business(plan_tier="starter")
        session = WebhookSession(business)

        newer = subscription_event(
            "customer.subscription.updated", PRICE_STARTER,
            event_id="evt_newer", status="active",
            previous_attributes={"items": {"data": [{"price": {"id": PRICE_BUSINESS}}]}})
        newer["created"] = 1_790_000_000
        deliver(newer, session)
        assert business.plan_tier == "starter"

        older = subscription_event(
            "customer.subscription.updated", PRICE_BUSINESS,
            event_id="evt_older", status="active",
            previous_attributes={"items": {"data": [{"price": {"id": PRICE_STARTER}}]}})
        older["created"] = 1_780_000_000          # a day earlier
        deliver(older, session)

        assert business.plan_tier == "starter", (
            "an out-of-order event resurrected a plan the customer had left")

    def test_a_stale_event_still_records_its_status(self, deliver):
        """Freshness gates the TIER only. Being slightly stale about a status is
        safer than ignoring a cancellation that arrived out of order."""
        business = a_business(plan_tier="pro", subscription_status="active")
        session = WebhookSession(business)

        newer = subscription_event("customer.subscription.updated", PRICE_PRO,
                                   event_id="evt_fresh", status="active")
        newer["created"] = 1_790_000_000
        deliver(newer, session)

        older = subscription_event("customer.subscription.deleted", PRICE_PRO,
                                   event_id="evt_stale_cancel", status="canceled")
        older["created"] = 1_780_000_000
        deliver(older, session)

        assert business.subscription_status == "canceled"
        assert_tier_unchanged(business, "pro", "a stale cancellation")


class TestATransientFailureIsRetryable:
    """The first implementation caught `Exception` around the commit and
    returned 200, so a transient database error threw the event away while
    telling Stripe it had been processed — a silent webhook outage, which this
    product has already had once for two months."""

    class _FailingSession(WebhookSession):
        def __init__(self, business, error):
            super().__init__(business)
            self._error = error

        def commit(self):
            raise self._error

    def test_a_database_error_returns_5xx_so_stripe_retries(self, deliver):
        from sqlalchemy.exc import OperationalError
        business = a_business(plan_tier="starter")
        session = self._FailingSession(
            business, OperationalError("SELECT 1", {}, Exception("connection lost")))

        response = deliver(subscription_event(
            "customer.subscription.updated", PRICE_PRO,
            event_id="evt_db_down", status="active"), session)

        assert response.status_code >= 500, (
            "a failed commit reported success; Stripe will never retry it")

    def test_a_duplicate_conflict_returns_200(self, deliver):
        """The one failure that IS success: the other transaction applied it."""
        from sqlalchemy.exc import IntegrityError
        business = a_business(plan_tier="starter")
        session = self._FailingSession(
            business,
            IntegrityError("INSERT", {}, Exception("duplicate key value")))

        response = deliver(subscription_event(
            "customer.subscription.updated", PRICE_PRO,
            event_id="evt_race", status="active"), session)

        assert response.status_code == 200


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
    "ENFORCEMENT of read-only — CLOSED, in its own file": (
        "This entry asked for the resolver that turns `unpaid`/`canceled` into "
        "an actually read-only surface. It exists: `auth.resolve_access_level` "
        "plus `auth.enforce_read_only`, tested in "
        "backend/tests/test_readonly_resolver.py — refusals for every AI and "
        "outbound feature and every mutating HTTP method, permissions for "
        "views, the PDF export and the billing paths. What remains untested "
        "there is HTTP-level: those tests call the real dependency directly, "
        "so FastAPI routing and a real JWT are not exercised."
    ),
    "releasing the Twilio number on cancellation": (
        "DECISION 3 says the number releases when a business goes read-only. "
        "Nothing here or anywhere else tests that, and it is the one "
        "read-only consequence that costs real money every month if missed. "
        "Deliberately deferred to its own ticket (Mike, 24 Sep 2026), so it is "
        "STILL OPEN: a cancelled business keeps its number and its monthly "
        "cost until that ticket lands."
    ),
    "the stale `is_active` rows this fix leaves behind": (
        "The old handler wrote `is_active = status in ('active','trialing')`, "
        "so every business that has ever been past_due, unpaid or canceled "
        "carries a False this code can no longer distinguish from a deliberate "
        "admin suspension. The resolver keeps admin suspension absolute, so "
        "those rows stay suspended until repaired — audits/BH-006-PROD-RUNBOOK.md, "
        "which is prod SQL and therefore Mike's to run. Nothing in this suite "
        "can detect that the repair has not happened."
    ),
    "unknown price ids and empty items": (
        "An event whose price maps to no plan, or which carries no items at "
        "all. `plan_tier` is left alone — `_resolve_plan_from_price` returns "
        "None and the write is behind `if plan_tier:` — but nothing here "
        "asserts it, so a change that defaulted an unknown price to a tier "
        "would still pass. Cheap to pin once the policy is stated."
    ),
    "the fake's column-identity check is exact; three other holes are NOT": (
        "Codex's review-2 blocker is closed: `_column_of` requires column "
        "IDENTITY against the selected entity's mapper, so a labelled literal "
        "or another table's column raises instead of matching "
        "(TestTheFakeCannotBeFooledIntoMatching). Reviewing the implementation, "
        "Codex then demonstrated three holes that remain OPEN, listed here "
        "rather than fixed because each needs the fake to model more of "
        "SQLAlchemy than a fake should:\n"
        "  - a callable `bindparam` whose `.value` matches while its "
        "`effective_value` is a different customer: the evaluator reads "
        "`.value`\n"
        "  - `.limit(0)` returns the business: query modifiers are ignored\n"
        "  - `rollback()` clears the fake's bookkeeping but not mutations "
        "already made to the shared Business object, so a handler that wrote "
        "the business and then rolled back looks the same as one that did not\n"
        "The handler uses none of those shapes. They are false-GREEN routes "
        "for a hypothetical wrong implementation, not defects in this one, and "
        "the real answer to all three is the executed-against-Postgres suite "
        "the atomicity entry above asks for."
    ),
    "endpoints a read-only business can still reach": (
        "Enforcement covers the three shared context dependencies, the feature "
        "gate, and the four self-authenticating paths (assistant chat, TTS, "
        "realtime voice, inbound receptionist call). NOT covered, and "
        "deliberately: OAuth callbacks (a connection already begun may finish; "
        "USING it is refused by the feature gate) and provider callbacks "
        "arriving with a valid provider signature (Twilio media-stream "
        "continuation, WhatsApp actions). Those need per-path decisions about "
        "what a half-finished external interaction should do, which is a "
        "product question, not a gate."
    ),
    "the Twilio media-stream continuation and WhatsApp callbacks": (
        "The inbound call is refused now, so a read-only business's "
        "receptionist stops answering. But a call already in progress, and a "
        "WhatsApp callback carrying a valid signature, are not re-checked "
        "mid-flow. Low value to close before the number-release ticket lands, "
        "since that removes the number and with it the inbound path entirely."
    ),
}


def test_the_not_pinned_registry_explains_itself():
    for area, reason in NOT_PINNED.items():
        assert len(reason) > 80, f"NOT_PINNED['{area}'] must say why"
