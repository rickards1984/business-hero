"""FastAPI application for AI Admin Assistant."""

import os
import re
import json
import copy
import secrets
import stripe
import logging
import base64
import httpx
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager
from cryptography.fernet import Fernet

from fastapi import FastAPI, Depends, HTTPException, Query, Request, Response, status, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, APIKeyHeader
from pydantic import ValidationError
from sqlmodel import Session, select
from sqlalchemy import text, func, or_
import pytz
import csv
import io
from datetime import date as date_type
from decimal import Decimal

from db import init_db, get_session
from models import (
    Business,
    Task,
    Call,
    BusinessSettings,
    Integration,
    Invoice,
    EmailConnection,
    EmailOutbox,
    EmailAccount,
    EmailMessage,
    EmailSyncState,
    EmailBriefing,
    EmailDraft,
    SupportTicket,
    StripeEvent,
)
from schemas import (
    BusinessCreate, BusinessResponse, BusinessListItem, BusinessProfile,
    TaskCreate, TaskResponse, SnoozeRequest,
    CallCreate, CallResponse,
    BriefingResponse, HealthResponse,
    ChatRequest, ChatResponse, ChatBusinessInfo,
    BusinessSettingsResponse, BusinessSettingsUpdate,
    IntegrationResponse, IntegrationListResponse, IntegrationUpdate,
    LogoUploadResponse, LogoUpdateRequest,
    Invoice as InvoiceSchema, InvoiceListResponse, ImportResponse, ChaseDraftResponse,
    EmailConnectionPublic, EmailConnectionUpsert, EmailTestResponse,
    SendChaseRequest, SendChaseResponse, BulkSendRequest, BulkSendResponse,
    EmailOutboxItem, EmailOutboxListResponse,
    EmailMessageItem, EmailMessageListResponse, EmailSyncRunResponse,
    EmailBriefingRequest, EmailBriefingResponse,
    EmailDraftRequest, EmailDraftResponse, EmailDraftSendResponse,
    SupportTicketCreateAdmin, SupportTicketUpdateAdmin,
    BillingCheckoutRequest, BillingSessionResponse, BillingPortalResponse,
)
from auth import verify_master_key, get_current_business, get_access_token, get_user_auth_context, get_user_business_context, get_platform_admin_context, is_platform_admin_user
from openai_utils import generate_call_summary
from supabase_auth import verify_supabase_token
from assistant_chat import process_chat_message, get_business_for_user
from app.email.service import (
    get_or_create_smtp_account,
    send_email_smtp,
    get_business_by_id,
    get_default_email_account,
    get_provider_for_account,
)
from app.email.router import (
    router as email_router,
    oauth_router as email_oauth_router,
    build_google_oauth_start_url,
    build_microsoft_oauth_start_url,
)
from app.billing.config import get_stripe_config, validate_stripe_config
from accounting import router as accounting_router
from realtime_voice import router as realtime_voice_router
from dependencies import get_current_user_business, get_current_user_and_business


# ============================================================================
# EMAIL OAUTH HELPERS
# ============================================================================

def _decrypt_email_token(ciphertext: str) -> str:
    """Decrypt an encrypted email token."""
    key = os.getenv("EMAIL_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("EMAIL_ENCRYPTION_KEY not configured")
    f = Fernet(key.encode("utf-8"))
    return f.decrypt(ciphertext.encode("utf-8")).decode("utf-8")


def _refresh_google_token_for_sending(session: Session, account) -> str:
    """Refresh an expired Google access token and update the database."""
    try:
        refresh_token = _decrypt_email_token(account.refresh_token_ciphertext)
        
        response = httpx.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": os.getenv("GOOGLE_OAUTH_CLIENT_ID"),
                "client_secret": os.getenv("GOOGLE_OAUTH_CLIENT_SECRET"),
                "refresh_token": refresh_token,
                "grant_type": "refresh_token"
            },
            timeout=30
        )
        
        if response.status_code != 200:
            raise Exception(f"Token refresh failed: {response.status_code}")
        
        data = response.json()
        new_access_token = data.get("access_token")
        expires_in = data.get("expires_in", 3600)
        
        if not new_access_token:
            raise Exception("No access token in refresh response")
        
        # Encrypt and store the new token
        key = os.getenv("EMAIL_ENCRYPTION_KEY")
        f = Fernet(key.encode("utf-8"))
        new_token_ciphertext = f.encrypt(new_access_token.encode("utf-8")).decode("utf-8")
        
        new_expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
        
        # Update the account in the database
        account.token_ciphertext = new_token_ciphertext
        account.token_expires_at = new_expires_at
        account.updated_at = datetime.utcnow()
        session.add(account)
        session.commit()
        
        return new_access_token
    except Exception as e:
        raise Exception(f"Failed to refresh token: {str(e)}")


def _send_gmail_with_refresh(session: Session, account, access_token: str, to_email: str, subject: str, body: str) -> dict:
    """Send email via Gmail API with automatic token refresh on 401."""
    def attempt_send(token):
        message = MIMEText(body)
        message['to'] = to_email
        message['subject'] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
        
        response = httpx.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"raw": raw},
            timeout=30
        )
        return response
    
    # First attempt
    response = attempt_send(access_token)
    
    # If 401, refresh token and retry
    if response.status_code == 401 and account.refresh_token_ciphertext:
        try:
            new_token = _refresh_google_token_for_sending(session, account)
            response = attempt_send(new_token)
        except Exception as refresh_error:
            raise Exception(f"Gmail token expired and refresh failed: {str(refresh_error)}. Please reconnect your Google account.")
    
    if response.status_code not in [200, 202]:
        raise Exception(f"Gmail API error: {response.status_code} - {response.text}")
    
    return response.json()


def _send_microsoft_email_with_refresh(session: Session, account, access_token: str, to_email: str, subject: str, body: str) -> dict:
    """Send email via Microsoft Graph API with automatic token refresh."""
    def attempt_send(token):
        response = httpx.post(
            "https://graph.microsoft.com/v1.0/me/sendMail",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "message": {
                    "subject": subject,
                    "body": {"contentType": "Text", "content": body},
                    "toRecipients": [{"emailAddress": {"address": to_email}}]
                }
            },
            timeout=30
        )
        return response
    
    response = attempt_send(access_token)
    
    # If 401, token is expired (Microsoft refresh can be added later if needed)
    if response.status_code == 401:
        raise Exception("Microsoft token expired. Please reconnect your Microsoft account.")
    
    if response.status_code not in [200, 202]:
        raise Exception(f"Microsoft Graph error: {response.status_code} - {response.text}")
    
    return {"status": "sent"}


def send_email_oauth(session: Session, account: EmailAccount, to_email: str, subject: str, body: str) -> dict:
    """Send email using OAuth account (Google or Microsoft) with automatic token refresh."""
    if not account.token_ciphertext:
        raise Exception("No access token available for this account")
    
    try:
        access_token = _decrypt_email_token(account.token_ciphertext)
    except Exception as e:
        raise Exception(f"Failed to decrypt token: {str(e)}")
    
    if account.provider == "google":
        return _send_gmail_with_refresh(session, account, access_token, to_email, subject, body)
    elif account.provider == "microsoft":
        return _send_microsoft_email_with_refresh(session, account, access_token, to_email, subject, body)
    else:
        raise Exception(f"Unsupported provider: {account.provider}")


def get_email_account_for_sending(session: Session, business_id: str):
    """Get the best email account for sending (OAuth preferred over SMTP).
    
    Returns tuple of (oauth_account, smtp_connection) - one will be None.
    """
    # First try OAuth accounts (Google/Microsoft)
    oauth_account = session.exec(
        select(EmailAccount).where(
            EmailAccount.business_id == business_id,
            EmailAccount.provider.in_(["google", "microsoft"])
        ).order_by(EmailAccount.created_at.desc())
    ).first()
    
    if oauth_account:
        return (oauth_account, None)
    
    # Fall back to SMTP
    smtp_connection = session.exec(
        select(EmailConnection).where(
            EmailConnection.business_id == business_id,
            EmailConnection.is_enabled == True
        )
    ).first()
    
    if smtp_connection:
        return (None, smtp_connection)
    
    return (None, None)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - initialize database on startup."""
    init_db()
    yield


app = FastAPI(
    title="AI Admin Assistant API",
    description="Multi-tenant backend for AI Admin Assistant - integrates with Awaz AI webhooks and Custom GPT Actions",
    version="1.0.0",
    lifespan=lifespan,
    swagger_ui_parameters={"persistAuthorization": True}
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(_request: Request, exc: Exception):
    logging.getLogger("app").exception("Unhandled exception", exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})


# CORS configuration
# Note: When allow_credentials=True, we cannot use "*" for allow_origins
# We must specify exact origins
allowed_origins = [
    "https://business-hero.vercel.app",
    "http://localhost:5173",
    "http://localhost:3000",
    "http://localhost:8000",
]
allow_origin_regex = r"^https://.*\.vercel\.app$"
print(f"CORS allowed_origins={allowed_origins} allow_origin_regex={allow_origin_regex}")


def _is_allowed_origin(origin: Optional[str]) -> bool:
    if not origin:
        return False
    if origin in allowed_origins:
        return True
    return re.match(allow_origin_regex, origin) is not None

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=allow_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=86400,
)

app.include_router(email_router)
app.include_router(email_oauth_router)
app.include_router(accounting_router)
app.include_router(realtime_voice_router)


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """Health check endpoint."""
    return HealthResponse(ok=True)


@app.get("/v1/_debug/ping")
async def debug_ping():
    return {"ok": True, "ts": datetime.utcnow().isoformat() + "Z"}


@app.get("/v1/debug/cors")
async def debug_cors(request: Request):
    origin = request.headers.get("origin")
    return {"origin": origin, "allowed": _is_allowed_origin(origin)}


@app.get("/v1/oauth/google")
async def oauth_google_start(
    mode: Optional[str] = Query(default=None),
    auth_ctx=Depends(get_user_business_context),
):
    return RedirectResponse(url=build_google_oauth_start_url(auth_ctx, mode))


@app.get("/v1/oauth/google/start")
async def oauth_google_start_json(
    mode: Optional[str] = Query(default="connect"),
    auth_ctx=Depends(get_user_business_context),
):
    return {"url": build_google_oauth_start_url(auth_ctx, mode)}


@app.get("/v1/oauth/microsoft")
async def oauth_microsoft_start(
    mode: Optional[str] = Query(default=None),
    auth_ctx=Depends(get_user_business_context),
):
    return RedirectResponse(url=build_microsoft_oauth_start_url(auth_ctx, mode))


@app.get("/v1/oauth/microsoft/start")
async def oauth_microsoft_start_json(
    mode: Optional[str] = Query(default="connect"),
    auth_ctx=Depends(get_user_business_context),
):
    return {"url": build_microsoft_oauth_start_url(auth_ctx, mode)}


@app.get("/openapi-action.json", include_in_schema=False)
async def get_openapi_action_schema(request: Request):
    """
    Returns a filtered OpenAPI 3.1.0 schema for ChatGPT GPT Actions.
    
    - Excludes admin endpoints
    - Uses Bearer auth security scheme
    - Includes x-openai-isConsequential flags
    - Uses HTTPS base URL when called externally
    """
    base_url = str(request.base_url).rstrip("/")
    if request.headers.get("x-forwarded-proto") == "https" or "replit" in base_url:
        base_url = base_url.replace("http://", "https://")
    
    allowed_paths = {
        "/health": ["get"],
        "/v1/me": ["get"],
        "/v1/tasks": ["get", "post"],
        "/v1/tasks/{task_id}": ["delete"],
        "/v1/tasks/{task_id}/complete": ["post"],
        "/v1/tasks/{task_id}/snooze": ["post"],
        "/v1/calls": ["get", "post"],
        "/v1/briefing/today": ["get"],
    }
    
    consequential_flags: Dict[str, Dict[str, bool]] = {
        "/health": {"get": False},
        "/v1/me": {"get": False},
        "/v1/tasks": {"get": False, "post": False},
        "/v1/tasks/{task_id}": {"delete": True},
        "/v1/tasks/{task_id}/complete": {"post": False},
        "/v1/tasks/{task_id}/snooze": {"post": False},
        "/v1/calls": {"get": False, "post": False},
        "/v1/briefing/today": {"get": False},
    }
    
    original_schema = app.openapi()
    
    filtered_paths: Dict[str, Any] = {}
    for path, methods in allowed_paths.items():
        if path in original_schema.get("paths", {}):
            filtered_paths[path] = {}
            for method in methods:
                if method in original_schema["paths"][path]:
                    operation = copy.deepcopy(original_schema["paths"][path][method])
                    
                    if path == "/health":
                        operation["security"] = []
                    else:
                        operation["security"] = [{"bearerAuth": []}]
                    
                    is_consequential = consequential_flags.get(path, {}).get(method, False)
                    operation["x-openai-isConsequential"] = is_consequential
                    
                    filtered_paths[path][method] = operation
    
    filtered_components = copy.deepcopy(original_schema.get("components", {}))
    filtered_components["securitySchemes"] = {
        "bearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "description": "Business API key obtained when creating a business via admin endpoint"
        }
    }
    
    action_schema = {
        "openapi": "3.1.0",
        "info": {
            "title": "AI Admin Assistant - GPT Actions",
            "description": "API for managing tasks, calls, and daily briefings. Use your business API key for authentication.",
            "version": "1.0.0"
        },
        "servers": [{"url": base_url}],
        "paths": filtered_paths,
        "components": filtered_components,
        "security": [{"bearerAuth": []}]
    }
    
    return JSONResponse(content=action_schema)


@app.post(
    "/v1/admin/businesses",
    response_model=BusinessResponse,
    tags=["Admin"],
    dependencies=[Depends(verify_master_key)]
)
async def create_business(
    data: BusinessCreate,
    session: Session = Depends(get_session)
):
    """Create a new business (admin only)."""
    business = Business(name=data.name, timezone=data.timezone)
    session.add(business)
    session.commit()
    session.refresh(business)
    
    return BusinessResponse(
        id=str(business.id),
        name=business.name,
        timezone=business.timezone,
        api_key=business.api_key
    )


@app.get(
    "/v1/admin/businesses",
    response_model=List[BusinessListItem],
    tags=["Admin"],
    dependencies=[Depends(verify_master_key)]
)
async def list_businesses(session: Session = Depends(get_session)):
    """List all businesses (admin only). Does not expose API keys."""
    statement = select(Business).order_by(Business.created_at.desc())
    businesses = session.exec(statement).all()
    
    return [
        BusinessListItem(
            id=str(b.id),
            name=b.name,
            timezone=b.timezone,
            created_at=b.created_at
        )
        for b in businesses
    ]


@app.get("/v1/admin/me", tags=["Admin"])
async def admin_me(auth_ctx=Depends(get_platform_admin_context)):
    return {
        "user_id": auth_ctx["user_id"],
        "email": auth_ctx.get("email"),
        "is_platform_admin": True,
    }


@app.get("/v1/admin/businesses/{business_id}/health", tags=["Admin"])
async def get_business_health(
    business_id: str,
    auth_ctx=Depends(get_platform_admin_context),
    session: Session = Depends(get_session),
):
    require_platform_admin(auth_ctx, session)
    query = text(
        """
        SELECT
            b.id::text AS id,
            b.name,
            b.plan_tier,
            b.is_active,
            b.subscription_status,
            b.current_period_end,
            b.feature_flags,
            b.limits,
            (
                SELECT NULLIF(i.config->>'last_received_at', '')::timestamptz
                FROM integrations i
                WHERE i.business_id = b.id AND i.integration_type = 'awaz'
                LIMIT 1
            ) AS last_awaz_webhook_at,
            EXISTS (
                SELECT 1
                FROM integrations i
                WHERE i.business_id = b.id
                  AND i.integration_type = 'awaz'
                  AND (i.config->>'last_received_at') IS NOT NULL
            ) AS awaz_connected,
            (
                SELECT ea.email_address
                FROM email_accounts ea
                WHERE ea.business_id = b.id AND ea.is_default = true
                LIMIT 1
            ) AS default_email,
            EXISTS (
                SELECT 1 FROM email_accounts ea WHERE ea.business_id = b.id
            ) AS email_connected,
            EXISTS (
                SELECT 1
                FROM calendar_sync_state cs
                JOIN email_accounts ea ON ea.id = cs.email_account_id
                WHERE ea.business_id = b.id
            ) AS calendar_connected,
            (
                SELECT MAX(es.last_synced_at)
                FROM email_sync_state es
                JOIN email_accounts ea ON ea.id = es.email_account_id
                WHERE ea.business_id = b.id
            ) AS last_email_sync_at,
            (
                SELECT MAX(cs.last_synced_at)
                FROM calendar_sync_state cs
                JOIN email_accounts ea ON ea.id = cs.email_account_id
                WHERE ea.business_id = b.id
            ) AS last_calendar_sync_at,
            (
                SELECT MAX(created_at) FROM calls c WHERE c.business_id = b.id
            ) AS last_call_at,
            (
                SELECT MAX(created_at) FROM tasks t WHERE t.business_id = b.id AND t.deleted_at IS NULL
            ) AS last_task_at,
            (
                SELECT COUNT(*) FROM support_tickets st
                WHERE st.business_id = b.id AND st.status != 'closed'
            ) AS open_ticket_count
        FROM businesses b
        WHERE b.id = :business_id
        LIMIT 1
        """
    )
    row = session.execute(text(query), {"business_id": business_id}).first()
    if not row:
        raise HTTPException(status_code=404, detail="Business not found")
    data = dict(row._mapping)
    return {
        "business": {
            "id": data["id"],
            "name": data["name"],
            "plan_tier": data["plan_tier"],
            "is_active": data["is_active"],
            "subscription_status": data["subscription_status"],
            "current_period_end": data["current_period_end"],
            "feature_flags": data["feature_flags"] or {},
            "limits_json": data["limits"] or {},
        },
        "awaz": {
            "connected": data["awaz_connected"],
            "last_webhook_at": data["last_awaz_webhook_at"],
        },
        "email": {
            "connected": data["email_connected"],
            "default_email": data["default_email"],
            "last_sync_at": data["last_email_sync_at"],
        },
        "calendar": {
            "connected": data["calendar_connected"],
            "last_sync_at": data["last_calendar_sync_at"],
        },
        "activity": {
            "last_call_at": data["last_call_at"],
            "last_task_at": data["last_task_at"],
        },
        "support": {
            "open_ticket_count": data["open_ticket_count"],
        },
    }


@app.post("/v1/admin/businesses/{business_id}/awaz/test", tags=["Admin"])
async def admin_test_awaz(
    business_id: str,
    auth_ctx=Depends(get_platform_admin_context),
    session: Session = Depends(get_session),
):
    require_platform_admin(auth_ctx, session)
    logger.info("admin_awaz_test", extra={"user_id": auth_ctx["user_id"], "business_id": business_id})
    call_id = await _run_awaz_test_for_business(business_id, session)
    return {"call_id": call_id}


@app.post("/v1/admin/businesses/{business_id}/email/sync", response_model=EmailSyncRunResponse, tags=["Admin"])
async def admin_email_sync(
    business_id: str,
    auth_ctx=Depends(get_platform_admin_context),
    session: Session = Depends(get_session),
):
    require_platform_admin(auth_ctx, session)
    logger.info("admin_email_sync", extra={"user_id": auth_ctx["user_id"], "business_id": business_id})
    return _run_email_sync_for_business(business_id, session)


@app.post("/v1/admin/businesses/{business_id}/calendar/sync", tags=["Admin"])
async def admin_calendar_sync(
    business_id: str,
    auth_ctx=Depends(get_platform_admin_context),
    session: Session = Depends(get_session),
):
    require_platform_admin(auth_ctx, session)
    logger.info("admin_calendar_sync", extra={"user_id": auth_ctx["user_id"], "business_id": business_id})
    raise HTTPException(status_code=501, detail="Calendar sync not implemented")


@app.get("/v1/admin/businesses/summary", tags=["Admin"])
async def list_businesses_summary(
    auth_ctx=Depends(get_platform_admin_context),
    session: Session = Depends(get_session),
):
    require_platform_admin(auth_ctx, session)
    query = text(
        """
        SELECT
            b.id::text AS id,
            b.name,
            b.timezone,
            b.plan_tier,
            b.is_active,
            b.subscription_status,
            (
                SELECT NULLIF(i.config->>'last_received_at', '')::timestamptz
                FROM integrations i
                WHERE i.business_id = b.id AND i.integration_type = 'awaz'
                LIMIT 1
            ) AS last_awaz_webhook_at,
            EXISTS (
                SELECT 1
                FROM integrations i
                WHERE i.business_id = b.id
                  AND i.integration_type = 'awaz'
                  AND (i.config->>'last_received_at') IS NOT NULL
            ) AS awaz_connected,
            EXISTS (
                SELECT 1 FROM email_accounts ea WHERE ea.business_id = b.id
            ) AS email_connected,
            EXISTS (
                SELECT 1
                FROM calendar_sync_state cs
                JOIN email_accounts ea ON ea.id = cs.email_account_id
                WHERE ea.business_id = b.id
            ) AS calendar_connected,
            (
                SELECT COUNT(*) FROM support_tickets st
                WHERE st.business_id = b.id AND st.status != 'closed'
            ) AS open_ticket_count,
            (
                SELECT MAX(created_at) FROM calls c WHERE c.business_id = b.id
            ) AS last_call_at,
            (
                SELECT MAX(created_at) FROM tasks t WHERE t.business_id = b.id AND t.deleted_at IS NULL
            ) AS last_task_at,
            (
                SELECT MAX(es.last_synced_at)
                FROM email_sync_state es
                JOIN email_accounts ea ON ea.id = es.email_account_id
                WHERE ea.business_id = b.id
            ) AS last_email_sync_at,
            (
                SELECT MAX(cs.last_synced_at)
                FROM calendar_sync_state cs
                JOIN email_accounts ea ON ea.id = cs.email_account_id
                WHERE ea.business_id = b.id
            ) AS last_calendar_sync_at
        FROM businesses b
        ORDER BY b.created_at DESC
        """
    )
    try:
        rows = session.execute(text(query)).all()
    except Exception:
        logger.warning("admin_businesses_summary_fallback", exc_info=True)
        businesses = session.exec(select(Business).order_by(Business.created_at.desc())).all()
        summaries = []
        for business in businesses:
            summaries.append(
                {
                    "id": str(business.id),
                    "name": business.name,
                    "timezone": business.timezone,
                    "plan_tier": business.plan_tier,
                    "is_active": business.is_active,
                    "subscription_status": business.subscription_status,
                    "last_awaz_webhook_at": None,
                    "awaz_connected": False,
                    "email_connected": False,
                    "calendar_connected": False,
                    "open_ticket_count": 0,
                    "last_email_sync_at": None,
                    "last_calendar_sync_at": None,
                    "last_activity_at": None,
                }
            )
        return summaries
    summaries = []
    for row in rows:
        data = dict(row._mapping)
        last_call = data.pop("last_call_at")
        last_task = data.pop("last_task_at")
        if last_call and last_task:
            last_activity_at = max(last_call, last_task)
        else:
            last_activity_at = last_call or last_task
        data["last_activity_at"] = last_activity_at
        summaries.append(data)
    return summaries


@app.post("/v1/billing/checkout-session", response_model=BillingSessionResponse, tags=["Billing"])
async def create_checkout_session(
    payload: BillingCheckoutRequest,
    request: Request,
    auth_ctx=Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    ok, missing = validate_stripe_config()
    if not ok:
        raise HTTPException(status_code=500, detail=f"Stripe not configured. Missing: {', '.join(missing)}")
    config = get_stripe_config()
    stripe.api_key = config["stripe_secret_key"]
    business = session.exec(select(Business).where(Business.id == auth_ctx["business_id"])).first()
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    customer_id = business.stripe_customer_id
    if not customer_id:
        customer = stripe.Customer.create(
            email=getattr(request.state, "user_email", None),
            metadata={"business_id": str(business.id)},
        )
        customer_id = customer["id"]
        business.stripe_customer_id = customer_id
        session.add(business)
        session.commit()

    plan_tier = payload.plan_tier.lower()
    if plan_tier == "premium":
        plan_tier = "elite"
    prices = config.get("prices", {})
    price_id = prices.get(plan_tier)
    if not price_id:
        raise HTTPException(status_code=400, detail="Unknown or unmapped plan tier")
    base_url = _get_frontend_base_url(request)
    checkout = stripe.checkout.Session.create(
        mode="subscription",
        customer=customer_id,
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=f"{base_url}/app/settings/billing?success=1",
        cancel_url=f"{base_url}/app/settings/billing?canceled=1",
        metadata={"business_id": str(business.id), "plan_tier": plan_tier},
        client_reference_id=str(business.id),
    )
    return BillingSessionResponse(url=checkout["url"])


@app.get("/v1/billing/status", tags=["Billing"])
async def billing_status(auth_ctx=Depends(get_user_business_context)):
    ok, missing = validate_stripe_config()
    config = get_stripe_config()
    prices = config.get("prices", {})
    return {
        "configured": ok,
        "missing": missing,
        "app_base_url": config.get("app_base_url"),
        "prices": {
            "starter": bool(prices.get("starter")),
            "pro": bool(prices.get("pro")),
            "elite": bool(prices.get("elite")),
        },
    }


@app.post("/v1/billing/portal", response_model=BillingPortalResponse, tags=["Billing"])
async def create_billing_portal(
    request: Request,
    auth_ctx=Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    ok, missing = validate_stripe_config()
    if not ok:
        raise HTTPException(status_code=500, detail=f"Stripe not configured. Missing: {', '.join(missing)}")
    config = get_stripe_config()
    stripe.api_key = config["stripe_secret_key"]
    business = session.exec(select(Business).where(Business.id == auth_ctx["business_id"])).first()
    if not business or not business.stripe_customer_id:
        raise HTTPException(status_code=400, detail="Stripe customer not found for this business")
    base_url = _get_frontend_base_url(request)
    portal = stripe.billing_portal.Session.create(
        customer=business.stripe_customer_id,
        return_url=f"{base_url}/app/settings/billing",
    )
    return BillingPortalResponse(url=portal["url"])


@app.post("/v1/billing/webhook", tags=["Billing"])
async def stripe_webhook(
    request: Request,
    session: Session = Depends(get_session),
):
    ok, missing = validate_stripe_config()
    if not ok:
        raise HTTPException(status_code=500, detail=f"Stripe not configured. Missing: {', '.join(missing)}")
    config = get_stripe_config()
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    webhook_secret = config["stripe_webhook_secret"]
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid webhook signature: {exc}")

    event_dict = event.to_dict() if hasattr(event, "to_dict") else event
    event_type = event_dict["type"]
    event_data = event_dict["data"]["object"]
    business = None

    if event_type == "checkout.session.completed":
        business_id = event_data.get("metadata", {}).get("business_id")
        if business_id:
            business = session.exec(select(Business).where(Business.id == business_id)).first()
        if business:
            business.stripe_customer_id = event_data.get("customer") or business.stripe_customer_id
            business.stripe_subscription_id = event_data.get("subscription") or business.stripe_subscription_id
            business.last_stripe_event_at = datetime.utcnow()
            session.add(business)
            session.commit()

    if event_type in ("customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"):
        customer_id = event_data.get("customer")
        subscription_id = event_data.get("id")
        business = session.exec(
            select(Business).where(
                (Business.stripe_customer_id == customer_id) | (Business.stripe_subscription_id == subscription_id)
            )
        ).first()
        if business:
            plan_tier = None
            items = event_data.get("items", {}).get("data", [])
            if items:
                price_id = items[0].get("price", {}).get("id")
                plan_tier = _resolve_plan_from_price(price_id)
            status = event_data.get("status")
            business.stripe_customer_id = customer_id or business.stripe_customer_id
            business.stripe_subscription_id = subscription_id or business.stripe_subscription_id
            business.subscription_status = status
            business.current_period_end = datetime.fromtimestamp(event_data.get("current_period_end")) if event_data.get("current_period_end") else None
            business.cancel_at_period_end = bool(event_data.get("cancel_at_period_end", False))
            business.last_stripe_event_at = datetime.utcnow()
            if plan_tier:
                business.plan_tier = plan_tier
                business.feature_flags = _merge_feature_flags(business.feature_flags or {}, plan_tier)
            business.is_active = status in ("active", "trialing")
            session.add(business)
            session.commit()

    try:
        stripe_event = StripeEvent(
            business_id=business.id if business else None,
            event_id=event_dict.get("id"),
            type=event_type,
            payload=event_dict,
        )
        session.add(stripe_event)
        session.commit()
    except Exception:
        session.rollback()

    return {"received": True}


@app.get("/v1/admin/support-tickets", tags=["Admin"])
async def list_support_tickets(
    business_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    severity: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    auth_ctx=Depends(get_platform_admin_context),
    session: Session = Depends(get_session),
):
    require_platform_admin(auth_ctx, session)
    statement = select(SupportTicket).order_by(SupportTicket.created_at.desc())
    if business_id:
        statement = statement.where(SupportTicket.business_id == business_id)
    if status:
        statement = statement.where(SupportTicket.status == status)
    if severity:
        statement = statement.where(SupportTicket.severity == severity)
    statement = statement.offset(offset).limit(limit)
    return session.exec(statement).all()


@app.post("/v1/admin/support-tickets", tags=["Admin"])
async def create_support_ticket_admin(
    payload: SupportTicketCreateAdmin,
    auth_ctx=Depends(get_platform_admin_context),
    session: Session = Depends(get_session),
):
    require_platform_admin(auth_ctx, session)
    ticket = SupportTicket(
        business_id=payload.business_id,
        user_id=auth_ctx["user_id"],
        title=payload.title,
        message=payload.message,
        severity=payload.severity or "normal",
        category=payload.category or "general",
        status="open",
        page_url=payload.page_url,
        context=payload.context or {},
    )
    session.add(ticket)
    session.commit()
    session.refresh(ticket)
    return ticket


@app.patch("/v1/admin/support-tickets/{ticket_id}", tags=["Admin"])
async def update_support_ticket_admin(
    ticket_id: str,
    payload: SupportTicketUpdateAdmin,
    auth_ctx=Depends(get_platform_admin_context),
    session: Session = Depends(get_session),
):
    require_platform_admin(auth_ctx, session)
    ticket = session.exec(select(SupportTicket).where(SupportTicket.id == ticket_id)).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Support ticket not found")
    if payload.status is not None:
        ticket.status = payload.status
    if payload.admin_notes is not None:
        ticket.admin_notes = payload.admin_notes
    if payload.severity is not None:
        ticket.severity = payload.severity
    elif payload.priority is not None:
        ticket.severity = payload.priority
    ticket.updated_at = datetime.utcnow()
    session.add(ticket)
    session.commit()
    session.refresh(ticket)
    return ticket


@app.get("/v1/me", tags=["Business"])
async def get_my_profile(
    auth_ctx=Depends(get_user_auth_context),
):
    """Get current user info and business profile for UI bootstrapping."""
    business = None
    try:
        business = get_business_for_user(auth_ctx["user_id"])
    except ValueError as exc:
        args = exc.args
        if not (len(args) >= 2 and args[0] == "NO_BUSINESS"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    # Build response with user info and business profile
    response = {
        "user_id": auth_ctx["user_id"],
        "email": auth_ctx.get("email"),
        "is_platform_admin": auth_ctx.get("is_platform_admin", False),
        "business_id": str(business.id) if business else None,
    }
    
    # Include business profile fields for the frontend
    if business:
        response.update({
            "id": str(business.id),
            "name": business.name,
            "timezone": business.timezone,
            "logo_url": business.logo_url,
        })
    
    return response


@app.get("/v1/business/settings", response_model=BusinessSettingsResponse, tags=["Business"])
async def get_business_settings(
    business: Business = Depends(get_current_user_business),
    session: Session = Depends(get_session)
):
    """Get business settings. Returns default empty settings if not yet created."""
    statement = select(BusinessSettings).where(BusinessSettings.business_id == business.id)
    settings = session.exec(statement).first()
    
    if not settings:
        # Return default settings if not found
        return BusinessSettingsResponse(
            id="",
            business_id=str(business.id),
            settings={},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
    
    return BusinessSettingsResponse(
        id=str(settings.id),
        business_id=str(settings.business_id),
        settings=settings.settings,
        created_at=settings.created_at,
        updated_at=settings.updated_at
    )


@app.put("/v1/business/settings", response_model=BusinessSettingsResponse, tags=["Business"])
async def update_business_settings(
    data: BusinessSettingsUpdate,
    business: Business = Depends(get_current_user_business),
    session: Session = Depends(get_session)
):
    """Update business settings. Creates settings if they don't exist."""
    statement = select(BusinessSettings).where(BusinessSettings.business_id == business.id)
    settings = session.exec(statement).first()
    
    if not settings:
        # Create new settings
        settings = BusinessSettings(
            business_id=business.id,
            settings=data.settings
        )
        session.add(settings)
    else:
        # Update existing settings
        settings.settings = data.settings
        settings.updated_at = datetime.utcnow()
    
    session.commit()
    session.refresh(settings)
    
    return BusinessSettingsResponse(
        id=str(settings.id),
        business_id=str(settings.business_id),
        settings=settings.settings,
        created_at=settings.created_at,
        updated_at=settings.updated_at
    )


@app.get("/v1/business/integrations", response_model=IntegrationListResponse, tags=["Business"])
async def get_business_integrations(
    business: Business = Depends(get_current_user_business),
    session: Session = Depends(get_session)
):
    """Get all integrations for the current business."""
    statement = select(Integration).where(Integration.business_id == business.id)
    integrations = session.exec(statement).all()
    
    return IntegrationListResponse(
        integrations=[
            IntegrationResponse(
                id=str(i.id),
                business_id=str(i.business_id),
                integration_type=i.integration_type,
                is_enabled=i.is_enabled,
                config=(
                    {k: v for k, v in (i.config or {}).items() if k != "webhook_secret"}
                    if i.integration_type == "awaz"
                    else i.config
                ),
                created_at=i.created_at,
                updated_at=i.updated_at
            )
            for i in integrations
        ]
    )


@app.get("/v1/integrations/awaz", tags=["Integrations"])
async def get_awaz_integration_status(
    request: Request,
    business_id: Optional[str] = Query(default=None),
    auth_ctx=Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    target_business_id = resolve_awaz_business_id(auth_ctx, session, business_id)
    integration = ensure_awaz_integration(target_business_id, session)
    config = integration.config or {}
    last_received_at = config.get("last_received_at")
    last_received_dt = _parse_iso_datetime(last_received_at)
    connected = False
    if last_received_dt:
        connected = last_received_dt >= datetime.utcnow() - timedelta(days=30)

    return {
        "webhook_url": _build_awaz_webhook_url(request, config.get("webhook_secret", "")),
        "connected": connected,
        "last_received_at": last_received_at,
        "last_error": config.get("last_error"),
        "receptionist_name": config.get("receptionist_name"),
        "phone_number": config.get("phone_number"),
    }


@app.post("/v1/integrations/awaz/rotate-secret", tags=["Integrations"])
async def rotate_awaz_webhook_secret(
    request: Request,
    business_id: Optional[str] = Query(default=None),
    auth_ctx=Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    target_business_id = resolve_awaz_business_id(auth_ctx, session, business_id)
    integration = ensure_awaz_integration(target_business_id, session)
    config = integration.config or {}
    config["webhook_secret"] = secrets.token_urlsafe(32)
    integration.config = config
    integration.updated_at = datetime.utcnow()
    session.add(integration)
    session.commit()

    return {
        "webhook_url": _build_awaz_webhook_url(request, config["webhook_secret"]),
    }


@app.post("/v1/integrations/awaz/test", tags=["Integrations"])
async def test_awaz_integration(
    business_id: Optional[str] = Query(default=None),
    auth_ctx=Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    target_business_id = resolve_awaz_business_id(auth_ctx, session, business_id)
    business = session.exec(
        select(Business).where(Business.id == target_business_id)
    ).first()
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    integration = ensure_awaz_integration(target_business_id, session)
    config = integration.config or {}

    payload = CallCreate(
        caller_number=config.get("phone_number") or "+440000000000",
        caller_name=config.get("receptionist_name") or "Awaz Test",
        started_at=datetime.utcnow(),
        ended_at=datetime.utcnow(),
        transcript="Test call from Awaz integration.",
        intent="test",
        create_follow_up_task=True,
    )
    response = await _create_call_record(payload, business, session)

    config["last_received_at"] = datetime.utcnow().isoformat()
    config["last_error"] = None
    integration.config = config
    integration.updated_at = datetime.utcnow()
    session.add(integration)
    session.commit()

    return {"call_id": response.id}


@app.put("/v1/business/integrations/{integration_type}", response_model=IntegrationResponse, tags=["Business"])
async def update_business_integration(
    integration_type: str,
    data: IntegrationUpdate,
    business: Business = Depends(get_current_user_business),
    session: Session = Depends(get_session)
):
    """Update or create an integration for the current business."""
    statement = select(Integration).where(
        Integration.business_id == business.id,
        Integration.integration_type == integration_type
    )
    integration = session.exec(statement).first()
    
    if not integration:
        # Create new integration
        integration = Integration(
            business_id=business.id,
            integration_type=integration_type,
            is_enabled=data.is_enabled if data.is_enabled is not None else False,
            config=data.config if data.config is not None else {}
        )
        session.add(integration)
    else:
        # Update existing integration
        if data.is_enabled is not None:
            integration.is_enabled = data.is_enabled
        if data.config is not None:
            integration.config = data.config
        integration.updated_at = datetime.utcnow()
    
    session.commit()
    session.refresh(integration)
    
    return IntegrationResponse(
        id=str(integration.id),
        business_id=str(integration.business_id),
        integration_type=integration.integration_type,
        is_enabled=integration.is_enabled,
        config=integration.config,
        created_at=integration.created_at,
        updated_at=integration.updated_at
    )


@app.post("/v1/business/logo/upload-url", response_model=LogoUploadResponse, tags=["Business"])
async def get_logo_upload_url(
    business: Business = Depends(get_current_user_business)
):
    """
    Generate a signed upload URL for business logo.
    
    Requires: Supabase JWT auth (Authorization: Bearer <access_token>)
    
    Note: The frontend should use Supabase Storage client directly to upload.
    This endpoint returns the path where the logo should be uploaded.
    The actual upload should be done via Supabase Storage client in the frontend.
    """
    import uuid
    from datetime import datetime, timedelta
    
    # Generate unique filename: {business_id}/logo_{timestamp}.{ext}
    # The extension will be determined by the frontend based on file type
    timestamp = int(datetime.utcnow().timestamp())
    logo_path = f"{business.id}/logo_{timestamp}"
    
    # Return the path - frontend will use Supabase Storage client to upload
    # The signed URL generation is handled by Supabase client in the frontend
    return LogoUploadResponse(
        upload_url="",  # Frontend will generate this using Supabase client
        logo_path=logo_path,
        expires_at=datetime.utcnow() + timedelta(hours=1)
    )


@app.put("/v1/business/logo", response_model=BusinessProfile, tags=["Business"])
async def update_business_logo(
    data: LogoUpdateRequest,
    business: Business = Depends(get_current_user_business),
    session: Session = Depends(get_session)
):
    """Update the logo URL for the current business.
    
    Requires: Supabase JWT auth (Authorization: Bearer <access_token>)
    """
    business.logo_url = data.logo_url if data.logo_url else None
    session.add(business)
    session.commit()
    session.refresh(business)
    
    return BusinessProfile(
        id=str(business.id),
        name=business.name,
        timezone=business.timezone,
        logo_url=business.logo_url
    )


@app.post("/v1/tasks", response_model=TaskResponse, tags=["Tasks"])
async def create_task(
    data: TaskCreate,
    business: Business = Depends(get_current_user_business),
    session: Session = Depends(get_session)
):
    """Create a new task."""
    task = Task(
        business_id=business.id,
        title=data.title,
        description=data.description,
        due_at=data.due_at,
        recurrence=data.recurrence,
        source=data.source
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    
    return TaskResponse(
        id=str(task.id),
        business_id=str(task.business_id),
        title=task.title,
        description=task.description,
        due_at=task.due_at,
        recurrence=task.recurrence,
        status=task.status,
        source=task.source,
        created_at=task.created_at,
        updated_at=task.updated_at
    )


@app.get("/v1/tasks", response_model=List[TaskResponse], tags=["Tasks"])
async def list_tasks(
    status: Optional[str] = Query(None, description="Filter by status: open, done, snoozed"),
    due_before: Optional[datetime] = Query(None, description="Filter tasks due before this datetime"),
    due_after: Optional[datetime] = Query(None, description="Filter tasks due after this datetime"),
    limit: int = Query(50, le=100, description="Maximum number of tasks to return"),
    business: Business = Depends(get_current_user_business),
    session: Session = Depends(get_session)
):
    """List tasks for the current business."""
    statement = select(Task).where(
        Task.business_id == business.id,
        Task.deleted_at.is_(None),
    )
    
    if status:
        statement = statement.where(Task.status == status)
    if due_before:
        statement = statement.where(Task.due_at <= due_before)
    if due_after:
        statement = statement.where(Task.due_at >= due_after)
    
    statement = statement.order_by(Task.created_at.desc()).limit(limit)
    tasks = session.exec(statement).all()
    
    return [
        TaskResponse(
            id=str(t.id),
            business_id=str(t.business_id),
            title=t.title,
            description=t.description,
            due_at=t.due_at,
            recurrence=t.recurrence,
            status=t.status,
            source=t.source,
            created_at=t.created_at,
            updated_at=t.updated_at
        )
        for t in tasks
    ]


@app.post("/v1/tasks/{task_id}/complete", response_model=TaskResponse, tags=["Tasks"])
async def complete_task(
    task_id: str,
    business: Business = Depends(get_current_user_business),
    session: Session = Depends(get_session)
):
    """Mark a task as done."""
    statement = select(Task).where(
        Task.id == task_id,
        Task.business_id == business.id,
        Task.deleted_at.is_(None),
    )
    task = session.exec(statement).first()
    
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    
    task.status = "done"
    task.updated_at = datetime.utcnow()
    session.add(task)
    session.commit()
    session.refresh(task)
    
    return TaskResponse(
        id=str(task.id),
        business_id=str(task.business_id),
        title=task.title,
        description=task.description,
        due_at=task.due_at,
        recurrence=task.recurrence,
        status=task.status,
        source=task.source,
        created_at=task.created_at,
        updated_at=task.updated_at
    )


@app.post("/v1/tasks/{task_id}/snooze", response_model=TaskResponse, tags=["Tasks"])
async def snooze_task(
    task_id: str,
    data: SnoozeRequest,
    business: Business = Depends(get_current_user_business),
    session: Session = Depends(get_session)
):
    """Snooze a task. Provide either 'minutes' or 'until'."""
    statement = select(Task).where(
        Task.id == task_id,
        Task.business_id == business.id,
        Task.deleted_at.is_(None),
    )
    task = session.exec(statement).first()
    
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    
    if data.until:
        task.due_at = data.until
    elif data.minutes:
        task.due_at = datetime.utcnow() + timedelta(minutes=data.minutes)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide either 'minutes' or 'until'"
        )
    
    task.status = "snoozed"
    task.updated_at = datetime.utcnow()
    session.add(task)
    session.commit()
    session.refresh(task)
    
    return TaskResponse(
        id=str(task.id),
        business_id=str(task.business_id),
        title=task.title,
        description=task.description,
        due_at=task.due_at,
        recurrence=task.recurrence,
        status=task.status,
        source=task.source,
        created_at=task.created_at,
        updated_at=task.updated_at
    )


@app.delete("/v1/tasks/{task_id}", tags=["Tasks"])
async def delete_task(
    task_id: str,
    business: Business = Depends(get_current_user_business),
    session: Session = Depends(get_session),
):
    """Soft delete a task."""
    statement = select(Task).where(
        Task.id == task_id,
        Task.business_id == business.id,
        Task.deleted_at.is_(None),
    )
    task = session.exec(statement).first()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    task.deleted_at = datetime.utcnow()
    task.updated_at = datetime.utcnow()
    session.add(task)
    session.commit()

    return {
        "ok": True,
        "task_id": str(task.id),
        "deleted_at": task.deleted_at,
    }


@app.post("/v1/calls", response_model=CallResponse, tags=["Calls"])
async def create_call(
    data: CallCreate,
    business: Business = Depends(get_current_user_business),
    session: Session = Depends(get_session)
):
    """
    Create a call event from Awaz webhook or other sources.
    Optionally auto-creates a follow-up task.
    """
    return await _create_call_record(data, business, session)


async def _create_call_record(
    data: CallCreate,
    business: Business,
    session: Session,
    source: str = "Awaz",
) -> CallResponse:
    summary = data.summary
    if not summary and data.transcript:
        summary = await generate_call_summary(data.transcript)

    call_event = Call(
        business_id=business.id,
        source=source,
        caller_number=data.caller_number,
        caller_name=data.caller_name,
        started_at=data.started_at,
        ended_at=data.ended_at,
        transcript=data.transcript,
        summary=summary,
        intent=data.intent,
    )
    session.add(call_event)

    if data.create_follow_up_task or data.intent == "new_lead":
        caller_info = data.caller_name or data.caller_number or "Unknown"
        follow_up_task = Task(
            business_id=business.id,
            title=f"Follow up call: {caller_info}",
            description=f"Follow up on call from {caller_info}. Intent: {data.intent or 'not specified'}",
            source="awaz",
            status="open",
        )
        session.add(follow_up_task)

    session.commit()
    session.refresh(call_event)

    return CallResponse(
        id=str(call_event.id),
        business_id=str(call_event.business_id),
        source=call_event.source,
        caller_number=call_event.caller_number,
        caller_name=call_event.caller_name,
        started_at=call_event.started_at,
        ended_at=call_event.ended_at,
        transcript=call_event.transcript,
        summary=call_event.summary,
        intent=call_event.intent,
        archived=getattr(call_event, 'archived', False),
        created_at=call_event.created_at,
        updated_at=getattr(call_event, 'updated_at', None),
    )


_awaz_api_key_header = APIKeyHeader(name="x-api-key", auto_error=False)
_awaz_logger = logging.getLogger("webhooks")


def _select_awaz_token(x_api_key: Optional[str], api_key: Optional[str]) -> Optional[str]:
    return x_api_key or api_key


async def _parse_awaz_webhook_payload(request: Request) -> dict:
    body = await request.body()
    if not body:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty request body")

    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            payload = await request.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload") from exc
    elif "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
        form = await request.form()
        payload = dict(form)
    else:
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"Unsupported content-type: {content_type or 'unknown'}",
            ) from exc

    if isinstance(payload, list):
        if not payload:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty request body")
        payload = payload[0]

    if not isinstance(payload, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid payload type")

    return payload


async def get_awaz_business(
    api_key: Optional[str] = Query(default=None, description="Business API key for Awaz webhooks"),
    x_api_key: Optional[str] = Depends(_awaz_api_key_header),
    request: Request = None,
    session: Session = Depends(get_session),
) -> Business:
    token = _select_awaz_token(x_api_key, api_key)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing business api key",
        )
    auth_via = "header" if x_api_key else "query"
    if not x_api_key and api_key:
        _awaz_logger.info("Awaz webhook auth via query param")

    integration = None
    dialect = session.get_bind().dialect.name
    if request is not None:
        request.state.awaz_auth_via = auth_via
        request.state.awaz_dialect = dialect
    try:
        # Fetch all awaz integrations and filter in Python
        # This avoids SQL dialect differences for JSON queries
        integrations = session.exec(
            select(Integration).where(Integration.integration_type == "awaz")
        ).all()
        integration = next(
            (
                candidate
                for candidate in integrations
                if (candidate.config or {}).get("webhook_secret") == token
            ),
            None,
        )
    except Exception:
        _awaz_logger.exception("awaz_webhook_auth_lookup_failed", extra={"dialect": dialect})
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Webhook auth lookup failed")
    if integration:
        business = session.exec(
            select(Business).where(Business.id == integration.business_id)
        ).first()
        if not business:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook secret")
        if request is not None:
            request.state.awaz_integration = integration
            request.state.awaz_token = token
        return business

    # TODO(2026-01-31): Remove legacy business api key fallback for Awaz webhook.
    statement = select(Business).where(Business.api_key == token)
    business = session.exec(statement).first()
    if not business:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook secret")
    if request is not None:
        request.state.awaz_integration = None
        request.state.awaz_token = token
    return business


@app.post(
    "/v1/webhooks/awaz/calls",
    response_model=CallResponse,
    tags=["Webhooks"],
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {"schema": {"$ref": "#/components/schemas/CallCreate"}}
            },
        }
    },
)
async def awaz_calls_webhook(
    request: Request,
    business: Business = Depends(get_awaz_business),
    session: Session = Depends(get_session),
):
    """Handle Awaz calls webhook using business API key auth."""
    integration = getattr(request.state, "awaz_integration", None)
    auth_via = getattr(request.state, "awaz_auth_via", "unknown")
    dialect = getattr(request.state, "awaz_dialect", "unknown")

    try:
        payload_dict = await _parse_awaz_webhook_payload(request)
    except HTTPException as exc:
        if integration is not None:
            config = integration.config or {}
            config["last_error"] = exc.detail
            integration.config = config
            integration.updated_at = datetime.utcnow()
            session.add(integration)
            session.commit()
        _awaz_logger.exception(
            "awaz_webhook_payload_parse_failed",
            extra={
                "auth_via": auth_via,
                "dialect": dialect,
                "business_id": str(business.id),
                "payload_keys": [],
            },
        )
        raise

    payload_keys = list(payload_dict.keys())
    try:
        data = CallCreate(**payload_dict)
    except ValidationError as exc:
        if integration is not None:
            config = integration.config or {}
            config["last_error"] = "Validation error"
            integration.config = config
            integration.updated_at = datetime.utcnow()
            session.add(integration)
            session.commit()
        _awaz_logger.exception(
            "awaz_webhook_validation_failed",
            extra={
                "auth_via": auth_via,
                "dialect": dialect,
                "business_id": str(business.id),
                "payload_keys": payload_keys,
            },
        )
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.errors())

    try:
        result = await _create_call_record(data, business, session, source="awaz")
    except Exception:
        session.rollback()
        if integration is not None:
            config = integration.config or {}
            config["last_error"] = "Failed to process webhook payload"
            integration.config = config
            integration.updated_at = datetime.utcnow()
            session.add(integration)
            session.commit()
        _awaz_logger.exception(
            "awaz_webhook_failed",
            extra={
                "auth_via": auth_via,
                "dialect": dialect,
                "business_id": str(business.id),
                "payload_keys": payload_keys,
            },
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to process webhook payload")

    if integration is not None:
        config = integration.config or {}
        config["last_received_at"] = datetime.utcnow().isoformat()
        config["last_error"] = None
        integration.config = config
        integration.updated_at = datetime.utcnow()
        session.add(integration)
        session.commit()

    _awaz_logger.info(
        "awaz_webhook_processed",
        extra={
            "auth_via": auth_via,
            "dialect": dialect,
            "business_id": str(business.id),
            "payload_keys": payload_keys,
        },
    )
    return result


@app.get("/v1/calls", response_model=List[CallResponse], tags=["Calls"])
async def list_calls(
    limit: int = Query(50, le=100, description="Maximum number of calls to return"),
    archived: Optional[bool] = Query(None, description="Filter by archived status (null=all, true=archived only, false=non-archived only)"),
    business: Business = Depends(get_current_user_business),
    session: Session = Depends(get_session)
):
    """List recent call events for the current business."""
    statement = select(Call).where(Call.business_id == business.id)
    
    # Apply archived filter if specified
    if archived is not None:
        statement = statement.where(Call.archived == archived)
    
    statement = statement.order_by(Call.created_at.desc()).limit(limit)
    calls = session.exec(statement).all()
    
    return [
        CallResponse(
            id=str(c.id),
            business_id=str(c.business_id),
            source=c.source,
            caller_number=c.caller_number,
            caller_name=c.caller_name,
            started_at=c.started_at,
            ended_at=c.ended_at,
            transcript=c.transcript,
            summary=c.summary,
            intent=c.intent,
            archived=getattr(c, 'archived', False),
            created_at=c.created_at,
            updated_at=getattr(c, 'updated_at', None),
        )
        for c in calls
    ]


@app.patch("/v1/calls/{call_id}/archive", tags=["Calls"])
async def archive_call(
    call_id: str,
    business: Business = Depends(get_current_user_business),
    session: Session = Depends(get_session),
):
    """Archive or unarchive a call (toggles the archived status)."""
    # Find the call
    call = session.exec(
        select(Call).where(
            Call.id == call_id,
            Call.business_id == business.id
        )
    ).first()
    
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    
    # Toggle archived status
    call.archived = not getattr(call, 'archived', False)
    call.updated_at = datetime.utcnow()
    session.add(call)
    session.commit()
    session.refresh(call)
    
    return {"success": True, "archived": call.archived, "call_id": str(call.id)}


@app.get("/v1/briefing/today", response_model=BriefingResponse, tags=["Briefing"])
async def get_today_briefing(
    business: Business = Depends(get_current_user_business),
    session: Session = Depends(get_session)
):
    """Get today's briefing including tasks and recent calls."""
    try:
        tz = pytz.timezone(business.timezone)
    except pytz.UnknownTimeZoneError:
        tz = pytz.timezone("Europe/London")
    
    now = datetime.utcnow()
    now_local = pytz.utc.localize(now).astimezone(tz)
    
    today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    
    today_start_utc = today_start.astimezone(pytz.utc).replace(tzinfo=None)
    today_end_utc = today_end.astimezone(pytz.utc).replace(tzinfo=None)
    
    tasks_due_today_stmt = (
        select(Task)
        .where(
            Task.business_id == business.id,
            Task.status == "open",
            Task.deleted_at.is_(None),
            Task.due_at >= today_start_utc,
            Task.due_at < today_end_utc
        )
        .order_by(Task.due_at)
    )
    tasks_due_today = session.exec(tasks_due_today_stmt).all()
    
    overdue_stmt = (
        select(Task)
        .where(
            Task.business_id == business.id,
            Task.status == "open",
            Task.deleted_at.is_(None),
            Task.due_at < now
        )
        .order_by(Task.due_at)
    )
    overdue_tasks = session.exec(overdue_stmt).all()
    
    open_tasks_stmt = (
        select(Task)
        .where(
            Task.business_id == business.id,
            Task.status == "open",
            Task.deleted_at.is_(None),
        )
        .order_by(Task.created_at.desc())
        .limit(10)
    )
    open_tasks = session.exec(open_tasks_stmt).all()
    
    recent_calls_stmt = (
        select(Call)
        .where(Call.business_id == business.id)
        .order_by(Call.created_at.desc())
        .limit(5)
    )
    recent_calls = session.exec(recent_calls_stmt).all()
    
    def task_to_response(t: Task) -> TaskResponse:
        return TaskResponse(
            id=str(t.id),
            business_id=str(t.business_id),
            title=t.title,
            description=t.description,
            due_at=t.due_at,
            recurrence=t.recurrence,
            status=t.status,
            source=t.source,
            created_at=t.created_at,
            updated_at=t.updated_at
        )
    
    def call_to_response(c: Call) -> CallResponse:
        return CallResponse(
            id=str(c.id),
            business_id=str(c.business_id),
            source=c.source,
            caller_number=c.caller_number,
            caller_name=c.caller_name,
            started_at=c.started_at,
            ended_at=c.ended_at,
            transcript=c.transcript,
            summary=c.summary,
            intent=c.intent,
            archived=getattr(c, 'archived', False),
            created_at=c.created_at,
            updated_at=getattr(c, 'updated_at', None),
        )
    
    return BriefingResponse(
        tasks_due_today=[task_to_response(t) for t in tasks_due_today],
        overdue_tasks=[task_to_response(t) for t in overdue_tasks],
        open_tasks=[task_to_response(t) for t in open_tasks],
        recent_calls=[call_to_response(c) for c in recent_calls],
        generated_at=now
    )


@app.post("/v1/assistant/chat", response_model=ChatResponse, tags=["Assistant"])
async def assistant_chat(
    data: ChatRequest,
    token: str = Depends(get_access_token)
):
    """AI Assistant chat endpoint.
    
    Authenticates user via Supabase access token, determines business context,
    and processes the message through the AI assistant with tool calling capabilities.
    
    Authentication: Bearer token (Supabase access token) in Authorization header.
    """
    user = await verify_supabase_token(token)
    
    result = await process_chat_message(
        user=user,
        message=data.message,
        conversation_id=data.conversation_id,
        business_id=data.business_id,
        voice_mode=data.voice_mode
    )
    
    if "error" in result:
        status_code = result.get("status", 500)
        raise HTTPException(status_code=status_code, detail=result["error"])
    
    return ChatResponse(
        reply=result["reply"],
        business_id=result["business_id"],
        business=ChatBusinessInfo(
            id=result["business"]["id"],
            name=result["business"]["name"],
            timezone=result["business"]["timezone"]
        ),
        conversation_id=result.get("conversation_id")
    )


@app.post("/v1/tts", tags=["Assistant"])
async def text_to_speech(
    request: Request,
    token: str = Depends(get_access_token)
):
    """Convert text to speech using OpenAI TTS API.
    
    Returns audio as base64-encoded MP3.
    Voice options: alloy, echo, fable, onyx, nova, shimmer
    """
    from openai import OpenAI
    
    # Verify user is authenticated
    await verify_supabase_token(token)
    
    try:
        data = await request.json()
        text = data.get("text", "")
        voice = data.get("voice", "nova")  # nova is a natural female voice
        
        if not text:
            raise HTTPException(status_code=400, detail="Text is required")
        
        # Validate voice option
        valid_voices = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]
        if voice not in valid_voices:
            voice = "nova"
        
        # Limit text length to control costs (roughly 4096 chars max)
        if len(text) > 4096:
            text = text[:4096]
        
        openai_api_key = os.getenv("OPENAI_API_KEY")
        if not openai_api_key:
            raise HTTPException(status_code=500, detail="OpenAI API key not configured")
        
        client = OpenAI(api_key=openai_api_key)
        
        response = client.audio.speech.create(
            model="tts-1",  # Use tts-1-hd for higher quality but more cost
            voice=voice,
            input=text,
            response_format="mp3"
        )
        
        # Return audio as base64
        audio_base64 = base64.b64encode(response.content).decode('utf-8')
        
        return {"audio": audio_base64, "format": "mp3"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"TTS error: {e}")
        raise HTTPException(status_code=500, detail=f"TTS failed: {str(e)}")


# ============================================================================
# INVOICE ENDPOINTS
# ============================================================================

def normalize_column_name(name: str) -> str:
    """Normalize CSV column names for matching."""
    return name.lower().strip().replace('_', '').replace('-', '').replace(' ', '')


def parse_date(value: str) -> Optional[date_type]:
    """Parse date from string, trying common formats."""
    if not value or not value.strip():
        return None
    value = value.strip()
    formats = ['%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%Y/%m/%d', '%d-%m-%Y', '%m-%d-%Y']
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def parse_amount(value: str) -> Optional[float]:
    """Parse amount from string, removing currency symbols."""
    if not value or not value.strip():
        return None


def ensure_awaz_integration(business_id: str, session: Session) -> Integration:
    """Ensure Awaz integration row exists with a webhook secret."""
    integration = session.exec(
        select(Integration).where(
            Integration.business_id == business_id,
            Integration.integration_type == "awaz",
        )
    ).first()
    if integration:
        return integration

    config = {
        "webhook_secret": secrets.token_urlsafe(32),
        "last_received_at": None,
        "last_error": None,
        "receptionist_name": None,
        "phone_number": None,
    }
    integration = Integration(
        business_id=business_id,
        integration_type="awaz",
        is_enabled=False,
        config=config,
    )
    session.add(integration)
    session.commit()
    session.refresh(integration)
    return integration


def get_awaz_integration(business_id: str, session: Session) -> Dict[str, Any]:
    """Return Awaz integration id + config."""
    integration = session.exec(
        select(Integration).where(
            Integration.business_id == business_id,
            Integration.integration_type == "awaz",
        )
    ).first()
    if not integration:
        raise HTTPException(status_code=404, detail="Awaz integration not found")
    return {"id": str(integration.id), "config": integration.config or {}}


def require_platform_admin(auth_ctx: dict, session: Session) -> None:
    if not is_platform_admin_user(auth_ctx["user_id"], session):
        raise HTTPException(status_code=403, detail="Insufficient permissions")


logger = logging.getLogger("admin")


async def _run_awaz_test_for_business(business_id: str, session: Session) -> str:
    business = session.exec(
        select(Business).where(Business.id == business_id)
    ).first()
    if not business:
        raise HTTPException(status_code=404, detail="Business not found")

    integration = ensure_awaz_integration(business_id, session)
    config = integration.config or {}

    payload = CallCreate(
        caller_number=config.get("phone_number") or "+440000000000",
        caller_name=config.get("receptionist_name") or "Awaz Test",
        started_at=datetime.utcnow(),
        ended_at=datetime.utcnow(),
        transcript="Test call from Awaz integration.",
        intent="test",
        create_follow_up_task=True,
    )
    response = await _create_call_record(payload, business, session)

    config["last_received_at"] = datetime.utcnow().isoformat()
    config["last_error"] = None
    integration.config = config
    integration.updated_at = datetime.utcnow()
    session.add(integration)
    session.commit()

    return response.id


def _run_email_sync_for_business(business_id: str, session: Session) -> EmailSyncRunResponse:
    business = get_business_by_id(session, business_id)
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

    return EmailSyncRunResponse(
        email_account_id=str(account.id),
        synced=True,
        message_count=message_count,
        cursor=sync_state.cursor,
    )


def _get_frontend_base_url(request: Request) -> str:
    config = get_stripe_config()
    base_url = config.get("app_base_url")
    if base_url:
        return str(base_url).rstrip("/")
    return str(request.base_url).rstrip("/")


def _plan_feature_defaults(plan_tier: str) -> Dict[str, bool]:
    defaults = {
        "starter": {},
        "pro": {"email": True},
        "elite": {"email": True, "calendar": True, "voice": True},
        "beta": {"email": True, "calendar": True, "voice": True},
        "paused": {},
    }
    return defaults.get(plan_tier, {})


def _merge_feature_flags(existing: Dict[str, Any], plan_tier: str) -> Dict[str, Any]:
    defaults = _plan_feature_defaults(plan_tier)
    merged = {**defaults, **(existing or {})}
    return merged


def _resolve_plan_from_price(price_id: str) -> Optional[str]:
    if not price_id:
        return None
    config = get_stripe_config()
    prices = config.get("prices", {})
    if price_id == prices.get("starter"):
        return "starter"
    if price_id == prices.get("pro"):
        return "pro"
    if price_id == prices.get("elite"):
        return "elite"
    return None


def resolve_awaz_business_id(
    auth_ctx: dict,
    session: Session,
    business_id: Optional[str] = None,
) -> str:
    if business_id and business_id != auth_ctx["business_id"]:
        if not is_platform_admin_user(auth_ctx["user_id"], session):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return business_id
    return auth_ctx["business_id"]


def _build_awaz_webhook_url(request: Request, webhook_secret: str) -> str:
    base_url = os.getenv("PUBLIC_BASE_URL")
    if base_url:
        base = base_url.rstrip("/")
    else:
        base = str(request.base_url).rstrip("/")
    return f"{base}/v1/webhooks/awaz/calls?api_key={webhook_secret}"


def _parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    value = value.strip().replace('£', '').replace('$', '').replace(',', '').replace('€', '')
    try:
        return float(value)
    except ValueError:
        return None


def generate_chase_email(invoice: Invoice, business: Business, stage: int, user_name: Optional[str] = None) -> Dict[str, str]:
    """Generate chase email subject/body based on stage (1-4).
    
    Uses professional escalating templates from email_templates module.
    """
    from email_templates import get_chase_email_template
    
    # Normalize stage to 1-4 range (previously was 0-3, now 1-4)
    stage = min(max(stage, 1), 4)
    
    # Build invoice data dict for template
    invoice_data = {
        "customer_name": invoice.customer_name or "Customer",
        "invoice_number": invoice.invoice_number,
        "amount": float(invoice.amount) if invoice.amount else 0,
        "due_date": invoice.due_date.strftime("%d/%m/%Y") if invoice.due_date else "N/A",
        "currency": invoice.currency or "£"
    }
    
    return get_chase_email_template(stage, invoice_data, business.name, user_name)


@app.get("/v1/invoices", response_model=InvoiceListResponse, tags=["Invoices"])
async def list_invoices(
    status: Optional[str] = Query(default=None, description="Filter by status: unpaid, paid, partially_paid, cancelled"),
    overdue: Optional[bool] = Query(default=None, description="Filter overdue invoices"),
    archived: Optional[bool] = Query(default=False, description="Include archived invoices"),
    search: Optional[str] = Query(default=None, description="Search by customer name, invoice number, or email"),
    sort_by: Optional[str] = Query(default="due_date", description="Sort by: due_date, amount, created_at, customer_name, status"),
    sort_order: Optional[str] = Query(default="asc", description="Sort order: asc or desc"),
    limit: int = Query(default=50, ge=1, le=500, description="Maximum number of invoices to return"),
    offset: int = Query(default=0, ge=0, description="Offset for pagination"),
    business: Business = Depends(get_current_user_business),
    session: Session = Depends(get_session)
):
    """List invoices for the current business with filtering, searching, and sorting.
    
    Authentication: Bearer token (Supabase access token) in Authorization header.
    """
    from datetime import date as date_type
    
    statement = select(Invoice).where(Invoice.business_id == business.id)
    
    # Filter by archived status
    if not archived:
        statement = statement.where(or_(Invoice.archived == False, Invoice.archived == None))
    
    # Filter by status
    if status:
        statement = statement.where(Invoice.status == status)
    
    # Filter by overdue
    if overdue is True:
        today = date_type.today()
        statement = statement.where(Invoice.due_date < today).where(Invoice.status != 'paid')
    elif overdue is False:
        today = date_type.today()
        statement = statement.where(
            (Invoice.due_date >= today) | (Invoice.status == 'paid')
        )
    
    # Search
    if search:
        search_term = f"%{search}%"
        statement = statement.where(
            or_(
                Invoice.customer_name.ilike(search_term),
                Invoice.invoice_number.ilike(search_term),
                Invoice.customer_email.ilike(search_term)
            )
        )
    
    # Sorting
    sort_column_map = {
        "due_date": Invoice.due_date,
        "amount": Invoice.amount,
        "created_at": Invoice.created_at,
        "customer_name": Invoice.customer_name,
        "status": Invoice.status,
    }
    sort_column = sort_column_map.get(sort_by, Invoice.due_date)
    
    if sort_order == "desc":
        statement = statement.order_by(sort_column.desc())
    else:
        statement = statement.order_by(sort_column.asc())
    
    # Get total count (before pagination)
    count_statement = select(func.count()).select_from(statement.subquery())
    total = session.exec(count_statement).one()
    
    # Apply pagination
    statement = statement.offset(offset).limit(limit)
    
    invoices = session.exec(statement).all()
    
    def invoice_to_response(inv: Invoice) -> InvoiceSchema:
        return InvoiceSchema(
            id=str(inv.id),
            business_id=str(inv.business_id),
            invoice_number=inv.invoice_number,
            customer_name=inv.customer_name,
            customer_email=inv.customer_email,
            issue_date=inv.issue_date,
            due_date=inv.due_date,
            amount=float(inv.amount) if inv.amount else 0,
            currency=inv.currency,
            status=inv.status or "unpaid",
            paid_date=inv.paid_date,
            paid_amount=float(inv.paid_amount) if inv.paid_amount else None,
            paid_at=inv.paid_at,
            archived=inv.archived or False,
            last_chased_at=inv.last_chased_at,
            chase_stage=inv.chase_stage or 0,
            source=inv.source,
            source_ref=inv.source_ref,
            created_at=inv.created_at,
            updated_at=inv.updated_at
        )
    
    return InvoiceListResponse(
        invoices=[invoice_to_response(inv) for inv in invoices],
        total=total,
        limit=limit,
        offset=offset
    )


@app.patch("/v1/invoices/{invoice_id}/status", tags=["Invoices"])
async def update_invoice_status(
    invoice_id: str,
    status: str = Query(..., description="New status: paid, unpaid, partially_paid, cancelled"),
    paid_amount: Optional[float] = Query(None, description="Amount paid (for partial payments)"),
    paid_date: Optional[str] = Query(None, description="Date of payment (ISO format)"),
    user_business=Depends(get_current_user_and_business),
    session: Session = Depends(get_session),
):
    """Update invoice status (mark as paid, cancelled, etc.)."""
    _, business = user_business
    
    invoice = session.exec(
        select(Invoice).where(
            Invoice.id == invoice_id,
            Invoice.business_id == business.id
        )
    ).first()
    
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    valid_statuses = ["paid", "unpaid", "partially_paid", "cancelled"]
    if status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {valid_statuses}")
    
    invoice.status = status
    invoice.updated_at = datetime.utcnow()
    
    if status == "paid":
        invoice.paid_amount = float(invoice.amount) if invoice.amount else 0
        invoice.paid_at = datetime.fromisoformat(paid_date.replace("Z", "+00:00")) if paid_date else datetime.utcnow()
    elif status == "partially_paid" and paid_amount is not None:
        invoice.paid_amount = paid_amount
        invoice.paid_at = datetime.fromisoformat(paid_date.replace("Z", "+00:00")) if paid_date else datetime.utcnow()
    elif status == "unpaid":
        invoice.paid_amount = None
        invoice.paid_at = None
    
    session.add(invoice)
    session.commit()
    session.refresh(invoice)
    
    return {
        "success": True,
        "invoice_id": str(invoice.id),
        "status": invoice.status,
        "paid_amount": float(invoice.paid_amount) if invoice.paid_amount else None,
        "paid_at": invoice.paid_at.isoformat() if invoice.paid_at else None
    }


@app.patch("/v1/invoices/{invoice_id}/archive", tags=["Invoices"])
async def archive_invoice(
    invoice_id: str,
    user_business=Depends(get_current_user_and_business),
    session: Session = Depends(get_session),
):
    """Archive or unarchive an invoice (soft delete toggle)."""
    _, business = user_business
    
    invoice = session.exec(
        select(Invoice).where(
            Invoice.id == invoice_id,
            Invoice.business_id == business.id
        )
    ).first()
    
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    invoice.archived = not (invoice.archived or False)
    invoice.updated_at = datetime.utcnow()
    session.add(invoice)
    session.commit()
    
    return {"success": True, "archived": invoice.archived}


@app.delete("/v1/invoices/{invoice_id}", tags=["Invoices"])
async def delete_invoice(
    invoice_id: str,
    user_business=Depends(get_current_user_and_business),
    session: Session = Depends(get_session),
):
    """Permanently delete an invoice."""
    _, business = user_business
    
    invoice = session.exec(
        select(Invoice).where(
            Invoice.id == invoice_id,
            Invoice.business_id == business.id
        )
    ).first()
    
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    session.delete(invoice)
    session.commit()
    
    return {"success": True, "deleted": True}


@app.post("/v1/invoices/import/csv", response_model=ImportResponse, tags=["Invoices"])
async def import_invoices_csv(
    file: UploadFile = File(...),
    business: Business = Depends(get_current_user_business),
    session: Session = Depends(get_session)
):
    """Import invoices from CSV file.
    
    Authentication: Bearer token (Supabase access token) in Authorization header.
    
    CSV should have headers. Common column names are automatically mapped:
    - invoice_number, invoice, invoice_no, inv_number
    - customer_name, customer, client_name, client
    - customer_email, email, client_email
    - issue_date, issued_date, date_issued
    - due_date, due, payment_due
    - amount, total, invoice_amount
    - status, payment_status
    """
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="File must be a CSV")
    
    content = await file.read()
    text_content = content.decode('utf-8-sig')  # Handle BOM
    reader = csv.DictReader(io.StringIO(text_content))
    
    # Map common column names
    column_map = {}
    for col in reader.fieldnames or []:
        normalized = normalize_column_name(col)
        if normalized in ['invoicenumber', 'invoice', 'invoiceno', 'invnumber']:
            column_map['invoice_number'] = col
        elif normalized in ['customername', 'customer', 'clientname', 'client']:
            column_map['customer_name'] = col
        elif normalized in ['customeremail', 'email', 'clientemail']:
            column_map['customer_email'] = col
        elif normalized in ['issuedate', 'issueddate', 'dateissued']:
            column_map['issue_date'] = col
        elif normalized in ['duedate', 'due', 'paymentdue']:
            column_map['due_date'] = col
        elif normalized in ['amount', 'total', 'invoiceamount']:
            column_map['amount'] = col
        elif normalized in ['status', 'paymentstatus']:
            column_map['status'] = col
    
    if 'invoice_number' not in column_map or 'due_date' not in column_map or 'amount' not in column_map:
        raise HTTPException(
            status_code=400,
            detail="CSV must contain invoice_number, due_date, and amount columns"
        )
    
    imported = 0
    updated = 0
    errors = []
    
    for row_num, row in enumerate(reader, start=2):  # Start at 2 (header is row 1)
        try:
            invoice_number = row.get(column_map.get('invoice_number', ''), '').strip()
            if not invoice_number:
                errors.append(f"Row {row_num}: Missing invoice_number")
                continue
            
            customer_name = row.get(column_map.get('customer_name', ''), '').strip()
            if not customer_name:
                errors.append(f"Row {row_num}: Missing customer_name")
                continue
            
            customer_email = row.get(column_map.get('customer_email', ''), '').strip() or None
            issue_date = parse_date(row.get(column_map.get('issue_date', ''), ''))
            due_date = parse_date(row.get(column_map.get('due_date', ''), ''))
            if not due_date:
                errors.append(f"Row {row_num}: Invalid or missing due_date")
                continue
            
            amount = parse_amount(row.get(column_map.get('amount', ''), ''))
            if amount is None:
                errors.append(f"Row {row_num}: Invalid or missing amount")
                continue
            
            status = row.get(column_map.get('status', ''), '').strip().lower() or 'unpaid'
            if status not in ['paid', 'unpaid', 'overdue', 'cancelled']:
                status = 'unpaid'
            
            # Check if invoice exists
            existing = session.exec(
                select(Invoice).where(
                    Invoice.business_id == business.id,
                    Invoice.invoice_number == invoice_number
                )
            ).first()
            
            if existing:
                # Update existing
                existing.customer_name = customer_name
                existing.customer_email = customer_email
                existing.issue_date = issue_date
                existing.due_date = due_date
                existing.amount = Decimal(str(amount))
                existing.status = status
                existing.source = 'csv'
                session.add(existing)
                updated += 1
            else:
                # Create new
                invoice = Invoice(
                    business_id=business.id,
                    invoice_number=invoice_number,
                    customer_name=customer_name,
                    customer_email=customer_email,
                    issue_date=issue_date,
                    due_date=due_date,
                    amount=Decimal(str(amount)),
                    currency='GBP',
                    status=status,
                    source='csv'
                )
                session.add(invoice)
                imported += 1
        except Exception as e:
            errors.append(f"Row {row_num}: {str(e)}")
    
    session.commit()
    
    return ImportResponse(imported=imported, updated=updated, errors=errors)


@app.post("/v1/invoices/{invoice_id}/mark-chased", response_model=InvoiceSchema, tags=["Invoices"])
async def mark_invoice_chased(
    invoice_id: str,
    business: Business = Depends(get_current_user_business),
    session: Session = Depends(get_session)
):
    """Mark an invoice as chased (increment chase stage and update last_chased_at).
    
    Authentication: Bearer token (Supabase access token) in Authorization header.
    """
    invoice = session.exec(
        select(Invoice).where(
            Invoice.id == invoice_id,
            Invoice.business_id == business.id
        )
    ).first()
    
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    invoice.last_chased_at = datetime.utcnow()
    invoice.chase_stage = invoice.chase_stage + 1
    
    session.add(invoice)
    session.commit()
    session.refresh(invoice)
    
    return InvoiceSchema(
        id=str(invoice.id),
        business_id=str(invoice.business_id),
        invoice_number=invoice.invoice_number,
        customer_name=invoice.customer_name,
        customer_email=invoice.customer_email,
        issue_date=invoice.issue_date,
        due_date=invoice.due_date,
        amount=float(invoice.amount),
        currency=invoice.currency,
        status=invoice.status,
        paid_date=invoice.paid_date,
        last_chased_at=invoice.last_chased_at,
        chase_stage=invoice.chase_stage,
        source=invoice.source,
        source_ref=invoice.source_ref,
        created_at=invoice.created_at,
        updated_at=invoice.updated_at
    )


@app.post("/v1/invoices/{invoice_id}/chase-draft", response_model=ChaseDraftResponse, tags=["Invoices"])
async def get_chase_draft(
    invoice_id: str,
    stage: Optional[int] = Query(default=None, ge=1, le=4, description="Chase stage (1-4), defaults to next stage"),
    user_business=Depends(get_current_user_and_business),
    session: Session = Depends(get_session)
):
    """Get email draft for chasing an invoice.
    
    Authentication: Bearer token (Supabase access token) in Authorization header.
    
    Returns email subject and body based on chase stage (1-4).
    Does NOT send the email.
    """
    from email_templates import get_stage_description
    
    user, business = user_business
    invoice = session.exec(
        select(Invoice).where(
            Invoice.id == invoice_id,
            Invoice.business_id == business.id
        )
    ).first()
    
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    # Get user's name for email signature
    user_name = None
    try:
        result = session.execute(text("""
            SELECT full_name, display_name FROM profiles WHERE id = :user_id
        """), {"user_id": str(user.id)})
        row = result.fetchone()
        if row:
            user_name = row[1] or row[0]
    except Exception:
        pass
    
    # Determine stage: use provided stage or next stage (current+1, min 1, max 4)
    if stage is not None:
        chase_stage = stage
    else:
        chase_stage = min((invoice.chase_stage or 0) + 1, 4)
    
    template = generate_chase_email(invoice, business, chase_stage, user_name)

    return ChaseDraftResponse(
        subject=template["subject"],
        body=template["body"],
        chase_stage=chase_stage,
        stage_description=get_stage_description(chase_stage)
    )


# ============================================================================
# INVOICE CHASE SEND ENDPOINTS
# ============================================================================

@app.post("/v1/invoices/{invoice_id}/send-chase", response_model=SendChaseResponse, tags=["Invoices"])
async def send_chase_email(
    invoice_id: str,
    data: SendChaseRequest,
    user_business=Depends(get_current_user_and_business),
    session: Session = Depends(get_session)
):
    """Send a chase email for a single invoice at specified stage (1-4)."""
    from email_templates import get_stage_description
    
    user, business = user_business
    invoice = session.exec(
        select(Invoice).where(
            Invoice.id == invoice_id,
            Invoice.business_id == business.id
        )
    ).first()

    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    # Get user's name for email signature
    user_name = None
    try:
        result = session.execute(text("""
            SELECT full_name, display_name FROM profiles WHERE id = :user_id
        """), {"user_id": str(user.id)})
        row = result.fetchone()
        if row:
            user_name = row[1] or row[0]  # Prefer display_name over full_name
    except Exception:
        pass  # profiles table might not exist

    # Determine stage (1-4, default to current+1 or 1)
    if data.chase_stage is not None:
        stage = min(max(data.chase_stage, 1), 4)
    else:
        # Auto-increment: if current stage is 0, start at 1; otherwise next stage up to 4
        stage = min((invoice.chase_stage or 0) + 1, 4)
    
    template = generate_chase_email(invoice, business, stage, user_name)
    subject = data.subject or template["subject"]
    body = data.body or template["body"]
    stage_desc = get_stage_description(stage)

    if data.dry_run:
        return SendChaseResponse(
            invoice_id=str(invoice.id),
            subject=subject,
            body=body,
            chase_stage=stage,
            stage_description=stage_desc,
            status="dry_run",
            dry_run=True
        )

    # Get email account (OAuth or SMTP)
    oauth_account, smtp_connection = get_email_account_for_sending(session, str(business.id))
    
    if not oauth_account and not smtp_connection:
        raise HTTPException(status_code=400, detail="No email account configured. Please connect Google/Microsoft or configure SMTP in Email Settings.")

    # Create outbox entry
    outbox = EmailOutbox(
        business_id=business.id,
        email_account_id=oauth_account.id if oauth_account else None,
        invoice_id=invoice.id,
        chase_stage=stage,
        to_emails=[invoice.customer_email or ""],
        subject=subject,
        body_preview=body,
        status="queued",
    )
    session.add(outbox)
    session.commit()
    session.refresh(outbox)

    if not invoice.customer_email:
        outbox.status = "failed"
        outbox.error = "Customer email not set"
        session.add(outbox)
        session.commit()
        return SendChaseResponse(
            invoice_id=str(invoice.id),
            subject=subject,
            body=body,
            chase_stage=stage,
            stage_description=stage_desc,
            status="failed",
            error_message="Customer email not set",
            outbox_id=str(outbox.id)
        )

    try:
        if oauth_account:
            send_email_oauth(session, oauth_account, invoice.customer_email, subject, body)
        else:
            send_email_smtp(smtp_connection, invoice.customer_email, subject, body)
        
        outbox.status = "sent"
        outbox.sent_at = datetime.utcnow()
        session.add(outbox)

        invoice.last_chased_at = datetime.utcnow()
        invoice.chase_stage = stage  # Set to the actual stage sent
        session.add(invoice)

        session.commit()
        return SendChaseResponse(
            invoice_id=str(invoice.id),
            subject=subject,
            body=body,
            chase_stage=stage,
            stage_description=stage_desc,
            status="sent",
            outbox_id=str(outbox.id)
        )
    except Exception as exc:
        outbox.status = "failed"
        outbox.error = str(exc)
        session.add(outbox)
        session.commit()
        return SendChaseResponse(
            invoice_id=str(invoice.id),
            subject=subject,
            body=body,
            chase_stage=stage,
            stage_description=stage_desc,
            status="failed",
            error_message=str(exc),
            outbox_id=str(outbox.id)
        )


@app.post("/v1/invoices/send-chase/bulk", response_model=BulkSendResponse, tags=["Invoices"])
async def send_chase_bulk(
    data: BulkSendRequest,
    user_business=Depends(get_current_user_and_business),
    session: Session = Depends(get_session)
):
    """Send chase emails for multiple invoices at specified stage (1-4)."""
    from email_templates import get_stage_description
    
    user, business = user_business
    results: List[SendChaseResponse] = []
    sent = 0
    failed = 0

    # Get user's name for email signature
    user_name = None
    try:
        result = session.execute(text("""
            SELECT full_name, display_name FROM profiles WHERE id = :user_id
        """), {"user_id": str(user.id)})
        row = result.fetchone()
        if row:
            user_name = row[1] or row[0]
    except Exception:
        pass

    invoices = session.exec(
        select(Invoice).where(
            Invoice.business_id == business.id,
            Invoice.id.in_(data.invoice_ids)
        )
    ).all()
    invoice_map = {str(inv.id): inv for inv in invoices}

    oauth_account = None
    smtp_connection = None
    if not data.dry_run:
        oauth_account, smtp_connection = get_email_account_for_sending(session, str(business.id))
        if not oauth_account and not smtp_connection:
            raise HTTPException(status_code=400, detail="No email account configured. Please connect Google/Microsoft or configure SMTP in Email Settings.")

    window_start = datetime.utcnow() - timedelta(minutes=1)
    recent_count = session.exec(
        select(func.count())
        .select_from(EmailOutbox)
        .where(
            EmailOutbox.business_id == business.id,
            EmailOutbox.created_at >= window_start
        )
    ).one()
    sent_in_window = int(recent_count or 0)

    for invoice_id in data.invoice_ids:
        invoice = invoice_map.get(invoice_id)
        if not invoice:
            failed += 1
            stage = min(max(data.chase_stage or 1, 1), 4)
            results.append(SendChaseResponse(
                invoice_id=invoice_id,
                subject="",
                body="",
                chase_stage=stage,
                stage_description=get_stage_description(stage),
                status="failed",
                error_message="Invoice not found"
            ))
            continue

        # Determine stage: use provided or next stage (current+1, min 1, max 4)
        if data.chase_stage is not None:
            stage = min(max(data.chase_stage, 1), 4)
        else:
            stage = min((invoice.chase_stage or 0) + 1, 4)
        
        stage_desc = get_stage_description(stage)
        template = generate_chase_email(invoice, business, stage, user_name)
        subject = template["subject"]
        body = template["body"]

        if data.dry_run:
            results.append(SendChaseResponse(
                invoice_id=str(invoice.id),
                subject=subject,
                body=body,
                chase_stage=stage,
                stage_description=stage_desc,
                status="dry_run",
                dry_run=True
            ))
            continue

        if sent_in_window >= 30:
            failed += 1
            results.append(SendChaseResponse(
                invoice_id=str(invoice.id),
                subject=subject,
                body=body,
                chase_stage=stage,
                stage_description=stage_desc,
                status="failed",
                error_message="Rate limit exceeded"
            ))
            continue

        if not invoice.customer_email:
            failed += 1
            results.append(SendChaseResponse(
                invoice_id=str(invoice.id),
                subject=subject,
                body=body,
                chase_stage=stage,
                stage_description=stage_desc,
                status="failed",
                error_message="Customer email not set"
            ))
            continue

        outbox = EmailOutbox(
            business_id=business.id,
            email_account_id=oauth_account.id if oauth_account else None,
            invoice_id=invoice.id,
            chase_stage=stage,
            to_emails=[invoice.customer_email],
            subject=subject,
            body_preview=body,
            status="queued",
        )
        session.add(outbox)
        session.commit()
        session.refresh(outbox)

        try:
            if oauth_account:
                send_email_oauth(session, oauth_account, invoice.customer_email, subject, body)
            else:
                send_email_smtp(smtp_connection, invoice.customer_email, subject, body)
            outbox.status = "sent"
            outbox.sent_at = datetime.utcnow()
            session.add(outbox)

            invoice.last_chased_at = datetime.utcnow()
            invoice.chase_stage = stage  # Set to the actual stage sent
            session.add(invoice)

            session.commit()
            sent += 1
            sent_in_window += 1
            results.append(SendChaseResponse(
                invoice_id=str(invoice.id),
                subject=subject,
                body=body,
                chase_stage=stage,
                stage_description=stage_desc,
                status="sent",
                outbox_id=str(outbox.id)
            ))
        except Exception as exc:
            outbox.status = "failed"
            outbox.error = str(exc)
            session.add(outbox)
            session.commit()
            failed += 1
            results.append(SendChaseResponse(
                invoice_id=str(invoice.id),
                subject=subject,
                body=body,
                chase_stage=stage,
                stage_description=stage_desc,
                status="failed",
                error_message=str(exc),
                outbox_id=str(outbox.id)
            ))

    return BulkSendResponse(
        total=len(data.invoice_ids),
        sent=sent,
        failed=failed,
        results=results
    )


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 3000))
    uvicorn.run(app, host="0.0.0.0", port=port)

