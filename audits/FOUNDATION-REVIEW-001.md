# Foundation review 001 — handoff and evidence

Independent review of the engineering foundation by Codex, and Claude Code's
response to it. The reviewer's original report is
`audits/foundation-review-001-codex-report.md` — **unedited, and it stays
unedited.** This document records what was done about it.

---

## 1 · What was reviewed

| | |
|---|---|
| Reviewed commit | **`3a388f98762a59084efa6de3f64afe94ce8ce0dc`** |
| Comparison base | `9826f61a6ccf998877fc333018b78b6b14bef466` (origin/main) |
| Branch | `foundation/rc1-baseline` |
| Commits in scope | `7e01b8b`, `d60a46b`, `3a388f9` |
| Diff size | 22 files, +2,323 / −284 |
| Working tree at review | clean — 0 uncommitted tracked changes |

**Review scope:** the four agreed corrections (push policy, migration
classification, stale setup paths, CI/harness alignment); the audit's material
claims tested against code; entitlement-enforcement gaps distinguished from
tenant isolation; whether CI actually enforces the required checks; and a
challenge to the RC1 boundary and ticket dependencies.

## 2 · Reviewer execution status

| | |
|---|---|
| Tool | Codex CLI 0.153.4, non-interactive (`codex exec`) |
| Model | `gpt-6-astra` |
| Auth | existing ChatGPT login — **no API credentials used** |
| Sandbox | `workspace-write`, confined to the review worktree + tmp; no network |
| Approvals | `approval_policy="never"` — nothing auto-approved, nothing bypassed |
| Worktree | `~/dev/bh2-foundation-review`, detached at the reviewed commit |
| Session id | `01a0826c-0d1d-7923-ac5c-be30ecef8bb9` |
| Started / ended | 2026-09-08T19:08:34Z / 19:12:41Z (~4m 07s) |
| Process exit | **0** — review completed, report returned in full |
| Worktree after | clean, still at the reviewed commit; reviewer made no edits |
| **Verdict** | **REQUEST-CHANGES** |

**Usage, as reported by the tool:** `tokens used 101,680`. This is the
figure Codex printed for the session. It is **not a bill and not an exact
cost** — it excludes any plan-level accounting, and no billing API was
consulted.

## 3 · Verification evidence

`./check.sh full` at the reviewed commit, captured in
`audits/foundation-review-001-check-full.txt`:

```
5 passed   0 failed   1 skipped        exit 0
PASS tsc --noEmit / python syntax (py_compile) / ruff / pytest / preflight
SKIP eslint  (no lint script in package.json)
382 passed, 20 warnings, 104 subtests passed
```

Run 2026-09-08T19:05:45Z on Python 3.12.14, ruff 0.16.6, pytest 9.1.1,
node v22.22.2. **These are results from that run, not carried figures.**

Codex reproduced the same run independently in its worktree (382 tests, 104
subtests, five traps) and additionally ran 96 targeted entitlement and schema
tests. It executed two in-memory probes against extracted code, which is how
findings 4 and 5 moved from "suspected" to "confirmed".

## 4 · Uncommitted work

At the reviewed commit the tracked tree was clean. One change is **not** in
git and will not reach any other clone or the reviewer:

- `.claude/settings.local.json` — the old-path permission entry was repointed
  to `~/dev/business-hero-2`. The file is ignored globally via
  `~/.config/git/ignore`. Two further entries there reference a scratchpad
  from a dead session and are stale by session id, not by path; they were
  left alone.

Nothing else is outstanding.

## 5 · Disposition of the findings

Fixed in the correction cycle unless marked otherwise.

| # | Severity | Finding | Disposition |
|---|---|---|---|
| 1 | MAJOR | `check.sh` could report green having skipped mandatory checks | **Fixed.** `check.sh` now fails closed on a missing backend dir, ruff, pytest or preflight. eslint stays the one legitimate skip. CI now asserts the five required steps **passed** rather than looking for two skip strings |
| 2 | MAJOR | Remote gate gaps; preflight compared against a hardcoded `origin/main` and failed open | **Fixed.** CI runs on every branch push, not just `main`. `preflight.sh` resolves a base explicitly (`PREFLIGHT_BASE`, else `origin/main`, else `HEAD~1`) and **fails closed** when it cannot. CI resolves an event-appropriate base and errors if none exists |
| 3 | MAJOR | Runtime alignment incomplete; `@capacitor/cli` needs node ≥22, CI pinned node 20 | **Fixed.** CI moved to node 22 / Python 3.12 to match the local toolchain. Verified the engine constraint at `frontend/client/package-lock.json:856`. Unpinned backend deps remain — recorded, not fixed |
| 4 | MAJOR | Stripe claims false: `deleted` treated like `updated`; dedup written after commit | **Docs corrected; code deferred.** `docs/CURRENT_STATE.md` no longer claims either property. Four acceptance criteria added to **P0-7**. The code fix is RC1 lane work and was not started |
| 5 | MAJOR | Confirmed cross-tenant leak in accounting category join | **Recorded as P0-9a; code deferred.** Verified in code at `backend/accounting.py:200` and `:300`. Recorded in `CURRENT_STATE.md` and `RC1_SCOPE.md`. Not fixed here — it is feature-lane work, and the lanes are not open |
| 6 | MAJOR | RLS evidence query answers inventory, not isolation | **Fixed.** `docs/PERMISSIONS_AND_TENANCY.md` now requires policy expressions, roles/commands, grants, default privileges and executed negative tests |
| 7 | MAJOR | Entitlement criteria contradict the plan matrix; board meetings wrongly called ungated | **Fixed.** Criteria are now per feature/plan/status; the smoke test lists what Starter genuinely has; `RC1_SCOPE.md` corrected — board meetings *are* gated, by a second mechanism |
| 8 | MAJOR | Founder decision contradicted its own criteria and claimed unimplemented behaviour | **Fixed.** Both defects were introduced by Claude Code's own earlier edits. The resolution now reads as a decision, not an observed state; the criterion says MSC `business`, New Body `pro`; read-only scope reconciled |
| 9 | MINOR | 032 treated as history, but not established as applied | **Fixed, and the reviewer understated it.** `032` is **not applied to prod**: absent from the migration table, and `live-schema-public.txt:479,588` still show the columns it would change. It is a *pending* runbook — path updated and a status banner added |
| 10 | MINOR | Surviving "Mike pushes"; audit-reuse rule vs verification; duplicated master-key status | **Fixed.** All three |
| 11 | MAJOR | Pre-push hook verified the working tree, not the pushed revision | **Fixed.** The hook now refuses a push whose SHA is not HEAD, and refuses a dirty tree, so what the gate verified is what gets pushed |

**Suspicions, both left open:** accounting-sync direction is undefined
(recorded as boundary challenge 4); and no production exploit or real CI
failure was demonstrated — correctly, since network and database access were
prohibited.

## 6 · Deliberately not done

- **No product code was changed.** Findings 4 and 5 are real defects in
  `backend/main.py` and `backend/accounting.py`. Fixing them is RC1 lane
  work, and the feature lanes are not open. They are recorded as P0 items
  with acceptance criteria.
- **The RC1 boundary was not redrawn.** Codex's six challenges are recorded
  verbatim in `docs/RC1_SCOPE.md` under "Review 001 boundary challenges" and
  marked as needing Mike's decision. The boundary is his acceptance gate.
- **No production SQL, no Railway change, no merge to main.**

## 7 · Limits of this review

Everything in Codex's §7 stands: live schema, RLS, grants and applied
migration state; GitHub run results and branch protection; clean-CI
installs under node 22 / Python 3.12; deployed behaviour; browser journeys;
and the production exploitability of finding 5 are all **unverified**, because
database and network access were prohibited. The CI changes here are
*unexercised* — no run has occurred against them.
