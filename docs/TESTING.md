# Testing — STUB

**Status: stub.** Inventory and exact baseline results are in
`docs/CURRENT_STATE.md` §1. Harness rationale is in `audits/SETUP-HARNESS.md`.

## The one command

```bash
./check.sh          # tsc, py_compile, ruff, pytest
./check.sh full     # + scripts/preflight.sh deploy traps
```

Baseline at commit `9826f61`: **382 passed, 0 failed**, 19 test files, all
backend.

## What is NOT tested — the honest part

- **No frontend tests.** Zero. 124 files, ~33.8k lines, untested
- **No end-to-end tests.** No test drives a browser
- **No tenant-isolation test.** The July audit asked for one; it does not
  exist. This is the highest-value missing test in the repository
- **No test of any golden journey** from the brief
- ~~CI runs pytest directly rather than `check.sh`, so the two can drift~~ —
  **fixed 8 Sep 2026: CI runs `./check.sh full`**, the same command the
  pre-push hook runs
- ~~`ruff` runs with `continue-on-error: true` in CI — lint does not gate~~ —
  **fixed 8 Sep 2026: lint gates in CI**, because it gates inside `check.sh`

## Minimum critical test layer, in dependency order

Per the brief: do not attempt to build every test at once.

1. Tenant and role separation (RC1 P0-9)
2. Entitlement enforcement — a Starter plan is refused at the API
3. Lead → quote → invoice → payment, the RC1 journey (P1-5)
4. Failure handling — AI, telephony, email and payment failures must not
   corrupt data or silently duplicate an action
5. Incoming call → identification → action → CRM update

Journeys 4 and 5 from the brief, and the contractor compliance journey, are
out of RC1.
