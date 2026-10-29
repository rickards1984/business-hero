"""OUT-19 F on real PostgreSQL: a paid brand goes live when Stripe shows it
paid, a top-up is credited once, through the real schema's businesses columns,
settings document and meters, under the business lock."""
# ruff: noqa: F811 - the pg fixture is a parameter by design
import json

import pytest
from sqlalchemy import text
from sqlmodel import Session

from test_outreach_send_rls import DATABASE_URL, pg  # noqa: F401
from test_outreach_send import A, BRAND, NOW

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="RLS_LOCAL_DATABASE_URL is not set")


@pytest.fixture
def paid(pg, monkeypatch):
    monkeypatch.setenv("STRIPE_PRICE_OUTREACH_ADDON", "price_addon")
    monkeypatch.setenv("STRIPE_PRICE_EXTRA_BRAND", "price_extra")
    with pg.engine.begin() as c:
        c.execute(text("UPDATE businesses SET plan_tier = 'pro', stripe_customer_id = 'cus_pg', "
                       "stripe_subscription_id = 'sub_pg' WHERE id = :b"), {"b": A})
        raw = c.execute(text("SELECT settings::text FROM business_settings WHERE business_id = :b"), {"b": A}).scalar()
        doc = json.loads(raw or "{}")
        doc["outreach_brand_billing"] = {"brands": {BRAND: {"state": "pending", "price": 9900,
                                                             "requested_at": NOW.isoformat()}}, "pending": {}, "paid": []}
        c.execute(text("UPDATE business_settings SET settings = CAST(:s AS jsonb) WHERE business_id = :b"),
                  {"s": json.dumps(doc), "b": A})
    yield pg


def test_a_paid_brand_goes_live_on_postgres(paid):
    from services import outreach_billing
    with Session(paid.engine) as s:
        assert outreach_billing.brand_live(s, A, BRAND, NOW) is False
        s.rollback()
        outreach_billing.apply_subscription(s, {"id": "sub_pg", "customer": "cus_pg", "status": "active",
                                                "items": {"data": [{"id": "si", "price": {"id": "price_addon"},
                                                                    "quantity": 1}]}})
        s.commit()
    with Session(paid.engine) as s:
        assert outreach_billing.brand_live(s, A, BRAND, NOW) is True


def test_a_top_up_is_credited_once_on_postgres(paid):
    from services import outreach_billing
    intent = {"id": "pi_pg", "amount": 2500, "amount_received": 2500,
              "metadata": {"kind": "outreach_topup", "business_id": A, "brand_id": BRAND}}
    for _ in range(2):
        with Session(paid.engine) as s:
            outreach_billing.apply_payment_intent(s, "payment_intent.succeeded", intent, created=NOW)
            s.commit()
    with paid.engine.connect() as c:
        assert float(c.execute(text("SELECT coalesce(sum(value), 0) FROM usage_meters WHERE business_id = :b "
                                    "AND meter = :m"), {"b": A, "m": f"outreach_topup_pence:{BRAND}"}).scalar()) == 2500
