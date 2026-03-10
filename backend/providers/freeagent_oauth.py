"""
FreeAgent OAuth 2.0 implementation.
Follows the same pattern as xero_oauth.py.

FreeAgent OAuth docs: https://dev.freeagent.com/docs/oauth
API base: https://api.freeagent.com/v2
Sandbox:  https://api.sandbox.freeagent.com/v2
"""

import os
import logging
from typing import Tuple

import httpx

from email_utils import encrypt_str, decrypt_str

_logger = logging.getLogger("freeagent_oauth")

FREEAGENT_AUTH_URL = "https://api.freeagent.com/v2/approve_app"
FREEAGENT_TOKEN_URL = "https://api.freeagent.com/v2/token_endpoint"
FREEAGENT_API_BASE = "https://api.freeagent.com/v2"

FREEAGENT_SANDBOX_AUTH_URL = "https://api.sandbox.freeagent.com/v2/approve_app"
FREEAGENT_SANDBOX_TOKEN_URL = "https://api.sandbox.freeagent.com/v2/token_endpoint"
FREEAGENT_SANDBOX_API_BASE = "https://api.sandbox.freeagent.com/v2"


def _is_sandbox() -> bool:
    return os.getenv("FREEAGENT_SANDBOX", "false").lower() == "true"


def _get_auth_url() -> str:
    return FREEAGENT_SANDBOX_AUTH_URL if _is_sandbox() else FREEAGENT_AUTH_URL


def _get_token_url() -> str:
    return FREEAGENT_SANDBOX_TOKEN_URL if _is_sandbox() else FREEAGENT_TOKEN_URL


def get_freeagent_api_base() -> str:
    return FREEAGENT_SANDBOX_API_BASE if _is_sandbox() else FREEAGENT_API_BASE


def get_freeagent_auth_url(business_id: str, redirect_uri: str) -> str:
    """Generate the FreeAgent OAuth authorization URL."""
    client_id = os.getenv("FREEAGENT_CLIENT_ID", "")
    state = encrypt_str(business_id)

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
    }

    query_string = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{_get_auth_url()}?{query_string}"
    _logger.info(f"Generated FreeAgent auth URL for business {business_id}")
    return url


def exchange_freeagent_code_for_tokens(code: str, redirect_uri: str) -> dict:
    """Exchange authorization code for access + refresh tokens."""
    client_id = os.getenv("FREEAGENT_CLIENT_ID", "")
    client_secret = os.getenv("FREEAGENT_CLIENT_SECRET", "")

    resp = httpx.post(
        _get_token_url(),
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        },
        auth=(client_id, client_secret),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15.0,
    )

    if resp.status_code != 200:
        _logger.error(f"FreeAgent token exchange failed: {resp.status_code} {resp.text}")
        raise Exception(f"FreeAgent token exchange failed: {resp.status_code}")

    _logger.info("Successfully exchanged FreeAgent auth code for tokens")
    return resp.json()


def refresh_freeagent_token(refresh_token: str) -> Tuple[str, str, int]:
    """Refresh an expired FreeAgent access token."""
    client_id = os.getenv("FREEAGENT_CLIENT_ID", "")
    client_secret = os.getenv("FREEAGENT_CLIENT_SECRET", "")

    resp = httpx.post(
        _get_token_url(),
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        auth=(client_id, client_secret),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15.0,
    )

    if resp.status_code != 200:
        _logger.error(f"FreeAgent token refresh failed: {resp.status_code} {resp.text}")
        raise Exception(f"FreeAgent token refresh failed: {resp.status_code}")

    data = resp.json()
    _logger.info("Successfully refreshed FreeAgent access token")
    return (
        data["access_token"],
        data.get("refresh_token", refresh_token),
        data.get("expires_in", 3600),
    )


async def get_freeagent_company(access_token: str) -> dict:
    """Fetch the connected company details after OAuth."""
    api_base = get_freeagent_api_base()

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{api_base}/company",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )

    if resp.status_code != 200:
        _logger.error(f"Failed to get FreeAgent company: {resp.status_code}")
        return {}

    data = resp.json()
    return data.get("company", {})
