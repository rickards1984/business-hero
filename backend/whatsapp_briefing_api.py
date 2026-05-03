"""
WhatsApp CEO Briefing API — config, manual triggers, message history.
"""

import json
import logging
from datetime import date as date_cls, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlmodel import Session

from db import get_session
from auth import get_user_business_context, get_platform_admin_context

from services.briefing_data import gather_business_data
from services.briefing_generator import generate_daily_pulse, generate_weekly_briefing
from services.whatsapp_service import send_whatsapp_message

_logger = logging.getLogger("whatsapp_briefing")

router = APIRouter(prefix="/v1/whatsapp", tags=["WhatsApp Briefing"])
admin_router = APIRouter(prefix="/v1/admin/whatsapp", tags=["Admin WhatsApp"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# User endpoints
# ---------------------------------------------------------------------------


@router.get("/config")
async def get_whatsapp_config(
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """Get WhatsApp config for the current business"""
    business_id = str(auth_ctx["business_id"])
    row = session.execute(
        text("""
            SELECT id, business_id, phone_number, enabled, timezone, owner_name,
                   daily_pulse_enabled, daily_pulse_time,
                   weekly_briefing_enabled, weekly_briefing_day, weekly_briefing_time,
                   preferred_detail_level, created_at, updated_at,
                   COALESCE(task_reminder_enabled, false) as task_reminder_enabled,
                   COALESCE(task_reminder_frequency, 'daily') as task_reminder_frequency,
                   COALESCE(task_reminder_time, '08:00') as task_reminder_time
            FROM whatsapp_configs
            WHERE business_id = :business_id
        """),
        {"business_id": business_id},
    ).fetchone()

    if not row:
        return {"configured": False}

    return {
        "configured": True,
        "id": str(row[0]),
        "business_id": str(row[1]),
        "phone_number": row[2],
        "enabled": row[3],
        "timezone": row[4],
        "owner_name": row[5] or "",
        "daily_pulse_enabled": row[6],
        "daily_pulse_time": row[7],
        "weekly_briefing_enabled": row[8],
        "weekly_briefing_day": row[9],
        "weekly_briefing_time": row[10],
        "preferred_detail_level": row[11],
        "created_at": row[12].isoformat() if row[12] else None,
        "updated_at": row[13].isoformat() if row[13] else None,
        "task_reminder_enabled": bool(row[14]),
        "task_reminder_frequency": row[15] or "daily",
        "task_reminder_time": row[16] or "08:00",
    }


@router.put("/config")
async def upsert_whatsapp_config(
    config: dict[str, Any],
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """Create or update WhatsApp config"""
    business_id = str(auth_ctx["business_id"])
    now = datetime.utcnow().isoformat()
    phone = (config.get("phone_number") or "").replace(" ", "").strip()

    existing = session.execute(
        text("SELECT id FROM whatsapp_configs WHERE business_id = :business_id"),
        {"business_id": business_id},
    ).fetchone()

    cfg_params = {
        "business_id": business_id,
        "phone_number": phone,
        "enabled": config.get("enabled", True),
        "timezone": config.get("timezone", "Europe/London"),
        "owner_name": config.get("owner_name") or None,
        "daily_pulse_enabled": config.get("daily_pulse_enabled", False),
        "daily_pulse_time": config.get("daily_pulse_time", "07:30"),
        "weekly_briefing_enabled": config.get("weekly_briefing_enabled", False),
        "weekly_briefing_day": (config.get("weekly_briefing_day") or "monday").lower(),
        "weekly_briefing_time": config.get("weekly_briefing_time", "08:00"),
        "preferred_detail_level": config.get("preferred_detail_level", "standard"),
        "task_reminder_enabled": config.get("task_reminder_enabled", False),
        "task_reminder_frequency": config.get("task_reminder_frequency", "daily"),
        "task_reminder_time": config.get("task_reminder_time", "08:00"),
        "updated_at": now,
    }

    if existing:
        session.execute(
            text("""
                UPDATE whatsapp_configs SET
                    phone_number = :phone_number,
                    enabled = :enabled,
                    timezone = :timezone,
                    owner_name = :owner_name,
                    daily_pulse_enabled = :daily_pulse_enabled,
                    daily_pulse_time = :daily_pulse_time,
                    weekly_briefing_enabled = :weekly_briefing_enabled,
                    weekly_briefing_day = :weekly_briefing_day,
                    weekly_briefing_time = :weekly_briefing_time,
                    preferred_detail_level = :preferred_detail_level,
                    task_reminder_enabled = :task_reminder_enabled,
                    task_reminder_frequency = :task_reminder_frequency,
                    task_reminder_time = :task_reminder_time,
                    updated_at = :updated_at
                WHERE business_id = :business_id
            """),
            cfg_params,
        )
    else:
        session.execute(
            text("""
                INSERT INTO whatsapp_configs
                (business_id, phone_number, enabled, timezone, owner_name,
                 daily_pulse_enabled, daily_pulse_time,
                 weekly_briefing_enabled, weekly_briefing_day, weekly_briefing_time,
                 preferred_detail_level,
                 task_reminder_enabled, task_reminder_frequency, task_reminder_time,
                 updated_at)
                VALUES (:business_id, :phone_number, :enabled, :timezone, :owner_name,
                        :daily_pulse_enabled, :daily_pulse_time,
                        :weekly_briefing_enabled, :weekly_briefing_day, :weekly_briefing_time,
                        :preferred_detail_level,
                        :task_reminder_enabled, :task_reminder_frequency, :task_reminder_time,
                        :updated_at)
            """),
            cfg_params,
        )
    session.commit()

    row = session.execute(
        text("""
            SELECT id, phone_number, enabled, timezone, owner_name,
                   daily_pulse_enabled, daily_pulse_time,
                   weekly_briefing_enabled, weekly_briefing_day, weekly_briefing_time,
                   preferred_detail_level, updated_at,
                   COALESCE(task_reminder_enabled, false),
                   COALESCE(task_reminder_frequency, 'daily'),
                   COALESCE(task_reminder_time, '08:00')
            FROM whatsapp_configs
            WHERE business_id = :business_id
        """),
        {"business_id": business_id},
    ).fetchone()

    return {
        "id": str(row[0]),
        "phone_number": row[1],
        "enabled": row[2],
        "timezone": row[3],
        "owner_name": row[4] or "",
        "daily_pulse_enabled": row[5],
        "daily_pulse_time": row[6],
        "weekly_briefing_enabled": row[7],
        "weekly_briefing_day": row[8],
        "weekly_briefing_time": row[9],
        "preferred_detail_level": row[10],
        "updated_at": row[11].isoformat() if row[11] else None,
        "task_reminder_enabled": bool(row[12]),
        "task_reminder_frequency": row[13] or "daily",
        "task_reminder_time": row[14] or "08:00",
    }


# ---------------------------------------------------------------------------
# Manual trigger endpoints (for testing)
# ---------------------------------------------------------------------------


@router.post("/send-daily-pulse")
async def trigger_daily_pulse(
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """Manually trigger a daily pulse (for testing)"""
    business_id = str(auth_ctx["business_id"])

    config_row = session.execute(
        text("""
            SELECT phone_number, owner_name, preferred_detail_level
            FROM whatsapp_configs
            WHERE business_id = :business_id
        """),
        {"business_id": business_id},
    ).fetchone()

    if not config_row:
        raise HTTPException(status_code=404, detail="WhatsApp not configured")

    biz_row = session.execute(
        text("SELECT name FROM businesses WHERE id = :bid"),
        {"bid": business_id},
    ).fetchone()
    business_name = biz_row[0] if biz_row else "Your Business"

    data = await gather_business_data(session, business_id, period="yesterday")

    calls = data.get("calls", {})
    emails = data.get("emails", {})
    tasks = data.get("tasks", {})
    financial = data.get("financial", {})
    invoices_data = data.get("invoices", {})

    calls_summary = (
        f"{calls.get('total', 0)} calls yesterday. "
        f"{calls.get('handled_by_ai', 0)} handled by AI receptionist, "
        f"{calls.get('transferred', 0)} transferred."
    )
    emails_summary = (
        f"{emails.get('total_received', 0)} new emails. "
        f"{emails.get('action_required', 0)} action required, "
        f"{emails.get('awaiting_reply', 0)} awaiting reply."
    )
    tasks_summary = (
        f"{tasks.get('open_total', 0)} open tasks. "
        f"{tasks.get('open_high_priority', 0)} high priority, "
        f"{tasks.get('pending', 0)} pending."
    )
    snapshot = (
        f"Revenue: £{financial.get('revenue', 0):,.2f}. "
        f"Expenses: £{financial.get('expenses', 0):,.2f}. "
        f"Net: £{financial.get('net_profit', 0):,.2f}. "
        f"{invoices_data.get('overdue_count', 0)} overdue invoices "
        f"(£{invoices_data.get('overdue_total', 0):,.2f})."
    )

    sid = await send_whatsapp_message(
        to_number=config_row[0],
        body=json.dumps({
            "1": business_name,
            "2": calls_summary[:500],
            "3": emails_summary[:500],
            "4": tasks_summary[:500],
            "5": snapshot[:500],
        }),
        business_id=business_id,
        message_type="daily_pulse",
    )

    return {"sent": bool(sid), "message_sid": sid}


@router.post("/send-weekly-briefing")
async def trigger_weekly_briefing(
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """Manually trigger a weekly CEO briefing (for testing)"""
    business_id = str(auth_ctx["business_id"])

    config_row = session.execute(
        text("""
            SELECT phone_number, owner_name, preferred_detail_level
            FROM whatsapp_configs
            WHERE business_id = :business_id
        """),
        {"business_id": business_id},
    ).fetchone()

    if not config_row:
        raise HTTPException(status_code=404, detail="WhatsApp not configured")

    biz_row = session.execute(
        text("SELECT name FROM businesses WHERE id = :bid"),
        {"bid": business_id},
    ).fetchone()
    business_name = biz_row[0] if biz_row else "Your Business"

    data = await gather_business_data(
        session, business_id, period="week", include_previous=True
    )

    week_ending = date_cls.today().strftime("%-d %B %Y")

    calls = data.get("calls", {})
    emails = data.get("emails", {})
    tasks = data.get("tasks", {})
    financial = data.get("financial", {})
    invoices_data = data.get("invoices", {})

    calls_summary = (
        f"{calls.get('total', 0)} calls this week. "
        f"{calls.get('handled_by_ai', 0)} handled by AI receptionist"
        f" ({calls.get('ai_resolution_rate', 0)}% resolution rate), "
        f"{calls.get('transferred', 0)} transferred, "
        f"{calls.get('voicemail', 0)} voicemail."
    )
    emails_summary = (
        f"{emails.get('total_received', 0)} received. "
        f"{emails.get('action_required', 0)} action required, "
        f"{emails.get('awaiting_reply', 0)} awaiting reply, "
        f"{emails.get('newsletters', 0)} newsletters filtered."
    )
    tasks_summary = (
        f"{tasks.get('created_this_period', 0)} created, "
        f"{tasks.get('completed_this_period', 0)} completed, "
        f"{tasks.get('open_high_priority', 0)} high priority open."
    )
    financial_summary = (
        f"Revenue: £{financial.get('revenue', 0):,.2f}. "
        f"Expenses: £{financial.get('expenses', 0):,.2f}. "
        f"Net profit: £{financial.get('net_profit', 0):,.2f}."
    )
    invoices_summary = (
        f"{invoices_data.get('unpaid_count', 0)} unpaid "
        f"(£{invoices_data.get('unpaid_total', 0):,.2f}). "
        f"{invoices_data.get('overdue_count', 0)} overdue "
        f"(£{invoices_data.get('overdue_total', 0):,.2f})."
    )

    sid = await send_whatsapp_message(
        to_number=config_row[0],
        body=json.dumps({
            "1": business_name,
            "2": week_ending,
            "3": calls_summary[:500],
            "4": emails_summary[:500],
            "5": tasks_summary[:500],
            "6": financial_summary[:500],
            "7": invoices_summary[:500],
        }),
        business_id=business_id,
        message_type="weekly_briefing",
    )

    return {
        "sent": bool(sid),
        "message_sid": sid,
    }


@router.post("/send-task-reminder")
async def trigger_task_reminder(
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """Manually trigger a task reminder (for testing)"""
    business_id = str(auth_ctx["business_id"])

    config_row = session.execute(
        text("""
            SELECT phone_number
            FROM whatsapp_configs
            WHERE business_id = :business_id AND enabled = true
        """),
        {"business_id": business_id},
    ).fetchone()

    if not config_row or not config_row[0]:
        raise HTTPException(status_code=400, detail="WhatsApp not configured")

    biz_row = session.execute(
        text("SELECT name FROM businesses WHERE id = :bid"),
        {"bid": business_id},
    ).fetchone()

    from services.briefing_scheduler import _send_task_reminder
    await _send_task_reminder(
        business_id=business_id,
        phone=config_row[0],
        business_name=biz_row[0] if biz_row else "Your Business",
    )

    return {"status": "sent"}


# ---------------------------------------------------------------------------
# WhatsApp message history
# ---------------------------------------------------------------------------


@router.get("/messages")
async def get_whatsapp_messages(
    limit: int = 50,
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """Get WhatsApp message history"""
    business_id = str(auth_ctx["business_id"])

    rows = session.execute(
        text("""
            SELECT id, direction, message_type, phone_number, content,
                   twilio_message_sid, twilio_status, related_entity_type,
                   related_entity_id, created_at
            FROM whatsapp_messages
            WHERE business_id = :business_id
            ORDER BY created_at DESC
            LIMIT :limit
        """),
        {"business_id": business_id, "limit": limit},
    ).fetchall()

    return [
        {
            "id": str(r[0]),
            "direction": r[1],
            "message_type": r[2],
            "phone_number": r[3],
            "content": r[4],
            "twilio_message_sid": r[5],
            "twilio_status": r[6],
            "related_entity_type": r[7],
            "related_entity_id": str(r[8]) if r[8] else None,
            "created_at": r[9].isoformat() if r[9] else None,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Inbound WhatsApp webhook (Twilio – no auth)
# ---------------------------------------------------------------------------


@router.post("/webhook")
async def whatsapp_webhook(request: Request):
    """
    Twilio webhook for incoming WhatsApp messages.
    Handles numbered replies to take action from briefings/alerts.
    """
    try:
        form_data = await request.form()
        from_number = form_data.get("From", "").replace("whatsapp:", "").strip()
        body = form_data.get("Body", "").strip()
        message_sid = form_data.get("MessageSid", "")

        _logger.info(f"[WhatsApp Webhook] Received from {from_number}: {body[:80]}")

        from db import get_session_context, get_session_transactional

        with get_session_context() as session:
            config_row = session.execute(
                text("""
                    SELECT business_id, phone_number, owner_name
                    FROM whatsapp_configs
                    WHERE phone_number = :phone AND enabled = true
                """),
                {"phone": from_number},
            ).fetchone()

        if not config_row:
            _logger.warning(f"[WhatsApp Webhook] No config found for number: {from_number}")
            return Response(content="", status_code=200)

        business_id = str(config_row[0])
        owner_name = config_row[2] or ""

        # Log the inbound message
        try:
            from services.whatsapp_service import log_whatsapp_message
            log_whatsapp_message(
                business_id=business_id,
                direction="inbound",
                message_type="user_reply",
                phone_number=from_number,
                content=body[:5000],
                twilio_message_sid=message_sid,
                twilio_status="received",
            )
        except Exception as e:
            _logger.warning(f"[WhatsApp Webhook] Failed to log inbound message: {e}")

        reply_text = body.strip()
        action_number = None
        if reply_text.isdigit():
            action_number = int(reply_text)
        elif reply_text.lower() in ("one", "1️⃣"):
            action_number = 1
        elif reply_text.lower() in ("two", "2️⃣"):
            action_number = 2
        elif reply_text.lower() in ("three", "3️⃣"):
            action_number = 3
        elif reply_text.lower() in ("four", "4️⃣"):
            action_number = 4
        elif reply_text.lower() in ("five", "5️⃣"):
            action_number = 5

        if action_number:
            with get_session_context() as session:
                action_row = session.execute(
                    text("""
                        SELECT id, action_type, action_config
                        FROM whatsapp_pending_actions
                        WHERE business_id = :business_id
                          AND action_number = :action_number
                          AND (status IS NULL OR status = 'pending')
                        ORDER BY created_at DESC
                        LIMIT 1
                    """),
                    {"business_id": business_id, "action_number": action_number},
                ).fetchone()

            if action_row:
                action = {
                    "id": str(action_row[0]),
                    "action_type": action_row[1],
                    "action_config": action_row[2] or {},
                }
                if isinstance(action["action_config"], str):
                    import json
                    try:
                        action["action_config"] = json.loads(action["action_config"])
                    except Exception:
                        action["action_config"] = {}

                await _execute_whatsapp_action(
                    action, business_id, from_number, owner_name
                )

                with get_session_transactional() as session:
                    session.execute(
                        text("""
                            UPDATE whatsapp_pending_actions
                            SET status = 'executed', executed_at = :now
                            WHERE id = :action_id
                        """),
                        {
                            "action_id": action["id"],
                            "now": datetime.utcnow().isoformat(),
                        },
                    )
            else:
                await send_whatsapp_message(
                    to_number=from_number,
                    body=f"Sorry, I don't have an active action for option {action_number}. Actions expire after 24 hours. You can trigger a new briefing from your Business Hero dashboard.",
                    business_id=business_id,
                    message_type="action_confirmation",
                )
        else:
            await send_whatsapp_message(
                to_number=from_number,
                body="Thanks for your message! To take a quick action, reply with a number (1, 2, 3...) from your last briefing. For anything else, head to your Business Hero dashboard.",
                business_id=business_id,
                message_type="action_confirmation",
            )

        return Response(content="", status_code=200)

    except Exception as exc:
        _logger.exception(
            "[WhatsApp Webhook] Unhandled exception — returning 200 "
            "to Twilio to prevent retry. Investigate immediately."
        )
        return Response(content="", status_code=200)


async def _execute_whatsapp_action(
    action: dict, business_id: str, phone: str, owner_name: str
) -> None:
    """Execute a pending WhatsApp action"""
    action_type = action.get("action_type", "")
    action_config = action.get("action_config", {})

    _logger.info(f"[WhatsApp Action] Executing {action_type} for {business_id}")

    if action_type == "send_chase":
        invoice_id = action_config.get("invoice_id")
        stage = action_config.get("stage", 1)
        if invoice_id:
            try:
                from services.invoice_chase_helper import send_chase_for_invoice
                success, _ = send_chase_for_invoice(business_id, invoice_id, stage)
                if success:
                    await send_whatsapp_message(
                        to_number=phone,
                        body=f"✅ Chase reminder (Stage {stage}) sent for the invoice. You can check the status in your Invoices tab.",
                        business_id=business_id,
                        message_type="action_confirmation",
                    )
                else:
                    raise ValueError("Chase failed")
            except Exception as e:
                _logger.warning(f"[WhatsApp Action] Chase failed: {e}")
                await send_whatsapp_message(
                    to_number=phone,
                    body="⚠️ Couldn't send the chase email automatically. Please send it manually from the Invoices tab in your dashboard.",
                    business_id=business_id,
                    message_type="action_confirmation",
                )

    elif action_type == "show_breakdown":
        from db import get_session_context
        with get_session_context() as session:
            data = await gather_business_data(session, business_id, period="week")
        financial = data.get("financial", {})
        invoices = data.get("invoices", {})
        breakdown = (
            f"💰 Financial Breakdown\n\n"
            f"Revenue: £{financial.get('revenue', 0):.2f}\n"
            f"Expenses: £{financial.get('expenses', 0):.2f}\n"
            f"Net Profit: £{financial.get('net_profit', 0):.2f}\n\n"
            f"📋 Invoices:\n"
            f"Unpaid: {invoices.get('unpaid_count', 0)} (£{invoices.get('unpaid_total', 0):.2f})\n"
            f"Overdue: {invoices.get('overdue_count', 0)} (£{invoices.get('overdue_total', 0):.2f})\n"
        )
        for inv in invoices.get("overdue_details", [])[:5]:
            breakdown += f"\n  • {inv.get('contact', 'Unknown')}: £{inv.get('amount', 0):.2f} ({inv.get('days_overdue', 0)}d overdue)"
        await send_whatsapp_message(
            to_number=phone,
            body=breakdown,
            business_id=business_id,
            message_type="action_confirmation",
            related_entity_type="financial",
        )

    elif action_type == "show_tasks":
        from db import get_session_context
        with get_session_context() as session:
            rows = session.execute(
                text("""
                    SELECT title, priority, category, status
                    FROM tasks
                    WHERE business_id = :business_id
                      AND status = 'open'
                      AND deleted_at IS NULL
                    ORDER BY CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END
                    LIMIT 10
                """),
                {"business_id": business_id},
            ).fetchall()
        if rows:
            task_list = "✅ Open Tasks:\n\n"
            for r in rows:
                icon = "🔴" if r[1] == "high" else "🟡" if r[1] == "medium" else "⚪"
                task_list += f"{icon} {r[0]}\n"
            task_list += f"\nTotal: {len(rows)} open tasks"
        else:
            task_list = "✅ No open tasks — you're all caught up!"
        await send_whatsapp_message(
            to_number=phone,
            body=task_list,
            business_id=business_id,
            message_type="action_confirmation",
            related_entity_type="task",
        )

    elif action_type == "draft_email_replies":
        await send_whatsapp_message(
            to_number=phone,
            body="📧 Your emails needing replies are ready in the Emails tab of your dashboard. Aria can help draft responses — click 'Ask Aria' next to any email.",
            business_id=business_id,
            message_type="action_confirmation",
        )

    elif action_type == "add_to_kb":
        topic = action_config.get("topic", "")
        await send_whatsapp_message(
            to_number=phone,
            body=f'📚 To add information about "{topic}" to your receptionist\'s knowledge base, go to the Receptionist tab → Knowledge Base section in your dashboard.\n\nThe AI will use this to answer future caller questions about this topic.',
            business_id=business_id,
            message_type="action_confirmation",
        )

    elif action_type == "approve_automation":
        execution_id = action_config.get("execution_id")
        if execution_id:
            from services.automation_engine import _do_execute_action
            from db import get_session_context
            import json

            action_type_to_run = action_config.get("action_type", "")
            action_config_to_run = action_config.get("action_config", {})
            if isinstance(action_config_to_run, str):
                try:
                    action_config_to_run = json.loads(action_config_to_run)
                except Exception:
                    action_config_to_run = {}

            await _do_execute_action(
                action_type_to_run,
                action_config_to_run,
                business_id,
                execution_id,
                None,
            )
        await send_whatsapp_message(
            to_number=phone,
            body="✅ Automation approved and executed. Check your dashboard for details.",
            business_id=business_id,
            message_type="action_confirmation",
        )

    elif action_type == "reject_automation":
        execution_id = action_config.get("execution_id")
        if execution_id:
            from db import get_session_transactional

            with get_session_transactional() as session:
                session.execute(
                    text("""
                        UPDATE automation_executions
                        SET status = 'rejected', executed_at = :now
                        WHERE id = :execution_id AND business_id = :business_id
                    """),
                    {
                        "execution_id": execution_id,
                        "business_id": business_id,
                        "now": datetime.utcnow().isoformat(),
                    },
                )
        await send_whatsapp_message(
            to_number=phone,
            body="👍 Automation skipped as requested.",
            business_id=business_id,
            message_type="action_confirmation",
        )

    else:
        await send_whatsapp_message(
            to_number=phone,
            body="👍 Got it! Head to your Business Hero dashboard for full details.",
            business_id=business_id,
            message_type="action_confirmation",
        )


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


@admin_router.get("/overview")
async def admin_whatsapp_overview(
    auth_ctx: dict = Depends(get_platform_admin_context),
    session: Session = Depends(get_session),
):
    """Admin: overview of all WhatsApp configurations"""
    rows = session.execute(
        text("""
            SELECT wc.id, wc.business_id, wc.phone_number, wc.enabled,
                   wc.timezone, wc.owner_name, wc.daily_pulse_enabled,
                   wc.weekly_briefing_enabled, wc.created_at, b.name, b.plan_tier
            FROM whatsapp_configs wc
            LEFT JOIN businesses b ON wc.business_id = b.id
            ORDER BY wc.created_at DESC
        """)
    ).fetchall()

    return [
        {
            "id": str(r[0]),
            "business_id": str(r[1]),
            "phone_number": r[2],
            "enabled": r[3],
            "timezone": r[4],
            "owner_name": r[5] or "",
            "daily_pulse_enabled": r[6],
            "weekly_briefing_enabled": r[7],
            "created_at": r[8].isoformat() if r[8] else None,
            "business_name": r[9] or "",
            "plan_tier": r[10] or "",
        }
        for r in rows
    ]


@admin_router.put("/{business_id}/config")
async def admin_update_whatsapp_config(
    business_id: str,
    config: dict[str, Any],
    auth_ctx: dict = Depends(get_platform_admin_context),
    session: Session = Depends(get_session),
):
    """Admin: create or update WhatsApp config for any business"""
    now = datetime.utcnow().isoformat()
    phone = (config.get("phone_number") or "").replace(" ", "").strip()

    existing = session.execute(
        text("SELECT id FROM whatsapp_configs WHERE business_id = :business_id"),
        {"business_id": business_id},
    ).fetchone()

    cfg = {
        "business_id": business_id,
        "phone_number": phone,
        "enabled": config.get("enabled", True),
        "timezone": config.get("timezone", "Europe/London"),
        "owner_name": config.get("owner_name") or None,
        "daily_pulse_enabled": config.get("daily_pulse_enabled", False),
        "daily_pulse_time": config.get("daily_pulse_time", "07:30"),
        "weekly_briefing_enabled": config.get("weekly_briefing_enabled", False),
        "weekly_briefing_day": (config.get("weekly_briefing_day") or "monday").lower(),
        "weekly_briefing_time": config.get("weekly_briefing_time", "08:00"),
        "preferred_detail_level": config.get("preferred_detail_level", "standard"),
        "updated_at": now,
    }

    if existing:
        session.execute(
            text("""
                UPDATE whatsapp_configs SET
                    phone_number = :phone_number,
                    enabled = :enabled,
                    timezone = :timezone,
                    owner_name = :owner_name,
                    daily_pulse_enabled = :daily_pulse_enabled,
                    daily_pulse_time = :daily_pulse_time,
                    weekly_briefing_enabled = :weekly_briefing_enabled,
                    weekly_briefing_day = :weekly_briefing_day,
                    weekly_briefing_time = :weekly_briefing_time,
                    preferred_detail_level = :preferred_detail_level,
                    updated_at = :updated_at
                WHERE business_id = :business_id
            """),
            cfg,
        )
    else:
        session.execute(
            text("""
                INSERT INTO whatsapp_configs
                (business_id, phone_number, enabled, timezone, owner_name,
                 daily_pulse_enabled, daily_pulse_time,
                 weekly_briefing_enabled, weekly_briefing_day, weekly_briefing_time,
                 preferred_detail_level, updated_at)
                VALUES (:business_id, :phone_number, :enabled, :timezone, :owner_name,
                        :daily_pulse_enabled, :daily_pulse_time,
                        :weekly_briefing_enabled, :weekly_briefing_day, :weekly_briefing_time,
                        :preferred_detail_level, :updated_at)
            """),
            cfg,
        )
    session.commit()

    row = session.execute(
        text("""
            SELECT id, phone_number, enabled, timezone, owner_name,
                   daily_pulse_enabled, daily_pulse_time,
                   weekly_briefing_enabled, weekly_briefing_day, weekly_briefing_time,
                   preferred_detail_level, updated_at
            FROM whatsapp_configs
            WHERE business_id = :business_id
        """),
        {"business_id": business_id},
    ).fetchone()

    return {
        "id": str(row[0]),
        "phone_number": row[1],
        "enabled": row[2],
        "timezone": row[3],
        "owner_name": row[4] or "",
        "daily_pulse_enabled": row[5],
        "daily_pulse_time": row[6],
        "weekly_briefing_enabled": row[7],
        "weekly_briefing_day": row[8],
        "weekly_briefing_time": row[9],
        "preferred_detail_level": row[10],
        "updated_at": row[11].isoformat() if row[11] else None,
    }
