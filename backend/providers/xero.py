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

            if resp.status_code in (401, 403):
                _logger.error(f"Xero returned {resp.status_code} — token expired, invalid, or forbidden")
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
            if resp.status_code in (401, 403):
                raise XeroAuthError("Xero access token is expired or invalid")
            resp.raise_for_status()
            return resp.json().get("Accounts", [])

    async def get_contacts(self, page: int = 1) -> List[Dict[str, Any]]:
        """Fetch contacts/suppliers from Xero."""
        url = f"{XERO_API_BASE}/Contacts"
        params = {"page": page}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=self.headers, params=params)
            if resp.status_code in (401, 403):
                raise XeroAuthError("Xero access token is expired or invalid")
            resp.raise_for_status()
            return resp.json().get("Contacts", [])

    async def get_contact_email(self, contact_id: str) -> Optional[str]:
        """Fetch a single contact's email address from the Contacts API."""
        url = f"{XERO_API_BASE}/Contacts/{contact_id}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=self.headers)
            if resp.status_code != 200:
                _logger.warning(f"Failed to fetch contact {contact_id}: HTTP {resp.status_code}")
                return None
            contacts = resp.json().get("Contacts", [])
            if contacts:
                return contacts[0].get("EmailAddress") or None
            return None

    async def get_organisation(self) -> Dict[str, Any]:
        """Fetch organisation details — useful to show the connected org name."""
        url = f"{XERO_API_BASE}/Organisation"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=self.headers)
            if resp.status_code in (401, 403):
                raise XeroAuthError("Xero access token is expired or invalid")
            resp.raise_for_status()
            orgs = resp.json().get("Organisations", [])
            return orgs[0] if orgs else {}

    async def get_bank_summary(self) -> Dict[str, Any]:
        """
        Fetch the BankSummary report from Xero.
        Returns bank account balances (opening and closing) for the current period.
        
        Xero endpoint: GET /Reports/BankSummary
        """
        url = f"{XERO_API_BASE}/Reports/BankSummary"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=self.headers)
            if resp.status_code in (401, 403):
                raise XeroAuthError("Xero access token is expired or invalid")
            resp.raise_for_status()
            return resp.json()

    async def get_profit_and_loss(
        self,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Fetch Profit and Loss report from Xero.
        
        Args:
            from_date: Start date YYYY-MM-DD (defaults to start of current month)
            to_date: End date YYYY-MM-DD (defaults to today)
            
        Xero endpoint: GET /Reports/ProfitAndLoss
        """
        url = f"{XERO_API_BASE}/Reports/ProfitAndLoss"
        params = {}
        if from_date:
            params["fromDate"] = from_date
        if to_date:
            params["toDate"] = to_date
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=self.headers, params=params)
            if resp.status_code in (401, 403):
                raise XeroAuthError("Xero access token is expired or invalid")
            resp.raise_for_status()
            return resp.json()

    async def get_balance_sheet(self, date: Optional[str] = None) -> Dict[str, Any]:
        """
        Fetch Balance Sheet report from Xero.
        Args:
            date: Report date YYYY-MM-DD (defaults to today)
        """
        url = f"{XERO_API_BASE}/Reports/BalanceSheet"
        params = {}
        if date:
            params["date"] = date
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=self.headers, params=params)
            if resp.status_code in (401, 403):
                raise XeroAuthError("Xero access token is expired or invalid")
            resp.raise_for_status()
            return resp.json()

    async def get_trial_balance(self, date: Optional[str] = None) -> Dict[str, Any]:
        """
        Fetch Trial Balance report.
        Args:
            date: Report date YYYY-MM-DD (defaults to today)
        """
        url = f"{XERO_API_BASE}/Reports/TrialBalance"
        params = {}
        if date:
            params["date"] = date
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=self.headers, params=params)
            if resp.status_code in (401, 403):
                raise XeroAuthError("Xero access token is expired or invalid")
            resp.raise_for_status()
            return resp.json()

    async def get_aged_receivables(self) -> Dict[str, Any]:
        """Fetch Aged Receivables (who owes you money) report."""
        url = f"{XERO_API_BASE}/Reports/AgedReceivablesByContact"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=self.headers)
            if resp.status_code in (401, 403):
                raise XeroAuthError("Xero access token is expired or invalid")
            resp.raise_for_status()
            return resp.json()

    async def get_aged_payables(self) -> Dict[str, Any]:
        """Fetch Aged Payables (who you owe money to) report."""
        url = f"{XERO_API_BASE}/Reports/AgedPayablesByContact"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=self.headers)
            if resp.status_code in (401, 403):
                raise XeroAuthError("Xero access token is expired or invalid")
            resp.raise_for_status()
            return resp.json()

    async def get_invoices(
        self,
        modified_since: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
    ) -> Dict[str, Any]:
        """
        Fetch invoices from Xero.

        Args:
            modified_since: ISO datetime string to only fetch recently modified invoices
            status: Filter by status (DRAFT, SUBMITTED, AUTHORISED, PAID, VOIDED, DELETED)
            page: Page number (100 invoices per page)
        """
        url = f"{XERO_API_BASE}/Invoices"
        params: Dict[str, Any] = {"page": page, "order": "Date DESC"}
        if status:
            params["Statuses"] = status

        headers = {**self.headers}
        if modified_since:
            headers["If-Modified-Since"] = modified_since

        async with httpx.AsyncClient(timeout=30.0) as client:
            _logger.info(f"Fetching Xero invoices page={page} status={status}")
            resp = await client.get(url, headers=headers, params=params)

            if resp.status_code in (401, 403):
                raise XeroAuthError("Xero access token is expired or invalid")
            if resp.status_code == 304:
                return {"Invoices": []}
            if resp.status_code == 429:
                raise XeroRateLimitError("Xero API rate limit exceeded")

            resp.raise_for_status()
            data = resp.json()
            _logger.info(f"Fetched {len(data.get('Invoices', []))} invoices from Xero")
            return data

    async def get_all_invoices(
        self,
        modified_since: Optional[str] = None,
        statuses: str = "AUTHORISED,SUBMITTED",
        max_pages: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Fetch ALL invoices across all pages from Xero.
        Defaults to only fetching outstanding (unpaid) invoices.
        """
        all_invoices: List[Dict[str, Any]] = []
        page = 1

        while page <= max_pages:
            data = await self.get_invoices(
                modified_since=modified_since,
                status=statuses,
                page=page,
            )
            invoices = data.get("Invoices", [])
            all_invoices.extend(invoices)

            if len(invoices) < 100:
                break
            page += 1

        _logger.info(f"Total Xero invoices fetched: {len(all_invoices)} across {page} page(s)")
        return all_invoices


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


def map_xero_invoice_to_business_hero(xero_invoice: Dict[str, Any]) -> Dict[str, Any]:
    """
    Map a Xero Invoice to Business Hero's invoices table format.

    Xero Invoice fields:
    - InvoiceID, InvoiceNumber, Type (ACCREC / ACCPAY)
    - Contact.Name / Contact.EmailAddress
    - Total, AmountDue, AmountPaid
    - Status: DRAFT, SUBMITTED, AUTHORISED, PAID, VOIDED, DELETED
    - Date, DueDate (in /Date(...)/ or ISO format)
    - Reference, CurrencyCode
    """
    xero_status = xero_invoice.get("Status", "")
    if xero_status == "PAID":
        bh_status = "paid"
    elif xero_status == "VOIDED":
        bh_status = "cancelled"
    elif xero_status == "DRAFT":
        bh_status = "draft"
    elif xero_status in ("AUTHORISED", "SUBMITTED"):
        bh_status = "unpaid"
    else:
        bh_status = "unpaid"

    contact = xero_invoice.get("Contact", {})

    return {
        "external_id": xero_invoice.get("InvoiceID"),
        "external_source": "xero",
        "invoice_number": xero_invoice.get("InvoiceNumber", ""),
        "customer_name": contact.get("Name", "Unknown"),
        "customer_email": contact.get("EmailAddress") or None,
        "amount": float(xero_invoice.get("Total", 0)),
        "amount_due": float(xero_invoice.get("AmountDue", 0)),
        "amount_paid": float(xero_invoice.get("AmountPaid", 0)),
        "status": bh_status,
        "issue_date": _parse_xero_date(xero_invoice.get("Date")),
        "due_date": _parse_xero_date(xero_invoice.get("DueDate")),
        "reference": xero_invoice.get("Reference", ""),
        "currency": xero_invoice.get("CurrencyCode", "GBP"),
        "invoice_type": xero_invoice.get("Type", "ACCREC"),
    }


class XeroAuthError(Exception):
    """Raised when Xero returns 401 — token needs refresh or reconnection."""
    pass


class XeroRateLimitError(Exception):
    """Raised when Xero returns 429 — rate limit exceeded."""
    pass
