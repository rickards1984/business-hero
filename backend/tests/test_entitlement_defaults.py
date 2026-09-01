"""
ENTITLEMENT-SPEC PART C — plan is the source of truth.

Two things are encoded here.

ONE: there is exactly ONE plan->feature table in the Python codebase, it is
the canonical PART B table, and it agrees with the two other copies that
cannot be deduplicated away (the frontend's `entitlements.ts`, and the
`plan_defaults` CTE in `backend/migrations/033_entitlement.sql`). The sweep
found five copies in three vocabularies; `auth.py` and `main.py` held the
same non-canonical dict, twice.

    THE ORDERING THIS PROTECTS: 033 SECTION 7 removes flags that merely
    restate the plan default. Applied against the DEPLOYED non-canonical
    dict, that measured EIGHT feature losses across the two live businesses
    on staging (see the migration's SECTION 6 warning). SECTION 7 is safe
    only once the canonical table is what ships. These tests are what says
    it shipped.

TWO: no creation path writes plan defaults into `feature_flags`. That dict
holds ONLY deliberate per-business exceptions — a beta grant, a goodwill
grant, a feature switched off for one customer. Empty is the normal state.
Anything that writes a default back undoes SECTION 7 on the first save.

The strip rule, stated once:

    a key is REMOVED only when it is in the canonical vocabulary AND holds
    a boolean AND that boolean EQUALS the plan default for this tier.

Everything else survives — unknown keys, non-booleans, and any boolean that
CONTRADICTS its default (which is the whole point: an explicit `false`
against a granting plan is a deliberate denial, not noise).

`limits` is deliberately untouched throughout. Nothing reads it for
enforcement, so stripping it would remove a record rather than relocate one.
"""
import asyncio
import json
import re
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
ENTITLEMENTS_TS = ROOT / "frontend" / "client" / "src" / "lib" / "entitlements.ts"
MIGRATION_033 = ROOT / "backend" / "migrations" / "033_entitlement.sql"

CANONICAL_TIERS = ("starter", "pro", "business", "beta")
ADMIN = {"user_id": "admin-1", "email": "admin@example.com"}


# ── The two out-of-Python copies, parsed rather than restated ────────────────
#
# Restating the table here would make this file a SIXTH copy, and a test that
# is a copy of the thing it tests cannot catch drift. These read the real
# files instead: change either one without changing Python and this fails.

def parse_typescript_defaults():
    src = ENTITLEMENTS_TS.read_text()
    match = re.search(
        r"PLAN_FEATURE_DEFAULTS[^=]*=\s*\{(.*?)\n\};", src, re.DOTALL
    )
    assert match, "PLAN_FEATURE_DEFAULTS not found in entitlements.ts — has it moved?"
    table = {}
    for tier, body in re.findall(r"(\w+):\s*\{(.*?)\}", match.group(1), re.DOTALL):
        table[tier] = {
            key: value == "true"
            for key, value in re.findall(r"(\w+):\s*(true|false)", body)
        }
    assert table, "parsed entitlements.ts to nothing — the regex is wrong, not the code"
    return table


def parse_migration_defaults():
    src = MIGRATION_033.read_text()
    match = re.search(
        r"WITH plan_defaults\(plan_tier, feature, enabled\) AS \(\s*VALUES(.*?)\n\),",
        src,
        re.DOTALL,
    )
    assert match, "plan_defaults CTE not found in 033 — has SECTION 7 moved?"
    table = {}
    for tier, feature, enabled in re.findall(
        r"\('(\w+)','(\w+)',(true|false)\)", match.group(1)
    ):
        table.setdefault(tier, {})[feature] = enabled == "true"
    assert table, "parsed the 033 CTE to nothing — the regex is wrong, not the code"
    return table


class TestOneCanonicalTable(unittest.TestCase):
    def test_python_agrees_with_the_frontend(self):
        import auth
        expected = parse_typescript_defaults()
        for tier in CANONICAL_TIERS:
            self.assertEqual(
                auth._plan_feature_defaults(tier), expected[tier],
                f"{tier} disagrees with entitlements.ts. The frontend hides a "
                f"button; the backend refuses the request. They must agree or "
                f"a customer sees a feature they cannot use, or vice versa.",
            )

    def test_python_agrees_with_migration_033(self):
        import auth
        expected = parse_migration_defaults()
        for tier in CANONICAL_TIERS:
            self.assertEqual(
                auth._plan_feature_defaults(tier), expected[tier],
                f"{tier} disagrees with 033's plan_defaults CTE. SECTION 7 "
                f"strips flags using that CTE and the running code resolves "
                f"them using this dict. A mismatch removes paid access.",
            )

    def test_the_vocabulary_is_the_canonical_twelve(self):
        import auth
        self.assertEqual(
            set(auth.CANONICAL_FEATURES),
            {"quoting", "invoicing", "accounting", "email", "aria_chat",
             "aria_voice", "whatsapp", "board_meetings", "calendar_booking",
             "calendar_sync", "receptionist", "outreach"},
        )
        for tier in CANONICAL_TIERS:
            self.assertEqual(
                set(auth._plan_feature_defaults(tier)), set(auth.CANONICAL_FEATURES),
                f"{tier} must give every canonical feature an explicit "
                f"true/false. A missing key resolves to False by omission, "
                f"which is a denial nobody wrote down.",
            )

    def test_the_old_non_canonical_keys_are_gone(self):
        # `calendar` and `voice` were the deployed dict's invention. They are
        # in no plan, no migration and no frontend list.
        import auth
        for tier in CANONICAL_TIERS:
            defaults = auth._plan_feature_defaults(tier)
            self.assertNotIn("calendar", defaults)
            self.assertNotIn("voice", defaults)

    def test_starter_is_not_empty(self):
        # The deployed dict gave starter `{}` — every feature denied. A paying
        # starter customer resolves to no access at all under PART C.
        import auth
        starter = auth._plan_feature_defaults("starter")
        self.assertTrue(starter["quoting"])
        self.assertTrue(starter["invoicing"])
        self.assertTrue(starter["accounting"])
        self.assertTrue(starter["email"])
        self.assertTrue(starter["aria_chat"])
        self.assertFalse(starter["outreach"])
        self.assertFalse(starter["receptionist"])

    def test_calendar_sync_is_granted_by_every_tier(self):
        # It gates nothing today and is true everywhere on purpose: Google
        # issues Gmail and Calendar under ONE consent, so a business that has
        # connected email has already granted calendar access. The word exists
        # so the concept is not lost; separating it would mean splitting the
        # OAuth grant first. If it ever becomes a real gate, this test is the
        # thing that should have to change deliberately.
        import auth
        for tier in CANONICAL_TIERS:
            self.assertTrue(
                auth._plan_feature_defaults(tier)["calendar_sync"],
                f"{tier} denies calendar_sync, but nothing gates it and it "
                f"rides on `email`, which {tier} grants.",
            )
        self.assertIn("calendar_sync", auth.CANONICAL_FEATURES)

    def test_calendar_sync_and_calendar_booking_are_different_features(self):
        # calendar_booking is a sold, plan-gated feature (the receptionist
        # taking a booking). calendar_sync is the Google grant. Collapsing the
        # two is how `calendar` became a key nobody could explain.
        import auth
        self.assertFalse(auth._plan_feature_defaults("starter")["calendar_booking"])
        self.assertTrue(auth._plan_feature_defaults("starter")["calendar_sync"])

    def test_outreach_is_what_separates_business_from_pro(self):
        # The spec's downgrade case: business -> pro loses outreach.
        import auth
        self.assertTrue(auth._plan_feature_defaults("business")["outreach"])
        self.assertFalse(auth._plan_feature_defaults("pro")["outreach"])

    def test_an_unknown_tier_falls_back_to_starter(self):
        # Fails closed to the least-privileged tier, matching planDefaults()
        # in entitlements.ts. `paused` is deliberately not a tier — DECISION 3
        # and 033 SECTION 1's CHECK both dropped it.
        import auth
        starter = auth._plan_feature_defaults("starter")
        self.assertEqual(auth._plan_feature_defaults("nonsense"), starter)
        self.assertEqual(auth._plan_feature_defaults(None), starter)
        self.assertEqual(auth._plan_feature_defaults("paused"), starter)

    def test_tier_lookup_is_case_insensitive(self):
        import auth
        self.assertEqual(
            auth._plan_feature_defaults("PRO"), auth._plan_feature_defaults("pro")
        )

    def test_callers_cannot_mutate_the_shared_table(self):
        # `_merge_feature_flags` used to hand this dict straight into a
        # `{**defaults, **existing}`. A caller that mutates it instead would
        # silently repartition every business on the process.
        import auth
        auth._plan_feature_defaults("pro")["outreach"] = True
        self.assertFalse(
            auth._plan_feature_defaults("pro")["outreach"],
            "the defaults table is mutable through its return value",
        )


class TestPartCResolution(unittest.TestCase):
    """flags[feature] if present, else the plan default, else False."""

    def enabled(self, plan_tier, flags, feature):
        import auth
        business = SimpleNamespace(plan_tier=plan_tier, feature_flags=flags)
        return auth._is_feature_enabled(business, feature)

    def test_empty_flags_resolve_entirely_from_the_plan(self):
        # The normal state after 033 SECTION 7: both live businesses on `pro`
        # with `{}`, keeping all ten features the plan grants.
        self.assertTrue(self.enabled("pro", {}, "receptionist"))
        self.assertTrue(self.enabled("pro", {}, "accounting"))
        self.assertTrue(self.enabled("pro", {}, "quoting"))
        self.assertTrue(self.enabled("pro", {}, "whatsapp"))
        self.assertTrue(self.enabled("pro", {}, "calendar_booking"))

    def test_an_explicit_false_denies_what_the_plan_grants(self):
        self.assertTrue(self.enabled("pro", {}, "receptionist"))
        self.assertFalse(self.enabled("pro", {"receptionist": False}, "receptionist"))

    def test_an_explicit_true_grants_what_the_plan_denies(self):
        # The beta-grant case.
        self.assertFalse(self.enabled("pro", {}, "outreach"))
        self.assertTrue(self.enabled("pro", {"outreach": True}, "outreach"))

    def test_a_downgrade_removes_access_immediately(self):
        # The PART C acceptance criterion. With no default written into flags,
        # dropping business -> pro loses outreach at the next read.
        self.assertTrue(self.enabled("business", {}, "outreach"))
        self.assertFalse(self.enabled("pro", {}, "outreach"))

    def test_a_default_written_into_flags_defeats_the_downgrade(self):
        # Not a wish — a statement of why the creation paths matter. This is
        # the behaviour every test below exists to prevent reaching the DB.
        self.assertTrue(self.enabled("pro", {"outreach": True}, "outreach"))

    def test_an_unknown_feature_is_denied(self):
        self.assertFalse(self.enabled("business", {}, "teleportation"))


class TestStripPlanDefaults(unittest.TestCase):
    """The one rule, applied server-side on every write path."""

    def strip(self, flags, plan_tier):
        import auth
        return auth.strip_plan_defaults(flags, plan_tier)

    def test_a_boolean_restating_its_default_is_removed(self):
        self.assertEqual(self.strip({"receptionist": True}, "pro"), {})
        self.assertEqual(self.strip({"outreach": False}, "pro"), {})

    def test_a_boolean_contradicting_its_default_is_kept(self):
        # Both directions. A denial is as deliberate as a grant.
        self.assertEqual(
            self.strip({"receptionist": False}, "pro"), {"receptionist": False}
        )
        self.assertEqual(self.strip({"outreach": True}, "pro"), {"outreach": True})

    def test_a_full_plan_copy_strips_to_nothing(self):
        # Exactly what the wizard submits today.
        import auth
        self.assertEqual(self.strip(dict(auth._plan_feature_defaults("pro")), "pro"), {})

    def test_an_unknown_key_is_kept_even_when_boolean(self):
        # R3. `whatsapp_briefing` and `invoice_chasing` are the wizard's own
        # vocabulary and are in no plan table. Nothing here may drop them —
        # this code cannot know whether they mean something to someone.
        self.assertEqual(
            self.strip({"whatsapp_briefing": True, "invoice_chasing": False}, "pro"),
            {"whatsapp_briefing": True, "invoice_chasing": False},
        )

    def test_a_non_boolean_is_kept(self):
        # `brand_color` (pending 033 SECTION 6) and the wizard's `industry`.
        self.assertEqual(
            self.strip({"brand_color": "#3B82F6", "industry": "plumbing"}, "pro"),
            {"brand_color": "#3B82F6", "industry": "plumbing"},
        )

    def test_it_separates_the_deliberate_from_the_redundant(self):
        result = self.strip(
            {
                "receptionist": True,      # pro default true  -> redundant
                "accounting": True,        # pro default true  -> redundant
                "outreach": True,          # pro default false -> a grant
                "email": False,            # pro default true  -> a denial
                "industry": "fitness",     # not a boolean     -> kept
                "invoice_chasing": True,   # unknown key       -> kept
            },
            "pro",
        )
        self.assertEqual(
            result,
            {"outreach": True, "email": False,
             "industry": "fitness", "invoice_chasing": True},
        )

    def test_the_tier_decides_what_is_redundant(self):
        # Identical input, different plan, opposite outcome.
        self.assertEqual(self.strip({"outreach": True}, "business"), {})
        self.assertEqual(self.strip({"outreach": True}, "pro"), {"outreach": True})

    def test_empty_and_none_are_safe(self):
        self.assertEqual(self.strip({}, "pro"), {})
        self.assertEqual(self.strip(None, "pro"), {})

    def test_it_does_not_mutate_its_input(self):
        original = {"receptionist": True, "outreach": True}
        self.strip(original, "pro")
        self.assertEqual(original, {"receptionist": True, "outreach": True})


# ── Fakes for the creation paths ────────────────────────────────────────────

class FakeRow:
    def __init__(self, values):
        self._mapping = dict(values)
        for name, value in values.items():
            setattr(self, name, value)

    def keys(self):
        return list(self._mapping)


class FakeResult:
    def __init__(self, row=None, rows=None):
        self._row = row
        self._rows = rows or []

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows

    def first(self):
        return self._row


class RecordingSession:
    """Records every statement so a test can assert on what reached the DB."""

    def __init__(self, plan_tier="pro", is_admin=True):
        self.is_admin = is_admin
        self.plan_tier = plan_tier
        # PART D: readers resolve `plan_tier` + `feature_flags` together, so
        # the fake has to serve both from one row. Empty is the normal state.
        self.feature_flags = {}
        self.statements = []
        self.committed = False

    def execute(self, statement, params=None):
        sql = statement.text if hasattr(statement, "text") else str(statement)
        self.statements.append((sql, dict(params or {})))

        if "platform_admins" in sql:
            return FakeResult((1,) if self.is_admin else None)
        if "FROM plan_definitions" in sql:
            # The sixth authority. Still consulted for `limits`; must no
            # longer decide feature_flags.
            return FakeResult(FakeRow({
                "features": json.dumps({"receptionist": True, "quoting": True}),
                "limits": json.dumps({"users": 5}),
            }))
        if "INSERT INTO businesses" in sql:
            return FakeResult(FakeRow({"id": "biz-1", "name": "Test Ltd",
                                       "plan_tier": self.plan_tier}))
        if "INSERT INTO onboarding_sessions" in sql:
            return FakeResult(FakeRow({"id": "sess-1", "business_id": "biz-1"}))
        if "FROM onboarding_sessions" in sql:
            return FakeResult(FakeRow({
                "id": "sess-1",
                "business_id": "biz-1",
                "steps_completed": json.dumps({"business_details": True}),
                "wizard_data": json.dumps({}),
            }))
        if "plan_tier" in sql and "FROM businesses" in sql:
            return FakeResult(FakeRow({"plan_tier": self.plan_tier,
                                       "feature_flags": self.feature_flags}))
        if "FROM receptionist_configs" in sql:
            return FakeResult(None)
        return FakeResult(None)

    def commit(self):
        self.committed = True

    # `find` / `exec` are unused on these paths; absence is the assertion.

    def statements_matching(self, needle):
        return [(sql, params) for sql, params in self.statements if needle in sql]


class TestOnboardingCreatesWithEmptyFeatureFlags(unittest.TestCase):
    """onboarding_api.py — the business_details step (was :218-227)."""

    def run_start(self, plan_tier="pro"):
        import onboarding_api
        session = RecordingSession(plan_tier=plan_tier)
        step = onboarding_api.BusinessDetailsStep(
            name="Test Ltd", timezone="Europe/London", plan_tier=plan_tier
        )
        asyncio.run(onboarding_api.start_onboarding(
            step=step, auth_ctx=ADMIN, session=session))
        inserts = session.statements_matching("INSERT INTO businesses")
        self.assertEqual(len(inserts), 1, "expected exactly one business INSERT")
        return inserts[0]

    def test_the_insert_does_not_name_feature_flags(self):
        sql, _ = self.run_start()
        self.assertNotIn(
            "feature_flags", sql,
            "the column must be omitted entirely so the DB default '{}' "
            "applies. Writing '{}' explicitly would work today but restates "
            "a default the schema already guarantees.",
        )

    def test_the_insert_binds_no_feature_flags_parameter(self):
        _, params = self.run_start()
        self.assertNotIn("feature_flags", params)

    def test_limits_is_still_written_from_the_plan(self):
        # Deliberately unchanged. Nothing reads `limits` for enforcement, so
        # blanking it would delete a record rather than relocate one.
        sql, params = self.run_start()
        self.assertIn("limits", sql)
        self.assertIn("limits", params)
        self.assertEqual(json.loads(params["limits"]), {"users": 5})


class TestOnboardingPlanFeaturesStepStrips(unittest.TestCase):
    """onboarding_api.py — the plan_features step (was :371-374)."""

    def saved_flags(self, submitted, plan_tier="pro"):
        import onboarding_api
        session = RecordingSession(plan_tier=plan_tier)
        asyncio.run(onboarding_api.save_wizard_step(
            business_id="biz-1", step_name="plan_features",
            step_data={"feature_flags": submitted},
            auth_ctx=ADMIN, session=session,
        ))
        updates = session.statements_matching("UPDATE businesses SET feature_flags")
        self.assertEqual(len(updates), 1, "expected exactly one feature_flags UPDATE")
        return json.loads(updates[0][1]["flags"])

    def test_a_full_plan_copy_is_stored_as_empty(self):
        # What the wizard submits today for a pro business.
        import auth
        self.assertEqual(self.saved_flags(dict(auth._plan_feature_defaults("pro"))), {})

    def test_a_genuine_grant_survives(self):
        import auth
        submitted = dict(auth._plan_feature_defaults("pro"))
        submitted["outreach"] = True
        self.assertEqual(self.saved_flags(submitted), {"outreach": True})

    def test_a_genuine_denial_survives(self):
        import auth
        submitted = dict(auth._plan_feature_defaults("pro"))
        submitted["receptionist"] = False
        self.assertEqual(self.saved_flags(submitted), {"receptionist": False})

    def test_the_industry_string_survives(self):
        self.assertEqual(
            self.saved_flags({"receptionist": True, "industry": "plumbing"}),
            {"industry": "plumbing"},
        )

    def test_it_strips_against_the_businesss_own_tier(self):
        # A starter business submitting the same dict keeps more, because
        # starter grants less. The tier must be read, not assumed.
        self.assertEqual(self.saved_flags({"receptionist": True}, plan_tier="pro"), {})
        self.assertEqual(
            self.saved_flags({"receptionist": True}, plan_tier="starter"),
            {"receptionist": True},
        )


class TestAdminBusinessCreateStrips(unittest.TestCase):
    """admin_business_api.py — create_business (was :239)."""

    def created_flags(self, submitted, plan_tier="pro"):
        import admin_business_api
        session = RecordingSession(plan_tier=plan_tier)
        result = asyncio.run(admin_business_api.create_business(
            data={"name": "Test Ltd", "plan_tier": plan_tier,
                  "feature_flags": submitted},
            auth_ctx=ADMIN, session=session,
        ))
        inserts = session.statements_matching("INSERT INTO businesses")
        self.assertEqual(len(inserts), 1)
        return inserts[0][1]["feature_flags"], result["feature_flags"]

    def test_a_full_plan_copy_is_stored_as_empty(self):
        # AdminDashboard's FEATURE_PRESETS submits exactly this shape.
        import auth
        stored, _ = self.created_flags(dict(auth._plan_feature_defaults("pro")))
        self.assertEqual(stored, {})

    def test_a_genuine_exception_survives(self):
        stored, _ = self.created_flags({"outreach": True, "receptionist": True})
        self.assertEqual(stored, {"outreach": True})

    def test_brand_color_survives(self):
        # Still permitted as a named exception until 033 SECTION 6 lands.
        stored, _ = self.created_flags({"brand_color": "#FF0000", "quoting": True})
        self.assertEqual(stored, {"brand_color": "#FF0000"})

    def test_the_response_reports_what_was_stored_not_what_was_sent(self):
        # The admin UI reads this back. If it echoes the submitted dict the
        # screen shows eleven flags that are not in the database.
        stored, returned = self.created_flags({"outreach": True, "receptionist": True})
        self.assertEqual(returned, stored)

    def test_limits_is_passed_through_untouched(self):
        import admin_business_api
        session = RecordingSession()
        asyncio.run(admin_business_api.create_business(
            data={"name": "Test Ltd", "plan_tier": "pro",
                  "limits": {"users": 5, "businesses": 3}},
            auth_ctx=ADMIN, session=session,
        ))
        _, params = session.statements_matching("INSERT INTO businesses")[0]
        self.assertEqual(params["limits"], {"users": 5, "businesses": 3})

    def test_validation_still_runs_before_the_strip(self):
        # Stripping must not become a way to smuggle a bad payload past the
        # 030b validators.
        import admin_business_api
        from fastapi import HTTPException
        session = RecordingSession()
        with self.assertRaises(HTTPException):
            asyncio.run(admin_business_api.create_business(
                data={"name": "Test Ltd", "plan_tier": "pro",
                      "feature_flags": {"quoting": "yes please"}},
                auth_ctx=ADMIN, session=session,
            ))


class TestStripeWebhookStopsWritingDefaults(unittest.TestCase):
    """
    Not in the brief, but step 1 forces the question.

    `_merge_feature_flags` did `{**defaults, **existing}` and assigned the
    result to `business.feature_flags` on every subscription event. Against
    the old dict that wrote at most three keys. Against the canonical table it
    would write ELEVEN — so shipping step 1 alone makes this call site
    strictly worse, and the first webhook after deploy would undo every
    creation-path fix above. PART C's first acceptance criterion says the
    webhook sets `plan_tier` only.
    """

    def test_the_merge_helper_is_gone(self):
        import main
        self.assertFalse(
            hasattr(main, "_merge_feature_flags"),
            "_merge_feature_flags wrote plan defaults into the column by "
            "construction. Keeping the name invites the behaviour back.",
        )

    def test_the_webhook_strips_rather_than_merges(self):
        src = (ROOT / "backend" / "main.py").read_text()
        branch = re.search(
            r"if plan_tier:(.*?)business\.is_active", src, re.DOTALL
        )
        self.assertIsNotNone(branch, "the subscription webhook branch has moved")
        # Comments are allowed to name the old helper — that is how the call
        # site records what it replaced. Only the code is asserted on.
        code = "\n".join(
            line for line in branch.group(1).splitlines()
            if not line.strip().startswith("#")
        )
        self.assertIn("strip_plan_defaults", code)
        self.assertNotIn("_merge_feature_flags", code)

    def test_a_plan_default_is_not_written_into_flags(self):
        import main
        self.assertEqual(main.strip_plan_defaults({}, "business"), {})

    def test_a_genuine_exception_survives_a_plan_change(self):
        import main
        self.assertEqual(
            main.strip_plan_defaults({"outreach": True}, "pro"), {"outreach": True}
        )

    def test_an_upgrade_drops_the_exception_it_makes_redundant(self):
        # A goodwill `outreach` grant on pro stops being an exception once the
        # customer upgrades to business. Keeping it would survive a later
        # downgrade as a grant nobody re-authorised.
        import main
        self.assertEqual(main.strip_plan_defaults({"outreach": True}, "business"), {})

    def test_a_downgrade_removes_access_once_flags_are_clean(self):
        # The end-to-end PART C criterion, for a business in the normal state.
        import auth
        import main
        flags = main.strip_plan_defaults({}, "pro")
        business = SimpleNamespace(plan_tier="pro", feature_flags=flags)
        self.assertEqual(flags, {})
        self.assertFalse(auth._is_feature_enabled(business, "outreach"))

    def test_a_LEGACY_MERGED_FLAG_SURVIVES_A_DOWNGRADE(self):
        """A real limitation, encoded so nobody discovers it on an invoice.

        A business that already carries `outreach: True` in the column — put
        there by the old `_merge_feature_flags` — keeps it when it drops to
        `pro`. The strip cannot distinguish a stale merged default from a
        deliberate goodwill grant: relative to `pro`, both look like an
        explicit value CONTRADICTING the plan, and R2 says never drop those.

        This is not a hole the code can close, and it is exactly what
        033 SECTION 7 is for: it strips against the CURRENT tier, so running
        it while both live businesses are still on `pro` reduces them to `{}`
        and every later downgrade then works. Until SECTION 7 runs, a
        downgrade does not revoke a feature the row already claims.
        """
        import auth
        import main
        flags = main.strip_plan_defaults({"outreach": True}, "pro")
        business = SimpleNamespace(plan_tier="pro", feature_flags=flags)
        self.assertEqual(flags, {"outreach": True})
        self.assertTrue(auth._is_feature_enabled(business, "outreach"))


class TestNoSecondPlanTableSurvives(unittest.TestCase):
    """An absence, so it is asserted by looking. Same reasoning as 030b."""

    def test_main_py_declares_no_plan_feature_table_of_its_own(self):
        src = (ROOT / "backend" / "main.py").read_text()
        self.assertNotIn(
            'def _plan_feature_defaults', src,
            "main.py must import the table from auth, not define one.",
        )

    def test_no_backend_source_still_carries_the_calendar_voice_vocabulary(self):
        offenders = []
        for path in sorted((ROOT / "backend").rglob("*.py")):
            if "/tests/" in str(path) or "/.venv/" in str(path):
                continue
            src = path.read_text()
            if '"voice": True' in src and '"calendar": True' in src:
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [], f"non-canonical plan table still present in {offenders}")


if __name__ == "__main__":
    unittest.main()


# ── The wizard, frontend side ───────────────────────────────────────────────
#
# Source-level, for the same reason 030b's hygiene tests are: the fix is that
# a wholesale write STOPPED happening, and an absence is only verifiable by
# looking. AdminBusinessDetail.tsx already carries this shape; the wizard was
# its unfixed twin.

WIZARD = ROOT / "frontend" / "client" / "src" / "pages" / "AdminOnboardingWizard.tsx"


def wizard_source():
    assert WIZARD.exists(), f"expected {WIZARD} to exist — has it moved?"
    return WIZARD.read_text()


class TestWizardUsesTheSetFeatureFlagRule(unittest.TestCase):
    def test_the_industry_handler_calls_setFeatureFlag(self):
        src = wizard_source()
        handler = re.search(
            r"ONBOARDING_INDUSTRY_PRESETS\[ind\](.*?)\n\s*\}\}", src, re.DOTALL
        )
        self.assertIsNotNone(handler, "the industry onChange handler has moved")
        self.assertIn(
            "setFeatureFlag", handler.group(1),
            "the industry preset must be applied through setFeatureFlag so a "
            "key that matches the plan default is dropped rather than written.",
        )

    def test_the_wholesale_write_is_gone(self):
        # The exact line that pinned an explicit false on every key the preset
        # omitted, writing plan defaults and denials alike.
        src = wizard_source()
        self.assertNotIn("updated[f.key] = presets.includes(f.key)", src)

    def test_it_imports_from_the_canonical_module(self):
        src = wizard_source()
        self.assertIn("@/lib/entitlements", src)
        self.assertIn("setFeatureFlag", src)

    def test_the_preset_keys_are_canonical(self):
        # A preset naming `invoice_chasing` cannot be matched against any plan
        # default, so setFeatureFlag would never strip it and the swap would
        # be a no-op. Canonical keys are what make the rule bite.
        import auth
        src = wizard_source()
        block = re.search(
            r"ONBOARDING_INDUSTRY_PRESETS[^=]*=\s*\{(.*?)\n\};", src, re.DOTALL
        )
        self.assertIsNotNone(block, "ONBOARDING_INDUSTRY_PRESETS has moved")
        used = set(re.findall(r"'([a-z_]+)'", block.group(1)))
        unknown = used - set(auth.CANONICAL_FEATURES) - set(
            re.findall(r"(\w+):", block.group(1))
        )
        self.assertEqual(
            unknown, set(),
            f"non-canonical feature keys in the wizard's presets: {sorted(unknown)}",
        )

    def test_the_feature_catalog_is_canonical(self):
        import auth
        src = wizard_source()
        block = re.search(r"ALL_FEATURE_KEYS[^=]*=\s*\[(.*?)\n\];", src, re.DOTALL)
        self.assertIsNotNone(block, "ALL_FEATURE_KEYS has moved")
        keys = set(re.findall(r"key:\s*'([a-z_]+)'", block.group(1)))
        self.assertEqual(
            keys, set(auth.CANONICAL_FEATURES),
            "the wizard's catalog must be the canonical vocabulary — it is "
            "the list the industry handler and the review screen both "
            "iterate.",
        )

    def test_plan_defaults_come_from_entitlements_not_plan_definitions(self):
        # `plan_definitions` is a SIXTH plan->feature authority, editable at
        # runtime through PUT /v1/admin/onboarding/plans, and nothing keeps it
        # in step with the other copies. It may price a plan; it may not
        # decide entitlement.
        src = wizard_source()
        self.assertIn("planDefaults(", src)
        self.assertNotIn(
            "setPlanFeatureDefaults({ ...plan.features })", src,
            "the wizard must seed its defaults from planDefaults(tier), not "
            "from whatever plan_definitions currently holds.",
        )


class TestWizardReviewScreenBadges(unittest.TestCase):
    """The 'Pending owner OAuth' badge must name only things an OAuth gates."""

    def branch(self):
        src = wizard_source()
        match = re.search(r"\[([^\]]*)\]\.includes\(f\.key\) && enabled", src)
        assert match, "the pending-OAuth branch has moved"
        return set(re.findall(r"'([a-z_]+)'", match.group(1)))

    def test_calendar_booking_is_not_badged_pending_oauth(self):
        # Booking is gated by booking_settings.enabled, not by an OAuth grant.
        # The badge claimed a blocker that does not exist, and an admin reading
        # the review screen would have waited for an owner action that was
        # never coming.
        self.assertNotIn(
            "calendar_booking", self.branch(),
            "calendar_booking does not wait on an OAuth — booking_settings."
            "enabled gates it.",
        )

    def test_the_badged_features_are_the_ones_an_oauth_actually_gates(self):
        self.assertEqual(self.branch(), {"email", "accounting"})

    def test_calendar_sync_is_not_badged_separately(self):
        # Google grants Gmail and Calendar under ONE consent, so calendar_sync
        # is never separately pending. The `email` entry already represents
        # that owner action; badging both would make one action look like two.
        self.assertNotIn("calendar_sync", self.branch())

    def test_every_badged_key_is_canonical(self):
        # `calendar` sat in this list for months and never fired, because it
        # was not a feature key. A non-canonical key here is a dead branch.
        import auth
        self.assertEqual(self.branch() - set(auth.CANONICAL_FEATURES), set())
