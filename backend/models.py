"""SQLModel database models for AI Admin Assistant."""

import uuid as uuid_module
from datetime import datetime, date
from typing import Optional, Dict, Any, List
from uuid import UUID
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Column, UniqueConstraint, Date, Numeric, Text, JSON
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB, ARRAY
import secrets


def generate_api_key() -> str:
    """Generate a secure, non-guessable API key."""
    return f"sk_{secrets.token_urlsafe(32)}"


def generate_uuid() -> UUID:
    """Generate a UUID."""
    return uuid_module.uuid4()


class Business(SQLModel, table=True):
    """Business entity - represents a tenant."""
    __tablename__ = "businesses"
    
    id: UUID = Field(
        default_factory=generate_uuid,
        sa_column=Column(PG_UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    )
    name: str = Field(index=True)
    timezone: str = Field(default="Europe/London")
    api_key: str = Field(default_factory=generate_api_key, unique=True, index=True)
    logo_url: Optional[str] = None
    plan_tier: str = Field(default="starter")
    is_active: bool = Field(default=True)
    trial_ends_at: Optional[datetime] = None
    feature_flags: Dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default='{}')
    )
    limits: Dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default='{}')
    )
    stripe_customer_id: Optional[str] = None
    stripe_subscription_id: Optional[str] = None
    subscription_status: Optional[str] = None
    current_period_end: Optional[datetime] = None
    cancel_at_period_end: bool = Field(default=False)
    last_stripe_event_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    tasks: list["Task"] = Relationship(back_populates="business")
    calls: list["Call"] = Relationship(back_populates="business")


class Task(SQLModel, table=True):
    """Task entity - belongs to a business."""
    __tablename__ = "tasks"
    
    id: UUID = Field(
        default_factory=generate_uuid,
        sa_column=Column(PG_UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    )
    business_id: UUID = Field(foreign_key="businesses.id", index=True)
    title: str
    description: Optional[str] = None
    due_at: Optional[datetime] = None
    recurrence: str = Field(default="none")
    status: str = Field(default="open", index=True)
    source: str = Field(default="manual")
    deleted_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    business: Optional[Business] = Relationship(back_populates="tasks")


class Call(SQLModel, table=True):
    """Call entity - represents a phone call record."""
    __tablename__ = "calls"
    
    id: UUID = Field(
        default_factory=generate_uuid,
        sa_column=Column(PG_UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    )
    business_id: UUID = Field(foreign_key="businesses.id", index=True)
    source: str = Field(default="Awaz")
    caller_number: Optional[str] = None
    caller_name: Optional[str] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    transcript: Optional[str] = None
    summary: Optional[str] = None
    intent: Optional[str] = None
    archived: bool = Field(default=False, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None
    
    business: Optional[Business] = Relationship(back_populates="calls")


# Alias for backward compatibility
CallEvent = Call


class BusinessSettings(SQLModel, table=True):
    """Business settings - 1 row per business."""
    __tablename__ = "business_settings"
    
    id: UUID = Field(
        default_factory=generate_uuid,
        sa_column=Column(PG_UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    )
    business_id: UUID = Field(foreign_key="businesses.id", index=True, unique=True)
    settings: Dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default='{}')
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    business: Optional[Business] = Relationship()


class Integration(SQLModel, table=True):
    """Integration configuration - 1 row per business per integration type."""
    __tablename__ = "integrations"
    __table_args__ = (
        UniqueConstraint('business_id', 'integration_type', name='uq_integration_business_type'),
    )
    
    id: UUID = Field(
        default_factory=generate_uuid,
        sa_column=Column(PG_UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    )
    business_id: UUID = Field(foreign_key="businesses.id", index=True)
    integration_type: str = Field(index=True, max_length=100)
    is_enabled: bool = Field(default=False)
    config: Dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default='{}')
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    business: Optional[Business] = Relationship()


class SupportTicket(SQLModel, table=True):
    """Support ticket - customer feedback/support workflow."""
    __tablename__ = "support_tickets"

    id: UUID = Field(
        default_factory=generate_uuid,
        sa_column=Column(PG_UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    )
    business_id: UUID = Field(foreign_key="businesses.id", index=True)
    user_id: UUID = Field(foreign_key="auth.users.id", index=True)
    title: str
    category: str = Field(default="general")
    severity: str = Field(default="normal")
    status: str = Field(default="open")
    message: str
    page_url: Optional[str] = None
    context: Dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default='{}')
    )
    admin_notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class StripeEvent(SQLModel, table=True):
    """Stripe webhook event audit."""
    __tablename__ = "stripe_events"

    id: UUID = Field(
        default_factory=generate_uuid,
        sa_column=Column(PG_UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    )
    business_id: Optional[UUID] = Field(default=None, foreign_key="businesses.id", index=True)
    event_id: str = Field(index=True)
    type: str
    payload: Dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default='{}')
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)

class OAuthToken(SQLModel, table=True):
    """OAuth token storage - encrypted tokens, backend-only access."""
    __tablename__ = "oauth_tokens"
    __table_args__ = (
        UniqueConstraint('business_id', 'integration_type', name='uq_oauth_token_business_type'),
    )
    
    id: UUID = Field(
        default_factory=generate_uuid,
        sa_column=Column(PG_UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    )
    business_id: UUID = Field(foreign_key="businesses.id", index=True)
    integration_type: str = Field(index=True, max_length=100)
    encrypted_access_token: str
    encrypted_refresh_token: Optional[str] = None
    expires_at: Optional[datetime] = None
    token_type: str = Field(default="Bearer", max_length=50)
    scope: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    business: Optional[Business] = Relationship()


class Invoice(SQLModel, table=True):
    """Invoice entity - for invoice chasing functionality."""
    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint('business_id', 'invoice_number', name='uq_invoice_business_number'),
    )
    
    id: UUID = Field(
        default_factory=generate_uuid,
        sa_column=Column(PG_UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    )
    business_id: UUID = Field(foreign_key="businesses.id", index=True)
    invoice_number: str = Field(index=True)
    customer_name: str
    customer_email: Optional[str] = None
    issue_date: Optional[date] = Field(default=None, sa_column=Column(Date))
    due_date: date = Field(sa_column=Column(Date))
    amount: float = Field(sa_column=Column(Numeric(12, 2)))
    currency: str = Field(default="GBP")
    status: str = Field(default="unpaid", index=True)
    paid_date: Optional[date] = Field(default=None, sa_column=Column(Date))
    last_chased_at: Optional[datetime] = None
    chase_stage: int = Field(default=0)
    source: str = Field(default="csv")
    source_ref: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    business: Optional[Business] = Relationship()


class EmailConnection(SQLModel, table=True):
    """Email connection configuration for SMTP sending."""
    __tablename__ = "email_connections"
    __table_args__ = (
        UniqueConstraint('business_id', name='uq_email_connection_business'),
    )

    id: UUID = Field(
        default_factory=generate_uuid,
        sa_column=Column(PG_UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    )
    business_id: UUID = Field(foreign_key="businesses.id", index=True)
    provider: str = Field(default="smtp")
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password_encrypted: str
    from_email: str
    from_name: Optional[str] = None
    use_tls: bool = Field(default=True)
    use_ssl: bool = Field(default=False)
    is_enabled: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    business: Optional[Business] = Relationship()


class EmailAccount(SQLModel, table=True):
    """Email account for OAuth-connected email (Google/Microsoft) or SMTP."""
    __tablename__ = "email_accounts"
    id: UUID = Field(default_factory=generate_uuid, sa_column=Column(PG_UUID(as_uuid=True), primary_key=True, default=generate_uuid))
    business_id: UUID = Field(foreign_key="businesses.id", index=True)
    user_id: UUID = Field(index=True)
    provider: str = Field(index=True)  # 'google', 'microsoft', 'smtp'
    email_address: str
    display_name: Optional[str] = None
    capabilities: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    is_default: bool = Field(default=False)
    token_ciphertext: Optional[str] = None  # encrypted access token
    refresh_token_ciphertext: Optional[str] = None  # encrypted refresh token
    token_expires_at: Optional[datetime] = None
    smtp_config: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    business: Optional[Business] = Relationship()


class EmailOutbox(SQLModel, table=True):
    """Email outbox for queued/sent/failed email records."""
    __tablename__ = "email_outbox"

    id: UUID = Field(
        default_factory=generate_uuid,
        sa_column=Column(PG_UUID(as_uuid=True), primary_key=True, default=generate_uuid)
    )
    business_id: UUID = Field(foreign_key="businesses.id", index=True)
    email_account_id: UUID = Field(foreign_key="email_accounts.id", index=True)
    invoice_id: Optional[UUID] = Field(default=None, foreign_key="invoices.id", index=True)
    chase_stage: Optional[int] = None
    to_emails: List[str] = Field(sa_column=Column(ARRAY(Text), nullable=False))
    subject: str
    body_preview: str
    provider_message_id: Optional[str] = None
    status: str = Field(default="queued", index=True)
    error: Optional[str] = None
    sent_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    business: Optional[Business] = Relationship()
    email_account: Optional[EmailAccount] = Relationship()
    invoice: Optional[Invoice] = Relationship()


class EmailMessage(SQLModel, table=True):
    """Synced email message from provider."""
    __tablename__ = "email_messages"
    id: UUID = Field(default_factory=generate_uuid, sa_column=Column(PG_UUID(as_uuid=True), primary_key=True, default=generate_uuid))
    business_id: UUID = Field(foreign_key="businesses.id", index=True)
    email_account_id: UUID = Field(foreign_key="email_accounts.id", index=True)
    provider_message_id: str = Field(index=True)
    provider_thread_id: Optional[str] = None
    folder: Optional[str] = None
    from_email: Optional[str] = None
    from_name: Optional[str] = None
    to_emails: List[str] = Field(default=[], sa_column=Column(ARRAY(Text), nullable=False, server_default="{}"))
    cc_emails: List[str] = Field(default=[], sa_column=Column(ARRAY(Text), nullable=False, server_default="{}"))
    subject: Optional[str] = None
    snippet: Optional[str] = None
    body_text: Optional[str] = None
    body_html: Optional[str] = None
    received_at: Optional[datetime] = None
    is_unread: bool = Field(default=True)
    has_attachments: bool = Field(default=False)
    labels: List[str] = Field(default=[], sa_column=Column(ARRAY(Text), nullable=False, server_default="{}"))
    raw_headers: Dict[str, Any] = Field(default={}, sa_column=Column(JSONB, nullable=False, server_default="{}"))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    business: Optional[Business] = Relationship()


class EmailSyncState(SQLModel, table=True):
    """Tracks sync cursor/state for each email account."""
    __tablename__ = "email_sync_states"
    id: UUID = Field(default_factory=generate_uuid, sa_column=Column(PG_UUID(as_uuid=True), primary_key=True, default=generate_uuid))
    email_account_id: UUID = Field(foreign_key="email_accounts.id", unique=True, index=True)
    cursor: Dict[str, Any] = Field(default={}, sa_column=Column(JSONB, nullable=False, server_default="{}"))
    last_synced_at: Optional[datetime] = None
    last_error: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class EmailBriefing(SQLModel, table=True):
    """AI-generated email briefing/summary."""
    __tablename__ = "email_briefings"
    id: UUID = Field(default_factory=generate_uuid, sa_column=Column(PG_UUID(as_uuid=True), primary_key=True, default=generate_uuid))
    business_id: UUID = Field(foreign_key="businesses.id", index=True)
    email_account_id: UUID = Field(foreign_key="email_accounts.id", index=True)
    summary: str
    highlights: List[str] = Field(default=[], sa_column=Column(ARRAY(Text), nullable=False, server_default="{}"))
    action_items: List[str] = Field(default=[], sa_column=Column(ARRAY(Text), nullable=False, server_default="{}"))
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    business: Optional[Business] = Relationship()


class EmailDraft(SQLModel, table=True):
    """AI-generated email draft."""
    __tablename__ = "email_drafts"
    id: UUID = Field(default_factory=generate_uuid, sa_column=Column(PG_UUID(as_uuid=True), primary_key=True, default=generate_uuid))
    business_id: UUID = Field(foreign_key="businesses.id", index=True)
    email_account_id: UUID = Field(foreign_key="email_accounts.id", index=True)
    in_reply_to_message_id: Optional[UUID] = Field(default=None, foreign_key="email_messages.id")
    to_emails: List[str] = Field(default=[], sa_column=Column(ARRAY(Text), nullable=False, server_default="{}"))
    cc_emails: List[str] = Field(default=[], sa_column=Column(ARRAY(Text), nullable=False, server_default="{}"))
    subject: str
    body_text: str
    body_html: Optional[str] = None
    status: str = Field(default="draft", index=True)
    sent_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    business: Optional[Business] = Relationship()