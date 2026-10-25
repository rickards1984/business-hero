import base64
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from .oauth_utils import get_valid_access_token
from .base import BaseEmailProvider, ProviderSendResult, ProviderSyncResult, ProviderMessage, checked_senders


GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
GRAPH_SEARCH_MAX_PAGES = 10  # AUTO-2: a reply search longer than this is refused, not truncated


def _parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


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
        to_emails: List[str],
        subject: str,
        body_text: Optional[str] = None,
        body_html: Optional[str] = None,
        in_reply_to: Optional[str] = None,
    ) -> ProviderSendResult:
        access_token = get_valid_access_token(account)
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

    def send_outreach(self, *, account, operation_key, to_emails, cc_emails, subject, body_text, body_html=None,
                      rfc_message_id, in_reply_to=None, references=None, provider_thread_id=None, headers=None,
                      reply_provider_message_id=None) -> dict:
        """OUT-16: one outreach email through Microsoft Graph, sent as a full MIME
        message so our Message-ID and unsubscribe headers survive (Graph's JSON
        form only allows x- headers). Graph returns no ids on send, so the sent
        message is found again by its Message-ID.

        Threading (Codex OUT-16 review 1): Graph's MIME /reply always addresses
        the original message's sender, which for a follow-up is our own mailbox,
        so follow-ups and replies go through sendMail carrying In-Reply-To,
        References and a "Re:" subject — what the recipient's mail client threads
        on. Graph's own grouping is then checked, not assumed: the conversation
        the sent copy landed in is reported, and a mismatch with the expected
        thread is named in `thread_note` rather than hidden."""
        from . import outreach_mime
        evidence = {"provider": "microsoft", "mailbox_id": str(account.id), "rfc_message_id": rfc_message_id}
        try:
            message = outreach_mime.build(account=account, to_emails=to_emails, cc_emails=cc_emails, subject=subject,
                                          body_text=body_text, rfc_message_id=rfc_message_id, in_reply_to=in_reply_to,
                                          references=references, headers=headers)
        except outreach_mime.UnsafeMessage as exc:
            return {**evidence, "outcome": "definitely_not_accepted", "reason": str(exc)}
        try:
            access_token = get_valid_access_token(account)
        except Exception as exc:
            return {**evidence, "outcome": "definitely_not_accepted", "reason": f"token: {type(exc).__name__}"}
        auth = {"Authorization": f"Bearer {access_token}"}
        try:
            with httpx.Client(timeout=30) as client:
                response = client.post(f"{GRAPH_BASE_URL}/me/sendMail", headers={**auth, "Content-Type": "text/plain"},
                                       content=base64.b64encode(message.as_bytes()))
        except Exception as exc:
            return {**evidence, "outcome": "unknown", "reason": type(exc).__name__}
        outcome = outreach_mime.outcome_for_status(response.status_code, 202)
        if outcome != "accepted":
            return {**evidence, "outcome": outcome, "reason": f"HTTP {response.status_code}"}
        found = {}
        escaped = rfc_message_id.replace("'", "''")
        for attempt in range(3):   # the sent copy takes a moment to appear
            try:
                with httpx.Client(timeout=15) as client:
                    lookup = client.get(f"{GRAPH_BASE_URL}/me/messages", headers=auth,
                                        params={"$filter": f"internetMessageId eq '{escaped}'",
                                                "$select": "id,conversationId", "$top": "1"})
                items = (lookup.json() or {}).get("value") or [] if lookup.status_code == 200 else []
            except Exception:
                items = []
            if items:
                found = items[0]
                break
            time.sleep(1.5)
        result = {"outcome": "accepted", "provider": "microsoft", "mailbox_id": str(account.id),
                  "provider_message_id": found.get("id"), "provider_thread_id": found.get("conversationId"),
                  "rfc_message_id": rfc_message_id}
        if provider_thread_id and found and found.get("conversationId") != provider_thread_id:
            result["thread_note"] = "sent copy is in a different Outlook conversation from the email it follows"
        elif provider_thread_id and not found:
            result["thread_note"] = "sent copy not found yet, so its Outlook conversation is unconfirmed"
        return result

    def sync_inbox_changes(
        self,
        *,
        account: Any,
        cursor: Dict[str, Any],
    ) -> ProviderSyncResult:
        access_token = get_valid_access_token(account)
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

    def search_from(
        self,
        *,
        account: Any,
        senders: List[str],
        since: datetime,
    ) -> List[ProviderMessage]:
        """AUTO-2: every message from `senders` since `since`, across all mail
        folders, paged to the end. UNVERIFIED against a live Microsoft
        mailbox (19 Oct 2026): the results are re-checked here, and any error
        or too many pages raises — which means no automatic chase, never a
        chase over an unseen reply."""
        addresses = checked_senders(senders)
        if not addresses:
            return []
        stamp = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        who = " or ".join("from/emailAddress/address eq '" + a.replace("'", "''") + "'" for a in addresses)
        access_token = get_valid_access_token(account)
        headers = {"Authorization": f"Bearer {access_token}"}
        read_scope = _get_read_scope(account)
        url: Optional[str] = f"{GRAPH_BASE_URL}/me/messages"
        params: Optional[Dict[str, Any]] = {
            "$filter": f"receivedDateTime ge {stamp} and ({who})",
            "$top": "50",
        }
        found: List[ProviderMessage] = []
        with httpx.Client(timeout=30) as client:
            for _ in range(GRAPH_SEARCH_MAX_PAGES):
                response = client.get(url, headers=headers, params=params)
                if response.status_code != 200:
                    raise RuntimeError(f"Microsoft Graph search failed: {response.status_code}")
                data = response.json()
                for raw in data.get("value", []) or []:
                    raw_sender = str(((raw.get("from") or {}).get("emailAddress") or {})
                                     .get("address") or "").strip().lower()
                    mapped = _map_graph_message(raw, read_scope)
                    if raw_sender in addresses and (mapped is None or mapped.received_at is None):
                        # From the customer but unusable: fail closed rather
                        # than skip it (Codex AUTO-2 review 2).
                        raise RuntimeError("a matching Microsoft message could not be read")
                    if mapped is None:
                        continue
                    sender = (mapped.from_email or "").strip().lower()
                    if sender in addresses and mapped.received_at >= since:
                        found.append(mapped)
                url, params = data.get("@odata.nextLink"), None
                if not url:
                    break
            else:
                raise RuntimeError("Microsoft Graph search returned more pages than allowed")
        return found

    def fetch_message(
        self,
        *,
        account: Any,
        provider_message_id: str,
    ) -> Optional[ProviderMessage]:
        # TODO: Implement Microsoft Graph message fetch
        return None


__all__ = ["MicrosoftGraphProvider", "_map_graph_message"]
