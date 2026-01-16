from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class ProviderSendResult:
    provider_message_id: Optional[str] = None


@dataclass
class ProviderMessage:
    provider_message_id: str
    provider_thread_id: Optional[str] = None
    folder: str = "INBOX"
    from_email: Optional[str] = None
    from_name: Optional[str] = None
    to_emails: Optional[List[str]] = None
    cc_emails: Optional[List[str]] = None
    subject: Optional[str] = None
    snippet: Optional[str] = None
    received_at: Optional[datetime] = None
    is_unread: bool = True
    has_attachments: bool = False
    labels: Optional[List[str]] = None
    body_text: Optional[str] = None
    body_html: Optional[str] = None
    raw_headers: Optional[Dict[str, Any]] = None


@dataclass
class ProviderSyncResult:
    messages: List[ProviderMessage]
    cursor: Dict[str, Any]


class BaseEmailProvider(ABC):
    @abstractmethod
    def send_email(
        self,
        *,
        account: Any,
        to_emails: List[str],
        subject: str,
        body_text: Optional[str] = None,
        body_html: Optional[str] = None,
        in_reply_to: Optional[str] = None,
    ) -> ProviderSendResult:
        raise NotImplementedError

    @abstractmethod
    def sync_inbox_changes(
        self,
        *,
        account: Any,
        cursor: Dict[str, Any],
    ) -> ProviderSyncResult:
        raise NotImplementedError

    @abstractmethod
    def fetch_message(
        self,
        *,
        account: Any,
        provider_message_id: str,
    ) -> Optional[ProviderMessage]:
        raise NotImplementedError
