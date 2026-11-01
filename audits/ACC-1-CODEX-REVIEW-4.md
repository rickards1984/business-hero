# ACC-1 Codex review 4 (quick targeted, commit 8f3d1d5)

Model gpt-6-astra · session 01a198be-469d-7f63-8b58-37c8db988936 · 22,152 tokens · verdict **APPROVE**

## Prompt

```
You are reviewing branch ticket/ACC-1-xero-sync in this repository, read-only. This is a QUICK TARGETED review (cycle limit reached): review ONLY commit 8f3d1d5 (`git show 8f3d1d5`), which fixes Codex review 3 (audits/ACC-1-CODEX-REVIEW-3.md). Do not re-review the rest of the ticket.

Check each review-3 finding is actually fixed and the fix introduces no regression:
1. `_lock` in backend/services/xero_sync.py: missing settings row is created insert-only (never UPDATE), then locked with FOR UPDATE; works on SQLite and PostgreSQL; concurrent creators cannot blank each other's settings.
2. Contact-email lookup failures (`lookup_emails` returns (found, failed)) make the invoice run incomplete so the invoice cursor does not advance (backend/main.py sync_xero_invoices).
3. `resolve()` refuses "hide" against an archived Xero counterpart (409) while "keep" can still restore.
Also the lower items: connection stamp order (xero_connections then accounting_connections) in background_sync, sync-all synced_at from the transaction result, settings PUT preserving xero_* and accounting_duplicates.

Production symptom to keep in mind: on main, POST /v1/accounting/sync-all logs "Transaction sync failed: parameter `request` must be an instance of starlette.requests.Request" and returns 200; confirm this branch's sync-all path cannot hit that.

Output: verdict APPROVE or CHANGES REQUIRED; list any P1/P2 with file:line and a concrete failure scenario. Be brief. Do not edit files, commit or push.
```

## Final message (verbatim)

**APPROVE** — no P1/P2 findings in commit `8f3d1d5`.

- Missing settings creation is insert-only; PostgreSQL then uses `FOR UPDATE`. SQLite uses a harmless self-update for locking. Neither path blanks existing settings.
- Failed email lookups mark invoice sync incomplete and prevent cursor advancement.
- Archived Xero counterparts reject **Hide** with 409; **Keep** can still restore.
- Connection stamp order, transaction-derived `synced_at`, and settings PUT preservation are fixed.
- Sync-all calls undecorated handlers via `.__wrapped__`, passing `request`; the reported nested SlowAPI request error cannot arise through those calls.

Source review only; tests and PostgreSQL concurrency were not run. No files changed.