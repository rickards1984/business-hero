"""Reading OUR plan out of a Stripe subscription: which item carries the plan,
which plan a price is, and when the paid period ends.

Shared by the webhook (main.py) and the daily reconciliation, so the check
reads Stripe exactly as the writer does. It lives here, not in main.py,
because the reconciliation runs in a scheduler thread and must not import the
web application: the server process need not be the module named `main`, and
production failed with "cannot import name '_plan_item' from 'main'"."""
import logging
from datetime import datetime, timezone
from typing import Optional

from app.billing.config import get_stripe_config

logger = logging.getLogger(__name__)


def resolve_current_period_end(event_data: dict) -> Optional[datetime]:
    """Where Stripe actually puts `current_period_end`.

    Current API versions carry it on the subscription ITEM
    (`items.data[0].current_period_end`); older ones carry it on the
    subscription object. Returns None when NEITHER has it, which the caller
    must treat as "leave the stored value alone" — not as "set it to null".
    Reading only the subscription level is BH-006 defect 3, and it wiped the
    stored period on every event.
    """
    candidates = [plan_item(event_data) or {}, event_data]
    for source in candidates:
        raw = (source or {}).get("current_period_end")
        parsed = epoch_to_utc(raw)
        if parsed is not None:
            return parsed
    return None


def epoch_to_utc(raw) -> Optional[datetime]:
    """A Stripe epoch second -> an aware UTC datetime, or None.

    Three corrections from Codex's review of the first version:

      * `datetime.fromtimestamp(x)` with no tzinfo returns NAIVE LOCAL time.
        Under Europe/London, 1782864000 became 2026-07-01 01:00:00 instead of
        00:00 UTC — an hour out for half the year, silently. The test missed it
        because it round-tripped through `.timestamp()`, which re-applies the
        same local offset.
      * `True` is an int in Python, so `int(True)` is 1 and a boolean became
        1970-01-01. Booleans are rejected explicitly.
      * A float was truncated by `int()`. Only whole numbers are accepted.
    """
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, float) and not raw.is_integer():
        logger.warning("non-integral current_period_end from Stripe: %r", raw)
        return None
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw.lstrip("-").isdigit():
            logger.warning("non-numeric current_period_end from Stripe: %r", raw)
            return None
    try:
        seconds = int(raw)
    except (TypeError, ValueError):
        logger.warning("unparseable current_period_end from Stripe: %r", raw)
        return None
    if seconds <= 0:
        return None
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (OSError, OverflowError, ValueError):
        logger.warning("out-of-range current_period_end from Stripe: %r", raw)
        return None


def plan_item(subscription: dict) -> Optional[dict]:
    """The subscription item that carries OUR plan's price.

    NOT `items.data[0]`. Codex's review: a subscription can hold several items
    and the plan need not be the first — a metered add-on could be. This picks
    the item whose price maps to a known plan and falls back to the first item
    only when none does, so behaviour on today's single-item subscriptions is
    unchanged while a multi-item one stops being read off the wrong row.
    """
    items = (subscription.get("items") or {}).get("data") or []
    for item in items:
        price_id = ((item or {}).get("price") or {}).get("id")
        if resolve_plan_from_price(price_id):
            return item
    return items[0] if items else None


def resolve_plan_from_price(price_id: str) -> Optional[str]:
    if not price_id:
        return None
    config = get_stripe_config()
    prices = config.get("prices", {})
    if price_id == prices.get("starter"):
        return "starter"
    if price_id == prices.get("pro"):
        return "pro"
    if price_id == prices.get("business"):
        return "business"
    return None
