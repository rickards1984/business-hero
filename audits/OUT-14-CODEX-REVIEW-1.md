**REQUEST CHANGES — OUT-14 review 1, `e5e60a6`.** These findings affect North Star P8: trustworthy figures and honest reporting.

**P1**

- **Stage lists expose expired prospect details.** [outreach_dashboard.py:312](/Users/michaelrickards/dev/bh2-OUT-14/backend/services/outreach_dashboard.py:312) returns company, name and role without checking `retention_due_at`. The existing prospect reader redacts these after expiry. Reproduced with an expired prospect. Apply the existing retention projection and add a regression test.

**P2**

- **Progressing a meeting to Won erases the meeting result.** [outreach_dashboard.py:347](/Users/michaelrickards/dev/bh2-OUT-14/backend/services/outreach_dashboard.py:347) overwrites the sole outcome record; results also require that outcome to match the current stage. Reproduced: meetings falls from **1 to 0** after marking Won. Preserve dated outcome evidence separately from current pipeline position, with explicit undo semantics.

- **Aria falsely reports “Nothing needs you” when failures exist.** [outreach_dashboard.py:254](/Users/michaelrickards/dev/bh2-OUT-14/backend/services/outreach_dashboard.py:254) checks replies and approvals but ignores failures. Reproduced with a failed email. Include failures before giving the all-clear.

- **Stopped brands are reported as awaiting payment.** [outreach_dashboard.py:236](/Users/michaelrickards/dev/bh2-OUT-14/backend/services/outreach_dashboard.py:236) treats every `not brand_live(...)` as a payment problem. That includes an owner-cancelled brand whose paid period ended. Count actual payment-waiting states and display the real billing state.

- **Top-up copy conflates payment with AI allowance.** [OutreachDashboard.tsx:115](/Users/michaelrickards/dev/bh2-OUT-14/frontend/client/src/components/OutreachDashboard.tsx:115) says the allowance includes the full paid top-up, although `allowance_pence` adds only one third. A £30 payment adds £10 allowance. Label paid top-ups separately.

**Backlog**

- Add a stage-dialog loading/error state; failed requests currently leave an unexplained empty dialog.
- Include outcome marks in “last activity”.
- Describe positive replies as “interested or referred”; the summary currently calls both “interested”.
- Expand tests for DST boundaries, brand-filtered approvals, nonzero spend/top-ups, feature/history denial and prospect deletion. The current Aria grounding test bypasses its access-check helper.

Tenant-scoped queries, brand validation, owner-only API spend and outcome writes, cohort/category calculations, accepted-live email filtering and zero-denominator rates otherwise look consistent with the ticket. Settings writes preserve the outcomes key; no competing production stage writer was found.

**Verification:** 41 tests passed using an in-memory replacement for the file-backed SQLite fixture; additional probes reproduced the retention, outcome and summary defects. No files changed, committed or pushed. Full `check.sh`, browser/mobile behaviour and PostgreSQL locking were not verified.

After fixes, Mike’s click path: **Overview → Meeting → progress to Won → check period totals; inspect a failure-only summary and a topped-up/cancelled brand.**