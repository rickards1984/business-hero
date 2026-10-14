"""BH-014: read-only Stripe safety net. Process-local last attempt, never billing writes."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import logging
from threading import Lock

import stripe
from sqlalchemy import text

from app.billing.config import get_stripe_config

logger = logging.getLogger(__name__)
_last_result = None
_result_lock = Lock()
_TERMINAL = {"canceled", "incomplete_expired"}


def _utc(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0)


def _new_result(now):
    return {"started_at": now.isoformat(), "finished_at": now.isoformat(),
            "complete": True, "counts": {"businesses_checked": 0,
            "subscriptions_checked": 0, "divergences": 0, "errors": 0},
            "divergences": [], "errors": []}


def alert(result):
    """One structured ERROR record; no payloads, exception text or credentials."""
    logger.error(json.dumps({"event": "stripe_reconciliation", **result}))


def _publish(result):
    global _last_result
    result["counts"]["divergences"] = len(result["divergences"])
    result["counts"]["errors"] = len(result["errors"])
    result["complete"] = result["complete"] and not result["errors"]
    with _result_lock:
        _last_result = deepcopy(result)
    try:
        if result["divergences"] or result["errors"] or not result["complete"]:
            alert(result)
        else:
            logger.info(json.dumps({"event": "stripe_reconciliation", **result}))
    except Exception:
        # Dashboard publication precedes logging; a broken handler cannot
        # stop the scheduler or hide the last attempt from the admin.
        pass
    return result


def record_failure(*, now=None):
    """Includes failures opening/closing the scheduler's database session."""
    result = _new_result(_utc(now or datetime.now(timezone.utc)))
    result["errors"].append({"scope": "run", "business_id": None, "business_name": None, "code": "run_failed"})
    return _publish(result)


def last_run(*, now=None):
    with _result_lock:
        result = deepcopy(_last_result)
    if result is None:
        return {"status": "not_run", "age_seconds": None, "result": None}
    age = max(0, int((_utc(now or datetime.now(timezone.utc)) - _utc(result["finished_at"])).total_seconds()))
    if not result["complete"] or result["errors"]:
        status = "incomplete"
    elif result["divergences"]:
        status = "attention"
    elif age > 24 * 3600:
        status = "stale"
    else:
        status = "healthy"
    return {"status": status, "age_seconds": age, "result": result}


def run(session, *, now=None, silence_threshold=timedelta(hours=48)):
    """Sequential SDK reads, two bounded SDK retries, SDK's bounded timeout.

    Pass the configured key per request, without changing the webhook's SDK
    globals. The installed RequestsClient defaults to an 80-second timeout.
    SDK pagination preserves request options, including the retry bound.
    """
    from main import _plan_item, _resolve_plan_from_price, _resolve_current_period_end

    started = _utc(now or datetime.now(timezone.utc))
    result = _new_result(started)
    by_id = {}
    fetched = {}
    compared = set()
    options = {"api_key": get_stripe_config()["stripe_secret_key"], "max_network_retries": 2}

    def finding(kind, bid=None, sid=None, **values):
        entry = {"kind": kind, "business_id": bid, "business_name": by_id.get(bid, {}).get("name"), "subscription_id": sid, **values}
        if entry not in result["divergences"]:
            result["divergences"].append(entry)

    def error(scope, bid=None):
        result["errors"].append({"scope": scope, "business_id": bid,
                                 "business_name": by_id.get(bid, {}).get("name"), "code": "fetch_failed"})

    try:
        # Read all IDs for metadata matching, even rows without Stripe IDs.
        businesses = [dict(r) for r in session.execute(text(
            "SELECT id, name, stripe_subscription_id, stripe_customer_id, subscription_status, "
            "plan_tier, current_period_end FROM businesses ORDER BY id"
        )).mappings()]
        for b in businesses:
            b["id"] = str(b["id"])
        by_id = {b["id"]: b for b in businesses}

        def resolve(sub, expected=None):
            sid = sub.get("id")
            customer = sub.get("customer")
            if isinstance(customer, dict):
                customer = customer.get("id")
            metadata_id = (sub.get("metadata") or {}).get("business_id")
            subscription_matches = [b for b in businesses if b["stripe_subscription_id"] == sid]
            customer_matches = [b for b in businesses if customer and b["stripe_customer_id"] == customer]
            candidates = {b["id"] for b in subscription_matches + customer_matches}
            if metadata_id in by_id:
                candidates.add(metadata_id)
            conflict = (len(subscription_matches) > 1 or len(customer_matches) > 1 or len(candidates) > 1
                        or (metadata_id and metadata_id not in by_id and bool(candidates)))
            if expected:
                conflict = conflict or (expected["stripe_customer_id"] and expected["stripe_customer_id"] != customer)
                conflict = conflict or (expected["stripe_subscription_id"] and expected["stripe_subscription_id"] != sid)
                conflict = conflict or (metadata_id and metadata_id != expected["id"])
                conflict = conflict or candidates != {expected["id"]}
            if conflict:
                finding("identity_conflict", expected["id"] if expected else None, sid)
                return None
            if not candidates:
                finding("orphan_subscription", None, sid)
                return None
            matched = by_id[next(iter(candidates))]
            if matched["stripe_subscription_id"] and matched["stripe_subscription_id"] != sid:
                finding("identity_conflict", matched["id"], sid)
                return None
            return matched

        def compare(b, sub):
            sid = sub.get("id")
            if (b["id"], sid) in compared:
                return
            compared.add((b["id"], sid))
            def diff(kind, local=None, remote=None):
                finding(kind, b["id"], sid, local=local, remote=remote)
            if b["subscription_status"] != sub.get("status"):
                diff("subscription_status", b["subscription_status"], sub.get("status"))
            price = ((_plan_item(sub) or {}).get("price") or {}).get("id")
            plan = _resolve_plan_from_price(price)
            if plan is None:
                diff("unresolved_price", b["plan_tier"], price)
            elif plan != b["plan_tier"]:
                diff("plan_tier", b["plan_tier"], plan)
            period = _resolve_current_period_end(sub)
            local = _utc(b["current_period_end"])
            if period is None:
                diff("unresolved_period", local.isoformat() if local else None)
            elif _utc(period) != local:
                diff("current_period_end", local.isoformat() if local else None, _utc(period).isoformat())

        for b in businesses:
            if not (b["stripe_subscription_id"] or b["stripe_customer_id"]):
                continue
            result["counts"]["businesses_checked"] += 1
            try:
                if b["stripe_subscription_id"]:
                    sub = stripe.Subscription.retrieve(b["stripe_subscription_id"], **options).to_dict()
                    fetched[sub["id"]] = sub
                else:
                    rows = [s.to_dict() for s in stripe.Subscription.list(customer=b["stripe_customer_id"], status="all", limit=100, **options).auto_paging_iter()]
                    fetched.update({s["id"]: s for s in rows})
                    viable = [s for s in rows if s.get("status") not in _TERMINAL]
                    candidates = viable or rows
                    if not candidates:
                        finding("missing_subscription", b["id"])
                        continue
                    if len(candidates) != 1:
                        finding("identity_conflict", b["id"])
                        continue
                    sub = candidates[0]
                if resolve(sub, b):
                    compare(b, sub)
            except stripe.InvalidRequestError as exc:
                if exc.code == "resource_missing" and b["stripe_subscription_id"]:
                    finding("missing_subscription", b["id"], b["stripe_subscription_id"])
                else:
                    error("business", b["id"])
            except Exception:
                error("business", b["id"])

        try:
            for resource in stripe.Subscription.list(status="all", limit=100, **options).auto_paging_iter():
                sub = resource.to_dict()
                fetched[sub["id"]] = sub
                if sub.get("status") not in _TERMINAL:
                    resolve(sub)
        except Exception:
            error("inventory")
        latest = _utc(session.execute(text("SELECT MAX(created_at) FROM stripe_events")).scalar())
        if any(s.get("status") == "active" for s in fetched.values()) and (latest is None or started - latest > silence_threshold):
            finding("webhook_silence", last_received_at=latest.isoformat() if latest else None,
                    threshold_seconds=int(silence_threshold.total_seconds()))
    except Exception:
        error("run")
    result["counts"]["subscriptions_checked"] = len(fetched)
    result["finished_at"] = (started if now is not None else _utc(datetime.now(timezone.utc))).isoformat()
    return _publish(result)
