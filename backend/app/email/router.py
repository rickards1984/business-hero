"""Email router entrypoint."""

from typing import Any, Dict, List, Optional
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import hmac
import json
import os
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlmodel import Session, select

from auth import get_user_business_context, require_feature
from db import get_session
from models import EmailAccount, EmailBriefing, EmailConnection, EmailDraft, EmailMessage, EmailOutbox, EmailSyncState
from schemas import (
    EmailConnectionPublic,
    EmailConnectionUpsert,
    EmailTestResponse,
    EmailOutboxItem,
    EmailOutboxListResponse,
    EmailMessageItem,
    EmailMessageListResponse,
    EmailSyncRunResponse,
    EmailBriefingRequest,
    EmailBriefingResponse,
    EmailDraftRequest,
    EmailDraftResponse,
    EmailDraftSendResponse,
    EmailAnalysis,
    EmailAnalyzeResponse,
    EmailDraftOptionsResponse,
)
from .crypto import encrypt_secret
from .service import (
    SupabaseAdminClient,
    get_supabase_admin_client,
    get_business_by_id,
    ensure_email_manager_role,
    send_email_smtp,
    get_default_email_account,
    get_provider_for_account,
    generate_email_briefing_markdown,
    generate_email_reply_draft,
    generate_email_reply_drafts,
    analyze_email_batch,
    get_or_create_smtp_account,
)
from providers.google_gmail import GoogleGmailProvider
from providers.microsoft_graph import MicrosoftGraphProvider
from providers.smtp import SMTPProvider


router = APIRouter(
    prefix="/v1/email",
    tags=["Email"],
    dependencies=[Depends(require_feature("email"))],
)

# Separate router for OAuth callbacks (no auth required - these receive redirects from OAuth providers)
oauth_router = APIRouter(
    prefix="/v1/email",
    tags=["Email OAuth"],
)


class EmailAccountPublic(BaseModel):
    id: str
    business_id: str
    user_id: str
    provider: str
    email_address: str
    display_name: Optional[str] = None
    capabilities: Dict[str, Any] = Field(default_factory=dict)
    is_default: bool
    created_at: str
    updated_at: Optional[str] = None


class EmailAccountsResponse(BaseModel):
    accounts: List[EmailAccountPublic]
    total: int


class SmtpAccountRequest(BaseModel):
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    from_email: str
    from_name: Optional[str] = None
    use_tls: bool = True
    use_ssl: bool = False
    business_id: Optional[str] = None


class SendEmailRequest(BaseModel):
    email_account_id: Optional[str] = None
    to_emails: List[str]
    subject: str
    body_text: Optional[str] = None
    body_html: Optional[str] = None
    invoice_id: Optional[str] = None
    chase_stage: Optional[int] = None


class SendEmailResponse(BaseModel):
    outbox_id: str
    status: str
    provider_message_id: Optional[str] = None
    error: Optional[str] = None


GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_PROFILE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/profile"

MICROSOFT_AUTH_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
MICROSOFT_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
MICROSOFT_PROFILE_URL = "https://graph.microsoft.com/v1.0/me"


def _get_state_secret() -> bytes:
    secret = os.getenv("EMAIL_OAUTH_STATE_SECRET") or os.getenv("EMAIL_ENCRYPTION_KEY")
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="EMAIL_OAUTH_STATE_SECRET is not configured",
        )
    return secret.encode("utf-8")


def _encode_b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("utf-8").rstrip("=")


def _decode_b64(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _sign_state(payload: Dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    sig = hmac.new(_get_state_secret(), raw, hashlib.sha256).digest()
    return f"{_encode_b64(raw)}.{_encode_b64(sig)}"


def _verify_state(state: str) -> Dict[str, Any]:
    try:
        raw_b64, sig_b64 = state.split(".", 1)
        raw = _decode_b64(raw_b64)
        sig = _decode_b64(sig_b64)
        expected = hmac.new(_get_state_secret(), raw, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected):
            raise ValueError("Invalid state signature")
        payload = json.loads(raw.decode("utf-8"))
        exp = payload.get("exp")
        if exp is not None:
            if datetime.utcnow().timestamp() > float(exp):
                raise ValueError("State expired")
        return payload
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _google_scopes(mode: Optional[str]) -> str:
    if mode == "read_basic":
        return "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/calendar.readonly"
    return (
        "https://www.googleapis.com/auth/gmail.readonly "
        "https://www.googleapis.com/auth/gmail.send "
        "https://www.googleapis.com/auth/calendar.readonly "
        "https://www.googleapis.com/auth/calendar.events.readonly "
        "https://www.googleapis.com/auth/calendar.events"
    )


def _microsoft_scopes(mode: Optional[str]) -> str:
    if mode == "read_basic":
        return "offline_access https://graph.microsoft.com/User.Read https://graph.microsoft.com/Mail.ReadBasic"
    return (
        "offline_access https://graph.microsoft.com/User.Read "
        "https://graph.microsoft.com/Mail.Read https://graph.microsoft.com/Mail.Send"
    )


def _frontend_settings_url(provider: str) -> str:
    base_url = os.getenv("FRONTEND_BASE_URL", "https://business-hero.vercel.app").rstrip("/")
    return f"{base_url}/app/settings/email?provider={provider}&success=1"


def build_google_oauth_start_url(auth_ctx: dict, mode: Optional[str]) -> str:
    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
    redirect_uri = os.getenv("GOOGLE_OAUTH_REDIRECT_URI")
    if not client_id or not redirect_uri:
        raise HTTPException(status_code=500, detail="Google OAuth not configured")

    now_ts = int(datetime.utcnow().timestamp())
    state = _sign_state(
        {
            "provider": "google",
            "user_id": auth_ctx["user_id"],
            "business_id": auth_ctx["business_id"],
            "ts": now_ts,
            "exp": now_ts + 600,
            "mode": mode or "read_full",
        }
    )
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "access_type": "offline",
        "prompt": "consent",
        "scope": _google_scopes(mode),
        "state": state,
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def build_microsoft_oauth_start_url(auth_ctx: dict, mode: Optional[str]) -> str:
    client_id = os.getenv("MICROSOFT_OAUTH_CLIENT_ID")
    redirect_uri = os.getenv("MICROSOFT_OAUTH_REDIRECT_URI")
    if not client_id or not redirect_uri:
        raise HTTPException(status_code=500, detail="Microsoft OAuth not configured")

    now_ts = int(datetime.utcnow().timestamp())
    state = _sign_state(
        {
            "provider": "microsoft",
            "user_id": auth_ctx["user_id"],
            "business_id": auth_ctx["business_id"],
            "ts": now_ts,
            "exp": now_ts + 600,
            "mode": mode or "read_full",
        }
    )
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "response_mode": "query",
        "scope": _microsoft_scopes(mode),
        "state": state,
    }
    return f"{MICROSOFT_AUTH_URL}?{urlencode(params)}"


@router.get("/_status")
async def email_status(
    _: dict = Depends(get_user_business_context),
    __: SupabaseAdminClient = Depends(get_supabase_admin_client),
) -> dict:
    return {"ok": True}


def _get_provider(provider_name: str):
    provider = (provider_name or "").lower()
    if provider == "google":
        return GoogleGmailProvider()
    if provider == "microsoft":
        return MicrosoftGraphProvider()
    if provider == "smtp":
        return SMTPProvider()
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported provider: {provider_name}")


def _to_preview(body_text: Optional[str], body_html: Optional[str]) -> str:
    preview = (body_text or body_html or "").strip()
    if len(preview) > 500:
        return preview[:500]
    return preview


async def _fetch_google_profile(access_token: str) -> Dict[str, Any]:
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(GOOGLE_PROFILE_URL, headers=headers)
    if response.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Google profile fetch failed: {response.status_code} {response.text}",
        )
    return response.json()


async def _fetch_microsoft_profile(access_token: str) -> Dict[str, Any]:
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(MICROSOFT_PROFILE_URL, headers=headers)
    if response.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Microsoft profile fetch failed: {response.status_code} {response.text}",
        )
    return response.json()


@router.get("/accounts", response_model=EmailAccountsResponse)
async def list_email_accounts(
    auth_ctx: dict = Depends(get_user_business_context),
    admin: SupabaseAdminClient = Depends(get_supabase_admin_client),
) -> EmailAccountsResponse:
    fields = "id,business_id,user_id,provider,email_address,display_name,capabilities,is_default,created_at,updated_at"
    rows = await admin.fetch_email_accounts(auth_ctx["business_id"], fields=fields) or []
    accounts = [EmailAccountPublic(**row) for row in rows]
    return EmailAccountsResponse(accounts=accounts, total=len(accounts))


@router.post("/accounts/{account_id}/set-default", response_model=EmailAccountPublic)
async def set_default_email_account(
    account_id: str,
    auth_ctx: dict = Depends(get_user_business_context),
    admin: SupabaseAdminClient = Depends(get_supabase_admin_client),
) -> EmailAccountPublic:
    business_id = auth_ctx["business_id"]
    await admin._update("email_accounts", {"is_default": False}, filters={"business_id": business_id})
    updated = await admin._update(
        "email_accounts",
        {"is_default": True},
        filters={"id": account_id, "business_id": business_id},
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email account not found")
    row = updated[0]
    return EmailAccountPublic(
        id=row["id"],
        business_id=row["business_id"],
        user_id=row["user_id"],
        provider=row["provider"],
        email_address=row["email_address"],
        display_name=row.get("display_name"),
        capabilities=row.get("capabilities") or {},
        is_default=row["is_default"],
        created_at=row["created_at"],
        updated_at=row.get("updated_at"),
    )


@router.post("/accounts/smtp", response_model=EmailAccountPublic)
async def upsert_smtp_account(
    data: SmtpAccountRequest,
    auth_ctx: dict = Depends(get_user_business_context),
    admin: SupabaseAdminClient = Depends(get_supabase_admin_client),
) -> EmailAccountPublic:
    if data.business_id and data.business_id != auth_ctx["business_id"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Business access denied")

    smtp_config = {
        "host": data.smtp_host,
        "port": data.smtp_port,
        "username": data.smtp_username,
        "password_ciphertext": encrypt_secret(data.smtp_password),
        "use_tls": data.use_tls,
        "use_ssl": data.use_ssl,
        "from_email": data.from_email,
        "from_name": data.from_name,
    }

    payload = {
        "business_id": auth_ctx["business_id"],
        "user_id": auth_ctx["user_id"],
        "provider": "smtp",
        "email_address": data.from_email,
        "display_name": data.from_name,
        "capabilities": {"send": True},
        "smtp_config": smtp_config,
        "is_default": False,
    }
    rows = await admin.upsert_email_accounts(payload)
    row = rows[0] if rows else payload
    return EmailAccountPublic(
        id=row["id"],
        business_id=row["business_id"],
        user_id=row["user_id"],
        provider=row["provider"],
        email_address=row["email_address"],
        display_name=row.get("display_name"),
        capabilities=row.get("capabilities") or {},
        is_default=row.get("is_default", False),
        created_at=row.get("created_at", ""),
        updated_at=row.get("updated_at"),
    )


@router.delete("/accounts/{account_id}")
async def delete_email_account(
    account_id: str,
    auth_ctx: dict = Depends(get_user_business_context),
    admin: SupabaseAdminClient = Depends(get_supabase_admin_client),
):
    """Disconnect/delete an email account."""
    business_id = auth_ctx["business_id"]
    
    # First fetch the account to get details for the response
    account = await admin.fetch_email_account(
        business_id=business_id,
        account_id=account_id,
        fields="id,provider,email_address",
    )
    
    if not account:
        raise HTTPException(status_code=404, detail="Email account not found")
    
    # Delete it via Supabase admin client
    deleted = await admin._delete("email_accounts", filters={"id": account_id, "business_id": business_id})
    
    if not deleted:
        raise HTTPException(status_code=404, detail="Email account not found or already deleted")
    
    return {
        "success": True,
        "message": f"Disconnected {account['provider']} account {account['email_address']}"
    }


@router.post("/send", response_model=SendEmailResponse)
async def send_email(
    data: SendEmailRequest,
    auth_ctx: dict = Depends(get_user_business_context),
    admin: SupabaseAdminClient = Depends(get_supabase_admin_client),
) -> SendEmailResponse:
    fields = (
        "id,business_id,user_id,provider,email_address,display_name,capabilities,is_default,"
        "token_ciphertext,refresh_token_ciphertext,token_expires_at,smtp_config"
    )
    business_id = auth_ctx["business_id"]

    account_row = None
    if data.email_account_id:
        account_row = await admin.fetch_email_account(
            business_id=business_id,
            account_id=data.email_account_id,
            fields=fields,
        )
    if not account_row:
        account_row = await admin.fetch_email_account(
            business_id=business_id,
            is_default=True,
            fields=fields,
        )
    if not account_row:
        account_row = await admin.fetch_email_account(
            business_id=business_id,
            fields=fields,
        )
    if not account_row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Email account not found")

    account = SimpleNamespace(**account_row)
    preview = _to_preview(data.body_text, data.body_html)

    outbox_rows = await admin.insert_email_outbox(
        {
            "business_id": business_id,
            "email_account_id": account_row["id"],
            "invoice_id": data.invoice_id,
            "chase_stage": data.chase_stage,
            "to_emails": data.to_emails,
            "subject": data.subject,
            "body_preview": preview,
            "status": "queued",
        }
    )
    outbox = outbox_rows[0] if outbox_rows else None
    outbox_id = outbox["id"] if outbox else ""

    provider = _get_provider(account_row["provider"])
    try:
        result = provider.send_email(
            account=account,
            to_emails=data.to_emails,
            subject=data.subject,
            body_text=data.body_text,
            body_html=data.body_html,
        )
        provider_message_id = getattr(result, "provider_message_id", None)
        await admin.update_email_outbox(
            outbox_id,
            {
                "status": "sent",
                "sent_at": datetime.utcnow().isoformat(),
                "provider_message_id": provider_message_id,
                "error": None,
            },
        )
        if data.invoice_id and data.chase_stage is not None:
            await admin._update(
                "invoices",
                {"chase_stage": data.chase_stage},
                filters={"id": data.invoice_id, "business_id": business_id},
            )
        return SendEmailResponse(
            outbox_id=outbox_id,
            status="sent",
            provider_message_id=provider_message_id,
        )
    except Exception as exc:
        await admin.update_email_outbox(
            outbox_id,
            {
                "status": "failed",
                "error": str(exc),
            },
        )
        return SendEmailResponse(outbox_id=outbox_id, status="failed", error=str(exc))


@router.get("/connection", response_model=EmailConnectionPublic)
async def get_email_connection(
    auth_ctx=Depends(get_user_business_context),
    admin: SupabaseAdminClient = Depends(get_supabase_admin_client),
):
    """Get email connection settings for the current business."""
    fields = "id,business_id,provider,smtp_config,created_at,updated_at"
    rows = await admin._request(
        "GET",
        "email_accounts",
        params={
            "select": fields,
            "business_id": f"eq.{auth_ctx['business_id']}",
            "provider": "eq.smtp",
            "limit": "1",
        },
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Email connection not found")
    account = rows[0]
    smtp_config = account.get("smtp_config") or {}

    return EmailConnectionPublic(
        id=str(account["id"]),
        business_id=str(account["business_id"]),
        provider=account.get("provider") or "smtp",
        smtp_host=smtp_config.get("host") or "",
        smtp_port=int(smtp_config.get("port") or 0),
        smtp_username=smtp_config.get("username") or "",
        from_email=smtp_config.get("from_email") or "",
        from_name=smtp_config.get("from_name"),
        use_tls=bool(smtp_config.get("use_tls", True)),
        use_ssl=bool(smtp_config.get("use_ssl", False)),
        is_enabled=bool(smtp_config.get("is_enabled", True)),
        created_at=account.get("created_at"),
        updated_at=account.get("updated_at"),
    )


@router.put("/connection", response_model=EmailConnectionPublic)
async def upsert_email_connection(
    data: EmailConnectionUpsert,
    auth_ctx=Depends(get_user_business_context),
    admin: SupabaseAdminClient = Depends(get_supabase_admin_client),
    session: Session = Depends(get_session),
):
    """Create or update email connection settings."""
    ensure_email_manager_role(auth_ctx["user_id"], auth_ctx["business_id"], session)
    encrypted_password = encrypt_secret(data.smtp_password)

    smtp_config = {
        "host": data.smtp_host,
        "port": data.smtp_port,
        "username": data.smtp_username,
        "password_ciphertext": encrypted_password,
        "from_email": data.from_email,
        "from_name": data.from_name,
        "use_tls": data.use_tls,
        "use_ssl": data.use_ssl,
        "is_enabled": data.is_enabled,
    }

    existing_default = await admin.fetch_email_account(
        business_id=auth_ctx["business_id"],
        fields="id,is_default",
        is_default=True,
    )

    rows = await admin.upsert_email_accounts(
        {
            "provider": "smtp",
            "business_id": auth_ctx["business_id"],
            "user_id": auth_ctx["user_id"],
            "email_address": data.from_email,
            "display_name": data.from_name,
            "capabilities": {"send": True},
            "smtp_config": smtp_config,
            "is_default": existing_default is None,
        }
    )
    row = rows[0] if rows else {}
    smtp_config = row.get("smtp_config") or smtp_config

    return EmailConnectionPublic(
        id=str(row.get("id")),
        business_id=str(row.get("business_id")),
        provider=row.get("provider") or "smtp",
        smtp_host=smtp_config.get("host") or "",
        smtp_port=int(smtp_config.get("port") or 0),
        smtp_username=smtp_config.get("username") or "",
        from_email=smtp_config.get("from_email") or "",
        from_name=smtp_config.get("from_name"),
        use_tls=bool(smtp_config.get("use_tls", True)),
        use_ssl=bool(smtp_config.get("use_ssl", False)),
        is_enabled=bool(smtp_config.get("is_enabled", True)),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


@router.post("/test", response_model=EmailTestResponse)
async def send_test_email(
    request: Request,
    auth_ctx=Depends(get_user_business_context),
    admin: SupabaseAdminClient = Depends(get_supabase_admin_client),
):
    """Send a test email to the logged-in user's email address."""
    user_email = getattr(request.state, "user_email", None)
    if not user_email:
        raise HTTPException(status_code=400, detail="User email not found")

    fields = "id,business_id,provider,email_address,smtp_config"
    rows = await admin._request(
        "GET",
        "email_accounts",
        params={
            "select": fields,
            "business_id": f"eq.{auth_ctx['business_id']}",
            "provider": "eq.smtp",
            "limit": "1",
        },
    )
    if not rows:
        raise HTTPException(status_code=400, detail="Email connection not configured or disabled")
    account_row = rows[0]
    smtp_config = account_row.get("smtp_config") or {}
    if not smtp_config.get("password_ciphertext"):
        raise HTTPException(status_code=400, detail="Email connection not configured or disabled")

    subject = "Business Hero - Test Email"
    body = "Hello,\n\nThis is a test email from Business Hero.\n\nBest regards,\nBusiness Hero"

    outbox_rows = await admin.insert_email_outbox(
        {
            "business_id": auth_ctx["business_id"],
            "email_account_id": account_row["id"],
            "invoice_id": None,
            "chase_stage": None,
            "to_emails": [user_email],
            "subject": subject,
            "body_preview": body,
            "status": "queued",
        }
    )
    outbox_id = outbox_rows[0]["id"] if outbox_rows else ""

    provider = SMTPProvider()
    account = SimpleNamespace(**account_row)
    try:
        provider.send_email(
            account=account,
            to_emails=[user_email],
            subject=subject,
            body_text=body,
            body_html=None,
        )
        await admin.update_email_outbox(
            outbox_id,
            {"status": "sent", "sent_at": datetime.utcnow().isoformat()},
        )
        return EmailTestResponse(success=True, message="Test email sent", outbox_id=str(outbox_id))
    except Exception as exc:
        await admin.update_email_outbox(outbox_id, {"status": "failed", "error": str(exc)})
        return EmailTestResponse(success=False, message=str(exc), outbox_id=str(outbox_id))


@router.get("/outbox", response_model=EmailOutboxListResponse)
async def list_email_outbox(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    auth_ctx=Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """List email outbox records for the current business."""
    business = get_business_by_id(session, auth_ctx["business_id"])
    statement = select(EmailOutbox).where(EmailOutbox.business_id == business.id)
    if status_filter:
        statement = statement.where(EmailOutbox.status == status_filter)
    statement = statement.order_by(EmailOutbox.created_at.desc()).limit(limit)
    rows = session.exec(statement).all()

    items = [
        EmailOutboxItem(
            id=str(row.id),
            business_id=str(row.business_id),
            invoice_id=str(row.invoice_id) if row.invoice_id else None,
            to_email=", ".join(row.to_emails or []),
            subject=row.subject,
            body=row.body_preview,
            chase_stage=row.chase_stage,
            status=row.status,
            error_message=row.error,
            sent_at=row.sent_at,
            created_at=row.created_at,
        )
        for row in rows
    ]

    return EmailOutboxListResponse(emails=items, total=len(items))


@router.get("/messages", response_model=EmailMessageListResponse)
async def list_email_messages(
    email_account_id: Optional[str] = Query(default=None),
    folder: Optional[str] = Query(default="INBOX"),
    unread_only: Optional[bool] = Query(default=None),
    category: Optional[str] = Query(default=None, description="Filter by AI category"),
    priority_min: Optional[int] = Query(default=None, ge=1, le=5, description="Minimum AI priority"),
    sort_by: Optional[str] = Query(default="received_at", description="Sort by: received_at, ai_priority"),
    limit: int = Query(default=50, ge=1, le=200),
    auth_ctx=Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """List cached email messages for the current business."""
    business = get_business_by_id(session, auth_ctx["business_id"])
    statement = select(EmailMessage).where(EmailMessage.business_id == business.id)
    if email_account_id:
        statement = statement.where(EmailMessage.email_account_id == email_account_id)
    if folder:
        statement = statement.where(EmailMessage.folder == folder)
    if unread_only is True:
        statement = statement.where(EmailMessage.is_unread == True)
    if category:
        statement = statement.where(EmailMessage.ai_category == category)
    if priority_min is not None:
        statement = statement.where(EmailMessage.ai_priority >= priority_min)

    if sort_by == "ai_priority":
        statement = statement.order_by(EmailMessage.ai_priority.desc().nullslast(), EmailMessage.received_at.desc())
    else:
        statement = statement.order_by(EmailMessage.received_at.desc())

    statement = statement.limit(limit)
    rows = session.exec(statement).all()

    items = [
        EmailMessageItem(
            id=str(row.id),
            business_id=str(row.business_id),
            email_account_id=str(row.email_account_id),
            provider_message_id=row.provider_message_id,
            provider_thread_id=row.provider_thread_id,
            folder=row.folder,
            from_email=row.from_email,
            from_name=row.from_name,
            to_emails=row.to_emails,
            cc_emails=row.cc_emails,
            subject=row.subject,
            snippet=row.snippet,
            received_at=row.received_at,
            is_unread=row.is_unread,
            has_attachments=row.has_attachments,
            labels=row.labels,
            ai_category=row.ai_category,
            ai_priority=row.ai_priority,
            ai_summary=row.ai_summary,
            ai_suggested_action=row.ai_suggested_action,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row in rows
    ]

    return EmailMessageListResponse(messages=items, total=len(items))


@router.post("/sync/run", response_model=EmailSyncRunResponse)
async def run_email_sync(
    auth_ctx=Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """Run inbox sync for the default email account."""
    business = get_business_by_id(session, auth_ctx["business_id"])
    account = get_default_email_account(session, business)
    provider = get_provider_for_account(account)

    sync_state = session.exec(
        select(EmailSyncState).where(EmailSyncState.email_account_id == account.id)
    ).first()
    if not sync_state:
        sync_state = EmailSyncState(email_account_id=account.id, cursor={})
        session.add(sync_state)
        session.commit()
        session.refresh(sync_state)

    result = provider.sync_inbox_changes(account=account, cursor=sync_state.cursor or {})
    message_count = 0

    for msg in result.messages:
        existing = session.exec(
            select(EmailMessage).where(
                EmailMessage.email_account_id == account.id,
                EmailMessage.provider_message_id == msg.provider_message_id,
            )
        ).first()
        if existing:
            existing.provider_thread_id = msg.provider_thread_id
            existing.folder = msg.folder
            existing.from_email = msg.from_email
            existing.from_name = msg.from_name
            existing.to_emails = msg.to_emails
            existing.cc_emails = msg.cc_emails
            existing.subject = msg.subject
            existing.snippet = msg.snippet
            existing.received_at = msg.received_at
            existing.is_unread = msg.is_unread
            existing.has_attachments = msg.has_attachments
            existing.labels = msg.labels
            existing.body_text = msg.body_text
            existing.body_html = msg.body_html
            existing.raw_headers = msg.raw_headers or {}
            existing.updated_at = datetime.utcnow()
            session.add(existing)
        else:
            record = EmailMessage(
                business_id=business.id,
                email_account_id=account.id,
                provider_message_id=msg.provider_message_id,
                provider_thread_id=msg.provider_thread_id,
                folder=msg.folder,
                from_email=msg.from_email,
                from_name=msg.from_name,
                to_emails=msg.to_emails,
                cc_emails=msg.cc_emails,
                subject=msg.subject,
                snippet=msg.snippet,
                received_at=msg.received_at,
                is_unread=msg.is_unread,
                has_attachments=msg.has_attachments,
                labels=msg.labels,
                body_text=msg.body_text,
                body_html=msg.body_html,
                raw_headers=msg.raw_headers or {},
            )
            session.add(record)
        message_count += 1

    sync_state.cursor = result.cursor or {}
    sync_state.last_synced_at = datetime.utcnow()
    sync_state.last_error = None
    session.add(sync_state)
    session.commit()

    # Auto-analyze un-analyzed messages (limit 30 per sync)
    if message_count > 0:
        try:
            unanalyzed = session.exec(
                select(EmailMessage)
                .where(
                    EmailMessage.business_id == business.id,
                    EmailMessage.ai_analyzed_at == None,
                )
                .order_by(EmailMessage.received_at.desc())
                .limit(30)
            ).all()
            if unanalyzed:
                from sqlalchemy import text as sa_text
                batch_size = 10
                for i in range(0, len(unanalyzed), batch_size):
                    batch = unanalyzed[i : i + batch_size]
                    analyses = analyze_email_batch(batch)
                    for analysis in analyses:
                        session.execute(
                            sa_text("""
                                UPDATE email_messages
                                SET ai_category = :category, ai_priority = :priority,
                                    ai_summary = :summary, ai_suggested_action = :action,
                                    ai_analyzed_at = NOW()
                                WHERE id = :id AND business_id = :business_id
                            """),
                            {
                                "category": analysis.category,
                                "priority": analysis.priority,
                                "summary": analysis.summary,
                                "action": analysis.suggested_action,
                                "id": analysis.message_id,
                                "business_id": str(business.id),
                            },
                        )
                session.commit()
        except Exception:
            pass  # Don't fail sync if analysis fails

    return EmailSyncRunResponse(
        email_account_id=str(account.id),
        synced=True,
        message_count=message_count,
        cursor=sync_state.cursor,
    )


# How recently emails must have been synced before we consider the cache
# "fresh" and skip scheduling a background sync. Tunable.
EMAIL_SYNC_FRESHNESS_MINUTES = 15


class EmailSyncEnsureResponse(BaseModel):
    """Live-computed sync status for the cache-first email load path.

    `sync_status` is derived on every request from row_count + last_synced_at;
    it is NEVER read from or written to the email_sync_states.sync_status column.
    """
    sync_status: str  # 'empty' | 'fresh' | 'syncing'
    last_synced_at: Optional[str] = None
    scheduled: bool


@router.post("/sync/ensure", response_model=EmailSyncEnsureResponse)
async def ensure_email_sync(
    background_tasks: BackgroundTasks,
    auth_ctx=Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """Cache-first trigger: schedule a background email sync only when the
    locally-cached emails are missing or stale. Returns instantly; the actual
    sync runs off-request so a page load never blocks on Gmail/OpenAI.

    Status is computed live, never persisted:
      - 'empty'   : no email account connected (nothing to sync)
      - 'fresh'   : cached emails exist and were synced within the threshold
      - 'syncing' : a background sync was just scheduled (cache empty or stale)
    """
    business = get_business_by_id(session, auth_ctx["business_id"])

    # 1. Resolve the default email account. If none is connected, there is
    #    nothing to sync — report 'empty' rather than raising.
    try:
        account = get_default_email_account(session, business)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_404_NOT_FOUND:
            return EmailSyncEnsureResponse(
                sync_status="empty",
                last_synced_at=None,
                scheduled=False,
            )
        raise

    # 2. Count locally-cached messages for this business.
    row_count = session.exec(
        select(func.count()).select_from(EmailMessage).where(
            EmailMessage.business_id == business.id
        )
    ).one()

    # 3. Read last_synced_at for the default account.
    sync_state = session.exec(
        select(EmailSyncState).where(EmailSyncState.email_account_id == account.id)
    ).first()
    last_synced_at = sync_state.last_synced_at if sync_state else None

    # Freshness check — normalise naive timestamps to UTC for a safe compare.
    is_fresh = False
    if last_synced_at is not None:
        ls = last_synced_at
        if ls.tzinfo is None:
            ls = ls.replace(tzinfo=timezone.utc)
        is_fresh = (datetime.now(timezone.utc) - ls) <= timedelta(
            minutes=EMAIL_SYNC_FRESHNESS_MINUTES
        )

    last_synced_iso = last_synced_at.isoformat() if last_synced_at else None

    # 4. Decide: fresh cache with rows → do nothing; otherwise schedule a
    #    background sync. We return 'syncing' in the same response that
    #    schedules the task so the frontend can begin polling.
    if row_count > 0 and is_fresh:
        return EmailSyncEnsureResponse(
            sync_status="fresh",
            last_synced_at=last_synced_iso,
            scheduled=False,
        )

    # _sync_email_for_business is a SYNCHRONOUS callable that opens its own
    # isolated DB session; scheduling it via BackgroundTasks runs it in
    # Starlette's threadpool (off the event loop), so its blocking provider
    # client cannot stall other requests.
    from services.background_sync import _sync_email_for_business

    background_tasks.add_task(_sync_email_for_business, str(business.id))

    return EmailSyncEnsureResponse(
        sync_status="syncing",
        last_synced_at=last_synced_iso,
        scheduled=True,
    )


@router.post("/sync/inbox", response_model=EmailSyncRunResponse)
async def sync_email_inbox(
    auth_ctx=Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """Sync inbox for the default email account."""
    business = get_business_by_id(session, auth_ctx["business_id"])
    account = get_default_email_account(session, business)
    provider = get_provider_for_account(account)

    sync_state = session.exec(
        select(EmailSyncState).where(EmailSyncState.email_account_id == account.id)
    ).first()
    if not sync_state:
        sync_state = EmailSyncState(email_account_id=account.id, cursor={})
        session.add(sync_state)
        session.commit()
        session.refresh(sync_state)

    try:
        result = provider.sync_inbox_changes(account=account, cursor=sync_state.cursor or {})
    except Exception as exc:
        sync_state.last_error = str(exc)
        session.add(sync_state)
        session.commit()
        raise HTTPException(status_code=500, detail=str(exc))

    message_count = 0
    for msg in result.messages:
        existing = session.exec(
            select(EmailMessage).where(
                EmailMessage.email_account_id == account.id,
                EmailMessage.provider_message_id == msg.provider_message_id,
            )
        ).first()
        if existing:
            existing.provider_thread_id = msg.provider_thread_id
            existing.folder = msg.folder
            existing.from_email = msg.from_email
            existing.from_name = msg.from_name
            existing.to_emails = msg.to_emails
            existing.cc_emails = msg.cc_emails
            existing.subject = msg.subject
            existing.snippet = msg.snippet
            existing.received_at = msg.received_at
            existing.is_unread = msg.is_unread
            existing.has_attachments = msg.has_attachments
            existing.labels = msg.labels
            existing.body_text = msg.body_text
            existing.body_html = msg.body_html
            existing.raw_headers = msg.raw_headers or {}
            existing.updated_at = datetime.utcnow()
            session.add(existing)
        else:
            record = EmailMessage(
                business_id=business.id,
                email_account_id=account.id,
                provider_message_id=msg.provider_message_id,
                provider_thread_id=msg.provider_thread_id,
                folder=msg.folder,
                from_email=msg.from_email,
                from_name=msg.from_name,
                to_emails=msg.to_emails,
                cc_emails=msg.cc_emails,
                subject=msg.subject,
                snippet=msg.snippet,
                received_at=msg.received_at,
                is_unread=msg.is_unread,
                has_attachments=msg.has_attachments,
                labels=msg.labels,
                body_text=msg.body_text,
                body_html=msg.body_html,
                raw_headers=msg.raw_headers or {},
            )
            session.add(record)
        message_count += 1

    sync_state.cursor = result.cursor or {}
    sync_state.last_synced_at = datetime.utcnow()
    sync_state.last_error = None
    session.add(sync_state)
    session.commit()

    return EmailSyncRunResponse(
        email_account_id=str(account.id),
        synced=True,
        message_count=message_count,
        cursor=sync_state.cursor,
    )


@router.post("/briefings/generate", response_model=EmailBriefingResponse)
async def generate_email_briefing(
    data: Optional[EmailBriefingRequest] = None,
    hours: int = Query(default=24, ge=1, le=168),
    email_account_id: Optional[str] = Query(default=None),
    auth_ctx=Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """Generate a markdown briefing from recent email messages."""
    business = get_business_by_id(session, auth_ctx["business_id"])
    account = None
    requested_account_id = data.email_account_id if data and data.email_account_id else email_account_id
    if requested_account_id:
        account = session.exec(
            select(EmailAccount).where(
                EmailAccount.id == requested_account_id,
                EmailAccount.business_id == business.id,
            )
        ).first()
        if not account:
            raise HTTPException(status_code=404, detail="Email account not found")
    else:
        account = get_default_email_account(session, business)

    period_end = datetime.utcnow()
    period_hours = data.hours if data else hours
    period_start = period_end - timedelta(hours=period_hours)

    statement = select(EmailMessage).where(
        EmailMessage.business_id == business.id,
        EmailMessage.received_at >= period_start,
        EmailMessage.received_at <= period_end,
        EmailMessage.email_account_id == account.id,
    )
    statement = statement.order_by(EmailMessage.received_at.desc()).limit(200)
    messages = session.exec(statement).all()

    briefing_markdown = generate_email_briefing_markdown(messages, business)
    stats = {
        "total_messages": len(messages),
        "unread_messages": sum(1 for m in messages if m.is_unread),
    }

    briefing = EmailBriefing(
        business_id=business.id,
        user_id=auth_ctx["user_id"],
        email_account_id=account.id,
        period_start=period_start,
        period_end=period_end,
        briefing_markdown=briefing_markdown,
        stats=stats,
    )
    session.add(briefing)
    session.commit()
    session.refresh(briefing)

    return EmailBriefingResponse(
        id=str(briefing.id),
        business_id=str(briefing.business_id),
        user_id=str(briefing.user_id),
        email_account_id=str(briefing.email_account_id) if briefing.email_account_id else None,
        period_start=briefing.period_start,
        period_end=briefing.period_end,
        briefing_markdown=briefing.briefing_markdown,
        created_at=briefing.created_at,
    )


@router.get("/briefings/latest", response_model=EmailBriefingResponse)
async def get_latest_email_briefing(
    auth_ctx=Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """Fetch the latest email briefing for the business."""
    business = get_business_by_id(session, auth_ctx["business_id"])
    briefing = session.exec(
        select(EmailBriefing)
        .where(EmailBriefing.business_id == business.id)
        .order_by(EmailBriefing.created_at.desc())
        .limit(1)
    ).first()
    if not briefing:
        raise HTTPException(status_code=404, detail="No briefings found")

    return EmailBriefingResponse(
        id=str(briefing.id),
        business_id=str(briefing.business_id),
        user_id=str(briefing.user_id),
        email_account_id=str(briefing.email_account_id) if briefing.email_account_id else None,
        period_start=briefing.period_start,
        period_end=briefing.period_end,
        briefing_markdown=briefing.briefing_markdown,
        created_at=briefing.created_at,
    )


class EmailAnalyzeRequest(BaseModel):
    message_ids: List[str] = Field(default_factory=list)


@router.post("/analyze", response_model=EmailAnalyzeResponse)
async def analyze_emails(
    data: EmailAnalyzeRequest,
    auth_ctx=Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """Analyze emails with AI: categorise, score priority, summarise."""
    from sqlalchemy import text as sa_text

    business = get_business_by_id(session, auth_ctx["business_id"])

    if data.message_ids:
        statement = select(EmailMessage).where(
            EmailMessage.business_id == business.id,
            EmailMessage.id.in_(data.message_ids),
        )
    else:
        statement = (
            select(EmailMessage)
            .where(
                EmailMessage.business_id == business.id,
                EmailMessage.ai_analyzed_at == None,
            )
            .order_by(EmailMessage.received_at.desc())
            .limit(50)
        )

    messages = session.exec(statement).all()
    if not messages:
        return EmailAnalyzeResponse(analyses=[], analyzed_count=0)

    all_analyses: List[EmailAnalysis] = []
    batch_size = 10
    for i in range(0, len(messages), batch_size):
        batch = messages[i : i + batch_size]
        batch_results = analyze_email_batch(batch)
        all_analyses.extend(batch_results)

    for analysis in all_analyses:
        session.execute(
            sa_text("""
                UPDATE email_messages
                SET ai_category = :category, ai_priority = :priority,
                    ai_summary = :summary, ai_suggested_action = :action,
                    ai_analyzed_at = NOW()
                WHERE id = :id AND business_id = :business_id
            """),
            {
                "category": analysis.category,
                "priority": analysis.priority,
                "summary": analysis.summary,
                "action": analysis.suggested_action,
                "id": analysis.message_id,
                "business_id": str(business.id),
            },
        )
    session.commit()

    return EmailAnalyzeResponse(analyses=all_analyses, analyzed_count=len(all_analyses))


@router.post("/drafts/generate-options", response_model=EmailDraftOptionsResponse)
async def generate_email_draft_options(
    data: EmailDraftRequest,
    auth_ctx=Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """Generate 3 draft reply options with different tones."""
    from sqlalchemy import text as sa_text

    business = get_business_by_id(session, auth_ctx["business_id"])
    message = session.exec(
        select(EmailMessage).where(
            EmailMessage.id == data.email_message_id,
            EmailMessage.business_id == business.id,
        )
    ).first()
    if not message:
        raise HTTPException(status_code=404, detail="Email message not found")

    to_emails = data.to_emails or ([message.from_email] if message.from_email else [])
    if not to_emails:
        raise HTTPException(status_code=400, detail="Recipient email not available")

    user_name = None
    try:
        result = session.execute(
            sa_text("SELECT full_name, display_name FROM profiles WHERE id = :user_id"),
            {"user_id": auth_ctx["user_id"]},
        )
        row = result.fetchone()
        if row:
            user_name = row[1] or row[0]
    except Exception:
        pass

    draft_options = generate_email_reply_drafts(message, business, user_name)

    saved_drafts: List[EmailDraftResponse] = []
    for option in draft_options:
        draft = EmailDraft(
            business_id=business.id,
            email_message_id=message.id,
            to_emails=to_emails,
            subject=option["subject"],
            body_text=option.get("body_text"),
            body_html=option.get("body_html"),
            status="draft",
        )
        session.add(draft)
        session.commit()
        session.refresh(draft)
        saved_drafts.append(
            EmailDraftResponse(
                id=str(draft.id),
                business_id=str(draft.business_id),
                email_message_id=str(draft.email_message_id),
                to_emails=draft.to_emails,
                subject=draft.subject,
                body_text=draft.body_text,
                body_html=draft.body_html,
                status=draft.status,
                provider_message_id=draft.provider_message_id,
                tone=option.get("tone", "professional"),
                created_at=draft.created_at,
                updated_at=draft.updated_at,
            )
        )

    return EmailDraftOptionsResponse(drafts=saved_drafts, message_id=str(message.id))


@router.post("/drafts/generate", response_model=EmailDraftResponse)
async def generate_email_draft(
    data: EmailDraftRequest,
    auth_ctx=Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """Generate a suggested reply draft for an email message."""
    business = get_business_by_id(session, auth_ctx["business_id"])
    message = session.exec(
        select(EmailMessage).where(
            EmailMessage.id == data.email_message_id,
            EmailMessage.business_id == business.id,
        )
    ).first()
    if not message:
        raise HTTPException(status_code=404, detail="Email message not found")

    to_emails = data.to_emails or ([message.from_email] if message.from_email else [])
    if not to_emails:
        raise HTTPException(status_code=400, detail="Recipient email not available")

    draft_content = generate_email_reply_draft(message, business)
    draft = EmailDraft(
        business_id=business.id,
        email_message_id=message.id,
        to_emails=to_emails,
        subject=draft_content["subject"],
        body_text=draft_content.get("body_text"),
        body_html=draft_content.get("body_html"),
        status="draft",
    )
    session.add(draft)
    session.commit()
    session.refresh(draft)

    return EmailDraftResponse(
        id=str(draft.id),
        business_id=str(draft.business_id),
        email_message_id=str(draft.email_message_id),
        to_emails=draft.to_emails,
        subject=draft.subject,
        body_text=draft.body_text,
        body_html=draft.body_html,
        status=draft.status,
        provider_message_id=draft.provider_message_id,
        created_at=draft.created_at,
        updated_at=draft.updated_at,
    )


@router.post("/drafts/{draft_id}/send", response_model=EmailDraftSendResponse)
async def send_email_draft(
    draft_id: str,
    auth_ctx=Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """Send an approved draft using the provider."""
    business = get_business_by_id(session, auth_ctx["business_id"])
    draft = session.exec(
        select(EmailDraft).where(
            EmailDraft.id == draft_id,
            EmailDraft.business_id == business.id,
        )
    ).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Email draft not found")

    message = session.exec(
        select(EmailMessage).where(
            EmailMessage.id == draft.email_message_id,
            EmailMessage.business_id == business.id,
        )
    ).first()
    if not message:
        raise HTTPException(status_code=404, detail="Email message not found")

    account = session.exec(
        select(EmailAccount).where(
            EmailAccount.id == message.email_account_id,
            EmailAccount.business_id == business.id,
        )
    ).first()
    if not account:
        account = get_default_email_account(session, business)

    provider = get_provider_for_account(account)
    body_preview = draft.body_text or draft.body_html or ""

    try:
        result = provider.send_email(
            account=account,
            to_emails=draft.to_emails,
            subject=draft.subject,
            body_text=draft.body_text,
            body_html=draft.body_html,
            in_reply_to=message.provider_message_id,
        )

        outbox = EmailOutbox(
            business_id=business.id,
            email_account_id=account.id,
            invoice_id=None,
            chase_stage=None,
            to_emails=draft.to_emails,
            subject=draft.subject,
            body_preview=body_preview,
            provider_message_id=result.provider_message_id,
            status="sent",
            sent_at=datetime.utcnow(),
        )
        session.add(outbox)

        draft.status = "sent"
        draft.provider_message_id = result.provider_message_id
        draft.updated_at = datetime.utcnow()
        session.add(draft)

        session.commit()
        session.refresh(outbox)

        return EmailDraftSendResponse(
            success=True,
            message="Draft sent",
            outbox_id=str(outbox.id),
            provider_message_id=result.provider_message_id,
            status=draft.status,
        )
    except Exception as exc:
        outbox = EmailOutbox(
            business_id=business.id,
            email_account_id=account.id,
            invoice_id=None,
            chase_stage=None,
            to_emails=draft.to_emails,
            subject=draft.subject,
            body_preview=body_preview,
            status="failed",
            error=str(exc),
        )
        session.add(outbox)
        session.commit()
        session.refresh(outbox)

        return EmailDraftSendResponse(
            success=False,
            message=str(exc),
            outbox_id=str(outbox.id),
            status="failed",
        )


@router.get("/oauth/google/start")
async def google_oauth_start(
    auth_ctx: dict = Depends(get_user_business_context),
    mode: Optional[str] = Query(default=None),
) -> RedirectResponse:
    return RedirectResponse(url=build_google_oauth_start_url(auth_ctx, mode))


@oauth_router.get("/oauth/google/callback")
async def google_oauth_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    admin: SupabaseAdminClient = Depends(get_supabase_admin_client),
):
    if error:
        raise HTTPException(status_code=400, detail=error)
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")

    payload = _verify_state(state)
    if payload.get("provider") != "google":
        raise HTTPException(status_code=400, detail="Invalid state provider")

    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
    redirect_uri = os.getenv("GOOGLE_OAUTH_REDIRECT_URI")
    if not client_id or not client_secret or not redirect_uri:
        raise HTTPException(status_code=500, detail="Google OAuth not configured")

    token_payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }
    async with httpx.AsyncClient(timeout=20) as client:
        token_response = await client.post(GOOGLE_TOKEN_URL, data=token_payload)
    if token_response.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail=f"Google token exchange failed: {token_response.status_code} {token_response.text}",
        )
    token_data = token_response.json()
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    expires_in = int(token_data.get("expires_in", 0))
    if not access_token:
        raise HTTPException(status_code=400, detail="Google access token missing")

    profile = await _fetch_google_profile(access_token)
    email_address = profile.get("emailAddress")
    if not email_address:
        raise HTTPException(status_code=400, detail="Google profile email missing")

    token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in or 0)
    rows = await admin.upsert_email_accounts(
        {
            "provider": "google",
            "business_id": payload["business_id"],
            "user_id": payload["user_id"],
            "email_address": email_address,
            "display_name": None,
            "capabilities": {"send": True, "read": True},
            "token_ciphertext": encrypt_secret(access_token),
            "refresh_token_ciphertext": encrypt_secret(refresh_token) if refresh_token else None,
            "token_expires_at": token_expires_at.isoformat(),
        }
    )
    return RedirectResponse(url=_frontend_settings_url("google"))


@router.get("/oauth/microsoft/start")
async def microsoft_oauth_start(
    auth_ctx: dict = Depends(get_user_business_context),
    mode: Optional[str] = Query(default=None),
) -> RedirectResponse:
    return RedirectResponse(url=build_microsoft_oauth_start_url(auth_ctx, mode))


@oauth_router.get("/oauth/microsoft/callback")
async def microsoft_oauth_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    admin: SupabaseAdminClient = Depends(get_supabase_admin_client),
):
    if error:
        raise HTTPException(status_code=400, detail=error)
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")

    payload = _verify_state(state)
    if payload.get("provider") != "microsoft":
        raise HTTPException(status_code=400, detail="Invalid state provider")

    client_id = os.getenv("MICROSOFT_OAUTH_CLIENT_ID")
    client_secret = os.getenv("MICROSOFT_OAUTH_CLIENT_SECRET")
    redirect_uri = os.getenv("MICROSOFT_OAUTH_REDIRECT_URI")
    if not client_id or not client_secret or not redirect_uri:
        raise HTTPException(status_code=500, detail="Microsoft OAuth not configured")

    token_payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }
    async with httpx.AsyncClient(timeout=20) as client:
        token_response = await client.post(MICROSOFT_TOKEN_URL, data=token_payload)
    if token_response.status_code != 200:
        raise HTTPException(
            status_code=400,
            detail=f"Microsoft token exchange failed: {token_response.status_code} {token_response.text}",
        )
    token_data = token_response.json()
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    expires_in = int(token_data.get("expires_in", 0))
    if not access_token:
        raise HTTPException(status_code=400, detail="Microsoft access token missing")

    profile = await _fetch_microsoft_profile(access_token)
    email_address = profile.get("mail") or profile.get("userPrincipalName")
    display_name = profile.get("displayName")
    if not email_address:
        raise HTTPException(status_code=400, detail="Microsoft profile email missing")

    token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in or 0)
    rows = await admin.upsert_email_accounts(
        {
            "provider": "microsoft",
            "business_id": payload["business_id"],
            "user_id": payload["user_id"],
            "email_address": email_address,
            "display_name": display_name,
            "capabilities": {"send": True, "read": True},
            "token_ciphertext": encrypt_secret(access_token),
            "refresh_token_ciphertext": encrypt_secret(refresh_token) if refresh_token else None,
            "token_expires_at": token_expires_at.isoformat(),
        }
    )
    return RedirectResponse(url=_frontend_settings_url("microsoft"))
