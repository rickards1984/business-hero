"""The onboarding wizard's `feature_flags` writer — BH-007.

WHY THIS FILE EXISTS. `admin_business_api` validated `feature_flags` and
`onboarding_api.save_wizard_step` did not. Its `plan_features` branch takes an
untyped `step_data: dict` — the declared `PlanFeaturesStep` model is not
applied to it — and passed `feature_flags` straight into `strip_plan_defaults`
and then into the column.

Two consequences, and the first is an entitlement escalation:

    business.feature_flags = {"receptionist": "false"}   # a STRING
    _is_feature_enabled(business, "receptionist")        # -> True

`bool("false")` is True. So a value spelled like a denial GRANTED the feature,
on a `starter` plan whose own default for it is False. Verified against the
real `_is_feature_enabled` in `test_the_escalation_this_prevents` below rather
than asserted.

The second: once such a value was stored, the admin editor refused every
subsequent save of that business, because its validator correctly rejects a
non-boolean feature key. That is how it was found — BH-007 started as "the
admin cannot save a business" and the wizard turned out to be the other half.

Codex's review of the first BH-007 fix caught this: the validator had been
fixed in one writer and left open in the other, while the commit message
claimed an admin-wide invariant.
"""
import asyncio
import json
import unittest
from types import SimpleNamespace

from fastapi import HTTPException

from auth import _is_feature_enabled, validate_feature_flags


def api():
    import onboarding_api
    return onboarding_api


ADMIN = {"user_id": "admin-1", "is_platform_admin": True}


class FakeRow:
    """Carries `_mapping`, because `_row_to_dict` reads it (onboarding_api:137)."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        self._mapping = dict(kwargs)

    def __getitem__(self, i):
        return list(self._mapping.values())[i]


class WizardSession:
    """Enough session for save_wizard_step's plan_features branch."""

    def __init__(self, plan_tier="starter"):
        self.plan_tier = plan_tier
        self.statements = []
        self.committed = False

    def execute(self, statement, params=None):
        sql = " ".join(str(statement).split())
        self.statements.append((sql, params or {}))
        upper = sql.upper()
        if "SELECT PLAN_TIER FROM BUSINESSES" in upper:
            return SimpleNamespace(fetchone=lambda: FakeRow(plan_tier=self.plan_tier))
        if "FROM ONBOARDING_SESSIONS" in upper:
            return SimpleNamespace(fetchone=lambda: FakeRow(
                id="00000000-0000-0000-0000-0000000000aa",
                business_id="00000000-0000-0000-0000-000000000001",
                status="in_progress", steps_completed={}, wizard_data={},
                current_step="plan_features"))
        if "FROM PLATFORM_ADMINS" in upper:
            return SimpleNamespace(fetchone=lambda: FakeRow(user_id="admin-1"),
                                   first=lambda: (1,))
        return SimpleNamespace(fetchone=lambda: None, first=lambda: None)

    def commit(self):
        self.committed = True

    def flags_written(self):
        for sql, params in self.statements:
            if "UPDATE BUSINESSES SET FEATURE_FLAGS" in sql.upper():
                value = params.get("flags")
                return json.loads(value) if isinstance(value, str) else value
        return None


def save_plan_features(session, flags):
    return asyncio.run(api().save_wizard_step(
        business_id="00000000-0000-0000-0000-000000000001",
        step_name="plan_features",
        step_data={"feature_flags": flags},
        auth_ctx=ADMIN,
        session=session,
    ))


class TestTheEscalation(unittest.TestCase):

    def test_the_escalation_this_prevents(self):
        """Not a hypothetical. This is what the unvalidated writer could store,
        and what it did to access. Asserted against the REAL gate."""
        business = SimpleNamespace(plan_tier="starter",
                                   feature_flags={"receptionist": "false"})
        self.assertTrue(
            _is_feature_enabled(business, "receptionist"),
            "if this is False the escalation no longer exists and this test "
            "should be rewritten — but bool('false') is True in Python",
        )
        # And the plan itself does not grant it, so the string is the only
        # reason access would be given.
        from auth import PLAN_FEATURE_DEFAULTS
        self.assertFalse(PLAN_FEATURE_DEFAULTS["starter"]["receptionist"])

    def test_the_shared_validator_refuses_it(self):
        with self.assertRaises(HTTPException) as ctx:
            validate_feature_flags({"receptionist": "false"})
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("must be true or false", ctx.exception.detail)


class TestTheWizardWriter(unittest.TestCase):
    """Through `save_wizard_step` itself, which is the path that was open."""

    def _expect_400(self, flags):
        with self.assertRaises(HTTPException) as ctx:
            save_plan_features(WizardSession(), flags)
        self.assertEqual(ctx.exception.status_code, 400)
        return ctx.exception.detail

    def test_a_string_on_a_canonical_feature_is_refused(self):
        detail = self._expect_400({"receptionist": "false"})
        self.assertIn("receptionist", detail)

    def test_a_number_on_a_canonical_feature_is_refused(self):
        self._expect_400({"email": 1})

    def test_a_nested_object_is_refused(self):
        self._expect_400({"email": {"enabled": True}})

    def test_nothing_is_written_when_validation_fails(self):
        """The 400 must come BEFORE the UPDATE, or the bad value is already in
        the column and the admin editor is blocked regardless."""
        session = WizardSession()
        with self.assertRaises(HTTPException):
            save_plan_features(session, {"receptionist": "false"})
        self.assertIsNone(session.flags_written(),
                          "feature_flags was written despite failing validation")
        self.assertFalse(session.committed)

    def test_the_wizard_s_industry_metadata_still_works(self):
        """The fix must not break the wizard's own legitimate string."""
        session = WizardSession(plan_tier="starter")
        save_plan_features(session, {"industry": "construction",
                                     "receptionist": True})
        written = session.flags_written()
        self.assertEqual(written["industry"], "construction")
        self.assertIs(written["receptionist"], True)

    def test_a_plan_default_is_still_stripped(self):
        """PART C's strip must still run after validation."""
        session = WizardSession(plan_tier="starter")
        save_plan_features(session, {"quoting": True, "industry": "gym"})
        written = session.flags_written()
        self.assertNotIn("quoting", written,
                         "a flag restating the plan default was stored")
        self.assertEqual(written["industry"], "gym")


class TestEveryWriterUsesTheSameValidator(unittest.TestCase):
    """The invariant BH-007's first attempt claimed without establishing."""

    def test_admin_and_onboarding_share_one_implementation(self):
        import admin_business_api
        import auth
        self.assertIs(admin_business_api.validate_feature_flags,
                      auth.validate_feature_flags)
        self.assertIs(api().validate_feature_flags, auth.validate_feature_flags)

    def test_the_vocabulary_is_derived_from_the_plan_table(self):
        import auth
        self.assertEqual(auth.FEATURE_FLAG_VOCABULARY,
                         frozenset(auth.PLAN_FEATURE_DEFAULTS["business"]))

    def test_every_tier_declares_the_same_keys(self):
        """The derivation above uses `business` as the vocabulary. That is only
        sound while every tier declares the same keys — Codex's point that the
        'cannot drift' claim rests on an invariant rather than being automatic.
        Asserted here so it fails loudly if a tier diverges."""
        import auth
        vocab = frozenset(auth.PLAN_FEATURE_DEFAULTS["business"])
        for tier, defaults in auth.PLAN_FEATURE_DEFAULTS.items():
            self.assertEqual(frozenset(defaults), vocab,
                             f"tier {tier!r} declares a different key set")


if __name__ == "__main__":
    unittest.main()
