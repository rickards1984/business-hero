"""
A quote discount may not exceed the post-line-discount net.

Boundary rule:
    discount <  net   accepted
    discount == net   accepted, and the quote totals zero
    discount >  net   REJECTED, 400, naming both the discount and the net

Enforced at the API boundary rather than in the calculator. `calculate_totals`
stays lenient on purpose: a quote already stored with an over-large discount
(from before this rule, or from a direct DB edit) must still convert and still
render rather than raising in the middle of an invoice.

Equal-to-net is deliberately allowed. A job written off, or one fully covered
by a deposit, is a real thing a trade business does, and the resulting zero
total is correct rather than an error.
"""
import asyncio
import re
import unittest
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.sql.elements import TextClause

import quoting_api


class FakeRow:
    def __init__(self, columns, values):
        self._values = list(values)
        for name, value in zip(columns, values):
            setattr(self, name, value)

    def __getitem__(self, index):
        return self._values[index]


class FakeResult:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row

    def first(self):
        return self._row


class RecordingSession:
    """Projects only the columns the SQL asked for; invents nothing."""

    SETTINGS = {
        "id": "qs-1", "business_id": "biz-1", "quote_prefix": "QTE-",
        "next_quote_number": 1, "default_terms": "Terms.", "default_valid_days": 30,
        "default_tax_rate": Decimal("20"), "include_tax": True,
        "default_markup": Decimal("0"), "company_name": "Test Co",
        "company_address": None, "company_phone": None, "company_email": None,
        "company_logo_url": None, "company_registration": None, "vat_number": None,
        "industry": "general", "labour_rates": [],
    }
    BUSINESS = {
        "id": "biz-1", "name": "Test Co", "region": "UK",
        "tax_registered": True, "tax_number": None, "currency": "GBP",
    }

    def __init__(self, quote=None):
        self.quote = quote
        self.statements = []

    def execute(self, statement, params=None):
        assert isinstance(statement, TextClause), f"expected TextClause, got {type(statement)}"
        sql = " ".join(statement.text.split())
        self.statements.append((sql, params))
        if not sql.upper().startswith("SELECT"):
            return FakeResult(None)
        if re.search(r"FROM\s+businesses", sql, re.I):
            source = self.BUSINESS
        elif re.search(r"FROM\s+quotes", sql, re.I):
            source = self.quote
        else:
            source = self.SETTINGS
        if source is None:
            return FakeResult(None)
        clause = re.search(r"SELECT\s+(.*?)\s+FROM", sql, re.I | re.S)
        assert clause, f"unparseable SELECT: {sql}"
        raw = clause.group(1).strip()
        columns = list(source) if raw == "*" else [c.strip().split()[-1] for c in raw.split(",")]
        missing = [c for c in columns if c not in source]
        assert not missing, f"query selected {missing}, which this fake does not hold: {sql}"
        return FakeResult(FakeRow(columns, [source[c] for c in columns]))

    def commit(self):
        pass

    def params_for(self, fragment):
        matches = [p for sql, p in self.statements if fragment.upper() in sql.upper()]
        assert matches, f"no statement matching {fragment!r}"
        return matches[0]


def create(session, line_items, discount, discount_type="fixed"):
    return asyncio.run(quoting_api.create_quote(
        data={
            "customer_name": "A Customer",
            "job_title": "A Job",
            "line_items": line_items,
            "discount_amount": discount,
            "discount_type": discount_type,
        },
        auth_ctx={"business_id": "biz-1", "user_id": "user-1"},
        session=session,
    ))


ONE_HUNDRED = [{"description": "Work", "quantity": 1, "unit_cost": 100.00}]


class TestDiscountBelowNet(unittest.TestCase):
    """discount < net — the ordinary case."""

    def test_is_accepted(self):
        session = RecordingSession()
        create(session, ONE_HUNDRED, 30)
        params = session.params_for("INSERT INTO quotes")
        self.assertEqual(params["subtotal"], Decimal("100.00"))
        self.assertEqual(params["discount_amount"], Decimal("30"))

    def test_totals_reflect_the_discount(self):
        # net 70.00, VAT at 20% is 14.00, gross 84.00
        session = RecordingSession()
        create(session, ONE_HUNDRED, 30)
        params = session.params_for("INSERT INTO quotes")
        self.assertEqual(params["tax_amount"], Decimal("14.00"))
        self.assertEqual(params["total"], Decimal("84.00"))

    def test_a_percentage_below_one_hundred_is_accepted(self):
        session = RecordingSession()
        create(session, ONE_HUNDRED, 25, discount_type="percentage")
        params = session.params_for("INSERT INTO quotes")
        self.assertEqual(params["total"], Decimal("90.00"))


class TestDiscountEqualToNet(unittest.TestCase):
    """discount == net — valid, and the quote totals zero."""

    def test_is_accepted(self):
        session = RecordingSession()
        create(session, ONE_HUNDRED, 100)
        params = session.params_for("INSERT INTO quotes")
        self.assertEqual(params["discount_amount"], Decimal("100"))

    def test_total_is_zero(self):
        session = RecordingSession()
        create(session, ONE_HUNDRED, 100)
        params = session.params_for("INSERT INTO quotes")
        self.assertEqual(params["subtotal"], Decimal("100.00"))
        self.assertEqual(params["tax_amount"], Decimal("0.00"))
        self.assertEqual(params["total"], Decimal("0.00"))

    def test_one_hundred_percent_is_accepted(self):
        session = RecordingSession()
        create(session, ONE_HUNDRED, 100, discount_type="percentage")
        params = session.params_for("INSERT INTO quotes")
        self.assertEqual(params["total"], Decimal("0.00"))

    def test_equal_to_net_after_a_line_discount_is_accepted(self):
        # line 100.00 less a 40.00 line discount leaves a net of 60.00
        lines = [{"description": "Work", "quantity": 1, "unit_cost": 100.00,
                  "discount_amount": 40.00, "discount_type": "fixed"}]
        session = RecordingSession()
        create(session, lines, 60)
        params = session.params_for("INSERT INTO quotes")
        self.assertEqual(params["total"], Decimal("0.00"))


class TestDiscountAboveNet(unittest.TestCase):
    """discount > net — rejected, naming both numbers."""

    def _rejected(self, line_items, discount, discount_type="fixed"):
        session = RecordingSession()
        with self.assertRaises(HTTPException) as ctx:
            create(session, line_items, discount, discount_type)
        self.assertEqual(ctx.exception.status_code, 400)
        return ctx.exception.detail

    def test_is_rejected_with_400(self):
        self._rejected(ONE_HUNDRED, Decimal("100.01"))

    def test_error_names_both_the_discount_and_the_net(self):
        detail = self._rejected(ONE_HUNDRED, Decimal("100.01"))
        self.assertIn("100.01", detail, f"detail does not name the discount: {detail}")
        self.assertIn("100.00", detail, f"detail does not name the net: {detail}")

    def test_a_percentage_over_one_hundred_is_rejected(self):
        detail = self._rejected(ONE_HUNDRED, Decimal("110"), discount_type="percentage")
        self.assertIn("110.00", detail)
        self.assertIn("100.00", detail)

    def test_the_net_is_measured_after_line_discounts(self):
        # Subtotal is 100.00 but a 50.00 line discount leaves a net of 50.00,
        # so a 60.00 quote discount is too big even though it is below the
        # subtotal. Measuring against the gross would wrongly allow this.
        lines = [{"description": "Work", "quantity": 1, "unit_cost": 100.00,
                  "discount_amount": 50.00, "discount_type": "fixed"}]
        detail = self._rejected(lines, Decimal("60"))
        self.assertIn("60.00", detail)
        self.assertIn("50.00", detail)

    def test_nothing_is_written_when_the_discount_is_rejected(self):
        session = RecordingSession()
        with self.assertRaises(HTTPException):
            create(session, ONE_HUNDRED, Decimal("100.01"))
        writes = [sql for sql, _ in session.statements
                  if sql.upper().startswith(("INSERT INTO QUOTES", "INSERT INTO QUOTE_LINE_ITEMS"))]
        self.assertEqual(writes, [], f"a rejected quote still wrote rows: {writes}")


class TestUpdateAppliesTheSameRule(unittest.TestCase):
    """The rule holds on edit, not only on create."""

    QUOTE = {"id": "quote-1", "status": "draft", "tax_rate": Decimal("20"),
             "discount_amount": Decimal("0"), "discount_type": "fixed",
             "business_id": "biz-1"}

    def _update(self, discount):
        session = RecordingSession(quote=dict(self.QUOTE))
        return session, asyncio.run(quoting_api.update_quote(
            quote_id="quote-1",
            data={"customer_name": "A Customer", "job_title": "A Job",
                  "line_items": ONE_HUNDRED, "discount_amount": discount,
                  "discount_type": "fixed"},
            auth_ctx={"business_id": "biz-1", "user_id": "user-1"},
            session=session,
        ))

    def test_equal_to_net_is_accepted_on_update(self):
        session, _ = self._update(100)
        self.assertEqual(session.params_for("UPDATE quotes")["total"], Decimal("0.00"))

    def test_above_net_is_rejected_on_update(self):
        with self.assertRaises(HTTPException) as ctx:
            self._update(Decimal("100.01"))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("100.01", ctx.exception.detail)


if __name__ == "__main__":
    unittest.main()
