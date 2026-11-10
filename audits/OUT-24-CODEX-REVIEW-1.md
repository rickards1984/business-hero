# OUT-24 — Codex review 1 (verbatim)

Reviewed `git diff origin/main...HEAD` at f8029f7.

1. **P2 — Expired cards permanently block replacement.** `backend/services/outreach_send.py:182` rejects cards selected by `OPEN_CARD_WHERE`, which includes expired rows still marked `proposed`. `aria_actions.list_open()` hides these without updating their status. After an unattended card expires, asking Aria for a replacement now fails with “already waiting”; preparation also keeps returning the expired card. **Fix:** under the business lock, transition expired proposed cards to `expired` before deduplication. Preserve blocking for `executing` cards. Add a regression test using elapsed expiry, not an explicitly dismissed card.

2. **P2 — Sequence-card deduplication incorrectly blocks reply cards.** `backend/services/outreach_send.py:182` also runs through `outreach_replies.propose_answer()` at `backend/services/outreach_replies.py:409`. Concrete scenario: the first email succeeded, a follow-up has an unknown outcome and remains `executing`, and the prospect replies to the earlier accepted email. Reply ingestion dismisses only **proposed** sequence cards; the executing card remains. The new guard therefore rejects the otherwise eligible grounded answer, despite its separate reply-slot authority and idempotency key. **Fix:** apply sequence-card deduplication specifically to `send_outreach` creation, keeping shared payload construction available to the reply path. Test this scenario while preserving the unknown send’s reservation.

3. **P2 — Rollback can block production without the advertised timeout bounds.** `audits/040-PROD-RUNBOOK.md:83` uses ordinary `DROP INDEX` without lock or statement timeouts. Unlike STEP 1, this can wait for an exclusive table lock and queue other access behind it. **Fix:** give rollback an explicit transaction with local lock/statement timeouts and instructions for timeout failure; verify the index remains present when rollback fails.

4. **P3 — STEP 3’s EXPECT conflates cumulative enrolments with daily intake.** `audits/040-PROD-RUNBOOK.md:105` expects the next research summary to keep more than five contacts. At a five-per-day warm-up limit, successful operation can add five or fewer while cumulative active enrolments exceed five. Existing waiting contacts and due follow-ups also consume capacity. **Fix:** verify cumulative enrolments can exceed five when capacity permits, while daily intake remains bounded by `capacity()`.

Read-only review completed. SQLite’s text-payload lookup worked in an in-memory check; the expired-card case matched as described. Full checks and PostgreSQL concurrency tests were not run. Both referenced OUT-23 review documents are absent from this checkout.

VERDICT: CHANGES REQUESTED