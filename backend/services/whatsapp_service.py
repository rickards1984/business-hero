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

# Verified against the Twilio Console on 2026-05-10. The keys MUST match
# message_type values; the values MUST match the variable count placeholders
# defined inside the corresponding Twilio Content Template body. If you add
# a new template, register it here AND in TEMPLATE_SID_MAP above.
TEMPLATE_VARIABLE_COUNTS = {
    "task_reminder": 4,
    "automation_report": 4,
    "daily_pulse": 5,
    "weekly_briefing": 7,
    "action_confirmation": 2,
    "alert": 3,
}


def get_business_name(business_id: str) -> str:
    """Look up the business name for `business_id`, defaulting to 'Your business'.

    Used to inject {{1}} business name into 2-variable templates when a caller
    sends a free-form text body (auto-wrap pattern in send_whatsapp_message).
    """
    if not business_id:
        return "Your business"
    try:
        from sqlalchemy import text
        from db import get_session_context
        with get_session_context() as session:
            row = session.execute(
                text("SELECT name FROM businesses WHERE id = :bid LIMIT 1"),
                {"bid": business_id},
            ).fetchone()
        if row and row[0]:
            return str(row[0])
    except Exception as exc:
        logger.warning(f"[WhatsApp] get_business_name failed for {business_id}: {exc}")
    return "Your business"

# Initialize Twilio client
_twilio_client = None

def get_twilio_client():
    global _twilio_client
    if _twilio_client is None and TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
        _twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    return _twilio_client

def _validate_content_variables(content_variables: dict, template_name: str) -> tuple[bool, str]:
    """
    Validate template content variables before sending to Twilio.

    Twilio error 21656 = 'Content Variables parameter is invalid'.
    Common causes: None values, missing required keys, empty strings.

    Returns (is_valid, error_message).
    """
    if content_variables is None:
        return False, f"content_variables is None for template '{template_name}'"

    if not isinstance(content_variables, dict):
        return False, (
            f"content_variables must be a dict, got "
            f"{type(content_variables).__name__} for template '{template_name}'"
        )

    if not content_variables:
        return False, f"content_variables is empty for template '{template_name}'"

    for key, value in content_variables.items():
        if value is None:
            return False, f"variable '{key}' is None for template '{template_name}'"
        if isinstance(value, str) and not value.strip():
            return False, f"variable '{key}' is empty string for template '{template_name}'"

    return True, ""


def _sanitize_template_vars(variables: dict) -> dict:
    """Ensure all template variables are non-null, non-empty strings within Twilio limits."""
    sanitized = {}
    for key, value in variables.items():
        if value is None:
            sanitized[str(key)] = "N/A"
        elif isinstance(value, (int, float)):
            sanitized[str(key)] = str(value)
        elif isinstance(value, str):
            cleaned = value.strip()
            if not cleaned:
                sanitized[str(key)] = "N/A"
            else:
                sanitized[str(key)] = cleaned[:1024]
        else:
            sanitized[str(key)] = str(value)[:1024] or "N/A"
    return sanitized


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
            expected_count = TEMPLATE_VARIABLE_COUNTS.get(message_type)

            # Step 1: parse the body into a `variables` dict.
            # If body looks like JSON, trust the caller. Otherwise it's
            # free-form and we may need to auto-wrap it.
            parsed_variables = None
            try:
                if isinstance(body, str) and body.startswith("{"):
                    parsed_variables = json.loads(body)
                    if not isinstance(parsed_variables, dict):
                        parsed_variables = None
            except (json.JSONDecodeError, AttributeError):
                parsed_variables = None

            if parsed_variables is not None:
                variables = parsed_variables
            else:
                # Free-form body. Auto-wrap based on the template's
                # expected variable count.
                if expected_count is None or expected_count == 1:
                    variables = {"1": (body or "")[:4000]}
                elif expected_count == 2:
                    biz_name = get_business_name(business_id)
                    variables = {
                        "1": biz_name,
                        "2": (body or "")[:4000],
                    }
                else:
                    # 3+ variable templates have ambiguous structure for a
                    # free-form body. The caller MUST send explicit JSON.
                    error_msg = (
                        f"Free-form body sent to template '{message_type}' "
                        f"which expects {expected_count} variables. Caller "
                        f"must build a JSON body with explicit variable keys."
                    )
                    logger.error(f"[WhatsApp] BLOCKED send to {to_number}: {error_msg}")
                    _log_whatsapp_message(
                        business_id=business_id,
                        direction="outbound",
                        message_type=message_type,
                        phone_number=phone_clean,
                        content=body,
                        twilio_status="blocked_freeform_for_multivar_template",
                        related_entity_type=related_entity_type,
                        related_entity_id=related_entity_id,
                    )
                    return None

            logger.info(
                f"[WhatsApp] Attempting send to {to_number}: "
                f"template={message_type}, "
                f"variable_keys={list(variables.keys()) if isinstance(variables, dict) else None}"
            )

            # Step 2: variable-count sanity check against the verified template
            # spec. Catches caller drift before the API call.
            if (
                expected_count is not None
                and isinstance(variables, dict)
                and len(variables) != expected_count
            ):
                error_msg = (
                    f"Template '{message_type}' expects {expected_count} "
                    f"variables, got {len(variables)}. "
                    f"Variable keys: {list(variables.keys())}"
                )
                logger.error(f"[WhatsApp] BLOCKED send to {to_number}: {error_msg}")
                _log_whatsapp_message(
                    business_id=business_id,
                    direction="outbound",
                    message_type=message_type,
                    phone_number=phone_clean,
                    content=body,
                    twilio_status="blocked_template_variable_count_mismatch",
                    related_entity_type=related_entity_type,
                    related_entity_id=related_entity_id,
                )
                return None

            # Step 3: per-variable validity (None / empty / wrong type)
            is_valid, error_msg = _validate_content_variables(variables, message_type)
            if not is_valid:
                logger.error(
                    f"[WhatsApp] BLOCKED send to {to_number}: {error_msg}. "
                    f"template={message_type}, variables={variables}"
                )
                _log_whatsapp_message(
                    business_id=business_id,
                    direction="outbound",
                    message_type=message_type,
                    phone_number=phone_clean,
                    content=body,
                    twilio_status="blocked_invalid_vars",
                    related_entity_type=related_entity_type,
                    related_entity_id=related_entity_id,
                )
                return None

            variables = _sanitize_template_vars(variables)

            if all(v == "N/A" for v in variables.values()):
                logger.info(f"[WhatsApp] Skipping {message_type} — all variables are empty")
                return None

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
