"""Email provider implementations."""

from .base import BaseEmailProvider, ProviderMessage, ProviderSendResult, ProviderSyncResult
from .gmail import GmailProvider
from .msgraph import MsGraphProvider
from .smtp import SmtpProvider

__all__ = [
    "BaseEmailProvider",
    "ProviderMessage",
    "ProviderSendResult",
    "ProviderSyncResult",
    "GmailProvider",
    "MsGraphProvider",
    "SmtpProvider",
]
