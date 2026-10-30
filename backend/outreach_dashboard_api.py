"""OUT-14: the outreach dashboard's endpoints (docs/OUT-14-TICKET.md)."""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import Session

import auth
from auth import get_user_business_context
from db import get_session
from rate_limiting import limiter
from services import outreach_dashboard as dashboard
from services.aria_actions import ActionRefused

router = APIRouter(prefix="/v1/outreach/dashboard", tags=["Outreach"])


def _business(session, context):
    business = auth._load_business(session, context["business_id"])
    auth.assert_feature_access(business, "outreach", retained_history=True)   # reading history
    return business


def _refused(session, exc: ActionRefused):
    session.rollback()
    return HTTPException(exc.status_code, exc.detail)


@router.get("")
def dashboard_view(brand_id: Optional[UUID] = None, period: str = "week",
                   context=Depends(get_user_business_context), session: Session = Depends(get_session)):
    """Pipeline, results for the period, Needs you and Aria's summary; spend
    for the owner only (Mike, 30 Oct 2026)."""
    from services import aria_actions
    business = _business(session, context)
    owner = aria_actions._is_active_owner(session, business, context["user_id"])
    try:
        return dashboard.build(session, business, brand_id=str(brand_id) if brand_id else None, period=period,
                               moment=dashboard.now(), include_spend=bool(owner))
    except ActionRefused as exc:
        raise _refused(session, exc) from None


@router.get("/stage/{stage}")
def dashboard_stage(stage: str, brand_id: Optional[UUID] = None, limit: int = 20, offset: int = 0,
                    context=Depends(get_user_business_context), session: Session = Depends(get_session)):
    business = _business(session, context)
    try:
        return dashboard.stage_list(session, str(business.id), stage, brand_id=str(brand_id) if brand_id else None,
                                    limit=limit, offset=offset)
    except ActionRefused as exc:
        raise _refused(session, exc) from None


class Outcome(BaseModel):
    outcome: Optional[str] = None


@router.post("/prospects/{prospect_id}/outcome")
@limiter.limit("30/minute")
def dashboard_outcome(request: Request, prospect_id: UUID, body: Outcome,
                      context=Depends(get_user_business_context), session: Session = Depends(get_session)):
    """The owner marks a meeting, a win or a close, or undoes it."""
    business = _business(session, context)
    try:
        return dashboard.mark_outcome(session, business, context["user_id"], str(prospect_id), body.outcome,
                                      moment=dashboard.now())
    except ActionRefused as exc:
        raise _refused(session, exc) from None
