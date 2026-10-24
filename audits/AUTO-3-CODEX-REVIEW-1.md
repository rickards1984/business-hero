**REQUEST-CHANGES** — three P1 blockers at `677d918`, affecting North Star P4/P8/P9.

**P1 — blocks**

- **Partial payments leave incorrect amounts sendable.** [aria_actions.py:692](/Users/michaelrickards/dev/bh2-AUTO-3-review/backend/services/aria_actions.py:692)  
  Draft a combined chase for £500 + £100, then record £400 against the first invoice. Approval still sends £500 + £100, total £600, although only £200 remains owed. Reproduced. Approval must compare current balances with the drafted amounts.

- **AUTO-2 loses every invoice except the lead invoice.** [chase_replies.py:229](/Users/michaelrickards/dev/bh2-AUTO-3-review/backend/services/chase_replies.py:229)  
  After a combined chase for A and B, a reply saying “I paid both invoices” is associated only with A. Pressing Stop stops A; B is automatically chased the following week. Reproduced through send, scan, resolve and subsequent autopilot run. Expand combined history into every listed invoice.

- **Customer ownership is not revalidated at approval.** [aria_actions.py:689](/Users/michaelrickards/dev/bh2-AUTO-3-review/backend/services/aria_actions.py:689)  
  Draft a combined card, then correct one invoice’s customer to a different customer. Approval still emails that invoice’s details to the original recipient. Reproduced. Revalidate every invoice’s current customer against the bound recipient before sending.

**Backlog — does not block**

- **P2: stage-4 re-chases escape stale-card detection.** [aria_actions.py:694](/Users/michaelrickards/dev/bh2-AUTO-3-review/backend/services/aria_actions.py:694)  
  Two combined cards drafted while all listed invoices are at stage 4 can both send: the first send leaves stages at 4, so the second passes. Reproduced with two proposals; production exposure requires duplicate outstanding cards. Compare `last_chased_at` as well as stage.

- **P2: the chat confirmation path produces an unusable stage-4 card.** [aria_actions.py:572](/Users/michaelrickards/dev/bh2-AUTO-3-review/backend/services/aria_actions.py:572)  
  For a single invoice recently chased at stage 4, `chase_again: true` drafts a card, but tapping it always fails because `4 >= 4`. Reproduced.

Verification: requested suite **220 passed**; `./check.sh` **green**, with **2,773 passed, 261 skipped**. Six isolated mocked probes confirmed the scenarios above. PostgreSQL-specific behavior was inspected, not executed against PostgreSQL.

No network, commits or pushes. Temporary artifacts removed; worktree clean.