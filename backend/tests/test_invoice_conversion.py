"""
ITEM 2 — convert_to_invoice must carry the line items and the tax split.

Today `quoting_api.convert_to_invoice` (quoting_api.py:512-571) copies exactly
one money field — `quote.total` — into `invoices.amount`, and discards every
line and the entire VAT breakdown. A UK VAT invoice must legally show the VAT
charged; the invoice this produces structurally cannot.

Criteria covered here:
  * convert_to_invoice copies every line, the subtotal, tax and total
  * stored subtotal equals the sum of stored line_total values exactly
  * subtotal + tax_amount = amount exactly
  * invoices.amount keeps its current meaning — the GROSS total
  * tax rate stored per line; tax_treatment carried through
  * numbering goes through the atomic counter, never COUNT(*)

The worked example is the spec's own: convert a 3-line quote at 20% and check
the gross equals the quote total to the penny.
"""
import asyncio
import re
import unittest
from decimal import Decimal

from sqlalchemy.sql.elements import TextClause

import quoting_api


# A 3-line quote at 20%. Per-line tax, ROUND_HALF_UP, then summed:
#   100.00 -> 20.00 | 250.50 -> 50.10 | 33.33 -> 6.666 -> 6.67
#   subtotal 383.83 | tax 76.77 | gross 460.60
QUOTE_LINES = [
    {"id": "l1", "quote_id": "q1", "description": "Labour", "category": "labour",
     "quantity": Decimal("1"), "unit": "day", "unit_cost": Decimal("100.0000"),
     "line_total": Decimal("100.00"), "markup_percentage": Decimal("0"),
     "markup_amount": Decimal("0"), "sort_order": 0, "group_name": "Works",
     "tax_rate": Decimal("20"), "tax_amount": Decimal("20.00"),
     "tax_treatment": "standard"},
    {"id": "l2", "quote_id": "q1", "description": "Materials", "category": "materials",
     "quantity": Decimal("1"), "unit": "each", "unit_cost": Decimal("250.5000"),
     "line_total": Decimal("250.50"), "markup_percentage": Decimal("0"),
     "markup_amount": Decimal("0"), "sort_order": 1, "group_name": "Works",
     "tax_rate": Decimal("20"), "tax_amount": Decimal("50.10"),
     "tax_treatment": "standard"},
    {"id": "l3", "quote_id": "q1", "description": "Disposal", "category": "other",
     "quantity": Decimal("1"), "unit": "each", "unit_cost": Decimal("33.3300"),
     "line_total": Decimal("33.33"), "markup_percentage": Decimal("0"),
     "markup_amount": Decimal("0"), "sort_order": 2, "group_name": "Works",
     "tax_rate": Decimal("20"), "tax_amount": Decimal("6.67"),
     "tax_treatment": "standard"},
]

QUOTE = {
    "id": "q1", "business_id": "biz-1", "quote_number": "QTE-0001",
    "reference": None, "customer_name": "A Customer",
    "customer_email": "c@example.com", "customer_phone": None,
    "customer_address": None, "job_title": "A Job", "job_description": None,
    "job_location": None,
    "subtotal": Decimal("383.83"), "tax_rate": Decimal("20"),
    "tax_amount": Decimal("76.77"), "discount_amount": Decimal("0"),
    "discount_type": "fixed", "total": Decimal("460.60"), "currency": "GBP",
    "markup_percentage": Decimal("0"), "profit_margin": Decimal("0"),
    "status": "accepted", "issue_date": None, "valid_until": None,
    "accepted_at": None, "declined_at": None, "terms": None, "notes": None,
    "customer_notes": None, "ai_generated": False, "ai_prompt": None,
    "ai_model": None, "invoice_id": None, "pdf_url": None, "sent_at": None,
    "sent_via": None, "viewed_at": None, "project_reference": None,
    "created_at": None, "updated_at": None, "created_by": None,
}


class FakeRow:
    def __init__(self, columns, values):
        self._values = list(values)
        for name, value in zip(columns, values):
            setattr(self, name, value)

    def __getitem__(self, index):
        return self._values[index]


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class ConversionSession:
    """
    Projects the columns the SQL actually asked for, and refuses to invent a
    column it does not hold — so a query for a field that does not exist fails
    loudly instead of quietly yielding None and a plausible-looking total.
    """

    def __init__(self, quote=None, lines=None, counter=1):
        self.quote = dict(quote or QUOTE)
        self.lines = [dict(item) for item in (lines if lines is not None else QUOTE_LINES)]
        self.counter = counter
        self.statements = []
        self.used_count_star = False
        self.committed = False

    @staticmethod
    def _norm(statement):
        assert isinstance(statement, TextClause), f"expected TextClause, got {type(statement)}"
        return " ".join(statement.text.split())

    def _project(self, sql, source):
        clause = re.search(r"SELECT\s+(.*?)\s+FROM", sql, re.IGNORECASE | re.DOTALL)
        assert clause, f"unparseable SELECT: {sql}"
        raw = clause.group(1).strip()
        if raw == "*":
            columns = list(source.keys())
        else:
            columns = [c.strip().split()[-1] for c in raw.split(",")]
        missing = [c for c in columns if c not in source]
        assert not missing, (
            f"query selected {missing}, which this fake does not hold — it will "
            f"not invent a money value. SQL: {sql}"
        )
        return FakeRow(columns, [source[c] for c in columns])

    def execute(self, statement, params=None):
        sql = self._norm(statement)
        self.statements.append((sql, params))
        upper = sql.upper()

        if "COUNT(" in upper:
            self.used_count_star = True
            return FakeResult([FakeRow(["count"], [0])])

        if upper.startswith("UPDATE") and "NEXT_INVOICE_NUMBER" in upper and "RETURNING" in upper:
            issued, self.counter = self.counter, self.counter + 1
            return FakeResult([FakeRow(["next_invoice_number", "invoice_prefix"],
                                       [issued, "INV-"])])

        if upper.startswith("SELECT"):
            assert "BUSINESS_ID" in upper or "QUOTE_ID" in upper, (
                f"read is neither tenant- nor parent-scoped: {sql}"
            )
            if "QUOTE_LINE_ITEMS" in upper:
                return FakeResult([self._project(sql, line) for line in self.lines])
            if "FROM QUOTES" in upper:
                return FakeResult([self._project(sql, self.quote)])
            return FakeResult([])

        return FakeResult([])

    def commit(self):
        self.committed = True

    # -- assertions ---------------------------------------------------------
    def all_params(self, fragment):
        return [p for sql, p in self.statements if fragment.upper() in sql.upper()]

    def params_for(self, fragment):
        matches = self.all_params(fragment)
        assert matches, (
            f"no statement matching {fragment!r} was issued. Statements were:\n  "
            + "\n  ".join(sql for sql, _ in self.statements)
        )
        return matches[0]


def convert(session):
    return asyncio.run(quoting_api.convert_to_invoice(
        quote_id="q1",
        auth_ctx={"business_id": "biz-1", "user_id": "user-1"},
        session=session,
    ))


def assertMoney(case, actual, expected, label):
    """Value AND type. Decimal('20') == 20.0 is True, so value alone is not enough."""
    case.assertIsInstance(actual, Decimal, f"{label} is {type(actual).__name__}({actual!r})")
    case.assertNotIsInstance(actual, float)
    case.assertEqual(actual, expected, f"{label} was {actual!r}")


class TestLineItemsAreCopied(unittest.TestCase):
    """Criterion: convert_to_invoice copies every line."""

    def test_one_invoice_line_is_written_per_quote_line(self):
        session = ConversionSession()
        convert(session)
        self.assertEqual(len(session.all_params("INSERT INTO invoice_line_items")), 3)

    def test_line_descriptions_and_amounts_are_carried_over(self):
        session = ConversionSession()
        convert(session)
        written = session.all_params("INSERT INTO invoice_line_items")
        self.assertEqual(len(written), 3, "no invoice line items were written")
        self.assertEqual(
            [p["description"] for p in written],
            ["Labour", "Materials", "Disposal"],
        )
        for params, source in zip(written, QUOTE_LINES):
            assertMoney(self, params["line_total"], source["line_total"], "line_total")
            assertMoney(self, params["unit_cost"], source["unit_cost"], "unit_cost")

    def test_four_dp_unit_cost_survives_the_copy(self):
        lines = [dict(QUOTE_LINES[0], unit_cost=Decimal("3.3333"),
                      quantity=Decimal("47.5"), line_total=Decimal("158.33"),
                      tax_amount=Decimal("31.67"))]
        quote = dict(QUOTE, subtotal=Decimal("158.33"), tax_amount=Decimal("31.67"),
                     total=Decimal("190.00"))
        session = ConversionSession(quote=quote, lines=lines)
        convert(session)
        params = session.params_for("INSERT INTO invoice_line_items")
        assertMoney(self, params["unit_cost"], Decimal("3.3333"), "unit_cost")

    def test_tax_rate_is_stored_per_line(self):
        session = ConversionSession()
        convert(session)
        written = session.all_params("INSERT INTO invoice_line_items")
        # Guard first: a `for` over an empty list asserts nothing at all, and
        # no invoice lines are written today.
        self.assertEqual(len(written), 3, "no invoice line items were written")
        for params in written:
            assertMoney(self, params["tax_rate"], Decimal("20"), "line tax_rate")

    def test_tax_amount_is_stored_per_line(self):
        session = ConversionSession()
        convert(session)
        self.assertEqual(
            [p["tax_amount"] for p in session.all_params("INSERT INTO invoice_line_items")],
            [Decimal("20.00"), Decimal("50.10"), Decimal("6.67")],
        )

    def test_tax_treatment_label_is_carried_over(self):
        session = ConversionSession()
        convert(session)
        written = session.all_params("INSERT INTO invoice_line_items")
        self.assertEqual(len(written), 3, "no invoice line items were written")
        for params in written:
            self.assertEqual(params["tax_treatment"], "standard")

    def test_category_is_carried_over_for_the_future_cis_split(self):
        session = ConversionSession()
        convert(session)
        self.assertEqual(
            [p["category"] for p in session.all_params("INSERT INTO invoice_line_items")],
            ["labour", "materials", "other"],
        )


class TestInvoiceTotals(unittest.TestCase):
    """Criteria: invoices gain subtotal and tax_amount; amount stays the gross."""

    def test_invoice_stores_a_subtotal(self):
        session = ConversionSession()
        convert(session)
        assertMoney(self, session.params_for("INSERT INTO invoices")["subtotal"],
                    Decimal("383.83"), "subtotal")

    def test_invoice_stores_a_tax_amount(self):
        session = ConversionSession()
        convert(session)
        assertMoney(self, session.params_for("INSERT INTO invoices")["tax_amount"],
                    Decimal("76.77"), "tax_amount")

    def test_amount_is_still_the_gross_total(self):
        # Xero sync, briefings and accounting all read `amount`. Nothing that
        # reads it today may change behaviour.
        session = ConversionSession()
        convert(session)
        assertMoney(self, session.params_for("INSERT INTO invoices")["amount"],
                    Decimal("460.60"), "amount")

    def test_amount_due_matches_the_gross_on_a_new_invoice(self):
        session = ConversionSession()
        convert(session)
        assertMoney(self, session.params_for("INSERT INTO invoices")["amount_due"],
                    Decimal("460.60"), "amount_due")

    def test_gross_equals_the_quote_total_to_the_penny(self):
        # The spec's own acceptance test.
        session = ConversionSession()
        convert(session)
        self.assertEqual(
            session.params_for("INSERT INTO invoices")["amount"], QUOTE["total"]
        )


class TestInternalConsistency(unittest.TestCase):
    """
    Criteria: stored subtotal equals the sum of stored line_totals exactly —
    no second, differently-derived subtotal anywhere — and
    subtotal + tax_amount = amount exactly.
    """

    def test_subtotal_equals_the_sum_of_the_written_line_totals(self):
        session = ConversionSession()
        convert(session)
        written = session.all_params("INSERT INTO invoice_line_items")
        self.assertEqual(
            session.params_for("INSERT INTO invoices")["subtotal"],
            sum((p["line_total"] for p in written), Decimal("0")),
        )

    def test_tax_amount_equals_the_sum_of_the_written_line_tax(self):
        session = ConversionSession()
        convert(session)
        written = session.all_params("INSERT INTO invoice_line_items")
        self.assertEqual(
            session.params_for("INSERT INTO invoices")["tax_amount"],
            sum((p["tax_amount"] for p in written), Decimal("0")),
        )

    def test_subtotal_plus_tax_equals_amount_exactly(self):
        session = ConversionSession()
        convert(session)
        params = session.params_for("INSERT INTO invoices")
        self.assertEqual(params["subtotal"] + params["tax_amount"], params["amount"])

    def test_consistency_holds_where_per_line_rounding_bites(self):
        # Three lines that each round up by a third of a penny: per-line tax
        # sums to 2.01 where a subtotal-level calculation gives 2.00. The
        # invariant must hold on the awkward case, not just the tidy one.
        lines = [
            dict(QUOTE_LINES[0], description=f"Line {n}", sort_order=n,
                 unit_cost=Decimal("3.3300"), quantity=Decimal("1"),
                 line_total=Decimal("3.33"), tax_amount=Decimal("0.67"))
            for n in range(3)
        ]
        quote = dict(QUOTE, subtotal=Decimal("9.99"), tax_amount=Decimal("2.01"),
                     total=Decimal("12.00"))
        session = ConversionSession(quote=quote, lines=lines)
        convert(session)
        params = session.params_for("INSERT INTO invoices")
        assertMoney(self, params["tax_amount"], Decimal("2.01"), "tax_amount")
        self.assertEqual(params["subtotal"] + params["tax_amount"], params["amount"])


class TestNumbering(unittest.TestCase):
    """Criterion: conversion allocates through the atomic counter, never COUNT(*)."""

    def test_conversion_does_not_count_invoices(self):
        session = ConversionSession()
        convert(session)
        self.assertFalse(
            session.used_count_star,
            "convert_to_invoice still numbers with COUNT(*) + 1",
        )

    def test_conversion_uses_the_atomic_counter(self):
        session = ConversionSession()
        convert(session)
        self.assertTrue(
            any("next_invoice_number" in sql.lower() for sql, _ in session.statements),
            "convert_to_invoice never touched the invoice counter",
        )


if __name__ == "__main__":
    unittest.main()
