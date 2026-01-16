"""Email router entrypoint."""

from typing import Any, Dict, List, Optional
from types import SimpleNamespace
from datetime import datetime, timedelta
import base64
import hashlib
import hmac
import json
import os
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from auth import get_user_business_context
from .crypto import encrypt_secret
from .service import SupabaseAdminClient, get_supabase_admin_client
from providers.google_gmail import GoogleGmailProvider
from providers.microsoft_graph import MicrosoftGraphProvider
from providers.smtp import SMTPProvider


router = APIRouter(prefix="/v1/email", tags=["Email"])


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
        return json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


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


@router.get("/oauth/google/start")
async def google_oauth_start(
    auth_ctx: dict = Depends(get_user_business_context),
) -> RedirectResponse:
    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
    redirect_uri = os.getenv("GOOGLE_OAUTH_REDIRECT_URI")
    if not client_id or not redirect_uri:
        raise HTTPException(status_code=500, detail="Google OAuth not configured")

    state = _sign_state(
        {
            "provider": "google",
            "user_id": auth_ctx["user_id"],
            "business_id": auth_ctx["business_id"],
            "ts": int(datetime.utcnow().timestamp()),
        }
    )
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "access_type": "offline",
        "prompt": "consent",
        "scope": " ".join(
            [
                "https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/gmail.send",
            ]
        ),
        "state": state,
    }
    return RedirectResponse(url=f"{GOOGLE_AUTH_URL}?{urlencode(params)}")


@router.get("/oauth/google/callback")
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
    return {
        "provider": "google",
        "email_address": email_address,
        "account_id": rows[0]["id"] if rows else None,
    }


@router.get("/oauth/microsoft/start")
async def microsoft_oauth_start(
    auth_ctx: dict = Depends(get_user_business_context),
) -> RedirectResponse:
    client_id = os.getenv("MICROSOFT_OAUTH_CLIENT_ID")
    redirect_uri = os.getenv("MICROSOFT_OAUTH_REDIRECT_URI")
    if not client_id or not redirect_uri:
        raise HTTPException(status_code=500, detail="Microsoft OAuth not configured")

    state = _sign_state(
        {
            "provider": "microsoft",
            "user_id": auth_ctx["user_id"],
            "business_id": auth_ctx["business_id"],
            "ts": int(datetime.utcnow().timestamp()),
        }
    )
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "response_mode": "query",
        "scope": " ".join(
            [
                "offline_access",
                "https://graph.microsoft.com/User.Read",
                "https://graph.microsoft.com/Mail.Read",
                "https://graph.microsoft.com/Mail.Send",
            ]
        ),
        "state": state,
    }
    return RedirectResponse(url=f"{MICROSOFT_AUTH_URL}?{urlencode(params)}")


@router.get("/oauth/microsoft/callback")
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
    return {
        "provider": "microsoft",
        "email_address": email_address,
        "account_id": rows[0]["id"] if rows else None,
    }
