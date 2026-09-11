"""BH-003 — tenant isolation on the BACKEND path, against a real database.

RC1 P0-9. `docs/CURRENT_STATE.md` calls this "the highest-value missing test
in the repository"; the July 2026 audit asked for it and it did not exist.

### Why this is the path that needs testing

There are two data paths with opposite isolation mechanisms (`AGENTS.md` §4):

  frontend -> supabase-js, anon key  -> RLS is the gate
  backend  -> elevated role          -> **RLS is bypassed entirely**

On the backend path the ONLY thing keeping one business out of another's rows
is the application remembering to write `WHERE business_id = ...` — every
time, on every join, forever. There is no second gate. BH-002 was exactly this
failure: the transaction filter was scoped and the category join was not, and
six screens returned another tenant's data.

This file is the generic version of that test, so the next one is caught by
the suite rather than by a reviewer.

### What is covered, and what is NOT

This runs the REAL endpoint functions against a REAL SQLite database seeded
with two synthetic tenants. Not fakes: a fake session can only prove which SQL
was emitted, which is what BH-002's first test did — and Codex correctly called
that a tripwire, not proof.

`UNCOVERED` at the bottom of this file is a deliberate, readable registry of
what is not yet tested and why. **It is part of the deliverable.** An honest
list of gaps is worth more than a number that implies coverage nobody checked.

### Not covered here at all: the RLS path

The anon-key half of P0-9 needs a real Postgres with the live policies —
`supabase start`, which needs Docker. **Docker is not installed on this
machine**, so that half is blocked, not done. See `UNCOVERED`.

All data is synthetic. Nothing touches a live or staging database.
"""

import asyncio
import sqlite3
import unittest
import uuid
from datetime import date, datetime

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

import accounting

BUSINESS_A = str(uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"))
BUSINESS_B = str(uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"))

# Every string below belongs to business B. If any of them reaches a caller
# authenticated as business A, that is a tenant-isolation failure. Distinctive
# on purpose, so a leak is unmistakable in an assertion message.
B_SECRETS = [
    "B-PRIVATE-CATEGORY",
    "B-PRIVATE-TRANSACTION",
    "B-PRIVATE-PAYEE",
    "B-PRIVATE-REFERENCE",
    "B-PRIVATE-NOTE",
]

SCHEMA = """
CREATE TABLE accounting_categories (
    id TEXT PRIMARY KEY, business_id TEXT NOT NULL,
    name TEXT, type TEXT, color TEXT, icon TEXT,
    is_default BOOLEAN DEFAULT 0, created_at TIMESTAMP
);
CREATE TABLE accounting_transactions (
    id TEXT PRIMARY KEY, business_id TEXT NOT NULL, category_id TEXT,
    transaction_date DATE, description TEXT, amount NUMERIC, type TEXT,
    reference TEXT, payee_payer TEXT, account TEXT, notes TEXT,
    is_reconciled BOOLEAN DEFAULT 0, is_archived BOOLEAN DEFAULT 0,
    created_at TIMESTAMP, updated_at TIMESTAMP, import_id TEXT
);
"""


def list_transactions_as(session, caller, **overrides):
    """Call the real endpoint with EVERY parameter given explicitly.

    Calling a FastAPI endpoint as a plain function does not apply its
    `Query(...)` defaults — the parameter keeps the `Query` object itself,
    which is truthy. Omitting `search` therefore took the search branch and
    emitted Postgres-only `ILIKE`, which SQLite rejects. Nothing to do with
    isolation; it would have looked like one if left unexplained.
    """
    params = dict(type=None, category_id=None, start_date=None, end_date=None,
                  search=None, is_reconciled=None, limit=50, page=1, offset=None)
    params.update(overrides)
    return asyncio.run(accounting.list_transactions(
        user_business=caller, session=session, **params))


def list_categories_as(session, caller, type=None):
    return asyncio.run(accounting.list_categories(
        type=type, user_business=caller, session=session))


class FakeBusiness:
    def __init__(self, business_id):
        self.id = business_id


def as_business(business_id):
    """The (user, business) tuple the endpoints destructure."""
    return (object(), FakeBusiness(business_id))


class TwoTenantDatabase:
    """A real SQLite database holding two businesses' accounting data."""

    def __init__(self):
        # PARSE_DECLTYPES so DATE and TIMESTAMP columns come back as date and
        # datetime objects. Without it SQLite hands back strings, the endpoint
        # calls .isoformat() on them and raises — an artefact of the fixture,
        # not a defect in the code under test.
        self.engine = create_engine(
            "sqlite://",
            connect_args={"detect_types": sqlite3.PARSE_DECLTYPES},
        )
        self.session = Session(self.engine)
        for statement in SCHEMA.strip().split(";"):
            if statement.strip():
                self.session.execute(text(statement))
        self._seed()
        self.session.commit()

    def _seed(self):
        now = datetime(2026, 9, 1, 12, 0, 0)

        # Business A: ordinary, unremarkable data.
        self.a_category = str(uuid.uuid4())
        self._category(self.a_category, BUSINESS_A, "A Office Costs", now)
        self.a_transaction = str(uuid.uuid4())
        self._transaction(self.a_transaction, BUSINESS_A, self.a_category,
                          "A's own transaction", "A-PAYEE", "A-REF", "A-NOTE", now)

        # Business B: everything distinctively labelled.
        self.b_category = str(uuid.uuid4())
        self._category(self.b_category, BUSINESS_B, "B-PRIVATE-CATEGORY", now)
        self.b_transaction = str(uuid.uuid4())
        self._transaction(self.b_transaction, BUSINESS_B, self.b_category,
                          "B-PRIVATE-TRANSACTION", "B-PRIVATE-PAYEE",
                          "B-PRIVATE-REFERENCE", "B-PRIVATE-NOTE", now)

        # The contaminated row BH-002 could create: A's transaction pointing at
        # B's category. It must render as uncategorised, never as B's name.
        self.a_contaminated = str(uuid.uuid4())
        self._transaction(self.a_contaminated, BUSINESS_A, self.b_category,
                          "A's row with a foreign category", "A-PAYEE-2",
                          "A-REF-2", "A-NOTE-2", now)

    def _category(self, cid, business_id, name, now):
        self.session.execute(
            text("INSERT INTO accounting_categories "
                 "(id, business_id, name, type, color, icon, is_default,"
                 " created_at) "
                 "VALUES (:i, :b, :n, 'expense', '#000000', 'tag', 0, :c)"),
            {"i": cid, "b": business_id, "n": name, "c": now},
        )

    def _transaction(self, tid, business_id, category_id, description,
                     payee, reference, note, now):
        self.session.execute(
            text("INSERT INTO accounting_transactions "
                 "(id, business_id, category_id, transaction_date, description,"
                 " amount, type, reference, payee_payer, account, notes,"
                 " is_reconciled, is_archived, created_at) "
                 "VALUES (:i, :b, :c, :d, :desc, -100.0, 'expense', :ref, :pay,"
                 " 'current', :note, 0, 0, :now)"),
            {"i": tid, "b": business_id, "c": category_id,
             "d": date(2026, 9, 1), "desc": description, "ref": reference,
             "pay": payee, "note": note, "now": now},
        )

    def close(self):
        self.session.close()


def assert_no_b_data(payload, what):
    """Fail if anything belonging to business B appears in this response."""
    blob = repr(payload)
    for secret in B_SECRETS:
        assert secret not in blob, (
            f"TENANT ISOLATION FAILURE in {what}: business B's {secret!r} "
            f"reached a caller authenticated as business A.\n"
            f"Response was: {blob[:600]}"
        )
    assert BUSINESS_B not in blob, (
        f"TENANT ISOLATION FAILURE in {what}: business B's id leaked."
    )


class TenantIsolationCase(unittest.TestCase):
    """Base class: two tenants, a real database, A is the caller."""

    def setUp(self):
        self.db = TwoTenantDatabase()
        self.session = self.db.session
        self.caller_a = as_business(BUSINESS_A)

    def tearDown(self):
        self.db.close()


class TestAccountingReadsAreScopedToTheCaller(TenantIsolationCase):

    def test_transaction_list_returns_only_the_callers_rows(self):
        result = list_transactions_as(self.session, self.caller_a)
        assert_no_b_data(result, "GET /accounting/transactions")

    def test_transaction_list_still_returns_the_callers_own_rows(self):
        """The guard that stops 'return nothing' passing as isolation."""
        result = list_transactions_as(self.session, self.caller_a)
        assert "A's own transaction" in repr(result), (
            "business A cannot see its own data — over-scoped, not isolated"
        )

    def test_a_foreign_category_reads_as_uncategorised_not_as_bs_name(self):
        """BH-002's exact defect, now guarded generically."""
        result = list_transactions_as(self.session, self.caller_a)
        blob = repr(result)
        assert "A's row with a foreign category" in blob, "fixture row missing"
        assert "B-PRIVATE-CATEGORY" not in blob, (
            "a transaction referencing another tenant's category displayed "
            "that tenant's category name"
        )

    def test_filtering_by_another_tenants_category_returns_nothing(self):
        """A filter is caller-supplied input, so it is an attack surface."""
        result = list_transactions_as(
            self.session, self.caller_a, category_id=self.db.b_category)
        assert_no_b_data(result, "GET /accounting/transactions?category_id=<B's>")

    def test_category_list_returns_only_the_callers_categories(self):
        result = list_categories_as(self.session, self.caller_a)
        assert_no_b_data(result, "GET /accounting/categories")


class TestTheHarnessItselfCanDetectALeak(TenantIsolationCase):
    """A test suite that cannot fail is not evidence.

    BH-002 taught this: the first completeness test scanned one file and
    reported the fix complete. These prove the harness reacts to a real leak,
    so a green run means something.
    """

    def test_an_unscoped_query_is_caught(self):
        leaky = self.session.execute(text(
            "SELECT t.description, c.name FROM accounting_transactions t "
            "LEFT JOIN accounting_categories c ON t.category_id = c.id "
            "WHERE t.business_id = :b"
        ), {"b": BUSINESS_A}).fetchall()
        with self.assertRaises(AssertionError):
            assert_no_b_data(leaky, "deliberately unscoped query")

    def test_a_query_with_no_tenant_filter_at_all_is_caught(self):
        everything = self.session.execute(
            text("SELECT * FROM accounting_transactions")).fetchall()
        with self.assertRaises(AssertionError):
            assert_no_b_data(everything, "deliberately unfiltered query")


# ─────────────────────────────────────────────────────────────────────────────
# UNCOVERED — the registry. Part of the deliverable, not an apology.
# ─────────────────────────────────────────────────────────────────────────────

UNCOVERED = {
    "the RLS / anon-key path (the other half of P0-9)": (
        "Needs a real Postgres carrying the live policies — `supabase start`, "
        "which needs Docker. DOCKER IS NOT INSTALLED on this machine, so this "
        "is BLOCKED, not done. Until it runs, no statement about frontend "
        "tenant isolation is evidence-backed. This is the larger half of the "
        "risk: on that path RLS is the only gate."
    ),
    "the transaction search filter": (
        "`search` emits ILIKE, which SQLite rejects, so the search path is "
        "not exercised here. It interpolates caller-supplied text into a "
        "query that is already tenant-scoped, but it is untested by this "
        "harness and should be covered once a Postgres fixture exists."
    ),
    "endpoints whose SQL is Postgres-only": (
        "Bulk operations use ANY(CAST(:ids AS uuid[])) and the ownership check "
        "uses CAST(:id AS uuid); SQLite mangles both. Their tenant scoping is "
        "covered by test_accounting_tenant_isolation.py against fakes, which "
        "proves the validator is called, not what Postgres does with it."
    ),
    "every non-accounting resource": (
        "Quotes, invoices, emails, calls, tasks, bookings, receptionist "
        "configs, board meetings. The harness generalises — add a fixture "
        "table and a reader — but they are NOT covered yet. Accounting was "
        "first because BH-002 proved a live defect there."
    ),
    "the admin surface": (
        "Admin and customer share the `authenticated` Postgres role, so an "
        "admin-only column grant is a customer-reachable grant. Needs the "
        "BH-001 evidence packet before it can even be stated correctly."
    ),
    "write-path isolation beyond accounting categories": (
        "BH-002 covered the three category write paths. No systematic test "
        "asserts that a write naming another tenant's id is refused elsewhere."
    ),
}


class TestTheRegistryIsHonest(unittest.TestCase):

    def test_every_uncovered_entry_explains_itself(self):
        for area, reason in UNCOVERED.items():
            self.assertGreater(
                len(reason), 80,
                f"UNCOVERED['{area}'] must say why, not just that")

    def test_the_rls_path_is_still_recorded_as_blocked(self):
        """If someone installs Docker and wires it up, this should be deleted
        in the same commit — and it failing is the reminder."""
        key = "the RLS / anon-key path (the other half of P0-9)"
        self.assertIn(key, UNCOVERED)
        self.assertIn("BLOCKED", UNCOVERED[key])


if __name__ == "__main__":
    unittest.main()
