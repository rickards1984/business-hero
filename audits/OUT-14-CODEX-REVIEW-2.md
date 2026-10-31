**REQUEST CHANGES — OUT-14 review 2, `51f0133`.** North Star P8.

**P1:** None found. The retention exposure is fixed and regression-tested.

**P2**

- **Meeting → Won still loses the meeting through the UI.** [OutreachDashboard.tsx:174](/Users/michaelrickards/dev/bh2-OUT-14/frontend/client/src/components/OutreachDashboard.tsx:174) offers only “Undo mark” for Meeting/Won/Closed prospects. To mark a meeting as Won, the owner must undo it first, deleting its event. Allow progression directly and add a behavioural regression covering that click path.

- **Paid grandfathered brands are labelled “included”.** [outreach_dashboard.py:306](/Users/michaelrickards/dev/bh2-OUT-14/backend/services/outreach_dashboard.py:306) assumes a missing billing entry means included. Reproduced an extra brand labelled “included” while billing calculates **£79/month**. Derive the label from plan inclusion, free status and billing state, consistent with the billing service; regression-test the grandfathered case.

- **Repeated clicks can undo multiple historical marks.** [OutreachDashboard.tsx:152](/Users/michaelrickards/dev/bh2-OUT-14/frontend/client/src/components/OutreachDashboard.tsx:152) leaves Undo enabled during saving and refetching. Two requests against a Meeting → Won history remove both events. Guard the pending action through refresh; add a regression proving repeated activation removes only the intended latest mark.

**Backlog**

- The top-up regression checks only `topups_pence`; it would pass with the old misleading frontend wording. Add rendered-copy coverage.
- Add durable tests for repeated outcome kinds across periods, DST boundaries and successful retained-history access.
- Label results explicitly as **people with a meeting/win mark**, matching distinct-person counting.

Review-1 status: retention, failure-only summaries and stopped-brand handling have code fixes and behavioural regressions. Meeting preservation works through the API, but remains inaccessible through the normal UI. Top-up copy is corrected, with the coverage gap above. Loading/error states, outcome activity dates and referral wording are implemented.

**Verification:** 51 tests passed using an in-memory SQLite fixture; TypeScript passed. Additional probes confirmed distinct-person counting, period filtering, undo restoration and the billing-label defect. No competing production stage writer found. Full `check.sh`, browser/mobile behaviour and PostgreSQL concurrency were not verified. No files modified, committed or pushed; existing untracked `data.db` left untouched.

After fixes, click **Overview → Meeting → Won → Undo**: both period totals should initially remain, then only the win should disappear. Check a paid grandfathered brand’s label too.

**Verdict: REQUEST CHANGES.**