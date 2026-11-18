"""
Shared FastAPI dependencies for Business Hero API.
Extracted to avoid circular imports between main.py and feature routers.
"""

from fastapi import Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from sqlmodel import Session, select

from db import get_session
from models import Business
from auth import enforce_access, get_access_token, is_platform_admin_user
from supabase_auth import verify_supabase_token
from assistant_chat import get_business_for_user


async def get_current_user_business(
    request: Request,
    token: str = Depends(get_access_token),
    session: Session = Depends(get_session)
) -> Business:
    """Get current business from Supabase JWT token.

    For user-facing endpoints (dashboard, mobile app) that use Supabase auth.
    Validates JWT and looks up user's business via business_members table.

    Also enforces DECISION 3's access levels. THIS DEPENDENCY WAS THE HOLE:
    the first version of BH-006 guarded `auth.get_user_business_context` and
    `get_current_user_and_business` and claimed every authenticated endpoint
    resolved through one of them. It does not — 31 endpoints use this one,
    including create/edit/delete for tasks and calls, business settings,
    integrations, the logo and brand colour, invoice import, and the whole
    receptionist config and knowledge base. Codex enumerated them. A read-only
    business could write through every one.
    """
    user = await verify_supabase_token(token)
    return await run_in_threadpool(_owned_business, request, user, session)


async def get_current_user_and_business(
    request: Request,
    token: str = Depends(get_access_token),
    session: Session = Depends(get_session)
):
    """Get current Supabase user and business from JWT token.

    Also enforces DECISION 3's read-only state, exactly as
    `auth.get_user_business_context` does — these are the two dependencies
    every authenticated endpoint resolves through, and enforcing in only one
    of them would leave 26 endpoints (quoting, invoicing, accounting) open to
    a non-paying customer's writes.
    """
    user = await verify_supabase_token(token)
    return user, await run_in_threadpool(_owned_business, request, user, session)


def _load_business_row(session: Session, business_id) -> Business:
    return session.exec(select(Business).where(Business.id == business_id)).first()


def _owned_business(request: Request, user, session: Session) -> Business:
    """STAB-1: both dependencies' database work, off the event loop and on the
    request's own connection: one connection, never two. Production ran out of
    them on 18 Nov 2026, and the wait, in the loop, froze every request."""
    try:
        business_ctx = get_business_for_user(user.id, session=session)
    except ValueError as e:
        args = e.args
        if len(args) >= 2:
            error_type, message = args[0], args[1]
            if error_type == "NO_BUSINESS":
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
            elif error_type == "FORBIDDEN":
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message)
            elif error_type == "NOT_FOUND":
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    business = _load_business_row(session, business_ctx.id)
    if not business:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Business not found"
        )

    if not is_platform_admin_user(user.id, session):
        enforce_access(request, business)

    return business
