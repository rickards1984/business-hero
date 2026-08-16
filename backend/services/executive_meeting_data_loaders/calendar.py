"""
Calendar loader: bookings volume + capacity utilisation.

Notes
-----
- no_shows is intentionally returned as None: calendar_events.status doesn't
  reliably mark no-shows; that's a manual annotation. Returning a fabricated
  value would mislead the meeting.
- Capacity utilisation is a heuristic against booking_settings.business_hours
  if available; otherwise None.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlmodel import Session

from ._common import pct_delta, trend_label

logger = logging.getLogger(__name__)


def _empty_section() -> Dict[str, Any]:
    return {
        "available": False,
        "errors": [],
        "bookings_this_period": None,
        "no_shows": None,
        "capacity_utilization_pct": None,
        "previous_period_bookings": None,
        "trend": "unknown",
    }


def _parse_business_hours(raw: Any) -> List[Dict[str, Any]]:
    """Accept jsonb str or already-decoded list; return a list of day blocks."""
    if not raw:
        return []
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(data, list):
            return data
        return []
    except Exception:
        return []


def _slots_per_week(hours_blocks: List[Dict[str, Any]], slot_minutes: int = 60) -> int:
    """Approximate weekly slots from a business_hours array."""
    total_minutes = 0
    for block in hours_blocks:
        if not block.get("enabled"):
            continue
        try:
            sh, sm = [int(x) for x in str(block.get("start", "09:00")).split(":")]
            eh, em = [int(x) for x in str(block.get("end", "17:00")).split(":")]
            start_min = sh * 60 + sm
            end_min = eh * 60 + em
            if end_min > start_min:
                total_minutes += end_min - start_min
        except Exception:
            continue
    if total_minutes <= 0 or slot_minutes <= 0:
        return 0
    return total_minutes // slot_minutes


def _capacity_pct(
    bookings: int,
    period_days: int,
    weekly_slots: int,
) -> Optional[int]:
    if weekly_slots <= 0 or period_days <= 0:
        return None
    expected_slots = (weekly_slots / 7.0) * period_days
    if expected_slots <= 0:
        return None
    pct = round(bookings / expected_slots * 100)
    return max(0, min(100, pct))


def _count_period(
    session: Session,
    business_id: str,
    start_iso: str,
    end_iso: str,
) -> int:
    row = session.execute(
        text(
            """
            SELECT COUNT(*)
            FROM calendar_events
            WHERE business_id = :business_id
              AND start_at >= :start
              AND start_at <= :end
            """
        ),
        {"business_id": business_id, "start": start_iso, "end": end_iso},
    ).fetchone()
    return int(row[0]) if row else 0


def gather(
    business_id: str,
    period: Dict[str, Any],
    session: Session,
) -> Dict[str, Any]:
    section = _empty_section()
    try:
        # Quick existence check — if no calendar_events table row ever, the
        # business isn't using this feature.
        any_row = session.execute(
            text(
                """
                SELECT 1 FROM calendar_events
                WHERE business_id = :business_id
                LIMIT 1
                """
            ),
            {"business_id": business_id},
        ).fetchone()
        if not any_row:
            section["errors"].append("No calendar events found for business")
            return section

        current_count = _count_period(
            session, business_id,
            period["current_start_iso"], period["current_end_iso"],
        )
        previous_count = _count_period(
            session, business_id,
            period["previous_start_iso"], period["previous_end_iso"],
        )

        # Period length in days, for capacity scaling
        try:
            cur_start = period["current_start"]
            cur_end = period["current_end"]
            period_days = max(1, (cur_end.date() - cur_start.date()).days + 1)
        except Exception:
            period_days = 7

        # Capacity utilisation from booking_settings.business_hours
        capacity_pct = None
        try:
            bs_row = session.execute(
                text(
                    "SELECT business_hours FROM booking_settings "
                    "WHERE business_id = :business_id LIMIT 1"
                ),
                {"business_id": business_id},
            ).fetchone()
            if bs_row:
                hours_blocks = _parse_business_hours(bs_row[0])
                weekly_slots = _slots_per_week(hours_blocks)
                capacity_pct = _capacity_pct(current_count, period_days, weekly_slots)
        except Exception:
            # booking_settings may not exist for this business — capacity stays None
            capacity_pct = None

        delta = pct_delta(float(current_count), float(previous_count)) \
            if (current_count or previous_count) else None

        section.update(
            {
                "available": True,
                "bookings_this_period": current_count,
                # Returning None per audit decision — no reliable no-show signal.
                "no_shows": None,
                "capacity_utilization_pct": capacity_pct,
                "previous_period_bookings": previous_count,
                "trend": trend_label(delta),
            }
        )
        return section
    except Exception as e:
        logger.exception("[Prep] calendar loader failed")
        section["available"] = False
        section["errors"].append(str(e))
        return section
