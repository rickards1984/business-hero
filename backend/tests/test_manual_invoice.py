"""BH-010 (RC1 P0-5) — an owner can create an invoice without a quote.

Today there is no POST /v1/invoices: Finance offers CSV upload only
(`docs/CURRENT_STATE.md` §6, confirmed end to end in July). A contractor who
did not quote through the product cannot invoice through it.

Stage 1: tests first. Money is RED (AGENTS.md §2), so Mike reviews these
before any implementation. Every new-behaviour test is a strict xfail that
may fail ONLY because the module does not exist yet; any other error fails.

The contract these tests fix:
  POST /v1/invoices  (new router `backend/invoices_api.py`)
  body: customer_name*, customer_email, customer_address, invoice_date,
        supply_date, due_date, lines*[{description*, quantity*, unit,
        unit_cost*, discount_amount, discount_type}], discount_amount,
        discount_type. Money as strings or numbers; converted ONLY by
        services.money.to_decimal.
  201 -> the stored invoice with its number, totals as strings to the penny.

Totals come from services.money.calculate_totals — the same engine quote
conversion uses — and the tax rate from the business's own settings
(quoting_api._quote_tax_context), never 20% by assumption. The number comes
from services.invoice_numbering.allocate, never COUNT(*) and never the
client. The address and supply date need migration 034 (Mike, 8 Oct 2026).

The real numbering and money code runs against an in-memory SQLite database
holding two businesses. The real login dependency, read-only refusal and
feature gate run; only the token check and the business lookups are
substituted. SQLite proves scoping and arithmetic, not PostgreSQL types,
constraints or RLS.
"""

import importlib
import importlib.util
import os
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

for _key in ("SUPABASE_DATABASE_URL", "DATABASE_URL"):
    if os.getenv(_key) and not os.environ[_key].startswith("sqlite"):
        raise RuntimeError("REFUSING TO RUN: non-SQLite database configured")

import pytest  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import Session  # noqa: E402


class MissingManualInvoices(AssertionError):
    """Only this precise, intentional Stage 1 absence may be xfailed."""


pending = pytest.mark.xfail(
    strict=True, raises=MissingManualInvoices,
    reason="BH-010: tests first; implementation follows Mike's review",
)

A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
D = Decimal

# The money engine's worked example (test_invoice_conversion.py): per-line
# tax at 20%, ROUND_HALF_UP, then summed.
#   100.00 -> 20.00 | 250.50 -> 50.10 | 33.33 -> 6.67
#   subtotal 383.83 | tax 76.77 | gross 460.60
LINES = [
    {"description": "Labour", "quantity": "1", "unit": "day", "unit_cost": "100.00"},
    {"description": "Materials", "quantity": "1", "unit": "each", "unit_cost": "250.50"},
    {"description": "Disposal", "quantity": "1", "unit": "each", "unit_cost": "33.33"},
]


def target():
    if importlib.util.find_spec("invoices_api") is None:
        raise MissingManualInvoices("backend/invoices_api.py does not exist yet")
    return importlib.import_module("invoices_api")


SCHEMA = """
CREATE TABLE businesses (id TEXT PRIMARY KEY, name TEXT, region TEXT,
  tax_registered BOOLEAN, timezone TEXT);
CREATE TABLE quote_settings (business_id TEXT UNIQUE, next_invoice_number INTEGER,
  invoice_prefix TEXT, default_tax_rate TEXT);
CREATE TABLE invoices (id TEXT PRIMARY KEY, business_id TEXT NOT NULL,
  invoice_number TEXT NOT NULL, customer_name TEXT, customer_email TEXT,
  customer_address TEXT, invoice_date TEXT, issue_date TEXT, supply_date TEXT,
  due_date TEXT, subtotal TEXT, tax_amount TEXT, amount TEXT, amount_due TEXT,
  currency TEXT, status TEXT, source TEXT, source_ref TEXT,
  archived BOOLEAN DEFAULT 0, chase_stage INTEGER DEFAULT 0,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (business_id, invoice_number));
CREATE TABLE invoice_line_items (
  id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))), invoice_id TEXT,
  category TEXT, description TEXT, quantity TEXT, unit TEXT, unit_cost TEXT,
  line_total TEXT, discount_amount TEXT, discount_type TEXT,
  apportioned_discount TEXT, taxable TEXT, tax_rate TEXT, tax_amount TEXT,
  tax_treatment TEXT, sort_order INTEGER, group_name TEXT);
"""


@pytest.fixture
def database():
    # PostgreSQL's driver binds Decimal natively; sqlite3 does not. Store it as
    # its exact text form for the life of the test, then remove the adapter
    # so no other test inherits it.
    import sqlite3
    key = (Decimal, sqlite3.PrepareProtocol)
    previous = sqlite3.adapters.get(key)
    sqlite3.register_adapter(Decimal, str)
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    with Session(engine) as s:
        for stmt in SCHEMA.split(";"):
            if stmt.strip():
                s.execute(text(stmt))
        s.execute(text("INSERT INTO businesses VALUES (:a,'A Plumbing','UK',1,'Europe/London')"),
                  {"a": A})
        s.execute(text("INSERT INTO businesses VALUES (:b,'B Builders','UK',1,'Europe/London')"),
                  {"b": B})
        s.execute(text("INSERT INTO quote_settings VALUES (:a,1,'INV-','20')"), {"a": A})
        s.execute(text("INSERT INTO quote_settings VALUES (:b,1,'BB-','20')"), {"b": B})
        s.commit()
    yield engine
    engine.dispose()
    if previous is None:
        sqlite3.adapters.pop(key, None)
    else:
        sqlite3.adapters[key] = previous


def _rows(engine, sql, **params):
    with Session(engine) as s:
        return s.execute(text(sql), params).mappings().all()


def client_for(database, monkeypatch, business=A, status="active", is_active=True,
               invoicing=True):
    module = target()
    import auth
    import db
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    entitlement = SimpleNamespace(
        id=business, subscription_status=status, is_active=is_active,
        trial_ends_at=None, plan_tier="starter", feature_flags={"invoicing": invoicing})

    async def _verify(token):
        return SimpleNamespace(id="owner-" + business[:4], email="owner@example.com")

    monkeypatch.setattr(auth, "verify_supabase_token", _verify)
    monkeypatch.setattr(auth, "is_platform_admin_user", lambda *a, **k: False)
    monkeypatch.setattr(auth, "get_business_for_user",
                        lambda user_id, requested_business_id=None: SimpleNamespace(id=business))
    monkeypatch.setattr(auth, "_load_business", lambda session, bid: entitlement)

    class GateSession(Session):
        """The feature gate loads the ORM Business; everything else is SQL."""
        def exec(self, statement, *a, **k):
            from models import Business
            if statement.column_descriptions[0]["entity"] is Business:
                return SimpleNamespace(first=lambda: entitlement)
            return super().exec(statement, *a, **k)

    def sessions():
        with GateSession(database) as s:
            yield s

    app = FastAPI()
    app.include_router(module.router)
    app.dependency_overrides[db.get_session] = sessions
    client = TestClient(app)
    client.headers["Authorization"] = "Bearer synthetic"
    return client


def create(client, **overrides):
    body = {"customer_name": "Sam Carter", "customer_email": "sam@example.com",
            "customer_address": "1 High Street, Bath BA1 1AA",
            "invoice_date": "2026-10-08", "lines": LINES}
    body.update(overrides)
    return client.post("/v1/invoices", json=body)


# ------------------------------------------------------------- the money ---

def test_totals_come_from_the_money_engine_to_the_penny(database, monkeypatch):
    r = create(client_for(database, monkeypatch))
    assert r.status_code == 201, r.text
    body = r.json()
    assert (body["subtotal"], body["tax_amount"], body["amount"]) == ("383.83", "76.77", "460.60")
    [inv] = _rows(database, "SELECT * FROM invoices WHERE business_id = :b", b=A)
    assert (D(inv["subtotal"]), D(inv["tax_amount"]), D(inv["amount"])) == \
        (D("383.83"), D("76.77"), D("460.60"))
    assert D(inv["amount_due"]) == D("460.60")
    assert inv["status"] == "unpaid" and inv["source"] == "manual"


def test_every_line_is_stored_with_its_own_tax(database, monkeypatch):
    create(client_for(database, monkeypatch))
    lines = _rows(database, "SELECT * FROM invoice_line_items ORDER BY sort_order")
    assert [ln["description"] for ln in lines] == ["Labour", "Materials", "Disposal"]
    assert [D(ln["tax_amount"]) for ln in lines] == [D("20.00"), D("50.10"), D("6.67")]
    assert all(D(ln["tax_rate"]) == D("20") for ln in lines)
    # The header is the sum of the lines, exactly — one derivation, not two.
    total_net = sum(D(ln["taxable"]) for ln in lines)
    total_tax = sum(D(ln["tax_amount"]) for ln in lines)
    [inv] = _rows(database, "SELECT subtotal, tax_amount FROM invoices")
    assert (total_net, total_tax) == (D(inv["subtotal"]), D(inv["tax_amount"]))


def test_a_business_not_registered_for_vat_charges_none(database, monkeypatch):
    with Session(database) as s:
        s.execute(text("UPDATE businesses SET tax_registered = 0 WHERE id = :a"), {"a": A})
        s.commit()
    body = create(client_for(database, monkeypatch)).json()
    assert body["tax_amount"] == "0.00" and body["amount"] == "383.83"


def test_a_zero_default_rate_stays_zero(database, monkeypatch):
    """The `rate or 20` trap (test_tax_registration.py), on the invoice path."""
    with Session(database) as s:
        s.execute(text("UPDATE quote_settings SET default_tax_rate = '0' WHERE business_id = :a"),
                  {"a": A})
        s.commit()
    body = create(client_for(database, monkeypatch)).json()
    assert body["tax_amount"] == "0.00"


def test_a_rate_sent_by_the_client_is_ignored(database, monkeypatch):
    """The rate is the business's, not whatever the browser sends."""
    body = create(client_for(database, monkeypatch), tax_rate="0").json()
    assert body["tax_amount"] == "76.77"


def test_money_is_exact_with_no_float_drift(database, monkeypatch):
    """2.675 must round to 2.68; Decimal(2.675) from a float gives 2.67."""
    r = create(client_for(database, monkeypatch),
               lines=[{"description": "Washer", "quantity": "1", "unit_cost": 2.675}])
    assert r.status_code == 201, r.text
    assert r.json()["subtotal"] == "2.68"


def test_an_invoice_discount_is_applied_and_apportioned(database, monkeypatch):
    body = create(client_for(database, monkeypatch),
                  discount_amount="83.83", discount_type="fixed").json()
    # Net 383.83 - 83.83 = 300.00 taxable; VAT 60.00; gross 360.00.
    assert body["tax_amount"] == "60.00" and body["amount"] == "360.00"


# ------------------------------------------------------------- numbering ---

def test_numbers_come_from_the_atomic_counter_per_business(database, monkeypatch):
    a = client_for(database, monkeypatch, business=A)
    assert create(a).json()["invoice_number"] == "INV-0001"
    assert create(a).json()["invoice_number"] == "INV-0002"
    b = client_for(database, monkeypatch, business=B)
    assert create(b).json()["invoice_number"] == "BB-0001"
    [row] = _rows(database, "SELECT next_invoice_number FROM quote_settings WHERE business_id = :a", a=A)
    assert row["next_invoice_number"] == 3


def test_the_client_cannot_choose_the_number(database, monkeypatch):
    """HMRC: unique and sequential. A number typed by the user breaks the
    sequence, so it is refused rather than silently ignored."""
    r = create(client_for(database, monkeypatch), invoice_number="INV-9999")
    assert r.status_code == 422
    assert _rows(database, "SELECT * FROM invoices") == []


# -------------------------------------------- what HMRC needs on the record ---

def test_address_and_dates_are_stored(database, monkeypatch):
    create(client_for(database, monkeypatch), supply_date="2026-10-06", due_date="2026-11-07")
    [inv] = _rows(database, "SELECT * FROM invoices")
    assert inv["customer_address"] == "1 High Street, Bath BA1 1AA"
    assert inv["invoice_date"] == "2026-10-08"
    assert inv["supply_date"] == "2026-10-06"
    assert inv["due_date"] == "2026-11-07"


def test_due_date_defaults_to_thirty_days_after_the_invoice(database, monkeypatch):
    create(client_for(database, monkeypatch))
    [inv] = _rows(database, "SELECT due_date FROM invoices")
    assert inv["due_date"] == (date(2026, 10, 8) + timedelta(days=30)).isoformat()


def test_invoice_date_defaults_to_today_in_the_business_timezone(database, monkeypatch):
    body = {"customer_name": "Sam", "lines": LINES}
    r = client_for(database, monkeypatch).post("/v1/invoices", json=body)
    assert r.status_code == 201, r.text
    [inv] = _rows(database, "SELECT invoice_date FROM invoices")
    assert inv["invoice_date"], "an invoice must carry its date"


# ------------------------------------------------------------ validation ---

@pytest.mark.parametrize("overrides,why", [
    ({"lines": []}, "no lines"),
    ({"customer_name": "  "}, "no customer"),
    ({"lines": [{"description": "x", "quantity": "0", "unit_cost": "10"}]}, "zero quantity"),
    ({"lines": [{"description": "x", "quantity": "1", "unit_cost": "-10"}]}, "negative price"),
    ({"lines": [{"description": "", "quantity": "1", "unit_cost": "10"}]}, "no description"),
    ({"lines": [{"description": "x", "quantity": "1", "unit_cost": "NaN"}]}, "NaN"),
    ({"lines": [{"description": "x", "quantity": "1", "unit_cost": "0"}]}, "nothing to pay"),
    ({"due_date": "2026-10-01"}, "due before the invoice date"),
    ({"discount_amount": "500", "discount_type": "fixed"}, "discount exceeds the net"),
])
def test_invalid_invoices_are_refused_and_nothing_is_written(database, monkeypatch, overrides, why):
    r = create(client_for(database, monkeypatch), **overrides)
    assert r.status_code == 422, f"{why}: {r.status_code} {r.text}"
    assert _rows(database, "SELECT * FROM invoices") == [], why
    assert _rows(database, "SELECT * FROM invoice_line_items") == [], why
    [row] = _rows(database, "SELECT next_invoice_number FROM quote_settings WHERE business_id = :a", a=A)
    assert row["next_invoice_number"] == 1, f"{why}: a refused invoice must not use up a number"


# --------------------------------------------------- isolation and access ---

def test_the_invoice_belongs_to_the_callers_business_whatever_the_body_says(database, monkeypatch):
    create(client_for(database, monkeypatch, business=A), business_id=B)
    rows = _rows(database, "SELECT business_id FROM invoices")
    assert [r["business_id"] for r in rows] == [A]
    assert _rows(database, "SELECT * FROM invoices WHERE business_id = :b", b=B) == []


@pytest.mark.parametrize("status,is_active,invoicing,why", [
    ("unpaid", False, True, "read-only: unpaid"),
    ("canceled", False, True, "read-only: cancelled"),
    ("active", False, True, "suspended by an admin"),
    ("active", True, False, "invoicing not on the plan"),
])
def test_creation_is_refused_without_full_access(database, monkeypatch, status, is_active,
                                                 invoicing, why):
    """Creating is a mutation: DECISION 3 refuses it for read-only accounts,
    which may still VIEW and EXPORT (BH-009's PDF) but not issue new ones."""
    r = create(client_for(database, monkeypatch, status=status, is_active=is_active,
                          invoicing=invoicing))
    assert r.status_code == 403, f"{why}: {r.status_code}"
    assert _rows(database, "SELECT * FROM invoices") == [], why


# ------------------------------------------ quote conversion (decision 2) ---

def _convert_capturing():
    """Run the real convert_to_invoice against the conversion suite's fake."""
    from tests.test_invoice_conversion import QUOTE, ConversionSession, convert
    session = ConversionSession(quote={**QUOTE, "customer_address": "9 Quote Lane, Leeds LS1 1AA"})
    convert(session)
    return session.params_for("INSERT INTO invoices")


def test_conversion_copies_the_quote_address_as_a_snapshot():
    assert _convert_capturing().get("customer_address") == "9 Quote Lane, Leeds LS1 1AA"


def test_conversion_records_the_invoice_date():
    assert _convert_capturing().get("invoice_date"), "decision 2: conversion records the date"



# --------------------------------------------- Codex BH-010 review 1 additions ---

@pytest.mark.parametrize("line,why", [
    ({"description": "x", "quantity": "0.0004", "unit_cost": "10000"},
     "quantity finer than the 3 places stored"),
    ({"description": "x", "quantity": "1", "unit_cost": "2.67501"},
     "price finer than the 4 places stored"),
    ({"description": "x", "quantity": "1", "unit_cost": "10", "discount_amount": "1.005"},
     "line discount finer than the 2 places stored"),
])
def test_amounts_finer_than_storage_are_refused(database, monkeypatch, line, why):
    """Codex review 1, finding 1: calculating with 0.0004 but storing 0.000
    leaves a line whose stored figures no longer produce its stored total.
    Refuse rather than round silently."""
    r = create(client_for(database, monkeypatch), lines=[line])
    assert r.status_code == 422, f"{why}: {r.status_code} {r.text}"
    assert _rows(database, "SELECT * FROM invoices") == [], why


def test_storage_precision_itself_is_accepted(database, monkeypatch):
    r = create(client_for(database, monkeypatch),
               lines=[{"description": "Cable", "quantity": "12.125", "unit_cost": "1.2345"}])
    assert r.status_code == 201, r.text


@pytest.mark.parametrize("line,why", [
    ({"description": "x", "quantity": "1", "unit_cost": "10",
      "discount_amount": "200", "discount_type": "percentage"}, "200% off one line"),
    ({"description": "x", "quantity": "1", "unit_cost": "10",
      "discount_amount": "15", "discount_type": "fixed"}, "£15 off a £10 line"),
    ({"description": "x", "quantity": "1", "unit_cost": "10",
      "discount_amount": "1", "discount_type": "bogus"}, "unknown discount type"),
])
def test_each_line_discount_is_checked_on_its_own(database, monkeypatch, line, why):
    """Codex review 1, finding 2: another line must not be able to hide a
    line whose discount exceeds it — that line would carry negative VAT."""
    lines = [line, {"description": "Other work", "quantity": "1", "unit_cost": "100"}]
    r = create(client_for(database, monkeypatch), lines=lines)
    assert r.status_code == 422, f"{why}: {r.status_code} {r.text}"
    assert _rows(database, "SELECT * FROM invoices") == [], why


def test_aria_can_read_the_new_invoice_fields_for_her_business_only(database, monkeypatch):
    """North Star Gate 7 (Codex review 1, finding 3): data the app stores is
    data Aria can read, through a tenant-scoped tool."""
    import assistant_tools
    create(client_for(database, monkeypatch, business=A),
           customer_address="1 High Street, Bath BA1 1AA", supply_date="2026-10-06")
    create(client_for(database, monkeypatch, business=B),
           customer_name="B Private Customer", customer_address="B private address")
    result = assistant_tools._list_invoices(database, A, {})
    assert result["count"] == 1
    [inv] = result["invoices"]
    assert inv["customer_address"] == "1 High Street, Bath BA1 1AA"
    assert inv["invoice_date"] == "2026-10-08"
    assert inv["supply_date"] == "2026-10-06"
    flat = str(result)
    assert "B private" not in flat and "B Private Customer" not in flat
