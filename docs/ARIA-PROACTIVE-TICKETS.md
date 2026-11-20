# ARIA-1 to ARIA-4: Aria as a proactive colleague

**From:** Mike, 19 Nov 2026, after using Grok Bot. He wants Business Hero and Aria to be "much more like a user's colleague and personal assistant". He decided on 19 Nov:

- **Order:** build these after OUT-28a (#105) has been tested:
  1. ARIA-1 (the inbox) and ARIA-2 (the dashboard grid), with OUT-27's grouped outreach card folded into the grid;
  2. ARIA-3, the finance strip;
  3. OUT-28 Part B;
  4. ARIA-4, Save to.
- **Email checks:** every 15 minutes, weekdays 07:00–19:00 UK, new mail only.
- **Save to:** a download to the computer, Google Drive, OneDrive and Dropbox (all four).

**Never, in any of these:**
- Aria never sends an ordinary email by herself. Every reply is the owner's one tap, on the exact version shown, through the existing `aria_actions` approval.
- Every AI step is recorded by the profit guard, and a business's total AI cost stays within its plan (`outreach-profit-rule`).

## What exists today (checked in code, 19 Nov)

**Runs on the server, logged in or not** (`services/briefing_scheduler.py`):
- email sync, every 2 hours in working hours on weekdays;
- Xero, 3 times a day;
- outreach research and cards, hourly;
- outreach autopilot, every 2 minutes;
- invoice chasing;
- reading replies to chases and outreach;
- briefings and the WhatsApp pulse.

**Inbox sorting exists, but only on demand.**
- `POST /v1/email/analyze` (the Inbox page's Analyse button) calls `app/email/service.analyze_email_batch`, which uses gpt-4o-mini.
- It writes `email_messages.ai_category`, `ai_priority`, `ai_summary` and `ai_suggested_action`, with these categories: action_required, awaiting_reply, fyi, marketing, finance, scheduling, spam.
- It never runs in the background and drafts no replies.

**Bug found:** `services/home_summary.summary` counts `ai_category = 'Action Required'`, but the sorter writes `action_required`. So the dashboard's "emails needing action" count is always 0. ARIA-1 fixes it.

**Google permissions held today:** `gmail.readonly`, `gmail.send` and calendar. There is no Drive permission.

---

## ARIA-1: Aria's inbox (RED: sends email on the owner's behalf)

**1. Sorting, in the background.**
- Every 15 minutes, weekdays 07:00–19:00 UK, each connected mailbox fetches **new** mail only. This replaces the 2-hourly sync in those hours.
- New messages are sorted without the owner pressing anything.
- **Cheap filters run first, with no AI:**
  - anything with a `List-Unsubscribe` header, a bulk or no-reply sender, or the owner's own sent mail is skipped;
  - outreach and chase replies are left to their own scanners (OUT-7 and chase replies).

**2. Categories in Mike's words:**

| Category | Covers |
|---|---|
| Money | Payments, remittances, invoices received, bank notices |
| New enquiry | Someone new asking about the business |
| Customer | An existing customer's request or question |
| Complaint | |
| Supplier | |
| Scheduling | |
| FYI | |
| Junk | |

- Priority runs from 1 to 5.
- "Important" means Money, New enquiry, Customer or Complaint, or priority 4 and above.
- The old values map onto these, and the home summary reads the new ones (which fixes the bug above).

**3. Drafted replies, for important emails only.**
- A draft is grounded in the business's details and its approved knowledge (as the receptionist's).
- It **never invents** prices, dates or promises. Anything Aria doesn't know becomes a question back to the owner in the draft notes, never a guess.
- **It is made once, when the email is sorted**, and stored. Opening the dashboard never calls the AI.

**4. Learning from edits.**
- When the owner edits a draft and sends it, the pair "Aria's draft → what the owner sent" is stored for that business and category.
- The few most recent pairs are given to the drafter as examples next time.
- The owner can see and delete what Aria has learnt (Settings → Aria → "How I write your replies").
- Nothing is learnt from emails the owner didn't send.

**5. One tap to send.**
- The reply goes through the existing approval card, on the exact version shown.
- It is sent from the mailbox the email arrived at, in the same thread.
- It is recorded in the email outbox.

**6. Cost.**
- Sorting uses a small model on filtered mail.
- Drafting runs only for important emails.
- Both are recorded under the profit guard, with their own purposes (`inbox_classify`, `inbox_draft`).
- Drafting is paused (sorting carries on) if the business is over its AI allowance. The owner is told: "Aria will draft replies again on [date]".

**Acceptance:**
- An enquiry email is sorted as New enquiry within 15 minutes, with a draft.
- An edited reply sends once, from the right mailbox and thread.
- The next draft in that category shows the owner's style.
- Newsletters cost nothing.
- The dashboard count is correct.

## ARIA-2: the dashboard grid (AMBER; sending goes through ARIA-1 and OUT-27)

This replaces the text "what Aria did" with a tidy grid of cards. It shows **at most 6**, the most urgent first:

| Card | What it shows |
|---|---|
| Important emails | "3 need you", one line each |
| Outreach ready | "5 emails ready" (OUT-27's grouped card) |
| Replies to outreach | |
| Money | Paid today, overdue, chases sent |
| Today | Meetings, and receptionist calls |
| Aria did | What Aria sent or did automatically |

**Tapping a card opens it in place.** For an email, it shows:
- the email;
- Aria's draft, editable there;
- **Approve and send**, **Not now**, and **Open in Emails**.

For outreach, it shows the list with **Approve all** (paced, as OUT-27) and each email editable, or **Open Outreach**.

**Speed:**
- The grid reads stored data only: one request (`/v1/home/summary` extended), and no AI or provider calls on load.
- It works at phone width, and cards stack.
- It is tasteful: the same palette and type as the app, with no more than one accent colour per card.

## ARIA-3: the finance health strip (AMBER)

It sits under the grid and taps through to Finance. It shows four figures:
- cash in the bank (from Xero);
- owed to you;
- overdue;
- this month compared with last.

**Fresh, without slowing anything:**
- The stored figures show instantly, with "Updated 2 minutes ago".
- On login, if the last accounting sync is more than 60 minutes old, an **incremental** Xero sync is queued in the background. It is the same sync the Finance page uses, and not the full pack.
- The strip then refreshes when that sync finishes.
- At most one sync per business at a time, and one per hour from logins.

## ARIA-4: Save to (AMBER for the files; RED for any new OAuth permission)

For the accountancy pack, an outreach summary spreadsheet (.xlsx) and documents Aria writes (.docx), "Save to…" offers:

1. **This computer:** a normal download.
2. **Google Drive:**
   - adds the `drive.file` permission, which lets Aria see only files she created;
   - each business reconnects Google once;
   - files go in a "Business Hero" folder.
3. **OneDrive:** the Microsoft connection gains `Files.ReadWrite.AppFolder`; files go in the app's own folder.
4. **Dropbox:**
   - Mike registers a Dropbox app (scoped to an app folder) and sets its keys in Railway;
   - each business connects Dropbox once.

Aria can also do it from chat: "Save this month's outreach summary to my Drive". That is a proposal card the owner taps, never automatic.

**Not in scope:** reading or changing the owner's other files.

---

## Suggested build order inside ARIA-1 and ARIA-2

1. Fix the home-summary category bug (small, today).
2. Background sorting, with the new categories and the cheap filters.
3. Drafts and storing the learning pairs.
4. The grid, reading stored data only.
5. Expand in place, with the email card's edit and send.
6. Fold in OUT-27: the outreach card, Approve all and the per-brand auto-send offer.
