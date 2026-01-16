from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

from email_utils import decrypt_str, encrypt_str
from supabase_auth import SUPABASE_SERVICE_ROLE_KEY, SUPABASE_URL


GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
MICROSOFT_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"


def _parse_expires_at(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _update_tokens_in_supabase(
    account_id: str,
    *,
    access_token: str,
    expires_at: datetime,
    refresh_token: Optional[str] = None,
) -> None:
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("Supabase service role not configured")
    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/email_accounts"
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    payload = {
        "token_ciphertext": encrypt_str(access_token),
        "token_expires_at": expires_at.isoformat(),
    }
    if refresh_token:
        payload["refresh_token_ciphertext"] = encrypt_str(refresh_token)

    params = {"id": f"eq.{account_id}"}
    with httpx.Client(timeout=20) as client:
        response = client.patch(url, headers=headers, params=params, json=payload)
    if response.status_code >= 400:
        raise RuntimeError(f"Supabase token update failed: {response.status_code} {response.text}")


def _refresh_google_token(refresh_token: str) -> tuple[str, Optional[str], int]:
    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError("Google OAuth client not configured")
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    with httpx.Client(timeout=20) as client:
        response = client.post(GOOGLE_TOKEN_URL, data=payload)
    if response.status_code != 200:
        raise RuntimeError(f"Google token refresh failed: {response.status_code} {response.text}")
    data = response.json()
    return data["access_token"], data.get("refresh_token"), int(data.get("expires_in", 0))


def _refresh_microsoft_token(refresh_token: str) -> tuple[str, Optional[str], int]:
    client_id = os.getenv("MICROSOFT_OAUTH_CLIENT_ID")
    client_secret = os.getenv("MICROSOFT_OAUTH_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError("Microsoft OAuth client not configured")
    scopes = os.getenv(
        "MICROSOFT_OAUTH_SCOPES",
        "offline_access https://graph.microsoft.com/User.Read https://graph.microsoft.com/Mail.Read https://graph.microsoft.com/Mail.Send",
    )
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "scope": scopes,
    }
    with httpx.Client(timeout=20) as client:
        response = client.post(MICROSOFT_TOKEN_URL, data=payload)
    if response.status_code != 200:
        raise RuntimeError(f"Microsoft token refresh failed: {response.status_code} {response.text}")
    data = response.json()
    return data["access_token"], data.get("refresh_token"), int(data.get("expires_in", 0))


def get_valid_access_token(account: Any) -> str:
    token_ciphertext = getattr(account, "token_ciphertext", None)
    if not token_ciphertext:
        raise RuntimeError("Access token not configured")

    access_token = decrypt_str(token_ciphertext)
    expires_at = _parse_expires_at(getattr(account, "token_expires_at", None))
    now = datetime.now(timezone.utc)
    if expires_at and expires_at > now + timedelta(minutes=2):
        return access_token

    refresh_ciphertext = getattr(account, "refresh_token_ciphertext", None)
    if not refresh_ciphertext:
        raise RuntimeError("Refresh token not configured")

    refresh_token = decrypt_str(refresh_ciphertext)
    provider = (getattr(account, "provider", "") or "").lower()
    if provider == "google":
        new_access, new_refresh, expires_in = _refresh_google_token(refresh_token)
    elif provider == "microsoft":
        new_access, new_refresh, expires_in = _refresh_microsoft_token(refresh_token)
    else:
        raise RuntimeError(f"Unsupported provider for refresh: {provider}")

    new_expires_at = now + timedelta(seconds=expires_in or 0)
    _update_tokens_in_supabase(
        str(getattr(account, "id")),
        access_token=new_access,
        refresh_token=new_refresh,
        expires_at=new_expires_at,
    )
    return new_access
