"""Rehearse migration 038 on STAGING only. Refuses any other database.

Reads STAGING_DB_URL from .env.staging (or the file STAGING_ENV_FILE names)
and never prints it. Runs the sections the way Mike will: Section 1 (one
concurrent index, autocommit), then Section 2 as its single transaction.
Proves the counts, re-paste, the runbook's STEP 6 rollback back to the exact
before-state, then re-applies and leaves 038 applied (staging parity).
Refuses to start unless staging is free of 038 objects.
"""
import os
import re
import sys

import psycopg2

env_file = os.environ.get("STAGING_ENV_FILE", ".env.staging")
env = dict(line.split("=", 1) for line in open(env_file).read().splitlines()
           if "=" in line and not line.startswith("#"))
url = env.get("STAGING_DB_URL", "").strip().strip('"')
if "gzcrsrqmygublveuzqyg" not in url or "oxblcmwhuwtobdhsfgyi" in url:
    sys.exit("REFUSING: STAGING_DB_URL is not the staging project")

sql = open("backend/migrations/038_outreach_replies.sql").read()
s1 = sql[sql.index("-- SECTION 1"):sql.index("-- SECTION 2")]
(section1,) = re.findall(r"CREATE UNIQUE INDEX CONCURRENTLY[^;]*;", s1)
s2 = sql[sql.index("-- SECTION 2"):]
section2 = s2[s2.index("BEGIN;"):s2.rindex("COMMIT;") + len("COMMIT;")]
runbook = open("audits/038-PROD-RUNBOOK.md").read()
rb = runbook[runbook.index("## STEP 6"):runbook.index("## Mike's plain checklist")]
rollback = [b.split("```")[0] for b in rb.split("```sql")[1:]]
assert len(rollback) == 2 and "DROP TABLE public.outreach_reply_slots" in rollback[0]
assert section2 in open("audits/038-STEP-3-section2.sql").read(), \
    "audits/038-STEP-3-section2.sql (what Mike pastes) differs from the migration's Section 2"

conn = psycopg2.connect(url)
conn.autocommit = True
cur = conn.cursor()


def snapshot():
    q = {
        "outreach_tables": "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' "
                           "AND table_name LIKE 'outreach\\_%' AND table_type='BASE TABLE'",
        "columns": "SELECT count(*) FROM information_schema.columns WHERE table_schema='public'",
        "policies": "SELECT count(*) FROM pg_policies WHERE schemaname='public'",
        "out7_key": "SELECT count(*) FROM pg_constraint WHERE conname='outreach_replies_out7_identity_key'",
        "out7_index": "SELECT count(*) FROM pg_indexes WHERE indexname='outreach_replies_out7_identity_key'",
        "freeze_fn": "SELECT count(*) FROM pg_proc WHERE proname='outreach_freeze_knowledge'",
        "knowledge_policy": "SELECT count(*) FROM pg_policies WHERE tablename='outreach_knowledge'",
        "slot_policies": "SELECT count(*) FROM pg_policies WHERE tablename='outreach_reply_slots'",
        "rls_on": "SELECT count(*) FROM pg_class WHERE relname IN ('outreach_knowledge','outreach_reply_slots') "
                  "AND relrowsecurity",
        "anon_privileges": "SELECT count(*) FROM information_schema.role_table_grants WHERE grantee='anon' "
                           "AND table_name IN ('outreach_knowledge','outreach_reply_slots')",
        "reply_rows": "SELECT count(*) FROM public.outreach_replies",
    }
    out = {}
    for key, query in q.items():
        cur.execute(query)
        out[key] = cur.fetchone()[0]
    return out


def apply():
    cur.execute(section1)
    cur.execute(section2)


before = snapshot()
print("- before:", before)
if before["out7_key"] or before["freeze_fn"] or before["knowledge_policy"]:
    sys.exit("REFUSING: staging already has 038 objects; start from the true before-state")

apply()
after = snapshot()
print("- after first apply:", after)
expect = {"outreach_tables": before["outreach_tables"] + 2, "columns": before["columns"] + 32,
          "policies": before["policies"] + 1, "out7_key": 1, "freeze_fn": 1, "knowledge_policy": 1,
          "slot_policies": 0, "rls_on": 2, "anon_privileges": 0, "reply_rows": before["reply_rows"]}
assert all(after[k] == v for k, v in expect.items()), {k: (after[k], v) for k, v in expect.items() if after[k] != v}
print("- deltas as the runbook states: +2 tables, +32 columns, +1 policy: ok")

apply()
assert snapshot() == after, "re-paste changed something"
print("- re-paste: no change: ok")

cur.execute(rollback[0])
cur.execute(rollback[1])
rolled = snapshot()
print("- after STEP 6 rollback:", rolled)
assert rolled == before, {k: (rolled[k], before[k]) for k in before if rolled[k] != before[k]}
print("- rollback returns the exact before-state: ok")

apply()
final = snapshot()
assert final == after
print("- re-applied and left applied (staging parity):", final)
conn.close()
