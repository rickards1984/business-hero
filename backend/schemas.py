"""Pydantic schemas for request/response models."""

from datetime import datetime, date
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
    archived: bool = False
    created_at: datetime
    updated_at: Optional[datetime] = None


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


class SupportTicketCreateAdmin(BaseModel):
    """Schema for admin-created support ticket."""
    business_id: str
    title: str
    message: str
    severity: Optional[str] = "normal"
    category: Optional[str] = "general"
    page_url: Optional[str] = None
    context: Optional[Dict[str, Any]] = None


class SupportTicketUpdateAdmin(BaseModel):
    """Schema for admin updating support ticket."""
    status: Optional[str] = None
    admin_notes: Optional[str] = None
    severity: Optional[str] = None
    priority: Optional[str] = None


class BillingCheckoutRequest(BaseModel):
    plan_tier: str


class BillingSessionResponse(BaseModel):
    url: str


class BillingPortalResponse(BaseModel):
    url: str


class MessageResponse(BaseModel):
    """Generic message response."""
    message: str


class ChatRequest(BaseModel):
    """Schema for AI assistant chat request."""
    message: str = Field(..., description="User message to the assistant")
    conversation_id: Optional[str] = Field(None, alias="conversationId", description="Optional conversation ID for context")
    business_id: Optional[str] = Field(None, alias="businessId", description="Optional business ID (required if user belongs to multiple businesses)")
    voice_mode: bool = Field(False, alias="voiceMode", description="Whether the user is in voice conversation mode (more concise responses)")
    
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


class Invoice(BaseModel):
    """Schema for invoice response."""
    id: str
    business_id: str
    invoice_number: str
    customer_name: str
    customer_email: Optional[str] = None
    issue_date: Optional[date] = None
    due_date: date
    amount: float
    currency: str
    status: str
    paid_date: Optional[date] = None
    last_chased_at: Optional[datetime] = None
    chase_stage: int
    source: str
    source_ref: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class InvoiceListResponse(BaseModel):
    """Schema for list of invoices."""
    invoices: List[Invoice]
    total: int


class ImportResponse(BaseModel):
    """Schema for CSV import response."""
    imported: int
    updated: int
    errors: List[str] = Field(default_factory=list)


class ChaseDraftResponse(BaseModel):
    """Schema for chase email draft response."""
    subject: str
    body: str
    chase_stage: int
    stage_description: Optional[str] = None


class EmailConnectionPublic(BaseModel):
    """Public email connection settings (no password)."""
    id: str
    business_id: str
    provider: str
    smtp_host: str
    smtp_port: int
    smtp_username: str
    from_email: str
    from_name: Optional[str] = None
    use_tls: bool
    use_ssl: bool
    is_enabled: bool
    created_at: datetime
    updated_at: datetime


class EmailConnectionUpsert(BaseModel):
    """Schema for creating/updating email connection settings."""
    provider: str = "smtp"
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    from_email: str
    from_name: Optional[str] = None
    use_tls: bool = True
    use_ssl: bool = False
    is_enabled: bool = True


class EmailTestResponse(BaseModel):
    """Schema for email test response."""
    success: bool
    message: str
    outbox_id: Optional[str] = None


class SendChaseRequest(BaseModel):
    """Schema for sending chase email."""
    subject: Optional[str] = None
    body: Optional[str] = None
    chase_stage: Optional[int] = None
    dry_run: bool = False


class SendChaseResponse(BaseModel):
    """Schema for chase email send response."""
    invoice_id: str
    subject: str
    body: str
    chase_stage: int
    stage_description: Optional[str] = None
    status: str
    error_message: Optional[str] = None
    outbox_id: Optional[str] = None
    dry_run: bool = False


class BulkSendRequest(BaseModel):
    """Schema for bulk chase email send."""
    invoice_ids: List[str]
    chase_stage: Optional[int] = None
    dry_run: bool = False


class BulkSendResponse(BaseModel):
    """Schema for bulk chase email send response."""
    total: int
    sent: int
    failed: int
    results: List[SendChaseResponse]


class EmailOutboxItem(BaseModel):
    """Schema for email outbox item."""
    id: str
    business_id: str
    invoice_id: Optional[str] = None
    to_email: str
    subject: str
    body: str
    chase_stage: Optional[int] = None
    status: str
    error_message: Optional[str] = None
    sent_at: Optional[datetime] = None
    created_at: datetime


class EmailOutboxListResponse(BaseModel):
    """Schema for list of outbox emails."""
    emails: List[EmailOutboxItem]
    total: int


class EmailMessageItem(BaseModel):
    """Schema for cached email message."""
    id: str
    business_id: str
    email_account_id: str
    provider_message_id: str
    provider_thread_id: Optional[str] = None
    folder: str
    from_email: Optional[str] = None
    from_name: Optional[str] = None
    to_emails: Optional[List[str]] = None
    cc_emails: Optional[List[str]] = None
    subject: Optional[str] = None
    snippet: Optional[str] = None
    received_at: Optional[datetime] = None
    is_unread: bool
    has_attachments: bool
    labels: Optional[List[str]] = None
    created_at: datetime
    updated_at: datetime


class EmailMessageListResponse(BaseModel):
    """Schema for list of cached email messages."""
    messages: List[EmailMessageItem]
    total: int


class EmailSyncRunResponse(BaseModel):
    """Schema for sync run response."""
    email_account_id: str
    synced: bool
    message_count: int
    cursor: Dict[str, Any]


class EmailBriefingRequest(BaseModel):
    """Schema for generating an email briefing."""
    hours: int = Field(default=24, ge=1, le=168)
    email_account_id: Optional[str] = None


class EmailBriefingResponse(BaseModel):
    """Schema for email briefing response."""
    id: str
    business_id: str
    user_id: str
    email_account_id: Optional[str] = None
    period_start: datetime
    period_end: datetime
    briefing_markdown: str
    created_at: datetime


class EmailDraftRequest(BaseModel):
    """Schema for generating an email draft."""
    email_message_id: str
    to_emails: Optional[List[str]] = None


class EmailDraftResponse(BaseModel):
    """Schema for email draft response."""
    id: str
    business_id: str
    email_message_id: str
    to_emails: List[str]
    subject: str
    body_text: Optional[str] = None
    body_html: Optional[str] = None
    status: str
    provider_message_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class EmailDraftSendResponse(BaseModel):
    """Schema for sending a draft."""
    success: bool
    message: str
    outbox_id: Optional[str] = None
    provider_message_id: Optional[str] = None
    status: Optional[str] = None