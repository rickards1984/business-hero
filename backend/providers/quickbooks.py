"""
QuickBooks Online accounting data provider.
Implements the AccountingProvider interface for QuickBooks.

QuickBooks API docs:
  https://developer.intuit.com/app/developer/qbo/docs/api/accounting/all-entities
"""

import logging
from typing import Any, Dict, List, Optional

import httpx

from providers.accounting_base import (
    AccountingProvider, BankAccount, Invoice, Transaction,
)
from providers.quickbooks_oauth import get_quickbooks_api_base

_logger = logging.getLogger("quickbooks_provider")


def _get_line_description(txn: dict) -> str:
    """Extract a description from QuickBooks line items."""
    for line in txn.get("Line", []):
        desc = line.get("Description", "")
        if desc:
            return desc
    return "Transaction"


class QuickBooksProvider(AccountingProvider):
    provider_id = "quickbooks"

    def __init__(self, access_token: str, realm_id: str, minor_version: int = 75):
        self.api_base = get_quickbooks_api_base()
        self.realm_id = realm_id
        self.minor_version = minor_version
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def _get(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        url = f"{self.api_base}/company/{self.realm_id}/{endpoint.lstrip('/')}"
        if params is None:
            params = {}
        params["minorversion"] = self.minor_version

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=self.headers, params=params)

        if resp.status_code == 401:
            raise Exception("QuickBooks authentication failed — token may be expired")
        if resp.status_code == 429:
            raise Exception("QuickBooks rate limit exceeded")
        if resp.status_code != 200:
            _logger.error(f"QuickBooks API error: {resp.status_code} {resp.text[:200]}")
            raise Exception(f"QuickBooks API error: {resp.status_code}")

        return resp.json()

    async def _query(self, query: str) -> List[Dict]:
        """Execute a QuickBooks query (SQL-like syntax)."""
        url = f"{self.api_base}/company/{self.realm_id}/query"
        params = {"query": query, "minorversion": self.minor_version}

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=self.headers, params=params)

        if resp.status_code != 200:
            _logger.error(f"QuickBooks query error: {resp.status_code} {resp.text[:200]}")
            return []

        qr = resp.json().get("QueryResponse", {})
        for key in qr:
            if isinstance(qr[key], list):
                return qr[key]
        return []

    # ------------------------------------------------------------------
    # AccountingProvider interface
    # ------------------------------------------------------------------

    async def get_bank_summary(self) -> List[BankAccount]:
        accounts = await self._query(
            "SELECT * FROM Account WHERE AccountType IN ('Bank', 'Credit Card') AND Active = true"
        )
        result = []
        for acct in accounts:
            currency_ref = acct.get("CurrencyRef")
            currency = currency_ref.get("value", "GBP") if isinstance(currency_ref, dict) else "GBP"
            result.append(BankAccount(
                account_id=str(acct.get("Id", "")),
                name=acct.get("Name", "Unknown"),
                balance=float(acct.get("CurrentBalance", 0)),
                currency=currency,
                account_type=acct.get("AccountType", "Bank"),
            ))
        return result

    async def get_profit_and_loss(self, from_date: str, to_date: str) -> Dict[str, float]:
        try:
            data = await self._get("reports/ProfitAndLoss", params={
                "start_date": from_date,
                "end_date": to_date,
            })

            rows = data.get("Rows", {}).get("Row", [])
            income = 0.0
            expenses = 0.0
            net_profit = 0.0

            for row in rows:
                group = row.get("group", "")
                summary = row.get("Summary", {})
                col_data = summary.get("ColData", [])
                if group == "Income" and len(col_data) > 1:
                    income = float(col_data[1].get("value", 0))
                elif group == "Expenses" and len(col_data) > 1:
                    expenses = abs(float(col_data[1].get("value", 0)))
                elif group == "NetIncome" and len(col_data) > 1:
                    net_profit = float(col_data[1].get("value", 0))

            if net_profit == 0 and (income or expenses):
                net_profit = income - expenses

            return {
                "income": round(income, 2),
                "expenses": round(expenses, 2),
                "net_profit": round(net_profit, 2),
            }
        except Exception as exc:
            _logger.error(f"QuickBooks P&L report error: {exc}")
            return {"income": 0, "expenses": 0, "net_profit": 0}

    async def get_bank_transactions(
        self, modified_since: Optional[str] = None, page: int = 1,
    ) -> List[Transaction]:
        offset = (page - 1) * 100
        transactions: List[Transaction] = []

        # Purchases (expenses)
        pq = "SELECT * FROM Purchase ORDERBY TxnDate DESC"
        if modified_since:
            pq = f"SELECT * FROM Purchase WHERE MetaData.LastUpdatedTime > '{modified_since}' ORDERBY TxnDate DESC"
        pq += f" STARTPOSITION {offset + 1} MAXRESULTS 100"

        for txn in await self._query(pq):
            amount = -abs(float(txn.get("TotalAmt", 0)))
            acct_ref = txn.get("AccountRef")
            entity_ref = txn.get("EntityRef")
            transactions.append(Transaction(
                external_id=str(txn.get("Id", "")),
                date=txn.get("TxnDate", ""),
                description=txn.get("PrivateNote", "") or _get_line_description(txn),
                amount=amount,
                transaction_type="expense",
                category=acct_ref.get("name", "") if isinstance(acct_ref, dict) else "",
                contact_name=entity_ref.get("name", "") if isinstance(entity_ref, dict) else "",
                reference=str(txn.get("DocNumber", "")),
                account_name=acct_ref.get("name", "") if isinstance(acct_ref, dict) else "",
                is_reconciled=False,
                provider="quickbooks",
                raw_data=txn,
            ))

        # Deposits (income)
        dq = "SELECT * FROM Deposit ORDERBY TxnDate DESC"
        if modified_since:
            dq = f"SELECT * FROM Deposit WHERE MetaData.LastUpdatedTime > '{modified_since}' ORDERBY TxnDate DESC"
        dq += f" STARTPOSITION {offset + 1} MAXRESULTS 100"

        for txn in await self._query(dq):
            amount = abs(float(txn.get("TotalAmt", 0)))
            dep_ref = txn.get("DepositToAccountRef")
            transactions.append(Transaction(
                external_id=str(txn.get("Id", "")),
                date=txn.get("TxnDate", ""),
                description=txn.get("PrivateNote", "") or "Deposit",
                amount=amount,
                transaction_type="income",
                contact_name="",
                reference=str(txn.get("DocNumber", "")),
                account_name=dep_ref.get("name", "") if isinstance(dep_ref, dict) else "",
                is_reconciled=False,
                provider="quickbooks",
                raw_data=txn,
            ))

        transactions.sort(key=lambda t: t.date, reverse=True)
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
            if len(batch) < 200:
                break
            page += 1

        return all_txns

    async def get_invoices(
        self, modified_since: Optional[str] = None, status: Optional[str] = None,
    ) -> List[Invoice]:
        query = "SELECT * FROM Invoice ORDERBY TxnDate DESC MAXRESULTS 100"
        if modified_since:
            query = (
                f"SELECT * FROM Invoice WHERE MetaData.LastUpdatedTime > '{modified_since}' "
                "ORDERBY TxnDate DESC MAXRESULTS 100"
            )

        return [self._map_invoice(inv) for inv in await self._query(query)]

    async def get_all_invoices(self, modified_since: Optional[str] = None) -> List[Invoice]:
        return await self.get_invoices(modified_since=modified_since)

    async def get_contacts(self, page: int = 1) -> List[Dict[str, Any]]:
        offset = (page - 1) * 100
        return await self._query(
            f"SELECT * FROM Customer WHERE Active = true STARTPOSITION {offset + 1} MAXRESULTS 100"
        )

    async def get_organisation(self) -> Dict[str, Any]:
        data = await self._get(f"companyinfo/{self.realm_id}")
        return data.get("CompanyInfo", {})

    async def get_balance_sheet(self, date: Optional[str] = None) -> Optional[Dict]:
        params = {}
        if date:
            params["as_of_date"] = date
        try:
            return await self._get("reports/BalanceSheet", params=params)
        except Exception as exc:
            _logger.warning(f"QuickBooks balance sheet error: {exc}")
            return None

    async def get_trial_balance(self, date: Optional[str] = None) -> Optional[Dict]:
        params = {}
        if date:
            params["as_of_date"] = date
        try:
            return await self._get("reports/TrialBalance", params=params)
        except Exception as exc:
            _logger.warning(f"QuickBooks trial balance error: {exc}")
            return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _map_invoice(inv: Dict) -> Invoice:
        total = float(inv.get("TotalAmt", 0))
        balance = float(inv.get("Balance", 0))

        if balance == 0 and total > 0:
            mapped_status = "paid"
        elif inv.get("EmailStatus") == "EmailSent":
            mapped_status = "sent"
        else:
            mapped_status = "authorised"

        customer_ref = inv.get("CustomerRef")
        customer_name = customer_ref.get("name", "") if isinstance(customer_ref, dict) else ""
        bill_email = inv.get("BillEmail")
        customer_email = bill_email.get("Address", "") if isinstance(bill_email, dict) else ""
        currency_ref = inv.get("CurrencyRef")
        currency = currency_ref.get("value", "GBP") if isinstance(currency_ref, dict) else "GBP"

        return Invoice(
            external_id=str(inv.get("Id", "")),
            invoice_number=str(inv.get("DocNumber", "")),
            contact_name=customer_name,
            contact_email=customer_email or None,
            date=inv.get("TxnDate", ""),
            due_date=inv.get("DueDate", ""),
            total=total,
            amount_due=balance,
            amount_paid=total - balance,
            status=mapped_status,
            currency=currency,
            provider="quickbooks",
            raw_data=inv,
        )
