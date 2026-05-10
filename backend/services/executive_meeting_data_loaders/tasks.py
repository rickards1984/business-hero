"""
Tasks loader: open backlog, completion rate this period, by-category breakdown.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict

from sqlalchemy import text
from sqlmodel import Session

logger = logging.getLogger(__name__)


def _empty_section() -> Dict[str, Any]:
    return {
        "available": False,
        "errors": [],
        "open_total": None,
        "overdue": None,
        "completed_this_period": None,
        "by_category": {},
        "completion_rate_pct": None,
    }


def gather(
    business_id: str,
    period: Dict[str, Any],
    session: Session,
) -> Dict[str, Any]:
    section = _empty_section()
    try:
        # Snapshot of all live (non-deleted) tasks
        rows = session.execute(
            text(
                """
                SELECT status, category, due_at
                FROM tasks
                WHERE business_id = :business_id
                  AND deleted_at IS NULL
                """
            ),
            {"business_id": business_id},
        ).fetchall()

        now = datetime.now(timezone.utc)
        open_total = 0
        overdue = 0
        by_category: Dict[str, int] = {}
        for r in rows:
            status = (r[0] or "").lower()
            category = r[1] or "general"
            due_at = r[2]
            if status == "open":
                open_total += 1
                by_category[category] = by_category.get(category, 0) + 1
                if due_at is not None:
                    # Make tz-aware if needed for comparison
                    due = due_at if due_at.tzinfo else due_at.replace(tzinfo=timezone.utc)
                    if due < now:
                        overdue += 1

        # Completed in current period
        completed_row = session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM tasks
                WHERE business_id = :business_id
                  AND deleted_at IS NULL
                  AND LOWER(status) = 'completed'
                  AND updated_at >= :start
                  AND updated_at <= :end
                """
            ),
            {
                "business_id": business_id,
                "start": period["current_start_iso"],
                "end": period["current_end_iso"],
            },
        ).fetchone()
        completed_this_period = int(completed_row[0]) if completed_row else 0

        # Completion rate: completed / (open_now + completed_this_period)
        denom = open_total + completed_this_period
        completion_rate = (
            round(completed_this_period / denom * 100) if denom > 0 else None
        )

        section.update(
            {
                "available": True,
                "open_total": open_total,
                "overdue": overdue,
                "completed_this_period": completed_this_period,
                "by_category": by_category,
                "completion_rate_pct": completion_rate,
            }
        )
        return section
    except Exception as e:
        logger.exception("[Prep] tasks loader failed")
        section["available"] = False
        section["errors"].append(str(e))
        return section
