"""
AI Receptionist — Backend API
Handles config, knowledge base, voice options, call history, stats, and admin operations.
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from uuid import UUID

import pytz
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlmodel import Session, SQLModel, Field as SQLField, select
from sqlalchemy import Column, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB

from db import get_session
from models import Business, Call
from auth import (
    get_user_business_context,
    get_platform_admin_context,
    is_platform_admin_user,
)
from dependencies import get_current_user_business

_logger = logging.getLogger("receptionist")

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
    _logger.warning("Twilio credentials not configured — receptionist phone features will be unavailable")

# ---------------------------------------------------------------------------
# SQLModel table models for new tables
# ---------------------------------------------------------------------------

def _generate_uuid():
    import uuid
    return uuid.uuid4()


class ReceptionistConfig(SQLModel, table=True):
    __tablename__ = "receptionist_configs"

    id: UUID = SQLField(
        default_factory=_generate_uuid,
        sa_column=Column(PG_UUID(as_uuid=True), primary_key=True, default=_generate_uuid),
    )
    business_id: UUID = SQLField(index=True, unique=True)
    enabled: bool = SQLField(default=False)
    twilio_phone_number: Optional[str] = None
    twilio_phone_sid: Optional[str] = None
    voice: str = SQLField(default="shimmer")
    language: str = SQLField(default="en-GB")
    personality_prompt: Optional[str] = None
    greeting_message: str = SQLField(
        default="Hello, thank you for calling. How can I help you today?"
    )
    tone: str = SQLField(default="professional")
    humor_enabled: bool = SQLField(default=False)
    speaking_speed: str = SQLField(default="normal")
    business_hours: Dict[str, Any] = SQLField(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )
    timezone: str = SQLField(default="Europe/London")
    after_hours_message: Optional[str] = None
    after_hours_action: str = SQLField(default="message")
    transfer_enabled: bool = SQLField(default=True)
    transfer_number: Optional[str] = None
    transfer_trigger_phrases: Optional[str] = None
    max_call_duration_seconds: int = SQLField(default=300)
    created_at: datetime = SQLField(default_factory=datetime.utcnow)
    updated_at: datetime = SQLField(default_factory=datetime.utcnow)


class KnowledgeBaseItem(SQLModel, table=True):
    __tablename__ = "knowledge_base_items"

    id: UUID = SQLField(
        default_factory=_generate_uuid,
        sa_column=Column(PG_UUID(as_uuid=True), primary_key=True, default=_generate_uuid),
    )
    business_id: UUID = SQLField(index=True)
    category: str = SQLField(default="general")
    title: str
    content: str
    is_active: bool = SQLField(default=True)
    sort_order: int = SQLField(default=0)
    created_at: datetime = SQLField(default_factory=datetime.utcnow)
    updated_at: datetime = SQLField(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Pydantic request / response schemas
# ---------------------------------------------------------------------------

class ReceptionistConfigCreateUpdate(BaseModel):
    enabled: Optional[bool] = None
    voice: Optional[str] = None
    language: Optional[str] = None
    personality_prompt: Optional[str] = None
    greeting_message: Optional[str] = None
    tone: Optional[str] = None
    humor_enabled: Optional[bool] = None
    speaking_speed: Optional[str] = None
    business_hours: Optional[Dict[str, Any]] = None
    timezone: Optional[str] = None
    after_hours_message: Optional[str] = None
    after_hours_action: Optional[str] = None
    transfer_enabled: Optional[bool] = None
    transfer_number: Optional[str] = None
    transfer_trigger_phrases: Optional[str] = None
    max_call_duration_seconds: Optional[int] = None


class KnowledgeBaseItemCreate(BaseModel):
    category: str = "general"
    title: str
    content: str
    is_active: bool = True
    sort_order: int = 0


class KnowledgeBaseItemUpdate(BaseModel):
    category: Optional[str] = None
    title: Optional[str] = None
    content: Optional[str] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


# ---------------------------------------------------------------------------
# Static data
# ---------------------------------------------------------------------------

AVAILABLE_VOICES = [
    {"id": "shimmer", "name": "Shimmer", "description": "Warm and clear, great for professional businesses", "gender": "female", "accent": "American"},
    {"id": "alloy", "name": "Alloy", "description": "Balanced and versatile, works well for most use cases", "gender": "neutral", "accent": "American"},
    {"id": "echo", "name": "Echo", "description": "Smooth and calm, ideal for healthcare or wellness", "gender": "male", "accent": "American"},
    {"id": "fable", "name": "Fable", "description": "Expressive and engaging, great for creative businesses", "gender": "neutral", "accent": "British"},
    {"id": "onyx", "name": "Onyx", "description": "Deep and authoritative, perfect for legal or finance", "gender": "male", "accent": "American"},
    {"id": "nova", "name": "Nova", "description": "Friendly and upbeat, excellent for retail and hospitality", "gender": "female", "accent": "American"},
    {"id": "cedar", "name": "Cedar", "description": "Natural and warm, OpenAI's latest premium voice", "gender": "male", "accent": "American"},
    {"id": "marin", "name": "Marin", "description": "Bright and personable, OpenAI's latest premium voice", "gender": "female", "accent": "American"},
]

KNOWLEDGE_BASE_CATEGORIES = [
    {"id": "services", "label": "Services", "description": "What your business offers", "icon": "Briefcase"},
    {"id": "pricing", "label": "Pricing", "description": "Costs, plans, membership fees", "icon": "PoundSterling"},
    {"id": "hours", "label": "Opening Hours", "description": "When you're open, holiday closures", "icon": "Clock"},
    {"id": "policies", "label": "Policies", "description": "Cancellation, refund, booking policies", "icon": "Shield"},
    {"id": "faq", "label": "FAQs", "description": "Commonly asked questions", "icon": "HelpCircle"},
    {"id": "team", "label": "Team", "description": "Staff names, roles, specialities", "icon": "Users"},
    {"id": "location", "label": "Location", "description": "Address, parking, directions, facilities", "icon": "MapPin"},
    {"id": "general", "label": "General", "description": "Any other business information", "icon": "Info"},
]

DEFAULT_BUSINESS_HOURS: Dict[str, Any] = {
    "monday": {"open": "09:00", "close": "17:00", "enabled": True},
    "tuesday": {"open": "09:00", "close": "17:00", "enabled": True},
    "wednesday": {"open": "09:00", "close": "17:00", "enabled": True},
    "thursday": {"open": "09:00", "close": "17:00", "enabled": True},
    "friday": {"open": "09:00", "close": "17:00", "enabled": True},
    "saturday": {"open": "10:00", "close": "14:00", "enabled": False},
    "sunday": {"open": "00:00", "close": "00:00", "enabled": False},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_receptionist_flag(business: Business):
    flags = business.feature_flags or {}
    if not flags.get("receptionist", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Receptionist feature is not enabled for this business",
        )


def _require_platform_admin(auth_ctx: dict, session: Session):
    if not is_platform_admin_user(auth_ctx["user_id"], session):
        raise HTTPException(status_code=403, detail="Insufficient permissions")


def _config_to_dict(cfg: ReceptionistConfig) -> dict:
    return {
        "id": str(cfg.id),
        "business_id": str(cfg.business_id),
        "enabled": cfg.enabled,
        "twilio_phone_number": cfg.twilio_phone_number,
        "voice": cfg.voice,
        "language": cfg.language,
        "personality_prompt": cfg.personality_prompt,
        "greeting_message": cfg.greeting_message,
        "tone": cfg.tone,
        "humor_enabled": cfg.humor_enabled,
        "speaking_speed": cfg.speaking_speed,
        "business_hours": cfg.business_hours or DEFAULT_BUSINESS_HOURS,
        "timezone": cfg.timezone,
        "after_hours_message": cfg.after_hours_message,
        "after_hours_action": cfg.after_hours_action,
        "transfer_enabled": cfg.transfer_enabled,
        "transfer_number": cfg.transfer_number,
        "transfer_trigger_phrases": cfg.transfer_trigger_phrases,
        "max_call_duration_seconds": cfg.max_call_duration_seconds,
        "created_at": cfg.created_at.isoformat() if cfg.created_at else None,
        "updated_at": cfg.updated_at.isoformat() if cfg.updated_at else None,
    }


def _kb_item_to_dict(item: KnowledgeBaseItem) -> dict:
    return {
        "id": str(item.id),
        "business_id": str(item.business_id),
        "category": item.category,
        "title": item.title,
        "content": item.content,
        "is_active": item.is_active,
        "sort_order": item.sort_order,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def _default_config_response(business_id: str) -> dict:
    return {
        "id": None,
        "business_id": business_id,
        "enabled": False,
        "twilio_phone_number": None,
        "voice": "shimmer",
        "language": "en-GB",
        "personality_prompt": None,
        "greeting_message": "Hello, thank you for calling. How can I help you today?",
        "tone": "professional",
        "humor_enabled": False,
        "speaking_speed": "normal",
        "business_hours": DEFAULT_BUSINESS_HOURS,
        "timezone": "Europe/London",
        "after_hours_message": "I'm sorry, we are currently closed. Please call back during business hours.",
        "after_hours_action": "message",
        "transfer_enabled": True,
        "transfer_number": None,
        "transfer_trigger_phrases": None,
        "max_call_duration_seconds": 300,
        "created_at": None,
        "updated_at": None,
    }


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/v1/receptionist", tags=["receptionist"])


# ======================== Config endpoints ========================

@router.get("/config")
async def get_receptionist_config(
    business: Business = Depends(get_current_user_business),
    session: Session = Depends(get_session),
):
    """Get receptionist config for the current business."""
    _require_receptionist_flag(business)
    bid = business.id

    cfg = session.exec(
        select(ReceptionistConfig).where(ReceptionistConfig.business_id == bid)
    ).first()

    if cfg:
        return _config_to_dict(cfg)
    return _default_config_response(str(bid))


@router.put("/config")
async def upsert_receptionist_config(
    data: ReceptionistConfigCreateUpdate,
    business: Business = Depends(get_current_user_business),
    session: Session = Depends(get_session),
):
    """Create or update receptionist config for the current business."""
    _require_receptionist_flag(business)
    bid = business.id

    cfg = session.exec(
        select(ReceptionistConfig).where(ReceptionistConfig.business_id == bid)
    ).first()

    update_fields = data.model_dump(exclude_unset=True)

    if cfg:
        for field, value in update_fields.items():
            setattr(cfg, field, value)
        cfg.updated_at = datetime.utcnow()
    else:
        cfg = ReceptionistConfig(business_id=bid, **update_fields)

    session.add(cfg)
    session.commit()
    session.refresh(cfg)
    return _config_to_dict(cfg)


@router.patch("/config/toggle")
async def toggle_receptionist(
    business: Business = Depends(get_current_user_business),
    session: Session = Depends(get_session),
):
    """Toggle the receptionist on/off."""
    _require_receptionist_flag(business)
    bid = business.id

    cfg = session.exec(
        select(ReceptionistConfig).where(ReceptionistConfig.business_id == bid)
    ).first()

    if not cfg:
        raise HTTPException(status_code=404, detail="Receptionist not configured yet. Please set up your receptionist first.")

    if not cfg.enabled and not cfg.twilio_phone_number:
        raise HTTPException(status_code=400, detail="Cannot enable receptionist without a phone number assigned. Please contact support.")

    cfg.enabled = not cfg.enabled
    cfg.updated_at = datetime.utcnow()
    session.add(cfg)
    session.commit()
    return {"enabled": cfg.enabled}


# ======================== Knowledge base endpoints ========================

@router.get("/knowledge-base/categories")
async def list_knowledge_base_categories():
    """Return available knowledge base categories."""
    return KNOWLEDGE_BASE_CATEGORIES


@router.get("/knowledge-base")
async def list_knowledge_base(
    category: Optional[str] = None,
    business: Business = Depends(get_current_user_business),
    session: Session = Depends(get_session),
):
    """List knowledge base items for the current business."""
    _require_receptionist_flag(business)

    stmt = (
        select(KnowledgeBaseItem)
        .where(KnowledgeBaseItem.business_id == business.id)
        .order_by(KnowledgeBaseItem.sort_order, KnowledgeBaseItem.created_at)
    )
    if category:
        stmt = stmt.where(KnowledgeBaseItem.category == category)

    items = session.exec(stmt).all()
    return [_kb_item_to_dict(i) for i in items]


@router.post("/knowledge-base", status_code=201)
async def create_knowledge_base_item(
    item: KnowledgeBaseItemCreate,
    business: Business = Depends(get_current_user_business),
    session: Session = Depends(get_session),
):
    """Add a knowledge base item."""
    _require_receptionist_flag(business)

    kb = KnowledgeBaseItem(business_id=business.id, **item.model_dump())
    session.add(kb)
    session.commit()
    session.refresh(kb)
    return _kb_item_to_dict(kb)


@router.put("/knowledge-base/{item_id}")
async def update_knowledge_base_item(
    item_id: str,
    item: KnowledgeBaseItemUpdate,
    business: Business = Depends(get_current_user_business),
    session: Session = Depends(get_session),
):
    """Update a knowledge base item."""
    _require_receptionist_flag(business)

    kb = session.exec(
        select(KnowledgeBaseItem)
        .where(KnowledgeBaseItem.id == item_id, KnowledgeBaseItem.business_id == business.id)
    ).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base item not found")

    for field, value in item.model_dump(exclude_unset=True).items():
        setattr(kb, field, value)
    kb.updated_at = datetime.utcnow()

    session.add(kb)
    session.commit()
    session.refresh(kb)
    return _kb_item_to_dict(kb)


@router.delete("/knowledge-base/{item_id}")
async def delete_knowledge_base_item(
    item_id: str,
    business: Business = Depends(get_current_user_business),
    session: Session = Depends(get_session),
):
    """Delete a knowledge base item."""
    _require_receptionist_flag(business)

    kb = session.exec(
        select(KnowledgeBaseItem)
        .where(KnowledgeBaseItem.id == item_id, KnowledgeBaseItem.business_id == business.id)
    ).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base item not found")

    session.delete(kb)
    session.commit()
    return {"status": "deleted"}


# ======================== Voices endpoint ========================

@router.get("/voices")
async def list_voices():
    """Return available voice options for the AI receptionist."""
    return AVAILABLE_VOICES


# ======================== Call history & stats ========================

@router.get("/calls")
async def list_receptionist_calls(
    period: Optional[str] = "all",
    outcome: Optional[str] = None,
    limit: int = Query(50, le=100),
    offset: int = 0,
    business: Business = Depends(get_current_user_business),
    session: Session = Depends(get_session),
):
    """List calls handled by the AI receptionist."""
    _require_receptionist_flag(business)

    stmt = (
        select(Call)
        .where(
            Call.business_id == business.id,
            Call.source == "receptionist",
            Call.archived == False,
        )
        .order_by(Call.created_at.desc())
    )

    if period == "today":
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        stmt = stmt.where(Call.created_at >= today)
    elif period == "week":
        stmt = stmt.where(Call.created_at >= datetime.utcnow() - timedelta(days=7))
    elif period == "month":
        stmt = stmt.where(Call.created_at >= datetime.utcnow() - timedelta(days=30))

    if outcome:
        stmt = stmt.where(Call.outcome == outcome)

    stmt = stmt.offset(offset).limit(limit)
    calls = session.exec(stmt).all()

    return [
        {
            "id": str(c.id),
            "business_id": str(c.business_id),
            "caller_number": c.caller_number,
            "caller_name": c.caller_name,
            "started_at": c.started_at.isoformat() if c.started_at else None,
            "ended_at": c.ended_at.isoformat() if c.ended_at else None,
            "duration_seconds": getattr(c, "duration_seconds", None),
            "transcript": c.transcript,
            "summary": c.summary,
            "intent": c.intent,
            "outcome": getattr(c, "outcome", None),
            "recording_url": getattr(c, "recording_url", None),
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in calls
    ]


@router.get("/stats")
async def receptionist_stats(
    business: Business = Depends(get_current_user_business),
    session: Session = Depends(get_session),
):
    """Get receptionist call statistics for dashboard cards."""
    _require_receptionist_flag(business)

    calls = session.exec(
        select(Call).where(Call.business_id == business.id, Call.source == "receptionist")
    ).all()

    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today - timedelta(days=today.weekday())

    durations = [getattr(c, "duration_seconds", None) for c in calls if getattr(c, "duration_seconds", None)]
    avg_dur = sum(durations) / len(durations) if durations else 0

    return {
        "total_receptionist_calls": len(calls),
        "today_calls": sum(1 for c in calls if c.created_at and c.created_at >= today),
        "this_week_calls": sum(1 for c in calls if c.created_at and c.created_at >= week_start),
        "handled_calls": sum(1 for c in calls if getattr(c, "outcome", None) == "handled"),
        "transferred_calls": sum(1 for c in calls if getattr(c, "outcome", None) == "transferred"),
        "voicemail_calls": sum(1 for c in calls if getattr(c, "outcome", None) == "voicemail"),
        "missed_calls": sum(1 for c in calls if getattr(c, "outcome", None) == "missed"),
        "avg_duration_seconds": round(avg_dur, 1),
    }


# ======================== Admin endpoints ========================

admin_router = APIRouter(prefix="/v1/admin/receptionist", tags=["admin-receptionist"])


@admin_router.get("/overview")
async def admin_receptionist_overview(
    auth_ctx=Depends(get_platform_admin_context),
    session: Session = Depends(get_session),
):
    """Admin: Get receptionist status for all businesses."""
    _require_platform_admin(auth_ctx, session)

    businesses = session.exec(select(Business)).all()
    configs = session.exec(select(ReceptionistConfig)).all()
    config_map = {str(c.business_id): c for c in configs}

    result = []
    for biz in businesses:
        cfg = config_map.get(str(biz.id))
        flags = biz.feature_flags or {}
        result.append({
            "business_id": str(biz.id),
            "business_name": biz.name,
            "plan_tier": biz.plan_tier,
            "is_active": biz.is_active,
            "receptionist_enabled": flags.get("receptionist", False),
            "receptionist_live": cfg.enabled if cfg else False,
            "twilio_phone_number": cfg.twilio_phone_number if cfg else None,
            "voice": cfg.voice if cfg else None,
            "last_updated": cfg.updated_at.isoformat() if cfg and cfg.updated_at else None,
        })
    return result


@admin_router.put("/{business_id}/feature-flag")
async def admin_toggle_receptionist_flag(
    business_id: str,
    enabled: bool = True,
    auth_ctx=Depends(get_platform_admin_context),
    session: Session = Depends(get_session),
):
    """Admin: Enable/disable receptionist feature for a business."""
    _require_platform_admin(auth_ctx, session)

    biz = session.exec(select(Business).where(Business.id == business_id)).first()
    if not biz:
        raise HTTPException(status_code=404, detail="Business not found")

    flags = dict(biz.feature_flags or {})
    flags["receptionist"] = enabled
    biz.feature_flags = flags

    session.add(biz)
    session.commit()
    return {"business_id": business_id, "receptionist_enabled": enabled}


@admin_router.put("/{business_id}/config")
async def admin_update_receptionist_config(
    business_id: str,
    data: ReceptionistConfigCreateUpdate,
    auth_ctx=Depends(get_platform_admin_context),
    session: Session = Depends(get_session),
):
    """Admin: Create or update receptionist config for any business."""
    _require_platform_admin(auth_ctx, session)

    cfg = session.exec(
        select(ReceptionistConfig).where(ReceptionistConfig.business_id == business_id)
    ).first()

    update_fields = data.model_dump(exclude_unset=True)

    if cfg:
        for field, value in update_fields.items():
            setattr(cfg, field, value)
        cfg.updated_at = datetime.utcnow()
    else:
        cfg = ReceptionistConfig(business_id=business_id, **update_fields)

    session.add(cfg)
    session.commit()
    session.refresh(cfg)
    return _config_to_dict(cfg)


@admin_router.put("/{business_id}/phone-number")
async def admin_assign_phone_number(
    business_id: str,
    phone_number: str = Query(...),
    phone_sid: Optional[str] = Query(None),
    auth_ctx=Depends(get_platform_admin_context),
    session: Session = Depends(get_session),
):
    """Admin: Assign a Twilio phone number to a business's receptionist."""
    _require_platform_admin(auth_ctx, session)

    cfg = session.exec(
        select(ReceptionistConfig).where(ReceptionistConfig.business_id == business_id)
    ).first()

    if cfg:
        cfg.twilio_phone_number = phone_number
        cfg.twilio_phone_sid = phone_sid
        cfg.updated_at = datetime.utcnow()
    else:
        cfg = ReceptionistConfig(
            business_id=business_id,
            twilio_phone_number=phone_number,
            twilio_phone_sid=phone_sid,
        )

    session.add(cfg)
    session.commit()
    return {"business_id": business_id, "twilio_phone_number": phone_number}


@admin_router.get("/{business_id}/knowledge-base")
async def admin_list_knowledge_base(
    business_id: str,
    auth_ctx=Depends(get_platform_admin_context),
    session: Session = Depends(get_session),
):
    """Admin: List knowledge base items for any business."""
    _require_platform_admin(auth_ctx, session)

    items = session.exec(
        select(KnowledgeBaseItem)
        .where(KnowledgeBaseItem.business_id == business_id)
        .order_by(KnowledgeBaseItem.sort_order, KnowledgeBaseItem.created_at)
    ).all()
    return [_kb_item_to_dict(i) for i in items]


@admin_router.post("/{business_id}/knowledge-base", status_code=201)
async def admin_create_knowledge_base_item(
    business_id: str,
    item: KnowledgeBaseItemCreate,
    auth_ctx=Depends(get_platform_admin_context),
    session: Session = Depends(get_session),
):
    """Admin: Add a knowledge base item to any business."""
    _require_platform_admin(auth_ctx, session)

    kb = KnowledgeBaseItem(business_id=business_id, **item.model_dump())
    session.add(kb)
    session.commit()
    session.refresh(kb)
    return _kb_item_to_dict(kb)


# ---------------------------------------------------------------------------
# Internal helper — build the system prompt for the AI receptionist
# ---------------------------------------------------------------------------

async def build_receptionist_system_prompt(business_id: str, session: Session) -> dict:
    """
    Assemble the full system prompt from config + knowledge base.

    Returns dict with keys: system_prompt, voice, greeting, config.
    """
    cfg = session.exec(
        select(ReceptionistConfig).where(ReceptionistConfig.business_id == business_id)
    ).first()
    if not cfg:
        raise ValueError(f"No receptionist config for business {business_id}")

    biz = session.exec(select(Business).where(Business.id == business_id)).first()
    business_name = biz.name if biz else "the business"

    kb_items = session.exec(
        select(KnowledgeBaseItem)
        .where(KnowledgeBaseItem.business_id == business_id, KnowledgeBaseItem.is_active == True)
        .order_by(KnowledgeBaseItem.sort_order)
    ).all()

    # Build knowledge base text
    kb_text = ""
    if kb_items:
        categories: Dict[str, list] = {}
        for item in kb_items:
            categories.setdefault(item.category, []).append(f"- {item.title}: {item.content}")
        sections = [f"\n## {cat.replace('_', ' ').title()}\n" + "\n".join(entries) for cat, entries in categories.items()]
        kb_text = "\n\n--- BUSINESS KNOWLEDGE BASE ---" + "\n".join(sections)

    tone_map = {
        "professional": "Maintain a professional, polished tone. Be courteous and efficient.",
        "friendly": "Be warm, friendly, and approachable. Use a conversational style while staying helpful.",
        "casual": "Keep it relaxed and casual. Be personable and natural, like chatting with a friend.",
    }
    speed_map = {
        "slow": "Speak at a measured, deliberate pace. Take your time with explanations.",
        "normal": "Speak at a natural, conversational pace.",
        "fast": "Be concise and efficient. Get to the point quickly while staying polite.",
    }

    tone_inst = tone_map.get(cfg.tone, tone_map["professional"])
    speed_inst = speed_map.get(cfg.speaking_speed, speed_map["normal"])
    humor_inst = (
        "Feel free to use appropriate light humour to build rapport, but always stay professional and helpful."
        if cfg.humor_enabled
        else "Stay focused and professional. Avoid jokes or humour."
    )

    tz = pytz.timezone(cfg.timezone or "Europe/London")
    now = datetime.now(tz)
    day_name = now.strftime("%A").lower()
    hours = cfg.business_hours or DEFAULT_BUSINESS_HOURS
    today_hours = hours.get(day_name, {})
    hours_ctx = (
        f"The business is open today ({now.strftime('%A')}) from {today_hours['open']} to {today_hours['close']}."
        if today_hours.get("enabled")
        else f"The business is closed today ({now.strftime('%A')})."
    )

    transfer_inst = ""
    if cfg.transfer_enabled and cfg.transfer_number:
        phrases = cfg.transfer_trigger_phrases or "speak to a person,talk to someone,real human,manager"
        transfer_inst = f"""
CALL TRANSFER RULES:
- If the caller asks to speak to a real person, a human, a manager, or uses phrases like "{phrases}", transfer the call.
- Before transferring, say: "Of course, let me put you through to someone who can help. One moment please."
- Use the transfer_call function to transfer.
"""

    personality_block = (
        f"\nADDITIONAL PERSONALITY INSTRUCTIONS FROM THE BUSINESS OWNER:\n{cfg.personality_prompt}"
        if cfg.personality_prompt
        else ""
    )

    system_prompt = f"""You are the AI receptionist for {business_name}. You are answering a phone call.

CORE IDENTITY:
- You represent {business_name} and should speak as a member of the team, using "we" and "our" when referring to the business.
- You are warm, helpful, and knowledgeable about the business.
- {tone_inst}
- {speed_inst}
- {humor_inst}
{personality_block}

CURRENT CONTEXT:
- Current time: {now.strftime('%H:%M on %A, %d %B %Y')}
- {hours_ctx}
- Timezone: {cfg.timezone or 'Europe/London'}

CONVERSATION RULES:
- Keep responses concise and natural. This is a phone call, not an essay.
- NEVER say you are an AI unless directly asked. If asked, be honest: "I'm the AI assistant for {business_name}."
- Listen carefully and address the caller's needs efficiently.
- If you don't know something that isn't in your knowledge base, say: "I don't have that information to hand, but I can take your details and have someone get back to you."
- Always offer to help with anything else before ending the call.
- NEVER make up information. Only share facts from your knowledge base.
- If the caller provides their name, use it naturally in conversation.

{transfer_inst}

CAPABILITIES:
- Answer questions about the business using the knowledge base below.
- Take messages from callers (capture their name, number, and reason for calling).
- Provide business hours and location information.
- Help with general enquiries.

{kb_text}

END OF INSTRUCTIONS. Begin the conversation by answering the phone with your greeting."""

    return {
        "system_prompt": system_prompt.strip(),
        "voice": cfg.voice or "shimmer",
        "greeting": cfg.greeting_message or "Hello, thank you for calling. How can I help you today?",
        "config": _config_to_dict(cfg),
    }
