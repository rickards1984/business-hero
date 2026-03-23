"""
Quoting System API — CRUD for quotes, line items, and settings.
"""
import json
import logging
from datetime import date, datetime, timedelta
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlmodel import Session

from db import get_session
from auth import get_user_business_context

logger = logging.getLogger("quoting_api")
router = APIRouter(prefix="/v1/quotes", tags=["Quotes"])


# ── Helpers ──────────────────────────────────────────────

def _get_next_quote_number(session: Session, business_id: str) -> str:
    """Get and increment the next quote number."""
    row = session.execute(
        text("SELECT quote_prefix, next_quote_number FROM quote_settings WHERE business_id = :bid"),
        {"bid": business_id},
    ).fetchone()

    if row:
        prefix = row[0] or "QTE-"
        num = row[1] or 1
        session.execute(
            text("UPDATE quote_settings SET next_quote_number = :next WHERE business_id = :bid"),
            {"bid": business_id, "next": num + 1},
        )
    else:
        prefix = "QTE-"
        num = 1
        session.execute(
            text("""
                INSERT INTO quote_settings (business_id, next_quote_number)
                VALUES (:bid, 2)
            """),
            {"bid": business_id},
        )

    return f"{prefix}{num:04d}"


def _calculate_totals(line_items: list, tax_rate: float = 20.0, discount_amount: float = 0, discount_type: str = "fixed") -> dict:
    """Calculate subtotal, tax, and total from line items."""
    subtotal = sum(
        float(item.get("quantity", 1)) * float(item.get("unit_cost", 0))
        for item in line_items
    )

    if discount_type == "percentage" and discount_amount > 0:
        actual_discount = subtotal * (discount_amount / 100)
    else:
        actual_discount = float(discount_amount)

    taxable = subtotal - actual_discount
    tax_amount = taxable * (tax_rate / 100) if tax_rate > 0 else 0
    total = taxable + tax_amount

    return {
        "subtotal": round(subtotal, 2),
        "tax_amount": round(tax_amount, 2),
        "total": round(total, 2),
        "discount_applied": round(actual_discount, 2),
    }


def _row_to_quote(row) -> dict:
    """Convert a database row to a quote dict."""
    return {
        "id": str(row.id),
        "business_id": str(row.business_id),
        "quote_number": row.quote_number,
        "reference": row.reference,
        "customer_name": row.customer_name,
        "customer_email": row.customer_email,
        "customer_phone": row.customer_phone,
        "customer_address": row.customer_address,
        "job_title": row.job_title,
        "job_description": row.job_description,
        "job_location": row.job_location,
        "subtotal": float(row.subtotal) if row.subtotal else 0,
        "tax_rate": float(row.tax_rate) if row.tax_rate else 20,
        "tax_amount": float(row.tax_amount) if row.tax_amount else 0,
        "discount_amount": float(row.discount_amount) if row.discount_amount else 0,
        "discount_type": row.discount_type or "fixed",
        "total": float(row.total) if row.total else 0,
        "currency": row.currency or "GBP",
        "markup_percentage": float(row.markup_percentage) if row.markup_percentage else 0,
        "profit_margin": float(row.profit_margin) if row.profit_margin else 0,
        "status": row.status,
        "issue_date": row.issue_date.isoformat() if row.issue_date else None,
        "valid_until": row.valid_until.isoformat() if row.valid_until else None,
        "accepted_at": row.accepted_at.isoformat() if row.accepted_at else None,
        "declined_at": row.declined_at.isoformat() if row.declined_at else None,
        "terms": row.terms,
        "notes": row.notes,
        "customer_notes": row.customer_notes,
        "ai_generated": row.ai_generated,
        "ai_prompt": row.ai_prompt,
        "invoice_id": str(row.invoice_id) if row.invoice_id else None,
        "pdf_url": row.pdf_url,
        "sent_at": row.sent_at.isoformat() if row.sent_at else None,
        "sent_via": row.sent_via,
        "viewed_at": row.viewed_at.isoformat() if row.viewed_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "project_reference": getattr(row, "project_reference", None),
    }


# ── Quote CRUD ───────────────────────────────────────────

@router.get("")
async def list_quotes(
    status: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """List quotes with optional filters."""
    business_id = str(auth_ctx["business_id"])

    query = "SELECT * FROM quotes WHERE business_id = :bid"
    params: dict = {"bid": business_id}

    if status:
        query += " AND status = :status"
        params["status"] = status

    if search:
        query += " AND (customer_name ILIKE :search OR job_title ILIKE :search OR quote_number ILIKE :search)"
        params["search"] = f"%{search}%"

    query += " ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
    params["limit"] = limit
    params["offset"] = offset

    rows = session.execute(text(query), params).fetchall()

    counts = session.execute(
        text("""
            SELECT status, COUNT(*) as count
            FROM quotes WHERE business_id = :bid
            GROUP BY status
        """),
        {"bid": business_id},
    ).fetchall()

    status_counts = {r[0]: r[1] for r in counts}

    return {
        "quotes": [_row_to_quote(r) for r in rows],
        "total": sum(status_counts.values()),
        "status_counts": status_counts,
    }


@router.get("/{quote_id}")
async def get_quote(
    quote_id: str,
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """Get a single quote with its line items."""
    business_id = str(auth_ctx["business_id"])

    row = session.execute(
        text("SELECT * FROM quotes WHERE id = :qid AND business_id = :bid"),
        {"qid": quote_id, "bid": business_id},
    ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Quote not found")

    items = session.execute(
        text("SELECT * FROM quote_line_items WHERE quote_id = :qid ORDER BY sort_order, created_at"),
        {"qid": quote_id},
    ).fetchall()

    quote = _row_to_quote(row)
    quote["line_items"] = [
        {
            "id": str(item.id),
            "category": item.category,
            "description": item.description,
            "quantity": float(item.quantity),
            "unit": item.unit,
            "unit_cost": float(item.unit_cost),
            "line_total": float(item.line_total),
            "markup_percentage": float(item.markup_percentage) if item.markup_percentage else 0,
            "markup_amount": float(item.markup_amount) if item.markup_amount else 0,
            "sort_order": item.sort_order,
            "group_name": item.group_name,
        }
        for item in items
    ]

    return quote


@router.post("")
async def create_quote(
    data: dict,
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """Create a new quote with line items."""
    business_id = str(auth_ctx["business_id"])
    user_id = str(auth_ctx["user_id"])

    quote_number = _get_next_quote_number(session, business_id)
    line_items = data.get("line_items", [])

    totals = _calculate_totals(
        line_items,
        tax_rate=float(data.get("tax_rate", 20)),
        discount_amount=float(data.get("discount_amount", 0)),
        discount_type=data.get("discount_type", "fixed"),
    )

    valid_days = data.get("valid_days", 30)
    issue_date = date.today()
    valid_until = issue_date + timedelta(days=valid_days)

    terms = data.get("terms")
    if not terms:
        settings_row = session.execute(
            text("SELECT default_terms FROM quote_settings WHERE business_id = :bid"),
            {"bid": business_id},
        ).fetchone()
        terms = settings_row[0] if settings_row else "This quote is valid for 30 days."

    quote_id = str(uuid4())

    session.execute(
        text("""
            INSERT INTO quotes
            (id, business_id, quote_number, reference, customer_name, customer_email,
             customer_phone, customer_address, job_title, job_description, job_location,
             subtotal, tax_rate, tax_amount, discount_amount, discount_type, total,
             currency, markup_percentage, status, issue_date, valid_until, terms,
             notes, customer_notes, ai_generated, ai_prompt, ai_model, created_by,
             project_reference)
            VALUES
            (:id, :bid, :qnum, :ref, :cname, :cemail, :cphone, :caddr,
             :jtitle, :jdesc, :jloc, :subtotal, :tax_rate, :tax_amount,
             :discount_amount, :discount_type, :total, :currency, :markup,
             'draft', :issue_date, :valid_until, :terms, :notes, :cnotes,
             :ai_gen, :ai_prompt, :ai_model, :created_by, :project_ref)
        """),
        {
            "id": quote_id,
            "bid": business_id,
            "qnum": quote_number,
            "ref": data.get("reference"),
            "cname": data.get("customer_name", ""),
            "cemail": data.get("customer_email"),
            "cphone": data.get("customer_phone"),
            "caddr": data.get("customer_address"),
            "jtitle": data.get("job_title", ""),
            "jdesc": data.get("job_description"),
            "jloc": data.get("job_location"),
            "subtotal": totals["subtotal"],
            "tax_rate": float(data.get("tax_rate", 20)),
            "tax_amount": totals["tax_amount"],
            "discount_amount": float(data.get("discount_amount", 0)),
            "discount_type": data.get("discount_type", "fixed"),
            "total": totals["total"],
            "currency": data.get("currency", "GBP"),
            "markup": float(data.get("markup_percentage", 0)),
            "issue_date": issue_date.isoformat(),
            "valid_until": valid_until.isoformat(),
            "terms": terms,
            "notes": data.get("notes"),
            "cnotes": data.get("customer_notes"),
            "ai_gen": data.get("ai_generated", False),
            "ai_prompt": data.get("ai_prompt"),
            "ai_model": data.get("ai_model"),
            "project_ref": data.get("project_reference"),
            "created_by": user_id,
        },
    )

    for i, item in enumerate(line_items):
        qty = float(item.get("quantity", 1))
        unit_cost = float(item.get("unit_cost", 0))
        markup_pct = float(item.get("markup_percentage", 0))
        line_total = qty * unit_cost
        markup_amt = line_total * (markup_pct / 100) if markup_pct > 0 else 0

        session.execute(
            text("""
                INSERT INTO quote_line_items
                (quote_id, category, description, quantity, unit, unit_cost,
                 line_total, markup_percentage, markup_amount, sort_order, group_name)
                VALUES
                (:qid, :cat, :desc, :qty, :unit, :ucost, :ltotal,
                 :markup_pct, :markup_amt, :sort, :group_name)
            """),
            {
                "qid": quote_id,
                "cat": item.get("category", "general"),
                "desc": item.get("description", ""),
                "qty": qty,
                "unit": item.get("unit", "each"),
                "ucost": unit_cost,
                "ltotal": round(line_total, 2),
                "markup_pct": markup_pct,
                "markup_amt": round(markup_amt, 2),
                "sort": i,
                "group_name": item.get("group_name"),
            },
        )

    session.commit()

    return {"id": quote_id, "quote_number": quote_number, "status": "draft", "total": totals["total"]}


@router.put("/{quote_id}")
async def update_quote(
    quote_id: str,
    data: dict,
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """Update a quote and its line items."""
    business_id = str(auth_ctx["business_id"])

    existing = session.execute(
        text("SELECT id, status FROM quotes WHERE id = :qid AND business_id = :bid"),
        {"qid": quote_id, "bid": business_id},
    ).fetchone()

    if not existing:
        raise HTTPException(status_code=404, detail="Quote not found")

    line_items = data.get("line_items", [])
    totals = _calculate_totals(
        line_items,
        tax_rate=float(data.get("tax_rate", 20)),
        discount_amount=float(data.get("discount_amount", 0)),
        discount_type=data.get("discount_type", "fixed"),
    )

    session.execute(
        text("""
            UPDATE quotes SET
                reference = :ref, customer_name = :cname, customer_email = :cemail,
                customer_phone = :cphone, customer_address = :caddr,
                job_title = :jtitle, job_description = :jdesc, job_location = :jloc,
                subtotal = :subtotal, tax_rate = :tax_rate, tax_amount = :tax_amount,
                discount_amount = :discount_amount, discount_type = :discount_type,
                total = :total, markup_percentage = :markup,
                terms = :terms, notes = :notes, customer_notes = :cnotes,
                valid_until = :valid_until, project_reference = :project_ref,
                updated_at = now()
            WHERE id = :qid AND business_id = :bid
        """),
        {
            "qid": quote_id, "bid": business_id,
            "ref": data.get("reference"),
            "cname": data.get("customer_name", ""),
            "cemail": data.get("customer_email"),
            "cphone": data.get("customer_phone"),
            "caddr": data.get("customer_address"),
            "jtitle": data.get("job_title", ""),
            "jdesc": data.get("job_description"),
            "jloc": data.get("job_location"),
            "subtotal": totals["subtotal"],
            "tax_rate": float(data.get("tax_rate", 20)),
            "tax_amount": totals["tax_amount"],
            "discount_amount": float(data.get("discount_amount", 0)),
            "discount_type": data.get("discount_type", "fixed"),
            "total": totals["total"],
            "markup": float(data.get("markup_percentage", 0)),
            "terms": data.get("terms"),
            "notes": data.get("notes"),
            "cnotes": data.get("customer_notes"),
            "valid_until": data.get("valid_until"),
            "project_ref": data.get("project_reference"),
        },
    )

    session.execute(
        text("DELETE FROM quote_line_items WHERE quote_id = :qid"),
        {"qid": quote_id},
    )

    for i, item in enumerate(line_items):
        qty = float(item.get("quantity", 1))
        unit_cost = float(item.get("unit_cost", 0))
        markup_pct = float(item.get("markup_percentage", 0))
        line_total = qty * unit_cost
        markup_amt = line_total * (markup_pct / 100) if markup_pct > 0 else 0

        session.execute(
            text("""
                INSERT INTO quote_line_items
                (quote_id, category, description, quantity, unit, unit_cost,
                 line_total, markup_percentage, markup_amount, sort_order, group_name)
                VALUES (:qid, :cat, :desc, :qty, :unit, :ucost, :ltotal,
                        :markup_pct, :markup_amt, :sort, :group_name)
            """),
            {
                "qid": quote_id,
                "cat": item.get("category", "general"),
                "desc": item.get("description", ""),
                "qty": qty,
                "unit": item.get("unit", "each"),
                "ucost": unit_cost,
                "ltotal": round(line_total, 2),
                "markup_pct": markup_pct,
                "markup_amt": round(markup_amt, 2),
                "sort": i,
                "group_name": item.get("group_name"),
            },
        )

    session.commit()
    return {"status": "updated", "total": totals["total"]}


@router.delete("/{quote_id}")
async def delete_quote(
    quote_id: str,
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """Delete a quote and its line items."""
    business_id = str(auth_ctx["business_id"])
    session.execute(
        text("DELETE FROM quotes WHERE id = :qid AND business_id = :bid"),
        {"qid": quote_id, "bid": business_id},
    )
    session.commit()
    return {"status": "deleted"}


# ── Status Actions ───────────────────────────────────────

@router.post("/{quote_id}/send")
async def send_quote(
    quote_id: str,
    data: dict,
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """Mark quote as sent. Actual sending (email/WhatsApp) handled separately."""
    business_id = str(auth_ctx["business_id"])
    via = data.get("via", "email")

    session.execute(
        text("""
            UPDATE quotes SET status = 'sent', sent_at = now(), sent_via = :via,
            issue_date = COALESCE(issue_date, CURRENT_DATE), updated_at = now()
            WHERE id = :qid AND business_id = :bid
        """),
        {"qid": quote_id, "bid": business_id, "via": via},
    )
    session.commit()
    return {"status": "sent"}


@router.post("/{quote_id}/accept")
async def accept_quote(
    quote_id: str,
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """Mark quote as accepted."""
    business_id = str(auth_ctx["business_id"])
    session.execute(
        text("UPDATE quotes SET status = 'accepted', accepted_at = now(), updated_at = now() WHERE id = :qid AND business_id = :bid"),
        {"qid": quote_id, "bid": business_id},
    )
    session.commit()
    return {"status": "accepted"}


@router.post("/{quote_id}/decline")
async def decline_quote(
    quote_id: str,
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """Mark quote as declined."""
    business_id = str(auth_ctx["business_id"])
    session.execute(
        text("UPDATE quotes SET status = 'declined', declined_at = now(), updated_at = now() WHERE id = :qid AND business_id = :bid"),
        {"qid": quote_id, "bid": business_id},
    )
    session.commit()
    return {"status": "declined"}


@router.post("/{quote_id}/convert-to-invoice")
async def convert_to_invoice(
    quote_id: str,
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """Convert an accepted quote into an invoice."""
    business_id = str(auth_ctx["business_id"])

    quote_row = session.execute(
        text("SELECT * FROM quotes WHERE id = :qid AND business_id = :bid"),
        {"qid": quote_id, "bid": business_id},
    ).fetchone()

    if not quote_row:
        raise HTTPException(status_code=404, detail="Quote not found")

    if quote_row.status not in ("accepted", "sent", "draft"):
        raise HTTPException(status_code=400, detail=f"Cannot convert quote with status '{quote_row.status}'")

    invoice_id = str(uuid4())
    today = date.today()
    due_date = today + timedelta(days=30)

    inv_count = session.execute(
        text("SELECT COUNT(*) FROM invoices WHERE business_id = :bid"),
        {"bid": business_id},
    ).fetchone()
    inv_number = f"INV-{(inv_count[0] or 0) + 1:04d}"

    session.execute(
        text("""
            INSERT INTO invoices
            (id, business_id, invoice_number, customer_name, customer_email,
             due_date, amount, amount_due, currency, status, source, source_ref, created_at)
            VALUES
            (:id, :bid, :inum, :cname, :cemail, :due, :amount, :amount_due,
             :currency, 'unpaid', 'quote', :qnum, now())
        """),
        {
            "id": invoice_id,
            "bid": business_id,
            "inum": inv_number,
            "cname": quote_row.customer_name,
            "cemail": quote_row.customer_email,
            "due": due_date.isoformat(),
            "amount": float(quote_row.total),
            "amount_due": float(quote_row.total),
            "currency": quote_row.currency or "GBP",
            "qnum": quote_row.quote_number,
        },
    )

    session.execute(
        text("UPDATE quotes SET status = 'invoiced', invoice_id = :iid, updated_at = now() WHERE id = :qid"),
        {"qid": quote_id, "iid": invoice_id},
    )

    session.commit()
    return {"status": "invoiced", "invoice_id": invoice_id, "invoice_number": inv_number}


# ── Quote Settings ───────────────────────────────────────

@router.get("/settings/config")
async def get_quote_settings(
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """Get quote settings for the business."""
    business_id = str(auth_ctx["business_id"])
    row = session.execute(
        text("SELECT * FROM quote_settings WHERE business_id = :bid"),
        {"bid": business_id},
    ).fetchone()

    if not row:
        return {
            "quote_prefix": "QTE-",
            "next_quote_number": 1,
            "default_terms": "This quote is valid for 30 days from the date of issue.",
            "default_valid_days": 30,
            "default_tax_rate": 20.0,
            "include_tax": True,
            "default_markup": 0,
            "industry": "general",
        }

    return {
        "quote_prefix": row.quote_prefix,
        "next_quote_number": row.next_quote_number,
        "default_terms": row.default_terms,
        "default_valid_days": row.default_valid_days,
        "default_tax_rate": float(row.default_tax_rate) if row.default_tax_rate else 20.0,
        "include_tax": row.include_tax,
        "default_markup": float(row.default_markup) if row.default_markup else 0,
        "company_name": row.company_name,
        "company_address": row.company_address,
        "company_phone": row.company_phone,
        "company_email": row.company_email,
        "company_logo_url": row.company_logo_url,
        "company_registration": row.company_registration,
        "vat_number": row.vat_number,
        "industry": row.industry,
    }


@router.put("/settings/config")
async def update_quote_settings(
    settings: dict,
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """Update quote settings."""
    business_id = str(auth_ctx["business_id"])

    existing = session.execute(
        text("SELECT id FROM quote_settings WHERE business_id = :bid"),
        {"bid": business_id},
    ).fetchone()

    params = {
        "bid": business_id,
        "prefix": settings.get("quote_prefix", "QTE-"),
        "terms": settings.get("default_terms"),
        "valid_days": settings.get("default_valid_days", 30),
        "tax_rate": settings.get("default_tax_rate", 20),
        "inc_tax": settings.get("include_tax", True),
        "markup": settings.get("default_markup", 0),
        "co_name": settings.get("company_name"),
        "co_addr": settings.get("company_address"),
        "co_phone": settings.get("company_phone"),
        "co_email": settings.get("company_email"),
        "co_logo": settings.get("company_logo_url"),
        "co_reg": settings.get("company_registration"),
        "vat": settings.get("vat_number"),
        "industry": settings.get("industry", "general"),
    }

    if existing:
        session.execute(
            text("""
                UPDATE quote_settings SET
                    quote_prefix = :prefix, default_terms = :terms,
                    default_valid_days = :valid_days, default_tax_rate = :tax_rate,
                    include_tax = :inc_tax, default_markup = :markup,
                    company_name = :co_name, company_address = :co_addr,
                    company_phone = :co_phone, company_email = :co_email,
                    company_logo_url = :co_logo, company_registration = :co_reg,
                    vat_number = :vat, industry = :industry, updated_at = now()
                WHERE business_id = :bid
            """),
            params,
        )
    else:
        session.execute(
            text("""
                INSERT INTO quote_settings
                (business_id, quote_prefix, default_terms, default_valid_days,
                 default_tax_rate, include_tax, default_markup, company_name,
                 company_address, company_phone, company_email, company_logo_url,
                 company_registration, vat_number, industry)
                VALUES (:bid, :prefix, :terms, :valid_days, :tax_rate, :inc_tax,
                        :markup, :co_name, :co_addr, :co_phone, :co_email,
                        :co_logo, :co_reg, :vat, :industry)
            """),
            params,
        )

    session.commit()
    return {"status": "saved"}


# ── AI Quote Generation ──────────────────────────────────

@router.post("/ai/generate")
async def generate_ai_quote(
    data: dict,
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """Generate a quote using AI from a job description."""
    import httpx
    import os

    business_id = str(auth_ctx["business_id"])
    job_description = data.get("description", "")

    if not job_description:
        raise HTTPException(status_code=400, detail="Job description is required")

    settings_row = session.execute(
        text("SELECT industry, default_markup, default_tax_rate FROM quote_settings WHERE business_id = :bid"),
        {"bid": business_id},
    ).fetchone()

    industry = settings_row[0] if settings_row else "general"

    system_prompt = f"""You are an expert quantity surveyor and pricing specialist for the {industry} industry in the UK.

Given a job description, break it down into a detailed, itemised quote with realistic UK pricing.

Group items by trade/category. For each line item provide:
- group_name: the trade group (e.g., "Groundworks", "Electrical", "Plumbing", "Decorating")
- category: one of "labour", "materials", "equipment", "subcontractor", "other"
- description: clear description of the item
- quantity: estimated quantity needed
- unit: the unit of measurement (hours, days, each, sqm, lm, kg, cubic_m, litres, tonnes)
- unit_cost: realistic UK cost per unit in GBP

Use current UK trade rates:
- General labourer: £120-180/day
- Skilled tradesperson (bricklayer, carpenter, plasterer): £200-350/day
- Electrician: £250-400/day
- Plumber: £250-350/day
- Painter/decorator: £180-280/day
- Use realistic UK material prices

Be thorough but realistic. Include all necessary items that a professional would include.
Do NOT include VAT — that's calculated separately.
Do NOT include any markup — that's applied by the business separately.

Respond with ONLY a JSON object, no markdown, no explanation. Format:
{{
  "job_title": "concise title for the job",
  "groups": [
    {{
      "name": "Group Name",
      "items": [
        {{"description": "item", "quantity": 1, "unit": "each", "unit_cost": 100.00, "category": "materials"}}
      ]
    }}
  ],
  "estimated_duration": "estimated time to complete",
  "notes": "any important assumptions or exclusions"
}}"""

    try:
        openai_key = os.getenv("OPENAI_API_KEY")
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {openai_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-4o",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": job_description},
                    ],
                    "temperature": 0.3,
                    "response_format": {"type": "json_object"},
                },
            )

        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail=f"AI service error: {resp.status_code}")

        ai_response = resp.json()
        content = ai_response["choices"][0]["message"]["content"]
        quote_data = json.loads(content)

        line_items = []
        for group in quote_data.get("groups", []):
            for item in group.get("items", []):
                item["group_name"] = group.get("name", "")
                qty = float(item.get("quantity", 1))
                unit_cost = float(item.get("unit_cost", 0))
                item["line_total"] = round(qty * unit_cost, 2)
                line_items.append(item)

        subtotal = sum(item.get("line_total", 0) for item in line_items)

        return {
            "job_title": quote_data.get("job_title", ""),
            "line_items": line_items,
            "subtotal": round(subtotal, 2),
            "estimated_duration": quote_data.get("estimated_duration", ""),
            "notes": quote_data.get("notes", ""),
            "ai_model": "gpt-4o",
            "ai_prompt": job_description,
        }

    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="AI returned invalid response format")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"AI quote generation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Quote generation failed: {str(e)}")
