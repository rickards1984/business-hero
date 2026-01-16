from typing import Any, Dict
from email.message import EmailMessage
import smtplib

from email_utils import decrypt_str

from .base import BaseEmailProvider, ProviderSendResult, ProviderSyncResult, ProviderMessage


class SMTPProvider(BaseEmailProvider):
    """SMTP provider implementation (send-only)."""

    def send_email(
        self,
        *,
        account: Any,
        to_emails: list[str],
        subject: str,
        body_text: str | None = None,
        body_html: str | None = None,
        in_reply_to: str | None = None,
    ) -> ProviderSendResult:
        smtp_config = getattr(account, "smtp_config", {}) or {}
        host = smtp_config.get("host")
        port = smtp_config.get("port")
        username = smtp_config.get("username")
        password_ciphertext = smtp_config.get("password_ciphertext")
        from_email = smtp_config.get("from_email")
        use_tls = smtp_config.get("use_tls", True)
        use_ssl = smtp_config.get("use_ssl", False)

        if not host or not port or not username or not password_ciphertext or not from_email:
            raise RuntimeError("SMTP configuration incomplete")

        password = decrypt_str(password_ciphertext)

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = from_email
        msg["To"] = ", ".join(to_emails)

        if body_html:
            msg.set_content(body_text or "")
            msg.add_alternative(body_html, subtype="html")
        else:
            msg.set_content(body_text or "")

        if use_ssl:
            server = smtplib.SMTP_SSL(host, int(port), timeout=10)
        else:
            server = smtplib.SMTP(host, int(port), timeout=10)

        try:
            if use_tls and not use_ssl:
                server.starttls()
            server.login(username, password)
            server.send_message(msg)
        finally:
            server.quit()
        return ProviderSendResult(provider_message_id=None)

    def sync_inbox_changes(
        self,
        *,
        account: Any,
        cursor: Dict[str, Any],
    ) -> ProviderSyncResult:
        # SMTP has no inbox sync support.
        return ProviderSyncResult(messages=[], cursor=cursor or {})

    def fetch_message(
        self,
        *,
        account: Any,
        provider_message_id: str,
    ) -> ProviderMessage | None:
        # SMTP has no inbox fetch support.
        return None
