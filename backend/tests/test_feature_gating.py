import asyncio
import unittest
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy.sql.elements import TextClause

from auth import require_feature


class FakeResult:
    def __init__(self, value):
        self._value = value

    def first(self):
        return self._value


class FakeSession:
    def __init__(self, business, is_admin=False):
        self.business = business
        self.is_admin = is_admin

    def exec(self, statement, params=None):
        if isinstance(statement, TextClause) and "platform_admins" in statement.text:
            return FakeResult(1 if self.is_admin else None)
        return FakeResult(self.business)


class TestFeatureGating(unittest.TestCase):
    def test_email_feature_disabled_returns_403(self):
        business = SimpleNamespace(
            id="biz-1",
            is_active=True,
            trial_ends_at=None,
            plan_tier="starter",
            feature_flags={"email": False},
        )
        session = FakeSession(business, is_admin=False)
        dep = require_feature("email")
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(dep(auth_ctx={"user_id": "user-1", "business_id": "biz-1"}, session=session))
        self.assertEqual(ctx.exception.status_code, 403)

    def test_email_feature_enabled_allows_access(self):
        business = SimpleNamespace(
            id="biz-1",
            is_active=True,
            trial_ends_at=None,
            plan_tier="starter",
            feature_flags={"email": True},
        )
        session = FakeSession(business, is_admin=False)
        dep = require_feature("email")
        result = asyncio.run(dep(auth_ctx={"user_id": "user-1", "business_id": "biz-1"}, session=session))
        self.assertTrue(result)

    def test_platform_admin_bypass(self):
        business = SimpleNamespace(
            id="biz-1",
            is_active=True,
            trial_ends_at=None,
            plan_tier="starter",
            feature_flags={"email": False},
        )
        session = FakeSession(business, is_admin=True)
        dep = require_feature("email")
        result = asyncio.run(dep(auth_ctx={"user_id": "admin-1", "business_id": "biz-1"}, session=session))
        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
