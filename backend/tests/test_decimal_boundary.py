"""
D4 — the float boundary.

Money arriving over the JSON API must be converted with `Decimal(str(x))`,
never `Decimal(x)`.

    Decimal(0.1)   == 0.1000000000000000055511151231257827021181583404541015625
    Decimal("0.1") == 0.1

The damage is not theoretical and it is not confined to the far decimal places.
`Decimal(2.675)` quantises HALF_UP to **2.67**; `Decimal(str(2.675))` quantises
to **2.68**. The binary approximation is already on the wrong side of the
rounding boundary before any arithmetic happens, so every downstream guarantee
in D2 is void. A penny, on the line, from the first conversion.

Target surface:

    backend/services/money.py
        to_decimal(value) -> Decimal | None
            str / int / Decimal / float accepted; float goes via str().
            None and "" -> None. NaN and Infinity are refused.

`to_decimal` is the ONLY place a float is allowed to become a Decimal.
`calculate_totals` still refuses floats outright (see test_money_totals.py) —
the boundary converts, the calculator does not.
"""
import asyncio
import re
import unittest
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.sql.elements import TextClause

import quoting_api


def money():
    """Imported per-test so each test fails on its own, not at collection."""
    from services import money as _money
    return _money


def q2(value):
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class TestToDecimalUsesStrConversion(unittest.TestCase):
    """The criterion, stated as directly as it can be stated."""

    def test_point_one_is_exactly_point_one(self):
        self.assertEqual(money().to_decimal(0.1), Decimal("0.1"))

    def test_point_one_is_not_the_binary_expansion(self):
        # The explicit negative. Decimal(0.1) is a 55-digit number.
        self.assertNotEqual(money().to_decimal(0.1), Decimal(0.1))

    def test_2675_lands_on_the_right_side_of_the_rounding_boundary(self):
        # Decimal(2.675)      -> 2.674999999... -> quantises to 2.67
        # Decimal(str(2.675)) -> 2.675          -> quantises to 2.68
        self.assertEqual(q2(money().to_decimal(2.675)), Decimal("2.68"))

    def test_1005_lands_on_the_right_side_of_the_rounding_boundary(self):
        self.assertEqual(q2(money().to_decimal(1.005)), Decimal("1.01"))

    def test_repeated_addition_stays_exact(self):
        convert = money().to_decimal
        self.assertEqual(convert(0.1) + convert(0.2), Decimal("0.3"))

    def test_a_thousand_additions_do_not_drift(self):
        convert = money().to_decimal
        total = sum((convert(0.01) for _ in range(1000)), Decimal("0"))
        self.assertEqual(total, Decimal("10.00"))


class TestToDecimalAcceptedInputs(unittest.TestCase):
    """Every shape money arrives in over the wire."""

    def test_string(self):
        self.assertEqual(money().to_decimal("1234.56"), Decimal("1234.56"))

    def test_int(self):
        self.assertEqual(money().to_decimal(50), Decimal("50"))

    def test_decimal_passes_through_unchanged(self):
        original = Decimal("19.9900")
        self.assertEqual(money().to_decimal(original), original)

    def test_float_with_four_decimal_places(self):
        # 4dp unit prices arrive as JSON numbers too.
        self.assertEqual(money().to_decimal(3.3333), Decimal("3.3333"))

    def test_negative_float(self):
        self.assertEqual(money().to_decimal(-50.05), Decimal("-50.05"))

    def test_zero_is_returned_not_treated_as_absent(self):
        result = money().to_decimal(0)
        self.assertIsNotNone(result, "0 is a value, not a missing field")
        self.assertEqual(result, Decimal("0"))

    def test_always_returns_decimal_never_float(self):
        for value in (0.1, "0.1", 1, Decimal("0.1")):
            self.assertIsInstance(money().to_decimal(value), Decimal)
            self.assertNotIsInstance(money().to_decimal(value), float)


class TestToDecimalRejections(unittest.TestCase):
    """What must not silently become a number."""

    def _assert_live(self):
        # A None result only means "rejected" if the converter can return
        # something else.
        self.assertEqual(
            money().to_decimal("1.00"), Decimal("1.00"),
            "converter is not live — a None below would prove nothing",
        )

    def test_none_is_none(self):
        self._assert_live()
        self.assertIsNone(money().to_decimal(None))

    def test_empty_string_is_none(self):
        self._assert_live()
        self.assertIsNone(money().to_decimal(""))

    def test_nan_is_refused(self):
        # A NaN that reaches a money column poisons every aggregate that
        # touches it, silently and permanently.
        with self.assertRaises((ValueError, TypeError, ArithmeticError)):
            money().to_decimal(float("nan"))

    def test_infinity_is_refused(self):
        with self.assertRaises((ValueError, TypeError, ArithmeticError)):
            money().to_decimal(float("inf"))

    def test_unparseable_string_is_refused_or_none(self):
        self._assert_live()
        try:
            self.assertIsNone(money().to_decimal("abc"))
        except (ValueError, TypeError, ArithmeticError):
            pass          # raising is an acceptable contract; 0 is not
        else:
            self.assertNotEqual(money().to_decimal("abc"), Decimal("0"))


# ── The same criterion, through the real endpoint ────────────────────────────

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


class JsonPayloadSession:
    """Projects only the columns the SQL asked for; invents nothing."""

    SETTINGS = {
        "id": "qs-1", "business_id": "biz-1", "quote_prefix": "QTE-",
        "next_quote_number": 1, "default_terms": "Terms.", "default_valid_days": 30,
        "default_tax_rate": Decimal("0"), "include_tax": False,
        "default_markup": Decimal("0"), "company_name": "Test Co",
        "company_address": None, "company_phone": None, "company_email": None,
        "company_logo_url": None, "company_registration": None, "vat_number": None,
        "industry": "general", "labour_rates": [],
    }
    BUSINESS = {
        "id": "biz-1", "name": "Test Co", "region": "UK",
        "tax_registered": False, "tax_number": None, "currency": "GBP",
    }

    def __init__(self):
        self.statements = []

    def execute(self, statement, params=None):
        assert isinstance(statement, TextClause), f"expected TextClause, got {type(statement)}"
        sql = " ".join(statement.text.split())
        self.statements.append((sql, params))
        if not sql.upper().startswith("SELECT"):
            return FakeResult(None)
        source = self.BUSINESS if re.search(r"FROM\s+businesses", sql, re.I) else self.SETTINGS
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
        assert matches, (
            f"no statement matching {fragment!r}. Statements were:\n  "
            + "\n  ".join(sql for sql, _ in self.statements)
        )
        return matches[0]


def create_quote_from_json(session, line_items):
    """Line items exactly as json.loads would hand them over: bare floats."""
    return asyncio.run(quoting_api.create_quote(
        data={"customer_name": "A Customer", "job_title": "A Job",
              "line_items": line_items},
        auth_ctx={"business_id": "biz-1", "user_id": "user-1"},
        session=session,
    ))


class TestJsonFloatsAreConvertedAtTheBoundary(unittest.TestCase):
    """
    Criterion: money arriving over the JSON API is converted with
    Decimal(str(x)). FastAPI hands `data: dict` straight from json.loads, so
    every unit_cost in these payloads is a genuine Python float.
    """

    def test_a_2675_unit_cost_stores_268_not_267(self):
        session = JsonPayloadSession()
        create_quote_from_json(session, [
            {"description": "Work", "quantity": 1, "unit_cost": 2.675},
        ])
        subtotal = session.params_for("INSERT INTO quotes")["subtotal"]
        self.assertIsInstance(subtotal, Decimal, f"subtotal is {type(subtotal).__name__}")
        self.assertEqual(subtotal, Decimal("2.68"))

    def test_three_tenths_sum_exactly(self):
        session = JsonPayloadSession()
        create_quote_from_json(session, [
            {"description": f"Line {n}", "quantity": 1, "unit_cost": 0.1}
            for n in range(3)
        ])
        subtotal = session.params_for("INSERT INTO quotes")["subtotal"]
        self.assertIsInstance(subtotal, Decimal)
        self.assertEqual(subtotal, Decimal("0.30"))

    def test_a_four_dp_float_unit_cost_is_not_degraded(self):
        session = JsonPayloadSession()
        create_quote_from_json(session, [
            {"description": "Screed", "quantity": 47.5, "unit_cost": 3.3333},
        ])
        subtotal = session.params_for("INSERT INTO quotes")["subtotal"]
        self.assertIsInstance(subtotal, Decimal)
        self.assertEqual(subtotal, Decimal("158.33"))

    def test_a_float_quantity_is_converted_too(self):
        # quantity is numeric(12,3) — it goes through the same boundary.
        session = JsonPayloadSession()
        create_quote_from_json(session, [
            {"description": "Sand", "quantity": 2.5, "unit_cost": 1.005},
        ])
        subtotal = session.params_for("INSERT INTO quotes")["subtotal"]
        self.assertIsInstance(subtotal, Decimal)
        self.assertEqual(subtotal, Decimal("2.51"))


if __name__ == "__main__":
    unittest.main()
