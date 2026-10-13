"""Rehearse migration 035 on STAGING only. Refuses any other database."""
import sys

import psycopg2

env = dict(l.split("=", 1) for l in open(".env.staging").read().splitlines() if "=" in l and not l.startswith("#"))
url = env.get("STAGING_DB_URL", "").strip().strip('"')
if "gzcrsrqmygublveuzqyg" not in url or "oxblcmwhuwtobdhsfgyi" in url:
    sys.exit("REFUSING: STAGING_DB_URL is not the staging project")
sql = open("backend/migrations/035_aria_actions.sql").read()
section1 = sql[sql.index("BEGIN;"):sql.index("COMMIT;") + len("COMMIT;")]
rollback = "BEGIN;\nDROP TABLE IF EXISTS public.aria_actions;\nCOMMIT;"
assert "-- DROP TABLE IF EXISTS public.aria_actions;" in sql, "rollback in the file has changed"

conn = psycopg2.connect(url)
conn.autocommit = True
cur = conn.cursor()


def q(s, params=None):
    cur.execute(s, params)
    return cur.fetchall()


def exists():
    return q("select to_regclass('public.aria_actions') is not null")[0][0]


def snapshot():
    if not exists():
        return {"exists": False}
    return {
        "exists": True,
        "columns": q("select column_name, data_type, is_nullable from information_schema.columns "
                     "where table_schema='public' and table_name='aria_actions' order by 1"),
        "rls": q("select relrowsecurity, relforcerowsecurity from pg_class "
                 "where oid='public.aria_actions'::regclass"),
        "policies": q("select policyname, cmd, permissive, roles::text, qual is not null, "
                      "with_check is not null from pg_policies where schemaname='public' "
                      "and tablename='aria_actions' order by 1"),
        "grants": q("select grantee, privilege_type from information_schema.role_table_grants "
                    "where table_schema='public' and table_name='aria_actions' "
                    "and grantee in ('anon','authenticated','service_role') order by 1,2"),
        "constraints": q("select conname from pg_constraint "
                         "where conrelid='public.aria_actions'::regclass order by 1"),
        "indexes": q("select indexname from pg_indexes where schemaname='public' "
                     "and tablename='aria_actions' order by 1"),
        "rows": q("select count(*) from public.aria_actions")[0][0],
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
log.append(("before: aria_actions exists", before["exists"]))

cur.execute(section1)
log.append(("SECTION 1 applied", "ok"))
mid = snapshot()
log.append(("columns (14 expected)", f"{len(mid['columns'])}: {mid['columns']}"))
log.append(("RLS (enabled, forced)", mid["rls"]))
log.append(("policies", mid["policies"]))
log.append(("grants", mid["grants"]))
log.append(("anon has nothing", not any(g[0] == "anon" for g in mid["grants"])))
log.append(("authenticated has SELECT only",
            [g[1] for g in mid["grants"] if g[0] == "authenticated"] == ["SELECT"]))
log.append(("constraints", [c[0] for c in mid["constraints"]]))
log.append(("indexes", [i[0] for i in mid["indexes"]]))
log.append(("rows (0 expected)", mid["rows"]))

must_fail("CHECK action_type rejects delete_task",
          "insert into public.aria_actions (business_id, action_type, payload, expires_at) "
          "values (%s, 'delete_task', '{}', now())", (biz,))
must_fail("CHECK status rejects 'sent'",
          "insert into public.aria_actions (business_id, action_type, payload, status, expires_at) "
          "values (%s, 'create_task', '{}', 'sent', now())", (biz,))
must_fail("authenticated role cannot INSERT",
          "set local role authenticated; insert into public.aria_actions "
          "(business_id, action_type, payload, expires_at) values (%s, 'create_task', '{}', now())",
          (biz,))
must_fail("authenticated role cannot UPDATE",
          "set local role authenticated; update public.aria_actions set status='proposed'")

cur.execute("BEGIN")
cur.execute("insert into public.aria_actions (id, business_id, action_type, payload, expires_at) "
            "values ('00000000-0000-4000-8000-000000000035', %s, 'create_task', "
            "'{\"title\":\"rehearsal\"}', now() + interval '1 hour')", (biz,))
claim = ("update public.aria_actions set status='executing' "
         "where id='00000000-0000-4000-8000-000000000035' and status='proposed' "
         "and expires_at > now() returning id")
first = len(q(claim))
second = len(q(claim))
cur.execute("ROLLBACK")
log.append(("claim: first returns 1 row, second 0", (first, second)))
cur.execute("BEGIN")
cur.execute("insert into public.aria_actions (id, business_id, action_type, payload, expires_at) "
            "values ('00000000-0000-4000-8000-000000000036', %s, 'create_task', '{}', "
            "now() - interval '1 minute')", (biz,))
expired = len(q(claim.replace("035'", "036'")))
cur.execute("ROLLBACK")
log.append(("claim on an expired row returns 0", expired))

cur.execute(section1)
log.append(("SECTION 1 applied again (idempotent), snapshot unchanged", snapshot() == mid))

cur.execute(rollback)
log.append(("ROLLBACK 1 run; table gone (== before)", snapshot() == before))

cur.execute(section1)
log.append(("SECTION 1 re-applied and LEFT APPLIED (staging models prod-after-035)",
            snapshot() == mid))

for k, v in log:
    print(f"- {k}: {v}")
