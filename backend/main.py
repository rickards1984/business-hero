"""FastAPI application for AI Admin Assistant."""

import os
import json
import copy
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlmodel import Session, select
import pytz

from db import init_db, get_session
from models import Business, Task, Call, BusinessSettings, Integration
from schemas import (
    BusinessCreate, BusinessResponse, BusinessListItem, BusinessProfile,
    TaskCreate, TaskResponse, SnoozeRequest,
    CallCreate, CallResponse,
    BriefingResponse, HealthResponse,
    ChatRequest, ChatResponse, ChatBusinessInfo,
    BusinessSettingsResponse, BusinessSettingsUpdate,
    IntegrationResponse, IntegrationListResponse, IntegrationUpdate
)
from auth import verify_master_key, get_current_business, get_access_token
from openai_utils import generate_call_summary
from supabase_auth import verify_supabase_token
from assistant_chat import process_chat_message


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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """Health check endpoint."""
    return HealthResponse(ok=True)


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
async def get_my_profile(business: Business = Depends(get_current_business)):
    """Get current business profile."""
    return BusinessProfile(
        id=str(business.id),
        name=business.name,
        timezone=business.timezone,
        logo_url=business.logo_url
    )


@app.get("/v1/business/settings", response_model=BusinessSettingsResponse, tags=["Business"])
async def get_business_settings(
    business: Business = Depends(get_current_business),
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
    business: Business = Depends(get_current_business),
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
    business: Business = Depends(get_current_business),
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
    business: Business = Depends(get_current_business),
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
    business: Business = Depends(get_current_business)
):
    """
    Generate a signed upload URL for business logo.
    
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
    business: Business = Depends(get_current_business),
    session: Session = Depends(get_session)
):
    """Update the logo URL for the current business."""
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
    business: Business = Depends(get_current_business),
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
    business: Business = Depends(get_current_business),
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
    business: Business = Depends(get_current_business),
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
    business: Business = Depends(get_current_business),
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
    business: Business = Depends(get_current_business),
    session: Session = Depends(get_session)
):
    """
    Create a call event from Awaz webhook or other sources.
    Optionally auto-creates a follow-up task.
    """
    raw_payload = json.dumps(data.model_dump(mode="json"))
    
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
        intent=data.intent
    )
    session.add(call_event)
    
    if data.create_follow_up_task or data.intent == "new_lead":
        caller_info = data.caller_name or data.caller_number or "Unknown"
        follow_up_task = Task(
            business_id=business.id,
            title=f"Follow up call: {caller_info}",
            description=f"Follow up on call from {caller_info}. Intent: {data.intent or 'not specified'}",
            source="awaz",
            status="open"
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
        created_at=call_event.created_at
    )


@app.get("/v1/calls", response_model=List[CallResponse], tags=["Calls"])
async def list_calls(
    limit: int = Query(50, le=100, description="Maximum number of calls to return"),
    business: Business = Depends(get_current_business),
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
    business: Business = Depends(get_current_business),
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


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 3000))
    uvicorn.run(app, host="0.0.0.0", port=port)
