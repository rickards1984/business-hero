# OUT-26 — Codex code review 1 (verbatim)

Commit reviewed: 1691326.

---

None.

- The guard precedes all ORM reads. No expired-object access occurs between `_approve_outreach`’s commit and dispatch, including the reply wrapper.
- An uncommitted failed action CAS still fails the transaction guard before dispatch can commit anything.
- Reloading `business.id` afterward adds an ordinary read before locking; it introduces no row-lock inversion. Dispatch’s mutable eligibility checks still occur after `lock_business`.
- Autopilot and replies share the corrected boundary. Other approval action types do not use this transaction guard.
- Both tests target the failure mechanism. The SQLite test uses a simulated reload and `LocalActions`; the PostgreSQL test exercises real `auth._load_business`, ORM expiration and `aria_actions.approve`.

Tests were inspected, not run: their fixtures write files or database rows, outside this read-only review.

VERDICT: APPROVE