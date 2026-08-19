"""
ITEM 2 — money arithmetic: per-line tax, ROUND_HALF_UP, Decimal, 4dp unit prices.

Target surface (does not exist yet):

    backend/services/money.py
        calculate_totals(
            line_items,                  # iterable of dicts
            *,
            tax_rate,                    # Decimal percentage, e.g. Decimal("20")
            discount_amount=Decimal("0"),
            discount_type="fixed",       # "fixed" | "percentage"
            tax_registered=True,
        ) -> dict with keys:
            subtotal        Decimal, 2dp
            tax_amount      Decimal, 2dp
            total           Decimal, 2dp
            discount_applied Decimal, 2dp
            tax_applicable  bool
            lines           list of dicts, each with line_total / tax_amount /
                            tax_rate / tax_treatment

        invoice_line_summary(lines) -> {subtotal, tax_amount, total}
            empty-safe, for historical invoices that have no line items

Spec decisions encoded: D2 (per-line tax, ROUND_HALF_UP to 2dp, then summed;
unit prices 4dp) and D3 (not tax-registered => no tax at all).

Why ROUND_HALF_UP matters here: the current implementation
(quoting_api.py:73-76) uses Python's round(), which is banker's rounding.
Verified against live code today: a 0.625 subtotal rounds DOWN to 0.62 and a
0.125 tax rounds DOWN to 0.12. Both are a penny short in the customer's
favour, on every affected line, forever.
"""
import unittest
from decimal import Decimal


def money():
    """Imported per-test so each test fails on its own, not at collection."""
    from services import money as _money
    return _money


def line(qty, unit_cost, **extra):
    item = {"quantity": Decimal(str(qty)), "unit_cost": Decimal(str(unit_cost))}
    item.update(extra)
    return item


class TestRoundHalfUp(unittest.TestCase):
    """Criterion (D2): per-line tax, ROUND_HALF_UP to 2dp, then summed."""

    def test_half_rounds_up_not_to_even_on_line_total(self):
        # 0.625 -> 0.63 under HALF_UP. Python's round() gives 0.62.
        result = money().calculate_totals([line(1, "0.6250")], tax_rate=Decimal("20"))
        self.assertEqual(result["subtotal"], Decimal("0.63"))

    def test_half_rounds_up_not_to_even_on_tax(self):
        # net 0.625 @ 20% = 0.125 tax -> 0.13 under HALF_UP, 0.12 under round().
        result = money().calculate_totals([line(1, "0.6250")], tax_rate=Decimal("20"))
        self.assertEqual(result["tax_amount"], Decimal("0.13"))

    def test_tax_is_rounded_per_line_then_summed_not_on_the_subtotal(self):
        # Three lines of 3.33 net at 20%.
        #   per line: 0.666 -> 0.67, summed = 2.01   <- required
        #   on subtotal: 9.99 * 0.20 = 1.998 -> 2.00 <- what the code does today
        # 1p. On eighty invoices it is eighty pence and a reconciliation that
        # never balances.
        lines = [line(1, "3.33"), line(1, "3.33"), line(1, "3.33")]
        result = money().calculate_totals(lines, tax_rate=Decimal("20"))
        self.assertEqual(result["subtotal"], Decimal("9.99"))
        self.assertEqual(result["tax_amount"], Decimal("2.01"))
        self.assertEqual(result["total"], Decimal("12.00"))

    def test_every_returned_money_value_is_quantised_to_2dp(self):
        result = money().calculate_totals([line(3, "1.005")], tax_rate=Decimal("20"))
        for key in ("subtotal", "tax_amount", "total", "discount_applied"):
            with self.subTest(key=key):
                self.assertEqual(
                    result[key].as_tuple().exponent, -2,
                    f"{key}={result[key]!r} is not quantised to exactly 2dp",
                )


class TestFourDecimalUnitPrices(unittest.TestCase):
    """Criterion: unit_cost carries 4dp; money totals stay 2dp."""

    def test_four_dp_unit_price_is_not_truncated_to_two(self):
        # The spec's own example: 47.5 m2 at 3.3333/m2.
        #   full precision: 47.5 * 3.3333 = 158.331750 -> 158.33
        #   truncated to 3.33: 47.5 * 3.33 = 158.175   -> 158.18
        result = money().calculate_totals(
            [line("47.5", "3.3333")], tax_rate=Decimal("0"), tax_registered=False
        )
        self.assertEqual(result["subtotal"], Decimal("158.33"))
        self.assertNotEqual(
            result["subtotal"], Decimal("158.18"),
            "unit_cost was rounded to 2dp before multiplying — the 15p error",
        )

    def test_four_dp_precision_survives_a_large_quantity(self):
        # 1000 tonnes at 0.0001 apart is 10p — the error scales with quantity.
        result = money().calculate_totals(
            [line(1000, "12.3456")], tax_rate=Decimal("0"), tax_registered=False
        )
        self.assertEqual(result["subtotal"], Decimal("12345.60"))


class TestDecimalThroughout(unittest.TestCase):
    """Criterion: all new arithmetic uses Decimal, never float."""

    def test_all_money_outputs_are_decimal(self):
        result = money().calculate_totals([line(2, "10.00")], tax_rate=Decimal("20"))
        for key in ("subtotal", "tax_amount", "total", "discount_applied"):
            with self.subTest(key=key):
                self.assertIsInstance(result[key], Decimal)
                self.assertNotIsInstance(result[key], float)

    def test_per_line_outputs_are_decimal(self):
        result = money().calculate_totals([line(2, "10.00")], tax_rate=Decimal("20"))
        for item in result["lines"]:
            self.assertIsInstance(item["line_total"], Decimal)
            self.assertIsInstance(item["tax_amount"], Decimal)

    def test_float_input_is_rejected_rather_than_silently_coerced(self):
        # A float that reaches the money path is a bug upstream. Failing loudly
        # is the only way it gets found; coercing it hides it forever.
        with self.assertRaises((TypeError, ValueError)):
            money().calculate_totals(
                [{"quantity": 1, "unit_cost": 10.1}], tax_rate=Decimal("20")
            )


class TestInternalConsistency(unittest.TestCase):
    """
    Criteria: stored subtotal equals the sum of stored line_totals exactly —
    no second, differently-derived subtotal anywhere; and
    subtotal + tax_amount = total exactly.
    """

    def test_subtotal_equals_sum_of_line_totals_exactly(self):
        lines = [line(3, "19.9900"), line("2.5", "7.7777"), line(1, "0.0050")]
        result = money().calculate_totals(lines, tax_rate=Decimal("20"))
        self.assertEqual(
            result["subtotal"],
            sum((item["line_total"] for item in result["lines"]), Decimal("0")),
        )

    def test_tax_amount_equals_sum_of_line_tax_exactly(self):
        lines = [line(3, "19.9900"), line("2.5", "7.7777"), line(1, "0.0050")]
        result = money().calculate_totals(lines, tax_rate=Decimal("20"))
        self.assertEqual(
            result["tax_amount"],
            sum((item["tax_amount"] for item in result["lines"]), Decimal("0")),
        )

    def test_subtotal_plus_tax_equals_total_exactly(self):
        lines = [line(3, "19.9900"), line("2.5", "7.7777"), line(1, "0.0050")]
        result = money().calculate_totals(lines, tax_rate=Decimal("20"))
        self.assertEqual(result["subtotal"] + result["tax_amount"], result["total"])


class TestDiscounts(unittest.TestCase):
    """Discount is applied before tax, and is itself 2dp."""

    def test_fixed_discount_reduces_the_taxable_base(self):
        result = money().calculate_totals(
            [line(1, "100.00")],
            tax_rate=Decimal("20"),
            discount_amount=Decimal("10.00"),
            discount_type="fixed",
        )
        self.assertEqual(result["discount_applied"], Decimal("10.00"))
        self.assertEqual(result["tax_amount"], Decimal("18.00"))
        self.assertEqual(result["total"], Decimal("108.00"))

    def test_percentage_discount_reduces_the_taxable_base(self):
        result = money().calculate_totals(
            [line(1, "100.00")],
            tax_rate=Decimal("20"),
            discount_amount=Decimal("10"),
            discount_type="percentage",
        )
        self.assertEqual(result["discount_applied"], Decimal("10.00"))
        self.assertEqual(result["total"], Decimal("108.00"))


class TestTaxTreatmentIsDisplayOnly(unittest.TestCase):
    """
    Criterion: each line carries a tax_treatment label — stored and displayed
    only, it drives NO calculation.

    This is the criterion most likely to be implemented "helpfully" wrong, by
    someone deciding that `exempt` ought to zero the line. It must not. Business
    Hero does not determine taxability (spec preamble); the rate the business
    entered is the rate that is charged.
    """

    def test_exempt_label_does_not_zero_the_tax(self):
        result = money().calculate_totals(
            [line(1, "100.00", tax_treatment="exempt")], tax_rate=Decimal("20")
        )
        self.assertEqual(result["tax_amount"], Decimal("20.00"))

    def test_treatment_label_is_carried_through_to_the_line(self):
        result = money().calculate_totals(
            [line(1, "100.00", tax_treatment="reverse_charge")], tax_rate=Decimal("20")
        )
        self.assertEqual(result["lines"][0]["tax_treatment"], "reverse_charge")

    def test_all_labels_produce_identical_arithmetic(self):
        amounts = set()
        for label in ("standard", "reduced", "zero", "exempt", "reverse_charge",
                      "taxable"):
            result = money().calculate_totals(
                [line(1, "100.00", tax_treatment=label)], tax_rate=Decimal("20")
            )
            amounts.add(result["tax_amount"])
        self.assertEqual(
            amounts, {Decimal("20.00")},
            "a tax_treatment label changed the arithmetic — it must not",
        )

    def test_rate_is_stored_per_line_even_when_uniform(self):
        result = money().calculate_totals(
            [line(1, "100.00"), line(1, "50.00")], tax_rate=Decimal("20")
        )
        self.assertEqual([i["tax_rate"] for i in result["lines"]],
                         [Decimal("20"), Decimal("20")])


class TestNotTaxRegistered(unittest.TestCase):
    """
    Criterion (D3): if a business is not tax-registered, omit tax entirely.
    Never print "VAT 0.00" — it implies a registration the business does not
    have, and charging VAT unregistered is illegal.
    """

    def test_no_tax_is_charged(self):
        result = money().calculate_totals(
            [line(1, "100.00")], tax_rate=Decimal("20"), tax_registered=False
        )
        self.assertEqual(result["tax_amount"], Decimal("0.00"))
        self.assertEqual(result["total"], result["subtotal"])

    def test_tax_applicable_flag_is_false_so_renderers_can_omit_the_line(self):
        result = money().calculate_totals(
            [line(1, "100.00")], tax_rate=Decimal("20"), tax_registered=False
        )
        self.assertFalse(result["tax_applicable"])

    def test_tax_applicable_is_true_for_a_registered_business_at_zero_rate(self):
        # A registered business on a 0% rate is NOT the same thing as an
        # unregistered one. It still shows a tax line, at zero.
        result = money().calculate_totals(
            [line(1, "100.00")], tax_rate=Decimal("0"), tax_registered=True
        )
        self.assertTrue(result["tax_applicable"])
        self.assertEqual(result["tax_amount"], Decimal("0.00"))


class TestEmptyLineItems(unittest.TestCase):
    """
    Criterion: existing invoices with no line items still render everywhere
    they render today — no blank screens, no exceptions on historical data.
    Three of the five invoices in prod are legacy CSV rows with no lines.
    """

    def test_summary_of_no_lines_is_zeros_not_an_exception(self):
        summary = money().invoice_line_summary([])
        self.assertEqual(summary["subtotal"], Decimal("0.00"))
        self.assertEqual(summary["tax_amount"], Decimal("0.00"))
        self.assertEqual(summary["total"], Decimal("0.00"))

    def test_calculate_totals_of_no_lines_is_zeros_not_an_exception(self):
        result = money().calculate_totals([], tax_rate=Decimal("20"))
        self.assertEqual(result["subtotal"], Decimal("0.00"))
        self.assertEqual(result["total"], Decimal("0.00"))
        self.assertEqual(result["lines"], [])


if __name__ == "__main__":
    unittest.main()
