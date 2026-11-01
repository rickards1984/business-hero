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


# Mike approved these rules and tests on 1 Nov 2026; the strict-xfail marker is removed.


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
        # as live (audits/live-schema-public.txt): id, created_at, updated_at required, no defaults
        c.execute(text("CREATE TABLE business_settings (id TEXT NOT NULL, business_id TEXT PRIMARY KEY, "
                       "settings TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"))
        for b in (BIZ, OTHER):
            c.execute(text("INSERT INTO business_settings VALUES (:i, :b, '{}', 'x', 'x')"), {"i": str(uuid.uuid4()), "b": b})
    yield e
    e.dispose()


def xdate(d: date) -> str:
    return f"/Date({int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()) * 1000}+0000)/"


def bank(i, *, kind="SPEND", total=10.0, on=date(2026, 9, 1), status="AUTHORISED", code="400", ref=None):
    return {"BankTransactionID": f"bt-{i}", "Type": kind, "Status": status, "Total": total, "Date": xdate(on),
            "Contact": {"Name": f"Supplier {i}"}, "Reference": ref,
            "LineItems": [{"Description": f"Item {i}", "AccountCode": code, "LineAmount": total}]}


def payment(i, *, kind="ACCRECPAYMENT", amount=100.0, on=date(2026, 10, 2), invoice="inv-1", status="AUTHORISED",
            bank_amount=None, account="bank-1"):
    p = {"PaymentID": f"pay-{i}", "PaymentType": kind, "Status": status, "Amount": amount, "Date": xdate(on),
         "Account": {"AccountID": account},
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
        self.accounts = [{"AccountID": "bank-1", "Type": "BANK"}, {"AccountID": "clear-1", "Type": "CURRLIAB"}]

    async def get_accounts(self):
        self.calls.append(("accounts", None, None))
        return self.accounts

    async def get_trial_balance(self):
        self.calls.append(("chart", None, None))
        return {"Reports": []}

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


def run(engine, xero, *, moment=NOW, business=BIZ, banks=("bank-1",), others=("clear-1",)):
    with Session(engine) as s:
        out = asyncio.run(sync().run(s, business, xero, moment=moment, account_lookup=LOOKUP,
                                     bank_accounts=None if banks is None else list(banks),
                                     other_accounts=None if others is None else list(others)))
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



def test_sync_all_can_actually_run_the_syncs_it_wraps():
    """THE ROOT CAUSE (6 July 2026): the rate limiter raises unless called with
    a request; sync-all called the decorated functions without one, so every
    sync from the page failed before doing anything, silently."""
    import asyncio
    import inspect
    sync()
    import main
    assert hasattr(main.sync_xero_transactions, "__wrapped__") and hasattr(main.sync_xero_invoices, "__wrapped__")
    with pytest.raises(Exception, match="request"):
        asyncio.run(main.sync_xero_transactions(user_business=None, session=None))   # what sync-all used to do
    source = inspect.getsource(main.sync_all_accounting)
    assert "sync_xero_transactions.__wrapped__(request=request" in source
    assert "sync_xero_invoices.__wrapped__(request=request" in source


# ------------------------------------------------- speed (Mike, 1 Nov 2026) ---

def test_a_routine_sync_after_the_first_asks_xero_twice(engine):
    """After the first full run, a sync with nothing new is two requests:
    one page of bank transactions, one of payments. No invoices, nothing else."""
    run(engine, FakeXero(bank_rows=[bank(i) for i in range(250)], payments=[payment(1)]))
    quiet = FakeXero()
    out = run(engine, quiet, moment=NOW + timedelta(hours=4))
    assert out["complete"] and len(quiet.calls) == 2
    assert {k for k, _, _ in quiet.calls} == {"bank", "payments"}


def test_the_chart_of_accounts_is_read_from_xero_at_most_once_a_day(engine):
    class Chart:
        calls = 0

        async def get_accounts(self):
            return [{"AccountID": "bank-1", "Type": "BANK"}, {"AccountID": "clear-1", "Type": "CURRLIAB"}]

        async def get_trial_balance(self):
            Chart.calls += 1
            return {"Reports": [{"Rows": [{"RowType": "Section", "Title": "Revenue", "Rows": [
                {"Cells": [{"Value": "Sales (200)", "Attributes": [{"Value": "uuid-200"}]}, {"Value": "1"}]}]}]}]}
    chart = Chart()
    for hours in (0, 6, 23):
        with Session(engine) as s:
            lookup = asyncio.run(sync().cached_accounts(s, BIZ, chart, NOW + timedelta(hours=hours)))
            s.commit()
    assert Chart.calls == 1 and lookup["200"] == {"name": "Sales", "type": "income"}
    with Session(engine) as s:
        asyncio.run(sync().cached_accounts(s, BIZ, chart, NOW + timedelta(hours=25)))
        s.commit()
    assert Chart.calls == 2


# ------------------------------------------------- Codex review 1 regressions ---

def test_a_clearing_account_settlement_is_counted_once(engine):
    """P1: a card processor's workflow. Invoice payments go to a CLEARING
    account (not cash yet); the bank receipt settling it, net of the fee, is
    the cash. £100 of sales, a £2 fee, £98 into the bank: income is £98, once."""
    xero = FakeXero(
        payments=[payment(1, amount=60.0, account="clear-1"), payment(2, amount=40.0, account="clear-1")],
        bank_rows=[bank(1, kind="RECEIVE", total=98.0, on=date(2026, 10, 3))])
    run(engine, xero)
    visible = rows(engine, archived=False)
    assert [(r["external_id"], float(r["amount"])) for r in visible] == [("bt-1", 98.0)]


def test_a_payment_to_an_account_xero_still_cannot_identify_is_held_back(engine):
    xero = FakeXero(payments=[payment(1, account="mystery")])
    out = run(engine, xero)
    assert rows(engine) == [] and out["complete"] is False
    assert "cursor" not in doc(engine).get("xero_sync", {}), "tried again next sync, never lost"


def test_a_business_without_a_settings_row_gets_one_and_its_cursor(engine):
    """P2: the live table requires id, created_at and updated_at."""
    with engine.begin() as c:
        c.execute(text("DELETE FROM business_settings WHERE business_id = :b"), {"b": BIZ})
    out = run(engine, FakeXero(bank_rows=[bank(1)]))
    assert out["complete"] is True and doc(engine)["xero_sync"]["cursor"]


def test_a_failed_row_never_leaves_a_dead_category_for_the_next(engine, monkeypatch):
    """P2: the category created inside a rolled-back savepoint must not be reused."""
    real = sync()._write
    calls = {"n": 0}

    def fail_first(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("the first write fails after its category was created")
        return real(*args, **kwargs)
    monkeypatch.setattr(sync(), "_write", fail_first)
    out = run(engine, FakeXero(bank_rows=[bank(1, code="400"), bank(2, code="400")]))
    second = next(r for r in rows(engine) if r["external_id"] == "bt-2")
    with engine.connect() as c:
        assert c.execute(text("SELECT count(*) FROM accounting_categories WHERE id = :i"),
                         {"i": second["category_id"]}).scalar() == 1, "a live category, not a rolled-back one"
    assert len(out["errors"]) == 1


def test_keeping_one_candidate_leaves_the_others_for_review(engine):
    """P2: decisions are per pair."""
    a = upload(engine, amount=-9.99, kind="expense", on=date(2026, 6, 30))
    b = upload(engine, amount=-9.99, kind="expense", on=date(2026, 7, 1))
    run(engine, FakeXero(bank_rows=[bank(1, total=9.99, on=date(2026, 7, 1))]))
    with Session(engine) as s:
        sync().resolve(s, BIZ, a, "keep")
        s.commit()
    review = doc(engine)["accounting_duplicates"]["review"]
    assert len(review) == 1 and review[0]["uploads"] == [b]
    with Session(engine) as s:
        listed = sync().duplicates(s, BIZ)
    assert [u["id"] for u in listed["review"][0]["uploads"]] == [b]


def test_a_kept_pair_doesnt_stop_the_upload_matching_another_xero_row(engine):
    """P2: keeping an upload against Xero row A says nothing about Xero row B."""
    up = upload(engine, amount=-20.0, kind="expense", on=date(2026, 6, 30))
    run(engine, FakeXero(bank_rows=[bank(1, total=20.0, on=date(2026, 6, 30))]))
    first = doc(engine)["accounting_duplicates"]["hidden"][up]
    with Session(engine) as s:
        sync().resolve(s, BIZ, up, "keep", first)
        s.commit()
    assert doc(engine)["accounting_duplicates"]["kept_pairs"] == [[up, first]]
    run(engine, FakeXero(bank_rows=[bank(2, total=20.0, on=date(2026, 7, 1))]), moment=NOW + timedelta(hours=1))
    assert up not in {r["id"] for r in rows(engine, archived=False)}, "hidden against the other Xero row"


def test_hiding_one_upload_settles_that_xero_row_and_frees_the_others(engine):
    a = upload(engine, amount=-9.99, kind="expense", on=date(2026, 6, 30))
    b = upload(engine, amount=-9.99, kind="expense", on=date(2026, 7, 1))
    run(engine, FakeXero(bank_rows=[bank(1, total=9.99, on=date(2026, 7, 1))]))
    with Session(engine) as s:
        sync().resolve(s, BIZ, b, "hide")
        s.commit()
    d = doc(engine)["accounting_duplicates"]
    assert d["review"] == [] and b in d["hidden"] and a in {r["id"] for r in rows(engine, archived=False)}


def test_a_sync_and_a_decision_take_the_businesss_lock():
    """P2: one writer per business (the settings row lock)."""
    import inspect
    source = inspect.getsource(sync().run) + inspect.getsource(sync().resolve)
    assert source.count("_lock(session, bid)") == 2


def test_the_refresh_lock_serialises_callers_on_different_event_loops():
    """P2: worker threads run their own loops; one refresh at a time across all."""
    import threading
    from providers import token_refresh_lock as trl
    trl._last_refresh_times.clear()
    refreshes = []

    async def current():
        return {"access_token": "old", "refresh_token": "r", "token_refreshed_at": None}

    async def refresh(_token):
        refreshes.append(1)
        await asyncio.sleep(0.2)
        return {"access_token": "new", "refresh_token": "r2"}

    async def save(*_args):
        return None

    def caller(results):
        results.append(asyncio.run(trl.coordinated_token_refresh("biz-lock", "xero", current, refresh, save)))
    results = []
    threads = [threading.Thread(target=caller, args=(results,)) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert len(refreshes) == 1 and len(results) == 3


def test_a_routine_invoice_sync_is_one_request_and_emails_are_asked_once(engine):
    """P2 (speed): the page's invoice sync is incremental, one stream."""
    class Inv:
        def __init__(self, invoices):
            self.invoices, self.calls, self.emails = invoices, [], 0

        async def get_invoices(self, modified_since=None, status=None, page=1):
            self.calls.append((modified_since, status, page))
            return {"Invoices": self.invoices[(page - 1) * 100: page * 100]}

        async def get_contact_email_checked(self, contact_id):
            self.emails += 1
            return "client@example.invalid"
    first = Inv([{"InvoiceID": f"i{n}"} for n in range(150)])
    with Session(engine) as s:
        got, complete = asyncio.run(sync().fetch_invoices(s, BIZ, first))
        sync().invoices_done(s, BIZ, NOW)
        for _ in range(3):
            asyncio.run(sync().contact_email(s, BIZ, first, "contact-1"))
        s.commit()
    assert len(got) == 150 and complete and first.calls[0][0] is None and first.emails == 1
    assert "VOIDED" in first.calls[0][1] and "PAID" in first.calls[0][1]
    quiet = Inv([])
    with Session(engine) as s:
        asyncio.run(sync().fetch_invoices(s, BIZ, quiet))
    assert len(quiet.calls) == 1 and quiet.calls[0][0] == "2026-11-01T09:55:00"



# ------------------------------------------------- Codex review 2 regressions ---

def test_a_payment_into_a_bank_added_today_is_counted(engine):
    """P1: an account the cached list doesn't know is checked with Xero, never assumed not a bank."""
    xero = FakeXero(payments=[payment(1, account="bank-2")])
    xero.accounts.append({"AccountID": "bank-2", "Type": "BANK"})
    out = run(engine, xero)
    assert out["complete"] is True and [r["external_id"] for r in rows(engine)] == ["payment:pay-1"]
    assert "bank-2" in doc(engine)["xero_accounts"]["bank"]


def test_credit_card_and_paypal_accounts_count_as_bank(engine):
    """Xero: Type BANK with BankAccountType CREDITCARD / PAYPAL."""
    xero = FakeXero(payments=[payment(1, kind="ACCPAYPAYMENT", account="card-1", invoice="bill-9")],
                    invoices={"bill-9": {"InvoiceID": "bill-9", "LineItems": [{"AccountCode": "400", "LineAmount": 1}]}})
    xero.accounts.append({"AccountID": "card-1", "Type": "BANK", "BankAccountType": "CREDITCARD"})
    run(engine, xero, banks=("bank-1",), others=("clear-1",))
    assert [r["type"] for r in rows(engine)] == ["expense"]


def test_a_failed_chart_refresh_is_never_marked_fresh(engine):
    class Broken:
        async def get_trial_balance(self):
            return {"Reports": []}

        async def get_accounts(self):
            raise RuntimeError("Xero is down")
    with Session(engine) as s:
        asyncio.run(sync().cached_chart(s, BIZ, Broken(), NOW))
        s.commit()
    assert "at" not in doc(engine).get("xero_accounts", {})


def test_a_stale_second_tab_cannot_hide_another_upload_against_the_same_xero_row(engine):
    """P2: one-to-one holds even when two screens decide."""
    a = upload(engine, amount=-9.99, kind="expense", on=date(2026, 6, 30))
    b = upload(engine, amount=-9.99, kind="expense", on=date(2026, 7, 1))
    run(engine, FakeXero(bank_rows=[bank(1, total=9.99, on=date(2026, 7, 1))]))
    xero_row = doc(engine)["accounting_duplicates"]["review"][0]["xero"]
    with Session(engine) as s:
        sync().resolve(s, BIZ, a, "hide", xero_row)
        s.commit()
    with Session(engine) as s, pytest.raises(Exception) as exc:
        sync().resolve(s, BIZ, b, "hide", xero_row)
    assert getattr(exc.value, "status_code", None) == 409
    assert b in {r["id"] for r in rows(engine, archived=False)}
    with Session(engine) as s, pytest.raises(Exception) as exc:
        sync().resolve(s, BIZ, b, "keep", "not-a-row")
    assert getattr(exc.value, "status_code", None) == 404


def test_a_failed_email_lookup_is_asked_again(engine):
    """P2: a 429 is not "no email"."""
    class Flaky:
        calls = 0

        async def get_contact_email_checked(self, contact_id):
            Flaky.calls += 1
            if Flaky.calls == 1:
                raise RuntimeError("HTTP 429")
            return "client@example.invalid"
    with Session(engine) as s:
        first = asyncio.run(sync().contact_email(s, BIZ, Flaky(), "c-1"))
        second = asyncio.run(sync().contact_email(s, BIZ, Flaky(), "c-1"))
        third = asyncio.run(sync().contact_email(s, BIZ, Flaky(), "c-1"))
        s.commit()
    assert (first, second, third) == (None, "client@example.invalid", "client@example.invalid") and Flaky.calls == 2


def test_last_synced_means_the_transactions_synced():
    """P2: one meaning everywhere: the ledger's transactions fully synced."""
    import inspect
    sync()
    import main
    source = inspect.getsource(main.sync_all_accounting)
    # the transaction run's own start: the same moment the connection is stamped with (Codex review 3)
    assert '"synced_at": (txn_result or {}).get("synced_at") if (txn_result or {}).get("complete") else None' in source


# ------------------------------------------------- Codex review 3 regressions ---

def test_creating_a_missing_settings_row_never_blanks_one_made_in_between(engine):
    """P2: the absence check, then another writer creates the row, then ours: insert-only."""
    with engine.begin() as c:
        c.execute(text("DELETE FROM business_settings WHERE business_id = :b"), {"b": BIZ})

    class Racing:
        """The first look finds nothing; another writer then commits its row."""
        def __init__(self, session):
            self.s, self.looked = session, False

        def __getattr__(self, name):
            return getattr(self.s, name)

        def execute(self, statement, params=None):
            sql = str(statement)
            if not self.looked and sql.startswith("SELECT 1 FROM business_settings WHERE business_id"):
                self.looked = True
                with engine.begin() as c:
                    c.execute(text("INSERT INTO business_settings VALUES (:i, :b, :s, 'x', 'x')"),
                              {"i": str(uuid.uuid4()), "b": BIZ, "s": json.dumps({"theirs": True})})
                return self.s.execute(text("SELECT 1 WHERE 0"))
            return self.s.execute(statement, params)
    with Session(engine) as s:
        sync()._lock(Racing(s), BIZ)
        s.commit()
    assert doc(engine) == {"theirs": True}


def test_a_failed_email_lookup_holds_the_invoice_cursor():
    """P2: so the unchanged invoice is fetched, and its contact asked, again."""
    import inspect
    sync()
    import main
    source = inspect.getsource(main.sync_xero_invoices)
    assert "if email_failures:\n        inv_complete = False" in source


def test_a_failed_lookup_is_counted(engine):
    class Down:
        async def get_contact_email_checked(self, contact_id):
            raise RuntimeError("HTTP 429")
    with Session(engine) as s:
        found, failed = asyncio.run(sync().lookup_emails(s, BIZ, Down(), ["c-1", "c-2"]))
    assert found == {} and failed == 2


def test_a_stale_hide_against_a_since_voided_xero_row_is_refused(engine):
    """P2: hide only against a live Xero transaction; restoring stays possible."""
    a = upload(engine, amount=-9.99, kind="expense", on=date(2026, 6, 30))
    upload(engine, amount=-9.99, kind="expense", on=date(2026, 7, 1))
    run(engine, FakeXero(bank_rows=[bank(1, total=9.99, on=date(2026, 7, 1))]))
    xero_row = doc(engine)["accounting_duplicates"]["review"][0]["xero"]
    run(engine, FakeXero(bank_rows=[bank(1, total=9.99, on=date(2026, 7, 1), status="VOIDED")]),
        moment=NOW + timedelta(hours=1))
    with Session(engine) as s, pytest.raises(Exception) as exc:
        sync().resolve(s, BIZ, a, "hide", xero_row)
    assert getattr(exc.value, "status_code", None) == 409
    assert a in {r["id"] for r in rows(engine, archived=False)}
