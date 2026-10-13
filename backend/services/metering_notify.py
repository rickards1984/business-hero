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
import os

from sqlalchemy import text

logger = logging.getLogger(__name__)


def _manage_link() -> str:
    base = os.getenv("FRONTEND_URL", os.getenv("APP_BASE_URL", "https://business-hero.vercel.app"))
    return f"{base.strip().rstrip('/')}/app/ai?tab=receptionist"


def _words(state: str, usage: dict) -> tuple:
    """Plain, accurate wording (P8): the monthly ALLOWANCE resets; extra
    minutes already used are still billed. A direct link to the switch."""
    used = f"{usage['used_minutes']:.1f}"
    allowance = f"{usage['allowance_minutes']:.0f}"
    link = _manage_link()
    if state == "spend_cap_reached":
        subject = "Business Hero: your receptionist has reached its monthly spending cap"
        body = (
            f"Your AI receptionist has reached its monthly cap of "
            f"£{usage['spend_cap_gbp']:.2f} for extra minutes "
            f"(£{usage['overage_spend_gbp']:.2f} used this month). New calls will not "
            f"be answered until your monthly allowance resets at the start of next "
            f"month, or until you raise the cap here: {link}"
        )
    else:
        subject = "Business Hero: your receptionist minutes for this month are used up"
        body = (
            f"Your AI receptionist has used {used} of its {allowance} minutes this "
            f"month. New calls will not be answered until your monthly allowance "
            f"resets at the start of next month. To keep answering now, switch on "
            f"extra minutes (£0.45 a minute, up to a monthly cap you choose) here: {link}"
        )
    return subject, body


def whatsapp_alert(business_name: str, state: str, usage: dict) -> tuple:
    """The registered 'alert' Content Template (3 variables), as real-time
    alerts use: free text only reaches the owner inside WhatsApp's 24-hour
    reply window, so an unsolicited notice must be a template."""
    _, body = _words(state, usage)
    return "alert", {
        "1": business_name or "your business",
        "2": body.split(" To keep answering now")[0].split(" or until you raise")[0],
        "3": f"Manage it in Business Hero: {_manage_link()}",
    }


def _send_email(business_id: str, subject: str, body: str) -> bool:
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
        return False
    # A system notice to the owner's own mailbox — not an Aria action, so it
    # does not go through the NS-A1 refusal on the assistant's dispatcher.
    result = assistant_tools._send_email(
        engine, business_id, {"to": row[0], "subject": subject, "body": body})
    if not result.get("success"):
        logger.error("[Metering] notice email failed for %s: %s",
                     business_id, result.get("error"))
        return False
    return True


def _send_whatsapp(business, state: str, usage: dict) -> bool:
    import json
    from db import engine

    business_id = str(business.id)
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT phone_number FROM whatsapp_configs "
                 "WHERE business_id = :business_id AND enabled = true"),
            {"business_id": business_id},
        ).fetchone()
    if row is None or not row[0]:
        return False
    from services.whatsapp_service import send_whatsapp_message
    message_type, variables = whatsapp_alert(getattr(business, "name", ""), state, usage)
    coro = send_whatsapp_message(row[0], json.dumps(variables), business_id,
                                 message_type=message_type)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return bool(asyncio.run(coro))

    def _logged(task):
        if task.exception() or not task.result():
            logger.error("[Metering] WhatsApp notice failed for %s", business_id)
    loop.create_task(coro).add_done_callback(_logged)
    return True  # handed to the loop; failures are logged, the email is primary


def send_usage_notice(business, state: str, usage: dict) -> bool:
    """True if any channel took the notice. The banner needs no sending."""
    business_id = str(business.id)
    subject, body = _words(state, usage)
    delivered = False
    for send in (lambda: _send_email(business_id, subject, body),
                 lambda: _send_whatsapp(business, state, usage)):
        try:
            delivered = bool(send()) or delivered
        except Exception as exc:
            logger.error("[Metering] notice failed for %s: %s", business_id, exc)
    return delivered
