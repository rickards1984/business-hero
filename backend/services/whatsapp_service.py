"""
WhatsApp messaging service using Twilio.
Handles all outbound WhatsApp messages for CEO briefings, alerts, and notifications.
"""

import os
import json
import logging
from typing import Optional, List
from twilio.rest import Client

logger = logging.getLogger(__name__)

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")

# Content Template SIDs for scheduled messages (bypass 24hr window)
TWILIO_DAILY_PULSE_CONTENT_SID = os.getenv("TWILIO_DAILY_PULSE_CONTENT_SID", "")
TWILIO_WEEKLY_BRIEFING_CONTENT_SID = os.getenv("TWILIO_WEEKLY_BRIEFING_CONTENT_SID", "")
TWILIO_ALERT_CONTENT_SID = os.getenv("TWILIO_ALERT_CONTENT_SID", "")
TWILIO_ACTION_CONFIRMATION_CONTENT_SID = os.getenv("TWILIO_ACTION_CONFIRMATION_CONTENT_SID", "")
TWILIO_AUTOMATION_REPORT_CONTENT_SID = os.getenv("TWILIO_AUTOMATION_REPORT_CONTENT_SID", "")
TWILIO_TASK_REMINDER_CONTENT_SID = os.getenv("TWILIO_TASK_REMINDER_CONTENT_SID", "")

TEMPLATE_SID_MAP = {
    "daily_pulse": TWILIO_DAILY_PULSE_CONTENT_SID,
    "weekly_briefing": TWILIO_WEEKLY_BRIEFING_CONTENT_SID,
    "alert": TWILIO_ALERT_CONTENT_SID,
    "action_confirmation": TWILIO_ACTION_CONFIRMATION_CONTENT_SID,
    "automation_report": TWILIO_AUTOMATION_REPORT_CONTENT_SID,
    "task_reminder": TWILIO_TASK_REMINDER_CONTENT_SID,
}

# Initialize Twilio client
_twilio_client = None

def get_twilio_client():
    global _twilio_client
    if _twilio_client is None and TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
        _twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    return _twilio_client

def split_message(text: str, max_length: int = 4000) -> List[str]:
    """Split a long message into chunks, breaking at newlines where possible"""
    if len(text) <= max_length:
        return [text]

    chunks = []
    while text:
        if len(text) <= max_length:
            chunks.append(text)
            break

        # Find a good break point (newline, then space)
        break_point = text.rfind("\n", 0, max_length)
        if break_point < max_length // 2:
            break_point = text.rfind(" ", 0, max_length)
        if break_point < max_length // 2:
            break_point = max_length

        chunks.append(text[:break_point])
        text = text[break_point:].lstrip()

    return chunks

def log_whatsapp_message(
    business_id: str,
    direction: str,
    message_type: str,
    phone_number: str,
    content: str,
    twilio_message_sid: Optional[str] = None,
    twilio_status: str = "sent",
    related_entity_type: Optional[str] = None,
    related_entity_id: Optional[str] = None,
    session=None,  # Ignored - used for API compatibility
):
    """Log an inbound or outbound message (e.g. from webhook)."""
    _log_whatsapp_message(
        business_id, direction, message_type, phone_number, content,
        twilio_message_sid, twilio_status, related_entity_type, related_entity_id,
    )

def _log_whatsapp_message(
    business_id: str,
    direction: str,
    message_type: str,
    phone_number: str,
    content: str,
    twilio_message_sid: Optional[str] = None,
    twilio_status: str = "sent",
    related_entity_type: Optional[str] = None,
    related_entity_id: Optional[str] = None,
):
    """Insert a message record into whatsapp_messages. Uses sync session."""
    from sqlalchemy import text
    from db import get_session_context

    try:
        with get_session_context() as session:
            session.execute(
                text("""
                    INSERT INTO whatsapp_messages
                    (business_id, direction, message_type, phone_number, content,
                     twilio_message_sid, twilio_status, related_entity_type, related_entity_id)
                    VALUES (:business_id, :direction, :message_type, :phone_number, :content,
                            :twilio_message_sid, :twilio_status, :related_entity_type, :related_entity_id)
                """),
                {
                    "business_id": business_id,
                    "direction": direction,
                    "message_type": message_type,
                    "phone_number": phone_number,
                    "content": content[:5000] if content else None,
                    "twilio_message_sid": twilio_message_sid,
                    "twilio_status": twilio_status,
                    "related_entity_type": related_entity_type,
                    "related_entity_id": related_entity_id,
                },
            )
            session.commit()
    except Exception as e:
        logger.warning(f"[WhatsApp] Failed to log message: {e}")


async def send_whatsapp_message(
    to_number: str,
    body: str,
    business_id: str,
    message_type: str = "notification",
    related_entity_type: Optional[str] = None,
    related_entity_id: Optional[str] = None,
) -> Optional[str]:
    """
    Send a WhatsApp message via Twilio.

    Args:
        to_number: Recipient phone number (e.g., +447885249222)
        body: Message text (WhatsApp supports up to 4096 characters)
        business_id: Business ID for audit logging
        message_type: daily_pulse, weekly_briefing, alert, automation_report, action_confirmation
        related_entity_type: invoice, call, email, task, financial
        related_entity_id: ID of the related entity

    Returns:
        Twilio message SID if successful, None if failed
    """
    client = get_twilio_client()
    if not client:
        logger.error("[WhatsApp] Twilio client not configured")
        return None

    # Format the recipient number for WhatsApp
    if not to_number.startswith("whatsapp:"):
        to_number = f"whatsapp:{to_number}"

    phone_clean = to_number.replace("whatsapp:", "")

    try:
        # Use content templates for scheduled messages (bypasses 24hr window)
        content_sid = TEMPLATE_SID_MAP.get(message_type, "")

        if content_sid:
            # Template-based send — parse variables from body
            try:
                variables = json.loads(body) if body.startswith("{") else {"1": body[:4000]}
            except (json.JSONDecodeError, AttributeError):
                variables = {"1": (body or "")[:4000]}

            message = client.messages.create(
                from_=TWILIO_WHATSAPP_FROM,
                to=to_number,
                content_sid=content_sid,
                content_variables=json.dumps(variables),
            )
            message_sid = message.sid
            logger.info(
                f"[WhatsApp] Sent template message {message.sid} to {to_number} "
                f"(template: {message_type})"
            )
        else:
            # Freeform send — for replies within 24hr window
            chunks = split_message(body, max_length=4000)
            message_sid = None
            for i, chunk in enumerate(chunks):
                message = client.messages.create(
                    from_=TWILIO_WHATSAPP_FROM,
                    to=to_number,
                    body=chunk,
                )
                message_sid = message.sid
                logger.info(
                    f"[WhatsApp] Sent message {message.sid} to {to_number} "
                    f"(chunk {i+1}/{len(chunks)})"
                )

        _log_whatsapp_message(
            business_id=business_id,
            direction="outbound",
            message_type=message_type,
            phone_number=phone_clean,
            content=body,
            twilio_message_sid=message_sid,
            twilio_status="sent",
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
        )
        return message_sid

    except Exception as e:
        logger.error(f"[WhatsApp] Failed to send message to {to_number}: {e}")
        _log_whatsapp_message(
            business_id=business_id,
            direction="outbound",
            message_type=message_type,
            phone_number=phone_clean,
            content=body,
            twilio_status="failed",
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
        )
        return None
