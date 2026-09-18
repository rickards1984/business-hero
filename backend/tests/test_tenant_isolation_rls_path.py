"""BH-003 — tenant isolation on the RLS / anon-key path (RC1 P0-9, second half).

The frontend talks to Postgres through PostgREST with the public anon key, as
the `authenticated` role, and Row Level Security is the ONLY gate on that
path (`AGENTS.md` §3.8, §4). `test_tenant_isolation_backend_path.py` covers
the other path, where the backend bypasses RLS and the application's WHERE
clause is the gate. The two are opposite mechanisms and neither proves the
other.

WHAT THIS RUNS AGAINST
  A local Supabase Postgres built by `scripts/rls-local.sh up`: Supabase's
  own image (so `auth.uid()`, the roles and the default privileges are real),
  with this repository's migrations replayed and the pre-baseline ghost
  policies pruned against the 5 July 2026 production policy export
  (`audits/live-policies-2026-07-05.csv`). Read the script header before
  trusting a green run — it says what the replay assumes, including that
  `029_secure_rls_gaps.sql` was applied to production, which the repository
  does not record.

WHAT A GREEN RUN MEANS
  "The policies and grants AS THE MIGRATIONS AND THE JULY CAPTURE DESCRIBE
  THEM isolate the two synthetic tenants on the operations exercised here."
  Not "production isolates". `AGENTS.md` §3.4: migration files are not
  evidence of live state. BH-001's production census closes that gap by
  comparing `scripts/rls-local.sh census` with the six production CSVs.

HOW A TENANT IS IMPERSONATED
  Exactly as PostgREST does it: `SET LOCAL ROLE authenticated` and the JWT
  claims as transaction-local settings. Supabase's `auth.uid()` reads
  `request.jwt.claim.sub` (and newer builds read `request.jwt.claims`), so
  both are set. Every test runs in a transaction that is rolled back.

REFUSES TO RUN against anything that is not loopback. This file writes rows.
"""

import os
import uuid
from contextlib import contextmanager
from urllib.parse import urlparse

import psycopg2
import psycopg2.errors
import pytest

DATABASE_URL = os.getenv("RLS_LOCAL_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="RLS_LOCAL_DATABASE_URL is not set. This suite needs the local "
           "Supabase Postgres: `scripts/rls-local.sh up`, then "
           "`scripts/rls-local.sh test`. It is NOT part of ./check.sh, and a "
           "skip here is a skip, not a pass — see UNCOVERED in "
           "test_tenant_isolation_backend_path.py.",
)

if DATABASE_URL:
    _host = urlparse(DATABASE_URL).hostname
    if _host not in ("127.0.0.1", "localhost", "::1"):
        raise RuntimeError(
            f"REFUSING TO RUN: RLS_LOCAL_DATABASE_URL points at {_host!r}. "
            "This suite inserts and deletes rows and impersonates tenants. "
            "Loopback only. Never staging, never production."
        )

# Two users, two businesses, one membership each. UUIDs fixed so a leak is
# recognisable in an assertion message, and so teardown is exact.
USER_A = "aaaaaaaa-0000-4000-8000-00000000000a"
USER_B = "bbbbbbbb-0000-4000-8000-00000000000b"
BIZ_A = "aaaaaaaa-1111-4111-8111-11111111111a"
BIZ_B = "bbbbbbbb-1111-4111-8111-11111111111b"
EMAIL_A = "bh003-a@example.invalid"
EMAIL_B = "bh003-b@example.invalid"

# Everything below belongs to B. If any of it reaches A, that is the failure.
B_MARKERS = ["B-PRIVATE-BUSINESS", "B-PRIVATE-CATEGORY", "B-PRIVATE-TXN",
             "B-PRIVATE-QUOTE", "B-PRIVATE-TASK", "B-PRIVATE-CUSTOMER", BIZ_B,
             USER_B]


@pytest.fixture(scope="module")
def db():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    with conn.cursor() as cur:
        # `postgres` in the Supabase image is NOT a superuser; it is the
        # table owner with BYPASSRLS — the same posture as the backend's
        # elevated connection in production (AGENTS.md §4). That is what
        # seeding and the structural reads need.
        cur.execute("SELECT current_user, rolbypassrls FROM pg_roles "
                    "WHERE rolname = current_user")
        who, bypass = cur.fetchone()
        assert bypass, f"seeding needs a BYPASSRLS role; connected as {who}"
    _teardown(conn)
    seeded = _seed(conn)
    yield conn, seeded
    _teardown(conn)
    conn.close()


def _seed(conn):
    s = {}
    with conn.cursor() as cur:
        for uid, email in ((USER_A, EMAIL_A), (USER_B, EMAIL_B)):
            cur.execute("INSERT INTO auth.users (id, email, aud, role) "
                        "VALUES (%s, %s, 'authenticated', 'authenticated')",
                        (uid, email))
        cur.execute("INSERT INTO public.businesses (id, name, api_key, plan_tier) "
                    "VALUES (%s, 'A Ltd', %s, 'starter'), "
                    "       (%s, 'B-PRIVATE-BUSINESS', %s, 'pro')",
                    (BIZ_A, f"bh003-{uuid.uuid4()}", BIZ_B, f"bh003-{uuid.uuid4()}"))
        cur.execute("INSERT INTO public.business_members "
                    "(business_id, user_id, role, is_active) "
                    "VALUES (%s, %s, 'owner', true), (%s, %s, 'owner', true)",
                    (BIZ_A, USER_A, BIZ_B, USER_B))
        for key, biz, name in (("cat_a", BIZ_A, "A Office"),
                               ("cat_b", BIZ_B, "B-PRIVATE-CATEGORY")):
            cur.execute("INSERT INTO public.accounting_categories "
                        "(business_id, name, type) VALUES (%s, %s, 'expense') "
                        "RETURNING id", (biz, name))
            s[key] = str(cur.fetchone()[0])
        for key, biz, cat, desc in (("txn_a", BIZ_A, s["cat_a"], "A txn"),
                                    ("txn_b", BIZ_B, s["cat_b"], "B-PRIVATE-TXN")):
            cur.execute("INSERT INTO public.accounting_transactions "
                        "(business_id, category_id, transaction_date, "
                        " description, amount, type) "
                        "VALUES (%s, %s, '2026-09-01', %s, -10, 'expense') "
                        "RETURNING id", (biz, cat, desc))
            s[key] = str(cur.fetchone()[0])
        for key, biz, num, cust in (("quote_a", BIZ_A, "BH003-A-1", "A customer"),
                                    ("quote_b", BIZ_B, "BH003-B-1", "B-PRIVATE-CUSTOMER")):
            cur.execute("INSERT INTO public.quotes "
                        "(business_id, quote_number, customer_name, job_title) "
                        "VALUES (%s, %s, %s, %s) RETURNING id",
                        (biz, num, cust, "B-PRIVATE-QUOTE" if biz == BIZ_B else "A job"))
            s[key] = str(cur.fetchone()[0])
        for key, biz, title in (("task_a", BIZ_A, "A task"),
                                ("task_b", BIZ_B, "B-PRIVATE-TASK")):
            cur.execute("INSERT INTO public.tasks (business_id, title) "
                        "VALUES (%s, %s) RETURNING id", (biz, title))
            s[key] = str(cur.fetchone()[0])
    return s


def _teardown(conn):
    with conn.cursor() as cur:
        # businesses cascades to members, categories, transactions, quotes,
        # tasks where the FK says so; the rest are swept explicitly.
        for table in ("accounting_transactions", "accounting_categories",
                      "quotes", "tasks", "business_members"):
            cur.execute(f"DELETE FROM public.{table} WHERE business_id IN (%s, %s)",
                        (BIZ_A, BIZ_B))
        cur.execute("DELETE FROM public.businesses WHERE id IN (%s, %s)",
                    (BIZ_A, BIZ_B))
        cur.execute("DELETE FROM auth.users WHERE id IN (%s, %s)", (USER_A, USER_B))


@contextmanager
def acting_as(role, user_id=None, email=None):
    """One transaction as PostgREST would run it for this caller. Rolled back."""
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    try:
        cur = conn.cursor()
        if user_id:
            claims = ('{"sub": "%s", "email": "%s", "role": "%s"}'
                      % (user_id, email or "", role))
            cur.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (user_id,))
            cur.execute("SELECT set_config('request.jwt.claim.email', %s, true)", (email or "",))
            cur.execute("SELECT set_config('request.jwt.claims', %s, true)", (claims,))
        cur.execute(f"SET LOCAL ROLE {role}")
        yield cur
    finally:
        conn.rollback()
        conn.close()


def as_member_of_a():
    return acting_as("authenticated", USER_A, EMAIL_A)


def as_member_of_b():
    return acting_as("authenticated", USER_B, EMAIL_B)


def rows(cur, sql, params=None):
    cur.execute(sql, params)
    return cur.fetchall()


def assert_no_b_data(payload, what):
    blob = repr(payload)
    for marker in B_MARKERS:
        assert marker not in blob, (
            f"TENANT ISOLATION FAILURE on the RLS path in {what}: business B's "
            f"{marker!r} reached a caller authenticated as business A.\n"
            f"Rows: {blob[:600]}")


# ── 1. Structural invariants, read as the owner ─────────────────────────────

def test_the_harness_is_talking_to_the_expected_database(db):
    conn, _ = db
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM pg_roles WHERE rolname IN "
                    "('anon','authenticated','service_role')")
        assert cur.fetchone()[0] == 3, "not a Supabase image"
        cur.execute("SELECT auth.uid()")
        assert cur.fetchone()[0] is None
        cur.execute("SELECT to_regprocedure('public.is_business_member(uuid, uuid)')")
        assert cur.fetchone()[0] is not None, "is_business_member() is missing"


def test_every_public_table_is_either_rls_on_or_unreachable_by_client_roles(db):
    """The invariant behind `AGENTS.md` §3.3 and §3.8, stated precisely.

    Default privileges in this image grant anon and authenticated ALL on every
    new public table, so "RLS off" means "publicly reachable" UNLESS the
    grants were revoked. Both states are acceptable; RLS off WITH grants is
    the create_all() trap, live.
    """
    conn, _ = db
    with conn.cursor() as cur:
        cur.execute("""
            SELECT c.relname
              FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'public' AND c.relkind = 'r'
               AND NOT c.relrowsecurity
               AND EXISTS (SELECT 1 FROM information_schema.role_table_grants g
                            WHERE g.table_schema = 'public' AND g.table_name = c.relname
                              AND g.grantee IN ('anon', 'authenticated'))
             ORDER BY 1""")
        exposed = [r[0] for r in cur.fetchall()]
    assert exposed == [], (
        f"RLS OFF with client-role grants — publicly reachable: {exposed}")


def test_every_rls_table_reachable_by_authenticated_has_a_policy(db):
    conn, _ = db
    with conn.cursor() as cur:
        cur.execute("""
            SELECT c.relname
              FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relrowsecurity
               AND NOT EXISTS (SELECT 1 FROM pg_policy p WHERE p.polrelid = c.oid)
               AND EXISTS (SELECT 1 FROM information_schema.role_table_grants g
                            WHERE g.table_schema = 'public' AND g.table_name = c.relname
                              AND g.grantee = 'authenticated')
             ORDER BY 1""")
        silent = [r[0] for r in cur.fetchall()]
    # RLS on + no policy = deny-all on the client path. Not a leak, but it
    # means no frontend code can be relying on the table. Listed, not hidden.
    assert silent == [], f"RLS on, no policy, still granted: {silent}"


# The only permissive policies allowed to be unconditionally true for a
# client role. Each is a catalogue table with no tenant column, or a
# published-only read. Anything else appearing here is a finding.
ALLOWED_UNSCOPED_POLICIES = {
    ("accounting_providers", "accounting_providers_public_read"),
    ("automation_rule_templates", "automation_rule_templates_member_read"),
    ("plan_definitions", "plan_definitions_public_read"),
}


def test_no_tenant_table_has_an_unscoped_permissive_policy(db):
    """A `USING (true)` on a table with a business_id column satisfies a
    policy count while isolating nothing, and one permissive `true` defeats
    every restrictive policy on the table. The July 2026 audit found two
    (SEC-02, SEC-03); the replay's prune step removes their ghosts, and
    this test is what notices if they ever come back."""
    conn, _ = db
    with conn.cursor() as cur:
        cur.execute("""
            SELECT c.relname, p.polname
              FROM pg_policy p
              JOIN pg_class c ON c.oid = p.polrelid
              JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'public' AND p.polpermissive
               AND pg_get_expr(p.polqual, p.polrelid) = 'true'
               AND (p.polroles = '{0}'::oid[]
                    OR p.polroles && ARRAY(SELECT oid FROM pg_roles
                                            WHERE rolname IN ('anon','authenticated')))
             ORDER BY 1, 2""")
        unscoped = set(cur.fetchall())
    assert unscoped == ALLOWED_UNSCOPED_POLICIES, (
        f"unexpected unconditional policies: {unscoped - ALLOWED_UNSCOPED_POLICIES}; "
        f"missing expected: {ALLOWED_UNSCOPED_POLICIES - unscoped}")


def test_every_policy_on_a_tenant_table_references_the_membership(db):
    """Mike's question, answered for the migration-defined state: does every
    policy on a table carrying `business_id` gate on membership? The
    accepted forms are is_business_member(), a business_members subquery,
    or is_platform_admin() / platform_admins. The exceptions are listed by
    name so a new one cannot slip in as 'probably fine'."""
    conn, _ = db
    accepted = ("is_business_member", "business_members", "is_platform_admin",
                "platform_admins")
    # The membership table itself cannot be gated on membership without
    # recursion; its policies gate on the caller's own identity instead.
    # `users_view_own` also shows an invitee their pending row by email —
    # by design, and the disclosure is one business_id and a role.
    self_scoped = {("business_members", "users_view_own"),
                   ("business_members", "users_link_self")}
    with conn.cursor() as cur:
        cur.execute("""
            SELECT c.relname, p.polname,
                   coalesce(pg_get_expr(p.polqual, p.polrelid), '') || ' ' ||
                   coalesce(pg_get_expr(p.polwithcheck, p.polrelid), '')
              FROM pg_policy p
              JOIN pg_class c ON c.oid = p.polrelid
              JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'public'
               AND EXISTS (SELECT 1 FROM information_schema.columns k
                            WHERE k.table_schema = 'public' AND k.table_name = c.relname
                              AND k.column_name = 'business_id')
             ORDER BY 1, 2""")
        offenders = {(t, p) for t, p, expr in cur.fetchall()
                     if not any(a in expr for a in accepted)}
    assert offenders == self_scoped, (
        f"policies on tenant tables not gated on membership: {offenders - self_scoped}; "
        f"expected self-scoped exceptions missing: {self_scoped - offenders}")


def test_no_view_bypasses_the_rls_of_its_base_tables(db):
    """A view runs with its OWNER's privileges unless `security_invoker` is
    on. A view owned by postgres over `calls`, granted SELECT to anon by the
    default ACL, hands cross-tenant aggregates to the anon key however good
    the policies on `calls` are. BH-001's Q1 (`relkind = 'r'`) cannot see
    views; the 3 Sep 2026 dump shows two in production that no migration
    creates (`receptionist_call_stats`, `support_stats`). Vacuous here —
    the replay makes no views — and that is the point: the query is ready
    for the production census."""
    conn, _ = db
    with conn.cursor() as cur:
        cur.execute("""
            SELECT c.relname
              FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'public' AND c.relkind IN ('v', 'm')
               AND NOT coalesce('security_invoker=on' = ANY(c.reloptions)
                                OR 'security_invoker=true' = ANY(c.reloptions), false)
               AND EXISTS (SELECT 1 FROM information_schema.role_table_grants g
                            WHERE g.table_schema = 'public' AND g.table_name = c.relname
                              AND g.grantee IN ('anon', 'authenticated'))
             ORDER BY 1""")
        leaky = [r[0] for r in cur.fetchall()]
    assert leaky == [], f"views reachable by client roles that run as their owner: {leaky}"


# ── 2. Behaviour, as a member of business A ────────────────────────────────

def test_a_sees_exactly_its_own_business(db):
    _, s = db
    with as_member_of_a() as cur:
        got = rows(cur, "SELECT id::text, name FROM public.businesses ORDER BY name")
    assert got == [(BIZ_A, "A Ltd")]


@pytest.mark.parametrize("table,own_key,own_col", [
    ("accounting_categories", "cat_a", "name"),
    ("accounting_transactions", "txn_a", "description"),
    ("quotes", "quote_a", "customer_name"),
    ("tasks", "task_a", "title"),
])
def test_a_reads_exactly_its_own_rows(db, table, own_key, own_col):
    _, s = db
    with as_member_of_a() as cur:
        got = rows(cur, f"SELECT id::text, business_id::text, {own_col} "
                        f"FROM public.{table} WHERE business_id IN (%s, %s)",
                   (BIZ_A, BIZ_B))
    assert_no_b_data(got, f"SELECT FROM {table}")
    assert [(r[0], r[1]) for r in got] == [(s[own_key], BIZ_A)], (
        f"{table}: expected exactly A's row, got {got}")


def test_a_sees_only_its_own_membership(db):
    with as_member_of_a() as cur:
        got = rows(cur, "SELECT business_id::text, user_id::text "
                        "FROM public.business_members "
                        "WHERE business_id IN (%s, %s)", (BIZ_A, BIZ_B))
    assert got == [(BIZ_A, USER_A)]


def test_a_cannot_update_bs_rows(db):
    _, s = db
    with as_member_of_a() as cur:
        cur.execute("UPDATE public.businesses SET name = 'pwned' WHERE id = %s", (BIZ_B,))
        assert cur.rowcount == 0, "A updated B's business row"
        cur.execute("UPDATE public.accounting_transactions SET description = 'pwned' "
                    "WHERE id = %s", (s["txn_b"],))
        assert cur.rowcount == 0, "A updated B's transaction"
        cur.execute("UPDATE public.quotes SET customer_name = 'pwned' WHERE id = %s",
                    (s["quote_b"],))
        assert cur.rowcount == 0, "A updated B's quote"


def test_a_cannot_delete_bs_rows(db):
    _, s = db
    with as_member_of_a() as cur:
        cur.execute("DELETE FROM public.accounting_transactions WHERE id = %s", (s["txn_b"],))
        assert cur.rowcount == 0
        cur.execute("DELETE FROM public.tasks WHERE id = %s", (s["task_b"],))
        assert cur.rowcount == 0
        cur.execute("DELETE FROM public.businesses WHERE id = %s", (BIZ_B,))
        assert cur.rowcount == 0


@pytest.mark.parametrize("table,columns,values", [
    ("accounting_categories", "(business_id, name, type)", "(%s, 'x', 'expense')"),
    ("accounting_transactions",
     "(business_id, transaction_date, description, amount, type)",
     "(%s, '2026-09-01', 'x', -1, 'expense')"),
    ("quotes", "(business_id, quote_number, customer_name, job_title)",
     "(%s, 'BH003-X', 'x', 'x')"),
    ("tasks", "(business_id, title)", "(%s, 'x')"),
])
def test_a_cannot_insert_into_bs_scope(db, table, columns, values):
    """WITH CHECK is the write-side gate. A NULL with_check on a member
    policy would let A write a row it can never read back — into B."""
    with as_member_of_a() as cur:
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            cur.execute(f"INSERT INTO public.{table} {columns} VALUES {values}", (BIZ_B,))


def test_a_can_still_write_into_its_own_scope(db):
    """The positive control: refusing everything is not isolation."""
    with as_member_of_a() as cur:
        cur.execute("INSERT INTO public.accounting_transactions "
                    "(business_id, transaction_date, description, amount, type) "
                    "VALUES (%s, '2026-09-02', 'A can write', -1, 'expense') "
                    "RETURNING id", (BIZ_A,))
        assert cur.fetchone() is not None
        cur.execute("UPDATE public.tasks SET title = 'A can edit' WHERE business_id = %s",
                    (BIZ_A,))
        assert cur.rowcount == 1


def test_the_reverse_direction_holds(db):
    _, s = db
    with as_member_of_b() as cur:
        got = rows(cur, "SELECT id::text FROM public.businesses")
        assert got == [(BIZ_B,)]
        got = rows(cur, "SELECT id::text FROM public.accounting_transactions "
                        "WHERE business_id IN (%s, %s)", (BIZ_A, BIZ_B))
        assert got == [(s["txn_b"],)]
        cur.execute("UPDATE public.businesses SET name = 'pwned' WHERE id = %s", (BIZ_A,))
        assert cur.rowcount == 0


def test_a_member_of_no_business_sees_nothing(db):
    stranger = "cccccccc-0000-4000-8000-00000000000c"
    with acting_as("authenticated", stranger, "nobody@example.invalid") as cur:
        for table in ("businesses", "business_members", "accounting_transactions",
                      "quotes", "tasks"):
            assert rows(cur, f"SELECT 1 FROM public.{table} LIMIT 1") == [], table


def test_anon_sees_nothing(db):
    with acting_as("anon") as cur:
        for table in ("businesses", "business_members", "accounting_transactions",
                      "quotes", "tasks"):
            try:
                got = rows(cur, f"SELECT 1 FROM public.{table} LIMIT 1")
            except psycopg2.errors.InsufficientPrivilege:
                cur.connection.rollback()
                cur.execute("SET LOCAL ROLE anon")
                continue    # no grant at all is the stronger refusal
            assert got == [], f"anon read {table}"


# ── 3. The RED one: entitlement self-service through the client path ───────
#
# RC1 P0-3 / 030b Release 2. `033` narrowed `authenticated`'s UPDATE on
# `businesses` from table-level to a COLUMN LIST — and that list still
# contains plan_tier, is_active, feature_flags, limits and
# subscription_status. With `biz_update_if_owner` permitting an owner to
# update their own row, an owner can raise their own tier from the browser.
# Column grants do not appear in role_table_grants (BH-001 Q6), only in
# column_privileges (Q4).

ENTITLEMENT_COLUMNS = ("plan_tier", "is_active", "feature_flags", "limits",
                       "subscription_status")


def test_which_entitlement_columns_authenticated_may_update(db):
    """Not an assertion of policy — a RECORD of the migration-defined grant,
    so that the runbook for 030b Release 2 starts from evidence."""
    conn, _ = db
    with conn.cursor() as cur:
        cur.execute("""
            SELECT column_name FROM information_schema.column_privileges
             WHERE table_schema = 'public' AND table_name = 'businesses'
               AND grantee = 'authenticated' AND privilege_type = 'UPDATE'
             ORDER BY 1""")
        granted = {r[0] for r in cur.fetchall()}
    print(f"\nauthenticated may UPDATE businesses columns: {sorted(granted)}")
    # Both possible states are legitimate at different times; what is not
    # legitimate is the test silently agreeing with whichever it finds.
    assert granted, "no column grant at all — 033's column list is gone; " \
                    "if that is 030b Release 2, update this test to assert emptiness"


@pytest.mark.xfail(
    strict=True,
    reason="RC1 P0-3, 030b Release 2 not yet applied: 033's column-level "
           "UPDATE grant plus biz_update_if_owner lets an owner set their own "
           "plan_tier from the browser. Remove this marker in the commit that "
           "lands Release 2's revoke.",
)
@pytest.mark.parametrize("column,value", [
    ("plan_tier", "'business'"),
    ("is_active", "true"),
    ("feature_flags", "'{\"receptionist\": true}'::jsonb"),
    ("subscription_status", "'active'"),
])
def test_an_owner_cannot_raise_their_own_entitlement(db, column, value):
    with as_member_of_a() as cur:
        try:
            cur.execute(f"UPDATE public.businesses SET {column} = {value} "
                        f"WHERE id = %s", (BIZ_A,))
        except psycopg2.errors.InsufficientPrivilege:
            return    # refused by grant — the desired outcome
        assert cur.rowcount == 0, (
            f"an owner updated their own businesses.{column} through the "
            f"client path — entitlement is self-service")


def test_an_owner_cannot_insert_a_business_from_the_client(db):
    """Today: no INSERT policy on businesses for non-admins, so RLS refuses
    even though the table grant exists. Passes now; 030b Release 2's revoke
    of INSERT makes it belt-and-braces. If this ever fails, business
    creation from the browser has been opened."""
    with as_member_of_a() as cur:
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            cur.execute("INSERT INTO public.businesses (name, api_key) "
                        "VALUES ('from-browser', %s)", (f"bh003-{uuid.uuid4()}",))
