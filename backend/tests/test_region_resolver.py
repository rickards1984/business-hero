"""
ITEM 5 — the region resolver (the seam, not the rollout).

Target surface (does not exist yet):

    backend/services/region.py
        UK = "UK"; US = "US"
        DEFAULT_REGION = "UK"
        TERMS   -> ONE dict of UK term -> US term
        resolve(region) -> dict with:
            region, currency, locale, date_format, tax_label,
            default_tax_rate (Decimal), quote_noun
        term(word, region) -> str

Scope note: this file covers the resolver and the terminology map only. Wiring
the PDFs and the 108 hardcoded frontend "£" to it is the rest of Item 5 and is
not tested here.

Why "Estimate" gets its own tests: in US trades a Quote is an Estimate. The
spec calls this out as the thing that "marks the product as foreign on first
screen". It is a one-line map entry and a lost customer if it is missing.
"""
import unittest
from decimal import Decimal


def region():
    """Imported per-test so each test fails on its own, not at collection."""
    from services import region as _region
    return _region


UK_EXPECTED = {
    "currency": "GBP",
    "locale": "en-GB",
    "date_format": "DD/MM/YYYY",
    "tax_label": "VAT",
    "default_tax_rate": Decimal("20"),
    "quote_noun": "Quote",
}

US_EXPECTED = {
    "currency": "USD",
    "locale": "en-US",
    "date_format": "MM/DD/YYYY",
    "tax_label": "Sales Tax",
    "default_tax_rate": Decimal("0"),
    "quote_noun": "Estimate",
}


class TestUKProfile(unittest.TestCase):
    """Criterion: derived defaults per region, in ONE place."""

    def test_every_uk_default(self):
        profile = region().resolve("UK")
        for key, expected in UK_EXPECTED.items():
            with self.subTest(key=key):
                self.assertEqual(profile[key], expected)

    def test_uk_default_rate_is_decimal_not_float(self):
        rate = region().resolve("UK")["default_tax_rate"]
        self.assertIsInstance(rate, Decimal)
        self.assertNotIsInstance(rate, float)


class TestUSProfile(unittest.TestCase):
    def test_every_us_default(self):
        profile = region().resolve("US")
        for key, expected in US_EXPECTED.items():
            with self.subTest(key=key):
                self.assertEqual(profile[key], expected)

    def test_us_default_rate_is_zero_and_stays_zero(self):
        # US sales tax is entered manually per job. The default is 0, and 0 is
        # a real answer here — the same `or` trap as Item 3, in a new place.
        rate = region().resolve("US")["default_tax_rate"]
        self.assertEqual(rate, Decimal("0"))
        self.assertIsInstance(rate, Decimal)

    def test_us_calls_a_quote_an_estimate(self):
        self.assertEqual(region().resolve("US")["quote_noun"], "Estimate")

    def test_us_calls_vat_sales_tax(self):
        self.assertEqual(region().resolve("US")["tax_label"], "Sales Tax")


class TestDefaulting(unittest.TestCase):
    """
    Criterion: existing businesses default to UK — no behaviour change for MSC
    or New Body, neither of which has a region set.
    """

    def test_none_defaults_to_uk(self):
        self.assertEqual(region().resolve(None)["region"], "UK")

    def test_empty_string_defaults_to_uk(self):
        self.assertEqual(region().resolve("")["region"], "UK")

    def test_unknown_region_defaults_to_uk_without_raising(self):
        self.assertEqual(region().resolve("FR")["region"], "UK")

    def test_defaulted_profile_is_a_full_uk_profile(self):
        # Defaulting must yield the whole UK profile, not a half-populated one
        # that quietly drops the currency.
        profile = region().resolve(None)
        for key, expected in UK_EXPECTED.items():
            with self.subTest(key=key):
                self.assertEqual(profile[key], expected)

    def test_lowercase_is_accepted(self):
        self.assertEqual(region().resolve("us")["region"], "US")
        self.assertEqual(region().resolve("uk")["region"], "UK")

    def test_surrounding_whitespace_is_tolerated(self):
        self.assertEqual(region().resolve(" US ")["region"], "US")


class TestProfileShape(unittest.TestCase):
    """Criterion: ONE place. Both regions expose exactly the same keys."""

    REQUIRED = {"region", "currency", "locale", "date_format", "tax_label",
                "default_tax_rate", "quote_noun"}

    def test_uk_profile_has_every_key(self):
        self.assertTrue(self.REQUIRED.issubset(region().resolve("UK").keys()))

    def test_us_profile_has_every_key(self):
        self.assertTrue(self.REQUIRED.issubset(region().resolve("US").keys()))

    def test_both_regions_expose_identical_keys(self):
        self.assertEqual(
            set(region().resolve("UK").keys()),
            set(region().resolve("US").keys()),
            "the two profiles have drifted — a caller reading a key that only "
            "one region defines is a KeyError waiting for a US signup",
        )

    def test_mutating_a_returned_profile_does_not_poison_the_next_caller(self):
        first = region().resolve("UK")
        first["currency"] = "XXX"
        self.assertEqual(region().resolve("UK")["currency"], "GBP")


class TestTerminology(unittest.TestCase):
    """
    Criterion: a terminology module — ONE map, no scattered ternaries.
    All ten pairs from the spec.
    """

    PAIRS = [
        ("Quote", "Estimate"),
        ("VAT", "Sales Tax"),
        ("VAT Number", "Tax ID"),
        ("Labour", "Labor"),
        ("Postcode", "ZIP Code"),
        ("Organisation", "Organization"),
        ("Cheque", "Check"),
        ("Turnover", "Revenue"),
        ("inc. VAT", "incl. tax"),
        ("Sole trader", "Sole proprietor"),
    ]

    def test_every_term_translates_for_us(self):
        translate = region().term
        for uk_term, us_term in self.PAIRS:
            with self.subTest(term=uk_term):
                self.assertEqual(translate(uk_term, "US"), us_term)

    def test_every_term_is_unchanged_for_uk(self):
        translate = region().term
        for uk_term, _ in self.PAIRS:
            with self.subTest(term=uk_term):
                self.assertEqual(translate(uk_term, "UK"), uk_term)

    def test_the_map_is_a_single_dict_covering_every_pair(self):
        terms = region().TERMS
        self.assertIsInstance(terms, dict)
        for uk_term, us_term in self.PAIRS:
            with self.subTest(term=uk_term):
                self.assertEqual(terms.get(uk_term), us_term)

    def test_an_unmapped_word_passes_through_unchanged(self):
        self.assertEqual(region().term("Scaffolding", "US"), "Scaffolding")

    def test_unknown_region_falls_back_to_uk_wording(self):
        self.assertEqual(region().term("Quote", "FR"), "Quote")


if __name__ == "__main__":
    unittest.main()
