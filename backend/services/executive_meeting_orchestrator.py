"""
Executive Board Meeting — Conversation Orchestrator (Prompt 3 of 4).

Public surface:
- start_meeting(meeting_id, session)         — generate opening Aria turn
- handle_turn(meeting_id, owner_text, session) — owner -> Aria response
- end_meeting(meeting_id, session)           — extract + summarise + close

Token caps (heuristic via len/4, consistent with Prompt 2's estimator):
- SOFT_CAP_TOKENS = 50_000 — append wrap-up hint to GPT context, log warning
- HARD_CAP_TOKENS = 100_000 — refuse new turns; owner must call /end

Resilience: the orchestrator NEVER raises. Worst case is a graceful Aria
fallback message and a logged error. A meeting must never get stuck.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI
from sqlalchemy import text
from sqlmodel import Session

from services.executive_meeting_prompts import (
    messages_for_extraction,
    messages_for_opening,
    messages_for_summary,
    messages_for_turn,
)
from services.executive_meeting_scheduling import compute_next_meeting_time

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
EXECUTIVE_MEETING_AI_MODEL = os.getenv("EXECUTIVE_MEETING_AI_MODEL", "gpt-5")

# Token budgets. tiktoken isn't a project dependency, so we estimate using
# the same len/4 heuristic Prompt 2 uses for its prep-data warning.
SOFT_CAP_TOKENS = 50_000
HARD_CAP_TOKENS = 100_000

# Per-turn generation cap. Keeps Aria's responses tight (the system prompt
# already instructs 2–5 short paragraphs).
MAX_OUTPUT_TOKENS = 1200
MAX_OPENING_TOKENS = 1500
MAX_SUMMARY_TOKENS = 800
MAX_EXTRACTION_TOKENS = 4000

ARIA_ERROR_FALLBACK = (
    "Apologies — I'm having trouble accessing the data right now. "
    "Could you try sending that again in a moment?"
)


# ============================================================================
# Public API
# ============================================================================

async def start_meeting(meeting_id: str, session: Session) -> Dict[str, Any]:
    """
    Generate the opening Aria turn for a meeting that's in 'prep_ready' state.

    Returns: {"opening_message": str, "tokens_used": int, "agenda_section": "opening"}
    Raises ValueError if meeting not in 'prep_ready' state or prep_data missing.
    """
    meeting = _load_meeting(meeting_id, session)
    if not meeting:
        raise ValueError(f"Meeting {meeting_id} not found")
    if meeting["status"] != "prep_ready":
        raise ValueError(
            f"Cannot start meeting in status '{meeting['status']}'. "
            f"Expected 'prep_ready'."
        )
    prep_data = meeting.get("prep_data") or {}
    if not prep_data:
        raise ValueError(f"Meeting {meeting_id} has no prep_data")

    settings = _load_settings(meeting["business_id"], session) or {}

    # Transition state first so concurrent retries don't double-fire openings
    _update_meeting(
        meeting_id,
        session,
        {"status": "in_progress", "started_at": datetime.now(timezone.utc).isoformat()},
    )

    msgs = messages_for_opening(prep_data, settings)
    content, tokens = await _gpt_chat_completion(
        messages=msgs,
        temperature=0.4,
        max_tokens=MAX_OPENING_TOKENS,
    )

    if not content:
        content = (
            "Welcome to today's executive board meeting. I had trouble drafting "
            "the opening, but we can begin: how would you like to start — with "
            "the financial review or any specific item on your mind?"
        )

    _save_message(
        meeting_id=meeting_id,
        business_id=meeting["business_id"],
        role="aria",
        content=content,
        tokens_used=tokens,
        agenda_section="opening",
        session=session,
    )
    _increment_total_tokens(meeting_id, tokens, session)
    session.commit()

    return {
        "opening_message": content,
        "tokens_used": tokens,
        "agenda_section": "opening",
    }


async def handle_turn(
    meeting_id: str,
    owner_message: str,
    session: Session,
) -> Dict[str, Any]:
    """
    Handle one conversation turn: persist owner message, call GPT, persist
    Aria's response. Returns the Aria response payload.

    Refuses to process if cumulative tokens exceed HARD_CAP_TOKENS.
    """
    meeting = _load_meeting(meeting_id, session)
    if not meeting:
        raise ValueError(f"Meeting {meeting_id} not found")
    if meeting["status"] != "in_progress":
        raise ValueError(
            f"Cannot send messages to meeting in status '{meeting['status']}'. "
            f"Expected 'in_progress'."
        )

    total_tokens = int(meeting.get("total_tokens_used") or 0)
    if total_tokens >= HARD_CAP_TOKENS:
        raise ValueError(
            "Token budget exhausted for this meeting. Please end the meeting "
            "to capture commitments and start a new one if needed."
        )
    soft_capped = total_tokens >= SOFT_CAP_TOKENS

    if not owner_message or not owner_message.strip():
        raise ValueError("Owner message cannot be empty")

    business_id = meeting["business_id"]
    prep_data = meeting.get("prep_data") or {}
    settings = _load_settings(business_id, session) or {}

    # 1. Persist owner message FIRST so the history is preserved even if GPT fails
    _save_message(
        meeting_id=meeting_id,
        business_id=business_id,
        role="owner",
        content=owner_message.strip(),
        tokens_used=0,
        session=session,
    )
    session.commit()

    # 2. Load fresh history (now includes the new owner message)
    history = _load_message_history(meeting_id, session)

    # 3. Build GPT messages and call
    msgs = messages_for_turn(
        prep_data=prep_data,
        settings=settings,
        history=history,
        inject_wrap_up_hint=soft_capped,
    )

    content, tokens = await _gpt_chat_completion(
        messages=msgs,
        temperature=0.4,
        max_tokens=MAX_OUTPUT_TOKENS,
    )

    if not content:
        content = ARIA_ERROR_FALLBACK

    _save_message(
        meeting_id=meeting_id,
        business_id=business_id,
        role="aria",
        content=content,
        tokens_used=tokens,
        session=session,
    )
    _increment_total_tokens(meeting_id, tokens, session)
    session.commit()

    return {
        "role": "aria",
        "content": content,
        "tokens_used": tokens,
        "soft_cap_warning": soft_capped,
    }


async def end_meeting(meeting_id: str, session: Session) -> Dict[str, Any]:
    """
    Close a meeting: run extraction + summary, persist commitments,
    update meeting record, recalculate next_meeting_at.

    NEVER raises (except ValueError for invalid state). Extraction and
    summary failures are logged but do not block the close.

    Returns: {
      "meeting_id", "summary", "key_takeaways", "sentiment",
      "action_items_count", "goals_count", "decisions_count",
      "next_meeting_at"
    }
    """
    meeting = _load_meeting(meeting_id, session)
    if not meeting:
        raise ValueError(f"Meeting {meeting_id} not found")
    if meeting["status"] != "in_progress":
        raise ValueError(
            f"Cannot end meeting in status '{meeting['status']}'. "
            f"Expected 'in_progress'."
        )

    business_id = meeting["business_id"]
    history = _load_message_history(meeting_id, session)
    transcript = _build_transcript(history)
    extraction_failure: Optional[str] = None
    summary_failure: Optional[str] = None

    # ---- Extraction (resilient) ----
    action_count = 0
    goal_count = 0
    decision_count = 0
    extracted_total_tokens = 0
    try:
        extraction_result = await _run_extraction(
            transcript=transcript,
            meeting_id=meeting_id,
            business_id=business_id,
            session=session,
        )
        action_count = extraction_result["action_items_count"]
        goal_count = extraction_result["goals_count"]
        decision_count = extraction_result["decisions_count"]
        extracted_total_tokens += extraction_result["tokens_used"]
    except Exception as e:
        extraction_failure = str(e)
        logger.exception(
            "[ExecMeeting] Extraction failed for meeting %s — meeting will still close",
            meeting_id,
        )

    # ---- Summary (resilient) ----
    summary_text: Optional[str] = None
    key_takeaways: List[str] = []
    sentiment: Optional[str] = None
    try:
        summary_result = await _run_summary(transcript)
        summary_text = summary_result.get("summary")
        key_takeaways = summary_result.get("key_takeaways") or []
        sentiment = summary_result.get("sentiment")
        extracted_total_tokens += summary_result.get("tokens_used", 0)
    except Exception as e:
        summary_failure = str(e)
        logger.exception(
            "[ExecMeeting] Summary generation failed for meeting %s — using fallback",
            meeting_id,
        )
        summary_text = "Meeting concluded. Detailed summary unavailable."
        key_takeaways = []
        sentiment = None

    # ---- Compute duration ----
    started_at = meeting.get("started_at")
    duration_minutes: Optional[int] = None
    ended_at_dt = datetime.now(timezone.utc)
    if started_at:
        try:
            started_dt = (
                started_at
                if isinstance(started_at, datetime)
                else datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
            )
            if started_dt.tzinfo is None:
                started_dt = started_dt.replace(tzinfo=timezone.utc)
            duration_minutes = int((ended_at_dt - started_dt).total_seconds() / 60)
        except Exception:
            duration_minutes = None

    # ---- Update meeting record ----
    update_fields: Dict[str, Any] = {
        "status": "completed",
        "ended_at": ended_at_dt.isoformat(),
        "summary": summary_text,
        "key_takeaways": json.dumps(key_takeaways),
        "sentiment": _clamp_sentiment(sentiment),
    }
    if duration_minutes is not None:
        update_fields["duration_minutes"] = duration_minutes
    _update_meeting(meeting_id, session, update_fields)
    if extracted_total_tokens:
        _increment_total_tokens(meeting_id, extracted_total_tokens, session)
    session.commit()

    # ---- Recompute next_meeting_at ----
    next_meeting_iso: Optional[str] = None
    try:
        settings = _load_settings(business_id, session) or {}
        next_dt = compute_next_meeting_time(settings)
        if next_dt is not None:
            next_meeting_iso = next_dt.isoformat()
            session.execute(
                text(
                    """
                    UPDATE executive_meeting_settings
                    SET next_meeting_at = :next_at,
                        last_meeting_at = NOW(),
                        total_meetings_completed = COALESCE(total_meetings_completed, 0) + 1,
                        updated_at = NOW()
                    WHERE business_id = :business_id
                    """
                ),
                {"business_id": business_id, "next_at": next_meeting_iso},
            )
            session.commit()
    except Exception:
        logger.exception(
            "[ExecMeeting] Failed to recompute next_meeting_at for business %s",
            business_id,
        )

    logger.info(
        "[ExecMeeting] Meeting %s closed. actions=%d goals=%d decisions=%d "
        "duration=%s next=%s extraction_err=%s summary_err=%s",
        meeting_id,
        action_count,
        goal_count,
        decision_count,
        duration_minutes,
        next_meeting_iso,
        bool(extraction_failure),
        bool(summary_failure),
    )

    return {
        "meeting_id": meeting_id,
        "summary": summary_text,
        "key_takeaways": key_takeaways,
        "sentiment": _clamp_sentiment(sentiment),
        "action_items_count": action_count,
        "goals_count": goal_count,
        "decisions_count": decision_count,
        "duration_minutes": duration_minutes,
        "next_meeting_at": next_meeting_iso,
        "extraction_error": extraction_failure,
        "summary_error": summary_failure,
    }


async def extract_actions_and_goals(meeting_id: str, session: Session) -> Dict[str, Any]:
    """
    Public entry for the /extract-actions endpoint. Runs extraction over
    the meeting's transcript and persists the results. Returns counts.

    Can be called repeatedly — extraction always inserts new rows; we don't
    attempt to de-duplicate. (If you call /end which itself calls extraction,
    do not call this separately.)
    """
    meeting = _load_meeting(meeting_id, session)
    if not meeting:
        raise ValueError(f"Meeting {meeting_id} not found")
    history = _load_message_history(meeting_id, session)
    if not history:
        return {
            "action_items_count": 0,
            "goals_count": 0,
            "decisions_count": 0,
            "tokens_used": 0,
        }
    transcript = _build_transcript(history)
    result = await _run_extraction(
        transcript=transcript,
        meeting_id=meeting_id,
        business_id=meeting["business_id"],
        session=session,
    )
    if result.get("tokens_used"):
        _increment_total_tokens(meeting_id, result["tokens_used"], session)
    session.commit()
    return result


# ============================================================================
# Internal: GPT call wrapper
# ============================================================================

def _get_async_client() -> Optional[AsyncOpenAI]:
    """Lazy AsyncOpenAI client. Returns None if no API key configured."""
    if not OPENAI_API_KEY:
        return None
    return AsyncOpenAI(api_key=OPENAI_API_KEY)


async def _gpt_chat_completion(
    messages: List[Dict[str, str]],
    temperature: float = 0.4,
    max_tokens: int = MAX_OUTPUT_TOKENS,
    response_format: Optional[Dict[str, str]] = None,
) -> tuple[Optional[str], int]:
    """
    Single point of contact with OpenAI. Returns (content, tokens_used).
    On any failure returns (None, 0) — caller must handle.

    Uses EXECUTIVE_MEETING_AI_MODEL env var to pick the model. Set this in
    Railway to override the default (e.g. "gpt-5.5").
    """
    client = _get_async_client()
    if client is None:
        logger.error("[ExecMeeting] OPENAI_API_KEY not configured")
        return None, 0

    kwargs: Dict[str, Any] = {
        "model": EXECUTIVE_MEETING_AI_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format is not None:
        kwargs["response_format"] = response_format

    try:
        response = await client.chat.completions.create(**kwargs)
    except Exception as exc:
        logger.exception("[ExecMeeting] GPT call failed: %s", exc)
        return None, 0

    try:
        content = response.choices[0].message.content
        tokens = int(response.usage.total_tokens) if response.usage else 0
        return content, tokens
    except Exception:
        logger.exception("[ExecMeeting] Could not parse GPT response shape")
        return None, 0


# ============================================================================
# Internal: extraction
# ============================================================================

async def _run_extraction(
    transcript: str,
    meeting_id: str,
    business_id: str,
    session: Session,
) -> Dict[str, Any]:
    """Run the extraction GPT call and persist results. Always returns counts."""
    msgs = messages_for_extraction(transcript)
    content, tokens = await _gpt_chat_completion(
        messages=msgs,
        temperature=0.1,
        max_tokens=MAX_EXTRACTION_TOKENS,
        response_format={"type": "json_object"},
    )

    if not content:
        return {
            "action_items_count": 0,
            "goals_count": 0,
            "decisions_count": 0,
            "tokens_used": tokens,
        }

    try:
        extracted = json.loads(content)
        if not isinstance(extracted, dict):
            raise ValueError("Extraction response is not a JSON object")
    except Exception:
        logger.exception("[ExecMeeting] Extraction returned malformed JSON")
        return {
            "action_items_count": 0,
            "goals_count": 0,
            "decisions_count": 0,
            "tokens_used": tokens,
        }

    action_items = extracted.get("action_items") or []
    goals = extracted.get("goals") or []
    decisions = extracted.get("decisions") or []

    a_count = 0
    for item in action_items if isinstance(action_items, list) else []:
        try:
            _save_action_item(meeting_id, business_id, item, session)
            a_count += 1
        except Exception:
            logger.exception(
                "[ExecMeeting] Failed to persist action item: %s",
                _safe_repr(item),
            )

    g_count = 0
    for goal in goals if isinstance(goals, list) else []:
        try:
            _save_goal(meeting_id, business_id, goal, session)
            g_count += 1
        except Exception:
            logger.exception(
                "[ExecMeeting] Failed to persist goal: %s", _safe_repr(goal)
            )

    d_count = 0
    for decision in decisions if isinstance(decisions, list) else []:
        try:
            _save_decision(meeting_id, business_id, decision, session)
            d_count += 1
        except Exception:
            logger.exception(
                "[ExecMeeting] Failed to persist decision: %s", _safe_repr(decision)
            )

    return {
        "action_items_count": a_count,
        "goals_count": g_count,
        "decisions_count": d_count,
        "tokens_used": tokens,
    }


def _save_action_item(
    meeting_id: str, business_id: str, item: Dict[str, Any], session: Session
) -> None:
    """Persist one extracted action item. Caller commits."""
    title = str(item.get("title") or "").strip()
    if not title:
        return  # title is required by schema; silently skip malformed entries

    priority = (item.get("priority") or "medium").strip().lower()
    if priority not in ("low", "medium", "high", "urgent"):
        priority = "medium"

    due_date = _parse_iso_date(item.get("due_date"))
    assignee_name = str(item.get("assignee_name") or "").strip() or None
    assignee_email = str(item.get("assignee_email") or "").strip() or None
    description = _safe_text(item.get("description"))
    success_criteria = _safe_text(item.get("success_criteria"))
    rationale = _safe_text(item.get("rationale"))

    session.execute(
        text(
            """
            INSERT INTO executive_meeting_action_items
                (meeting_id, business_id, title, description,
                 assignee_name, assignee_email,
                 status, priority, due_date,
                 rationale, success_criteria)
            VALUES
                (:meeting_id, :business_id, :title, :description,
                 :assignee_name, :assignee_email,
                 'open', :priority, :due_date,
                 :rationale, :success_criteria)
            """
        ),
        {
            "meeting_id": meeting_id,
            "business_id": business_id,
            "title": title[:500],
            "description": description,
            "assignee_name": assignee_name,
            "assignee_email": assignee_email,
            "priority": priority,
            "due_date": due_date,
            "rationale": rationale,
            "success_criteria": success_criteria,
        },
    )


def _save_goal(
    meeting_id: str, business_id: str, goal: Dict[str, Any], session: Session
) -> None:
    """Persist one extracted goal. Caller commits."""
    title = str(goal.get("title") or "").strip()
    if not title:
        return

    horizon = (goal.get("horizon") or "short_term").strip().lower()
    if horizon not in ("short_term", "medium_term", "long_term"):
        horizon = "short_term"

    target_date = _parse_iso_date(goal.get("target_date"))
    category = _safe_text(goal.get("category"), max_len=100)
    kpi_name = _safe_text(goal.get("kpi_name"), max_len=200)
    kpi_unit = _safe_text(goal.get("kpi_unit"), max_len=50)
    description = _safe_text(goal.get("description"))

    def _num(v):
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    session.execute(
        text(
            """
            INSERT INTO executive_meeting_goals
                (business_id, set_in_meeting_id, title, description,
                 horizon, category,
                 kpi_name, kpi_target_value, kpi_unit,
                 status, target_date)
            VALUES
                (:business_id, :meeting_id, :title, :description,
                 :horizon, :category,
                 :kpi_name, :kpi_target, :kpi_unit,
                 'active', :target_date)
            """
        ),
        {
            "business_id": business_id,
            "meeting_id": meeting_id,
            "title": title[:500],
            "description": description,
            "horizon": horizon,
            "category": category,
            "kpi_name": kpi_name,
            "kpi_target": _num(goal.get("kpi_target_value")),
            "kpi_unit": kpi_unit,
            "target_date": target_date,
        },
    )


def _save_decision(
    meeting_id: str, business_id: str, decision: Dict[str, Any], session: Session
) -> None:
    """Persist one extracted decision. Caller commits."""
    decision_text = str(decision.get("decision") or "").strip()
    if not decision_text:
        return

    owner_chose = decision.get("owner_chose_differently")
    if not isinstance(owner_chose, bool):
        owner_chose = False

    session.execute(
        text(
            """
            INSERT INTO executive_meeting_decisions
                (meeting_id, business_id,
                 decision, context, rationale,
                 aria_recommendation, owner_chose_differently)
            VALUES
                (:meeting_id, :business_id,
                 :decision, :context, :rationale,
                 :aria_recommendation, :owner_chose)
            """
        ),
        {
            "meeting_id": meeting_id,
            "business_id": business_id,
            "decision": decision_text[:2000],
            "context": _safe_text(decision.get("context"), max_len=2000),
            "rationale": _safe_text(decision.get("rationale"), max_len=2000),
            "aria_recommendation": _safe_text(
                decision.get("aria_recommendation"), max_len=2000
            ),
            "owner_chose": owner_chose,
        },
    )


# ============================================================================
# Internal: summary
# ============================================================================

async def _run_summary(transcript: str) -> Dict[str, Any]:
    """Run the closing-summary GPT call. Returns parsed JSON or fallback."""
    msgs = messages_for_summary(transcript)
    content, tokens = await _gpt_chat_completion(
        messages=msgs,
        temperature=0.2,
        max_tokens=MAX_SUMMARY_TOKENS,
        response_format={"type": "json_object"},
    )

    if not content:
        return {
            "summary": "Meeting concluded.",
            "key_takeaways": [],
            "sentiment": None,
            "tokens_used": tokens,
        }

    try:
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError("Summary response is not a JSON object")
    except Exception:
        logger.exception("[ExecMeeting] Summary returned malformed JSON")
        return {
            "summary": "Meeting concluded.",
            "key_takeaways": [],
            "sentiment": None,
            "tokens_used": tokens,
        }

    takeaways = parsed.get("key_takeaways") or []
    if not isinstance(takeaways, list):
        takeaways = []

    return {
        "summary": _safe_text(parsed.get("summary"), max_len=5000)
        or "Meeting concluded.",
        "key_takeaways": [str(t)[:500] for t in takeaways][:5],
        "sentiment": parsed.get("sentiment"),
        "tokens_used": tokens,
    }


# ============================================================================
# Internal: DB helpers
# ============================================================================

def _load_meeting(meeting_id: str, session: Session) -> Optional[Dict[str, Any]]:
    """Load a meeting row by id. Returns dict or None."""
    row = session.execute(
        text(
            """
            SELECT id, business_id, status, scheduled_for, prep_started_at,
                   started_at, ended_at, prep_data, ai_model,
                   total_tokens_used
            FROM executive_meetings
            WHERE id = :meeting_id
            LIMIT 1
            """
        ),
        {"meeting_id": meeting_id},
    ).fetchone()
    if not row:
        return None
    prep_raw = row[7]
    if isinstance(prep_raw, str):
        try:
            prep_raw = json.loads(prep_raw)
        except Exception:
            prep_raw = {}
    return {
        "id": str(row[0]),
        "business_id": str(row[1]),
        "status": row[2],
        "scheduled_for": row[3],
        "prep_started_at": row[4],
        "started_at": row[5],
        "ended_at": row[6],
        "prep_data": prep_raw or {},
        "ai_model": row[8],
        "total_tokens_used": row[9] or 0,
    }


def _load_settings(business_id: str, session: Session) -> Optional[Dict[str, Any]]:
    row = session.execute(
        text(
            """
            SELECT enabled, frequency, day_of_week, day_of_month, meeting_time,
                   timezone, focus_areas, custom_agenda_items, attendees,
                   directness_level, include_disclaimers
            FROM executive_meeting_settings
            WHERE business_id = :business_id
            LIMIT 1
            """
        ),
        {"business_id": business_id},
    ).fetchone()
    if not row:
        return None
    return {
        "enabled": bool(row[0]),
        "frequency": row[1],
        "day_of_week": row[2],
        "day_of_month": row[3],
        "meeting_time": str(row[4]) if row[4] else None,
        "timezone": row[5] or "Europe/London",
        "focus_areas": _coerce_jsonb_list(row[6]),
        "custom_agenda_items": _coerce_jsonb_list(row[7]),
        "attendees": _coerce_jsonb_list(row[8]),
        "directness_level": row[9] or "balanced",
        "include_disclaimers": bool(row[10]) if row[10] is not None else True,
    }


def _load_message_history(meeting_id: str, session: Session) -> List[Dict[str, Any]]:
    rows = session.execute(
        text(
            """
            SELECT role, content, agenda_section, created_at, tokens_used
            FROM executive_meeting_messages
            WHERE meeting_id = :meeting_id
            ORDER BY created_at ASC, id ASC
            """
        ),
        {"meeting_id": meeting_id},
    ).fetchall()
    return [
        {
            "role": r[0],
            "content": r[1],
            "agenda_section": r[2],
            "created_at": r[3].isoformat() if r[3] else None,
            "tokens_used": r[4] or 0,
        }
        for r in rows
    ]


def _save_message(
    meeting_id: str,
    business_id: str,
    role: str,
    content: str,
    tokens_used: int = 0,
    agenda_section: Optional[str] = None,
    session: Session = None,
) -> None:
    """Persist a single message. Caller commits."""
    session.execute(
        text(
            """
            INSERT INTO executive_meeting_messages
                (meeting_id, business_id, role, content, agenda_section, tokens_used)
            VALUES
                (:meeting_id, :business_id, :role, :content, :agenda_section, :tokens_used)
            """
        ),
        {
            "meeting_id": meeting_id,
            "business_id": business_id,
            "role": role,
            "content": content or "",
            "agenda_section": agenda_section,
            "tokens_used": int(tokens_used or 0),
        },
    )


def _update_meeting(
    meeting_id: str, session: Session, fields: Dict[str, Any]
) -> None:
    """Update a meeting row with arbitrary field values. Caller commits."""
    allowed = {
        "status",
        "started_at",
        "ended_at",
        "duration_minutes",
        "summary",
        "key_takeaways",
        "sentiment",
    }
    pairs = {k: v for k, v in fields.items() if k in allowed}
    if not pairs:
        return
    set_clauses = []
    params: Dict[str, Any] = {"meeting_id": meeting_id}
    for k, v in pairs.items():
        if k == "key_takeaways":
            set_clauses.append(f"{k} = CAST(:{k} AS jsonb)")
        else:
            set_clauses.append(f"{k} = :{k}")
        params[k] = v
    session.execute(
        text(
            f"""
            UPDATE executive_meetings
            SET {", ".join(set_clauses)}, updated_at = NOW()
            WHERE id = :meeting_id
            """
        ),
        params,
    )


def _increment_total_tokens(meeting_id: str, delta: int, session: Session) -> None:
    """Add `delta` tokens to the meeting's running total. Caller commits."""
    if not delta:
        return
    session.execute(
        text(
            """
            UPDATE executive_meetings
            SET total_tokens_used = COALESCE(total_tokens_used, 0) + :delta,
                updated_at = NOW()
            WHERE id = :meeting_id
            """
        ),
        {"meeting_id": meeting_id, "delta": int(delta)},
    )


# ============================================================================
# Internal: small helpers
# ============================================================================

def _build_transcript(history: List[Dict[str, Any]]) -> str:
    """Render the message history as a plain-text transcript for GPT context."""
    lines: List[str] = []
    for msg in history:
        role = msg.get("role")
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        speaker = {
            "aria": "Aria",
            "owner": "Owner",
            "system": "System",
            "attendee": "Attendee",
        }.get(role, role or "Unknown")
        lines.append(f"{speaker}: {content}")
    return "\n\n".join(lines)


def _coerce_jsonb_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
            return decoded if isinstance(decoded, list) else []
        except Exception:
            return []
    return []


def _parse_iso_date(value: Any) -> Optional[str]:
    """
    Best-effort ISO date parser. Returns 'YYYY-MM-DD' string or None.
    Per the audit decision, natural-language dates ("by Friday") become None
    so the action item is still created and the owner can date it later.
    """
    if not value:
        return None
    try:
        s = str(value).strip()
        # Accept ISO date or ISO datetime; take just the date part.
        date_part = s.split("T")[0]
        # Validate
        from datetime import date as _date
        _date.fromisoformat(date_part)
        return date_part
    except Exception:
        return None


def _safe_text(value: Any, max_len: int = 1000) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    return s[:max_len]


def _clamp_sentiment(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip().lower()
    if s in ("positive", "neutral", "concerning", "critical"):
        return s
    return None


def _safe_repr(obj: Any, max_len: int = 200) -> str:
    """Bounded repr for log lines."""
    try:
        s = json.dumps(obj, default=str)
    except Exception:
        s = repr(obj)
    return s if len(s) <= max_len else s[:max_len] + "…"
