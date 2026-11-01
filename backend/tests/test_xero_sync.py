"""ACC-1 — the Xero sync brings in everything, once (docs/ACC-1-TICKET.md). RED:
the ledger every report and the accountancy pack read.

Mike, 1 Nov 2026: transactions stopped at 4 July though Xero is reconciled
to yesterday. Bank transactions AND payments (lines matched to invoices or
bills) are brought in, with no page cap; transfers are never income or
expense; a run that missed anything never moves the marker; one bad row never
loses the rest; and a Xero copy of an uploaded transaction hides the upload
(Xero wins), unless the match is ambiguous, when Mike decides.

Tests first: strict xfail until Mike approves and the module exists. A fake
Xero; SQLite with the live table's own constraints; no network.
"""
import asyncio
import importlib
import importlib.util
import json
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlmodel import Session

NOW = datetime(2026, 11, 1, 10, tzinfo=timezone.utc)
BIZ, OTHER = str(uuid.uuid4()), str(uuid.uuid4())


class Missing(AssertionError):
    """Only the intentional absence of the module may be xfailed."""


pytestmark = pytest.mark.xfail(strict=True, raises=Missing,
                               reason="ACC-1: tests first, until Mike approves and the module exists")


def sync():
    if importlib.util.find_spec("services.xero_sync") is None:
        raise Missing("backend/services/xero_sync.py does not exist yet")
    return importlib.import_module("services.xero_sync")


@pytest.fixture
def engine(tmp_path):
    e = create_engine("sqlite:///" + str(tmp_path / "acc1.sqlite"))
    with e.begin() as c:
        c.execute(text("""CREATE TABLE accounting_transactions (
            id TEXT PRIMARY KEY, business_id TEXT NOT NULL, import_id TEXT, category_id TEXT,
            transaction_date DATE NOT NULL, description TEXT NOT NULL, amount NUMERIC NOT NULL,
            type VARCHAR(20) NOT NULL CHECK (type IN ('income', 'expense')),
            reference VARCHAR(100), payee_payer VARCHAR(255), account VARCHAR(100), notes TEXT,
            is_reconciled BOOLEAN DEFAULT 0, is_archived BOOLEAN DEFAULT 0,
            created_at TEXT, updated_at TEXT, external_id TEXT, external_source TEXT, provider TEXT DEFAULT 'xero')"""))
        c.execute(text("CREATE UNIQUE INDEX idx_accounting_txn_external ON accounting_transactions "
                       "(business_id, external_source, external_id) WHERE external_id IS NOT NULL"))
        c.execute(text("CREATE TABLE accounting_categories (id TEXT PRIMARY KEY, business_id TEXT, name TEXT, "
                       "type TEXT, color TEXT, created_at TEXT, updated_at TEXT)"))
        c.execute(text("CREATE TABLE business_settings (business_id TEXT PRIMARY KEY, settings TEXT)"))
        for b in (BIZ, OTHER):
            c.execute(text("INSERT INTO business_settings VALUES (:b, '{}')"), {"b": b})
    yield e
    e.dispose()


def xdate(d: date) -> str:
    return f"/Date({int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()) * 1000}+0000)/"


def bank(i, *, kind="SPEND", total=10.0, on=date(2026, 9, 1), status="AUTHORISED", code="400", ref=None):
    return {"BankTransactionID": f"bt-{i}", "Type": kind, "Status": status, "Total": total, "Date": xdate(on),
            "Contact": {"Name": f"Supplier {i}"}, "Reference": ref,
            "LineItems": [{"Description": f"Item {i}", "AccountCode": code, "LineAmount": total}]}


def payment(i, *, kind="ACCRECPAYMENT", amount=100.0, on=date(2026, 10, 2), invoice="inv-1", status="AUTHORISED",
            bank_amount=None):
    p = {"PaymentID": f"pay-{i}", "PaymentType": kind, "Status": status, "Amount": amount, "Date": xdate(on),
         "Invoice": {"InvoiceID": invoice, "InvoiceNumber": f"INV-{invoice}", "Contact": {"Name": "Client Ltd"}}}
    if bank_amount is not None:
        p["BankAmount"] = bank_amount
    return p


class FakeXero:
    """Pages of 100, like Xero. Records what it was asked."""

    def __init__(self, bank_rows=(), payments=(), invoices=None, always_full=False, fail_on=None):
        self.bank_rows, self.payments = list(bank_rows), list(payments)
        self.invoices = invoices or {"inv-1": {"InvoiceID": "inv-1", "InvoiceNumber": "INV-1",
                                                "LineItems": [{"AccountCode": "200", "LineAmount": 100}]}}
        self.always_full, self.fail_on, self.calls = always_full, fail_on, []

    def _page(self, rows, page):
        if self.always_full:
            return [dict(rows[0], BankTransactionID=f"bt-p{page}-{n}") for n in range(100)] if rows else []
        return rows[(page - 1) * 100: page * 100]

    async def get_bank_transactions(self, modified_since=None, page=1):
        self.calls.append(("bank", modified_since, page))
        return {"BankTransactions": self._page(self.bank_rows, page)}

    async def get_payments(self, modified_since=None, page=1):
        self.calls.append(("payments", modified_since, page))
        return {"Payments": self.payments[(page - 1) * 100: page * 100]}

    async def get_invoices_by_ids(self, ids):
        self.calls.append(("invoices", tuple(ids), None))
        return [self.invoices[i] for i in ids if i in self.invoices]


LOOKUP = {"200": {"name": "Sales", "type": "income"}, "400": {"name": "Advertising", "type": "expense"}}


def run(engine, xero, *, moment=NOW, business=BIZ):
    with Session(engine) as s:
        out = asyncio.run(sync().run(s, business, xero, moment=moment, account_lookup=LOOKUP))
        s.commit()
        return out


def rows(engine, business=BIZ, archived=None):
    sql = "SELECT * FROM accounting_transactions WHERE business_id = :b"
    if archived is not None:
        sql += " AND is_archived = :a"
    with engine.connect() as c:
        return [dict(r) for r in c.execute(text(sql), {"b": business, "a": archived}).mappings()]


def doc(engine, business=BIZ):
    with engine.connect() as c:
        return json.loads(c.execute(text("SELECT settings FROM business_settings WHERE business_id = :b"),
                                    {"b": business}).scalar() or "{}")


def upload(engine, *, amount, kind, on, business=BIZ, import_id="imp-1"):
    ident = str(uuid.uuid4())
    with engine.begin() as c:
        c.execute(text("INSERT INTO accounting_transactions (id, business_id, import_id, transaction_date, description, "
                       "amount, type, is_archived) VALUES (:i, :b, :imp, :d, 'uploaded', :a, :t, 0)"),
                  {"i": ident, "b": business, "imp": import_id, "d": on.isoformat(), "a": amount, "t": kind})
    return ident


# --------------------------------------------------------------- everything ---

def test_more_than_a_thousand_transactions_all_arrive(engine):
    xero = FakeXero(bank_rows=[bank(i, on=date(2026, 1, 1) + timedelta(days=i % 300)) for i in range(2350)])
    out = run(engine, xero)
    assert out["complete"] is True and out["new"] == 2350 and len(rows(engine)) == 2350
    assert max(p for k, _, p in xero.calls if k == "bank") == 24


def test_a_runaway_list_stops_incomplete_and_never_moves_the_marker(engine):
    xero = FakeXero(bank_rows=[bank(0)], always_full=True)
    out = run(engine, xero)
    assert out["complete"] is False
    assert "cursor" not in doc(engine).get("xero_sync", {})


def test_payments_matched_to_invoices_and_bills_arrive(engine):
    xero = FakeXero(payments=[payment(1, kind="ACCRECPAYMENT", amount=250.0),
                              payment(2, kind="ACCPAYPAYMENT", amount=80.0, invoice="bill-9"),
                              payment(3, kind="ARCREDITPAYMENT", amount=20.0),
                              payment(4, kind="APCREDITPAYMENT", amount=15.0, invoice="bill-9")],
                    invoices={"inv-1": {"InvoiceID": "inv-1", "InvoiceNumber": "INV-1",
                                        "LineItems": [{"AccountCode": "200", "LineAmount": 250}]},
                              "bill-9": {"InvoiceID": "bill-9", "InvoiceNumber": "B-9",
                                         "LineItems": [{"AccountCode": "400", "LineAmount": 80}]}})
    run(engine, xero)
    got = {r["external_id"]: (r["type"], float(r["amount"])) for r in rows(engine)}
    assert got == {"payment:pay-1": ("income", 250.0), "payment:pay-2": ("expense", -80.0),
                   "payment:pay-3": ("expense", -20.0), "payment:pay-4": ("income", 15.0)}
    first = next(r for r in rows(engine) if r["external_id"] == "payment:pay-1")
    assert first["reference"] == "INV-inv-1" and first["transaction_date"] == "2026-10-02"
    with engine.connect() as c:
        assert c.execute(text("SELECT name FROM accounting_categories WHERE id = :i"),
                         {"i": first["category_id"]}).scalar() == "Sales"


def test_a_payment_uses_the_bank_accounts_amount(engine):
    run(engine, FakeXero(payments=[payment(1, amount=100.0, bank_amount=86.5)]))
    assert float(rows(engine)[0]["amount"]) == 86.5


def test_an_unknown_payment_type_is_skipped_not_guessed(engine):
    out = run(engine, FakeXero(payments=[payment(1, kind="SOMETHINGNEW")]))
    assert rows(engine) == [] and out["skipped"] == 1


# ------------------------------------------------------------ types and money ---

def test_transfers_between_own_accounts_are_never_income_or_expense(engine):
    run(engine, FakeXero(bank_rows=[bank(1, kind="SPEND-TRANSFER"), bank(2, kind="RECEIVE-TRANSFER")]))
    assert rows(engine) == []


def test_a_transfer_stored_by_the_old_sync_is_archived(engine):
    with engine.begin() as c:                  # the old code booked it as an expense
        c.execute(text("INSERT INTO accounting_transactions (id, business_id, transaction_date, description, amount, "
                       "type, external_id, external_source, is_archived) VALUES ('old', :b, '2026-06-01', 'x', -500, "
                       "'expense', 'bt-7', 'xero', 0)"), {"b": BIZ})
    run(engine, FakeXero(bank_rows=[bank(7, kind="SPEND-TRANSFER", total=500.0)]))
    assert rows(engine, archived=False) == [] and rows(engine)[0]["is_archived"] in (1, True)


@pytest.mark.parametrize("kind,expected", [("RECEIVE", "income"), ("RECEIVE-OVERPAYMENT", "income"),
                                           ("RECEIVE-PREPAYMENT", "income"), ("SPEND", "expense"),
                                           ("SPEND-OVERPAYMENT", "expense"), ("SPEND-PREPAYMENT", "expense")])
def test_each_bank_transaction_type_has_its_direction(engine, kind, expected):
    run(engine, FakeXero(bank_rows=[bank(1, kind=kind, total=40.0)]))
    r = rows(engine)[0]
    assert r["type"] == expected and float(r["amount"]) == (40.0 if expected == "income" else -40.0)


def test_deleted_or_voided_in_xero_is_archived_and_restored_if_it_returns(engine):
    run(engine, FakeXero(bank_rows=[bank(1), bank(2)]))
    run(engine, FakeXero(bank_rows=[bank(1, status="DELETED"), bank(2, status="VOIDED")]))
    assert rows(engine, archived=False) == []
    run(engine, FakeXero(bank_rows=[bank(1)]))
    assert [r["external_id"] for r in rows(engine, archived=False)] == ["bt-1"]


def test_a_changed_date_or_amount_follows_xero(engine):
    run(engine, FakeXero(bank_rows=[bank(1, total=10.0, on=date(2026, 9, 1))]))
    run(engine, FakeXero(bank_rows=[bank(1, total=12.5, on=date(2026, 9, 3))]))
    r = rows(engine)[0]
    assert r["transaction_date"] == "2026-09-03" and float(r["amount"]) == -12.5


def test_one_bad_row_never_loses_the_rest_and_holds_the_marker(engine):
    good = [bank(i) for i in range(5)]
    bad = dict(bank(99), Date="not a date")
    out = run(engine, FakeXero(bank_rows=good[:2] + [bad] + good[2:]))
    assert len(rows(engine)) == 5 and out["errors"] and out["complete"] is False
    assert "cursor" not in doc(engine).get("xero_sync", {})


def test_long_text_is_cut_to_the_columns(engine):
    run(engine, FakeXero(bank_rows=[bank(1, ref="R" * 300)]))
    assert len(rows(engine)[0]["reference"]) == 100


# ------------------------------------------------------------------ marker ---

def test_the_first_run_is_full_and_later_runs_start_before_the_last_began(engine):
    with engine.begin() as c:
        c.execute(text("UPDATE business_settings SET settings = :s WHERE business_id = :b"),
                  {"s": json.dumps({"xero_sync": {"cursor": "2026-07-04T00:00:00"}}), "b": BIZ})   # an old-style cursor
    xero = FakeXero(bank_rows=[bank(1)])
    run(engine, xero)
    assert all(since is None for k, since, _ in xero.calls if k in ("bank", "payments")), "full re-sync once"
    later = FakeXero(bank_rows=[bank(2)])
    run(engine, later, moment=NOW + timedelta(hours=1))
    assert {since for k, since, _ in later.calls if k in ("bank", "payments")} == {"2026-11-01T09:55:00"}


# -------------------------------------------------------------- duplicates ---

def test_a_xero_copy_of_an_uploaded_transaction_hides_the_upload(engine):
    up = upload(engine, amount=-42.10, kind="expense", on=date(2026, 6, 30))
    out = run(engine, FakeXero(bank_rows=[bank(1, total=42.10, on=date(2026, 7, 2))]))
    assert out["duplicates_hidden"] == 1
    visible = rows(engine, archived=False)
    assert [r["external_id"] for r in visible] == ["bt-1"]
    assert up in doc(engine)["accounting_duplicates"]["hidden"]


@pytest.mark.parametrize("amount,on,kind", [(-42.11, date(2026, 6, 30), "expense"),     # a penny out
                                            (-42.10, date(2026, 6, 25), "expense"),     # 7 days away
                                            (42.10, date(2026, 6, 30), "income")])      # the other direction
def test_only_a_true_match_hides_an_upload(engine, amount, on, kind):
    upload(engine, amount=amount, kind=kind, on=on)
    out = run(engine, FakeXero(bank_rows=[bank(1, total=42.10, on=date(2026, 7, 2))]))
    assert out["duplicates_hidden"] == 0 and len(rows(engine, archived=False)) == 2


def test_two_possible_uploads_are_left_for_mike(engine):
    a = upload(engine, amount=-9.99, kind="expense", on=date(2026, 6, 30))
    b = upload(engine, amount=-9.99, kind="expense", on=date(2026, 7, 1))
    out = run(engine, FakeXero(bank_rows=[bank(1, total=9.99, on=date(2026, 7, 1))]))
    assert out["duplicates_hidden"] == 0 and out["needs_review"] == 1
    review = doc(engine)["accounting_duplicates"]["review"]
    assert len(review) == 1 and set(review[0]["uploads"]) == {a, b}


def test_an_upload_is_matched_once_at_most(engine):
    upload(engine, amount=-5.0, kind="expense", on=date(2026, 6, 30))
    out = run(engine, FakeXero(bank_rows=[bank(1, total=5.0, on=date(2026, 6, 30)),
                                          bank(2, total=5.0, on=date(2026, 7, 1))]))
    assert out["duplicates_hidden"] == 1 and len(rows(engine, archived=False)) == 2


def test_typed_in_entries_and_other_businesses_are_never_touched(engine):
    with engine.begin() as c:
        c.execute(text("INSERT INTO accounting_transactions (id, business_id, transaction_date, description, amount, "
                       "type, is_archived) VALUES ('typed', :b, '2026-06-30', 'typed', -42.10, 'expense', 0)"), {"b": BIZ})
    upload(engine, amount=-42.10, kind="expense", on=date(2026, 6, 30), business=OTHER)
    run(engine, FakeXero(bank_rows=[bank(1, total=42.10, on=date(2026, 6, 30))]))
    assert len(rows(engine, archived=False)) == 2 and len(rows(engine, OTHER, archived=False)) == 1


def test_a_pair_mike_keeps_is_never_hidden_again(engine):
    up = upload(engine, amount=-42.10, kind="expense", on=date(2026, 6, 30))
    run(engine, FakeXero(bank_rows=[bank(1, total=42.10, on=date(2026, 6, 30))]))
    with Session(engine) as s:
        sync().resolve(s, BIZ, up, "keep")
        s.commit()
    assert len(rows(engine, archived=False)) == 2
    with engine.begin() as c:
        c.execute(text("UPDATE business_settings SET settings = json_set(settings, '$.xero_sync.version', 1) "
                       "WHERE business_id = :b"), {"b": BIZ})       # force another full run
    run(engine, FakeXero(bank_rows=[bank(1, total=42.10, on=date(2026, 6, 30))]))
    assert len(rows(engine, archived=False)) == 2


def test_mike_hides_a_reviewed_upload(engine):
    a = upload(engine, amount=-9.99, kind="expense", on=date(2026, 6, 30))
    upload(engine, amount=-9.99, kind="expense", on=date(2026, 7, 1))
    run(engine, FakeXero(bank_rows=[bank(1, total=9.99, on=date(2026, 7, 1))]))
    with Session(engine) as s:
        sync().resolve(s, BIZ, a, "hide")
        s.commit()
    assert a not in {r["id"] for r in rows(engine, archived=False)}
    assert doc(engine)["accounting_duplicates"]["review"] == []


# ------------------------------------------------------------------ wiring ---

def test_the_sync_runs_off_the_servers_event_loop_and_sync_all_reports_failure():
    import inspect
    sync()
    import main
    source = inspect.getsource(main.sync_xero_transactions)
    assert "to_thread" in source and "xero_sync.run" in inspect.getsource(main)
    all_source = inspect.getsource(main.sync_all_accounting)
    assert '"success": all_ok' in all_source or "'success': all_ok" in all_source


def test_each_listed_transaction_says_where_it_came_from():
    import inspect
    sync()
    import accounting
    source = inspect.getsource(accounting.list_transactions)
    assert '"source"' in source and "xero_payment" in inspect.getsource(sync())
