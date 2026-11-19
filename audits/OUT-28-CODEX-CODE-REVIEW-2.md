# OUT-28a — Codex code review 2 (verbatim)

Commit 92be354. Model gpt-6-astra, read-only sandbox, 19 Nov 2026.

---

REQUEST CHANGES

1. **Resolved — original P1: lapsed grants revived.** [outreach_manage.py:344](/Users/michaelrickards/dev/bh2-OUT28/backend/services/outreach_manage.py:344) now checks owner, mailbox, campaign version and sequence version against the pre-edit campaign. **Scenario:** changing the daily limit, then saving wording, no longer renews an invalid grant. [test_outreach_edit_any_time.py:249](/Users/michaelrickards/dev/bh2-OUT28/backend/tests/test_outreach_edit_any_time.py:249) checks invalid grants before and after saving for all three mismatch cases.

2. **Resolved — original P1: multiple placeholders cannot be repaired.** [OutreachEmails.tsx:93](/Users/michaelrickards/dev/bh2-OUT28/frontend/client/src/components/OutreachEmails.tsx:93) creates one shared draft; switching editors preserves it, and line 102 submits all accumulated changes. [outreachEmailDraft.ts:24](/Users/michaelrickards/dev/bh2-OUT28/frontend/client/src/lib/outreachEmailDraft.ts:24) preserves the other emails when editing one. **Scenario:** all three `[Your Name]` placeholders can now be removed before one save. The Node assertions cover this accumulation.

3. **Resolved — original P1: refresh bypasses stale-editor protection.** [outreachEmailDraft.ts:18](/Users/michaelrickards/dev/bh2-OUT28/frontend/client/src/lib/outreachEmailDraft.ts:18) copies emails and version together; `payload()` retains that version. [OutreachEmails.tsx:154](/Users/michaelrickards/dev/bh2-OUT28/frontend/client/src/components/OutreachEmails.tsx:154) disables saving when refreshed data differs. **Scenario:** another tab saves during editing; refresh now blocks saving, while an unseen update remains protected by the server’s version check. Tests verify helper behaviour, but do not exercise a React refetch.

4. **Resolved — original P2: bespoke replies inflate performance.** [outreach_manage.py:399](/Users/michaelrickards/dev/bh2-OUT28/backend/services/outreach_manage.py:399) restricts messages to `initial` and `followup`. **Scenario:** answering a recipient no longer adds another template send or counts replies to that bespoke answer. [test_outreach_edit_any_time.py:344](/Users/michaelrickards/dev/bh2-OUT28/backend/tests/test_outreach_edit_any_time.py:344) verifies exclusion using synthetic records; it does **not** exercise the real reply-send path requested previously.

5. **New — P2: test fixture can overwrite/delete files and collide across runs.** [test_outreach_email_draft.py:63](/Users/michaelrickards/dev/bh2-OUT28/backend/tests/test_outreach_email_draft.py:63) writes a fixed filename, then unconditionally removes it at line 71. **Failure scenario:** an existing file is overwritten and deleted; concurrent pytest processes can remove each other’s entry before esbuild reads it. Use an exclusively created, unique temporary file and clean up only that file. The Node assertions are meaningful helper tests, but the current file handling is unsafe.

No other actionable regression found in the diff. Static review only: tests and `check.sh` were not run because this session is read-only. No files changed, committed or pushed.