# OUT-20 Codex review 3 (targeted, cycle 3 of 3)

Model gpt-6-astra · verdict **CHANGES REQUIRED** (2 × P2)

## Prompt

```
Read-only targeted re-review (cycle 3 of 3) of OUT-20 in this worktree: `git show HEAD` against your review 2 (audits/OUT-20-CODEX-REVIEW-2.md); response in the "Codex review 2" section of docs/OUT-20-TICKET.md. Confirm the 4 findings are fixed and proven, and say whether any case remains where the panel shows "Running" while research would refuse to search for a reason knowable in advance (or the reverse). APPROVE or CHANGES REQUIRED with P1/P2. Brief. Do not edit, commit or push.
```

## Final message (verbatim)

**CHANGES REQUIRED — 2 × P2.**

Review-2 findings **#1–4 are addressed in code**, but not all proven: #2 lacks a regression test; #4 mocks zero capacity rather than proving exhausted inbox/pilot behaviour.

Remaining mismatches:

- **P2 — “Running” despite a missing Companies House key.** [Research refuses before searching](/Users/michaelrickards/dev/bh2-OUT-20/backend/services/outreach_research.py:935), but the checklist never checks this prerequisite.
- **P2 — Reverse mismatch remains.** [Setup selects only the latest audience version](/Users/michaelrickards/dev/bh2-OUT-20/backend/services/outreach_setup.py:1140), and [launch restricts eligibility to those IDs](/Users/michaelrickards/dev/bh2-OUT-20/backend/services/outreach_launch.py:101). A newer draft can hide an older, still-current approved version with campaign capacity: panel says “Not running”, while research can search. Its additional privacy/template gates also deliberately allow reverse mismatches.

All 18 tests were blocked during fixture setup by the read-only environment’s lack of a writable temporary directory. No edits, commits or pushes.