from typing import Any, Dict

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
        # TODO: Implement SMTP send using account.smtp_config
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
