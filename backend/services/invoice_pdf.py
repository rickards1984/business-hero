"""Render stored invoice records without recalculating their issued totals.

No network, persistence or ORM money conversions. The API supplies tenant-scoped
records; P0-5 can reuse this renderer after storing its canonical invoice values.
"""

from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    LongTable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from services.money import q2, to_decimal
from services.region import currency_symbol, resolve


def decimal_value(value):
    """Raw PostgreSQL NUMERIC is Decimal; never pass it through a float ORM."""
    if isinstance(value, float):
        raise ValueError("Invoice money must be read as Decimal, not float")
    return to_decimal(value)


def stored_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value:
        return date.fromisoformat(str(value)[:10])
    return None


def nonblank(value):
    return str(value).strip() if value is not None else ""


def prepare_invoice(invoice, line_items, business, settings):
    """Normalize presentation, validate RC1 decisions, report absent fields.

    Discounts are the difference between stored gross and stored taxable line
    values, which already include both discount stages. Percentage input fields
    are never mistaken for money. Header totals are never derived from lines.
    """
    invoice = dict(invoice)
    registered = bool(business.get("tax_registered"))
    currency = (
        nonblank(invoice.get("currency")).upper()
        or resolve(business.get("region"))["currency"]
    )
    invoice["currency"] = currency
    if registered and currency != "GBP":
        raise ValueError(
            "Cannot download this invoice in RC1: VAT on a foreign-currency invoice must also be shown in sterling."
        )
    for field in ("subtotal", "tax_amount", "amount", "discount_amount"):
        invoice[field] = decimal_value(invoice.get(field))
    if (
        not registered
        and invoice["tax_amount"] is not None
        and invoice["tax_amount"] != 0
    ):
        raise ValueError(
            "This invoice contains stored VAT but your business is not VAT-registered. Please check your VAT settings."
        )
    invoice["issue_date"] = stored_date(
        invoice.get("issue_date")
        or invoice.get("invoice_date")
        or invoice.get("created_at")
    )
    invoice["tax_point"] = stored_date(
        invoice.get("tax_point") or invoice.get("supply_date")
    )
    invoice["vat_number"] = nonblank(business.get("tax_number")) or nonblank(
        settings.get("vat_number")
    )
    invoice["supplier_name"] = nonblank(settings.get("company_name")) or nonblank(
        business.get("name")
    )
    if invoice["discount_amount"] is None and line_items:
        differences = []
        for line in line_items:
            gross = decimal_value(line.get("line_total"))
            taxable = decimal_value(line.get("taxable"))
            if gross is None or taxable is None:
                break
            differences.append(gross - taxable)
        if len(differences) == len(line_items):
            invoice["discount_amount"] = sum(differences, Decimal("0"))

    missing = []
    invoice["total_excluding_vat"] = invoice["subtotal"]
    if registered and invoice["discount_amount"]:
        # Presentation only: validate the discounted header net against stored
        # taxable lines. Never overwrite issued subtotal, VAT or payable totals.
        invoice["total_excluding_vat"] = None
        taxable_values = [decimal_value(line.get("taxable")) for line in line_items]
        if invoice["subtotal"] is not None and taxable_values and all(
            value is not None for value in taxable_values
        ):
            net = invoice["subtotal"] - invoice["discount_amount"]
            if net == sum(taxable_values, Decimal("0")):
                invoice["total_excluding_vat"] = net
        if invoice["total_excluding_vat"] is None:
            missing.append("total_excluding_vat")
    for field, value in (
        ("supplier_name", invoice["supplier_name"]),
        ("supplier_address", settings.get("company_address")),
        ("invoice_number", invoice.get("invoice_number")),
        ("invoice_date", invoice["issue_date"]),
        ("customer_name", invoice.get("customer_name")),
    ):
        if not nonblank(value):
            missing.append(field)
    if registered and not invoice["vat_number"]:
        missing.append("vat_number")
    # Nonregistered invoices cannot use the less-detailed VAT invoice exception.
    if (
        not registered
        or invoice["amount"] is None
        or invoice["amount"] > Decimal("250")
    ) and not nonblank(invoice.get("customer_address")):
        missing.append("customer_address")
    for field in ("subtotal", "tax_amount", "amount"):
        if invoice[field] is None:
            missing.append(field)
    return invoice, missing


async def generate_invoice_pdf(invoice, line_items, business, settings) -> bytes:
    invoice, _ = prepare_invoice(invoice, line_items, business, settings)
    registered = bool(business.get("tax_registered"))
    symbol = currency_symbol(invoice["currency"])

    def money(value):
        value = decimal_value(value)
        return "" if value is None else f"{symbol}{q2(value):,.2f}"

    def number(value):
        value = decimal_value(value)
        if value is None:
            return ""
        formatted = format(value, "f")
        return formatted.rstrip("0").rstrip(".") if "." in formatted else formatted

    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(name="InvoiceCell", fontName="Helvetica", fontSize=9, leading=12)
    )

    def paragraph(value, style="Normal"):
        return Paragraph(escape(str(value or "")).replace("\n", "<br/>"), styles[style])

    source = nonblank(invoice.get("source")).lower()
    external_source = nonblank(invoice.get("external_source")).lower()
    systems = {"xero": "Xero", "quickbooks": "QuickBooks", "freeagent": "FreeAgent"}
    imported = source in {*systems, "csv"} or bool(
        external_source or nonblank(invoice.get("external_id"))
    )
    origin = external_source or source
    title = (
        "Invoice copy"
        if imported
        else "VAT invoice"
        if registered
        else "Invoice"
    )
    story = [
        paragraph(title, "Title"),
        paragraph(invoice.get("invoice_number"), "Heading2"),
    ]
    if imported:
        if origin == "csv":
            label = "Imported from CSV"
        elif origin in systems:
            label = f"Originally issued from {systems[origin]}"
        else:
            label = "Originally issued externally"
        story.append(paragraph(label))
    story.extend(
        [
            paragraph(invoice["supplier_name"], "Heading2"),
            paragraph(settings.get("company_address")),
        ]
    )
    for field in ("company_email", "company_phone"):
        if settings.get(field):
            story.append(paragraph(settings[field]))
    if registered and invoice["vat_number"]:
        story.append(paragraph(f"VAT number: {invoice['vat_number']}"))
    story.extend(
        [
            Spacer(1, 12),
            paragraph("Bill to", "Heading3"),
            paragraph(invoice.get("customer_name")),
            paragraph(invoice.get("customer_address")),
            Spacer(1, 12),
        ]
    )
    if invoice["issue_date"]:
        story.append(paragraph(f"Invoice date: {invoice['issue_date']:%d/%m/%Y}"))
    if invoice["tax_point"] and invoice["tax_point"] != invoice["issue_date"]:
        story.append(paragraph(f"Tax point: {invoice['tax_point']:%d/%m/%Y}"))
    story.append(Spacer(1, 16))
    if line_items:
        headings = [
            "Description",
            "Quantity",
            "Unit price excluding VAT" if registered else "Unit price",
        ]
        if registered:
            headings.append("VAT rate")
        headings.append("Line amount")
        rows = [[paragraph(label, "InvoiceCell") for label in headings]]
        for line in line_items:
            description = str(line.get("description") or "")
            treatment = line.get("tax_treatment")
            if registered and treatment and treatment != "standard":
                description += f"\n{str(treatment).replace('_', ' ')}"
            cells = [
                description,
                number(line.get("quantity")),
                money(line.get("unit_cost")),
            ]
            if registered:
                rate = number(line.get("tax_rate"))
                cells.append(f"{rate}%" if rate else "")
            cells.append(money(line.get("line_total")))
            rows.append([paragraph(cell, "InvoiceCell") for cell in cells])
        widths = [211, 52, 100, 65, 95] if registered else [256, 62, 105, 100]
        table = LongTable(rows, colWidths=widths, repeatRows=1, splitInRow=1)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#edf1f5")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
                    ("TOPPADDING", (0, 0), (-1, -1), 9),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.grey),
                ]
            )
        )
        story.append(table)
    else:
        story.append(paragraph("No itemised lines"))
    story.append(Spacer(1, 18))
    has_discount = bool(invoice["discount_amount"])
    totals = [
        ("Total excluding VAT" if registered and not has_discount else "Subtotal", invoice["subtotal"])
    ]
    if has_discount:
        totals.append(("Discount", invoice["discount_amount"]))
        if registered:
            totals.append(("Total excluding VAT", invoice["total_excluding_vat"]))
    if registered:
        totals.append(("Total VAT", invoice["tax_amount"]))
    totals.append(("Total payable", invoice["amount"]))
    # Unknown totals are omitted, never silently replaced with zero or inferred.
    table = Table(
        [
            [paragraph(label), paragraph(money(value))]
            for label, value in totals
            if value is not None
        ],
        colWidths=[170, 110],
        hAlign="RIGHT",
    )
    table.setStyle(
        TableStyle(
            [
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(table)
    output = BytesIO()
    pdf = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=42,
        title=f"{title} {invoice.get('invoice_number', '')}",
    )

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(A4[0] - 36, 24, f"Page {doc.page}")
        canvas.restoreState()

    pdf.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
