"""
ITEM 4 — parse_amount.

`backend/main.py:2143` is a two-line stub that returns None for every input.
`git log -L` shows it has been that way since the original invoice commit,
so CSV invoice import has never worked.

Contract pinned here (spec Item 4):
  * returns Decimal, never float
  * handles 1234.56, GBP/USD symbols, thousands separators, negatives, integers
  * returns None for empty / whitespace / unparseable — NEVER 0.0

The last one is the point. A silent zero on a money import is worse than a
rejection, because nothing downstream can tell the difference between
"this invoice was for nothing" and "we could not read the amount".
"""
import unittest
from decimal import Decimal

from main import parse_amount


class TestParseAmountReturnsDecimal(unittest.TestCase):
    """Criterion: returns Decimal, not float."""

    def test_returns_decimal_not_float(self):
        result = parse_amount("50")
        self.assertIsInstance(result, Decimal)
        self.assertNotIsInstance(result, float)

    def test_decimal_is_exact_not_binary_approximated(self):
        # 0.1 + 0.2 != 0.3 in float. The whole reason for Decimal.
        self.assertEqual(
            parse_amount("0.10") + parse_amount("0.20"),
            Decimal("0.30"),
        )


class TestParseAmountValidInputs(unittest.TestCase):
    """Criterion: handles 1234.56, GBP1,234.56, $1,234.56, 1,234.56, -50.00, 50."""

    def test_plain_decimal(self):
        self.assertEqual(parse_amount("1234.56"), Decimal("1234.56"))

    def test_pound_symbol_and_thousands_separator(self):
        self.assertEqual(parse_amount("£1,234.56"), Decimal("1234.56"))

    def test_dollar_symbol_and_thousands_separator(self):
        self.assertEqual(parse_amount("$1,234.56"), Decimal("1234.56"))

    def test_euro_symbol_is_stripped(self):
        self.assertEqual(parse_amount("€99.99"), Decimal("99.99"))

    def test_thousands_separator_without_symbol(self):
        self.assertEqual(parse_amount("1,234.56"), Decimal("1234.56"))

    def test_negative(self):
        self.assertEqual(parse_amount("-50.00"), Decimal("-50.00"))

    def test_bare_integer(self):
        self.assertEqual(parse_amount("50"), Decimal("50"))

    def test_surrounding_whitespace_is_tolerated(self):
        self.assertEqual(parse_amount("  42.50  "), Decimal("42.50"))

    def test_millions_with_multiple_separators(self):
        self.assertEqual(parse_amount("£1,234,567.89"), Decimal("1234567.89"))

    def test_trailing_zeros_preserved_as_written(self):
        # Decimal("100.00") == Decimal("100") compares equal, so assert the
        # scale explicitly — a money value that loses its scale loses its
        # pennies when it is later quantised.
        self.assertEqual(parse_amount("100.00"), Decimal("100.00"))


class TestParseAmountRejections(unittest.TestCase):
    """Criterion: None for empty, whitespace or unparseable input — never 0.0."""

    def _assert_parser_is_live(self):
        # A None return only means "rejected" if the parser is capable of
        # returning something else. Against the current stub EVERY input
        # returns None, which would make every assertion in this class
        # vacuously true. So prove liveness first, then trust the None.
        self.assertEqual(
            parse_amount("1.00"),
            Decimal("1.00"),
            "parser is not live — a None below would prove nothing",
        )

    def _assert_rejected(self, value):
        self._assert_parser_is_live()
        result = parse_amount(value)
        self.assertIsNone(
            result,
            f"parse_amount({value!r}) must return None, got {result!r}",
        )
        # Belt and braces: the failure mode this criterion exists to prevent.
        self.assertNotEqual(result, Decimal("0"))
        self.assertNotEqual(result, 0.0)

    def test_empty_string(self):
        self._assert_rejected("")

    def test_whitespace_only(self):
        self._assert_rejected("   ")

    def test_none_input(self):
        self._assert_rejected(None)

    def test_alphabetic_garbage(self):
        self._assert_rejected("abc")

    def test_two_decimal_points(self):
        self._assert_rejected("12.34.56")

    def test_symbol_with_no_digits(self):
        self._assert_rejected("£")

    def test_double_negative(self):
        self._assert_rejected("--5")

    def test_unparseable_never_degrades_to_zero(self):
        # The explicit anti-regression for accounting.py:1164, which returns
        # 0.0 on any parse failure. parse_amount must not copy that.
        self._assert_parser_is_live()
        for bad in ("abc", "", "   ", "12.34.56", "n/a", "TBC"):
            with self.subTest(bad=bad):
                self.assertIsNone(parse_amount(bad))


if __name__ == "__main__":
    unittest.main()
