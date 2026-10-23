# Aria automations and B2B outreach — the plan (for Mike's decisions)

**Drafted 18 Oct 2026** from Mike's direction:
> "Aria chasing invoices automatically sending the pre-approved templates…
> providing a briefing on invoices she's chased when the user logs in… toggle
> this feature on and off; and the same for other relevant features… check
> for responses to invoice chasing emails… flag the business user… If the
> response was someone proving they have paid… the invoice chasing is closed
> off… go as far as we can with such automation… whilst taking into account
> limits for now, and of course, regulations."

and: "the B2B outreach section, making what we built part of Business Hero…
currently, I believe it's local to this Mac only??"

**North Star fit.** P4 says autonomy is earned one action type at a time,
like our own GREEN/AMBER/RED model, and Phase 3 is "Aria acts". This plan is
Phase 3, built on what now exists:
- NS-B10's approval cards and send-once engine;
- the email sync;
- the scheduler;
- metering.

---

## Part 1 — What exists today (checked 18 Oct 2026)

### In Business Hero
- **Aria drafts → you tap → she acts, once.** Email, invoice chase,
  booking and task (NS-B10).
- **Chase templates**, stages 1–4 (`email_templates.get_chase_email_template`).
- **Every send is recorded** in `email_outbox`, with the Gmail message id.
- **Inbound email is synced** into `email_messages`, with thread ids and an
  AI category.
- **A scheduler** runs every minute, plus metering, notices and the home
  briefing.

### The B2B outreach — **outside Business Hero, on this Mac only**
- **It lives in `~/.openclaw/`.** OpenClaw is a local AI-agent setup with
  agents for:
  - **research** (finds prospects; ranks fit, need and "why now");
  - **outreach writer** (drafts only);
  - **follow-up controller**;
  - **content**.
- **Each business has a queue** (`workspace-<business>/outreach/queue.json`).
- **How it works:**
  - it sends from Gmail through a command-line tool (`gog`);
  - follow-ups have due dates;
  - replies are detected by counting messages in each Gmail thread.
- **Scale:** Business Hero alone has **844 queue entries: 812 sent, 31
  failed**. There are also folders for New Body, MSC and FitFutures.
- **Schedule:** daily jobs ran research top-ups, sending, follow-ups and a
  reply sweep. **Those jobs are switched off now.** The morning and evening
  briefings and the weekly content jobs are still on.
- **Limits:**
  - nothing runs when the Mac is asleep or off;
  - nobody else (Amy, or a customer) can use it;
  - none of it is in Business Hero's security, metering, audit trail or
    compliance controls.

---

## Part 2 — Aria automations ("standing permissions")

### The model, for every automation
- **Off by default.** The owner switches each automation on in
  **Settings → Aria → What Aria can do on her own**. Each one says plainly
  what she will do, when, and the limits.
- **One action type at a time,** with its own **rules** (e.g. which stages,
  how often), **limits** (per day, per customer, quiet hours and working days
  only) and a **pause-all** switch.
- **She only uses wording the owner has approved** (templates). Anything
  outside a template still comes as a card for a tap.
- **Every automatic action is recorded** like an approved card (the
  `aria_actions` audit trail, `approved_by = standing permission`). Each one
  is undoable where possible, and visible on the home:
  > "While you were away I sent 3 chases (2 stage-one, 1 stage-two) and
  > paused chasing Harper Builds because they replied."
- **It never touches money:** no payments, no refunds, and no changes to bank
  details (North Star P4: never).

### Automation 1 — invoice chasing on autopilot
- **Rules.** Chase an unpaid invoice at stage 1 when it's **N days overdue**,
  then stages 2–4 every **M days**, using the approved stage templates and the
  AI-assistant sign-off. The owner sets N and M.
- **It never chases** an invoice that is:
  - paid;
  - disputed;
  - marked "don't chase";
  - for a customer who has replied and is awaiting a response;
  - outside working hours.
- **Limits.** At most one chase per customer per week, and a daily cap.
  Stage 4 always comes as a card for a tap.
- **The home briefing** lists what was chased since the owner's last visit.

### Automation 2 — reply watching (works with or without autopilot)
- **Linking replies.** Each chase records its Gmail thread. When the email
  sync sees a reply in that thread, Aria reads it and sorts it:
  - **"says they've paid"** (with or without a remittance or proof);
  - **promise to pay** (with a date);
  - **query or dispute;**
  - **out of office;**
  - **other.**
- **On any reply, chasing for that customer pauses at once.** Aria flags it
  under **Needs you**:
  > "Harper Builds replied to the INV-0038 chase: they say they paid on
  > Friday and attached a remittance. Mark INV-0038 paid and stop chasing?"
- **She never marks an invoice paid on her own.** The owner taps, or it
  closes itself when the Xero sync shows the payment.
- **A "promise to pay on the 25th"** sets a reminder and holds chasing until
  then.

### Later candidates, the same model each time
- **Quote follow-ups:** a nudge N days after sending.
- **Booking confirmations and reminders.**
- **Replying to routine enquiries** from approved answers.
- **The daily WhatsApp briefing,** including what she did.

### Regulations and limits, for invoice chasing
- **UK GDPR.** Chasing your own customers about their own invoices falls
  under the contract and legitimate interests. We keep the data to what's
  needed and keep an audit trail.
- **Consumer customers** (e.g. gym members) must not be harassed. The
  frequency limits, quiet hours and pause-on-reply cover this.
- **Business customers** can be charged statutory interest and fixed
  compensation under the Late Payment of Commercial Debts (Interest) Act
  1998. That could become a later **stage-4 option**, owner-approved only.
- **Gmail and Microsoft sending limits.** The daily cap stays far below them.

---

## Part 3 — B2B outreach inside Business Hero

### What it becomes
An **Outreach** section, for plans that include the `outreach` feature (see
Decision 3). It covers:
- **prospects;**
- **campaigns** (a target segment, a sequence of first email plus
  follow-ups, and daily limits);
- **Aria's research** (finding prospects and writing why each one fits);
- **drafts, sending, follow-ups and replies.**

All of it is server-side, so it runs 24/7, for every user of the business,
inside Business Hero's security, metering and audit trail.

### How it works
1. **Research.** Aria finds prospects that match the business's target
   (sector, area, size), using sources we can use lawfully:
   - **Companies House** (free API; also tells us whether a prospect is a
     company — see compliance below);
   - the business's own website and public pages, with permission.

   Each prospect gets a fit score and a "why now". The owner reviews the list.
2. **Drafts.** Aria writes short, specific first emails from the campaign
   template. The **first batch of every campaign** comes as cards for
   approval. Then, if the owner switches it on, a standing permission sends
   template-based messages within the daily limits.
3. **Sending.** From the business's connected mailbox, with a hard daily cap
   (gentle warm-up for a new mailbox) and a one-click unsubscribe line.
   Every message is in the audit trail.
4. **Follow-ups.** On the campaign's schedule, and they stop the moment
   someone replies.
5. **Replies.** Through the email sync, the same as reply watching. Aria
   sorts each one (interested, not now, unsubscribe, out of office, wrong
   person) and puts the interested ones under **Needs you**. Unsubscribes
   are added to the **suppression list** at once and permanently.
6. **Metering.** Outreach is the second-largest cost (PRICING-MODEL §2), so
   prospects researched and emails sent are metered with an allowance per
   plan, as voice minutes are.

### Compliance (UK) — built in, not optional
- **PECR.** Unsolicited marketing email to **corporate subscribers**
  (limited companies, LLPs, public bodies) is allowed without prior consent.
  To **sole traders and partnerships** it is NOT, unless they consented or
  it's a soft opt-in. So Aria checks Companies House:
  - prospects that aren't companies are flagged;
  - they are excluded by default.
- **Every message** identifies the sender, says it's from an AI assistant
  (D12), and offers a working opt-out. Opt-outs are honoured immediately and
  kept on a suppression list.
- **UK GDPR.**
  - **Legitimate interests**, with a recorded assessment (we provide a
    template).
  - **Article 14:** prospects are told where their details came from, in the
    first email's footer, with a link to the privacy notice.
  - **Data minimisation**, and a **retention limit:** unanswered prospects
    are deleted after 12 months.
  - The right to object is honoured instantly.
- **Deliverability.** SPF/DKIM/DMARC checks for the domain; daily caps;
  Gmail's bulk-sender rules (one-click unsubscribe).

### Moving off this Mac
We **import** each business's OpenClaw queue history into Business Hero, so
the history isn't lost:
- **who was contacted, when, and the thread** — so nobody is emailed twice;
- **replies and outcomes;**
- **any opt-outs** — straight onto the suppression list.

Then OpenClaw's outreach jobs stay off for good. The morning and evening
briefings and the content jobs can keep running locally, or move into
Business Hero later.

---

## Part 4 — Order of work (recommendation)

1. **AUTO-1: invoice chasing on autopilot** — the standing-permission
   framework, the settings page, the home briefing. First, because it builds
   directly on NS-B10, is small, and pays for itself quickly.
2. **AUTO-2: reply watching** for chases, including "they say they've paid".
   It needs the email sync's thread linking.
3. **OUT-1: outreach foundation, in parallel by Codex.**
   - Migrations: `prospects`, `campaigns`, `outreach_messages`,
     `suppressions` — RED, with runbooks.
   - Importing the OpenClaw history.
   - Sending with approval cards; reply sorting (shared with AUTO-2).
4. **OUT-2: Aria's research** (Companies House plus web), campaigns,
   standing permission for sends, metering.

**Each is its own ticket:** tests first, a different agent reviews, and
Mike's click tests.

---

## Decisions for Mike

1. **Order:** AUTO-1 → AUTO-2, with OUT-1 started in parallel by Codex?
   *Recommended.*
2. **Chasing defaults when switched on:**
   - stage 1 at **7 days** overdue;
   - then every **7 days** to stage 3;
   - **stage 4 always a card**;
   - at most **1 chase per customer per week**;
   - **weekdays 9:00–17:00** only.
   *Recommended.*
3. **Outreach for which plans?**
   - *Recommended:* **Business plan**, with a monthly allowance (e.g. 500
     emails and 200 researched prospects), or as a paid add-on.
   - Founder accounts (New Body, MSC) are metered but not charged, as for
     voice.
4. **Lead sources:** Companies House plus the business's own criteria, and
   companies only by default (PECR). *Recommended.* Paid data sources
   (e.g. Google Places) later, if needed.
5. **The OpenClaw history:** import all four businesses' history (Business
   Hero, New Body, MSC, FitFutures) into their Business Hero accounts?
   - FitFutures isn't a Business Hero business yet. Should it become one?

---

## Mike's decisions — 19 October 2026

1. **Order — agreed.**
   - AUTO-1 (invoice autopilot), then AUTO-2 (reply watching), built by
     Claude.
   - OUT-1 (outreach in Business Hero) in parallel, built by Codex.
2. **Chasing defaults — agreed.**
   - Stage 1 at 7 days overdue, then every 7 days to stage 3.
   - Stage 4 always a card.
   - At most 1 chase per customer per week.
   - Weekdays 9:00–17:00 only.
3. **Outreach is a paid add-on.**
   - **Included** in the highest tier (Business).
   - A **paid add-on** for the lower tiers.
   - Also a **standalone, outreach-only** product.
   - (Stripe products and plan wiring are RED, a separate ticket.)
4. **Lead sources — yes, and research must be much smarter.**
   - Find the **decision makers**, the "yes/no" people, where possible.
     Sources:
     - Companies House officers (directors are public, through the free
       API);
     - the company's own website (About us / Team pages);
     - public search-result previews, which can include LinkedIn profile
       snippets — but **never scraping LinkedIn itself**.
   - Use the latest, most capable models.
   - (Mike notes the local OpenClaw agents run on older, costlier models.
     He will upgrade the local ones himself, separately.)
5. **History import.**
   - **MSC** history → the **MSC** account.
   - **FitFutures** (UKFI, the education side of New Body Health and
     Fitness) → the **New Body** account. Its outreach is very much needed.
   - **New Body** history → New Body.
   - **Business Hero's own outreach stays LOCAL** on OpenClaw ("Byron and
     his team"). It is **not** imported; Mike will use and upgrade it
     separately.

**Reply handling must be smarter** (Mike). The old reply sweep answered
every reply with a booking link, which feels fake when someone has asked a
question. Instead:
- Aria reads the reply and answers basic questions from the business's
  **product knowledge** (as the AI receptionist uses its knowledge base),
  briefly and specifically, and moves gently towards a meeting **or** hands
  over to the owner.
- **At most one bespoke reply** before a human takes over.
- **Default: an "Approve response" card**, optionally with the owner **CC'd**
  into the thread so they can take over seamlessly.
- A booking link is sent only when the person asks to meet or shows clear
  interest.
- Always honest that it is an AI assistant (D12).

**The dashboard.** Outreach becomes a **department in the menu**, with an
easy-to-navigate dashboard **inspired by current outreach and CRM apps, and
on a par with them**:
- a pipeline;
- prospects;
- campaigns and sequences;
- a replies inbox;
- results.

## Progress and launch sequence — Mike, 19 October 2026

**Where things stand:**
- **AUTO-1** (chasing on autopilot): Codex approved it (review 6), and it is PR #36. It is off until switched on.
- **AUTO-2** (replies to chases): the tests are written and await Mike's approval. Its migration is 036.
- **OUT-2** (shared contracts): agreed, and reviewed by Claude.
- **OUT-3** (outreach core schema): the tests are written and await Mike's approval. Its migration is 037.

**The launch sequence:**
1. Finish AUTO-2 and the outreach department (the OUT tickets).
2. **The final finish: an admin-panel review.** Mike must be able to onboard a new business easily, with every feature switchable when setting it up. That includes the outreach add-on: included in the Business tier, a paid add-on below it, and a standalone outreach-only product. It also includes the business's mailboxes.
3. **Mike uses Business Hero himself, as a customer, for a month.**
4. **A few businesses Mike already knows** join, likely with a free first month, to help refine it.
5. Only then come paid subscriptions for others.

## Upcoming: from a "Daily Pulse" to Aria's briefings — Mike, 20 October 2026

Today the WhatsApp "Daily Pulse" goes out every day. Its stats are mostly zeros, and so are the financials on the odd day they appear. It's too frequent, and too empty to be worth reading. Replace it with:

- **A weekly briefing from Aria.** It's written as Aria, not as a "Daily Pulse", and it's useful. It covers:
  - what she did on her own, such as invoices chased on autopilot;
  - replies waiting for the owner;
  - what's owed and overdue;
  - what needs a decision.
- **A monthly business-performance snapshot.**
- **No daily messages.**

**Outreach is included in both** when the business's package includes it (entitlement-gated).

**Rule:** a section with nothing to say is left out, never shown as zeros.

**Order:** queued as its own ticket after the current AUTO/OUT work; it is not started.
