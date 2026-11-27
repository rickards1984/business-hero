# MSG-1 — Codex DESIGN review 4 (verbatim)

Targeted review of docs/MSG-1-DESIGN.md v4 (design only, no code) on d3e7ee6.

Reviewed `d3e7ee6` against review 3, serving North Star P4/P9 and the correctness prerequisite. **No P0/P1/P2 findings.**

- **§5.9 resolves the remaining P1.** Expiry now triggers fencing before reconciliation; persisted operation keys recover committed work after a crash; committed charges settle exactly once under the reservation lock; only the unused remainder becomes available. Unknown outcomes remain uncharged. The required tests cover committed-document recovery, expiry racing settlement, and refused writes from fenced workers.
- **§11 faithfully carries all five task-packet follow-up groups**, including tool-free chat charging, held-lot refunds, `send_quote_email`, deletion races, and migration provenance.
- **No new design defect identified in the v4 diff.** Previously resolved findings remain closed.

Implementation review should verify that fencing also covers writes already in flight when recovery starts, with the fence check and commit correctly serialised. This implements §5.9’s stated guarantee.

No files modified; no tests or `check.sh` run. This approves the design, not its implementation or production behaviour.

**Verdict: APPROVE with the recorded task-packet follow-ups.**
