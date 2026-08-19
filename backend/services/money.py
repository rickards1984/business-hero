"""
The money engine — spec decisions D2, D3, D4 and D5.

Three rules this module exists to enforce:

  * Decimal only. `calculate_totals` REFUSES floats rather than coercing them.
    A float reaching the money path is an upstream bug; failing loudly is the
    only way it gets found.
  * ROUND_HALF_UP, per line, then summed. Python's round() is banker's
    rounding and puts 0.125 at 0.12 — a penny short, in the customer's
    favour, on every affected line forever.
  * One discount order (D5), implemented once, here.

The float boundary lives in `to_decimal`, and only there.
"""
import math
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

TWO_DP = Decimal("0.01")
HUNDRED = Decimal("100")
ZERO = Decimal("0.00")


def q2(value):
    """Quantise to 2dp, ROUND_HALF_UP. The only rounding used for money."""
    return Decimal(value).quantize(TWO_DP, rounding=ROUND_HALF_UP)


def to_decimal(value):
    """Convert a value arriving over the JSON API into a Decimal.

    THE ONLY PLACE a float is allowed to become a Decimal, and it goes via
    str() to do it. `Decimal(0.1)` is 0.1000000000000000055511151231257827;
    `Decimal(str(0.1))` is 0.1. The binary approximation is already on the
    wrong side of the rounding boundary before any arithmetic happens —
    Decimal(2.675) quantises to 2.67 where Decimal("2.675") gives 2.68.

    Returns None for absent input. Refuses NaN and Infinity: a NaN in a money
    column poisons every aggregate that touches it, silently and forever.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        if value.is_nan() or value.is_infinite():
            raise ValueError(f"refusing non-finite money value: {value!r}")
        return value
    if isinstance(value, bool):
        raise TypeError(f"refusing bool as a money value: {value!r}")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise ValueError(f"refusing non-finite money value: {value!r}")
        return Decimal(str(value))          # <- the whole point of this function
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = Decimal(text)
        except InvalidOperation:
            return None
        if parsed.is_nan() or parsed.is_infinite():
            raise ValueError(f"refusing non-finite money value: {value!r}")
        return parsed
    return None


def _strict(value, label):
    """Accept Decimal and int. Reject float, loudly.

    The calculator does not convert — `to_decimal` does that at the boundary.
    By the time a value gets here it should already be exact.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise TypeError(f"{label} must be Decimal, got bool {value!r}")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        raise TypeError(
            f"{label} must be Decimal, got float {value!r}. Convert it at the "
            f"API boundary with money.to_decimal(), never Decimal(x)."
        )
    raise TypeError(f"{label} must be Decimal, got {type(value).__name__}")


def resolve_tax_rate(quote_tax_rate, default_tax_rate, tax_registered, fallback_rate):
    """Work out the rate that actually applies, without losing a stored zero.

    `rate or 20` turns a stored 0 into 20 in Python, and `rate || 20` does the
    same in JavaScript. A business that has told the product it charges no VAT
    would then charge 20% on every quote — which is illegal, and which the
    product would have done to them. Hence the explicit `is None` tests.
    """
    if not tax_registered:
        return Decimal("0")
    if quote_tax_rate is not None:
        return _strict(quote_tax_rate, "quote_tax_rate")
    if default_tax_rate is not None:
        return _strict(default_tax_rate, "default_tax_rate")
    return _strict(fallback_rate, "fallback_rate")


def _line_discount(line_total, item):
    """Step 2 of D5 — the line's own discount."""
    amount = _strict(item.get("discount_amount", ZERO), "line discount_amount")
    if item.get("discount_type", "fixed") == "percentage":
        return q2(line_total * amount / HUNDRED)
    return q2(amount)


def net_of_lines(line_items):
    """The base a quote-level discount applies to: line totals less line discounts.

    This is step 2 of D5 stopped halfway, and it is what the API validates a
    quote discount against.
    """
    total = Decimal("0")
    for item in line_items:
        quantity = _strict(item.get("quantity", Decimal("1")), "quantity")
        unit_cost = _strict(item.get("unit_cost", ZERO), "unit_cost")
        line_total = q2(quantity * unit_cost)
        total += line_total - _line_discount(line_total, item)
    return q2(total)


def quote_discount_for(net, discount_amount, discount_type="fixed"):
    """The quote-level discount as an absolute amount.

    A percentage is taken on the net AFTER line discounts, not on the gross
    subtotal (D5). Returns what was ASKED FOR — it does not cap or reject;
    that judgement belongs to the caller.
    """
    amount = _strict(discount_amount, "discount_amount")
    if discount_type == "percentage":
        return q2(_strict(net, "net") * amount / HUNDRED)
    return q2(amount)


def _apportion(target, nets, orders):
    """Step 3 of D5 — split the quote discount pro-rata by line net.

    Shares round HALF_UP, so they rarely sum to the target exactly. £10 over
    three equal lines gives 3.33 each and loses a penny. The remainder — of
    either sign — goes to the largest line by net, ties broken by lowest
    sort_order. Without this the invoice does not add up, and an invoice that
    does not add up is the one thing a customer always notices.
    """
    net_total = sum(nets, Decimal("0"))
    if target == 0 or net_total <= 0:
        return [ZERO for _ in nets]

    shares = [q2(target * net / net_total) for net in nets]
    remainder = target - sum(shares, Decimal("0"))
    if remainder != 0:
        biggest = min(range(len(nets)), key=lambda i: (-nets[i], orders[i]))
        shares[biggest] = q2(shares[biggest] + remainder)
    return shares


def calculate_totals(
    line_items,
    *,
    tax_rate,
    discount_amount=ZERO,
    discount_type="fixed",
    tax_registered=True,
):
    """Apply D5 in order and return the quote/invoice totals.

        line_total -> line discount -> quote discount apportioned pro-rata
        by line net -> per-line tax on the discounted net

    The invariant that makes this safe: the sum of the line taxables equals
    the quote taxable EXACTLY, on every quote, including discounts that do not
    divide evenly. There is one derivation of the quote taxable, not two that
    can drift apart.
    """
    rate = _strict(tax_rate, "tax_rate")
    if not tax_registered:
        rate = Decimal("0")

    lines = []
    for index, item in enumerate(line_items):
        quantity = _strict(item.get("quantity", Decimal("1")), "quantity")
        unit_cost = _strict(item.get("unit_cost", ZERO), "unit_cost")
        line_total = q2(quantity * unit_cost)
        discount = _line_discount(line_total, item)
        lines.append({
            "line_total": line_total,
            "line_discount": discount,
            "net": line_total - discount,
            "order": item.get("sort_order", index),
            "tax_treatment": item.get("tax_treatment", "standard"),
        })

    nets = [line["net"] for line in lines]
    orders = [line["order"] for line in lines]
    net_total = sum(nets, Decimal("0"))

    # A percentage quote discount is taken on the net AFTER line discounts,
    # not on the gross subtotal (D5). A quote whose lines are fully discounted
    # away has nothing left to take a quote discount from — the API rejects an
    # over-large discount before it reaches here, so this is the defensive
    # floor rather than the rule.
    target = ZERO if net_total <= 0 else quote_discount_for(
        net_total, discount_amount, discount_type
    )

    shares = _apportion(target, nets, orders)

    out_lines = []
    for line, share in zip(lines, shares):
        taxable = line["net"] - share
        out_lines.append({
            "line_total": line["line_total"],
            "line_discount": line["line_discount"],
            "apportioned_discount": share,
            "taxable": q2(taxable),
            "tax_rate": rate,
            # The label is stored and displayed and drives NO calculation.
            # Business Hero does not determine taxability; the rate the
            # business entered is the rate that is charged.
            "tax_treatment": line["tax_treatment"],
            "tax_amount": q2(taxable * rate / HUNDRED),
        })

    subtotal = q2(sum((ln["line_total"] for ln in out_lines), Decimal("0")))
    line_discount_total = q2(sum((ln["line_discount"] for ln in out_lines), Decimal("0")))
    discount_applied = q2(sum((ln["apportioned_discount"] for ln in out_lines), Decimal("0")))
    taxable_total = q2(sum((ln["taxable"] for ln in out_lines), Decimal("0")))
    tax_total = q2(sum((ln["tax_amount"] for ln in out_lines), Decimal("0")))

    return {
        "subtotal": subtotal,
        "line_discount_total": line_discount_total,
        "discount_applied": discount_applied,
        "taxable": taxable_total,
        "tax_amount": tax_total,
        "total": q2(taxable_total + tax_total),
        # A registered business on a 0% rate is NOT the same thing as an
        # unregistered one: it still shows a tax line, at zero. An
        # unregistered one must show none at all (D3).
        "tax_applicable": bool(tax_registered),
        "lines": out_lines,
    }


def invoice_line_summary(lines):
    """Totals for a set of stored invoice lines. Empty-safe.

    Three of the five invoices in prod are legacy CSV rows with no line items
    at all, and they must keep rendering everywhere they render today.
    """
    rows = list(lines or [])
    subtotal = q2(sum((_strict(r.get("line_total", ZERO), "line_total") for r in rows), Decimal("0")))
    tax_amount = q2(sum((_strict(r.get("tax_amount", ZERO), "tax_amount") for r in rows), Decimal("0")))
    return {"subtotal": subtotal, "tax_amount": tax_amount, "total": q2(subtotal + tax_amount)}
