from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
import base64
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .oauth_utils import get_valid_access_token

from .base import BaseEmailProvider, ProviderSendResult, ProviderSyncResult, ProviderMessage, checked_senders


_logger = logging.getLogger("gmail_provider")

# Bounded-concurrency tuning for the per-message metadata fan-out.
GMAIL_FETCH_CONCURRENCY = 8            # max simultaneous Gmail GETs (per-user limit ~250 units/s; get = 5 units)
GMAIL_FETCH_MAX_RETRIES = 3           # attempts per message on 429 / 5xx / transient network errors
GMAIL_RETRY_AFTER_CAP_SECONDS = 5.0   # cap on any honored Retry-After / backoff sleep
GMAIL_FETCH_DEADLINE_SECONDS = 30.0   # hard cap on total retry time per message
GMAIL_SEARCH_MAX_PAGES = 10            # AUTO-2: a reply search longer than this is refused, not truncated


class _GmailFetchError(Exception):
    """Raised by _fetch_message_metadata on a non-200 response so the retry
    wrapper can inspect the status code and any Retry-After header."""

    def __init__(self, status_code: int, retry_after: Optional[str] = None, detail: str = ""):
        super().__init__(f"Gmail fetch failed: {status_code} {detail}")
        self.status_code = status_code
        self.retry_after = retry_after


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

    def send_outreach(self, *, account, operation_key, to_emails, cc_emails, subject, body_text, body_html=None,
                      rfc_message_id, in_reply_to=None, references=None, provider_thread_id=None, headers=None,
                      reply_provider_message_id=None) -> dict:
        """OUT-16: one outreach email through the Gmail API, with an honest outcome.
        Never retried here: a timeout may still have been sent, so it is unknown."""
        from . import outreach_mime
        evidence = {"provider": "google", "mailbox_id": str(account.id), "rfc_message_id": rfc_message_id}
        try:
            message = outreach_mime.build(account=account, to_emails=to_emails, cc_emails=cc_emails, subject=subject,
                                          body_text=body_text, rfc_message_id=rfc_message_id, in_reply_to=in_reply_to,
                                          references=references, headers=headers)
        except outreach_mime.UnsafeMessage as exc:
            return {**evidence, "outcome": "definitely_not_accepted", "reason": str(exc)}
        try:
            access_token = get_valid_access_token(account)
        except Exception as exc:   # no usable token: nothing was sent
            return {**evidence, "outcome": "definitely_not_accepted", "reason": f"token: {type(exc).__name__}"}
        payload = {"raw": base64.urlsafe_b64encode(message.as_bytes()).decode("ascii").rstrip("=")}
        if provider_thread_id:
            payload["threadId"] = provider_thread_id
        try:
            with httpx.Client(timeout=30) as client:
                response = client.post("https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                                       headers={"Authorization": f"Bearer {access_token}"}, json=payload)
        except Exception as exc:
            return {**evidence, "outcome": "unknown", "reason": type(exc).__name__}
        outcome = outreach_mime.outcome_for_status(response.status_code)
        if outcome != "accepted":
            return {**evidence, "outcome": outcome, "reason": f"HTTP {response.status_code}"}
        try:
            data = response.json() or {}
        except Exception:
            data = {}
        return {"outcome": "accepted", "provider": "google", "mailbox_id": str(account.id),
                "provider_message_id": data.get("id"), "provider_thread_id": data.get("threadId"),
                "rfc_message_id": rfc_message_id}

    def sync_inbox_changes(
        self,
        *,
        account: Any,
        cursor: Dict[str, Any],
    ) -> ProviderSyncResult:
        access_token = get_valid_access_token(account)
        headers = {"Authorization": f"Bearer {access_token}"}

        url = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
        params = {"labelIds": "INBOX", "maxResults": 50}
        with httpx.Client(timeout=20) as client:
            response = client.get(url, headers=headers, params=params)
            if response.status_code != 200:
                raise RuntimeError(f"Gmail list failed: {response.status_code} {response.text}")
            data = response.json()

            ids = [item["id"] for item in (data.get("messages") or []) if item.get("id")]

            # Fan out the per-message metadata fetches with bounded concurrency.
            # The httpx.Client is shared across worker threads (thread-safe), and
            # the bearer token / headers were resolved once and are immutable here,
            # so the workers only share read-only state.
            results: Dict[str, ProviderMessage] = {}
            if ids:
                with ThreadPoolExecutor(max_workers=GMAIL_FETCH_CONCURRENCY) as pool:
                    future_to_id = {
                        pool.submit(_fetch_message_metadata_safe, client, headers, mid): mid
                        for mid in ids
                    }
                    for future in as_completed(future_to_id):
                        msg = future.result()  # _safe never raises; returns None on give-up
                        if msg:
                            results[future_to_id[future]] = msg

            # Preserve the original list order (Gmail returns newest-first).
            messages = [results[mid] for mid in ids if mid in results]

        _logger.info(
            f"[GmailSync] Fetched {len(messages)}/{len(ids)} INBOX messages "
            f"({len(ids) - len(messages)} skipped)"
        )
        return ProviderSyncResult(messages=messages, cursor=cursor or {})

    def search_from(
        self,
        *,
        account: Any,
        senders: List[str],
        since: datetime,
    ) -> List[ProviderMessage]:
        """AUTO-2: Gmail's own search over the whole mailbox (not only the
        newest page of INBOX), paged to the end. Raises rather than return a
        partial answer: a failed fetch or too many pages means "unknown"."""
        addresses = checked_senders(senders)
        if not addresses:
            return []
        query = "(" + " OR ".join(f"from:{a}" for a in addresses) + f") after:{int(since.timestamp())}"
        access_token = get_valid_access_token(account)
        headers = {"Authorization": f"Bearer {access_token}"}
        url = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
        ids: List[str] = []
        with httpx.Client(timeout=20) as client:
            token = None
            for _ in range(GMAIL_SEARCH_MAX_PAGES):
                # Spam and Trash too: a reply filed as spam is still a reply
                # (Codex AUTO-2 review 2).
                params = {"q": query, "maxResults": 100, "includeSpamTrash": "true"}
                if token:
                    params["pageToken"] = token
                response = client.get(url, headers=headers, params=params)
                if response.status_code != 200:
                    raise RuntimeError(f"Gmail search failed: {response.status_code}")
                data = response.json()
                ids.extend(item["id"] for item in (data.get("messages") or []) if item.get("id"))
                token = data.get("nextPageToken")
                if not token:
                    break
            else:
                raise RuntimeError("Gmail search returned more pages than allowed")
            found: List[ProviderMessage] = []
            for mid in ids:
                message = _fetch_message_metadata_safe(client, headers, mid)
                if message is None:
                    raise RuntimeError("a Gmail message found by the search could not be read")
                found.append(message)
        return found

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
        raise _GmailFetchError(
            response.status_code,
            retry_after=response.headers.get("Retry-After"),
            detail=response.text[:200],
        )
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


def _retry_after_seconds(retry_after: Optional[str], fallback: float) -> float:
    """Seconds to wait before retrying: honor a numeric Retry-After (capped),
    otherwise use the exponential-backoff fallback. HTTP-date Retry-After
    values are not parsed — we fall back rather than risk a long sleep."""
    if retry_after:
        try:
            return min(float(retry_after), GMAIL_RETRY_AFTER_CAP_SECONDS)
        except (TypeError, ValueError):
            return fallback
    return fallback


def _fetch_message_metadata_safe(
    client: httpx.Client,
    headers: Dict[str, str],
    message_id: str,
) -> Optional[ProviderMessage]:
    """Fetch one message's metadata with bounded retry/backoff.

    Retries on 429 / 5xx and transient network errors, honoring Retry-After
    when present, with exponential backoff (0.5s, 1s, 2s, capped). A 404 — the
    message was deleted between list and fetch — or any other 4xx is a
    permanent skip and is not retried. Total retry time is capped. Returns
    None on final give-up so a single bad message can never abort the run.
    """
    backoff = 0.5
    last_status: Any = None
    deadline = time.monotonic() + GMAIL_FETCH_DEADLINE_SECONDS

    for attempt in range(1, GMAIL_FETCH_MAX_RETRIES + 1):
        try:
            return _fetch_message_metadata(client, headers, message_id)
        except _GmailFetchError as e:
            last_status = e.status_code
            # Permanent failures (404 deleted, other non-429 4xx) — do not retry.
            if e.status_code != 429 and 400 <= e.status_code < 500:
                _logger.warning(
                    f"[GmailSync] Skipping message {message_id}: "
                    f"permanent status {e.status_code}"
                )
                return None
            wait = _retry_after_seconds(e.retry_after, backoff)
        except httpx.HTTPError as e:
            # Transient network error / timeout — retry with backoff.
            last_status = repr(e)
            wait = backoff
        except Exception as e:  # never let one message abort the whole run
            _logger.warning(
                f"[GmailSync] Skipping message {message_id}: unexpected error {e!r}"
            )
            return None

        # Out of attempts, or the next wait would exceed the per-message deadline.
        if attempt >= GMAIL_FETCH_MAX_RETRIES or (time.monotonic() + wait) >= deadline:
            break
        time.sleep(wait)
        backoff = min(backoff * 2, GMAIL_RETRY_AFTER_CAP_SECONDS)

    _logger.warning(
        f"[GmailSync] Giving up on message {message_id} after "
        f"{GMAIL_FETCH_MAX_RETRIES} attempt(s) (last status {last_status})"
    )
    return None


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
