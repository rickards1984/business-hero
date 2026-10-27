**REQUEST CHANGES** — review 4 of `82f7ccd`, North Star P8.

**P1 — Retained reviews no longer consume campaign/pilot places.**  
At [outreach_research.py:746](/Users/michaelrickards/dev/bh2-OUT-19/backend/services/outreach_research.py:746), reviews reduce mailbox capacity but neither campaign usage nor pilot membership. Removing `places − unplaced` exposes those places again on subsequent attempts.

Reproduced independently with a 20-capacity inbox and:

- Pilot limit five.
- Campaign daily cap five, pilot unlimited.

Both cases purchased **three searches and retained 15 reviews**, with room still reported as five. Account for retained reviews against campaign/pilot places as well as their mailbox, without subtracting twice.

**P2 — The test-date fix remains dependent on the real clock.**  
[The fixed research timestamp](/Users/michaelrickards/dev/bh2-OUT-19/backend/tests/test_outreach_research.py:29) precedes approvals created during today’s test execution. Research refuses them as “approval is missing or out of date.” The three research suites produced **78 failures, 99 passes**; freezing the setup clock in memory yielded **177 passes**. Fixtures need a consistent clock.

**Verified closure and regression checks**

- Review-3’s shared-mailbox P1 is closed for the reported case. Its regression passes at HEAD and **fails with the parent’s capacity function restored in memory**.
- No double subtraction in the tested ordinary case: three reviews leave 17 places. No ready campaigns and excess retained reviews correctly produce zero room.
- Atomic enrolment, qualification rollback, search ownership/cleanup, manual pilot setting and lock order remain intact. The campaign/pilot accounting regression above is the exception.
- Merged research cost/router checks: **17 passed**. Send/OUT-16 suites: **155 passed**. No additional merge inconsistency found.

**Backlog:** PostgreSQL contention/lease-expiry and DST-transition coverage remain outstanding.

Verification used in-memory SQLite fixtures with bytecode/cache writes disabled; the research pass required the clock adjustment described above. `check.sh` and PostgreSQL verification were not run. No files modified, committed or pushed.