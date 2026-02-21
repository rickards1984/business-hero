"""
Xero API provider for Business Hero.
Handles all Xero REST API interactions for bank transactions, accounts, and contacts.
Follows the same provider pattern as google_gmail.py and microsoft_graph.py.
"""

import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

import httpx

_logger = logging.getLogger("xero_provider")

XERO_API_BASE = "https://api.xero.com/api.xro/2.0"
XERO_CONNECTIONS_URL = "https://api.xero.com/connections"


class XeroProvider:
    """Xero API client for a single authenticated tenant."""

    def __init__(self, access_token: str, tenant_id: str):
        self.access_token = access_token
        self.tenant_id = tenant_id
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Xero-Tenant-Id": tenant_id,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def get_bank_transactions(
        self,
        modified_since: Optional[str] = None,
        page: int = 1,
    ) -> Dict[str, Any]:
        """
        Fetch bank transactions from Xero.
        
        Args:
            modified_since: ISO datetime string for incremental sync (If-Modified-Since header)
            page: Page number (100 results per page)
            
        Returns:
            Xero API response dict containing BankTransactions list
        """
        url = f"{XERO_API_BASE}/BankTransactions"
        params = {"page": page, "order": "Date DESC"}
        headers = {**self.headers}

        if modified_since:
            headers["If-Modified-Since"] = modified_since

        async with httpx.AsyncClient(timeout=30.0) as client:
            _logger.info(f"Fetching Xero bank transactions page={page} modified_since={modified_since}")
            resp = await client.get(url, headers=headers, params=params)

            if resp.status_code == 304:
                _logger.info("Xero returned 304 Not Modified — no new transactions")
                return {"BankTransactions": []}

            if resp.status_code == 401:
                _logger.error("Xero token expired or invalid")
                raise XeroAuthError("Xero access token is expired or invalid")

            if resp.status_code == 429:
                _logger.warning("Xero rate limit hit")
                raise XeroRateLimitError("Xero API rate limit exceeded")

            resp.raise_for_status()
            data = resp.json()
            _logger.info(f"Fetched {len(data.get('BankTransactions', []))} transactions from Xero")
            return data

    async def get_all_bank_transactions(
        self,
        modified_since: Optional[str] = None,
        max_pages: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Fetch ALL bank transactions with automatic pagination.
        Xero returns 100 per page.
        
        Args:
            modified_since: ISO datetime for incremental sync
            max_pages: Safety limit to prevent runaway pagination
            
        Returns:
            Flat list of all bank transaction dicts
        """
        all_transactions = []
        page = 1

        while page <= max_pages:
            data = await self.get_bank_transactions(modified_since=modified_since, page=page)
            transactions = data.get("BankTransactions", [])

            if not transactions:
                break

            all_transactions.extend(transactions)

            if len(transactions) < 100:
                break

            page += 1

        _logger.info(f"Total Xero transactions fetched: {len(all_transactions)} across {page} page(s)")
        return all_transactions

    async def get_accounts(self) -> List[Dict[str, Any]]:
        """Fetch chart of accounts from Xero. Useful for category mapping."""
        url = f"{XERO_API_BASE}/Accounts"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=self.headers)
            resp.raise_for_status()
            return resp.json().get("Accounts", [])

    async def get_contacts(self, page: int = 1) -> List[Dict[str, Any]]:
        """Fetch contacts/suppliers from Xero."""
        url = f"{XERO_API_BASE}/Contacts"
        params = {"page": page}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=self.headers, params=params)
            resp.raise_for_status()
            return resp.json().get("Contacts", [])

    async def get_organisation(self) -> Dict[str, Any]:
        """Fetch organisation details — useful to show the connected org name."""
        url = f"{XERO_API_BASE}/Organisation"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=self.headers)
            resp.raise_for_status()
            orgs = resp.json().get("Organisations", [])
            return orgs[0] if orgs else {}


async def get_tenant_connections(access_token: str) -> List[Dict[str, Any]]:
    """
    After OAuth callback, call /connections to get the user's Xero tenant(s).
    Most small businesses have one tenant, but some may have multiple.
    
    Returns list of dicts with: tenantId, tenantName, tenantType, createdDateUtc, updatedDateUtc
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            XERO_CONNECTIONS_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        connections = resp.json()
        _logger.info(f"Xero tenant connections: {[c.get('tenantName') for c in connections]}")
        return connections


def map_xero_transaction_to_business_hero(xero_txn: Dict[str, Any]) -> Dict[str, Any]:
    """
    Map a Xero BankTransaction dict to Business Hero's accounting_transactions format.
    
    Xero BankTransaction fields used:
        - BankTransactionID (unique ID for dedup)
        - Type: "SPEND" or "RECEIVE"
        - Date: ISO date string
        - Total: Transaction total (always positive in Xero)
        - Reference: Optional reference text
        - Contact.Name: Payee/payer name
        - LineItems[0].Description: Transaction description
        - Status: "AUTHORISED", "DELETED", etc.
    """
    status = xero_txn.get("Status", "")
    if status in ("DELETED", "VOIDED"):
        return None

    xero_type = xero_txn.get("Type", "SPEND")
    is_income = xero_type == "RECEIVE"

    description = ""
    line_items = xero_txn.get("LineItems", [])
    if line_items:
        description = line_items[0].get("Description", "") or ""
    
    contact_name = xero_txn.get("Contact", {}).get("Name", "")
    if not description and contact_name:
        description = contact_name
    elif not description:
        description = f"Xero {xero_type.lower()} transaction"

    total = float(xero_txn.get("Total", 0))

    raw_date = xero_txn.get("Date", "")
    transaction_date = _parse_xero_date(raw_date)

    return {
        "transaction_date": transaction_date,
        "description": description.strip(),
        "amount": total if is_income else -total,
        "type": "income" if is_income else "expense",
        "reference": xero_txn.get("Reference", None),
        "payee_payer": contact_name or None,
        "external_id": xero_txn.get("BankTransactionID"),
        "external_source": "xero",
    }


def _parse_xero_date(date_value) -> Optional[str]:
    """
    Parse Xero's date format into a date string (YYYY-MM-DD).
    
    Xero can return dates as:
    - "/Date(1234567890000+0000)/" (legacy .NET JSON format)
    - "2024-01-15T00:00:00" (ISO format)
    - "2024-01-15" (simple date)
    """
    if not date_value:
        return None

    date_str = str(date_value)

    if date_str.startswith("/Date("):
        import re
        match = re.search(r"/Date\((\d+)", date_str)
        if match:
            timestamp_ms = int(match.group(1))
            dt = datetime.utcfromtimestamp(timestamp_ms / 1000)
            return dt.strftime("%Y-%m-%d")

    try:
        if "T" in date_str:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d")
        else:
            return date_str[:10]
    except (ValueError, AttributeError):
        _logger.warning(f"Could not parse Xero date: {date_value}")
        return None


class XeroAuthError(Exception):
    """Raised when Xero returns 401 — token needs refresh or reconnection."""
    pass


class XeroRateLimitError(Exception):
    """Raised when Xero returns 429 — rate limit exceeded."""
    pass
