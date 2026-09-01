"""
ENTITLEMENT-SPEC PART D — the READ side.

PART C made `plan_tier` the source of truth and reduced `feature_flags` to
deliberate exceptions. It fixed every WRITE path. It did not touch the
readers, and that is the gap this file closes.

The failure it encodes, concretely: 033 SECTION 7 strips `receptionist: true`
from a `pro` business because the plan already grants it. Every reader that
goes through the resolver is unaffected — `_is_feature_enabled` falls back to
the plan. Every reader that does `flags.get("receptionist", False)` sees a
missing key and returns False. Same column, same business, opposite answer.

    The redundancy was masking the gap. `feature_flags` was doing two jobs —
    recording exceptions AND being the readable state of the world. PART C
    took the second job away. Anything still reading it raw now reads a
    column that is, correctly, empty.

Four readers were wrong and one write path was missing the strip:

  * receptionist_api._require_receptionist_flag  — 403 on nine settings
    endpoints for an entitled business. NOT the phone line: the Twilio
    webhook gates on `receptionist_configs.enabled`, a different column, and
    never loads the business at all. So the receptionist kept answering while
    its owner was locked out of the settings — including `PATCH
    /config/toggle`, the only way to switch it off.
  * onboarding_api's step-skip loop — the worst of them, because it does not
    error. It marks `receptionist_setup` and `accounting_setup` COMPLETE and
    moves on. `accounting` is true on every tier, so post-strip that step is
    skipped for every business the wizard ever runs.
  * receptionist_api's admin overview — reports `receptionist_enabled: false`
    for a business that has it.
  * AdminBusinessDetail's email chip — reads raw, sitting beside three chips
    that resolve properly.
  * PUT /v1/admin/receptionist/{id}/feature-flag — wrote the flag back
    unstripped, which closed a loop with the frontend: after a strip the
    button reads "Enable Feature", and pressing it re-pinned `receptionist:
    true`, undoing SECTION 7 by hand.

And one adjacent bug of the same species from SECTION 6: `brand_color` moved
to its own column, the save endpoint followed it, and `BrandingSettings.tsx`
kept reading the flag. Written here because it is the same mistake — a
reader left behind by a migration — and because bool("#3B82F6") is True, so
while it lived in the flags dict it read as an enabled feature.

The last class is the guard that did not exist. The vocabulary drift test
PARSES the copies of the table that cannot be deduplicated; this one PARSES
the source for reads that bypass the resolver. One protects what the table
says, the other protects how it is asked.
"""
import asyncio
import re
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
FRONTEND_SRC = ROOT / "frontend" / "client" / "src"

ADMIN = {"user_id": "admin-1", "email": "admin@example.com"}


# ── Fakes ───────────────────────────────────────────────────────────────────

class FakeResult:
    def __init__(self, row=None, rows=None):
        self._row = row
        self._rows = rows if rows is not None else []

    def first(self):
        return self._row

    def fetchone(self):
        return self._row

    def all(self):
        return self._rows


class AdminSession:
    """Enough session for the two admin receptionist endpoints."""

    def __init__(self, businesses=(), configs=(), is_admin=True):
        self.businesses = list(businesses)
        self.configs = list(configs)
        self.is_admin = is_admin
        self.added = []
        self.committed = False

    def execute(self, statement, params=None):
        sql = statement.text if hasattr(statement, "text") else str(statement)
        assert "platform_admins" in sql, f"unexpected core-SQL statement: {sql}"
        return FakeResult((1,) if self.is_admin else None)

    def exec(self, statement):
        sql = str(statement)
        if "receptionist_configs" in sql:
            return FakeResult(rows=self.configs,
                              row=self.configs[0] if self.configs else None)
        return FakeResult(rows=self.businesses,
                          row=self.businesses[0] if self.businesses else None)

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.committed = True


def fake_business(plan_tier="pro", flags=None, name="Test Ltd"):
    return SimpleNamespace(
        id="biz-1", name=name, plan_tier=plan_tier, is_active=True,
        feature_flags={} if flags is None else flags,
    )


# ── 1. The settings gate ────────────────────────────────────────────────────

class TestReceptionistGateResolvesAgainstThePlan(unittest.TestCase):
    """receptionist_api._require_receptionist_flag — nine endpoints."""

    def allowed(self, plan_tier, flags):
        import receptionist_api
        try:
            receptionist_api._require_receptionist_flag(
                fake_business(plan_tier, flags))
            return True
        except HTTPException as exc:
            self.assertEqual(exc.status_code, 403)
            return False

    def test_a_pro_business_with_empty_flags_is_allowed(self):
        # THE REGRESSION. This is both live businesses the moment SECTION 7
        # runs: `pro`, `{}`, and entitled to a receptionist by their plan.
        self.assertTrue(self.allowed("pro", {}))

    def test_business_and_beta_tiers_are_allowed_with_empty_flags(self):
        self.assertTrue(self.allowed("business", {}))
        self.assertTrue(self.allowed("beta", {}))

    def test_a_starter_business_is_still_refused(self):
        # The gate must still gate. Starter does not include a receptionist.
        self.assertFalse(self.allowed("starter", {}))

    def test_an_explicit_false_still_denies_a_granting_plan(self):
        # A deliberate denial survives the strip and must be honoured.
        self.assertFalse(self.allowed("pro", {"receptionist": False}))

    def test_an_explicit_true_still_grants_a_denying_plan(self):
        # The goodwill grant. A starter business sold the receptionist alone.
        self.assertTrue(self.allowed("starter", {"receptionist": True}))

    def test_an_unknown_tier_fails_closed(self):
        self.assertFalse(self.allowed("nonsense", {}))
        self.assertFalse(self.allowed(None, {}))

    def test_null_flags_are_treated_as_empty(self):
        self.assertTrue(self.allowed("pro", None))
        self.assertFalse(self.allowed("starter", None))


# ── 2. The onboarding step-skip loop ────────────────────────────────────────

class TestOnboardingStepSkipResolvesAgainstThePlan(unittest.TestCase):
    """onboarding_api — the loop that marks steps complete without asking.

    This one does not 403. It writes `steps_completed[step] = True` and
    advances, so the failure looks exactly like a wizard that has finished.
    """

    def advance(self, from_step, plan_tier="pro", flags=None):
        import onboarding_api
        from test_entitlement_defaults import RecordingSession
        session = RecordingSession(plan_tier=plan_tier)
        session.feature_flags = {} if flags is None else flags
        return asyncio.run(onboarding_api.save_wizard_step(
            business_id="biz-1", step_name=from_step, step_data={},
            auth_ctx=ADMIN, session=session,
        ))

    def test_a_pro_business_with_empty_flags_reaches_receptionist_setup(self):
        # THE REGRESSION, and the one that fails silently. Pre-fix this
        # returns next_step="calendar_setup" with receptionist_setup already
        # ticked off — for a business whose plan includes a receptionist.
        result = self.advance("email_setup", plan_tier="pro")
        self.assertEqual(result["next_step"], "receptionist_setup")
        self.assertNotIn("receptionist_setup",
                         [k for k, v in result["steps_completed"].items() if v])

    def test_accounting_setup_is_reached_on_every_tier(self):
        # `accounting` is true on all four tiers, so post-strip NO business
        # has the key and the step was being skipped for everyone.
        for tier in ("starter", "pro", "business", "beta"):
            result = self.advance("calendar_setup", plan_tier=tier)
            self.assertEqual(
                result["next_step"], "accounting_setup",
                f"{tier} skipped accounting_setup, which every tier includes",
            )

    def test_a_starter_business_still_skips_receptionist_setup(self):
        # The skip is a real feature: don't ask an admin to configure a
        # receptionist the customer has not bought.
        result = self.advance("email_setup", plan_tier="starter")
        self.assertEqual(result["next_step"], "calendar_setup")
        self.assertTrue(result["steps_completed"]["receptionist_setup"])

    def test_an_explicit_denial_skips_it_on_a_granting_plan(self):
        result = self.advance("email_setup", plan_tier="pro",
                              flags={"receptionist": False})
        self.assertEqual(result["next_step"], "calendar_setup")

    def test_a_goodwill_grant_reaches_it_on_a_denying_plan(self):
        result = self.advance("email_setup", plan_tier="starter",
                              flags={"receptionist": True})
        self.assertEqual(result["next_step"], "receptionist_setup")


# ── 3. The admin overview ───────────────────────────────────────────────────

class TestAdminOverviewReportsResolvedEntitlement(unittest.TestCase):

    def overview(self, businesses):
        import receptionist_api
        return asyncio.run(receptionist_api.admin_receptionist_overview(
            auth_ctx=ADMIN, session=AdminSession(businesses=businesses)))

    def test_a_pro_business_with_empty_flags_reads_as_enabled(self):
        rows = self.overview([fake_business("pro", {})])
        self.assertTrue(rows[0]["receptionist_enabled"])

    def test_a_starter_business_reads_as_disabled(self):
        rows = self.overview([fake_business("starter", {})])
        self.assertFalse(rows[0]["receptionist_enabled"])

    def test_an_explicit_denial_reads_as_disabled(self):
        rows = self.overview([fake_business("pro", {"receptionist": False})])
        self.assertFalse(rows[0]["receptionist_enabled"])

    def test_the_flag_and_the_live_line_stay_separate(self):
        # `receptionist_enabled` is the entitlement; `receptionist_live` is
        # receptionist_configs.enabled, which is what the Twilio webhook
        # actually gates on. Collapsing them would hide exactly the state
        # this whole file is about: entitled but not switched on, or — the
        # thing that happened — switched on but reading as unentitled.
        rows = self.overview([fake_business("pro", {})])
        self.assertIn("receptionist_enabled", rows[0])
        self.assertIn("receptionist_live", rows[0])
        self.assertFalse(rows[0]["receptionist_live"])


# ── 4. The fourth write path ────────────────────────────────────────────────

class TestAdminFeatureFlagWriteStrips(unittest.TestCase):
    """PUT /v1/admin/receptionist/{id}/feature-flag.

    PART C fixed three write paths and missed this one. It matters more than
    a stray key: the admin UI computes the button's next value from the flag,
    so after a strip it offers "Enable Feature" and pressing it writes the
    default straight back. The repair path recreated the fault.
    """

    def written_flags(self, plan_tier, existing, enabled):
        import receptionist_api
        biz = fake_business(plan_tier, dict(existing))
        asyncio.run(receptionist_api.admin_toggle_receptionist_flag(
            business_id="biz-1", enabled=enabled,
            auth_ctx=ADMIN, session=AdminSession(businesses=[biz])))
        return biz.feature_flags

    def test_enabling_what_the_plan_already_grants_writes_nothing(self):
        self.assertEqual(self.written_flags("pro", {}, True), {})

    def test_disabling_what_the_plan_denies_writes_nothing(self):
        self.assertEqual(self.written_flags("starter", {}, False), {})

    def test_a_genuine_denial_is_stored(self):
        self.assertEqual(self.written_flags("pro", {}, False),
                         {"receptionist": False})

    def test_a_genuine_grant_is_stored(self):
        self.assertEqual(self.written_flags("starter", {}, True),
                         {"receptionist": True})

    def test_re_enabling_clears_a_previous_denial(self):
        # pro + {"receptionist": False} -> enable -> back to the plan, not to
        # a pinned `true`. This is the loop the admin UI was driving.
        self.assertEqual(
            self.written_flags("pro", {"receptionist": False}, True), {})

    def test_other_keys_are_left_alone(self):
        # It must not become a general-purpose strip of someone else's data.
        result = self.written_flags(
            "pro", {"outreach": True, "industry": "plumbing"}, True)
        self.assertEqual(result, {"outreach": True, "industry": "plumbing"})

    def test_the_response_reports_the_resolved_value(self):
        import receptionist_api
        biz = fake_business("pro", {})
        result = asyncio.run(receptionist_api.admin_toggle_receptionist_flag(
            business_id="biz-1", enabled=True,
            auth_ctx=ADMIN, session=AdminSession(businesses=[biz])))
        self.assertTrue(
            result["receptionist_enabled"],
            "the response must say what the business can now DO. Echoing the "
            "stored flag would report False for a pro business that has just "
            "been enabled, because the correct thing to store is nothing.",
        )


# ── 5. The source guard ─────────────────────────────────────────────────────
#
# What this can and cannot see, stated plainly so nobody trusts it further
# than it goes. It reads source text. It resolves ONE level of aliasing — a
# local bound directly from a `feature_flags` expression — and knows nothing
# about a value passed through a function, stored on an object, or returned
# from an API call. It is a tripwire on the shape of the mistake that was
# actually made five times, not a proof that no raw read exists.

def source_files():
    for path in sorted(BACKEND.rglob("*.py")):
        parts = set(path.parts)
        if "tests" in parts or "migrations" in parts or ".venv" in parts:
            continue
        # auth.py IS the resolver. Reading flags raw is its job.
        if path.name == "auth.py":
            continue
        yield path
    for suffix in ("*.ts", "*.tsx"):
        for path in sorted(FRONTEND_SRC.rglob(suffix)):
            # entitlements.ts is the frontend resolver, same exemption.
            if path.name == "entitlements.ts":
                continue
            yield path


# Names that denote the flags dict itself, before aliasing.
FLAGS_NAMES = ("feature_flags", "featureFlags")

# Mentioning any of these means the read is resolver-aware. `planDefaults`
# also covers `planFeatureDefaults`.
RESOLVERS = ("isFeatureEnabled", "planDefaults", "planFeatureDefaults",
             "_is_feature_enabled", "strip_plan_defaults", "PLAN_FEATURE_DEFAULTS")


def strip_comment_lines(lines):
    """Blank out whole-line comments. Prose about feature_flags is not a read."""
    out = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(("#", "//", "*", "/*")):
            out.append("")
        else:
            out.append(line)
    return out


def flags_expressions(path, lines):
    """Every name in this file that denotes the flags dict.

    Iterated to a fixpoint because the real chain is two hops:
    `raw = biz_row.feature_flags` then `flags = json.loads(raw) ...`. One hop
    would have missed onboarding_api entirely, which is the site that matters
    most — the one that fails without raising.
    """
    names = set(FLAGS_NAMES)
    alias = re.compile(r"^\s*(?:const|let|var)?\s*(\w+)\s*=\s*[^=](.*)$")
    while True:
        found = set()
        for line in lines:
            match = alias.match(line)
            if match and any(name in match.group(2) for name in names):
                found.add(match.group(1))
        if found <= names:
            return names
        names |= found


def raw_reads(path):
    """(line_no, line, why) for each read that bypasses the resolver."""
    import auth
    lines = strip_comment_lines(path.read_text().splitlines())
    names = flags_expressions(path, lines)
    obj = "(?:" + "|".join(sorted(map(re.escape, names), key=len, reverse=True)) + ")"
    canonical = "(?:" + "|".join(auth.CANONICAL_FEATURES) + ")"

    literal = re.compile(
        rf"\b{obj}\s*(?:\?\.)?\[\s*['\"]{canonical}['\"]\s*\]"   # flags['receptionist']
        rf"|\b{obj}\s*\.\s*get\(\s*['\"]{canonical}['\"]"        # flags.get("receptionist"
        rf"|\b{obj}\s*\??\.\s*{canonical}\b"                     # flags?.receptionist
    )
    variable = re.compile(
        rf"\b{obj}\s*(?:\?\.)?\[\s*(?!['\"])"                    # flags[someKey]
        rf"|\b{obj}\s*\.\s*get\(\s*(?!['\"])"                    # flags.get(some_key
    )

    findings = []
    for index, line in enumerate(lines):
        number = index + 1
        match = literal.search(line)
        if match and not re.match(r"\s*=[^=]", line[match.end():]):
            findings.append((number, line.strip(),
                             "reads a canonical feature by name"))
            continue
        match = variable.search(line)
        if not match:
            continue
        if re.match(r"\s*[^=]*?\]\s*=[^=]", line[match.end():]):
            continue  # an assignment target, not a read
        window = "\n".join(lines[max(0, index - 2):index + 3])
        if any(name in window for name in RESOLVERS):
            continue
        findings.append((number, line.strip(),
                         "reads a variable key with no resolver in sight"))
    return findings


class TestNoRawFeatureFlagReads(unittest.TestCase):

    def test_no_source_file_reads_a_canonical_flag_without_the_resolver(self):
        offenders = []
        for path in source_files():
            for number, line, why in raw_reads(path):
                offenders.append(
                    f"{path.relative_to(ROOT)}:{number} — {why}\n      {line}")
        self.assertEqual(
            offenders, [],
            "These read `feature_flags` directly. Under PART C that column "
            "holds only exceptions, so a missing key means 'follow the plan', "
            "NOT 'denied'. Use auth._is_feature_enabled (backend) or "
            "isFeatureEnabled (frontend):\n\n    "
            + "\n\n    ".join(offenders) + "\n",
        )

    def test_the_guard_catches_the_shapes_it_claims_to(self):
        # A test whose only failure mode is a regex that matches nothing is
        # not a test. These are the five real sites, as they were written.
        import tempfile
        samples = {
            'if not flags.get("receptionist", False):': True,
            "receptionistEnabled = featureFlags?.receptionist === true": True,
            "label={`Email: ${business.feature_flags?.email ? 1 : 0}`}": True,
            'x = flags["whatsapp"]': True,
            "if not flags.get(required_feature, False):": True,
            # ...and the shapes that are correct, which it must NOT flag.
            "isFeatureEnabled(b.plan_tier, b.feature_flags, 'receptionist')": False,
            'industry = flags.get("industry", industry)': False,
            'return {"feature_flags": flags}': False,
            "checked={business?.feature_flags?.[k] ?? planDefaults(t)[k]}": False,
        }
        for line, should_flag in samples.items():
            with tempfile.NamedTemporaryFile(
                "w", suffix=".py", delete=False, dir=BACKEND / "tests"
            ) as handle:
                handle.write("flags = business.feature_flags or {}\n" + line + "\n")
                temp = Path(handle.name)
            try:
                flagged = bool(raw_reads(temp))
            finally:
                temp.unlink()
            self.assertEqual(
                flagged, should_flag,
                f"guard {'missed' if should_flag else 'false-flagged'}: {line}",
            )


class TestBrandColorIsNotAnEntitlement(unittest.TestCase):
    """033 SECTION 6, the same species: a reader left behind by a migration."""

    def test_no_source_file_reads_brand_color_out_of_feature_flags(self):
        pattern = re.compile(
            # No whitespace allowed around the accessor: a docstring reading
            # "not feature_flags. brand_color is not an entitlement" is prose,
            # not a read, and /v1/business/brand-color's own docstring says
            # exactly that.
            r"(?:feature_flags|featureFlags)(?:\?\.|\.|\[\s*['\"])brand_color"
        )
        offenders = []
        for path in source_files():
            for index, line in enumerate(strip_comment_lines(
                    path.read_text().splitlines())):
                if pattern.search(line):
                    offenders.append(f"{path.relative_to(ROOT)}:{index + 1}")
        self.assertEqual(
            offenders, [],
            "brand_color lives in the businesses.brand_color COLUMN since 033 "
            "SECTION 6. /v1/business/brand-color writes the column; these read "
            "the flag, so a saved colour never loads back:\n  "
            + "\n  ".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
