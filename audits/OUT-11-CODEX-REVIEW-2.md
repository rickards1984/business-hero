**REQUEST-CHANGES — one P1 remains at `25165e0`.**

**P1**

- **Pacing still permits bunched sends.** [outreach_autopilot.py:166](/Users/michaelrickards/dev/bh2-OUT-11-review/backend/services/outreach_autopilot.py:166) reserves against the timestamp captured before `run_due` processes all businesses. If earlier businesses take seven minutes, a six-minute reservation is already expired when this business sends. Another scheduler can immediately send its next email. Reproduced **two accepted sends at the same actual timestamp**. Check and reserve pacing atomically with the claim using fresh time; a delayed attempt must not retain permission to send outside its slot.

**Backlog**

- **P2 — verification fails:** [test_outreach_autopilot.py:295](/Users/michaelrickards/dev/bh2-OUT-11-review/backend/tests/test_outreach_autopilot.py:295) assigns unused variable `m`, causing Ruff and `check.sh` to fail. Removing the assignment passes Ruff in an in-memory check.

Review-1’s revoked-grant resurrection is closed: reservation and release now reread settings under the shared lock. Ordinary overlapping runs are blocked, but pacing is **not closed generally**. The authority-snapshot and home-period fixes also check out. No additional defect found in grant revalidation, reply exclusion, trust counting, retained OUT-6 gates, tenant scoping or `_settle`.

Verification:

- Requested suite: **274 passed**.
- `./check.sh`: **3,344 passed, 306 skipped**, 220 subtests passed; fails only Ruff. Known OUT-7 flake did not occur.
- Additional probes: **4 passed, 1 reproduced the pacing defect**.
- Scheduler: **35 additions, zero removals**, CRLF preserved; whitespace check passes.

[Review-2 probes](/private/tmp/test_out11_review2.py) remain available. PostgreSQL concurrency and live delivery were not verified. No network, commit or push; worktree restored clean.