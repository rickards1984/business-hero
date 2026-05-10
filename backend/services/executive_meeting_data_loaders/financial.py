"""
Financial data loader: revenue/expenses/profit deltas + bank cash position.

Strategy:
- Pull a fresh active accounting_connections row to determine availability,
  data source label, and last-sync timestamp.
- Compute revenue/expenses/profit from accounting_transactions for BOTH the
  current and previous period (consistent transaction-based calculation
  for a clean period-over-period comparison).
- Read cash_position from the latest financial_summary_cache.bank_summary
  if present (only the cache holds bank-account totals).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlmodel import Session

from ._common import build_period_metric, empty_period_metric, iso_or_none

logger = logging.getLogger(__name__)

# Mirror briefing_data.py categorisation so we stay consistent with existing
# financial reporting elsewhere in the app.
_INCOME_TYPES = {
    "income", "RECEIVE", "receive", "ACCRECPAYMENT", "AROVERPAYMENT",
    "EXPPAYMENT", "credit", "Credit", "CREDIT",
}
_EXPENSE_TYPES = {
    "expense", "SPEND", "spend", "ACCPAYPAYMENT", "APOVERPAYMENT",
    "APCREDITPAYMENT", "debit", "Debit", "DEBIT",
}
_TRANSFER_TYPES = {"TRANSFER", "transfer", "Transfer"}


def _empty_section() -> Dict[str, Any]:
    return {
        "available": False,
        "data_source": None,
        "data_freshness": None,
        "errors": [],
        "revenue": empty_period_metric(),
        "expenses": empty_period_metric(),
        "profit": empty_period_metric(),
        "cash_position": {"available_balance": None, "as_of": None},
    }


def _sum_period(
    session: Session,
    business_id: str,
    period_start_iso: str,
    period_end_iso: str,
) -> tuple[float, float]:
    """Return (income, expenses) for a single period from accounting_transactions."""
    rows = session.execute(
        text(
            """
            SELECT amount, type
            FROM accounting_transactions
            WHERE business_id = :business_id
              AND is_archived = false
              AND transaction_date >= :start
              AND transaction_date <= :end
            """
        ),
        {
            "business_id": business_id,
            "start": period_start_iso,
            "end": period_end_iso,
        },
    ).fetchall()

    income = 0.0
    expenses = 0.0
    for r in rows:
        amt = float(r[0]) if r[0] is not None else 0.0
        ttype = (r[1] or "").strip()
        if ttype in _TRANSFER_TYPES:
            continue
        if ttype in _INCOME_TYPES:
            income += abs(amt)
        elif ttype in _EXPENSE_TYPES:
            expenses += abs(amt)
        elif amt > 0:
            income += abs(amt)
        elif amt < 0:
            expenses += abs(amt)

    return income, expenses


def _parse_bank_balance(bank_summary: Any) -> Optional[float]:
    """Parse the bank-account balance total from a Xero-style cached summary."""
    if not bank_summary:
        return None
    try:
        data = json.loads(bank_summary) if isinstance(bank_summary, str) else bank_summary
        accounts = (data or {}).get("Accounts", [])
        if not accounts:
            return None
        total = 0.0
        for a in accounts:
            v = a.get("Total")
            if v is None:
                continue
            try:
                total += float(v)
            except (TypeError, ValueError):
                continue
        return round(total, 2)
    except Exception:
        return None


def gather(
    business_id: str,
    period: Dict[str, Any],
    session: Session,
) -> Dict[str, Any]:
    """Gather financial section of the prep_data."""
    section = _empty_section()
    try:
        # Active accounting connection (drives availability + freshness label)
        conn_row = session.execute(
            text(
                """
                SELECT provider, last_sync_at
                FROM accounting_connections
                WHERE business_id = :business_id AND is_active = true
                ORDER BY last_sync_at DESC NULLS LAST
                LIMIT 1
                """
            ),
            {"business_id": business_id},
        ).fetchone()

        if not conn_row:
            section["errors"].append("No active accounting connection")
            return section

        section["available"] = True
        section["data_source"] = conn_row[0]
        section["data_freshness"] = iso_or_none(conn_row[1])

        # Period-over-period income/expenses from transactions
        cur_income, cur_expenses = _sum_period(
            session,
            business_id,
            period["current_start_iso"],
            period["current_end_iso"],
        )
        prev_income, prev_expenses = _sum_period(
            session,
            business_id,
            period["previous_start_iso"],
            period["previous_end_iso"],
        )

        section["revenue"] = build_period_metric(cur_income, prev_income)
        section["expenses"] = build_period_metric(cur_expenses, prev_expenses)
        section["profit"] = build_period_metric(
            cur_income - cur_expenses,
            prev_income - prev_expenses,
        )

        # Cash position from the cached bank summary (single most-recent row)
        cache_row = session.execute(
            text(
                """
                SELECT bank_summary, cached_at
                FROM financial_summary_cache
                WHERE business_id = :business_id
                ORDER BY cached_at DESC
                LIMIT 1
                """
            ),
            {"business_id": business_id},
        ).fetchone()

        if cache_row:
            balance = _parse_bank_balance(cache_row[0])
            section["cash_position"] = {
                "available_balance": balance,
                "as_of": iso_or_none(cache_row[1]),
            }

        return section
    except Exception as e:
        logger.exception("[Prep] financial loader failed")
        section["available"] = False
        section["errors"].append(str(e))
        return section
