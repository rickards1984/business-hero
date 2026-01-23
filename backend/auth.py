"""Authentication dependencies for FastAPI."""

import os
from typing import Optional, Dict
from datetime import datetime, timezone
from fastapi import Header, HTTPException, Depends, Request, Query, status
from fastapi.security import APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials
from sqlmodel import Session, select
from sqlalchemy import text
from db import get_session
from models import Business
from supabase_auth import verify_supabase_token
from assistant_chat import get_business_for_user

api_key_header = APIKeyHeader(name="x-api-key", auto_error=False)
master_key_header = APIKeyHeader(name="x-master-key", auto_error=False)
bearer_auth = HTTPBearer(auto_error=False)
supabase_bearer = HTTPBearer(auto_error=False, description="Supabase access token for AI Assistant endpoints")


def extract_token(auth_header: Optional[str]) -> Optional[str]:
    """Extract token from Authorization header.
    
    Handles both 'Bearer <token>' and plain '<token>' formats.
    """
    if not auth_header:
        return None
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return auth_header


def get_master_key() -> str:
    """Get the master admin key from environment."""
    key = os.getenv("MASTER_ADMIN_KEY")
    if not key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="MASTER_ADMIN_KEY not configured"
        )
    return key


async def verify_master_key(
    x_master_key: Optional[str] = Depends(master_key_header),
    authorization: Optional[HTTPAuthorizationCredentials] = Depends(bearer_auth),
    auth_header: Optional[str] = Header(None, alias="Authorization")
) -> bool:
    """Verify the master admin key.
    
    Accepts either:
    - x-master-key header
    - Authorization: Bearer <MASTER_ADMIN_KEY>
    - Authorization: <MASTER_ADMIN_KEY>
    """
    token = None
    
    if x_master_key:
        token = x_master_key
    elif authorization:
        token = authorization.credentials
    elif auth_header:
        token = extract_token(auth_header)
    
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication. Use x-master-key header or Authorization: Bearer <key>"
        )
    
    master_key = get_master_key()
    if token != master_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid master key"
        )
    return True


async def get_access_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(supabase_bearer),
    access_token: Optional[str] = Query(default=None),
    token: Optional[str] = Query(default=None),
) -> str:
    """Extract and return the Supabase access token from Authorization header.
    
    Used for AI Assistant endpoints that require Supabase JWT authentication.
    Raises 401 if no token is provided.
    """
    if credentials:
        return credentials.credentials
    if access_token:
        return access_token
    if token:
        return token
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header or access_token query param"
        )
    return credentials.credentials


async def get_user_business_context(
    request: Request,
    token: str = Depends(get_access_token),
    business_id: Optional[str] = Query(default=None),
    session: Session = Depends(get_session),
) -> dict:
    """Return user_id and business_id from a Supabase JWT.

    If business_id is provided, verify user membership for that business.
    """
    user = await verify_supabase_token(token)
    is_platform_admin = is_platform_admin_user(user.id, session)
    if is_platform_admin:
        request.state.user_email = user.email
        if business_id:
            return {
                "user_id": user.id,
                "business_id": business_id,
                "is_platform_admin": True,
            }
        try:
            business_ctx = get_business_for_user(user.id)
        except ValueError as exc:
            args = exc.args
            if len(args) >= 2 and args[0] == "NO_BUSINESS":
                return {
                    "user_id": user.id,
                    "business_id": None,
                    "is_platform_admin": True,
                }
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
        return {
            "user_id": user.id,
            "business_id": business_ctx.id,
            "is_platform_admin": True,
        }
    try:
        business_ctx = get_business_for_user(user.id, requested_business_id=business_id)
    except ValueError as exc:
        args = exc.args
        if len(args) >= 2:
            error_type, message = args[0], args[1]
            if error_type == "NO_BUSINESS":
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
            if error_type == "FORBIDDEN":
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message)
            if error_type == "NOT_FOUND":
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    request.state.user_email = user.email
    return {"user_id": user.id, "business_id": business_ctx.id, "is_platform_admin": False}


async def get_current_business(
    x_api_key: Optional[str] = Depends(api_key_header),
    authorization: Optional[HTTPAuthorizationCredentials] = Depends(bearer_auth),
    auth_header: Optional[str] = Header(None, alias="Authorization"),
    session: Session = Depends(get_session)
) -> Business:
    """Get the current business from API key.
    
    Accepts either:
    - x-api-key header
    - Authorization: Bearer <business_api_key>
    - Authorization: <business_api_key>
    """
    token = None
    
    if x_api_key:
        token = x_api_key
    elif authorization:
        token = authorization.credentials
    elif auth_header:
        token = extract_token(auth_header)
    
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication. Use x-api-key header or Authorization: Bearer <key>"
        )
    
    statement = select(Business).where(Business.api_key == token)
    business = session.exec(statement).first()
    
    if not business:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key"
        )
    
    return business


def is_platform_admin_user(user_id: str, session: Session) -> bool:
    result = session.exec(
        text("SELECT 1 FROM platform_admins WHERE user_id = :user_id LIMIT 1"),
        {"user_id": user_id},
    ).first()
    return result is not None


def _is_trial_expired(trial_ends_at: Optional[datetime]) -> bool:
    if not trial_ends_at:
        return True
    if trial_ends_at.tzinfo is None:
        return trial_ends_at < datetime.utcnow()
    return trial_ends_at < datetime.now(timezone.utc)


def _plan_feature_defaults(plan_tier: Optional[str]) -> Dict[str, bool]:
    defaults = {
        "starter": {},
        "pro": {"email": True},
        "elite": {"email": True, "calendar": True, "voice": True},
        "beta": {"email": True, "calendar": True, "voice": True},
        "paused": {},
    }
    return defaults.get((plan_tier or "starter").lower(), {})


def _is_feature_enabled(business: Business, feature_name: str) -> bool:
    flags = business.feature_flags or {}
    if feature_name in flags:
        return bool(flags.get(feature_name))
    plan_defaults = _plan_feature_defaults(business.plan_tier)
    return bool(plan_defaults.get(feature_name, False))


def require_feature(feature_name: str):
    async def _dependency(
        auth_ctx: dict = Depends(get_user_business_context),
        session: Session = Depends(get_session),
    ):
        if is_platform_admin_user(auth_ctx["user_id"], session):
            return True
        business = session.exec(
            select(Business).where(Business.id == auth_ctx["business_id"])
        ).first()
        if not business:
            raise HTTPException(status_code=404, detail="Business not found")
        if not business.is_active and _is_trial_expired(business.trial_ends_at):
            raise HTTPException(
                status_code=403,
                detail="Account inactive or trial expired"
            )
        if not _is_feature_enabled(business, feature_name):
            raise HTTPException(
                status_code=403,
                detail=f"Feature '{feature_name}' not enabled for your plan"
            )
        return True

    return _dependency
