"""Booking settings API for AI receptionist calendar integration."""
import json
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlmodel import Session
from db import get_session, engine
from auth import get_user_business_context

logger = logging.getLogger("booking_api")
router = APIRouter(prefix="/v1/booking", tags=["Booking"])

DEFAULT_BUSINESS_HOURS = [
    {"day": "monday", "start": "09:00", "end": "17:00", "enabled": True},
    {"day": "tuesday", "start": "09:00", "end": "17:00", "enabled": True},
    {"day": "wednesday", "start": "09:00", "end": "17:00", "enabled": True},
    {"day": "thursday", "start": "09:00", "end": "17:00", "enabled": True},
    {"day": "friday", "start": "09:00", "end": "17:00", "enabled": True},
    {"day": "saturday", "start": "10:00", "end": "14:00", "enabled": False},
    {"day": "sunday", "start": "00:00", "end": "00:00", "enabled": False},
]

DEFAULT_APPOINTMENT_TYPES = [
    {"name": "Consultation", "duration_minutes": 60, "description": "General consultation"},
    {"name": "Quick Call", "duration_minutes": 30, "description": "Brief phone call"},
]


@router.get("/calendars")
async def list_google_calendars(
    auth_ctx: dict = Depends(get_user_business_context),
):
    """List available Google Calendars for the authenticated user."""
    import httpx
    from assistant_tools import _get_google_calendar_token, _refresh_google_token

    business_id = str(auth_ctx["business_id"])
    access_token, account_id, refresh_ciphertext = _get_google_calendar_token(engine, business_id)

    if not access_token:
        raise HTTPException(
            status_code=400,
            detail="Google Calendar not connected. Please connect Google in Email settings first.",
        )

    async def _fetch(token: str):
        async with httpx.AsyncClient(timeout=30) as client:
            return await client.get(
                "https://www.googleapis.com/calendar/v3/users/me/calendarList",
                headers={"Authorization": f"Bearer {token}"},
                params={"minAccessRole": "writer"},
            )

    resp = await _fetch(access_token)

    if resp.status_code == 401 and refresh_ciphertext:
        try:
            access_token = _refresh_google_token(engine, account_id, refresh_ciphertext)
            resp = await _fetch(access_token)
        except Exception:
            raise HTTPException(status_code=401, detail="Calendar token expired — please reconnect Google")

    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Failed to fetch calendars: {resp.status_code}")

    calendars = []
    for cal in resp.json().get("items", []):
        calendars.append({
            "id": cal.get("id"),
            "name": cal.get("summary", "Unnamed Calendar"),
            "description": cal.get("description", ""),
            "primary": cal.get("primary", False),
            "background_color": cal.get("backgroundColor"),
        })

    return {"calendars": calendars}


@router.get("/settings")
async def get_booking_settings(
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    business_id = str(auth_ctx["business_id"])
    row = session.execute(
        text("SELECT * FROM booking_settings WHERE business_id = :bid"),
        {"bid": business_id},
    ).fetchone()

    if not row:
        return {
            "enabled": False,
            "calendar_id": "primary",
            "business_hours": DEFAULT_BUSINESS_HOURS,
            "appointment_types": DEFAULT_APPOINTMENT_TYPES,
            "buffer_minutes": 15,
            "max_advance_days": 30,
            "min_notice_hours": 2,
            "confirmation_message": "Your appointment has been booked. You will receive a calendar invite shortly.",
        }

    return {
        "enabled": row.enabled,
        "calendar_id": getattr(row, "calendar_id", "primary") or "primary",
        "business_hours": row.business_hours if isinstance(row.business_hours, list) else json.loads(row.business_hours or "[]"),
        "appointment_types": row.appointment_types if isinstance(row.appointment_types, list) else json.loads(row.appointment_types or "[]"),
        "buffer_minutes": row.buffer_minutes,
        "max_advance_days": row.max_advance_days,
        "min_notice_hours": row.min_notice_hours,
        "confirmation_message": row.confirmation_message,
    }


@router.put("/settings")
async def update_booking_settings(
    settings: dict,
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    business_id = str(auth_ctx["business_id"])

    existing = session.execute(
        text("SELECT id FROM booking_settings WHERE business_id = :bid"),
        {"bid": business_id},
    ).fetchone()

    business_hours = json.dumps(settings.get("business_hours", DEFAULT_BUSINESS_HOURS))
    appointment_types = json.dumps(settings.get("appointment_types", DEFAULT_APPOINTMENT_TYPES))

    params = {
        "bid": business_id,
        "enabled": settings.get("enabled", False),
        "calendar_id": settings.get("calendar_id", "primary"),
        "business_hours": business_hours,
        "appointment_types": appointment_types,
        "buffer_minutes": settings.get("buffer_minutes", 15),
        "max_advance_days": settings.get("max_advance_days", 30),
        "min_notice_hours": settings.get("min_notice_hours", 2),
        "confirmation_message": settings.get("confirmation_message", ""),
    }

    if existing:
        session.execute(
            text("""
                UPDATE booking_settings SET
                    enabled = :enabled,
                    calendar_id = :calendar_id,
                    business_hours = CAST(:business_hours AS jsonb),
                    appointment_types = CAST(:appointment_types AS jsonb),
                    buffer_minutes = :buffer_minutes,
                    max_advance_days = :max_advance_days,
                    min_notice_hours = :min_notice_hours,
                    confirmation_message = :confirmation_message,
                    updated_at = now()
                WHERE business_id = :bid
            """),
            params,
        )
    else:
        session.execute(
            text("""
                INSERT INTO booking_settings
                (business_id, enabled, calendar_id, business_hours, appointment_types,
                 buffer_minutes, max_advance_days, min_notice_hours, confirmation_message)
                VALUES (:bid, :enabled, :calendar_id, CAST(:business_hours AS jsonb), CAST(:appointment_types AS jsonb),
                        :buffer_minutes, :max_advance_days, :min_notice_hours, :confirmation_message)
            """),
            params,
        )

    session.commit()
    return {"status": "saved"}
