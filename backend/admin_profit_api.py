"""PROFIT-1: Mike's view of this month's running costs against income, the
alarm and the kill switch, and which businesses cost more than they pay.
PROFIT-2: the itemised running costs and real Stripe income.
Platform admins only."""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from auth import get_platform_admin_context
from db import get_session
from services import profit_guard, running_costs, stripe_income
from services.aria_actions import ActionRefused

router = APIRouter(prefix="/v1/admin/profit", tags=["Admin"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.get("")
def profit(auth_ctx: dict = Depends(get_platform_admin_context), session: Session = Depends(get_session)):
    return profit_guard.status(session, moment=_now())


@router.get("/costs")
def cost_items(period: Optional[str] = None, auth_ctx: dict = Depends(get_platform_admin_context),
               session: Session = Depends(get_session)):
    """The month's bills (its own list, or the one it carries forward)."""
    from services.metering import period_for
    period = period or period_for(_now())
    try:
        running_costs._check_period(period, _now())
    except ActionRefused as exc:
        raise HTTPException(exc.status_code, exc.detail) from None
    total, source = running_costs.fixed_total(session, period)
    return {"period": period, "items": running_costs.items(session, period), "total_pence": total, "source": source}


class Bill(BaseModel):
    period: str
    name: str
    pence: Optional[int] = None


def _write(session, fn, *args):
    try:
        out = fn(session, *args, moment=_now())
        session.commit()
        return out
    except ActionRefused as exc:
        session.rollback()
        raise HTTPException(exc.status_code, exc.detail) from None


@router.put("/costs")
def put_cost(body: Bill, auth_ctx: dict = Depends(get_platform_admin_context), session: Session = Depends(get_session)):
    if body.pence is None:
        raise HTTPException(422, "A bill needs an amount.")
    return _write(session, running_costs.set_item, body.period, body.name, body.pence)


@router.delete("/costs")
def delete_cost(body: Bill, auth_ctx: dict = Depends(get_platform_admin_context), session: Session = Depends(get_session)):
    return _write(session, running_costs.remove_item, body.period, body.name)


@router.post("/refresh-income")
def refresh_income(auth_ctx: dict = Depends(get_platform_admin_context), session: Session = Depends(get_session)):
    """Read every business's paid invoices from Stripe and record any new ones."""
    try:
        out = stripe_income.refresh(session)
        session.commit()
        return out
    except Exception:
        session.rollback()
        raise HTTPException(502, "Stripe couldn't be read just now. Please try again.") from None
