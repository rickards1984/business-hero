# OUT-13 core — Codex CODE review 2 (verbatim)

Reviewed `git diff HEAD~1..HEAD` at 49ba8a2.

All seven original findings are resolved in their original scope:

| Finding | Resolution |
|---|---|
| 1. Contacted imports starve candidates | Resolved: durable classification excludes them from new candidates. |
| 2. Housekeeping consumes candidate budget | Resolved: candidate timing starts afterward. |
| 3. Uncertain sends bypass withholding | Resolved across all three readers; established contact remains exempt. |
| 4. Browser withholding stalls | Resolved: clock changes selector identity; identity stays stable between ticks. Hooks precede conditional returns. |
| 5. Transaction timeouts disappear | Resolved at the identified transaction boundaries, including recovery. |
| 6. Incorrect backlog deadline | Resolved using the earliest effective deadline. |
| 7. Missing escalation | Resolved through the tenant-scoped summary and home warning, as documented. |

Two new defects:

1. **P1 — Summary scrubbing can permanently skip businesses.** [outreach_erasure.py:461](/Users/michaelrickards/dev/bh2-OUT-13/backend/services/outreach_erasure.py:461). The text cast makes `LIKE` valid on PostgreSQL jsonb, but the query repeatedly selects up to 200 research settings documents without excluding cleaned documents or advancing a cursor. With 200 clean documents ahead of a legacy summary, that summary’s identifying domain survives indefinitely—even after the never-emailed prospect is erased—with no owner-visible exception. Reproduced in memory across three passes. **Fix:** use resumable keyset pagination or durable cleanup progress so every matching business is eventually visited; test beyond the selection limit.

2. **P2 — Contacted classifications become false dashboard erasure warnings.** [outreach_dashboard.py:260](/Users/michaelrickards/dev/bh2-OUT-13/backend/services/outreach_dashboard.py:260), triggered by the new persistence at [outreach_erasure.py:344](/Users/michaelrickards/dev/bh2-OUT-13/backend/services/outreach_erasure.py:344). `exceptions_for` and escalations exclude `contacted`, but `erasure_held` does not. An imported, already-emailed contact without a notice timestamp now appears under “Needs you” as past deadline and “being checked.” **Fix:** exclude `contacted` from that aggregation and add a dashboard regression test.

Contacted classifications also consume the existing 20-row recheck allowance, but cannot consume the separate new-candidate budget. Escalations add one tenant-scoped query per summary request; no additional qualifying defect found there.

Verification: read harness passed; all 30 erasure tests passed with the SQLite fixture redirected to memory; TypeScript passed. PostgreSQL and `check.sh` were not run. Working tree unchanged; nothing modified, committed or pushed.

VERDICT: CHANGES REQUESTED