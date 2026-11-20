# OUT-28a fix (044) — Codex code review 1 (verbatim)

Commit 379d87b. Model gpt-6-astra, read-only sandbox, 20 Nov 2026.

---

REQUEST CHANGES

1. **[P1] Dropping the FK leaves a trigger that breaks erasure after wording changes.**  
   [044_outreach_wording_moves.sql:42](/Users/michaelrickards/dev/bh2-OUT28fix/backend/migrations/044_outreach_wording_moves.sql:42) drops the constraint, but [037_outreach_core.sql:624](/Users/michaelrickards/dev/bh2-OUT28fix/backend/migrations/037_outreach_core.sql:624) still defines `outreach_bind_message_version()`: **every message UPDATE** replaces its version with the enrolment’s current version.

   Concrete scenario: a failed v1 email exists; saving moves its enrolment to v2; the never-contacted prospect later reaches its erasure deadline. [outreach_erasure.py:356](/Users/michaelrickards/dev/bh2-OUT28fix/backend/services/outreach_erasure.py:356) clears message references before deletion. That UPDATE triggers rebinding to v2 while `step_id` still identifies v1. The retained step FK rejects it, rolls back erasure and leaves an error exception.

   Update the trigger to preserve historical version binding during unrelated updates, retaining insertion and identity safeguards. Add a PostgreSQL regression covering **failed send → wording edit → deadline erasure**. The new negative test at [test_outreach_edit_any_time_pg.py:145](/Users/michaelrickards/dev/bh2-OUT28fix/backend/tests/test_outreach_edit_any_time_pg.py:145) misses this: its expected `IntegrityError` also occurs for an entirely legitimate update.

2. **[P2] Definition matching can falsely report “already applied” while the blocking FK remains.**  
   [044_outreach_wording_moves.sql:34](/Users/michaelrickards/dev/bh2-OUT28fix/backend/migrations/044_outreach_wording_moves.sql:34) compares reconstructed SQL against one exact, unqualified string. Schema qualification depends on PostgreSQL’s deparser/search-path behaviour; this is not a portable identity check across environments. PostgreSQL’s own [discussion of this behaviour](https://www.postgresql.org/message-id/CAP53PkyRA9z5Sg2WKgTZ1NmTLcqA5VR_MRAWFcUWrjAjMwwcmw@mail.gmail.com) illustrates the problem.

   Concrete scenario: the definition contains `REFERENCES public.outreach_enrolments(...)`, or an additional constraint clause. `found` becomes NULL and the migration commits its “already applied” notice, although saves still fail. The multiple-match exception does not protect this path.

   Match relation OIDs and ordered column identities through `conkey`/`confkey`; distinguish genuine absence from an unexpected constraint definition. Verify retained identity/step constraints too. Runbook STEP 2 would catch the ordinary no-op, but STEP 0/2 only inspect version-related FKs and cannot establish all the claimed retained invariants.

3. **[P2] The shared 5xx message promises a rollback it cannot establish.**  
   [outreachErrors.ts:24](/Users/michaelrickards/dev/bh2-OUT28fix/frontend/client/src/lib/outreachErrors.ts:24) says “nothing was saved” for every 5xx.

   Concrete scenario: `save_emails` commits successfully, then a gateway returns 502/504 before the browser receives the response. The wording and enrolments have changed, but the screen explicitly says otherwise and invites another attempt. This helper also handles other outreach mutations and reads.

   Use uncertainty-aware wording: “We couldn’t confirm the result. Refresh to check the saved state before trying again.” The 4xx handling does not introduce HTML execution at the inspected React call sites, and I found no concrete raw-exception disclosure in the inspected refusal paths. However, a 400-character limit is not an internal-detail sanitizer; safe detail remains a backend responsibility.

4. **[P2] A fresh documented PostgreSQL harness does not apply 044.**  
   [test_outreach_edit_any_time_pg.py:129](/Users/michaelrickards/dev/bh2-OUT28fix/backend/tests/test_outreach_edit_any_time_pg.py:129) requires the removed FK, but [scripts/rls-local.sh:97](/Users/michaelrickards/dev/bh2-OUT28fix/scripts/rls-local.sh:97) only appends migrations through 039, and the imported fixture does not apply 044.

   Concrete scenario: another reviewer recreates the harness using `scripts/rls-local.sh up` and runs these tests. They encounter the original FK failure despite checking out the fix. Integrate 044 into reproducible harness setup, including necessary prerequisites, or document an explicit local application command. The accepted/failed real-send histories are meaningful regressions, but should also verify sending the next appropriate step after moving an enrolment with history.

The **constraint-removal direction is appropriate for E1**: retained FKs preserve business/campaign/prospect/enrolment identity and historical step identity. I found no message–enrolment history join requiring equal sequence versions in the requested services. Preparation checks current enrolment/campaign/step equality; executing-card exclusion protects the send interval. Refusing to move enrolments with history would contradict E1.

The transaction and timeout settings are sensible. The rollback restores the original FK and correctly warns that it cannot be reapplied after divergent history exists; staging must likewise remain free of intervening wording edits during rehearsal.

Read-only review completed. No files changed; tests and `check.sh` were not run.