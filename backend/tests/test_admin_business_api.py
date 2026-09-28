"""
030b — the four admin business endpoints.

Target surface (does not exist yet):

    backend/admin_business_api.py
        router                                    APIRouter
        create_business(data, auth_ctx, session)              A3
        get_business_admin(business_id, auth_ctx, session)     A4
        update_business_overview(business_id, data, auth_ctx, session)  A1
        set_business_active(business_id, data, auth_ctx, session)       A2

WHY THIS EXISTS: four frontend sites write `businesses` directly through
supabase-js, gated only by `biz_update_if_owner` — a column-blind RLS policy
behind a table-wide UPDATE grant. Any owner can set their own `plan_tier`,
`is_active` and `feature_flags` from the browser. These endpoints are what
makes revoking that grant possible.

RULINGS ENCODED HERE (audits/030B-SPEC.md, 20 Aug 2026):
  * feature_flags — option (a): structure-only validation. REVISED by BH-007
    (28 Sep 2026): the named exception became "canonical feature keys must be
    boolean, other keys are metadata and may hold any scalar". See
    TestFeatureFlagsValidation for why the named list was the wrong shape.
  * limits — kept, accepted opaquely, structure-only
  * api_key — server-side `secrets.token_urlsafe(32)` only, never accepted
  * is_active — explicit state, never a toggle
"""
import asyncio
import re
import unittest

from fastapi import HTTPException
from sqlalchemy.sql.elements import TextClause

CANONICAL_TIERS = ("starter", "pro", "business", "beta")
ADMIN = {"user_id": "admin-1", "email": "admin@example.com"}


def api():
    """Imported per-test so each test fails on its own, not at collection."""
    import admin_business_api
    return admin_business_api


# ── Fakes ────────────────────────────────────────────────────────────────────

class FakeRow:
    def __init__(self, columns, values):
        self._columns = list(columns)
        self._values = list(values)
        for name, value in zip(columns, values):
            setattr(self, name, value)

    def __getitem__(self, index):
        return self._values[index]

    def keys(self):
        return list(self._columns)


class FakeResult:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row

    def first(self):
        return self._row


BUSINESS = {
    "id": "biz-1",
    "name": "Multi Skilled Contractors LTD",
    "timezone": "Europe/London",
    "plan_tier": "pro",
    "is_active": True,
    "trial_ends_at": None,
    "feature_flags": {"email": True, "brand_color": "#3B82F6"},
    "limits": {},
    "subscription_status": "active",
    "current_period_end": None,
    "api_key": "sk_" + "x" * 43,
}


class AdminSession:
    """
    Projects the columns the SQL actually asked for and refuses to invent one
    it does not hold.

    It also refuses a read that selects `api_key` on any path except the
    creation path — the credential must not leak through a read endpoint, and
    a fake that quietly served it would let that regression through.
    """

    def __init__(self, business=None, allow_api_key_read=False):
        self.business = dict(business) if business is not None else dict(BUSINESS)
        self.allow_api_key_read = allow_api_key_read
        self.statements = []
        self.committed = False

    @staticmethod
    def _norm(statement):
        assert isinstance(statement, TextClause), (
            f"expected a TextClause, got {type(statement)}"
        )
        return " ".join(statement.text.split())

    def execute(self, statement, params=None):
        sql = self._norm(statement)
        self.statements.append((sql, params))
        upper = sql.upper()

        if upper.startswith("SELECT"):
            clause = re.search(r"SELECT\s+(.*?)\s+FROM", sql, re.I | re.S)
            assert clause, f"unparseable SELECT: {sql}"
            raw = clause.group(1).strip()
            assert raw != "*", (
                "admin reads must name their columns explicitly — `SELECT *` is "
                "what puts api_key within reach of a read endpoint"
            )
            columns = [c.strip().split()[-1] for c in raw.split(",")]
            if not self.allow_api_key_read:
                assert "api_key" not in columns, (
                    f"a read endpoint selected api_key: {sql}"
                )
            # A missing row is not a malformed query. Postgres runs the query
            # and returns nothing, so model that rather than asserting — the
            # shape checks above still apply, only the projection is skipped.
            if not self.business:
                return FakeResult(None)
            missing = [c for c in columns if c not in self.business]
            assert not missing, f"query selected {missing}, not held by this fake: {sql}"
            return FakeResult(FakeRow(columns, [self.business[c] for c in columns]))

        return FakeResult(None)

    def commit(self):
        self.committed = True

    def rollback(self):
        pass

    # -- assertions ---------------------------------------------------------
    def params_for(self, fragment):
        matches = [p for sql, p in self.statements if fragment.upper() in sql.upper()]
        assert matches, (
            f"no statement matching {fragment!r}. Statements were:\n  "
            + "\n  ".join(sql for sql, _ in self.statements)
        )
        return matches[0]

    def wrote(self):
        return [sql for sql, _ in self.statements
                if not sql.upper().startswith("SELECT")]


def overview(session, **fields):
    return asyncio.run(api().update_business_overview(
        business_id="biz-1", data=dict(fields), auth_ctx=ADMIN, session=session))


def set_active(session, **fields):
    return asyncio.run(api().set_business_active(
        business_id="biz-1", data=dict(fields), auth_ctx=ADMIN, session=session))


def create(session, **fields):
    payload = {"name": "A Business", "timezone": "Europe/London"}
    payload.update(fields)
    return asyncio.run(api().create_business(
        data=payload, auth_ctx=ADMIN, session=session))


def expect_400(case, fn, *args, **kwargs):
    with case.assertRaises(HTTPException) as ctx:
        fn(*args, **kwargs)
    case.assertEqual(ctx.exception.status_code, 400,
                     f"expected 400, got {ctx.exception.status_code}")
    return ctx.exception.detail


# ── Auth ─────────────────────────────────────────────────────────────────────

class TestEveryRouteIsAdminGated(unittest.TestCase):
    """
    Criterion: all four endpoints under Depends(get_platform_admin_context).

    Asserted against the router rather than each handler, so an endpoint added
    later without the dependency also fails.
    """

    def test_router_exposes_four_routes(self):
        routes = [r for r in api().router.routes if getattr(r, "methods", None)]
        self.assertGreaterEqual(len(routes), 4, "expected at least four routes")

    def test_every_route_requires_platform_admin(self):
        from auth import get_platform_admin_context
        routes = [r for r in api().router.routes if getattr(r, "methods", None)]
        self.assertTrue(routes, "no routes on the router — nothing was asserted")
        for route in routes:
            with self.subTest(path=route.path):
                deps = [getattr(d, "dependency", None) for d in route.dependant.dependencies]
                sub = [d.call for d in route.dependant.dependencies]
                self.assertTrue(
                    get_platform_admin_context in deps or get_platform_admin_context in sub,
                    f"{route.path} is not gated by get_platform_admin_context",
                )

    def test_no_route_uses_the_master_key(self):
        from auth import verify_master_key
        routes = [r for r in api().router.routes if getattr(r, "methods", None)]
        self.assertTrue(routes, "no routes on the router — nothing was asserted")
        for route in routes:
            with self.subTest(path=route.path):
                sub = [d.call for d in route.dependant.dependencies]
                self.assertNotIn(verify_master_key, sub,
                                 "the admin surface settles on one scheme (PART C)")


# ── Shared validation ────────────────────────────────────────────────────────

class TestPlanTierValidation(unittest.TestCase):
    """Criterion: validated against the canonical set; unknown is a 400; no remap."""

    def test_every_canonical_tier_is_accepted(self):
        update = api().update_business_overview      # resolve outside the loop
        for tier in CANONICAL_TIERS:
            with self.subTest(tier=tier):
                session = AdminSession()
                asyncio.run(update(business_id="biz-1", data={"plan_tier": tier},
                                   auth_ctx=ADMIN, session=session))
                self.assertEqual(session.params_for("UPDATE businesses")["plan_tier"], tier)

    def test_unknown_tier_is_rejected(self):
        detail = expect_400(self, overview, AdminSession(), plan_tier="enterprise")
        self.assertIn("enterprise", detail, f"error does not name the value: {detail}")

    def test_error_names_the_permitted_set(self):
        detail = expect_400(self, overview, AdminSession(), plan_tier="enterprise")
        for tier in CANONICAL_TIERS:
            self.assertIn(tier, detail, f"error does not name {tier}: {detail}")

    def test_premium_is_rejected_not_silently_remapped(self):
        # backend/main.py:836 rewrites ("premium","elite") -> "business".
        # That is the pattern this endpoint must not reproduce.
        session = AdminSession()
        expect_400(self, overview, session, plan_tier="premium")
        self.assertEqual(session.wrote(), [], "a rejected tier still wrote")

    def test_elite_is_rejected_not_silently_remapped(self):
        session = AdminSession()
        expect_400(self, overview, session, plan_tier="elite")
        self.assertEqual(session.wrote(), [], "a rejected tier still wrote")

    def test_paused_is_rejected(self):
        # Removed from the vocabulary by ENTITLEMENT-SPEC DECISION 3.
        expect_400(self, overview, AdminSession(), plan_tier="paused")

    def test_tier_is_case_sensitive_or_normalised_but_never_guessed(self):
        # "Pro" must either be accepted as "pro" or rejected. What it must not
        # do is store "Pro", which no lookup matches.
        session = AdminSession()
        try:
            overview(session, plan_tier="Pro")
        except HTTPException:
            return
        self.assertEqual(session.params_for("UPDATE businesses")["plan_tier"], "pro")


class TestFeatureFlagsValidation(unittest.TestCase):
    """
    RULE (BH-007, 28 Sep 2026, superseding 030B-SPEC's named exception):

      * a key in the canonical feature vocabulary MUST be a boolean — those are
        what `auth._is_feature_enabled` consults to grant access;
      * any other key is metadata and may hold any SCALAR;
      * nested objects and arrays are refused for every key.

    Enforced by `auth.validate_feature_flags`, which every writer of the column
    uses. This class tests it through the admin endpoints; the onboarding
    writer has its own regression test in test_onboarding_flags.py.
    """

    def test_flat_booleans_are_accepted(self):
        session = AdminSession()
        overview(session, feature_flags={"email": True, "receptionist": False})
        self.assertEqual(
            session.params_for("UPDATE businesses")["feature_flags"],
            {"email": True, "receptionist": False},
        )

    def test_empty_object_is_accepted(self):
        session = AdminSession()
        overview(session, feature_flags={})
        self.assertEqual(session.params_for("UPDATE businesses")["feature_flags"], {})

    def test_nested_object_is_rejected(self):
        expect_400(self, overview, AdminSession(),
                   feature_flags={"email": {"enabled": True}})

    def test_array_value_is_rejected(self):
        expect_400(self, overview, AdminSession(), feature_flags={"email": [True]})

    def test_non_object_is_rejected(self):
        api()   # resolve outside the loop: subTest swallows an ImportError
        for bad in ([], "email", 3, True):
            with self.subTest(bad=bad):
                expect_400(self, overview, AdminSession(), feature_flags=bad)

    def test_brand_color_string_is_permitted(self):
        # Still permitted, now because `brand_color` is not a canonical feature
        # key rather than because it is on a named list.
        session = AdminSession()
        overview(session, feature_flags={"email": True, "brand_color": "#3B82F6"})
        self.assertEqual(
            session.params_for("UPDATE businesses")["feature_flags"]["brand_color"],
            "#3B82F6",
        )

    # ── BH-007, 28 Sep 2026 ──────────────────────────────────────────────────
    #
    # THIS CLASS PREVIOUSLY ASSERTED THE BUG. The test that stood here was:
    #
    #     def test_the_exemption_covers_brand_color_and_nothing_else(self):
    #         # If any other key may hold a string, the exemption has become a
    #         # loophole and tightening it after 033 will silently break callers.
    #         expect_400(self, overview, AdminSession(),
    #                    feature_flags={"industry": "construction"})
    #
    # It required `industry: "construction"` to be REJECTED — and `industry` is
    # a live string the onboarding wizard writes and `quoting_api.py` reads to
    # build the AI quoting prompt. So a business that had been through the
    # wizard could not be saved through the admin editor at all: the UI posts
    # the whole flags object back, so changing `plan_tier` alone returned
    # 400 `feature_flags.industry must be true or false`. Reported from the ZZ
    # test business.
    #
    # The reasoning in that comment was sound about `brand_color`'s lifecycle
    # and simply did not account for a second, permanent string key. Removed
    # rather than softened, and replaced by tests for the rule that puts
    # strictness where it protects something.

    def test_the_wizard_s_industry_string_is_accepted(self):
        """THE REGRESSION. This is the 400 an admin hit in production."""
        session = AdminSession()
        overview(session, feature_flags={"email": True, "industry": "construction"})
        self.assertEqual(
            session.params_for("UPDATE businesses")["feature_flags"]["industry"],
            "construction",
        )

    def test_a_business_carrying_both_metadata_strings_can_be_saved(self):
        """The realistic shape of a live row: canonical booleans plus the two
        metadata strings. An admin must be able to save this, because otherwise
        they cannot onboard a business or resolve its support tickets."""
        session = AdminSession()
        overview(session, feature_flags={
            "receptionist": True, "email": True, "aria_voice": False,
            "brand_color": "#3B82F6", "industry": "construction",
        })
        saved = session.params_for("UPDATE businesses")["feature_flags"]
        self.assertEqual(saved["industry"], "construction")
        self.assertEqual(saved["brand_color"], "#3B82F6")
        self.assertIs(saved["receptionist"], True)
        self.assertIs(saved["aria_voice"], False)

    def test_every_canonical_feature_key_must_be_a_boolean(self):
        """Strictness where it matters. These keys are what
        `auth._is_feature_enabled` consults to grant access, and
        `bool("false")` is True — so a string here would grant a feature by
        accident. Parametrised over the whole vocabulary so a new feature is
        covered the day it is added."""
        module = api()
        for key in sorted(module.PLAN_FEATURE_VOCABULARY):
            for bad in ("true", "false", "yes", 1, 0, 1.5, None):
                with self.subTest(key=key, bad=bad):
                    expect_400(self, overview, AdminSession(),
                               feature_flags={key: bad})

    def test_the_vocabulary_is_derived_from_auth_not_copied(self):
        """ENTITLEMENT-SPEC PART B: auth holds THE ONLY COPY IN PYTHON. If this
        validator kept its own list the two could drift, and a new feature
        would be unenforced here until someone noticed."""
        module = api()
        from auth import PLAN_FEATURE_DEFAULTS
        self.assertEqual(module.PLAN_FEATURE_VOCABULARY,
                         frozenset(PLAN_FEATURE_DEFAULTS["business"]))
        self.assertIn("receptionist", module.PLAN_FEATURE_VOCABULARY)
        self.assertNotIn("industry", module.PLAN_FEATURE_VOCABULARY)
        self.assertNotIn("brand_color", module.PLAN_FEATURE_VOCABULARY)

    def test_metadata_may_hold_ANY_scalar_not_just_a_string(self):
        """Codex's review: the first version of these tests only ever put
        STRINGS in metadata keys, so a validator that accepted `str` and `bool`
        and rejected numbers or null would have passed them while violating the
        stated "any scalar" rule."""
        for value in ("a string", 42, 3.5, True, False, None):
            with self.subTest(value=value):
                session = AdminSession()
                overview(session, feature_flags={"some_metadata": value})
                self.assertEqual(
                    session.params_for("UPDATE businesses")["feature_flags"],
                    {"some_metadata": value},
                )

    def test_every_canonical_key_accepts_BOTH_booleans(self):
        """The other half of the vocabulary check. The rejection test covers
        every key, but acceptance was only exercised for a few — so a validator
        that rejected `False` (or both values) for an unexercised key could have
        passed."""
        module = api()
        for key in sorted(module.PLAN_FEATURE_VOCABULARY):
            for value in (True, False):
                with self.subTest(key=key, value=value):
                    session = AdminSession()
                    overview(session, feature_flags={key: value})
                    self.assertIs(
                        session.params_for("UPDATE businesses")["feature_flags"][key],
                        value,
                    )

    def test_create_preserves_metadata_and_strips_only_plan_defaults(self):
        """The create path runs `strip_plan_defaults` after validating, so
        metadata must survive that too — otherwise a wizard-created business
        would lose its `industry` on the first admin save."""
        session = AdminSession()
        create(session, name="ZZ Test", plan_tier="starter", feature_flags={
            "industry": "construction",
            "brand_color": "#3B82F6",
            "receptionist": True,      # contradicts starter's default -> kept
            "quoting": True,           # restates starter's default -> stripped
        })
        saved = session.params_for("INSERT INTO businesses")["feature_flags"]
        self.assertEqual(saved["industry"], "construction")
        self.assertEqual(saved["brand_color"], "#3B82F6")
        self.assertIs(saved["receptionist"], True)
        self.assertNotIn("quoting", saved,
                         "a flag that merely restates the plan default was stored")

    def test_an_undocumented_metadata_key_is_accepted_not_refused(self):
        """The failure this change exists to prevent: a key nobody anticipated
        must not stop an admin editing a business. It is inert —
        `_is_feature_enabled` looks up the exact canonical key — so accepting it
        grants nothing. It is logged, not rejected."""
        session = AdminSession()
        overview(session, feature_flags={"some_future_key": "a value", "email": True})
        self.assertEqual(
            session.params_for("UPDATE businesses")["feature_flags"]["some_future_key"],
            "a value",
        )

    def test_a_typo_of_a_canonical_key_is_accepted_but_grants_nothing(self):
        """The cost of the permissive rule, stated rather than hidden.

        `receptionis` (sic) is accepted as metadata and does not grant the real
        feature, because the gate looks up `receptionist` exactly. The blast
        radius is a junk key, versus a blocked admin under the old rule.

        BE PRECISE ABOUT WHY IT IS HARMLESS, because the first version of this
        docstring said "inert by construction" and that is not true:
        `_is_feature_enabled` does NOT restrict itself to the vocabulary, so
        asking it for `receptionis` on `{"receptionis": True}` returns True. It
        is inert because no caller passes a non-canonical name — inert by
        convention. If a caller ever takes a feature name from user input, that
        stops being true.
        """
        session = AdminSession()
        overview(session, feature_flags={"receptionis": True})
        saved = session.params_for("UPDATE businesses")["feature_flags"]
        self.assertIs(saved["receptionis"], True)

        from auth import _is_feature_enabled
        from types import SimpleNamespace
        business = SimpleNamespace(plan_tier="starter", feature_flags=saved)
        self.assertFalse(_is_feature_enabled(business, "receptionist"),
                         "a typo'd key granted the real feature")

    def test_structure_is_still_enforced_for_every_key(self):
        """Metadata may be any SCALAR — not an object or an array. The column
        stays flat whatever the key is called."""
        for bad in ({"hex": "#000"}, ["#000"]):
            with self.subTest(bad=bad):
                expect_400(self, overview, AdminSession(),
                           feature_flags={"brand_color": bad})
                expect_400(self, overview, AdminSession(),
                           feature_flags={"industry": bad})
                expect_400(self, overview, AdminSession(),
                           feature_flags={"anything_at_all": bad})


class TestLimitsValidation(unittest.TestCase):
    """
    Criterion (RULING): kept, accepted opaquely, structure-only. Must be a flat
    JSON object; values unconstrained; keys unchecked.
    """

    def test_flat_object_of_numbers_is_accepted(self):
        session = AdminSession()
        overview(session, limits={"voice_minutes": 350, "seats": 6})
        self.assertEqual(
            session.params_for("UPDATE businesses")["limits"],
            {"voice_minutes": 350, "seats": 6},
        )

    def test_values_are_not_constrained(self):
        # Deliberately permissive pending 033's usage_meters.
        session = AdminSession()
        overview(session, limits={"note": "unmetered", "seats": 6, "beta": True})
        self.assertEqual(session.params_for("UPDATE businesses")["limits"]["note"],
                         "unmetered")

    def test_empty_object_is_accepted(self):
        session = AdminSession()
        overview(session, limits={})
        self.assertEqual(session.params_for("UPDATE businesses")["limits"], {})

    def test_nested_object_is_rejected(self):
        expect_400(self, overview, AdminSession(), limits={"voice": {"minutes": 350}})

    def test_non_object_is_rejected(self):
        api()   # resolve outside the loop: subTest swallows an ImportError
        for bad in ([], "none", 7):
            with self.subTest(bad=bad):
                expect_400(self, overview, AdminSession(), limits=bad)


class TestUnknownFieldsRejected(unittest.TestCase):
    """Criterion: any other key in the body is a 400, not silently ignored."""

    def test_unknown_key_is_rejected(self):
        detail = expect_400(self, overview, AdminSession(), nickname="Bob")
        self.assertIn("nickname", detail, f"error does not name the key: {detail}")

    def test_api_key_in_the_body_is_rejected(self):
        detail = expect_400(self, overview, AdminSession(), api_key="sk_forged")
        self.assertIn("api_key", detail)

    def test_subscription_status_cannot_be_set_by_an_admin(self):
        # Stripe owns this column. ENTITLEMENT-SPEC DECISION 3 makes it the
        # driver of access, so a hand-edit here would fake a paid state.
        expect_400(self, overview, AdminSession(), subscription_status="active")

    def test_nothing_is_written_when_a_field_is_rejected(self):
        session = AdminSession()
        expect_400(self, overview, session, plan_tier="pro", nickname="Bob")
        self.assertEqual(session.wrote(), [],
                         "a rejected body still produced a write")


# ── A1 — update overview ─────────────────────────────────────────────────────

class TestUpdateOverview(unittest.TestCase):
    """Criterion: accepts the five fields; omitted means unchanged."""

    FIELDS = ("plan_tier", "is_active", "trial_ends_at", "feature_flags", "limits")

    def test_accepts_all_five_fields_together(self):
        session = AdminSession()
        overview(session, plan_tier="business", is_active=False,
                 trial_ends_at="2026-12-01T00:00:00Z",
                 feature_flags={"email": True}, limits={"seats": 6})
        params = session.params_for("UPDATE businesses")
        for field in self.FIELDS:
            with self.subTest(field=field):
                self.assertIn(field, params)

    def test_an_omitted_field_is_not_written(self):
        session = AdminSession()
        overview(session, plan_tier="pro")
        params = session.params_for("UPDATE businesses")
        self.assertIn("plan_tier", params)
        for field in ("is_active", "feature_flags", "limits"):
            with self.subTest(field=field):
                self.assertNotIn(field, params,
                                 f"{field} was omitted but still written")

    def test_explicit_null_clears_trial_ends_at(self):
        session = AdminSession()
        overview(session, trial_ends_at=None)
        params = session.params_for("UPDATE businesses")
        self.assertIn("trial_ends_at", params,
                      "explicit null must be distinguishable from omission")
        self.assertIsNone(params["trial_ends_at"])

    def test_an_empty_body_writes_nothing(self):
        session = AdminSession()
        overview(session)
        self.assertEqual(session.wrote(), [])

    def test_returns_the_updated_row(self):
        session = AdminSession()
        result = overview(session, plan_tier="business")
        self.assertIsInstance(result, dict)
        self.assertEqual(result.get("plan_tier"), "business")

    def test_the_returned_row_never_contains_api_key(self):
        session = AdminSession()
        result = overview(session, plan_tier="pro")
        self.assertNotIn("api_key", result)


# ── A2 — explicit active state ───────────────────────────────────────────────

class TestSetActiveIsStateNotToggle(unittest.TestCase):
    """
    Criterion: accepts an explicit boolean, never a toggle.

    Both frontend sites today send `!business.is_active` — an inversion of a
    value held in client memory. Two admins on one business, or one stale tab,
    and the toggle flips the wrong way with no error. The endpoint must say
    what it wants to be true.
    """

    def test_setting_false_writes_false(self):
        session = AdminSession(business=dict(BUSINESS, is_active=True))
        set_active(session, is_active=False)
        self.assertIs(session.params_for("UPDATE businesses")["is_active"], False)

    def test_setting_true_writes_true(self):
        session = AdminSession(business=dict(BUSINESS, is_active=False))
        set_active(session, is_active=True)
        self.assertIs(session.params_for("UPDATE businesses")["is_active"], True)

    def test_it_does_not_invert_the_stored_value(self):
        # THE POINT. Asking for True on a business already True must write
        # True — an implementation that inverts would write False here.
        session = AdminSession(business=dict(BUSINESS, is_active=True))
        set_active(session, is_active=True)
        self.assertIs(session.params_for("UPDATE businesses")["is_active"], True)

    def test_setting_the_current_value_is_a_success_not_an_error(self):
        session = AdminSession(business=dict(BUSINESS, is_active=True))
        result = set_active(session, is_active=True)      # must not raise
        self.assertIs(result.get("is_active"), True)

    def test_repeating_the_call_is_idempotent(self):
        session = AdminSession(business=dict(BUSINESS, is_active=False))
        first = set_active(session, is_active=True)
        second = set_active(session, is_active=True)
        self.assertEqual(first.get("is_active"), second.get("is_active"))

    def test_a_missing_is_active_is_rejected(self):
        # No default. A body that does not say cannot be guessed.
        expect_400(self, set_active, AdminSession())

    def test_a_non_boolean_is_rejected(self):
        api()   # resolve outside the loop: subTest swallows an ImportError
        for bad in ("true", 1, None, "yes"):
            with self.subTest(bad=bad):
                expect_400(self, set_active, AdminSession(), is_active=bad)

    def test_returns_the_resulting_state(self):
        session = AdminSession(business=dict(BUSINESS, is_active=True))
        result = set_active(session, is_active=False)
        self.assertIs(result.get("is_active"), False)

    def test_it_writes_only_is_active(self):
        session = AdminSession()
        set_active(session, is_active=False)
        params = session.params_for("UPDATE businesses")
        self.assertEqual(
            {k for k in params if k not in ("bid", "business_id", "id")},
            {"is_active"},
        )


# ── A3 — create ──────────────────────────────────────────────────────────────

class TestCreateBusiness(unittest.TestCase):
    """Criterion: name required; api_key server-side only."""

    def test_name_is_required(self):
        expect_400(self, lambda s: asyncio.run(api().create_business(
            data={"timezone": "Europe/London"}, auth_ctx=ADMIN, session=s)),
            AdminSession(allow_api_key_read=True))

    def test_whitespace_only_name_is_rejected(self):
        expect_400(self, create, AdminSession(allow_api_key_read=True), name="   ")

    def test_name_is_trimmed(self):
        session = AdminSession(allow_api_key_read=True)
        create(session, name="  A Business  ")
        self.assertEqual(session.params_for("INSERT INTO businesses")["name"],
                         "A Business")

    def test_api_key_is_generated_server_side(self):
        session = AdminSession(allow_api_key_read=True)
        create(session)
        key = session.params_for("INSERT INTO businesses")["api_key"]
        self.assertTrue(key.startswith("sk_"), f"unexpected prefix: {key!r}")
        self.assertEqual(len(key), 46,
                         f"expected sk_ + 43 chars from token_urlsafe(32), got {len(key)}")

    def test_two_creates_produce_different_keys(self):
        first = AdminSession(allow_api_key_read=True)
        second = AdminSession(allow_api_key_read=True)
        create(first)
        create(second)
        self.assertNotEqual(first.params_for("INSERT INTO businesses")["api_key"],
                            second.params_for("INSERT INTO businesses")["api_key"])

    def test_an_api_key_in_the_body_is_rejected(self):
        session = AdminSession(allow_api_key_read=True)
        detail = expect_400(self, create, session, api_key="bh_forged")
        self.assertIn("api_key", detail)
        self.assertEqual(session.wrote(), [])

    def test_a_bh_prefixed_key_is_never_produced(self):
        session = AdminSession(allow_api_key_read=True)
        create(session)
        self.assertFalse(
            session.params_for("INSERT INTO businesses")["api_key"].startswith("bh_"),
            "bh_ is the client-side Math.random() format being retired",
        )

    def test_plan_tier_is_validated_on_create_too(self):
        expect_400(self, create, AdminSession(allow_api_key_read=True),
                   plan_tier="enterprise")

    def test_the_created_row_is_returned_with_its_key(self):
        # The only moment api_key is displayable.
        session = AdminSession(allow_api_key_read=True)
        result = create(session)
        self.assertIn("api_key", result)
        self.assertTrue(result["api_key"].startswith("sk_"))


# ── A4 — admin read ──────────────────────────────────────────────────────────

class TestGetBusinessAdmin(unittest.TestCase):
    """Criterion: the ten columns the detail page reads, and never api_key."""

    EXPECTED = {"id", "name", "timezone", "plan_tier", "is_active",
                "trial_ends_at", "feature_flags", "limits",
                "subscription_status", "current_period_end"}

    def test_returns_the_ten_columns(self):
        session = AdminSession()
        result = asyncio.run(api().get_business_admin(
            business_id="biz-1", auth_ctx=ADMIN, session=session))
        self.assertTrue(self.EXPECTED.issubset(result.keys()),
                        f"missing: {self.EXPECTED - set(result.keys())}")

    def test_never_returns_api_key(self):
        session = AdminSession()
        result = asyncio.run(api().get_business_admin(
            business_id="biz-1", auth_ctx=ADMIN, session=session))
        self.assertNotIn("api_key", result)

    def test_it_does_not_select_star(self):
        # AdminSession asserts this on the way through; naming it here means a
        # failure reads as the criterion rather than as a fake.
        session = AdminSession()
        asyncio.run(api().get_business_admin(
            business_id="biz-1", auth_ctx=ADMIN, session=session))
        selects = [sql for sql, _ in session.statements if sql.upper().startswith("SELECT")]
        self.assertTrue(selects, "no read was issued")
        for sql in selects:
            self.assertNotIn("SELECT *", sql.upper())

    def test_a_missing_business_is_404_not_500(self):
        session = AdminSession()
        session.business = {}
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(api().get_business_admin(
                business_id="nope", auth_ctx=ADMIN, session=session))
        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
