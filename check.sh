#!/usr/bin/env bash
# Business Hero — single-command verification.
# Usage: ./check.sh [fast|full]
#   fast  (default) typecheck + lint + unit tests. Seconds. Run constantly.
#   full  everything in fast, plus preflight deploy traps.
#
# Exit 0 = safe to proceed. Non-zero = something is broken; the output says what.
# This script is the agent's feedback loop. It must stay fast and honest.
#
# FAIL CLOSED. A missing tool is a FAILURE, not a skip. Review 001 finding 1:
# check.sh could report green having verified almost nothing — no backend
# directory, no ruff, no pytest, no preflight all counted as skips, and a skip
# is not a failure. That is the worst possible behaviour in a gate, because it
# is indistinguishable from success in CI logs nobody reads. The ONLY
# legitimate skip is eslint, which is genuinely optional (no lint script).

set -uo pipefail
MODE="${1:-fast}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || PY="python3"

PASS=0; FAIL=0; SKIP=0
FAILED_STEPS=()

hr()  { printf '%s\n' "------------------------------------------------------------"; }
step(){ hr; printf '  %s\n' "$1"; hr; }
ok()  { printf '  PASS  %s\n' "$1"; PASS=$((PASS+1)); }
bad() { printf '  FAIL  %s\n' "$1"; FAIL=$((FAIL+1)); FAILED_STEPS+=("$1"); }
skip(){ printf '  SKIP  %s  (%s)\n' "$1" "$2"; SKIP=$((SKIP+1)); }

# ---------------------------------------------------------------- frontend ---
step "FRONTEND"
FE="frontend/client"
if [ ! -d "$FE" ]; then
  bad "frontend directory $FE is missing — cannot verify the frontend"
elif [ ! -d "$FE/node_modules" ]; then
  bad "frontend deps not installed — run: (cd $FE && npm install)"
  printf '        Without node_modules, TypeScript errors only appear at the\n'
  printf '        Vercel build. That is a 3-minute loop instead of 8 seconds.\n'
else
  if (cd "$FE" && npx --no-install tsc --noEmit) 2>&1 | sed 's/^/        /'; then
    ok "tsc --noEmit"
  else
    bad "tsc --noEmit"
  fi

  if (cd "$FE" && [ -f package.json ] && grep -q '"lint"' package.json); then
    if (cd "$FE" && npm run --silent lint) 2>&1 | sed 's/^/        /'; then
      ok "eslint"
    else
      bad "eslint"
    fi
  else
    skip "eslint" "no lint script in package.json"
  fi
fi

# ----------------------------------------------------------------- backend ---
step "BACKEND"
if [ ! -d backend ]; then
  bad "backend directory is missing — cannot verify the backend"
else
  # Syntax check every Python file. Cheap, catches the obvious.
  if find backend -name '*.py' -not -path '*/.venv/*' -print0 \
       | xargs -0 "$PY" -m py_compile 2>&1 | sed 's/^/        /'; then
    ok "python syntax (py_compile)"
  else
    bad "python syntax (py_compile)"
  fi

  if "$PY" -m ruff --version >/dev/null 2>&1; then
    if "$PY" -m ruff check backend 2>&1 | sed 's/^/        /'; then
      ok "ruff"
    else
      bad "ruff"
    fi
  else
    bad "ruff is not installed — the lint gate cannot run"
    printf '        Install it: %s -m pip install ruff\n' "$PY"
  fi

  if "$PY" -m pytest --version >/dev/null 2>&1 && [ -d backend/tests ]; then
    if "$PY" -m pytest backend/tests -q 2>&1 | tail -25 | sed 's/^/        /'; then
      ok "pytest"
    else
      bad "pytest"
    fi
  else
    bad "pytest is not installed, or backend/tests is missing — tests cannot run"
    printf '        Install it: %s -m pip install pytest\n' "$PY"
  fi
fi

# ---------------------------------------------------------------- preflight --
if [ "$MODE" = "full" ]; then
  step "PREFLIGHT (deploy traps)"
  if [ -x scripts/preflight.sh ]; then
    if ./scripts/preflight.sh 2>&1 | sed 's/^/        /'; then
      ok "preflight"
    else
      bad "preflight"
    fi
  else
    bad "scripts/preflight.sh is missing or not executable — deploy traps cannot run"
  fi
fi

# ------------------------------------------------------------------ verdict --
hr
printf '  %d passed   %d failed   %d skipped\n' "$PASS" "$FAIL" "$SKIP"
if [ "$FAIL" -gt 0 ]; then
  printf '\n  BLOCKED. Fix these before proceeding:\n'
  for s in "${FAILED_STEPS[@]}"; do printf '    - %s\n' "$s"; done
  hr
  exit 1
fi
printf '  Green. Safe to proceed.\n'
hr
exit 0
