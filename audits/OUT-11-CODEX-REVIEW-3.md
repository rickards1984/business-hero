Reviewed `2ef8f0d` against North Star P8.

**P1 — pacing remains unsafe.** At [outreach_autopilot.py:235](/Users/michaelrickards/dev/bh2-OUT-11/backend/services/outreach_autopilot.py:235), time is evaluated **before** acquiring the business lock. After reservation, neither claim nor dispatch validates the pacing token or expiry.

Reproduced through the real approval path with a fake provider:

1. First attempt reserves at 11:00.
2. Execution pauses before approval until 11:07.
3. First attempt sends at 11:07.
4. Another run sends a second email at **11:07**.

The stale `run_due` timestamp is fixed, but delayed attempts retain permission outside their slots. Read time after acquiring the lock and enforce pacing at the send boundary, including expired or superseded reservations. Add regression coverage for delays after reservation and while awaiting the lock.

**P2:** No additional findings.

**Backlog:** Previous Ruff finding closed; backend Ruff passes.

Other checks:

- Automatic sends enforce OUT-18 daily and monthly brand caps; another brand’s usage does not consume their allowance.
- Research leaves campaigns with valid automatic permission to the autopilot.
- No additional bypass found in OUT-6 gates, locked grant revalidation, reply exclusion, trust counting or tenant scoping.
- The new stale-time regression **fails without the fix**, verified by an in-memory mutation. It does not cover the remaining delay scenario.

Verification: **297 focused tests passed** using in-memory SQLite to preserve read-only operation. Additional cap and revoke-during-search probes passed. Expanded reply checks passed 62 tests; one concurrency test remained blocked by SQLite table locking after correcting the in-memory harness’s thread configuration. PostgreSQL concurrency, live delivery and `check.sh` were not verified.

No files modified, committed or pushed. Pre-existing untracked `data.db` left untouched.

**Verdict: REQUEST CHANGES.**