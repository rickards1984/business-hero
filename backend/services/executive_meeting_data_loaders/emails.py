"""
Emails loader: volume, AI category breakdown, unanswered backlog.

Notes
-----
- avg_response_time_hours is intentionally returned as None — the schema has no
  reliable response-correlation column on email_messages. Surfacing a fake
  proxy would mislead the meeting; honesty over false precision.
- unanswered_over_24h is computed from email_messages columns we DO have:
  unread + ai_category='Action Required' + received_at < now-24h.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from sqlalchemy import text
from sqlmodel import Session

logger = logging.getLogger(__name__)


def _empty_section() -> Dict[str, Any]:
    return {
        "available": False,
        "errors": [],
        "total_received": None,
        "by_category": {},
        "avg_response_time_hours": None,
        "unanswered_over_24h": None,
    }


def gather(
    business_id: str,
    period: Dict[str, Any],
    session: Session,
) -> Dict[str, Any]:
    section = _empty_section()
    try:
        # Existence / volume in current period
        rows = session.execute(
            text(
                """
                SELECT ai_category, is_unread
                FROM email_messages
                WHERE business_id = :business_id
                  AND received_at >= :start
                  AND received_at <= :end
                """
            ),
            {
                "business_id": business_id,
                "start": period["current_start_iso"],
                "end": period["current_end_iso"],
            },
        ).fetchall()

        total = len(rows)
        by_category: Dict[str, int] = {}
        for r in rows:
            cat = r[0] or "uncategorised"
            by_category[cat] = by_category.get(cat, 0) + 1

        # Backlog: action-required emails received >24h ago that are still unread
        backlog_row = session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM email_messages
                WHERE business_id = :business_id
                  AND is_unread = true
                  AND ai_category = 'Action Required'
                  AND received_at < (NOW() - INTERVAL '24 hours')
                """
            ),
            {"business_id": business_id},
        ).fetchone()
        unanswered_over_24h = int(backlog_row[0]) if backlog_row else 0

        section.update(
            {
                "available": True,
                "total_received": total,
                "by_category": by_category,
                # Honest null — see module docstring.
                "avg_response_time_hours": None,
                "unanswered_over_24h": unanswered_over_24h,
            }
        )
        return section
    except Exception as e:
        logger.exception("[Prep] emails loader failed")
        section["available"] = False
        section["errors"].append(str(e))
        return section
