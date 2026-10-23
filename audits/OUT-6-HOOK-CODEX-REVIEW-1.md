**REQUEST-CHANGES — one P1.**

**P1**

- [backend/services/aria_actions.py:507](/Users/michaelrickards/dev/bh2-OUT-6-review/backend/services/aria_actions.py:507): **Non-owner members can approve outreach.** The hook checks only that `user_id` is non-empty. The [API:73](/Users/michaelrickards/dev/bh2-OUT-6-review/backend/aria_actions_api.py:73) passes through an authenticated business member’s identity without checking ownership. A non-owner member can retrieve a card and approve its exact version, causing customer contact and metered usage. A temporary synthetic test confirmed the real hook sends with an unrelated non-empty user ID. Require active ownership of this business for outreach approval, with API regression tests for non-owner and platform-admin access.

**Backlog — non-blocking**

- [backend/tests/test_outreach_send_rls.py:131](/Users/michaelrickards/dev/bh2-OUT-6-review/backend/tests/test_outreach_send_rls.py:131): Worker exceptions other than `ActionRefused` are not propagated, and timed-out threads are not asserted finished. The duplicate-card test can report success when one approval sends and the other crashes unexpectedly. Capture every exception and require every worker to finish with an asserted outcome.
- [backend/tests/test_outreach_send_rls.py:230](/Users/michaelrickards/dev/bh2-OUT-6-review/backend/tests/test_outreach_send_rls.py:230): The lost-claim test changes status inside the approval’s own transaction. It proves rollback after a forced CAS failure, **not** concurrent dismissal. Add a separate-session edit/dismiss race; otherwise blocking or stale-version failures remain untested.
- [backend/tests/test_outreach_send_rls.py:205](/Users/michaelrickards/dev/bh2-OUT-6-review/backend/tests/test_outreach_send_rls.py:205): Only monthly last-slot concurrency is tested. Business/mailbox/campaign daily-cap races and concurrent pause/suppression/token revocation remain unproved. For example, two different recipients competing for the final mailbox slot are not exercised.

The remaining hook structure matches the contract: mandatory exact version, NULL/automation rejection, search before the claim transaction, `prepare_claim` before the conditional UPDATE, rollback and permit removal on claim failure, commit before dispatch, and no generic email bookkeeping. The hook introduces no early action lock. Subject/body-only edits and chat/voice exclusion are correctly wired; existing action and AUTO regression tests pass.

Verification:

- Requested four-file suite: **281 passed**.
- `./check.sh`: **4 passed, 0 failed, 1 skipped**; backend **2,708 passed, 257 skipped**.
- PostgreSQL: **not verified**. All six tests encountered setup errors because loopback connections were denied with `Operation not permitted`.
- Temporary reproduction removed; worktree clean. No commits, pushes, external network or real sends.