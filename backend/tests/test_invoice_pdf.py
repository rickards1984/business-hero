"""BH-009 approved Stage 1 contract and Stage 2 decision regressions.

Text assertions observe ReportLab's real text drawing, not mocked PDF bytes.
Visual layout and PDF-reader extraction remain separate verification.
"""
import asyncio
import importlib
import importlib.util
import os
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session

# Before ANY app import: db.py may connect during import. Never print secrets.
for _key in ("SUPABASE_DATABASE_URL", "DATABASE_URL"):
    if os.getenv(_key) and not os.environ[_key].startswith("sqlite"):
        raise RuntimeError("REFUSING TO RUN: non-SQLite database configured")


class MissingInvoicePDF(AssertionError):
    """A missing implementation is now an ordinary contract-test failure."""


D = Decimal
A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
IA = "11111111-1111-4111-8111-111111111111"
IB = "22222222-2222-4222-8222-222222222222"


def target(name):
    if importlib.util.find_spec(name) is None:
        raise MissingInvoicePDF(f"Required BH-009 module {name} does not exist")
    return importlib.import_module(name)


@pytest.fixture(autouse=True)
def no_external_io(monkeypatch):
    """An accidental network or default-database use is a hard failure."""
    import socket
    from sqlalchemy.engine import Engine

    original = Engine.connect

    def connect(engine, *args, **kwargs):
        assert engine.url.get_backend_name() == "sqlite"
        assert engine.url.database in (None, "", ":memory:"), "disk DB forbidden"
        return original(engine, *args, **kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError("Network access forbidden in BH-009 tests")

    monkeypatch.setattr(Engine, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


@pytest.fixture
def document():
    return {
        "invoice": dict(invoice_number="INV-2026-0042", customer_name="A Customer",
                        customer_address="22 Customer Road, Bristol BS1 2AA",
                        issue_date=date(2026, 9, 29), tax_point=date(2026, 9, 28),
                        subtotal=D("100.00"), tax_amount=D("18.00"),
                        discount_amount=D("10.00"), amount=D("108.00"),
                        currency="GBP", source="quote"),
        "line_items": [dict(description="Replace copper pipe", quantity=D("2"),
                            unit_cost=D("50.0000"), line_total=D("100.00"),
                            discount_amount=D("0"), apportioned_discount=D("10.00"),
                            taxable=D("90.00"), tax_rate=D("20"),
                            tax_amount=D("18.00"), tax_treatment="standard")],
        "business": dict(name="A Plumbing Ltd", region="UK", tax_registered=True,
                         tax_number="GB123456789"),
        "settings": dict(company_name="A Plumbing Ltd",
                         company_address="11 Supplier Street, Bath BA1 1AA"),
    }


@pytest.fixture
def rendered_text(monkeypatch):
    from reportlab.pdfgen.textobject import PDFTextObject

    fragments = []
    original = PDFTextObject._formatText

    def record(obj, value, *args, **kwargs):
        fragments.append(value)
        return original(obj, value, *args, **kwargs)

    monkeypatch.setattr(PDFTextObject, "_formatText", record)
    return fragments


def render(document, fragments):
    module = target("services.invoice_pdf")
    payload = asyncio.run(module.generate_invoice_pdf(**document))
    assert isinstance(payload, bytes)
    assert payload.startswith(b"%PDF-") and b"%%EOF" in payload[-1024:]
    assert len(payload) > 500
    return " ".join(" ".join(fragments).split())


def test_pdf_text_observer_sees_real_reportlab_output(rendered_text):
    """Unmarked harness check: currency and text observation actually work."""
    import io
    from reportlab.pdfgen.canvas import Canvas

    output = io.BytesIO()
    canvas = Canvas(output)
    canvas.drawString(10, 10, "Probe £2.68 $9.99")
    canvas.save()
    assert "Probe £2.68 $9.99" in rendered_text
    assert output.getvalue().startswith(b"%PDF-")


def test_registered_invoice_has_required_identity_dates_and_line_fields(document, rendered_text):
    result = render(document, rendered_text)
    assert "vat invoice" in result.lower() or "tax invoice" in result.lower()
    for expected in ("A Plumbing Ltd", "11 Supplier Street", "BA1 1AA",
                     "GB123456789", "INV-2026-0042", "29/09/2026", "28/09/2026",
                     "A Customer", "22 Customer Road", "BS1 2AA",
                     "Replace copper pipe", "2", "£50.00", "20%", "£100.00"):
        assert expected in result
    for label in ("description", "quantity", "unit price", "excluding vat", "tax point"):
        assert label in result.lower()


def test_stored_discount_and_header_totals_are_not_recalculated(document, rendered_text):
    # Deliberate mismatch: existing records are authoritative, even when lines
    # would yield other totals. Never silently rewrite issued header amounts.
    document["invoice"].update(subtotal=D("123.45"), tax_amount=D("22.69"),
                               amount=D("136.14"))
    result = render(document, rendered_text)
    for expected in ("£123.45", "£22.69", "£136.14", "£10.00"):
        assert expected in result
    assert "discount" in result.lower()
    assert "total payable" in result.lower()
    assert "total vat" in result.lower()
    assert "£108.00" not in result


@pytest.mark.parametrize("stale_rate", [D("0"), D("20")])
def test_unregistered_omits_all_vat_even_with_stale_settings(document, rendered_text, stale_rate):
    document["business"]["tax_registered"] = False
    document["settings"]["vat_number"] = "STALE-VAT-NUMBER"
    document["line_items"][0].update(tax_rate=stale_rate, tax_amount=D("0"))
    document["invoice"].update(tax_amount=D("0"), amount=D("90.00"))
    result = render(document, rendered_text)
    assert "invoice" in result.lower()
    assert "vat" not in result.lower()
    assert "%" not in result
    assert "GB123456789" not in result
    assert "STALE-VAT-NUMBER" not in result
    assert "£90.00" in result


def test_registered_zero_rate_is_not_replaced_by_twenty(document, rendered_text):
    document["line_items"][0].update(tax_rate=D("0"), tax_amount=D("0.00"))
    document["invoice"].update(tax_amount=D("0.00"), amount=D("90.00"))
    result = render(document, rendered_text)
    assert "0%" in result and "20%" not in result
    assert "£0.00" in result and "£90.00" in result


def test_mixed_rates_stay_attached_to_their_lines(document, rendered_text):
    document["line_items"] = [
        dict(description=name, quantity=D("1"), unit_cost=D("100"),
             line_total=D("100"), taxable=D("100"), tax_rate=D(rate),
             tax_amount=D(rate), tax_treatment=treatment)
        for name, rate, treatment in (("Standard pipe", "20", "standard"),
                                      ("Reduced work", "5", "reduced"),
                                      ("Zero work", "0", "zero_rated"))
    ]
    document["invoice"].update(subtotal=D("300"), tax_amount=D("25"),
                               amount=D("325"), discount_amount=D("0"))
    result = render(document, rendered_text)
    for index, (description, rate) in enumerate((("Standard pipe", "20%"),
                                               ("Reduced work", "5%"),
                                               ("Zero work", "0%"))):
        start = result.index(description)
        end = result.index(document["line_items"][index + 1]["description"]) if index < 2 else len(result)
        assert rate in result[start:end]
    assert "£25.00" in result and "£325.00" in result


class NoFloatDecimal(Decimal):
    def __float__(self):
        raise AssertionError("PDF must not convert exact money to float")


def test_decimal_pennies_survive_without_float_conversion(document, rendered_text):
    for row in [document["invoice"], *document["line_items"]]:
        for key, value in row.items():
            if isinstance(value, Decimal):
                row[key] = NoFloatDecimal(str(value))
    document["invoice"].update(subtotal=NoFloatDecimal("2.68"),
                               tax_amount=NoFloatDecimal("0.54"),
                               amount=NoFloatDecimal("3.22"))
    document["line_items"][0]["unit_cost"] = NoFloatDecimal("2.6750")
    result = render(document, rendered_text)
    assert "£2.68" in result and "£0.54" in result and "£3.22" in result
    assert "£2.67" not in result


@pytest.mark.parametrize("region,currency,symbol", [("UK", "GBP", "£"), ("US", "USD", "$")])
def test_currency_follows_region(document, rendered_text, region, currency, symbol):
    from services.region import resolve

    assert resolve(region)["currency"] == currency
    document["business"].update(region=region, tax_registered=False)
    document["invoice"].update(currency=currency, tax_amount=D("0"), amount=D("90"))
    result = render(document, rendered_text)
    assert f"{symbol}90.00" in result
    assert ("$" if symbol == "£" else "£") not in result


@pytest.mark.parametrize("source", ["csv", "xero"])
def test_import_without_lines_uses_only_header_totals(document, rendered_text, source):
    document["line_items"] = []
    document["invoice"].update(source=source, subtotal=D("987.65"),
                               tax_amount=D("197.53"), amount=D("1185.18"),
                               discount_amount=D("0"))
    result = render(document, rendered_text)
    assert "no itemised lines" in result.lower()
    for amount in ("987.65", "197.53", "1,185.18"):
        assert f"£{amount}" in result
    assert "Replace copper pipe" not in result


# SQLite proves query scoping, not PostgreSQL/RLS equivalence. Money stored
# as TEXT here avoids SQLite's float conversion; production NUMERIC is Decimal.
SCHEMA = """
CREATE TABLE invoices (id TEXT PRIMARY KEY, business_id TEXT, invoice_number TEXT,
 customer_name TEXT, customer_email TEXT, issue_date TEXT, invoice_date TEXT,
 created_at TEXT, due_date TEXT, subtotal TEXT, tax_amount TEXT, amount TEXT,
 currency TEXT, source TEXT, source_ref TEXT, related_invoice_id TEXT);
CREATE TABLE invoice_line_items (id TEXT PRIMARY KEY, invoice_id TEXT,
 description TEXT, quantity TEXT, unit_cost TEXT, line_total TEXT, taxable TEXT,
 tax_rate TEXT, tax_amount TEXT, tax_treatment TEXT, discount_amount TEXT,
 discount_type TEXT, apportioned_discount TEXT, sort_order INTEGER, unit TEXT);
CREATE TABLE businesses (id TEXT PRIMARY KEY, name TEXT, region TEXT,
 tax_registered BOOLEAN, tax_number TEXT);
CREATE TABLE quote_settings (business_id TEXT, company_name TEXT,
 company_address TEXT, vat_number TEXT);
CREATE TABLE quotes (id TEXT PRIMARY KEY, business_id TEXT, invoice_id TEXT,
 quote_number TEXT, customer_address TEXT);
"""


@pytest.fixture
def database():
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    with Session(engine) as session:
        for statement in SCHEMA.split(";"):
            if statement.strip():
                session.execute(text(statement))
        for business, invoice, marker, amount in ((A, IA, "A", "120.00"),
                                                   (B, IB, "B-PRIVATE", "933.32")):
            session.execute(text("INSERT INTO businesses VALUES (:b,:name,'UK',1,:tax)"),
                            dict(b=business, name=f"{marker} Supplier", tax=f"{marker}-TAX"))
            session.execute(text("INSERT INTO quote_settings VALUES (:b,:name,:address,:tax)"),
                            dict(b=business, name=f"{marker} Supplier",
                                 address=f"{marker} Supplier Address", tax=f"{marker}-TAX"))
            session.execute(text("""INSERT INTO invoices VALUES
                (:i,:b,:num,:customer,NULL,'2026-09-29','2026-09-29',
                 '2026-09-29','2026-10-29',:net,:tax,:amount,'GBP','quote',
                 'SHARED-QUOTE-NUMBER',NULL)"""),
                dict(i=invoice, b=business, num=f"{marker}-INV", customer=f"{marker} Customer",
                     net="100.00" if business == A else "777.77",
                     tax="20.00" if business == A else "155.55", amount=amount))
            session.execute(text("""INSERT INTO invoice_line_items VALUES
                (:i,:i,:description,'1',:net,:net,:net,'20',:tax,'standard',
                 '0','fixed','0',0,'each')"""),
                dict(i=invoice, description=f"{marker} Work", net="100.00" if business == A else "777.77",
                     tax="20.00" if business == A else "155.55"))
            session.execute(text("INSERT INTO quotes VALUES (:i,:b,:i,'SHARED-QUOTE-NUMBER',:address)"),
                            dict(i=invoice, b=business, address=f"{marker} Customer Address"))
        session.commit()
    yield engine
    engine.dispose()


def test_two_tenant_fixture_really_contains_distinct_private_data(database):
    with Session(database) as session:
        rows = session.execute(text("SELECT business_id, amount FROM invoices ORDER BY id")).all()
        assert rows == [(A, "120.00"), (B, "933.32")]
        assert session.execute(text("SELECT COUNT(*) FROM quotes WHERE quote_number='SHARED-QUOTE-NUMBER'")).scalar() == 2


def client_for(database, monkeypatch, business=A, status="active", enabled=True, active=True):
    module = target("invoice_pdf_api")
    import auth
    import db
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    # Run the REAL require_feature dependency and access resolver. Only the
    # ORM business lookup is substituted (Business maps PostgreSQL JSONB).
    # All invoice/line/address SQL executes against both tenants in SQLite.
    entitlement = SimpleNamespace(id=business, subscription_status=status,
                                  is_active=active, trial_ends_at=None,
                                  plan_tier="starter", feature_flags={"invoicing": enabled})

    class PDFSession(Session):
        def exec(self, statement, *args, **kwargs):
            from models import Business
            assert statement.column_descriptions[0]["entity"] is Business
            assert str(business) in map(str, statement.compile().params.values())
            return SimpleNamespace(first=lambda: entitlement)

    def sessions():
        with PDFSession(database) as session:
            yield session

    monkeypatch.setattr(auth, "is_platform_admin_user", lambda *args: False)
    app = FastAPI()
    app.include_router(module.router)
    app.dependency_overrides[auth.get_user_business_context] = lambda: {
        "business_id": business, "user_id": "synthetic-owner"}
    app.dependency_overrides[db.get_session] = sessions
    return TestClient(app)


@pytest.mark.parametrize("business,own,foreign", [(A, IA, IB), (B, IB, IA)])
def test_http_download_is_scoped_both_directions(database, monkeypatch, rendered_text, business, own, foreign):
    with client_for(database, monkeypatch, business=business) as client:
        response = client.get(f"/v1/invoices/{own}/pdf")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert "attachment" in response.headers["content-disposition"]
        assert response.content.startswith(b"%PDF-")
        observed = " ".join(rendered_text)
        marker = "A" if business == A else "B-PRIVATE"
        assert f"{marker} Customer Address" in observed
        assert f"{marker} Work" in observed
        assert ("£120.00" if business == A else "£933.32") in observed
        assert ("B-PRIVATE" if business == A else "A Customer") not in observed
        rendered_text.clear()
        denied = client.get(f"/v1/invoices/{foreign}/pdf")
        missing = client.get("/v1/invoices/33333333-3333-4333-8333-333333333333/pdf")
        assert denied.status_code == missing.status_code == 404
        assert denied.json() == missing.json()
        assert not denied.content.startswith(b"%PDF-")
        assert not rendered_text, "Foreign/missing invoice must never be rendered"


@pytest.mark.parametrize("status,active,enabled,expected", [
    ("active", True, True, 200), ("unpaid", False, True, 200),
    ("canceled", False, True, 200), ("active", True, False, 403),
    ("unpaid", False, False, 403), ("canceled", False, False, 403),
    ("active", False, True, 403),
])
def test_http_invoicing_entitlement_and_retained_read_access(
    database, monkeypatch, rendered_text, status, active, enabled, expected,
):
    with client_for(database, monkeypatch, status=status, active=active, enabled=enabled) as client:
        response = client.get(f"/v1/invoices/{IA}/pdf")
    assert response.status_code == expected
    if expected == 200:
        assert response.content.startswith(b"%PDF-")
    else:
        assert not response.content.startswith(b"%PDF-")
        assert not rendered_text


# Stage 2: Mike's approved decisions, added and run before implementation.
@pytest.mark.parametrize("issue,invoice_date,created,expected", [
    ("2026-10-08", "2026-10-07", "2026-10-06T12:30:00+00:00", "08/10/2026"),
    (None, "2026-10-07", "2026-10-06T12:30:00+00:00", "07/10/2026"),
    (None, None, "2026-10-06T12:30:00+00:00", "06/10/2026"),
])
def test_decision_invoice_date_precedence(database, monkeypatch, rendered_text, issue, invoice_date, created, expected):
    with Session(database) as session:
        session.execute(text("UPDATE invoices SET issue_date=:issue, invoice_date=:day, created_at=:created WHERE id=:id"),
                        dict(issue=issue, day=invoice_date, created=created, id=IA))
        session.commit()
    with client_for(database, monkeypatch) as client:
        assert client.get(f"/v1/invoices/{IA}/pdf").status_code == 200
    observed = " ".join(rendered_text)
    assert "Invoice date" in observed and expected in observed
    assert "Tax point" not in observed


@pytest.mark.parametrize("tax_point,shown", [(None, False), (date(2026, 9, 29), False), (date(2026, 9, 28), True)])
def test_decision_tax_point_only_when_stored_and_different(document, rendered_text, tax_point, shown):
    document["invoice"]["tax_point"] = tax_point
    observed = render(document, rendered_text)
    assert ("Tax point" in observed) == shown


@pytest.mark.parametrize("canonical,expected,absent", [
    ("CANONICAL-TAX", "CANONICAL-TAX", "LEGACY-TAX"),
    (None, "LEGACY-TAX", "CANONICAL-TAX"),
    ("   ", "LEGACY-TAX", "CANONICAL-TAX"),
])
def test_decision_vat_number_precedence(database, monkeypatch, rendered_text, canonical, expected, absent):
    with Session(database) as session:
        session.execute(text("UPDATE businesses SET tax_number=:number WHERE id=:id"), dict(number=canonical, id=A))
        session.execute(text("UPDATE quote_settings SET vat_number='LEGACY-TAX' WHERE business_id=:id"), dict(id=A))
        session.commit()
    with client_for(database, monkeypatch) as client:
        assert client.get(f"/v1/invoices/{IA}/pdf").status_code == 200
    observed = " ".join(rendered_text)
    assert expected in observed and absent not in observed


@pytest.mark.parametrize("source,label", [("csv", "Imported from CSV"), ("xero", "Originally issued from Xero")])
@pytest.mark.parametrize("has_lines", [False, True])
def test_decision_import_title_and_origin(document, rendered_text, source, label, has_lines):
    document["invoice"]["source"] = source
    if not has_lines:
        document["line_items"] = []
    observed = render(document, rendered_text)
    assert "Invoice copy" in observed and label in observed
    assert "vat invoice" not in observed.lower()
    assert ("No itemised lines" in observed) == (not has_lines)


@pytest.mark.parametrize("region,currency,symbol", [("UK", "USD", "$"), ("US", "GBP", "£"), ("UK", "CAD", "CAD ")])
def test_decision_invoice_currency_overrides_region(document, rendered_text, region, currency, symbol):
    document["business"].update(region=region, tax_registered=False)
    document["invoice"].update(currency=currency, tax_amount=D("0"))
    assert f"{symbol}108.00" in render(document, rendered_text)


@pytest.mark.parametrize("source", ["quote", "csv", "xero"])
def test_decision_registered_foreign_currency_refused(database, monkeypatch, rendered_text, source):
    with Session(database) as session:
        session.execute(text("UPDATE invoices SET currency='USD', source=:source WHERE id=:id"), dict(source=source, id=IA))
        session.commit()
    with client_for(database, monkeypatch) as client:
        response = client.get(f"/v1/invoices/{IA}/pdf")
    assert response.status_code == 422
    assert "sterling" in response.json()["detail"].lower()
    assert not response.content.startswith(b"%PDF-") and not rendered_text


@pytest.mark.parametrize("tax", ["20.00", "-20.00"])
def test_decision_unregistered_stored_vat_refused(database, monkeypatch, rendered_text, tax):
    with Session(database) as session:
        session.execute(text("UPDATE businesses SET tax_registered=0 WHERE id=:id"), dict(id=A))
        session.execute(text("UPDATE invoices SET tax_amount=:tax WHERE id=:id"), dict(tax=tax, id=IA))
        session.commit()
    with client_for(database, monkeypatch) as client:
        response = client.get(f"/v1/invoices/{IA}/pdf")
    assert response.status_code == 422
    assert "check" in response.json()["detail"].lower()
    assert "vat settings" in response.json()["detail"].lower()
    assert not response.content.startswith(b"%PDF-") and not rendered_text


@pytest.mark.parametrize("amount,registered,missing", [
    ("250.00", True, False), ("250.01", True, True),
    ("249.99", True, False), ("250.01", False, True),
])
def test_decision_missing_address_threshold_and_no_guess(database, monkeypatch, rendered_text, amount, registered, missing):
    with Session(database) as session:
        # Same source_ref still matches both quotes; neither is an authorised link.
        session.execute(text("UPDATE quotes SET invoice_id=NULL WHERE business_id=:id"), dict(id=A))
        # A malicious/incorrect foreign quote link must not supply the address.
        session.execute(text("UPDATE quotes SET invoice_id=:invoice WHERE business_id=:id"), dict(invoice=IA, id=B))
        session.execute(text("UPDATE invoices SET amount=:amount, tax_amount=:tax WHERE id=:id"),
                        dict(amount=amount, tax="20" if registered else "0", id=IA))
        session.execute(text("UPDATE businesses SET tax_registered=:registered WHERE id=:id"), dict(registered=registered, id=A))
        session.commit()
    with client_for(database, monkeypatch) as client:
        response = client.get(f"/v1/invoices/{IA}/pdf")
    assert response.status_code == 200
    assert ("customer_address" in response.headers.get("X-Invoice-Missing-Fields", "")) == missing
    observed = " ".join(rendered_text)
    assert "Customer Address" not in observed and "B-PRIVATE" not in observed
    assert "missing" not in observed.lower() and "incomplete" not in observed.lower()


def test_decision_missing_fields_and_complete_header(database, monkeypatch, rendered_text):
    with client_for(database, monkeypatch) as client:
        complete = client.get(f"/v1/invoices/{IA}/pdf")
        assert complete.status_code == 200
        assert "X-Invoice-Missing-Fields" not in complete.headers
        with Session(database) as session:
            session.execute(text("UPDATE businesses SET tax_number=NULL WHERE id=:id"), dict(id=A))
            session.execute(text("UPDATE quote_settings SET vat_number=NULL, company_address=NULL WHERE business_id=:id"), dict(id=A))
            session.commit()
        response = client.get(f"/v1/invoices/{IA}/pdf")
    assert response.status_code == 200
    assert set(response.headers["X-Invoice-Missing-Fields"].split(",")) == {"supplier_address", "vat_number"}


def test_decision_discount_uses_stored_taxable_not_percentage_input(database, monkeypatch, rendered_text):
    with Session(database) as session:
        session.execute(text("UPDATE invoice_line_items SET line_total='100', discount_type='percentage', discount_amount='10', apportioned_discount='5', taxable='85' WHERE invoice_id=:id"), dict(id=IA))
        session.commit()
    with client_for(database, monkeypatch) as client:
        assert client.get(f"/v1/invoices/{IA}/pdf").status_code == 200
    observed = " ".join(rendered_text)
    assert "Discount" in observed and "£15.00" in observed
    # Header is intentionally unchanged; the PDF must not reprice it.
    assert "£120.00" in observed and "£20.00" in observed


@pytest.mark.parametrize("source", ["csv", "xero"])
def test_import_with_null_net_and_tax_preserves_only_known_total(database, monkeypatch, rendered_text, source):
    """Real import writers can leave subtotal/tax_amount NULL; never invent zero."""
    with Session(database) as session:
        session.execute(text("DELETE FROM invoice_line_items WHERE invoice_id=:id"), dict(id=IA))
        session.execute(text("UPDATE invoices SET subtotal=NULL, tax_amount=NULL, source=:source WHERE id=:id"), dict(source=source, id=IA))
        session.commit()
    with client_for(database, monkeypatch) as client:
        response = client.get(f"/v1/invoices/{IA}/pdf")
    assert response.status_code == 200
    assert {"subtotal", "tax_amount"} <= set(response.headers["X-Invoice-Missing-Fields"].split(","))
    observed = " ".join(rendered_text)
    assert "Invoice copy" in observed and "£120.00" in observed
    assert "£0.00" not in observed and "No itemised lines" in observed


def test_long_invoice_wraps_and_paginates_without_losing_lines(document, rendered_text):
    document["line_items"] = [
        {**document["line_items"][0], "description": f"Work {index:03d}: Copper pipe & fittings <supplied> " + "long description " * 12}
        for index in range(65)
    ]
    observed = render(document, rendered_text)
    for index in range(65):
        assert f"Work {index:03d}" in observed
    assert "Page 2" in observed
    # ReportLab can draw escaped angle brackets as separate text fragments.
    assert "<supplied>" in observed.replace(" ", "")
    assert "£108.00" in observed


def test_ambiguous_quote_links_do_not_choose_an_address(database, monkeypatch, rendered_text):
    with Session(database) as session:
        session.execute(text("INSERT INTO quotes VALUES ('extra',:business,:invoice,'OTHER','Untrusted duplicate address')"), dict(business=A, invoice=IA))
        session.execute(text("UPDATE invoices SET amount='251' WHERE id=:id"), dict(id=IA))
        session.commit()
    with client_for(database, monkeypatch) as client:
        response = client.get(f"/v1/invoices/{IA}/pdf")
    assert response.status_code == 200
    assert "customer_address" in response.headers["X-Invoice-Missing-Fields"]
    assert "address" not in " ".join(rendered_text).lower().replace("supplier address", "")


def test_multipage_first_line_stays_below_invoice_header(document, rendered_text, monkeypatch):
    """Check drawing coordinates independently of PDF thumbnail rendering."""
    from reportlab.platypus import Paragraph

    positions = {}
    original = Paragraph.draw

    def observe(paragraph):
        content = paragraph.getPlainText()
        if content.startswith(('Invoice date:', 'Work 000:')):
            positions[content.split(':')[0]] = paragraph.canv.absolutePosition(0, paragraph.height)[1]
        return original(paragraph)

    monkeypatch.setattr(Paragraph, 'draw', observe)
    document['line_items'] = [
        {**document['line_items'][0], 'description': f'Work {i:03}: ' + 'Copper pipe & fittings <supplied> long description ' * 5}
        for i in range(65)
    ]
    render(document, rendered_text)
    assert positions['Work 000'] < positions['Invoice date']


# Repair cycle 1: regressions run against Stage 2 before implementation.
@pytest.mark.parametrize("origin,label", [
    ({"source": "quickbooks"}, "Originally issued from QuickBooks"),
    ({"source": "freeagent"}, "Originally issued from FreeAgent"),
    ({"external_source": "xero"}, "Originally issued from Xero"),
    ({"external_source": "quickbooks"}, "Originally issued from QuickBooks"),
    ({"external_source": "freeagent"}, "Originally issued from FreeAgent"),
    ({"external_source": "csv"}, "Imported from CSV"),
    ({"external_id": "remote-42"}, "Originally issued externally"),
])
@pytest.mark.parametrize("has_lines", [True, False])
def test_repair_external_invoice_copy(document, rendered_text, origin, label, has_lines):
    document["invoice"].update(origin)
    if not has_lines:
        document["line_items"] = []
    observed = render(document, rendered_text)
    assert "Invoice copy" in observed
    assert label in observed
    assert "vat invoice" not in observed.lower()


def test_repair_discounted_net_matches_stored_taxable(document, rendered_text):
    net = document["invoice"]["subtotal"] - document["invoice"]["discount_amount"]
    assert net == sum(line["taxable"] for line in document["line_items"])
    observed = render(document, rendered_text)
    assert "Subtotal £100.00 Discount £10.00 Total excluding VAT £90.00 Total VAT £18.00 Total payable £108.00" in observed


@pytest.mark.parametrize("subtotal", ["101", None])
def test_repair_unverified_net_omitted_and_reported(database, monkeypatch, rendered_text, subtotal):
    with Session(database) as session:
        session.execute(text("UPDATE invoices SET subtotal=:subtotal WHERE id=:id"), dict(subtotal=subtotal, id=IA))
        session.execute(text("UPDATE invoice_line_items SET taxable='90' WHERE invoice_id=:id"), dict(id=IA))
        session.commit()
    with client_for(database, monkeypatch) as client:
        response = client.get(f"/v1/invoices/{IA}/pdf")
    assert response.status_code == 200
    assert "total_excluding_vat" in response.headers.get("X-Invoice-Missing-Fields", "").split(",")
    observed = " ".join(rendered_text)
    assert "Total excluding VAT" not in observed
    assert "Total VAT £20.00 Total payable £120.00" in observed


@pytest.mark.parametrize("registered", [True, False])
@pytest.mark.parametrize("discount", [D("0"), None])
def test_repair_zero_discount_row_omitted(document, rendered_text, registered, discount):
    document["business"]["tax_registered"] = registered
    document["invoice"].update(discount_amount=discount, tax_amount=D("0"), amount=D("100"))
    document["line_items"][0]["taxable"] = D("100")
    observed = render(document, rendered_text)
    assert "Discount" not in observed
    assert ("Total excluding VAT £100.00" if registered else "Subtotal £100.00") in observed


def test_repair_router_uses_explicit_import():
    import ast
    from pathlib import Path

    tree = ast.parse((Path(__file__).parents[1] / "main.py").read_text())
    assert any(isinstance(node, ast.ImportFrom) and node.module == "invoice_pdf_api"
               and any(alias.name == "router" and alias.asname == "invoice_pdf_router" for alias in node.names)
               for node in tree.body)
    assert any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
               and node.func.attr == "include_router" and node.args
               and isinstance(node.args[0], ast.Name) and node.args[0].id == "invoice_pdf_router"
               for node in ast.walk(tree))
