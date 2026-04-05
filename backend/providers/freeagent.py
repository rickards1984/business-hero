"""
FreeAgent accounting data provider.
Implements the AccountingProvider interface for FreeAgent.

FreeAgent API docs: https://dev.freeagent.com/docs
"""

import logging
from typing import Any, Dict, List, Optional

import httpx

from providers.accounting_base import (
    AccountingProvider, BankAccount, Invoice, Transaction,
)
from providers.freeagent_oauth import get_freeagent_api_base

_logger = logging.getLogger("freeagent_provider")

_STATUS_MAP = {
    "draft": "draft",
    "sent": "sent",
    "viewed": "sent",
    "open": "authorised",
    "overdue": "authorised",
    "paid": "paid",
    "scheduled": "sent",
    "cancelled": "voided",
    "written_off": "voided",
}


class FreeAgentProvider(AccountingProvider):
    provider_id = "freeagent"

    def __init__(self, access_token: str, company_url: str = "", subdomain: str = ""):
        self.api_base = get_freeagent_api_base()
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        self.company_url = company_url
        self.subdomain = subdomain

    async def _get(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        url = f"{self.api_base}/{endpoint.lstrip('/')}"

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=self.headers, params=params)

        if resp.status_code == 401:
            raise Exception("FreeAgent authentication failed — token may be expired")
        if resp.status_code == 429:
            raise Exception("FreeAgent rate limit exceeded")
        if resp.status_code != 200:
            _logger.error(f"FreeAgent API error: {resp.status_code} {resp.text[:200]}")
            raise Exception(f"FreeAgent API error: {resp.status_code}")

        return resp.json()

    # ------------------------------------------------------------------
    # AccountingProvider interface
    # ------------------------------------------------------------------

    async def get_bank_summary(self) -> List[BankAccount]:
        data = await self._get("/bank_accounts")
        accounts = []
        for acct in data.get("bank_accounts", []):
            accounts.append(BankAccount(
                account_id=acct.get("url", ""),
                name=acct.get("name", "Unknown"),
                balance=float(acct.get("current_balance", 0)),
                currency=acct.get("currency", "GBP"),
                account_type=acct.get("type", "BANK"),
            ))
        return accounts

    async def get_profit_and_loss(self, from_date: str, to_date: str) -> Dict[str, float]:
        """
        FreeAgent has no dedicated P&L report endpoint.
        We approximate from invoices, bills, and bank transactions.
        """
        total_income = 0.0
        total_expenses = 0.0

        try:
            inv_data = await self._get("/invoices", params={
                "view": "recent_open_or_overdue",
                "from_date": from_date,
                "to_date": to_date,
            })
            for inv in inv_data.get("invoices", []):
                if inv.get("status") in ("Paid", "Sent", "Scheduled"):
                    total_income += float(inv.get("total_value", 0))
        except Exception as exc:
            _logger.warning(f"FreeAgent invoice P&L fetch failed: {exc}")

        try:
            bill_data = await self._get("/bills", params={
                "from_date": from_date,
                "to_date": to_date,
            })
            for bill in bill_data.get("bills", []):
                total_expenses += abs(float(bill.get("total_value", 0)))
        except Exception as exc:
            _logger.warning(f"FreeAgent bill P&L fetch failed: {exc}")

        try:
            txn_data = await self._get("/bank_transactions", params={
                "from_date": from_date,
                "to_date": to_date,
                "view": "all",
            })
            for txn in txn_data.get("bank_transactions", []):
                amount = float(txn.get("amount", 0))
                if amount < 0:
                    total_expenses += abs(amount)
                elif amount > 0:
                    total_income += amount
        except Exception as exc:
            _logger.warning(f"FreeAgent bank txn P&L fetch failed: {exc}")

        return {
            "income": round(total_income, 2),
            "expenses": round(total_expenses, 2),
            "net_profit": round(total_income - total_expenses, 2),
        }

    async def get_bank_transactions(
        self, modified_since: Optional[str] = None, page: int = 1,
    ) -> List[Transaction]:
        params: Dict[str, Any] = {"view": "all", "page": page, "per_page": 100}
        if modified_since:
            params["updated_since"] = modified_since

        data = await self._get("/bank_transactions", params=params)

        transactions = []
        for txn in data.get("bank_transactions", []):
            amount = float(txn.get("amount", 0))
            category_url = txn.get("category", "") or ""
            category_name = category_url.rsplit("/", 1)[-1] if category_url else None
            txn_type = "income" if amount >= 0 else "expense"
            transactions.append(Transaction(
                external_id=txn.get("url", ""),
                date=txn.get("dated_on", ""),
                description=txn.get("description", "") or txn.get("full_description", ""),
                amount=amount,
                transaction_type=txn_type,
                category=category_name,
                contact_name=None,
                reference=(txn.get("bank_transaction_explanation") or {}).get("description", ""),
                account_name=txn.get("bank_account", ""),
                is_reconciled=txn.get("is_reconciled", False),
                provider="freeagent",
                raw_data=txn,
                provider_category_name=category_name,
                provider_category_code=category_url.rsplit("/", 1)[-1] if category_url else None,
                provider_category_type=txn_type,
            ))
        return transactions

    async def get_all_bank_transactions(self, modified_since: Optional[str] = None) -> List[Transaction]:
        all_txns: List[Transaction] = []
        page = 1
        max_pages = 20

        while page <= max_pages:
            batch = await self.get_bank_transactions(modified_since=modified_since, page=page)
            if not batch:
                break
            all_txns.extend(batch)
            if len(batch) < 100:
                break
            page += 1

        return all_txns

    async def get_invoices(
        self, modified_since: Optional[str] = None, status: Optional[str] = None,
    ) -> List[Invoice]:
        params: Dict[str, Any] = {}
        params["view"] = status if status else "recent_open_or_overdue"
        if modified_since:
            params["updated_since"] = modified_since

        data = await self._get("/invoices", params=params)
        return [self._map_invoice(inv) for inv in data.get("invoices", [])]

    async def get_all_invoices(self, modified_since: Optional[str] = None) -> List[Invoice]:
        all_invoices: List[Invoice] = []
        seen: set = set()

        for view in ("recent_open_or_overdue", "last_3_months"):
            try:
                data = await self._get("/invoices", params={"view": view})
                for inv in data.get("invoices", []):
                    mapped = self._map_invoice(inv)
                    if mapped.external_id not in seen:
                        seen.add(mapped.external_id)
                        all_invoices.append(mapped)
            except Exception as exc:
                _logger.warning(f"FreeAgent get_all_invoices view={view} failed: {exc}")

        return all_invoices

    async def get_contacts(self, page: int = 1) -> List[Dict[str, Any]]:
        data = await self._get("/contacts", params={"page": page, "per_page": 100})
        return data.get("contacts", [])

    async def get_organisation(self) -> Dict[str, Any]:
        data = await self._get("/company")
        return data.get("company", {})

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _map_invoice(inv: Dict) -> Invoice:
        total = float(inv.get("total_value", 0))
        paid = float(inv.get("paid_value", 0))
        fa_status = inv.get("status", "").lower()
        contact = inv.get("contact", {})
        contact_name = contact.get("name", "") if isinstance(contact, dict) else ""

        return Invoice(
            external_id=inv.get("url", ""),
            invoice_number=inv.get("reference", ""),
            contact_name=contact_name,
            contact_email=None,
            date=inv.get("dated_on", ""),
            due_date=inv.get("due_on", ""),
            total=total,
            amount_due=total - paid,
            amount_paid=paid,
            status=_STATUS_MAP.get(fa_status, "authorised"),
            currency=inv.get("currency", "GBP"),
            provider="freeagent",
            raw_data=inv,
        )
