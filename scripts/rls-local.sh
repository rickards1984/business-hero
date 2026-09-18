#!/usr/bin/env bash
# Business Hero — a local Supabase Postgres carrying the migration-defined RLS
# state, for backend/tests/test_tenant_isolation_rls_path.py (BH-003, the
# anon-key half of RC1 P0-9).
#
# Usage:
#   scripts/rls-local.sh up        # fresh container, replay migrations, prune
#                                  # (always from scratch: the historical files
#                                  # are not idempotent, so there is no "re-replay")
#   scripts/rls-local.sh test      # run the RLS suite against it
#   scripts/rls-local.sh census    # print the BH-001 Q1/Q2/Q3/Q5/Q6 queries
#   scripts/rls-local.sh down      # remove the container
#
# WHAT THIS PROVES, AND WHAT IT DOES NOT
#   The image is Supabase's own Postgres build, so `auth.uid()`, the `anon`
#   / `authenticated` / `service_role` roles and the DEFAULT PRIVILEGES that
#   give those roles full access to every new public table (AGENTS.md §3.3,
#   §3.8) are Supabase's, not a shim. The schema, policies and grants come
#   from replaying this repository's migration files. That is the state the
#   MIGRATIONS describe. AGENTS.md §3.4: migration files are not evidence of
#   live state. Until BH-001's production census is in audits/ and compared
#   with `census` here, a green run says "the policies as written isolate",
#   not "production isolates".
#
# REPLAY ORDER — and why it is not "sort by number"
#   `businesses`, `business_members`, `tasks`, `calls`, `quotes` and the
#   accounting tables were never created by a migration: create_all() made
#   them, and every early migration ALTERs a table it assumes exists. 028 is
#   the first file that creates them, and it is idempotent by design
#   (CREATE IF NOT EXISTS, DROP POLICY IF EXISTS + CREATE). So: 028 first to
#   stand the ORM-born tables up, the historical files in their two
#   numbered series, 028 again to re-assert every live policy now that every
#   table exists, then 029 and the runbook-driven 030a–033.
#
#   Residual errors are expected and listed in REPLAY-EXPECTED-ERRORS below;
#   `replay` fails if any OTHER error appears, so drift in the migrations
#   cannot pass silently.

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

CONTAINER="${RLS_LOCAL_CONTAINER:-bh2-rls-local}"
PORT="${RLS_LOCAL_PORT:-54329}"
IMAGE="${RLS_LOCAL_IMAGE:-public.ecr.aws/supabase/postgres:17.6.1.140}"
export RLS_LOCAL_DATABASE_URL="postgresql://postgres:postgres@127.0.0.1:${PORT}/postgres"

ORDER=(
  supabase/migrations/028_baseline_live_state.sql
  backend/migrations/001_create_business_settings_integrations.sql
  backend/migrations/002_create_rls_policies.sql
  backend/migrations/003_add_logo_url_and_storage.sql
  backend/migrations/004_storage_rls_policies.sql
  backend/migrations/005_create_invoices.sql
  backend/migrations/006_email_smtp_outbox.sql
  backend/migrations/007_email_accounts_messages.sql
  backend/migrations/008_calendar_events.sql
  backend/migrations/009_tasks_soft_delete.sql
  backend/migrations/010_email_analysis_columns.sql
  backend/migrations/011_reconcile_email_sync_state.sql
  supabase/migrations/009_business_tiers_and_support.sql
  supabase/migrations/010_stripe_billing.sql
  supabase/migrations/011_calls_archived.sql
  supabase/migrations/012_invoices_paid_archived.sql
  supabase/migrations/013_xero_integration.sql
  supabase/migrations/014_invoice_xero_columns.sql
  supabase/migrations/015_task_categories.sql
  supabase/migrations/016_receptionist_tables.sql
  supabase/migrations/017_onboarding_wizard.sql
  supabase/migrations/018_support_system.sql
  supabase/migrations/019_accounting_providers.sql
  supabase/migrations/020_ceo_briefing_whatsapp.sql
  supabase/migrations/021_automation_alerts_tables.sql
  supabase/migrations/022_booking_calendar_id.sql
  supabase/migrations/023_token_refreshed_at.sql
  supabase/migrations/024_background_sync.sql
  supabase/migrations/025_rename_elite_to_business.sql
  supabase/migrations/026_executive_board_meetings.sql
  supabase/migrations/027_receptionist_voice_preset.sql
  supabase/migrations/028_baseline_live_state.sql
  supabase/migrations/029_secure_rls_gaps.sql
  backend/migrations/030a_pre_billing_security.sql
  backend/migrations/031_money_engine.sql
  backend/migrations/032_nullable_line_tax.sql
  backend/migrations/033_entitlement.sql
)

# Every error the replay is known to raise on a fresh Supabase image, as a
# regex matched against the ERROR line. Anything else fails the replay.
REPLAY_EXPECTED_ERRORS='relation "storage\.objects" does not exist|relation "realtime\.subscription" does not exist|cannot change name of input parameter "p_user_id"|relation "email_outbox" already exists|relation "idx_email_outbox_[a-z_]*" already exists|column "email_account_id" does not exist|syntax error at or near ","|relation "calls" does not exist|relation "email_sync_state" does not exist|relation "public\.calls" does not exist'

psql_in() { docker exec -i "$CONTAINER" psql -U postgres -v ON_ERROR_STOP=0 -q "$@"; }
psql_c()  { docker exec "$CONTAINER" psql -U postgres -At -c "$1"; }

up() {
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
  docker run -d --name "$CONTAINER" -e POSTGRES_PASSWORD=postgres \
    -p "${PORT}:5432" "$IMAGE" >/dev/null
  # The Supabase image initialises, RESTARTS Postgres, then serves. A single
  # pg_isready can pass in the first phase; the replay then hits the restart
  # and psql's "connection refused" is not an ERROR: line. Wait for the
  # second "ready to accept connections" in the container log, then for
  # three consecutive successful queries.
  for _ in $(seq 1 90); do
    n=$(docker logs "$CONTAINER" 2>&1 | grep -c "database system is ready to accept connections" || true)
    [ "$n" -ge 2 ] && break
    sleep 1
  done
  local ok=0
  for _ in $(seq 1 30); do
    if docker exec "$CONTAINER" psql -U postgres -Atqc "select 1" >/dev/null 2>&1; then
      ok=$((ok+1)); [ $ok -ge 3 ] && break
    else
      ok=0
    fi
    sleep 1
  done
  [ $ok -ge 3 ] || { echo "postgres never became stable" >&2; exit 1; }
  replay
}

replay() {
  local log unexpected=0
  log="$(mktemp -t bh2-rls-replay)"
  printf 'replaying %d migration files into %s\n' "${#ORDER[@]}" "$CONTAINER"
  local i=0
  for f in "${ORDER[@]}"; do
    [ -f "$f" ] || { echo "missing: $f" >&2; exit 1; }
    i=$((i+1))
    out="$(psql_in < "$f" 2>&1 || true)"
    if printf '%s' "$out" | grep -qiE 'could not connect|connection refused|server closed the connection|psql: error'; then
      echo "psql could not talk to $CONTAINER while applying $f:" >&2
      printf '%s\n' "$out" | grep -iE 'could not connect|connection refused|server closed|psql: error' >&2
      exit 1
    fi
    printf '%s\n' "$out" | grep '^ERROR' | sed "s|^|$i $f: |" >> "$log" || true
  done
  # Pass 1 of 028 (index 1) runs before every table exists; its "relation
  # does not exist" errors are the reason for the second pass and are
  # tolerated THERE ONLY. On every other file that error is a real failure.
  if grep -vE "$REPLAY_EXPECTED_ERRORS" "$log" \
       | grep -vE '^1 supabase/migrations/028_[^:]*: ERROR:  relation "public\.[a-z_]+" does not exist$' \
       | grep -q .; then
    echo "UNEXPECTED replay errors (not in REPLAY_EXPECTED_ERRORS):" >&2
    grep -vE "$REPLAY_EXPECTED_ERRORS" "$log" \
      | grep -vE '^1 supabase/migrations/028_[^:]*: ERROR:  relation "public\.[a-z_]+" does not exist$' >&2
    unexpected=1
  fi
  printf 'replay done: %s error lines, all expected=%s\n' \
    "$(wc -l < "$log" | tr -d ' ')" "$([ $unexpected = 0 ] && echo yes || echo NO)"
  [ $unexpected = 0 ] && prune_ghost_policies && apply_runbook_cleanups
}

# The migration files leave their rollback snapshots in place; the runbooks
# that ran them in production dropped two of them as their final step
# (031 STEP 15, 032 STEP 8), and the 3 Sep 2026 FULL schema dump
# (audits/live-schema-public.txt) shows neither table. 033's snapshot
# (zz_033_flags_backup) is deliberately retained (033 STEP 26) with anon /
# authenticated revoked, and stays. Note what the two dropped ones were
# while they existed: RLS off, default grants, holding every business's
# quote line costs — see the invariant test in the RLS suite.
apply_runbook_cleanups() {
  psql_c "DROP TABLE IF EXISTS public._031_unit_cost_before;" >/dev/null
  psql_c "DROP TABLE IF EXISTS public._032_line_tax_before;" >/dev/null
  echo "cleanup: dropped 031/032 rollback snapshots (runbook STEP 15 / STEP 8)"
}

# PRUNE — the pre-baseline files (002, 006–008, 013, 019 …) create policies
# that production no longer has: 028's own header says they "were superseded
# in the dashboard and NEVER matched what production runs today", and the
# 5 July 2026 pg_policies export in live_state/ confirms it — for example
# 013's `xero_connections_service_policy` (FOR ALL USING (true), no role)
# is absent there. 028 only re-creates the policies it captured; it does not
# drop the ghosts, so a naive replay leaves a USING (true) policy on the
# table holding accounting OAuth tokens, and RLS tests against that would be
# testing a database production never was. The allowlist is: every policy
# in the July export, plus every CREATE POLICY in 029 and the runbook-driven
# 030a–033. Anything else is dropped, and listed.
prune_ghost_policies() {
  local allow ghosts
  allow="$(.venv/bin/python - <<'PY'
import csv, re
names = set()
with open("audits/live-policies-2026-07-05.csv", newline="") as f:
    for row in csv.DictReader(f):
        names.add(f"{row['tablename']}|{row['policyname']}")
pat = re.compile(r'CREATE POLICY\s+("?)([^"\s]+(?:\s[^"\s]+)*?)\1\s+ON\s+(?:public\.)?([a-z_]+)', re.I)
for path in ["supabase/migrations/029_secure_rls_gaps.sql",
             "backend/migrations/030a_pre_billing_security.sql",
             "backend/migrations/031_money_engine.sql",
             "backend/migrations/032_nullable_line_tax.sql",
             "backend/migrations/033_entitlement.sql"]:
    txt = "\n".join(l for l in open(path) if not l.lstrip().startswith("--"))
    for m in pat.finditer(txt):
        names.add(f"{m.group(3)}|{m.group(2)}")
print("\n".join(sorted(names)))
PY
)"
  ghosts="$(psql_c "SELECT c.relname||'|'||p.polname FROM pg_policy p
                     JOIN pg_class c ON c.oid=p.polrelid JOIN pg_namespace n ON n.oid=c.relnamespace
                    WHERE n.nspname='public' ORDER BY 1" | grep -vxF -f <(printf '%s\n' "$allow") || true)"
  if [ -z "$ghosts" ]; then echo "prune: no ghost policies"; return 0; fi
  printf 'prune: dropping %s pre-baseline ghost policies:\n' "$(printf '%s\n' "$ghosts" | wc -l | tr -d ' ')"
  printf '%s\n' "$ghosts" | while IFS='|' read -r tbl pol; do
    printf '  %s.%s\n' "$tbl" "$pol"
    psql_c "DROP POLICY IF EXISTS \"$pol\" ON public.\"$tbl\";" >/dev/null
  done
}

census() {
  echo "-- Q1 inventory: table, rls_enabled, rls_forced, policy_count"
  psql_c "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, count(p.polname)
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            LEFT JOIN pg_policy p ON p.polrelid=c.oid
           WHERE n.nspname='public' AND c.relkind='r' GROUP BY 1,2,3 ORDER BY 2,1;"
  echo "-- Q1b views: relkind, owner, security_invoker, grants to client roles"
  echo "--     (BH-001's Q1 has relkind='r' and cannot see these; a view owned by"
  echo "--      postgres runs as postgres and bypasses the RLS on its base tables)"
  psql_c "SELECT c.relname, c.relkind, pg_get_userbyid(c.relowner),
                 coalesce(array_to_string(c.reloptions, ','), '-'),
                 coalesce((SELECT string_agg(g.grantee||':'||g.privilege_type, ' ')
                             FROM information_schema.role_table_grants g
                            WHERE g.table_schema='public' AND g.table_name=c.relname
                              AND g.grantee IN ('anon','authenticated')), 'none')
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
           WHERE n.nspname='public' AND c.relkind IN ('v','m') ORDER BY 1;"
  echo "-- Q2 policies"
  psql_c "SELECT c.relname, p.polname, p.polcmd, p.polpermissive,
                 COALESCE((SELECT string_agg(r.rolname, ', ') FROM pg_roles r WHERE r.oid = ANY(p.polroles)), 'PUBLIC'),
                 regexp_replace(pg_get_expr(p.polqual, p.polrelid), '\s+', ' ', 'g'),
                 regexp_replace(pg_get_expr(p.polwithcheck, p.polrelid), '\s+', ' ', 'g')
            FROM pg_policy p JOIN pg_class c ON c.oid=p.polrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace
           WHERE n.nspname='public' ORDER BY 1,2;"
  echo "-- Q3 table grants to anon/authenticated"
  psql_c "SELECT table_name, grantee, string_agg(privilege_type, ', ' ORDER BY privilege_type)
            FROM information_schema.role_table_grants
           WHERE table_schema='public' AND grantee IN ('anon','authenticated')
           GROUP BY 1,2 ORDER BY 1,2;"
  echo "-- Q5 default privileges"
  psql_c "SELECT n.nspname, d.defaclobjtype, pg_get_userbyid(d.defaclrole), d.defaclacl
            FROM pg_default_acl d LEFT JOIN pg_namespace n ON n.oid=d.defaclnamespace ORDER BY 1,2;"
  echo "-- Q6 businesses grants"
  psql_c "SELECT grantee, privilege_type FROM information_schema.role_table_grants
           WHERE table_schema='public' AND table_name='businesses' ORDER BY 1,2;"
}

test_() {
  .venv/bin/python -m pytest backend/tests/test_tenant_isolation_rls_path.py -v -p no:warnings "$@"
}

down() { docker rm -f "$CONTAINER" >/dev/null 2>&1 && echo "removed $CONTAINER" || true; }

case "${1-}" in
  up) up ;;
  census) census ;;
  test) shift; test_ "$@" ;;
  down) down ;;
  *) sed -n '2,12p' "$0"; exit 2 ;;
esac
