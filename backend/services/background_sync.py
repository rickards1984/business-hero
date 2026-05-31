"""
Background sync engine — keeps local email and financial data fresh automatically.

Email sync:  runs every 60 minutes, incremental via existing cursor-based sync
Financial sync: runs 3x daily (07:00, 13:00, 19:00), syncs transactions + invoices + caches summary

CRITICAL: Each business sync uses its OWN isolated database session. A failure
in one business must never poison the session used by another business or by
user-facing API requests.
"""

import json
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import text
from sqlmodel import Session, select

logger = logging.getLogger("background_sync")


async def background_email_sync_all():
    """
    Sync emails for ALL businesses with a connected email account.
    Each business gets its own isolated database session.
    """
    from db import get_session_context

    # Step 1: Get list of businesses to sync (own session, closed immediately)
    business_ids = []
    try:
        with get_session_context() as session:
            rows = session.execute(
                text("""
                    SELECT DISTINCT ea.business_id
                    FROM email_accounts ea
                    WHERE ea.provider IN ('google', 'microsoft')
                      AND ea.token_ciphertext IS NOT NULL
                """)
            ).fetchall()
            business_ids = [str(r[0]) for r in rows]
    except Exception as e:
        logger.error(f"[BackgroundSync] Failed to query email accounts: {e}")
        return

    if not business_ids:
        logger.debug("[BackgroundSync] No email accounts to sync")
        return

    # Step 2: Sync each business in its own session
    synced = 0
    for bid in business_ids:
        try:
            _sync_email_for_business(bid)
            synced += 1
        except Exception as e:
            logger.warning(f"[BackgroundSync] Email sync failed for business {bid}: {e}")

    logger.info(f"[BackgroundSync] Email sync complete: {synced}/{len(business_ids)} businesses synced")


def _sync_email_for_business(business_id: str):
    """Sync emails for a single business using a fresh isolated session."""
    from db import get_session_context
    from app.email.service import (
        get_business_by_id,
        get_default_email_account,
        get_provider_for_account,
    )
    from models import EmailSyncState, EmailMessage

    with get_session_context() as session:
        try:
            business = get_business_by_id(session, business_id)
            account = get_default_email_account(session, business)
            provider = get_provider_for_account(account)

            sync_state = session.exec(
                select(EmailSyncState).where(EmailSyncState.email_account_id == account.id)
            ).first()
            if not sync_state:
                sync_state = EmailSyncState(email_account_id=account.id, cursor={})
                session.add(sync_state)
                session.commit()
                session.refresh(sync_state)

            result = provider.sync_inbox_changes(account=account, cursor=sync_state.cursor or {})
            msg_count = 0

            for msg in result.messages:
                try:
                    existing = session.exec(
                        select(EmailMessage).where(
                            EmailMessage.email_account_id == account.id,
                            EmailMessage.provider_message_id == msg.provider_message_id,
                        )
                    ).first()
                    if existing:
                        existing.provider_thread_id = msg.provider_thread_id
                        existing.folder = msg.folder
                        existing.from_email = msg.from_email
                        existing.from_name = msg.from_name
                        existing.to_emails = msg.to_emails
                        existing.cc_emails = msg.cc_emails
                        existing.subject = msg.subject
                        existing.snippet = msg.snippet
                        existing.received_at = msg.received_at
                        existing.is_unread = msg.is_unread
                        existing.has_attachments = msg.has_attachments
                        existing.labels = msg.labels
                        existing.body_text = msg.body_text
                        existing.body_html = msg.body_html
                        existing.raw_headers = msg.raw_headers or {}
                        existing.updated_at = datetime.utcnow()
                        session.add(existing)
                    else:
                        record = EmailMessage(
                            business_id=business.id,
                            email_account_id=account.id,
                            provider_message_id=msg.provider_message_id,
                            provider_thread_id=msg.provider_thread_id,
                            folder=msg.folder,
                            from_email=msg.from_email,
                            from_name=msg.from_name,
                            to_emails=msg.to_emails,
                            cc_emails=msg.cc_emails,
                            subject=msg.subject,
                            snippet=msg.snippet,
                            received_at=msg.received_at,
                            is_unread=msg.is_unread,
                            has_attachments=msg.has_attachments,
                            labels=msg.labels,
                            body_text=msg.body_text,
                            body_html=msg.body_html,
                            raw_headers=msg.raw_headers or {},
                        )
                        session.add(record)
                    session.commit()
                    msg_count += 1
                except Exception as e:
                    logger.debug(f"[BackgroundSync] Failed to upsert email message: {e}")
                    try:
                        session.rollback()
                    except Exception:
                        pass

            # Update sync state
            try:
                sync_state.cursor = result.cursor or {}
                sync_state.last_synced_at = datetime.utcnow()
                sync_state.last_error = None
                session.add(sync_state)
                session.commit()
            except Exception as e:
                logger.debug(f"[BackgroundSync] Failed to update sync state: {e}")
                try:
                    session.rollback()
                except Exception:
                    pass

            if msg_count > 0:
                logger.info(f"[BackgroundSync] {msg_count} new/updated emails for {account.email_address}")
            else:
                logger.debug(f"[BackgroundSync] No new emails for {account.email_address}")

        except Exception as e:
            logger.warning(f"[BackgroundSync] Email sync failed for business {business_id}: {e}")
            try:
                session.rollback()
            except Exception:
                pass


async def background_financial_sync_all():
    """
    Sync accounting data for ALL businesses with connected providers.
    Each connection gets its own isolated database session.
    """
    from db import get_session_context

    # Step 1: Get list of connections to sync (own session, closed immediately)
    connection_list = []
    try:
        with get_session_context() as session:
            rows = session.execute(
                text("""
                    SELECT ac.id, ac.business_id, ac.provider, ac.tenant_id, ac.tenant_name
                    FROM accounting_connections ac
                    WHERE ac.is_active = true
                """)
            ).fetchall()
            connection_list = [
                {"id": str(r[0]), "business_id": str(r[1]), "provider": r[2], "tenant_id": r[3], "tenant_name": r[4]}
                for r in rows
            ]
    except Exception as e:
        logger.error(f"[BackgroundSync] Failed to query accounting connections: {e}")
        return

    if not connection_list:
        logger.debug("[BackgroundSync] No accounting connections to sync")
        return

    # Step 2: Sync each connection in its own session
    synced = 0
    for conn in connection_list:
        try:
            await _sync_financial_for_connection(conn)
            synced += 1
        except Exception as e:
            logger.error(f"[BackgroundSync] Financial sync failed for {conn['tenant_name']}: {e}")

    logger.info(f"[BackgroundSync] Financial sync complete: {synced}/{len(connection_list)} connections synced")


async def _sync_financial_for_connection(conn: dict):
    """Sync financial data for a single connection using a fresh isolated session."""
    from db import get_session_context
    from providers.accounting_service import AccountingService

    bid = conn["business_id"]
    conn_id = conn["id"]
    provider_name = conn["provider"]
    tenant_name = conn["tenant_name"]

    logger.info(f"[BackgroundSync] Financial sync starting for {tenant_name} ({provider_name})")

    with get_session_context() as session:
        try:
            svc = AccountingService(bid, session)
            provider = await svc.get_provider()
            if not provider:
                logger.warning(f"[BackgroundSync] Could not get provider for {bid}")
                return

            connection_data = svc.get_connection()
            last_sync = connection_data.get("last_sync_at") if connection_data else None
            modified_since = last_sync.isoformat() if last_sync and hasattr(last_sync, "isoformat") else None

            # Sync transactions
            try:
                txns = await provider.get_all_bank_transactions(modified_since=modified_since)
                for txn in txns:
                    try:
                        cat_name = getattr(txn, "provider_category_name", None) or txn.category
                        category_id = None
                        if cat_name and not str(cat_name).strip().isdigit():
                            existing = session.execute(
                                text("SELECT id FROM accounting_categories WHERE business_id = :bid AND LOWER(name) = LOWER(:name)"),
                                {"bid": bid, "name": cat_name},
                            ).fetchone()
                            category_id = str(existing[0]) if existing else None

                        session.execute(
                            text("""
                                INSERT INTO accounting_transactions
                                    (business_id, transaction_date, description, amount, type,
                                     reference, payee_payer, external_id, external_source, category_id)
                                VALUES
                                    (:bid, :txn_date, :desc, :amt, :type,
                                     :ref, :payee, :eid, :esrc, :category_id)
                                ON CONFLICT (business_id, external_source, external_id)
                                WHERE external_id IS NOT NULL
                                DO UPDATE SET
                                    description = EXCLUDED.description,
                                    amount = EXCLUDED.amount,
                                    type = EXCLUDED.type,
                                    reference = EXCLUDED.reference,
                                    payee_payer = EXCLUDED.payee_payer,
                                    category_id = COALESCE(EXCLUDED.category_id, accounting_transactions.category_id),
                                    updated_at = NOW()
                            """),
                            {
                                "bid": bid,
                                "txn_date": txn.date,
                                "desc": txn.description,
                                "amt": txn.amount,
                                "type": txn.transaction_type,
                                "ref": txn.reference,
                                "payee": txn.contact_name,
                                "eid": txn.external_id,
                                "esrc": provider_name,
                                "category_id": category_id,
                            },
                        )
                        session.commit()
                    except Exception as e:
                        logger.debug(f"[BackgroundSync] Failed to upsert transaction: {e}")
                        try:
                            session.rollback()
                        except Exception:
                            pass
                logger.info(f"[BackgroundSync] Synced {len(txns)} transactions for {tenant_name}")
            except Exception as e:
                logger.warning(f"[BackgroundSync] Transaction sync failed for {tenant_name}: {e}")
                try:
                    session.rollback()
                except Exception:
                    pass

            # Sync invoices
            try:
                invoices = await provider.get_invoices()
                for inv in invoices:
                    try:
                        session.execute(
                            text("""
                                INSERT INTO invoices (
                                    id, business_id, external_id, external_source,
                                    invoice_number, customer_name, customer_email,
                                    amount, amount_due, amount_paid,
                                    status, due_date, currency, source, archived,
                                    created_at, updated_at
                                ) VALUES (
                                    gen_random_uuid(), :bid, :eid, :esrc,
                                    :inum, :cname, :cemail,
                                    :amt, :amt_due, :amt_paid,
                                    :status, :due, :currency, :source, false,
                                    NOW(), NOW()
                                )
                                ON CONFLICT (business_id, external_source, external_id)
                                WHERE external_id IS NOT NULL
                                DO UPDATE SET
                                    amount = EXCLUDED.amount,
                                    amount_due = EXCLUDED.amount_due,
                                    amount_paid = EXCLUDED.amount_paid,
                                    status = EXCLUDED.status,
                                    due_date = EXCLUDED.due_date,
                                    updated_at = NOW()
                            """),
                            {
                                "bid": bid,
                                "eid": inv.external_id,
                                "esrc": provider_name,
                                "inum": inv.invoice_number,
                                "cname": inv.contact_name,
                                "cemail": inv.contact_email,
                                "amt": inv.total,
                                "amt_due": inv.amount_due,
                                "amt_paid": inv.amount_paid,
                                "status": inv.status,
                                "due": inv.due_date,
                                "currency": inv.currency or "GBP",
                                "source": provider_name,
                            },
                        )
                        session.commit()
                    except Exception as e:
                        logger.debug(f"[BackgroundSync] Failed to upsert invoice: {e}")
                        try:
                            session.rollback()
                        except Exception:
                            pass
                logger.info(f"[BackgroundSync] Synced {len(invoices)} invoices for {tenant_name}")
            except Exception as e:
                logger.warning(f"[BackgroundSync] Invoice sync failed for {tenant_name}: {e}")
                try:
                    session.rollback()
                except Exception:
                    pass

            # Cache financial summary
            try:
                await _refresh_financial_summary_cache(session, bid, provider, provider_name)
            except Exception as e:
                logger.warning(f"[BackgroundSync] Financial cache refresh failed for {tenant_name}: {e}")
                try:
                    session.rollback()
                except Exception:
                    pass

            # Update last_sync_at
            try:
                session.execute(
                    text("UPDATE accounting_connections SET last_sync_at = NOW() WHERE id = :cid"),
                    {"cid": conn_id},
                )
                session.commit()
            except Exception as e:
                logger.debug(f"[BackgroundSync] Failed to update last_sync_at: {e}")
                try:
                    session.rollback()
                except Exception:
                    pass

            logger.info(f"[BackgroundSync] Financial sync complete for {tenant_name}")

        except Exception as e:
            logger.error(f"[BackgroundSync] Financial sync failed for {tenant_name}: {e}")
            try:
                session.rollback()
            except Exception:
                pass


async def _refresh_financial_summary_cache(session, business_id: str, provider, provider_name: str):
    """Fetch fresh financial summary from the provider and cache it locally."""
    from datetime import date

    today = date.today()
    first_of_month = today.replace(day=1)

    bank_summary = None
    pnl = None

    try:
        if hasattr(provider, "get_bank_summary"):
            bank_summary = await provider.get_bank_summary()
    except Exception as e:
        logger.debug(f"[BackgroundSync] Bank summary fetch failed: {e}")

    try:
        if hasattr(provider, "get_profit_and_loss"):
            pnl = await provider.get_profit_and_loss(
                from_date=first_of_month.isoformat(),
                to_date=today.isoformat(),
            )
    except Exception as e:
        logger.debug(f"[BackgroundSync] P&L fetch failed: {e}")

    invoices_summary = {"overdue_count": 0, "overdue_amount": 0, "due_count": 0, "due_amount": 0}
    try:
        inv_row = session.execute(
            text("""
                SELECT
                    COUNT(*) FILTER (WHERE status IN ('overdue', 'OVERDUE') OR (due_date < CURRENT_DATE AND status NOT IN ('paid', 'PAID', 'cancelled', 'VOIDED'))) as overdue_count,
                    COALESCE(SUM(amount_due) FILTER (WHERE status IN ('overdue', 'OVERDUE') OR (due_date < CURRENT_DATE AND status NOT IN ('paid', 'PAID', 'cancelled', 'VOIDED'))), 0) as overdue_amount,
                    COUNT(*) FILTER (WHERE status NOT IN ('paid', 'PAID', 'cancelled', 'VOIDED', 'DELETED') AND amount_due > 0) as due_count,
                    COALESCE(SUM(amount_due) FILTER (WHERE status NOT IN ('paid', 'PAID', 'cancelled', 'VOIDED', 'DELETED') AND amount_due > 0), 0) as due_amount
                FROM invoices
                WHERE business_id = :bid AND archived = false
            """),
            {"bid": business_id},
        ).fetchone()
        if inv_row:
            invoices_summary = {
                "overdue_count": int(inv_row[0]),
                "overdue_amount": float(inv_row[1]),
                "due_count": int(inv_row[2]),
                "due_amount": float(inv_row[3]),
            }
    except Exception as e:
        logger.debug(f"[BackgroundSync] Invoice summary query failed: {e}")
        try:
            session.rollback()
        except Exception:
            pass

    session.execute(
        text("""
            INSERT INTO financial_summary_cache
                (business_id, provider, bank_summary, profit_and_loss, invoices_summary,
                 cached_at, period_start, period_end)
            VALUES
                (:business_id, :provider, :bank_summary, :pnl, :invoices_summary,
                 NOW(), :period_start, :period_end)
            ON CONFLICT (business_id, provider)
            DO UPDATE SET
                bank_summary = :bank_summary,
                profit_and_loss = :pnl,
                invoices_summary = :invoices_summary,
                cached_at = NOW(),
                period_start = :period_start,
                period_end = :period_end
        """),
        {
            "business_id": business_id,
            "provider": provider_name,
            "bank_summary": json.dumps(bank_summary) if bank_summary else None,
            "pnl": json.dumps(pnl) if pnl else None,
            "invoices_summary": json.dumps(invoices_summary),
            "period_start": first_of_month.isoformat(),
            "period_end": today.isoformat(),
        },
    )
    session.commit()
    logger.info(f"[BackgroundSync] Financial summary cached for business {business_id}")
