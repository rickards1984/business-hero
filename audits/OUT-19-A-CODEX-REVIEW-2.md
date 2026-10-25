# OUT-19 part A — Codex review 2

- Commit reviewed: 4d2c6a3
- Model: gpt-6-astra · tokens used: 71,261
- Verdict: REQUEST CHANGES

## Prompt

```
You are the independent reviewer for OUT-19 part A, cycle 2 (RED: AI spend). Do not commit, push or modify files.
Review 1 and the builder's response are in audits/OUT-19-A-CODEX-REVIEW-1.md. Review commit 4d2c6a3 (`git show 4d2c6a3`) with the files at HEAD.
Check each of the eight findings is resolved and that the fixes add no new problem: in particular the draft path's finally-block recording (rollback then save then commit — can it lose the caller's state or mask the original error?), the global advisory lock's interaction with the business lock (always last?), the after-commit alarm hook, the estimate for failed calls, research's reserve now derived from the shared price table, and the PostgreSQL tests in backend/tests/test_ai_costs_pg.py.
If pytest cannot run in your sandbox, read the tests and say so.
Verdict APPROVE or REQUEST CHANGES with numbered P1/P2/P3 findings.
```

## Review (verbatim)

**REQUEST CHANGES** — `4d2c6a3`, which is also HEAD. This review serves the North Star’s correctness and stability prerequisites.

1. **P2 — Rolled-back alarms fire on a later commit.** [ai_costs.py:128](/Users/michaelrickards/dev/bh2-OUT-19/backend/services/ai_costs.py:128) registers a session-level listener without clearing it on rollback. I reproduced: record 60p against a 50p alarm → rollback → empty commit on the same session → alarm reports 60p, although the database contains zero rows. A subsequent real crossing can also produce duplicate alarms. Tie pending alarms to their transaction and discard them on rollback. The existing test closes the rolled-back session, missing this case.

2. **P2 — A successful response without usage is recorded as free and not estimated.** [outreach_setup.py:519](/Users/michaelrickards/dev/bh2-OUT-19/backend/services/outreach_setup.py:519) passes missing usage to `note`, which converts it to zero tokens. I reproduced a ledger containing `ai_pence=0`, one call and no estimated-call marker. Research similarly treats missing token usage as zero. Unknown usage needs the conservative estimate even when the response itself succeeds; add tests for absent and incomplete usage.

3. **P2 — Historical brand selection does not enforce UK month boundaries.** [outreach_pricing.py:57](/Users/michaelrickards/dev/bh2-OUT-19/backend/services/outreach_pricing.py:57) passes a date-only string when comparing against `timestamptz`. PostgreSQL interprets that boundary using its session timezone. With UTC, a brand created at **00:30 BST on 1 October** is included in September’s projection, potentially adding £79. Construct an explicitly timezone-aware London boundary and test the BST transition between months.

4. **P3 — Some invalid price configurations escape validation.** [ai_costs.py:66](/Users/michaelrickards/dev/bh2-OUT-19/backend/services/ai_costs.py:66) does not catch `OverflowError`. A valid JSON array containing a 400-digit integer reproduces an uncaught exception instead of rejecting the entire override. Because research computes a reserve at import time, this can also break module loading. Catch numeric overflow and add a regression test.

5. **P3 — The month selector temporarily mislabels financial figures.** [AdminDashboard.tsx:244](/Users/michaelrickards/dev/bh2-OUT-19/frontend/client/src/pages/AdminDashboard.tsx:244) changes the selected month while retaining the preceding report during loading. The heading no longer displays `report.period`, and the explanation always says “this month.” Clear or visibly mark stale data and describe the returned period. The included-brand branch at line 277 also omits its required incremental margin.

The eight previous findings stand as follows:

| Review 1 finding | Cycle 2 assessment |
|---|---|
| 1. Refused drafts disappear | Fixed for normal recording; validation happens after the ledger commit. Missing usage remains above. |
| 2. Failed calls disappear | Exceptions now receive estimates; draft SDK retries are disabled. |
| 3. Pricing | Shared research pricing and unknown-model refusal fixed; overflow remains above. |
| 4. Alarm concurrency | Global serialization addresses concurrent crossings; rollback handling remains broken. |
| 5. Concurrent first writes | Atomic upsert fixes the collision. |
| 6. Usage detail | Required purpose × brand × model aggregates are stored. |
| 7. Historical economics | Projection and incremental-margin labels fixed; UK boundary remains incorrect. |
| 8. Last month | Selector added; presentation issues remain above. |

For the **draft `finally` block**, current callers have no pending business writes at that point, so I found no concrete caller-state loss. However, a failure in `save()` or `commit()` replaces the draft exception as the propagated error, with the original retained as exception context. Recording failure is not recovered or tested.

For **lock order**, I found no new cycle in current callers. Research takes business locks before the advisory lock; the over-reserve branch updates an already-locked settings row. Draft recording commits before subsequent authority locks. “Always the last lock” is nevertheless too broad: ledger upserts themselves acquire database locks afterward.

The **PostgreSQL tests** exercise first-write accounting and concurrent crossing, but both crossing writers use business A. They do not exercise mixed draft/research business-lock paths. Their barrier does not force overlap at the vulnerable read, and timed joins never assert that workers finished. Add transaction-reuse alarm coverage and bounded, coordinated concurrency checks.

**Verification:** pytest could not start: `No usable temporary directory found`. I read both test files and ran the in-memory reproductions described above. No PostgreSQL tests or full checks passed in this review. Default prices remain approximate; the shared table alone does not validate them against [provider pricing](https://developers.openai.com/api/docs/pricing).

No files were modified, committed or pushed.
## Response

1. **Taken.**
   - Pending alarms live in `session.info`. They are raised by an after-commit hook and discarded by after-rollback and after-soft-rollback hooks; the hooks are registered once per session.
   - The test now rolls back, then commits empty on the same session (no alarm), and commits twice after a real crossing (one alarm).
2. **Taken.**
   - `note()` requires the call's conservative (input, output) maximum. Missing or incomplete reported usage is charged at that maximum and marked estimated.
   - Research's adapter charges the full reserve, marked estimated, when usage is missing; `run()` records the estimated flag.
   - Tests cover no usage, input only and output only (drafts), and no usage (research).
3. **Taken.**
   - Brand creation is compared in Python, as instants, against midnight London time at the period's end, whatever the database's timezone.
   - An unparseable creation time projects no revenue.
   - Test: a brand made at 00:30 BST on 1 October belongs to October, not September.
4. **Taken.** OverflowError is caught: a 400-digit price rejects the whole setting. Test added.
5. **Taken.**
   - Changing the month clears the report and shows "Loading … for {period}".
   - The copy names the returned period and says "projected".
   - The included brand shows its incremental margin (£0 − cost).

**Side notes:**
- **Recording failure in the draft path:** if a successful draft can't be recorded, the error propagates and no unrecorded draft is handed out. If the draft itself failed, its own error propagates and the recording failure is logged. Both have tests.
- **The lock wording:** now precise in the module and the ticket.
- **The PostgreSQL tests:**
  - The alarm crossing uses businesses A and B.
  - Workers must finish (asserted).
  - The barrier still can't force overlap at the exact read. With the lock removed, the alarm test failed in three of three runs.
