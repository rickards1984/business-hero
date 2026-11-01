# ACC-1b Codex review 1

Model gpt-6-astra · session 01a198d7-8053-79a3-be0b-18385158b4e7 · 33,299 tokens · verdict **CHANGES REQUIRED**

## Prompt

```
You are reviewing the uncommitted diff in this worktree (branch ticket/ACC-1b-xero-rate-limit), read-only. Run `git diff` and read docs/ACC-1b-TICKET.md. This is a small RED-tier fix: Xero's 60-calls-a-minute rate limit (HTTP 429) used to abort the whole first full sync; now `_xero()` in backend/services/xero_sync.py waits 61s and retries up to 5 tries.

Check: every Xero call the sync paths make (run, fetch_chart, fetch_invoices, lookup_emails) is covered exactly once (no nested retry multiplying waits); both XeroRateLimitError and httpx HTTPStatusError(429) are recognised and nothing else is retried; a lasting limit still fails without writing rows or advancing cursors; no blocking sleep on the server event loop (the sync runs in a worker thread with its own loop — confirm in backend/main.py and services/background_sync.py); worst-case added time is acceptable; tests in backend/tests/test_xero_sync.py (tail) actually prove it.

Output: APPROVE or CHANGES REQUIRED, with P1/P2 findings (file:line, concrete failure). Be brief. Do not edit, commit or push.
```

## Final message (verbatim)

**CHANGES REQUIRED**

- **P1 — backend/services/xero_sync.py:642:** Exhausted contact retries are swallowed, then retried afresh for every remaining contact. A lasting limit adds **244 seconds per contact**—four contacts exceed 16 minutes—and invoice rows are subsequently written (`backend/main.py:4331`). Re-raise exhausted rate limits before writes.
- **P2 — backend/services/xero_sync.py:205,212:** Chart handling also swallows exhausted rate limits. If encountered during `run()`’s account refresh, execution can continue and write bank rows instead of failing atomically.
- **P2 — backend/tests/test_xero_sync.py:752:** Exhaustion is tested only on the first bank fetch; no cursor assertion, exact five-attempt assertion, or exhausted chart/contact coverage. These tests miss the failures above.

All specified calls are wrapped exactly once; both 429 forms are recognised. Sleeps are asynchronous, and transaction workers use their own loops (`main.py:4177`, `background_sync.py:339`).

Tests inspected, not executed: their SQLite fixtures require filesystem writes, unavailable in this read-only session.