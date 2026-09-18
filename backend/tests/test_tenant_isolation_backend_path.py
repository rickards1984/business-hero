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

### Not covered here: the RLS path

The anon-key half of P0-9 is `test_tenant_isolation_rls_path.py`, which runs
against a local Supabase Postgres (`scripts/rls-local.sh`) and is not part of
`./check.sh`. Its limits are its own; the one that matters is in `UNCOVERED`.

All data is synthetic. Nothing touches a live or staging database.
"""

import asyncio
import os
import sqlite3
import unittest
import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

# Checked BEFORE importing the application, and deliberately so. `import
# accounting` pulls in `db`, which CONNECTS AND RUNS `SELECT 1` at import time
# when a Postgres URL is configured. A tenant-isolation test that silently
# opens a production connection on import would be an appalling way to find
# that out, so refuse loudly first. Codex found this; the fix has to run
# before the import, which is why it sits above it.
_configured = os.getenv("SUPABASE_DATABASE_URL") or os.getenv("DATABASE_URL") or ""
if _configured and not _configured.startswith("sqlite"):
    raise RuntimeError(
        "REFUSING TO RUN: a non-SQLite database is configured "
        f"({_configured.split('@')[-1][:40]!r}). Importing the app would open "
        "a connection to it. Clear DATABASE_URL/SUPABASE_DATABASE_URL — these "
        "tests need no database but the synthetic one they build."
    )

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
    return _one_request(session, accounting.list_transactions(
        user_business=caller, session=session, **params))


def list_categories_as(session, caller, type=None):
    return _one_request(session, accounting.list_categories(
        type=type, user_business=caller, session=session))


def _one_request(session, coroutine):
    """Run one endpoint call the way one HTTP request would.

    Both readers do `with session.connection() as conn:`, which closes the
    session's connection on exit. In the app every request gets its own
    session, so that is harmless. Here a test that calls the endpoint twice
    — a page walk, a filter comparison — reuses one session, and the second
    call finds the connection closed. `session.close()` afterwards ends the
    stale transaction so the next call begins a fresh one. The in-memory
    database lives in the pooled DBAPI connection and survives it.
    """
    try:
        return asyncio.run(coroutine)
    finally:
        session.close()


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
        # Created one minute EARLIER than A's own row so the endpoint's
        # `ORDER BY transaction_date DESC, created_at DESC` is deterministic:
        # the exact-response test below asserts order, and two rows with
        # identical sort keys would make that assertion flap.
        self.a_contaminated = str(uuid.uuid4())
        self._transaction(self.a_contaminated, BUSINESS_A, self.b_category,
                          "A's row with a foreign category", "A-PAYEE-2",
                          "A-REF-2", "A-NOTE-2", now - timedelta(minutes=1))
        self.now = now

    def add_paging_rows(self, per_tenant):
        """Seed `per_tenant` more rows for EACH tenant, interleaved by date.

        The dates alternate A, B, A, B … so that on any date-ordered page the
        neighbouring row belongs to the other tenant. A tenant predicate that
        is dropped, or applied only to the first page, puts B's rows exactly
        where a page boundary falls. Returns A's new ids in the order the
        endpoint must return them (newest first).
        """
        a_ids = []
        for n in range(per_tenant):
            day = date(2026, 8, 30) - timedelta(days=n)
            stamp = datetime.combine(day, datetime.min.time())
            a_id = str(uuid.uuid4())
            self._transaction(a_id, BUSINESS_A, self.a_category,
                              f"A page row {n}", "A-PAYEE", f"A-REF-P{n}",
                              "A-NOTE", stamp, transaction_date=day)
            a_ids.append(a_id)
            self._transaction(str(uuid.uuid4()), BUSINESS_B, self.b_category,
                              "B-PRIVATE-TRANSACTION", "B-PRIVATE-PAYEE",
                              "B-PRIVATE-REFERENCE", "B-PRIVATE-NOTE", stamp,
                              transaction_date=day)
        self.session.commit()
        return a_ids

    def _category(self, cid, business_id, name, now):
        self.session.execute(
            text("INSERT INTO accounting_categories "
                 "(id, business_id, name, type, color, icon, is_default,"
                 " created_at) "
                 "VALUES (:i, :b, :n, 'expense', '#000000', 'tag', 0, :c)"),
            {"i": cid, "b": business_id, "n": name, "c": now},
        )

    def _transaction(self, tid, business_id, category_id, description,
                     payee, reference, note, now, transaction_date=None):
        self.session.execute(
            text("INSERT INTO accounting_transactions "
                 "(id, business_id, category_id, transaction_date, description,"
                 " amount, type, reference, payee_payer, account, notes,"
                 " is_reconciled, is_archived, created_at) "
                 "VALUES (:i, :b, :c, :d, :desc, -100.0, 'expense', :ref, :pay,"
                 " 'current', :note, 0, 0, :now)"),
            {"i": tid, "b": business_id, "c": category_id,
             "d": transaction_date or date(2026, 9, 1),
             "desc": description, "ref": reference,
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

    def _ids(self, result):
        return {row["id"] for row in result["transactions"]}

    def test_transaction_list_returns_only_the_callers_rows(self):
        result = list_transactions_as(self.session, self.caller_a)
        assert_no_b_data(result, "GET /accounting/transactions")

    def test_transaction_list_returns_exactly_the_callers_ids(self):
        """Marker-absence is not enough — assert the EXACT id set.

        Codex mutated the endpoint to append business B's transaction id to
        the response and this file stayed green, because the id carries none
        of B's marker strings. An id is quite sufficient to enumerate another
        tenant's records.
        """
        result = list_transactions_as(self.session, self.caller_a)
        self.assertEqual(
            self._ids(result),
            {self.db.a_transaction, self.db.a_contaminated},
            "the response did not contain exactly business A's transactions",
        )

    def test_the_total_counts_only_the_callers_rows(self):
        """Codex mutated the count to span every tenant and this file stayed
        green. A total is an aggregate disclosure: it tells A how much data B
        holds."""
        result = list_transactions_as(self.session, self.caller_a)
        self.assertEqual(result["total"], 2,
                         "the total counted rows belonging to another tenant")

    def test_transaction_list_still_returns_the_callers_own_rows(self):
        """The guard that stops 'return nothing' passing as isolation."""
        result = list_transactions_as(self.session, self.caller_a)
        assert "A's own transaction" in repr(result), (
            "business A cannot see its own data — over-scoped, not isolated"
        )

    def test_a_foreign_category_reads_as_uncategorised_not_as_bs_name(self):
        """BH-002's exact defect, now guarded generically."""
        result = list_transactions_as(self.session, self.caller_a)
        rows = {row["id"]: row for row in result["transactions"]}

        contaminated = rows[self.db.a_contaminated]
        self.assertIsNone(contaminated.get("category"),
                          "the foreign category was rendered, not suppressed")

        # And A's OWN category must still come through: asserting only that
        # B's name is absent is satisfied by returning no categories at all,
        # which Codex demonstrated by mutation.
        own = rows[self.db.a_transaction]
        self.assertIsNotNone(own.get("category"),
                             "business A cannot see its own category")
        self.assertEqual(own["category"]["name"], "A Office Costs",
                         "business A cannot see its own category — over-scoped")

    def test_filtering_by_another_tenants_category_yields_only_as_own_row(self):
        """A filter is caller-supplied input, so it is an attack surface.

        The honest contract, stated rather than implied: A's transaction that
        *references* B's category still matches the filter, because the filter
        is on the transaction's stored category_id and that row belongs to A.
        What must never happen is B's own transaction appearing, or B's
        category name being rendered. The earlier name promised "returns
        nothing", which is not what happens and not what should.
        """
        result = list_transactions_as(
            self.session, self.caller_a, category_id=self.db.b_category)
        assert_no_b_data(result, "GET /accounting/transactions?category_id=<B's>")
        self.assertEqual(self._ids(result), {self.db.a_contaminated})
        self.assertEqual(result["total"], 1)
        self.assertIsNone(result["transactions"][0].get("category"))

    def test_category_list_returns_only_the_callers_categories(self):
        result = list_categories_as(self.session, self.caller_a)
        assert_no_b_data(result, "GET /accounting/categories")
        self.assertEqual([c["name"] for c in result["categories"]],
                         ["A Office Costs"],
                         "the category list is not exactly business A's")
        self.assertEqual(result["count"], 1)

    def test_the_transaction_response_is_exactly_as_expected(self):
        """Codex's "single most valuable next addition": the WHOLE response,
        built from the fixture, compared with assertEqual.

        Every value below is written out from what was seeded, not read back
        from the endpoint. Closes, by construction, the mutations the second
        review confirmed survived: a nested category id swapped for B's, B's
        transaction id smuggled in as response metadata, a duplicated row,
        reversed ordering, and `total_pages` set to 999.
        """
        result = list_transactions_as(self.session, self.caller_a)
        stamp = self.db.now
        self.assertEqual(result, {
            "transactions": [
                {
                    "id": self.db.a_transaction,
                    "transaction_date": "2026-09-01",
                    "description": "A's own transaction",
                    "amount": -100.0,
                    "type": "expense",
                    "reference": "A-REF",
                    "payee_payer": "A-PAYEE",
                    "account": "current",
                    "notes": "A-NOTE",
                    "is_reconciled": False,
                    "created_at": stamp.isoformat(),
                    "category": {
                        "id": self.db.a_category,
                        "name": "A Office Costs",
                        "color": "#000000",
                    },
                },
                {
                    "id": self.db.a_contaminated,
                    "transaction_date": "2026-09-01",
                    "description": "A's row with a foreign category",
                    "amount": -100.0,
                    "type": "expense",
                    "reference": "A-REF-2",
                    "payee_payer": "A-PAYEE-2",
                    "account": "current",
                    "notes": "A-NOTE-2",
                    "is_reconciled": False,
                    "created_at": (stamp - timedelta(minutes=1)).isoformat(),
                    "category": None,
                },
            ],
            "total": 2,
            "page": 1,
            "per_page": 50,
            "total_pages": 1,
            "limit": 50,
            "offset": 0,
        })

    def test_the_category_response_is_exactly_as_expected(self):
        """Same discipline for the category reader, whose id was the one the
        second review showed could be swapped for B's without detection."""
        result = list_categories_as(self.session, self.caller_a)
        self.assertEqual(result, {
            "categories": [{
                "id": self.db.a_category,
                "name": "A Office Costs",
                "type": "expense",
                "color": "#000000",
                "icon": "tag",
                "is_default": False,
                "created_at": self.db.now.isoformat(),
            }],
            "count": 1,
        })

    def test_date_range_and_reconciliation_filters_stay_scoped(self):
        """Filters are caller input. Each must narrow A's rows, never widen
        into B's — and B has rows on the SAME dates, so a filter that
        forgot the tenant predicate would admit them."""
        self.db.add_paging_rows(3)   # A and B rows on 30, 29, 28 Aug

        in_range = list_transactions_as(
            self.session, self.caller_a,
            start_date=date(2026, 8, 29), end_date=date(2026, 8, 30))
        assert_no_b_data(in_range, "date-range filter")
        self.assertEqual(in_range["total"], 2)
        self.assertEqual(
            [t["description"] for t in in_range["transactions"]],
            ["A page row 0", "A page row 1"])

        unreconciled = list_transactions_as(
            self.session, self.caller_a, is_reconciled=False)
        assert_no_b_data(unreconciled, "is_reconciled filter")
        self.assertEqual(unreconciled["total"], 5)

        reconciled = list_transactions_as(
            self.session, self.caller_a, is_reconciled=True)
        self.assertEqual(reconciled, {
            "transactions": [], "total": 0, "page": 1, "per_page": 50,
            "total_pages": 1, "limit": 50, "offset": 0,
        })


class TestEveryPageIsScoped(TenantIsolationCase):
    """The mutation I said I would worry about: the tenant restriction
    removed only beyond page one. Every earlier assertion read page one."""

    def setUp(self):
        super().setUp()
        self.newer = self.db.add_paging_rows(5)
        # Newest first: the two 1 Sep rows, then the five paging rows.
        self.expected_order = [self.db.a_transaction, self.db.a_contaminated,
                               *self.newer]

    def test_walking_every_page_yields_exactly_as_rows_once_each(self):
        limit = 2
        first = list_transactions_as(self.session, self.caller_a,
                                     limit=limit, page=1)
        self.assertEqual(first["total"], len(self.expected_order))
        self.assertEqual(first["total_pages"], 4)

        seen = []
        for page in range(1, first["total_pages"] + 1):
            result = list_transactions_as(self.session, self.caller_a,
                                          limit=limit, page=page)
            assert_no_b_data(result, f"page {page}")
            self.assertEqual(result["page"], page)
            self.assertEqual(result["offset"], (page - 1) * limit)
            self.assertEqual(result["total"], len(self.expected_order),
                             f"the total changed on page {page}")
            seen.extend(t["id"] for t in result["transactions"])

        self.assertEqual(seen, self.expected_order,
                         "the pages, concatenated, are not exactly A's rows "
                         "in the endpoint's declared order")

        beyond = list_transactions_as(self.session, self.caller_a,
                                      limit=limit, page=first["total_pages"] + 1)
        self.assertEqual(beyond["transactions"], [],
                         "a page past the end returned rows")

    def test_an_explicit_offset_is_honoured_and_scoped(self):
        """The legacy `offset` parameter takes a different code path from
        `page`; the second review showed ignoring it survived."""
        result = list_transactions_as(self.session, self.caller_a,
                                      limit=3, offset=3)
        assert_no_b_data(result, "offset=3")
        self.assertEqual([t["id"] for t in result["transactions"]],
                         self.expected_order[3:6])
        self.assertEqual(result["offset"], 3)

    def test_the_reverse_direction_holds_too(self):
        """B calling must see only B. Isolation is not a property of A."""
        caller_b = as_business(BUSINESS_B)
        b_ids = {row[0] for row in self.session.execute(text(
            "SELECT id FROM accounting_transactions WHERE business_id = :b"),
            {"b": BUSINESS_B}).fetchall()}
        self.assertEqual(len(b_ids), 6)

        seen = set()
        for page in (1, 2, 3):
            result = list_transactions_as(self.session, caller_b,
                                          limit=2, page=page)
            blob = repr(result)
            for a_marker in ("A's own transaction", "A page row", "A-PAYEE",
                             "A Office Costs", BUSINESS_A):
                self.assertNotIn(a_marker, blob,
                                 f"business A's {a_marker!r} reached B")
            seen.update(t["id"] for t in result["transactions"])
        self.assertEqual(seen, b_ids)


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
    "the RLS / anon-key path — PRODUCTION equivalence": (
        "The other half of P0-9 now exists: test_tenant_isolation_rls_path.py "
        "runs against a local Supabase Postgres built by scripts/rls-local.sh "
        "from this repository's migrations, pruned to the 5 July 2026 "
        "production policy export. It is NOT part of ./check.sh (needs "
        "Docker) and a skip there is a skip. What it proves is that the "
        "policies AS THE MIGRATIONS DESCRIBE THEM isolate two tenants on the "
        "exercised tables; what it cannot prove is that production carries "
        "those policies — AGENTS.md §3.4. It also ASSUMES 029 was applied to "
        "production, which the repository does not record. BH-001's census "
        "compared with `scripts/rls-local.sh census` closes both gaps."
    ),
    "Postgres behaviour generally": (
        "These tests run on SQLite. UUID typing and casts, arrays, ILIKE, "
        "numeric precision, timezone handling, constraints, defaults, "
        "policies and database roles all differ or are absent. The seeded "
        "schema uses TEXT ids, omits foreign keys, and relaxes required "
        "fields. Removing either tenant predicate IS caught here, which is "
        "real evidence; Postgres equivalence is not established."
    ),
    "endpoints whose SQL is Postgres-only": (
        "Bulk operations use ANY(CAST(:ids AS uuid[])) and the ownership "
        "check uses CAST(:id AS uuid); SQLite mangles both. BH-002's tests "
        "cover CATEGORY-OWNERSHIP VALIDATION on those paths against fakes — "
        "narrower than it first sounds: they do not establish that a bulk "
        "operation validates the TRANSACTION ids it is given, and there is "
        "no bulk-delete isolation test anywhere."
    ),
    "the remaining accounting reads": (
        "Import history (`backend/accounting.py:1100`), the summary totals, "
        "the category aggregates, the AI-insight reads, the assistant tool "
        "reads and the dashboard reads are NOT executed here. Two readers are "
        "covered out of a larger set; the harness is a start on accounting, "
        "not a completion of it."
    ),
    "the transaction search filter": (
        "`search` emits ILIKE, which SQLite rejects, so the search path is "
        "not exercised. It passes the term as a BOUND parameter, so this is a "
        "coverage gap rather than an injection concern — an earlier draft of "
        "this note said 'interpolates', which was wrong and alarmist."
    ),
    "partial-field provenance": (
        "The second review's surviving mutations — category id swapped for "
        "B's (list and nested), B's transaction id as response metadata, a "
        "duplicated row, reversed ordering, total_pages=999, offset ignored, "
        "and the tenant restriction removed only beyond page one — are now "
        "targeted by exact full-response assertions and a page walk. They "
        "are CLAIMED closed by construction, and Codex's third review is the "
        "confirmation, not this sentence. What remains: both tenants still "
        "share amounts, account names and colours in the fixture, so a row "
        "carrying only those fields has no provenance and a mutation that "
        "copied B's `amount` onto A's row would pass."
    ),
    "HTTP, authentication and serialisation": (
        "The caller tuple is injected directly, so FastAPI parsing, "
        "validation, dependency resolution and real business selection are "
        "bypassed. Error responses and existence-disclosure via status codes "
        "are untested."
    ),
    "every non-accounting resource": (
        "Quotes, invoices, emails, calls, tasks, bookings, receptionist "
        "configs, board meetings. The two-tenant pattern is reusable, but "
        "'add a table and a reader' understates it: each resource needs its "
        "own seeding, its own markers and its own exact-value expectations."
    ),
    "the admin surface": (
        "Admin and customer share the `authenticated` Postgres role, so an "
        "admin-only column grant is a customer-reachable grant. Needs the "
        "BH-001 evidence packet before it can even be stated correctly."
    ),
}


class TestTheRegistryIsHonest(unittest.TestCase):

    def test_every_uncovered_entry_explains_itself(self):
        for area, reason in UNCOVERED.items():
            self.assertGreater(
                len(reason), 80,
                f"UNCOVERED['{area}'] must say why, not just that")

    def test_the_rls_paths_production_gap_is_still_recorded(self):
        """A bookmark, not a detector. The RLS suite exists now; what stays
        open is production equivalence, and this asserts that entry has not
        been quietly deleted before BH-001 closes it."""
        key = "the RLS / anon-key path — PRODUCTION equivalence"
        self.assertIn(key, UNCOVERED)
        self.assertIn("AGENTS.md §3.4", UNCOVERED[key])


if __name__ == "__main__":
    unittest.main()
