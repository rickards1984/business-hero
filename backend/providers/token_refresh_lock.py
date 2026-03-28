"""
Coordinated OAuth token refresh — prevents concurrent refresh race conditions.

Xero (and potentially FreeAgent/QuickBooks) use single-use refresh tokens.
When two requests detect an expired access token at the same time and both
try to refresh, the first succeeds but the second uses the now-consumed
refresh token and gets invalid_grant — killing the connection.

This module provides an in-process async lock keyed by business_id, plus a
staleness check (token_refreshed_at) so the second caller can re-read the
freshly-saved token instead of refreshing again.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

_refresh_locks: dict[str, asyncio.Lock] = {}


def _get_lock(business_id: str) -> asyncio.Lock:
    if business_id not in _refresh_locks:
        _refresh_locks[business_id] = asyncio.Lock()
    return _refresh_locks[business_id]


async def coordinated_token_refresh(
    business_id: str,
    provider_name: str,
    get_current_tokens: Callable[[], Awaitable[dict]],
    do_refresh: Callable[[str], Awaitable[dict]],
    save_tokens: Callable[[str, str, datetime], Awaitable[None]],
    staleness_window_seconds: int = 30,
) -> str:
    """
    Coordinates token refresh across concurrent callers. Returns a valid access token.

    Parameters:
        get_current_tokens: async fn returning {
            "access_token": str,
            "refresh_token": str,
            "token_refreshed_at": datetime | None
        }
        do_refresh: async fn that takes a refresh_token string, calls the provider's
            token endpoint, returns {"access_token": str, "refresh_token": str}
        save_tokens: async fn that saves new access_token, refresh_token, and
            token_refreshed_at back to the database
        staleness_window_seconds: if token was refreshed within this window, skip refresh

    Flow:
        1. Acquire async lock for this business_id
        2. Re-read tokens from DB (another caller may have refreshed while we waited)
        3. If token_refreshed_at is within staleness_window_seconds -> return existing token
        4. Otherwise -> refresh, save with timestamp, return new token
    """
    lock = _get_lock(business_id)

    async with lock:
        current = await get_current_tokens()

        if current.get("token_refreshed_at"):
            refreshed_at = current["token_refreshed_at"]
            if isinstance(refreshed_at, str):
                refreshed_at = datetime.fromisoformat(
                    refreshed_at.replace("Z", "+00:00")
                )

            age = (datetime.now(timezone.utc) - refreshed_at).total_seconds()

            if age < staleness_window_seconds:
                logger.info(
                    f"[{provider_name}] Token for business {business_id} was refreshed "
                    f"{age:.1f}s ago — using existing token"
                )
                return current["access_token"]

        logger.info(f"[{provider_name}] Refreshing token for business {business_id}")

        try:
            new_tokens = await do_refresh(current["refresh_token"])
            refreshed_at = datetime.now(timezone.utc)

            await save_tokens(
                new_tokens["access_token"],
                new_tokens["refresh_token"],
                refreshed_at,
            )

            logger.info(
                f"[{provider_name}] Token refreshed OK for business {business_id}"
            )
            return new_tokens["access_token"]

        except Exception as e:
            logger.error(
                f"[{provider_name}] Token refresh FAILED for business {business_id}: {e}"
            )
            raise
