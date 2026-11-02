"""ACC-2: an accountancy pack an accountant can trust (docs/ACC-2-TICKET.md).
RED: figures handed to an accountant, and tax points.

Mike approved the rules on 2 Nov 2026. A1–A9 cover accuracy, T1–T8 the tax
points, W the AI wording guard, and S speed. The fake Xero honours the
filters the pack sends (statuses, `where` dates and types, pages of 100), so
removing a filter or a comparative parameter turns a test red (Codex review 1).
It runs on SQLite, with no network.
"""
import asyncio
import importlib
import io
import json
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D

import pytest
from openpyxl import load_workbook
from sqlalchemy import create_engine, text
from sqlmodel import Session

BIZ = str(uuid.uuid4())
TODAY = date(2026, 11, 2)
FY = (date(2025, 4, 1), date(2026, 3, 31))


def pack():
    return importlib.import_module("services.accountancy_pack")


# ------------------------------------------------------------------ data ---

def xdate(d: date) -> str:
    return f"/Date({int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()) * 1000}+0000)/"


def cell(v):
    return {"Value": v}


def report(name, rows, titles=()):
    return {"Reports": [{"ReportName": name, "ReportTitles": list(titles), "Rows": rows}]}


def pnl_report(this_income="120000.00", prior_income="100000.00", this_net="48000.00", prior_net="30000.00"):
    return report("Profit and Loss", [
        {"RowType": "Header", "Cells": [cell(""), cell("31 Mar 2026"), cell("31 Mar 2025")]},
        {"RowType": "Section", "Title": "Income", "Rows": [
            {"RowType": "Row", "Cells": [cell("Sales (200)"), cell(this_income), cell(prior_income)]},
            {"RowType": "SummaryRow", "Cells": [cell("Total Income"), cell(this_income), cell(prior_income)]}]},
        {"RowType": "Section", "Title": "", "Rows": [
            {"RowType": "Row", "Cells": [cell("Net Profit"), cell(this_net), cell(prior_net)]}]},
    ])


def bs_report(assets="50000.00", liabilities="20000.00", equity="30000.00"):
    return report("Balance Sheet", [
        {"RowType": "Header", "Cells": [cell(""), cell("31 Mar 2026"), cell("31 Mar 2025")]},
        {"RowType": "Section", "Title": "Assets", "Rows": [
            {"RowType": "SummaryRow", "Cells": [cell("Total Assets"), cell(assets), cell("40000.00")]}]},
        {"RowType": "Section", "Title": "Liabilities", "Rows": [
            {"RowType": "SummaryRow", "Cells": [cell("Total Liabilities"), cell(liabilities), cell("15000.00")]}]},
        {"RowType": "Section", "Title": "Equity", "Rows": [
            {"RowType": "SummaryRow", "Cells": [cell("Total Equity"), cell(equity), cell("25000.00")]}]},
    ])


def invoice(i, *, kind="ACCREC", issued=date(2026, 1, 10), due=date(2026, 2, 10), total="120.00", sub="100.00",
            tax="20.00", status="AUTHORISED", contact="Client Ltd", due_now=None, payments=(), credits=(),
            currency="GBP", updated=None):
    return {"InvoiceID": f"inv-{i}", "InvoiceNumber": f"INV-{i}", "Type": kind, "Status": status,
            "Contact": {"Name": contact}, "Date": xdate(issued), "DueDate": xdate(due) if due else None,
            "SubTotal": sub, "TotalTax": tax, "Total": total, "AmountDue": due_now if due_now is not None else total,
            "CurrencyCode": currency, "UpdatedDateUTC": (updated or issued).isoformat() + "T00:00:00",
            "Payments": [{"PaymentID": f"p-{i}-{n}", "Date": xdate(d), "Amount": a, "Invoice": {"InvoiceID": f"inv-{i}"}}
                         for n, (d, a) in enumerate(payments)],
            "CreditNotes": [{"Date": xdate(d), "AppliedAmount": a} for d, a in credits]}


def credit_note(i, *, allocations=(), status="AUTHORISED", kind="ACCRECCREDIT", on=date(2025, 6, 1), sub="0.00"):
    return {"CreditNoteID": f"cn-{i}", "Type": kind, "Status": status, "Date": xdate(on), "SubTotal": sub,
            "CurrencyCode": "GBP",
            "Allocations": [{"Date": xdate(d), "Amount": a, "Invoice": {"InvoiceID": iid}} for iid, d, a in allocations]}


_WHERE = re.compile(r'(Type)=="(\w+)"|(Date)(<=|>=|>|<)DateTime\((\d+),(\d+),(\d+)\)')


def matches(record, where):
    """The `where` clauses the pack sends: Type=="X", Date op DateTime(y,m,d),
    and Status=="X" OR Status=="Y"."""
    statuses = set(re.findall(r'Status=="(\w+)"', where or ""))
    if statuses and record.get("Status") not in statuses:
        return False
    for m in _WHERE.finditer(where or ""):
        if m.group(1):
            if record.get("Type") != m.group(2):
                return False
            continue
        on = pack()._day(record.get("Date"))
        limit = date(int(m.group(5)), int(m.group(6)), int(m.group(7)))
        if not {"<=": on <= limit, ">=": on >= limit, ">": on > limit, "<": on < limit}[m.group(4)]:
            return False
    return True


class FakeXero:
    def __init__(self, *, org=None, invoices=(), credit_notes=(), prepayments=(), overpayments=(), pnl=None,
                 bs=None, fail=(), delay=0.0):
        self.org = org if org is not None else {
            "Name": "New Body Ltd", "OrganisationEntityType": "COMPANY", "TaxNumber": "", "BaseCurrency": "GBP",
            "FinancialYearEndDay": 31, "FinancialYearEndMonth": 3}
        self.invoices = list(invoices)
        self.records = {"CreditNotes": list(credit_notes), "Prepayments": list(prepayments),
                        "Overpayments": list(overpayments)}
        self.pnl, self.bs = pnl or pnl_report(), bs or bs_report()
        self.fail, self.delay, self.calls, self.kwargs = set(fail), delay, [], {}
        self.in_flight = self.peak = 0

    async def _go(self, name, value, **kw):
        self.calls.append(name)
        self.kwargs.setdefault(name, []).append(kw)
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        try:
            await asyncio.sleep(self.delay)
            if name in self.fail:
                raise RuntimeError(f"{name} unavailable")
            return value
        finally:
            self.in_flight -= 1

    @staticmethod
    def _page(rows, page):
        return rows[(page - 1) * 100: page * 100]

    async def get_organisation(self):
        return await self._go("organisation", self.org)

    async def get_profit_and_loss(self, from_date=None, to_date=None, periods=None, timeframe=None):
        return await self._go("pnl", self.pnl, from_date=from_date, to_date=to_date, periods=periods,
                              timeframe=timeframe)

    async def get_balance_sheet(self, date=None, periods=None, timeframe=None):
        return await self._go("bs", self.bs, date=date, periods=periods, timeframe=timeframe)

    async def get_trial_balance(self, date=None):
        return await self._go("tb", report("Trial Balance", [
            {"RowType": "Header", "Cells": [cell("Account"), cell("Debit"), cell("Credit")]},
            {"RowType": "Section", "Title": "Revenue", "Rows": [
                {"RowType": "Row", "Cells": [cell("200"), cell(""), cell("120000.00")]}]}]), date=date)

    async def get_invoice_list(self, *, where=None, statuses=None, modified_since=None, page=1):
        wanted = set((statuses or "").split(",")) - {""}
        rows = [i for i in self.invoices if (not wanted or i["Status"] in wanted) and matches(i, where)
                and (not modified_since or i["UpdatedDateUTC"] >= modified_since)]      # Xero's If-Modified-Since
        return await self._go("invoices", {"Invoices": self._page(rows, page)}, where=where, statuses=statuses)

    async def get_records(self, resource, *, where=None, statuses=None, page=1):
        if resource == "Payments":
            rows = [dict(p, Status="AUTHORISED") for i in self.invoices for p in i["Payments"] if matches(p, where)]
        else:
            assert statuses is None, "Statuses isn't a documented filter for credit records"
            rows = [r for r in self.records[resource] if matches(r, where)]
        return await self._go(resource, {resource: self._page(rows, page)}, where=where)

    async def get_invoices_by_ids(self, ids):
        return await self._go("by_ids", [i for i in self.invoices if i["InvoiceID"] in set(ids)], ids=list(ids))


@pytest.fixture
def engine(tmp_path):
    e = create_engine("sqlite:///" + str(tmp_path / "acc2.sqlite"))
    with e.begin() as c:
        c.execute(text("""CREATE TABLE accounting_transactions (
            id TEXT PRIMARY KEY, business_id TEXT NOT NULL, import_id TEXT, category_id TEXT,
            transaction_date DATE NOT NULL, description TEXT NOT NULL, amount NUMERIC NOT NULL,
            type VARCHAR(20) NOT NULL, reference VARCHAR(100), payee_payer VARCHAR(255), account VARCHAR(100),
            notes TEXT, is_reconciled BOOLEAN DEFAULT 0, is_archived BOOLEAN DEFAULT 0, created_at TEXT,
            updated_at TEXT, external_id TEXT, external_source TEXT, provider TEXT DEFAULT 'xero')"""))
        c.execute(text("CREATE TABLE accounting_categories (id TEXT PRIMARY KEY, business_id TEXT, name TEXT, "
                       "type TEXT, color TEXT, created_at TEXT, updated_at TEXT)"))
        c.execute(text("CREATE TABLE business_settings (id TEXT NOT NULL, business_id TEXT PRIMARY KEY, "
                       "settings TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"))
        c.execute(text("CREATE TABLE xero_connections (id TEXT PRIMARY KEY, business_id TEXT, is_active BOOLEAN, "
                       "last_sync_at TEXT)"))
        c.execute(text("CREATE TABLE invoices (id TEXT PRIMARY KEY, business_id TEXT, invoice_number TEXT, "
                       "customer_name TEXT, amount NUMERIC, status TEXT, issue_date DATE, due_date DATE, "
                       "archived BOOLEAN DEFAULT 0)"))
        c.execute(text("INSERT INTO business_settings VALUES ('s', :b, '{}', 'x', 'x')"), {"b": BIZ})
    yield e
    e.dispose()


def txn(engine, on, kind, amount, category=None, *, reconciled=True, archived=False, desc="Line", source="xero"):
    cid = None
    with engine.begin() as c:
        if category:
            cid = c.execute(text("SELECT id FROM accounting_categories WHERE name = :n AND business_id = :b"),
                            {"n": category, "b": BIZ}).scalar()
            if not cid:
                cid = str(uuid.uuid4())
                c.execute(text("INSERT INTO accounting_categories (id, business_id, name, type) VALUES (:i, :b, :n, :t)"),
                          {"i": cid, "b": BIZ, "n": category, "t": kind})
        c.execute(text("INSERT INTO accounting_transactions (id, business_id, category_id, transaction_date, description, "
                       "amount, type, is_reconciled, is_archived, external_source, created_at) VALUES "
                       "(:i, :b, :c, :d, :desc, :a, :t, :r, :x, :s, 'x')"),
                  {"i": str(uuid.uuid4()), "b": BIZ, "c": cid, "d": on.isoformat(), "desc": desc, "a": str(amount),
                   "t": kind, "r": reconciled, "x": archived, "s": source})


def synced(engine, when="2026-11-01T00:00:00+00:00"):
    with engine.begin() as c:
        c.execute(text("INSERT INTO xero_connections VALUES ('c', :b, 1, :w)"), {"b": BIZ, "w": when})


def build(engine, xero=None, *, start=None, end=None, ask=None, today=TODAY, now=None, xero_error=None):
    with Session(engine) as s:
        return asyncio.run(pack().build(s, BIZ, xero, start=start, end=end, today=today, ask=ask, now=now,
                                        xero_error=xero_error))


def sheet(result, name):
    wb = load_workbook(io.BytesIO(result["content"]))
    assert name in wb.sheetnames, f"{name} not in {wb.sheetnames}"
    return [tuple(row) for row in wb[name].iter_rows(values_only=True)]


def find(rows, label):
    for row in rows:
        if row and row[0] == label:
            return row
    raise AssertionError(f"no row {label!r}")


def words(rows):
    return " ".join(str(c) for row in rows for c in row if c is not None)


# ----------------------------------------------------------- A8 periods ---

@pytest.mark.parametrize("today,day,month,expected", [
    (date(2026, 11, 2), 31, 3, (date(2025, 4, 1), date(2026, 3, 31))),     # last completed year
    (date(2026, 3, 31), 31, 3, (date(2024, 4, 1), date(2025, 3, 31))),     # year end day itself: not complete
    (date(2026, 4, 1), 31, 3, (date(2025, 4, 1), date(2026, 3, 31))),
    (date(2026, 11, 2), 31, 12, (date(2025, 1, 1), date(2025, 12, 31))),
    (date(2025, 6, 1), 29, 2, (date(2024, 3, 1), date(2025, 2, 28))),      # Xero's 29 Feb in a non-leap year
    (date(2024, 6, 1), 28, 2, (date(2023, 3, 1), date(2024, 2, 29))),      # month end in a leap year
    (date(2026, 11, 2), None, None, (date(2025, 4, 6), date(2026, 4, 5))),  # no Xero: last tax year
])
def test_a8_default_period_is_the_last_completed_financial_year(today, day, month, expected):
    assert pack().default_period(today, day, month) == expected


def test_a8_prior_period_is_a_year_earlier():
    assert pack().prior_period(date(2025, 4, 1), date(2026, 3, 31)) == (date(2024, 4, 1), date(2025, 3, 31))
    assert pack().prior_period(date(2023, 3, 1), date(2024, 2, 29)) == (date(2022, 3, 1), date(2023, 2, 28))
    # a month end stays a month end: the year to 28 Feb 2025 follows the year to 29 Feb 2024
    assert pack().prior_period(date(2024, 3, 1), date(2025, 2, 28)) == (date(2023, 3, 1), date(2024, 2, 29))


def test_a8_a_resolved_period_that_runs_backwards_is_refused(engine):
    """Only a start given, after the default end (review 1)."""
    with pytest.raises(pack().PeriodError):
        build(engine, FakeXero(), start=date(2026, 4, 1))


def test_the_default_period_follows_xeros_year_end(engine):
    out = build(engine, FakeXero())                              # 31 March, generated 2 Nov 2026
    assert out["period"] == FY
    assert out["filename"].endswith("2025-04-01-to-2026-03-31.xlsx")


# --------------------------------------------------- A1 Xero report rows ---

def test_a1_numbers_only_from_value_cells_never_labels_or_headers():
    rows = pack().report_rows(report("Trial Balance", [
        {"RowType": "Header", "Cells": [cell("Account"), cell("2026")]},
        {"RowType": "Section", "Title": "Revenue", "Rows": [
            {"RowType": "Row", "Cells": [cell("200"), cell("1,234.50")]},
            {"RowType": "Row", "Cells": [cell("Sales"), cell("n/a")]},
            {"RowType": "SummaryRow", "Cells": [cell("Total"), cell("-12.00")]}]}])["Reports"][0])
    by = {r["kind"]: [] for r in rows}
    for r in rows:
        by[r["kind"]].append(r["cells"])
    assert by["header"] == [["Account", "2026"]]
    assert by["title"] == [["Revenue"]]
    assert by["row"][0] == ["200", D("1234.50")]                     # the label "200" is never £200
    assert by["row"][1] == ["Sales", "n/a"]
    assert by["summary"] == [["Total", D("-12.00")]]


def test_a1_xero_figures_and_comparatives_are_written_exactly(engine):
    xero = FakeXero()
    out = build(engine, xero)
    pnl = sheet(out, "Profit & Loss")
    assert find(pnl, "Total Income")[1:3] == (120000, 100000)
    assert find(pnl, "Net Profit")[1:3] == (48000, 30000)
    assert find(sheet(out, "Trial Balance"), "200")[0] == "200"
    # comparatives are asked for, for the right dates
    assert xero.kwargs["pnl"] == [{"from_date": "2025-04-01", "to_date": "2026-03-31", "periods": 1,
                                   "timeframe": "YEAR"}]
    assert xero.kwargs["bs"] == [{"date": "2026-03-31", "periods": 1, "timeframe": "YEAR"}]
    assert xero.kwargs["tb"] == [{"date": "2026-03-31"}]


# --------------------------------------------- A3 aged at the period end ---

def test_a3_aged_balances_are_as_at_the_period_end():
    end = date(2026, 3, 31)
    invs = [
        invoice(1, due=date(2026, 3, 31), total="100.00"),                                   # current
        invoice(2, due=date(2026, 3, 1), total="200.00", payments=[(date(2026, 3, 15), "50.00")]),   # 30 days: 150
        invoice(3, due=date(2026, 1, 15), total="300.00", payments=[(date(2026, 4, 20), "300.00")],
                status="PAID", due_now="0.00"),                                            # paid AFTER the end: owed then
        invoice(4, due=date(2025, 12, 1), total="400.00", status="PAID", due_now="0.00",
                payments=[(date(2026, 3, 30), "400.00")]),                                 # paid before the end: gone
        invoice(5, due=date(2025, 11, 1), total="500.00", credits=[(date(2026, 2, 1), "100.00")]),     # 150 days: 400
        invoice(6, issued=date(2026, 4, 2), due=date(2026, 5, 2), total="999.00"),           # issued after the end
        invoice(7, due=date(2026, 1, 1), total="70.00", status="VOIDED"),
        invoice(8, kind="ACCPAY", due=date(2026, 3, 1), total="80.00", contact="Supplier"),
    ]
    rows = pack().aged(invs, end, "ACCREC")
    assert len(rows) == 1
    r = rows[0]
    assert (r["contact"], r["current"], r["d1_30"], r["d31_60"], r["d61_90"], r["d90_plus"], r["total"]) == \
        ("Client Ltd", D("100.00"), D("150.00"), D("0"), D("300.00"), D("400.00"), D("950.00"))
    pay = pack().aged(invs, end, "ACCPAY")
    assert pay[0]["contact"] == "Supplier" and pay[0]["d1_30"] == D("80.00")


@pytest.mark.parametrize("days,bucket", [(0, "current"), (1, "d1_30"), (30, "d1_30"), (31, "d31_60"),
                                         (60, "d31_60"), (61, "d61_90"), (90, "d61_90"), (91, "d90_plus")])
def test_a3_bucket_edges(days, bucket):
    end = date(2026, 3, 31)
    rows = pack().aged([invoice(1, issued=date(2025, 1, 1), due=end - timedelta(days=days))], end, "ACCREC")
    assert rows[0][bucket] == D("120.00") and rows[0]["total"] == D("120.00")


def test_a3_an_invoice_paid_after_the_end_is_found_however_it_was_entered(engine):
    """Codex review 1: paid today by a payment dated after the year end, but
    entered (last modified) before it: an If-Modified-Since search misses it."""
    out = build(engine, FakeXero(invoices=[
        invoice(1, due=date(2026, 3, 1), total="1200.00", sub="1000.00", tax="200.00", status="PAID", due_now="0.00",
                payments=[(date(2026, 4, 10), "1200.00")], updated=date(2026, 3, 25)),
        invoice(2, due=date(2026, 3, 1), total="50.00", status="PAID", due_now="0.00",
                payments=[(date(2026, 3, 20), "50.00")]),                           # paid before: not owed
    ]), start=FY[0], end=FY[1])
    debtors = sheet(out, "Aged Debtors")
    assert any("31/03/2026" in str(c) for row in debtors[:3] for c in row if c)
    assert find(debtors, "Client Ltd")[-1] == 1200
    assert find(debtors, "Total")[-1] == 1200


def test_a3_a_credit_allocated_after_the_end_does_not_reduce_the_debt_at_the_end(engine):
    inv = invoice(1, due=date(2026, 3, 1), total="300.00", status="PAID", due_now="0.00")
    early = credit_note(1, allocations=[("inv-1", date(2026, 3, 10), "100.00")])
    late = credit_note(2, allocations=[("inv-1", date(2026, 4, 10), "200.00")])
    out = build(engine, FakeXero(invoices=[inv], credit_notes=[early, late]), start=FY[0], end=FY[1])
    assert find(sheet(out, "Aged Debtors"), "Client Ltd")[-1] == 200       # 300 less the March credit only


def test_a3_every_page_of_open_invoices_is_aged(engine):
    many = [invoice(n, due=date(2026, 3, 31), total="1.00", contact=f"C{n:03d}") for n in range(150)]
    out = build(engine, FakeXero(invoices=many), start=FY[0], end=FY[1])
    assert find(sheet(out, "Aged Debtors"), "Total")[-1] == 150


def test_a3_other_currencies_are_never_added_in_and_are_listed(engine):
    out = build(engine, FakeXero(invoices=[
        invoice(1, due=date(2026, 3, 31), total="1000.00"),
        invoice(2, due=date(2026, 3, 31), total="1000.00", currency="USD", contact="US Client")]),
        start=FY[0], end=FY[1])
    debtors = sheet(out, "Aged Debtors")
    assert find(debtors, "Total")[-1] == 1000
    assert "US Client" not in words(debtors)
    ends = words(sheet(out, "Loose Ends"))
    assert "other currencies" in ends and "USD" in ends


# ------------------------------------------------- A4 invoices in period ---

def test_a4_invoices_are_those_issued_in_the_period_and_add_up():
    invs = [invoice(1, issued=date(2025, 4, 1)), invoice(2, issued=date(2026, 3, 31)),
            invoice(3, issued=date(2025, 3, 31)), invoice(4, issued=date(2026, 4, 1)),
            invoice(5, issued=date(2025, 6, 1), status="VOIDED"), invoice(6, issued=date(2025, 6, 1), status="DRAFT"),
            invoice(7, kind="ACCPAY", issued=date(2025, 6, 1)),
            invoice(8, issued=date(2025, 6, 1), currency="EUR"),
            invoice(9, issued=date(2025, 7, 1), sub="100.00", tax="20.00", total="120.01")]   # Xero rounding
    rows = pack().period_invoices(invs, *FY)
    assert [r["number"] for r in rows] == ["INV-1", "INV-9", "INV-2"]
    for r in rows:
        assert r["net"] + r["vat"] + r["rounding"] == r["gross"]
    assert rows[1]["rounding"] == D("0.01") and rows[0]["rounding"] == D("0")


def test_a4_the_invoices_tab_shows_the_rounding_and_totals(engine):
    out = build(engine, FakeXero(invoices=[invoice(1, issued=date(2025, 7, 1), total="120.01"),
                                           invoice(2, issued=date(2025, 8, 1))]), start=FY[0], end=FY[1])
    tab = sheet(out, "Invoices")
    assert tab[3][:8] == ("Invoice", "Customer", "Issued", "Due", "Net", "VAT", "Rounding", "Gross")
    assert find(tab, "Total")[4:8] == (200, 40, pytest.approx(0.01), pytest.approx(240.01))


# --------------------------------------------------- A2/A7 ledger P&L ---

def test_a7_without_xero_a_cash_pnl_with_last_year_that_ties_to_the_transactions(engine):
    txn(engine, date(2025, 5, 1), "income", "1000.10", "Sales")
    txn(engine, date(2025, 6, 1), "income", "0.20", "Sales")
    txn(engine, date(2025, 6, 2), "expense", "300.15", "Rent")
    txn(engine, date(2025, 6, 3), "expense", "50.00")                         # uncategorised
    txn(engine, date(2025, 6, 4), "expense", "999.00", "Rent", archived=True)  # hidden
    txn(engine, date(2024, 6, 4), "expense", "77.00", "Rent")                 # last year
    out = build(engine, None, start=date(2025, 4, 6), end=date(2026, 4, 5))
    pnl = sheet(out, "Profit & Loss")
    assert "cash basis" in words(pnl).lower() and "unaudited" in words(pnl).lower()
    assert find(pnl, "Sales")[1:3] == (pytest.approx(1000.30), 0)
    assert find(pnl, "Rent")[1:3] == (pytest.approx(300.15), 77)              # last year beside this year
    assert find(pnl, "Total Income")[1] == pytest.approx(1000.30)
    assert find(pnl, "Uncategorised")[1] == pytest.approx(50.00)
    assert find(pnl, "Total Expenses")[1:3] == (pytest.approx(350.15), 77)
    assert find(pnl, "Net Profit")[1] == pytest.approx(650.15)
    tx = [r for r in sheet(out, "Transactions")[1:] if r and r[0] is not None]
    income = sum(D(str(r[5])) for r in tx if r[4] == "Income")
    expense = sum(D(str(r[5])) for r in tx if r[4] == "Expense")
    assert (len(tx), income, expense) == (4, D("1000.3"), D("350.15"))       # ties to the P&L exactly
    assert "Comparatives: 06/04/2024 to 05/04/2025" in words(sheet(out, "Summary"))


def test_a2_ledger_pnl_totals_are_exact_decimal_sums():
    lines = [{"type": "income", "amount": D("0.10"), "category": "A"}] * 3 + \
            [{"type": "expense", "amount": D("0.20"), "category": None}]
    p = pack().ledger_pnl(lines)
    assert p["total_income"] == D("0.30") and p["total_expense"] == D("0.20") and p["net"] == D("0.10")
    assert p["expense"] == [("Uncategorised", D("0.20"))]


# --------------------------------------------- A5 nothing missing silently ---

def test_a5_a_failed_report_is_listed_as_missing_with_its_reason(engine):
    out = build(engine, FakeXero(fail={"bs"}))
    assert "Balance Sheet" not in load_workbook(io.BytesIO(out["content"])).sheetnames
    assert "Balance Sheet" in out["missing"] and "unavailable" in out["missing"]["Balance Sheet"]
    assert "Balance Sheet: not included" in words(sheet(out, "Summary"))
    assert "Profit & Loss" in out["included"]


def test_a5_failed_invoice_records_drop_the_aged_tabs_with_the_reason(engine):
    out = build(engine, FakeXero(fail={"Payments"}))
    assert "Aged Debtors" in out["missing"] and "Payments unavailable" in out["missing"]["Aged Debtors"]
    assert "Aged Debtors" not in load_workbook(io.BytesIO(out["content"])).sheetnames


def test_a5_without_xero_the_balance_sheet_is_missing_with_the_reason(engine):
    out = build(engine, None)
    assert "Balance Sheet" in out["missing"] and "xero" in out["missing"]["Balance Sheet"].lower()


def test_a5_a_failed_xero_connection_says_so(engine):
    out = build(engine, None, xero_error="token refresh failed")
    assert "Xero connection failed: token refresh failed" in out["missing"]["Balance Sheet"]


# ------------------------------------------------------- A6 balance check ---

def test_a6_balance_sheet_that_does_not_balance_is_a_loose_end_with_the_difference(engine):
    assert pack().balance_difference(pack().report_rows(bs_report()["Reports"][0])) == D("0")
    out = build(engine, FakeXero(bs=bs_report(equity="29000.00")))
    assert find(sheet(out, "Loose Ends"), "Balance sheet doesn't balance")[2] == 1000


# ------------------------------------------------- A9 / loose ends ---

def test_a9_loose_ends_list_what_to_tidy(engine):
    txn(engine, date(2025, 5, 1), "expense", "40.00")                          # uncategorised
    txn(engine, date(2025, 5, 2), "expense", "60.00", "Rent", reconciled=False)
    with engine.begin() as c:
        c.execute(text("UPDATE business_settings SET settings = :s"), {"s": json.dumps(
            {"accounting_duplicates": {"hidden": {}, "kept_pairs": [], "review": [{"xero_id": "x", "uploads": ["u"]}]}})})
    synced(engine, "2026-02-01T00:00:00+00:00")
    out = build(engine, FakeXero(), start=FY[0], end=FY[1])
    ends = sheet(out, "Loose Ends")
    assert find(ends, "Uncategorised transactions")[1:3] == (1, 40)
    assert find(ends, "Unreconciled transactions")[1:3] == (1, 60)
    assert find(ends, "Possible duplicates waiting for review")[1] == 1
    assert "01/02/2026" in words([find(ends, "Last complete Xero sync is not after the period end")])


def test_a9_a_sync_after_the_period_end_is_not_a_loose_end(engine):
    synced(engine)
    out = build(engine, FakeXero(), start=FY[0], end=FY[1])
    assert "sync" not in words(sheet(out, "Loose Ends")[1:]).lower()


def test_a9_a_naive_sync_time_is_utc_not_london(engine):
    """31 Mar 23:30 UTC is 1 April in London (summer time): after the end (review 1)."""
    synced(engine, "2026-03-31 23:30:00")
    out = build(engine, FakeXero(), start=FY[0], end=FY[1])
    assert "sync" not in words(sheet(out, "Loose Ends")[1:]).lower()


def test_the_cash_summary_says_it_is_not_profit(engine):
    txn(engine, date(2025, 5, 1), "income", "100.00", "Sales")
    out = build(engine, FakeXero(), start=FY[0], end=FY[1])
    assert "not profit" in words(sheet(out, "Cash Summary")[:4]).lower()
    assert "Net Profit/Loss:" not in words(sheet(out, "Summary"))     # the old cash "profit" is gone


# ------------------------------------------------------------ tax points ---

def facts(**kw):
    base = dict(legal_type="company", vat_registered=True, turnover_12m=D("0"), capital_items=[], pension=D("1"),
                use_of_home=D("1"), vehicle_spend=D("0"), mileage=D("0"), profit=D("10000"),
                uncategorised_spend=D("0"), staff_entertainment=D("0"), period=FY)
    base.update(kw)
    return base


def codes(**kw):
    return {p["code"] for p in pack().tax_points(facts(**kw))}


def point(code, **kw):
    return next(p for p in pack().tax_points(facts(**kw)) if p["code"] == code)


def test_no_points_when_nothing_applies():
    assert codes() == set()


def test_t1_vat_threshold():
    t = pack().THRESHOLDS["vat_registration"]
    assert t == D("90000")
    assert "T1" in codes(vat_registered=False, turnover_12m=t * D("0.8"))
    assert "T1" not in codes(vat_registered=False, turnover_12m=t * D("0.8") - D("0.01"))
    assert "T1" not in codes(vat_registered=True, turnover_12m=t * 2)
    assert "T1" not in codes(vat_registered=None, turnover_12m=t * 2)
    assert "T1" not in codes(vat_registered=False, turnover_12m=None)


def test_t1_turnover_is_invoiced_sales_not_cash(engine):
    """Review 1: £100k invoiced with £60k collected must warn (cash in, loan
    included, is only £65k, under the 80% line); a loan recorded as income
    never counts."""
    sales = [invoice(n, issued=date(2025, 6, 1), sub="10000.00", tax="0.00", total="10000.00") for n in range(10)]
    txn(engine, date(2025, 7, 1), "income", "60000.00", "Sales")
    txn(engine, date(2025, 7, 2), "income", "5000.00", "Director loan")
    out = build(engine, FakeXero(invoices=sales), start=FY[0], end=FY[1])
    t1 = find(sheet(out, "Points to Discuss"), "T1")
    assert "£100,000.00" in t1[2] and "invoiced" in t1[2]
    credit = credit_note(1, on=date(2025, 9, 1), sub="40000.00")
    assert pack().invoiced_sales(sales, [credit], *FY) == D("60000.00")


def test_t2_capital_items():
    item = (date(2025, 6, 1), "Laptop", D("1200.00"))
    p = point("T2", capital_items=[item])
    assert p["figures"]["total"] == D("1200.00") and p["figures"]["count"] == 1
    assert "T2" not in codes()


def test_t2_facts_only_count_single_items_of_500_or_more_in_capital_categories():
    lines = [{"date": date(2025, 6, 1), "type": "expense", "amount": D("499.99"), "category": "Computer Equipment",
              "description": "Mouse"},
             {"date": date(2025, 6, 2), "type": "expense", "amount": D("500.00"), "category": "Tools", "description": "Drill"},
             {"date": date(2025, 6, 3), "type": "expense", "amount": D("5000.00"), "category": "Rent", "description": "Rent"}]
    f = pack().facts_from(lines, org=None, profit=None, turnover_12m=D("0"))
    assert [i[1] for i in f["capital_items"]] == ["Drill"]


def test_t3_pension_company_only():
    assert "T3" in codes(pension=D("0"))
    assert "T3" not in codes(pension=D("0"), legal_type="sole_trader")
    assert "T3" not in codes(pension=D("0"), legal_type=None)


def test_t4_use_of_home_sole_trader_only():
    assert "T4" in codes(legal_type="sole_trader", use_of_home=D("0"))
    assert "T4" not in codes(use_of_home=D("0"))


def test_t5_mileage():
    assert "T5" in codes(vehicle_spend=D("300"), mileage=D("0"))
    assert "T5" not in codes(vehicle_spend=D("300"), mileage=D("10"))


@pytest.mark.parametrize("period,expected,absent", [
    (FY, "45p a mile", "55p"),                                                  # year to 31 Mar 2026: before the rise
    ((date(2026, 4, 6), date(2027, 4, 5)), "55p a mile", "45p"),
    ((date(2026, 1, 1), date(2026, 12, 31)), "45p a mile until 05/04/2026 and 55p from 06/04/2026", None),
])
def test_t5_the_mileage_rate_is_the_one_for_the_period(period, expected, absent):
    """Review 1: 55p applies from 6 April 2026 only."""
    p = point("T5", vehicle_spend=D("300"), period=period)
    assert expected in p["text"]
    if absent:
        assert absent not in p["text"]


@pytest.mark.parametrize("profit,fires", [("45000", True), ("44999.99", False), ("55000", True), ("55000.01", False),
                                          ("225000", True), ("275000", True), ("150000", False)])
def test_t6_corporation_tax_band_edges(profit, fires):
    assert ("T6" in codes(profit=D(profit))) is fires
    assert "T6" not in codes(profit=D(profit), legal_type="sole_trader")


def test_t7_uncategorised_spending():
    assert "T7" in codes(uncategorised_spend=D("0.01"))


def test_t8_staff_entertainment_company_only_with_its_conditions():
    p = point("T8", staff_entertainment=D("400"))
    assert "all staff" in p["text"] and "not cash" in p["text"]
    assert "T8" not in codes(staff_entertainment=D("400"), legal_type="sole_trader")


def test_thresholds_are_dated_and_sourced():
    t = pack().THRESHOLDS
    assert t["checked"] == "2026-11-02" and t["sources"]
    assert t["mileage_first_10000"] == D("0.55") and t["ct_small_profits"] == D("50000")
    assert t["ct_main_rate_limit"] == D("250000") and t["staff_event_per_head"] == D("150")
    assert pack().mileage_rate(date(2026, 4, 5)) == D("0.45") and pack().mileage_rate(date(2026, 4, 6)) == D("0.55")


def test_every_point_is_framed_for_the_accountant():
    pts = pack().tax_points(facts(vat_registered=False, turnover_12m=D("80000"), pension=D("0"),
                                  uncategorised_spend=D("5"), vehicle_spend=D("1"), staff_entertainment=D("1")))
    assert len(pts) >= 5
    for p in pts:
        assert p["text"].endswith("Worth discussing with your accountant.")


# ------------------------------------------------------ W: AI wording ---

def _points():
    return pack().tax_points(facts(uncategorised_spend=D("125.50"), pension=D("0")))


@pytest.mark.parametrize("line,ok", [
    ("Spending without a category is harder for an accountant to check.", True),
    ("Claim £999k immediately.", False),
    ("Claim nine thousand pounds in tax relief.", False),
    ("You are guaranteed a tax refund.", False),
    ("You will save money by doing this.", False),
    ("This affects 3 things.", False),
    ("Roughly half of it may count.", False),
    ("A pension can help. Talk it through. Plan ahead. Then decide.", False),      # four sentences
    ("All your spending is tax deductible.", False),                                 # Codex review 2 probes
    ("Claim a dozen pounds in relief.", False),
    ("You qualify for tax relief.", False),
    ("Claim ½ of your costs.", False),
    ("Pension contributions are a common topic to raise with an accountant.", True),
    ("", False),
    (None, False),
])
def test_w_only_plain_lines_without_numbers_or_claims_survive(line, ok):
    assert pack().plain_line_ok(line) is ok


def test_w_the_rule_text_and_figures_are_never_changed_by_ai():
    pts = _points()

    async def ask(points):
        return {p["code"]: "You are guaranteed a £4,000 refund." if p["code"] == "T7"
                else "Pensions paid by a company are a common topic with accountants." for p in points}
    worded = asyncio.run(pack().word_points(pts, ask))
    for w, p in zip(worded, pts):
        assert (w["text"], w["figures"]) == (p["text"], p["figures"])
    by = {w["code"]: w for w in worded}
    assert by["T7"]["plain"] is None                                    # invented claim: dropped
    assert by["T3"]["plain"] == "Pensions paid by a company are a common topic with accountants."


@pytest.mark.parametrize("behaviour", ["raise", "garbage", "slow", "none"])
def test_w_ai_failure_leaves_the_rule_text_alone(behaviour, monkeypatch):
    pts = _points()
    monkeypatch.setattr(pack(), "WORDING_TIMEOUT_SECONDS", 0.05)

    async def ask(points):
        if behaviour == "raise":
            raise RuntimeError("openai down")
        if behaviour == "slow":
            await asyncio.sleep(1)                      # good wording, too late: never waited for
            return {p["code"]: "Late but fine." for p in points}
        return "not a dict"
    worded = asyncio.run(pack().word_points(pts, None if behaviour == "none" else ask))
    assert [(w["text"], w["plain"]) for w in worded] == [(p["text"], None) for p in pts]


def test_w_one_ai_call_per_pack_and_the_plain_line_is_labelled(engine):
    txn(engine, date(2025, 5, 1), "expense", "40.00")
    calls = []

    async def ask(points):
        calls.append(points)
        return {"T7": "Uncategorised spending is easy to overlook."}
    out = build(engine, FakeXero(), ask=ask, start=FY[0], end=FY[1])
    assert len(calls) == 1
    tab = sheet(out, "Points to Discuss")
    assert "accountant" in words(tab[:3]).lower() and "AI-written" in words(tab[:3])
    assert tab[3][3] == "In plain words (AI-written, may be imprecise)"
    assert "may be imprecise" in words(tab[:3])
    assert find(tab, "T7")[3] == "Uncategorised spending is easy to overlook."


def test_w_the_wording_call_goes_through_the_router_with_titles_only_and_is_metered(monkeypatch):
    from services import ai_costs, ai_router, profit_guard
    seen, saved = {}, []
    monkeypatch.setattr(profit_guard, "permits", lambda purpose: True)

    def json_chat(system, context, *, purpose, max_tokens):
        seen.update(context=context, purpose=purpose)
        ai_costs.note("openai", "gpt-6-luna", None, fallback=(100, 50))
        return {"T7": "Plain words."}
    monkeypatch.setattr(ai_router, "json_chat", json_chat)
    monkeypatch.setattr(ai_costs, "save", lambda s, bid, spent, *, purpose, **kw: saved.append((bid, purpose, spent)))
    ask = pack().make_ask(BIZ)
    answer = asyncio.run(ask(_points()))
    assert answer == {"T7": "Plain words."}
    assert seen["purpose"] == "wording"
    assert "125" not in json.dumps(seen["context"])                    # no figures reach the model
    assert saved and saved[0][:2] == (BIZ, "accountancy_pack") and saved[0][2]


def test_w_no_wording_at_the_profit_guard_limit(monkeypatch):
    from services import profit_guard
    monkeypatch.setattr(profit_guard, "permits", lambda purpose: False)
    assert pack().make_ask(BIZ) is None


# ------------------------------------------------------------- S: speed ---

def test_s_xero_reports_are_fetched_concurrently_but_at_most_five_at_once(engine):
    xero = FakeXero(delay=0.05)
    build(engine, xero, start=FY[0], end=FY[1])
    assert 1 < xero.peak <= 5


def test_s_xero_calls_go_through_the_rate_limit_wait(engine, monkeypatch):
    from services import xero_sync
    seen = []
    real = xero_sync._xero

    async def spy(call, *a, **kw):
        seen.append(getattr(call, "__name__", ""))
        return await real(call, *a, **kw)
    monkeypatch.setattr(xero_sync, "_xero", spy)
    build(engine, FakeXero(invoices=[invoice(1, status="PAID", payments=[(date(2026, 4, 1), "120.00")])]),
          start=FY[0], end=FY[1])
    assert {"get_organisation", "get_profit_and_loss", "get_balance_sheet", "get_trial_balance", "get_invoice_list",
            "get_records", "get_invoices_by_ids"} <= set(seen)


@pytest.mark.parametrize("instant,shown", [
    (datetime(2026, 7, 1, 23, 30, tzinfo=timezone.utc), "02/07/2026 00:30"),     # summer: UK is UTC+1
    (datetime(2026, 12, 1, 23, 30, tzinfo=timezone.utc), "01/12/2026 23:30"),
])
def test_the_generated_time_is_uk_time(engine, instant, shown):
    out = build(engine, None, now=instant)
    assert f"Generated: {shown} (UK time)" in words(sheet(out, "Summary"))


def test_a3_deleted_payments_and_voided_credits_never_reduce_a_debt():
    end = date(2026, 3, 31)
    inv = invoice(1, due=date(2026, 3, 1), total="300.00", payments=[(date(2026, 3, 10), "100.00")])
    inv["Payments"][0]["Status"] = "DELETED"
    voided = credit_note(1, status="VOIDED", allocations=[("inv-1", date(2026, 3, 12), "50.00")])
    allocs = pack().allocations_by_invoice([voided])
    assert allocs == {}
    assert pack().aged([inv], end, "ACCREC", allocs)[0]["total"] == D("300.00")



def test_a3_prepayments_and_overpayments_count_by_their_allocation_dates(engine):
    def credit(i, alloc_date):
        return {"Status": "AUTHORISED", "Date": xdate(date(2026, 1, 1)),
                "Allocations": [{"Date": xdate(alloc_date), "Amount": "100.00", "Invoice": {"InvoiceID": f"inv-{i}"}}]}
    invs = [invoice(1, due=date(2026, 3, 1), total="300.00", status="PAID", due_now="0.00"),
            invoice(2, due=date(2026, 3, 1), total="300.00", contact="Other Ltd")]
    out = build(engine, FakeXero(invoices=invs, prepayments=[credit(1, date(2026, 4, 2))],
                                 overpayments=[credit(2, date(2026, 3, 2))]), start=FY[0], end=FY[1])
    debtors = sheet(out, "Aged Debtors")
    assert find(debtors, "Client Ltd")[-1] == 300          # prepayment allocated after the end: still owed
    assert find(debtors, "Other Ltd")[-1] == 200           # overpayment allocated before the end: deducted


def test_a3_invoices_paid_after_the_end_are_fetched_in_batches_of_fifty(engine):
    many = [invoice(n, due=date(2026, 3, 1), total="2.00", status="PAID", due_now="0.00", contact=f"C{n:03d}",
                    payments=[(date(2026, 4, 2), "2.00")]) for n in range(60)]
    xero = FakeXero(invoices=many)
    out = build(engine, xero, start=FY[0], end=FY[1])
    assert find(sheet(out, "Aged Debtors"), "Total")[-1] == 120
    assert sorted(len(k["ids"]) for k in xero.kwargs["by_ids"]) == [10, 50]


def test_a5_an_organisation_that_cannot_be_read_falls_back_and_says_why(engine):
    txn(engine, date(2025, 5, 1), "income", "10.00", "Sales")
    out = build(engine, FakeXero(fail={"organisation"}))
    assert "Xero didn't answer" in out["missing"]["Balance Sheet"]
    assert "cash basis" in words(sheet(out, "Profit & Loss")).lower()        # the ledger P&L, not nothing


def test_a_non_gbp_organisation_is_shown_in_its_currency_with_no_pound_tax_points(engine):
    org = {"Name": "US Co", "OrganisationEntityType": "COMPANY", "TaxNumber": "", "BaseCurrency": "USD",
           "FinancialYearEndDay": 31, "FinancialYearEndMonth": 3}
    sales = [invoice(n, issued=date(2025, 6, 1), sub="10000.00", tax="0.00", total="10000.00", currency="USD")
             for n in range(10)]
    txn(engine, date(2025, 5, 1), "expense", "40.00")                       # would be T7 in pounds
    out = build(engine, FakeXero(org=org, invoices=sales + [invoice(99, due=date(2026, 3, 31), currency="USD")]),
                start=FY[0], end=FY[1])
    points = sheet(out, "Points to Discuss")
    assert not any(r and r[0] in ("T1", "T7") for r in points)
    assert "reports in USD" in words(points)
    assert "Currency: USD" in words(sheet(out, "Summary"))
    wb = load_workbook(io.BytesIO(out["content"]))
    total = next(r for r in wb["Aged Debtors"].iter_rows() if r[0].value == "Total")
    assert total[-1].value == 100120                         # ten open sales invoices plus one, in dollars
    assert "USD" in total[-1].number_format and "£" not in total[-1].number_format


# ------------------------------------------------------- the connection ---

class _Row:
    def __init__(self, expires):
        self.expires = expires


def _conn_engine(engine, expires):
    with engine.begin() as c:
        c.execute(text("DROP TABLE xero_connections"))
        c.execute(text("CREATE TABLE xero_connections (id TEXT, business_id TEXT, tenant_id TEXT, "
                       "token_ciphertext TEXT, token_expires_at TEXT, is_active BOOLEAN, last_sync_at TEXT)"))
        c.execute(text("INSERT INTO xero_connections VALUES ('c1', :b, 't1', 'secret', :e, 1, NULL)"),
                  {"b": BIZ, "e": expires})


class _Provider:
    def __init__(self, access_token, tenant_id):
        self.access_token, self.tenant_id = access_token, tenant_id


@pytest.mark.parametrize("expires,renewed,expect", [
    ("2026-11-02T12:00:00+00:00", None, ("token", None)),                      # fresh: used, no refresh
    ("2026-11-02T09:00:00+00:00", "new-token", ("new-token", None)),           # expired: renewed
    ("2026-11-02T09:00:00+00:00", None, (None, "couldn't be renewed")),        # expired, renewal failed: never used
])
def test_the_connection_never_uses_a_token_that_could_not_be_renewed(engine, expires, renewed, expect):
    _conn_engine(engine, expires)
    refreshed = []

    async def refresh(session, conn_id, tenant, bid, log):
        refreshed.append(conn_id)
        return renewed, None
    with Session(engine) as s:
        provider, error = asyncio.run(pack().connect(
            s, BIZ, refresh=refresh, decrypt=lambda c: "token", provider_cls=_Provider,
            now=datetime(2026, 11, 2, 10, tzinfo=timezone.utc)))
    token, reason = expect
    assert (provider.access_token if provider else None) == token
    assert (reason is None and error is None) or reason in error
    assert bool(refreshed) is expires.startswith("2026-11-02T09")


def test_no_connection_is_not_an_error(engine):
    _conn_engine(engine, "2026-11-02T12:00:00+00:00")
    with engine.begin() as c:
        c.execute(text("DELETE FROM xero_connections"))
    with Session(engine) as s:
        assert asyncio.run(pack().connect(s, BIZ, refresh=None, decrypt=None, provider_cls=None)) == (None, None)


def test_the_endpoint_builds_off_the_event_loop_and_a_backwards_period_is_400(monkeypatch):
    import threading
    from types import SimpleNamespace
    from fastapi import HTTPException
    import main
    seen = {}

    async def connect(*a, **kw):
        seen["connect_thread"] = threading.current_thread()
        return None, None

    async def build_ok(*a, **kw):
        seen["build_thread"] = threading.current_thread()
        return {"content": b"x", "filename": "pack.xlsx"}
    monkeypatch.setattr(pack(), "connect", connect)
    monkeypatch.setattr(pack(), "build", build_ok)
    monkeypatch.setattr(pack(), "make_ask", lambda bid: None)
    biz = SimpleNamespace(id=BIZ, name="Test")
    resp = asyncio.run(main.export_accountant_pack(period_start=None, period_end=None, user_business=(None, biz),
                                                   session=None))
    assert resp.headers["content-disposition"] == 'attachment; filename="pack.xlsx"'
    assert seen["connect_thread"] is not threading.main_thread() and seen["build_thread"] is not threading.main_thread()

    async def build_backwards(*a, **kw):
        raise pack().PeriodError("backwards")
    monkeypatch.setattr(pack(), "build", build_backwards)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(main.export_accountant_pack(period_start="2026-04-01", period_end=None, user_business=(None, biz),
                                                session=None))
    assert caught.value.status_code == 400


def test_w_a_slow_wording_call_never_holds_the_pack(monkeypatch):
    """Review 2: the router call is synchronous; the wait must still end on time."""
    import time
    from services import ai_costs, ai_router, profit_guard
    monkeypatch.setattr(profit_guard, "permits", lambda purpose: True)
    monkeypatch.setattr(pack(), "WORDING_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(ai_costs, "save", lambda *a, **kw: None)

    def slow(system, context, *, purpose, max_tokens):
        time.sleep(0.6)
        return {"T7": "Late."}
    monkeypatch.setattr(ai_router, "json_chat", slow)
    started = time.monotonic()
    worded = asyncio.run(pack().word_points(_points(), pack().make_ask(BIZ)))
    assert time.monotonic() - started < 0.4
    assert all(w["plain"] is None for w in worded)
