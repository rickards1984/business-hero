"""Pydantic schemas for request/response models."""

from datetime import datetime
from typing import Optional, Any, List, Dict
from pydantic import BaseModel, Field


class BusinessCreate(BaseModel):
    """Schema for creating a new business."""
    name: str
    timezone: str = "Europe/London"


class BusinessResponse(BaseModel):
    """Schema for business response (with API key - only on creation)."""
    id: str
    name: str
    timezone: str
    api_key: str


class BusinessListItem(BaseModel):
    """Schema for business in list (without API key)."""
    id: str
    name: str
    timezone: str
    created_at: datetime


class BusinessProfile(BaseModel):
    """Schema for current business profile."""
    id: str
    name: str
    timezone: str
    logo_url: Optional[str] = None


class LogoUploadResponse(BaseModel):
    """Schema for logo upload URL response."""
    upload_url: str
    logo_path: str
    expires_at: datetime


class LogoUpdateRequest(BaseModel):
    """Schema for updating business logo URL."""
    logo_url: Optional[str] = None


class TaskCreate(BaseModel):
    """Schema for creating a new task."""
    title: str
    description: Optional[str] = None
    due_at: Optional[datetime] = None
    recurrence: str = "none"
    source: str = "manual"


class TaskResponse(BaseModel):
    """Schema for task response."""
    id: str
    business_id: str
    title: str
    description: Optional[str]
    due_at: Optional[datetime]
    recurrence: str
    status: str
    source: str
    created_at: datetime
    updated_at: datetime


class SnoozeRequest(BaseModel):
    """Schema for snoozing a task."""
    minutes: Optional[int] = None
    until: Optional[datetime] = None


class CallCreate(BaseModel):
    """Schema for creating a call event (flexible payload)."""
    caller_number: Optional[str] = None
    caller_name: Optional[str] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    transcript: Optional[str] = None
    summary: Optional[str] = None
    intent: Optional[str] = None
    create_follow_up_task: bool = False
    
    class Config:
        extra = "allow"


class CallResponse(BaseModel):
    """Schema for call event response."""
    id: str
    business_id: str
    source: str
    caller_number: Optional[str]
    caller_name: Optional[str]
    started_at: Optional[datetime]
    ended_at: Optional[datetime]
    transcript: Optional[str]
    summary: Optional[str]
    intent: Optional[str]
    created_at: datetime


class BriefingResponse(BaseModel):
    """Schema for daily briefing."""
    tasks_due_today: List[TaskResponse]
    overdue_tasks: List[TaskResponse]
    open_tasks: List[TaskResponse]
    recent_calls: List[CallResponse]
    generated_at: datetime


class HealthResponse(BaseModel):
    """Schema for health check."""
    ok: bool = True


class MessageResponse(BaseModel):
    """Generic message response."""
    message: str


class ChatRequest(BaseModel):
    """Schema for AI assistant chat request."""
    message: str = Field(..., description="User message to the assistant")
    conversation_id: Optional[str] = Field(None, alias="conversationId", description="Optional conversation ID for context")
    business_id: Optional[str] = Field(None, alias="businessId", description="Optional business ID (required if user belongs to multiple businesses)")
    
    class Config:
        populate_by_name = True


class ChatBusinessInfo(BaseModel):
    """Business context included in chat response."""
    id: str = Field(..., description="Business UUID")
    name: str = Field(..., description="Business name")
    timezone: str = Field(..., description="Business timezone")


class ChatResponse(BaseModel):
    """Schema for AI assistant chat response."""
    reply: str = Field(..., description="Assistant's reply")
    business_id: str = Field(..., description="Business ID used for context")
    business: ChatBusinessInfo = Field(..., description="Business context details")
    conversation_id: Optional[str] = Field(None, description="Conversation ID")


class BusinessSettingsResponse(BaseModel):
    """Schema for business settings response."""
    id: str
    business_id: str
    settings: Dict[str, Any]
    created_at: datetime
    updated_at: datetime


class BusinessSettingsUpdate(BaseModel):
    """Schema for updating business settings."""
    settings: Dict[str, Any] = Field(..., description="Settings JSON object")


class IntegrationResponse(BaseModel):
    """Schema for integration response."""
    id: str
    business_id: str
    integration_type: str
    is_enabled: bool
    config: Dict[str, Any]
    created_at: datetime
    updated_at: datetime


class IntegrationListResponse(BaseModel):
    """Schema for list of integrations."""
    integrations: List[IntegrationResponse]


class IntegrationUpdate(BaseModel):
    """Schema for updating an integration."""
    is_enabled: Optional[bool] = None
    config: Optional[Dict[str, Any]] = None