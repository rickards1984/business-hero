"""Rehearse migration 034 on STAGING only. Refuses any other database."""
import json, os, re, sys
import psycopg2

env = dict(l.split("=", 1) for l in open(".env.staging").read().splitlines() if "=" in l and not l.startswith("#"))
url = env.get("STAGING_DB_URL", "").strip().strip('"')
if "gzcrsrqmygublveuzqyg" not in url or "oxblcmwhuwtobdhsfgyi" in url:
    sys.exit("REFUSING: STAGING_DB_URL is not the staging project")
sql = open("backend/migrations/034_invoice_customer_address.sql").read()
section1 = sql[sql.index("BEGIN;"):sql.index("COMMIT;") + len("COMMIT;")]
rollback = "\n".join(l[3:] for l in sql[sql.index("-- ROLLBACK 1"):].splitlines()
                     if l.startswith("-- ") and not l.startswith("-- ROLLBACK") and not l.startswith("-- two") and not l.startswith("-- -"))
rollback = rollback[rollback.index("BEGIN;"):]
verify = sql[sql.index("SELECT column_name, data_type, is_nullable"):].split(";")[0]

conn = psycopg2.connect(url); conn.autocommit = True; cur = conn.cursor()
cur.execute("select current_database(), inet_server_addr() is not null")
def q(s):
    cur.execute(s); return cur.fetchall()

def snapshot():
    return {
        "columns": q("select column_name, data_type, is_nullable, column_default from information_schema.columns where table_schema='public' and table_name='invoices' order by column_name"),
        "table_grants": q("select grantee, privilege_type from information_schema.role_table_grants where table_schema='public' and table_name='invoices' order by 1,2"),
        "column_grants": q("select grantee, column_name, privilege_type from information_schema.column_privileges where table_schema='public' and table_name='invoices' and grantee in ('anon','authenticated') order by 1,2,3"),
        "policies": q("select policyname, cmd, roles::text, qual, with_check from pg_policies where schemaname='public' and tablename='invoices' order by 1"),
        "rls": q("select relrowsecurity, relforcerowsecurity from pg_class where oid='public.invoices'::regclass"),
        "rows": q("select count(*) from public.invoices"),
    }

log = []
before = snapshot()
log.append(("before: invoices columns", len(before["columns"])))
log.append(("before: has customer_address/supply_date", [c[0] for c in before["columns"] if c[0] in ("customer_address","supply_date")]))
log.append(("before: RLS (enabled, forced)", before["rls"]))
log.append(("before: policies", [p[0] for p in before["policies"]]))
log.append(("before: table grants to anon/authenticated", [g for g in before["table_grants"] if g[0] in ("anon","authenticated")]))
cg = {(g[0], g[2]) for g in before["column_grants"]}
log.append(("before: column-level grant pattern (grantee, privilege) count", len(before["column_grants"])))

cur.execute(section1); log.append(("SECTION 1 applied", "ok"))
log.append(("VERIFY after section 1", q(verify)))
mid = snapshot()
new_cols = [c for c in mid["columns"] if c[0] in ("customer_address","supply_date")]
log.append(("new columns", new_cols))
log.append(("policies unchanged", mid["policies"] == before["policies"]))
log.append(("RLS unchanged", mid["rls"] == before["rls"]))
log.append(("row count unchanged", mid["rows"] == before["rows"]))
new_col_grants = [g for g in mid["column_grants"] if g[1] in ("customer_address","supply_date")]
log.append(("client column privileges on new columns (inherited from table grants)", new_col_grants))

cur.execute(section1); log.append(("SECTION 1 applied again (idempotent)", "ok"))
log.append(("VERIFY after re-apply", q(verify)))

cur.execute(rollback); log.append(("ROLLBACK 1 run", "ok"))
after_rb = snapshot()
log.append(("after rollback == before-snapshot (columns, grants, column grants, policies, RLS, rows)", after_rb == before))

cur.execute(section1); log.append(("SECTION 1 re-applied and LEFT APPLIED (staging now models prod-after-034)", "ok"))
log.append(("final VERIFY", q(verify)))

json.dump({"before": before}, open(os.environ.get("SNAP", "/dev/null"), "w"), default=str, indent=1)
for k, v in log:
    print(f"- {k}: {v}")
