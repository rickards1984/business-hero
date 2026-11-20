# OUT-28a fix (044) — Codex code review 2 (verbatim)

Commit 1cf9ee6. Model gpt-6-astra, read-only sandbox, 20 Nov 2026.

---

REQUEST CHANGES

1. **Resolved — previous P1: historical message updates.** `backend/migrations/044_outreach_wording_moves.sql:98` preserves `OLD.sequence_version` when the enrolment is unchanged; inserts and enrolment changes still bind from the enrolment. Changing `enrolment_id` to NULL clears the version; clearing `step_id` remains necessary under the existing CHECK constraint.
   
   The original failure scenario—failed send → edit → erasure—is covered through real erasure at `backend/tests/test_outreach_edit_any_time_pg.py:168`. Historical updates and subsequent sending are covered at lines 158 and 191. I found no legitimate UPDATE requiring rebinding: sending creates a new message (`backend/services/outreach_send.py:465`), reply targeting updates that new record, and `retry_of` changes do not change its wording identity.

2. **Partially resolved — P2: retained foreign keys are not fully verified.** `backend/migrations/044_outreach_wording_moves.sql:47` correctly matches the removed key using both ordered `conkey` and `confkey`. Unexpected version keys and duplicate matches raise exceptions; missing retained keys also raise.
   
   However, the retained-key checks at **lines 68–77 only inspect `conkey`**, not `confkey`. Failure scenario: a drifted contact FK has the expected source columns but references campaign/prospect columns in the wrong order. The migration accepts it, although legitimate message inserts fail. The STEP 0/2 query at `audits/044-PROD-RUNBOOK.md:48` cannot detect this either.
   
   **Required:** verify the retained keys’ ordered referenced columns too, and expose them in the runbook query.

3. **Resolved — previous P2: unsupported rollback promise.** `frontend/client/src/lib/outreachErrors.ts:26` now says the result could not be confirmed and instructs refresh before retrying. A successful commit followed by a gateway 502/504 no longer produces “nothing was saved.” The assertion at `backend/tests/test_outreach_email_draft.py:126` follows the corrected wording.

4. **Resolved — previous P2: fresh harness omits 044.** `scripts/rls-local.sh:98` appends migrations 040–044 in filename order, including the erasure tables required by the new regression. A fresh harness now includes the fix rather than reproducing the old FK failure.

5. **Runbook hardening — P3: “trigger: new” verifies function text, not an active trigger.** `audits/044-PROD-RUNBOOK.md:56` searches all functions with that name for the string `044`. Failure scenario: `outreach_message_version` is missing or disabled; STEP 2 still reports `trigger: new`, although automatic binding does not execute. Check the schema-qualified function and its enabled INSERT/UPDATE trigger attachment through `pg_trigger`.
   
   Otherwise, STEP 0’s three enrolment keys and three step keys match 037; STEP 2 correctly expects only the version-pinning enrolment key to disappear.

Reviewed commit `1cf9ee6`. No files modified; tests and `check.sh` were not run in this read-only review.