from typing import Any, Dict

from .base import BaseEmailProvider, ProviderSendResult, ProviderSyncResult, ProviderMessage


class GoogleGmailProvider(BaseEmailProvider):
    """Stub Gmail provider implementation."""

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
        # TODO: Implement Gmail API send
        return ProviderSendResult(provider_message_id=None)

    def sync_inbox_changes(
        self,
        *,
        account: Any,
        cursor: Dict[str, Any],
    ) -> ProviderSyncResult:
        # TODO: Implement Gmail history sync
        return ProviderSyncResult(messages=[], cursor=cursor or {})

    def fetch_message(
        self,
        *,
        account: Any,
        provider_message_id: str,
    ) -> ProviderMessage | None:
        # TODO: Implement Gmail message fetch
        return None
