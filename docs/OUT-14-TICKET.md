# OUT-14 — The outreach dashboard

**Tier:** YELLOW. It reads counts the owner acts on, and adds one owner write: marking a meeting or a win. It is tenant-scoped, and its counts are shared with Aria. **Builder:** Claude. **Reviewer:** Codex. **Tests first.**

**Design:** `docs/OUT-1-DESIGN.md`, Overview, plus the count definitions at line 46. OUT-18 adds the brand switcher ("All · each brand, each with its own pipeline, replies and results").

**Decided by Mike, 30 Oct 2026:**
1. **The layout,** as approved: the brand switcher, then Aria's summary, Needs you, the pipeline, results for a chosen period, and spend.
2. **Meetings and wins are marked by the owner.** On a prospect, one tap: "Meeting booked", "Won" or "Closed". It can be undone, and who and when are recorded. The dashboard counts only these confirmed marks; it never infers a meeting or a win from interest.
3. **The spend panel is shown to the owner only.** Staff see the pipeline and results, not money.

## Layout (approved)

```
Outreach  [ All brands | New Body | FitFutures ]

Aria: 14 people contacted this week, 3 replied, 1 interested. Two replies need you.   [Ask Aria]

NEEDS YOU          2 replies waiting · 1 approval · 0 failures
PIPELINE           Found > Ready > Contacted > Replied > Interested > Meeting > Won  (Closed)
RESULTS            [This week | This month | All time]
SPEND THIS MONTH   (owner only) per brand: AI spend of allowance · budget · top-ups
```

## Definitions (shared by the screen and Aria)

Every number is computed from stored records by one function, `services/outreach_dashboard.py`. The screen and Aria's tool use the same numbers. Each brand counts its own records:
- prospects belong to a brand through their audience (`lia_id` → compliance brand);
- messages belong to a brand through their campaign.

**Human reply:** a reply categorised as interested, question, not now, unsubscribe, objection, wrong person or referral. These are the categories the existing summary uses. Bounces, out-of-office replies, our own sent messages, complaints and unknown categories are not human replies.

**Positive reply:** interested or referral.

**Pipeline**: the current position of every prospect, each counted once at its furthest stage.

| Stage | A prospect is here when |
|---|---|
| Found | captured, but not eligible to contact: waiting for review, or blocked |
| Ready | eligible, and never contacted |
| Contacted | at least one accepted live outbound email, and no human reply |
| Replied | a human reply that isn't positive |
| Interested | a positive reply |
| Meeting / Won / Closed | the owner's mark, which outranks everything above |

"Accepted" means the provider accepted the email, not that it was delivered. Imported history (`origin = 'import'`) never counts as contact. A stage opens the list of the people in it.

**Results, for a period: this week (the last 7 UK days), this month (the UK calendar month), or all time.**

Each figure is labelled on screen with how it's counted.
- **Contacted:** unique prospects whose *first* accepted live email falls in the period. This is the cohort.
- **Replied** and **Positive:** unique people in that cohort with a human or positive reply, whenever it came.
- **Reply rate** and **positive rate:** replied ÷ contacted, and positive ÷ contacted. With nobody contacted, the rate shows as unavailable, never 0%.
- **Emails sent:** accepted live outbound emails dated in the period (cold emails and replies).
- **Objections** and **bounces:** replies of that category received in the period.
- **Meetings** and **wins:** the owner's marks dated in the period.

**Needs you (now, not period-bound):**
- **Replies waiting:** human replies not yet resolved (pending or handed over).
- **Approvals:** proposed outreach send or reply cards.
- **Failures:**
  - emails in an unknown or failed state in the last 7 days;
  - paused inboxes;
  - brands waiting for payment.

**Spend this month (owner only), per brand:**
- AI spend against the brand's allowance (C);
- the paid top-ups (F);
- the brand's billing state.
- For the business: the outreach budget and what is committed against it.

**Aria's summary:** one sentence built from these numbers, with no AI call and no cost. "Ask Aria" opens Aria. Aria gets a read tool, `get_outreach_dashboard` (brand and period). It returns the same pipeline, results and Needs you, without spend: that is owner-only, and Aria's research tool already reports spend.

## Marking meetings and wins (owner only)

- `POST /v1/outreach/dashboard/prospects/{id}/outcome` with `{"outcome": "meeting" | "won" | "closed" | null}`. Null undoes the mark.
- It sets the prospect's `stage` (the column already allows these values). Undoing sets it back to `ready` if eligible, otherwise `new`.
- Who and when are kept in the business settings document. No free text is stored, so nothing personal outlives the prospect's retention.
- It is owner-only, tenant-scoped and refused for a prospect of another business. It needs the outreach feature, but history access is enough: closing out a deal after a downgrade is allowed.

## Endpoints

- `GET /v1/outreach/dashboard?brand_id=&period=week|month|all` returns everything above. Spend is included only for the owner.
- `GET /v1/outreach/dashboard/stage/{stage}?brand_id=&limit=&offset=` returns the people at that pipeline stage. Each row has id, company, name, role and the date of their last activity.
- `POST /v1/outreach/dashboard/prospects/{id}/outcome`, as above.

## Not in OUT-14

- Revenue: no money is ever inferred from interest (design).
- Detecting meetings from calendar bookings.
- Readability refactor of `OutreachPage.tsx` beyond the overview (OUT-8 note).

**Tests first:** `backend/tests/test_outreach_dashboard.py`.

## As built

- **`services/outreach_dashboard.py`:**
  - `build`: pipeline, results, Needs you, summary, and spend for the owner;
  - `stage_list`;
  - `mark_outcome`;
  - `aria`, the tool.

  It reads every table with this business's id and aggregates in Python. That suits pilot volume; SQL aggregation is backlog.
- **`outreach_dashboard_api.py`:** the three endpoints, registered in `main.py`. They need the outreach feature with history access. Spend is included when the user is an active owner. Marking is limited to 30 a minute.
- **Aria:** `get_outreach_dashboard`, with brand and period, returns the same numbers without spend.
- **Screen:** `components/OutreachDashboard.tsx` replaces the old totals list on Outreach → Overview. The research summary and brand panel follow it.
  - Pipeline stages open a list of the people at that stage. There the owner can mark "Meeting booked", "Won" or "Closed", or undo a mark.
  - Results switch between this week, this month and all time, and each figure shows how it's counted.
- **Tests:** `backend/tests/test_outreach_dashboard.py`, 41 tests. Thirteen mutations are each caught, including tenant scoping on every table and the brand filter.
