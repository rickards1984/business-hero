"""
Internal helper to send chase emails for invoices.
Used by WhatsApp action "send_chase" and automation rules.
Uses same logic as the main send-chase endpoint.
"""

import logging
from typing import Optional

from sqlalchemy import text
from sqlmodel import select

from db import get_session_transactional

logger = logging.getLogger(__name__)


def send_chase_for_invoice(
    business_id: str,
    invoice_id: str,
    stage: int = 1,
) -> tuple[bool, Optional[str]]:
    """
    Send a chase email for an invoice. Uses the same logic as the HTTP endpoint.

    Returns (success: bool, error_message: Optional[str])
    """
    stage = min(max(stage, 1), 4)
    outbox_id = None

    try:
        with get_session_transactional() as session:
            inv_row = session.execute(
                text("""
                    SELECT id, customer_name, customer_email, invoice_number,
                           amount, amount_due, due_date, chase_stage
                    FROM invoices
                    WHERE id = :inv_id AND business_id = :bid
                """),
                {"inv_id": invoice_id, "bid": business_id},
            ).fetchone()

            if not inv_row:
                return (False, "Invoice not found")

            if not inv_row[2]:  # customer_email
                return (False, "Customer email not set")

            # Lazy imports to avoid circular dependency with main
            from models import Invoice, Business, EmailOutbox
            from main import (
                get_email_account_for_sending,
                generate_chase_email,
                send_email_oauth,
            )
            from app.email.service import send_email_smtp

            invoice = session.exec(
                select(Invoice).where(
                    Invoice.id == invoice_id,
                    Invoice.business_id == business_id,
                )
            ).first()
            business = session.exec(
                select(Business).where(Business.id == business_id)
            ).first()

            if not invoice or not business:
                return (False, "Invoice or business not found")

            template = generate_chase_email(invoice, business, stage, None)
            subject = template["subject"]
            body = template["body"]

            oauth_account, smtp_connection = get_email_account_for_sending(
                session, business_id
            )
            if not oauth_account and not smtp_connection:
                return (False, "No email account configured")

            outbox = EmailOutbox(
                business_id=invoice.business_id,
                email_account_id=oauth_account.id if oauth_account else None,
                invoice_id=invoice.id,
                chase_stage=stage,
                to_emails=[invoice.customer_email or ""],
                subject=subject,
                body_preview=body[:500],
                status="queued",
            )
            session.add(outbox)
            session.flush()
            outbox_id = outbox.id

            if oauth_account:
                send_email_oauth(
                    session, oauth_account, invoice.customer_email, subject, body
                )
            else:
                send_email_smtp(
                    smtp_connection, invoice.customer_email, subject, body
                )

            outbox.status = "sent"
            outbox.sent_at = __import__("datetime").datetime.utcnow()
            invoice.last_chased_at = outbox.sent_at
            invoice.chase_stage = stage
            session.add(invoice)

        return (True, None)

    except Exception as e:
        logger.warning(f"[Invoice Chase] Failed for invoice {invoice_id}: {e}")
        if outbox_id is not None:
            try:
                with get_session_transactional() as session:
                    from models import EmailOutbox
                    outbox_ref = session.get(EmailOutbox, outbox_id)
                    if outbox_ref:
                        outbox_ref.status = "failed"
                        outbox_ref.error = str(e)[:1000]
            except Exception as log_exc:
                logger.error(
                    f"[Invoice Chase] Could not write failure status "
                    f"for outbox {outbox_id}: {log_exc}"
                )
        return (False, str(e))
