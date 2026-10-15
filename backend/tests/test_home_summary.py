"""NS-B7 — the Aria home's figures are computed on the server, over every
row, and Aria's invoice summary uses the same receivables (Codex NS-B7
review 1, findings 1, 2, 5, 6). SQLite, synthetic data only."""

import os
from datetime import date, datetime, timezone

for _key in ("SUPABASE_DATABASE_URL", "DATABASE_URL"):
    if os.getenv(_key) and not os.environ[_key].startswith("sqlite"):
        raise RuntimeError("REFUSING TO RUN: non-SQLite database configured")

import pytest  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from services import home_summary  # noqa: E402

A, B = "biz-a", "biz-b"
NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def engine():
    eng = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    with eng.begin() as c:
        c.execute(text("""CREATE TABLE invoices (id INTEGER PRIMARY KEY, business_id TEXT, amount NUMERIC,
            amount_due NUMERIC, amount_paid NUMERIC DEFAULT 0, paid_amount NUMERIC, status TEXT,
            due_date DATE, archived BOOLEAN DEFAULT 0)"""))
        c.execute(text("""CREATE TABLE email_messages (id INTEGER PRIMARY KEY, business_id TEXT,
            ai_category TEXT, received_at TIMESTAMP)"""))
        c.execute(text("CREATE TABLE email_accounts (id TEXT, business_id TEXT)"))
        c.execute(text("CREATE TABLE email_sync_states (email_account_id TEXT, last_synced_at TIMESTAMP)"))
        c.execute(text("CREATE TABLE xero_connections (business_id TEXT, last_sync_at TIMESTAMP)"))
        c.execute(text("CREATE TABLE accounting_connections (business_id TEXT, last_sync_at TIMESTAMP)"))
    return eng


def invoice(eng, bid=A, amount=100, status="sent", due="2026-10-01", amount_due=None,
            amount_paid=0, paid_amount=None, archived=False):
    with eng.begin() as c:
        c.execute(text("""INSERT INTO invoices (business_id, amount, amount_due, amount_paid, paid_amount,
            status, due_date, archived) VALUES (:b, :a, :ad, :ap, :pa, :s, :d, :ar)"""),
                  {"b": bid, "a": amount, "ad": amount_due, "ap": amount_paid, "pa": paid_amount,
                   "s": status, "d": due, "ar": archived})


def owed(eng, bid=A):
    with eng.connect() as c:
        return home_summary.receivables(c, bid, date(2026, 10, 15))


def test_every_invoice_counts_not_just_the_first_fifty(engine):
    """Finding 1: 60 paid invoices and one overdue one still reports it."""
    for _ in range(60):
        invoice(engine, status="paid", due="2026-01-01")
    invoice(engine, amount=250, status="sent", due="2026-10-01")
    assert owed(engine) == {"outstanding_total": 250.0, "outstanding_count": 1,
                            "overdue_total": 250.0, "overdue_count": 1}


def test_part_payments_leave_the_balance_owed(engine):
    """Finding 2: £1,000 with £400 paid is £600 owed, whichever column holds it."""
    invoice(engine, amount=1000, status="partially_paid", amount_paid=400)
    invoice(engine, amount=500, status="authorised", paid_amount=200, due="2026-11-01")
    invoice(engine, amount=900, status="sent", amount_due=300)  # the provider's own figure
    r = owed(engine)
    assert r["outstanding_total"] == 600 + 300 + 300
    assert r["overdue_total"] == 600 + 300 and r["overdue_count"] == 2


@pytest.mark.parametrize("status", ["paid", "draft", "void", "voided", "deleted", "cancelled", "PAID"])
def test_nothing_settled_or_never_issued_is_owed(engine, status):
    invoice(engine, amount=100, status=status)
    assert owed(engine)["outstanding_total"] == 0


def test_archived_and_fully_paid_invoices_are_not_owed(engine):
    invoice(engine, amount=100, archived=True)
    invoice(engine, amount=100, amount_paid=100)
    assert owed(engine)["outstanding_count"] == 0


def test_another_business_is_never_counted(engine):
    invoice(engine, bid=B, amount=999)
    assert owed(engine, A)["outstanding_total"] == 0


def test_due_today_is_not_yet_overdue(engine):
    invoice(engine, amount=100, due="2026-10-15")
    assert owed(engine)["overdue_count"] == 0 and owed(engine)["outstanding_count"] == 1


def test_emails_needing_action_count_every_message_in_the_window(engine):
    """Finding 5: all of them, not a sample of 200 — and the window is stated."""
    with engine.begin() as c:
        for i in range(250):
            c.execute(text("INSERT INTO email_messages (business_id, ai_category, received_at) "
                           "VALUES (:b, 'Action Required', :r)"),
                      {"b": A, "r": datetime(2026, 10, 10, tzinfo=timezone.utc)})
        c.execute(text("INSERT INTO email_messages (business_id, ai_category, received_at) "
                       "VALUES (:b, 'Action Required', :r)"),
                  {"b": A, "r": datetime(2026, 9, 1, tzinfo=timezone.utc)})  # outside the window
        c.execute(text("INSERT INTO email_messages (business_id, ai_category, received_at) "
                       "VALUES (:b, 'Action Required', :r)"),
                  {"b": B, "r": datetime(2026, 10, 10, tzinfo=timezone.utc)})
    with engine.connect() as c:
        s = home_summary.summary(c, A, NOW)
    assert s["emails"] == {"action_required": 250, "window_days": 14}


def test_the_summary_says_when_each_source_last_synced(engine):
    """Finding 6: figures carry their age."""
    with engine.begin() as c:
        c.execute(text("INSERT INTO email_accounts VALUES ('acc1', :b)"), {"b": A})
        c.execute(text("INSERT INTO email_sync_states VALUES ('acc1', '2026-10-15 11:50:00')"))
        c.execute(text("INSERT INTO xero_connections VALUES (:b, '2026-10-15 10:00:00')"), {"b": A})
        c.execute(text("INSERT INTO xero_connections VALUES (:b, '2026-10-15 11:59:00')"), {"b": B})
    with engine.connect() as c:
        s = home_summary.summary(c, A, NOW)
    assert s["synced"] == {"email": "2026-10-15T11:50:00+00:00",
                           "accounting": "2026-10-15T10:00:00+00:00"}
    assert s["as_of"] == "2026-10-15T12:00:00+00:00"


def test_a_source_never_synced_says_so(engine):
    with engine.connect() as c:
        s = home_summary.summary(c, A, NOW)
    assert s["synced"] == {"email": None, "accounting": None}


def test_aria_and_the_home_agree_on_what_is_owed(engine, monkeypatch):
    """One truth (North Star P2): Aria's invoice summary uses the same function."""
    import assistant_tools
    invoice(engine, amount=1000, status="partially_paid", amount_paid=400)
    for _ in range(55):
        invoice(engine, status="paid", due="2026-01-01")
    result = assistant_tools._get_invoice_summary(engine, A, {})
    home = owed(engine)
    assert result["total_outstanding"] == home["outstanding_total"] == 600
    assert result["total_overdue"] == home["overdue_total"]
    assert result["overdue_count"] == home["overdue_count"]
