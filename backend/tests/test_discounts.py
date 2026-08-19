"""
ITEM 2 / D5 — line-level discounts alongside the quote-level discount.

Order (spec D5), applied in exactly one place:

    line_total  ->  line discount  ->  quote discount apportioned pro-rata
                    by line net    ->  per-line tax on the discounted net

Contract additions to `services.money.calculate_totals`:

    each line item may carry
        discount_amount   Decimal
        discount_type     "fixed" | "percentage"

    each returned line carries
        line_total            gross, 2dp
        line_discount         2dp
        apportioned_discount  this line's share of the quote discount, 2dp
        taxable               net after both discounts, 2dp
        tax_rate / tax_amount / tax_treatment

    the result carries
        subtotal              sum of line_total
        line_discount_total   sum of line_discount
        discount_applied      the quote-level discount, 2dp
        taxable / tax_amount / total

THE INVARIANT these tests exist to protect:

    sum(line.taxable) == result["taxable"]              exactly
    sum(line.apportioned_discount) == discount_applied  exactly

An apportionment that does not divide evenly is where this breaks. £10 across
three equal lines gives 3.33 each and loses a penny; the remainder — of either
sign — goes to the largest line by net, ties broken by lowest sort_order.
Without that rule the invoice does not add up, and an invoice that does not add
up is the one thing a customer always notices.

Every expected value below was computed independently and checked against the
invariant before being written down.
"""
import unittest
from decimal import Decimal


def money():
    """Imported per-test so each test fails on its own, not at collection."""
    from services import money as _money
    return _money


def line(unit_cost, discount=None, discount_type="fixed", qty="1", **extra):
    item = {
        "quantity": Decimal(qty),
        "unit_cost": Decimal(unit_cost),
        "discount_amount": Decimal(discount) if discount is not None else Decimal("0"),
        "discount_type": discount_type,
    }
    item.update(extra)
    return item


def decimals(values):
    return [Decimal(v) for v in values]


class DiscountCase(unittest.TestCase):
    """Shared assertions. Every case must satisfy the invariant."""

    def assert_invariant(self, result):
        lines = result["lines"]
        self.assertTrue(lines, "no lines were returned — nothing was asserted")

        self.assertEqual(
            sum((item["taxable"] for item in lines), Decimal("0")),
            result["taxable"],
            "sum of line taxables != quote taxable — the invoice does not add up",
        )
        self.assertEqual(
            sum((item["apportioned_discount"] for item in lines), Decimal("0")),
            result["discount_applied"],
            "apportioned shares do not sum to the quote discount",
        )
        self.assertEqual(
            sum((item["line_total"] for item in lines), Decimal("0")),
            result["subtotal"],
        )
        self.assertEqual(
            sum((item["line_discount"] for item in lines), Decimal("0")),
            result["line_discount_total"],
        )
        self.assertEqual(
            result["taxable"],
            result["subtotal"] - result["line_discount_total"] - result["discount_applied"],
            "the quote taxable was derived independently of the lines — there "
            "must be exactly one derivation, not two that can disagree",
        )
        self.assertEqual(
            sum((item["tax_amount"] for item in lines), Decimal("0")),
            result["tax_amount"],
        )
        self.assertEqual(result["taxable"] + result["tax_amount"], result["total"])


class TestUnevenApportionment(DiscountCase):
    """
    Criterion: sum of line taxables equals the quote taxable exactly, including
    discounts that do not divide evenly.
    """

    def test_ten_pounds_across_three_equal_lines(self):
        # 10.00 / 3 = 3.3333 -> 3.33 each = 9.99. The missing penny goes to the
        # largest line; all three tie on net, so it goes to the first.
        result = money().calculate_totals(
            [line("10.00"), line("10.00"), line("10.00")],
            tax_rate=Decimal("20"),
            discount_amount=Decimal("10"),
            discount_type="fixed",
        )
        self.assertEqual(
            [item["apportioned_discount"] for item in result["lines"]],
            decimals(["3.34", "3.33", "3.33"]),
        )
        self.assertEqual(
            [item["taxable"] for item in result["lines"]],
            decimals(["6.66", "6.67", "6.67"]),
        )
        self.assertEqual(result["taxable"], Decimal("20.00"))
        self.assert_invariant(result)

    def test_uneven_apportionment_still_taxes_per_line(self):
        # Per-line tax on 6.66 / 6.67 / 6.67 sums to 3.99, where 20% of the
        # 20.00 quote taxable would be 4.00. D2 says per-line wins.
        result = money().calculate_totals(
            [line("10.00"), line("10.00"), line("10.00")],
            tax_rate=Decimal("20"),
            discount_amount=Decimal("10"),
            discount_type="fixed",
        )
        self.assertEqual(result["tax_amount"], Decimal("3.99"))
        self.assertEqual(result["total"], Decimal("23.99"))

    def test_negative_remainder_is_taken_off_the_largest_line(self):
        # 5 / 5 / 20 with a 10.00 discount apportions to 1.67 + 1.67 + 6.67 =
        # 10.01, a penny too much. The overshoot comes off the largest line.
        result = money().calculate_totals(
            [line("5.00"), line("5.00"), line("20.00")],
            tax_rate=Decimal("20"),
            discount_amount=Decimal("10"),
            discount_type="fixed",
        )
        self.assertEqual(
            [item["apportioned_discount"] for item in result["lines"]],
            decimals(["1.67", "1.67", "6.66"]),
        )
        self.assertEqual(
            [item["taxable"] for item in result["lines"]],
            decimals(["3.33", "3.33", "13.34"]),
        )
        self.assert_invariant(result)

    def test_remainder_goes_to_the_largest_line_not_the_first(self):
        # Guards the rule against being implemented as "give it to line 0",
        # which happens to be right for the tied case above and wrong here.
        result = money().calculate_totals(
            [line("5.00"), line("5.00"), line("20.00")],
            tax_rate=Decimal("20"),
            discount_amount=Decimal("10"),
            discount_type="fixed",
        )
        self.assertEqual(result["lines"][0]["apportioned_discount"], Decimal("1.67"))
        self.assertEqual(result["lines"][2]["apportioned_discount"], Decimal("6.66"))

    def test_seven_uneven_lines(self):
        result = money().calculate_totals(
            [line(v) for v in ("1.00", "2.00", "3.00", "5.00", "7.00", "11.00", "13.00")],
            tax_rate=Decimal("20"),
            discount_amount=Decimal("10"),
            discount_type="fixed",
        )
        self.assertEqual(
            [item["apportioned_discount"] for item in result["lines"]],
            decimals(["0.24", "0.48", "0.71", "1.19", "1.67", "2.62", "3.09"]),
        )
        self.assertEqual(result["taxable"], Decimal("32.00"))
        self.assertEqual(result["tax_amount"], Decimal("6.40"))
        self.assert_invariant(result)

    def test_a_single_line_takes_the_whole_discount(self):
        result = money().calculate_totals(
            [line("10.00")],
            tax_rate=Decimal("20"),
            discount_amount=Decimal("3.33"),
            discount_type="fixed",
        )
        self.assertEqual(
            result["lines"][0]["apportioned_discount"], Decimal("3.33")
        )
        self.assert_invariant(result)


class TestOrderOfOperations(DiscountCase):
    """
    Criterion (D5): the quote discount is apportioned pro-rata by line NET —
    after line discounts — not by gross line_total.
    """

    LINES = [line("100.00", discount="50.00"), line("100.00")]

    def test_apportionment_weights_are_the_post_line_discount_nets(self):
        # Nets are 50 and 100, so a 30.00 quote discount splits 10 / 20.
        # Weighting by the gross 100 / 100 would split it 15 / 15.
        result = money().calculate_totals(
            list(self.LINES),
            tax_rate=Decimal("20"),
            discount_amount=Decimal("30"),
            discount_type="fixed",
        )
        self.assertEqual(
            [item["apportioned_discount"] for item in result["lines"]],
            decimals(["10.00", "20.00"]),
        )
        self.assertNotEqual(
            [item["apportioned_discount"] for item in result["lines"]],
            decimals(["15.00", "15.00"]),
        )
        self.assert_invariant(result)

    def test_line_discount_is_recorded_separately_from_the_apportioned_share(self):
        result = money().calculate_totals(
            list(self.LINES),
            tax_rate=Decimal("20"),
            discount_amount=Decimal("30"),
            discount_type="fixed",
        )
        first = result["lines"][0]
        self.assertEqual(first["line_total"], Decimal("100.00"))
        self.assertEqual(first["line_discount"], Decimal("50.00"))
        self.assertEqual(first["apportioned_discount"], Decimal("10.00"))
        self.assertEqual(first["taxable"], Decimal("40.00"))

    def test_tax_is_charged_on_the_taxable_not_the_line_total(self):
        result = money().calculate_totals(
            list(self.LINES),
            tax_rate=Decimal("20"),
            discount_amount=Decimal("30"),
            discount_type="fixed",
        )
        self.assertEqual(
            [item["tax_amount"] for item in result["lines"]],
            decimals(["8.00", "16.00"]),
        )
        self.assertEqual(result["total"], Decimal("144.00"))

    def test_percentage_line_discount_is_taken_on_the_line_total(self):
        result = money().calculate_totals(
            [line("100.00", discount="10", discount_type="percentage"),
             line("50.00", discount="10.00")],
            tax_rate=Decimal("20"),
            discount_amount=Decimal("13"),
            discount_type="fixed",
        )
        self.assertEqual(
            [item["line_discount"] for item in result["lines"]],
            decimals(["10.00", "10.00"]),
        )
        self.assertEqual(
            [item["taxable"] for item in result["lines"]],
            decimals(["81.00", "36.00"]),
        )
        self.assertEqual(result["total"], Decimal("140.40"))
        self.assert_invariant(result)


class TestPercentageQuoteDiscount(DiscountCase):
    """
    Criterion (D5): a percentage quote discount is taken on the net AFTER line
    discounts, not on the gross subtotal.
    """

    def test_percentage_is_taken_on_the_post_line_discount_net(self):
        # Subtotal 200, line discounts 50, net 150. 20% of 150 is 30.00.
        # 20% of the gross 200 would be 40.00.
        result = money().calculate_totals(
            [line("100.00", discount="50.00"), line("100.00")],
            tax_rate=Decimal("20"),
            discount_amount=Decimal("20"),
            discount_type="percentage",
        )
        self.assertEqual(result["discount_applied"], Decimal("30.00"))
        self.assertNotEqual(result["discount_applied"], Decimal("40.00"))
        self.assert_invariant(result)

    def test_percentage_and_fixed_agree_when_they_describe_the_same_money(self):
        # 20% of the 150.00 net IS 30.00. The two spellings must not produce
        # two different invoices.
        common = dict(tax_rate=Decimal("20"))
        as_percentage = money().calculate_totals(
            [line("100.00", discount="50.00"), line("100.00")],
            discount_amount=Decimal("20"), discount_type="percentage", **common,
        )
        as_fixed = money().calculate_totals(
            [line("100.00", discount="50.00"), line("100.00")],
            discount_amount=Decimal("30"), discount_type="fixed", **common,
        )
        self.assertEqual(as_percentage["taxable"], as_fixed["taxable"])
        self.assertEqual(as_percentage["tax_amount"], as_fixed["tax_amount"])
        self.assertEqual(as_percentage["total"], as_fixed["total"])
        self.assertEqual(
            [i["apportioned_discount"] for i in as_percentage["lines"]],
            [i["apportioned_discount"] for i in as_fixed["lines"]],
        )


class TestBothDiscountTypesTogether(DiscountCase):
    """
    Criterion: both discount types applied to the same quote produce a
    consistent, defined result — in every combination of line-level and
    quote-level fixed/percentage.
    """

    COMBINATIONS = [
        ("fixed line, fixed quote", "12.00", "fixed", Decimal("20"), "fixed"),
        ("fixed line, pct quote", "12.00", "fixed", Decimal("15"), "percentage"),
        ("pct line, fixed quote", "10", "percentage", Decimal("20"), "fixed"),
        ("pct line, pct quote", "10", "percentage", Decimal("15"), "percentage"),
    ]

    def test_every_combination_holds_the_invariant(self):
        calculate = money().calculate_totals   # outside the loop on purpose
        for name, ld, ldt, qd, qdt in self.COMBINATIONS:
            with self.subTest(combination=name):
                result = calculate(
                    [line("100.00", discount=ld, discount_type=ldt),
                     line("33.33", discount=ld, discount_type=ldt),
                     line("66.67", discount=ld, discount_type=ldt)],
                    tax_rate=Decimal("20"),
                    discount_amount=qd,
                    discount_type=qdt,
                )
                self.assert_invariant(result)

    def test_every_combination_returns_the_full_line_shape(self):
        calculate = money().calculate_totals
        required = {"line_total", "line_discount", "apportioned_discount",
                    "taxable", "tax_rate", "tax_amount"}
        for name, ld, ldt, qd, qdt in self.COMBINATIONS:
            with self.subTest(combination=name):
                result = calculate(
                    [line("100.00", discount=ld, discount_type=ldt)],
                    tax_rate=Decimal("20"), discount_amount=qd, discount_type=qdt,
                )
                self.assertTrue(required.issubset(result["lines"][0].keys()))

    def test_a_line_discount_with_no_quote_discount_is_defined(self):
        result = money().calculate_totals(
            [line("100.00", discount="25.00"), line("100.00")],
            tax_rate=Decimal("20"),
            discount_amount=Decimal("0"),
            discount_type="fixed",
        )
        self.assertEqual(result["line_discount_total"], Decimal("25.00"))
        self.assertEqual(result["discount_applied"], Decimal("0.00"))
        self.assertEqual(result["taxable"], Decimal("175.00"))
        self.assert_invariant(result)

    def test_a_quote_discount_with_no_line_discount_is_defined(self):
        result = money().calculate_totals(
            [line("100.00"), line("100.00")],
            tax_rate=Decimal("20"),
            discount_amount=Decimal("25"),
            discount_type="fixed",
        )
        self.assertEqual(result["line_discount_total"], Decimal("0.00"))
        self.assertEqual(result["discount_applied"], Decimal("25.00"))
        self.assertEqual(result["taxable"], Decimal("175.00"))
        self.assert_invariant(result)

    def test_no_discounts_at_all_is_still_the_same_shape(self):
        result = money().calculate_totals(
            [line("100.00")], tax_rate=Decimal("20"),
        )
        self.assertEqual(result["line_discount_total"], Decimal("0.00"))
        self.assertEqual(result["discount_applied"], Decimal("0.00"))
        self.assertEqual(result["taxable"], Decimal("100.00"))
        self.assert_invariant(result)


class TestDiscountEdges(DiscountCase):
    """Degenerate inputs that must not crash the money path."""

    def test_a_zero_net_quote_does_not_divide_by_zero(self):
        # Every line fully discounted away. Pro-rata weights sum to zero, and
        # a naive implementation divides by it.
        result = money().calculate_totals(
            [line("100.00", discount="100.00"), line("50.00", discount="50.00")],
            tax_rate=Decimal("20"),
            discount_amount=Decimal("10"),
            discount_type="fixed",
        )
        self.assertEqual(result["taxable"], Decimal("0.00"))
        self.assertEqual(result["tax_amount"], Decimal("0.00"))

    def test_discount_values_are_decimal_on_every_line(self):
        result = money().calculate_totals(
            [line("10.00"), line("10.00"), line("10.00")],
            tax_rate=Decimal("20"), discount_amount=Decimal("10"),
        )
        self.assertTrue(result["lines"], "no lines returned")
        for item in result["lines"]:
            self.assertIsInstance(item["apportioned_discount"], Decimal)
            self.assertIsInstance(item["taxable"], Decimal)
            self.assertNotIsInstance(item["apportioned_discount"], float)

    def test_apportioned_shares_are_quantised_to_2dp(self):
        result = money().calculate_totals(
            [line("10.00"), line("10.00"), line("10.00")],
            tax_rate=Decimal("20"), discount_amount=Decimal("10"),
        )
        self.assertTrue(result["lines"], "no lines returned")
        for item in result["lines"]:
            self.assertEqual(item["apportioned_discount"].as_tuple().exponent, -2)
            self.assertEqual(item["taxable"].as_tuple().exponent, -2)


if __name__ == "__main__":
    unittest.main()
