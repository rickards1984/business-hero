"""
Real-time alert dispatcher.
Called by other parts of the app when alert-worthy events happen.
"""

import logging
from typing import Optional, Dict, Any

from sqlalchemy import text

from db import get_session_context

logger = logging.getLogger(__name__)


async def dispatch_alert(
    business_id: str,
    alert_type: str,
    alert_data: Dict[str, Any],
) -> bool:
    """
    Send a real-time WhatsApp alert if the business has alerts enabled for this type.

    Call this from anywhere in the app when an alert-worthy event occurs.
    Returns True if alert was sent, False if skipped.
    """
    with get_session_context() as session:
        cfg_row = session.execute(
            text("""
                SELECT phone_number, enabled, real_time_alerts_enabled,
                       alert_invoice_overdue_days, alert_bank_balance_threshold,
                       alert_urgent_emails, alert_receptionist_transfers,
                       alert_payment_received_threshold
                FROM whatsapp_configs
                WHERE business_id = :business_id AND enabled = true
            """),
            {"business_id": business_id},
        ).fetchone()

    if not cfg_row or not cfg_row[2]:  # real_time_alerts_enabled
        return False

    phone = cfg_row[0]

    # Build config dict from row (phone, enabled, real_time_alerts, overdue_days,
    # balance_threshold, urgent_emails, receptionist_transfers, payment_threshold)
    config = {
        "phone_number": cfg_row[0],
        "enabled": cfg_row[1],
        "real_time_alerts_enabled": cfg_row[2],
        "alert_invoice_overdue_days": cfg_row[3],
        "alert_bank_balance_threshold": cfg_row[4],
        "alert_urgent_emails": cfg_row[5],
        "alert_receptionist_transfers": cfg_row[6],
        "alert_payment_received_threshold": cfg_row[7],
    }

    should_send = False

    if alert_type == "call_transferred" and config.get("alert_receptionist_transfers"):
        should_send = True
    elif alert_type == "payment_received":
        threshold = float(config.get("alert_payment_received_threshold") or 100)
        if float(alert_data.get("amount", 0)) >= threshold:
            should_send = True
    elif alert_type == "low_balance":
        threshold = config.get("alert_bank_balance_threshold")
        if threshold is not None and float(alert_data.get("balance", 0)) < float(threshold):
            should_send = True
    elif alert_type == "invoice_overdue":
        should_send = True
    elif alert_type == "urgent_email" and config.get("alert_urgent_emails"):
        should_send = True
    elif alert_type == "kb_gap":
        should_send = True

    if not should_send:
        return False

    from services.briefing_generator import generate_alert_message
    from services.whatsapp_service import send_whatsapp_message, get_business_name

    alert_content = generate_alert_message(alert_type, "", alert_data)

    # Build the 3-variable structure for the `alert` template.
    # {{1}} business name, {{2}} alert content, {{3}} action options.
    business_name = get_business_name(business_id)
    action_option = alert_data.get("action_option") or {}
    action_label = action_option.get("label") if isinstance(action_option, dict) else None
    if action_label:
        action_options = f"Reply 1️⃣ to {action_label}"
    else:
        # Template requires a non-empty {{3}} — provide a generic fallback so
        # the variable validator doesn't block legitimate informational alerts.
        action_options = "View details in your Business Hero dashboard"

    import json as _json
    sid = await send_whatsapp_message(
        to_number=phone,
        body=_json.dumps({
            "1": business_name,
            "2": alert_content,
            "3": action_options,
        }),
        business_id=business_id,
        message_type="alert",
        related_entity_type=alert_data.get("entity_type"),
        related_entity_id=alert_data.get("entity_id"),
    )

    # If the alert includes an action option, create a pending action
    if alert_data.get("action_option") and sid:
        try:
            with get_session_context() as session:
                msg_row = session.execute(
                    text("""
                        SELECT id FROM whatsapp_messages
                        WHERE twilio_message_sid = :sid
                        LIMIT 1
                    """),
                    {"sid": sid},
                ).fetchone()

                if msg_row:
                    action_opt = alert_data["action_option"]
                    session.execute(
                        text("""
                            INSERT INTO whatsapp_pending_actions
                            (business_id, source_message_id, action_number, action_label,
                             action_type, action_config, status)
                            VALUES (:business_id, :source_msg_id, 1, :label,
                                    :action_type, CAST(:config AS jsonb), 'pending')
                        """),
                        {
                            "business_id": business_id,
                            "source_msg_id": str(msg_row[0]),
                            "label": action_opt.get("label", ""),
                            "action_type": action_opt.get("type", ""),
                            "config": str(action_opt.get("config", {})),
                        },
                    )
                    session.commit()
        except Exception as e:
            logger.warning(f"[Alert] Failed to create pending action: {e}")

    return bool(sid)
