"""
ITEM 3 — tax registration and the business's own rate.

Target surface (does not exist yet):

    backend/services/money.py
        resolve_tax_rate(
            quote_tax_rate,      # Decimal | None — the rate stored on the quote
            default_tax_rate,    # Decimal | None — quote_settings.default_tax_rate
            tax_registered,      # bool          — businesses.tax_registered
            fallback_rate,       # Decimal       — from the region resolver
        ) -> Decimal

Plus the existing `quoting_api.create_quote` / `update_quote` endpoints, which
must stop hardcoding 20.

THE CENTRAL TEST IN THIS FILE is TestZeroRateStaysZero. The spec calls this
"the single most likely way to implement this wrongly", and it is: both
`rate or 20` in Python and `rate || 20` in JavaScript silently turn a stored 0
into 20. A business that has told the product it is not VAT-registered would
then charge 20% VAT on every quote — which is illegal, and which the product
would have done to them.
"""
import asyncio
import re
import unittest
from decimal import Decimal
from pathlib import Path

from sqlalchemy.sql.elements import TextClause

import quoting_api


QUOTING_API_SOURCE = Path(quoting_api.__file__)


def money():
    from services import money as _money
    return _money


# ── Fakes ────────────────────────────────────────────────────────────────────

class FakeRow:
    """
    A row that behaves like a SQLAlchemy Row: index access AND attribute
    access, over exactly the columns the query actually asked for.
    """

    def __init__(self, columns, values):
        self._columns = list(columns)
        self._values = list(values)
        for name, value in zip(self._columns, self._values):
            setattr(self, name, value)

    def __getitem__(self, index):
        return self._values[index]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)


class FakeResult:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row

    def fetchall(self):
        return [self._row] if self._row is not None else []

    def first(self):
        return self._row


class RecordingSession:
    """
    A fake session that projects the columns the SQL actually selected, rather
    than handing back a fixed row shape.

    The discipline: if the implementation asks for a column this fake does not
    hold, the test fails with a clear message instead of silently receiving a
    None and computing something plausible from it. A fake that answers
    questions it was never asked is not a test, it is a rubber stamp.
    """

    TABLES = ("quote_settings", "quotes", "businesses", "quote_line_items",
              "invoices", "invoice_line_items")

    def __init__(self, quote_settings=None, business=None, quote=None):
        self.data = {
            "quote_settings": quote_settings,
            "businesses": business,
            "quotes": quote,
        }
        self.statements = []      # (sql, params)
        self.committed = False

    # -- helpers ------------------------------------------------------------
    @staticmethod
    def _normalise(statement):
        assert isinstance(statement, TextClause), (
            f"expected a TextClause, got {type(statement)} — this fake only "
            f"models the raw-SQL path these endpoints actually use"
        )
        return " ".join(statement.text.split())

    def _table_of(self, sql):
        match = re.search(r"\b(?:FROM|INTO|UPDATE)\s+([a-z_]+)", sql, re.IGNORECASE)
        return match.group(1).lower() if match else None

    def _project(self, sql, table):
        source = self.data.get(table)
        if source is None:
            return None
        select_clause = re.search(r"SELECT\s+(.*?)\s+FROM", sql, re.IGNORECASE | re.DOTALL)
        assert select_clause, f"could not parse a SELECT list from: {sql}"
        raw = select_clause.group(1).strip()
        if raw == "*":
            columns = list(source.keys())
        else:
            columns = [c.strip().split()[-1] for c in raw.split(",")]
        missing = [c for c in columns if c not in source]
        assert not missing, (
            f"query selected {missing} from `{table}`, which this fake does not "
            f"hold. Either the column is wrong or the fake needs updating — "
            f"it will not invent a value. SQL: {sql}"
        )
        return FakeRow(columns, [source[c] for c in columns])

    # -- session API --------------------------------------------------------
    def execute(self, statement, params=None):
        sql = self._normalise(statement)
        self.statements.append((sql, params))
        table = self._table_of(sql)
        assert table in self.TABLES, f"unexpected table `{table}` in: {sql}"

        if sql.upper().startswith("SELECT"):
            # Every tenant-scoped read must be scoped. The backend bypasses
            # RLS, so this WHERE clause is the only tenant isolation there is.
            if table in ("quote_settings", "quotes", "businesses", "invoices"):
                assert "business_id" in sql or "WHERE id" in sql, (
                    f"tenant-scoped read is missing a business_id filter: {sql}"
                )
            return FakeResult(self._project(sql, table))
        return FakeResult(None)

    def commit(self):
        self.committed = True

    # -- assertions ---------------------------------------------------------
    def params_for(self, fragment):
        matches = [p for sql, p in self.statements if fragment.upper() in sql.upper()]
        assert matches, (
            f"no statement matching {fragment!r} was issued. Statements were:\n  "
            + "\n  ".join(sql for sql, _ in self.statements)
        )
        return matches[0]


def settings_row(**overrides):
    row = {
        "id": "qs-1",
        "business_id": "biz-1",
        "quote_prefix": "QTE-",
        "next_quote_number": 1,
        "default_terms": "Valid for 30 days.",
        "default_valid_days": 30,
        "default_tax_rate": Decimal("20"),
        "include_tax": True,
        "default_markup": Decimal("0"),
        "company_name": "Test Co",
        "company_address": None,
        "company_phone": None,
        "company_email": None,
        "company_logo_url": None,
        "company_registration": None,
        "vat_number": None,
        "industry": "general",
        "labour_rates": [],
    }
    row.update(overrides)
    return row


def business_row(**overrides):
    row = {
        "id": "biz-1",
        "name": "Test Co",
        "region": "UK",
        "tax_registered": True,
        "tax_number": "GB123456789",
        "currency": "GBP",
    }
    row.update(overrides)
    return row


def assertMoney(case, actual, expected, label):
    """
    Assert a money bind is both the right value AND a Decimal.

    Decimal("20") == 20.0 evaluates True in Python, so a value-only assertion
    is satisfied by the current float implementation. Without the type check
    these tests would rubber-stamp exactly what they exist to reject.
    """
    case.assertIsInstance(
        actual, Decimal,
        f"{label} is {type(actual).__name__}({actual!r}), not Decimal",
    )
    case.assertNotIsInstance(actual, float)
    case.assertEqual(actual, expected, f"{label} was {actual!r}")


def create_quote(session, **data):
    payload = {
        "customer_name": "A Customer",
        "job_title": "A Job",
        "line_items": [{"description": "Work", "quantity": Decimal("1"),
                        "unit_cost": Decimal("100.00")}],
    }
    payload.update(data)
    return asyncio.run(quoting_api.create_quote(
        data=payload,
        auth_ctx={"business_id": "biz-1", "user_id": "user-1"},
        session=session,
    ))


# ── The central criterion ────────────────────────────────────────────────────

class TestZeroRateStaysZero(unittest.TestCase):
    """
    Criterion: "A stored rate of 0 stays 0. `rate or 20` turns 0 into 20 in
    both Python and JavaScript — use explicit `is None`."
    """

    def test_stored_default_of_zero_resolves_to_zero_not_the_fallback(self):
        rate = money().resolve_tax_rate(
            quote_tax_rate=None,
            default_tax_rate=Decimal("0"),
            tax_registered=True,
            fallback_rate=Decimal("20"),
        )
        self.assertEqual(rate, Decimal("0"))

    def test_quote_rate_of_zero_is_not_overridden_by_a_nonzero_default(self):
        rate = money().resolve_tax_rate(
            quote_tax_rate=Decimal("0"),
            default_tax_rate=Decimal("20"),
            tax_registered=True,
            fallback_rate=Decimal("20"),
        )
        self.assertEqual(rate, Decimal("0"))

    def test_every_falsy_spelling_of_zero_survives(self):
        # Decimal("0"), Decimal("0.00") and Decimal("0E-2") are all falsy.
        # An `or` implementation turns every one of them into 20.
        # NB: resolve the module OUTSIDE the subTest loop — subTest swallows
        # exceptions, which would let a missing module report as a pass.
        resolve = money().resolve_tax_rate
        for spelling in (Decimal("0"), Decimal("0.00"), Decimal("0E-2")):
            with self.subTest(spelling=spelling):
                rate = resolve(
                    quote_tax_rate=None,
                    default_tax_rate=spelling,
                    tax_registered=True,
                    fallback_rate=Decimal("20"),
                )
                self.assertEqual(rate, Decimal("0"))

    def test_only_a_genuinely_absent_setting_falls_back(self):
        rate = money().resolve_tax_rate(
            quote_tax_rate=None,
            default_tax_rate=None,
            tax_registered=True,
            fallback_rate=Decimal("20"),
        )
        self.assertEqual(rate, Decimal("20"))

    def test_a_stored_nonzero_default_is_honoured(self):
        rate = money().resolve_tax_rate(
            quote_tax_rate=None,
            default_tax_rate=Decimal("5"),
            tax_registered=True,
            fallback_rate=Decimal("20"),
        )
        self.assertEqual(rate, Decimal("5"))

    def test_unregistered_business_gets_zero_whatever_is_stored(self):
        rate = money().resolve_tax_rate(
            quote_tax_rate=Decimal("20"),
            default_tax_rate=Decimal("20"),
            tax_registered=False,
            fallback_rate=Decimal("20"),
        )
        self.assertEqual(rate, Decimal("0"))

    def test_returns_decimal_not_float(self):
        rate = money().resolve_tax_rate(
            quote_tax_rate=None, default_tax_rate=Decimal("20"),
            tax_registered=True, fallback_rate=Decimal("20"),
        )
        self.assertIsInstance(rate, Decimal)
        self.assertNotIsInstance(rate, float)


class TestZeroRateStaysZeroEndToEnd(unittest.TestCase):
    """
    The same criterion, but through the real create_quote endpoint — because
    resolve_tax_rate being correct is worth nothing if the endpoint never
    calls it. This is the test that would have caught the live bug.
    """

    def test_business_with_zero_default_is_charged_no_tax(self):
        session = RecordingSession(
            quote_settings=settings_row(default_tax_rate=Decimal("0")),
            business=business_row(),
        )
        create_quote(session)
        params = session.params_for("INSERT INTO quotes")
        assertMoney(self, params["tax_rate"], Decimal("0"), "tax_rate")
        assertMoney(self, params["tax_amount"], Decimal("0.00"), "tax_amount")
        assertMoney(self, params["total"], Decimal("100.00"), "total")


# ── The remaining Item 3 criteria ────────────────────────────────────────────

class TestQuoteSeedsFromSettings(unittest.TestCase):
    """Criterion: new quotes seed tax_rate from quote_settings.default_tax_rate."""

    def test_quote_uses_the_businesss_stored_rate(self):
        session = RecordingSession(
            quote_settings=settings_row(default_tax_rate=Decimal("5")),
            business=business_row(),
        )
        create_quote(session)
        params = session.params_for("INSERT INTO quotes")
        assertMoney(self, params["tax_rate"], Decimal("5"), "tax_rate")
        assertMoney(self, params["tax_amount"], Decimal("5.00"), "tax_amount")
        assertMoney(self, params["total"], Decimal("105.00"), "total")

    def test_explicit_rate_in_the_payload_beats_the_setting(self):
        session = RecordingSession(
            quote_settings=settings_row(default_tax_rate=Decimal("5")),
            business=business_row(),
        )
        create_quote(session, tax_rate=Decimal("20"))
        params = session.params_for("INSERT INTO quotes")
        assertMoney(self, params["tax_rate"], Decimal("20"), "tax_rate")

    def test_the_settings_are_actually_read(self):
        # Guards against an implementation that "honours the setting" by
        # coincidence — e.g. by hardcoding 20 while the setting also says 20.
        session = RecordingSession(
            quote_settings=settings_row(default_tax_rate=Decimal("20")),
            business=business_row(),
        )
        create_quote(session)
        read_rate = any(
            "default_tax_rate" in sql
            for sql, _ in session.statements
            if sql.upper().startswith("SELECT")
        )
        self.assertTrue(
            read_rate,
            "create_quote never read default_tax_rate — the rate it used was "
            "a literal, not the business's setting",
        )


class TestNotTaxRegisteredEndToEnd(unittest.TestCase):
    """Criterion: when tax_registered is false, no tax on quotes or invoices."""

    def test_unregistered_business_gets_no_tax_on_a_quote(self):
        session = RecordingSession(
            quote_settings=settings_row(default_tax_rate=Decimal("20")),
            business=business_row(tax_registered=False),
        )
        create_quote(session)
        params = session.params_for("INSERT INTO quotes")
        assertMoney(self, params["tax_amount"], Decimal("0.00"), "tax_amount")
        assertMoney(self, params["total"], params["subtotal"], "total")

    def test_registration_status_is_actually_read(self):
        session = RecordingSession(
            quote_settings=settings_row(),
            business=business_row(tax_registered=False),
        )
        create_quote(session)
        read_registration = any(
            "tax_registered" in sql for sql, _ in session.statements
        )
        self.assertTrue(
            read_registration,
            "create_quote never read businesses.tax_registered",
        )


class TestExistingQuotesAreNotRewritten(unittest.TestCase):
    """Criterion: changing the default does not alter existing quotes."""

    def test_update_preserves_the_rate_stored_on_the_quote(self):
        # Quote was raised at 5%. The business has since changed its default
        # to 20%. Editing the quote's notes must not silently reprice it.
        session = RecordingSession(
            quote_settings=settings_row(default_tax_rate=Decimal("20")),
            business=business_row(),
            quote={"id": "quote-1", "status": "draft", "tax_rate": Decimal("5"),
                   "discount_amount": Decimal("0"), "discount_type": "fixed",
                   "business_id": "biz-1"},
        )
        asyncio.run(quoting_api.update_quote(
            quote_id="quote-1",
            data={"customer_name": "A Customer", "job_title": "A Job",
                  "line_items": [{"description": "Work",
                                  "quantity": Decimal("1"),
                                  "unit_cost": Decimal("100.00")}]},
            auth_ctx={"business_id": "biz-1", "user_id": "user-1"},
            session=session,
        ))
        params = session.params_for("UPDATE quotes")
        assertMoney(self, params["tax_rate"], Decimal("5"), "tax_rate")
        assertMoney(self, params["total"], Decimal("105.00"), "total")


class TestHardcodedTwentyIsGone(unittest.TestCase):
    """
    Criterion: "Hardcoded 20 removed from all four sites in quoting_api.py".

    A source-level assertion, deliberately. The four sites are literal
    fallbacks — `float(data.get("tax_rate", 20))` at lines 231, 279, 356 and
    386 — and the only way to prove a literal is gone is to look for it.
    """

    def test_no_tax_rate_literal_fallback_remains(self):
        source = QUOTING_API_SOURCE.read_text()
        hits = re.findall(r"""["']tax_rate["']\s*,\s*20""", source)
        self.assertEqual(
            hits, [],
            f"{len(hits)} hardcoded tax_rate fallbacks of 20 remain in "
            f"{QUOTING_API_SOURCE.name}",
        )

    def test_calculate_totals_has_no_default_rate_of_twenty(self):
        source = QUOTING_API_SOURCE.read_text()
        self.assertNotIn(
            "tax_rate: float = 20.0", source,
            "_calculate_totals still defaults its rate to 20.0 — a caller that "
            "forgets to pass a rate silently charges VAT",
        )

    def test_row_to_quote_does_not_default_a_missing_rate_to_twenty(self):
        source = QUOTING_API_SOURCE.read_text()
        self.assertNotIn(
            "float(row.tax_rate) if row.tax_rate else 20", source,
            "_row_to_quote turns a stored 0 into 20 on read — the same bug on "
            "the way out of the database",
        )


if __name__ == "__main__":
    unittest.main()
