"""Rehearse migration 036 on STAGING only. Refuses any other database.

Reads STAGING_DB_URL from .env.staging (or the file STAGING_ENV_FILE names)
and never prints it."""
import os
import sys

import psycopg2

env_file = os.environ.get("STAGING_ENV_FILE", ".env.staging")
env = dict(l.split("=", 1) for l in open(env_file).read().splitlines() if "=" in l and not l.startswith("#"))
url = env.get("STAGING_DB_URL", "").strip().strip('"')
if "gzcrsrqmygublveuzqyg" not in url or "oxblcmwhuwtobdhsfgyi" in url:
    sys.exit("REFUSING: STAGING_DB_URL is not the staging project")
sql = open("backend/migrations/036_chase_replies.sql").read()
section1 = sql[sql.index("BEGIN;"):sql.index("COMMIT;") + len("COMMIT;")]
rollback = "BEGIN;\nDROP TABLE IF EXISTS public.chase_replies;\nCOMMIT;"
assert "-- DROP TABLE IF EXISTS public.chase_replies;" in sql, "rollback in the file has changed"

conn = psycopg2.connect(url)
conn.autocommit = True
cur = conn.cursor()


def q(s, params=None):
    cur.execute(s, params)
    return cur.fetchall()


def exists():
    return q("select to_regclass('public.chase_replies') is not null")[0][0]


def snapshot():
    if not exists():
        return {"exists": False}
    return {
        "exists": True,
        "columns": q("select column_name, data_type, is_nullable from information_schema.columns "
                     "where table_schema='public' and table_name='chase_replies' order by 1"),
        "rls": q("select relrowsecurity, relforcerowsecurity from pg_class "
                 "where oid='public.chase_replies'::regclass"),
        "policies": q("select policyname, cmd, permissive, roles::text, qual is not null, "
                      "with_check is not null from pg_policies where schemaname='public' "
                      "and tablename='chase_replies' order by 1"),
        "grants": q("select grantee, privilege_type from information_schema.role_table_grants "
                    "where table_schema='public' and table_name='chase_replies' "
                    "and grantee in ('anon','authenticated','service_role') order by 1,2"),
        "constraints": q("select conname from pg_constraint "
                         "where conrelid='public.chase_replies'::regclass order by 1"),
        "indexes": q("select indexname from pg_indexes where schemaname='public' "
                     "and tablename='chase_replies' order by 1"),
        "rows": q("select count(*) from public.chase_replies")[0][0],
    }


def must_fail(label, statement, params=None):
    cur.execute("BEGIN")
    try:
        cur.execute(statement, params)
        outcome = "DID NOT FAIL"
    except psycopg2.Error as exc:
        outcome = f"failed as required ({exc.pgcode} {exc.diag.constraint_name or exc.diag.message_primary})"
    cur.execute("ROLLBACK")
    log.append((label, outcome))


log = []
biz = q("select id from public.businesses limit 1")[0][0]
before = snapshot()
log.append(("before: chase_replies exists", before["exists"]))

cur.execute(section1)
log.append(("SECTION 1 applied", "ok"))
mid = snapshot()
log.append(("columns (12 expected)", f"{len(mid['columns'])}: {mid['columns']}"))
log.append(("RLS (enabled, forced)", mid["rls"]))
log.append(("policies", mid["policies"]))
log.append(("grants", mid["grants"]))
log.append(("anon has nothing", not any(g[0] == "anon" for g in mid["grants"])))
log.append(("authenticated has SELECT only",
            [g[1] for g in mid["grants"] if g[0] == "authenticated"] == ["SELECT"]))
log.append(("constraints", [c[0] for c in mid["constraints"]]))
log.append(("indexes", [i[0] for i in mid["indexes"]]))
log.append(("rows (0 expected)", mid["rows"]))

must_fail("CHECK category rejects refund_them",
          "insert into public.chase_replies (business_id, customer_email, category) "
          "values (%s, 'x@example.invalid', 'refund_them')", (biz,))
must_fail("CHECK status rejects deleted",
          "insert into public.chase_replies (business_id, customer_email, category, status) "
          "values (%s, 'x@example.invalid', 'other', 'deleted')", (biz,))
must_fail("CHECK invoice_ids must be a list",
          "insert into public.chase_replies (business_id, customer_email, category, invoice_ids) "
          "values (%s, 'x@example.invalid', 'other', '{}'::jsonb)", (biz,))
must_fail("authenticated role cannot INSERT",
          "set local role authenticated; insert into public.chase_replies "
          "(business_id, customer_email, category) values (%s, 'x@example.invalid', 'other')", (biz,))
must_fail("authenticated role cannot UPDATE",
          "set local role authenticated; update public.chase_replies set status='resumed'")

cur.execute("BEGIN")
cur.execute("insert into public.chase_replies (business_id, customer_email, category) "
            "values (%s, 'x@example.invalid', 'paid') returning id", (biz,))
log.append(("a valid row inserts (rolled back)", cur.fetchone() is not None))
cur.execute("ROLLBACK")

cur.execute(section1)
log.append(("SECTION 1 applied again (idempotent), snapshot unchanged", snapshot() == mid))

cur.execute(rollback)
log.append(("ROLLBACK 1 run; table gone (== before)", snapshot() == before))

cur.execute(section1)
log.append(("SECTION 1 re-applied and LEFT APPLIED (staging models prod-after-036)",
            snapshot() == mid))

for k, v in log:
    print(f"- {k}: {v}")
