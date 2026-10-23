**APPROVE** at `6f412c8`. No P1 found. Review supports North Star P4/P8/P9.

Review 1 disposition:

| Finding | Result |
|---|---|
| P1: partial payment leaves old amount sendable | Closed: balance rechecked at `backend/services/aria_actions.py:214`. |
| P1: reply/Stop loses non-lead invoices | Closed: history expanded at `backend/services/chase_replies.py:234`. End-to-end probe confirmed both invoices remain stopped next week. |
| P1: changed customer receives another customer’s invoice | Closed: recipient revalidated at `backend/services/aria_actions.py:212`. |
| P2: sequential stage-4 cards both send | Original scenario closed: last-chased timestamp checked at `backend/services/aria_actions.py:217`. Concurrent variant below. |
| P2: stage-4 chat re-chase cannot be approved | Closed at `backend/services/aria_actions.py:624`; approval works once. |

**P1 list:** None.

**Backlog — non-blocking:**

- **P2: overlapping approvals can duplicate a chase.** `backend/services/aria_actions.py:749` — two separate combined cards both pass validation before either send updates the invoices. Both then send. Reproduced with interleaved approvals. The claim protects each card individually, not overlapping debts.
- **P2: due-date changes do not invalidate a card.** `backend/services/aria_actions.py:202` — draft a combined chase, extend one invoice’s due date into the future, then approve. It still sends that invoice with its old overdue date. Reproduced.

Verification: focused suite **227 passed**; `./check.sh` **green**, **2,780 passed, 261 skipped**. PostgreSQL JSONB equality, Decimal and date handling inspected; PostgreSQL and live providers were not exercised.

Behavioural check: reply to a combined chase, press **Stop**, and confirm every listed invoice stops.

No network, commits or pushes; `~/.openclaw` untouched. Temporary artifacts removed; worktree clean.