#!/usr/bin/env bash
# Business Hero — preflight. Every check here is a real incident from the
# handover's "each caused a real failure" list, turned into an automated test.
#
# Run before every push:  ./scripts/preflight.sh
# Exit 0 = safe to push.

set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

FAIL=0
ok()   { printf '  PASS  %s\n' "$1"; }
bad()  { printf '  FAIL  %s\n' "$1"; FAIL=1; }
note() { printf '        %s\n' "$1"; }

# --- TRAP 1: Railway installs from ROOT requirements.txt, not backend/. ------
# Bit us twice: slowapi, then reportlab. Both crashed the deploy with
# ModuleNotFoundError because the dep was only in backend/requirements.txt.
printf '\nTRAP 1 — requirements.txt sync\n'
if [ -f requirements.txt ] && [ -f backend/requirements.txt ]; then
  MISSING=""
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    case "$line" in \#*|-*) continue ;; esac
    pkg=$(printf '%s' "$line" | sed 's/[<>=!~[].*//' | tr -d ' \t\r' | tr 'A-Z' 'a-z')
    [ -z "$pkg" ] && continue
    norm_pkg=$(printf '%s' "$pkg" | tr '_' '-')
    # NOTE: strip spaces/tabs/CR only — NOT '[:space:]', which eats newlines
    # and collapses the file to a single line so grep -x can never match.
    if ! sed 's/[<>=!~[].*//' requirements.txt | tr -d ' \t\r' \
         | tr 'A-Z' 'a-z' | tr '_' '-' | grep -qx "$norm_pkg"; then
      MISSING="$MISSING $pkg"
    fi
  done < backend/requirements.txt

  if [ -n "$MISSING" ]; then
    bad "in backend/requirements.txt but NOT in root requirements.txt:$MISSING"
    note "Railway will crash on deploy with ModuleNotFoundError."
  else
    ok "every backend dep is present in root requirements.txt"
  fi
else
  bad "requirements.txt or backend/requirements.txt not found"
fi

# --- TRAP 2: root requirements.txt historically had no trailing newline. -----
printf '\nTRAP 2 — trailing newline on requirements.txt\n'
if [ -f requirements.txt ]; then
  if [ -n "$(tail -c 1 requirements.txt)" ]; then
    bad "requirements.txt has no trailing newline — next append will merge lines"
  else
    ok "trailing newline present"
  fi
fi

# --- TRAP 3: repo must live OUTSIDE Dropbox/CloudStorage. -------------------
# A repo inside CloudStorage caused .git/index.lock "Operation not permitted".
printf '\nTRAP 3 — repo location\n'
case "$ROOT" in
  *CloudStorage*|*Dropbox*)
    bad "repo is inside CloudStorage/Dropbox — git index.lock failures WILL occur"
    ;;
  *) ok "repo is outside CloudStorage/Dropbox" ;;
esac

# --- TRAP 4: create_all() drift — new SQLModel classes silently create -------
# live tables with RLS OFF and default grants. Any unmigrated model is a
# potentially exposed table. This is a heads-up, not a hard fail.
printf '\nTRAP 4 — create_all() RLS drift warning\n'
if [ -f backend/db.py ] && grep -q 'create_all' backend/db.py; then
  if git diff --name-only origin/main...HEAD 2>/dev/null | grep -q 'models.py'; then
    bad "models.py changed AND create_all() is live"
    note "A new SQLModel class creates a live table with RLS OFF."
    note "Confirm RLS + policies for any new table before deploying."
    note "Override intentionally with: SKIP_RLS_DRIFT=1 ./scripts/preflight.sh"
    [ "${SKIP_RLS_DRIFT:-0}" = "1" ] && { FAIL=0; note "(overridden)"; }
  else
    ok "no models.py changes on this branch"
  fi
else
  ok "create_all() not detected in backend/db.py"
fi

# --- TRAP 5: secrets must never be committed. -------------------------------
printf '\nTRAP 5 — secret scan on staged/changed files\n'
CHANGED=$(git diff --name-only origin/main...HEAD 2>/dev/null; git diff --name-only --cached 2>/dev/null)
if [ -n "$CHANGED" ]; then
  HITS=$(printf '%s\n' "$CHANGED" | sort -u | while read -r f; do
    [ -f "$f" ] || continue
    # This script's own source contains the detection patterns below (e.g.
    # the literal string "sk-ant-"), so it always matches its own scan.
    # Skip it — scanning the scanner for its own signatures is a false
    # positive, not a secret.
    [ "$f" = "scripts/preflight.sh" ] && continue
    grep -lEi 'sk-ant-[a-z0-9]|sk-proj-[a-z0-9]|xai-[a-z0-9]{20}|SUPABASE_SERVICE_ROLE|service_role.*ey[A-Za-z0-9]' "$f" 2>/dev/null
  done)
  if [ -n "$HITS" ]; then
    bad "possible secret in changed files:"
    printf '%s\n' "$HITS" | sed 's/^/          /'
  else
    ok "no secret patterns in changed files"
  fi
else
  ok "no changed files to scan"
fi

printf '\n'
if [ "$FAIL" -ne 0 ]; then
  printf 'PREFLIGHT FAILED — do not push.\n\n'
  exit 1
fi
printf 'PREFLIGHT PASSED — safe to push.\n\n'
exit 0
