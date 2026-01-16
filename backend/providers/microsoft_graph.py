from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from email_utils import decrypt_str
from .base import BaseEmailProvider, ProviderSendResult, ProviderSyncResult, ProviderMessage


GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"


def _parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _get_access_token(account: Any) -> str:
    token_ciphertext = getattr(account, "token_ciphertext", None)
    if not token_ciphertext:
        raise RuntimeError("Microsoft Graph access token not configured")
    return decrypt_str(token_ciphertext)


def _get_read_scope(account: Any) -> str:
    capabilities = getattr(account, "capabilities", {}) or {}
    read_scope = capabilities.get("mail_read") or capabilities.get("read_scope") or "basic"
    return str(read_scope).lower()


def _map_graph_message(message: Dict[str, Any], read_scope: str) -> Optional[ProviderMessage]:
    if message.get("@removed"):
        return None

    from_addr = message.get("from", {}).get("emailAddress", {})
    to_recipients = message.get("toRecipients", []) or []
    cc_recipients = message.get("ccRecipients", []) or []

    provider_message_id = message.get("id")
    if not provider_message_id:
        return None

    body_text = None
    body_html = None
    if read_scope == "full":
        body = message.get("body") or {}
        content = body.get("content")
        content_type = (body.get("contentType") or "").lower()
        if content_type == "html":
            body_html = content
        else:
            body_text = content

    return ProviderMessage(
        provider_message_id=provider_message_id,
        provider_thread_id=message.get("conversationId"),
        folder="INBOX",
        from_email=from_addr.get("address"),
        from_name=from_addr.get("name"),
        to_emails=[r.get("emailAddress", {}).get("address") for r in to_recipients if r.get("emailAddress")],
        cc_emails=[r.get("emailAddress", {}).get("address") for r in cc_recipients if r.get("emailAddress")],
        subject=message.get("subject"),
        snippet=message.get("bodyPreview"),
        received_at=_parse_iso_datetime(message.get("receivedDateTime")),
        is_unread=not bool(message.get("isRead")),
        has_attachments=bool(message.get("hasAttachments")),
        labels=message.get("categories"),
        body_text=body_text,
        body_html=body_html,
        raw_headers={"id": provider_message_id},
    )


class MicrosoftGraphProvider(BaseEmailProvider):
    """Microsoft Graph provider implementation."""

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
        access_token = _get_access_token(account)
        url = f"{GRAPH_BASE_URL}/me/sendMail"
        content_type = "HTML" if body_html else "Text"
        body_content = body_html or body_text or ""

        payload = {
            "message": {
                "subject": subject,
                "body": {"contentType": content_type, "content": body_content},
                "toRecipients": [{"emailAddress": {"address": email}} for email in to_emails],
            },
            "saveToSentItems": True,
        }
        if in_reply_to:
            payload["message"]["inReplyTo"] = in_reply_to

        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
        with httpx.Client(timeout=20) as client:
            response = client.post(url, headers=headers, json=payload)

        if response.status_code != 202:
            raise RuntimeError(f"Microsoft Graph send failed: {response.status_code} {response.text}")

        return ProviderSendResult(provider_message_id=None)

    def sync_inbox_changes(
        self,
        *,
        account: Any,
        cursor: Dict[str, Any],
    ) -> ProviderSyncResult:
        access_token = _get_access_token(account)
        headers = {"Authorization": f"Bearer {access_token}"}
        read_scope = _get_read_scope(account)

        delta_link = (cursor or {}).get("deltaLink")
        url = delta_link or f"{GRAPH_BASE_URL}/me/mailFolders/inbox/messages/delta"
        messages: List[ProviderMessage] = []
        next_cursor: Dict[str, Any] = cursor or {}

        with httpx.Client(timeout=30) as client:
            while url:
                response = client.get(url, headers=headers)
                if response.status_code != 200:
                    raise RuntimeError(
                        f"Microsoft Graph delta query failed: {response.status_code} {response.text}"
                    )
                data = response.json()
                for raw in data.get("value", []) or []:
                    mapped = _map_graph_message(raw, read_scope)
                    if mapped:
                        messages.append(mapped)

                if "@odata.nextLink" in data:
                    url = data["@odata.nextLink"]
                    continue

                if "@odata.deltaLink" in data:
                    next_cursor = {"deltaLink": data["@odata.deltaLink"]}
                url = None

        return ProviderSyncResult(messages=messages, cursor=next_cursor)

    def fetch_message(
        self,
        *,
        account: Any,
        provider_message_id: str,
    ) -> ProviderMessage | None:
        # TODO: Implement Microsoft Graph message fetch
        return None


__all__ = ["MicrosoftGraphProvider", "_map_graph_message"]
