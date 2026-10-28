**REQUEST CHANGES — PROFIT-1 cycle 2, `c70a7cf`, North Star P8.** Most fixes work, but review 1’s gating finding remains open and the scheduled check introduces an alert race.

**P1 — blocking**

1. **Non-essential calls still bypass the kill switch.**  
   [`_refuse_if_paused()`](/Users/michaelrickards/dev/bh2-PROFIT-1/backend/services/profit_guard.py:383) explicitly permits unattributed calls. Assistant email drafting, support drafting and call summaries remain unattributed:
   
   - [assistant_tools.py:2881](/Users/michaelrickards/dev/bh2-PROFIT-1/backend/assistant_tools.py:2881)
   - [support_api.py:663](/Users/michaelrickards/dev/bh2-PROFIT-1/backend/support_api.py:663)
   - [openai_utils.py:28](/Users/michaelrickards/dev/bh2-PROFIT-1/backend/openai_utils.py:28)

   A mocked provider was invoked with non-essential permission denied. Scope and label these operations, preserve their fallbacks, and test each actual call path. **Review 1 P1 #3 is only partially fixed.**

**P2 — required corrections**

1. **Scheduled checks can duplicate threshold emails.**  
   [`periodic_check()`](/Users/michaelrickards/dev/bh2-PROFIT-1/backend/services/profit_guard.py:281) bypasses the advisory lock used by `ai_costs.record`. A scheduled check and a ledger writer can both read an absent marker; their upserts then both succeed and both queue email. Take the same lock before checking, or atomically claim the marker and send only for the successful claimant. Add a PostgreSQL race test involving the scheduled check; the existing concurrency test covers two ledger writers only.

2. **Missing-usage estimates are not the claimed request maximum.**  
   [`_request_estimate()`](/Users/michaelrickards/dev/bh2-PROFIT-1/backend/services/profit_guard.py:308) excludes tool definitions and assumes 4,096 output tokens when the request specifies no limit. Owner chat sends tools without an output limit. My probe returned the identical estimate, `(2, 4096)`, with and without a 100,000-character tool definition. Include billable request components and use an enforced limit or defensible model maximum. **Review 1’s conservative-estimation P2 remains partially open.**

3. **Migration verification is incomplete.**  
   The [runbook](/Users/michaelrickards/dev/bh2-PROFIT-1/audits/039-PROD-RUNBOOK.md:5) records a local rehearsal, but not the staging rehearsal and proven rollback required by AGENTS.md §7. The four PostgreSQL tests cover accounting and alerts; they do not test migration CHECK constraints, denied client access or rollback. Record that evidence before production approval.

**Review 1 closure**

| Finding | Cycle 2 assessment |
|---|---|
| P1 #1: platform UUID/FK incompatibility | Correct storage separation; PostgreSQL execution not independently verified here |
| P1 #2: async SDK accounting | Fixed; real SDK mocked-transport test passes and fails with the old wrapper |
| P1 #3: gating and quoting | Quoting and email-router paths fixed; other named paths remain open |
| P1 #4: voice overage and TTS | Overage fixed and regression detects removal; TTS recording added |
| P1 #5: absolute kill bypass | Fixed; regression fails with old `permits`; essential exemptions work as requested |
| P1 #6: research double counting | `accounted()` suppression works; removing it fails the regression |
| P2: missing usage/failures | Recording added, but estimates remain incomplete |
| P2: savepoint alert rollback | Fixed; removing queue restoration fails the regression |
| P2: voice/fixed-cost notifications | Scheduled check added, but concurrency correction required |
| P2: attribution leakage | Scoped reset works, including direct awaiting and `asyncio.to_thread`; remaining attribution gaps are covered by P1 above |

**Other checks**

- All three email service paths—single draft, multiple drafts and inbox briefing—returned fallbacks under `Paused`, with **zero provider requests**.
- The restructured quote HTTP path produced the expected result and recorded reported usage **once**.
- Async cancellation propagated as `CancelledError` and recorded one estimated failure.
- Scheduler line endings are intact: **1,252 CRLF, zero bare LF**.
- `has_platform_table` caches by database URL. Negative results remain cached until restart; migration-before-deploy matters.
- Migration 039 atomically revokes access from `PUBLIC`, `anon`, `authenticated` and `service_role`, and enables RLS without policies. That supports backend-only access, provided the backend role has the required ownership/privileges.
- The period CHECK validates format, not month validity; `value` has no non-negative constraint. The documented drop rollback is appropriate for an empty, pre-deployment table; after deployment it would destroy accounting and alert history.
- The schema record clearly labels its additions as pending, not verified production state.

**Backlog**

- Per-business profitability still excludes paid top-ups.
- Alert configuration still does not establish successful delivery.
- Strengthen ledger value/month constraints and document cache invalidation and post-deployment rollback.
- Admin refresh is fixed. Financial limitations are documented, although “keeps platform costs well below income” still overstates a guard that exempts essential spending.

**Verification:** 40 existing test functions passed using an in-memory replacement for the disk fixture; targeted mutation and mocked-provider probes supplemented them. Changed Python files pass Ruff. I did not run `check.sh`, PostgreSQL tests or migrations under this read-only authorization. No files were modified, committed or pushed.

After correction, Mike’s behaviour check is to cross both thresholds in a test environment, confirm one email per threshold, exercise every drafting/briefing fallback, and confirm owner chat and live calls continue.

**Verdict: REQUEST CHANGES.**