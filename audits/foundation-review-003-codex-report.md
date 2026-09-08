# Foundation review 003 — Codex report (ORIGINAL, UNEDITED)

Review of correction cycle 2, which Mike authorised as one further bounded
cycle. Everything below the rule is exactly what Codex returned.

| | |
|---|---|
| Reviewed commit | `c72d4fcec0e773e47f6b11a0c39e203b91fd702f` |
| Delta reviewed | `34861db..c72d4fc` |
| Reviewer | Codex CLI 0.153.4, `gpt-6-astra`, ChatGPT auth |
| Session id | `01a082ae-05f4-7a40-8857-9ff17b5d7fa5` |
| Started / ended | 2026-09-08T20:19Z / 20:22:29Z |
| Process exit | 0 |
| Usage reported by the tool | `tokens used 38,561` — not a bill |
| **Verdict** | **REQUEST-CHANGES** (third consecutive) |

**Cycle 2 of 2 is now spent.** Mike's instruction was to stop after this cycle
if material blockers remain. They do. No cycle-3 changes have been made.

Note: Codex did **not** run `./check.sh full`, on the grounds that the new
harness tests execute git commits, which its no-commits constraint forbade.
That is a fair objection to the test design and is recorded as-is.

---

Reviewed **c72d4fcec0e773e47f6b11a0c39e203b91fd702f**, exclusively **`34861db..c72d4fc`**, against both prior reports.

Read-only probes confirmed the findings below. Working tree remained clean. No edits, commits, network, database access, pushes or deployments. **`./check.sh full` was not run:** its new tests execute commits, contrary to this review’s constraints.

| Remaining blocker | Disposition | What remains |
|---|---|---|
| 1. Claims and acceptance requirements | **PARTIAL** | 032 runbook wording corrected; omitted PDF/export challenges restored. Explicit stale/out-of-order Stripe acceptance remains absent. CI evidence concerns an earlier commit. |
| 2. Dependency reproducibility | **PARTIAL** | Constraints and captured clean-install evidence improve CI reproducibility. Production/local resolution remains unconstrained; lock completeness is unenforced. |
| 3. Modes and CI assertion | **PARTIAL** | Mode validation resolved, including explicit empty arguments and extra arguments. Required-check assertion is unchanged and still accepts unrelated output. |
| 4. Diff failures and comparison scopes | **PARTIAL** | Primary diff failures, equal SHA and unavailable ancestry now fail. Cached-diff errors remain ignored; ancestry and fallback scopes still permit incomplete inspection. |
| 5. Committed content and tags | **PARTIAL** | Tag peeling and default untracked refusal resolved. The escape permits precisely the missing-input discrepancy this blocker required closing. |

**Findings — new or surviving correction defects**

- **MAJOR — distinct base SHAs can still inspect nothing.** `scripts/preflight.sh:35–43`: rejecting `base == HEAD` is insufficient. When the base is a descendant of HEAD, the merge base is HEAD and three-dot diff is empty. This occurs when force-pushing a branch backwards or checking an older branch against newer `origin/main`. Locally, `git diff c72d4fc...34861db` returned an empty list despite distinct trees. The resolver accepts this relationship.

- **MAJOR — cached-diff errors still report PASS.** `scripts/preflight.sh:161`: the assignment’s failure status is unchecked. An in-memory wrapper making only `git diff --name-only --cached` return 128 reproduced **exit 0 / PREFLIGHT PASSED**. Check this operation’s status explicitly.

- **MAJOR — CI assertion still accepts diagnostic text.** `.github/workflows/ci.yml:128`: all five synthetic `diagnostic:   PASS  <required> NOT RUN` lines satisfied the actual matcher. This is unchanged from the previous review. Minimum correction: `grep -Fxq` against exact, top-level result lines; stronger correction: a dedicated machine-readable results file emitted by the gate and validated for exactly the required successful checks.

- **MAJOR — untracked escape forfeits committed-content verification.** `.githooks/pre-push:90–109`: `PREPUSH_ALLOW_UNTRACKED=1` allows an imported helper or collected test absent from HEAD. Shell history does not prove irrelevance. It is defensible as a documented human override, **not** as satisfaction of the mechanical guarantee. Verify an isolated committed tree, or restrict exceptions to inputs demonstrably outside the gate. Advising users to ignore files also does not establish irrelevance.

- **MAJOR — dependency contract remains incomplete.** `.github/workflows/ci.yml:78–80`, `requirements.lock.txt:8–24`: constraints against the real install manifest are a valid shape. However, a newly added dependency absent from the constraints installs unpinned, and `pip check` does not detect that omission. Railway’s root manifest still does not select these constraints. Enforce complete resolution coverage and document/test the supported local/CI/production contract.

**Comparison cases**

| Case | Assessment |
|---|---|
| Fork PR | Base SHA with the expected merge checkout is reasonable; actual GitHub checkout availability **UNVERIFIED**. |
| First branch push | `origin/main` works with suitable ancestry. Missing/unusable refs can fall back to only `HEAD~1`, omitting earlier branch changes. |
| Shallow clone | Explicit missing ancestry correctly blocks. Automatic parent fallback can silently narrow scope. |
| Root commit | Always blocks without a usable distinct ancestor; whole-tree scanning could support legitimate work. |
| Force push | Three-dot is not the before/after tree comparison; backward pushes can scan nothing. Unavailable `before` still substitutes another scope. |
| Explicit unusable base | Nonempty invalid/equal/unrelated bases fail closed. An explicitly empty `PREFLIGHT_BASE` is treated as absent. |

`check.sh`’s argument guard behaved correctly in local probes; no further **mode-selection** bypass was found. Its full-mode guarantee remains limited by preflight.

The 21 harness cases exercise real scripts, but coverage is incomplete. Hook tests appropriately stub the expensive gate, yet the escape test proves permission, not input independence. Valid-mode tests inspect source strings; ancestry tests use the live repository rather than isolated event histories.

**GIT_* scrubbing fixes the recorded inherited-environment mechanism.** An extracted-helper probe with poisoned `GIT_DIR` and `GIT_CONFIG_*` correctly resolved the intended non-bare repository. However, `backend/tests/test_harness_gates.py:102–107` still deliberately runs `git commit-tree` in the real repository, and isolation tests do not themselves inject poisoned variables. The suite is therefore not wholly repository-isolated, although I found no remaining inherited-GIT_* route that redirects fixture commits to the live branch.

**UNVERIFIED**

Run **34268900401** and its logs cannot be authenticated offline. The citation in `docs/CURRENT_STATE.md:94–101`, if accurate, supports one successful run on **ddb6e3e**, not CI execution of the changed dependency installation or harness at **c72d4fc**. Clean-install results are captured evidence, not independently rerun verification. Full gate, remote event behavior, production/staging state and deployed behavior remain UNVERIFIED.

**VERDICT — REQUEST-CHANGES**

Foundation blockers, shortest path first: narrow evidence claims and preserve missing acceptance requirements; replace the CI matcher; finish dependency coverage; close committed-input verification; correct comparison scopes and propagate every diff failure.

Stripe and accounting implementation remain **RC1 lane release blockers**, not prerequisites to foundation-only approval.