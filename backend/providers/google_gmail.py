from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
import base64
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .oauth_utils import get_valid_access_token

from .base import BaseEmailProvider, ProviderSendResult, ProviderSyncResult, ProviderMessage


class GoogleGmailProvider(BaseEmailProvider):
    """Stub Gmail provider implementation."""

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
        access_token = get_valid_access_token(account)
        from_email = getattr(account, "email_address", None)
        if not from_email:
            raise RuntimeError("Gmail account email missing")

        message = EmailMessage()
        message["To"] = ", ".join(to_emails)
        message["From"] = from_email
        message["Subject"] = subject
        if in_reply_to:
            message["In-Reply-To"] = in_reply_to

        if body_html:
            message.set_content(body_text or "")
            message.add_alternative(body_html, subtype="html")
        else:
            message.set_content(body_text or "")

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8").rstrip("=")
        payload = {"raw": raw}
        url = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
        headers = {"Authorization": f"Bearer {access_token}"}
        with httpx.Client(timeout=20) as client:
            response = client.post(url, headers=headers, json=payload)
        if response.status_code != 200:
            raise RuntimeError(f"Gmail send failed: {response.status_code} {response.text}")
        data = response.json()
        return ProviderSendResult(provider_message_id=data.get("id"))

    def sync_inbox_changes(
        self,
        *,
        account: Any,
        cursor: Dict[str, Any],
    ) -> ProviderSyncResult:
        access_token = get_valid_access_token(account)
        headers = {"Authorization": f"Bearer {access_token}"}
        messages: List[ProviderMessage] = []

        url = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
        params = {"labelIds": "INBOX", "maxResults": 50}
        with httpx.Client(timeout=20) as client:
            response = client.get(url, headers=headers, params=params)
            if response.status_code != 200:
                raise RuntimeError(f"Gmail list failed: {response.status_code} {response.text}")
            data = response.json()
            for item in data.get("messages", []) or []:
                msg_id = item.get("id")
                if not msg_id:
                    continue
                msg = _fetch_message_metadata(client, headers, msg_id)
                if msg:
                    messages.append(msg)

        return ProviderSyncResult(messages=messages, cursor=cursor or {})

    def fetch_message(
        self,
        *,
        account: Any,
        provider_message_id: str,
    ) -> ProviderMessage | None:
        # TODO: Implement Gmail message fetch
        return None


def _fetch_message_metadata(
    client: httpx.Client,
    headers: Dict[str, str],
    message_id: str,
) -> Optional[ProviderMessage]:
    url = f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}"
    params = {"format": "metadata"}
    response = client.get(url, headers=headers, params=params)
    if response.status_code != 200:
        raise RuntimeError(f"Gmail fetch failed: {response.status_code} {response.text}")
    data = response.json()
    payload = data.get("payload") or {}
    header_items = payload.get("headers") or []
    headers_map = {item.get("name"): item.get("value") for item in header_items if item.get("name")}

    from_name, from_email = _parse_single_address(headers_map.get("From"))
    to_emails = _parse_multi_addresses(headers_map.get("To"))
    cc_emails = _parse_multi_addresses(headers_map.get("Cc"))
    subject = headers_map.get("Subject")
    date_header = headers_map.get("Date")
    received_at = _parse_received_at(date_header, data.get("internalDate"))

    labels = data.get("labelIds") or []
    is_unread = "UNREAD" in labels

    return ProviderMessage(
        provider_message_id=data.get("id") or message_id,
        provider_thread_id=data.get("threadId"),
        folder="INBOX",
        from_email=from_email,
        from_name=from_name,
        to_emails=to_emails,
        cc_emails=cc_emails,
        subject=subject,
        snippet=data.get("snippet"),
        received_at=received_at,
        is_unread=is_unread,
        has_attachments=False,
        labels=labels,
        body_text=None,
        body_html=None,
        raw_headers=headers_map,
    )


def _parse_single_address(value: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    if not value:
        return None, None
    name, email = parseaddr(value)
    return name or None, email or None


def _parse_multi_addresses(value: Optional[str]) -> Optional[List[str]]:
    if not value:
        return None
    return [email for _, email in getaddresses([value]) if email]


def _parse_received_at(date_header: Optional[str], internal_date: Optional[str]) -> Optional[datetime]:
    if date_header:
        try:
            return parsedate_to_datetime(date_header)
        except (TypeError, ValueError):
            pass
    if internal_date:
        try:
            return datetime.fromtimestamp(int(internal_date) / 1000, tz=timezone.utc)
        except (TypeError, ValueError):
            return None
    return None
