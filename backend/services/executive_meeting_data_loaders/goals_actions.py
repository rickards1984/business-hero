"""
Goals + Action Items loader.

Returns two top-level sections (goals, action_items) by walking the
executive_meeting_goals and executive_meeting_action_items tables created
by Prompt 1.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List

from sqlalchemy import text
from sqlmodel import Session

from ._common import iso_or_none, safe_float, truncate

logger = logging.getLogger(__name__)

_MAX_GOAL_LIST = 10
_MAX_ACHIEVED = 5
_MAX_ACTION_LIST = 10


def _empty_goals() -> Dict[str, Any]:
    return {
        "active_count": 0,
        "achieved_this_period": [],
        "at_risk": [],
        "active_goals": [],
        "errors": [],
    }


def _empty_actions() -> Dict[str, Any]:
    return {
        "open_total": 0,
        "overdue_count": 0,
        "completed_this_period_count": 0,
        "by_priority": {"urgent": 0, "high": 0, "medium": 0, "low": 0},
        "open_items": [],
        "overdue_items": [],
        "errors": [],
    }


def _serialize_goal(r) -> Dict[str, Any]:
    return {
        "id": str(r[0]),
        "title": truncate(r[1], 200),
        "description": truncate(r[2], 500),
        "horizon": r[3],
        "category": r[4],
        "kpi_name": r[5],
        "kpi_target_value": safe_float(r[6]),
        "kpi_current_value": safe_float(r[7]),
        "kpi_unit": r[8],
        "status": r[9],
        "target_date": iso_or_none(r[10]),
        "achieved_at": iso_or_none(r[11]),
        "created_at": iso_or_none(r[12]),
    }


def _is_at_risk(g: Dict[str, Any]) -> bool:
    """
    Goal is at risk if:
    - it's 'active'
    - target_date is set
    - elapsed time from created_at to today is > 80% of total time to target
    - kpi_current_value < 50% of kpi_target_value (when both are set)
    """
    if g.get("status") != "active":
        return False
    target_iso = g.get("target_date")
    created_iso = g.get("created_at")
    if not target_iso or not created_iso:
        return False
    try:
        target_d = date.fromisoformat(str(target_iso)[:10])
        created_d = date.fromisoformat(str(created_iso)[:10])
    except Exception:
        return False
    today = date.today()
    total_days = max((target_d - created_d).days, 1)
    elapsed_days = max((today - created_d).days, 0)
    if (elapsed_days / total_days) <= 0.80:
        return False

    target_v = g.get("kpi_target_value")
    current_v = g.get("kpi_current_value")
    if target_v is None or current_v is None or target_v == 0:
        # No KPI numbers — flag purely on the time elapsed signal
        return True
    progress = current_v / target_v
    return progress < 0.5


def _serialize_action(r) -> Dict[str, Any]:
    return {
        "id": str(r[0]),
        "meeting_id": str(r[1]) if r[1] else None,
        "title": truncate(r[2], 200),
        "description": truncate(r[3], 500),
        "assignee_name": r[4],
        "status": r[5],
        "priority": r[6],
        "due_date": iso_or_none(r[7]),
        "completed_at": iso_or_none(r[8]),
        "rationale": truncate(r[9], 300),
        "success_criteria": truncate(r[10], 300),
        "created_at": iso_or_none(r[11]),
    }


def gather(
    business_id: str,
    period: Dict[str, Any],
    session: Session,
) -> Dict[str, Any]:
    """Returns a dict containing two sections: 'goals' and 'action_items'."""
    goals = _empty_goals()
    actions = _empty_actions()

    # ---------------- Goals ----------------
    try:
        goal_rows = session.execute(
            text(
                """
                SELECT id, title, description, horizon, category,
                       kpi_name, kpi_target_value, kpi_current_value, kpi_unit,
                       status, target_date, achieved_at, created_at
                FROM executive_meeting_goals
                WHERE business_id = :business_id
                ORDER BY created_at DESC
                """
            ),
            {"business_id": business_id},
        ).fetchall()

        all_goals = [_serialize_goal(r) for r in goal_rows]
        active = [g for g in all_goals if g.get("status") == "active"]

        # Achieved during the current period
        period_start = period["current_start_iso"]
        period_end = period["current_end_iso"]
        achieved = [
            g for g in all_goals
            if g.get("status") == "achieved"
            and g.get("achieved_at")
            and period_start <= g["achieved_at"] <= period_end
        ]

        at_risk = [g for g in active if _is_at_risk(g)]

        goals.update(
            {
                "active_count": len(active),
                "achieved_this_period": achieved[:_MAX_ACHIEVED],
                "at_risk": at_risk[:_MAX_GOAL_LIST],
                "active_goals": active[:_MAX_GOAL_LIST],
            }
        )
    except Exception as e:
        logger.exception("[Prep] goals loader failed")
        goals["errors"].append(str(e))

    # ---------------- Action Items ----------------
    try:
        action_rows = session.execute(
            text(
                """
                SELECT id, meeting_id, title, description, assignee_name,
                       status, priority, due_date, completed_at,
                       rationale, success_criteria, created_at
                FROM executive_meeting_action_items
                WHERE business_id = :business_id
                ORDER BY created_at DESC
                """
            ),
            {"business_id": business_id},
        ).fetchall()

        all_actions = [_serialize_action(r) for r in action_rows]
        today = date.today()

        open_items = [
            a for a in all_actions
            if a.get("status") in ("open", "in_progress", "blocked", "deferred")
        ]
        overdue_items: List[Dict[str, Any]] = []
        for a in open_items:
            if a.get("due_date"):
                try:
                    if date.fromisoformat(a["due_date"][:10]) < today:
                        overdue_items.append(a)
                except Exception:
                    continue

        # Completed in current period
        period_start = period["current_start_iso"]
        period_end = period["current_end_iso"]
        completed_this_period = [
            a for a in all_actions
            if a.get("status") == "completed"
            and a.get("completed_at")
            and period_start <= a["completed_at"] <= period_end
        ]

        # By priority for OPEN items
        by_priority = {"urgent": 0, "high": 0, "medium": 0, "low": 0}
        for a in open_items:
            pri = a.get("priority") or "medium"
            if pri in by_priority:
                by_priority[pri] += 1

        # Sort overdue by oldest due_date first; cap
        overdue_items.sort(key=lambda x: x.get("due_date") or "")

        actions.update(
            {
                "open_total": len(open_items),
                "overdue_count": len(overdue_items),
                "completed_this_period_count": len(completed_this_period),
                "by_priority": by_priority,
                "open_items": open_items[:_MAX_ACTION_LIST],
                "overdue_items": overdue_items[:_MAX_ACTION_LIST],
            }
        )
    except Exception as e:
        logger.exception("[Prep] action_items loader failed")
        actions["errors"].append(str(e))

    return {"goals": goals, "action_items": actions}
