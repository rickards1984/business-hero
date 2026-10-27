**REQUEST CHANGES — PROFIT-1 cycle 3, `405a569`, North Star P8.**

**P1 — blocking**

1. **Non-essential OpenAI paths still bypass the guard.**
   - [Assistant quote generation](/Users/michaelrickards/dev/bh2-PROFIT-1/backend/assistant_chat.py:190) uses direct HTTP without permission checking or cost recording. With non-essential permission denied, my mocked-provider probe completed a quote: **one provider request, zero recorded calls**.
   - Both receptionist preview paths remain unlabelled: [voice preview](/Users/michaelrickards/dev/bh2-PROFIT-1/backend/receptionist_api.py:599) and [preset preview](/Users/michaelrickards/dev/bh2-PROFIT-1/backend/receptionist_api.py:727), including their fallback models. These are optional previews, not live calls. The voice-preview probe reached the provider with the kill active.

   Gate and attribute these operations, including direct-HTTP accounting, with behavioural regressions.

2. **Call summaries were exempted rather than gated.**  
   [openai_utils.py:29](/Users/michaelrickards/dev/bh2-PROFIT-1/backend/openai_utils.py:29) labels summaries `receptionist`, making them essential. But [their caller](/Users/michaelrickards/dev/bh2-PROFIT-1/backend/main.py:1971) generates an optional summary while saving an already-transcribed call. The approved exemption covers **live receptionist calls**. My probe confirmed summary generation still reaches the provider at the kill threshold. Use a non-essential purpose and retain the existing `None` fallback. The new test currently enforces the exemption instead of closing the finding.

**P2 — required corrections**

1. **The PostgreSQL race regression is not deterministic.**  
   [test_profit_guard_pg.py:136](/Users/michaelrickards/dev/bh2-PROFIT-1/backend/tests/test_profit_guard_pg.py:136) uses `time.sleep(0.5)` before committing the writer. Nothing proves the scheduled check reached the contested operation. If its thread starts late, the test can pass with the lock removed. Also, `periodic_check()` swallows exceptions, so thread completion alone does not establish a successful check.

   The production lock change looks correct. Synchronise the test around an observed database wait/interleaving, assert successful completion, and demonstrate failure with the lock removed.

2. **Migration verification remains incomplete.**  
   [The runbook](/Users/michaelrickards/dev/bh2-PROFIT-1/audits/039-PROD-RUNBOOK.md:11) requests staging evidence; `039-STAGING-REHEARSAL.md` is absent. Instructions are not a completed rehearsal.
   
   STEP 2 also counts columns without inspecting CHECK definitions, despite claiming month/value constraints in its expectations. Its unconditional production-selector instruction conflicts with the new staging-first procedure. Record staging apply → rollback → reapply evidence, verify actual constraints, and make the project selection explicit for each environment.

**What is closed or verified**

- Assistant email drafting and admin support drafting return their existing fallbacks under `Paused`, with **zero provider requests**. Removing their labels in memory caused provider requests again.
- The estimator includes tools and model output limits. Its new regression fails with the old estimator restored in memory.
- Reported usage bypasses estimation entirely: a probe with large tools recorded exactly **1,200 input / 300 output tokens**, costing **0.4725p** for the configured `gpt-4o` rate. The larger fallback maximum does not inflate that normal path.
- Migration SQL now rejects invalid month numbers and negative values. PostgreSQL execution and mutation verification remain unverified in this review.

**Backlog / remaining inventory**

- [Customer support chat](/Users/michaelrickards/dev/bh2-PROFIT-1/backend/support_api.py:145) is still unlabelled and reaches the provider at the kill. If covered by the owner-chat exemption, label it explicitly.
- [Research comparison tooling](/Users/michaelrickards/dev/bh2-PROFIT-1/backend/services/research_compare.py:59) makes billed searches through accounted adapters without persisting their costs; reconcile this with “every AI call.”
- Retain paid-top-up profitability, alert-delivery visibility, and migration-cache handling backlog items.

**Verification:** 43 unit test functions passed using an in-memory replacement for the disk fixture; changed Python files pass Ruff. Additional mocked-provider and in-memory mutation probes produced the results above. I did not run artifact-writing `check.sh`, database-writing PostgreSQL tests, or migrations under the read-only instruction. No files were modified, committed or pushed.

**Verdict: REQUEST CHANGES.**