# OUT-23 — The prospect bank, then Hunter.io, then "running low"

**Asked for:** Mike, 10 Nov 2026. Research found only 1–4 contacts a day. He wants it to find many more good prospects than are emailed each day, held in a bank, so sending stays steady while sourcing slows and changes direction.

**Decisions (Mike, 10 Nov 2026):**
1. **Bank size:** about **3 weeks of sending**, recalculated daily as the inbox warms. Contacts still unsent at **day 28** are deleted, so the UK GDPR Article 14 deadline (notice within a month; the first email carries it) is always met.
2. **Add-on:** **Hunter.io first.** The owner pastes their own API key and pays Hunter directly. It finds and verifies named decision-makers at the companies Aria finds. Apollo comes later.
3. **Direction:** when results run low, Aria **suggests** new sectors or a wider area as one-tap cards. A per-audience "may widen on her own" toggle exists, off by default.

**Parts, in order:**
- **A:** the bank and lifting the pilot limit (this document's design).
- **B:** Hunter.io.
- **C:** running low and changing direction.

Each part is its own PR.

---

## Why 1–4 a day (verified in code, 10 Nov)

1. **OUT-19 D** (`outreach_research.capacity`, `_run`) keeps a contact only if it takes a campaign place at once (`_take_place`). Without a place it is unstored. Research's `room` is today's free first-email places, so nothing is ever banked.
2. **The pilot limit** (`PILOT_ENROLMENTS = 5`, OUT-10 decision E) allows 5 pending or active enrolments per campaign. It is lifted by `OUTREACH_PILOT_ENROLMENTS=0`, but only after `prepare`'s scan of open cards is indexed (OUT-8 note 2; HK-1). `outreach_manage.prepare` locks and loads **every** open `send_outreach` card once **per enrolment** and filters in Python.
3. **The warm-up** (`metering.mailbox_daily_cap`): 5 a day for the first 5 sending days, then 10, then 20 after the owner's health review.

---

## Part A design (revision 2, after Codex design review 1: `audits/OUT-23-CODEX-DESIGN-REVIEW-1.md`)

Review 1's 11 findings and where each is answered:

| Finding | Answered in |
|---|---|
| 1 | A5 |
| 2 | A5, A6 |
| 3 | A6 |
| 4 | A2, A3 |
| 5, 6 | A2, A4 |
| 7 | A7 |
| 8 | A4 |
| 9 | A8 |
| 10 | A2, A9 |
| 11 | A3 |

### A1. Words
- **Contacted:** the prospect has any `outreach_messages` row in `claimed`, `accepted`, `unknown` or `imported`. The email may have reached them, so the notice may have been given.
- **Never contacted:** everything else, including a prospect enrolled with a draft card the owner has not approved.
- **Banked:** eligible, never contacted, and not enrolled.
- **Review-held:** `eligibility='review'`, never contacted. Counted and shown separately from the bank, never drained, and capped at 10 per brand per day as today.

### A2. Bank size, per audience, from an allocation of each inbox (findings 4, 5, 10)

**Each inbox's capacity is split once, across every campaign on it, of any brand.**
- An inbox's `mailbox_daily_cap` (warm-up and boost; health as the send path's admission) is shared among the ready or running campaigns on it.
- Each campaign gets `min(its daily_cap boosted, an equal share of the inbox)`. Any unused share is redistributed to campaigns whose cap is higher, so two campaigns capped at 3 on a 5-a-day inbox get 3 and 2.

**A brand's 20 (or boosted) cap binds the sum over its campaigns.**
- `audience_cap(brand, audience)` = the sum over that brand's campaigns whose `target_hash` matches the audience, after the brand bound.
- An audience with no matching ready or running campaign has `audience_cap = 0`. There is **no research and no banking** for it, as OUT-19 D review 1 required.

**The target** is `bank_target(audience) = 5 × audience_cap`.
- It is labelled an **estimated steady-state buffer** (about 3 weeks of first emails when a third of sends are first emails).
- At start-up it empties faster; that is shown as days left (A9), not hidden.

### A3. Research fills the bank (findings 4, 11)
- **Gate:** `bank_room(audience) = bank_target − banked(audience) − waiting(audience)` (step 0, never contacted). It is checked before any spend, and again under the business lock before each store.
- **Per day:** at most `DAILY_RESEARCH_MAX = 40` contacts per brand, eligible and review-held together (personal data collected). Decision-makers come first; gatekeepers are at most half. It is separate from the provider's attempt, token and tool limits, which are unchanged.
- **Spend:** reservations and the OUT-19 H exception are unchanged and named. A search's actual cost may exceed its realistic reservation; the overrun is recorded, and the next reservation stops.
- **Storing a verified contact:**
  1. `qualified()` is checked against a matching campaign. If it fails, the contact is **not stored**, recorded as "rejected: <reason>".
  2. If a place is free now, it is enrolled (`_take_place`).
  3. Otherwise it is **banked** if `bank_room > 0`; if not, it is rejected with "bank full".

  "No free place" and "not qualified" are distinct outcomes.

### A4. Drain: the bank into campaigns (findings 6, 8)
`drain_due(session, moment)` runs on the hourly automations pass, for each business with banked contacts, from 07:00 UK, after the health checks.

**Phases, each its own transaction:**
1. Expiry (A5).
2. Drain, with the business lock held from selection to commit.
3. `prepare_due_cards`, after the commit.

**Authority, re-read under the lock:**
- `pause_all` off;
- outreach entitlement and setup complete (`outreach_manage.start`'s checks);
- the brand is paid (`outreach_billing.brand_live`);
- the campaign is ready or running;
- `qualified()` per contact, which covers suppression, eligibility, retention and audience approval.

Research being switched off does **not** stop the drain.

**Budget:**
- An explicit remaining budget per inbox, per campaign and per brand, from the A2 allocation less today's use: sends today, follow-ups due, step-0 waiting, and reserved or unknown sends, including campaigns that have since paused.
- It is decremented on every enrolment.
- It is **not** limited by how many contacts research found today.

**Order:** the oldest banked contact first, only into a place for its own brand and audience. Only contacts with at least **5 days** before the cutoff (A6) are drained.

**Sequence:** the drain runs **before** research in the same pass, so the existing bank takes today's places first. It is retried each hour while places are free, so a health check passing late does not strand the bank. Its marker is per hour and per business, and records completion, not the start.

### A5. Erasure of never-contacted contacts at the cutoff (findings 1, 2)
`expire_never_contacted(session, bid, moment)` handles every never-contacted prospect, eligible or review-held, enrolled or not, whose cutoff (A6) has passed.

**Skipped this pass:** a prospect with an `executing` card, or any message in `draft`, `proposed`, `claimed`, `unknown` or `imported`. Such a prospect is either being sent or has been. It is logged and retried next pass. Message rows in `failed` or `cancelled` mean nothing reached them, but their deletion belongs to OUT-13's message erasure. They are logged as "kept for OUT-13" and the prospect is not erased this pass.

**For the rest, in one transaction under the business lock:**
- open `send_outreach` cards for its enrolments become `expired`, with the payload redacted to `{"redacted": "OUT-23", "enrolment_id": …}`;
- its unsubscribe tokens with that `prospect_key_digest` and no sent message are deleted;
- its enrolments, then its evidence, then the prospect row are deleted;
- **suppressions are never deleted** (an opt-out survives erasure, OUT-2 F19).

**Schedule:**
- **every day, weekends included**, on the hourly pass;
- for every business, **whatever** its pause, entitlement or inbox state;
- retryable, and its completion recorded only in the same commit as the deletions.

The longest a contact can outlive its cutoff is one hourly pass plus one retry.

This is the "never contacted" slice of OUT-13. It also closes an **existing** gap: today a contact whose card is never approved is kept for 365 days.

### A6. The cutoff and the send path (finding 3)
- **New contacts:** `notice_due_at = captured_at + 28 days` (`NOTICE_WITHIN` becomes 28 days, under every calendar month). It is the operational **cutoff**: no first email after it, and erasure at it (A5). **Existing prospects** keep their stored deadline.
- **The send path:** `dispatch` re-checks `notice_due_at` and `retention_due_at` with a fresh clock immediately before transport. Today only the claim checks them.
- **Approving late:** approving a card after the cutoff is refused with "This contact's first email is past its deadline", and the card expires.
- The ticket no longer claims deletion "meets" Article 14. Every contact who is emailed receives the notice in the first email, within 28 days. Anyone not emailed by then is erased.

### A7. Recently erased: the re-collection guard (finding 7)
- **What is kept:** a tenant-keyed digest (`send.suppression_digest(bid, 'domain', d)` and `(bid, 'email', e)`) of each erased contact's domain and email. It is stored in the research config (`recently_erased: [{digest, kind, until}]`) and pruned at 90 days. It is pseudonymous, not anonymous, and documented as such: its purpose is not re-collecting someone just erased. A subject-access or erasure request deletes the matching entry (OUT-13 owns the request flow).
- **Where it is checked:** at verification, and again under the store lock, for eligible and review-held candidates alike. The prompt's exclusion list also carries the domains, as hints only.
- **Separate from opt-outs:** permanent opt-out suppression is unchanged.
- **After 90 days** a company may be found again: a new collection with a new 28-day cutoff. **Confirmed by Mike, 10 Nov 2026.**

### A8. Cards, and lifting the pilot limit (finding 9)
**One operation, `outreach_manage.card_for(session, business, enrolment)`.** It runs under the business lock, with an indexed lookup: `action_type='send_outreach' AND status IN ('proposed','executing') AND (payload->>'enrolment_id') = :e`. It finds the open card or creates one, so it never duplicates. It is used by `prepare`, `outreach_research._prepare_cards` and the autopilot's `_due_enrolment`.

Where a caller needs the whole set of open enrolment ids, it uses one query, not one per enrolment: `prepare`'s and the autopilot's scans become a single `NOT EXISTS` join. `send.rows` itself is unchanged.

**Migration `040_outreach_card_lookup.sql`** (RED; runbook with `SET lock_timeout = '5s'; SET statement_timeout = '60s'`; staging first):
`CREATE INDEX IF NOT EXISTS idx_aria_actions_outreach_enrolment ON public.aria_actions (business_id, ((payload->>'enrolment_id'))) WHERE action_type = 'send_outreach';`
- Tests check correctness and query count at a realistic number of cards (500 open). They do not insist the planner uses the index on a small table; the runbook's `EXPLAIN` is informational.
- **Then Mike sets `OUTREACH_PILOT_ENROLMENTS=0`.**

### A9. The owner sees the bank
`status()` gives, per audience:
- `{target, banked, review_held, waiting, oldest_days_left}`;
- whatever blocks sending: no campaign, inbox not healthy, brand unpaid, or paused.

The research panel shows, for example: "Prospect bank: 42 of about 100 (an estimate) · the oldest must be emailed within 9 days".

### A10. Not in Part A
- OUT-13's remaining work:
  - erasure of contacted prospects and their messages;
  - the subject-request flow;
  - backup and provider copies;
  - engaged-lead retention.
- Hunter (Part B), running low and changing direction (Part C).

### Tests first (RED: personal data, erasure, paid research)
- **The bank:**
  - it fills past today's places, up to the target, per audience;
  - an audience without a campaign gets nothing and no spend;
  - a contact that fails `qualified()` is not stored;
  - the target follows the warm-up (5 → 25, 10 → 50, 20 → 100);
  - brands sharing an inbox split it, never double count it, and two campaigns capped at 3 on a 5-a-day inbox get 3 and 2;
  - 40 a day and the spend reservation bind (the OUT-19 H overrun behaviour is unchanged).
- **The drain:**
  - oldest first, matching brand and audience only;
  - the budget is never exceeded across two inboxes with a brand cap of 20;
  - it rechecks suppression, pause, payment and campaign state under the lock;
  - it skips contacts within 5 days of the cutoff;
  - it runs with research off and takes places before research.
- **Erasure:**
  - at the cutoff, including enrolled contacts with an open card (the card expired and redacted, tokens gone);
  - weekends, paused or unentitled businesses;
  - never an executing or contacted prospect;
  - suppressions kept;
  - retried after failure;
  - the recently-erased guard blocks re-collection at verification and under the store lock (a race test), and is pruned at 90 days.
- **The send path:** dispatch refuses after the cutoff even when the claim was before it; late approval is refused.
- **Cards:** `card_for` never duplicates under concurrent prepare, research and autopilot (PostgreSQL interleaving), and the query count is flat at 500 open cards.
- **The migration:** rehearsed on the local PostgreSQL harness.

**Needs Mike:**
- may an erased company be found again after 90 days (A7)?
- the runbook for 040.
