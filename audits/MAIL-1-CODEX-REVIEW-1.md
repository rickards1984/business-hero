**REQUEST-CHANGES** — reviewed `origin/main..4dfba0b`. Two P1 findings block approval.

**P1**

- [mailboxes.py:93](/Users/michaelrickards/dev/bh2-MAIL-1-review/backend/app/email/mailboxes.py:93): **Connecting a second mailbox can move invoice chasing and general email off the owner’s mailbox.** An existing sole mailbox with `is_default=false` is AUTO-2’s effective default. Connecting outreach then marks outreach as default. Reproduced offline. The same problem occurs after disconnect leaves one unmarked mailbox. Preserve the effective default before adding another; reconnecting must also preserve an intentionally unset flag.

- [mailboxes.py:102](/Users/michaelrickards/dev/bh2-MAIL-1-review/backend/app/email/mailboxes.py:102): **Concurrent callbacks depend on an unestablished database constraint.** Both can read “no default” and mark different accounts default. Reproduced with interleaved callbacks without the external index. Migration 037 and its claimed unique index are absent from this commit’s repository; tests manufacture that protection. Establish the constraint dependency before shipping. Live existence remains unverified under the no-network restriction.

**Backlog — non-blocking**

- [mailboxes.py:42](/Users/michaelrickards/dev/bh2-MAIL-1-review/backend/app/email/mailboxes.py:42): Concurrent switches can lock different target rows, then deadlock or encounter uniqueness conflicts. Rollback protects the existing default, but one request fails. Serialize per business or retry.
- [router.py:1579](/Users/michaelrickards/dev/bh2-MAIL-1-review/backend/app/email/router.py:1579): Reconnecting Google clears the newly editable label through `display_name=None`; Microsoft replaces it with the provider’s name.
- [EmailSettings.tsx:330](/Users/michaelrickards/dev/bh2-MAIL-1-review/frontend/client/src/pages/EmailSettings.tsx:330): After a successful switch, a failed account refresh leaves stale default chips alongside a success message; refresh errors are only logged.
- [test_mailboxes.py:207](/Users/michaelrickards/dev/bh2-MAIL-1-review/backend/tests/test_mailboxes.py:207): The concurrency test’s fake async methods never suspend, so callbacks execute sequentially. It does not exercise the advertised race.

No cross-tenant path found in the reviewed operations; public account responses exclude credentials. OAuth state handling, scopes and `access_type=offline` are unchanged, and `consent` remains present. Actual refresh-token issuance and browser behaviour were not verified offline.

Verification: targeted tests **139 passed**; `./check.sh` **green**, including **1,994 passed, 50 skipped**. No tracked edits, commits or pushes; worktree clean.

Behaviour check after fixes: connect outreach while the owner’s sole mailbox is unmarked; confirm the owner remains the sending default.