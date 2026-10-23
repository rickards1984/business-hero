**APPROVE — no P1 findings.** Review 1’s owner-authorisation P1 is closed.

[auth.py:255](/Users/michaelrickards/dev/bh2-OUT-6-review/backend/auth.py:255) preserves the platform admin’s own JWT identity when selecting a business. [aria_actions_api.py:73](/Users/michaelrickards/dev/bh2-OUT-6-review/backend/aria_actions_api.py:73) passes that identity to the hook. [aria_actions.py:502](/Users/michaelrickards/dev/bh2-OUT-6-review/backend/services/aria_actions.py:502) requires active ownership of that business; platform-admin status alone grants no approval authority. Ownership is checked again under a membership-row lock before commit.

Exact-version approval, NULL-owner/automation rejection, search-before-claim, reservation rollback and permit removal, commit-before-dispatch, subject/body-only edits, and chat/voice exclusion match the contract. No regression found in the four existing action types or AUTO-1/AUTO-2.

**P1**
- None.

**Backlog — non-blocking**

- [aria_actions.py:543](/Users/michaelrickards/dev/bh2-OUT-6-review/backend/services/aria_actions.py:543): The new membership lock follows `prepare_claim`’s action lock, extending the documented “action last” order. Document and test this ordering with membership writers. A writer holding membership then requesting business/action locks could deadlock with approval; no current opposing writer was established.
- [test_outreach_send.py:960](/Users/michaelrickards/dev/bh2-OUT-6-review/backend/tests/test_outreach_send.py:960): Authorisation tests call the service directly. Add an API/auth-chain regression for a platform admin selecting another business. A future identity-substitution bug at that boundary would escape these tests; the current chain is correct by inspection.
- [test_outreach_send_rls.py:286](/Users/michaelrickards/dev/bh2-OUT-6-review/backend/tests/test_outreach_send_rls.py:286): Sleeping does not prove dismissal reached the blocked UPDATE. A delayed worker can start after approval commits and still satisfy every assertion. Synchronise on demonstrated database blocking.
- [test_outreach_send_rls.py:213](/Users/michaelrickards/dev/bh2-OUT-6-review/backend/tests/test_outreach_send_rls.py:213): Monthly last-slot coverage does not establish business/mailbox/campaign daily-cap or pause/suppression races. Two recipients competing for the final mailbox slot remain untested.

The race helper now rejects crashes, hangs and missing outcomes. The injected lost-claim test proves rollback; it does not itself prove concurrent dismissal.

Verification:
- Requested four-file suite: **286 passed**.
- `./check.sh`: **4 passed, 0 failed, 1 skipped**; backend **2,713 passed, 259 skipped**.
- PostgreSQL: **Claude reports 8 passed; not independently verified here because this sandbox cannot reach loopback Postgres**.
- Worktree clean; removed the empty test-generated `data.db`. No commits, pushes or external network access.

No new UI behaviour to click for this hook-only review; live sending remains outside this approval.