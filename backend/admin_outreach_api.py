"""OUT-19: Mike's view of what outreach costs and earns, per business and brand.
Platform admins only."""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from auth import get_platform_admin_context
from db import get_session
from services import outreach_pricing
from services.metering import period_for

router = APIRouter(prefix="/v1/admin/outreach", tags=["Admin"])


@router.get("/economics")
def economics(period: Optional[str] = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
              auth_ctx: dict = Depends(get_platform_admin_context), session: Session = Depends(get_session)):
    return outreach_pricing.report(session, period=period or period_for(datetime.now(timezone.utc)))
