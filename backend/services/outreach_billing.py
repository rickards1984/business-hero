"""OUT-19 F — Stripe for extra brands and top-ups (docs/OUT-19-TICKET.md, F).

Mike, 29 Oct 2026 ("Go with recommendations ... they also protect expenditure
vs income"):
  1. a new paid brand is added to the business's Stripe subscription as an
     item and charged pro-rata now (proration_behavior=always_invoice);
  2. it goes live only once Stripe confirms the payment
     (payment_behavior=pending_if_incomplete: the subscription's items change
     only when the invoice is paid, and the webhook then shows the quantity);
  3. top-ups of £10, £25 or £50 are an off-session charge to the saved card
     (3-D Secure: Stripe's hosted page), reserved against the owner's budget
     under the business lock BEFORE Stripe is called, credited only on
     payment_intent.succeeded, once;
  4. removing a paid brand stops billing at the end of the paid month.
Brands with no billing record (they existed when F went live) are
grandfathered and live. `outreach_brands_free` keeps every brand of a business
live without billing.

State lives in the business settings document (no migration):
  outreach_brand_billing = {"brands": {brand_id: {state, price, requested_at,
                            ends_at}}, "pending": {key: {amount, brand_id, at,
                            pi}}, "paid": [payment_intent ids]}
"""
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text

from services import outreach_send as send

BILLING_KEY = "outreach_brand_billing"
TOPUP_SIZES = (1000, 2500, 5000)
TOPUP_METER = "outreach_topup_pence"
PENDING_LIFE = timedelta(hours=24)       # a reservation whose payment never resolves stops counting
FREE_FLAG = "outreach_brands_free"
PRICE_ENV = {9900: "STRIPE_PRICE_OUTREACH_ADDON", 7900: "STRIPE_PRICE_EXTRA_BRAND"}


def refuse(status: int, detail: str):
    raise send.ActionRefused(status, detail)


# ------------------------------------------------------------------ state ---

def _doc(session, bid: str) -> dict:
    from services import outreach_setup as setup
    return setup._settings_doc(session, bid)


def _billing(doc: dict) -> dict:
    b = dict(doc.get(BILLING_KEY) or {})
    b["brands"] = dict(b.get("brands") or {})
    b["pending"] = dict(b.get("pending") or {})
    b["paid"] = list(b.get("paid") or [])
    return b


def _save(session, bid: str, billing: dict) -> None:
    from services import outreach_setup as setup
    doc = _doc(session, bid)
    doc[BILLING_KEY] = billing
    setup._save_settings_doc(session, bid, doc)


def _lock(session, bid: str) -> None:
    if not send.pg(session):
        session.execute(text("UPDATE business_settings SET business_id = business_id WHERE business_id = :b"), {"b": bid})
    send.lock_business(session, bid)


def _business_row(session, bid: str) -> dict:
    row = session.execute(text("SELECT * FROM businesses WHERE id = :b"), {"b": bid}).mappings().first()
    return dict(row) if row else {}


def _flags(row: dict) -> dict:
    flags = row.get("feature_flags")
    if isinstance(flags, str):
        try:
            flags = json.loads(flags or "{}")
        except ValueError:
            flags = {}
    return flags if isinstance(flags, dict) else {}


def free(session, bid: str) -> bool:
    return _flags(_business_row(session, bid)).get(FREE_FLAG) is True


def _parse(value) -> Optional[datetime]:
    from services.chase_replies import _parse as parse
    return parse(value)


def brand_live(session, bid: str, brand_id, moment: Optional[datetime] = None) -> bool:
    """Whether a brand may research and send cold email now."""
    from services import outreach_allowance
    moment = moment or send.now()
    bid = str(bid)
    if free(session, bid):
        return True
    price, included = outreach_allowance.prices(session, bid).get(str(brand_id), (0, False))
    if included:
        return True
    entry = _billing(_doc(session, bid))["brands"].get(str(brand_id))
    if entry is None:
        return True                       # grandfathered: existed before F went live
    if entry.get("state") == "active":
        return True
    if entry.get("state") == "ending":
        ends = _parse(entry.get("ends_at"))
        return ends is not None and moment < ends
    return False


def charged_brand_pence(session, bid: str) -> int:
    """What paid brands charge each month: every paid brand except those still
    awaiting payment; nothing for a free business."""
    from services import outreach_allowance
    if free(session, bid):
        return 0
    brands = _billing(_doc(session, bid))["brands"]
    return sum(price for brand_id, (price, included) in outreach_allowance.prices(session, bid).items()
               if not included and (brands.get(brand_id) or {}).get("state") != "awaiting_payment")


def pending_topup_pence(session, bid: str, moment: Optional[datetime] = None) -> int:
    moment = moment or send.now()
    total = 0
    for entry in _billing(_doc(session, bid))["pending"].values():
        at = _parse(entry.get("at"))
        if at is not None and moment - at < PENDING_LIFE:
            total += int(entry.get("amount") or 0)
    return total


def status(session, business) -> dict:
    from services import outreach_allowance
    bid = str(business.id)
    moment = send.now()
    billing = _billing(_doc(session, bid))
    is_free = free(session, bid)
    rows = []
    for brand_id, (price, included) in outreach_allowance.prices(session, bid).items():
        entry = billing["brands"].get(brand_id)
        state = ("free" if is_free else "included" if included else
                 "grandfathered" if entry is None else entry.get("state"))
        rows.append({"brand_id": brand_id, "billing": state, "price_pence": 0 if (is_free or included) else price,
                     "live": brand_live(session, bid, brand_id, moment),
                     "ends_at": (entry or {}).get("ends_at")})
    session.rollback()
    return {"brands": rows, "topup_sizes": list(TOPUP_SIZES)}


def mark_new_brand(session, bid: str, brand_id) -> None:
    """Called when a brand is created (after F): a brand that costs money waits
    for payment. In the caller's transaction."""
    from services import outreach_allowance
    if free(session, bid):
        return
    price, included = outreach_allowance.prices(session, bid).get(str(brand_id), (0, False))
    if included or not price:
        return
    if not os.environ.get(PRICE_ENV.get(int(price), ""), "").strip():
        return   # billing for brands starts once Mike has set the Stripe prices; until then nothing changes
    billing = _billing(_doc(session, bid))
    billing["brands"].setdefault(str(brand_id), {"state": "awaiting_payment", "price": price})
    _save(session, bid, billing)


# ------------------------------------------------------------------ stripe ---

def _stripe():
    import stripe
    from app.billing.config import get_stripe_config
    key = get_stripe_config().get("stripe_secret_key")
    if not key:
        refuse(503, "Payments aren't set up yet.")
    stripe.api_key = key
    return stripe


def _price_id(price_pence: int) -> str:
    name = PRICE_ENV.get(int(price_pence))
    value = os.environ.get(name or "", "").strip()
    if not value:
        refuse(503, "Paid brands aren't set up for billing yet. Please try again later.")
    return value


def _get(obj, key, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _items(subscription) -> list:
    return list(_get(_get(subscription, "items"), "data") or [])


def _item_price(item) -> Optional[str]:
    price = _get(item, "price")
    return price if isinstance(price, str) else _get(price, "id")


def _owner(session, business, user) -> None:
    from services import outreach_setup as setup
    setup._authority(session, business, user, growth=False)   # active owner, current entitlement, under lock


# -------------------------------------------------------- adding / removing ---

def add_paid_brand(session, business, user, brand_id, *, api=None) -> dict:
    """Charge a brand pro-rata now; it goes live when Stripe confirms payment."""
    from services import outreach_allowance
    bid = str(business.id)
    _owner(session, business, user)
    send.one(session, "outreach_brands", bid, brand_id)
    if free(session, bid):
        refuse(409, "This business's brands are free: there's nothing to pay.")
    billing = _billing(_doc(session, bid))
    entry = billing["brands"].get(str(brand_id))
    if not entry or entry.get("state") != "awaiting_payment":
        refuse(409, "This brand isn't waiting for payment.")
    price = int(entry.get("price") or 0)
    price_id = _price_id(price)
    row = _business_row(session, bid)
    if not row.get("stripe_subscription_id"):
        refuse(409, "Subscribe to a Business Hero plan first, then add paid brands to it.")
    if not outreach_allowance.can_charge(session, business, price):
        refuse(409, f"Adding this brand (£{price / 100:.2f} a month) would go beyond your monthly outreach budget. "
                    "Raise the budget first.")
    requested = send.now().isoformat()
    entry.update(state="pending", requested_at=requested)
    _save(session, bid, billing)
    session.commit()                       # reserved (counts as committed) before Stripe is called
    api = api or _stripe()
    try:
        sub = api.Subscription.retrieve(row["stripe_subscription_id"])
        existing = next((i for i in _items(sub) if _item_price(i) == price_id), None)
        item = ({"id": _get(existing, "id"), "quantity": int(_get(existing, "quantity") or 0) + 1} if existing
                else {"price": price_id, "quantity": 1})
        api.Subscription.modify(row["stripe_subscription_id"], items=[item], proration_behavior="always_invoice",
                                payment_behavior="pending_if_incomplete",
                                idempotency_key=f"outreach-brand-{brand_id}-{requested}")
    except send.ActionRefused:
        raise
    except Exception:
        _lock(session, bid)
        billing = _billing(_doc(session, bid))
        if (billing["brands"].get(str(brand_id)) or {}).get("requested_at") == requested:
            billing["brands"][str(brand_id)].update(state="awaiting_payment")
            billing["brands"][str(brand_id)].pop("requested_at", None)
            _save(session, bid, billing)
        session.commit()
        refuse(502, "Stripe couldn't add this brand just now; nothing was charged. Please try again.")
    return {"brand_id": str(brand_id), "billing": "pending"}


def remove_paid_brand(session, business, user, brand_id, *, api=None) -> dict:
    """Stop billing at the end of the month already paid; live until then."""
    bid = str(business.id)
    _owner(session, business, user)
    billing = _billing(_doc(session, bid))
    entry = billing["brands"].get(str(brand_id))
    if not entry or entry.get("state") != "active":
        refuse(409, "Only a paid, live brand can be removed from billing.")
    price_id = _price_id(int(entry.get("price") or 0))
    row = _business_row(session, bid)
    session.rollback()                     # no lock while Stripe is called
    api = api or _stripe()
    try:
        sub = api.Subscription.retrieve(row["stripe_subscription_id"])
        existing = next((i for i in _items(sub) if _item_price(i) == price_id), None)
        if existing is None:
            refuse(409, "Stripe has no paid line for this brand.")
        quantity = int(_get(existing, "quantity") or 0) - 1
        item = {"id": _get(existing, "id"), "deleted": True} if quantity <= 0 else {"id": _get(existing, "id"),
                                                                                     "quantity": quantity}
        ends = _get(existing, "current_period_end") or _get(sub, "current_period_end")
        api.Subscription.modify(row["stripe_subscription_id"], items=[item], proration_behavior="none",
                                idempotency_key=f"outreach-brand-remove-{brand_id}-{entry.get('requested_at')}")
    except send.ActionRefused:
        raise
    except Exception:
        refuse(502, "Stripe couldn't remove this brand just now; nothing changed. Please try again.")
    ends_at = datetime.fromtimestamp(int(ends), tz=timezone.utc).isoformat() if ends else send.now().isoformat()
    _lock(session, bid)
    billing = _billing(_doc(session, bid))
    billing["brands"].setdefault(str(brand_id), entry).update(state="ending", ends_at=ends_at)
    _save(session, bid, billing)
    session.commit()
    return {"brand_id": str(brand_id), "billing": "ending", "ends_at": ends_at}


def _business_for(session, subscription) -> Optional[str]:
    sub_id, customer = _get(subscription, "id"), _get(subscription, "customer")
    for column, value in (("stripe_subscription_id", sub_id), ("stripe_customer_id", customer)):
        if not value:
            continue
        try:
            found = session.execute(text(f"SELECT id FROM businesses WHERE {column} = :v"), {"v": value}).first()
        except Exception:
            return None
        if found:
            return str(found[0])
    return None


def apply_subscription(session, subscription) -> None:
    """From the webhook, in its transaction: the paid quantity of each outreach
    price goes, oldest first, to the brands waiting on it."""
    bid = _business_for(session, subscription)
    if bid is None:
        return
    prices = {name: os.environ.get(env, "").strip() for name, env in PRICE_ENV.items()}
    quantities, period_end = {}, None
    for item in _items(subscription):
        for amount, price_id in prices.items():
            if price_id and _item_price(item) == price_id:
                quantities[amount] = quantities.get(amount, 0) + int(_get(item, "quantity") or 0)
                period_end = period_end or _get(item, "current_period_end")
    _lock(session, bid)
    billing = _billing(_doc(session, bid))
    from services import outreach_allowance
    age = {brand_id: n for n, brand_id in enumerate(outreach_allowance.prices(session, bid))}   # oldest brand first
    changed = False
    for amount in prices:
        waiting = sorted(((brand_id, entry) for brand_id, entry in billing["brands"].items()
                          if int(entry.get("price") or 0) == amount and entry.get("state") in ("pending", "active")),
                         key=lambda pair: (pair[1].get("requested_at") or "", age.get(pair[0], 1 << 30), pair[0]))
        paid = quantities.get(amount, 0)
        for position, (brand_id, entry) in enumerate(waiting):
            state = "active" if position < paid else "pending"
            if entry.get("state") != state:
                entry["state"] = state
                changed = True
    if changed:
        _save(session, bid, billing)


# ------------------------------------------------------------------ top-ups ---

def _release(billing: dict, key: Optional[str] = None, pi: Optional[str] = None) -> bool:
    gone = [k for k, entry in billing["pending"].items() if k == key or (pi and entry.get("pi") == pi)]
    for k in gone:
        billing["pending"].pop(k, None)
    return bool(gone)


def start_topup(session, business, user, brand_id, amount_pence, *, api=None, return_url: str) -> dict:
    """£10, £25 or £50 on the saved card; reserved against the budget first."""
    from services import outreach_allowance
    if amount_pence not in TOPUP_SIZES:
        refuse(422, "A top-up is £10, £25 or £50.")
    bid = str(business.id)
    _owner(session, business, user)        # holds the business lock from here
    send.one(session, "outreach_brands", bid, brand_id)
    if not brand_live(session, bid, brand_id):
        refuse(409, "Top-ups are for brands that are live. Pay for this brand first.")
    row = _business_row(session, bid)
    if not row.get("stripe_customer_id") or not row.get("stripe_subscription_id"):
        refuse(409, "Subscribe to a Business Hero plan first.")
    if not outreach_allowance.can_charge(session, business, amount_pence):
        refuse(409, f"A £{amount_pence / 100:.0f} top-up would go beyond your monthly outreach budget. "
                    "Raise the budget first.")
    key = uuid.uuid4().hex
    billing = _billing(_doc(session, bid))
    billing["pending"][key] = {"amount": amount_pence, "brand_id": str(brand_id), "at": send.now().isoformat()}
    _save(session, bid, billing)
    session.commit()                       # reserved before Stripe is called
    api = api or _stripe()
    metadata = {"kind": "outreach_topup", "business_id": bid, "brand_id": str(brand_id)}

    def settle(pi: Optional[str] = None, release: bool = False) -> None:
        _lock(session, bid)
        current = _billing(_doc(session, bid))
        if release:
            _release(current, key=key)
        elif pi and key in current["pending"]:
            current["pending"][key]["pi"] = pi
        _save(session, bid, current)
        session.commit()

    card_error = getattr(getattr(api, "error", None), "CardError", None) or getattr(api, "CardError", Exception)
    try:
        sub = api.Subscription.retrieve(row["stripe_subscription_id"])
        method = _get(sub, "default_payment_method")
        method = method if isinstance(method, str) or method is None else _get(method, "id")
        if not method:
            settle(release=True)
            refuse(409, "There's no saved card on your subscription. Add one in Billing, then try again.")
        intent = api.PaymentIntent.create(amount=amount_pence, currency="gbp", customer=row["stripe_customer_id"],
                                          payment_method=method, off_session=True, confirm=True,
                                          description="Business Hero outreach top-up", metadata=metadata,
                                          idempotency_key=f"outreach-topup-{key}")
    except send.ActionRefused:
        raise
    except card_error as exc:
        code = getattr(exc, "code", None) or _get(getattr(exc, "error", None), "code")
        if code == "authentication_required":
            failed_pi = _get(_get(getattr(exc, "error", None), "payment_intent"), "id")
            settle(pi=failed_pi)
            checkout = api.checkout.Session.create(
                mode="payment", customer=row["stripe_customer_id"],
                line_items=[{"quantity": 1, "price_data": {"currency": "gbp", "unit_amount": amount_pence,
                                                          "product_data": {"name": "Outreach top-up"}}}],
                payment_intent_data={"metadata": metadata},
                success_url=return_url, cancel_url=return_url, idempotency_key=f"outreach-topup-checkout-{key}")
            return {"status": "needs_authentication", "checkout_url": _get(checkout, "url")}
        settle(release=True)
        refuse(402, "Your card was declined, so nothing was charged. Update your card in Billing and try again.")
    except Exception:
        settle(release=True)
        refuse(502, "Stripe couldn't take the payment just now; nothing was charged. Please try again.")
    settle(pi=_get(intent, "id"))
    return {"status": "processing"}


def apply_payment_intent(session, event_type: str, intent, *, created: Optional[datetime] = None) -> None:
    """From the webhook, in its transaction: a confirmed outreach top-up is
    credited once; a failed one releases its reservation."""
    metadata = _get(intent, "metadata") or {}
    if _get(metadata, "kind") != "outreach_topup":
        return
    bid, brand_id, pi = _get(metadata, "business_id"), _get(metadata, "brand_id"), _get(intent, "id")
    if not bid or not brand_id or not pi:
        return
    try:
        found = send.rows(session, "outreach_brands", bid, "AND id = :i", {"i": str(brand_id)})
    except Exception:
        return
    if not found:
        return                              # not a brand of that business: ignored
    _lock(session, bid)
    billing = _billing(_doc(session, bid))
    if event_type == "payment_intent.payment_failed":
        if _release(billing, pi=pi):
            _save(session, bid, billing)
        return
    if event_type != "payment_intent.succeeded" or pi in billing["paid"]:
        return
    amount = int(_get(intent, "amount_received") or _get(intent, "amount") or 0)
    moment = created or send.now()
    from services import outreach_research
    outreach_research._add_meter(session, bid, f"{TOPUP_METER}:{brand_id}", moment, amount)
    billing["paid"].append(pi)
    billing["paid"] = billing["paid"][-500:]
    _release(billing, pi=pi)
    # A hosted-page payment arrives under a new payment: release the oldest
    # matching reservation for this brand and amount too.
    for key, entry in sorted(billing["pending"].items(), key=lambda kv: kv[1].get("at") or ""):
        if entry.get("brand_id") == str(brand_id) and int(entry.get("amount") or 0) == amount:
            billing["pending"].pop(key)
            break
    _save(session, bid, billing)
