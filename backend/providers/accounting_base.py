"""
Abstract base class for accounting providers.
All providers (Xero, FreeAgent, QuickBooks) implement this interface so the
service layer can work with any of them through a single API.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class BankAccount:
    account_id: str
    name: str
    balance: float
    currency: str = "GBP"
    account_type: str = "BANK"


@dataclass
class FinancialSummary:
    total_bank_balance: float
    bank_accounts: List[Dict[str, Any]]
    income: float
    expenses: float
    net_profit: float
    invoices_outstanding: float
    invoices_overdue_count: int
    invoices_overdue_amount: float
    invoices_due_count: int
    invoices_due_amount: float
    provider: str
    connected: bool
    tenant_name: Optional[str] = None
    last_sync_at: Optional[str] = None


@dataclass
class Transaction:
    external_id: str
    date: str
    description: str
    amount: float
    transaction_type: str
    category: Optional[str] = None
    contact_name: Optional[str] = None
    reference: Optional[str] = None
    account_name: Optional[str] = None
    is_reconciled: bool = False
    provider: str = ""
    raw_data: Optional[Dict] = None
    provider_category_name: Optional[str] = None
    provider_category_code: Optional[str] = None
    provider_category_type: Optional[str] = None


@dataclass
class Invoice:
    external_id: str
    invoice_number: str
    contact_name: str
    contact_email: Optional[str]
    date: str
    due_date: str
    total: float
    amount_due: float
    amount_paid: float
    status: str
    currency: str = "GBP"
    provider: str = ""
    raw_data: Optional[Dict] = None


class AccountingProvider(ABC):
    """Every accounting provider must implement these methods."""

    provider_id: str = ""

    @abstractmethod
    async def get_bank_summary(self) -> List[BankAccount]:
        ...

    @abstractmethod
    async def get_profit_and_loss(self, from_date: str, to_date: str) -> Dict[str, float]:
        """Returns {"income": float, "expenses": float, "net_profit": float}"""
        ...

    @abstractmethod
    async def get_bank_transactions(self, modified_since: Optional[str] = None, page: int = 1) -> List[Transaction]:
        ...

    @abstractmethod
    async def get_all_bank_transactions(self, modified_since: Optional[str] = None) -> List[Transaction]:
        ...

    @abstractmethod
    async def get_invoices(self, modified_since: Optional[str] = None, status: Optional[str] = None) -> List[Invoice]:
        ...

    @abstractmethod
    async def get_all_invoices(self, modified_since: Optional[str] = None) -> List[Invoice]:
        ...

    @abstractmethod
    async def get_contacts(self, page: int = 1) -> List[Dict[str, Any]]:
        ...

    @abstractmethod
    async def get_organisation(self) -> Dict[str, Any]:
        ...

    async def get_balance_sheet(self, date: Optional[str] = None) -> Optional[Dict]:
        return None

    async def get_trial_balance(self, date: Optional[str] = None) -> Optional[Dict]:
        return None

    async def get_aged_receivables(self) -> Optional[Dict]:
        return None

    async def get_aged_payables(self) -> Optional[Dict]:
        return None
