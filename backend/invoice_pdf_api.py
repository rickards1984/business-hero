"""Read-only, tenant-scoped invoice PDF downloads (BH-009)."""

import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import text
from sqlmodel import Session

from auth import get_user_business_context, require_feature
from db import get_session
from services.invoice_pdf import generate_invoice_pdf, prepare_invoice

router = APIRouter(prefix="/v1/invoices", tags=["invoice-pdf"])


@router.get("/{invoice_id}/pdf", dependencies=[Depends(require_feature("invoicing"))])
async def download_invoice_pdf(
    invoice_id: UUID,
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    params = {
        "invoice_id": str(invoice_id),
        "business_id": str(auth_ctx["business_id"]),
    }
    row = (
        session.execute(
            text(
                "SELECT * FROM invoices WHERE id=:invoice_id AND business_id=:business_id"
            ),
            params,
        )
        .mappings()
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    invoice = dict(row)
    # Ownership is established before reading children; no ORM float conversion.
    lines = [
        dict(row)
        for row in session.execute(
            text(
                "SELECT * FROM invoice_line_items WHERE invoice_id=:invoice_id ORDER BY sort_order, id"
            ),
            params,
        ).mappings()
    ]
    business = dict(
        session.execute(
            text(
                "SELECT name, region, tax_registered, tax_number FROM businesses WHERE id=:business_id"
            ),
            params,
        )
        .mappings()
        .one()
    )
    settings = dict(
        session.execute(
            text("SELECT * FROM quote_settings WHERE business_id=:business_id"), params
        )
        .mappings()
        .first()
        or {}
    )
    addresses = (
        session.execute(
            text(
                "SELECT customer_address FROM quotes WHERE invoice_id=:invoice_id AND business_id=:business_id"
            ),
            params,
        )
        .scalars()
        .all()
    )
    # The invoice's own address (migration 034, BH-010) is a snapshot taken
    # when it was issued, and wins: editing the quote later must not change an
    # issued invoice. The linked quote is only the fallback for invoices issued
    # before the snapshot existed. No source_ref/name guess, and no arbitrary
    # choice if quote links are ambiguous.
    own = (invoice.get("customer_address") or "").strip()
    if not own:
        invoice["customer_address"] = addresses[0] if len(addresses) == 1 else None
    try:
        invoice, missing = prepare_invoice(invoice, lines, business, settings)
        payload = await generate_invoice_pdf(invoice, lines, business, settings)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    filename = re.sub(
        r"[^A-Za-z0-9_.-]", "_", str(invoice.get("invoice_number") or invoice_id)
    )[:100]
    headers = {
        "Content-Disposition": f'attachment; filename="invoice-{filename}.pdf"',
        "Cache-Control": "no-store",
    }
    if missing:
        headers["X-Invoice-Missing-Fields"] = ",".join(missing)
    return Response(payload, media_type="application/pdf", headers=headers)
