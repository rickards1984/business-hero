# AUTO-1 — Codex reviews, verbatim

## Review 1

| | |
|---|---|
| Reviewed commit | `69b6405` |
| Session id | `01a15574-0db9-75c2-9e3e-c3b8e7bea36a` |
| Model | `gpt-6-astra` |
| Usage, as reported | `tokens used 55,816` |
| **Verdict** | **REQUEST-CHANGES** |

Verbatim:

---

**REQUEST-CHANGES** — at `69b6405`. The blocking findings concern North Star P4, P8 and correctness.

1. **P1 — Unknown outcomes are retried through fresh cards.** [automations.py:111](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/services/automations.py:111), [automations.py:227](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/services/automations.py:227). An unconfirmed send remains `executing`, with no invoice timestamp update. The next pass ignores that action and proposes another. `chased_now` protects only the current pass. **Reproduced: two passes produced two provider calls and two `executing` actions.** Persistently block unresolved attempts for that customer; also account for successful sends whose invoice bookkeeping failed.

2. **P1 — Separate runs can send duplicate chases and exceed limits.** [automations.py:165](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/services/automations.py:165), [automations.py:215](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/services/automations.py:215). Both runs can read the same available cap and customer history, then create independently claimable cards. **Reproduced with interleaved passes: two sends for the same invoice, both `done`.** The scheduler’s task guard prevents overlap through its entry point in one process; two processes have separate guards. A database-backed reservation must enforce customer spacing and business cap across runs.

3. **P1 — Permission and time-window checks become stale during a run.** [automations.py:152](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/services/automations.py:152), [automations.py:257](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/services/automations.py:257). Settings, time and account eligibility are captured before sending. If the owner switches off or pauses a customer while earlier emails are being sent, subsequent sends continue under the old settings. A pass beginning at 16:59 can continue after 17:00. Suspension or plan changes likewise leave the loaded business stale. Revalidate current authority and time before each send.

4. **P1 — An invoice settled after candidate selection can still be chased.** [automations.py:171](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/services/automations.py:171), [aria_actions.py:399](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/services/aria_actions.py:399). Candidate selection checks the receivables balance, but approval only rechecks existence, literal `paid` status and stage. **Reproduced: setting `paid_amount = amount` between selection and proposal still sent the chase.** Cancellation or a synced zero balance has the same gap. Apply the full receivables eligibility rule again before execution.

5. **P1 — Concurrent settings saves can restore revoked permission.** [automations_api.py:67](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/automations_api.py:67), [automations_api.py:49](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/automations_api.py:49). The merge reads and rewrites the entire document without concurrency protection. A rules update can read `enabled=true`, an owner’s off request can commit, and the earlier update can then restore `true`. Other settings can also be overwritten. The generic [settings PUT:1475](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/main.py:1475) permits the same stale-document overwrite. Protect both write paths with version checking or coordinated atomic updates.

6. **P2 — Manually approved chases are reported as autonomous.** [automations.py:202](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/services/automations.py:202), [home_summary.py:127](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/services/home_summary.py:127). Stage-4 cards carry the automation marker; the home filters by that marker without checking the approver. **Reproduced: an owner-approved stage-4 chase appeared in `recent_automated`**, feeding “on autopilot” and “on her own” wording. Distinguish automated proposal creation from automated execution.

The existing per-card claim, payload-version binding and already-chased-stage refusal remain intact. They do not establish send-once guarantees across newly created cards. The PostgreSQL JSON casts look appropriate, but the new tests exercise SQLite only.

Verification: `./check.sh full` passed — **1,879 passed, 33 skipped**; AUTO-1 separately **35 passed**. Important missing tests cover the scenarios above, real scheduler overlap behaviour, PostgreSQL concurrency, and generic settings writes. The scheduler test merely checks source strings.

`docs/AUTOMATION-AND-OUTREACH-PLAN.md` is absent from this checkout, so Mike’s referenced decisions could not be independently verified. No source changes, commits or pushes; worktree is clean.