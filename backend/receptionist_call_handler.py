"""
AI Receptionist — Twilio + OpenAI Realtime WebSocket Bridge

Handles inbound phone calls via Twilio Media Streams, bridging audio
bidirectionally between Twilio (caller) and the OpenAI Realtime API (AI).

Endpoints:
  POST /v1/receptionist/incoming-call   — Twilio webhook (returns TwiML)
  WS   /v1/receptionist/media-stream    — bidirectional audio bridge
  GET  /v1/receptionist/health          — system health check
"""

import os
import json
import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from uuid import UUID

import websockets
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import Response
from twilio.twiml.voice_response import VoiceResponse, Connect
from sqlmodel import Session, select
from sqlalchemy import text as sa_text

from db import engine
from models import Task
from receptionist_api import ReceptionistConfig, build_receptionist_system_prompt

logger = logging.getLogger("receptionist_call")

# ---------------------------------------------------------------------------
# Environment — warn on startup if missing, never crash
# ---------------------------------------------------------------------------

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")

# Realtime model is env-var driven so we can roll forward/back without a deploy.
# Default is gpt-realtime-2 (released May 2026) — first voice model with
# GPT-5-class reasoning and reliable accent stability across long sessions.
RECEPTIONIST_REALTIME_MODEL = os.getenv("RECEPTIONIST_REALTIME_MODEL", "gpt-realtime-2")
OPENAI_REALTIME_URL = (
    f"wss://api.openai.com/v1/realtime?model={RECEPTIONIST_REALTIME_MODEL}"
)
OPENAI_AUDIO_FORMAT = "g711_ulaw"

if not OPENAI_API_KEY:
    logger.warning("[Receptionist] OPENAI_API_KEY not set — receptionist calls will fail")
if not TWILIO_ACCOUNT_SID:
    logger.warning("[Receptionist] TWILIO_ACCOUNT_SID not set — receptionist not fully configured")
if not TWILIO_AUTH_TOKEN:
    logger.warning("[Receptionist] TWILIO_AUTH_TOKEN not set — receptionist not fully configured")

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/v1/receptionist", tags=["Receptionist Calls"])


# ---------------------------------------------------------------------------
# Helper: save a call record using raw SQL (Call model lacks migration-only cols)
# ---------------------------------------------------------------------------

def _save_call_record(
    business_id: str,
    caller_number: str,
    caller_name: Optional[str],
    started_at: Optional[datetime],
    ended_at: datetime,
    duration_seconds: Optional[int],
    transcript: Optional[str],
    summary: Optional[str],
    intent: str,
    outcome: str,
    receptionist_config_id: Optional[str],
) -> None:
    with Session(engine) as session:
        session.execute(
            sa_text("""
                INSERT INTO calls (
                    business_id, source, caller_number, caller_name,
                    started_at, ended_at, transcript, summary, intent,
                    archived, duration_seconds, outcome, receptionist_config_id
                ) VALUES (
                    CAST(:business_id AS uuid), :source, :caller_number, :caller_name,
                    :started_at, :ended_at, :transcript, :summary, :intent,
                    :archived, :duration_seconds, :outcome,
                    CAST(:receptionist_config_id AS uuid)
                )
            """),
            {
                "business_id": business_id,
                "source": "receptionist",
                "caller_number": caller_number or "Unknown",
                "caller_name": caller_name,
                "started_at": started_at,
                "ended_at": ended_at,
                "transcript": transcript,
                "summary": summary,
                "intent": intent,
                "archived": False,
                "duration_seconds": duration_seconds,
                "outcome": outcome,
                "receptionist_config_id": receptionist_config_id,
            },
        )
        session.commit()


# ---------------------------------------------------------------------------
# Helper: create a task via SQLModel (Task model has all needed columns)
# ---------------------------------------------------------------------------

def _create_task(
    business_id: str,
    title: str,
    description: str,
    priority: str = "medium",
    category: str = "Phone Call",
) -> None:
    with Session(engine) as session:
        task = Task(
            business_id=UUID(business_id),
            title=title,
            description=description,
            status="open",
            priority=priority,
            category=category,
            source="receptionist",
        )
        session.add(task)
        session.commit()


# ---------------------------------------------------------------------------
# Function-call handler (invoked by the AI during a live call)
# ---------------------------------------------------------------------------

async def handle_receptionist_function_call(
    function_name: str,
    arguments: dict,
    business_id: str,
    caller_number: str,
    config: dict,
) -> dict:
    logger.info(f"[Receptionist Fn] {function_name}: {json.dumps(arguments)[:200]}")

    if function_name == "take_message":
        try:
            urgency = arguments.get("urgency", "normal")
            _create_task(
                business_id=business_id,
                title=f"Phone message from {arguments.get('caller_name', caller_number)}",
                description=(
                    f"Message: {arguments.get('message', 'No message')}\n"
                    f"Caller: {arguments.get('caller_name', 'Unknown')}\n"
                    f"Number: {arguments.get('callback_number', caller_number)}\n"
                    f"Urgency: {urgency}"
                ),
                priority="high" if urgency == "high" else "medium",
                category="Phone Call",
            )
            logger.info(f"[Receptionist Fn] Message saved as task for business {business_id}")
            return {
                "success": True,
                "message": (
                    "Message recorded successfully. Confirm to the caller that their "
                    "message has been taken and someone will get back to them."
                ),
            }
        except Exception as e:
            logger.error(f"[Receptionist Fn] Failed to save message: {e}")
            return {
                "success": False,
                "message": "I had trouble recording that. Please ask the caller to try again or call back.",
            }

    elif function_name == "transfer_call":
        transfer_number = config.get("transfer_number")
        if not transfer_number:
            logger.warning("[Receptionist Fn] Transfer requested but no transfer number configured")
            return {
                "success": False,
                "message": "No transfer number is configured. Apologise and offer to take a message instead.",
            }

        try:
            _create_task(
                business_id=business_id,
                title=f"URGENT: Transfer requested by {caller_number}",
                description=(
                    f"Caller requested to speak with a real person.\n"
                    f"Reason: {arguments.get('reason', 'Not specified')}\n"
                    f"Caller number: {caller_number}\n"
                    f"Please call them back immediately."
                ),
                priority="high",
                category="Phone Call",
            )
            try:
                from services.alert_dispatcher import dispatch_alert
                import asyncio
                asyncio.create_task(dispatch_alert(
                    business_id,
                    "call_transferred",
                    {
                        "caller_name": caller_number,
                        "caller_number": caller_number,
                        "reason": arguments.get("reason", "Caller requested human support"),
                        "time": datetime.utcnow().strftime("%H:%M"),
                        "entity_type": "call",
                        "action_option": {"label": "Call them back now", "type": "show_breakdown", "config": {}},
                    },
                ))
            except Exception:
                pass
            return {
                "success": True,
                "message": (
                    "Tell the caller: 'I've flagged this as urgent and a team member will "
                    "call you back very shortly. Is there anything else I can help with in "
                    "the meantime?'"
                ),
            }
        except Exception as e:
            logger.error(f"[Receptionist Fn] Failed to create transfer task: {e}")
            return {
                "success": False,
                "message": "Apologise for the difficulty and offer to take a detailed message instead.",
            }

    elif function_name == "create_task":
        try:
            _create_task(
                business_id=business_id,
                title=arguments.get("title", "Follow-up from phone call"),
                description=arguments.get("description", f"Created during call with {caller_number}"),
                priority=arguments.get("priority", "medium"),
                category=arguments.get("category", "Phone Call"),
            )
            logger.info(f"[Receptionist Fn] Task created: {arguments.get('title')}")
            return {
                "success": True,
                "message": "Task created. You can mention to the caller that you've noted this for the team.",
            }
        except Exception as e:
            logger.error(f"[Receptionist Fn] Failed to create task: {e}")
            return {
                "success": False,
                "message": "Couldn't create the task, but continue the conversation normally.",
            }

    elif function_name == "end_call":
        logger.info(f"[Receptionist Fn] Call ending — summary: {arguments.get('summary', 'No summary')}")
        return {"success": True, "message": "Say a warm goodbye and end the conversation naturally."}

    elif function_name == "check_availability":
        try:
            from assistant_tools import check_calendar_availability
            from db import get_session_context
            import json as _json

            date_str = arguments.get("date")
            appointment_type = arguments.get("appointment_type", "Consultation")

            with get_session_context() as session:
                from sqlalchemy import text as sql_text
                settings_row = session.execute(
                    sql_text("SELECT * FROM booking_settings WHERE business_id = :bid AND enabled = true"),
                    {"bid": business_id},
                ).fetchone()

            if not settings_row:
                return {
                    "success": False,
                    "message": (
                        "Appointment booking is not currently available. "
                        "Please take the caller's details and someone will get back to them."
                    ),
                }

            appointment_types = (
                settings_row.appointment_types
                if isinstance(settings_row.appointment_types, list)
                else _json.loads(settings_row.appointment_types or "[]")
            )
            duration = 60
            for apt in appointment_types:
                if apt.get("name", "").lower() == appointment_type.lower():
                    duration = apt.get("duration_minutes", 60)
                    break

            import datetime as _dt
            day_name = _dt.datetime.fromisoformat(date_str).strftime("%A").lower()
            business_hours = (
                settings_row.business_hours
                if isinstance(settings_row.business_hours, list)
                else _json.loads(settings_row.business_hours or "[]")
            )
            day_config = next((d for d in business_hours if d.get("day") == day_name), None)

            if not day_config or not day_config.get("enabled"):
                return {
                    "success": True,
                    "message": f"Sorry, we're not available on {day_name.title()}s. Would you like to try another day?",
                }

            start_hour = int(day_config["start"].split(":")[0])
            end_hour = int(day_config["end"].split(":")[0])
            calendar_id = getattr(settings_row, "calendar_id", None) or "primary"

            result = await check_calendar_availability(
                business_id=business_id,
                date=date_str,
                duration_minutes=duration,
                start_hour=start_hour,
                end_hour=end_hour,
                calendar_id=calendar_id,
            )

            if result.get("error"):
                return {
                    "success": False,
                    "message": (
                        "I'm having trouble checking the calendar right now. "
                        "Let me take your details and someone will call you back to arrange a time."
                    ),
                }
            elif result.get("total_available", 0) == 0:
                return {
                    "success": True,
                    "message": f"Unfortunately there are no available slots on {date_str}. Would you like to try another day?",
                }
            else:
                slots = result["available_slots"][:6]
                slot_text = ", ".join([s["start"] for s in slots])
                return {
                    "success": True,
                    "message": f"Available times on {date_str}: {slot_text}. Which time works best for you?",
                }
        except Exception as e:
            logger.error(f"[Receptionist Fn] check_availability failed: {e}")
            return {
                "success": False,
                "message": "I couldn't check the calendar right now. Let me take your details instead.",
            }

    elif function_name == "book_appointment":
        try:
            from assistant_tools import create_calendar_event
            from db import get_session_context
            import json as _json
            from datetime import datetime as _datetime, timedelta as _timedelta

            date_str = arguments.get("date")
            time_str = arguments.get("time")
            caller_name = arguments.get("caller_name", "")
            caller_email = arguments.get("caller_email")
            appointment_type = arguments.get("appointment_type", "Appointment")
            notes = arguments.get("notes", "")

            with get_session_context() as session:
                from sqlalchemy import text as sql_text
                settings_row = session.execute(
                    sql_text("SELECT * FROM booking_settings WHERE business_id = :bid AND enabled = true"),
                    {"bid": business_id},
                ).fetchone()

            duration = 60
            confirmation_msg = "Your appointment has been booked."
            if settings_row:
                appointment_types = (
                    settings_row.appointment_types
                    if isinstance(settings_row.appointment_types, list)
                    else _json.loads(settings_row.appointment_types or "[]")
                )
                for apt in appointment_types:
                    if apt.get("name", "").lower() == appointment_type.lower():
                        duration = apt.get("duration_minutes", 60)
                        break
                confirmation_msg = settings_row.confirmation_message or confirmation_msg

            start_dt = _datetime.fromisoformat(f"{date_str}T{time_str}:00")
            end_dt = start_dt + _timedelta(minutes=duration)

            desc_parts = [f"Booked by AI receptionist.", f"Caller: {caller_name}"]
            if caller_email:
                desc_parts.append(f"Email: {caller_email}")
            if notes:
                desc_parts.append(f"Notes: {notes}")

            calendar_id = getattr(settings_row, "calendar_id", None) or "primary"

            result = await create_calendar_event(
                business_id=business_id,
                title=f"{appointment_type} - {caller_name}",
                start_time=start_dt.isoformat(),
                end_time=end_dt.isoformat(),
                description="\n".join(desc_parts),
                attendee_email=caller_email,
                attendee_name=caller_name,
                calendar_id=calendar_id,
            )

            if result.get("success"):
                logger.info(f"[Receptionist Fn] Appointment booked: {caller_name} on {date_str} at {time_str}")
                return {
                    "success": True,
                    "message": (
                        f"I've booked a {appointment_type} for {caller_name} "
                        f"on {date_str} at {time_str}. {confirmation_msg}"
                    ),
                }
            else:
                return {
                    "success": False,
                    "message": (
                        "I'm having trouble booking that appointment right now. "
                        "Let me take your details and someone will confirm the booking shortly."
                    ),
                }
        except Exception as e:
            logger.error(f"[Receptionist Fn] book_appointment failed: {e}")
            return {
                "success": False,
                "message": "I couldn't complete the booking. Let me take your details and someone will call you back.",
            }

    else:
        logger.warning(f"[Receptionist Fn] Unknown function: {function_name}")
        return {"success": False, "message": f"Unknown function: {function_name}"}


# ---------------------------------------------------------------------------
# POST /v1/receptionist/incoming-call  — Twilio webhook
# ---------------------------------------------------------------------------

@router.post("/incoming-call")
async def receptionist_incoming_call(request: Request):
    """
    Twilio webhook: receives incoming phone calls.
    Looks up the business by the called phone number and returns TwiML that
    opens a bidirectional Media Stream WebSocket.
    """
    form_data = await request.form()
    to_number = form_data.get("To", "").replace(" ", "").strip()
    from_number = form_data.get("From", "").replace(" ", "").strip()
    call_sid = form_data.get("CallSid", "")

    logger.info(f"[Receptionist] Incoming call: {from_number} → {to_number} (CallSid: {call_sid})")

    try:
        with Session(engine) as session:
            cfg = session.exec(
                select(ReceptionistConfig)
                .where(
                    ReceptionistConfig.twilio_phone_number == to_number,
                    ReceptionistConfig.enabled == True,  # noqa: E712
                )
            ).first()
    except Exception as e:
        logger.error(f"[Receptionist] DB lookup failed: {e}")
        vr = VoiceResponse()
        vr.say("We're experiencing technical difficulties. Please try again later.", voice="alice")
        vr.hangup()
        return Response(content=str(vr), media_type="application/xml")

    if not cfg:
        logger.warning(f"[Receptionist] No active receptionist config for number: {to_number}")
        vr = VoiceResponse()
        vr.say(
            "I'm sorry, this number is not currently accepting calls. Please try again later.",
            voice="alice",
        )
        vr.hangup()
        return Response(content=str(vr), media_type="application/xml")

    business_id = str(cfg.business_id)
    logger.info(f"[Receptionist] Matched to business: {business_id}")

    host = request.headers.get("host", "")
    if not host:
        host = str(request.base_url).replace("http://", "").replace("https://", "").rstrip("/")

    ws_url = f"wss://{host}/v1/receptionist/media-stream"
    logger.info(f"[Receptionist] Media stream WebSocket URL: {ws_url}")

    vr = VoiceResponse()
    connect = Connect()
    stream = connect.stream(url=ws_url)
    stream.parameter(name="business_id", value=business_id)
    stream.parameter(name="caller_number", value=from_number)
    stream.parameter(name="call_sid", value=call_sid)
    vr.append(connect)

    logger.info(f"[Receptionist] TwiML response sent for CallSid: {call_sid}")
    return Response(content=str(vr), media_type="application/xml")


# ---------------------------------------------------------------------------
# WS /v1/receptionist/media-stream  — Twilio ↔ OpenAI audio bridge
# ---------------------------------------------------------------------------

@router.websocket("/media-stream")
async def receptionist_media_stream(ws: WebSocket):
    """
    Bidirectional audio bridge: Twilio Media Streams ↔ OpenAI Realtime API.
    """
    await ws.accept()
    logger.info("[Receptionist WS] Twilio connected")

    business_id: Optional[str] = None
    caller_number: Optional[str] = None
    call_sid: Optional[str] = None
    stream_sid: Optional[str] = None
    openai_ws = None
    call_start_time: Optional[datetime] = None
    transcript_parts: List[Dict[str, str]] = []
    caller_name: Optional[str] = None
    call_outcome = "handled"
    tasks_created: List[dict] = []
    messages_taken: List[dict] = []
    receptionist_config_id: Optional[str] = None

    try:
        # ---- PHASE 1: Receive Twilio 'start' event ----
        initial_message = await ws.receive_text()
        data = json.loads(initial_message)

        if data.get("event") == "connected":
            logger.info("[Receptionist WS] Received 'connected' event, waiting for 'start'...")
            start_message = await ws.receive_text()
            data = json.loads(start_message)

        if data.get("event") == "start":
            start_data = data.get("start", {})
            stream_sid = start_data.get("streamSid")
            custom_params = start_data.get("customParameters", {})
            business_id = custom_params.get("business_id")
            caller_number = custom_params.get("caller_number", "Unknown")
            call_sid = custom_params.get("call_sid", "")
            logger.info(
                f"[Receptionist WS] Stream started — business={business_id}, "
                f"caller={caller_number}, callSid={call_sid}, streamSid={stream_sid}"
            )
        else:
            logger.error(f"[Receptionist WS] Expected 'start' event, got: {data.get('event')}")
            await ws.close()
            return

        if not business_id:
            logger.error("[Receptionist WS] No business_id — closing")
            await ws.close()
            return

        call_start_time = datetime.utcnow()

        # ---- PHASE 2: Build system prompt & connect to OpenAI ----
        try:
            with Session(engine) as session:
                prompt_data = await build_receptionist_system_prompt(business_id, session)
                cfg = session.exec(
                    select(ReceptionistConfig).where(
                        ReceptionistConfig.business_id == business_id
                    )
                ).first()
                if cfg:
                    receptionist_config_id = str(cfg.id)
        except Exception as e:
            logger.error(f"[Receptionist WS] Failed to build system prompt: {e}")
            await ws.close()
            return

        system_prompt = prompt_data["system_prompt"]
        voice = prompt_data["voice"]
        greeting = prompt_data["greeting"]
        config_data = prompt_data["config"]
        preset_id = prompt_data.get("voice_preset_id")
        accent_name = prompt_data.get("accent")
        preset_verified = prompt_data.get("preset_verified", True)

        if not preset_verified:
            logger.warning(
                "[Receptionist WS] Using EXPERIMENTAL voice '%s' (preset=%s) — "
                "not yet validated end-to-end on %s. If the call fails to start, "
                "switch to a verified preset (e.g. shimmer_british, echo_british).",
                voice,
                preset_id,
                RECEPTIONIST_REALTIME_MODEL,
            )

        logger.info(
            "[Receptionist WS] System prompt built "
            "(model=%s, preset=%s, voice=%s, accent=%s, %d chars)",
            RECEPTIONIST_REALTIME_MODEL,
            preset_id,
            voice,
            accent_name,
            len(system_prompt),
        )

        if not OPENAI_API_KEY:
            logger.error("[Receptionist WS] OPENAI_API_KEY not set — cannot connect to OpenAI")
            await ws.close()
            return

        openai_headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "OpenAI-Beta": "realtime=v1",
        }

        try:
            openai_ws = await websockets.connect(
                OPENAI_REALTIME_URL,
                additional_headers=openai_headers,
                ping_interval=20,
                ping_timeout=20,
            )
            logger.info("[Receptionist WS] Connected to OpenAI Realtime API")
        except Exception as e:
            logger.error(f"[Receptionist WS] Failed to connect to OpenAI: {e}")
            await ws.close()
            return

        # ---- PHASE 3: Configure the OpenAI session ----
        session_config = {
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "instructions": system_prompt,
                "voice": voice,
                "input_audio_format": OPENAI_AUDIO_FORMAT,
                "output_audio_format": OPENAI_AUDIO_FORMAT,
                "input_audio_transcription": {"model": "whisper-1"},
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.5,
                    "prefix_padding_ms": 300,
                    "silence_duration_ms": 500,
                },
                "tools": [
                    {
                        "type": "function",
                        "name": "take_message",
                        "description": (
                            "Record a message from the caller including their name, phone number, "
                            "and the reason for their call. Use this when the caller wants to leave "
                            "a message or when you need to take their details for a callback."
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "caller_name": {"type": "string", "description": "The caller's name"},
                                "callback_number": {"type": "string", "description": "Phone number to call back on"},
                                "message": {"type": "string", "description": "The message or reason for calling"},
                                "urgency": {
                                    "type": "string",
                                    "enum": ["low", "normal", "high"],
                                    "description": "How urgent the message is",
                                },
                            },
                            "required": ["message"],
                        },
                    },
                    {
                        "type": "function",
                        "name": "transfer_call",
                        "description": (
                            "Transfer the caller to a human team member. Use when the caller "
                            "explicitly asks to speak to a real person, manager, or when the "
                            "query is beyond your knowledge."
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "reason": {"type": "string", "description": "Why the call is being transferred"},
                            },
                            "required": ["reason"],
                        },
                    },
                    {
                        "type": "function",
                        "name": "create_task",
                        "description": (
                            "Create a follow-up task for the business team. Use when something "
                            "needs action after the call ends — e.g., send information, schedule "
                            "callback, follow up on a request."
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string", "description": "Brief task title"},
                                "description": {"type": "string", "description": "Detailed description of what needs doing"},
                                "priority": {
                                    "type": "string",
                                    "enum": ["low", "medium", "high"],
                                    "description": "Task priority",
                                },
                                "category": {
                                    "type": "string",
                                    "enum": ["Phone Call", "Email Follow-up", "Lead to Contact", "Meeting to Book", "General"],
                                    "description": "Task category",
                                },
                            },
                            "required": ["title"],
                        },
                    },
                    {
                        "type": "function",
                        "name": "end_call",
                        "description": (
                            "End the phone call politely. Use this after the caller says goodbye, "
                            "confirms they have no more questions, or asks to hang up."
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "summary": {"type": "string", "description": "Brief summary of the call"},
                            },
                            "required": ["summary"],
                        },
                    },
                    {
                        "type": "function",
                        "name": "check_availability",
                        "description": (
                            "Check available appointment slots on a specific date. Use this when "
                            "a caller asks to book an appointment or wants to know when you're available."
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "date": {
                                    "type": "string",
                                    "description": "The date to check availability for in YYYY-MM-DD format",
                                },
                                "appointment_type": {
                                    "type": "string",
                                    "description": "Type of appointment requested (e.g., Consultation, Quick Call)",
                                },
                            },
                            "required": ["date"],
                        },
                    },
                    {
                        "type": "function",
                        "name": "book_appointment",
                        "description": (
                            "Book an appointment on the calendar. Only use after confirming "
                            "the date, time, and caller's details."
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "date": {
                                    "type": "string",
                                    "description": "Appointment date in YYYY-MM-DD format",
                                },
                                "time": {
                                    "type": "string",
                                    "description": "Appointment start time in HH:MM format (24h)",
                                },
                                "caller_name": {
                                    "type": "string",
                                    "description": "Name of the person booking",
                                },
                                "caller_email": {
                                    "type": "string",
                                    "description": "Email address for calendar invite (optional)",
                                },
                                "appointment_type": {
                                    "type": "string",
                                    "description": "Type of appointment",
                                },
                                "notes": {
                                    "type": "string",
                                    "description": "Any additional notes about the appointment",
                                },
                            },
                            "required": ["date", "time", "caller_name"],
                        },
                    },
                ],
            },
        }

        await openai_ws.send(json.dumps(session_config))
        logger.info("[Receptionist WS] OpenAI session configured")

        # ---- PHASE 4: Trigger the opening greeting ----
        greeting_event = {
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            f"A caller is on the line. Answer the phone with a natural version of "
                            f"this greeting: \"{greeting}\". Keep it warm and natural — don't read "
                            f"it word for word like a script."
                        ),
                    }
                ],
            },
        }
        await openai_ws.send(json.dumps(greeting_event))
        await openai_ws.send(json.dumps({"type": "response.create"}))
        logger.info("[Receptionist WS] Greeting triggered")

        # ---- PHASE 5: Bidirectional audio bridge ----

        async def forward_twilio_to_openai():
            """Read audio from Twilio, forward to OpenAI."""
            try:
                async for message in ws.iter_text():
                    msg = json.loads(message)
                    event_type = msg.get("event")

                    if event_type == "media":
                        audio_event = {
                            "type": "input_audio_buffer.append",
                            "audio": msg["media"]["payload"],
                        }
                        try:
                            await openai_ws.send(json.dumps(audio_event))
                        except Exception:
                            logger.warning("[Receptionist WS] Failed to send audio to OpenAI")
                            break

                    elif event_type == "stop":
                        logger.info("[Receptionist WS] Twilio stream stopped (caller hung up)")
                        break

            except WebSocketDisconnect:
                logger.info("[Receptionist WS] Twilio WebSocket disconnected")
            except Exception as e:
                logger.error(f"[Receptionist WS] Twilio→OpenAI error: {e}")

        async def forward_openai_to_twilio():
            """Read events from OpenAI, forward audio to Twilio, handle function calls."""
            nonlocal caller_name, call_outcome

            try:
                async for message in openai_ws:
                    event = json.loads(message)
                    event_type = event.get("type", "")

                    if event_type == "response.audio.delta":
                        audio_delta = event.get("delta", "")
                        if audio_delta and stream_sid:
                            twilio_msg = {
                                "event": "media",
                                "streamSid": stream_sid,
                                "media": {"payload": audio_delta},
                            }
                            try:
                                await ws.send_json(twilio_msg)
                            except Exception:
                                logger.warning("[Receptionist WS] Failed to send audio to Twilio")
                                break

                    elif event_type == "conversation.item.input_audio_transcription.completed":
                        user_text = event.get("transcript", "").strip()
                        if user_text:
                            transcript_parts.append({"role": "caller", "text": user_text})
                            logger.info(f"[Receptionist WS] Caller said: {user_text[:100]}")

                    elif event_type == "response.audio_transcript.done":
                        ai_text = event.get("transcript", "").strip()
                        if ai_text:
                            transcript_parts.append({"role": "receptionist", "text": ai_text})
                            logger.info(f"[Receptionist WS] AI said: {ai_text[:100]}")

                    elif event_type == "response.function_call_arguments.done":
                        fn_name = event.get("name", "")
                        call_id = event.get("call_id", "")
                        args_str = event.get("arguments", "{}")

                        logger.info(f"[Receptionist WS] Function call: {fn_name}")

                        try:
                            args = json.loads(args_str)
                        except json.JSONDecodeError:
                            args = {}

                        result = await handle_receptionist_function_call(
                            function_name=fn_name,
                            arguments=args,
                            business_id=business_id,
                            caller_number=caller_number,
                            config=config_data,
                        )

                        if fn_name == "take_message":
                            messages_taken.append(args)
                            if args.get("caller_name"):
                                caller_name = args["caller_name"]
                        elif fn_name == "transfer_call":
                            call_outcome = "transferred"
                        elif fn_name == "create_task":
                            tasks_created.append(args)
                        elif fn_name == "book_appointment":
                            call_outcome = "appointment_booked"
                            if args.get("caller_name"):
                                caller_name = args["caller_name"]

                        fn_result_event = {
                            "type": "conversation.item.create",
                            "item": {
                                "type": "function_call_output",
                                "call_id": call_id,
                                "output": json.dumps(result),
                            },
                        }
                        await openai_ws.send(json.dumps(fn_result_event))
                        await openai_ws.send(json.dumps({"type": "response.create"}))

                        if fn_name == "end_call":
                            logger.info("[Receptionist WS] end_call triggered — closing after final response")
                            await asyncio.sleep(5)
                            break

                    elif event_type == "error":
                        error_data = event.get("error", {})
                        logger.error(f"[Receptionist WS] OpenAI error: {error_data}")
                        if error_data.get("type") in ("server_error", "invalid_request_error"):
                            logger.error("[Receptionist WS] Fatal OpenAI error — closing call")
                            call_outcome = "error"
                            break

                    elif event_type == "session.created":
                        logger.info("[Receptionist WS] OpenAI session created")
                    elif event_type == "session.updated":
                        logger.info("[Receptionist WS] OpenAI session updated")

            except websockets.exceptions.ConnectionClosed:
                logger.info("[Receptionist WS] OpenAI WebSocket closed")
            except Exception as e:
                logger.error(f"[Receptionist WS] OpenAI→Twilio error: {e}")

        twilio_task = asyncio.create_task(forward_twilio_to_openai())
        openai_task = asyncio.create_task(forward_openai_to_twilio())

        done, pending = await asyncio.wait(
            [twilio_task, openai_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    except WebSocketDisconnect:
        logger.info("[Receptionist WS] WebSocket disconnected")
    except Exception as e:
        logger.error(f"[Receptionist WS] Unexpected error: {e}")
        call_outcome = "error"
    finally:
        # ---- PHASE 6: Cleanup & persist call record ----
        logger.info("[Receptionist WS] Cleaning up...")

        if openai_ws:
            try:
                await openai_ws.close()
            except Exception:
                pass

        try:
            await ws.close()
        except Exception:
            pass

        call_end_time = datetime.utcnow()
        duration_seconds: Optional[int] = None
        if call_start_time:
            duration_seconds = int((call_end_time - call_start_time).total_seconds())

        transcript_text = ""
        if transcript_parts:
            transcript_text = "\n".join(
                f"{'Caller' if t['role'] == 'caller' else 'Receptionist'}: {t['text']}"
                for t in transcript_parts
            )

        summary_text = ""
        if messages_taken:
            msg = messages_taken[0]
            parts = [p for p in [msg.get("caller_name"), msg.get("message")] if p]
            summary_text = " - ".join(parts)
        elif transcript_parts:
            caller_statements = [t["text"] for t in transcript_parts if t["role"] == "caller"]
            if caller_statements:
                summary_text = caller_statements[0][:200]

        intent = "general enquiry"
        if messages_taken:
            intent = "message"
        if tasks_created:
            categories = [t.get("category", "General") for t in tasks_created]
            intent = categories[0].lower() if categories else "follow-up"
        if call_outcome == "transferred":
            intent = "transfer requested"

        if business_id:
            try:
                _save_call_record(
                    business_id=business_id,
                    caller_number=caller_number or "Unknown",
                    caller_name=caller_name,
                    started_at=call_start_time,
                    ended_at=call_end_time,
                    duration_seconds=duration_seconds,
                    transcript=transcript_text or None,
                    summary=summary_text or None,
                    intent=intent,
                    outcome=call_outcome,
                    receptionist_config_id=receptionist_config_id,
                )
                logger.info(
                    f"[Receptionist WS] Call saved — business={business_id}, "
                    f"duration={duration_seconds}s, outcome={call_outcome}"
                )
            except Exception as e:
                logger.error(f"[Receptionist WS] Failed to save call record: {e}")

        logger.info("[Receptionist WS] Call session ended")


# ---------------------------------------------------------------------------
# GET /v1/receptionist/health  — system health check
# ---------------------------------------------------------------------------

@router.get("/health")
async def receptionist_health():
    """Check receptionist system health."""
    checks: Dict[str, Any] = {
        "openai_api_key": bool(OPENAI_API_KEY),
        "twilio_account_sid": bool(TWILIO_ACCOUNT_SID),
        "twilio_auth_token": bool(TWILIO_AUTH_TOKEN),
    }

    try:
        with Session(engine) as session:
            configs = session.exec(select(ReceptionistConfig)).all()
            checks["configs_total"] = len(configs)
            checks["configs_enabled"] = sum(1 for c in configs if c.enabled)
    except Exception as e:
        checks["db_error"] = str(e)

    checks["all_ok"] = all([
        checks.get("openai_api_key"),
        checks.get("twilio_account_sid"),
        checks.get("twilio_auth_token"),
    ])

    return checks
