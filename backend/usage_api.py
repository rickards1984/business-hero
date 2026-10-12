"""Usage and metering settings — BH-012 (RC1 P0-2).

GET  /v1/usage           what has been used this month, what is left, and
                         whether new calls are being answered (the in-app
                         banner reads `state`). The caller's business only.
PUT  /v1/usage/metering  switch extra minutes on or off, with a monthly cap.

`businesses.metered_usage_enabled` and `monthly_spend_cap_gbp` are writable
only here, on the backend: clients hold SELECT only on `businesses` since
030b Release 2, so an owner cannot raise their own cap from the browser.
"""

from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlmodel import Session

from auth import get_user_business_context, require_feature
from db import get_session
from services import metering

router = APIRouter(prefix="/v1/usage", tags=["Usage"])


def _load_business(session: Session, business_id: str):
    return metering.load_business(session, business_id)


def _save_metering_settings(session: Session, business_id: str, enabled: bool,
                            cap: Optional[Decimal]) -> None:
    session.execute(
        text("UPDATE businesses SET metered_usage_enabled = :enabled, "
             "monthly_spend_cap_gbp = :cap WHERE id = :business_id"),
        {"enabled": enabled, "cap": cap, "business_id": business_id},
    )
    session.commit()


def _one_dp(value: Decimal) -> str:
    return f"{value:.1f}"


def _view(u: dict) -> dict:
    return {
        "period": u["period"],
        "allowance_minutes": f"{u['allowance_minutes']:.0f}",
        "used_minutes": _one_dp(u["used_minutes"]),
        "remaining_minutes": _one_dp(u["remaining_minutes"]),
        "overage_minutes": _one_dp(u["overage_minutes"]),
        "overage_spend_gbp": f"{u['overage_spend_gbp']:.2f}",
        "overage_rate_gbp": f"{u['overage_rate_gbp']:.2f}",
        "metered_usage_enabled": u["metered_usage_enabled"],
        "spend_cap_gbp": f"{u['spend_cap_gbp']:.2f}",
        "state": u["state"],
    }


@router.get("")
async def get_usage(
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    business = _load_business(session, str(auth_ctx["business_id"]))
    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")
    return _view(metering.usage(session, business))


class MeteringSettings(BaseModel):
    enabled: bool
    monthly_spend_cap_gbp: Any = None


@router.put("/metering", dependencies=[Depends(require_feature("receptionist"))])
async def set_metering(
    settings: MeteringSettings,
    auth_ctx: dict = Depends(get_user_business_context),
    session: Session = Depends(get_session),
):
    business_id = str(auth_ctx["business_id"])
    business = _load_business(session, business_id)
    if business is None:
        raise HTTPException(status_code=404, detail="Business not found")

    cap: Optional[Decimal]
    if settings.monthly_spend_cap_gbp in (None, ""):
        cap = (metering.DEFAULT_SPEND_CAP_GBP if settings.enabled
               else getattr(business, "monthly_spend_cap_gbp", None))
    else:
        try:
            cap = Decimal(str(settings.monthly_spend_cap_gbp))
        except (InvalidOperation, ValueError):
            raise HTTPException(status_code=422, detail="The cap must be an amount in pounds")
        if not cap.is_finite() or cap <= 0:
            raise HTTPException(status_code=422, detail="The cap must be more than £0")
        if cap > metering.MAX_SPEND_CAP_GBP:
            raise HTTPException(status_code=422,
                                detail=f"The cap cannot be more than £{metering.MAX_SPEND_CAP_GBP:,.0f}")
        if cap.as_tuple().exponent < -2:
            raise HTTPException(status_code=422, detail="The cap must be in pounds and pence")

    _save_metering_settings(session, business_id, settings.enabled, cap)
    business.metered_usage_enabled = settings.enabled
    business.monthly_spend_cap_gbp = cap
    return _view(metering.usage(session, business))
