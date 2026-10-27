**REQUEST-CHANGES — two P1s.** Reviewed OUT-11’s diff at `2d534de`, against P4 standing permission and P8 trust.

**P1 — blocking**

- **Revoked permission can be restored.** [outreach_autopilot.py:205](/Users/michaelrickards/dev/bh2-OUT-11-review/backend/services/outreach_autopilot.py:205): after sending, the scheduler reads the settings document without locking, adds pacing, then replaces the whole document. If the owner’s revoke commits between that read and write, the scheduler restores the revoked grant. Subsequent automatic sends become authorised again without consent. Reproduced using a second session. Preserve settings under the shared lock.
- **Concurrent runs bypass pacing.** [outreach_autopilot.py:174](/Users/michaelrickards/dev/bh2-OUT-11-review/backend/services/outreach_autopilot.py:174): pacing is checked before claiming but recorded only after dispatch. Two overlapping runs can send to different recipients immediately; claim serialization never rechecks pacing. Reproduced two accepted sends at the same timestamp. The scheduler’s process-local task guard cannot protect concurrent schedulers. Reserve and check business-wide pacing atomically with the claim, using fresh time.

**Backlog — non-blocking**

- **P2: audit records a superseded grant.** [aria_actions.py:749](/Users/michaelrickards/dev/bh2-OUT-11-review/backend/services/aria_actions.py:749): `prepare_claim` writes the pre-search grant into `authority_snapshot`; the locked recheck does not replace it. Revoke and re-grant during search permits sending under the new grant but records the old one. Reproduced. Snapshot the grant validated under lock.
- **P2: home count does not implement “today”.** [useDashboardData.ts:151](/Users/michaelrickards/dev/bh2-OUT-11-review/frontend/client/src/hooks/useDashboardData.ts:151): outreach counts the seven-day `recent_automated` list without stating that period. Yesterday’s sends remain counted when today has none. Filter by UK calendar day or explicitly label the period.

Verification:

- Requested targeted suite: **269 passed**.
- `./check.sh`: **green**, **3,339 passed, 306 skipped**, 220 subtests passed. The known OUT-7 flake did not occur.
- Additional probes reproduced the three defects above; a revoke committed during reply search correctly blocked the claim and rolled back reservations.
- Scheduler diff preserves CRLF: **35 additions, no removals**; whitespace check passes with `cr-at-eol`.
- No additional defect found in reply exclusion, automatic-send trust counting, retained OUT-6 gates, tenant scoping, or `_settle`’s terminal `executed_at` update.

PostgreSQL concurrency and live delivery were not verified. No network, commit or push; worktree restored clean. Reproduction probes remain in [/private/tmp/test_out11_review.py](/private/tmp/test_out11_review.py).