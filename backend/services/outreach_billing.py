"""OUT-19 F — Stripe for extra brands and top-ups (docs/OUT-19-TICKET.md, F).

Mike, 29 Oct 2026 ("Go with recommendations ... they also protect expenditure
vs income"), simplified with Mike on 30 Oct 2026 after Codex's review 2:
  1. a new paid brand gets ITS OWN line on the business's Stripe subscription
     (its own Stripe price, made for it), charged pro-rata now
     (proration_behavior=always_invoice);
  2. it goes live only once Stripe has that line paid
     (payment_behavior=pending_if_incomplete);
  3. a top-up (£10, £25 or £50) is paid on Stripe's own payment page
     (Checkout): reserved against the owner's budget under the business lock
     BEFORE Stripe is called, credited only when Stripe says the page was
     paid, once; released only when Stripe says the page expired;
  4. removing a paid brand deletes its line with no proration; it stays live
     until the end of the period already paid.

Principles:
  * ONE BRAND, ONE LINE. Brands never share a quantity, so no brand can take
    another's paid place, and removing one can't touch another.
  * DURABLE, IDENTICAL REQUESTS. Each Stripe write has an identity saved
    before Stripe is called and reused as the idempotency key with exactly the
    same parameters. An outcome Stripe didn't confirm is kept and checked,
    never assumed to have failed.
  * STRIPE IS THE TRUTH, APPLIED ONLY IF NOTHING MOVED. reconcile() fetches
    the subscription (and payment pages) as Stripe has them now, then applies
    them only to records that haven't changed since the fetch.
  * ONE PAYMENT CHECK. A payment page is credited, or released, by one
    function, from the webhook or the scheduled check alike, and only against
    a purchase this business actually reserved.

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
CREDITED_METER = "outreach_topup_credited"      # one durable row per credited payment page
FREE_FLAG = "outreach_brands_free"
PRICE_ENV = {9900: "STRIPE_PRICE_OUTREACH_ADDON", 7900: "STRIPE_PRICE_EXTRA_BRAND"}
OP_LIFE = timedelta(minutes=10)                 # a subscription operation's claim
STALE = timedelta(hours=1)                      # an addition with no line and no pending update has failed
PAGE_LIFE = timedelta(minutes=60)               # a top-up page's expiry, fixed when reserved
# Stripe requires a page to expire at least 30 minutes after it is CREATED: a
# re-send up to 30 minutes after reserving still leaves 30 (Codex review 3).
PAGE_CHECK_AFTER = timedelta(minutes=5)         # the scheduled check asks Stripe about a page after this
PAGE_REBUILD_UNTIL = timedelta(minutes=30)      # an unconfirmed page creation is re-sent, same key, until then
PAGE_GIVE_UP = timedelta(days=4)                # past Stripe's 3 days of webhook retries: nothing was paid
DEAD = ("canceled", "incomplete_expired")


def refuse(status: int, detail: str):
    raise send.ActionRefused(status, detail)


# ------------------------------------------------------------------ state ---

def _doc(session, bid: str) -> dict:
    from services import outreach_setup as setup
    return setup._settings_doc(session, bid)


def _billing(doc: dict) -> dict:
    b = dict(doc.get(BILLING_KEY) or {})
    b["brands"] = {k: dict(v) for k, v in (b.get("brands") or {}).items()}
    b["purchases"] = {k: dict(v) for k, v in (b.get("purchases") or {}).items()}
    b["op"] = dict(b.get("op") or {})
    return b


def _save(session, bid: str, billing: dict) -> None:
    from services import outreach_setup as setup
    doc = _doc(session, bid)
    doc[BILLING_KEY] = billing
    setup._save_settings_doc(session, bid, doc)


def _lock(session, bid: str) -> None:
    """The business_settings row (the document's own row): it serialises every
    billing change, exists for every business, and is the first lock the
    owner's actions take, so every path locks in the same order."""
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


def _ended(entry: dict, moment: datetime) -> bool:
    ends = _parse(entry.get("ends_at"))
    return ends is not None and moment >= ends


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
        return not _ended(entry, moment)  # an ending brand always has its paid-period end recorded
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
        if entry is None or state in ("pending", "active") or (state == "ending" and not _ended(entry, moment)):
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
                     "note": (entry or {}).get("note"), "checking": bool((entry or {}).get("uncertain"))})
    topups = [{"brand_id": p.get("brand_id"), "amount_pence": int(p.get("amount") or 0)}
              for p in billing["purchases"].values()]
    session.rollback()
    return {"brands": rows, "topup_sizes": list(TOPUP_SIZES), "topups_in_progress": topups}


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


def _billed_prices(subscription) -> set:
    """The prices Stripe is billing now (none on a dead subscription)."""
    if _get(subscription, "status") in DEAD:
        return set()
    return {_item_price(i) for i in _items(subscription)}


def _waiting_prices(subscription) -> set:
    """The prices in an update Stripe holds until its invoice is paid."""
    pending = _get(subscription, "pending_update")
    return {_item_price(i) for i in (_get(pending, "subscription_items") or [])} if pending else set()


def _definite(api, exc) -> bool:
    """A Stripe refusal that certainly changed nothing (a 4xx: the card was
    declined, the request was invalid, the rate limit). Anything else — a
    timeout, a connection drop, a 5xx — may have been carried out."""
    for name in ("CardError", "InvalidRequestError", "RateLimitError", "AuthenticationError", "PermissionError",
                 "IdempotencyError"):
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
    if _op_held(billing, moment):
        return None
    token = uuid.uuid4().hex
    billing["op"] = {"token": token, "until": (moment + OP_LIFE).isoformat()}
    return token


def _op_held(billing: dict, moment: datetime) -> bool:
    held = billing.get("op") or {}
    until = _parse(held.get("until"))
    return bool(held.get("token") and until and moment < until)


def _update(session, bid: str, brand_id, check, token=None, **fields) -> dict:
    """Under the lock: change a brand's record if `check(entry)` still holds
    (a field given as None is removed); release the operation claim if it is
    ours; commit."""
    _lock(session, bid)
    billing = _billing(_doc(session, bid))
    entry = billing["brands"].get(str(brand_id))
    if entry is not None and check(entry):
        for key, value in fields.items():
            if value is None:
                entry.pop(key, None)
            else:
                entry[key] = value
    if token and (billing.get("op") or {}).get("token") == token:
        billing["op"] = {}
    _save(session, bid, billing)
    session.commit()
    return entry or {}


def _brand_price(api, bid: str, brand_id, amount: int, op: str) -> str:
    """This brand's own Stripe price: the same product and amount as the
    configured price, one per addition (idempotent on the addition's id)."""
    base = api.Price.retrieve(_price_id(amount))
    recurring = _get(base, "recurring") or {}
    if (_get(base, "unit_amount") != amount or _get(base, "currency") != "gbp"
            or _get(recurring, "interval") != "month"):
        logger.error("Outreach billing: Stripe price %s isn't £%.2f a month", _price_id(amount), amount / 100)
        refuse(503, "Paid brands aren't set up correctly for billing yet. Please try again later.")
    created = api.Price.create(product=_get(base, "product"), unit_amount=amount, currency="gbp",
                               recurring={"interval": "month"}, nickname=f"Outreach brand {brand_id}",
                               metadata={"kind": "outreach_brand", "business_id": bid, "brand_id": str(brand_id)},
                               idempotency_key=f"outreach-brand-price-{op}")
    return _get(created, "id")


# -------------------------------------------------------- adding / removing ---

class _Busy(Exception):
    pass


def add_paid_brand(session, business, user, brand_id, *, api=None) -> dict:
    """Charge a brand pro-rata now, on its own subscription line; it goes live
    when Stripe has that line paid."""
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
        for k in ("note", "price_id", "uncertain"):
            entry.pop(k, None)
    billing["brands"][str(brand_id)] = entry
    op = entry["op"]
    _save(session, bid, billing)
    session.commit()                       # recorded (and counted in the budget) before Stripe is called

    def mine(e):
        return e.get("op") == op and e.get("state") == "pending"
    try:
        api = api or _stripe()             # inside: a set-up error still releases the claim (Codex review 4)
        sub = api.Subscription.retrieve(row["stripe_subscription_id"])
        price_id = entry.get("price_id")
        if price_id and (price_id in _billed_prices(sub) or price_id in _waiting_prices(sub)):
            _update(session, bid, brand_id, mine, token, uncertain=None)   # the earlier attempt went through
            return {"brand_id": str(brand_id), "billing": "pending"}
        if _get(sub, "pending_update"):
            raise _Busy()
        if not price_id:
            price_id = _brand_price(api, bid, brand_id, price, op)
            _update(session, bid, brand_id, mine, None, price_id=price_id)   # the exact request, kept for a retry
        api.Subscription.modify(row["stripe_subscription_id"], items=[{"price": price_id, "quantity": 1}],
                                proration_behavior="always_invoice", payment_behavior="pending_if_incomplete",
                                idempotency_key=f"outreach-brand-{op}")
    except _Busy:
        _back_to_awaiting(session, bid, brand_id, mine, token, keep=retry)
        refuse(409, "A payment on your subscription is still being confirmed. Try again in a few minutes.")
    except send.ActionRefused:
        _back_to_awaiting(session, bid, brand_id, mine, token, keep=retry)
        raise
    except Exception as exc:
        if _definite(api, exc) and not retry:
            _back_to_awaiting(session, bid, brand_id, mine, token, keep=False)
            refuse(402 if _code(exc) else 409, "Stripe couldn't add this brand, so nothing was charged. "
                   "Check the card on your subscription in Billing and try again.")
        # Codex review 3: on a retry, even a definite refusal (a rate limit on
        # the read, say) says nothing about the FIRST attempt, which may have
        # been charged. Its identity is kept until Stripe shows the outcome.
        _update(session, bid, brand_id, mine, token, uncertain=True)
        refuse(502, "We couldn't confirm this with Stripe just now. We'll check automatically. Please don't pay "
                    "again: if it went through, the brand goes live on its own.")
    _update(session, bid, brand_id, mine, token, uncertain=None)
    return {"brand_id": str(brand_id), "billing": "pending"}


def _back_to_awaiting(session, bid, brand_id, mine, token, *, keep) -> None:
    if keep:      # a retry of an uncertain addition stays as it was: the first attempt may still have gone through
        _update(session, bid, brand_id, lambda e: False, token)
        return
    _update(session, bid, brand_id, mine, token, state="awaiting_payment", requested_at=None, op=None,
            price_id=None, uncertain=None)


def remove_paid_brand(session, business, user, brand_id, *, api=None) -> dict:
    """Delete the brand's own subscription line with no proration; it stays
    live until the end of the period already paid. The subscription operation
    is claimed BEFORE Stripe is read (Codex review 3: no other change can slip
    in between the read and the deletion), and the paid period's end is known
    before anything is recorded."""
    bid = str(business.id)
    _owner(session, business, user)
    if not billing_on():
        refuse(503, "Paid brands aren't set up for billing yet. Please try again later.")
    billing = _billing(_doc(session, bid))
    entry = billing["brands"].get(str(brand_id))
    if not entry or entry.get("state") != "active":
        refuse(409, "Only a paid, live brand can be removed from billing.")
    token = _claim_op(billing, send.now())
    if token is None:
        refuse(409, "Another change to your subscription is still going through. Try again in a minute.")
    price_id = entry.get("price_id")
    row = _business_row(session, bid)
    _save(session, bid, billing)
    session.commit()                       # claimed; no lock held while Stripe is asked

    def unchanged(e):
        return e.get("state") == "active" and e.get("price_id") == price_id
    try:
        api = api or _stripe()             # inside: a set-up error still releases the claim (Codex review 4)
        sub = api.Subscription.retrieve(row["stripe_subscription_id"])
    except Exception:
        _update(session, bid, brand_id, lambda e: False, token)
        refuse(502, "We couldn't reach Stripe just now, so nothing changed. Please try again in a minute.")
    if _get(sub, "pending_update"):
        _update(session, bid, brand_id, lambda e: False, token)
        refuse(409, "A payment on your subscription is still being confirmed. Try again in a few minutes.")
    item = next((i for i in _items(sub) if _item_price(i) == price_id), None)
    moment = send.now()
    ends = _get(item, "current_period_end") or _get(sub, "current_period_end")
    ends_at = datetime.fromtimestamp(int(ends), tz=timezone.utc).isoformat() if item and ends else moment.isoformat()
    remove_op = uuid.uuid4().hex
    fields = {"state": "ending", "ends_at": ends_at, "remove_op": remove_op, "item_id": _get(item, "id"),
              "uncertain": True if item is not None else None}
    if not _update(session, bid, brand_id, unchanged, None, **fields).get("remove_op") == remove_op:
        _update(session, bid, brand_id, lambda e: False, token)
        refuse(409, "This brand's billing changed just now. Please refresh and try again.")
    # stopped locally, with its end, before Stripe is asked to stop it; "uncertain" until Stripe confirms

    def mine(e):
        return e.get("remove_op") == remove_op and e.get("state") == "ending"
    if item is None:                       # Stripe wasn't billing it: nothing to stop
        _update(session, bid, brand_id, mine, token)
        return {"brand_id": str(brand_id), "billing": "ending", "ends_at": ends_at}
    try:
        api.Subscription.modify(row["stripe_subscription_id"], items=[{"id": _get(item, "id"), "deleted": True}],
                                proration_behavior="none", idempotency_key=f"outreach-brand-remove-{remove_op}")
    except Exception as exc:
        if _definite(api, exc):
            _update(session, bid, brand_id, mine, token, state="active", ends_at=None, remove_op=None, item_id=None,
                    uncertain=None)
            refuse(409, "Stripe couldn't stop this brand's billing, so nothing changed. Please try again.")
        _update(session, bid, brand_id, mine, token)   # kept, marked uncertain: the scheduled check finishes it
        refuse(502, "We couldn't confirm this with Stripe just now. We'll keep trying to stop this brand's billing; "
                    "it stays live until the end of the month already paid.")
    _update(session, bid, brand_id, mine, token, uncertain=None)
    return {"brand_id": str(brand_id), "billing": "ending", "ends_at": ends_at}


def resend_removals(session, bid: str, *, api=None, moment: Optional[datetime] = None) -> None:
    """From the scheduled check, in its own session: finish removals Stripe
    didn't confirm. Each is the same request under the same key, made under a
    claimed subscription operation with a fresh read of Stripe (Codex review
    3), and never while Stripe holds an unpaid update. If the line has renewed
    into a new paid period meanwhile, the brand stays live to that period's
    end: it was paid for."""
    moment = moment or send.now()
    _lock(session, bid)
    billing = _billing(_doc(session, bid))
    waiting = {k: e for k, e in billing["brands"].items()
               if e.get("state") == "ending" and e.get("uncertain") and e.get("remove_op") and e.get("item_id")}
    row = _business_row(session, bid)
    if not waiting or not row.get("stripe_subscription_id"):
        session.rollback()
        return
    token = _claim_op(billing, moment)
    if token is None:
        session.rollback()
        return
    _save(session, bid, billing)
    session.commit()
    try:
        api = api or _stripe()             # inside: a set-up error still releases the claim (Codex review 4)
        sub = api.Subscription.retrieve(row["stripe_subscription_id"])
        items = {_get(i, "id"): i for i in _items(sub)}
        for brand_id, entry in waiting.items():
            def mine(e, op=entry["remove_op"]):
                return e.get("remove_op") == op and e.get("state") == "ending"
            item = items.get(entry["item_id"])
            if item is None:               # already gone: Stripe carried it out
                _update(session, bid, brand_id, mine, None, uncertain=None)
                continue
            # A renewal is honoured even while another payment is pending and
            # the deletion has to wait (Codex review 4): it was paid for.
            renewed = _get(item, "current_period_end")
            if renewed and (_parse(entry.get("ends_at")) is None or
                            datetime.fromtimestamp(int(renewed), tz=timezone.utc) > _parse(entry["ends_at"])):
                _update(session, bid, brand_id, mine, None,
                        ends_at=datetime.fromtimestamp(int(renewed), tz=timezone.utc).isoformat())
            if _get(sub, "pending_update"):
                continue                   # never while Stripe holds an unpaid update
            try:
                api.Subscription.modify(row["stripe_subscription_id"], items=[{"id": entry["item_id"], "deleted": True}],
                                        proration_behavior="none",
                                        idempotency_key=f"outreach-brand-remove-{entry['remove_op']}")
                _update(session, bid, brand_id, mine, None, uncertain=None)
            except Exception:
                logger.exception("Outreach billing: re-sending a brand removal failed")
    finally:
        _update(session, bid, None, lambda e: False, token)


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


def _fingerprint(entry: dict) -> tuple:
    return tuple(entry.get(k) for k in ("state", "op", "price_id", "remove_op", "uncertain"))


def reconcile(session, bid: str, *, api=None, moment: Optional[datetime] = None, recover: bool = False) -> None:
    """Bring a business's brands and top-ups into line with Stripe as it is
    NOW. Stripe is asked with no lock held; its answers are then applied under
    the lock ONLY to records unchanged since they were read (Codex review 2:
    an operation that finished in between is never overwritten by an older
    answer). Idempotent; the caller commits."""
    moment = moment or send.now()
    row = _business_row(session, bid)
    billing = _billing(_doc(session, bid))
    if not (billing["brands"] or billing["purchases"]) or not row.get("stripe_subscription_id"):
        return
    before = {k: _fingerprint(e) for k, e in billing["brands"].items()}
    purchases_before = {k: dict(p) for k, p in billing["purchases"].items()}
    api = api or _stripe()                 # plain reads so far: no lock is held while Stripe is asked
    sub = api.Subscription.retrieve(row["stripe_subscription_id"])
    pages = _ask_about_pages(api, bid, row, billing, moment, recover=recover)
    _lock(session, bid)
    billing = _billing(_doc(session, bid))
    _apply_brands(billing, sub, moment, before, in_progress=_op_held(billing, moment))
    for key, page in pages.items():
        if billing["purchases"].get(key) == purchases_before.get(key):
            _settle_page(session, bid, row, billing, key, page, moment)
    for key, purchase in list(billing["purchases"].items()):
        if (not purchase.get("checkout_id") and purchase == purchases_before.get(key)
                and moment - (_parse(purchase.get("at")) or moment) >= PAGE_GIVE_UP):
            # A page never confirmed, re-sent without an answer, and no paid
            # page reported by Stripe's webhook in 4 days (it retries for 3):
            # nothing was paid.
            billing["purchases"].pop(key)
    _save(session, bid, billing)


def _apply_brands(billing: dict, sub, moment: datetime, before: dict, *, in_progress: bool = False) -> None:
    """Stripe's answer, applied. While a subscription operation is in progress
    (its claim held) nothing is taken away: Stripe's answer may predate the
    request that operation is making (Codex review 4)."""
    billed, waiting = _billed_prices(sub), _waiting_prices(sub)
    for brand_id, entry in billing["brands"].items():
        if before.get(brand_id) != _fingerprint(entry):
            continue                      # changed since Stripe was asked: the next pass sees it
        state, price_id = entry.get("state"), entry.get("price_id")
        if state == "pending":
            if price_id and price_id in billed:
                entry["state"] = "active"
                entry.pop("uncertain", None)
                entry.pop("note", None)
                continue
            if price_id and price_id in waiting:
                continue                  # Stripe holds it until the invoice is paid
            requested = _parse(entry.get("requested_at"))
            if not in_progress and requested is not None and moment - requested >= STALE:
                # No line and no update waiting, an hour on: the addition was
                # declined, abandoned or never arrived. Try again.
                entry.update(state="awaiting_payment", note="The payment didn't go through. Try again, or check "
                                                            "the card on your subscription.")
                for k in ("requested_at", "op", "uncertain", "price_id"):
                    entry.pop(k, None)
        elif state == "active" and price_id not in billed and not in_progress:
            entry.update(state="awaiting_payment", note="Stripe is no longer billing this brand, so it has "
                                                        "paused. Add it again to carry on.")
            for k in ("requested_at", "op", "uncertain", "price_id"):
                entry.pop(k, None)


# ------------------------------------------------------------------ top-ups ---

def _page_metadata(bid: str, purchase: dict, key: str) -> dict:
    # Not "business_id": the plan webhook reads that key on checkout.session.completed.
    return {"kind": "outreach_topup", "outreach_business_id": bid, "brand_id": purchase["brand_id"],
            "reservation": key}


def _create_page(api, bid: str, customer: str, purchase: dict, key: str):
    """Stripe's payment page for a top-up. Every parameter comes from the
    stored purchase, so a re-send with the same key is the same request."""
    metadata = _page_metadata(bid, purchase, key)
    at = _parse(purchase["at"])
    return api.checkout.Session.create(
        mode="payment", customer=customer, metadata=metadata, payment_intent_data={"metadata": metadata},
        payment_method_types=["card"],     # settles at once: no delayed payment can hold the budget
        line_items=[{"quantity": 1, "price_data": {"currency": "gbp", "unit_amount": int(purchase["amount"]),
                                                  "product_data": {"name": "Outreach top-up"}}}],
        success_url=purchase["return_url"], cancel_url=purchase["return_url"],
        expires_at=int((at + PAGE_LIFE).timestamp()), idempotency_key=f"outreach-topup-{key}")


def start_topup(session, business, user, brand_id, amount_pence, *, api=None, return_url: str) -> dict:
    """£10, £25 or £50, paid on Stripe's page; reserved against the budget first."""
    from services import outreach_allowance
    if amount_pence not in TOPUP_SIZES:
        refuse(422, "A top-up is £10, £25 or £50.")
    bid = str(business.id)
    _owner(session, business, user)        # holds the business lock from here
    send.one(session, "outreach_brands", bid, brand_id)
    if not brand_live(session, bid, brand_id):
        refuse(409, "Top-ups are for brands that are live. Pay for this brand first.")
    row = _business_row(session, bid)
    if not row.get("stripe_customer_id"):
        refuse(409, "Subscribe to a Business Hero plan first.")
    if not outreach_allowance.can_charge(session, business, amount_pence):
        refuse(409, f"A £{amount_pence / 100:.0f} top-up would go beyond your monthly outreach budget. "
                    "Raise the budget first.")
    key = uuid.uuid4().hex
    billing = _billing(_doc(session, bid))
    purchase = {"amount": amount_pence, "brand_id": str(brand_id), "at": send.now().isoformat(),
                "return_url": return_url}
    billing["purchases"][key] = purchase
    _save(session, bid, billing)
    session.commit()                       # reserved before Stripe is called
    api = api or _stripe()
    try:
        page = _create_page(api, bid, row["stripe_customer_id"], purchase, key)
    except Exception as exc:
        if _definite(api, exc):
            _lock(session, bid)
            billing = _billing(_doc(session, bid))
            billing["purchases"].pop(key, None)
            _save(session, bid, billing)
            session.commit()
            refuse(409, "Stripe couldn't open the payment page, so nothing was charged. Please try again.")
        refuse(502, "We couldn't open Stripe's payment page just now. Please try again in a minute: you can't be "
                    "charged twice.")
    _lock(session, bid)
    billing = _billing(_doc(session, bid))
    if key in billing["purchases"]:
        billing["purchases"][key]["checkout_id"] = _get(page, "id")
    _save(session, bid, billing)
    session.commit()
    return {"status": "checkout", "checkout_url": _get(page, "url")}


def _ask_about_pages(api, bid: str, row: dict, billing: dict, moment: datetime, *, recover: bool = False) -> dict:
    """Stripe's answer for each unsettled top-up page, asked with no lock held:
    a known page is fetched; a page whose creation wasn't confirmed is re-sent
    with the same key (Stripe returns the page it made, if it made one)."""
    out = {}
    for key, purchase in billing["purchases"].items():
        age = moment - (_parse(purchase.get("at")) or moment)
        if age < PAGE_CHECK_AFTER:
            continue
        try:
            if purchase.get("checkout_id"):
                out[key] = api.checkout.Session.retrieve(purchase["checkout_id"])
            elif recover and age < PAGE_REBUILD_UNTIL and row.get("stripe_customer_id") and purchase.get("return_url"):
                # only from the scheduled check: the webhook reads, never writes, to Stripe
                out[key] = _create_page(api, bid, row["stripe_customer_id"], purchase, key)
        except Exception:
            logger.exception("Outreach top-up: could not check reservation %s", key)
    return out


def _settle_page(session, bid: str, row: dict, billing: dict, key: str, page, moment: datetime, *,
                 failed: bool = False) -> None:
    """The one check for a top-up page, from the webhook and the scheduled
    check alike: it must be the page for a purchase this business reserved —
    its reservation, its Stripe customer, the brand, pounds, the exact amount.
    Paid: credited once. Expired: released. Otherwise: remembered, waited on."""
    purchase = billing["purchases"].get(key)
    if purchase is None:
        return                             # already settled (or never ours)
    metadata = _get(page, "metadata") or {}
    page_id = _get(page, "id")
    if (_get(metadata, "kind") != "outreach_topup" or _get(metadata, "reservation") != key
            or _get(metadata, "outreach_business_id") != bid or _get(metadata, "brand_id") != purchase["brand_id"]
            or (purchase.get("checkout_id") and purchase["checkout_id"] != page_id)
            or _get(page, "customer") != row.get("stripe_customer_id")):
        logger.warning("Outreach top-up page %s ignored: not this business's reservation %s", page_id, key)
        return
    if _get(page, "status") == "expired" or failed:   # expired unpaid, or Stripe says its payment failed
        billing["purchases"].pop(key)
        return
    if _get(page, "status") == "complete" and _get(page, "payment_status") == "paid":
        if _get(page, "currency") != "gbp" or int(_get(page, "amount_total") or 0) != int(purchase["amount"]):
            logger.error("Outreach top-up page %s: amount or currency differs from reservation %s; kept for review",
                         page_id, key)
            return
        credited = session.execute(text("SELECT 1 FROM usage_meters WHERE business_id = :b AND meter = :m"),
                                   {"b": bid, "m": f"{CREDITED_METER}:{page_id}"}).first()
        if not credited:
            from services import outreach_research
            outreach_research._add_meter(session, bid, f"{TOPUP_METER}:{purchase['brand_id']}", moment,
                                         int(purchase["amount"]))
            outreach_research._add_meter(session, bid, f"{CREDITED_METER}:{page_id}", moment, 1)
        billing["purchases"].pop(key)
        return
    if not purchase.get("checkout_id") and page_id:
        purchase["checkout_id"] = page_id


PAGE_EVENTS = ("checkout.session.completed", "checkout.session.async_payment_succeeded",
               "checkout.session.async_payment_failed", "checkout.session.expired")


def apply_page_event(session, page, *, created: Optional[datetime] = None, failed: bool = False) -> None:
    """A top-up page's event, in the webhook's transaction."""
    metadata = _get(page, "metadata") or {}
    if _get(metadata, "kind") != "outreach_topup":
        return
    bid, key = _get(metadata, "outreach_business_id"), _get(metadata, "reservation")
    if not bid or not key:
        return
    bid = str(bid)
    row = _business_row(session, bid)
    if not row:
        return
    _lock(session, bid)
    billing = _billing(_doc(session, bid))
    if key in billing["purchases"]:
        _settle_page(session, bid, row, billing, key, page, created or send.now(), failed=failed)
        _save(session, bid, billing)


def webhook(session, event_type: str, event_data, *, created: Optional[datetime] = None, api=None) -> None:
    """Everything outreach billing does on a Stripe event, in the webhook's
    transaction. A business with no outreach billing is left untouched."""
    if event_type in PAGE_EVENTS:
        apply_page_event(session, event_data, created=created,
                         failed=event_type == "checkout.session.async_payment_failed")
        return
    if event_type.startswith("customer.subscription.") or event_type.startswith("invoice."):
        sub_id = (_get(event_data, "id") if event_type.startswith("customer.subscription.")
                  else _get(event_data, "subscription"))
        bid = _business_for(session, customer=_get(event_data, "customer"), subscription_id=sub_id)
        if bid and has_billing(session, bid):
            reconcile(session, bid, api=api)


def scheduled_check(*, api=None) -> int:
    """From the scheduler: reconcile every business with outreach billing
    (unconfirmed brand changes and top-up pages settle here). Never raises."""
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
                    reconcile(s, bid, api=api, recover=True)
                    s.commit()
                with Session(engine) as s:
                    resend_removals(s, bid, api=api)
                done += 1
            except Exception:
                logger.exception("Outreach billing: scheduled check failed for %s", bid)
    except Exception:
        logger.exception("Outreach billing: scheduled check failed")
    return done
