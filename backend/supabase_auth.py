"""Supabase authentication helpers for verifying user tokens."""

import os
import httpx
from typing import Optional
from dataclasses import dataclass
from fastapi import HTTPException, status

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")


@dataclass
class SupabaseUser:
    """Authenticated Supabase user."""
    id: str
    email: Optional[str]


async def verify_supabase_token(access_token: str) -> SupabaseUser:
    """Verify a Supabase access token and return the user info.
    
    Args:
        access_token: The JWT access token from Supabase Auth
        
    Returns:
        SupabaseUser with id and email
        
    Raises:
        HTTPException: If token is invalid or verification fails
    """
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Supabase configuration missing"
        )
    
    url = f"{SUPABASE_URL.rstrip('/')}/auth/v1/user"
    headers = {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {access_token}"
    }
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers)
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Failed to verify token: {str(e)}"
            )
    
    if response.status_code == 401:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )
    
    if response.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token verification failed"
        )
    
    data = response.json()
    user_id = data.get("id")
    email = data.get("email")
    
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user data in token"
        )
    
    return SupabaseUser(id=user_id, email=email)


def get_service_role_headers() -> dict:
    """Get headers for service role API calls to Supabase."""
    return {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json"
    }
