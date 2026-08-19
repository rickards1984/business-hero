"""
ITEM 1 — invoice numbering.

Target surface (does not exist yet):

    backend/services/invoice_numbering.py

        next_invoice_number(session, business_id) -> str
            Allocates the next number via ONE atomic statement:
                UPDATE <settings> SET next_invoice_number = next_invoice_number + 1
                 WHERE business_id = :bid
             RETURNING next_invoice_number - 1 AS next_invoice_number, invoice_prefix
            Never COUNT(*).

        allocate(session, business_id, insert_fn, max_retries=5) -> str
            Allocates a number, calls insert_fn(number), and on IntegrityError
            retries with the NEXT number rather than surfacing a 500.

        seed_value_for_business(session, business_id) -> int
            The migration seed. Counts app-generated rows only (source='quote').

        detect_prefix_collision(session, business_id, provider_numbers) -> dict | None
            Warns. Never changes anything.

COUNTER CONTRACT: the stored column holds the NEXT number to issue, exactly
like the working `quote_settings.next_quote_number`. So a business seeded at 2
issues INV-0002 next. MSC holds INV-0001 (source='quote') and therefore seeds
to 2; every other business seeds to 1.

ON THE CONCURRENCY FAKE: `ConcurrentCounterSession` models exactly ONE
Postgres guarantee and no more —

    a single UPDATE ... RETURNING statement is atomic;
    a SELECT followed by a separate UPDATE is not.

Atomic single-statement increments are served under a lock, indivisibly.
Any read served to the caller sleeps before returning, which holds the race
window open for the duration a real one lasts. So a read-then-write
implementation — including today's COUNT(*) + 1 — reliably issues duplicates
here, and an atomic one reliably does not. The fake does not decide whether
the implementation is correct; it reproduces the conditions under which
incorrectness shows up.
"""
import re
import threading
import time
import unittest

from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.elements import TextClause


# A self-referential increment: `next_invoice_number = next_invoice_number + 1`,
# optionally table-qualified. This is the only form Postgres executes atomically.
ATOMIC_INCREMENT = re.compile(
    r"next_invoice_number\s*=\s*(?:[\w\"]+\.)?next_invoice_number\s*\+\s*1",
    re.IGNORECASE,
)


def numbering():
    """Imported per-test so each test fails on its own, not at collection."""
    from services import invoice_numbering as _numbering
    return _numbering


def duplicate_key_error(number):
    """The exception Postgres raises through SQLAlchemy on a unique violation."""
    return IntegrityError(
        "INSERT INTO invoices ...",
        {},
        Exception(
            'duplicate key value violates unique constraint '
            f'"uq_invoices_business_number" DETAIL: Key (invoice_number)=({number}) '
            "already exists."
        ),
    )


class FakeRow:
    def __init__(self, columns, values):
        self._values = list(values)
        for name, value in zip(columns, values):
            setattr(self, name, value)

    def __getitem__(self, index):
        return self._values[index]


class FakeResult:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row

    def first(self):
        return self._row

    def scalar(self):
        return self._row[0] if self._row is not None else None


class ConcurrentCounterSession:
    """See the module docstring for what this does and does not model."""

    def __init__(self, start=1, prefix="INV-", settings_exists=True, read_gap=0.003):
        self._lock = threading.Lock()
        self.counter = start
        self.prefix = prefix
        self.settings_exists = settings_exists
        self.read_gap = read_gap
        self.statements = []
        self.used_count_star = False
        self.atomic_increments = 0
        self.committed = 0

    def _record(self, sql, params):
        with self._lock:
            self.statements.append((sql, params))

    def execute(self, statement, params=None):
        assert isinstance(statement, TextClause), (
            f"expected a TextClause, got {type(statement)}"
        )
        sql = " ".join(statement.text.split())
        self._record(sql, params)
        upper = sql.upper()

        # The backend bypasses RLS. This WHERE clause is the entire tenant
        # boundary — a counter statement without it reads another business's
        # sequence.
        assert "BUSINESS_ID" in upper, f"counter statement is not tenant-scoped: {sql}"

        if "COUNT(" in upper:
            self.used_count_star = True
            with self._lock:
                issued_so_far = self.counter - 1
            time.sleep(self.read_gap)          # the window a real race lives in
            return FakeResult(FakeRow(["count"], [issued_so_far]))

        if upper.startswith("UPDATE") and ATOMIC_INCREMENT.search(sql):
            assert "RETURNING" in upper, (
                "an atomic increment must RETURN the number it allocated, "
                "otherwise the caller has to read it back in a second "
                f"statement and the atomicity is lost: {sql}"
            )
            with self._lock:
                if not self.settings_exists:
                    return FakeResult(None)     # UPDATE matched zero rows
                issued = self.counter
                self.counter += 1
                self.atomic_increments += 1
            return FakeResult(
                FakeRow(["next_invoice_number", "invoice_prefix"], [issued, self.prefix])
            )

        if upper.startswith("SELECT"):
            with self._lock:
                value, prefix, exists = self.counter, self.prefix, self.settings_exists
            time.sleep(self.read_gap)
            if not exists:
                return FakeResult(None)
            return FakeResult(
                FakeRow(["next_invoice_number", "invoice_prefix"], [value, prefix])
            )

        if upper.startswith("INSERT"):
            with self._lock:
                self.settings_exists = True
                if params and params.get("next_invoice_number") is not None:
                    self.counter = params["next_invoice_number"]
            return FakeResult(None)

        if upper.startswith("UPDATE"):
            # An absolute set — `SET next_invoice_number = :next`. Whatever
            # produced :next was a separate statement.
            with self._lock:
                for key in ("next", "next_invoice_number", "next_number"):
                    if params and params.get(key) is not None:
                        self.counter = params[key]
                        break
                else:
                    self.counter += 1
            return FakeResult(None)

        raise AssertionError(f"unmodelled statement: {sql}")

    def commit(self):
        self.committed += 1

    def rollback(self):
        pass


class TestAtomicAllocation(unittest.TestCase):
    """Criterion: atomic counter per business. Never COUNT(*)."""

    def test_uses_a_self_referential_increment_with_returning(self):
        session = ConcurrentCounterSession()
        numbering().next_invoice_number(session, "biz-1")
        self.assertGreaterEqual(
            session.atomic_increments, 1,
            "no atomic `next_invoice_number = next_invoice_number + 1 ... "
            "RETURNING` statement was issued",
        )

    def test_never_uses_count_star(self):
        session = ConcurrentCounterSession()
        numbering().next_invoice_number(session, "biz-1")
        self.assertFalse(
            session.used_count_star,
            "numbering used COUNT(*) — the pattern this item exists to remove",
        )

    def test_first_number_uses_the_seeded_value(self):
        session = ConcurrentCounterSession(start=1)
        self.assertEqual(numbering().next_invoice_number(session, "biz-1"), "INV-0001")

    def test_msc_seeded_at_two_issues_invoice_two(self):
        # MSC already holds INV-0001 (source='quote'), so its counter seeds to 2.
        session = ConcurrentCounterSession(start=2)
        self.assertEqual(numbering().next_invoice_number(session, "biz-1"), "INV-0002")


class TestConcurrency(unittest.TestCase):
    """
    Criterion: "Two invoices created simultaneously get different numbers —
    proven by a concurrency test."

    Real threads, released together by a barrier so they contend on the counter
    at the same instant rather than in sequence.
    """

    THREADS = 8

    def _run_concurrently(self, session):
        barrier = threading.Barrier(self.THREADS)
        issued, errors = [], []
        inserted = set()
        insert_lock = threading.Lock()

        def insert_fn(number):
            # Models the partial unique index on app-generated rows.
            with insert_lock:
                if number in inserted:
                    raise duplicate_key_error(number)
                inserted.add(number)

        def worker():
            barrier.wait()                      # everyone starts at once
            try:
                issued.append(numbering().allocate(session, "biz-1", insert_fn))
            except Exception as exc:            # noqa: BLE001 — recorded, then asserted
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(self.THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        self.assertFalse(any(t.is_alive() for t in threads), "a worker deadlocked")
        return issued, errors

    def test_simultaneous_allocation_never_issues_a_duplicate(self):
        session = ConcurrentCounterSession(start=1)
        issued, errors = self._run_concurrently(session)
        self.assertEqual(errors, [], f"allocation raised under contention: {errors}")
        self.assertEqual(len(issued), self.THREADS)
        self.assertEqual(
            len(set(issued)), self.THREADS,
            f"duplicate invoice numbers issued concurrently: "
            f"{sorted(n for n in issued if issued.count(n) > 1)}",
        )

    def test_simultaneous_allocation_leaves_no_gaps(self):
        session = ConcurrentCounterSession(start=1)
        issued, _ = self._run_concurrently(session)
        self.assertEqual(
            sorted(issued),
            [f"INV-{n:04d}" for n in range(1, self.THREADS + 1)],
            "HMRC and IRS both require sequential numbering — a gap is a "
            "compliance question the business has to answer",
        )

    def test_concurrent_allocation_does_not_fall_back_to_count(self):
        session = ConcurrentCounterSession(start=1)
        issued, errors = self._run_concurrently(session)
        # Prove the run happened before concluding anything from what it did
        # NOT do — otherwise workers dying on an import leave used_count_star
        # False and this passes having exercised nothing.
        self.assertEqual(errors, [])
        self.assertEqual(len(issued), self.THREADS)
        self.assertFalse(session.used_count_star)


class TestCollisionRetry(unittest.TestCase):
    """Criterion: insert retries with the next number on a collision, not a 500."""

    def test_retries_with_the_next_number(self):
        session = ConcurrentCounterSession(start=1)
        attempts = []

        def insert_fn(number):
            attempts.append(number)
            if len(attempts) == 1:
                raise duplicate_key_error(number)

        result = numbering().allocate(session, "biz-1", insert_fn)
        self.assertEqual(attempts, ["INV-0001", "INV-0002"])
        self.assertEqual(result, "INV-0002")

    def test_retries_more_than_once_if_it_has_to(self):
        session = ConcurrentCounterSession(start=1)
        attempts = []

        def insert_fn(number):
            attempts.append(number)
            if len(attempts) < 3:
                raise duplicate_key_error(number)

        result = numbering().allocate(session, "biz-1", insert_fn)
        self.assertEqual(result, "INV-0003")
        self.assertEqual(len(attempts), 3)

    def test_gives_up_after_max_retries_rather_than_looping_forever(self):
        session = ConcurrentCounterSession(start=1)
        attempts = []

        def insert_fn(number):
            attempts.append(number)
            raise duplicate_key_error(number)

        with self.assertRaises(IntegrityError):
            numbering().allocate(session, "biz-1", insert_fn, max_retries=3)
        self.assertGreaterEqual(len(attempts), 2, "it did not retry at all")
        self.assertLessEqual(
            len(attempts), 4,
            "allocate kept retrying past max_retries — an unbounded retry on a "
            "money path is a worse outage than a clean error",
        )

    def test_a_non_integrity_error_is_not_retried(self):
        # A NULL customer_name is not a numbering problem. Retrying it just
        # burns invoice numbers and leaves permanent gaps in the sequence.
        session = ConcurrentCounterSession(start=1)
        attempts = []

        def insert_fn(number):
            attempts.append(number)
            raise ValueError("customer_name must not be null")

        with self.assertRaises(ValueError):
            numbering().allocate(session, "biz-1", insert_fn)
        self.assertEqual(len(attempts), 1)


class TestNoReuse(unittest.TestCase):
    """
    Criterion: deleting or archiving an invoice does not cause reuse.

    NOTE FOR REVIEW: the spec's worked example reads "Create three, delete the
    middle one, create a fourth. Expect INV-0001, INV-0002, INV-0004." Deleting
    the middle of 0001/0002/0003 leaves 0001, 0003, 0004 — so the listed
    expectation looks like a slip. What these tests encode is the invariant
    underneath it, which is unambiguous: the fourth number is INV-0004, and no
    number is ever reissued.
    """

    def _allocate(self, session, live):
        def insert_fn(number):
            if number in live:
                raise duplicate_key_error(number)
            live.add(number)
        return numbering().allocate(session, "biz-1", insert_fn)

    def test_deleting_the_middle_invoice_does_not_reuse_its_number(self):
        session = ConcurrentCounterSession(start=1)
        live = set()
        first = self._allocate(session, live)
        second = self._allocate(session, live)
        third = self._allocate(session, live)
        self.assertEqual([first, second, third], ["INV-0001", "INV-0002", "INV-0003"])

        live.discard(second)                     # the delete
        fourth = self._allocate(session, live)

        self.assertEqual(fourth, "INV-0004")
        self.assertNotIn(fourth, {first, second, third})

    def test_archiving_does_not_reuse_a_number(self):
        session = ConcurrentCounterSession(start=1)
        live = set()
        first = self._allocate(session, live)
        self._allocate(session, live)
        # Archive is a flag, not a delete — the row and its number both remain.
        third = self._allocate(session, live)
        self.assertEqual(third, "INV-0003")
        self.assertNotEqual(third, first)

    def test_deleting_every_invoice_does_not_restart_the_sequence(self):
        session = ConcurrentCounterSession(start=1)
        live = set()
        for _ in range(3):
            self._allocate(session, live)
        live.clear()                             # every invoice deleted
        self.assertEqual(self._allocate(session, live), "INV-0004")


class TestPrefixAndPadding(unittest.TestCase):
    """Criteria: per-business prefix defaulting to INV-; padding survives >9999."""

    def test_default_prefix_is_inv(self):
        session = ConcurrentCounterSession(start=1, prefix="INV-")
        self.assertTrue(
            numbering().next_invoice_number(session, "biz-1").startswith("INV-")
        )

    def test_prefix_is_per_business_and_configurable(self):
        session = ConcurrentCounterSession(start=1, prefix="MSC-")
        self.assertEqual(numbering().next_invoice_number(session, "biz-1"), "MSC-0001")

    def test_padding_is_four_digits_below_ten_thousand(self):
        session = ConcurrentCounterSession(start=42)
        self.assertEqual(numbering().next_invoice_number(session, "biz-1"), "INV-0042")

    def test_number_above_9999_widens_rather_than_truncating(self):
        session = ConcurrentCounterSession(start=10000)
        self.assertEqual(numbering().next_invoice_number(session, "biz-1"), "INV-10000")

    def test_the_9999_to_10000_boundary_stays_ordered(self):
        session = ConcurrentCounterSession(start=9999)
        first = numbering().next_invoice_number(session, "biz-1")
        second = numbering().next_invoice_number(session, "biz-1")
        self.assertEqual([first, second], ["INV-9999", "INV-10000"])


class TestSettingsCreatedOnDemand(unittest.TestCase):
    """Criterion: businesses with no settings row get one created on demand."""

    def test_missing_settings_row_still_yields_a_number(self):
        session = ConcurrentCounterSession(start=1, settings_exists=False)
        self.assertEqual(numbering().next_invoice_number(session, "biz-1"), "INV-0001")

    def test_missing_settings_row_is_created(self):
        session = ConcurrentCounterSession(start=1, settings_exists=False)
        numbering().next_invoice_number(session, "biz-1")
        self.assertTrue(
            any(sql.upper().startswith("INSERT") for sql, _ in session.statements),
            "no settings row was created for a business that had none",
        )


class TestIndependenceFromSyncedInvoices(unittest.TestCase):
    """
    Criteria: the partial unique index means a synced invoice can never collide
    with the app's series, and synced numbers are stored verbatim.

    New Body already holds a Xero invoice numbered INV-0001. The app's counter
    for that business must be unaffected by it — it neither skips it nor
    renumbers it.
    """

    def test_app_series_is_not_advanced_by_a_synced_invoice(self):
        session = ConcurrentCounterSession(start=1)
        synced = {"INV-0001"}                    # from Xero, external_source set
        app_generated = set()

        def insert_fn(number):
            # The index is partial — WHERE external_source IS NULL — so only
            # app-generated rows can collide with each other.
            if number in app_generated:
                raise duplicate_key_error(number)
            app_generated.add(number)

        issued = numbering().allocate(session, "biz-1", insert_fn)
        self.assertEqual(
            issued, "INV-0001",
            "the app skipped a number because a SYNCED invoice used it — the "
            "partial index exists precisely so it does not have to",
        )
        self.assertEqual(synced, {"INV-0001"}, "the synced number was altered")


class SeedSession:
    """
    Serves the seed query, and refuses to answer one that is not scoped the way
    the spec requires: app-generated rows only.
    """

    def __init__(self, max_suffix):
        self.max_suffix = max_suffix
        self.statements = []

    def execute(self, statement, params=None):
        assert isinstance(statement, TextClause)
        sql = " ".join(statement.text.split())
        self.statements.append((sql, params))
        upper = sql.upper()
        assert "BUSINESS_ID" in upper, f"seed query is not tenant-scoped: {sql}"
        assert "'QUOTE'" in upper, (
            "the seed query must restrict to app-generated rows (source='quote'). "
            "Without it the legacy INV-100x CSV rows seed New Body's counter to "
            f"1004. SQL: {sql}"
        )
        assert "COUNT(" not in upper, f"seed must not COUNT rows: {sql}"
        return FakeResult(FakeRow(["max_suffix"], [self.max_suffix]))


class TestSeedValue(unittest.TestCase):
    """
    Criterion: counter seeds from app-generated rows only (source='quote') —
    MSC to 2, every other business to 1. Legacy INV-100x CSV rows and the Xero
    row are ignored.
    """

    def test_msc_seeds_to_two(self):
        # MSC holds exactly one app-generated invoice, INV-0001.
        session = SeedSession(max_suffix=1)
        self.assertEqual(numbering().seed_value_for_business(session, "msc"), 2)

    def test_business_with_no_app_generated_invoices_seeds_to_one(self):
        # New Body: three legacy CSV rows and one Xero row, none app-generated.
        session = SeedSession(max_suffix=None)
        self.assertEqual(numbering().seed_value_for_business(session, "newbody"), 1)

    def test_empty_business_seeds_to_one(self):
        session = SeedSession(max_suffix=None)
        self.assertEqual(numbering().seed_value_for_business(session, "test-a"), 1)

    def test_seed_query_is_restricted_to_app_generated_rows(self):
        # The SeedSession asserts this on the way through; this test names the
        # criterion so a failure reads as the criterion rather than as a fake.
        session = SeedSession(max_suffix=1)
        numbering().seed_value_for_business(session, "msc")
        self.assertTrue(
            any("'quote'" in sql.lower() for sql, _ in session.statements)
        )


class ReadOnlySession:
    """Records statements and rejects nothing — the test asserts what it saw."""

    def __init__(self, prefix="INV-"):
        self.prefix = prefix
        self.statements = []

    def execute(self, statement, params=None):
        assert isinstance(statement, TextClause)
        sql = " ".join(statement.text.split())
        self.statements.append((sql, params))
        return FakeResult(FakeRow(["invoice_prefix"], [self.prefix]))

    def commit(self):
        raise AssertionError("detect_prefix_collision must not commit anything")


class TestPrefixCollisionDetection(unittest.TestCase):
    """
    Criterion: on connecting a provider, detect its numbering format; if it
    matches the business's prefix, warn and offer to change. Warn, NEVER
    auto-change — an invoice series is the customer's own record, and silently
    renumbering it is the one thing that would be unforgivable.
    """

    def test_warns_when_provider_numbering_matches_the_prefix(self):
        session = ReadOnlySession(prefix="INV-")
        warning = numbering().detect_prefix_collision(
            session, "biz-1", ["INV-0001", "INV-0002"]
        )
        self.assertIsNotNone(warning, "Xero's INV- series went undetected")
        self.assertEqual(warning["current_prefix"], "INV-")
        self.assertTrue(warning["message"].strip())

    def test_offers_a_different_prefix_as_a_suggestion(self):
        session = ReadOnlySession(prefix="INV-")
        warning = numbering().detect_prefix_collision(session, "biz-1", ["INV-0001"])
        self.assertNotEqual(warning["suggested_prefix"], "INV-")

    def test_does_not_change_anything(self):
        session = ReadOnlySession(prefix="INV-")
        numbering().detect_prefix_collision(session, "biz-1", ["INV-0001"])
        writes = [
            sql for sql, _ in session.statements
            if not sql.upper().startswith("SELECT")
        ]
        self.assertEqual(
            writes, [],
            f"detect_prefix_collision issued writes: {writes}. It must warn only.",
        )

    def test_no_warning_when_the_formats_differ(self):
        session = ReadOnlySession(prefix="INV-")
        self.assertIsNone(
            numbering().detect_prefix_collision(session, "biz-1", ["XR-1001", "XR-1002"])
        )

    def test_no_warning_when_the_provider_has_no_invoices_yet(self):
        session = ReadOnlySession(prefix="INV-")
        self.assertIsNone(numbering().detect_prefix_collision(session, "biz-1", []))


if __name__ == "__main__":
    unittest.main()
