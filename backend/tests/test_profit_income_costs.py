"""PROFIT-2 — real income and a running-costs tracker (docs/PROFIT-2-TICKET.md).
RED: it changes what the profit guard's alarm and kill switch compare.

Mike, 31 Oct 2026: income is each business's REAL monthly charge (its last
full monthly Stripe invoice, after discounts, before VAT; plan price only as a
marked estimate until one is recorded), plus top-ups; cash received is shown
but never drives the alarm. Running costs are an itemised monthly list that
carries forward and can be corrected; PLATFORM_FIXED_COSTS_PENCE is the
fallback while no list exists.

Tests first: strict xfail until Mike approves and the modules exist. No
network: Stripe is a fake.
"""
import importlib
import importlib.util
import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlmodel import Session

NOW = datetime(2026, 10, 27, 9, tzinfo=timezone.utc)
PERIOD = "2026-10"


class Missing(AssertionError):
    """Only the intentional absence of the modules may be xfailed."""


pytestmark = pytest.mark.xfail(strict=True, raises=Missing,
                               reason="PROFIT-2: tests first, until Mike approves and the modules exist")


def module(name):
    if importlib.util.find_spec(f"services.{name}") is None:
        raise Missing(f"backend/services/{name}.py does not exist yet")
    return importlib.import_module(f"services.{name}")


def income():
    return module("stripe_income")


def costs():
    return module("running_costs")


def guard():
    module("stripe_income")
    module("running_costs")
    return importlib.import_module("services.profit_guard")


@pytest.fixture
def engine(tmp_path, monkeypatch):
    for name in ("AI_MONTHLY_KILL_PENCE", "AI_MONTHLY_ALARM_PENCE", "PLATFORM_FIXED_COSTS_PENCE",
                 "PROFIT_TRIAL_BUDGET_PENCE", "PROFIT_ALARM_PERCENT", "PROFIT_KILL_PERCENT",
                 "VOICE_COST_PENCE_PER_MINUTE", "PROFIT_ALERT_FROM_ACCOUNT", "PROFIT_ALERT_TO"):
        monkeypatch.delenv(name, raising=False)
    e = create_engine("sqlite:///" + str(tmp_path / "profit2.sqlite"))
    with e.begin() as c:
        c.execute(text("CREATE TABLE usage_meters (business_id TEXT, meter TEXT, period TEXT, value NUMERIC, "
                       "updated_at TEXT, UNIQUE (business_id, meter, period))"))
        c.execute(text("CREATE TABLE businesses (id TEXT PRIMARY KEY, name TEXT, plan_tier TEXT, "
                       "subscription_status TEXT, is_active BOOLEAN, feature_flags TEXT, "
                       "stripe_customer_id TEXT, stripe_subscription_id TEXT)"))
        c.execute(text("CREATE TABLE platform_meters (period TEXT NOT NULL, meter TEXT NOT NULL, "
                       "value NUMERIC NOT NULL DEFAULT 0, updated_at TEXT, PRIMARY KEY (period, meter))"))
    from services import ai_costs
    ai_costs._PLATFORM_TABLE.clear()
    yield e
    e.dispose()


def business(engine, bid, plan="pro", *, status="active", customer=None, subscription=None, flags=None):
    with engine.begin() as c:
        c.execute(text("INSERT INTO businesses VALUES (:b, :n, :p, :s, :a, :f, :c, :sub)"),
                  {"b": bid, "n": bid, "p": plan, "s": status, "a": True, "f": json.dumps(flags or {}),
                   "c": customer, "sub": subscription})


def invoice(ident, *, customer="cus_a", subscription="sub_a", paid=2900, tax=0, reason="subscription_cycle",
            currency="gbp", when=NOW):
    return {"id": ident, "object": "invoice", "customer": customer, "subscription": subscription,
            "amount_paid": paid, "tax": tax, "currency": currency, "billing_reason": reason, "status": "paid",
            "status_transitions": {"paid_at": int(when.timestamp())}}


def record(engine, inv):
    with Session(engine) as s:
        out = income().record_invoice(s, inv)
        s.commit()
        return out


def status(engine, moment=NOW):
    with Session(engine) as s:
        return guard().status(s, moment=moment)


def meter(engine, bid, name, period=PERIOD):
    with engine.connect() as c:
        return c.execute(text("SELECT value FROM usage_meters WHERE business_id = :b AND meter = :m AND period = :p"),
                         {"b": bid, "m": name, "p": period}).scalar()


# ------------------------------------------------------------------ income ---

def test_a_business_counts_its_real_monthly_charge_not_its_list_price(engine):
    business(engine, "mike", "pro", customer="cus_a", subscription="sub_a")
    record(engine, invoice("in_1", paid=150))                  # Mike's £1.50 test subscription
    out = status(engine)
    assert out["income_pence"] == 150
    assert out["income_detail"]["recurring_real_pence"] == 150 and out["income_detail"]["estimated_businesses"] == 0


def test_without_an_invoice_the_plan_price_is_used_and_marked_estimated(engine):
    business(engine, "new", "business")
    out = status(engine)
    assert out["income_pence"] == 26900
    assert out["income_detail"]["recurring_estimated_pence"] == 26900 and out["income_detail"]["estimated_businesses"] == 1


def test_vat_is_not_income(engine):
    business(engine, "a", customer="cus_a", subscription="sub_a")
    record(engine, invoice("in_1", paid=15480, tax=2580))
    assert status(engine)["income_pence"] == 12900


def test_an_invoice_is_counted_once(engine):
    business(engine, "a", customer="cus_a", subscription="sub_a")
    assert record(engine, invoice("in_1")) is True
    assert record(engine, invoice("in_1")) is False
    assert meter(engine, "a", "stripe_paid_pence") == 2900


def test_a_proration_is_cash_not_recurring(engine):
    """A brand added mid-month: real money, but not next month's charge."""
    business(engine, "a", customer="cus_a", subscription="sub_a")
    record(engine, invoice("in_cycle", paid=12900))
    record(engine, invoice("in_pro", paid=4000, reason="subscription_update"))
    out = status(engine)
    assert out["income_pence"] == 12900 and out["income_detail"]["cash_received_pence"] == 16900


def test_the_latest_full_monthly_invoice_is_the_charge(engine):
    business(engine, "a", customer="cus_a", subscription="sub_a")
    record(engine, invoice("in_sep", paid=12900, when=datetime(2026, 9, 27, tzinfo=timezone.utc)))
    record(engine, invoice("in_oct", paid=20800, when=datetime(2026, 10, 27, tzinfo=timezone.utc)))
    assert status(engine)["income_pence"] == 20800
    nov = status(engine, moment=datetime(2026, 11, 3, tzinfo=timezone.utc))
    assert nov["income_pence"] == 20800, "carried until the next monthly invoice"
    assert nov["income_detail"]["cash_received_pence"] == 0


def test_an_older_invoice_arriving_late_never_replaces_a_newer_charge(engine):
    business(engine, "a", customer="cus_a", subscription="sub_a")
    record(engine, invoice("in_new", paid=20800, when=datetime(2026, 10, 27, tzinfo=timezone.utc)))
    record(engine, invoice("in_old", paid=12900, when=datetime(2026, 10, 2, tzinfo=timezone.utc)))
    assert status(engine)["income_pence"] == 20800


@pytest.mark.parametrize("change", [{"currency": "usd"}, {"customer": "cus_nobody", "subscription": "sub_nobody"}])
def test_an_invoice_in_another_currency_or_for_nobody_changes_nothing(engine, change):
    business(engine, "a", "pro", customer="cus_a", subscription="sub_a")
    assert record(engine, {**invoice("in_x", paid=5), **change}) is False
    assert status(engine)["income_pence"] == 12900, "still the estimate"


def test_a_complimentary_or_inactive_business_brings_no_income(engine):
    business(engine, "msc", "business", flags={"complimentary": True})
    business(engine, "gone", "pro", status="canceled")
    assert status(engine)["income_pence"] == 0


def test_top_ups_still_count(engine):
    business(engine, "a", customer="cus_a", subscription="sub_a")
    record(engine, invoice("in_1", paid=12900))
    with engine.begin() as c:
        c.execute(text("INSERT INTO usage_meters VALUES ('a', 'outreach_topup_pence:brand', :p, 2500, :t)"),
                  {"p": PERIOD, "t": NOW.isoformat()})
    assert status(engine)["income_pence"] == 12900 + 2500


def test_the_trial_budget_is_still_a_floor(engine, monkeypatch):
    monkeypatch.setenv("PROFIT_TRIAL_BUDGET_PENCE", "20000")
    business(engine, "mike", customer="cus_a", subscription="sub_a")
    record(engine, invoice("in_1", paid=150))
    out = status(engine)
    assert out["income_pence"] == 20000 and out["income_basis"] == "trial budget"


def test_who_costs_more_than_they_pay_uses_the_real_charge(engine):
    business(engine, "mike", customer="cus_a", subscription="sub_a")
    record(engine, invoice("in_1", paid=150))
    with engine.begin() as c:
        c.execute(text("INSERT INTO usage_meters VALUES ('mike', 'ai_pence', :p, 900, :t)"), {"p": PERIOD, "t": NOW.isoformat()})
    losing = status(engine)["losing"]
    assert losing and losing[0]["pays_pence"] == 150


def test_refresh_from_stripe_records_each_paid_invoice_once(engine):
    business(engine, "a", customer="cus_a", subscription="sub_a")
    business(engine, "b", "business")                          # no Stripe customer: skipped

    class Invoices:
        calls = []

        @staticmethod
        def list(**kw):
            Invoices.calls.append(kw)
            return {"data": [invoice("in_2", paid=20800, when=datetime(2026, 10, 1, tzinfo=timezone.utc)),
                             invoice("in_1", paid=12900, when=datetime(2026, 9, 1, tzinfo=timezone.utc))]}
    api = type("Api", (), {"Invoice": Invoices})
    for _ in range(2):
        with Session(engine) as s:
            income().refresh(s, api=api)
            s.commit()
    assert Invoices.calls[0]["customer"] == "cus_a" and Invoices.calls[0]["status"] == "paid"
    assert all(set(c) <= {"customer", "status", "limit"} for c in Invoices.calls), "read only"
    assert status(engine)["income_pence"] == 20800 + 26900
    assert meter(engine, "a", "stripe_paid_pence") == 20800


def test_the_webhook_records_paid_invoices_inside_its_retry_boundary():
    import inspect
    income()
    import main
    source = inspect.getsource(main.stripe_webhook)
    at = source.index("stripe_income.webhook(")
    block = source[at:]
    assert block.index("status_code=503") < block.index("session.add(StripeEvent")
    assert at < source.index("session.add(business)"), "before the handler writes the business row"


def test_the_webhook_entry_point_ignores_other_events(engine):
    business(engine, "a", customer="cus_a", subscription="sub_a")
    with Session(engine) as s:
        income().webhook(s, "invoice.created", invoice("in_1"))
        income().webhook(s, "invoice.paid", invoice("in_2"))
        s.commit()
    assert meter(engine, "a", "stripe_paid_pence") == 2900


# ----------------------------------------------------------- running costs ---

def items(engine, period=PERIOD):
    with Session(engine) as s:
        return {i["name"]: i["pence"] for i in costs().items(s, period)}


def put(engine, name, pence, period=PERIOD, moment=NOW):
    with Session(engine) as s:
        costs().set_item(s, period, name, pence, moment=moment)
        s.commit()


def test_bills_are_itemised_and_summed_into_fixed_costs(engine):
    put(engine, "Railway", 2000)
    put(engine, "Vercel", 1600)
    put(engine, "Supabase", 2000)
    assert items(engine) == {"Railway": 2000, "Vercel": 1600, "Supabase": 2000}
    assert status(engine)["costs"]["fixed_pence"] == 5600


def test_the_list_carries_forward_without_writing_and_a_month_can_be_corrected(engine):
    put(engine, "Railway", 2000, period="2026-09", moment=NOW)
    put(engine, "Vercel", 1600, period="2026-09", moment=NOW)
    with engine.connect() as c:
        before = c.execute(text("SELECT count(*) FROM platform_meters")).scalar()
    assert items(engine) == {"Railway": 2000, "Vercel": 1600}   # October shows September's bills
    assert status(engine)["costs"]["fixed_pence"] == 3600
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM platform_meters")).scalar() == before, "reading never writes"
    put(engine, "Railway", 2350)                                # October's actual Railway bill
    assert items(engine) == {"Railway": 2350, "Vercel": 1600}
    assert items(engine, "2026-09") == {"Railway": 2000, "Vercel": 1600}, "September is unchanged"


def test_a_bill_can_be_removed_from_a_month(engine):
    put(engine, "Railway", 2000, period="2026-09")
    put(engine, "Twilio number", 115, period="2026-09")
    with Session(engine) as s:
        costs().remove_item(s, PERIOD, "Twilio number", moment=NOW)
        s.commit()
    assert items(engine) == {"Railway": 2000}
    assert items(engine, "2026-09") == {"Railway": 2000, "Twilio number": 115}


def test_an_emptied_month_stays_empty(engine):
    put(engine, "Railway", 2000, period="2026-09")
    with Session(engine) as s:
        costs().remove_item(s, PERIOD, "Railway", moment=NOW)
        s.commit()
    assert items(engine) == {} and status(engine)["costs"]["fixed_pence"] == 0


def test_without_a_list_the_railway_figure_is_used(engine, monkeypatch):
    monkeypatch.setenv("PLATFORM_FIXED_COSTS_PENCE", "8500")
    assert status(engine)["costs"]["fixed_pence"] == 8500
    put(engine, "Railway", 2000)
    assert status(engine)["costs"]["fixed_pence"] == 2000


@pytest.mark.parametrize("name,pence,period", [
    ("", 100, PERIOD), ("x" * 61, 100, PERIOD), ("Bad;name", 100, PERIOD), ("Railway", -1, PERIOD),
    ("Railway", 10_000_001, PERIOD), ("Railway", 1.5, PERIOD), ("Railway", 100, "2026-11"),   # a future month
    ("Railway", 100, "2024-09"), ("Railway", 100, "2026-13")])
def test_bad_bills_are_refused(engine, name, pence, period):
    running = costs()
    with Session(engine) as s, pytest.raises(Exception) as exc:
        running.set_item(s, period, name, pence, moment=NOW)
    assert getattr(exc.value, "status_code", None) == 422


def test_six_months_of_history(engine):
    business(engine, "a", customer="cus_a", subscription="sub_a")
    record(engine, invoice("in_sep", paid=12900, when=datetime(2026, 9, 20, tzinfo=timezone.utc)))
    put(engine, "Railway", 2000, period="2026-09")
    out = status(engine)["history"]
    assert [h["period"] for h in out] == ["2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"]
    sep = out[4]
    assert sep["income_pence"] == 12900 and sep["costs_pence"] == 2000 and sep["margin_pence"] == 10900


# --------------------------------------------------------------- endpoints ---

def test_only_platform_admins_reach_costs_and_refresh():
    import inspect
    module("stripe_income")
    import admin_profit_api
    source = inspect.getsource(admin_profit_api)
    for path in ('"/costs"', '"/refresh-income"'):
        assert path in source
    assert source.count("get_platform_admin_context") >= 5
