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

from db import get_session_context

logger = logging.getLogger(__name__)

_scheduler_running = False


async def start_briefing_scheduler():
    """Start the background scheduler. Call this on app startup."""
    global _scheduler_running
    if _scheduler_running:
        return
    _scheduler_running = True

    logger.info("[Scheduler] Starting CEO briefing scheduler")
    asyncio.create_task(_scheduler_loop())


async def _scheduler_loop():
    """Main scheduler loop — runs every 60 seconds"""
    while True:
        try:
            await _check_and_send_scheduled_messages()
        except Exception as e:
            logger.error(f"[Scheduler] Error in scheduler loop: {e}")

        await asyncio.sleep(60)


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
                       COALESCE(wc.real_time_alerts_enabled, false) as real_time_alerts_enabled
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
            }

            tz = pytz.timezone(config["timezone"])
            now_local = now_utc.astimezone(tz)
            current_time = now_local.strftime("%H:%M")
            current_day = now_local.strftime("%A").lower()

            business_id = config["business_id"]
            phone = config["phone_number"]
            business_name = config["business_name"]
            owner_name = config["owner_name"]
            detail_level = config["preferred_detail_level"]

            # Check daily pulse
            if (
                config["daily_pulse_enabled"]
                and current_time == config["daily_pulse_time"]
            ):
                already_sent = await _was_sent_today(
                    business_id, "daily_pulse", now_local.date()
                )
                if not already_sent:
                    logger.info(f"[Scheduler] Sending daily pulse to {business_name}")
                    await _send_daily_pulse(
                        business_id, phone, business_name, owner_name, detail_level
                    )

            # Check weekly briefing
            if (
                config["weekly_briefing_enabled"]
                and current_day == config["weekly_briefing_day"]
                and current_time == config["weekly_briefing_time"]
            ):
                already_sent = await _was_sent_today(
                    business_id, "weekly_briefing", now_local.date()
                )
                if not already_sent:
                    logger.info(
                        f"[Scheduler] Sending weekly briefing to {business_name}"
                    )
                    await _send_weekly_briefing(
                        business_id, phone, business_name, owner_name, detail_level
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


async def _send_daily_pulse(
    business_id: str,
    phone: str,
    business_name: str,
    owner_name: str,
    detail_level: str,
):
    """Generate and send the daily pulse"""
    from services.briefing_data import gather_business_data
    from services.briefing_generator import generate_daily_pulse
    from services.whatsapp_service import send_whatsapp_message

    with get_session_context() as session:
        data = await gather_business_data(session, business_id, period="day")
    pulse_text = await generate_daily_pulse(business_name, owner_name, data)

    await send_whatsapp_message(
        to_number=phone,
        body=pulse_text,
        business_id=business_id,
        message_type="daily_pulse",
    )

    # Save snapshot
    try:
        with get_session_context() as session:
            financial = data.get("financial", {})
            calls = data.get("calls", {})
            emails = data.get("emails", {})
            tasks = data.get("tasks", {})
            invoices = data.get("invoices", {})
            today = date.today()
            session.execute(
                text("""
                    INSERT INTO briefing_snapshots
                    (business_id, snapshot_type, period_start, period_end,
                     revenue, expenses, net_profit, calls_total, calls_handled_by_ai,
                     emails_received, emails_action_required, tasks_created, tasks_completed,
                     invoices_overdue_count, invoices_overdue_amount, full_data)
                    VALUES (:business_id, 'daily', :period_start, :period_end,
                            :revenue, :expenses, :net_profit, :calls_total, :calls_handled,
                            :emails_received, :emails_action, :tasks_created, :tasks_completed,
                            :invoices_overdue_count, :invoices_overdue_amount, :full_data)
                """),
                {
                    "business_id": business_id,
                    "period_start": today.isoformat(),
                    "period_end": today.isoformat(),
                    "revenue": financial.get("revenue", 0),
                    "expenses": financial.get("expenses", 0),
                    "net_profit": financial.get("net_profit", 0),
                    "calls_total": calls.get("total", 0),
                    "calls_handled": calls.get("handled_by_ai", 0),
                    "emails_received": emails.get("total_received", 0),
                    "emails_action": emails.get("action_required", 0),
                    "tasks_created": tasks.get("created_this_period", 0),
                    "tasks_completed": tasks.get("completed_this_period", 0),
                    "invoices_overdue_count": invoices.get("overdue_count", 0),
                    "invoices_overdue_amount": invoices.get("overdue_total", 0),
                    "full_data": json.loads(json.dumps(data, default=str)) if data else None,
                },
            )
            session.commit()
    except Exception as e:
        logger.warning(f"[Scheduler] Failed to save daily snapshot: {e}")


async def _send_weekly_briefing(
    business_id: str,
    phone: str,
    business_name: str,
    owner_name: str,
    detail_level: str,
):
    """Generate and send the weekly CEO briefing"""
    from services.briefing_data import gather_business_data
    from services.briefing_generator import generate_weekly_briefing
    from services.whatsapp_service import send_whatsapp_message

    with get_session_context() as session:
        data = await gather_business_data(
            session, business_id, period="week", include_previous=True
        )
    briefing_text, action_options, ai_analysis = await generate_weekly_briefing(
        business_name, owner_name, data, detail_level
    )

    msg_sid = await send_whatsapp_message(
        to_number=phone,
        body=briefing_text,
        business_id=business_id,
        message_type="weekly_briefing",
    )

    # Store action options for two-way interaction
    if action_options and msg_sid:
        try:
            with get_session_context() as session:
                msg_row = session.execute(
                    text("""
                        SELECT id FROM whatsapp_messages
                        WHERE twilio_message_sid = :sid
                        LIMIT 1
                    """),
                    {"sid": msg_sid},
                ).fetchone()
                msg_id = str(msg_row[0]) if msg_row else None

                for option in action_options:
                    session.execute(
                        text("""
                            INSERT INTO whatsapp_pending_actions
                            (business_id, source_message_id, action_number, action_label, action_type, action_config)
                            VALUES (:business_id, :source_message_id, :action_number, :action_label, :action_type, :action_config)
                        """),
                        {
                            "business_id": business_id,
                            "source_message_id": msg_id,
                            "action_number": option.get("number", 0),
                            "action_label": option.get("label", ""),
                            "action_type": option.get("type", ""),
                            "action_config": option.get("config") or {},
                        },
                    )
                session.commit()
        except Exception as e:
            logger.warning(f"[Scheduler] Failed to save pending action: {e}")

    # Save weekly snapshot
    try:
        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        financial = data.get("financial", {})
        calls = data.get("calls", {})
        emails = data.get("emails", {})
        tasks = data.get("tasks", {})
        invoices = data.get("invoices", {})

        import json

        with get_session_context() as session:
            session.execute(
                text("""
                    INSERT INTO briefing_snapshots
                    (business_id, snapshot_type, period_start, period_end,
                     revenue, expenses, net_profit, calls_total, calls_handled_by_ai,
                     emails_received, emails_action_required, tasks_created, tasks_completed,
                     invoices_overdue_count, invoices_overdue_amount,
                     ai_summary, ai_observations, ai_suggestions, full_data)
                    VALUES (:business_id, 'weekly', :period_start, :period_end,
                            :revenue, :expenses, :net_profit, :calls_total, :calls_handled,
                            :emails_received, :emails_action, :tasks_created, :tasks_completed,
                            :invoices_overdue_count, :invoices_overdue_amount,
                            :ai_summary, :ai_observations, :ai_suggestions, :full_data)
                """),
                {
                    "business_id": business_id,
                    "period_start": week_start.isoformat(),
                    "period_end": today.isoformat(),
                    "revenue": financial.get("revenue", 0),
                    "expenses": financial.get("expenses", 0),
                    "net_profit": financial.get("net_profit", 0),
                    "calls_total": calls.get("total", 0),
                    "calls_handled": calls.get("handled_by_ai", 0),
                    "emails_received": emails.get("total_received", 0),
                    "emails_action": emails.get("action_required", 0),
                    "tasks_created": tasks.get("created_this_period", 0),
                    "tasks_completed": tasks.get("completed_this_period", 0),
                    "invoices_overdue_count": invoices.get("overdue_count", 0),
                    "invoices_overdue_amount": invoices.get("overdue_total", 0),
                    "ai_summary": briefing_text[:5000] if briefing_text else None,
                    "ai_observations": ai_analysis.get("observations", []),
                    "ai_suggestions": ai_analysis.get("suggestions", []),
                    "full_data": json.loads(json.dumps(data, default=str)) if data else None,
                },
            )
            session.commit()
    except Exception as e:
        logger.warning(f"[Scheduler] Failed to save weekly snapshot: {e}")
