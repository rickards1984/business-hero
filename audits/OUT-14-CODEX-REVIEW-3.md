**OUT-14 review 3 — `acf248d`. North Star P8.**

**P1:** None found.

**P2:** Billing-label precedence still differs from the billing service. In [outreach_dashboard.py:313](/Users/michaelrickards/dev/bh2-OUT-14/backend/services/outreach_dashboard.py:313), plan inclusion is checked only when no billing record exists. An included brand retaining an earlier payment record—for example after a plan upgrade—can therefore display “waiting for payment”, “paid” or “stopped”. The [billing service](/Users/michaelrickards/dev/bh2-OUT-14/backend/services/outreach_billing.py:198) gives inclusion precedence over that record.

Reproduced: dashboard **“waiting for payment”**, billing service **“included”**, `live=True`. Check inclusion immediately after free status, before interpreting the record, and add a precedence regression.

The other review-2 fixes check out:

- Meeting → Won is directly available and preserves the meeting.
- UI buttons remain disabled through saving and refresh; the server rejects a repeated undo with 409.
- Legitimate first marks succeed from all five unmarked stages.
- Paid brands without billing records now receive the paid label.

**Backlog:** Rendered UI/copy coverage when a frontend runner exists; durable DST, repeated-mark period and successful retained-history access tests.

**Verification:** 55 dashboard tests passed using an in-memory SQLite fixture; TypeScript passed. Additional probes confirmed first-mark behavior and the precedence defect. UI judged by source inspection. Full `check.sh`, browser behavior and PostgreSQL concurrency were not verified. No files modified, committed or pushed; existing `data.db` untouched.

Mike’s click path after correction: **Overview → Meeting → Won → Undo**, then inspect an included brand retaining an earlier billing record.

**Verdict: REQUEST CHANGES.**