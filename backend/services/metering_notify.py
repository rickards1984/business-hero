"""Tell the owner a usage limit has been reached — BH-012.

ADR 0001 D19 (Mike, 10 Oct 2026): email + in-app banner, + WhatsApp when the
business has WhatsApp briefings switched on. The banner is the `state` that
GET /v1/usage returns; this module sends the messages.

There is no system mailer in Business Hero: email goes out through the
business's own connected mailbox (as invoice chases do), so this notice is
sent FROM and TO that mailbox — the inbox the owner reads. A business with
no connected mailbox still gets the banner, and WhatsApp if it is on.

Every send is best-effort: a failed notice is logged and never fails the
call record that triggered it.
"""

import asyncio
import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)


def _words(state: str, usage: dict) -> tuple:
    used = f"{usage['used_minutes']:.1f}"
    allowance = f"{usage['allowance_minutes']:.0f}"
    if state == "spend_cap_reached":
        subject = "Business Hero: your receptionist has reached its monthly spending cap"
        body = (
            f"Your AI receptionist has reached the monthly spending cap of "
            f"£{usage['spend_cap_gbp']:.2f} for extra minutes "
            f"(£{usage['overage_spend_gbp']:.2f} used this month). New calls will "
            f"not be answered until the month resets, or until you raise the cap "
            f"in Business Hero under AI Hub, Receptionist."
        )
    else:
        subject = "Business Hero: your receptionist minutes for this month are used up"
        body = (
            f"Your AI receptionist has used {used} of its {allowance} minutes this "
            f"month. New calls will not be answered until the month resets. To keep "
            f"answering now, switch on extra minutes (£0.45 a minute, up to a "
            f"monthly cap you choose) in Business Hero under AI Hub, Receptionist."
        )
    return subject, body


def _send_email(business_id: str, subject: str, body: str) -> None:
    from db import engine
    import assistant_tools

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT email_address FROM email_accounts "
                 "WHERE business_id = :business_id AND provider IN ('google', 'microsoft') "
                 "ORDER BY created_at DESC LIMIT 1"),
            {"business_id": business_id},
        ).fetchone()
    if row is None or not row[0]:
        logger.info("[Metering] no connected mailbox for %s; banner only", business_id)
        return
    # A system notice to the owner's own mailbox — not an Aria action, so it
    # does not go through the NS-A1 refusal on the assistant's dispatcher.
    result = assistant_tools._send_email(
        engine, business_id, {"to": row[0], "subject": subject, "body": body})
    if not result.get("success"):
        logger.error("[Metering] notice email failed for %s: %s",
                     business_id, result.get("error"))


def _send_whatsapp(business_id: str, body: str) -> None:
    from db import engine

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT phone_number FROM whatsapp_configs "
                 "WHERE business_id = :business_id AND enabled = true"),
            {"business_id": business_id},
        ).fetchone()
    if row is None or not row[0]:
        return
    from services.whatsapp_service import send_whatsapp_message
    coro = send_whatsapp_message(row[0], body, business_id, message_type="notification")
    try:
        asyncio.get_running_loop().create_task(coro)
    except RuntimeError:
        asyncio.run(coro)


def send_usage_notice(business, state: str, usage: dict) -> None:
    business_id = str(business.id)
    subject, body = _words(state, usage)
    for send in (lambda: _send_email(business_id, subject, body),
                 lambda: _send_whatsapp(business_id, body)):
        try:
            send()
        except Exception as exc:
            logger.error("[Metering] notice failed for %s: %s", business_id, exc)
