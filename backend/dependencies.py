"""
Shared FastAPI dependencies for Business Hero API.
Extracted to avoid circular imports between main.py and feature routers.
"""

from fastapi import Depends, HTTPException, Request, status
from sqlmodel import Session, select

from db import get_session
from models import Business
from auth import enforce_read_only, get_access_token, is_platform_admin_user
from supabase_auth import verify_supabase_token
from assistant_chat import get_business_for_user


async def get_current_user_business(
    token: str = Depends(get_access_token),
    session: Session = Depends(get_session)
) -> Business:
    """Get current business from Supabase JWT token.
    
    For user-facing endpoints (dashboard, mobile app) that use Supabase auth.
    Validates JWT and looks up user's business via business_members table.
    """
    user = await verify_supabase_token(token)
    
    try:
        business_ctx = get_business_for_user(user.id)
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
    
    statement = select(Business).where(Business.id == business_ctx.id)
    business = session.exec(statement).first()
    
    if not business:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Business not found"
        )
    
    return business


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

    try:
        business_ctx = get_business_for_user(user.id)
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

    statement = select(Business).where(Business.id == business_ctx.id)
    business = session.exec(statement).first()

    if not business:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Business not found"
        )

    if not is_platform_admin_user(user.id, session):
        enforce_read_only(request, business)

    return user, business
