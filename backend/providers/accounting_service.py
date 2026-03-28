"""
Accounting service layer — detects the active accounting provider for a business
and delegates calls to the correct implementation (Xero, FreeAgent, QuickBooks).

Provider-agnostic endpoints call this service; existing Xero-specific endpoints
continue to work as before and are NOT affected.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlmodel import Session

from email_utils import encrypt_str, decrypt_str
from providers.accounting_base import AccountingProvider
from providers.token_refresh_lock import coordinated_token_refresh

_logger = logging.getLogger("accounting_service")


class AccountingService:
    """
    Service layer that detects the provider and delegates to the right implementation.
    """

    def __init__(self, business_id: str, session: Session):
        self.business_id = business_id
        self.db = session
        self._provider: Optional[AccountingProvider] = None
        self._connection: Optional[Dict[str, Any]] = None

    def get_connection(self) -> Optional[Dict[str, Any]]:
        if self._connection is not None:
            return self._connection

        result = self.db.execute(
            text("""
                SELECT id, business_id, provider, tenant_id, tenant_name,
                       token_ciphertext, refresh_token_ciphertext,
                       token_expires_at, last_sync_at, is_active,
                       provider_metadata
                FROM accounting_connections
                WHERE business_id = :business_id AND is_active = true
                LIMIT 1
            """),
            {"business_id": self.business_id},
        )
        row = result.fetchone()
        if not row:
            self._connection = None
            return None

        self._connection = {
            "id": str(row[0]),
            "business_id": str(row[1]),
            "provider": row[2],
            "tenant_id": row[3],
            "tenant_name": row[4],
            "token_ciphertext": row[5],
            "refresh_token_ciphertext": row[6],
            "token_expires_at": row[7],
            "last_sync_at": row[8],
            "is_active": row[9],
            "provider_metadata": row[10],
        }
        return self._connection

    async def get_provider(self) -> Optional[AccountingProvider]:
        if self._provider is not None:
            return self._provider

        connection = self.get_connection()
        if not connection:
            return None

        provider_type = connection["provider"]
        access_token = decrypt_str(connection["token_ciphertext"])
        access_token = await self._ensure_valid_token(connection, access_token)

        if provider_type == "xero":
            from providers.xero import XeroProvider
            self._provider = XeroProvider(
                access_token=access_token,
                tenant_id=connection["tenant_id"],
            )
        elif provider_type == "freeagent":
            from providers.freeagent import FreeAgentProvider
            self._provider = FreeAgentProvider(
                access_token=access_token,
                company_url=(connection.get("provider_metadata") or {}).get("company_url", ""),
                subdomain=(connection.get("provider_metadata") or {}).get("subdomain", ""),
            )
        elif provider_type == "quickbooks":
            from providers.quickbooks import QuickBooksProvider
            metadata = connection.get("provider_metadata") or {}
            self._provider = QuickBooksProvider(
                access_token=access_token,
                realm_id=connection["tenant_id"],
                minor_version=metadata.get("minor_version", 75),
            )
        else:
            _logger.warning(f"Unknown provider type: {provider_type}")
            return None

        return self._provider

    async def _ensure_valid_token(self, connection: Dict[str, Any], access_token: str) -> str:
        expires_at = connection.get("token_expires_at")
        if not expires_at:
            return access_token

        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)
        if now < (expires_at - timedelta(minutes=2)):
            return access_token

        provider_type = connection["provider"]
        conn_id = connection["id"]
        db = self.db
        business_id = self.business_id

        _last_expires_in = [1800]

        async def get_current_tokens():
            row = db.execute(
                text("""
                    SELECT token_ciphertext, refresh_token_ciphertext, token_refreshed_at
                    FROM accounting_connections
                    WHERE id = :conn_id
                """),
                {"conn_id": conn_id},
            ).fetchone()
            return {
                "access_token": decrypt_str(row[0]),
                "refresh_token": decrypt_str(row[1]),
                "token_refreshed_at": row[2],
            }

        async def do_refresh(refresh_token: str):
            new_access, new_refresh, expires_in = await asyncio.to_thread(
                self._refresh_token, provider_type, refresh_token
            )
            _last_expires_in[0] = expires_in
            return {
                "access_token": new_access,
                "refresh_token": new_refresh,
            }

        async def save_tokens(new_access: str, new_refresh: str, refreshed_at: datetime):
            new_expires = refreshed_at + timedelta(seconds=_last_expires_in[0])
            db.execute(
                text("""
                    UPDATE accounting_connections
                    SET token_ciphertext = :token,
                        refresh_token_ciphertext = :refresh,
                        token_expires_at = :expires_at,
                        token_refreshed_at = :refreshed_at,
                        updated_at = NOW()
                    WHERE id = :conn_id
                """),
                {
                    "token": encrypt_str(new_access),
                    "refresh": encrypt_str(new_refresh),
                    "expires_at": new_expires,
                    "refreshed_at": refreshed_at,
                    "conn_id": conn_id,
                },
            )
            db.commit()

        return await coordinated_token_refresh(
            business_id=business_id,
            provider_name=provider_type,
            get_current_tokens=get_current_tokens,
            do_refresh=do_refresh,
            save_tokens=save_tokens,
        )

    @staticmethod
    def _refresh_token(provider: str, refresh_token: str):
        if provider == "xero":
            from providers.xero_oauth import refresh_xero_token
            return refresh_xero_token(refresh_token)
        elif provider == "freeagent":
            from providers.freeagent_oauth import refresh_freeagent_token
            return refresh_freeagent_token(refresh_token)
        elif provider == "quickbooks":
            from providers.quickbooks_oauth import refresh_quickbooks_token
            return refresh_quickbooks_token(refresh_token)
        else:
            raise ValueError(f"Unknown provider: {provider}")

    def get_status(self) -> Dict[str, Any]:
        connection = self.get_connection()
        if not connection or not connection.get("is_active"):
            return {
                "connected": False,
                "provider": None,
                "tenant_name": None,
                "last_sync_at": None,
            }

        last_sync = connection.get("last_sync_at")
        if last_sync and hasattr(last_sync, "isoformat"):
            last_sync = last_sync.isoformat()

        return {
            "connected": True,
            "provider": connection["provider"],
            "tenant_name": connection.get("tenant_name"),
            "last_sync_at": last_sync,
        }
