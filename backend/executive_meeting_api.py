"""
Executive Board Meeting — Settings & Configuration Endpoints

This file handles ONLY settings CRUD and read-only listings of meetings,
action items, and goals. The actual meeting orchestration is in subsequent
prompts.

Tier gating: pro / business / beta have access. starter and paused are
blocked at the API layer via `require_tier_feature`. Advanced features
(custom focus areas, multi-attendee) are gated to business / beta only.
"""
import json
import logging
from datetime import datetime, time, timedelta
from typing import Optional

import pytz
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlmodel import Session

from auth import get_user_business_context, get_platform_admin_context
from db import get_session
from services.tier_gating import (
    check_feature_access,
    get_business_tier,
    require_tier_feature,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/executive-meetings", tags=["executive-meetings"])

# Tiers that get advanced features (multi-attendee, custom focus areas).
# beta has parity with business so testers exercise the full code path.
_ADVANCED_TIERS = {"business", "beta"}
_STANDARD_FOCUS_AREAS = {"financial", "operations", "team", "growth"}


# ============================================================================
# Settings CRUD
# ============================================================================

@router.get("/settings")
async def get_meeting_settings(
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """Return the business's executive meeting settings, or defaults if none saved."""
    business_id = str(auth_ctx["business_id"])
    require_tier_feature(business_id, "executive_board_meeting", session)

    row = session.execute(
        text("""
            SELECT id, business_id, enabled, frequency, day_of_week, day_of_month,
                   meeting_time, timezone, focus_areas, custom_agenda_items,
                   attendees, directness_level, include_disclaimers,
                   last_meeting_at, next_meeting_at, total_meetings_completed,
                   created_at, updated_at
            FROM executive_meeting_settings
            WHERE business_id = :business_id
            LIMIT 1
        """),
        {"business_id": business_id},
    ).fetchone()

    if row:
        return _row_to_settings_dict(row)

    return {
        "business_id": business_id,
        "enabled": False,
        "frequency": "weekly",
        "day_of_week": 1,
        "day_of_month": 1,
        "meeting_time": "09:00",
        "timezone": "Europe/London",
        "focus_areas": ["financial", "operations", "team", "growth"],
        "custom_agenda_items": [],
        "attendees": [],
        "directness_level": "balanced",
        "include_disclaimers": True,
        "is_default": True,
    }


@router.put("/settings")
async def update_meeting_settings(
    settings: dict,
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """Create or update executive meeting settings for the current business.

    Calculates `next_meeting_at` based on the schedule.
    """
    business_id = str(auth_ctx["business_id"])
    tier = require_tier_feature(business_id, "executive_board_meeting", session)

    frequency = settings.get("frequency", "weekly")
    if frequency not in ("weekly", "monthly"):
        raise HTTPException(status_code=400, detail="Frequency must be 'weekly' or 'monthly'")

    if tier not in _ADVANCED_TIERS:
        settings["attendees"] = []
        requested_focus = settings.get("focus_areas") or []
        cleaned = [fa for fa in requested_focus if fa in _STANDARD_FOCUS_AREAS]
        settings["focus_areas"] = cleaned or list(_STANDARD_FOCUS_AREAS)

    next_meeting = _calculate_next_meeting_time(settings)

    params = {
        "business_id": business_id,
        "enabled": bool(settings.get("enabled", False)),
        "frequency": frequency,
        "day_of_week": int(settings.get("day_of_week", 1)),
        "day_of_month": int(settings.get("day_of_month", 1)),
        "meeting_time": settings.get("meeting_time", "09:00"),
        "timezone": settings.get("timezone", "Europe/London"),
        "focus_areas": json.dumps(settings.get("focus_areas") or []),
        "custom_agenda_items": json.dumps(settings.get("custom_agenda_items") or []),
        "attendees": json.dumps(settings.get("attendees") or []),
        "directness_level": settings.get("directness_level", "balanced"),
        "include_disclaimers": bool(settings.get("include_disclaimers", True)),
        "next_meeting_at": next_meeting.isoformat() if next_meeting else None,
    }

    existing = session.execute(
        text("SELECT id FROM executive_meeting_settings WHERE business_id = :business_id"),
        {"business_id": business_id},
    ).fetchone()

    if existing:
        session.execute(
            text("""
                UPDATE executive_meeting_settings SET
                    enabled = :enabled,
                    frequency = :frequency,
                    day_of_week = :day_of_week,
                    day_of_month = :day_of_month,
                    meeting_time = :meeting_time,
                    timezone = :timezone,
                    focus_areas = CAST(:focus_areas AS jsonb),
                    custom_agenda_items = CAST(:custom_agenda_items AS jsonb),
                    attendees = CAST(:attendees AS jsonb),
                    directness_level = :directness_level,
                    include_disclaimers = :include_disclaimers,
                    next_meeting_at = :next_meeting_at,
                    updated_at = NOW()
                WHERE business_id = :business_id
            """),
            params,
        )
    else:
        session.execute(
            text("""
                INSERT INTO executive_meeting_settings (
                    business_id, enabled, frequency, day_of_week, day_of_month,
                    meeting_time, timezone, focus_areas, custom_agenda_items,
                    attendees, directness_level, include_disclaimers,
                    next_meeting_at
                ) VALUES (
                    :business_id, :enabled, :frequency, :day_of_week, :day_of_month,
                    :meeting_time, :timezone,
                    CAST(:focus_areas AS jsonb),
                    CAST(:custom_agenda_items AS jsonb),
                    CAST(:attendees AS jsonb),
                    :directness_level, :include_disclaimers,
                    :next_meeting_at
                )
            """),
            params,
        )

    session.commit()

    row = session.execute(
        text("""
            SELECT id, business_id, enabled, frequency, day_of_week, day_of_month,
                   meeting_time, timezone, focus_areas, custom_agenda_items,
                   attendees, directness_level, include_disclaimers,
                   last_meeting_at, next_meeting_at, total_meetings_completed,
                   created_at, updated_at
            FROM executive_meeting_settings
            WHERE business_id = :business_id
            LIMIT 1
        """),
        {"business_id": business_id},
    ).fetchone()
    return _row_to_settings_dict(row) if row else {"status": "saved"}


@router.get("/access-check")
async def check_meeting_access(
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """Report whether the current business can use the Executive Board Meeting.

    Used by the frontend to show/hide the feature or display upgrade prompts.
    Does NOT raise — returns access info even for blocked tiers.
    """
    business_id = str(auth_ctx["business_id"])
    tier = get_business_tier(business_id, session)

    has_access = check_feature_access(business_id, "executive_board_meeting", session)
    has_advanced = check_feature_access(business_id, "executive_board_meeting_advanced", session)

    return {
        "has_access": has_access,
        "has_advanced": has_advanced,
        "current_tier": tier,
        "required_tier": "pro" if not has_access else None,
        "feature_name": "Executive Board Meeting",
    }


# ============================================================================
# Read-only listing endpoints (placeholders — full impl in Prompt 3)
# ============================================================================

@router.get("/meetings")
async def list_meetings(
    limit: int = 20,
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """List past and upcoming meetings for the current business."""
    business_id = str(auth_ctx["business_id"])
    require_tier_feature(business_id, "executive_board_meeting", session)

    limit = max(1, min(100, int(limit)))
    rows = session.execute(
        text("""
            SELECT id, business_id, status, scheduled_for, prep_started_at,
                   started_at, ended_at, duration_minutes, summary, sentiment,
                   total_tokens_used, created_at, updated_at
            FROM executive_meetings
            WHERE business_id = :business_id
            ORDER BY scheduled_for DESC
            LIMIT :limit
        """),
        {"business_id": business_id, "limit": limit},
    ).fetchall()

    return [_meeting_row_to_dict(r) for r in rows]


@router.get("/action-items")
async def list_action_items(
    status: Optional[str] = None,
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """List action items, optionally filtered by status."""
    business_id = str(auth_ctx["business_id"])
    require_tier_feature(business_id, "executive_board_meeting", session)

    if status:
        rows = session.execute(
            text("""
                SELECT id, meeting_id, business_id, title, description,
                       assignee_name, assignee_email, status, priority,
                       due_date, completed_at, rationale, success_criteria,
                       times_reviewed, last_reviewed_at, notes,
                       created_at, updated_at
                FROM executive_meeting_action_items
                WHERE business_id = :business_id AND status = :status
                ORDER BY created_at DESC
            """),
            {"business_id": business_id, "status": status},
        ).fetchall()
    else:
        rows = session.execute(
            text("""
                SELECT id, meeting_id, business_id, title, description,
                       assignee_name, assignee_email, status, priority,
                       due_date, completed_at, rationale, success_criteria,
                       times_reviewed, last_reviewed_at, notes,
                       created_at, updated_at
                FROM executive_meeting_action_items
                WHERE business_id = :business_id
                ORDER BY created_at DESC
            """),
            {"business_id": business_id},
        ).fetchall()

    return [_action_item_row_to_dict(r) for r in rows]


_ACTION_ITEM_UPDATABLE_FIELDS = {
    "title", "description", "assignee_name", "assignee_email",
    "status", "priority", "due_date", "rationale", "success_criteria",
    "notes",
}


@router.put("/action-items/{item_id}")
async def update_action_item(
    item_id: str,
    updates: dict,
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """Update the status, notes, or assignment of an action item."""
    business_id = str(auth_ctx["business_id"])
    require_tier_feature(business_id, "executive_board_meeting", session)

    update_pairs = {k: v for k, v in updates.items() if k in _ACTION_ITEM_UPDATABLE_FIELDS}

    if updates.get("status") == "completed" and "completed_at" not in update_pairs:
        update_pairs["completed_at"] = datetime.utcnow().isoformat()

    if not update_pairs:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    set_clauses = ", ".join([f"{k} = :{k}" for k in update_pairs.keys()])
    update_pairs["item_id"] = item_id
    update_pairs["business_id"] = business_id

    session.execute(
        text(f"""
            UPDATE executive_meeting_action_items
            SET {set_clauses}, updated_at = NOW()
            WHERE id = :item_id AND business_id = :business_id
        """),
        update_pairs,
    )
    session.commit()
    return {"status": "updated"}


@router.get("/goals")
async def list_goals(
    status: Optional[str] = None,
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """List goals, optionally filtered by status."""
    business_id = str(auth_ctx["business_id"])
    require_tier_feature(business_id, "executive_board_meeting", session)

    if status:
        rows = session.execute(
            text("""
                SELECT id, business_id, set_in_meeting_id, title, description,
                       horizon, category, kpi_name, kpi_target_value,
                       kpi_current_value, kpi_unit, status, target_date,
                       achieved_at, created_at, updated_at
                FROM executive_meeting_goals
                WHERE business_id = :business_id AND status = :status
                ORDER BY created_at DESC
            """),
            {"business_id": business_id, "status": status},
        ).fetchall()
    else:
        rows = session.execute(
            text("""
                SELECT id, business_id, set_in_meeting_id, title, description,
                       horizon, category, kpi_name, kpi_target_value,
                       kpi_current_value, kpi_unit, status, target_date,
                       achieved_at, created_at, updated_at
                FROM executive_meeting_goals
                WHERE business_id = :business_id
                ORDER BY created_at DESC
            """),
            {"business_id": business_id},
        ).fetchall()

    return [_goal_row_to_dict(r) for r in rows]


_GOAL_UPDATABLE_FIELDS = {
    "title", "description", "horizon", "category",
    "kpi_name", "kpi_target_value", "kpi_current_value", "kpi_unit",
    "status", "target_date",
}


@router.put("/goals/{goal_id}")
async def update_goal(
    goal_id: str,
    updates: dict,
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """Update a goal's progress, status, or details."""
    business_id = str(auth_ctx["business_id"])
    require_tier_feature(business_id, "executive_board_meeting", session)

    update_pairs = {k: v for k, v in updates.items() if k in _GOAL_UPDATABLE_FIELDS}

    if updates.get("status") == "achieved" and "achieved_at" not in update_pairs:
        update_pairs["achieved_at"] = datetime.utcnow().isoformat()

    if not update_pairs:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    set_clauses = ", ".join([f"{k} = :{k}" for k in update_pairs.keys()])
    update_pairs["goal_id"] = goal_id
    update_pairs["business_id"] = business_id

    session.execute(
        text(f"""
            UPDATE executive_meeting_goals
            SET {set_clauses}, updated_at = NOW()
            WHERE id = :goal_id AND business_id = :business_id
        """),
        update_pairs,
    )
    session.commit()
    return {"status": "updated"}


# ============================================================================
# Admin endpoints
# ============================================================================

@router.get("/admin/overview")
async def admin_meeting_overview(
    auth_ctx: dict = Depends(get_platform_admin_context),
    session: Session = Depends(get_session),
):
    """List all businesses with their executive meeting status (admin only)."""
    rows = session.execute(
        text("""
            SELECT s.id, s.business_id, b.name AS business_name,
                   b.plan_tier, s.enabled, s.frequency, s.next_meeting_at,
                   s.last_meeting_at, s.total_meetings_completed,
                   s.updated_at
            FROM executive_meeting_settings s
            JOIN businesses b ON b.id = s.business_id
            ORDER BY s.updated_at DESC
        """),
    ).fetchall()

    return [
        {
            "id": str(r[0]) if r[0] else None,
            "business_id": str(r[1]) if r[1] else None,
            "business_name": r[2],
            "plan_tier": r[3],
            "enabled": r[4],
            "frequency": r[5],
            "next_meeting_at": r[6].isoformat() if r[6] else None,
            "last_meeting_at": r[7].isoformat() if r[7] else None,
            "total_meetings_completed": r[8],
            "updated_at": r[9].isoformat() if r[9] else None,
        }
        for r in rows
    ]


# ============================================================================
# Helpers
# ============================================================================

def _row_to_settings_dict(row) -> dict:
    if not row:
        return {}
    return {
        "id": str(row[0]) if row[0] else None,
        "business_id": str(row[1]) if row[1] else None,
        "enabled": row[2],
        "frequency": row[3],
        "day_of_week": row[4],
        "day_of_month": row[5],
        "meeting_time": row[6].isoformat() if hasattr(row[6], "isoformat") else row[6],
        "timezone": row[7],
        "focus_areas": _coerce_json_list(row[8]),
        "custom_agenda_items": _coerce_json_list(row[9]),
        "attendees": _coerce_json_list(row[10]),
        "directness_level": row[11],
        "include_disclaimers": row[12],
        "last_meeting_at": row[13].isoformat() if row[13] else None,
        "next_meeting_at": row[14].isoformat() if row[14] else None,
        "total_meetings_completed": row[15],
        "created_at": row[16].isoformat() if row[16] else None,
        "updated_at": row[17].isoformat() if row[17] else None,
    }


def _coerce_json_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


def _meeting_row_to_dict(r) -> dict:
    return {
        "id": str(r[0]) if r[0] else None,
        "business_id": str(r[1]) if r[1] else None,
        "status": r[2],
        "scheduled_for": r[3].isoformat() if r[3] else None,
        "prep_started_at": r[4].isoformat() if r[4] else None,
        "started_at": r[5].isoformat() if r[5] else None,
        "ended_at": r[6].isoformat() if r[6] else None,
        "duration_minutes": r[7],
        "summary": r[8],
        "sentiment": r[9],
        "total_tokens_used": r[10],
        "created_at": r[11].isoformat() if r[11] else None,
        "updated_at": r[12].isoformat() if r[12] else None,
    }


def _action_item_row_to_dict(r) -> dict:
    return {
        "id": str(r[0]) if r[0] else None,
        "meeting_id": str(r[1]) if r[1] else None,
        "business_id": str(r[2]) if r[2] else None,
        "title": r[3],
        "description": r[4],
        "assignee_name": r[5],
        "assignee_email": r[6],
        "status": r[7],
        "priority": r[8],
        "due_date": r[9].isoformat() if r[9] else None,
        "completed_at": r[10].isoformat() if r[10] else None,
        "rationale": r[11],
        "success_criteria": r[12],
        "times_reviewed": r[13],
        "last_reviewed_at": r[14].isoformat() if r[14] else None,
        "notes": r[15],
        "created_at": r[16].isoformat() if r[16] else None,
        "updated_at": r[17].isoformat() if r[17] else None,
    }


def _goal_row_to_dict(r) -> dict:
    def num(v):
        return float(v) if v is not None else None
    return {
        "id": str(r[0]) if r[0] else None,
        "business_id": str(r[1]) if r[1] else None,
        "set_in_meeting_id": str(r[2]) if r[2] else None,
        "title": r[3],
        "description": r[4],
        "horizon": r[5],
        "category": r[6],
        "kpi_name": r[7],
        "kpi_target_value": num(r[8]),
        "kpi_current_value": num(r[9]),
        "kpi_unit": r[10],
        "status": r[11],
        "target_date": r[12].isoformat() if r[12] else None,
        "achieved_at": r[13].isoformat() if r[13] else None,
        "created_at": r[14].isoformat() if r[14] else None,
        "updated_at": r[15].isoformat() if r[15] else None,
    }


def _calculate_next_meeting_time(settings: dict) -> Optional[datetime]:
    """Compute the next meeting datetime from schedule settings.

    Returns None if disabled or schedule invalid.
    """
    if not settings.get("enabled", False):
        return None

    try:
        tz = pytz.timezone(settings.get("timezone") or "Europe/London")
    except Exception:
        tz = pytz.timezone("Europe/London")

    now = datetime.now(tz)

    time_str = settings.get("meeting_time") or "09:00"
    try:
        parts = str(time_str).split(":")
        hour, minute = int(parts[0]), int(parts[1])
        meeting_time = time(hour, minute)
    except Exception:
        meeting_time = time(9, 0)

    frequency = settings.get("frequency", "weekly")

    if frequency == "weekly":
        # SQL day_of_week: 0=Sun, 1=Mon ... 6=Sat
        # Python weekday():  0=Mon, 1=Tue ... 6=Sun
        target_dow = int(settings.get("day_of_week", 1))
        target_weekday = (target_dow - 1) % 7 if target_dow > 0 else 6

        days_ahead = (target_weekday - now.weekday()) % 7
        if days_ahead == 0:
            today_meeting = tz.localize(datetime.combine(now.date(), meeting_time))
            if today_meeting > now:
                return today_meeting
            days_ahead = 7

        next_date = now.date() + timedelta(days=days_ahead)
        return tz.localize(datetime.combine(next_date, meeting_time))

    if frequency == "monthly":
        target_day = max(1, min(28, int(settings.get("day_of_month", 1))))

        try:
            this_month = now.replace(
                day=target_day,
                hour=meeting_time.hour,
                minute=meeting_time.minute,
                second=0,
                microsecond=0,
            )
            if this_month > now:
                return this_month
        except Exception:
            pass

        if now.month == 12:
            return now.replace(
                year=now.year + 1,
                month=1,
                day=target_day,
                hour=meeting_time.hour,
                minute=meeting_time.minute,
                second=0,
                microsecond=0,
            )
        return now.replace(
            month=now.month + 1,
            day=target_day,
            hour=meeting_time.hour,
            minute=meeting_time.minute,
            second=0,
            microsecond=0,
        )

    return None


# ============================================================================
# Prompt 2 — Prep service endpoints
#
# Append-only: these endpoints integrate the prep orchestrator. Nothing above
# this line is modified.
# ============================================================================

@router.post("/prep-now")
async def trigger_prep_now(
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """
    Run the prep service for the current business right now and return the
    PrepData JSON. Does NOT persist a meeting record — for testing/preview.

    Tier-gated: pro/business/beta.
    """
    business_id = str(auth_ctx["business_id"])
    require_tier_feature(business_id, "executive_board_meeting", session)

    from services.executive_meeting_prep import generate_prep_data

    prep = generate_prep_data(business_id=business_id, db_session=session)
    return prep


@router.post("/start-now")
async def start_meeting_now(
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """
    Create an ad-hoc executive meeting record (scheduled_for=NOW), run prep,
    and store the prep_data on the row. Returns {meeting_id, status}.

    Prompt 3 will pick this row up and start the actual conversation.
    """
    business_id = str(auth_ctx["business_id"])
    require_tier_feature(business_id, "executive_board_meeting", session)

    from services.executive_meeting_prep import generate_prep_data

    now = datetime.utcnow()

    # Insert the meeting row in 'scheduled' state first
    inserted = session.execute(
        text(
            """
            INSERT INTO executive_meetings
                (business_id, status, scheduled_for, prep_started_at)
            VALUES (:business_id, 'scheduled', :scheduled_for, NOW())
            RETURNING id
            """
        ),
        {"business_id": business_id, "scheduled_for": now.isoformat()},
    ).fetchone()
    if not inserted:
        raise HTTPException(status_code=500, detail="Failed to create meeting record")
    meeting_id = str(inserted[0])
    session.commit()

    # Run prep on the same business with scheduled_for=now
    prep = generate_prep_data(
        business_id=business_id,
        db_session=session,
        scheduled_for=now,
    )

    # Persist prep_data and flip status
    session.execute(
        text(
            """
            UPDATE executive_meetings
            SET prep_data = CAST(:prep_data AS jsonb),
                status = 'prep_ready',
                ai_model = :ai_model,
                updated_at = NOW()
            WHERE id = :meeting_id
            """
        ),
        {
            "meeting_id": meeting_id,
            "prep_data": json.dumps(prep, default=str),
            "ai_model": prep.get("ai_model"),
        },
    )
    session.commit()

    return {
        "meeting_id": meeting_id,
        "status": "prep_ready",
        "scheduled_for": now.isoformat() + "Z",
        "completeness_score": (prep.get("data_quality") or {}).get("completeness_score"),
    }


@router.get("/{meeting_id}/prep-data")
async def get_meeting_prep_data(
    meeting_id: str,
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    """Fetch the prep_data JSONB for a specific meeting (own-business only)."""
    business_id = str(auth_ctx["business_id"])
    require_tier_feature(business_id, "executive_board_meeting", session)

    row = session.execute(
        text(
            """
            SELECT id, business_id, status, scheduled_for, prep_data,
                   ai_model, prep_started_at
            FROM executive_meetings
            WHERE id = :meeting_id AND business_id = :business_id
            LIMIT 1
            """
        ),
        {"meeting_id": meeting_id, "business_id": business_id},
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Meeting not found")

    prep_raw = row[4]
    if isinstance(prep_raw, str):
        try:
            prep_raw = json.loads(prep_raw)
        except Exception:
            prep_raw = None

    return {
        "meeting_id": str(row[0]),
        "business_id": str(row[1]),
        "status": row[2],
        "scheduled_for": row[3].isoformat() if row[3] else None,
        "prep_started_at": row[6].isoformat() if row[6] else None,
        "ai_model": row[5],
        "prep_data": prep_raw,
    }
