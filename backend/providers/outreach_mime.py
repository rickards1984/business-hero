"""OUT-16: one outreach email as a real RFC 5322 message, for any provider.

Our own Message-ID (so replies and follow-ups thread, and the send can be
found again), In-Reply-To/References for follow-ups, and only the one-click
unsubscribe headers (RFC 8058) besides the standard ones. A line break in any
header value is refused outright: it could add recipients or headers.
"""
from email.message import EmailMessage
from email.utils import formataddr, formatdate

ALLOWED_EXTRA = {"List-Unsubscribe", "List-Unsubscribe-Post"}


class UnsafeMessage(ValueError):
    """Refused before any provider call: the message is never sent."""


def _clean(value: str, field: str) -> str:
    value = "" if value is None else str(value)
    if "\r" in value or "\n" in value:
        raise UnsafeMessage(f"{field} contains a line break")
    return value


def build(*, account, to_emails, cc_emails, subject, body_text, rfc_message_id, in_reply_to=None,
          references=None, headers=None) -> EmailMessage:
    message = EmailMessage(policy=__import__("email.policy", fromlist=["SMTP"]).SMTP)
    address = _clean(getattr(account, "email_address", ""), "From")
    if not address or "@" not in address:
        raise UnsafeMessage("No sending address")
    name = _clean(getattr(account, "display_name", None) or "", "From name")
    message["From"] = formataddr((name, address)) if name else address
    message["To"] = ", ".join(_clean(e, "To") for e in to_emails)
    if cc_emails:
        message["Cc"] = ", ".join(_clean(e, "Cc") for e in cc_emails)
    message["Subject"] = _clean(subject, "Subject")
    message["Date"] = formatdate(localtime=False, usegmt=True)
    message["Message-ID"] = _clean(rfc_message_id, "Message-ID")
    if in_reply_to:
        message["In-Reply-To"] = _clean(in_reply_to, "In-Reply-To")
    if references:
        message["References"] = " ".join(_clean(r, "References") for r in references)
    for key, value in (headers or {}).items():
        if key not in ALLOWED_EXTRA:
            raise UnsafeMessage(f"Header {key} is not allowed")
        message[key] = _clean(value, key)
    message.set_content(body_text or "")
    return message


def outcome_for_status(status: int) -> str:
    """2xx accepted; a definite refusal (4xx, including rate limits) was not
    sent; a server error may still have been delivered, so it is unknown."""
    if 200 <= status < 300:
        return "accepted"
    if 400 <= status < 500:
        return "definitely_not_accepted"
    return "unknown"
