"""
Last meeting loader: most recent completed meeting + which committed actions
have been done since.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from sqlalchemy import text
from sqlmodel import Session

from ._common import iso_or_none, truncate

logger = logging.getLogger(__name__)

_MAX_TAKEAWAYS = 8
_MAX_ACTIONS_LIST = 10
_MAX_DECISIONS = 5


def _empty_section() -> Dict[str, Any]:
    return {
        "exists": False,
        "errors": [],
        "id": None,
        "date": None,
        "summary": None,
        "key_takeaways": [],
        "decisions_made": [],
        "actions_committed": [],
        "actions_completed_since": [],
        "actions_still_open": [],
    }


def _serialize_action(r) -> Dict[str, Any]:
    return {
        "id": str(r[0]),
        "title": truncate(r[1], 200),
        "status": r[2],
        "priority": r[3],
        "due_date": iso_or_none(r[4]),
        "completed_at": iso_or_none(r[5]),
        "assignee_name": r[6],
    }


def _coerce_list(raw: Any) -> List[Any]:
    """Some JSONB fields may arrive as list, str, or None."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    try:
        import json
        decoded = json.loads(raw) if isinstance(raw, str) else None
        if isinstance(decoded, list):
            return decoded
    except Exception:
        pass
    return []


def gather(
    business_id: str,
    period: Dict[str, Any],
    session: Session,
) -> Dict[str, Any]:
    section = _empty_section()
    try:
        meeting_row = session.execute(
            text(
                """
                SELECT id, scheduled_for, ended_at, summary, key_takeaways
                FROM executive_meetings
                WHERE business_id = :business_id
                  AND status = 'completed'
                ORDER BY COALESCE(ended_at, scheduled_for) DESC
                LIMIT 1
                """
            ),
            {"business_id": business_id},
        ).fetchone()

        if not meeting_row:
            return section

        meeting_id = str(meeting_row[0])
        meeting_date = meeting_row[2] or meeting_row[1]
        section.update(
            {
                "exists": True,
                "id": meeting_id,
                "date": iso_or_none(meeting_date),
                "summary": truncate(meeting_row[3], 1000),
                "key_takeaways": _coerce_list(meeting_row[4])[:_MAX_TAKEAWAYS],
            }
        )

        # Decisions made in that meeting
        try:
            decision_rows = session.execute(
                text(
                    """
                    SELECT decision, rationale, aria_recommendation, owner_chose_differently
                    FROM executive_meeting_decisions
                    WHERE meeting_id = :meeting_id
                    ORDER BY created_at ASC
                    LIMIT :limit
                    """
                ),
                {"meeting_id": meeting_id, "limit": _MAX_DECISIONS},
            ).fetchall()
            section["decisions_made"] = [
                {
                    "decision": truncate(r[0], 300),
                    "rationale": truncate(r[1], 300),
                    "aria_recommendation": truncate(r[2], 300),
                    "owner_chose_differently": bool(r[3]) if r[3] is not None else False,
                }
                for r in decision_rows
            ]
        except Exception as e:
            logger.warning(f"[Prep] last_meeting decisions sub-query failed: {e}")

        # Action items committed in that meeting + status now
        try:
            action_rows = session.execute(
                text(
                    """
                    SELECT id, title, status, priority, due_date, completed_at, assignee_name
                    FROM executive_meeting_action_items
                    WHERE meeting_id = :meeting_id
                    ORDER BY created_at ASC
                    """
                ),
                {"meeting_id": meeting_id},
            ).fetchall()
            actions = [_serialize_action(r) for r in action_rows]

            committed = actions[:_MAX_ACTIONS_LIST]
            completed_since = [a for a in actions if a.get("status") == "completed"][:_MAX_ACTIONS_LIST]
            still_open = [
                a for a in actions
                if a.get("status") in ("open", "in_progress", "blocked", "deferred")
            ][:_MAX_ACTIONS_LIST]

            section.update(
                {
                    "actions_committed": committed,
                    "actions_completed_since": completed_since,
                    "actions_still_open": still_open,
                }
            )
        except Exception as e:
            logger.warning(f"[Prep] last_meeting actions sub-query failed: {e}")

        return section
    except Exception as e:
        logger.exception("[Prep] last_meeting loader failed")
        section["exists"] = False
        section["errors"].append(str(e))
        return section
