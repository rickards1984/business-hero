"""
Xero OAuth token management for Business Hero.
Handles token refresh and encrypted storage, following the same pattern
as oauth_utils.py (used for Google/Microsoft email OAuth).
"""

import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple

import httpx

from email_utils import encrypt_value, decrypt_value

_logger = logging.getLogger("xero_oauth")

XERO_AUTH_URL = "https://login.xero.com/identity/connect/authorize"
XERO_TOKEN_URL = "https://identity.xero.com/connect/token"


def get_xero_auth_url(business_id: str, redirect_uri: str) -> str:
    """
    Build the Xero OAuth2 authorization URL.
    
    Args:
        business_id: The business ID to encode in state parameter
        redirect_uri: The callback URL registered with Xero
        
    Returns:
        Full authorization URL to redirect the user to
    """
    client_id = os.getenv("XERO_CLIENT_ID")
    scopes = os.getenv(
        "XERO_SCOPES",
        "openid profile email accounting.transactions.read accounting.contacts.read offline_access"
    )

    state = encrypt_value(business_id)

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scopes,
        "state": state,
    }

    query_string = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{XERO_AUTH_URL}?{query_string}"
    _logger.info(f"Generated Xero auth URL for business {business_id}")
    return url


async def exchange_code_for_tokens(code: str, redirect_uri: str) -> dict:
    """
    Exchange an authorization code for access + refresh tokens.
    
    Args:
        code: The authorization code from Xero callback
        redirect_uri: Must match the redirect_uri used in the auth request
        
    Returns:
        Token response dict with access_token, refresh_token, expires_in, etc.
    """
    client_id = os.getenv("XERO_CLIENT_ID")
    client_secret = os.getenv("XERO_CLIENT_SECRET")

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            XERO_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "client_secret": client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if resp.status_code != 200:
            _logger.error(f"Xero token exchange failed: {resp.status_code} {resp.text}")
            raise Exception(f"Xero token exchange failed: {resp.text}")

        tokens = resp.json()
        _logger.info("Successfully exchanged Xero auth code for tokens")
        return tokens


def refresh_xero_token(refresh_token: str) -> Tuple[str, str, int]:
    """
    Refresh an expired Xero access token.
    
    Args:
        refresh_token: The current refresh token (decrypted)
        
    Returns:
        Tuple of (new_access_token, new_refresh_token, expires_in_seconds)
    """
    client_id = os.getenv("XERO_CLIENT_ID")
    client_secret = os.getenv("XERO_CLIENT_SECRET")

    resp = httpx.post(
        XERO_TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15.0,
    )

    if resp.status_code != 200:
        _logger.error(f"Xero token refresh failed: {resp.status_code} {resp.text}")
        raise Exception(f"Xero token refresh failed: {resp.text}")

    data = resp.json()
    _logger.info("Successfully refreshed Xero access token")

    return (
        data["access_token"],
        data.get("refresh_token", refresh_token),
        data.get("expires_in", 1800),
    )


def get_valid_xero_access_token(xero_connection) -> str:
    """
    Get a valid (non-expired) Xero access token from a XeroConnection record.
    If the token is expired, refreshes it and returns the updated values
    that the caller should persist back to the database.
    
    This mirrors the pattern in oauth_utils.py -> get_valid_access_token().
    
    Args:
        xero_connection: A XeroConnection model instance with encrypted tokens
        
    Returns:
        Valid access token string (decrypted)
        
    Side effects:
        If token was refreshed, updates the xero_connection object's fields in-place:
            - token_ciphertext
            - refresh_token_ciphertext
            - token_expires_at
            - updated_at
        The caller is responsible for committing these changes to the database.
    """
    access_token = decrypt_value(xero_connection.token_ciphertext)
    refresh_token = decrypt_value(xero_connection.refresh_token_ciphertext)

    now = datetime.now(timezone.utc)
    expires_at = xero_connection.token_expires_at

    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if now < (expires_at - timedelta(minutes=2)):
        return access_token

    _logger.info(f"Xero token expired for business {xero_connection.business_id}, refreshing...")
    new_access, new_refresh, expires_in = refresh_xero_token(refresh_token)

    xero_connection.token_ciphertext = encrypt_value(new_access)
    xero_connection.refresh_token_ciphertext = encrypt_value(new_refresh)
    xero_connection.token_expires_at = now + timedelta(seconds=expires_in)
    xero_connection.updated_at = now

    _logger.info(f"Xero token refreshed, new expiry: {xero_connection.token_expires_at}")
    return new_access
