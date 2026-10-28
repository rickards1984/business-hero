"""OUT-19 B + C — each brand's hidden AI allowance, and the owner's budget.

Mike, 27 Oct 2026 ("go with the recommendations; review when live"; "as long
as we are always looking at a net profit for all transactions"):

B. A brand may spend on AI a quarter of what it pays: the Pro add-on £99 →
   £24.75 a month, an extra brand £79 → £19.75; a Business plan's included
   brand has a fixed £20. A top-up (part F) adds a third of its price for its
   month (top-ups are priced at cost × 3). Every AI cost of the brand counts
   (research, Aria's drafting, reply sorting) from the OUT-19 ledger, research
   reservations in flight included. At the allowance research stops; Aria's
   drafting carries on within a small reserve; reply sorting never stops (it
   is never checked here). The owner's research budget can only lower it.

C. One £ figure a month for what outreach may charge beyond the plan (paid
   brands and top-ups). Aria suggests one; only the owner sets it, never below
   what is already committed; every future charge must pass `can_charge`, and
   with no budget set nothing beyond what is committed is charged.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import text

from services import outreach_send as send
from services.metering import period_for

SHARE_PERCENT = 25
INCLUDED_PENCE = 2000
DRAFT_RESERVE_PENCE = 300
TOPUP_SHARE = 3                              # a top-up buys AI at cost × 3
TOPUP_METER = "outreach_topup_pence"          # part F: paid top-ups per brand, per month
BUDGET_KEY = "outreach_budget"                # settings-document key (kept by preserve_automations)
DRAFT_HOLD_METER = "outreach_draft_hold_pence"  # drafts in progress, held before Aria starts (Codex B+C review 1)
SUGGESTED_TOPUP_PENCE = 2500


def allowance_for_price(price_pence: int, *, included: bool) -> int:
    return INCLUDED_PENCE if included else int(price_pence) * SHARE_PERCENT // 100


def _plan(session, bid: str) -> Optional[str]:
    return session.execute(text("SELECT plan_tier FROM businesses WHERE id = :b"), {"b": bid}).scalar()


def _brand_ids(session, bid: str) -> list:
    return [str(r["id"]) for r in send.rows(session, "outreach_brands", bid, "ORDER BY created_at, id")]


def prices(session, bid: str) -> dict:
    """brand id -> (monthly price in pence, included in the plan?), as outreach_pricing projects them."""
    from services import outreach_pricing
    return outreach_pricing.brand_prices(_plan(session, bid), _brand_ids(session, bid))


def _meter(session, bid: str, name: str, period: str) -> float:
    return float(session.execute(text(
        "SELECT coalesce(sum(value), 0) FROM usage_meters WHERE business_id = :b AND meter = :m AND period = :p"),
        {"b": bid, "m": name, "p": period}).scalar() or 0)


def allowance_pence(session, bid: str, brand_id, period: str) -> int:
    price, included = prices(session, str(bid)).get(str(brand_id), (0, False))
    base = allowance_for_price(price, included=included)
    topped = _meter(session, str(bid), f"{TOPUP_METER}:{brand_id}", period)
    return base + int(topped) // TOPUP_SHARE


def _like(text_: str) -> str:
    """A literal LIKE prefix: "_" and "%" in a meter name match only themselves."""
    return text_.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def spent_pence(session, bid: str, brand_id, period: str) -> int:
    """All of a brand's AI spend this month: research as reserved and settled
    (its own meter, which the ledger's research rows mirror, plus the
    business-wide research meter from before OUT-18, which counts against
    every brand: fail closed, Codex B+C review 1), drafts held in progress,
    and every other purpose from the ledger."""
    from services import outreach_research
    research = (_meter(session, str(bid), outreach_research.meter_for(brand_id), period)
                + _meter(session, str(bid), outreach_research.METER, period))
    held = _meter(session, str(bid), f"{DRAFT_HOLD_METER}:{brand_id}", period)
    other = float(session.execute(text(
        "SELECT coalesce(sum(value), 0) FROM usage_meters WHERE business_id = :b AND period = :p "
        "AND meter LIKE :like ESCAPE '\\' AND meter NOT LIKE :research ESCAPE '\\'"),
        {"b": str(bid), "p": period, "like": _like("ai_pence:") + "%" + _like(f":{brand_id}:") + "%",
         "research": _like(f"ai_pence:research:{brand_id}:") + "%"}).scalar() or 0)
    return int(research + held + other)


def used_percent(session, bid: str, brand_id, moment: datetime) -> int:
    period = period_for(moment)
    cap = allowance_pence(session, bid, brand_id, period)
    return 100 if cap <= 0 else min(100, round(100 * spent_pence(session, bid, brand_id, period) / cap))


def may_research(session, bid: str, brand_id, moment: datetime, reserve: int) -> bool:
    period = period_for(moment)
    return spent_pence(session, bid, brand_id, period) + int(reserve) <= allowance_pence(session, bid, brand_id, period)


DRAFT_HOLD_PENCE = 50   # a draft's most likely cost, failover included; held until its real cost is recorded


def draft_hold_pence() -> int:
    import os
    try:
        return max(1, int(os.environ.get("OUTREACH_DRAFT_HOLD_PENCE", DRAFT_HOLD_PENCE)))
    except ValueError:
        return DRAFT_HOLD_PENCE


def may_draft(session, bid: str, brand_id, moment: datetime, hold: int = 0) -> bool:
    if brand_id is None:
        return True
    period = period_for(moment)
    return (spent_pence(session, bid, brand_id, period) + int(hold)
            <= allowance_pence(session, bid, brand_id, period) + DRAFT_RESERVE_PENCE)


def hold_draft(session, bid: str, brand_id, moment: datetime, pence: int) -> None:
    """Add (or, to release, subtract) a draft's hold, in the caller's transaction."""
    from services import outreach_research
    if brand_id is not None and pence:
        outreach_research._add_meter(session, str(bid), f"{DRAFT_HOLD_METER}:{brand_id}", moment, int(pence))


# Top-ups arrive with part F; until then nothing offers them (Codex B+C review 1).
ALLOWANCE_USED = "This brand's AI allowance for the month is used, so research has stopped until next month."
DRAFT_ALLOWANCE_USED = ("This brand's AI allowance for the month is used, so Aria can't draft this until next month. "
                        "Write it yourself for now.")


# ------------------------------------------------------------- C: the budget ---

def _committed(session, bid: str, moment: datetime) -> int:
    """What outreach already charges this month beyond the plan: paid brands
    and the top-ups bought this month."""
    paid = sum(price for price, included in prices(session, bid).values() if not included)
    topups = float(session.execute(text(
        "SELECT coalesce(sum(value), 0) FROM usage_meters WHERE business_id = :b AND period = :p AND meter LIKE :m ESCAPE '\\'"),
        {"b": bid, "p": period_for(moment), "m": _like(f"{TOPUP_METER}:") + "%"}).scalar() or 0)
    return int(paid + topups)


def budget_status(session, business, *, moment: Optional[datetime] = None) -> dict:
    from services import outreach_setup as setup
    bid = str(business.id)
    moment = moment or send.now()
    budget = (setup._settings_doc(session, bid).get(BUDGET_KEY) or {}).get("monthly_pence")
    brands = prices(session, bid)
    out = {"budget_pence": int(budget) if budget is not None else None,
           "committed_pence": _committed(session, bid, moment),
           "suggested_pence": sum(p for p, inc in brands.values() if not inc) + SUGGESTED_TOPUP_PENCE * len(brands)}
    session.rollback()
    return out


def set_budget(session, business, user, data: dict) -> dict:
    from services import outreach_setup as setup
    setup._authority(session, business, user, growth=False)      # the active owner, under the business lock
    bid = str(business.id)
    pence = data.get("monthly_pence")
    send.require(isinstance(pence, int) and not isinstance(pence, bool) and 0 <= pence <= 10_000_000,
                 "Enter the monthly budget in pence", 422)
    committed = _committed(session, bid, send.now())
    send.require(pence >= committed, "The budget can't be below what outreach already charges this month "
                                     f"(£{committed / 100:.2f})", 422)
    doc = setup._settings_doc(session, bid)
    doc[BUDGET_KEY] = {"monthly_pence": pence, "set_by": str(user), "set_at": send.now().isoformat()}
    setup._save_settings_doc(session, bid, doc)
    session.commit()
    return budget_status(session, business)


def can_charge(session, business, pence: int, *, moment: Optional[datetime] = None) -> bool:
    """Whether a further charge of `pence` this month stays within the owner's
    budget. No budget set: nothing beyond what is committed."""
    from services import outreach_setup as setup
    bid = str(business.id)
    moment = moment or send.now()
    budget = (setup._settings_doc(session, bid).get(BUDGET_KEY) or {}).get("monthly_pence")
    if budget is None:
        return False
    return _committed(session, bid, moment) + int(pence) <= int(budget)
