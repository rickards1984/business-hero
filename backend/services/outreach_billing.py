"""OUT-19 F — Stripe for extra brands and top-ups (docs/OUT-19-TICKET.md, F).

Mike, 29 Oct 2026 ("Go with recommendations ... they also protect expenditure
vs income"):
  1. a new paid brand is added to the business's Stripe subscription and
     charged pro-rata now (proration_behavior=always_invoice);
  2. it goes live only once Stripe confirms the payment
     (payment_behavior=pending_if_incomplete);
  3. top-ups of £10, £25 or £50 are an off-session charge to the saved card
     (3-D Secure: Stripe's hosted page), reserved against the owner's budget
     under the business lock BEFORE Stripe is called, credited only when
     Stripe confirms, once;
  4. removing a paid brand stops billing at the end of the paid month.

Two principles, after Codex's review 1:
  * DURABLE OPERATIONS. Every brand change and every top-up has an identity
    saved before Stripe is called and reused as Stripe's idempotency key. An
    outcome Stripe didn't confirm is kept ("uncertain") and checked later,
    never assumed to have failed: a retry can never charge twice.
  * STRIPE IS THE TRUTH. Brand state is reconciled against the subscription
    as Stripe has it NOW (fetched, never read off an event that may be old),
    on each webhook and on a scheduled check; the subscription's outreach
    quantities are set to the number of brands the business is paying for
    (absolute, not +1/-1), one operation at a time per business.

Brands with no billing record (they existed when F went live) are
grandfathered and live. Billing switches on only once both Stripe prices are
set. `outreach_brands_free` keeps a business's brands live without billing.

State lives in the business settings document (no migration):
  outreach_brand_billing = {"brands": {...}, "purchases": {...}, "op": {...}}
"""
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text

from services import outreach_send as send

logger = logging.getLogger(__name__)

BILLING_KEY = "outreach_brand_billing"
TOPUP_SIZES = (1000, 2500, 5000)
TOPUP_METER = "outreach_topup_pence"
CREDITED_METER = "outreach_topup_credited"      # one durable row per credited payment
FREE_FLAG = "outreach_brands_free"
PRICE_ENV = {9900: "STRIPE_PRICE_OUTREACH_ADDON", 7900: "STRIPE_PRICE_EXTRA_BRAND"}
OP_LIFE = timedelta(minutes=10)                 # a subscription operation's claim
STALE = timedelta(hours=1)                      # an unconfirmed brand or top-up is checked with Stripe after this


def refuse(status: int, detail: str):
    raise send.ActionRefused(status, detail)


# ------------------------------------------------------------------ state ---

def _doc(session, bid: str) -> dict:
    from services import outreach_setup as setup
    return setup._settings_doc(session, bid)


def _billing(doc: dict) -> dict:
    b = dict(doc.get(BILLING_KEY) or {})
    b["brands"] = dict(b.get("brands") or {})
    b["purchases"] = dict(b.get("purchases") or {})
    b["op"] = dict(b.get("op") or {})
    return b


def _save(session, bid: str, billing: dict) -> None:
    from services import outreach_setup as setup
    doc = _doc(session, bid)
    doc[BILLING_KEY] = billing
    setup._save_settings_doc(session, bid, doc)


def _lock(session, bid: str) -> None:
    """The business_settings row (the document's own row): enough to serialise
    every billing change, and present for every business, outreach or not
    (Codex review 1: outreach_settings may not exist)."""
    if send.pg(session):
        session.execute(text("SELECT 1 FROM business_settings WHERE business_id = :b FOR UPDATE"), {"b": bid})
    else:
        session.execute(text("UPDATE business_settings SET business_id = business_id WHERE business_id = :b"), {"b": bid})


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


def billing_on() -> bool:
    """Brand billing switches on only once BOTH Stripe prices are set."""
    return all(os.environ.get(env, "").strip() for env in PRICE_ENV.values())


def _price_id(price_pence: int) -> Optional[str]:
    return os.environ.get(PRICE_ENV.get(int(price_pence), ""), "").strip() or None


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
        return ends is None or moment < ends
    return False


def charged_brand_pence(session, bid: str, moment: Optional[datetime] = None) -> int:
    """What paid brands charge this month. A brand awaiting payment charges
    nothing; a stopped brand only until the end of its paid period;
    grandfathered paid brands at their price; a free business nothing."""
    from services import outreach_allowance
    moment = moment or send.now()
    if free(session, bid):
        return 0
    brands = _billing(_doc(session, bid))["brands"]
    total = 0
    for brand_id, (price, included) in outreach_allowance.prices(session, bid).items():
        if included:
            continue
        entry = brands.get(brand_id)
        state = (entry or {}).get("state")
        if entry is None or state in ("pending", "active"):
            total += price
        elif state == "ending":
            ends = _parse(entry.get("ends_at"))
            if ends is None or moment < ends:
                total += price
    return total


def pending_topup_pence(session, bid: str, moment: Optional[datetime] = None) -> int:
    """Top-ups reserved and not yet settled either way: until Stripe settles
    them they may still be paid, so they keep their place in the budget."""
    return sum(int(p.get("amount") or 0) for p in _billing(_doc(session, bid))["purchases"].values())


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
                     "live": brand_live(session, bid, brand_id, moment), "ends_at": (entry or {}).get("ends_at"),
                     "note": (entry or {}).get("note")})
    session.rollback()
    return {"brands": rows, "topup_sizes": list(TOPUP_SIZES)}


def mark_new_brand(session, bid: str, brand_id) -> None:
    """Called when a brand is created (after F): a brand that costs money waits
    for payment. In the caller's transaction."""
    from services import outreach_allowance
    if not billing_on() or free(session, bid):
        return   # billing for brands starts once Mike has set both Stripe prices
    price, included = outreach_allowance.prices(session, bid).get(str(brand_id), (0, False))
    if included or not price:
        return
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


def _definite(api, exc) -> bool:
    """A Stripe refusal that certainly changed nothing (a 4xx: the card was
    declined, the request was invalid, the rate limit). Anything else — a
    timeout, a connection drop, a 5xx — may have been carried out."""
    for name in ("CardError", "InvalidRequestError", "RateLimitError", "AuthenticationError", "PermissionError"):
        cls = getattr(api, name, None) or getattr(getattr(api, "error", None), name, None)
        if isinstance(cls, type) and isinstance(exc, cls):
            return True
    return False


def _code(exc) -> Optional[str]:
    return getattr(exc, "code", None) or _get(getattr(exc, "error", None), "code")


def _owner(session, business, user) -> None:
    from services import outreach_setup as setup
    setup._authority(session, business, user, growth=False)   # active owner, current entitlement, under lock


def _claim_op(billing: dict, moment: datetime) -> Optional[str]:
    """One subscription operation at a time per business."""
    held = billing.get("op") or {}
    until = _parse(held.get("until"))
    if held.get("token") and until and moment < until:
        return None
    token = uuid.uuid4().hex
    billing["op"] = {"token": token, "until": (moment + OP_LIFE).isoformat()}
    return token


def _desired(billing: dict) -> dict:
    """The quantity each outreach price should have: one per brand being paid
    for (pending or active; a stopped brand no longer counts)."""
    out: dict = {}
    for entry in billing["brands"].values():
        if entry.get("state") in ("pending", "active"):
            out[int(entry.get("price") or 0)] = out.get(int(entry.get("price") or 0), 0) + 1
    return out


def _item_changes(subscription, desired: dict, only: Optional[int] = None) -> list:
    changes = []
    for amount in PRICE_ENV:
        if only is not None and amount != only:
            continue
        price_id = _price_id(amount)
        if not price_id:
            continue
        want = int(desired.get(amount, 0))
        found = [i for i in _items(subscription) if _item_price(i) == price_id]
        have = sum(int(_get(i, "quantity") or 0) for i in found)
        if have == want:
            continue
        if found:
            changes.append({"id": _get(found[0], "id"), "deleted": True} if want == 0
                           else {"id": _get(found[0], "id"), "quantity": want})
        elif want:
            changes.append({"price": price_id, "quantity": want})
    return changes


# -------------------------------------------------------- adding / removing ---

class _Busy(Exception):
    pass


def add_paid_brand(session, business, user, brand_id, *, api=None) -> dict:
    """Charge a brand pro-rata now; it goes live when Stripe confirms payment."""
    from services import outreach_allowance
    bid = str(business.id)
    _owner(session, business, user)
    send.one(session, "outreach_brands", bid, brand_id)
    if free(session, bid):
        refuse(409, "This business's brands are free: there's nothing to pay.")
    if not billing_on():
        refuse(503, "Paid brands aren't set up for billing yet. Please try again later.")
    billing = _billing(_doc(session, bid))
    entry = billing["brands"].get(str(brand_id))
    retry = bool(entry and entry.get("state") == "pending" and entry.get("uncertain"))
    if not entry or (entry.get("state") != "awaiting_payment" and not retry):
        refuse(409, "This brand isn't waiting for payment.")
    price = int(entry.get("price") or 0)
    row = _business_row(session, bid)
    if not row.get("stripe_subscription_id"):
        refuse(409, "Subscribe to a Business Hero plan first, then add paid brands to it.")
    if not retry and not outreach_allowance.can_charge(session, business, price):
        refuse(409, f"Adding this brand (£{price / 100:.2f} a month) would go beyond your monthly outreach budget. "
                    "Raise the budget first.")
    moment = send.now()
    token = _claim_op(billing, moment)
    if token is None:
        refuse(409, "Another change to your subscription is still going through. Try again in a minute.")
    if not retry:
        entry.update(state="pending", requested_at=moment.isoformat(), op=uuid.uuid4().hex)
        entry.pop("note", None)
    op = entry["op"]
    _save(session, bid, billing)
    session.commit()                       # recorded (and counted in the budget) before Stripe is called
    api = api or _stripe()
    try:
        sub = api.Subscription.retrieve(row["stripe_subscription_id"])
        if _get(sub, "pending_update"):
            raise _Busy()
        changes = _item_changes(sub, _desired(billing), only=price)
        if changes:
            api.Subscription.modify(row["stripe_subscription_id"], items=changes, proration_behavior="always_invoice",
                                    payment_behavior="pending_if_incomplete", idempotency_key=f"outreach-brand-{op}")
    except _Busy:
        _settle_brand(session, bid, brand_id, op, token, revert=not retry)
        refuse(409, "A payment on your subscription is still being confirmed. Try again in a few minutes.")
    except Exception as exc:
        if _definite(api, exc):
            _settle_brand(session, bid, brand_id, op, token, revert=True)
            refuse(402 if _code(exc) else 409, "Stripe couldn't add this brand, so nothing was charged. "
                   "Check the card on your subscription in Billing and try again.")
        _settle_brand(session, bid, brand_id, op, token, uncertain=True)
        refuse(502, "We couldn't confirm this with Stripe just now. We'll check automatically. Please don't pay "
                    "again: if it went through, the brand goes live on its own.")
    _settle_brand(session, bid, brand_id, op, token)
    return {"brand_id": str(brand_id), "billing": "pending"}


def _settle_brand(session, bid, brand_id, op, token, *, revert=False, uncertain=False) -> None:
    _lock(session, bid)
    billing = _billing(_doc(session, bid))
    entry = billing["brands"].get(str(brand_id))
    if entry and entry.get("op") == op:
        if revert and entry.get("state") == "pending":
            entry.update(state="awaiting_payment")
            for k in ("requested_at", "op", "uncertain"):
                entry.pop(k, None)
        elif uncertain:
            entry["uncertain"] = True
        else:
            entry.pop("uncertain", None)
    if (billing.get("op") or {}).get("token") == token:
        billing["op"] = {}
    _save(session, bid, billing)
    session.commit()


def remove_paid_brand(session, business, user, brand_id, *, api=None) -> dict:
    """Stop billing at the end of the month already paid; live until then. The
    intent is recorded BEFORE Stripe is called."""
    bid = str(business.id)
    _owner(session, business, user)
    billing = _billing(_doc(session, bid))
    entry = billing["brands"].get(str(brand_id))
    if not entry or entry.get("state") != "active":
        refuse(409, "Only a paid, live brand can be removed from billing.")
    if not billing_on():
        refuse(503, "Paid brands aren't set up for billing yet. Please try again later.")
    row = _business_row(session, bid)
    moment = send.now()
    token = _claim_op(billing, moment)
    if token is None:
        refuse(409, "Another change to your subscription is still going through. Try again in a minute.")
    op = uuid.uuid4().hex
    entry.update(state="ending", ending_op=op, ends_at=None)
    _save(session, bid, billing)
    session.commit()                       # stopped locally first: it can no longer be counted as paid
    api = api or _stripe()
    price = int(entry.get("price") or 0)
    ends_at = None
    try:
        sub = api.Subscription.retrieve(row["stripe_subscription_id"])
        item = next((i for i in _items(sub) if _item_price(i) == _price_id(price)), None)
        ends = _get(item, "current_period_end") or _get(sub, "current_period_end")
        ends_at = datetime.fromtimestamp(int(ends), tz=timezone.utc).isoformat() if ends else None
        changes = _item_changes(sub, _desired(billing), only=price)
        if changes:
            api.Subscription.modify(row["stripe_subscription_id"], items=changes, proration_behavior="none",
                                    idempotency_key=f"outreach-brand-remove-{op}")
    except Exception as exc:
        definite = _definite(api, exc)
        _lock(session, bid)
        billing = _billing(_doc(session, bid))
        current = billing["brands"].get(str(brand_id)) or {}
        if definite and current.get("ending_op") == op:
            current.update(state="active")
            current.pop("ending_op", None)
            current.pop("ends_at", None)
        elif current.get("ending_op") == op and ends_at:
            current["ends_at"] = ends_at   # uncertain: the scheduled check settles Stripe's quantity
        if (billing.get("op") or {}).get("token") == token:
            billing["op"] = {}
        _save(session, bid, billing)
        session.commit()
        if definite:
            refuse(409, "Stripe couldn't stop this brand's billing, so nothing changed. Please try again.")
        refuse(502, "We couldn't confirm this with Stripe just now; billing for this brand will be stopped "
                    "automatically.")
    _lock(session, bid)
    billing = _billing(_doc(session, bid))
    current = billing["brands"].get(str(brand_id)) or {}
    if current.get("ending_op") == op:
        current["ends_at"] = ends_at or moment.isoformat()
    if (billing.get("op") or {}).get("token") == token:
        billing["op"] = {}
    _save(session, bid, billing)
    session.commit()
    return {"brand_id": str(brand_id), "billing": "ending", "ends_at": current.get("ends_at")}


# ----------------------------------------------------------- reconciliation ---

def _business_for(session, customer=None, subscription_id=None) -> Optional[str]:
    for column, value in (("stripe_subscription_id", subscription_id), ("stripe_customer_id", customer)):
        if not value:
            continue
        found = session.execute(text(f"SELECT id FROM businesses WHERE {column} = :v"), {"v": value}).first()
        if found:
            return str(found[0])
    return None


def has_billing(session, bid: str) -> bool:
    billing = _billing(_doc(session, bid))
    return bool(billing["brands"] or billing["purchases"])


def _quantity_of(sub, item_id) -> int:
    return sum(int(_get(i, "quantity") or 0) for i in _items(sub) if _get(i, "id") == item_id)


def reconcile(session, bid: str, *, api=None, moment: Optional[datetime] = None) -> None:
    """Bring a business's brand and top-up state into line with Stripe as it
    is NOW. Fetches before locking; applies under the lock; the caller
    commits. Idempotent: safe from any webhook, in any order, and from the
    scheduled check."""
    moment = moment or send.now()
    row = _business_row(session, bid)
    billing = _billing(_doc(session, bid))
    if not (billing["brands"] or billing["purchases"]) or not row.get("stripe_subscription_id"):
        return
    api = api or _stripe()
    sub = api.Subscription.retrieve(row["stripe_subscription_id"])
    found_payments = {}
    for key, purchase in billing["purchases"].items():
        at = _parse(purchase.get("at"))
        if at is not None and moment - at >= STALE:
            found_payments[key] = _find_payment(api, purchase, key)
    _lock(session, bid)
    billing = _billing(_doc(session, bid))
    _apply_brands(billing, sub, moment)
    for key, outcome in found_payments.items():
        purchase = billing["purchases"].get(key)
        if purchase is None:
            continue
        if outcome and outcome[0] == "succeeded":
            _credit(session, bid, purchase, key, outcome[1], billing, moment)
        elif outcome and outcome[0] == "gone":
            billing["purchases"].pop(key, None)
    _save(session, bid, billing)
    # Stripe still charging for a brand that has stopped (an uncertain removal):
    # set the quantity to what's being paid for, with no proration.
    held = billing.get("op") or {}
    held_until = _parse(held.get("until"))
    if not _get(sub, "pending_update") and not (held.get("token") and held_until and moment < held_until):
        over = [c for c in _item_changes(sub, _desired(billing))
                if c.get("deleted") or ("id" in c and int(c.get("quantity", 0)) < _quantity_of(sub, c["id"]))]
        if over:
            try:
                api.Subscription.modify(row["stripe_subscription_id"], items=over, proration_behavior="none",
                                        idempotency_key=f"outreach-brand-settle-{bid}-{moment.strftime('%Y%m%d%H')}")
            except Exception:
                logger.exception("Outreach billing: could not settle the subscription quantity for %s", bid)


def _apply_brands(billing: dict, sub, moment: datetime) -> None:
    """Paid quantity, oldest request first, to the brands being paid for."""
    pending_update = _get(sub, "pending_update")
    for amount in PRICE_ENV:
        price_id = _price_id(amount)
        if not price_id:
            continue
        paid = sum(int(_get(i, "quantity") or 0) for i in _items(sub) if _item_price(i) == price_id)
        waiting = sorted(((bid_, e) for bid_, e in billing["brands"].items()
                          if int(e.get("price") or 0) == amount and e.get("state") in ("pending", "active")),
                         key=lambda pair: (pair[1].get("requested_at") or "", pair[0]))
        for position, (brand_id, entry) in enumerate(waiting):
            if position < paid:
                entry["state"] = "active"
                entry.pop("uncertain", None)
                entry.pop("note", None)
                continue
            if entry.get("state") == "active":
                entry["state"] = "pending"      # Stripe no longer has it paid
            requested = _parse(entry.get("requested_at"))
            if not pending_update and requested is not None and moment - requested >= STALE:
                # No payment in progress and none arrived: the addition was
                # declined or abandoned. Back to awaiting payment, to try again.
                entry.update(state="awaiting_payment", note="The payment didn't go through. Try again, or check "
                                                            "the card on your subscription.")
                for k in ("requested_at", "op", "uncertain"):
                    entry.pop(k, None)


# ------------------------------------------------------------------ top-ups ---

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
    billing["purchases"][key] = {"amount": amount_pence, "brand_id": str(brand_id), "at": send.now().isoformat(),
                                 "state": "reserved"}
    _save(session, bid, billing)
    session.commit()                       # reserved before Stripe is called
    api = api or _stripe()
    metadata = {"kind": "outreach_topup", "business_id": bid, "brand_id": str(brand_id), "reservation": key}

    def mark(**fields) -> None:
        _lock(session, bid)
        current = _billing(_doc(session, bid))
        if key in current["purchases"]:
            if fields.get("release"):
                current["purchases"].pop(key)
            else:
                current["purchases"][key].update(fields)
        _save(session, bid, current)
        session.commit()

    try:
        sub = api.Subscription.retrieve(row["stripe_subscription_id"])
        method = _get(sub, "default_payment_method")
        method = method if isinstance(method, str) or method is None else _get(method, "id")
        if not method:
            mark(release=True)
            refuse(409, "There's no saved card on your subscription. Add one in Billing, then try again.")
        intent = api.PaymentIntent.create(amount=amount_pence, currency="gbp", customer=row["stripe_customer_id"],
                                          payment_method=method, off_session=True, confirm=True,
                                          description="Business Hero outreach top-up", metadata=metadata,
                                          idempotency_key=f"outreach-topup-{key}")
    except send.ActionRefused:
        raise
    except Exception as exc:
        if _definite(api, exc) and _code(exc) == "authentication_required":
            # The bank wants the owner present. The off-session attempt is
            # cancelled so it can never also succeed; the purchase continues on
            # Stripe's hosted page, still reserved, under the same identity.
            failed = _get(_get(getattr(exc, "error", None), "payment_intent"), "id")
            if failed:
                try:
                    api.PaymentIntent.cancel(failed)
                except Exception:
                    logger.exception("Outreach top-up: could not cancel %s", failed)
            try:
                checkout = api.checkout.Session.create(
                    mode="payment", customer=row["stripe_customer_id"], metadata=metadata,
                    line_items=[{"quantity": 1, "price_data": {"currency": "gbp", "unit_amount": amount_pence,
                                                              "product_data": {"name": "Outreach top-up"}}}],
                    payment_intent_data={"metadata": metadata},
                    success_url=return_url, cancel_url=return_url, idempotency_key=f"outreach-topup-checkout-{key}")
            except Exception:
                mark(state="uncertain")
                refuse(502, "We couldn't open Stripe's payment page just now. Please try again in a minute.")
            mark(state="checkout", checkout_id=_get(checkout, "id"))
            return {"status": "needs_authentication", "checkout_url": _get(checkout, "url")}
        if _definite(api, exc):
            mark(release=True)
            refuse(402, "Your card was declined, so nothing was charged. Update your card in Billing and try again.")
        mark(state="uncertain")
        refuse(502, "We couldn't confirm the payment with Stripe just now. We'll check automatically. Please don't "
                    "pay again: if it went through, it shows in a few minutes.")
    mark(state="processing", pi=_get(intent, "id"))
    return {"status": "processing"}


def _find_payment(api, purchase: dict, key: str):
    """What happened to a top-up, asked of Stripe by its own identity."""
    try:
        if purchase.get("state") == "checkout" and purchase.get("checkout_id"):
            session_ = api.checkout.Session.retrieve(purchase["checkout_id"])
            if _get(session_, "status") == "expired":
                return ("gone", None)
        found = api.PaymentIntent.search(query=f"metadata['reservation']:'{key}'")
        intents = list(_get(found, "data") or [])
        for intent in intents:
            if _get(intent, "status") == "succeeded":
                return ("succeeded", intent)
        if intents and all(_get(i, "status") == "canceled" for i in intents) and purchase.get("state") != "checkout":
            return ("gone", None)
        if not intents and purchase.get("state") in ("reserved", "uncertain"):
            return ("gone", None)          # Stripe never created it: nothing to pay
    except Exception:
        logger.exception("Outreach top-up: could not check reservation %s", key)
    return None


def _credit(session, bid, purchase, key, intent, billing, moment) -> bool:
    """Credit a confirmed payment, once (a durable row per payment)."""
    from services import outreach_research
    pi = _get(intent, "id")
    credited = session.execute(text("SELECT 1 FROM usage_meters WHERE business_id = :b AND meter = :m"),
                               {"b": bid, "m": f"{CREDITED_METER}:{pi}"}).first()
    if not credited:
        amount = int(_get(intent, "amount_received") or _get(intent, "amount") or 0)
        outreach_research._add_meter(session, bid, f"{TOPUP_METER}:{purchase['brand_id']}", moment, amount)
        outreach_research._add_meter(session, bid, f"{CREDITED_METER}:{pi}", moment, 1)
    billing["purchases"].pop(key, None)
    return not credited


def apply_payment_intent(session, event_type: str, intent, *, created: Optional[datetime] = None) -> None:
    """From the webhook, in its transaction. A payment is credited only when it
    is the business's own (its Stripe customer), in pounds, one of the three
    sizes, for one of its brands — and once. A failed off-session payment
    releases its reservation; a hosted-page purchase stays reserved until its
    page expires (the owner may still pay)."""
    metadata = _get(intent, "metadata") or {}
    if _get(metadata, "kind") != "outreach_topup":
        return
    bid, brand_id, key = _get(metadata, "business_id"), _get(metadata, "brand_id"), _get(metadata, "reservation")
    pi = _get(intent, "id")
    if not bid or not brand_id or not pi:
        return
    row = _business_row(session, bid)
    if not row or _get(intent, "customer") != row.get("stripe_customer_id"):
        logger.warning("Outreach top-up %s ignored: not the business's own Stripe customer", pi)
        return
    if not send.rows(session, "outreach_brands", bid, "AND id = :i", {"i": str(brand_id)}):
        return
    amount = int(_get(intent, "amount_received") or _get(intent, "amount") or 0)
    if _get(intent, "currency") != "gbp" or amount not in TOPUP_SIZES:
        logger.warning("Outreach top-up %s ignored: unexpected amount or currency", pi)
        return
    _lock(session, bid)
    billing = _billing(_doc(session, bid))
    purchase = billing["purchases"].get(key) or {"amount": amount, "brand_id": str(brand_id)}
    if purchase.get("brand_id") != str(brand_id):
        return
    if event_type == "payment_intent.succeeded":
        _credit(session, bid, purchase, key, intent, billing, created or send.now())
    elif event_type == "payment_intent.payment_failed":
        held = billing["purchases"].get(key)
        if held and held.get("state") in ("processing", "uncertain") and held.get("pi") in (None, pi):
            billing["purchases"].pop(key)
    _save(session, bid, billing)


def apply_checkout_expired(session, checkout) -> None:
    """A hosted payment page that expired unpaid releases its reservation."""
    metadata = _get(checkout, "metadata") or {}
    if _get(metadata, "kind") != "outreach_topup":
        return
    bid, key = _get(metadata, "business_id"), _get(metadata, "reservation")
    if not bid or not key:
        return
    row = _business_row(session, bid)
    if not row or _get(checkout, "customer") != row.get("stripe_customer_id"):
        return
    _lock(session, bid)
    billing = _billing(_doc(session, bid))
    if (billing["purchases"].get(key) or {}).get("checkout_id") == _get(checkout, "id"):
        billing["purchases"].pop(key)
        _save(session, bid, billing)


def webhook(session, event_type: str, event_data, *, created: Optional[datetime] = None, api=None) -> None:
    """Everything outreach billing does on a Stripe event, in the webhook's
    transaction. A business with no outreach billing is left untouched."""
    if event_type in ("payment_intent.succeeded", "payment_intent.payment_failed"):
        apply_payment_intent(session, event_type, event_data, created=created)
        return
    if event_type == "checkout.session.expired":
        apply_checkout_expired(session, event_data)
        return
    if event_type.startswith("customer.subscription.") or event_type.startswith("invoice."):
        sub_id = (_get(event_data, "id") if event_type.startswith("customer.subscription.")
                  else _get(event_data, "subscription"))
        bid = _business_for(session, customer=_get(event_data, "customer"), subscription_id=sub_id)
        if bid and has_billing(session, bid):
            reconcile(session, bid, api=api)


def scheduled_check(*, api=None) -> int:
    """From the scheduler: reconcile every business with outreach billing
    (uncertain brand changes and top-ups settle here). Never raises."""
    from sqlmodel import Session
    from db import engine
    done = 0
    try:
        with Session(engine) as s:
            ids = [str(r[0]) for r in s.execute(text(
                "SELECT business_id FROM business_settings WHERE CAST(settings AS TEXT) LIKE :k"),
                {"k": f'%"{BILLING_KEY}"%'})]
        for bid in ids:
            try:
                with Session(engine) as s:
                    reconcile(s, bid, api=api)
                    s.commit()
                    done += 1
            except Exception:
                logger.exception("Outreach billing: scheduled check failed for %s", bid)
    except Exception:
        logger.exception("Outreach billing: scheduled check failed")
    return done
