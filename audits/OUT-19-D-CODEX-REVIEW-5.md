**P1:** None. Campaign/pilot accounting is fixed. Both regression variants fail with the parent’s capacity function restored. Independent probes found no double counting across campaign, pilot, inbox or brand limits, including reviews without a matching ready campaign.

**P2 — Tests still depend on execution time.** [setup_clock()](/Users/michaelrickards/dev/bh2-OUT-19/backend/tests/test_outreach_research.py:149) freezes setup only. Afterwards, [qualified()](/Users/michaelrickards/dev/bh2-OUT-19/backend/services/outreach_manage.py:162) uses the real clock against approvals stamped at 06:30 UTC.

Simulating 00:59 UTC produced **51 failures, 128 passes**. A separate probe changing only `outreach_send.now` rejected a valid contact at 00:00 and 06:00, but accepted it at 07:00 and 23:00. Freeze the runtime clock consistently too, preserving explicit lease-test clock advances.

**Backlog:** PostgreSQL contention/lease-expiry and DST-transition coverage remain outstanding.

At the current clock, **179 tests passed** using in-memory SQLite. Earlier regression tests passed. No files changed; `check.sh` and PostgreSQL verification were not run.

**Verdict: REQUEST CHANGES — North Star P8.**