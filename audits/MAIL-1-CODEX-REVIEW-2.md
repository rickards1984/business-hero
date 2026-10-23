**APPROVE** — review 2 at `d3291d7`. Both original P1s are closed by the implementation; no new P1 found. This serves correctness and tenant isolation (P9).

**P1 list:** None.

Verified:

- Both callbacks snapshot **before** upserting. Settlement preserves the previously sole mailbox, including when that mailbox is itself being reconnected.
- Callback settlement and Make default share the per-business advisory lock. Lock acquisition, reads and writes stay in one transaction through commit; `get_session_context()` does not enable autocommit. This is compatible with transaction pooling and removes reliance on 037’s index. Hash collisions would serialize unrelated businesses, not mix their data.
- Snapshot reads and label updates are business-scoped. An additional local probe confirmed that reconnecting a same-address mailbox leaves the foreign business’s label untouched.

**Backlog:**

- **P2 — failed snapshot needs recovery:** [router.py:1547](/Users/michaelrickards/dev/bh2-MAIL-1-review/backend/app/email/router.py:1547). If the snapshot fails but the upsert succeeds, settlement is skipped. Adding a second mailbox to a sole unmarked mailbox leaves chasing paused until Make default; reconnecting can lose its label. It correctly avoids guessing a sender.
- **P2 — concurrent rename can be overwritten:** [mailboxes.py:132](/Users/michaelrickards/dev/bh2-MAIL-1-review/backend/app/email/mailboxes.py:132). A label changed after the snapshot can be replaced by the old snapshot label during settlement. Reproduced locally; the default lock does not protect rename.

**Verification:**

- Requested mailbox/chase tests: **81 passed**.
- `./check.sh`: **green** — 1,999 passed, 52 skipped; TypeScript, syntax and Ruff passed.
- Local Postgres tests: attempted because port 54329 is listening; **both errored before setup** with sandbox `Operation not permitted`. Concurrency could not be independently rerun; no index was changed.
- Worktree restored clean. No commits, pushes or external network access.

Behaviour check: in Email settings, connect a second Google mailbox and confirm the original retains **Default**; reconnect the original and confirm its label remains. Browser behaviour was not exercised here.