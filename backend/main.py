"""FastAPI application for AI Admin Assistant."""

import os
import json
import copy
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException, Query, Request, status, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, APIKeyHeader
from sqlmodel import Session, select
from sqlalchemy import text, func
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
)
from auth import verify_master_key, get_current_business, get_access_token, get_user_business_context
from openai_utils import generate_call_summary
from supabase_auth import verify_supabase_token
from assistant_chat import process_chat_message, get_business_for_user
from app.email.service import (
    get_or_create_smtp_account,
    send_email_smtp,
)
from app.email.router import (
    router as email_router,
    build_google_oauth_start_url,
    build_microsoft_oauth_start_url,
)


async def get_current_user_business(
    token: str = Depends(get_access_token),
    session: Session = Depends(get_session)
) -> Business:
    """Get current business from Supabase JWT token.
    
    For user-facing endpoints (dashboard, mobile app) that use Supabase auth.
    Validates JWT and looks up user's business via business_members table.
    """
    user = await verify_supabase_token(token)
    
    try:
        business_ctx = get_business_for_user(user.id)
    except ValueError as e:
        args = e.args
        if len(args) >= 2:
            error_type, message = args[0], args[1]
            if error_type == "NO_BUSINESS":
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
            elif error_type == "FORBIDDEN":
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message)
            elif error_type == "NOT_FOUND":
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    
    statement = select(Business).where(Business.id == business_ctx.id)
    business = session.exec(statement).first()
    
    if not business:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Business not found"
        )
    
    return business


async def get_current_user_and_business(
    token: str = Depends(get_access_token),
    session: Session = Depends(get_session)
):
    """Get current Supabase user and business from JWT token."""
    user = await verify_supabase_token(token)

    try:
        business_ctx = get_business_for_user(user.id)
    except ValueError as e:
        args = e.args
        if len(args) >= 2:
            error_type, message = args[0], args[1]
            if error_type == "NO_BUSINESS":
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
            elif error_type == "FORBIDDEN":
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message)
            elif error_type == "NOT_FOUND":
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    statement = select(Business).where(Business.id == business_ctx.id)
    business = session.exec(statement).first()

    if not business:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Business not found"
        )

    return user, business


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

# CORS configuration
# Note: When allow_credentials=True, we cannot use "*" for allow_origins
# We must specify exact origins
allowed_origins = [
    "https://business-hero.vercel.app",  # Production Vercel frontend
    "http://localhost:5000",  # Local development
    "http://localhost:3000",  # Alternative local port
    "http://127.0.0.1:5000",  # Local development (127.0.0.1)
    "http://127.0.0.1:3000",  # Alternative local port (127.0.0.1)
]

# Add Replit origins if running on Replit
# Replit provides REPLIT_URL or we can construct from REPL_SLUG and REPL_OWNER
replit_url = os.getenv("REPLIT_URL")
if not replit_url:
    repl_slug = os.getenv("REPL_SLUG")
    repl_owner = os.getenv("REPL_OWNER")
    if repl_slug and repl_owner:
        # Construct Replit URL: https://<slug>.<owner>.repl.co
        replit_url = f"https://{repl_slug}.{repl_owner}.repl.co"

if replit_url:
    # Ensure URL starts with http/https
    if not replit_url.startswith("http"):
        replit_url = f"https://{replit_url}"
    allowed_origins.append(replit_url)
    # Also add .replit.app variant (Replit's newer domain)
    if ".repl.co" in replit_url:
        allowed_origins.append(replit_url.replace(".repl.co", ".replit.app"))
    elif ".replit.app" in replit_url:
        allowed_origins.append(replit_url.replace(".replit.app", ".repl.co"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(email_router)


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """Health check endpoint."""
    return HealthResponse(ok=True)


@app.get("/v1/oauth/google")
async def oauth_google_start(
    mode: Optional[str] = Query(default=None),
    auth_ctx=Depends(get_user_business_context),
):
    return RedirectResponse(url=build_google_oauth_start_url(auth_ctx, mode))


@app.get("/v1/oauth/microsoft")
async def oauth_microsoft_start(
    mode: Optional[str] = Query(default=None),
    auth_ctx=Depends(get_user_business_context),
):
    return RedirectResponse(url=build_microsoft_oauth_start_url(auth_ctx, mode))


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
        "/v1/tasks/{task_id}/complete": ["post"],
        "/v1/tasks/{task_id}/snooze": ["post"],
        "/v1/calls": ["get", "post"],
        "/v1/briefing/today": ["get"],
    }
    
    consequential_flags: Dict[str, Dict[str, bool]] = {
        "/health": {"get": False},
        "/v1/me": {"get": False},
        "/v1/tasks": {"get": False, "post": False},
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


@app.get("/v1/me", response_model=BusinessProfile, tags=["Business"])
async def get_my_profile(business: Business = Depends(get_current_user_business)):
    """Get current business profile."""
    return BusinessProfile(
        id=str(business.id),
        name=business.name,
        timezone=business.timezone,
        logo_url=business.logo_url
    )


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
                config=i.config,
                created_at=i.created_at,
                updated_at=i.updated_at
            )
            for i in integrations
        ]
    )


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
    statement = select(Task).where(Task.business_id == business.id)
    
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
    statement = select(Task).where(Task.id == task_id, Task.business_id == business.id)
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
    statement = select(Task).where(Task.id == task_id, Task.business_id == business.id)
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
) -> CallResponse:
    summary = data.summary
    if not summary and data.transcript:
        summary = await generate_call_summary(data.transcript)

    call_event = Call(
        business_id=business.id,
        source="Awaz",
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
        created_at=call_event.created_at,
    )


_awaz_api_key_header = APIKeyHeader(name="x-api-key", auto_error=False)
_awaz_bearer_auth = HTTPBearer(auto_error=False)


async def get_awaz_business(
    api_key: Optional[str] = Query(default=None, description="Business API key for Awaz webhooks"),
    x_api_key: Optional[str] = Depends(_awaz_api_key_header),
    authorization: Optional[HTTPAuthorizationCredentials] = Depends(_awaz_bearer_auth),
    session: Session = Depends(get_session),
) -> Business:
    token = api_key or x_api_key or (authorization.credentials if authorization else None)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication. Use x-api-key header, Authorization: Bearer <key>, or api_key query param",
        )
    statement = select(Business).where(Business.api_key == token)
    business = session.exec(statement).first()
    if not business:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    return business


@app.post("/v1/webhooks/awaz/calls", response_model=CallResponse, tags=["Webhooks"])
async def awaz_calls_webhook(
    data: CallCreate,
    business: Business = Depends(get_awaz_business),
    session: Session = Depends(get_session),
):
    """Handle Awaz calls webhook using business API key auth."""
    return await _create_call_record(data, business, session)


@app.get("/v1/calls", response_model=List[CallResponse], tags=["Calls"])
async def list_calls(
    limit: int = Query(50, le=100, description="Maximum number of calls to return"),
    business: Business = Depends(get_current_user_business),
    session: Session = Depends(get_session)
):
    """List recent call events for the current business."""
    statement = (
        select(Call)
        .where(Call.business_id == business.id)
        .order_by(Call.created_at.desc())
        .limit(limit)
    )
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
            created_at=c.created_at
        )
        for c in calls
    ]


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
            Task.due_at < now
        )
        .order_by(Task.due_at)
    )
    overdue_tasks = session.exec(overdue_stmt).all()
    
    open_tasks_stmt = (
        select(Task)
        .where(Task.business_id == business.id, Task.status == "open")
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
            created_at=c.created_at
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
        business_id=data.business_id
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
    value = value.strip().replace('£', '').replace('$', '').replace(',', '').replace('€', '')
    try:
        return float(value)
    except ValueError:
        return None


def generate_chase_email(invoice: Invoice, business: Business, stage: int) -> Dict[str, str]:
    """Generate chase email subject/body based on stage."""
    stage = min(max(stage, 0), 3)
    amount_text = f"{invoice.currency} {float(invoice.amount):.2f}"
    due_date = invoice.due_date.strftime("%d %B %Y")

    templates = {
        0: {
            "subject": f"Payment Reminder: Invoice {invoice.invoice_number}",
            "body": (
                f"Dear {invoice.customer_name},\n\n"
                f"This is a friendly reminder that payment for invoice {invoice.invoice_number} "
                f"in the amount of {amount_text} is now due.\n\n"
                "Please arrange payment at your earliest convenience.\n\n"
                "Thank you for your business.\n\n"
                f"Best regards,\n{business.name}"
            ),
        },
        1: {
            "subject": f"Second Notice: Invoice {invoice.invoice_number} - Payment Overdue",
            "body": (
                f"Dear {invoice.customer_name},\n\n"
                f"We have not yet received payment for invoice {invoice.invoice_number} "
                f"in the amount of {amount_text}, which was due on {due_date}.\n\n"
                "Please arrange payment immediately to avoid further action.\n\n"
                "If you have already made payment, please disregard this notice.\n\n"
                f"Best regards,\n{business.name}"
            ),
        },
        2: {
            "subject": f"Final Notice: Invoice {invoice.invoice_number} - Urgent Payment Required",
            "body": (
                f"Dear {invoice.customer_name},\n\n"
                f"This is our final notice regarding invoice {invoice.invoice_number} "
                f"in the amount of {amount_text}, which is now significantly overdue.\n\n"
                f"Payment was due on {due_date} and we have not received payment despite previous reminders.\n\n"
                "Please arrange payment immediately. If payment is not received within 7 days, "
                "we may need to take further action.\n\n"
                "If you have any queries or concerns, please contact us immediately.\n\n"
                f"Best regards,\n{business.name}"
            ),
        },
        3: {
            "subject": f"URGENT: Invoice {invoice.invoice_number} - Immediate Payment Required",
            "body": (
                f"Dear {invoice.customer_name},\n\n"
                f"This is an urgent final notice regarding invoice {invoice.invoice_number} "
                f"in the amount of {amount_text}.\n\n"
                f"This invoice is now overdue since {due_date}, and we have sent multiple reminders without response.\n\n"
                "We require immediate payment. If payment is not received within 3 business days, "
                "we will have no choice but to escalate this matter, which may include legal action.\n\n"
                "Please contact us immediately to discuss payment arrangements.\n\n"
                f"Best regards,\n{business.name}"
            ),
        },
    }

    return templates[stage]


@app.get("/v1/invoices", response_model=InvoiceListResponse, tags=["Invoices"])
async def list_invoices(
    status: Optional[str] = Query(default="unpaid", description="Filter by status"),
    overdue: Optional[bool] = Query(default=None, description="Filter overdue invoices"),
    limit: int = Query(default=50, ge=1, le=500, description="Maximum number of invoices to return"),
    business: Business = Depends(get_current_user_business),
    session: Session = Depends(get_session)
):
    """List invoices for the current business.
    
    Authentication: Bearer token (Supabase access token) in Authorization header.
    """
    from datetime import date as date_type
    
    statement = select(Invoice).where(Invoice.business_id == business.id)
    
    if status:
        statement = statement.where(Invoice.status == status)
    
    if overdue is True:
        today = date_type.today()
        statement = statement.where(Invoice.due_date < today).where(Invoice.status != 'paid')
    elif overdue is False:
        today = date_type.today()
        statement = statement.where(
            (Invoice.due_date >= today) | (Invoice.status == 'paid')
        )
    
    statement = statement.order_by(Invoice.due_date.asc()).limit(limit)
    
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
            amount=float(inv.amount),
            currency=inv.currency,
            status=inv.status,
            paid_date=inv.paid_date,
            last_chased_at=inv.last_chased_at,
            chase_stage=inv.chase_stage,
            source=inv.source,
            source_ref=inv.source_ref,
            created_at=inv.created_at,
            updated_at=inv.updated_at
        )
    
    return InvoiceListResponse(
        invoices=[invoice_to_response(inv) for inv in invoices],
        total=len(invoices)
    )


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
    business: Business = Depends(get_current_user_business),
    session: Session = Depends(get_session)
):
    """Get email draft for chasing an invoice.
    
    Authentication: Bearer token (Supabase access token) in Authorization header.
    
    Returns email subject and body based on chase stage (0-3).
    Does NOT send the email.
    """
    invoice = session.exec(
        select(Invoice).where(
            Invoice.id == invoice_id,
            Invoice.business_id == business.id
        )
    ).first()
    
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    template = generate_chase_email(invoice, business, invoice.chase_stage)

    return ChaseDraftResponse(
        subject=template["subject"],
        body=template["body"],
        chase_stage=invoice.chase_stage
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
    """Send a chase email for a single invoice."""
    user, business = user_business
    invoice = session.exec(
        select(Invoice).where(
            Invoice.id == invoice_id,
            Invoice.business_id == business.id
        )
    ).first()

    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    stage = data.chase_stage if data.chase_stage is not None else invoice.chase_stage
    template = generate_chase_email(invoice, business, stage)
    subject = data.subject or template["subject"]
    body = data.body or template["body"]

    if data.dry_run:
        return SendChaseResponse(
            invoice_id=str(invoice.id),
            subject=subject,
            body=body,
            chase_stage=stage,
            status="dry_run",
            dry_run=True
        )

    connection = session.exec(
        select(EmailConnection).where(EmailConnection.business_id == business.id)
    ).first()
    if not connection or not connection.is_enabled:
        raise HTTPException(status_code=400, detail="Email connection not configured or disabled")

    account = get_or_create_smtp_account(session, business, user.id, connection)
    outbox = EmailOutbox(
        business_id=business.id,
        email_account_id=account.id,
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
            status="failed",
            error_message="Customer email not set",
            outbox_id=str(outbox.id)
        )

    try:
        send_email_smtp(connection, invoice.customer_email, subject, body)
        outbox.status = "sent"
        outbox.sent_at = datetime.utcnow()
        session.add(outbox)

        invoice.last_chased_at = datetime.utcnow()
        invoice.chase_stage = invoice.chase_stage + 1
        session.add(invoice)

        session.commit()
        return SendChaseResponse(
            invoice_id=str(invoice.id),
            subject=subject,
            body=body,
            chase_stage=stage,
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
    """Send chase emails for multiple invoices."""
    _, business = user_business
    results: List[SendChaseResponse] = []
    sent = 0
    failed = 0

    invoices = session.exec(
        select(Invoice).where(
            Invoice.business_id == business.id,
            Invoice.id.in_(data.invoice_ids)
        )
    ).all()
    invoice_map = {str(inv.id): inv for inv in invoices}

    if not data.dry_run:
        connection = session.exec(
            select(EmailConnection).where(EmailConnection.business_id == business.id)
        ).first()
        if not connection or not connection.is_enabled:
            raise HTTPException(status_code=400, detail="Email connection not configured or disabled")
    account = get_or_create_smtp_account(session, business, user.id, connection)
        account = get_or_create_smtp_account(session, business, user.id, connection)

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
            results.append(SendChaseResponse(
                invoice_id=invoice_id,
                subject="",
                body="",
                chase_stage=data.chase_stage or 0,
                status="failed",
                error_message="Invoice not found"
            ))
            continue

        stage = data.chase_stage if data.chase_stage is not None else invoice.chase_stage
        template = generate_chase_email(invoice, business, stage)
        subject = template["subject"]
        body = template["body"]

        if data.dry_run:
            results.append(SendChaseResponse(
                invoice_id=str(invoice.id),
                subject=subject,
                body=body,
                chase_stage=stage,
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
                status="failed",
                error_message="Customer email not set"
            ))
            continue

        outbox = EmailOutbox(
            business_id=business.id,
            email_account_id=account.id,
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
            send_email_smtp(connection, invoice.customer_email, subject, body)
            outbox.status = "sent"
            outbox.sent_at = datetime.utcnow()
            session.add(outbox)

            invoice.last_chased_at = datetime.utcnow()
            invoice.chase_stage = invoice.chase_stage + 1
            session.add(invoice)

            session.commit()
            sent += 1
            sent_in_window += 1
            results.append(SendChaseResponse(
                invoice_id=str(invoice.id),
                subject=subject,
                body=body,
                chase_stage=stage,
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

