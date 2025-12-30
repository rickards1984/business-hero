"""SQLModel database models for AI Admin Assistant."""

import uuid as uuid_module
from datetime import datetime
from typing import Optional
from uuid import UUID
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
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
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    business: Optional[Business] = Relationship(back_populates="calls")


# Alias for backward compatibility
CallEvent = Call
