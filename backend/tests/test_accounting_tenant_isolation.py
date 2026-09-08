"""BH-002 — accounting categories must not cross a tenant boundary.

Foundation review 001 finding 5. `accounting_transactions` was scoped by
`business_id` on every path, but `category_id` arrived from the request body
and was written without an ownership check, and the reporting joins matched
categories on id alone. Business A could therefore attach business B's
category to its own transaction, and every category-joined read then returned
B's category name and colour.

This is a TENANT ISOLATION defect, not an entitlement one. The backend
connects as an elevated role and bypasses RLS (`AGENTS.md` §4), so the
database does not catch it — these checks are the only control.

All data here is synthetic. Nothing touches a live or staging database.
"""

import asyncio
import sqlite3
import unittest
import uuid
from pathlib import Path

from fastapi import HTTPException

import accounting

BUSINESS_A = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
BUSINESS_B = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
CATEGORY_OF_B = uuid.UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
CATEGORY_OF_A = uuid.UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")


class FakeBusiness:
    def __init__(self, business_id):
        self.id = business_id


class FakeResult:
    def __init__(self, row=None):
        self._row = row

    def fetchone(self):
        return self._row

    def fetchall(self):
        return [self._row] if self._row else []


class OwnershipSession:
    """A session that answers the ownership probe truthfully for one tenant.

    Any category owned by `owner` resolves; anything else does not — which is
    what the live table would say.
    """

    def __init__(self, owner, owned_categories):
        self.owner = str(owner)
        self.owned = {str(c) for c in owned_categories}
        self.statements = []
        self.committed = False

    def execute(self, statement, params=None):
        sql = statement.text if hasattr(statement, "text") else str(statement)
        self.statements.append((sql, params or {}))
        if "FROM accounting_categories" in sql and "SELECT 1" in sql:
            cat = str((params or {}).get("category_id"))
            biz = str((params or {}).get("business_id"))
            ok = cat in self.owned and biz == self.owner
            return FakeResult((1,) if ok else None)
        # Any write returns a plausible RETURNING row.
        return FakeResult((str(uuid.uuid4()),))

    def commit(self):
        self.committed = True

    def probed_for_category(self):
        return [s for s, _ in self.statements if "FROM accounting_categories" in s]


def a_session():
    """Business A's session: A owns CATEGORY_OF_A and nothing else."""
    return OwnershipSession(BUSINESS_A, [CATEGORY_OF_A])


USER_A = (object(), FakeBusiness(BUSINESS_A))


class TestWritePathsRefuseAnotherTenantsCategory(unittest.TestCase):
    """The three paths that accept a caller-supplied category_id."""

    def test_create_transaction_refuses(self):
        session = a_session()
        payload = accounting.TransactionCreate(
            transaction_date="2026-09-08", description="synthetic",
            amount=10.0, type="expense", category_id=str(CATEGORY_OF_B),
        )
        with self.assertRaises(HTTPException) as caught:
            asyncio.run(accounting.create_transaction(
                transaction=payload, user_business=USER_A, session=session))
        self.assertEqual(caught.exception.status_code, 404)
        self.assertFalse(session.committed, "refused write must not commit")

    def test_create_transaction_allows_its_own_category(self):
        session = a_session()
        payload = accounting.TransactionCreate(
            transaction_date="2026-09-08", description="synthetic",
            amount=10.0, type="expense", category_id=str(CATEGORY_OF_A),
        )
        asyncio.run(accounting.create_transaction(
            transaction=payload, user_business=USER_A, session=session))
        self.assertTrue(session.probed_for_category(), "ownership was not checked")

    def test_create_transaction_allows_no_category(self):
        session = a_session()
        payload = accounting.TransactionCreate(
            transaction_date="2026-09-08", description="synthetic",
            amount=10.0, type="expense", category_id=None,
        )
        asyncio.run(accounting.create_transaction(
            transaction=payload, user_business=USER_A, session=session))

    def test_bulk_update_category_refuses(self):
        session = a_session()
        request = accounting.BulkUpdateCategoryRequest(
            transaction_ids=[str(uuid.uuid4())], category_id=str(CATEGORY_OF_B))
        with self.assertRaises(HTTPException) as caught:
            asyncio.run(accounting.bulk_update_category(
                request=request, user_business=USER_A, session=session))
        self.assertEqual(caught.exception.status_code, 404)
        self.assertFalse(session.committed)

    def test_bulk_update_category_allows_its_own(self):
        session = a_session()
        request = accounting.BulkUpdateCategoryRequest(
            transaction_ids=[str(uuid.uuid4())], category_id=str(CATEGORY_OF_A))
        asyncio.run(accounting.bulk_update_category(
            request=request, user_business=USER_A, session=session))

    def test_patch_transaction_refuses(self):
        session = a_session()
        updates = accounting.UpdateTransactionRequest(
            category_id=str(CATEGORY_OF_B))
        with self.assertRaises(HTTPException) as caught:
            asyncio.run(accounting.update_transaction(
                transaction_id=str(uuid.uuid4()), updates=updates,
                user_business=USER_A, session=session))
        self.assertEqual(caught.exception.status_code, 404)
        self.assertFalse(session.committed)

    def test_patch_transaction_allows_its_own(self):
        session = a_session()
        updates = accounting.UpdateTransactionRequest(
            category_id=str(CATEGORY_OF_A))
        asyncio.run(accounting.update_transaction(
            transaction_id=str(uuid.uuid4()), updates=updates,
            user_business=USER_A, session=session))


class TestOwnershipHelper(unittest.TestCase):

    def test_none_and_empty_pass_through(self):
        session = a_session()
        self.assertIsNone(accounting.require_own_category(session, None, BUSINESS_A))
        self.assertEqual(
            accounting.require_own_category(session, "", BUSINESS_A), "")

    def test_foreign_category_raises_404_not_403(self):
        """404, not 403: whether an id exists in another business is itself
        information this caller is not entitled to."""
        session = a_session()
        with self.assertRaises(HTTPException) as caught:
            accounting.require_own_category(session, str(CATEGORY_OF_B), BUSINESS_A)
        self.assertEqual(caught.exception.status_code, 404)


class TestTheJoinCannotReadAnotherTenantsCategory(unittest.TestCase):
    """The leak, reproduced on synthetic data, then shown closed.

    Two businesses, one transaction belonging to A that references B's
    category — exactly the row the unvalidated write paths could create, and
    which may already exist in production.
    """

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript(
            """
            CREATE TABLE accounting_categories (
                id TEXT PRIMARY KEY, business_id TEXT, name TEXT, color TEXT);
            CREATE TABLE accounting_transactions (
                id TEXT PRIMARY KEY, business_id TEXT, category_id TEXT,
                description TEXT, is_archived INTEGER DEFAULT 0);
            """
        )
        self.db.execute(
            "INSERT INTO accounting_categories VALUES (?,?,?,?)",
            (str(CATEGORY_OF_B), str(BUSINESS_B), "B PRIVATE CATEGORY", "#ff0000"))
        self.db.execute(
            "INSERT INTO accounting_transactions VALUES (?,?,?,?,0)",
            (str(uuid.uuid4()), str(BUSINESS_A), str(CATEGORY_OF_B), "A's row"))

    def _select(self, join_clause):
        return self.db.execute(
            f"""
            SELECT t.description, c.name AS category_name
              FROM accounting_transactions t
              {join_clause}
             WHERE t.business_id = ? AND t.is_archived = 0
            """,
            (str(BUSINESS_A),),
        ).fetchall()

    def test_the_unscoped_join_leaks(self):
        """Guards the test itself: if this stops leaking, the fixture no longer
        reproduces the defect and the test below proves nothing."""
        rows = self._select(
            "LEFT JOIN accounting_categories c ON t.category_id = c.id")
        self.assertEqual(rows[0][1], "B PRIVATE CATEGORY")

    def test_the_scoped_join_does_not_leak(self):
        rows = self._select(
            "LEFT JOIN accounting_categories c "
            "ON t.category_id = c.id AND c.business_id = t.business_id")
        self.assertEqual(len(rows), 1, "A's own transaction must still be returned")
        self.assertIsNone(rows[0][1], "another tenant's category name leaked")


class TestEveryCategoryJoinIsScoped(unittest.TestCase):
    """Coverage, not behaviour: a fifth join added later must be scoped too."""

    def test_no_unscoped_category_join_remains(self):
        src = (Path(accounting.__file__)).read_text()
        joins = [
            block for block in src.split("JOIN accounting_categories")[1:]
        ]
        self.assertGreaterEqual(len(joins), 4, "expected at least four joins")
        for block in joins:
            condition = block.split("WHERE")[0]
            self.assertIn(
                "c.business_id = t.business_id", condition,
                "a category join is not scoped to the transaction's business:\n"
                + condition.strip()[:200])


if __name__ == "__main__":
    unittest.main()
