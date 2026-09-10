# Foundation review 001 — Codex RE-REVIEW of the corrections (ORIGINAL, UNEDITED)

Delta review of the correction cycle. Everything below the rule is exactly
what Codex returned. Nothing added, removed or softened.

| | |
|---|---|
| Reviewed commit | `34861db41c69d4ed206e5b76c7650f55c57d9a9b` |
| Delta reviewed | `3a388f9..34861db` |
| Reviewer | Codex CLI 0.153.4, model `gpt-6-astra`, ChatGPT auth |
| Session id | `01a08278-7c46-7da1-b3ea-df35759b3ec9` |
| Invocation | `codex exec -s workspace-write -c approval_policy="never"` |
| Started / ended | 2026-09-08T19:19Z / 19:23:47Z |
| Process exit | 0 |
| Usage reported by the tool | `tokens used 39,347` — not a bill |
| Worktree after | clean, unchanged; reviewer made no edits |
| **Verdict** | **REQUEST-CHANGES** (second consecutive) |

**This is cycle 1 of 1.** A further correction cycle needs Mike's approval.

---

Reviewed **34861db41c69d4ed206e5b76c7650f55c57d9a9b**, exclusively the delta **`3a388f9..34861db`**, including both reports.

Local `./check.sh full` passed: **382 tests, 104 subtests; five required steps passed; ESLint skipped**. Targeted in-memory probes reproduced the gate gaps below. Repository status remained clean. No edits, commits, pushes, network or database access.

| # | Disposition | Assessment |
|---|---|---|
| 1 | **PARTIAL** | Missing mandatory tools/directories now fail. However, `full` inherits preflight’s false-green paths below. Unknown mode arguments also silently select fast behavior (`check.sh:18,98`). |
| 2 | **PARTIAL** | All branch pushes now trigger CI, but comparison-base handling still fails open. `CURRENT_STATE.md:77` still calls unexercised CI “complete and verified.” |
| 3 | **PARTIAL** | Node 22/Python 3.12 alignment fixes the runtime mismatch. Dependency resolution remains unpinned; no compatibility matrix or clean-install evidence establishes parity. |
| 4 | **DEFERRED, ACCEPTABLY** | False baseline claims corrected; P0-7 records deletion handling, price discrimination and atomic replay protection. Explicit stale/out-of-order event acceptance remains missing. Implementation belongs in the RC1 lane, not this foundation handoff. |
| 5 | **DEFERRED, ACCEPTABLY** | P0-9a accurately records the isolation defect, ownership checks, scoped joins and regression test. This is a mandatory security release blocker, but does not itself prevent foundation-only sign-off. |
| 6 | **RESOLVED** | Evidence requirements now distinguish inventory from isolation and include policies, grants, defaults and negative tests. Technical correction: `role_table_grants` does not supply column grants; those need separate collection. |
| 7 | **RESOLVED** | Starter access expectations and board-meeting gate descriptions corrected. |
| 8 | **RESOLVED** | Founder tiers, decision-versus-implementation wording and read-only scope reconciled. |
| 9 | **PARTIAL** | Executable path fixed. “NOT YET APPLIED … established 8 Sep” is unsupported: absence from a documentation table and an older schema snapshot establish neither current state nor “never applied.” |
| 10 | **RESOLVED** | The three identified policy/status inconsistencies were corrected. External-consumer confirmation remains independently unverified. |
| 11 | **PARTIAL** | Non-HEAD revisions and tracked modifications are refused, including mixed-revision multi-ref pushes. Untracked source/test helpers remain excluded from cleanliness checking, so tested content can still differ from pushed content. Annotated tags introduce another problem below. |

**New findings and remaining correction defects**

- **MAJOR — preflight still silently skips inspection.** `scripts/preflight.sh:28–42,104,126`: explicit `PREFLIGHT_BASE=HEAD` exits **0**, reporting no changed files. A resolved ref without a merge base also fails open: the diff error becomes “no models.py changes” and is masked by the subsequent cached diff. An injected diff failure reproduced exit **0**.
- **MAJOR — required-check assertion accepts unrelated output.** `.github/workflows/ci.yml:123`: substring matching accepted synthetic diagnostic lines containing `PASS … NOT RUN` for all five checks. A harmless formatting change instead rejected genuine pass labels. The current format works, but this is not a sound independent assertion. Use an explicit results contract or, at minimum, exact top-level records.
- **MINOR — annotated tags are unpushable through the hook.** `.githooks/pre-push:40–52`: an annotated tag’s object SHA differs from its target commit, even when that target is HEAD. Checking out the target does not resolve the refusal. Lightweight HEAD tags pass; multiple refs pass only when every non-deletion SHA equals HEAD.
- **MINOR — new documentation claims conflict with evidence.** `audits/032-PROD-RUNBOOK.md:3` and `audits/FOUNDATION-REVIEW-001.md:95` assert production state while the latter’s limits explicitly mark migration state unverified. Its “six challenges … verbatim” claim at `:110` is also inaccurate: RC1 records five paraphrased challenges, omitting the shared PDF/manual-invoice contract and unpaid export deliverable.

Base-resolution assessment:

| Case | Assessment |
|---|---|
| Fork PR | Explicit PR base SHA is appropriate for the expected merge checkout; does not rely on the fork’s `origin/main`. Remote execution unverified. |
| First branch push | Falls back to `origin/main`; reasonable when available with shared history. Otherwise `HEAD~1` can inspect only the final commit of a multi-commit branch. |
| Shallow clone | Missing refs/parent correctly block; **present refs without reachable merge ancestry can silently pass**. |
| Detached HEAD | Works with a valid comparison base; detachment itself is harmless. |
| Base equals HEAD | CI substitutes the parent; standalone preflight silently scans nothing. A root commit instead blocks although whole-tree inspection could support legitimate work. |
| Normal/force push | An ancestral `before` SHA works. Three-dot comparison is not the old-to-new tree comparison for non-ancestral force pushes; unavailable `before` silently falls back to another scope. |

**UNVERIFIED:** GitHub execution, event checkout/ref availability, branch protection, clean dependency installs, production/staging state, applied migrations, deployed behavior and production exploitability. `git diff --check` reports whitespace in captured evidence/original report; this is not a behavioral blocker.

**VERDICT: REQUEST-CHANGES**

Remaining blockers, shortest path first:

1. **Foundation:** correct unsupported 032/CI claims and accurately preserve the outstanding acceptance requirements.
2. **Foundation:** resolve dependency reproducibility or explicitly document/test the supported compatibility contract.
3. **Foundation:** validate check modes and replace the fragile CI success assertion.
4. **Foundation:** propagate diff failures and define complete comparison scopes for equal bases, missing history and event types.
5. **Foundation:** ensure the hook verifies committed content, including untracked-input handling; support or explicitly define tag restrictions.

Stripe and accounting fixes remain **RC1 lane work and release blockers**, not prerequisites to foundation-only approval.