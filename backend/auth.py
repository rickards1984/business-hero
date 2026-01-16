"""Authentication dependencies for FastAPI."""

import os
from typing import Optional
from fastapi import Header, HTTPException, Depends, Request, Query, status
from fastapi.security import APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials
from sqlmodel import Session, select
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
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(supabase_bearer)
) -> str:
    """Extract and return the Supabase access token from Authorization header.
    
    Used for AI Assistant endpoints that require Supabase JWT authentication.
    Raises 401 if no token is provided.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header"
        )
    return credentials.credentials


async def get_user_business_context(
    request: Request,
    token: str = Depends(get_access_token),
    business_id: Optional[str] = Query(default=None),
) -> dict:
    """Return user_id and business_id from a Supabase JWT.

    If business_id is provided, verify user membership for that business.
    """
    user = await verify_supabase_token(token)
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
    return {"user_id": user.id, "business_id": business_ctx.id}


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
