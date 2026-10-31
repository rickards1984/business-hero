"""PROFIT-2 — income from real Stripe amounts (docs/PROFIT-2-TICKET.md). RED.

Mike, 31 Oct 2026: a business's income is its REAL monthly charge, the net
amount (after discounts, before VAT) of its last full monthly Stripe invoice.
A proration (a brand added mid-month) is cash received, never next month's
charge. Cash received is recorded per UK month but never drives the alarm.
(A full monthly invoice can itself carry adjustments; the approved rule takes
its net amount as the charge. Refunds and credit notes aren't reconciled yet:
backlog.)

Recorded per business in usage_meters (no migration):
  stripe_paid_pence       cash received in the month
  stripe_recurring_pence  the month's full monthly charge (latest paid wins)
  stripe_recurring_at     when that charge was paid (epoch seconds)
  stripe_invoice:<id>     1 — this invoice is recorded (counted once, ever)
Read only from Stripe: nothing here writes to Stripe.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)

PAID, RECURRING, RECURRING_AT, SEEN = ("stripe_paid_pence", "stripe_recurring_pence", "stripe_recurring_at",
                                       "stripe_invoice:")
FULL_MONTH = ("subscription_cycle", "subscription_create")
REFRESH_LIMIT = 24


def _get(obj, key, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _period(moment: datetime) -> str:
    from services.metering import period_for
    return period_for(moment)


def _subscription_of(invoice) -> Optional[str]:
    """The invoice's subscription: `parent.subscription_details.subscription`
    on current Stripe API versions, `subscription` on older ones (Codex
    review 1)."""
    current = _get(_get(_get(invoice, "parent"), "subscription_details"), "subscription")
    value = current or _get(invoice, "subscription")
    return value if isinstance(value, str) or value is None else _get(value, "id")


def _business_for(session, customer, subscription) -> Optional[str]:
    """By subscription first; by customer only when exactly one business has
    it (a shared customer is ambiguous: never guessed)."""
    if subscription:
        found = session.execute(text("SELECT id FROM businesses WHERE stripe_subscription_id = :v"),
                                {"v": subscription}).all()
        if len(found) == 1:
            return str(found[0][0])
    if customer:
        found = session.execute(text("SELECT id FROM businesses WHERE stripe_customer_id = :v"), {"v": customer}).all()
        if len(found) == 1:
            return str(found[0][0])
        if len(found) > 1:
            logger.warning("Stripe income: customer %s belongs to %d businesses; invoice not attributed",
                           customer, len(found))
    return None


def _add(session, bid: str, meter: str, period: str, value: float, at: datetime) -> None:
    params = {"b": bid, "m": meter, "p": period, "v": value, "at": at.isoformat()}
    if not session.execute(text("UPDATE usage_meters SET value = value + :v, updated_at = :at "
                                "WHERE business_id = :b AND meter = :m AND period = :p"), params).rowcount:
        session.execute(text("INSERT INTO usage_meters (business_id, meter, period, value, updated_at) "
                             "VALUES (:b, :m, :p, :v, :at)"), params)


def _set(session, bid: str, meter: str, period: str, value: float, at: datetime) -> None:
    params = {"b": bid, "m": meter, "p": period, "v": value, "at": at.isoformat()}
    if not session.execute(text("UPDATE usage_meters SET value = :v, updated_at = :at "
                                "WHERE business_id = :b AND meter = :m AND period = :p"), params).rowcount:
        session.execute(text("INSERT INTO usage_meters (business_id, meter, period, value, updated_at) "
                             "VALUES (:b, :m, :p, :v, :at)"), params)


def _claim(session, bid: str, meter: str, period: str, at: datetime) -> bool:
    """Claim an invoice atomically: the marker row is INSERTED before anything
    is counted. usage_meters is unique on (business, meter, period) and an
    invoice's period never changes, so a concurrent second claim waits, then
    fails, and counts nothing (Codex review 1)."""
    from sqlalchemy.exc import IntegrityError
    if session.execute(text("SELECT 1 FROM usage_meters WHERE business_id = :b AND meter = :m"),
                       {"b": bid, "m": meter}).first():
        return False
    from services import outreach_send as send
    insert = text("INSERT INTO usage_meters (business_id, meter, period, value, updated_at) VALUES (:b, :m, :p, 1, :at)")
    params = {"b": bid, "m": meter, "p": period, "at": at.isoformat()}
    if not send.pg(session):
        # SQLite (tests) has one writer, and a savepoint there can start
        # outside the outer transaction and outlive its rollback (Codex
        # review 2): a plain insert in the caller's transaction instead.
        session.execute(insert, params)
        return True
    try:
        with session.begin_nested():   # PostgreSQL: a concurrent claim waits, then fails here
            session.execute(insert, params)
    except IntegrityError:
        return False
    return True


def _value(session, bid: str, meter: str, period: str) -> Optional[float]:
    found = session.execute(text("SELECT value FROM usage_meters WHERE business_id = :b AND meter = :m AND period = :p"),
                            {"b": bid, "m": meter, "p": period}).scalar()
    return float(found) if found is not None else None


def _tax(invoice) -> int:
    tax = _get(invoice, "tax")
    if tax is not None:
        return int(tax or 0)
    return sum(int(_get(t, "amount") or 0) for t in (_get(invoice, "total_taxes") or _get(invoice, "total_tax_amounts") or []))


def _paid_at(invoice) -> datetime:
    stamp = _get(_get(invoice, "status_transitions"), "paid_at") or _get(invoice, "created")
    return datetime.fromtimestamp(int(stamp), tz=timezone.utc) if stamp else datetime.now(timezone.utc)


def record_invoice(session, invoice) -> bool:
    """Record one paid invoice, once. In the caller's transaction. True when it
    was recorded now; False when it was already, or isn't a business's, or
    isn't in pounds."""
    ident = _get(invoice, "id")
    if not ident or _get(invoice, "status") not in (None, "paid"):
        return False
    if (_get(invoice, "currency") or "").lower() != "gbp":
        logger.warning("Stripe income: invoice %s is not in pounds; not counted", ident)
        return False
    bid = _business_for(session, _get(invoice, "customer"), _subscription_of(invoice))
    if bid is None:
        return False
    net = max(0, int(_get(invoice, "amount_paid") or 0) - _tax(invoice))
    paid_at = _paid_at(invoice)
    period = _period(paid_at)
    if not _claim(session, bid, SEEN + str(ident), period, paid_at):
        return False                      # recorded already (or by a concurrent transaction)
    _add(session, bid, PAID, period, net, paid_at)
    if _get(invoice, "billing_reason") in FULL_MONTH:
        latest = _value(session, bid, RECURRING_AT, period)
        if latest is None or paid_at.timestamp() >= latest:      # an older invoice arriving late never wins
            _set(session, bid, RECURRING, period, net, paid_at)
            _set(session, bid, RECURRING_AT, period, paid_at.timestamp(), paid_at)
    return True


def recurring_all(session, period: str) -> dict:
    """{business_id: its monthly charge as of `period`}: each business's
    latest recorded full monthly invoice up to that month, in one query."""
    out = {}
    for bid, value in session.execute(text(
            "SELECT business_id, value FROM usage_meters WHERE meter = :m AND period <= :p ORDER BY period"),
            {"m": RECURRING, "p": period}):
        out[str(bid)] = int(value or 0)                          # later months overwrite earlier ones
    return out


def recurring_pence(session, bid: str, period: str) -> Optional[int]:
    return recurring_all(session, period).get(str(bid))


def cash_pence(session, period: str, bid: Optional[str] = None) -> int:
    sql = "SELECT coalesce(sum(value), 0) FROM usage_meters WHERE meter = :m AND period = :p"
    params = {"m": PAID, "p": period}
    if bid is not None:
        sql, params["b"] = sql + " AND business_id = :b", str(bid)
    return int(session.execute(text(sql), params).scalar() or 0)


def webhook(session, event_type: str, data) -> None:
    """From the Stripe webhook, in its transaction."""
    if event_type == "invoice.paid":
        record_invoice(session, data)


def _stripe():
    import stripe
    from app.billing.config import get_stripe_config
    key = get_stripe_config().get("stripe_secret_key")
    if not key:
        raise RuntimeError("Stripe isn't set up")
    stripe.api_key = key
    return stripe


def refresh(session, *, api=None) -> dict:
    """Read each business's paid invoices from Stripe and record any not yet
    recorded. Read only; safe to run any number of times. The caller commits."""
    api = api or _stripe()
    recorded, businesses = 0, 0
    for (customer,) in session.execute(text(
            "SELECT DISTINCT stripe_customer_id FROM businesses WHERE stripe_customer_id IS NOT NULL "
            "AND stripe_customer_id <> ''")).all():
        businesses += 1
        found = api.Invoice.list(customer=customer, status="paid", limit=REFRESH_LIMIT)
        for invoice in sorted(_get(found, "data") or [], key=lambda i: _paid_at(i).timestamp()):
            recorded += 1 if record_invoice(session, invoice) else 0
    return {"customers": businesses, "recorded": recorded}
