"""
Invoices loader: outstanding/overdue counts, payment-velocity, top debtors.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List

from sqlalchemy import text
from sqlmodel import Session

from ._common import iso_or_none, safe_float, truncate

logger = logging.getLogger(__name__)

_OUTSTANDING_STATUSES = ("unpaid", "authorised", "sent")
_MAX_TOP_DEBTORS = 5


def _empty_section() -> Dict[str, Any]:
    return {
        "available": False,
        "errors": [],
        "outstanding_total": None,
        "outstanding_count": None,
        "overdue_count": None,
        "overdue_total": None,
        "oldest_overdue_days": None,
        "avg_payment_days_last_90d": None,
        "paid_this_period_count": None,
        "paid_this_period_total": None,
        "top_debtors": [],
        "trend": "unknown",
    }


def _classify_trend(overdue_count: int, outstanding_count: int, oldest_days: int) -> str:
    """Heuristic trend label for invoice health."""
    if overdue_count == 0 and outstanding_count <= 5:
        return "healthy"
    if overdue_count >= 5 or oldest_days >= 60 or outstanding_count >= 15:
        return "concerning"
    return "neutral"


def gather(
    business_id: str,
    period: Dict[str, Any],
    session: Session,
) -> Dict[str, Any]:
    section = _empty_section()
    try:
        today = date.today()

        # Snapshot of all non-archived invoices for the business
        rows = session.execute(
            text(
                """
                SELECT id, customer_name, status, amount, amount_due, due_date
                FROM invoices
                WHERE business_id = :business_id
                  AND (archived IS NULL OR archived = false)
                """
            ),
            {"business_id": business_id},
        ).fetchall()

        outstanding: List[Dict[str, Any]] = []
        overdue: List[Dict[str, Any]] = []

        for r in rows:
            status = (r[2] or "").lower()
            if status not in _OUTSTANDING_STATUSES:
                continue
            amount_due = safe_float(r[4]) if r[4] is not None else safe_float(r[3], 0.0) or 0.0
            inv = {
                "id": str(r[0]),
                "customer_name": r[1] or "Unknown",
                "amount_due": float(amount_due) if amount_due is not None else 0.0,
                "due_date": r[5],
            }
            outstanding.append(inv)
            if r[5] and r[5] < today:
                inv = dict(inv)
                inv["days_overdue"] = (today - r[5]).days
                overdue.append(inv)

        outstanding_total = round(sum(i["amount_due"] for i in outstanding), 2)
        overdue_total = round(sum(i["amount_due"] for i in overdue), 2)
        oldest_overdue_days = max((i.get("days_overdue", 0) for i in overdue), default=0)

        # Paid in current period
        paid_row = session.execute(
            text(
                """
                SELECT COUNT(*), COALESCE(SUM(amount), 0)
                FROM invoices
                WHERE business_id = :business_id
                  AND (archived IS NULL OR archived = false)
                  AND LOWER(status) = 'paid'
                  AND paid_at >= :start
                  AND paid_at <= :end
                """
            ),
            {
                "business_id": business_id,
                "start": period["current_start_iso"],
                "end": period["current_end_iso"],
            },
        ).fetchone()
        paid_count = int(paid_row[0]) if paid_row and paid_row[0] is not None else 0
        paid_total = float(paid_row[1]) if paid_row and paid_row[1] is not None else 0.0

        # Average days from issue_date to paid_date over last 90 days
        velocity_row = session.execute(
            text(
                """
                SELECT AVG(EXTRACT(EPOCH FROM (paid_at - issue_date::timestamp)) / 86400.0)
                FROM invoices
                WHERE business_id = :business_id
                  AND LOWER(status) = 'paid'
                  AND paid_at IS NOT NULL
                  AND issue_date IS NOT NULL
                  AND paid_at >= NOW() - INTERVAL '90 days'
                """
            ),
            {"business_id": business_id},
        ).fetchone()
        avg_payment_days = (
            round(float(velocity_row[0]), 1)
            if velocity_row and velocity_row[0] is not None
            else None
        )

        # Top debtors (largest overdue first, capped)
        overdue_sorted = sorted(
            overdue, key=lambda i: i["amount_due"], reverse=True
        )[:_MAX_TOP_DEBTORS]
        top_debtors = [
            {
                "id": i["id"],
                "name": truncate(i["customer_name"], 100),
                "amount": round(i["amount_due"], 2),
                "days_overdue": i.get("days_overdue", 0),
                "due_date": iso_or_none(i["due_date"]),
            }
            for i in overdue_sorted
        ]

        section.update(
            {
                "available": True,
                "outstanding_total": outstanding_total,
                "outstanding_count": len(outstanding),
                "overdue_count": len(overdue),
                "overdue_total": overdue_total,
                "oldest_overdue_days": int(oldest_overdue_days),
                "avg_payment_days_last_90d": avg_payment_days,
                "paid_this_period_count": paid_count,
                "paid_this_period_total": round(paid_total, 2),
                "top_debtors": top_debtors,
                "trend": _classify_trend(
                    len(overdue), len(outstanding), int(oldest_overdue_days)
                ),
            }
        )
        return section
    except Exception as e:
        logger.exception("[Prep] invoices loader failed")
        section["available"] = False
        section["errors"].append(str(e))
        return section
