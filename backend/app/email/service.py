"""Email service utilities and Supabase admin client."""

from __future__ import annotations

import json
import os
import smtplib
from datetime import datetime
from email.message import EmailMessage
from typing import Any, Dict, Iterable, List, Optional

import httpx
from fastapi import Depends, HTTPException, status
from openai import OpenAI
from sqlmodel import Session, select
from sqlalchemy import text

from email_utils import decrypt_secret
from models import Business, EmailAccount, EmailConnection, EmailMessage as EmailMessageModel
from providers.google_gmail import GoogleGmailProvider
from providers.microsoft_graph import MicrosoftGraphProvider
from providers.smtp import SMTPProvider
from supabase_auth import SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


class SupabaseAdminClient:
    """Minimal Supabase PostgREST client using the service role key."""

    def __init__(self, base_url: str, service_role_key: str, timeout: float = 20.0) -> None:
        if not base_url:
            raise ValueError("SUPABASE_URL is not configured")
        if not service_role_key:
            raise ValueError("SUPABASE_SERVICE_ROLE_KEY is not configured")
        self.base_url = base_url.rstrip("/")
        self.service_role_key = service_role_key
        self.timeout = timeout

    def _headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        headers = {
            "apikey": self.service_role_key,
            "Authorization": f"Bearer {self.service_role_key}",
            "Content-Type": "application/json",
        }
        if extra:
            headers.update(extra)
        return headers

    def _rest_url(self, table: str) -> str:
        return f"{self.base_url}/rest/v1/{table}"

    async def _request(
        self,
        method: str,
        table: str,
        *,
        params: Optional[Dict[str, str]] = None,
        json: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        url = self._rest_url(table)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.request(
                method,
                url,
                params=params,
                json=json,
                headers=self._headers(headers),
            )
        if response.status_code >= 400:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Supabase request failed ({response.status_code}): {response.text}",
            )
        if response.text:
            return response.json()
        return None

    @staticmethod
    def _normalize_payload(payload: Any) -> Any:
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, Iterable):
            return list(payload)
        return payload

    async def _upsert(self, table: str, payload: Any, *, on_conflict: str) -> Any:
        params = {"on_conflict": on_conflict}
        headers = {"Prefer": "resolution=merge-duplicates,return=representation"}
        return await self._request(
            "POST",
            table,
            params=params,
            json=self._normalize_payload(payload),
            headers=headers,
        )

    async def _insert(self, table: str, payload: Any) -> Any:
        headers = {"Prefer": "return=representation"}
        return await self._request(
            "POST",
            table,
            json=self._normalize_payload(payload),
            headers=headers,
        )

    async def _update(self, table: str, payload: Dict[str, Any], *, filters: Dict[str, Any]) -> Any:
        params = {key: f"eq.{value}" for key, value in filters.items()}
        headers = {"Prefer": "return=representation"}
        return await self._request(
            "PATCH",
            table,
            params=params,
            json=payload,
            headers=headers,
        )

    async def _delete(self, table: str, *, filters: Dict[str, Any]) -> Any:
        """Delete rows matching filters. Returns deleted rows."""
        params = {key: f"eq.{value}" for key, value in filters.items()}
        headers = {"Prefer": "return=representation"}
        return await self._request(
            "DELETE",
            table,
            params=params,
            headers=headers,
        )

    async def upsert_email_accounts(self, payload: Any) -> Any:
        return await self._upsert(
            "email_accounts",
            payload,
            on_conflict="business_id,email_address,provider",
        )

    async def fetch_email_accounts(self, business_id: str, *, fields: str) -> Any:
        params = {"select": fields, "business_id": f"eq.{business_id}"}
        return await self._request("GET", "email_accounts", params=params)

    async def fetch_email_account(
        self,
        *,
        business_id: str,
        fields: str,
        account_id: Optional[str] = None,
        is_default: Optional[bool] = None,
    ) -> Optional[Dict[str, Any]]:
        params = {"select": fields, "business_id": f"eq.{business_id}", "limit": "1"}
        if account_id:
            params["id"] = f"eq.{account_id}"
        if is_default is not None:
            params["is_default"] = f"eq.{str(is_default).lower()}"
        rows = await self._request("GET", "email_accounts", params=params)
        if rows:
            return rows[0]
        return None

    async def insert_email_outbox(self, payload: Any) -> Any:
        return await self._insert("email_outbox", payload)

    async def update_email_outbox(self, outbox_id: str, payload: Dict[str, Any]) -> Any:
        return await self._update("email_outbox", payload, filters={"id": outbox_id})

    async def upsert_email_messages(self, payload: Any) -> Any:
        return await self._upsert(
            "email_messages",
            payload,
            on_conflict="email_account_id,provider_message_id",
        )

    async def insert_email_briefings(self, payload: Any) -> Any:
        return await self._insert("email_briefings", payload)

    async def insert_email_drafts(self, payload: Any) -> Any:
        return await self._insert("email_drafts", payload)

    async def update_email_drafts(self, draft_id: str, payload: Dict[str, Any]) -> Any:
        return await self._update("email_drafts", payload, filters={"id": draft_id})


def get_supabase_admin_client() -> SupabaseAdminClient:
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Supabase service role configuration missing",
        )
    return SupabaseAdminClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


SupabaseAdminClientDep = Depends(get_supabase_admin_client)


def get_business_by_id(session: Session, business_id: str) -> Business:
    """Fetch business by ID or raise 404."""
    statement = select(Business).where(Business.id == business_id)
    business = session.exec(statement).first()
    if not business:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Business not found")
    return business


def is_platform_admin_user(user_id: str, session: Session) -> bool:
    """Check if user is a platform admin."""
    result = session.exec(
        text("SELECT 1 FROM platform_admins WHERE user_id = :user_id LIMIT 1"),
        {"user_id": user_id},
    ).first()
    return result is not None


def get_business_member_role(user_id: str, business_id: str, session: Session) -> Optional[str]:
    """Get business member role for a user in a business."""
    result = session.exec(
        text(
            "SELECT role FROM business_members "
            "WHERE user_id = :user_id AND business_id = :business_id AND is_active = true "
            "LIMIT 1"
        ),
        {"user_id": user_id, "business_id": business_id},
    ).first()
    return result[0] if result else None


def ensure_email_manager_role(user_id: str, business_id: str, session: Session) -> None:
    """Ensure user has role to manage email settings."""
    if is_platform_admin_user(user_id, session):
        return
    role = get_business_member_role(user_id, business_id, session)
    if role not in {"owner", "manager", "admin"}:
        raise HTTPException(status_code=403, detail="Insufficient permissions for email settings")


def send_email_smtp(connection: EmailConnection, to_email: str, subject: str, body: str) -> None:
    """Send email using SMTP connection settings."""
    password = decrypt_secret(connection.smtp_password_encrypted)
    msg = EmailMessage()
    msg["To"] = to_email
    msg["Subject"] = subject
    if connection.from_name:
        msg["From"] = f"{connection.from_name} <{connection.from_email}>"
    else:
        msg["From"] = connection.from_email
    msg.set_content(body)

    if connection.use_ssl:
        server = smtplib.SMTP_SSL(connection.smtp_host, connection.smtp_port, timeout=10)
    else:
        server = smtplib.SMTP(connection.smtp_host, connection.smtp_port, timeout=10)
    try:
        if connection.use_tls and not connection.use_ssl:
            server.starttls()
        server.login(connection.smtp_username, password)
        server.send_message(msg)
    finally:
        server.quit()


def get_provider_for_account(account: EmailAccount):
    """Return provider implementation based on account provider type."""
    provider = (account.provider or "").lower()
    if provider == "google":
        return GoogleGmailProvider()
    if provider == "microsoft":
        return MicrosoftGraphProvider()
    if provider == "smtp":
        return SMTPProvider()
    raise HTTPException(status_code=400, detail=f"Unsupported provider: {account.provider}")


def get_default_email_account(session: Session, business: Business) -> EmailAccount:
    """Fetch default email account for a business (fallback to any account)."""
    account = session.exec(
        select(EmailAccount).where(
            EmailAccount.business_id == business.id,
            EmailAccount.is_default == True,
        )
    ).first()
    if not account:
        account = session.exec(
            select(EmailAccount).where(EmailAccount.business_id == business.id)
        ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Email account not configured")
    return account


def get_or_create_smtp_account(
    session: Session,
    business: Business,
    user_id: str,
    connection: EmailConnection,
) -> EmailAccount:
    """Create a shadow SMTP account so email_outbox can link to an account."""
    account = session.exec(
        select(EmailAccount).where(
            EmailAccount.business_id == business.id,
            EmailAccount.email_address == connection.from_email,
            EmailAccount.provider == "smtp",
        )
    ).first()
    if account:
        return account

    has_default = session.exec(
        select(EmailAccount).where(
            EmailAccount.business_id == business.id,
            EmailAccount.is_default == True,
        )
    ).first()

    account = EmailAccount(
        business_id=business.id,
        user_id=user_id,
        provider="smtp",
        email_address=connection.from_email,
        display_name=connection.from_name,
        is_default=has_default is None,
        smtp_config={
            "host": connection.smtp_host,
            "port": connection.smtp_port,
            "username": connection.smtp_username,
            "use_tls": connection.use_tls,
            "use_ssl": connection.use_ssl,
            "from_email": connection.from_email,
            "from_name": connection.from_name,
        },
    )
    session.add(account)
    session.commit()
    session.refresh(account)
    return account


def _text_to_html(text: str) -> str:
    safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return safe.replace("\n", "<br>")


CATEGORIZE_SYSTEM_PROMPT = """You are an email categorisation assistant for a business.
Analyse each email and return a JSON array with one object per email.

Categories (pick ONE):
- action_required: Needs a response or action from the user
- awaiting_reply: User already replied, waiting for the other party
- fyi: Informational, no action needed
- marketing: Newsletters, promotions, marketing emails
- finance: Invoices, payments, receipts, bank notifications
- scheduling: Meeting requests, calendar invites, appointment changes
- spam: Junk, phishing, irrelevant

Priority (1-5):
- 5: Urgent - needs immediate attention (e.g. overdue payment, angry client)
- 4: High - should handle today (e.g. client question, important request)
- 3: Medium - handle this week (e.g. general business correspondence)
- 2: Low - handle when convenient (e.g. FYI emails, non-urgent updates)
- 1: Minimal - can ignore or archive (e.g. marketing, newsletters)

Return ONLY a JSON array. No markdown, no explanation.
Each object must have: message_id, category, priority, summary, suggested_action"""


def analyze_email_batch(messages: List[EmailMessageModel]) -> list:
    """Analyze a batch of emails using gpt-4o-mini for categorisation.

    Failure contract: on a HARD failure (OpenAI 429/timeout/exception, or an
    unparseable response) this returns an EMPTY list rather than fabricated
    fallback categories. Callers must stamp ai_analyzed_at only for the
    message_ids actually present in the returned list — so a hard failure
    stamps nothing and those rows are retried on the next pass (instead of
    being permanently frozen as 'fyi'). An empty return for a non-empty input
    batch therefore means "analysis failed, retry later".
    """
    import logging
    _logger = logging.getLogger("email_analysis")

    if not messages:
        return []

    if not OPENAI_API_KEY:
        from schemas import EmailAnalysis
        return [
            EmailAnalysis(
                message_id=str(m.id),
                category="fyi",
                priority=2,
                summary=m.subject or "No subject",
                suggested_action=None,
            )
            for m in messages
        ]

    email_items = []
    for m in messages:
        email_items.append(
            f"message_id: {str(m.id)}\n"
            f"from_email: {m.from_email or 'Unknown'}\n"
            f"from_name: {m.from_name or 'Unknown'}\n"
            f"subject: {m.subject or '(no subject)'}\n"
            f"snippet: {(m.snippet or '')[:300]}\n"
            f"received_at: {m.received_at.isoformat() if m.received_at else 'unknown'}"
        )

    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": CATEGORIZE_SYSTEM_PROMPT},
                {"role": "user", "content": "Analyze these emails:\n\n" + "\n---\n".join(email_items)},
            ],
            max_tokens=1500,
            temperature=0.1,
        )
        content = (response.choices[0].message.content or "").strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        from schemas import EmailAnalysis
        parsed = json.loads(content)
        results = []
        for item in parsed:
            results.append(
                EmailAnalysis(
                    message_id=item.get("message_id", ""),
                    category=item.get("category", "fyi"),
                    priority=max(1, min(5, int(item.get("priority", 2)))),
                    summary=item.get("summary", ""),
                    suggested_action=item.get("suggested_action"),
                )
            )
        return results
    except Exception as e:
        # Hard failure (e.g. OpenAI 429/timeout, or an unparseable response).
        # Return an empty list — do NOT fabricate fallback 'fyi' categories.
        # Callers stamp ai_analyzed_at only for returned message_ids, so these
        # rows stay un-analysed (ai_analyzed_at = NULL) and get retried next pass.
        _logger.warning(f"Email analysis failed; leaving messages un-analysed for retry: {e}")
        return []


def generate_email_briefing_markdown(
    messages: List[EmailMessageModel],
    business: Business,
) -> str:
    """Generate a markdown briefing for recent emails using gpt-5."""
    if not messages:
        return "No recent emails in the selected period."

    fallback_lines = [
        f"# Email Briefing for {business.name}",
        "",
        f"Total messages: {len(messages)}",
        "",
        "## Recent Emails",
    ]
    for msg in messages[:20]:
        subject = msg.subject or "(no subject)"
        sender = msg.from_email or "Unknown sender"
        fallback_lines.append(f"- {subject} — {sender}")
    fallback_text = "\n".join(fallback_lines)

    if not OPENAI_API_KEY:
        return fallback_text

    # Build structured section from AI analysis data
    priority_actions = []
    awaiting_reply = []
    fyi_items = []
    for msg in messages:
        if msg.ai_category == "action_required" and msg.ai_priority and msg.ai_priority >= 4:
            level = "URGENT" if msg.ai_priority == 5 else "HIGH"
            priority_actions.append(
                f"- **[{level}]** {msg.ai_summary or msg.subject or 'No subject'} — {msg.from_email or 'Unknown'}"
            )
        elif msg.ai_category == "awaiting_reply":
            days_ago = ""
            if msg.received_at:
                delta = (datetime.utcnow() - msg.received_at).days
                days_ago = f" ({delta} day{'s' if delta != 1 else ''} ago)"
                awaiting_reply.append(f"- {msg.subject or 'No subject'} to {msg.from_email or 'Unknown'}{days_ago}")
        elif msg.ai_category in ("fyi", "marketing", "spam"):
            fyi_items.append(msg)

    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        items = []
        for msg in messages[:50]:
            items.append(
                f"From: {msg.from_email or 'Unknown'}\n"
                f"Subject: {msg.subject or '(no subject)'}\n"
                f"Snippet: {msg.snippet or ''}\n"
                f"AI Category: {msg.ai_category or 'unanalyzed'}\n"
                f"AI Priority: {msg.ai_priority or 'N/A'}\n"
            )
        prompt = "\n---\n".join(items)
        response = client.chat.completions.create(
            model="gpt-5",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Write a concise, action-oriented email briefing in markdown. "
                        "Group by urgency. Include key actions, deadlines, and suggested next steps. "
                        "Do not hallucinate. If details are missing, say so explicitly."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Summarize these emails for {business.name}. "
                        "Include key actions, deadlines, and suggested next steps:\n\n"
                        f"{prompt}"
                    ),
                },
            ],
            max_tokens=1200,
            temperature=0.2,
        )
        briefing = response.choices[0].message.content or fallback_text

        # Append structured section
        structured_parts = []
        if priority_actions:
            structured_parts.append("\n## Priority Actions\n" + "\n".join(priority_actions))
        if awaiting_reply:
            structured_parts.append(f"\n## Awaiting Reply ({len(awaiting_reply)})\n" + "\n".join(awaiting_reply))
        if fyi_items:
            structured_parts.append(f"\n## FYI / Can Archive ({len(fyi_items)})\n- {len(fyi_items)} informational/marketing emails")
        if structured_parts:
            briefing += "\n\n---\n" + "\n".join(structured_parts)

        return briefing
    except Exception:
        return fallback_text


def generate_email_reply_draft(message: EmailMessageModel, business: Business) -> Dict[str, str]:
    """Generate a single suggested reply for a message (backwards compat)."""
    subject = message.subject or "Your email"
    reply_subject = f"Re: {subject}"
    fallback_body = (
        f"Hi {message.from_name or 'there'},\n\n"
        "Thanks for your email. I will review and get back to you shortly.\n\n"
        f"Best regards,\n{business.name}"
    )

    if not OPENAI_API_KEY:
        return {"subject": reply_subject, "body_text": fallback_body, "body_html": _text_to_html(fallback_body)}

    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        prompt = (
            f"From: {message.from_email or 'Unknown'}\n"
            f"Subject: {message.subject or '(no subject)'}\n"
            f"Snippet: {message.snippet or ''}\n"
            f"Body:\n{message.body_text or ''}"
        )
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Draft a concise, action-oriented reply. "
                        "Do not hallucinate. If details are missing, say so. "
                        "Return JSON with keys: subject, body_text, body_html."
                    ),
                },
                {"role": "user", "content": f"Draft a reply to this email:\n\n{prompt}"},
            ],
            max_tokens=400,
            temperature=0.3,
        )
        content = response.choices[0].message.content or ""
        body_text = fallback_body
        body_html = _text_to_html(fallback_body)
        if content:
            try:
                data = json.loads(content)
                reply_subject = data.get("subject") or reply_subject
                body_text = data.get("body_text") or fallback_body
                body_html = data.get("body_html") or _text_to_html(body_text)
            except json.JSONDecodeError:
                body_text = content
                body_html = _text_to_html(content)
        return {"subject": reply_subject, "body_text": body_text, "body_html": body_html}
    except Exception:
        return {"subject": reply_subject, "body_text": fallback_body, "body_html": _text_to_html(fallback_body)}


def generate_email_reply_drafts(
    message: EmailMessageModel,
    business: Business,
    user_name: Optional[str] = None,
) -> List[Dict[str, str]]:
    """Generate 3 draft reply options with different tones using gpt-5."""
    import logging
    _logger = logging.getLogger("email_drafts")

    subject = message.subject or "Your email"
    reply_subject = f"Re: {subject}"
    sender_name = message.from_name or "there"
    sign_off_name = user_name or business.name

    fallback = {
        "subject": reply_subject,
        "body_text": (
            f"Hi {sender_name},\n\n"
            "Thanks for your email. I will review and get back to you shortly.\n\n"
            f"Best regards,\n{sign_off_name}"
        ),
        "tone": "professional",
    }
    fallback["body_html"] = _text_to_html(fallback["body_text"])

    if not OPENAI_API_KEY:
        return [fallback]

    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        email_context = (
            f"From: {message.from_email or 'Unknown'}\n"
            f"From Name: {message.from_name or 'Unknown'}\n"
            f"Subject: {message.subject or '(no subject)'}\n"
            f"Snippet: {message.snippet or ''}\n"
            f"Body:\n{message.body_text or message.snippet or ''}"
        )

        response = client.chat.completions.create(
            model="gpt-5",
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"You are a business email assistant for {business.name}. "
                        f"The user's name is {sign_off_name}.\n\n"
                        "Generate exactly 3 reply drafts with different tones:\n"
                        '1. "professional" — Formal, polished, corporate tone.\n'
                        '2. "friendly" — Warm, conversational but business-appropriate.\n'
                        '3. "brief" — Ultra-concise, 2-3 sentences max.\n\n'
                        "Each draft should actually address the email content, "
                        f"be ready to send, and sign off as {sign_off_name}. "
                        "Do not hallucinate details.\n\n"
                        "Return ONLY a JSON array with 3 objects: tone, subject, body_text\n"
                        "No markdown, no backticks, no explanation."
                    ),
                },
                {"role": "user", "content": f"Generate 3 reply drafts for this email:\n\n{email_context}"},
            ],
            max_tokens=1200,
            temperature=0.4,
        )

        content = (response.choices[0].message.content or "").strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1] if "\n" in content else content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        drafts = json.loads(content)
        result = []
        for draft in drafts:
            body_text = draft.get("body_text", "")
            result.append({
                "subject": draft.get("subject", reply_subject),
                "body_text": body_text,
                "body_html": _text_to_html(body_text),
                "tone": draft.get("tone", "professional"),
            })
        return result if result else [fallback]

    except Exception as e:
        _logger.error(f"Multi-tone draft generation error: {e}")
        return [fallback]
