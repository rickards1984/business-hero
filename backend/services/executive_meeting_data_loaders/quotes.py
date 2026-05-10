"""
Quotes loader: issue/accept counts + values + conversion rate.

Marks `available=false` if the business has no quotes records at all
(proxy for "doesn't use the quoting feature").
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from sqlalchemy import text
from sqlmodel import Session

from ._common import safe_float

logger = logging.getLogger(__name__)


def _empty_section() -> Dict[str, Any]:
    return {
        "available": False,
        "errors": [],
        "issued_count": None,
        "issued_total_value": None,
        "accepted_count": None,
        "accepted_total_value": None,
        "conversion_rate_pct": None,
    }


def gather(
    business_id: str,
    period: Dict[str, Any],
    session: Session,
) -> Dict[str, Any]:
    section = _empty_section()
    try:
        # Treat "no quotes records ever" as feature unused for this business.
        any_row = session.execute(
            text(
                "SELECT 1 FROM quotes WHERE business_id = :business_id LIMIT 1"
            ),
            {"business_id": business_id},
        ).fetchone()
        if not any_row:
            section["errors"].append("No quotes records found for business")
            return section

        # Issued: created within the current period
        issued_row = session.execute(
            text(
                """
                SELECT COUNT(*), COALESCE(SUM(total), 0)
                FROM quotes
                WHERE business_id = :business_id
                  AND created_at >= :start
                  AND created_at <= :end
                """
            ),
            {
                "business_id": business_id,
                "start": period["current_start_iso"],
                "end": period["current_end_iso"],
            },
        ).fetchone()
        issued_count = int(issued_row[0]) if issued_row else 0
        issued_total = safe_float(issued_row[1] if issued_row else 0, 0.0) or 0.0

        # Accepted: accepted_at falls within current period (irrespective of
        # when issued — captures "won this week" momentum).
        accepted_row = session.execute(
            text(
                """
                SELECT COUNT(*), COALESCE(SUM(total), 0)
                FROM quotes
                WHERE business_id = :business_id
                  AND accepted_at IS NOT NULL
                  AND accepted_at >= :start
                  AND accepted_at <= :end
                """
            ),
            {
                "business_id": business_id,
                "start": period["current_start_iso"],
                "end": period["current_end_iso"],
            },
        ).fetchone()
        accepted_count = int(accepted_row[0]) if accepted_row else 0
        accepted_total = safe_float(accepted_row[1] if accepted_row else 0, 0.0) or 0.0

        conversion = (
            round(accepted_count / issued_count * 100)
            if issued_count > 0
            else None
        )

        section.update(
            {
                "available": True,
                "issued_count": issued_count,
                "issued_total_value": round(issued_total, 2),
                "accepted_count": accepted_count,
                "accepted_total_value": round(accepted_total, 2),
                "conversion_rate_pct": conversion,
            }
        )
        return section
    except Exception as e:
        logger.exception("[Prep] quotes loader failed")
        section["available"] = False
        section["errors"].append(str(e))
        return section
