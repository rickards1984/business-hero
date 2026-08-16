"""
Xero OAuth token management for Business Hero.
Handles token refresh and encrypted storage, following the same pattern
as oauth_utils.py (used for Google/Microsoft email OAuth).
"""

import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Tuple

import httpx

from email_utils import encrypt_str, decrypt_str

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
        "openid profile email accounting.transactions.read accounting.contacts.read accounting.reports.read accounting.settings.read offline_access"
    )

    state = encrypt_str(business_id)

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


async def refresh_and_persist_xero_token(session, xero_connection_id: str, business_id: str) -> str:
    """
    THE ONLY function that should refresh Xero tokens. Reads from xero_connections
    (the primary source) and writes to BOTH xero_connections and accounting_connections
    atomically. Goes through the coordinated_token_refresh lock to prevent race conditions.

    Returns the new access token.
    """
    from sqlalchemy import text as _text
    from providers.token_refresh_lock import coordinated_token_refresh

    async def get_current_tokens():
        row = session.execute(
            _text("""
                SELECT token_ciphertext, refresh_token_ciphertext, token_refreshed_at
                FROM xero_connections WHERE id = :conn_id
            """),
            {"conn_id": xero_connection_id},
        ).fetchone()
        if not row:
            raise Exception(f"Xero connection {xero_connection_id} not found")
        return {
            "access_token": decrypt_str(row[0]),
            "refresh_token": decrypt_str(row[1]),
            "token_refreshed_at": row[2],
        }

    async def do_refresh(current_refresh_token: str):
        new_access, new_refresh, expires_in = refresh_xero_token(current_refresh_token)
        return {
            "access_token": new_access,
            "refresh_token": new_refresh,
            "expires_in": expires_in,
        }

    _last_expires_in = [1800]

    async def _do_refresh_wrapper(current_refresh_token: str):
        result = await do_refresh(current_refresh_token)
        _last_expires_in[0] = result.get("expires_in", 1800)
        return {"access_token": result["access_token"], "refresh_token": result["refresh_token"]}

    async def save_tokens(new_access: str, new_refresh: str, refreshed_at: datetime):
        encrypted_access = encrypt_str(new_access)
        encrypted_refresh = encrypt_str(new_refresh)
        expires_at = refreshed_at + timedelta(seconds=_last_expires_in[0])

        # Update xero_connections (PRIMARY source of truth)
        session.execute(
            _text("""
                UPDATE xero_connections
                SET token_ciphertext = :token,
                    refresh_token_ciphertext = :refresh,
                    token_expires_at = :expires_at,
                    token_refreshed_at = :refreshed_at,
                    updated_at = NOW()
                WHERE id = :conn_id
            """),
            {
                "token": encrypted_access,
                "refresh": encrypted_refresh,
                "expires_at": expires_at,
                "refreshed_at": refreshed_at,
                "conn_id": xero_connection_id,
            },
        )

        # ALSO update accounting_connections (keeps provider-agnostic layer in sync)
        try:
            session.execute(
                _text("""
                    UPDATE accounting_connections
                    SET token_ciphertext = :token,
                        refresh_token_ciphertext = :refresh,
                        token_expires_at = :expires_at,
                        token_refreshed_at = :refreshed_at,
                        updated_at = NOW()
                    WHERE business_id = :business_id AND provider = 'xero'
                """),
                {
                    "token": encrypted_access,
                    "refresh": encrypted_refresh,
                    "expires_at": expires_at,
                    "refreshed_at": refreshed_at,
                    "business_id": business_id,
                },
            )
        except Exception:
            _logger.warning(f"Failed to dual-write token to accounting_connections for business {business_id}")

        session.commit()

    return await coordinated_token_refresh(
        business_id=business_id,
        provider_name="xero",
        get_current_tokens=get_current_tokens,
        do_refresh=_do_refresh_wrapper,
        save_tokens=save_tokens,
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
    access_token = decrypt_str(xero_connection.token_ciphertext)
    refresh_token = decrypt_str(xero_connection.refresh_token_ciphertext)

    now = datetime.now(timezone.utc)
    expires_at = xero_connection.token_expires_at

    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if now < (expires_at - timedelta(minutes=2)):
        return access_token

    _logger.info(f"Xero token expired for business {xero_connection.business_id}, refreshing...")
    new_access, new_refresh, expires_in = refresh_xero_token(refresh_token)

    xero_connection.token_ciphertext = encrypt_str(new_access)
    xero_connection.refresh_token_ciphertext = encrypt_str(new_refresh)
    xero_connection.token_expires_at = now + timedelta(seconds=expires_in)
    xero_connection.updated_at = now

    _logger.info(f"Xero token refreshed, new expiry: {xero_connection.token_expires_at}")
    return new_access
