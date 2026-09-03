"""
Schema conformance — does the SQL we ship name columns the live DB has?

WHY THIS EXISTS (the incident): `admin_business_api` wrote
`UPDATE businesses SET ..., updated_at = now()` on two endpoints. There is no
`businesses.updated_at`, and there never has been — not in models.py, not in
the 028 baseline, not in any observed dump. Both endpoints (overview save and
the admin activate/pause button) returned 500 on every request from the commit
that introduced them until this test was written. Nothing caught it:

  * `create_all()` creates tables but NEVER columns, so boot was silent.
  * Migration files are not evidence of live state (CLAUDE.md #4).
  * The unit fakes assert hard on SELECT projections but treat any non-SELECT
    as an opaque string — `AdminSession.execute` records the statement and
    returns. A write's columns were never checked against anything.
  * `updated_at = now()` is a literal SQL fragment with no bound parameter, so
    it was also invisible to the `params_for("UPDATE businesses")` assertions.
    The suite's model of a write was "what did you bind", not "what does the
    table have".

So this test asks the one question the fakes cannot: for every column the
backend WRITES, does that column exist in the live schema?

WHAT IT CANNOT DO. It reads SQL as text. Interpolated column lists
(`SELECT {', '.join(ADMIN_COLUMNS)} FROM businesses`) are opaque to it, which
is why `ADMIN_COLUMNS` gets its own check below. It does not see ORM writes,
and it is only ever as current as audits/live-schema-public.txt.
"""
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"
LIVE_SCHEMA = REPO / "audits" / "live-schema-public.txt"

# Tables whose live columns the guard must know. This is a floor, not a list:
# the assertion is `covered >= EXPECTED_COVERED`, so a fuller dump only ever
# adds. Removing a table from the dump fails here rather than quietly
# reducing what is checked.
#
# These are the 39 tables the backend writes, as of the full dump of
# 2026-09-03. The floor is held separately from the `coverage: FULL` header so
# that reverting the header to PARTIAL still cannot quietly un-guard them.
EXPECTED_COVERED = {
    'accounting_categories', 'accounting_connections',
    'accounting_imports', 'accounting_transactions',
    'assistant_conversations', 'assistant_messages',
    'automation_executions', 'automation_rules', 'booking_settings',
    'briefing_snapshots', 'businesses', 'calls', 'email_accounts',
    'email_messages', 'executive_meeting_action_items',
    'executive_meeting_decisions', 'executive_meeting_goals',
    'executive_meeting_messages', 'executive_meeting_settings',
    'executive_meetings', 'financial_summary_cache', 'invoice_line_items',
    'invoices', 'knowledge_base_items', 'onboarding_checklist',
    'onboarding_sessions', 'plan_definitions', 'quote_line_items',
    'quote_settings', 'quotes', 'receptionist_configs',
    'support_articles', 'support_conversations', 'support_messages',
    'tasks', 'whatsapp_configs', 'whatsapp_messages',
    'whatsapp_pending_actions', 'xero_connections',
}

# Ratchet. Tables the backend writes that the dump does not describe. This may
# go DOWN without ceremony; it may only go UP by editing this number, which is
# the point — a new unguarded table is a decision, not an accident. A FULL dump
# must drive it to zero, and `test_full_coverage_leaves_nothing_unguarded`
# enforces that.
UNGUARDED_BUDGET = 0

# Not real writes: SQL built inside a test fixture or asserted on as a string.
SKIP_DIRS = {"tests", ".venv", "migrations", "__pycache__"}


# ── the live schema ──────────────────────────────────────────────────────────

def load_live_schema():
    """Returns (coverage, {table: {column, ...}}).

    Tolerates raw psql output and a downloaded CSV — the Supabase editor gives
    the latter (033-PROD-RUNBOOK STEP 27 moves a .csv), so the leading quote
    and any trailing comma must not defeat the parse.
    """
    if not LIVE_SCHEMA.exists():
        raise AssertionError(
            f"{LIVE_SCHEMA.relative_to(REPO)} is missing. It is the source of "
            f"truth for this guard.\nRegenerate it by running "
            f"scripts/dump-live-schema.sql against project oxblcmwhuwtobdhsfgyi "
            f"(CONFIRM THE PROJECT SELECTOR) and saving the result there."
        )

    text = LIVE_SCHEMA.read_text()

    match = re.search(r"^#\s*coverage:\s*(PARTIAL|FULL)\s*$", text, re.M)
    assert match, (
        f"{LIVE_SCHEMA.name} has no `# coverage: PARTIAL` or `# coverage: FULL` "
        f"header. The guard's strictness depends on it, so it may not be absent."
    )
    coverage = match.group(1)

    schema = {}
    for line in text.splitlines():
        found = re.match(r'^\s*"?col\s+([A-Za-z_]\w*)\.([A-Za-z_]\w*)', line)
        if found:
            schema.setdefault(found.group(1).lower(), set()).add(found.group(2).lower())
    return coverage, schema


# ── reading the SQL we ship ──────────────────────────────────────────────────

def _strip_literals(sql):
    """Remove '...' literals and ::casts before hunting for `column =`.

    `SET notes = 'a=b'` would otherwise yield a phantom column `a`.
    """
    sql = re.sub(r"'(?:[^']|'')*'", "''", sql)
    return re.sub(r"::\s*[A-Za-z_][\w ]*", "", sql)


# `=` but not `>=`, `<=`, `!=`, `==` — an operator is not an assignment.
_ASSIGN = re.compile(r"([A-Za-z_]\w*)\s*(?<![<>!=:])=(?!=)")


def scan_writes(root=None):
    """Every (path, line, kind, table, column) the backend writes.

    Also returns the fragments it could not read, so an f-string column list
    is reported rather than silently dropped.
    """
    root = root or BACKEND
    writes, unparseable = [], []

    paths = [p for p in sorted(root.rglob("*.py"))
             if not SKIP_DIRS & set(p.relative_to(root).parts)]

    for path in paths:
        src = path.read_text()
        # Relative to the repo for a real scan, to the scan root for the
        # self-tests' temp tree — which is not under the repo at all.
        try:
            rel = str(path.relative_to(REPO))
        except ValueError:
            rel = str(path.relative_to(root))

        for m in re.finditer(
            r"\bUPDATE\s+(?:public\.)?([A-Za-z_]\w*)\s+SET\b(.*?)"
            r"(?=\bWHERE\b|\bRETURNING\b|\bFROM\b|\"\"\"|$)",
            src, re.I | re.S,
        ):
            table, frag = m.group(1).lower(), _strip_literals(m.group(2))
            line = src[: m.start()].count("\n") + 1
            for col in _ASSIGN.findall(frag):
                writes.append((rel, line, "UPDATE", table, col.lower()))

        for m in re.finditer(
            r"\bINSERT\s+INTO\s+(?:public\.)?([A-Za-z_]\w*)\s*\(([^)]*)\)",
            src, re.I | re.S,
        ):
            table = m.group(1).lower()
            line = src[: m.start()].count("\n") + 1
            for raw in m.group(2).split(","):
                token = raw.strip()
                if not token:
                    continue
                if re.fullmatch(r"[A-Za-z_]\w*", token):
                    writes.append((rel, line, "INSERT", table, token.lower()))
                else:
                    unparseable.append((rel, line, table, token))

    return writes, unparseable


def written_tables(writes):
    return {table for _, _, _, table, _ in writes}


# ── the guard ────────────────────────────────────────────────────────────────

class LiveSchemaConformance(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.coverage, cls.schema = load_live_schema()
        cls.writes, cls.unparseable = scan_writes()

    def test_every_written_column_exists_in_the_live_schema(self):
        """The incident test. A column we write must be a column that exists."""
        offenders = [
            (path, line, kind, table, col)
            for path, line, kind, table, col in self.writes
            if table in self.schema and col not in self.schema[table]
        ]
        if offenders:
            detail = "\n".join(
                f"  {p}:{ln}  {kind} {t}  ->  {t}.{c} IS NOT IN THE LIVE SCHEMA"
                for p, ln, kind, t, c in sorted(offenders)
            )
            self.fail(
                f"{len(offenders)} write(s) name a column the live database does "
                f"not have.\n{detail}\n\n"
                f"Postgres raises UndefinedColumn, which main.py's catch-all "
                f"exception handler turns into a 500 — so this fails in prod at "
                f"runtime, on every request, and the response body says only "
                f"'Internal Server Error'.\n"
                f"Either remove the write, or add the column with a migration "
                f"(create_all() will NOT add it) and regenerate "
                f"{LIVE_SCHEMA.name}."
            )

    def test_covered_tables_do_not_shrink(self):
        covered = set(self.schema)
        missing = EXPECTED_COVERED - covered
        self.assertFalse(
            missing,
            f"{LIVE_SCHEMA.name} no longer describes {sorted(missing)}. "
            f"Coverage may grow, never shrink — a table dropping out of the "
            f"dump silently stops being checked, which is the failure mode this "
            f"guard exists to prevent.",
        )

    def test_unguarded_table_count_only_ratchets_down(self):
        unguarded = written_tables(self.writes) - set(self.schema)
        self.assertLessEqual(
            len(unguarded), UNGUARDED_BUDGET,
            f"{len(unguarded)} tables are written but not described by "
            f"{LIVE_SCHEMA.name}, over the budget of {UNGUARDED_BUDGET}:\n  "
            + "\n  ".join(sorted(unguarded))
            + f"\n\nPreferred fix: regenerate {LIVE_SCHEMA.name} with "
              f"scripts/dump-live-schema.sql so these become guarded. "
              f"Raising UNGUARDED_BUDGET instead is a deliberate decision to "
              f"leave a table unchecked.",
        )

    def test_full_coverage_leaves_nothing_unguarded(self):
        """PARTIAL is a bootstrap. FULL must mean what it says."""
        if self.coverage != "FULL":
            self.skipTest("live schema dump is PARTIAL — see STEP 24b")
        unguarded = written_tables(self.writes) - set(self.schema)
        self.assertFalse(
            unguarded,
            f"{LIVE_SCHEMA.name} claims `coverage: FULL` but the backend writes "
            f"tables it does not describe:\n  " + "\n  ".join(sorted(unguarded))
            + "\n\nEither the dump is stale, or it was taken with a filter.",
        )
        self.assertEqual(
            UNGUARDED_BUDGET, 0,
            "coverage is FULL, so UNGUARDED_BUDGET must be 0.",
        )

    def test_admin_columns_are_all_live(self):
        """`ADMIN_COLUMNS` is interpolated into SELECT, so the scanner is blind
        to it. It is the admin detail page's whole read; check it directly.

        Parsed from source rather than imported: the repo targets 3.11 and this
        suite must not depend on importing FastAPI to check a tuple of strings.
        """
        src = (BACKEND / "admin_business_api.py").read_text()
        m = re.search(r"^ADMIN_COLUMNS\s*=\s*\((.*?)\)", src, re.M | re.S)
        self.assertIsNotNone(m, "ADMIN_COLUMNS not found in admin_business_api.py")
        columns = re.findall(r'"([A-Za-z_]\w*)"', m.group(1))
        self.assertIn("id", columns, "ADMIN_COLUMNS parsed as nonsense")
        missing = [c for c in columns if c not in self.schema["businesses"]]
        self.assertFalse(
            missing,
            f"ADMIN_COLUMNS selects {missing}, which businesses does not have. "
            f"Every admin business read would 500.",
        )

    def test_unparseable_column_lists_are_reported(self):
        """Not a failure — a receipt. If this ever lists something, the guard
        has a blind spot at that line and the message says where."""
        for rel, line, table, token in self.unparseable:
            print(f"  NOTE: unparseable column {token!r} in {rel}:{line} ({table})")


# ── the guard's own guard ────────────────────────────────────────────────────

class ScannerSelfTest(unittest.TestCase):
    """A regex that matches nothing passes every test above. These fail if the
    scanner has stopped reading SQL, so green cannot mean blind.
    """

    def setUp(self):
        self.writes, _ = scan_writes()

    def test_scanner_finds_a_substantial_number_of_writes(self):
        self.assertGreater(
            len(self.writes), 100,
            f"the scanner found only {len(self.writes)} written columns across "
            f"the backend. It has stopped matching real SQL — every conformance "
            f"test above would pass vacuously.",
        )

    def test_scanner_finds_known_write_sites(self):
        found = {(table, col) for _, _, _, table, col in self.writes}
        for table, col in [
            ("businesses", "plan_tier"),        # admin overview UPDATE
            ("businesses", "is_active"),        # admin activate UPDATE
            ("businesses", "feature_flags"),    # onboarding UPDATE
            ("quote_line_items", "tax_rate"),   # 031/032 columns, INSERT list
            ("quotes", "status"),
        ]:
            self.assertIn(
                (table, col), found,
                f"the scanner no longer sees {table}.{col} being written",
            )

    def test_scanner_catches_a_phantom_column(self):
        """The incident, reconstructed. Both statement shapes, on a temp tree."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "fake_api.py").write_text(
                'a = text("UPDATE businesses SET name = :n, ghost_col = now() '
                'WHERE id = :b")\n'
                'b = text("INSERT INTO businesses (id, phantom_col) '
                'VALUES (:i, :p)")\n'
            )
            writes, _ = scan_writes(root)
            found = {(kind, col) for _, _, kind, _, col in writes}
            self.assertIn(("UPDATE", "ghost_col"), found)
            self.assertIn(("INSERT", "phantom_col"), found)
            self.assertIn(("UPDATE", "name"), found)
            self.assertNotIn(
                ("UPDATE", "id"), found,
                "the WHERE clause was read as an assignment",
            )

    def test_scanner_ignores_operators_and_string_literals(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "fake_api.py").write_text(
                'q = text("UPDATE quotes SET notes = \'a=b\', total = 1 '
                'WHERE v >= 2 AND w != 3")\n'
            )
            writes, _ = scan_writes(root)
            cols = {col for _, _, _, _, col in writes}
            self.assertEqual(
                cols, {"notes", "total"},
                f"expected only the two assigned columns, got {sorted(cols)}",
            )

    def test_scanner_skips_test_files(self):
        self.assertFalse(
            [w for w in self.writes if "tests/" in w[0]],
            "SQL inside test fixtures is being scanned as if it were shipped",
        )


if __name__ == "__main__":
    unittest.main()
