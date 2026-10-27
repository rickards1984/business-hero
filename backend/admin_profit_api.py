"""PROFIT-1: Mike's view of this month's running costs against income, the
alarm and the kill switch, and which businesses cost more than they pay.
Platform admins only."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlmodel import Session

from auth import get_platform_admin_context
from db import get_session
from services import profit_guard

router = APIRouter(prefix="/v1/admin/profit", tags=["Admin"])


@router.get("")
def profit(auth_ctx: dict = Depends(get_platform_admin_context), session: Session = Depends(get_session)):
    return profit_guard.status(session, moment=datetime.now(timezone.utc))
