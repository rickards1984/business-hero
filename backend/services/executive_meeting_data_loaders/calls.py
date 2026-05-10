"""
Calls loader: volume, missed-call rate, AI handling rate, peak hour.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from sqlalchemy import text
from sqlmodel import Session

from ._common import pct_delta, trend_label

logger = logging.getLogger(__name__)


def _empty_section() -> Dict[str, Any]:
    return {
        "available": False,
        "errors": [],
        "total_calls": None,
        "missed_calls": None,
        "answered_by_ai_pct": None,
        "avg_duration_seconds": None,
        "peak_hour": None,
        "previous_period_total": None,
        "trend": "unknown",
    }


def gather(
    business_id: str,
    period: Dict[str, Any],
    session: Session,
) -> Dict[str, Any]:
    section = _empty_section()
    try:
        # Current period — full row data so we can compute several metrics
        current_rows = session.execute(
            text(
                """
                SELECT source, outcome, duration_seconds, started_at
                FROM calls
                WHERE business_id = :business_id
                  AND (archived IS NULL OR archived = false)
                  AND started_at >= :start
                  AND started_at <= :end
                """
            ),
            {
                "business_id": business_id,
                "start": period["current_start_iso"],
                "end": period["current_end_iso"],
            },
        ).fetchall()

        # Previous period — count only
        prev_count_row = session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM calls
                WHERE business_id = :business_id
                  AND (archived IS NULL OR archived = false)
                  AND started_at >= :start
                  AND started_at <= :end
                """
            ),
            {
                "business_id": business_id,
                "start": period["previous_start_iso"],
                "end": period["previous_end_iso"],
            },
        ).fetchone()
        previous_total = int(prev_count_row[0]) if prev_count_row else 0

        total = len(current_rows)
        receptionist = [r for r in current_rows if (r[0] or "") == "receptionist"]
        missed = [
            r for r in current_rows
            if (r[1] or "").lower() in ("missed", "voicemail", "no_answer")
        ]
        handled_by_ai = [
            r for r in receptionist if (r[1] or "").lower() == "handled"
        ]
        durations = [int(r[2]) for r in receptionist if r[2] is not None]

        if total > 0 and receptionist:
            answered_pct = round(len(handled_by_ai) / max(len(receptionist), 1) * 100)
        elif total > 0:
            answered_pct = 0
        else:
            answered_pct = None

        avg_duration = (
            round(sum(durations) / len(durations)) if durations else None
        )

        # Peak hour by count, tz-naive grouping (started_at is timestamp)
        hour_counts: Dict[int, int] = {}
        for r in current_rows:
            ts = r[3]
            if ts is None:
                continue
            try:
                hour_counts[ts.hour] = hour_counts.get(ts.hour, 0) + 1
            except Exception:
                continue
        peak_hour = None
        if hour_counts:
            peak = max(hour_counts.items(), key=lambda x: x[1])
            peak_hour = f"{peak[0]:02d}:00"

        delta = pct_delta(float(total), float(previous_total)) if total or previous_total else None

        section.update(
            {
                "available": True,
                "total_calls": total,
                "missed_calls": len(missed),
                "answered_by_ai_pct": answered_pct,
                "avg_duration_seconds": avg_duration,
                "peak_hour": peak_hour,
                "previous_period_total": previous_total,
                "trend": trend_label(delta),
            }
        )
        return section
    except Exception as e:
        logger.exception("[Prep] calls loader failed")
        section["available"] = False
        section["errors"].append(str(e))
        return section
