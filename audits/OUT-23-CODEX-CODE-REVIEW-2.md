# OUT-23 Part A — Codex code review 2 (targeted, verbatim)

Commit reviewed: a2bf1a6 (fixes for review 1). Prompt: diff eb6e350..a2bf1a6.

---

1. **P2 — Mixed blockers produce a false “next weekday” explanation.** [outreach_bank.py:359](/Users/michaelrickards/dev/bh2-BANK/backend/services/outreach_bank.py:359). If campaign A has a full pilot but a healthy inbox, and campaign B has pilot room but a failed inbox, neither `all(reasons)` nor the pilot check succeeds. The fallback claims today’s places are used, although no daily allowance need be exhausted and tomorrow will not resolve either blocker. **Fix:** derive reasons per campaign and report the actual combination; only promise a daily reset when daily capacity is the blocker. Add this mixed-blocker regression.

2. **P2 — Thread liveness does not prove the claimed database interleavings.** [test_outreach_bank_pg.py:106](/Users/michaelrickards/dev/bh2-BANK/backend/tests/test_outreach_bank_pg.py:106). `join(1.5)` proves only that the other thread has not finished. Connection acquisition or scheduling can delay it until after drain release, allowing a serial execution to pass. The approval test additionally ignores `early`. The service paths do acquire shared business locks, but these assertions do not verify that contention occurred. **Fix:** identify both PostgreSQL sessions and wait for evidence that the second is blocked by the drain, such as `pg_blocking_pids`, before releasing it. Assert that observation for every claimed interleaving.

3. **P2 — Manual-enrolment failure can pass unnoticed.** [test_outreach_bank_pg.py:120](/Users/michaelrickards/dev/bh2-BANK/backend/tests/test_outreach_bank_pg.py:120). The helper captures exceptions into `other`, but this test never checks it. Manual enrolment can wait, then raise after acquiring the lock; the drain’s successful insert still satisfies every assertion. **Fix:** assert successful manual enrolment and that its returned item identifies the same enrolment created by the drain.

4. **P2 — The migrated PostgreSQL test mixes frozen and wall-clock time.** [test_outreach_setup_rls.py:161](/Users/michaelrickards/dev/bh2-BANK/backend/tests/test_outreach_setup_rls.py:161). The inherited `pg` fixture freezes `outreach_send.now()` at **23 October 2026**, which research uses when storing `captured_at`. The new drain uses `datetime.now(timezone.utc)`. After 15 November at 11:00 UTC, those prospects fall inside the five-day margin and the expected twelve enrolments become zero. **Fix:** use one controlled instant for research, stored timestamps, mailbox health and drain.

The all-campaign ledger and deadline-ordering fixes address findings 1 and 2 from review 1. Other campaigns’ campaign/pilot balances remain isolated by campaign ID. No files modified; tests were not run because their fixtures write databases/files and this review is read-only.

VERDICT: CHANGES REQUESTED