"""The Aria home's figures, computed once on the server — NS-B7 (Codex
review 1, findings 1, 2, 5, 6).

The home page used to add up the first 50 invoices in the browser, from the
gross amount, and count "action required" emails in the latest 200. So it
could say "none overdue" when one was, ignore part-payments, and miss older
emails. These figures are computed here, over ALL of the business's rows,
and Aria's invoice summary tool uses the same receivables function, so the
home and Aria can never disagree (North Star P2).
"""

from datetime import date, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import text

# Statuses that are not money owed, whatever the balance column says.
_NOT_OWED = ("paid", "draft", "void", "voided", "deleted", "cancelled")
EMAIL_ACTION_WINDOW_DAYS = 14

# What is still owed on an invoice — one authority per kind of row, matched
# to how each is written (Codex NS-B7 reviews 2 and 3):
# * Synced from accounts software (external_id set): the provider's own
#   balance, amount_due, is the ledger; failing that, amount less the
#   provider's amount_paid. A payment ticked in the app (paid_amount) does not
#   override it — the next sync is the truth (a local "paid" status still
#   removes the row via the status filter until then).
# * Local (manual, CSV, from a quote): amount less what was recorded as paid
#   in the app. Here amount_due is only ever the full amount at creation (and
#   a CSV update can leave it stale), so it is not used.
# Never below zero: the outer query counts only balances above zero.
_LOCAL_PAID = """CASE WHEN COALESCE(amount_paid, 0) > COALESCE(paid_amount, 0)
                      THEN COALESCE(amount_paid, 0) ELSE COALESCE(paid_amount, 0) END"""
_BALANCE = f"""
    CASE
      WHEN external_id IS NOT NULL THEN COALESCE(amount_due, amount - COALESCE(amount_paid, 0))
      ELSE amount - {_LOCAL_PAID}
    END
"""


def uk_today(now: Optional[datetime] = None) -> date:
    """The UK calendar day — the one invoices are dated in. Used by the home
    AND Aria's invoice summary, so "overdue" means the same in both."""
    now = now or datetime.now(timezone.utc)
    return now.astimezone(ZoneInfo("Europe/London")).date()


def receivables(conn, business_id: str, today: date) -> dict:
    """Outstanding and overdue balances over every invoice of this business."""
    not_owed = ", ".join(f"'{s}'" for s in _NOT_OWED)
    row = conn.execute(text(f"""
        SELECT
          COALESCE(SUM(CASE WHEN bal > 0 THEN bal ELSE 0 END), 0),
          COALESCE(SUM(CASE WHEN bal > 0 THEN 1 ELSE 0 END), 0),
          COALESCE(SUM(CASE WHEN bal > 0 AND due_date < :today THEN bal ELSE 0 END), 0),
          COALESCE(SUM(CASE WHEN bal > 0 AND due_date < :today THEN 1 ELSE 0 END), 0)
        FROM (
          SELECT {_BALANCE} AS bal, due_date
          FROM invoices
          WHERE business_id = :business_id
            AND (archived IS NULL OR archived = false)
            AND LOWER(status) NOT IN ({not_owed})
        ) owed
    """), {"business_id": str(business_id), "today": today}).fetchone()
    return {
        "outstanding_total": round(float(row[0] or 0), 2),
        "outstanding_count": int(row[1] or 0),
        "overdue_total": round(float(row[2] or 0), 2),
        "overdue_count": int(row[3] or 0),
    }


def _iso(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:  # these sync columns are stored without a zone, in UTC
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def summary(conn, business_id: str, now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    today = uk_today(now)
    bid = str(business_id)
    since = now - timedelta(days=EMAIL_ACTION_WINDOW_DAYS)
    action_required = conn.execute(text("""
        SELECT COUNT(*) FROM email_messages
        WHERE business_id = :business_id AND ai_category = 'Action Required'
          AND received_at >= :since
    """), {"business_id": bid, "since": since}).scalar()
    email_synced = conn.execute(text("""
        SELECT MAX(s.last_synced_at) FROM email_sync_states s
        JOIN email_accounts a ON a.id = s.email_account_id
        WHERE a.business_id = :business_id
    """), {"business_id": bid}).scalar()
    xero_synced = conn.execute(text(
        "SELECT MAX(last_sync_at) FROM xero_connections WHERE business_id = :business_id"),
        {"business_id": bid}).scalar()
    other_synced = conn.execute(text(
        "SELECT MAX(last_sync_at) FROM accounting_connections WHERE business_id = :business_id"),
        {"business_id": bid}).scalar()
    accounting = [v for v in (_iso(xero_synced), _iso(other_synced)) if v]
    return {
        "as_of": now.astimezone(timezone.utc).isoformat(),
        "invoices": receivables(conn, bid, today),
        "emails": {"action_required": int(action_required or 0),
                   "window_days": EMAIL_ACTION_WINDOW_DAYS},
        "synced": {
            "email": _iso(email_synced),
            "accounting": max(accounting) if accounting else None,
        },
    }
