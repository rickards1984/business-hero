"""OUT-19 — what outreach earns against what it costs.

Mike's prices (25 Oct 2026), to be checked against real costs during his own
month as a customer and adjusted from that evidence:
  * the first brand is included in the Business plan (£269);
  * each extra brand is £79 a month;
  * on Pro (and Starter with the add-on) the first brand is £99 a month.
A brand's AI cost is set against that price; a business whose outreach AI
costs more than its outreach revenue is flagged as losing money.

Two honest limits, stated on the report itself (Codex OUT-19 review 1):
  * revenue is PROJECTED from each business's current plan and the brands it
    had by the end of the period — not invoices (Stripe billing for brands is
    OUT-19 part F);
  * the margin is the INCREMENTAL outreach margin. A Business plan's included
    brand carries £0 of outreach revenue, so any of its AI cost shows as a
    loss there; that is not the whole account's profitability.
"""
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from services.chase_replies import _parse
from services.metering import month_bounds
import json

from sqlalchemy import text

from services import ai_costs

EXTRA_BRAND_PENCE = 7900
ADDON_FIRST_BRAND_PENCE = 9900
INCLUDES_FIRST_BRAND = {"business", "beta"}


def brand_prices(plan_tier, brand_ids: list) -> dict:
    """brand id -> (monthly price in pence, included in the plan?), oldest brand first."""
    out = {}
    for i, bid in enumerate(brand_ids):
        if i == 0:
            out[bid] = (0, True) if (plan_tier or "").lower() in INCLUDES_FIRST_BRAND else (ADDON_FIRST_BRAND_PENCE, False)
        else:
            out[bid] = (EXTRA_BRAND_PENCE, False)
    return out


def _outreach_on(plan_tier, flags) -> bool:
    from auth import _plan_feature_defaults
    flags = flags if isinstance(flags, dict) else json.loads(flags or "{}")
    if "outreach" in flags:
        return bool(flags["outreach"])
    return bool(_plan_feature_defaults(plan_tier).get("outreach", False))


def _before(created, end: datetime) -> bool:
    try:
        moment = _parse(created)
    except ValueError:
        moment = None
    if moment is None:
        return False   # unknown creation time: no revenue is projected for it
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment < end


def report(session, *, period: str) -> dict:
    """Each business with outreach or AI cost this period: its brands' cost and
    price, revenue, cost, margin, and whether it is losing money."""
    ledger = ai_costs.economics(session, period=period)
    spend = ledger["businesses"]
    rows = []
    # Brands existing by the end of the UK month: midnight London time, compared
    # as instants, so a brand made at 00:30 BST on the 1st belongs to that
    # month, whatever the database's timezone (Codex OUT-19 review 2).
    following = month_bounds(date.fromisoformat(period + "-01"))[1]
    end = datetime(following.year, following.month, 1, tzinfo=ZoneInfo("Europe/London"))
    for bid, name, plan_tier, flags in session.execute(text(
            "SELECT id, name, plan_tier, feature_flags FROM businesses ORDER BY name")).fetchall():
        bid = str(bid)
        on, cost = _outreach_on(plan_tier, flags), spend.get(bid)
        if not on and not cost:
            continue
        brands = [(b_id, b_name) for b_id, b_name, created in session.execute(text(
            "SELECT id, name, created_at FROM outreach_brands WHERE business_id = :b ORDER BY created_at, id"),
            {"b": bid}).fetchall() if _before(created, end)]
        prices = brand_prices(plan_tier, [str(b[0]) for b in brands]) if on else {}
        by_brand = (cost or {}).get("by_brand", {})
        brand_rows = [{"id": str(b_id), "name": b_name, "cost_pence": round(by_brand.get(str(b_id), 0), 2),
                       "price_pence": prices.get(str(b_id), (0, False))[0],
                       "included": prices.get(str(b_id), (0, False))[1]} for b_id, b_name in brands]
        revenue = sum(p for p, _ in prices.values())
        total = round((cost or {}).get("total_pence", 0), 2)
        rows.append({"business_id": bid, "name": name, "plan_tier": plan_tier, "outreach": on, "brands": brand_rows,
                     "revenue_pence": revenue, "cost_pence": total, "margin_pence": round(revenue - total, 2),
                     "losing_money": total > revenue, "by_purpose": (cost or {}).get("by_purpose", {}),
                     "models": (cost or {}).get("models", {})})
    return {"period": period, "businesses": rows,
            "revenue_basis": "Projected from each business's current plan and the brands it had by the end of the month; not invoices.",
            "margin_basis": "Incremental outreach margin: a Business plan's included brand has £0 outreach revenue.",
            "losing_money": [r["business_id"] for r in rows if r["losing_money"]],
            "platform_cost_pence": round(sum(r["cost_pence"] for r in rows), 2),
            "platform_revenue_pence": sum(r["revenue_pence"] for r in rows),
            "alarm_pence": ledger["alarm_pence"], "kill_pence": ledger["kill_pence"]}
