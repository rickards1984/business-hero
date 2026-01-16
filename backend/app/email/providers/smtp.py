from __future__ import annotations

from typing import Any, Dict, Optional

from .base import BaseEmailProvider, ProviderMessage, ProviderSendResult, ProviderSyncResult


class SmtpProvider(BaseEmailProvider):
    """SMTP provider stub; inbox sync is not supported for SMTP."""

    def send_email(
        self,
        *,
        account: Any,
        to_emails: list[str],
        subject: str,
        body_text: Optional[str] = None,
        body_html: Optional[str] = None,
        in_reply_to: Optional[str] = None,
    ) -> ProviderSendResult:
        raise NotImplementedError("SMTP send_email not implemented in this module")

    def sync_inbox_changes(
        self,
        *,
        account: Any,
        cursor: Dict[str, Any],
    ) -> ProviderSyncResult:
        return ProviderSyncResult(messages=[], cursor=cursor)

    def fetch_message(
        self,
        *,
        account: Any,
        provider_message_id: str,
    ) -> Optional[ProviderMessage]:
        return None
