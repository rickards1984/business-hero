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
- **The RC1 boundary was not redrawn.** Codex's boundary challenges are
  recorded in `docs/RC1_SCOPE.md` under "Review 001 boundary challenges",
  **paraphrased, not verbatim**, and marked as needing Mike's decision. The
  boundary is his acceptance gate.

  *Corrected in cycle 2:* this line previously said "six challenges …
  verbatim" when five were recorded, in paraphrase. The two that had been
  dropped — the shared entitlement/read-only/tax contract for the PDF and
  manual-invoice work, and the export deliverable for unpaid customers — are
  now recorded as challenges 6 and 7.
- **No production SQL, no Railway change, no merge to main.**

## 7 · Limits of this review

Everything in Codex's §7 stands: live schema, RLS, grants and applied
migration state; GitHub run results and branch protection; clean-CI
installs under node 22 / Python 3.12; deployed behaviour; browser journeys;
and the production exploitability of finding 5 are all **unverified**, because
database and network access were prohibited. The CI changes here are
*unexercised* — no run has occurred against them.

---

## 8 · Re-review outcome — **REQUEST-CHANGES, and the cycle is spent**

`audits/foundation-review-001-codex-rereview.md` (unedited) reviewed the
correction commit `34861db`. Result: **4 RESOLVED, 5 PARTIAL, 2 DEFERRED
ACCEPTABLY**, four new findings, verdict **REQUEST-CHANGES**.

Per the handoff rules, one correction/re-review cycle was permitted and has
been used. **No cycle-2 changes have been made.** The foundation is
**BLOCKED pending Mike's decision.** A second REQUEST-CHANGES is not
approval, and nothing here should be read as one.

### Claims in this repository that the re-review showed are unsupported

These are committed and currently **wrong**. They are Claude Code's errors,
left in place only because correcting them would be an unapproved second
cycle:

1. `audits/032-PROD-RUNBOOK.md:3` — "**NOT YET APPLIED TO PROD (established
   8 Sep 2026)**". Overstated. Absence from a documentation table plus a
   schema snapshot that `033` STEP 24b itself marks stale do not *establish*
   that 032 was never applied. The honest claim is "no in-repository evidence
   that 032 was applied; treat as pending until confirmed against the live
   database."
2. `audits/FOUNDATION-REVIEW-001.md:110` — "Codex's **six** challenges are
   recorded **verbatim**". Both wrong: `docs/RC1_SCOPE.md` records **five**,
   **paraphrased**. The omitted two are the shared PDF/manual-invoice
   entitlement contract and the unpaid-customer export deliverable.
3. `docs/CURRENT_STATE.md:77` — still calls CI "**complete and verified**"
   while no CI run has ever executed the current workflow.

### Correction-cycle fixes that were incomplete

4. `scripts/preflight.sh` — `PREFLIGHT_BASE=HEAD` exits **0** reporting "no
   changed files to scan". The equal-base guard was added to CI but **not**
   to preflight itself, so the fail-closed claim is only true for the CI
   path. Verified locally.
5. `check.sh:11` — `MODE="${1:-fast}"` means any unrecognised argument
   silently runs fast mode. `./check.sh ful` prints "Green. Safe to proceed."
   having skipped every deploy trap. Verified locally.
6. `.github/workflows/ci.yml` — the required-checks assertion is substring
   matching, which accepts unrelated output containing the same text and
   breaks on a formatting change.
7. `.githooks/pre-push` — annotated tags cannot be pushed at all: the tag
   object SHA never equals HEAD. Untracked files are still excluded from the
   cleanliness check, so tested content can differ from pushed content.
8. `docs/PERMISSIONS_AND_TENANCY.md` — `role_table_grants` does not carry
   **column** grants; those need separate collection.

---

## 9 · Cycle 2 outcome — **REQUEST-CHANGES again; stopping as instructed**

Mike authorised one further bounded cycle. It was used, reviewed, and the
verdict is `audits/foundation-review-003-codex-report.md`: **REQUEST-CHANGES**,
reviewed commit `c72d4fc`, all five blockers **PARTIAL**.

His instruction was to stop after this cycle if material blockers remain. They
do. **No cycle-3 changes have been made.**

### What cycle 2 did close

| Was | Now |
|---|---|
| `./check.sh ful` ran fast mode and printed "Green" | Unrecognised and extra arguments rejected; `${1-fast}` so an explicitly empty argument is validated too — a second instance found while writing the test |
| `PREFLIGHT_BASE=HEAD` exited 0 having inspected nothing | Equal bases, unresolvable refs and missing merge bases all fail closed |
| A failed `git diff` read as "no changes" | The primary diff's status is propagated; both traps refuse to PASS |
| Every annotated tag refused | Tags peeled with `^{commit}`; supported push types written down |
| Untracked files invisible to the gate | Refused by default, with a named escape |
| 19 requirement lines, 0 pins | `requirements.lock.txt`, 62 packages, applied as constraints; clean-environment evidence captured |
| CI "complete and verified", never executed | Four real runs cited with SHAs and conclusions |

### What still stands — five MAJOR findings

1. **A base that is a *descendant* of HEAD still inspects nothing.** Rejecting
   `base == HEAD` was not enough: when the base descends from HEAD the merge
   base *is* HEAD, so the three-dot diff is empty. Reachable by force-pushing
   backwards. `scripts/preflight.sh:35-43`.
2. **The cached-diff failure is still unchecked** — `preflight.sh:161`. Codex
   reproduced `exit 0 / PREFLIGHT PASSED` with only that call failing.
3. **The CI required-checks assertion is still substring matching**, unchanged
   from the previous review. Synthetic `diagnostic: PASS <name> NOT RUN` lines
   satisfy it. Minimum fix `grep -Fxq` on exact lines; better, have the gate
   emit a machine-readable result file.
4. **`PREPUSH_ALLOW_UNTRACKED=1` forfeits the guarantee it was added to
   provide.** Defensible as a documented human override; not a mechanical
   guarantee that tested content equals pushed content.
5. **Dependency coverage is incomplete.** A dependency added to
   `requirements.txt` but absent from the lock installs unpinned, and
   `pip check` does not detect the omission. Railway's install still does not
   use the constraints, so production resolution remains unpinned.

Also recorded: Codex declined to run `./check.sh full`, because the new harness
tests execute git commits and its constraints forbade commits. That is a fair
objection to the test design. And `test_harness_gates.py` still runs
`git commit-tree` against the real repository.

### The incident this cycle caused, and fixed

Writing those harness tests caused a real one. Run from inside the pre-push
hook, they inherited git's exported `GIT_DIR`, so fixture `git` commands
operated on the real repository: a fixture commit landed on
`ticket/BH-002-accounting-category-isolation`, and a fixture `git init` set
`core.bare = true` on the main clone. Both were detected within minutes — by
the hook refusing the push — and both were repaired from reflog and config.
`foundation/rc1-baseline` was never moved; verified against its reflog and
against origin. Nothing was force-pushed and no history was lost. `run()` now
strips every `GIT_*` variable, with two tests covering it.

It is worth stating plainly: the gate caught this, which is the argument for
having it. It is equally worth stating that the gate's own test suite was the
thing that broke the repository.
