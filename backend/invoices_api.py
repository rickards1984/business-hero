"""Manual invoice creation — BH-010 (RC1 P0-5).

An owner can invoice without a quote. Everything that makes an invoice
trustworthy is reused, not re-implemented:

  totals  services.money.calculate_totals — the engine quote conversion uses
  rate    quoting_api._quote_tax_context  — the business's own, never "20"
  number  services.invoice_numbering.allocate — atomic, never COUNT(*), never
          the client's (HMRC: unique and sequential)
  money   services.money.to_decimal — the only float -> Decimal boundary

Every check runs BEFORE a number is allocated: a refused invoice must not
leave a gap in a sequence that has to be sequential.

Tenant: the business comes only from the authenticated context; anything a
body says about `business_id` is ignored. Access: `get_user_business_context`
refuses mutations for read-only and suspended businesses (DECISION 3), and
`require_feature("invoicing")` refuses plans without invoicing.

SQL is portable (CURRENT_TIMESTAMP, not now()) so the tests can run the real
code against SQLite.
"""

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, List, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlmodel import Session

from auth import get_user_business_context, require_feature
from db import get_session
from quoting_api import _quote_tax_context
from services import region as region_module
from services.invoice_numbering import allocate
from services.money import calculate_totals, net_of_lines, q2, resolve_tax_rate, to_decimal

router = APIRouter(prefix="/v1/invoices", tags=["Invoices"])

DEFAULT_DUE_DAYS = 30


class InvoiceLineIn(BaseModel):
    description: str = ""
    quantity: Any = None
    unit: Optional[str] = None
    unit_cost: Any = None
    discount_amount: Any = None
    discount_type: Optional[str] = None


class InvoiceCreate(BaseModel):
    """Unknown fields (e.g. a `tax_rate` or `business_id`) are ignored — the
    rate and the business are never the client's to choose. `invoice_number`
    is declared only so that sending one can be refused explicitly."""
    customer_name: str = ""
    customer_email: Optional[str] = None
    customer_address: Optional[str] = None
    invoice_date: Optional[date] = None
    supply_date: Optional[date] = None
    due_date: Optional[date] = None
    lines: List[InvoiceLineIn] = []
    discount_amount: Any = None
    discount_type: Optional[str] = None
    invoice_number: Any = None


def _refuse(message: str):
    raise HTTPException(status_code=422, detail=message)


def _money(value, label, *, allow_negative=False):
    try:
        parsed = to_decimal(value)
    except (ValueError, TypeError):
        _refuse(f"{label} must be a number")
    if parsed is None:
        _refuse(f"{label} must be a number")
    if parsed < 0 and not allow_negative:
        _refuse(f"{label} cannot be negative")
    return parsed


def _fits(value: Decimal, places: int, label: str) -> Decimal:
    """Refuse a value finer than the column stores it. Calculating with
    0.0004 and storing 0.000 leaves a line whose stored figures no longer
    produce its stored total (Codex BH-010 review 1). Refusing is honest;
    rounding silently is not. Storage: quantity numeric(12,3), unit_cost
    numeric(14,4), discounts numeric(12,2)."""
    if value.as_tuple().exponent < -places:
        _refuse(f"{label} can have at most {places} decimal places")
    return value


def _clean_text(value: Optional[str]) -> Optional[str]:
    value = (value or "").strip()
    return value or None


def _business_profile(session: Session, business_id: str):
    row = session.execute(
        text("SELECT region, timezone FROM businesses WHERE id = :bid"),
        {"bid": business_id},
    ).fetchone()
    region = row[0] if row is not None else None
    tz_name = (row[1] if row is not None else None) or "Europe/London"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("Europe/London")
    return region, tz


@router.post("", status_code=201, dependencies=[Depends(require_feature("invoicing"))])
async def create_invoice(
    data: InvoiceCreate,
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    business_id = str(auth_ctx["business_id"])

    # ---- every check before a number is allocated -------------------------
    if data.invoice_number not in (None, ""):
        _refuse("Invoice numbers are issued automatically, in sequence; "
                "they cannot be chosen.")
    customer_name = _clean_text(data.customer_name)
    if not customer_name:
        _refuse("A customer name is required")
    if not data.lines:
        _refuse("An invoice needs at least one line")

    lines = []
    for index, line in enumerate(data.lines, start=1):
        description = _clean_text(line.description)
        if not description:
            _refuse(f"Line {index} needs a description")
        quantity = _fits(_money(line.quantity, f"Line {index} quantity"), 3,
                         f"Line {index} quantity")
        if quantity <= 0:
            _refuse(f"Line {index} quantity must be more than zero")
        unit_cost = _fits(_money(line.unit_cost, f"Line {index} price"), 4,
                          f"Line {index} price")
        discount = (_fits(_money(line.discount_amount, f"Line {index} discount"), 2,
                          f"Line {index} discount")
                    if line.discount_amount not in (None, "") else Decimal("0"))
        line_discount_type = line.discount_type or "fixed"
        if line_discount_type not in ("fixed", "percentage"):
            _refuse(f"Line {index} discount type must be 'fixed' or 'percentage'")
        # Each line on its own: another line's value must not be able to hide
        # a discount larger than this line, which would carry negative VAT.
        if line_discount_type == "percentage" and discount > Decimal("100"):
            _refuse(f"Line {index} discount cannot exceed 100%")
        if line_discount_type == "fixed" and discount > q2(quantity * unit_cost):
            _refuse(f"Line {index} discount is larger than the line")
        lines.append({
            "description": description,
            "quantity": quantity,
            "unit": _clean_text(line.unit) or "each",
            "unit_cost": unit_cost,
            "discount_amount": discount,
            "discount_type": line_discount_type,
            "tax_treatment": "standard",
            "category": "general",
            "group_name": None,
            "sort_order": index - 1,
        })

    discount_amount = (_fits(_money(data.discount_amount, "Discount"), 2, "Discount")
                       if data.discount_amount not in (None, "") else Decimal("0"))
    discount_type = data.discount_type or "fixed"
    if discount_type not in ("fixed", "percentage"):
        _refuse("Discount type must be 'fixed' or 'percentage'")

    region, tz = _business_profile(session, business_id)
    invoice_date = data.invoice_date or datetime.now(tz).date()
    due_date = data.due_date or (invoice_date + timedelta(days=DEFAULT_DUE_DAYS))
    if due_date < invoice_date:
        _refuse("The due date cannot be before the invoice date")

    default_rate, registered, fallback = _quote_tax_context(session, business_id)
    rate = resolve_tax_rate(None, default_rate, registered, fallback)

    net = net_of_lines(lines)
    if discount_type == "fixed" and discount_amount > net:
        _refuse("The discount is larger than the invoice")
    if discount_type == "percentage" and discount_amount > Decimal("100"):
        _refuse("A percentage discount cannot exceed 100%")

    totals = calculate_totals(
        lines, tax_rate=rate, discount_amount=discount_amount,
        discount_type=discount_type, tax_registered=registered,
    )
    if totals["total"] <= 0:
        _refuse("There is nothing to pay on this invoice")

    currency = region_module.resolve(region)["currency"]

    # ---- write: number, header, lines — one transaction --------------------
    invoice_id = str(uuid.uuid4())

    def _insert_invoice(inv_number: str) -> None:
        session.execute(
            text("""
                INSERT INTO invoices
                (id, business_id, invoice_number, customer_name, customer_email,
                 customer_address, invoice_date, supply_date, due_date,
                 subtotal, tax_amount, amount, amount_due, currency,
                 status, source, created_at)
                VALUES
                (:id, :bid, :inum, :cname, :cemail,
                 :caddress, :idate, :sdate, :due,
                 :subtotal, :tax_amount, :amount, :amount_due, :currency,
                 'unpaid', 'manual', CURRENT_TIMESTAMP)
            """),
            {
                "id": invoice_id, "bid": business_id, "inum": inv_number,
                "cname": customer_name, "cemail": _clean_text(data.customer_email),
                "caddress": _clean_text(data.customer_address),
                "idate": invoice_date.isoformat(),
                "sdate": data.supply_date.isoformat() if data.supply_date else None,
                "due": due_date.isoformat(),
                "subtotal": totals["subtotal"], "tax_amount": totals["tax_amount"],
                # `amount` is the GROSS total, as quote conversion writes it.
                "amount": totals["total"], "amount_due": totals["total"],
                "currency": currency,
            },
        )

    inv_number = allocate(session, business_id, _insert_invoice)

    for source, computed in zip(lines, totals["lines"]):
        session.execute(
            text("""
                INSERT INTO invoice_line_items
                (invoice_id, category, description, quantity, unit, unit_cost,
                 line_total, discount_amount, discount_type, apportioned_discount,
                 taxable, tax_rate, tax_amount, tax_treatment, sort_order, group_name)
                VALUES
                (:invoice_id, :category, :description, :quantity, :unit, :unit_cost,
                 :line_total, :discount_amount, :discount_type, :apportioned_discount,
                 :taxable, :tax_rate, :tax_amount, :tax_treatment, :sort_order, :group_name)
            """),
            {
                "invoice_id": invoice_id,
                "category": source["category"], "description": source["description"],
                "quantity": source["quantity"], "unit": source["unit"],
                "unit_cost": source["unit_cost"],
                "line_total": computed["line_total"],
                "discount_amount": source["discount_amount"],
                "discount_type": source["discount_type"],
                "apportioned_discount": computed["apportioned_discount"],
                "taxable": computed["taxable"], "tax_rate": computed["tax_rate"],
                "tax_amount": computed["tax_amount"],
                "tax_treatment": computed["tax_treatment"],
                "sort_order": source["sort_order"], "group_name": source["group_name"],
            },
        )

    session.commit()

    def m(value):
        return f"{q2(value):.2f}"

    return {
        "id": invoice_id,
        "invoice_number": inv_number,
        "customer_name": customer_name,
        "customer_email": _clean_text(data.customer_email),
        "customer_address": _clean_text(data.customer_address),
        "invoice_date": invoice_date.isoformat(),
        "supply_date": data.supply_date.isoformat() if data.supply_date else None,
        "due_date": due_date.isoformat(),
        "currency": currency,
        "status": "unpaid",
        "source": "manual",
        "subtotal": m(totals["subtotal"]),
        "tax_amount": m(totals["tax_amount"]),
        "amount": m(totals["total"]),
        "lines": [
            {"description": s["description"], "quantity": str(s["quantity"]),
             "unit": s["unit"], "unit_cost": str(s["unit_cost"]),
             "line_total": m(c["line_total"]), "tax_rate": str(c["tax_rate"]),
             "tax_amount": m(c["tax_amount"])}
            for s, c in zip(lines, totals["lines"])
        ],
    }
