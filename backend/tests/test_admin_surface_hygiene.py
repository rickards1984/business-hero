"""
030b — the things that must STOP existing.

The endpoints in test_admin_business_api.py are only half of 030b. The other
half is removal: the direct supabase-js writes, the client-side key generator,
the `select('*')` reads and the silent tier remap. Those are absences, and an
absence is only verifiable by looking.

These are source-level assertions on purpose. A literal is gone or it is not,
and no behavioural test can prove the second write path was deleted rather
than merely unused.

Grant and policy changes (PART E) are NOT tested here — they are verified
against the live database by the migration's own VERIFY blocks, per 031/032.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend" / "client" / "src"
BACKEND = ROOT / "backend"

WRITE_SITES = [
    ("pages/AdminBusinessDetail.tsx", "handleSaveOverview"),
    ("pages/AdminBusinessDetail.tsx", "handleToggleActive"),
    ("pages/AdminDashboard.tsx", "handleToggleActive"),
    ("pages/AdminDashboard.tsx", "handleCreateBusiness"),
]

READ_SITES = [
    "pages/BusinessDashboard.tsx",
    "pages/BrandingSettings.tsx",
    "pages/AdminBusinessDetail.tsx",
]


def tsx(relative):
    path = FRONTEND / relative
    assert path.exists(), f"expected {path} to exist — has it moved?"
    return path.read_text()


def frontend_files():
    files = sorted(list(FRONTEND.rglob("*.tsx")) + list(FRONTEND.rglob("*.ts")))
    assert files, "found no frontend sources — the glob is wrong, not the code"
    return files


class TestNoDirectWritesToBusinesses(unittest.TestCase):
    """
    Criterion (PART E): after 030b there are zero frontend writes to
    `businesses`, which is what makes REVOKE INSERT, UPDATE possible.
    """

    def _business_ops(self, text, op):
        # `.from('businesses')` and the operation are on separate lines in all
        # four sites, so match across the intervening whitespace.
        return re.findall(
            r"from\(['\"]businesses['\"]\)\s*\.\s*" + op + r"\s*\(",
            text,
        )

    def test_no_update_anywhere_in_the_frontend(self):
        offenders = []
        for path in frontend_files():
            if self._business_ops(path.read_text(), "update"):
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [],
                         f"direct UPDATE on businesses remains in: {offenders}")

    def test_no_insert_anywhere_in_the_frontend(self):
        # AdminDashboard's create is an INSERT, not an UPDATE. Revoking UPDATE
        # alone would leave business creation — including plan_tier and
        # feature_flags on the new row — open from the browser.
        offenders = []
        for path in frontend_files():
            if self._business_ops(path.read_text(), "insert"):
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [],
                         f"direct INSERT on businesses remains in: {offenders}")

    def test_no_upsert_or_delete_either(self):
        offenders = []
        for path in frontend_files():
            text = path.read_text()
            if self._business_ops(text, "upsert") or self._business_ops(text, "delete"):
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [], f"other direct writes remain in: {offenders}")


def handler_body(relative, handler):
    """Extract ONE handler's body, bounded at the next handler.

    A fixed-size window is not safe here: `handleSaveOverview`'s neighbour
    begins 980 characters in, so a 2000-character window picks up the next
    function's `apiRequest` call and reports a pass the code has not earned.
    """
    text = tsx(relative)
    start = text.index(f"const {handler}")
    following = re.search(r"\n  const \w+", text[start + 10:])
    end = start + 10 + following.start() if following else len(text)
    body = text[start:end]
    assert len(body) > 40, f"{handler} body looks empty — extractor is wrong"
    return body


class TestWriteSitesGoThroughTheBackend(unittest.TestCase):
    """
    The four handlers must call the API, not supabase directly.

    Offenders are accumulated and asserted once rather than looped through
    subTest: a subTest failure leaves the parent labelled PASSED, which is
    exactly the ambiguity these tests exist to remove.
    """

    def test_each_handler_still_exists(self):
        # If a handler were renamed, the assertions below would pass vacuously
        # by finding nothing to check.
        missing = [f"{rel}:{h}" for rel, h in WRITE_SITES if h not in tsx(rel)]
        self.assertEqual(missing, [],
                         f"handlers not found — renamed? update WRITE_SITES: {missing}")

    def test_each_handler_calls_apirequest(self):
        offenders = [f"{rel}:{h}" for rel, h in WRITE_SITES
                     if "apiRequest" not in handler_body(rel, h)]
        self.assertEqual(offenders, [],
                         f"these handlers do not call apiRequest: {offenders}")

    def test_no_handler_still_references_supabase_from_businesses(self):
        offenders = [f"{rel}:{h}" for rel, h in WRITE_SITES
                     if "from('businesses')" in handler_body(rel, h)]
        self.assertEqual(offenders, [],
                         f"these handlers still write via supabase: {offenders}")


class TestNoSelectStar(unittest.TestCase):
    """
    Criterion (PART B): the three `select('*')` reads are narrowed. This is what
    keeps `api_key` out of reach of a page that never wanted it.
    """

    def test_no_select_star_on_businesses_anywhere(self):
        offenders = []
        for path in frontend_files():
            if re.search(r"from\(['\"]businesses['\"]\)\s*\.\s*select\(\s*['\"]\*['\"]",
                         path.read_text()):
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [],
                         f"select('*') on businesses remains in: {offenders}")

    def test_each_named_read_site_still_selects_from_businesses(self):
        # Guards the test above against passing because the read was deleted
        # rather than narrowed.
        gone = [rel for rel in READ_SITES
                if "from('businesses')" not in tsx(rel) and "apiRequest" not in tsx(rel)]
        self.assertEqual(gone, [], f"these pages no longer read a business: {gone}")

    def test_every_read_site_names_its_columns_and_excludes_api_key(self):
        """
        Two conditions, because either alone is satisfiable the wrong way.

        Checking only for the literal `api_key` passes trivially while the
        selects are still `'*'` — a wildcard does not contain the string, but
        it does return the column. So require an explicit list AND require
        api_key to be absent from it.
        """
        offenders = []
        for relative in READ_SITES:
            text = tsx(relative)
            # Match the select that FOLLOWS `.from('businesses')`, not every
            # select in a file that happens to mention the table. The previous
            # filter tested `text` rather than `x`, so reads on `calls` and
            # `business_members` — other tables, out of 030b's scope — were
            # swept in and reported as unnarrowed.
            business_selects = re.findall(
                r"from\(['\"]businesses['\"]\)\s*\.\s*select\(\s*['\"]([^'\"]+)['\"]",
                text,
            )
            if not business_selects:
                offenders.append(f"{relative}: no select list found")
                continue
            for selected in business_selects:
                if selected.strip() == "*":
                    offenders.append(f"{relative}: still select('*')")
                elif "api_key" in selected:
                    offenders.append(f"{relative}: selects api_key")
        self.assertEqual(offenders, [], f"read sites not narrowed: {offenders}")


class TestClientSideKeyGeneratorIsGone(unittest.TestCase):
    """
    Criterion (PART D): `api_key` is generated server-side with
    secrets.token_urlsafe(32) and never in the browser.

    The retired generator used Math.random(), which is not a CSPRNG, to mint a
    credential that `get_current_business` accepts as bearer auth.
    """

    def test_generateapikey_is_deleted(self):
        self.assertNotIn("generateApiKey", tsx("pages/AdminDashboard.tsx"))

    def test_no_frontend_file_mints_an_api_key(self):
        offenders = []
        for path in frontend_files():
            text = path.read_text()
            if "generateApiKey" in text or re.search(r"['\"]bh_['\"]\s*[+;]", text):
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [], f"api_key minting remains in: {offenders}")

    def test_backend_uses_token_urlsafe_for_api_keys(self):
        """
        Formatting-robust. The source is whitespace-normalised before matching,
        so an assignment split across lines reads the same as a single line —
        the previous line-anchored regex would have missed a perfectly valid
        multi-line implementation and reported a failure the code did not earn.

        Matches both the assignment form (`api_key = ...`) and the dict-literal
        form (`"api_key": ...`), and asserts the entropy argument as well as the
        call, so a low-entropy argument cannot satisfy it.
        """
        sources = [p for p in BACKEND.rglob("*.py") if "__pycache__" not in str(p)]
        self.assertTrue(sources, "found no backend sources")
        pattern = re.compile(
            r"""api_key["']?\s*[=:]\s*[^,;]{0,200}?token_urlsafe\(\s*(\d+)\s*\)"""
        )
        found = []
        for path in sources:
            flat = " ".join(path.read_text().split())
            for entropy in pattern.findall(flat):
                found.append((path, int(entropy)))
        self.assertTrue(
            found, "no backend file mints api_key with secrets.token_urlsafe")
        weak = [f"{p.relative_to(ROOT)}: token_urlsafe({n})" for p, n in found if n < 32]
        self.assertEqual(weak, [], f"api_key minted with weak entropy: {weak}")

    def test_no_backend_file_uses_a_weak_key_length(self):
        # Prod holds an sk_ + 14-char format from an undocumented second
        # generator. Whatever produced it must not still be reachable.
        offenders = []
        for path in [p for p in BACKEND.rglob("*.py") if "__pycache__" not in str(p)]:
            for match in re.findall(r"token_urlsafe\(\s*(\d+)\s*\)", path.read_text()):
                if int(match) < 32:
                    offenders.append(f"{path.relative_to(ROOT)}: token_urlsafe({match})")
        self.assertEqual(offenders, [],
                         f"weak key generation remains: {offenders}")


class TestNoSilentTierRemap(unittest.TestCase):
    """
    Criterion (shared validation): an unrecognised plan_tier is a 400, never a
    silent rewrite. `backend/main.py:836` currently maps ("premium","elite")
    to "business" without telling anyone.
    """

    def test_the_premium_elite_remap_is_removed(self):
        source = (BACKEND / "main.py").read_text()
        self.assertNotIn('("premium", "elite")', source)

    def test_no_backend_file_rewrites_a_plan_tier_silently(self):
        offenders = []
        for path in [p for p in BACKEND.rglob("*.py")
                     if "__pycache__" not in str(p) and "tests" not in str(p)]:
            for line in path.read_text().splitlines():
                if re.search(r"plan_tier\s*=\s*['\"](business|pro|starter|beta)['\"]", line):
                    offenders.append(f"{path.relative_to(ROOT)}: {line.strip()}")
        self.assertEqual(offenders, [],
                         f"plan_tier assigned a literal: {offenders}")


class TestOneAuthScheme(unittest.TestCase):
    """
    Criterion (PART C): the admin surface settles on
    get_platform_admin_context. verify_master_key gates two endpoints today,
    both of which 030b replaces.
    """

    def test_no_admin_endpoint_uses_verify_master_key(self):
        source = (BACKEND / "main.py").read_text()
        offenders = [line.strip() for line in source.splitlines()
                     if "verify_master_key" in line and "import" not in line]
        self.assertEqual(offenders, [],
                         f"verify_master_key still gates: {offenders}")


if __name__ == "__main__":
    unittest.main()
