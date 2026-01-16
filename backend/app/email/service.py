"""Email service utilities and Supabase admin client."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

import httpx
from fastapi import Depends, HTTPException, status

from supabase_auth import SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY


class SupabaseAdminClient:
    """Minimal Supabase PostgREST client using the service role key."""

    def __init__(self, base_url: str, service_role_key: str, timeout: float = 20.0) -> None:
        if not base_url:
            raise ValueError("SUPABASE_URL is not configured")
        if not service_role_key:
            raise ValueError("SUPABASE_SERVICE_ROLE_KEY is not configured")
        self.base_url = base_url.rstrip("/")
        self.service_role_key = service_role_key
        self.timeout = timeout

    def _headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        headers = {
            "apikey": self.service_role_key,
            "Authorization": f"Bearer {self.service_role_key}",
            "Content-Type": "application/json",
        }
        if extra:
            headers.update(extra)
        return headers

    def _rest_url(self, table: str) -> str:
        return f"{self.base_url}/rest/v1/{table}"

    async def _request(
        self,
        method: str,
        table: str,
        *,
        params: Optional[Dict[str, str]] = None,
        json: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        url = self._rest_url(table)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.request(
                method,
                url,
                params=params,
                json=json,
                headers=self._headers(headers),
            )
        if response.status_code >= 400:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Supabase request failed ({response.status_code}): {response.text}",
            )
        if response.text:
            return response.json()
        return None

    @staticmethod
    def _normalize_payload(payload: Any) -> Any:
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, Iterable):
            return list(payload)
        return payload

    async def _upsert(self, table: str, payload: Any, *, on_conflict: str) -> Any:
        params = {"on_conflict": on_conflict}
        headers = {"Prefer": "resolution=merge-duplicates,return=representation"}
        return await self._request(
            "POST",
            table,
            params=params,
            json=self._normalize_payload(payload),
            headers=headers,
        )

    async def _insert(self, table: str, payload: Any) -> Any:
        headers = {"Prefer": "return=representation"}
        return await self._request(
            "POST",
            table,
            json=self._normalize_payload(payload),
            headers=headers,
        )

    async def _update(self, table: str, payload: Dict[str, Any], *, filters: Dict[str, Any]) -> Any:
        params = {key: f"eq.{value}" for key, value in filters.items()}
        headers = {"Prefer": "return=representation"}
        return await self._request(
            "PATCH",
            table,
            params=params,
            json=payload,
            headers=headers,
        )

    async def upsert_email_accounts(self, payload: Any) -> Any:
        return await self._upsert(
            "email_accounts",
            payload,
            on_conflict="business_id,email_address,provider",
        )

    async def fetch_email_accounts(self, business_id: str, *, fields: str) -> Any:
        params = {"select": fields, "business_id": f"eq.{business_id}"}
        return await self._request("GET", "email_accounts", params=params)

    async def fetch_email_account(
        self,
        *,
        business_id: str,
        fields: str,
        account_id: Optional[str] = None,
        is_default: Optional[bool] = None,
    ) -> Optional[Dict[str, Any]]:
        params = {"select": fields, "business_id": f"eq.{business_id}", "limit": "1"}
        if account_id:
            params["id"] = f"eq.{account_id}"
        if is_default is not None:
            params["is_default"] = f"eq.{str(is_default).lower()}"
        rows = await self._request("GET", "email_accounts", params=params)
        if rows:
            return rows[0]
        return None

    async def insert_email_outbox(self, payload: Any) -> Any:
        return await self._insert("email_outbox", payload)

    async def update_email_outbox(self, outbox_id: str, payload: Dict[str, Any]) -> Any:
        return await self._update("email_outbox", payload, filters={"id": outbox_id})

    async def upsert_email_messages(self, payload: Any) -> Any:
        return await self._upsert(
            "email_messages",
            payload,
            on_conflict="email_account_id,provider_message_id",
        )

    async def upsert_email_sync_state(self, payload: Any) -> Any:
        return await self._upsert("email_sync_state", payload, on_conflict="email_account_id")

    async def insert_email_briefings(self, payload: Any) -> Any:
        return await self._insert("email_briefings", payload)

    async def insert_email_drafts(self, payload: Any) -> Any:
        return await self._insert("email_drafts", payload)

    async def update_email_drafts(self, draft_id: str, payload: Dict[str, Any]) -> Any:
        return await self._update("email_drafts", payload, filters={"id": draft_id})


def get_supabase_admin_client() -> SupabaseAdminClient:
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Supabase service role configuration missing",
        )
    return SupabaseAdminClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


SupabaseAdminClientDep = Depends(get_supabase_admin_client)
