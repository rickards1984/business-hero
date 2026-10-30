"""OUT-19 F — Stripe for extra brands and top-ups (docs/OUT-19-TICKET.md, F).
RED: money.

Mike, 29 Oct 2026, simplified with Mike on 30 Oct 2026 after Codex's review 2:
  1. each new paid brand gets its own line on the subscription (its own Stripe
     price), charged pro-rata now;
  2. it goes live only once Stripe has that line paid (until then research
     and cold sending are off; replies are never stopped);
  3. top-ups of £10, £25 or £50 are paid on Stripe's own page, reserved
     against the owner's budget first, credited when Stripe says the page was
     paid (once), released only when Stripe says it expired;
  4. removing a paid brand deletes its line, live until the end of the month
     already paid.
Brands that exist when F goes live stay live (grandfathered); an admin flag
`outreach_brands_free` keeps a business's brands live for its free month.

Stripe here is a stateful fake that keeps idempotency the way Stripe does:
the same key with different parameters is refused; with the same parameters
it returns the first answer and changes nothing. Nothing is charged; no
network.
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
LATER = NOW + timedelta(hours=2)          # past the one-hour "the addition failed" threshold
SOON = NOW + timedelta(minutes=10)        # a page is checked with Stripe after 5 minutes


def billing():
    return importlib.import_module("services.outreach_billing")


@pytest.fixture(autouse=True)
def prices(monkeypatch):
    monkeypatch.setenv("STRIPE_PRICE_EXTRA_BRAND", EXTRA)
    monkeypatch.setenv("STRIPE_PRICE_OUTREACH_ADDON", ADDON)
    monkeypatch.setenv("OUTREACH_PILOT_ENROLMENTS", "0")


class CardError(Exception):
    def __init__(self, code="card_declined"):
        super().__init__(code)
        self.code = code


class InvalidRequestError(Exception):
    pass


class IdempotencyError(Exception):
    pass


class APIConnectionError(Exception):
    pass


class FakeStripe:
    """A stateful stand-in for Stripe, with Stripe's idempotency rules.

    `fail[name]` makes the next call to `name` fail: an exception raised before
    anything happens, or ("lost", exc) — carried out, then the answer is lost.
    """

    CardError, InvalidRequestError, IdempotencyError, APIConnectionError = (
        CardError, InvalidRequestError, IdempotencyError, APIConnectionError)

    def __init__(self, hold=False):
        self.calls, self.hold, self.fail, self.keys = [], hold, {}, {}
        self.items = [{"id": "si_plan", "price": {"id": PLAN_PRO}, "quantity": 1, "current_period_end": PERIOD_END}]
        self.pending_items, self.prices, self.pages, self.status = None, {}, {}, "active"
        self.base = {EXTRA: 7900, ADDON: 9900}
        self.now = NOW                     # Stripe's clock, for the page-expiry rule
        api = self

        def idempotent(name, kw, act):
            api.calls.append((name, kw))
            key = kw.get("idempotency_key")
            params = {k: v for k, v in kw.items() if k != "idempotency_key"}
            if key in api.keys:
                seen_name, seen_params, answer = api.keys[key]
                if (seen_name, seen_params) != (name, params):
                    raise IdempotencyError("Keys for idempotent requests can only be used with the same parameters")
                return answer
            failure = api.fail.pop(name, None)
            if failure is not None and not isinstance(failure, tuple):
                raise failure
            answer = act()
            if key:
                api.keys[key] = (name, params, answer)
            if failure is not None:
                raise failure[1]
            return answer

        class Price:
            @staticmethod
            def retrieve(price_id, **kw):
                api.calls.append(("Price.retrieve", price_id))
                return {"id": price_id, "unit_amount": api.base[price_id], "currency": "gbp",
                        "recurring": {"interval": "month"}, "product": f"prod_{price_id}"}

            @staticmethod
            def create(**kw):
                def act():
                    pid = f"price_brand_{len(api.prices) + 1}"
                    api.prices[pid] = kw
                    return {"id": pid}
                return idempotent("Price.create", kw, act)

        class Subscription:
            @staticmethod
            def retrieve(sub_id, **kw):
                api.calls.append(("Subscription.retrieve", sub_id))
                failure = api.fail.pop("Subscription.retrieve", None)
                if failure is not None:
                    raise failure
                return {"id": sub_id, "customer": "cus_mike", "status": api.status,
                        "items": {"data": [dict(i) for i in api.items]},
                        "pending_update": {"subscription_items": [{"price": {"id": i["price"]}} for i in api.pending_items]}
                        if api.pending_items else None}

            @staticmethod
            def modify(sub_id, **kw):
                def act():
                    if api.hold and kw.get("payment_behavior") == "pending_if_incomplete":
                        api.pending_items = kw["items"]
                    else:
                        api._apply(kw["items"])
                    return {"id": sub_id}
                return idempotent("Subscription.modify", dict(kw, sub=sub_id), act)

        class CheckoutSession:
            @staticmethod
            def create(**kw):
                def act():
                    if kw["expires_at"] - api.now.timestamp() < 30 * 60:
                        raise InvalidRequestError("expires_at must be at least 30 minutes after creation")
                    cs = f"cs_{len(api.pages) + 1}"
                    line = kw["line_items"][0]["price_data"]
                    api.pages[cs] = {"id": cs, "status": "open", "payment_status": "unpaid", "url": f"https://pay.example/{cs}",
                                     "customer": kw["customer"], "metadata": dict(kw["metadata"]),
                                     "amount_total": line["unit_amount"], "currency": line["currency"]}
                    return dict(api.pages[cs])
                return idempotent("checkout.Session.create", kw, act)

            @staticmethod
            def retrieve(cs, **kw):
                api.calls.append(("checkout.Session.retrieve", cs))
                return dict(api.pages[cs])

        self.Price, self.Subscription = Price, Subscription
        self.checkout = SimpleNamespace(Session=CheckoutSession)

    def _apply(self, changes):
        for change in changes:
            if "price" in change:
                self.items.append({"id": f"si_{change['price']}", "price": {"id": change["price"]},
                                   "quantity": change["quantity"], "current_period_end": PERIOD_END})
            elif change.get("deleted"):
                self.items = [i for i in self.items if i["id"] != change["id"]]

    def pay(self):
        """The pending invoice is paid: Stripe applies the waiting change."""
        if self.pending_items:
            self._apply(self.pending_items)
        self.pending_items = None

    def pay_page(self, cs):
        self.pages[cs].update(status="complete", payment_status="paid")
        return dict(self.pages[cs])

    def expire_page(self, cs):
        self.pages[cs].update(status="expired")
        return dict(self.pages[cs])

    def billed(self):
        return [i["price"]["id"] for i in self.items if i["price"]["id"] != PLAN_PRO]

    def named(self, name):
        return [c[1] for c in self.calls if c[0] == name]


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
        c.execute(text("UPDATE outreach_brands SET created_at = :t WHERE id = :b"), {"t": NOW - age, "b": brand["id"]})
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


def purchases(db):
    return (settings(db).get("outreach_brand_billing") or {}).get("purchases") or {}


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


def topped_up(db, brand):
    with db.connect() as c:
        return int(c.execute(text("SELECT coalesce(sum(value), 0) FROM usage_meters WHERE business_id = :b AND meter = :m"),
                             {"b": A, "m": f"outreach_topup_pence:{brand['id']}"}).scalar() or 0)


def live(db, brand, moment=NOW):
    with run_clock(), Session(db) as s:
        return billing().brand_live(s, A, brand["id"], moment)


def webhook(db, api, event_type="customer.subscription.updated", data=None, moment=NOW):
    """A Stripe event reaches the webhook: billing reconciles with Stripe's current state."""
    data = data if data is not None else {"id": "sub_mike", "customer": "cus_mike"}
    with run_clock(), Session(db) as s:
        billing().webhook(s, event_type, data, created=moment, api=api)
        s.commit()


def reconcile(db, api, moment, recover=True):
    """The scheduled check's reconcile (recover=True: it may re-send a page
    creation Stripe never confirmed); the webhook's passes recover=False."""
    api.now = moment
    with run_clock(), Session(db) as s:
        billing().reconcile(s, A, api=api, moment=moment, recover=recover)
        s.commit()


def check(db, api, moment):
    """The scheduled check: reconcile, then finish unconfirmed removals."""
    reconcile(db, api, moment)
    with run_clock(), Session(db) as s:
        billing().resend_removals(s, A, api=api, moment=moment)


def paid_brand_flow(db):
    biz, brand, lia, campaign = started(db)
    grandfather(db, brand)
    stripe_ids(db)
    fit, fit_lia = new_brand(db, biz)
    budget(db, biz)
    return biz, brand, fit, fit_lia


def refused(fn, *args, **kw):
    with run_clock(), pytest.raises(Exception) as exc:
        fn(*args, **kw)
    return exc.value


def add(db, biz, brand, api):
    with run_clock(), Session(db) as s:
        return billing().add_paid_brand(s, biz, OWNER, brand["id"], api=api)


def add_refused(db, biz, brand, api, user=OWNER):
    with Session(db) as s:
        return refused(billing().add_paid_brand, s, biz, user, brand["id"], api=api)


def remove(db, biz, brand, api):
    with run_clock(), Session(db) as s:
        return billing().remove_paid_brand(s, biz, OWNER, brand["id"], api=api)


def remove_refused(db, biz, brand, api):
    with Session(db) as s:
        return refused(billing().remove_paid_brand, s, biz, OWNER, brand["id"], api=api)


def paid_for(db, biz, brand, api):
    add(db, biz, brand, api)
    webhook(db, api)
    assert live(db, brand) is True


def topup(db, biz, brand, amount, api):
    with run_clock(), Session(db) as s:
        return billing().start_topup(s, biz, OWNER, brand["id"], amount, api=api, return_url="https://app.example/r")


def topup_refused(db, biz, brand, amount, api, user=OWNER):
    with Session(db) as s:
        return refused(billing().start_topup, s, biz, user, brand["id"], amount, api=api,
                       return_url="https://app.example/r")


def code(exc):
    return getattr(exc, "status_code", None)


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
    monkeypatch.delenv(unset)
    biz, brand, lia, campaign = started(db)
    stripe_ids(db)
    fit, fit_lia = new_brand(db, biz)
    assert live(db, brand) is True and live(db, fit) is True and entry(db, fit) is None


def test_status_shows_each_brands_billing_and_price(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    with run_clock(), Session(db) as s:
        out = billing().status(s, biz)
    rows = {r["brand_id"]: r for r in out["brands"]}
    assert rows[brand["id"]]["billing"] == "grandfathered" and rows[brand["id"]]["live"] is True
    assert rows[fit["id"]]["billing"] == "awaiting_payment" and rows[fit["id"]]["price_pence"] == 7900
    assert rows[fit["id"]]["live"] is False and out["topups_in_progress"] == []


# ------------------------------------------------------------- adding a brand ---

def test_a_paid_brand_gets_its_own_line_charged_pro_rata_now(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe(hold=True)
    out = add(db, biz, fit, api)
    made = api.named("Price.create")[0]
    assert made["product"] == f"prod_{EXTRA}" and made["unit_amount"] == 7900 and made["currency"] == "gbp"
    assert made["recurring"] == {"interval": "month"} and made["metadata"]["brand_id"] == fit["id"]
    call = api.named("Subscription.modify")[0]
    own = entry(db, fit)["price_id"]
    assert call["sub"] == "sub_mike" and call["items"] == [{"price": own, "quantity": 1}]
    assert call["proration_behavior"] == "always_invoice" and call["payment_behavior"] == "pending_if_incomplete"
    assert call["idempotency_key"] == f"outreach-brand-{entry(db, fit)['op']}"
    assert out["billing"] == "pending" and live(db, fit) is False
    assert committed(db, biz) == 9900 + 7900, "counted in the budget while it may be charged"


def test_a_misconfigured_stripe_price_charges_nothing(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe()
    api.base[EXTRA] = 7500                              # the Stripe price isn't £79
    assert code(add_refused(db, biz, fit, api)) == 503
    assert api.named("Subscription.modify") == [] and entry(db, fit)["state"] == "awaiting_payment"


def test_only_the_owner_adds_a_paid_brand(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe()
    assert code(add_refused(db, biz, fit, api, user=STAFF)) == 403 and api.calls == []


def test_a_brand_beyond_the_owners_budget_is_never_charged(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    budget(db, biz, 9900 + 7899)                      # £99 add-on committed; £79 more doesn't fit
    api = FakeStripe()
    exc = add_refused(db, biz, fit, api)
    assert code(exc) == 409 and "budget" in exc.detail and api.calls == []


def test_without_a_subscription_a_brand_cannot_be_added(db):
    biz, brand, lia, campaign = started(db)
    stripe_ids(db, subscription=None)
    fit, fit_lia = new_brand(db, biz)
    budget(db, biz)
    assert code(add_refused(db, biz, fit, FakeStripe())) == 409


def test_without_the_stripe_prices_set_nothing_is_charged(db, monkeypatch):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    monkeypatch.delenv("STRIPE_PRICE_EXTRA_BRAND")
    api = FakeStripe()
    assert code(add_refused(db, biz, fit, api)) == 503 and api.calls == []


def test_two_paid_brands_have_two_lines_and_neither_shares_the_others_place(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    second, second_lia = new_brand(db, biz, "Schools Outreach", age=timedelta(minutes=20))
    api = FakeStripe()
    paid_for(db, biz, fit, api)
    paid_for(db, biz, second, api)
    assert sorted(api.billed()) == sorted([entry(db, fit)["price_id"], entry(db, second)["price_id"]])
    assert entry(db, fit)["price_id"] != entry(db, second)["price_id"]


def test_a_second_change_waits_while_one_is_still_going_through(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    doc = settings(db)
    doc["outreach_brand_billing"]["op"] = {"token": "busy", "until": (NOW + timedelta(minutes=5)).isoformat()}
    save_settings(db, doc)
    api = FakeStripe()
    assert code(add_refused(db, biz, fit, api)) == 409 and api.calls == []
    assert entry(db, fit)["state"] == "awaiting_payment"


def test_no_addition_while_stripe_holds_an_unpaid_update(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    second, second_lia = new_brand(db, biz, "Schools Outreach", age=timedelta(minutes=20))
    api = FakeStripe(hold=True)
    add(db, biz, fit, api)
    assert code(add_refused(db, biz, second, api)) == 409 and len(api.named("Subscription.modify")) == 1
    assert entry(db, second)["state"] == "awaiting_payment" and entry(db, fit)["state"] == "pending"


# --------------------------------------------------------- Stripe confirms ---

def test_the_brand_goes_live_when_stripe_has_its_line_paid(db):
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
    """Stripe's CURRENT subscription decides, never the event's copy."""
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe()
    paid_for(db, biz, fit, api)
    stale = {"id": "sub_mike", "customer": "cus_mike", "items": {"data": [{"price": {"id": PLAN_PRO}, "quantity": 1}]}}
    webhook(db, api, data=stale)
    assert live(db, fit) is True


def test_an_answer_fetched_before_an_addition_finished_is_not_applied_over_it(db):
    """Codex review 2 P1 1: the check fetched Stripe, the owner's addition was
    paid and went live, then the check's older answer arrived."""
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe()
    real = api.Subscription.retrieve
    state = {"done": False}

    def stale_then_add(sub_id, **kw):
        snapshot = real(sub_id)           # before the addition: no line for the brand
        if not state["done"]:
            state["done"] = True
            paid_for(db, biz, fit, api)   # meanwhile: added, paid, live
        return snapshot
    api.Subscription.retrieve = staticmethod(stale_then_add)
    reconcile(db, api, LATER)
    assert entry(db, fit)["state"] == "active" and live(db, fit) is True


def test_an_event_for_a_business_without_outreach_billing_touches_nothing(db):
    started(db)
    stripe_ids(db, customer="cus_other", subscription="sub_other", bid=B)
    api = FakeStripe()
    webhook(db, api, data={"id": "sub_other", "customer": "cus_other"})
    webhook(db, api, "invoice.paid", {"subscription": "sub_nobody", "customer": "cus_nobody"})
    assert api.calls == []


def test_an_uncertain_addition_is_retried_as_the_identical_request(db):
    """A timeout before Stripe acted: the retry sends the same price under the same key."""
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe()
    api.fail["Subscription.modify"] = APIConnectionError("read timed out")
    exc = add_refused(db, biz, fit, api)
    assert code(exc) == 502 and "don't pay again" in exc.detail.lower()
    assert entry(db, fit)["state"] == "pending" and entry(db, fit)["uncertain"] is True
    assert committed(db, biz) == 9900 + 7900, "still counted: it may have been charged"
    add(db, biz, fit, api)
    first, second = api.named("Subscription.modify")
    assert first == second, "same parameters, same key"
    assert len(api.named("Price.create")) == 1
    webhook(db, api)
    assert live(db, fit) is True and len(api.billed()) == 1


def test_an_addition_that_went_through_but_whose_answer_was_lost_is_never_sent_twice(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe()
    api.fail["Subscription.modify"] = ("lost", APIConnectionError("connection reset"))
    add_refused(db, biz, fit, api)
    add(db, biz, fit, api)                             # the owner tries again
    assert len(api.named("Subscription.modify")) == 1, "Stripe already has it: nothing re-sent"
    reconcile(db, api, NOW)
    assert live(db, fit) is True and len(api.billed()) == 1


def test_a_declined_addition_goes_back_to_awaiting_payment(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe()
    api.fail["Subscription.modify"] = CardError()
    assert code(add_refused(db, biz, fit, api)) == 402
    assert entry(db, fit)["state"] == "awaiting_payment" and committed(db, biz) == 9900


def test_an_addition_whose_invoice_was_never_paid_can_be_tried_again(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe(hold=True)
    add(db, biz, fit, api)
    reconcile(db, api, LATER)
    assert entry(db, fit)["state"] == "pending", "Stripe still holds the update for payment"
    api.pending_items = None                           # Stripe's pending update expired unpaid
    reconcile(db, api, LATER)
    assert entry(db, fit)["state"] == "awaiting_payment" and "didn't go through" in entry(db, fit)["note"]
    assert committed(db, biz) == 9900
    api.hold = False
    add(db, biz, fit, api)
    webhook(db, api)
    assert live(db, fit) is True


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
    paid_for(db, biz, fit, api)
    own = entry(db, fit)["price_id"]
    out = remove(db, biz, fit, api)
    call = api.named("Subscription.modify")[-1]
    assert call["proration_behavior"] == "none" and call["items"] == [{"id": f"si_{own}", "deleted": True}]
    assert out["billing"] == "ending" and live(db, fit) is True, "paid until the end of the month"
    assert live(db, fit, AFTER_PERIOD) is False and api.billed() == []
    assert committed(db, biz, AFTER_PERIOD) == 9900, "a stopped brand stops counting in the budget"


def test_removing_one_brand_never_hands_its_place_to_another(db):
    """Codex review 2 P1 2: remove A (Stripe's answer lost before it acted), then add B."""
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    second, second_lia = new_brand(db, biz, "Schools Outreach", age=timedelta(minutes=20))
    api = FakeStripe()
    paid_for(db, biz, fit, api)
    api.fail["Subscription.modify"] = APIConnectionError("read timed out")
    assert code(remove_refused(db, biz, fit, api)) == 502
    assert entry(db, fit)["state"] == "ending" and entry(db, fit)["ends_at"]
    api.hold = True
    add(db, biz, second, api)
    assert api.named("Subscription.modify")[-1]["items"] == [{"price": entry(db, second)["price_id"], "quantity": 1}]
    reconcile(db, api, NOW)
    assert live(db, second) is False, "B waits for its own payment; A's paid line is A's"
    api.pay()
    check(db, api, NOW + timedelta(minutes=11))        # the operation claim has lapsed: A's removal is re-sent
    assert live(db, second) is True and api.billed() == [entry(db, second)["price_id"]]
    assert live(db, fit, AFTER_PERIOD) is False


def test_a_removal_that_cant_reach_stripe_changes_nothing(db):
    """Codex review 2 P1 3: the paid period's end is known before anything is recorded."""
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe()
    paid_for(db, biz, fit, api)
    api.fail["Subscription.retrieve"] = APIConnectionError("timed out")
    assert code(remove_refused(db, biz, fit, api)) == 502
    assert entry(db, fit)["state"] == "active" and len(api.billed()) == 1


def test_an_unconfirmed_removal_is_re_sent_and_ends_on_time(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe()
    paid_for(db, biz, fit, api)
    api.fail["Subscription.modify"] = APIConnectionError("read timed out")
    remove_refused(db, biz, fit, api)
    with run_clock(), Session(db) as s:
        assert {r["brand_id"]: r for r in billing().status(s, biz)["brands"]}[fit["id"]]["checking"] is True
    check(db, api, NOW + timedelta(minutes=11))
    first, again = api.named("Subscription.modify")[-2:]
    assert first == again and api.billed() == []
    assert live(db, fit) is True and live(db, fit, AFTER_PERIOD + timedelta(days=100)) is False


def test_a_refused_removal_leaves_the_brand_paid_and_live(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe()
    paid_for(db, biz, fit, api)
    api.fail["Subscription.modify"] = InvalidRequestError("no")
    assert code(remove_refused(db, biz, fit, api)) == 409
    assert entry(db, fit)["state"] == "active" and "ends_at" not in entry(db, fit)


def test_no_removal_while_stripe_holds_an_unpaid_update(db):
    """Codex review 2 P1 4: removing would replace the waiting update."""
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    second, second_lia = new_brand(db, biz, "Schools Outreach", age=timedelta(minutes=20))
    api = FakeStripe()
    paid_for(db, biz, fit, api)
    api.hold = True
    add(db, biz, second, api)
    sent = len(api.named("Subscription.modify"))
    assert code(remove_refused(db, biz, fit, api)) == 409
    assert len(api.named("Subscription.modify")) == sent and api.pending_items
    assert entry(db, fit)["state"] == "active"


# ------------------------------------------------------------------ top-ups ---

def test_a_top_up_opens_stripes_payment_page_reserved_first(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe()
    out = topup(db, biz, brand, 2500, api)
    call = api.named("checkout.Session.create")[0]
    key = call["metadata"]["reservation"]
    assert call["mode"] == "payment" and call["customer"] == "cus_mike"
    assert call["line_items"][0]["price_data"]["unit_amount"] == 2500
    assert call["line_items"][0]["price_data"]["currency"] == "gbp"
    assert call["metadata"] == {"kind": "outreach_topup", "outreach_business_id": A, "brand_id": brand["id"],
                                "reservation": key}
    assert call["payment_intent_data"] == {"metadata": call["metadata"]}
    assert call["expires_at"] == int((NOW + timedelta(minutes=60)).timestamp())
    assert call["payment_method_types"] == ["card"], "settles at once: nothing delayed holds the budget"
    assert call["idempotency_key"] == f"outreach-topup-{key}"
    assert out == {"status": "checkout", "checkout_url": "https://pay.example/cs_1"}
    assert committed(db, biz) == 9900 + 2500 and purchases(db)[key]["checkout_id"] == "cs_1"


@pytest.mark.parametrize("amount", [999, 1500, 7500, 0, -1000])
def test_only_the_three_top_up_sizes_are_offered(db, amount):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe()
    assert code(topup_refused(db, biz, brand, amount, api)) == 422 and api.calls == []


def test_a_paid_page_is_credited_once_and_raises_the_allowance(db):
    from services import outreach_allowance
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe()
    with run_clock(), Session(db) as s:
        before = outreach_allowance.allowance_pence(s, A, brand["id"], "2026-10")
    topup(db, biz, brand, 2500, api)
    page = api.pay_page("cs_1")
    webhook(db, api, "checkout.session.completed", page)
    webhook(db, api, "checkout.session.completed", page)     # a second delivery: never twice
    reconcile(db, api, SOON)                                  # nor from the scheduled check
    with run_clock(), Session(db) as s:
        assert outreach_allowance.allowance_pence(s, A, brand["id"], "2026-10") == before + 2500 // 3
    assert topped_up(db, brand) == 2500 and purchases(db) == {} and committed(db, biz) == 9900 + 2500


def test_a_paid_page_found_by_the_scheduled_check_is_credited(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe()
    topup(db, biz, brand, 1000, api)
    api.pay_page("cs_1")                                      # the webhook never arrived
    reconcile(db, api, SOON)
    assert topped_up(db, brand) == 1000 and purchases(db) == {}


def test_an_expired_page_releases_its_reservation(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe()
    topup(db, biz, brand, 2500, api)
    reconcile(db, api, SOON)
    assert committed(db, biz) == 9900 + 2500, "an open page may still be paid"
    webhook(db, api, "checkout.session.expired", api.expire_page("cs_1"))
    assert committed(db, biz) == 9900 and topped_up(db, brand) == 0


def test_one_paid_page_releases_only_its_own_reservation(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe()
    topup(db, biz, brand, 2500, api)
    topup(db, biz, brand, 2500, api)
    webhook(db, api, "checkout.session.completed", api.pay_page("cs_1"))
    assert len(purchases(db)) == 1 and committed(db, biz) == 9900 + 5000


def test_a_page_stripe_refused_to_open_releases_its_reservation(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe()
    api.fail["checkout.Session.create"] = InvalidRequestError("no")
    assert code(topup_refused(db, biz, brand, 5000, api)) == 409 and committed(db, biz) == 9900


@pytest.mark.parametrize("lost", [False, True])
def test_an_unconfirmed_page_is_recovered_with_the_same_request(db, lost):
    """Codex review 2 P1 5: the page may exist; its reservation stays until Stripe settles it."""
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe()
    failure = APIConnectionError("read timed out")
    api.fail["checkout.Session.create"] = ("lost", failure) if lost else failure
    assert code(topup_refused(db, biz, brand, 2500, api)) == 502
    assert committed(db, biz) == 9900 + 2500
    reconcile(db, api, SOON)
    first, again = api.named("checkout.Session.create")
    assert first == again and len(api.pages) == 1, "one page, ever"
    (key, purchase), = purchases(db).items()
    assert purchase["checkout_id"] == "cs_1"
    api.pay_page("cs_1")
    reconcile(db, api, SOON)
    assert topped_up(db, brand) == 2500 and purchases(db) == {}


def test_a_page_never_confirmed_is_held_until_stripes_webhooks_have_had_their_chance(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe()
    api.fail["checkout.Session.create"] = APIConnectionError("read timed out")
    topup_refused(db, biz, brand, 2500, api)
    api.fail["checkout.Session.create"] = APIConnectionError("still down")
    reconcile(db, api, SOON)
    reconcile(db, api, NOW + timedelta(days=3))
    assert committed(db, biz) == 9900 + 2500
    reconcile(db, api, NOW + timedelta(days=4, minutes=1))
    assert purchases(db) == {}


def test_two_top_ups_never_pass_the_budget(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    budget(db, biz, 9900 + 5000)                       # room for £50 of top-ups, once
    api = FakeStripe()
    topup(db, biz, brand, 5000, api)
    assert code(topup_refused(db, biz, brand, 1000, api)) == 409
    assert len(api.named("checkout.Session.create")) == 1


def test_a_top_up_needs_a_live_brand_and_the_owner(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    for user, target in ((STAFF, brand), (OWNER, fit)):   # not the owner; a brand not yet paid for
        api = FakeStripe()
        assert code(topup_refused(db, biz, target, 1000, api, user=user)) in (403, 409) and api.calls == []


@pytest.mark.parametrize("change", [{"customer": "cus_someone_else"}, {"currency": "usd"}, {"amount_total": 5000},
                                    {"id": "cs_other"}, {"metadata.brand_id": "not-a-brand"},
                                    {"metadata.outreach_business_id": B}, {"metadata.reservation": "someone-else"}])
@pytest.mark.parametrize("path", ["webhook", "scheduled check"])
def test_a_page_that_isnt_this_reservations_is_never_credited(db, change, path):
    """Codex review 2 P1 6: one check, on both paths, against the purchase reserved."""
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe()
    topup(db, biz, brand, 2500, api)
    page = api.pay_page("cs_1")
    (field, value), = change.items()
    if field.startswith("metadata."):
        page["metadata"] = dict(page["metadata"], **{field.split(".")[1]: value})
    else:
        page[field] = value
    if path == "webhook":
        webhook(db, api, "checkout.session.completed", page)
    else:
        api.pages["cs_1"] = page
        reconcile(db, api, SOON)
    assert topped_up(db, brand) == 0 and committed(db, biz) == 9900 + 2500, "the reservation stays for review"


def test_a_paid_page_with_no_reservation_credits_nothing(db):
    """Codex review 2 P1 6: never a fabricated purchase."""
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    page = {"id": "cs_x", "status": "complete", "payment_status": "paid", "customer": "cus_mike", "currency": "gbp",
            "amount_total": 5000, "metadata": {"kind": "outreach_topup", "outreach_business_id": A,
                                               "brand_id": brand["id"], "reservation": "made-up"}}
    webhook(db, FakeStripe(), "checkout.session.completed", page)
    assert topped_up(db, brand) == 0



# ------------------------------------------------- Codex review 3 regressions ---

def test_a_failed_retry_never_forgets_an_addition_that_may_have_been_charged(db):
    """P1 1: the first attempt was carried out (answer lost); the retry's read
    is then refused by Stripe. The first attempt's identity must survive."""
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe()
    api.fail["Subscription.modify"] = ("lost", APIConnectionError("connection reset"))
    add_refused(db, biz, fit, api)
    first = dict(entry(db, fit))
    api.fail["Subscription.retrieve"] = InvalidRequestError("rate limited")
    exc = add_refused(db, biz, fit, api)
    assert code(exc) == 502 and "don't pay again" in exc.detail.lower()
    kept = entry(db, fit)
    assert (kept["state"], kept["op"], kept["price_id"], kept["uncertain"]) == ("pending", first["op"], first["price_id"], True)
    add(db, biz, fit, api)
    reconcile(db, api, NOW)
    assert live(db, fit) is True and len(api.billed()) == 1, "one line, charged once"


def test_no_other_change_can_slip_between_a_removals_read_and_its_deletion(db):
    """P1 2: the removal claims the subscription before reading it, so an
    addition arriving in between waits rather than leaving a payment pending."""
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    second, second_lia = new_brand(db, biz, "Schools Outreach", age=timedelta(minutes=20))
    api = FakeStripe()
    paid_for(db, biz, fit, api)
    real = api.Subscription.retrieve
    seen = {}

    def read_then_someone_adds(sub_id, **kw):
        snapshot = real(sub_id)
        if "added" not in seen:
            api.hold = True
            seen["added"] = add_refused(db, biz, second, api)
        return snapshot
    api.Subscription.retrieve = staticmethod(read_then_someone_adds)
    remove(db, biz, fit, api)
    assert code(seen["added"]) == 409, "the addition waited for the removal"
    assert api.pending_items is None and entry(db, second)["state"] == "awaiting_payment"


def test_the_scheduled_check_never_removes_while_another_change_holds_the_subscription(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe()
    paid_for(db, biz, fit, api)
    api.fail["Subscription.modify"] = APIConnectionError("read timed out")
    remove_refused(db, biz, fit, api)
    doc = settings(db)
    doc["outreach_brand_billing"]["op"] = {"token": "busy", "until": (NOW + timedelta(hours=1)).isoformat()}
    save_settings(db, doc)
    sent = len(api.named("Subscription.modify"))
    check(db, api, NOW + timedelta(minutes=11))
    assert len(api.named("Subscription.modify")) == sent and len(api.billed()) == 1


def test_a_removal_finished_after_a_renewal_keeps_the_brand_for_the_month_paid(db):
    """P1 3: the deletion never reached Stripe; the line renewed (and was paid)
    before the scheduled check finished the removal."""
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe()
    paid_for(db, biz, fit, api)
    api.fail["Subscription.modify"] = APIConnectionError("read timed out")
    remove_refused(db, biz, fit, api)
    renewed = PERIOD_END + 30 * 24 * 3600
    for item in api.items:
        item["current_period_end"] = renewed
    check(db, api, AFTER_PERIOD)
    assert api.billed() == [], "billing stopped"
    assert live(db, fit, AFTER_PERIOD) is True, "the renewed month was paid for"
    assert live(db, fit, datetime.fromtimestamp(renewed, tz=timezone.utc) + timedelta(minutes=1)) is False
    assert entry(db, fit).get("uncertain") is None


def test_a_page_re_sent_ten_minutes_on_still_meets_stripes_expiry_rule(db):
    """P2 1: Stripe needs 30 minutes from creation; the fake now enforces it."""
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe()
    api.fail["checkout.Session.create"] = APIConnectionError("never arrived")
    topup_refused(db, biz, brand, 2500, api)
    reconcile(db, api, NOW + timedelta(minutes=29))
    assert len(api.pages) == 1 and list(purchases(db).values())[0]["checkout_id"] == "cs_1"


def test_a_failed_delayed_payment_releases_its_reservation(db):
    """P2 2 (cards settle at once; this is the backstop)."""
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe()
    topup(db, biz, brand, 2500, api)
    page = dict(api.pages["cs_1"], status="complete", payment_status="unpaid")
    webhook(db, api, "checkout.session.async_payment_failed", page)
    assert committed(db, biz) == 9900 and topped_up(db, brand) == 0


# ------------------------------------------------- Codex review 4 regressions ---

def test_a_check_never_abandons_an_addition_whose_retry_is_in_flight(db):
    """P1 1: an unconfirmed addition, an hour old, is retried; the check runs
    between the retry's read and its request. It must not clear the addition."""
    from unittest import mock
    from services import outreach_send
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe()
    api.fail["Subscription.modify"] = APIConnectionError("never arrived")
    add_refused(db, biz, fit, api)
    real = api.Subscription.retrieve

    once = []

    def read_then_check(sub_id, **kw):
        snapshot = real(sub_id)
        if not once:
            once.append(1)
            reconcile(db, api, LATER)      # sees no line and no update: the addition looks abandoned
        return snapshot
    api.Subscription.retrieve = staticmethod(read_then_check)
    with run_clock(), mock.patch.object(outreach_send, "now", lambda: LATER), Session(db) as s:
        billing().add_paid_brand(s, biz, OWNER, fit["id"], api=api)
    api.Subscription.retrieve = staticmethod(real)
    reconcile(db, api, LATER)
    assert live(db, fit) is True and len(api.billed()) == 1
    assert code(add_refused(db, biz, fit, api)) == 409, "nothing left to pay: no second line"


def test_a_renewal_is_honoured_even_while_another_payment_is_pending(db):
    """P1 2: the deletion waits for the pending payment; the renewed month still counts."""
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    second, second_lia = new_brand(db, biz, "Schools Outreach", age=timedelta(minutes=20))
    api = FakeStripe()
    paid_for(db, biz, fit, api)
    api.fail["Subscription.modify"] = APIConnectionError("read timed out")
    remove_refused(db, biz, fit, api)
    renewed = PERIOD_END + 30 * 24 * 3600
    for item in api.items:
        item["current_period_end"] = renewed
    api.hold = True
    doc = settings(db)                     # the removal's claim has lapsed; another brand is added: payment pending
    doc["outreach_brand_billing"]["op"] = {}
    save_settings(db, doc)
    add(db, biz, second, api)
    sent = len(api.named("Subscription.modify"))
    check(db, api, AFTER_PERIOD)
    assert len(api.named("Subscription.modify")) == sent, "no deletion while a payment is pending"
    assert live(db, fit, AFTER_PERIOD) is True, "the renewed month was paid for"
    assert entry(db, fit)["ends_at"] == datetime.fromtimestamp(renewed, tz=timezone.utc).isoformat()


@pytest.mark.parametrize("action", ["add", "remove"])
def test_a_stripe_set_up_error_never_leaves_the_subscription_claimed(db, monkeypatch, action):
    """P2 1."""
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    if action == "remove":
        paid_for(db, biz, fit, FakeStripe())
    def broken():
        raise RuntimeError("Stripe key unreadable")
    monkeypatch.setattr(billing(), "_stripe", broken)
    with Session(db) as s:
        fn = billing().add_paid_brand if action == "add" else billing().remove_paid_brand
        refused(fn, s, biz, OWNER, fit["id"])
    assert not (settings(db)["outreach_brand_billing"].get("op") or {}).get("token")


def test_the_scheduled_finish_of_a_removal_never_leaves_the_subscription_claimed(db, monkeypatch):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe()
    paid_for(db, biz, fit, api)
    api.fail["Subscription.modify"] = APIConnectionError("read timed out")
    remove_refused(db, biz, fit, api)
    def broken():
        raise RuntimeError("Stripe key unreadable")
    monkeypatch.setattr(billing(), "_stripe", broken)
    with run_clock(), Session(db) as s:
        try:
            billing().resend_removals(s, A, moment=NOW + timedelta(minutes=11))
        except RuntimeError:
            pass
    assert not (settings(db)["outreach_brand_billing"].get("op") or {}).get("token")


def test_the_webhook_never_creates_a_payment_page(db):
    """P2 2: only the scheduled check re-sends an unconfirmed page creation."""
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe()
    api.fail["checkout.Session.create"] = APIConnectionError("never arrived")
    topup_refused(db, biz, brand, 2500, api)
    api.now = SOON
    from unittest import mock
    from services import outreach_send
    with run_clock(), mock.patch.object(outreach_send, "now", lambda: SOON), Session(db) as s:   # ten minutes on
        billing().webhook(s, "invoice.paid", {"subscription": "sub_mike", "customer": "cus_mike"}, created=SOON, api=api)
        s.commit()
    assert len(api.named("checkout.Session.create")) == 1 and api.pages == {}
    reconcile(db, api, SOON)               # the scheduled check does recover it
    assert len(api.pages) == 1


# ------------------------------------------------- Codex review 5 regressions ---

def test_a_check_spanning_a_retry_whose_answer_was_lost_never_clears_it(db):
    """P2: the check reads Stripe; a retry then adds the line but its answer
    is lost (claim released, still "uncertain"); the check's older answer must
    not clear the addition, or the next Add would charge a second line."""
    from unittest import mock
    from services import outreach_send
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe()
    api.fail["Subscription.modify"] = APIConnectionError("never arrived")
    add_refused(db, biz, fit, api)
    real = api.Subscription.retrieve
    once = []

    def read_then_retry(sub_id, **kw):
        snapshot = real(sub_id)            # before the line exists
        if not once:
            once.append(1)
            api.fail["Subscription.modify"] = ("lost", APIConnectionError("connection reset"))
            api.Subscription.retrieve = staticmethod(real)
            with mock.patch.object(outreach_send, "now", lambda: LATER), Session(db) as s:
                refused(billing().add_paid_brand, s, biz, OWNER, fit["id"], api=api)
        return snapshot
    api.Subscription.retrieve = staticmethod(read_then_retry)
    with run_clock(), Session(db) as s:
        billing().reconcile(s, A, api=api, moment=LATER)
        s.commit()
    assert entry(db, fit)["state"] == "pending" and entry(db, fit).get("price_id")
    reconcile(db, api, LATER)
    assert live(db, fit) is True and len(api.billed()) == 1
    assert code(add_refused(db, biz, fit, api)) == 409, "nothing left to pay: no second line"


def test_an_active_brand_is_never_paused_by_a_check_while_a_change_is_in_progress(db):
    biz, brand, fit, fit_lia = paid_brand_flow(db)
    api = FakeStripe()
    paid_for(db, biz, fit, api)
    doc = settings(db)
    doc["outreach_brand_billing"]["op"] = {"token": "busy", "until": (LATER + timedelta(minutes=5)).isoformat()}
    save_settings(db, doc)
    stale = FakeStripe()                   # an answer without the brand's line
    reconcile(db, stale, LATER)
    assert entry(db, fit)["state"] == "active" and live(db, fit) is True

# ----------------------------------------------------------- the wiring ---

def test_the_stripe_webhook_hands_events_to_billing_first_inside_its_retry_boundary():
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
    import inspect
    import outreach_setup_api as api
    assert "/app/outreach/settings" in inspect.getsource(api._return_url)


@pytest.mark.parametrize("who,code_", [(OWNER, 200), (STAFF, 403)])
def test_the_billing_endpoints(db, monkeypatch, who, code_):
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
    assert (added.status_code, topped.status_code) == (code_, code_) and bad.status_code == 422
    assert (len(fake.calls) > 0) == (code_ == 200)
    if code_ == 200:
        assert topped.json()["checkout_url"] == "https://pay.example/cs_1"
