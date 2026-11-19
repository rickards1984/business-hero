# OUT-28a — Codex code review 1 (verbatim)

Commit 2f4857e. Model gpt-6-astra, read-only sandbox, 19 Nov 2026. (A first attempt on 18 Nov failed: Codex workspace out of credits.)

---

REQUEST CHANGES

1. **P1 — Saving revives an invalid automatic-send grant.** [backend/services/outreach_manage.py:340](/Users/michaelrickards/dev/bh2-OUT28/backend/services/outreach_manage.py:340) checks the owner and mailbox but ignores the grant’s existing campaign and sequence versions. For example, changing the daily cap invalidates automatic sending; subsequently saving an email rewrites the stale grant to the latest versions and silently resumes automatic sends. Carry over only a grant valid against the **pre-edit** campaign. The tests cover another owner and no grant, but not a stale same-owner grant.

2. **P1 — The editor cannot repair the documented multiple-placeholder problem.** [frontend/client/src/components/OutreachEmails.tsx:151](/Users/michaelrickards/dev/bh2-OUT28/frontend/client/src/components/OutreachEmails.tsx:151) submits all three emails while allowing only one to be edited. With `[Your Name]` in all three, fixing Email 1 still submits invalid Emails 2 and 3, so the server rejects everything. Cancelling to edit another email discards the first correction. Allow all three corrections to accumulate before saving, and test the New Body scenario described in the ticket.

3. **P1 — Background refresh bypasses stale-editor protection.** [frontend/client/src/components/OutreachEmails.tsx:142](/Users/michaelrickards/dev/bh2-OUT28/frontend/client/src/components/OutreachEmails.tsx:142) initialises draft state once, but line 156 submits the latest `campaign.version` from props. If another tab saves while this editor is open, focus or periodic refetch updates the version without updating the local draft. Saving then overwrites newer wording successfully instead of returning 409. Capture the three-email snapshot and its version together when editing begins. Add a refetch-during-edit regression test.

4. **P2 — Bespoke answers inflate template performance.** [backend/services/outreach_manage.py:389](/Users/michaelrickards/dev/bh2-OUT28/backend/services/outreach_manage.py:389) counts every accepted outbound message joined to a sequence step. `reply_outreach` answers also carry a step ID—specifically the first step—and are stored with `kind='bespoke'`. Sending Email 1 and then answering its recipient counts as two sends of Email 1’s wording; subsequent replies can also distort its results. Exclude bespoke answers and test through the real reply-send path.

The tests contain meaningful regression assertions, particularly the wizard enrolment move, but miss these scenarios. The PostgreSQL race test also does not establish the claimed lock-order regression, as the ticket acknowledges.

Review was static and read-only. I did not run tests or `check.sh`: their database/cache/bytecode writes are incompatible with this session’s read-only filesystem. No files were changed, committed or pushed.