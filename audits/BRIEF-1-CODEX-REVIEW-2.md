# BRIEF-1 — Codex review 2, targeted (preserved verbatim)

**Findings — not approved yet.**

- **P2: Retry cap and duplicate prevention are not atomic.** [whatsapp_briefings.py:259](/Users/michaelrickards/dev/bh2-BRIEF-1/backend/services/whatsapp_briefings.py:259) reads attempts before sending, without a shared lock or reservation. Concurrent schedulers can both send. An in-memory reproduction starting with two attempts finished with four. The documented single-replica constraint limits exposure, but this does **not** enforce the cap across replicas. Use a database-backed claim before sending.
- **P2: Logging failure defeats both safeguards even on one replica.** [whatsapp_service.py:212](/Users/michaelrickards/dev/bh2-BRIEF-1/backend/services/whatsapp_service.py:212) swallows logging errors. If Twilio accepts a message but its row is not saved, the next tick sends again; failed attempts whose logging fails likewise never reach the cap.

The original fixes are otherwise resolved by inspection:

- Zone-aware period bounds use the configured business timezone.
- Partial-payment and overdue invoices count at the corrected balance.
- Logged failures permit retries; test sends are excluded; success requires a SID. `related_entity_type` reaches both success and failure logs.
- NULL call outcomes no longer count as answered.

Legacy NULL `related_entity_type` rows are ignored. Old `daily_pulse`/`weekly_briefing` rows also have different message types, so that is harmless for migration from the old scheduler. Any previously sent **new-type** rows with NULL markers would not prevent a duplicate.

Read-only review; no changes. Ran the in-memory concurrency reproduction only; did not rerun `check.sh` or PostgreSQL tests.