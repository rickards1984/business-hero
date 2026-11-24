# ARIA-1 to ARIA-4: Aria as a proactive colleague

**From:** Mike, 19 Nov 2026, after using Grok Bot. He wants Business Hero and Aria to be "much more like a user's colleague and personal assistant". He decided on 19 Nov:

- **Order:** build these after OUT-28a (#105) has been tested:
  1. ARIA-1 (the inbox) and ARIA-2 (the dashboard grid), with OUT-27's grouped outreach card folded into the grid;
  2. ARIA-3, the finance strip;
  3. OUT-28 Part B;
  4. ARIA-4, Save to.
- **Updated order (22 Nov 2026):** AI-1 (the model switchboard) went first and is done (AI-1a–1d, #108–#114). Mike then added QUOTE-1, the estimator that wins work (`docs/QUOTE-1-TICKET.md`), as of equal value. The order from here:
  1. ARIA-1;
  2. **QUOTE-1**;
  3. ARIA-2;
  4. ARIA-3;
  5. OUT-28 Part B;
  6. ARIA-4;
  7. STAB-2.
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

### ARIA-1a: sorting, as built (24 Nov)

**Corrections to "What exists today":**
- Sorting already ran in the background, after each 2-hourly sync (`background_sync._analyze_uncategorised_for_business`). It wasn't on demand only.
- "Analyse all" wasn't broken. It found nothing unsorted, because the background had sorted it all, and it said so too faintly to notice.
- The "Action Required" mismatch was in **three** places: the dashboard, the WhatsApp briefing's email counts (`briefing_data`, whose figures were all 0) and the automation trigger "email needs action", which could never fire.

**Built:**
- **`services/inbox_sorting.py`, the one definition.**
  - Mike's categories, with `normalise` reading every stored value, old ones included (`finance` → money and so on), so no migration is needed.
  - `is_important` and `IMPORTANT_SQL`: Money, New enquiry, Customer or Complaint, or priority 4 and above, and never Junk. They're used by the dashboard, the WhatsApp briefing, the automation trigger, the message list's "important" filter and the Comms page.
- **Free filters before any AI:** the owner's own address, a reply to the business's outreach (left to Outreach → Replies), spam, Gmail promotions, social and forums, mailing-list headers, and automated mail.
  - **A money email is never filtered away:** a subject that looks like money (invoice, payment, remittance, statement, a £ amount…) always goes to the AI, whatever its sender or headers.
  - Chase replies are sorted, not skipped: they can't be told apart at sync time, and they belong in Money anyway.
- **`sort_pending`**, one pass shared by the background and "Sort now".
  - Newest first, in batches, costed to the business as `classify`.
  - A failed batch stamps nothing and is reported.
  - An answer about mail outside the batch is ignored.
  - With no key for any chosen model, mail is left unsorted. It used to be stamped "fyi" for good.
- **The schedule (`services/inbox_schedule.py`):** weekdays 07:00–19:00 UK. A **new-mail-only check every 15 minutes**: Gmail skips the metadata fetch for mail already stored. The **full sync every 2 hours** also refreshes read and unread state.
  - The sync ran its Gmail calls and sorting **on the event loop**. Each business now syncs in a worker thread, and no two syncs overlap.
  - The message list endpoint is now a plain `def`, so its DB work runs off the loop too.
- **The Comms inbox:**
  - A status line: "Aria sorts new mail every 15 minutes, weekdays 7am to 7pm · last sorted … · next check … · N waiting".
  - **Sort now** says what it did: how many were sorted and how many sorted free, "nothing new", or "couldn't sort; she'll try again".
  - Chips for each category plus Important; cards for "Needs you", "New enquiries" and "Unread", each tappable to filter; and colour per category.
  - The older Inbox page uses the same categories. The page's rule is tested against the server's in every case.
- **The AI defaults (`services/ai_models`):** no default on gpt-4o. Mike's 22 Nov choices are now the defaults, each with a fallback where the job can take one:
  - CEO briefings and the help assistant: gpt-5, then Claude Sonnet 5.5;
  - inbox sorting, the single reply draft and call summaries: gpt-6-luna, then gpt-4o-mini;
  - the board meeting: Claude Opus 5.5, then gpt-5;
  - quote chat: gpt-6.1-sol.

**Found while building:** `test_followups_due_on_existing_enrolments_get_their_morning_card` started failing on its own on 24 Nov 2026, 28 days after its fixed date. The card's check reads the real clock, for the 28-day first-send deadline. The test now holds that clock. **Follow-up:** sweep the other tests with fixed autumn-2026 dates for the same kind of date bomb.

**Next (ARIA-1b):** drafted replies for important email, learning from the owner's edits, and one-tap send.

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
