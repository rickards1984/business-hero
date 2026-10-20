"""Rehearse migration 037 on STAGING only. Refuses any other database.

Reads STAGING_DB_URL from .env.staging (or the file STAGING_ENV_FILE names)
and never prints it. Runs the sections the way Mike will: Section 1 one
statement per execution (concurrent indexes), Section 2 as its single
transaction, Section 3 read-only, Section 4 only if Section 3 has no BLOCKS
row. Proves legacy chase rows are untouched, re-paste is clean, the
runbook's rollback returns the exact before-state, and re-applies.
Synthetic fixture rows (fixed ids ...037xxx) are removed at the end.
"""
import json
import os
import re
import sys

import psycopg2

env_file = os.environ.get("STAGING_ENV_FILE", ".env.staging")
env = dict(l.split("=", 1) for l in open(env_file).read().splitlines() if "=" in l and not l.startswith("#"))
url = env.get("STAGING_DB_URL", "").strip().strip('"')
if "gzcrsrqmygublveuzqyg" not in url or "oxblcmwhuwtobdhsfgyi" in url:
    sys.exit("REFUSING: STAGING_DB_URL is not the staging project")

sql = open("backend/migrations/037_outreach_core.sql").read()
s1 = sql[sql.index("-- SECTION 1"):sql.index("-- SECTION 2")]
section1 = re.findall(r"CREATE UNIQUE INDEX CONCURRENTLY[^;]*;", s1)
s2 = sql[sql.index("-- SECTION 2"):sql.index("-- SECTION 3")]
section2 = s2[s2.index("BEGIN;"):s2.rindex("COMMIT;") + len("COMMIT;")]
s3 = sql[sql.index("-- SECTION 3"):sql.index("-- SECTION 4")]
section3 = s3[s3.index("SELECT"):s3.rindex(";") + 1]
s4 = sql[sql.index("-- SECTION 4"):]
section4 = s4[s4.index("CREATE UNIQUE INDEX"):s4.index(";") + 1]
runbook = open("audits/037-PROD-RUNBOOK.md").read()
rb = runbook[runbook.index("## STEP 9 — Rollback"):]
rollback_blocks = [b.split("```")[0] for b in rb.split("```sql")[1:3]]
assert len(section1) == 6 and "outreach_usage_events" in section2 and len(rollback_blocks) == 2
assert section2 in open("audits/037-STEP-3-section2.sql").read(), \
    "audits/037-STEP-3-section2.sql (what Mike pastes) differs from the migration's Section 2"

conn = psycopg2.connect(url)
conn.autocommit = True
cur = conn.cursor()
log = []

FX_USER, FX_BIZ, FX_ACCT = ("00000000-0000-4000-8000-000000037001",
                            "00000000-0000-4000-8000-000000037002",
                            "00000000-0000-4000-8000-000000037004")


def q(stmt, params=None):
    cur.execute(stmt, params)
    return cur.fetchall() if cur.description else None


def snapshot():
    return {
        "outreach_tables": q("select count(*) from pg_tables where schemaname='public' "
                             "and tablename like 'outreach\\_%'")[0][0],
        "policies": q("select count(*) from pg_policies where schemaname='public'")[0][0],
        "out3_constraints": q("select count(*) from pg_constraint where conname like '%out3%'")[0][0],
        "out3_indexes": q("select count(*) from pg_indexes where schemaname='public' "
                          "and indexname like '%out3%'")[0][0],
        "type_check": q("select pg_get_constraintdef(oid) from pg_constraint "
                        "where conname='aria_actions_type_chk'")[0][0],
        "functions": q("select count(*) from pg_proc where proname like 'outreach\\_%'")[0][0],
    }


def legacy():
    rows = q("select 'aria_actions', id::text, to_jsonb(a) from public.aria_actions a "
             "where business_id = %s union all "
             "select 'email_outbox', id::text, to_jsonb(o) from public.email_outbox o "
             "where business_id = %s union all "
             "select 'business_settings', id::text, to_jsonb(s) from public.business_settings s "
             "where business_id = %s order by 1, 2", (FX_BIZ, FX_BIZ, FX_BIZ))
    return json.dumps(rows, sort_keys=True, default=str)


def apply_all(label):
    for st in section1:
        cur.execute(st)
    cur.execute(section2)
    log.append((f"{label}: Section 1 (6 statements, one by one) and Section 2 applied", "ok"))


def remove_fixture():
    cur.execute("BEGIN")
    for t in ("email_outbox", "aria_actions", "business_settings", "email_accounts",
              "business_members"):
        cur.execute(f"DELETE FROM public.{t} WHERE business_id = %s", (FX_BIZ,))
    cur.execute("DELETE FROM public.businesses WHERE id = %s", (FX_BIZ,))
    cur.execute("DELETE FROM auth.users WHERE id = %s", (FX_USER,))
    cur.execute("COMMIT")


# A previous interrupted run may have left the fixed-id synthetic rows.
remove_fixture()

# --- the before-state and the synthetic legacy rows (runbook STEP 2) ---
before = snapshot()
if before["outreach_tables"] or before["out3_constraints"]:
    sys.exit("REFUSING: staging already has 037 objects; roll it back first, so the "
             "rehearsal starts from the before-state")
log.append(("before", before))
step2 = runbook[runbook.index("## STEP 2 — Rehearse"):runbook.index("## STEP 3 — Section 1")]
fixture = step2.split("```sql")[1].split("```")[0]
assert "INSERT INTO auth.users" in fixture, "picked up the wrong block as the fixture"
cur.execute(fixture)
legacy_before = legacy()
assert len(json.loads(legacy_before)) == 5, "the fixture did not seed its five legacy rows"
log.append(("fixture: legacy rows captured", len(json.loads(legacy_before))))

# --- apply ---
apply_all("first apply")
after = snapshot()
log.append(("after", after))
log.append(("17 outreach tables", after["outreach_tables"] == 17))
rls = q("select count(*) from pg_class c join pg_namespace n on n.oid=c.relnamespace "
        "where n.nspname='public' and c.relname like 'outreach\\_%%' and c.relkind='r' "
        "and c.relrowsecurity")[0][0]
log.append(("RLS on all 17", rls == 17))
anon = q("select count(*) from information_schema.role_table_grants where table_schema='public' "
         "and table_name like 'outreach\\_%%' and grantee='anon'")[0][0]
log.append(("anon has nothing on outreach tables", anon == 0))
auth = q("select table_name, string_agg(privilege_type, ',' order by privilege_type) "
         "from information_schema.role_table_grants where table_schema='public' "
         "and table_name like 'outreach\\_%%' and grantee='authenticated' group by 1 order by 1")
log.append(("authenticated: SELECT only, on 6 tables", (len(auth), {r[1] for r in auth})))
log.append(("action types now include outreach", "send_outreach" in after["type_check"]
            and "reply_outreach" in after["type_check"]))
log.append(("legacy rows unchanged by 037", legacy() == legacy_before))

audit = q(section3)
blocks = [r for r in audit if r[-1] == "BLOCKS"]
log.append(("Section 3 audit (rows, BLOCKS rows)", (len(audit), len(blocks))))
if not blocks:
    cur.execute(section4)
    log.append(("Section 4 default index", q("select indisvalid from pg_index x join pg_class i "
                                             "on i.oid=x.indexrelid where i.relname="
                                             "'email_accounts_one_default_idx'")))

# --- re-paste ---
apply_all("re-paste")
log.append(("re-paste leaves the snapshot unchanged", snapshot() == after))

# --- rollback (runbook STEP 9, both blocks) ---
for block in rollback_blocks:
    cur.execute(block)
if not blocks:
    cur.execute("DROP INDEX CONCURRENTLY IF EXISTS public.email_accounts_one_default_idx")
log.append(("rollback returns the exact before-state", snapshot() == before))
log.append(("legacy rows unchanged by the rollback", legacy() == legacy_before))

# --- re-apply and leave applied ---
apply_all("re-apply")
if not blocks:
    cur.execute(section4)
log.append(("re-applied and LEFT APPLIED (staging models prod-after-037)", snapshot() == after))
log.append(("legacy rows unchanged after re-apply", legacy() == legacy_before))

# --- remove the synthetic rows ---
remove_fixture()
log.append(("synthetic rows removed", q("select count(*) from public.businesses where id=%s",
                                        (FX_BIZ,))[0][0] == 0))

for k, v in log:
    print(f"- {k}: {v}")
