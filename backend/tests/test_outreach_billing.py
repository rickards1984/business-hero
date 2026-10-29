"""OUT-19 F — Stripe for extra brands and top-ups (docs/OUT-19-TICKET.md, F).
RED: money.

Mike, 29 Oct 2026 ("Go with recommendations ... they also protect expenditure
vs income"):
  1. a new paid brand is added to the subscription and charged pro-rata now;
  2. it goes live only once Stripe confirms the payment (until then research
     and cold sending are off; replies are never stopped);
  3. top-ups of £10, £25 or £50 are two taps on the saved card (3-D Secure:
     Stripe's hosted page), reserved against the owner's budget under the
     business lock first, credited only when Stripe confirms, once;
  4. removing a paid brand stops billing at the end of the paid month.
Brands that exist when F goes live stay live (grandfathered); an admin flag
`outreach_brands_free` keeps a business's brands live for its free month.

After Codex's review 1: every operation has a durable identity reused as
Stripe's idempotency key; an outcome Stripe didn't confirm is kept and checked,
never assumed failed; brand state is reconciled against Stripe's CURRENT
subscription, never an event's copy. Stripe here is a stateful fake: nothing
is charged, no network.
"""
# ruff: noqa: F811 - pytest fixtures imported from the research harness are parameters by design

import importlib
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlmodel import Session

from test_outreach_setup import A, B, OWNER, STAFF, db  # noqa: F401
from test_outreach_research import NOW, World, person, research, run, run_clock, setup_clock, started

EXTRA, ADDON, PLAN_PRO = "price_extra_brand", "price_outreach_addon", "price_plan_pro"
PERIOD_END = int(datetime(2026, 11, 21, 14, tzinfo=timezone.utc).timestamp())
AFTER_PERIOD = datetime.fromtimestamp(PERIOD_END, tz=timezone.utc) + timedelta(minutes=1)
LATER = NOW + timedelta(hours=2)          # past the one-hour check-with-Stripe threshold


def billing():
    return importlib.import_module("services.outreach_billing")


@pytest.fixture(autouse=True)
def prices(monkeypatch):
    monkeypatch.setenv("STRIPE_PRICE_EXTRA_BRAND", EXTRA)
    monkeypatch.setenv("STRIPE_PRICE_OUTREACH_ADDON", ADDON)
    monkeypatch.setenv("OUTREACH_PILOT_ENROLMENTS", "0")


class CardError(Exception):
    def __init__(self, code, pi="pi_needs_auth"):
        super().__init__(code)
        self.code = code
        self.error = SimpleNamespace(code=code, payment_intent={"id": pi, "status": "requires_action"})


class InvalidRequestError(Exception):
    pass


class APIConnectionError(Exception):
    pass


class FakeStripe:
    """A stateful stand-in for Stripe. The subscription changes when a change
    is made (or waits, unpaid, with `hold`); payments can be searched by their
    reservation; every call is recorded."""

    CardError, InvalidRequestError, APIConnectionError = CardError, InvalidRequestError, APIConnectionError

    def __init__(self, payment="succeeded", hold=False, modify_error=None):
        self.calls, self.payment, self.hold, self.modify_error = [], payment, hold, modify_error
        self.items = [{"id": "si_plan", "price": {"id": PLAN_PRO}, "quantity": 1, "current_period_end": PERIOD_END}]
        self.pending_items, self.intents, self.sessions = None, {}, {}
        api = self

        class Subscription:
            @staticmethod
            def retrieve(sub_id, **kw):
                api.calls.append(("Subscription.retrieve", sub_id, kw))
                return {"id": sub_id, "customer": "cus_mike", "default_payment_method": "pm_saved", "status": "active",
                        "items": {"data": [dict(i) for i in api.items]},
                        "pending_update": {"subscription_items": api.pending_items} if api.pending_items else None}

            @staticmethod
            def modify(sub_id, **kw):
                api.calls.append(("Subscription.modify", sub_id, kw))
                if api.modify_error:
                    raise api.modify_error
                if api.hold and kw.get("payment_behavior") == "pending_if_incomplete":
                    api.pending_items = kw["items"]
                else:
                    api._apply(kw["items"])
                return {"id": sub_id}

        class PaymentIntent:
            @staticmethod
            def create(**kw):
                api.calls.append(("PaymentIntent.create", None, kw))
                if api.payment == "authentication_required":
                    raise CardError("authentication_required")
                if api.payment == "declined":
                    raise CardError("card_declined")
                if api.payment == "timeout":
                    raise APIConnectionError("read timed out")
                pi = f"pi_{len(api.intents) + 1}"
                api.intents[pi] = {"id": pi, "status": "succeeded", "amount": kw["amount"], "currency": kw["currency"],
                                   "customer": kw["customer"], "metadata": dict(kw["metadata"])}
                return dict(api.intents[pi])

            @staticmethod
            def cancel(pi, **kw):
                api.calls.append(("PaymentIntent.cancel", pi, kw))

            @staticmethod
            def search(query, **kw):
                api.calls.append(("PaymentIntent.search", query, kw))
                key = query.split("'")[3]
                return {"data": [dict(i) for i in api.intents.values() if i["metadata"].get("reservation") == key]}

        class CheckoutSession:
            @staticmethod
            def create(**kw):
                api.calls.append(("checkout.Session.create", None, kw))
                api.sessions["cs_1"] = {"id": "cs_1", "status": "open", "metadata": kw.get("metadata"),
                                        "url": "https://checkout.stripe.example/cs_1", "customer": kw.get("customer")}
                return dict(api.sessions["cs_1"])

            @staticmethod
            def retrieve(cs, **kw):
                api.calls.append(("checkout.Session.retrieve", cs, kw))
                return dict(api.sessions[cs])

        self.Subscription, self.PaymentIntent = Subscription, PaymentIntent
        self.checkout = SimpleNamespace(Session=CheckoutSession)

    def _apply(self, changes):
        for change in changes:
            if "price" in change:
                self.items.append({"id": f"si_{change['price']}", "price": {"id": change["price"]},
                                   "quantity": change["quantity"], "current_period_end": PERIOD_END})
            elif change.get("deleted"):
                self.items = [i for i in self.items if i["id"] != change["id"]]
            else:
                for item in self.items:
                    if item["id"] == change["id"]:
                        item["quantity"] = change["quantity"]

    def pay(self):
        """The pending invoice is paid: Stripe applies the waiting change."""
        if self.pending_items:
            self._apply(self.pending_items)
        self.pending_items = None

    def quantity(self, price):
        return sum(i["quantity"] for i in self.items if i["price"]["id"] == price)

    def named(self, name):
        return [c for c in self.calls if c[0] == name]


def stripe_ids(db, customer="cus_mike", subscription="sub_mike", flags=None, bid=A):
    with db.begin() as c:
        for column in ("stripe_customer_id", "stripe_subscription_id"):
            try:
                c.execute(text(f"ALTER TABLE businesses ADD COLUMN {column} TEXT"))
            except Exception:
                pass
        c.execute(text("UPDATE businesses SET stripe_customer_id = :c, stripe_subscription_id = :s WHERE id = :b"),
                  {"c": customer, "s": subscription, "b": bid})
        if flags is not None:
            c.execute(text("UPDATE businesses SET feature_flags = :f WHERE id = :b"), {"f": json.dumps(flags), "b": bid})


def new_brand(db, biz, name="FitFutures", age=timedelta(minutes=30)):
    """A brand made after F went live (through the wizard), with an approved audience."""
    from test_outreach_setup import draft_lia, setup_module_or_missing
    m = setup_module_or_missing()
    with db.begin() as c:   # every existing brand clearly older, so the price order is fixed (the fixtures share one clock)
        c.execute(text("UPDATE outreach_brands SET created_at = :t WHERE business_id = :b AND created_at > :t"),
                  {"t": NOW - timedelta(hours=3), "b": A})   # a datetime: stored in the same format as the app's
    with setup_clock(), Session(db) as s:
        brand = m.save_brand(s, biz, OWNER, {"name": name, "sender_identity": f"{name} by New Body"})
        lia = m.draft_audience(s, biz, OWNER, {"brand_id": brand["id"], "description": "Gyms that host interns",
                                              "segments": ["gym"], "regions": ["Kent"]}, draft=draft_lia)
        m.approve_audience(s, biz, OWNER, lia["id"], {})
        research().configure(s, biz, OWNER, {"brand_id": brand["id"], "enabled": True})
    with db.begin() as c:
        c.execute(text("UPDATE outreach_brands SET created_at = :t WHERE id = :b"),
                  {"t": NOW - age, "b": brand["id"]})
    return brand, lia


def settings(db):
    with db.connect() as c:
        return json.loads(c.execute(text("SELECT settings FROM business_settings WHERE business_id = :b"),
                                    {"b": A}).scalar() or "{}")


def save_settings(db, doc):
    with db.begin() as c:
        c.execute(text("UPDATE business_settings SET settings = :s WHERE business_id = :b"),
                  {"s": json.dumps(doc), "b": A})


def entry(db, brand):
    return ((settings(db).get("outreach_brand_billing") or {}).get("brands") or {}).get(brand["id"])


def grandfather(db, brand):
    """As if the brand existed before F went live: no billing record."""
    doc = settings(db)
    (doc.get("outreach_brand_billing") or {}).get("brands", {}).pop(brand["id"], None)
    save_settings(db, doc)


def budget(db, biz, pence=100000):
    from services import outreach_allowance
    with run_clock(), Session(db) as s:
        outreach_allowance.set_budget(s, biz, OWNER, {"monthly_pence": pence})


def committed(db, biz, moment=NOW):
    from services import outreach_allowance
    with run_clock(), Session(db) as s:
        return outreach_allowance.budget_status(s, biz, moment=moment)["committed_pence"]


def pending_topups(db):
    with run_clock(), Session(db) as s:
        return billing().pending_topup_pence(s, A)


def live(db, brand, moment=NOW):
    with run_clock(), Session(db) as s:
        return billing().brand_live(s, A, brand["id"], moment)


def webhook(db, api, event_type="customer.subscription.updated", data=None, moment=NOW):
    """A Stripe event reaches the webhook: billing reconciles with Stripe's current state."""
    data = data if data is not None else {"id": "sub_mike", "customer": "cus_mike"}
    with run_clock(), Session(db) as s:
        billing().webhook(s, event_type, data, created=moment, api=api)
        s.commit()


def reconcile(db, api, moment):
    with run_clock(), Session(db) as s:
        billing().reconcile(s, A, api=api, moment=moment)
        s.commit()


def paid_brand_flow(db):
    biz, brand, lia, campaign = started(db)
    grandfather(db, brand)
    stripe_ids(db)
    fit, fit_lia = new_brand(db, biz)
    budget(db, biz)
    return biz, brand, fit, fit_lia


def add(db, biz, brand, api):
    with run_clock(), Session(db) as s:
        return billing().add_paid_brand(s, biz, OWNER, brand["id"], api=api)


def refused(fn, *args, **kw):
    with run_clock(), pytest.raises(Exception) as exc:
        fn(*args, **kw)
    return exc.value


def add_refused(db, biz, brand, api, user=OWNER):
    with Session(db) as s:
        return refused(billing().add_paid_brand, s, biz, user, brand["id"], api=api)


def topup(db, biz, brand, amount, api):
    with run_clock(), Session(db) as s:
        return billing().start_topup(s, biz, OWNER, brand["id"], amount, api=api, return_url="https://app.example/r")


def topup_refused(db, biz, brand, amount, api, user=OWNER):
    with Session(db) as s:
        return refused(billing().start_topup, s, biz, user, brand["id"], amount, api=api,
                       return_url="https://app.example/r")


# --------------------------------------------------- who is live, and when ---

def test_brands_that_existed_before_f_stay_live(db):
    biz, brand, lia, campaign = started(db)
    grandfather(db, brand)
    stripe_ids(db)
    assert live(db, brand) is True                     # Mike's own brand: grandfathered


def test_a_new_paid_brand_waits_for_payment_and_research_does_not_run(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    assert live(db, fit) is False
    world = World([[person(i) for i in range(5)]])
    out = run(db, biz, fit_lia, world)
    assert world.briefs == [] and "payment" in out["stopped"].lower()


def test_a_business_plans_included_brand_is_live_without_billing(db):
    biz, brand, lia, campaign = started(db)
    with db.begin() as c:
        c.execute(text("UPDATE businesses SET plan_tier = 'business' WHERE id = :b"), {"b": A})
    stripe_ids(db)
    save_settings(db, {"outreach_brand_billing": {"brands": {brand["id"]: {"state": "awaiting_payment", "price": 7900}}}})
    assert live(db, brand) is True


def test_the_free_month_switch_keeps_every_brand_live(db):
    biz, brand, lia, campaign = started(db)
    stripe_ids(db, flags={"outreach": True, "outreach_brands_free": True})
    fit, fit_lia = new_brand(db, biz)
    assert live(db, fit) is True


@pytest.mark.parametrize("unset", ["STRIPE_PRICE_EXTRA_BRAND", "STRIPE_PRICE_OUTREACH_ADDON"])
def test_until_both_stripe_prices_are_set_new_brands_change_nothing(db, monkeypatch, unset):
    """Review 1 P2: billing switches on only when BOTH prices are set."""
    monkeypatch.delenv(unset)
    biz, brand, lia, campaign = started(db)
    stripe_ids(db)
    fit, fit_lia = new_brand(db, biz)
    assert live(db, brand) is True and live(db, fit) is True and entry(db, fit) is None


def test_status_shows_each_brands_billing_and_price(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    with run_clock(), Session(db) as s:
        rows = {r["brand_id"]: r for r in billing().status(s, biz)["brands"]}
    assert rows[brand["id"]]["billing"] == "grandfathered" and rows[brand["id"]]["live"] is True
    assert rows[fit["id"]]["billing"] == "awaiting_payment" and rows[fit["id"]]["price_pence"] == 7900
    assert rows[fit["id"]]["live"] is False


# ------------------------------------------------------------- adding a brand ---

def test_adding_a_paid_brand_charges_pro_rata_now_and_waits_for_stripe(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe(hold=True)
    out = add(db, biz, fit, api)
    call = api.named("Subscription.modify")[0]
    assert call[1] == "sub_mike"
    assert call[2]["proration_behavior"] == "always_invoice"
    assert call[2]["payment_behavior"] == "pending_if_incomplete"
    assert call[2]["items"] == [{"price": EXTRA, "quantity": 1}]
    assert call[2]["idempotency_key"] == f"outreach-brand-{entry(db, fit)['op']}"
    assert out["billing"] == "pending" and live(db, fit) is False
    assert committed(db, biz) == 9900 + 7900, "counted in the budget while it may be charged"


def test_only_the_owner_adds_a_paid_brand(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe()
    assert getattr(add_refused(db, biz, fit, api, user=STAFF), "status_code", None) == 403 and api.calls == []


def test_a_brand_beyond_the_owners_budget_is_never_charged(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    budget(db, biz, 9900 + 7899)                      # £99 add-on committed; £79 more doesn't fit
    api = FakeStripe()
    exc = add_refused(db, biz, fit, api)
    assert getattr(exc, "status_code", None) == 409 and "budget" in exc.detail and api.calls == []


def test_without_a_subscription_a_brand_cannot_be_added(db):
    biz, brand, lia, campaign = started(db)
    stripe_ids(db, subscription=None)
    fit, fit_lia = new_brand(db, biz)
    budget(db, biz)
    assert getattr(add_refused(db, biz, fit, FakeStripe()), "status_code", None) == 409


def test_without_the_stripe_prices_set_nothing_is_charged(db, monkeypatch):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    monkeypatch.delenv("STRIPE_PRICE_EXTRA_BRAND")
    api = FakeStripe()
    assert getattr(add_refused(db, biz, fit, api), "status_code", None) == 503 and api.calls == []


def test_quantities_are_set_to_what_is_paid_for_not_counted_up(db):
    """Review 1 P1 5: absolute quantities, so changes converge."""
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    second, second_lia = new_brand(db, biz, "Schools Outreach", age=timedelta(minutes=20))
    api = FakeStripe()
    add(db, biz, fit, api)
    webhook(db, api)
    add(db, biz, second, api)
    assert api.named("Subscription.modify")[1][2]["items"] == [{"id": f"si_{EXTRA}", "quantity": 2}]
    assert api.quantity(EXTRA) == 2


def test_a_second_change_waits_while_one_is_still_going_through(db):
    """Review 1 P1 5: one subscription operation at a time per business."""
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    doc = settings(db)
    doc["outreach_brand_billing"]["op"] = {"token": "busy", "until": (NOW + timedelta(minutes=5)).isoformat()}
    save_settings(db, doc)
    api = FakeStripe()
    exc = add_refused(db, biz, fit, api)
    assert getattr(exc, "status_code", None) == 409 and api.calls == []
    assert entry(db, fit)["state"] == "awaiting_payment"


def test_no_change_while_stripe_still_has_an_unpaid_update(db):
    """Review 1 P1 5: a second update would replace the first's pending invoice."""
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    second, second_lia = new_brand(db, biz, "Schools Outreach", age=timedelta(minutes=20))
    api = FakeStripe(hold=True)
    add(db, biz, fit, api)
    exc = add_refused(db, biz, second, api)
    assert getattr(exc, "status_code", None) == 409 and len(api.named("Subscription.modify")) == 1
    assert entry(db, second)["state"] == "awaiting_payment" and entry(db, fit)["state"] == "pending"


# --------------------------------------------------------- Stripe confirms ---

def test_the_brand_goes_live_when_stripe_has_it_paid(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe(hold=True)
    add(db, biz, fit, api)
    webhook(db, api)
    assert live(db, fit) is False, "still waiting: the invoice isn't paid"
    api.pay()
    webhook(db, api, "invoice.paid", {"subscription": "sub_mike", "customer": "cus_mike"})
    assert live(db, fit) is True
    out = run(db, biz, fit_lia, World([[person(i) for i in range(3)]]))
    assert "payment" not in (out["stopped"] or "").lower(), "research no longer waits for payment"


def test_an_old_event_cannot_switch_a_paid_brand_off(db):
    """Review 1 P1 6: Stripe's CURRENT subscription decides, not the event's copy."""
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe()
    add(db, biz, fit, api)
    webhook(db, api)
    stale = {"id": "sub_mike", "customer": "cus_mike", "items": {"data": [{"price": {"id": PLAN_PRO}, "quantity": 1}]}}
    webhook(db, api, data=stale)
    assert live(db, fit) is True


def test_paid_places_go_to_the_oldest_request_first(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    second, second_lia = new_brand(db, biz, "Schools Outreach", age=timedelta(minutes=20))
    doc = settings(db)
    brands = doc["outreach_brand_billing"]["brands"]
    brands[second["id"]].update(state="pending", requested_at=NOW.isoformat(), op="b")
    brands[fit["id"]].update(state="pending", requested_at=(NOW - timedelta(minutes=1)).isoformat(), op="a")
    save_settings(db, doc)
    api = FakeStripe()
    api._apply([{"price": EXTRA, "quantity": 1}])      # Stripe has one paid
    webhook(db, api)
    assert live(db, fit) is True and live(db, second) is False


def test_an_event_for_a_business_without_outreach_billing_touches_nothing(db):
    """Review 1 P1 1: other customers' events never reach Stripe or fail."""
    started(db)
    stripe_ids(db, customer="cus_other", subscription="sub_other", bid=B)
    api = FakeStripe()
    webhook(db, api, data={"id": "sub_other", "customer": "cus_other"})
    webhook(db, api, "invoice.paid", {"subscription": "sub_nobody", "customer": "cus_nobody"})
    assert api.calls == []


def test_an_uncertain_addition_is_kept_and_retried_with_the_same_identity(db):
    """Review 1 P1 2: a timeout may have been carried out; never 'nothing was charged'."""
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe(modify_error=APIConnectionError("read timed out"))
    exc = add_refused(db, biz, fit, api)
    assert getattr(exc, "status_code", None) == 502 and "don't pay again" in exc.detail.lower()
    assert entry(db, fit)["state"] == "pending" and entry(db, fit)["uncertain"] is True
    assert committed(db, biz) == 9900 + 7900, "still counted: it may have been charged"
    first_key = api.named("Subscription.modify")[0][2]["idempotency_key"]
    api.modify_error = None
    add(db, biz, fit, api)
    assert api.named("Subscription.modify")[1][2]["idempotency_key"] == first_key
    webhook(db, api)
    assert live(db, fit) is True


def test_an_uncertain_addition_that_did_go_through_is_found_by_the_check(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe()
    real = api.Subscription.modify

    def carried_out_then_dropped(sub_id, **kw):
        real(sub_id, **kw)
        raise APIConnectionError("connection reset")
    api.Subscription.modify = staticmethod(carried_out_then_dropped)
    add_refused(db, biz, fit, api)
    reconcile(db, api, LATER)
    assert live(db, fit) is True and api.quantity(EXTRA) == 1


def test_a_declined_addition_goes_back_to_awaiting_payment(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe(modify_error=CardError("card_declined"))
    assert getattr(add_refused(db, biz, fit, api), "status_code", None) == 402
    assert entry(db, fit)["state"] == "awaiting_payment" and committed(db, biz) == 9900


def test_an_addition_whose_invoice_was_never_paid_can_be_tried_again(db):
    """Review 1 P2: an abandoned or declined pending update is recovered."""
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe(hold=True)
    add(db, biz, fit, api)
    reconcile(db, api, LATER)
    assert entry(db, fit)["state"] == "pending", "Stripe still has the update waiting for payment"
    api.pending_items = None                           # Stripe dropped the unpaid update
    reconcile(db, api, LATER)
    assert entry(db, fit)["state"] == "awaiting_payment" and "didn't go through" in entry(db, fit)["note"]
    assert committed(db, biz) == 9900
    add(db, biz, fit, FakeStripe())


def test_cold_sending_waits_for_payment_but_replies_never_do(db):
    """The send path itself refuses an unpaid brand's cold email."""
    import inspect
    from services import metering
    source = inspect.getsource(metering.reserve_outreach_usage)
    assert "brand_live" in source
    assert source.index("brand_live") > source.index("if not reply")


# ---------------------------------------------------------- removing a brand ---

def test_removing_a_paid_brand_stops_billing_at_the_end_of_the_paid_month(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe()
    add(db, biz, fit, api)
    webhook(db, api)
    with run_clock(), Session(db) as s:
        out = billing().remove_paid_brand(s, biz, OWNER, fit["id"], api=api)
    call = api.named("Subscription.modify")[-1][2]
    assert call["proration_behavior"] == "none" and call["items"] == [{"id": f"si_{EXTRA}", "deleted": True}]
    assert out["billing"] == "ending" and live(db, fit) is True, "paid until the end of the month"
    assert live(db, fit, AFTER_PERIOD) is False
    assert committed(db, biz, AFTER_PERIOD) == 9900, "a stopped brand stops counting in the budget (review 1 P2)"


def test_removing_one_of_two_keeps_the_other_live(db):
    """Review 1 P1 5: Stripe's event may land before its answer does."""
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    second, second_lia = new_brand(db, biz, "Schools Outreach", age=timedelta(minutes=20))
    api = FakeStripe()
    add(db, biz, fit, api)
    webhook(db, api)
    add(db, biz, second, api)
    webhook(db, api)
    real = api.Subscription.modify

    def modify_then_webhook(sub_id, **kw):
        out = real(sub_id, **kw)
        webhook(db, api)
        return out
    api.Subscription.modify = staticmethod(modify_then_webhook)
    with run_clock(), Session(db) as s:
        billing().remove_paid_brand(s, biz, OWNER, fit["id"], api=api)
    assert api.quantity(EXTRA) == 1
    assert live(db, second) is True and live(db, fit) is True      # fit: until its paid month ends
    assert live(db, fit, AFTER_PERIOD) is False and live(db, second, AFTER_PERIOD) is True


# ------------------------------------------------------------------ top-ups ---

def test_a_top_up_is_two_taps_on_the_saved_card(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe()
    out = topup(db, biz, brand, 2500, api)
    call = api.named("PaymentIntent.create")[0][2]
    assert call["amount"] == 2500 and call["currency"] == "gbp" and call["customer"] == "cus_mike"
    assert call["payment_method"] == "pm_saved" and call["off_session"] is True and call["confirm"] is True
    key = call["metadata"]["reservation"]
    assert call["metadata"] == {"kind": "outreach_topup", "business_id": A, "brand_id": brand["id"], "reservation": key}
    assert call["idempotency_key"] == f"outreach-topup-{key}"
    assert out["status"] == "processing", "credited only when Stripe confirms"
    assert committed(db, biz) == 9900 + 2500, "reserved until Stripe settles it"


@pytest.mark.parametrize("amount", [999, 1500, 7500, 0, -1000])
def test_only_the_three_top_up_sizes_are_offered(db, amount):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe()
    assert getattr(topup_refused(db, biz, brand, amount, api), "status_code", None) == 422 and api.calls == []


def test_when_the_bank_asks_for_3d_secure_the_owner_finishes_on_stripes_page(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe(payment="authentication_required")
    out = topup(db, biz, brand, 1000, api)
    assert out["checkout_url"] == "https://checkout.stripe.example/cs_1"
    assert api.named("PaymentIntent.cancel")[0][1] == "pi_needs_auth", "the off-session attempt can never also succeed"
    session_call = api.named("checkout.Session.create")[0][2]
    key = api.named("PaymentIntent.create")[0][2]["metadata"]["reservation"]
    assert session_call["mode"] == "payment" and session_call["payment_intent_data"]["metadata"]["reservation"] == key


def test_the_hosted_page_keeps_its_reservation_until_it_expires(db):
    """Review 1 P1 4: the failed off-session attempt doesn't release a page still payable."""
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe(payment="authentication_required")
    topup(db, biz, brand, 1000, api)
    metadata = api.named("checkout.Session.create")[0][2]["metadata"]
    failed = {"id": "pi_needs_auth", "amount": 1000, "currency": "gbp", "customer": "cus_mike", "metadata": metadata}
    webhook(db, api, "payment_intent.payment_failed", failed)
    assert committed(db, biz) == 9900 + 1000
    webhook(db, api, "checkout.session.expired", {"id": "cs_1", "customer": "cus_mike", "metadata": metadata})
    assert committed(db, biz) == 9900


def test_a_declined_card_charges_nothing_and_releases_the_reservation(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    assert getattr(topup_refused(db, biz, brand, 5000, FakeStripe(payment="declined")), "status_code", None) == 402
    assert committed(db, biz) == 9900


def test_an_uncertain_top_up_stays_reserved_and_is_credited_when_stripe_has_it(db):
    """Review 1 P1 2: a timeout is checked later by the payment's own identity."""
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe(payment="timeout")
    assert getattr(topup_refused(db, biz, brand, 2500, api), "status_code", None) == 502
    assert committed(db, biz) == 9900 + 2500
    sent = api.named("PaymentIntent.create")[0][2]
    api.intents["pi_late"] = {"id": "pi_late", "status": "succeeded", "amount": 2500, "currency": "gbp",
                              "customer": "cus_mike", "metadata": sent["metadata"]}
    reconcile(db, api, NOW + timedelta(minutes=5))
    assert api.named("PaymentIntent.search") == [], "checked only once it's had time to settle"
    reconcile(db, api, LATER)
    reconcile(db, api, LATER)
    assert pending_topups(db) == 0 and committed(db, biz) == 9900 + 2500, "credited, once"


def test_an_uncertain_top_up_that_never_reached_stripe_is_released(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe(payment="timeout")
    topup_refused(db, biz, brand, 2500, api)
    reconcile(db, api, LATER)
    assert committed(db, biz) == 9900


def test_two_top_ups_never_pass_the_budget(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    budget(db, biz, 9900 + 5000)                       # room for £50 of top-ups, once
    api = FakeStripe()
    topup(db, biz, brand, 5000, api)
    assert getattr(topup_refused(db, biz, brand, 1000, api), "status_code", None) == 409
    assert len(api.named("PaymentIntent.create")) == 1


def test_a_top_up_needs_a_live_brand_and_the_owner(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    for user, target in ((STAFF, brand), (OWNER, fit)):   # not the owner; a brand not yet paid for
        api = FakeStripe()
        assert getattr(topup_refused(db, biz, target, 1000, api, user=user), "status_code", None) in (403, 409)
        assert api.calls == []


def test_a_confirmed_top_up_is_credited_once_and_raises_the_allowance(db):
    from services import outreach_allowance
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe()
    with run_clock(), Session(db) as s:
        before = outreach_allowance.allowance_pence(s, A, brand["id"], "2026-10")
    topup(db, biz, brand, 2500, api)
    webhook(db, api, "payment_intent.succeeded", dict(api.intents["pi_1"]))
    webhook(db, api, "payment_intent.succeeded", dict(api.intents["pi_1"]))     # a second delivery: never twice
    with run_clock(), Session(db) as s:
        assert outreach_allowance.allowance_pence(s, A, brand["id"], "2026-10") == before + 2500 // 3
    assert pending_topups(db) == 0 and committed(db, biz) == 9900 + 2500


def test_one_confirmed_top_up_releases_only_its_own_reservation(db):
    """Review 1 P1 3."""
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe()
    topup(db, biz, brand, 2500, api)
    topup(db, biz, brand, 2500, api)
    webhook(db, api, "payment_intent.succeeded", dict(api.intents["pi_1"]))
    assert pending_topups(db) == 2500, "the other £25 is still payable"
    assert committed(db, biz) == 9900 + 5000


def test_a_failed_payment_releases_its_reservation(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe()
    topup(db, biz, brand, 2500, api)
    webhook(db, api, "payment_intent.payment_failed", dict(api.intents["pi_1"], status="requires_payment_method"))
    assert committed(db, biz) == 9900


@pytest.mark.parametrize("change", [{"customer": "cus_someone_else"}, {"currency": "usd"}, {"amount": 9999},
                                    {"metadata": {}}, {"brand_id": "not-a-brand"}])
def test_a_payment_that_isnt_this_businesss_own_top_up_is_ignored(db, change):
    """Review 1 P1 7: bound to the business's own Stripe customer, in pounds, a real size."""
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    intent = {"id": "pi_x", "status": "succeeded", "amount": 2500, "currency": "gbp", "customer": "cus_mike",
              "metadata": {"kind": "outreach_topup", "business_id": A, "brand_id": brand["id"], "reservation": "r"}}
    if "brand_id" in change:
        intent["metadata"]["brand_id"] = change["brand_id"]
    else:
        intent.update(change)
    webhook(db, FakeStripe(), "payment_intent.succeeded", intent)
    assert committed(db, biz) == 9900


# ----------------------------------------------------------- the webhook ---

def test_the_stripe_webhook_hands_events_to_billing_inside_its_retry_boundary():
    import inspect
    import main
    source = inspect.getsource(main.stripe_webhook)
    at = source.index("outreach_billing.webhook(")
    block = source[at:]
    assert block.index("status_code=503") < block.index("session.add(StripeEvent")
    assert at < source.index("session.add(business)"), "before the handler writes the business row"
    # Behaviour, end to end on PostgreSQL: tests/test_outreach_billing_pg.py.


def test_the_scheduler_runs_the_billing_check():
    import inspect
    from services import briefing_scheduler
    assert "outreach_billing.scheduled_check" in inspect.getsource(briefing_scheduler._run_profit_check_if_due)


def test_the_scheduled_check_settles_every_business_with_billing(db, monkeypatch):
    import db as db_module
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe()
    add(db, biz, fit, api)
    monkeypatch.setattr(db_module, "engine", db)
    with run_clock():
        assert billing().scheduled_check(api=api) == 1
    assert live(db, fit) is True


def test_stripe_returns_the_owner_to_the_page_with_billing_on_it():
    """Review 1 P2: the research panel (and its billing) is on the settings tab."""
    import inspect
    import outreach_setup_api as api
    assert "/app/outreach/settings" in inspect.getsource(api._return_url)


@pytest.mark.parametrize("who,code", [(OWNER, 200), (STAFF, 403)])
def test_the_billing_endpoints(db, monkeypatch, who, code):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import auth
    import outreach_setup_api as api
    from auth import get_user_business_context
    from db import get_session
    from rate_limiting import limiter
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    monkeypatch.setattr(auth, "_load_business", lambda session, bid: biz)
    monkeypatch.setattr(limiter, "enabled", False)
    fake = FakeStripe()
    monkeypatch.setattr(billing(), "_stripe", lambda: fake)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[get_user_business_context] = lambda: {"business_id": A, "user_id": who}
    app.dependency_overrides[get_session] = lambda: Session(db)
    with run_clock(), TestClient(app) as client:
        assert client.get("/v1/outreach/setup/billing").status_code == 200
        added = client.post(f"/v1/outreach/setup/brands/{fit['id']}/billing")
        topped = client.post("/v1/outreach/setup/topups", json={"brand_id": brand["id"], "amount_pence": 1000})
        bad = client.post("/v1/outreach/setup/topups", json={"brand_id": brand["id"], "amount_pence": "lots"})
    assert (added.status_code, topped.status_code) == (code, code) and bad.status_code == 422
    assert (len(fake.calls) > 0) == (code == 200)

