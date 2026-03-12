"""
Data aggregation engine for CEO briefings.
Pulls data from all Business Hero features: calls, emails, tasks, invoices, accounting.
"""

import logging
from typing import Dict, Any
from datetime import datetime, timedelta, timezone, date

from sqlalchemy import text
from sqlmodel import Session

logger = logging.getLogger(__name__)


async def gather_business_data(
    session: Session,
    business_id: str,
    period: str = "week",
    include_previous: bool = True,
) -> Dict[str, Any]:
    """
    Gather comprehensive business data for a briefing.
    Returns a structured dict with all metrics across all features.
    """
    now = datetime.now(timezone.utc)
    today = now.date()

    # Define period boundaries
    if period == "day":
        period_start = today
        period_end = today
        prev_start = today - timedelta(days=1)
        prev_end = today - timedelta(days=1)
    elif period == "week":
        period_start = today - timedelta(days=today.weekday())
        period_end = today
        prev_start = period_start - timedelta(days=7)
        prev_end = period_start - timedelta(days=1)
    elif period == "month":
        period_start = today.replace(day=1)
        period_end = today
        prev_month = period_start - timedelta(days=1)
        prev_start = prev_month.replace(day=1)
        prev_end = prev_month
    else:
        period_start = today
        period_end = today
        prev_start = today
        prev_end = today

    data = {
        "business_id": business_id,
        "period": period,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "generated_at": now.isoformat(),
    }

    # --- Calls ---
    try:
        period_end_ts = f"{period_end}T23:59:59"
        calls_rows = session.execute(
            text("""
                SELECT id, source, outcome, duration_seconds, caller_name, started_at, summary
                FROM calls
                WHERE business_id = :business_id
                  AND started_at >= :period_start
                  AND started_at <= :period_end_ts
            """),
            {
                "business_id": business_id,
                "period_start": period_start.isoformat(),
                "period_end_ts": period_end_ts,
            },
        ).fetchall()

        calls = [
            {
                "id": str(r[0]),
                "source": r[1],
                "outcome": r[2],
                "duration_seconds": r[3],
                "caller_name": r[4],
                "started_at": r[5].isoformat() if r[5] else None,
                "summary": r[6],
            }
            for r in calls_rows
        ]
        receptionist_calls = [c for c in calls if c.get("source") == "receptionist"]
        durations = [c.get("duration_seconds") or 0 for c in receptionist_calls if c.get("duration_seconds")]
        handled = len([c for c in receptionist_calls if c.get("outcome") == "handled"])

        data["calls"] = {
            "total": len(calls),
            "receptionist_total": len(receptionist_calls),
            "handled_by_ai": handled,
            "transferred": len([c for c in receptionist_calls if c.get("outcome") == "transferred"]),
            "voicemail": len([c for c in receptionist_calls if c.get("outcome") == "voicemail"]),
            "avg_duration": round(sum(durations) / max(len(receptionist_calls), 1)) if receptionist_calls else 0,
            "ai_resolution_rate": round(handled / max(len(receptionist_calls), 1) * 100),
            "recent_summaries": [
                {"caller": c.get("caller_name", "Unknown"), "summary": (c.get("summary", "") or "")[:100]}
                for c in receptionist_calls[:5]
            ],
        }

        if include_previous:
            prev_end_ts = f"{prev_end}T23:59:59"
            prev_calls = session.execute(
                text("""
                    SELECT id FROM calls
                    WHERE business_id = :business_id
                      AND started_at >= :prev_start
                      AND started_at <= :prev_end_ts
                """),
                {
                    "business_id": business_id,
                    "prev_start": prev_start.isoformat(),
                    "prev_end_ts": prev_end_ts,
                },
            ).fetchall()
            data["calls"]["previous_total"] = len(prev_calls)
    except Exception as e:
        logger.error(f"[Briefing Data] Failed to gather calls: {e}")
        data["calls"] = {"total": 0, "error": str(e)}

    # --- Emails (email_messages) ---
    try:
        emails_rows = session.execute(
            text("""
                SELECT id, ai_category, is_unread, received_at
                FROM email_messages
                WHERE business_id = :business_id
                  AND received_at >= :period_start
            """),
            {"business_id": business_id, "period_start": period_start.isoformat()},
        ).fetchall()

        emails = [
            {"id": str(r[0]), "ai_category": r[1], "is_read": not r[2] if r[2] is not None else True, "received_at": r[3]}
            for r in emails_rows
        ]

        data["emails"] = {
            "total_received": len(emails),
            "action_required": len([e for e in emails if e.get("ai_category") == "Action Required"]),
            "awaiting_reply": len([e for e in emails if e.get("ai_category") == "Awaiting Reply"]),
            "unread": len([e for e in emails if e.get("is_read") is False]),
            "fyi": len([e for e in emails if e.get("ai_category") == "FYI"]),
            "newsletters": len(
                [e for e in emails if e.get("ai_category") in ("Newsletter", "Marketing")]
            ),
        }
    except Exception as e:
        logger.error(f"[Briefing Data] Failed to gather emails: {e}")
        data["emails"] = {"total_received": 0, "error": str(e)}

    # --- Tasks ---
    try:
        tasks_rows = session.execute(
            text("""
                SELECT id, status, priority, category, created_at, updated_at
                FROM tasks
                WHERE business_id = :business_id
                  AND deleted_at IS NULL
            """),
            {"business_id": business_id},
        ).fetchall()

        all_tasks = [
            {
                "id": str(r[0]),
                "status": r[1],
                "priority": r[2],
                "category": r[3],
                "created_at": r[4].isoformat() if r[4] else None,
                "updated_at": r[5].isoformat() if r[5] else None,
            }
            for r in tasks_rows
        ]
        period_start_str = period_start.isoformat()
        period_tasks = [t for t in all_tasks if (t.get("created_at", "")[:10] or "") >= period_start_str]

        data["tasks"] = {
            "open_total": len([t for t in all_tasks if t.get("status") == "open"]),
            "open_high_priority": len(
                [t for t in all_tasks if t.get("status") == "open" and t.get("priority") == "high"]
            ),
            "pending": len([t for t in all_tasks if t.get("status") == "pending"]),
            "created_this_period": len(period_tasks),
            "completed_this_period": len(
                [
                    t
                    for t in all_tasks
                    if t.get("status") == "completed"
                    and (t.get("updated_at", "")[:10] or "") >= period_start_str
                ]
            ),
        }
    except Exception as e:
        logger.error(f"[Briefing Data] Failed to gather tasks: {e}")
        data["tasks"] = {"open_total": 0, "error": str(e)}

    # --- Invoices ---
    try:
        invoices_rows = session.execute(
            text("""
                SELECT id, status, total, amount_due, due_date, customer_name, chase_stage
                FROM invoices
                WHERE business_id = :business_id
            """),
            {"business_id": business_id},
        ).fetchall()

        invoices = [
            {
                "id": str(r[0]),
                "status": r[1],
                "total": float(r[2]) if r[2] else 0,
                "amount_due": float(r[3]) if r[3] is not None else float(r[2]) if r[2] else 0,
                "due_date": r[4].isoformat() if r[4] else None,
                "contact_name": r[5],
                "chase_stage": r[6],
            }
            for r in invoices_rows
        ]
        unpaid = [i for i in invoices if i.get("status") in ("unpaid", "authorised", "sent")]
        overdue = [
            i
            for i in unpaid
            if i.get("due_date") and date.fromisoformat(i["due_date"]) < today
        ]

        data["invoices"] = {
            "unpaid_count": len(unpaid),
            "unpaid_total": round(sum(float(i.get("amount_due", 0)) for i in unpaid), 2),
            "overdue_count": len(overdue),
            "overdue_total": round(sum(float(i.get("amount_due", 0)) for i in overdue), 2),
            "overdue_details": [
                {
                    "id": i["id"],
                    "contact": i.get("contact_name", "Unknown"),
                    "amount": float(i.get("amount_due", 0)),
                    "due_date": i.get("due_date"),
                    "chase_stage": i.get("chase_stage"),
                    "days_overdue": (
                        (today - date.fromisoformat(i["due_date"])).days
                        if i.get("due_date")
                        else 0
                    ),
                }
                for i in overdue[:10]
            ],
        }
    except Exception as e:
        logger.error(f"[Briefing Data] Failed to gather invoices: {e}")
        data["invoices"] = {"unpaid_count": 0, "error": str(e)}

    # --- Financial Summary (accounting_transactions) ---
    try:
        txns_rows = session.execute(
            text("""
                SELECT id, amount, type, transaction_date
                FROM accounting_transactions
                WHERE business_id = :business_id
                  AND is_archived = false
                  AND transaction_date >= :period_start
                  AND transaction_date <= :period_end
            """),
            {
                "business_id": business_id,
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
            },
        ).fetchall()

        transactions = [{"type": r[2], "amount": float(r[1]) if r[1] else 0} for r in txns_rows]
        income = sum(
            abs(t.get("amount", 0))
            for t in transactions
            if t.get("type") == "income" or t.get("amount", 0) > 0
        )
        expenses = sum(
            abs(t.get("amount", 0))
            for t in transactions
            if t.get("type") == "expense" or t.get("amount", 0) < 0
        )

        data["financial"] = {
            "revenue": round(income, 2),
            "expenses": round(expenses, 2),
            "net_profit": round(income - expenses, 2),
            "transaction_count": len(transactions),
        }

        try:
            conn_row = session.execute(
                text("""
                    SELECT provider, tenant_name
                    FROM accounting_connections
                    WHERE business_id = :business_id AND is_active = true
                    LIMIT 1
                """),
                {"business_id": business_id},
            ).fetchone()
            if conn_row:
                data["financial"]["accounting_connected"] = True
                data["financial"]["provider"] = conn_row[0]
            else:
                data["financial"]["accounting_connected"] = False
        except Exception:
            data["financial"]["accounting_connected"] = False

        if include_previous:
            prev_txns = session.execute(
                text("""
                    SELECT id, amount, type
                    FROM accounting_transactions
                    WHERE business_id = :business_id
                      AND is_archived = false
                      AND transaction_date >= :prev_start
                      AND transaction_date <= :prev_end
                """),
                {
                    "business_id": business_id,
                    "prev_start": prev_start.isoformat(),
                    "prev_end": prev_end.isoformat(),
                },
            ).fetchall()
            prev_data = [{"type": r[2], "amount": float(r[1]) if r[1] else 0} for r in prev_txns]
            prev_income = sum(
                abs(t.get("amount", 0))
                for t in prev_data
                if t.get("type") == "income" or t.get("amount", 0) > 0
            )
            prev_expenses = sum(
                abs(t.get("amount", 0))
                for t in prev_data
                if t.get("type") == "expense" or t.get("amount", 0) < 0
            )
            data["financial"]["previous_revenue"] = round(prev_income, 2)
            data["financial"]["previous_expenses"] = round(prev_expenses, 2)
            data["financial"]["previous_net_profit"] = round(
                prev_income - prev_expenses, 2
            )
    except Exception as e:
        logger.error(f"[Briefing Data] Failed to gather financials: {e}")
        data["financial"] = {"revenue": 0, "expenses": 0, "net_profit": 0, "error": str(e)}

    # --- Receptionist Knowledge Base Gaps ---
    try:
        week_ago = (now - timedelta(days=7)).isoformat()
        gap_rows = session.execute(
            text("""
                SELECT transcript
                FROM calls
                WHERE business_id = :business_id
                  AND source = 'receptionist'
                  AND started_at >= :week_ago
            """),
            {"business_id": business_id, "week_ago": week_ago},
        ).fetchall()

        gap_indicators = 0
        phrases = [
            "don't have that information",
            "i don't have specific details",
            "let me take your details",
            "someone from the team",
            "get back to you",
        ]
        for row in gap_rows:
            transcript = (row[0] or "").lower()
            if any(p in transcript for p in phrases):
                gap_indicators += 1
        data["receptionist_gaps"] = gap_indicators
    except Exception:
        data["receptionist_gaps"] = 0

    return data
