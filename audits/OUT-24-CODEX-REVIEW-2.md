# OUT-24 — Codex review 2 (verbatim)

Reviewed `git diff HEAD~1..HEAD` at 1f6c9e4.

Review 1 findings:

1. **Resolved:** expired proposed cards no longer block replacement; executing cards still block. The expiry UPDATE is scoped to the business, enrolment and `send_outreach` type.
2. **Resolved:** sequence proposals pass `one_card=True`; `outreach_replies.propose_answer` retains the default `False` and its existing business lock and reply-slot protection. The sequence test double passes `True`.
3. **Resolved:** rollback now has transaction-local lock and statement timeouts, plus an index-presence check after timeout.
4. **Resolved:** STEP 3 distinguishes daily capacity from cumulative enrolments.

**New findings: none at the requested severity bar.**

The UTC-aware bound datetime is compatible with PostgreSQL `timestamptz`. The additional expiry filter preserves eligibility for migration 040’s partial index. The UPDATE leaves executing cards and reply cards untouched; inspection found no new lock cycle or lost-send interaction with approve, dismiss or `list_open`.

Two non-blocking qualifications: SQLite’s test double stores ISO timestamps with `T`, which can misclassify same-day expiry against a space-separated datetime binding; production uses `timestamptz`, and real proposal inserts bind datetimes consistently. Also, rollback can briefly queue other work while awaiting its lock—the runbook’s “never” wording overstates the protection, although the timeout bounds are present.

Read-only inspection and an in-memory SQLite comparison completed. Full checks and PostgreSQL concurrency tests were not run. Nothing modified, committed or pushed.

VERDICT: APPROVE