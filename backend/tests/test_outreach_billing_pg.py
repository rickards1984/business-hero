"""OUT-19 F on real PostgreSQL, through the real Stripe webhook endpoint
(Codex review 1: behavioural webhook tests, and the transaction they share):
an ordinary customer's event is accepted untouched; a paid brand goes live
when Stripe has its own line paid; a paid top-up page is credited once; and the webhook takes its
locks in the same order as the owner's billing actions, so the two can't
deadlock."""
# ruff: noqa: F811 - the pg fixture is a parameter by design
import json
import threading
import time
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlmodel import Session

from test_outreach_send_rls import DATABASE_URL, pg  # noqa: F401
from test_outreach_send import A, B, BRAND, NOW

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="RLS_LOCAL_DATABASE_URL is not set")

PRICE_PRO, PRICE_ADDON, PRICE_EXTRA = "price_pg_pro", "price_outreach_addon", "price_extra_brand"
OWN_PRICE = "price_brand_pg"              # the brand's own Stripe price (one line per brand)
ENV = {"STRIPE_SECRET_KEY": "sk_test_not_a_real_key", "STRIPE_WEBHOOK_SECRET": "whsec_test", "APP_BASE_URL": "https://example.invalid",
       "STRIPE_PRICE_STARTER": "price_pg_starter", "STRIPE_PRICE_PRO": PRICE_PRO,
       "STRIPE_PRICE_BUSINESS": "price_pg_business",
       "STRIPE_PRICE_OUTREACH_ADDON": PRICE_ADDON, "STRIPE_PRICE_EXTRA_BRAND": PRICE_EXTRA}


def fake_stripe(paid):
    from test_outreach_billing import FakeStripe
    api = FakeStripe()
    if paid:
        api._apply([{"price": OWN_PRICE, "quantity": 1}])
    return api


@pytest.fixture
def paid(pg, monkeypatch):
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    with pg.engine.begin() as c:
        for bid, customer in ((A, "cus_pg"), (B, "cus_pg_other")):
            c.execute(text("UPDATE businesses SET plan_tier = 'starter', stripe_customer_id = :c, "
                           "stripe_subscription_id = :s WHERE id = :b"),
                      {"c": customer, "s": customer.replace("cus", "sub"), "b": bid})
        raw = c.execute(text("SELECT settings::text FROM business_settings WHERE business_id = :b"), {"b": A}).scalar()
        doc = json.loads(raw or "{}")
        doc["outreach_brand_billing"] = {"brands": {BRAND: {"state": "pending", "price": 9900, "op": "op-pg",
                                                             "price_id": OWN_PRICE, "requested_at": NOW.isoformat()}}}
        c.execute(text("UPDATE business_settings SET settings = CAST(:s AS jsonb) WHERE business_id = :b"),
                  {"s": json.dumps(doc), "b": A})
    yield pg
    with pg.engine.begin() as c:
        c.execute(text("DELETE FROM stripe_events WHERE business_id IN (:a, :b) OR event_id LIKE 'evt_pg_%'"),
                  {"a": A, "b": B})


def event(event_id, customer):
    return {"id": event_id, "type": "customer.subscription.updated", "created": int(NOW.timestamp()),
            "data": {"object": {"id": customer.replace("cus", "sub"), "customer": customer, "status": "active",
                                "items": {"data": [{"id": "si_plan", "price": {"id": PRICE_PRO}, "quantity": 1,
                                                    "current_period_end": int((NOW + timedelta(days=20)).timestamp())}]}}}}


def post(engine, monkeypatch, body):
    from fastapi.testclient import TestClient
    import main
    from db import get_session
    monkeypatch.setattr(main.stripe.Webhook, "construct_event", lambda payload, sig, secret: body)
    main.app.dependency_overrides[get_session] = lambda: Session(engine)
    try:
        return TestClient(main.app).post("/v1/billing/webhook", content=json.dumps(body).encode(),
                                         headers={"stripe-signature": "t=1,v1=x"})
    finally:
        main.app.dependency_overrides.pop(get_session, None)


def live(engine):
    from services import outreach_billing
    with Session(engine) as s:
        return outreach_billing.brand_live(s, A, BRAND, NOW)


def test_an_ordinary_customers_event_is_accepted_and_stripe_is_not_asked(paid, monkeypatch):
    """Review 1 P1 1: a business with no outreach billing (and none set up)."""
    from services import outreach_billing
    monkeypatch.setattr(outreach_billing, "_stripe", lambda: pytest.fail("Stripe is never asked about it"))
    response = post(paid.engine, monkeypatch, event("evt_pg_other", "cus_pg_other"))
    assert response.status_code == 200, response.text
    with paid.engine.connect() as c:
        assert c.execute(text("SELECT business_id FROM stripe_events WHERE event_id = 'evt_pg_other'")).scalar() is not None


def test_a_paid_brand_goes_live_through_the_real_webhook(paid, monkeypatch):
    from services import outreach_billing
    api = fake_stripe(paid=False)
    monkeypatch.setattr(outreach_billing, "_stripe", lambda: api)
    assert post(paid.engine, monkeypatch, event("evt_pg_1", "cus_pg")).status_code == 200
    assert live(paid.engine) is False, "Stripe doesn't have it paid yet"
    api._apply([{"price": OWN_PRICE, "quantity": 1}])
    assert post(paid.engine, monkeypatch, event("evt_pg_2", "cus_pg")).status_code == 200
    assert live(paid.engine) is True
    with paid.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM stripe_events WHERE event_id LIKE 'evt_pg_%'")).scalar() == 2


def test_when_stripe_cant_be_reached_the_event_is_retried_and_nothing_is_kept(paid, monkeypatch):
    from services import outreach_billing
    api = fake_stripe(paid=True)

    def down(*a, **k):
        raise ConnectionError("Stripe unreachable")
    api.Subscription.retrieve = staticmethod(down)
    monkeypatch.setattr(outreach_billing, "_stripe", lambda: api)
    assert post(paid.engine, monkeypatch, event("evt_pg_down", "cus_pg")).status_code == 503
    with paid.engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM stripe_events WHERE event_id = 'evt_pg_down'")).scalar() == 0
        assert c.execute(text("SELECT plan_tier FROM businesses WHERE id = :b"), {"b": A}).scalar() == "starter"


def test_a_paid_top_up_page_is_credited_once_through_the_real_webhook(paid, monkeypatch):
    """Codex review 2: end to end, not the service alone."""
    with paid.engine.begin() as c:
        raw = c.execute(text("SELECT settings::text FROM business_settings WHERE business_id = :b"), {"b": A}).scalar()
        doc = json.loads(raw)
        doc["outreach_brand_billing"]["purchases"] = {"r-pg": {"amount": 2500, "brand_id": BRAND, "checkout_id": "cs_pg",
                                                               "at": NOW.isoformat(), "return_url": "https://x"}}
        c.execute(text("UPDATE business_settings SET settings = CAST(:s AS jsonb) WHERE business_id = :b"),
                  {"s": json.dumps(doc), "b": A})
    page = {"id": "cs_pg", "object": "checkout.session", "status": "complete", "payment_status": "paid",
            "customer": "cus_pg", "currency": "gbp", "amount_total": 2500,
            "metadata": {"kind": "outreach_topup", "outreach_business_id": A, "brand_id": BRAND, "reservation": "r-pg"}}
    for n in (1, 2):                      # two distinct deliveries of the same payment
        body = {"id": f"evt_pg_page_{n}", "type": "checkout.session.completed", "created": int(NOW.timestamp()),
                "data": {"object": page}}
        assert post(paid.engine, monkeypatch, body).status_code == 200
    with paid.engine.connect() as c:
        assert float(c.execute(text("SELECT coalesce(sum(value), 0) FROM usage_meters WHERE business_id = :b "
                                    "AND meter = :m"), {"b": A, "m": f"outreach_topup_pence:{BRAND}"}).scalar()) == 2500
        doc = json.loads(c.execute(text("SELECT settings::text FROM business_settings WHERE business_id = :b"),
                                   {"b": A}).scalar())
        assert doc["outreach_brand_billing"]["purchases"] == {}


def test_the_webhook_and_the_owners_billing_lock_in_the_same_order(paid, monkeypatch):
    """The owner's billing actions lock business_settings, then businesses.
    The webhook must not hold businesses while it waits for business_settings,
    or the two deadlock. Synchronised on PostgreSQL itself."""
    from services import outreach_billing
    api = fake_stripe(paid=True)
    monkeypatch.setattr(outreach_billing, "_stripe", lambda: api)
    owner = Session(paid.engine)
    owner.execute(text("SELECT 1 FROM business_settings WHERE business_id = :b FOR UPDATE"), {"b": A})
    mine = owner.execute(text("SELECT pg_backend_pid()")).scalar()
    result = {}
    worker = threading.Thread(
        target=lambda: result.update(r=post(paid.engine, monkeypatch, event("evt_pg_order", "cus_pg"))))
    worker.start()
    try:
        deadline = time.monotonic() + 10
        with paid.engine.connect() as watch:
            while time.monotonic() < deadline:
                if watch.execute(text("SELECT count(*) FROM pg_stat_activity WHERE :p = ANY(pg_blocking_pids(pid))"),
                                 {"p": mine}).scalar():
                    break
                watch.rollback()    # pg_stat_activity is one snapshot per transaction: a fresh one each poll
                time.sleep(0.05)
            else:
                pytest.fail("the webhook never waited for the owner's lock")
        owner.execute(text("SET LOCAL lock_timeout = '3s'"))
        owner.execute(text("SELECT 1 FROM businesses WHERE id = :b FOR UPDATE"), {"b": A})   # must not wait
        owner.commit()
    finally:
        owner.close()
        worker.join(timeout=20)
    assert result["r"].status_code == 200, result["r"].text
    assert live(paid.engine) is True
