"""GET /v1/home/summary — the Aria home's figures (NS-B7).

Read-only, the caller's business only. Computed on the server over every
row (services/home_summary.py), with when each source last synced, so the
home can say how fresh a figure is instead of implying it is live.
"""

from fastapi import APIRouter, Depends

from auth import get_user_business_context
from db import engine
from services import home_summary

router = APIRouter(prefix="/v1/home", tags=["Home"])


@router.get("/summary")
def get_home_summary(auth_ctx: dict = Depends(get_user_business_context)):
    with engine.connect() as conn:
        return home_summary.summary(conn, str(auth_ctx["business_id"]))
