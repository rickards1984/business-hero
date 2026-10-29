"""OUT-19 F — Stripe for extra brands and top-ups (docs/OUT-19-TICKET.md, F).
RED: money.

Mike, 29 Oct 2026 ("Go with recommendations ... they also protect expenditure
vs income"):
  1. a new paid brand is added to the subscription and charged pro-rata now;
  2. it goes live only once Stripe confirms the payment (until then research
     and cold sending are off; replies are never stopped);
  3. top-ups of £10, £25 or £50 are two taps on the saved card (3-D Secure:
     Stripe's hosted page), reserved against the owner's budget under the
     business lock first, credited only on Stripe's payment_intent.succeeded;
  4. removing a paid brand stops billing at the end of the paid month.
Brands that exist when F goes live stay live (grandfathered); an admin flag
`outreach_brands_free` keeps a business's brands live for its free month.

Tests first: strict xfail until services.outreach_billing exists. Stripe is a
recording fake; nothing is charged; no network.
"""
# ruff: noqa: F811 - pytest fixtures imported from the research harness are parameters by design

import importlib
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlmodel import Session

from test_outreach_setup import A, OWNER, STAFF, db  # noqa: F401
from test_outreach_research import NOW, World, person, research, run, run_clock, setup_clock, started


class MissingBilling(AssertionError):
    """Only the intentional absence of the module may be xfailed."""


pytestmark = pytest.mark.xfail(raises=MissingBilling, strict=True, reason="OUT-19 F tests first: awaiting Mike's approval")

EXTRA, ADDON, PLAN_PRO = "price_extra_brand", "price_outreach_addon", "price_plan_pro"
PERIOD_END = int(datetime(2026, 11, 21, 14, tzinfo=timezone.utc).timestamp())


def billing():
    if importlib.util.find_spec("services.outreach_billing") is None:
        raise MissingBilling("backend/services/outreach_billing.py does not exist yet")
    return importlib.import_module("services.outreach_billing")


@pytest.fixture(autouse=True)
def prices(monkeypatch):
    monkeypatch.setenv("STRIPE_PRICE_EXTRA_BRAND", EXTRA)
    monkeypatch.setenv("STRIPE_PRICE_OUTREACH_ADDON", ADDON)
    monkeypatch.setenv("OUTREACH_PILOT_ENROLMENTS", "0")


class CardError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code
        self.error = SimpleNamespace(code=code, payment_intent={"id": "pi_needs_auth", "status": "requires_action"})


class FakeStripe:
    """Records every call; answers like Stripe; charges nothing."""

    def __init__(self, items=None, payment="succeeded"):
        self.calls = []
        self.items = items if items is not None else [{"id": "si_plan", "price": {"id": PLAN_PRO}, "quantity": 1,
                                                      "current_period_end": PERIOD_END}]
        self.payment = payment
        api = self

        class Subscription:
            @staticmethod
            def retrieve(sub_id, **kw):
                api.calls.append(("Subscription.retrieve", sub_id, kw))
                return {"id": sub_id, "customer": "cus_mike", "items": {"data": [dict(i) for i in api.items]},
                        "default_payment_method": "pm_saved", "status": "active"}

            @staticmethod
            def modify(sub_id, **kw):
                api.calls.append(("Subscription.modify", sub_id, kw))
                return {"id": sub_id, "pending_update": {"subscription_items": kw.get("items")}}

        class PaymentIntent:
            @staticmethod
            def create(**kw):
                api.calls.append(("PaymentIntent.create", None, kw))
                if api.payment == "authentication_required":
                    raise CardError("authentication_required")
                if api.payment == "declined":
                    raise CardError("card_declined")
                return {"id": "pi_ok", "status": "succeeded", "amount": kw["amount"], "metadata": kw.get("metadata")}

        class CheckoutSession:
            @staticmethod
            def create(**kw):
                api.calls.append(("checkout.Session.create", None, kw))
                return {"id": "cs_1", "url": "https://checkout.stripe.example/cs_1"}

        self.Subscription, self.PaymentIntent = Subscription, PaymentIntent
        self.checkout = SimpleNamespace(Session=CheckoutSession)
        self.error = SimpleNamespace(CardError=CardError, StripeError=Exception)

    def named(self, name):
        return [c for c in self.calls if c[0] == name]


def stripe_ids(db, customer="cus_mike", subscription="sub_mike", flags=None):
    with db.begin() as c:
        for column in ("stripe_customer_id", "stripe_subscription_id"):
            try:
                c.execute(text(f"ALTER TABLE businesses ADD COLUMN {column} TEXT"))
            except Exception:
                pass
        c.execute(text("UPDATE businesses SET stripe_customer_id = :c, stripe_subscription_id = :s WHERE id = :b"),
                  {"c": customer, "s": subscription, "b": A})
        if flags is not None:
            c.execute(text("UPDATE businesses SET feature_flags = :f WHERE id = :b"), {"f": json.dumps(flags), "b": A})


def new_brand(db, biz, name="FitFutures"):
    """A brand made after F went live (through the wizard), with an approved audience."""
    from test_outreach_setup import draft_lia, setup_module_or_missing
    m = setup_module_or_missing()
    with setup_clock(), Session(db) as s:
        brand = m.save_brand(s, biz, OWNER, {"name": name, "sender_identity": f"{name} by New Body"})
        lia = m.draft_audience(s, biz, OWNER, {"brand_id": brand["id"], "description": "Gyms that host interns",
                                              "segments": ["gym"], "regions": ["Kent"]}, draft=draft_lia)
        m.approve_audience(s, biz, OWNER, lia["id"], {})
        research().configure(s, biz, OWNER, {"brand_id": brand["id"], "enabled": True})
    with db.begin() as c:   # made after the first brand (the fixtures share one pinned clock)
        c.execute(text("UPDATE outreach_brands SET created_at = :t WHERE id = :b"),
                  {"t": (NOW - timedelta(minutes=30)).isoformat(), "b": brand["id"]})
    return brand, lia


def budget(db, biz, pence=100000):
    from services import outreach_allowance
    with run_clock(), Session(db) as s:
        outreach_allowance.set_budget(s, biz, OWNER, {"monthly_pence": pence})


def live(db, brand):
    with run_clock(), Session(db) as s:
        return billing().brand_live(s, A, brand["id"], NOW)


def subscription_event(db, items, pending_update=None):
    sub = {"id": "sub_mike", "customer": "cus_mike", "status": "active",
           "items": {"data": [{"id": "si_plan", "price": {"id": PLAN_PRO}, "quantity": 1,
                               "current_period_end": PERIOD_END}] + items}}
    if pending_update is not None:
        sub["pending_update"] = pending_update
    with run_clock(), Session(db) as s:
        billing().apply_subscription(s, sub)
        s.commit()


def paid_brand_flow(db):
    biz, brand, lia, campaign = started(db)
    stripe_ids(db)
    fit, fit_lia = new_brand(db, biz)
    budget(db, biz)
    return biz, brand, fit, fit_lia


# --------------------------------------------------- who is live, and when ---

def test_brands_that_existed_before_f_stay_live(db):
    billing()
    biz, brand, lia, campaign = started(db)
    stripe_ids(db)
    assert live(db, brand) is True                     # Mike's own brand: grandfathered


def test_a_new_paid_brand_waits_for_payment_and_research_does_not_run(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    assert live(db, fit) is False
    world = World([[person(i) for i in range(5)]])
    out = run(db, biz, fit_lia, world)
    assert world.briefs == [] and "payment" in out["stopped"].lower()


def test_a_business_plans_included_brand_is_live_without_billing(db):
    billing()
    biz, brand, lia, campaign = started(db)
    with db.begin() as c:
        c.execute(text("UPDATE businesses SET plan_tier = 'business' WHERE id = :b"), {"b": A})
    stripe_ids(db)
    with db.begin() as c:                              # as if made after F: still included, so live
        c.execute(text("UPDATE business_settings SET settings = :s WHERE business_id = :b"),
                  {"s": json.dumps({"outreach_brand_billing": {}}), "b": A})
    assert live(db, brand) is True


def test_the_free_month_switch_keeps_every_brand_live(db):
    billing()
    biz, brand, lia, campaign = started(db)
    stripe_ids(db, flags={"outreach": True, "outreach_brands_free": True})
    fit, fit_lia = new_brand(db, biz)
    assert live(db, fit) is True


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
    api = FakeStripe()
    with run_clock(), Session(db) as s:
        out = billing().add_paid_brand(s, biz, OWNER, fit["id"], api=api)
    call = api.named("Subscription.modify")[0]
    assert call[1] == "sub_mike"
    assert call[2]["proration_behavior"] == "always_invoice"
    assert call[2]["payment_behavior"] == "pending_if_incomplete"
    assert {"price": EXTRA, "quantity": 1} in [{k: i[k] for k in ("price", "quantity") if k in i} for i in call[2]["items"]]
    assert call[2].get("idempotency_key")
    assert out["billing"] == "pending" and live(db, fit) is False


def test_only_the_owner_adds_a_paid_brand(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe()
    with run_clock(), Session(db) as s, pytest.raises(Exception) as exc:
        billing().add_paid_brand(s, biz, STAFF, fit["id"], api=api)
    assert getattr(exc.value, "status_code", None) == 403 and api.calls == []


def test_a_brand_beyond_the_owners_budget_is_never_charged(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    budget(db, biz, 9900 + 7899)                      # £99 add-on committed; £79 more doesn't fit
    api = FakeStripe()
    with run_clock(), Session(db) as s, pytest.raises(Exception) as exc:
        billing().add_paid_brand(s, biz, OWNER, fit["id"], api=api)
    assert getattr(exc.value, "status_code", None) == 409 and "budget" in exc.value.detail
    assert api.calls == []


def test_without_a_subscription_a_brand_cannot_be_added(db):
    billing()
    biz, brand, lia, campaign = started(db)
    stripe_ids(db, subscription=None)
    fit, fit_lia = new_brand(db, biz)
    budget(db, biz)
    with run_clock(), Session(db) as s, pytest.raises(Exception) as exc:
        billing().add_paid_brand(s, biz, OWNER, fit["id"], api=FakeStripe())
    assert getattr(exc.value, "status_code", None) == 409


def test_a_second_paid_brand_raises_the_quantity(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe(items=[{"id": "si_plan", "price": {"id": PLAN_PRO}, "quantity": 1, "current_period_end": PERIOD_END},
                            {"id": "si_extra", "price": {"id": EXTRA}, "quantity": 1, "current_period_end": PERIOD_END}])
    with run_clock(), Session(db) as s:
        billing().add_paid_brand(s, biz, OWNER, fit["id"], api=api)
    items = api.named("Subscription.modify")[0][2]["items"]
    assert {"id": "si_extra", "quantity": 2} in [{k: i[k] for k in ("id", "quantity") if k in i} for i in items]


# --------------------------------------------------------- Stripe confirms ---

def test_the_brand_goes_live_when_stripe_shows_it_paid(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    with run_clock(), Session(db) as s:
        billing().add_paid_brand(s, biz, OWNER, fit["id"], api=FakeStripe())
    subscription_event(db, [], pending_update={"subscription_items": [{"price": EXTRA, "quantity": 1}]})
    assert live(db, fit) is False, "still waiting: the invoice isn't paid"
    subscription_event(db, [{"id": "si_extra", "price": {"id": EXTRA}, "quantity": 1, "current_period_end": PERIOD_END}])
    assert live(db, fit) is True
    out = run(db, biz, fit_lia, World([[person(i) for i in range(3)]]))
    assert out["accepted"]


def test_paid_places_go_to_the_oldest_waiting_brand_first(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    second, second_lia = new_brand(db, biz, "Schools Outreach")
    with db.begin() as c:
        c.execute(text("UPDATE outreach_brands SET created_at = :t WHERE id = :b"),
                  {"t": (NOW - timedelta(minutes=10)).isoformat(), "b": second["id"]})
    api = FakeStripe()
    with run_clock(), Session(db) as s:
        billing().add_paid_brand(s, biz, OWNER, fit["id"], api=api)
        billing().add_paid_brand(s, biz, OWNER, second["id"], api=api)
    subscription_event(db, [{"id": "si_extra", "price": {"id": EXTRA}, "quantity": 1, "current_period_end": PERIOD_END}])
    assert live(db, fit) is True and live(db, second) is False


def test_an_event_for_another_customer_changes_nothing(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    with run_clock(), Session(db) as s:
        billing().add_paid_brand(s, biz, OWNER, fit["id"], api=FakeStripe())
        billing().apply_subscription(s, {"id": "sub_other", "customer": "cus_other", "status": "active",
                                         "items": {"data": [{"id": "x", "price": {"id": EXTRA}, "quantity": 5}]}})
        s.commit()
    assert live(db, fit) is False


def test_cold_sending_waits_for_payment_but_replies_never_do(db):
    """The send path itself refuses an unpaid brand's cold email."""
    billing()
    import inspect
    from services import metering
    source = inspect.getsource(metering.reserve_outreach_usage)
    assert "brand_live" in source
    assert source.index("brand_live") > source.index("if not reply")


# ---------------------------------------------------------- removing a brand ---

def test_removing_a_paid_brand_stops_billing_at_the_end_of_the_paid_month(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    with run_clock(), Session(db) as s:
        billing().add_paid_brand(s, biz, OWNER, fit["id"], api=FakeStripe())
    subscription_event(db, [{"id": "si_extra", "price": {"id": EXTRA}, "quantity": 1, "current_period_end": PERIOD_END}])
    api = FakeStripe(items=[{"id": "si_plan", "price": {"id": PLAN_PRO}, "quantity": 1, "current_period_end": PERIOD_END},
                            {"id": "si_extra", "price": {"id": EXTRA}, "quantity": 1, "current_period_end": PERIOD_END}])
    with run_clock(), Session(db) as s:
        out = billing().remove_paid_brand(s, biz, OWNER, fit["id"], api=api)
    call = api.named("Subscription.modify")[0][2]
    assert call["proration_behavior"] == "none"
    assert any(i.get("id") == "si_extra" and (i.get("quantity") == 0 or i.get("deleted")) for i in call["items"])
    assert out["billing"] == "ending" and live(db, fit) is True, "paid until the end of the month"
    after = datetime.fromtimestamp(PERIOD_END, tz=timezone.utc) + timedelta(minutes=1)
    with run_clock(), Session(db) as s:
        assert billing().brand_live(s, A, fit["id"], after) is False


# ------------------------------------------------------------------ top-ups ---

def test_a_top_up_is_two_taps_on_the_saved_card(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe()
    with run_clock(), Session(db) as s:
        out = billing().start_topup(s, biz, OWNER, brand["id"], 2500, api=api, return_url="https://app.example/outreach")
    call = api.named("PaymentIntent.create")[0][2]
    assert call["amount"] == 2500 and call["currency"] == "gbp" and call["customer"] == "cus_mike"
    assert call["payment_method"] == "pm_saved" and call["off_session"] is True and call["confirm"] is True
    assert call["metadata"] == {"kind": "outreach_topup", "business_id": A, "brand_id": brand["id"]}
    assert call.get("idempotency_key")
    assert out["status"] == "processing", "credited only when Stripe confirms"


@pytest.mark.parametrize("amount", [999, 1500, 7500, 0, -1000])
def test_only_the_three_top_up_sizes_are_offered(db, amount):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe()
    with run_clock(), Session(db) as s, pytest.raises(Exception) as exc:
        billing().start_topup(s, biz, OWNER, brand["id"], amount, api=api, return_url="https://app.example/outreach")
    assert getattr(exc.value, "status_code", None) == 422 and api.calls == []


def test_when_the_bank_asks_for_3d_secure_the_owner_finishes_on_stripes_page(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe(payment="authentication_required")
    with run_clock(), Session(db) as s:
        out = billing().start_topup(s, biz, OWNER, brand["id"], 1000, api=api, return_url="https://app.example/outreach")
    assert out["checkout_url"] == "https://checkout.stripe.example/cs_1"
    session_call = api.named("checkout.Session.create")[0][2]
    assert session_call["mode"] == "payment"
    assert session_call["payment_intent_data"]["metadata"]["kind"] == "outreach_topup"


def test_a_declined_card_charges_nothing_and_releases_the_reservation(db):
    from services import outreach_allowance
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    with run_clock(), Session(db) as s, pytest.raises(Exception) as exc:
        billing().start_topup(s, biz, OWNER, brand["id"], 5000, api=FakeStripe(payment="declined"),
                              return_url="https://app.example/outreach")
    assert getattr(exc.value, "status_code", None) == 402
    with run_clock(), Session(db) as s:
        assert outreach_allowance.budget_status(s, biz, moment=NOW)["committed_pence"] == 9900


def test_two_top_ups_at_once_never_pass_the_budget(db):
    """Each is reserved under the business lock before Stripe is called."""
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    budget(db, biz, 9900 + 5000)                       # room for £50 of top-ups, once
    api = FakeStripe()
    with run_clock(), Session(db) as s:
        billing().start_topup(s, biz, OWNER, brand["id"], 5000, api=api, return_url="https://app.example/outreach")
    with run_clock(), Session(db) as s, pytest.raises(Exception) as exc:
        billing().start_topup(s, biz, OWNER, brand["id"], 1000, api=api, return_url="https://app.example/outreach")
    assert getattr(exc.value, "status_code", None) == 409 and len(api.named("PaymentIntent.create")) == 1


def test_a_top_up_needs_a_live_brand_and_the_owner(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    for user, brand_id in ((STAFF, brand["id"]), (OWNER, fit["id"])):   # not the owner; a brand not yet paid for
        api = FakeStripe()
        with run_clock(), Session(db) as s, pytest.raises(Exception) as exc:
            billing().start_topup(s, biz, user, brand_id, 1000, api=api, return_url="https://app.example/outreach")
        assert getattr(exc.value, "status_code", None) in (403, 409) and api.calls == []


def payment_event(db, event_type, *, pi="pi_ok", amount=2500, brand_id=None, metadata=None, created=None):
    intent = {"id": pi, "object": "payment_intent", "amount": amount, "amount_received": amount, "currency": "gbp",
              "metadata": metadata if metadata is not None else {"kind": "outreach_topup", "business_id": A,
                                                                 "brand_id": brand_id}}
    with run_clock(), Session(db) as s:
        billing().apply_payment_intent(s, event_type, intent, created=created or NOW)
        s.commit()


def test_a_confirmed_top_up_is_credited_once_and_raises_the_allowance(db):
    from services import outreach_allowance
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    with run_clock(), Session(db) as s:
        before = outreach_allowance.allowance_pence(s, A, brand["id"], "2026-10")
        billing().start_topup(s, biz, OWNER, brand["id"], 2500, api=FakeStripe(), return_url="https://app.example/outreach")
    payment_event(db, "payment_intent.succeeded", brand_id=brand["id"])
    payment_event(db, "payment_intent.succeeded", brand_id=brand["id"])     # a second delivery: never twice
    with run_clock(), Session(db) as s:
        assert outreach_allowance.allowance_pence(s, A, brand["id"], "2026-10") == before + 2500 // 3
        assert outreach_allowance.budget_status(s, biz, moment=NOW)["committed_pence"] == 9900 + 2500


def test_a_failed_payment_releases_its_reservation(db):
    from services import outreach_allowance
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    with run_clock(), Session(db) as s:
        billing().start_topup(s, biz, OWNER, brand["id"], 2500, api=FakeStripe(payment="authentication_required"),
                              return_url="https://app.example/outreach")
    payment_event(db, "payment_intent.payment_failed", pi="pi_needs_auth", brand_id=brand["id"])
    with run_clock(), Session(db) as s:
        assert outreach_allowance.budget_status(s, biz, moment=NOW)["committed_pence"] == 9900


def test_a_payment_that_isnt_an_outreach_top_up_is_ignored(db):
    from services import outreach_allowance
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    payment_event(db, "payment_intent.succeeded", pi="pi_invoice", metadata={})
    payment_event(db, "payment_intent.succeeded", pi="pi_forged",
                  metadata={"kind": "outreach_topup", "business_id": A, "brand_id": "not-a-brand"})
    with run_clock(), Session(db) as s:
        assert outreach_allowance.budget_status(s, biz, moment=NOW)["committed_pence"] == 9900


def test_without_the_stripe_prices_set_nothing_is_charged(db, monkeypatch):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    monkeypatch.delenv("STRIPE_PRICE_EXTRA_BRAND")
    api = FakeStripe()
    with run_clock(), Session(db) as s, pytest.raises(Exception) as exc:
        billing().add_paid_brand(s, biz, OWNER, fit["id"], api=api)
    assert getattr(exc.value, "status_code", None) == 503 and api.calls == []


# ----------------------------------------------------------- the webhook ---

def test_the_stripe_webhook_hands_subscriptions_and_payments_to_billing():
    import inspect
    billing()
    import main
    source = inspect.getsource(main.stripe_webhook)
    assert "outreach_billing.apply_subscription" in source
    assert "outreach_billing.apply_payment_intent" in source
    assert "payment_intent.succeeded" in source and "payment_intent.payment_failed" in source
