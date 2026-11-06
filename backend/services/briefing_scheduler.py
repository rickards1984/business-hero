"""
Scheduler for CEO briefings and daily pulses.
Runs as a FastAPI background task, checking every minute if any messages need sending.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone, date, timedelta

import pytz
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError

from db import get_session_context, get_session_transactional

logger = logging.getLogger(__name__)

_scheduler_running = False
MAX_TEMPLATE_VAR_LENGTH = 500

_last_email_sync: datetime | None = None
_last_financial_sync: datetime | None = None
_FINANCIAL_SYNC_HOURS = {7, 13, 19}
_STARTUP_DELAY_MINUTES = 5


async def start_briefing_scheduler():
    """Start the background scheduler. Call this on app startup."""
    global _scheduler_running, _last_email_sync, _last_financial_sync
    if _scheduler_running:
        return
    _scheduler_running = True

    # Pretend the last EMAIL sync happened 115 minutes ago so the first one
    # fires _STARTUP_DELAY_MINUTES from now rather than immediately, and the
    # financial sync as if it just ran.
    #
    # This delays the two SYNC JOBS ONLY. It does not protect the healthcheck:
    # `_check_and_send_scheduled_messages` is not governed by these timestamps
    # and used to run the instant the loop was scheduled — a blocking psycopg2
    # query on the event loop, roughly one second after startup, while Railway
    # was still probing /health. The leading `await asyncio.sleep()` in
    # `_scheduler_loop` is what keeps the first minute clear; see the note
    # there before shortening either delay.
    now = datetime.now(timezone.utc)
    _last_email_sync = now - timedelta(minutes=120 - _STARTUP_DELAY_MINUTES)
    _last_financial_sync = now

    logger.info("[Scheduler] Starting CEO briefing scheduler")
    asyncio.create_task(_scheduler_loop())


_last_stripe_reconcile = None
_stripe_reconcile_task = None


async def _reconcile_stripe_if_due():
    global _last_stripe_reconcile, _stripe_reconcile_task
    if _stripe_reconcile_task is not None and not _stripe_reconcile_task.done():
        return
    current = datetime.now(timezone.utc)
    if _last_stripe_reconcile and current - _last_stripe_reconcile < timedelta(days=1):
        return
    _last_stripe_reconcile = current

    def _run():
        from db import get_session_context
        from services import stripe_reconciliation
        try:
            with get_session_context() as session:
                stripe_reconciliation.run(session)
        except Exception as exc:
            # Say WHY, so the next failure can be fixed from the logs: the error
            # class and a short message only (Stripe masks keys in its messages).
            logger.error("[Scheduler] Stripe reconciliation failed: %s: %s",
                         type(exc).__name__, str(exc)[:200])
            stripe_reconciliation.record_failure()

    # Retain the task and skip overlapping runs without holding up other jobs.
    _stripe_reconcile_task = asyncio.create_task(asyncio.to_thread(_run))


_last_metering_reconcile = None


async def _reconcile_metering_if_due():
    global _last_metering_reconcile
    current = datetime.utcnow()
    if _last_metering_reconcile and (current - _last_metering_reconcile).total_seconds() < 900:
        return
    _last_metering_reconcile = current

    def _run():
        from db import get_session_context
        from services import metering
        with get_session_context() as session:
            count = metering.reconcile_unmetered_calls(session)
            session.commit()
        if count:
            logger.warning(f"[Scheduler] Metering reconciliation counted {count} missed call(s)")
        # NS-V1: Aria voice sessions whose end-of-session accrual never landed.
        import realtime_voice
        with get_session_context() as session:
            voice = metering.reconcile_open_voice_sessions(
                session, alive=realtime_voice.live_sessions())
        if voice:
            logger.warning(f"[Scheduler] Metering recovered {voice} voice session(s)")

    await asyncio.to_thread(_run)


_last_invoice_autopilot = None
_invoice_autopilot_task = None


async def _run_invoice_autopilot_if_due():
    """AUTO-1: Aria's invoice-chasing autopilot, hourly, for every business
    that switched it on. In a worker thread (sync DB and email sends), in the
    background so it never holds up the loop, and never two runs at once."""
    global _last_invoice_autopilot, _invoice_autopilot_task
    if _invoice_autopilot_task is not None and not _invoice_autopilot_task.done():
        return
    current = datetime.now(timezone.utc)
    if _last_invoice_autopilot and current - _last_invoice_autopilot < timedelta(hours=1):
        return
    _last_invoice_autopilot = current

    def _run():
        from db import get_session_context
        from services import automations
        try:
            with get_session_context() as session:
                sent = automations.run_all_due(session)
            if sent:
                logger.info(f"[Scheduler] Invoice autopilot sent {sent} chase(s)")
        except Exception as e:
            logger.error(f"[Scheduler] Invoice autopilot failed: {e}")

    _invoice_autopilot_task = asyncio.create_task(asyncio.to_thread(_run))


_last_outreach_autopilot = None
_outreach_autopilot_task = None


async def _run_outreach_autopilot_if_due():
    """OUT-11: automatic outreach sends under the owner's standing permission.
    Every 2 minutes, off the loop, never two at once; the 6-12 minute pace
    and every send rule live in services.outreach_autopilot."""
    global _last_outreach_autopilot, _outreach_autopilot_task
    if _outreach_autopilot_task is not None and not _outreach_autopilot_task.done():
        return
    current = datetime.now(timezone.utc)
    if _last_outreach_autopilot and current - _last_outreach_autopilot < timedelta(minutes=2):
        return
    _last_outreach_autopilot = current

    def _run():
        from db import get_session_context
        from services import outreach_autopilot
        try:
            with get_session_context() as session:
                sent = outreach_autopilot.run_due(session)
            if sent:
                logger.info(f"[Scheduler] Outreach autopilot sent {len(sent)} email(s)")
        except Exception as e:
            logger.error(f"[Scheduler] Outreach autopilot failed: {type(e).__name__}")

    _outreach_autopilot_task = asyncio.create_task(asyncio.to_thread(_run))


_last_profit_check = None


async def _run_profit_check_if_due():
    """PROFIT-1: voice minutes or fixed costs can cross a threshold with no
    AI call to notice it: checked every 15 minutes, off the loop. Never raises."""
    global _last_profit_check
    current = datetime.now(timezone.utc)
    if _last_profit_check and current - _last_profit_check < timedelta(minutes=15):
        return
    _last_profit_check = current
    from services import profit_guard
    asyncio.create_task(asyncio.to_thread(profit_guard.periodic_check))
    # OUT-19 F: brand changes and top-ups Stripe didn't confirm are checked
    # with Stripe on the same 15-minute beat (never raises).
    from services import outreach_billing
    asyncio.create_task(asyncio.to_thread(outreach_billing.scheduled_check))


async def _deliver_metering_notices():
    """BH-012: send pending usage notices every tick, in a worker thread. In a
    thread there is no running event loop, so the WhatsApp send is awaited to
    completion and its result is a real acknowledgement."""
    def _run():
        from db import get_session_context
        from services import metering
        with get_session_context() as session:
            metering.deliver_pending_notices(session)

    await asyncio.to_thread(_run)


async def _scheduler_loop():
    """Main scheduler loop — runs every 60 seconds.

    THE SLEEP LEADS THE ITERATION, DELIBERATELY. It used to trail it, so the
    first `_check_and_send_scheduled_messages()` ran the moment the task was
    scheduled — about a second after startup. That function is `async def` but
    its body is a synchronous SQLModel session (`get_session_context`), so it
    blocks the event loop on psycopg2 I/O and the app cannot answer /health
    while it runs. Sleeping first gives startup a clear minute.

    `sleep_seconds` carries the backoff to the NEXT wait: a database error
    shortens it to 30s, anything else restores 60s.
    """
    sleep_seconds = 60
    while True:
        await asyncio.sleep(sleep_seconds)
        sleep_seconds = 60
        try:
            await _check_and_send_scheduled_messages()
        except (OperationalError, DBAPIError) as db_err:
            logger.warning(
                f"[Scheduler] Database connection error, will retry: {db_err}"
            )
            try:
                from db import engine
                engine.dispose()
            except Exception as dispose_err:
                logger.error(
                    f"[Scheduler] Failed to dispose engine: {dispose_err}"
                )
            sleep_seconds = 30
        except Exception as e:
            logger.error(
                f"[Scheduler] Error in scheduler loop: {e}", exc_info=True
            )

        # Background sync jobs (fire-and-forget so they don't block the loop)
        try:
            _run_background_sync_jobs_nonblocking()
        except Exception as e:
            logger.error(f"[Scheduler] Error scheduling background sync: {e}")

        try:
            await _run_invoice_autopilot_if_due()
        except Exception as e:
            logger.error(f"[Scheduler] Invoice autopilot scheduling failed: {e}")

        try:
            await _run_outreach_autopilot_if_due()
        except Exception as e:
            logger.error(f"[Scheduler] Outreach autopilot scheduling failed: {e}")

        try:
            await _run_profit_check_if_due()
        except Exception as e:
            logger.error(f"[Scheduler] Profit check scheduling failed: {e}")

        try:
            await _reconcile_stripe_if_due()
        except Exception:
            logger.error("[Scheduler] Stripe reconciliation failed")

        # BH-012: meter any finished receptionist call that missed metering
        # at call end. Every 15 minutes, off the event loop (sync DB work).
        try:
            await _reconcile_metering_if_due()
        except Exception as e:
            logger.error(f"[Scheduler] Metering reconciliation failed: {e}")
        try:
            await _deliver_metering_notices()
        except Exception as e:
            logger.error(f"[Scheduler] Metering notice delivery failed: {e}")

        # Executive Board Meeting prep (Prompt 2). Wrapped in its own try/except
        # so a failure here can never break the existing scheduler.
        try:
            await _check_and_prep_executive_meetings()
        except Exception as e:
            logger.error(
                f"[Scheduler] Executive meeting prep failed: {e}", exc_info=True
            )


def _run_background_sync_jobs_nonblocking():
    """Check if background sync jobs are due and fire them as non-blocking tasks."""
    global _last_email_sync, _last_financial_sync
    now = datetime.now(timezone.utc)

    # Email sync: every 2 hours during business hours (08–18), weekdays only
    london_tz = pytz.timezone("Europe/London")
    now_london = now.astimezone(london_tz)
    is_business_hours = now_london.weekday() < 5 and 8 <= now_london.hour <= 18
    if is_business_hours and (
        _last_email_sync is None or (now - _last_email_sync).total_seconds() >= 7200
    ):
        _last_email_sync = now
        asyncio.create_task(_safe_background_email_sync())

    # 3x daily financial sync (07:00, 13:00, 19:00 UTC)
    current_hour = now.hour
    if current_hour in _FINANCIAL_SYNC_HOURS:
        should_run = (
            _last_financial_sync is None
            or _last_financial_sync.hour != current_hour
            or (now - _last_financial_sync).total_seconds() >= 3600
        )
        if should_run:
            _last_financial_sync = now
            asyncio.create_task(_safe_background_financial_sync())


async def _safe_background_email_sync():
    """Run email sync in a fire-and-forget task with error handling."""
    try:
        from services.background_sync import background_email_sync_all
        logger.info("[Scheduler] Starting hourly background email sync")
        await background_email_sync_all()
    except Exception as e:
        logger.error(f"[Scheduler] Background email sync failed: {e}")


async def _safe_background_financial_sync():
    """Run financial sync in a fire-and-forget task with error handling."""
    try:
        from services.background_sync import background_financial_sync_all
        current_hour = datetime.now(timezone.utc).hour
        logger.info(f"[Scheduler] Starting background financial sync ({current_hour:02d}:00)")
        await background_financial_sync_all()
    except Exception as e:
        logger.error(f"[Scheduler] Background financial sync failed: {e}")


async def _check_and_send_scheduled_messages():
    """Check if any briefings or pulses are due to be sent"""
    now_utc = datetime.now(timezone.utc)

    with get_session_context() as session:
        config_rows = session.execute(
            text("""
                SELECT wc.id, wc.business_id, wc.phone_number, wc.timezone,
                       wc.owner_name, wc.daily_pulse_enabled, wc.daily_pulse_time,
                       wc.weekly_briefing_enabled, wc.weekly_briefing_day, wc.weekly_briefing_time,
                       wc.preferred_detail_level, b.name as business_name,
                       COALESCE(wc.real_time_alerts_enabled, false) as real_time_alerts_enabled,
                       COALESCE(wc.task_reminder_enabled, false) as task_reminder_enabled,
                       COALESCE(wc.task_reminder_frequency, 'daily') as task_reminder_frequency,
                       COALESCE(wc.task_reminder_time, '08:00') as task_reminder_time
                FROM whatsapp_configs wc
                LEFT JOIN businesses b ON wc.business_id = b.id
                WHERE wc.enabled = true
            """)
        ).fetchall()

    for row in config_rows:
        try:
            config = {
                "id": str(row[0]),
                "business_id": str(row[1]),
                "phone_number": row[2],
                "timezone": row[3] or "Europe/London",
                "owner_name": row[4] or "",
                "daily_pulse_enabled": row[5],
                "daily_pulse_time": row[6] or "07:30",
                "weekly_briefing_enabled": row[7],
                "weekly_briefing_day": (row[8] or "monday").lower(),
                "weekly_briefing_time": row[9] or "08:00",
                "preferred_detail_level": row[10] or "standard",
                "business_name": row[11] or "Your Business",
                "real_time_alerts_enabled": bool(row[12]) if len(row) > 12 else False,
                "task_reminder_enabled": bool(row[13]) if len(row) > 13 else False,
                "task_reminder_frequency": (row[14] or "daily") if len(row) > 14 else "daily",
                "task_reminder_time": (row[15] or "08:00") if len(row) > 15 else "08:00",
            }

            tz = pytz.timezone(config["timezone"])
            now_local = now_utc.astimezone(tz)
            current_time = now_local.strftime("%H:%M")
            current_day = now_local.strftime("%A").lower()

            business_id = config["business_id"]
            phone = config["phone_number"]
            business_name = config["business_name"]

            # BRIEF-1: Aria's weekly (Fridays 16:00) and monthly (the 1st, 08:00)
            # briefings, from stored data only. The daily pulse is retired.
            from services import whatsapp_briefings
            from services.whatsapp_service import send_whatsapp_message
            try:   # isolated: a briefing failure never skips this business's reminders below
                for kind in await whatsapp_briefings.run_for(
                    config, now_local, session_factory=get_session_context, send=send_whatsapp_message
                ):
                    logger.info(f"[Scheduler] Sent {kind} to {business_name}")
            except Exception as e:
                logger.error(f"[Scheduler] Briefing failed for {business_id}: {type(e).__name__}")

            # Check task reminder
            if config.get("task_reminder_enabled"):
                task_reminder_time = config.get("task_reminder_time", "08:00")
                task_reminder_freq = config.get("task_reminder_frequency", "daily")

                should_send_task = False
                if task_reminder_freq == "daily" and current_time == task_reminder_time:
                    should_send_task = True
                elif task_reminder_freq == "weekly" and current_day == "monday" and current_time == task_reminder_time:
                    should_send_task = True

                if should_send_task:
                    already_sent = await _was_sent_today(
                        business_id, "task_reminder", now_local.date()
                    )
                    if not already_sent:
                        logger.info(f"[Scheduler] Sending task reminder to {business_name}")
                        await _send_task_reminder(
                            business_id, phone, business_name
                        )

            # Evaluate automation rules and invoice overdue alerts every 5 minutes
            if now_local.minute % 5 == 0:
                try:
                    from services.automation_engine import evaluate_automation_rules
                    await evaluate_automation_rules(business_id)
                except Exception as e:
                    logger.error(f"[Scheduler] Automation evaluation failed for {business_id}: {e}")

                # Dispatch invoice_overdue alerts for businesses with real-time alerts enabled
                if config.get("real_time_alerts_enabled"):
                    try:
                        await _dispatch_overdue_invoice_alerts(business_id)
                    except Exception as e:
                        logger.error(f"[Scheduler] Invoice overdue alerts failed for {business_id}: {e}")

        except Exception as e:
            logger.error(
                f"[Scheduler] Error processing config for {row[1] if row else 'unknown'}: {e}"
            )


async def _dispatch_overdue_invoice_alerts(business_id: str) -> None:
    """Dispatch invoice_overdue alerts for overdue invoices not yet alerted (max 3 per run)."""
    from services.alert_dispatcher import dispatch_alert

    today = date.today()
    cutoff = (today - timedelta(days=1)).isoformat()  # alerts sent in last 24h

    with get_session_context() as session:
        overdue = session.execute(
            text("""
                SELECT id, invoice_number, customer_name,
                       COALESCE(amount_due, amount) as amount_due, due_date
                FROM invoices
                WHERE business_id = :business_id
                  AND status IN ('unpaid', 'authorised', 'sent')
                  AND due_date < :today
                  AND (archived IS NULL OR archived = false)
            """),
            {"business_id": business_id, "today": today.isoformat()},
        ).fetchall()

    alerted_ids = set()
    with get_session_context() as session:
        recent = session.execute(
            text("""
                SELECT related_entity_id FROM whatsapp_messages
                WHERE business_id = :business_id
                  AND message_type = 'alert'
                  AND related_entity_type = 'invoice'
                  AND related_entity_id IS NOT NULL
                  AND created_at >= :cutoff
            """),
            {"business_id": business_id, "cutoff": cutoff},
        ).fetchall()
        alerted_ids = {str(r[0]) for r in recent if r[0]}

    count = 0
    for row in overdue:
        if count >= 3:
            break
        inv_id = str(row[0])
        if inv_id in alerted_ids:
            continue
        inv_number = row[1] or ""
        contact_name = row[2] or "Unknown"
        amount = float(row[3] or 0)
        due = row[4]
        days_overdue = (today - due).days if due else 0
        due_str = due.isoformat() if due else ""

        await dispatch_alert(
            business_id,
            "invoice_overdue",
            {
                "contact_name": contact_name,
                "amount": amount,
                "invoice_number": inv_number,
                "due_date": due_str,
                "days_overdue": days_overdue,
                "entity_type": "invoice",
                "entity_id": inv_id,
                "action_option": {
                    "label": "Send friendly chase reminder",
                    "type": "send_chase",
                    "config": {"invoice_id": inv_id, "stage": 1},
                },
            },
        )
        alerted_ids.add(inv_id)
        count += 1


async def _was_sent_today(business_id: str, message_type: str, today: date) -> bool:
    """Check if a message type was already sent today"""
    with get_session_context() as session:
        result = session.execute(
            text("""
                SELECT id FROM whatsapp_messages
                WHERE business_id = :business_id
                  AND message_type = :message_type
                  AND created_at >= :today_start
                LIMIT 1
            """),
            {
                "business_id": business_id,
                "message_type": message_type,
                "today_start": today.isoformat(),
            },
        ).fetchone()
    return result is not None


async def _sync_accounting_for_pulse(business_id: str):
    """
    Trigger a lightweight accounting sync before the daily pulse.
    If the background financial sync ran recently (< 2 hours), skip the live sync
    since data is already fresh in the database.
    """
    try:
        with get_session_context() as session:
            cached = session.execute(
                text("""
                    SELECT cached_at FROM financial_summary_cache
                    WHERE business_id = :bid
                    LIMIT 1
                """),
                {"bid": business_id},
            ).fetchone()
            if cached and cached[0]:
                cache_age = (datetime.now(timezone.utc) - (cached[0].replace(tzinfo=timezone.utc) if cached[0].tzinfo is None else cached[0])).total_seconds() / 3600
                if cache_age < 2:
                    logger.info(f"[Scheduler] Financial cache is fresh ({cache_age:.1f}h old), skipping live sync for {business_id}")
                    return
    except Exception:
        pass

    from providers.accounting_service import AccountingService

    with get_session_transactional() as session:
        svc = AccountingService(business_id, session)
        connection = svc.get_connection()
        if not connection:
            logger.info(f"[Scheduler] No accounting connection for {business_id}, skipping sync")
            return

        provider = await svc.get_provider()
        if not provider:
            return

        provider_name = connection["provider"]
        logger.info(f"[Scheduler] Syncing {provider_name} data for {business_id} before pulse")

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
                            "bid": business_id,
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
                except Exception:
                    pass
            logger.info(f"[Scheduler] Synced {len(invoices)} invoices for {business_id}")
        except Exception as e:
            logger.warning(f"[Scheduler] Invoice sync failed for {business_id}: {e}")

        # Sync bank transactions (for revenue/expense figures)
        try:
            last_sync = connection.get("last_sync_at")
            modified_since = last_sync.isoformat() if last_sync and hasattr(last_sync, "isoformat") else None
            txns = await provider.get_all_bank_transactions(modified_since=modified_since)

            sched_cat_cache = {}
            for txn in txns:
                try:
                    category_id = None
                    cat_name = getattr(txn, "provider_category_name", None) or txn.category
                    if cat_name and not str(cat_name).strip().isdigit():
                        if cat_name in sched_cat_cache:
                            category_id = sched_cat_cache[cat_name]
                        else:
                            existing = session.execute(
                                text("SELECT id FROM accounting_categories WHERE business_id = :bid AND LOWER(name) = LOWER(:name)"),
                                {"bid": business_id, "name": cat_name},
                            ).fetchone()
                            if existing:
                                category_id = str(existing[0])
                            else:
                                cat_type = getattr(txn, "provider_category_type", None) or (
                                    "income" if txn.transaction_type == "income" else "expense"
                                )
                                new_cat = session.execute(
                                    text("""
                                        INSERT INTO accounting_categories
                                            (business_id, name, type, color, created_at, updated_at)
                                        VALUES (:bid, :name, :cat_type, '#6B7280', NOW(), NOW())
                                        RETURNING id
                                    """),
                                    {"bid": business_id, "name": cat_name, "cat_type": cat_type},
                                ).fetchone()
                                category_id = str(new_cat[0]) if new_cat else None
                            sched_cat_cache[cat_name] = category_id

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
                            "bid": business_id,
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
                except Exception:
                    pass
            logger.info(f"[Scheduler] Synced {len(txns)} transactions for {business_id}")
        except Exception as e:
            logger.warning(f"[Scheduler] Transaction sync failed for {business_id}: {e}")

        # Update last_sync_at
        try:
            session.execute(
                text("UPDATE accounting_connections SET last_sync_at = NOW() WHERE id = :cid"),
                {"cid": connection["id"]},
            )
        except Exception as e:
            logger.warning(f"[Scheduler] Failed to update last_sync_at: {e}")


async def _send_task_reminder(
    business_id: str,
    phone: str,
    business_name: str,
):
    """Generate and send task reminder via WhatsApp."""
    from services.whatsapp_service import send_whatsapp_message

    with get_session_context() as session:
        tasks_rows = session.execute(
            text("""
                SELECT id, title, status, priority, category, due_date
                FROM tasks
                WHERE business_id = :bid
                  AND status = 'open'
                  AND deleted_at IS NULL
                ORDER BY
                  CASE WHEN priority = 'high' THEN 0 WHEN priority = 'medium' THEN 1 ELSE 2 END,
                  due_date ASC NULLS LAST
            """),
            {"bid": business_id},
        ).fetchall()

    if not tasks_rows:
        return

    tasks = [
        {
            "title": r[1],
            "priority": r[3],
            "due_date": r[5].isoformat() if r[5] else None,
        }
        for r in tasks_rows
    ]

    today = date.today()

    open_count = len(tasks)
    overdue = [t for t in tasks if t["due_date"] and date.fromisoformat(t["due_date"]) < today]
    high_priority = [t for t in tasks if t["priority"] == "high"]

    open_summary = f"{open_count} open task{'s' if open_count != 1 else ''}."

    if overdue:
        overdue_lines = []
        for t in overdue[:3]:
            days = (today - date.fromisoformat(t["due_date"])).days
            overdue_lines.append(f"\u2022 {t['title']} ({days} day{'s' if days != 1 else ''} overdue)")
        overdue_summary = "\n".join(overdue_lines)
        if len(overdue) > 3:
            overdue_summary += f"\n...and {len(overdue) - 3} more"
    else:
        overdue_summary = "None \u2014 all caught up!"

    if high_priority:
        hp_lines = [f"\u2022 {t['title']}" for t in high_priority[:3]]
        hp_summary = "\n".join(hp_lines)
        if len(high_priority) > 3:
            hp_summary += f"\n...and {len(high_priority) - 3} more"
    else:
        hp_summary = "None right now."

    await send_whatsapp_message(
        to_number=phone,
        body=json.dumps({
            "1": business_name,
            "2": open_summary[:MAX_TEMPLATE_VAR_LENGTH],
            "3": overdue_summary[:MAX_TEMPLATE_VAR_LENGTH],
            "4": hp_summary[:MAX_TEMPLATE_VAR_LENGTH],
        }),
        business_id=business_id,
        message_type="task_reminder",
    )


# ============================================================================
# Executive Board Meeting prep tick (Prompt 2)
# ============================================================================

# Window before scheduled_for during which we run prep. 35 minutes gives a
# 30-min prep target plus 5-min scheduler-tick granularity.
_EXEC_PREP_WINDOW_MINUTES = 35


async def _check_and_prep_executive_meetings() -> None:
    """
    Find businesses with executive meetings due in the next ~35 minutes,
    create the meeting record if it doesn't exist yet, and run prep.

    Pattern:
    - SELECT settings rows where enabled AND next_meeting_at <= now() + 35m
    - For each, ensure an executive_meetings row exists with scheduled_for=next_meeting_at
    - If meeting still status='scheduled', run prep, store prep_data, set status='prep_ready'

    Failures in any single business's prep are logged and do not affect others.
    """
    try:
        with get_session_context() as session:
            due_rows = session.execute(
                text(
                    """
                    SELECT business_id, next_meeting_at, frequency, timezone,
                           focus_areas, custom_agenda_items, attendees,
                           directness_level, include_disclaimers
                    FROM executive_meeting_settings
                    WHERE enabled = true
                      AND next_meeting_at IS NOT NULL
                      AND next_meeting_at <= NOW() + (:window_minutes * INTERVAL '1 minute')
                      AND next_meeting_at >= NOW() - INTERVAL '5 minutes'
                    """
                ),
                {"window_minutes": _EXEC_PREP_WINDOW_MINUTES},
            ).fetchall()
    except Exception as e:
        logger.error(f"[Scheduler] Failed to query exec meeting settings: {e}")
        return

    if not due_rows:
        return

    for row in due_rows:
        business_id = str(row[0])
        next_meeting_at = row[1]
        try:
            await _prep_one_executive_meeting(business_id, next_meeting_at)
        except Exception as e:
            logger.error(
                f"[Scheduler] Exec meeting prep failed for business {business_id}: {e}",
                exc_info=True,
            )


async def _prep_one_executive_meeting(business_id: str, scheduled_for) -> None:
    """Create-if-missing the meeting row, then run prep if it's still 'scheduled'."""
    import time as _time

    # Step 1: ensure a meeting row exists for this scheduled_for
    meeting_id = None
    current_status = None
    try:
        with get_session_transactional() as session:
            existing = session.execute(
                text(
                    """
                    SELECT id, status
                    FROM executive_meetings
                    WHERE business_id = :business_id
                      AND scheduled_for = :scheduled_for
                    LIMIT 1
                    """
                ),
                {"business_id": business_id, "scheduled_for": scheduled_for},
            ).fetchone()

            if existing:
                meeting_id = str(existing[0])
                current_status = existing[1]
            else:
                inserted = session.execute(
                    text(
                        """
                        INSERT INTO executive_meetings
                            (business_id, status, scheduled_for)
                        VALUES (:business_id, 'scheduled', :scheduled_for)
                        RETURNING id
                        """
                    ),
                    {"business_id": business_id, "scheduled_for": scheduled_for},
                ).fetchone()
                if inserted:
                    meeting_id = str(inserted[0])
                    current_status = "scheduled"
                    logger.info(
                        "[Scheduler] Created exec meeting row for business=%s scheduled=%s",
                        business_id, scheduled_for,
                    )
    except Exception as e:
        logger.error(f"[Scheduler] Failed to ensure exec meeting row: {e}")
        return

    if not meeting_id:
        return
    if current_status != "scheduled":
        # Already prepped (prep_ready), running, completed, etc — nothing to do.
        return

    # Step 2: run prep with a fresh read-only session
    started = _time.monotonic()
    try:
        from services.executive_meeting_prep import generate_prep_data

        with get_session_context() as session:
            prep_data = generate_prep_data(
                business_id=business_id,
                db_session=session,
                scheduled_for=scheduled_for,
            )
    except Exception as e:
        logger.error(f"[Scheduler] generate_prep_data failed for business {business_id}: {e}", exc_info=True)
        # Mark the meeting as failed so we don't keep re-trying every tick.
        try:
            with get_session_transactional() as session:
                session.execute(
                    text(
                        """
                        UPDATE executive_meetings
                        SET status = 'failed', updated_at = NOW()
                        WHERE id = :meeting_id
                        """
                    ),
                    {"meeting_id": meeting_id},
                )
        except Exception:
            logger.exception("[Scheduler] Failed to mark exec meeting as failed")
        return

    # Step 3: store prep_data + flip status to prep_ready
    duration_ms = int((_time.monotonic() - started) * 1000)
    try:
        with get_session_transactional() as session:
            session.execute(
                text(
                    """
                    UPDATE executive_meetings
                    SET prep_data = CAST(:prep_data AS jsonb),
                        prep_started_at = COALESCE(prep_started_at, NOW()),
                        status = 'prep_ready',
                        ai_model = :ai_model,
                        updated_at = NOW()
                    WHERE id = :meeting_id
                      AND status = 'scheduled'
                    """
                ),
                {
                    "meeting_id": meeting_id,
                    "prep_data": json.dumps(prep_data, default=str),
                    "ai_model": prep_data.get("ai_model"),
                },
            )
        logger.info(
            "[Scheduler] Exec meeting prep complete: business=%s meeting=%s in %dms",
            business_id, meeting_id, duration_ms,
        )
    except Exception as e:
        logger.error(f"[Scheduler] Failed to persist prep_data: {e}", exc_info=True)
