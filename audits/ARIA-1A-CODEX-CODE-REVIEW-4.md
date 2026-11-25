# ARIA-1a — Codex code review 4, narrow and final (verbatim)

Model gpt-6-astra, read-only sandbox, 25 Nov 2026.

---

APPROVE

1. **Review-3 finding 1 — fixed; previous P2 blocker closed.** [EmailsTab.tsx:273](/Users/michaelrickards/dev/bh2-ARIA1/frontend/client/src/components/EmailsTab.tsx:273), [inboxView.ts:17](/Users/michaelrickards/dev/bh2-ARIA1/frontend/client/src/lib/inboxView.ts:17). Open an unsorted mailbox and select Important: the initial status records `null`; the first sorting timestamp now triggers the current list loader. An unchanged timestamp causes no further reload.

2. **Review-3 finding 2 — fixed; previous P2 blocker closed.** [EmailsTab.tsx:275](/Users/michaelrickards/dev/bh2-ARIA1/frontend/client/src/components/EmailsTab.tsx:275). Request All time, then Today; resolve Today first. The late All-time response fails the request-token check before changing counts or `lastSortedRef`.

3. **Review-3 finding 3 — fixed; previous P2 blocker closed.** [EmailsTab.tsx:164](/Users/michaelrickards/dev/bh2-ARIA1/frontend/client/src/components/EmailsTab.tsx:164), [EmailsTab.tsx:317](/Users/michaelrickards/dev/bh2-ARIA1/frontend/client/src/components/EmailsTab.tsx:317). An old request failing after Money succeeds cannot clear its messages, change `hasEmailAccount`, or alter loading. Start Sort now on All, then select Money: completion invokes the current Money loader. Period changes likewise use the current status loader.

4. **P3 — non-blocking: committed tests prove helpers, but only partially prove component behaviour.** [test_inbox_view_frontend.py:69](/Users/michaelrickards/dev/bh2-ARIA1/backend/tests/test_inbox_view_frontend.py:69), [test_inbox_schedule.py:300](/Users/michaelrickards/dev/bh2-ARIA1/backend/tests/test_inbox_schedule.py:300). Source-string assertions would still pass if the three guards were misplaced or the loader refs stopped updating. They do not execute the late-error, loading, polling, or mid-sort view-change scenarios.

No new ordering or stale-state regression found in the scoped change. Polling retains its current-loader reference; the fresh sync-check path now uses it too.

Verification: in-memory execution passed the committed helper assertions and additional deferred-response checks using the actual component callbacks for findings 1–3, loading/account state, Sort now and the fresh sync check. These were not rendered React tests. The pytest fixture and `check.sh` were not run because they write files. No files modified, committed or pushed.