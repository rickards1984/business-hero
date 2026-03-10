"""
QuickBooks Online OAuth 2.0 implementation.
Follows the same pattern as xero_oauth.py.

QuickBooks OAuth docs:
  https://developer.intuit.com/app/developer/qbo/docs/develop/authentication-and-authorization
API base (production): https://quickbooks.api.intuit.com/v3
API base (sandbox):    https://sandbox-quickbooks.api.intuit.com/v3
"""

import base64
import logging
import os
from typing import Tuple

import httpx

from email_utils import encrypt_str, decrypt_str

_logger = logging.getLogger("quickbooks_oauth")

QB_AUTH_URL = "https://appcenter.intuit.com/connect/oauth2"
QB_TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
QB_API_BASE = "https://quickbooks.api.intuit.com/v3"
QB_SANDBOX_API_BASE = "https://sandbox-quickbooks.api.intuit.com/v3"


def _is_sandbox() -> bool:
    return os.getenv("QUICKBOOKS_SANDBOX", "false").lower() == "true"


def get_quickbooks_api_base() -> str:
    return QB_SANDBOX_API_BASE if _is_sandbox() else QB_API_BASE


def _get_basic_auth_header() -> str:
    """QuickBooks uses HTTP Basic Auth (base64-encoded client_id:client_secret)."""
    client_id = os.getenv("QUICKBOOKS_CLIENT_ID", "")
    client_secret = os.getenv("QUICKBOOKS_CLIENT_SECRET", "")
    encoded = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    return f"Basic {encoded}"


def get_quickbooks_auth_url(business_id: str, redirect_uri: str) -> str:
    """Generate the QuickBooks OAuth authorization URL."""
    client_id = os.getenv("QUICKBOOKS_CLIENT_ID", "")
    state = encrypt_str(business_id)

    params = {
        "client_id": client_id,
        "scope": "com.intuit.quickbooks.accounting",
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "state": state,
    }

    query_string = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{QB_AUTH_URL}?{query_string}"
    _logger.info(f"Generated QuickBooks auth URL for business {business_id}")
    return url


def exchange_quickbooks_code_for_tokens(code: str, redirect_uri: str) -> dict:
    """Exchange authorization code for access + refresh tokens."""
    resp = httpx.post(
        QB_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        },
        headers={
            "Authorization": _get_basic_auth_header(),
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        timeout=15.0,
    )

    if resp.status_code != 200:
        _logger.error(f"QuickBooks token exchange failed: {resp.status_code} {resp.text}")
        raise Exception(f"QuickBooks token exchange failed: {resp.status_code}")

    _logger.info("Successfully exchanged QuickBooks auth code for tokens")
    return resp.json()


def refresh_quickbooks_token(refresh_token: str) -> Tuple[str, str, int]:
    """Refresh an expired QuickBooks access token."""
    resp = httpx.post(
        QB_TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        headers={
            "Authorization": _get_basic_auth_header(),
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        timeout=15.0,
    )

    if resp.status_code != 200:
        _logger.error(f"QuickBooks token refresh failed: {resp.status_code} {resp.text}")
        raise Exception(f"QuickBooks token refresh failed: {resp.status_code}")

    data = resp.json()
    _logger.info("Successfully refreshed QuickBooks access token")
    return (
        data["access_token"],
        data.get("refresh_token", refresh_token),
        data.get("expires_in", 3600),
    )


async def get_quickbooks_company_info(access_token: str, realm_id: str) -> dict:
    """Fetch company info after OAuth."""
    api_base = get_quickbooks_api_base()

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{api_base}/company/{realm_id}/companyinfo/{realm_id}",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )

    if resp.status_code != 200:
        _logger.error(f"Failed to get QuickBooks company info: {resp.status_code}")
        return {}

    data = resp.json()
    return data.get("CompanyInfo", {})
