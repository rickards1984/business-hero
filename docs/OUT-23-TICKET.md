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

## Part A design, revision 4 (11 Nov 2026) — APPROVED by Codex design review 5 — answers `audits/OUT-23-CODEX-DESIGN-REVIEW-3.md`

Mike chose "fix, quick check, then build". Revision 4 supersedes revision 3 where they differ; B1, B3 and B6 stand.

**R4.1 The drain has its own budget, separate from research's quota and from bank sizing (finding 1).** `outreach_bank.drain_budget(session, bid, moment)` is built from **send-use accounting only**:
- today's sends: reserved, committed and unknown usage events;
- follow-ups due by the end of today;
- step-0 enrolments not yet claimed;
- the pilot limit's members.

**Banked and review-held prospects are never counted as use.** `capacity()` keeps its research role and is not used by the drain.

**Allocation is per candidate:** for each banked contact, oldest first, the drain takes one place in a matching campaign only if every bound in R4.2 has room. A campaign with no qualifying candidates therefore takes no inbox capacity. A same-day test covers research banking 25 at 06:00 and the 07:00 drain enrolling 5 into a 5-a-day inbox.

**R4.2 One commitment ledger, every bound (finding 2).** Each queued, unreserved item (a follow-up due today, or a step-0 enrolment not yet claimed) counts **once** against **every** bound it will use. Reserved and unknown usage already counts as a send and is not added again.

| Bound | Starting balance |
|---|---|
| campaign | `daily_cap` (boosted) less sends today less queued |
| inbox, cold | `mailbox_daily_cap` less cold sends today less queued on the inbox |
| inbox, total (replies included) | `reply_headroom()["left"]` less queued on the inbox; **0 if `blocked`** (today's check not yet passed) |
| brand, daily | the send path's brand limit, **exactly** `outreach_boost.follow(min(20, business_daily_cap), outreach_boost.brand_level(...))` as `metering._cold_limits` (an owner cap left at 20 rises with a boost; a lower one binds), less brand sends and queued |
| brand, monthly | daily limit × weekdays (as `_cold_limits`) less this month's cold sends less the brand's queued |

Every new enrolment decrements all five. Tests: each bound alone; combined limits (replies at 39 of 40 with one waiting means no new enrolment; one monthly place with a follow-up due means none); repeated hourly passes without double counting.

These are scheduling allocations, not reservations. A later reply or a change of authority can still make a send refuse, and the contact then waits, or is erased at its deadline by OUT-13 core.

**R4.3 Cards prepared independently (finding 3).** Every hourly pass calls `prepare_due_cards` for **every business with due active enrolments** (one indexed query), whatever its bank, research toggle or new placements. It runs outside any drain transaction and is retryable; autopilot grants are still skipped, as `_prepare_cards` does today. Tests cover a crash between the drain's commit and preparation, an empty bank, research off, a later follow-up, and an autopilot grant revoked.

**R4.4 Deterministic allocation for the bank's size (finding 4).**
- The brand limit is the send path's own: `follow(min(20, business_daily_cap), brand_level)`, as in R4.2 (Codex design review 4). Tests: a boosted brand with the default 20 (30 places); a lower owner cap still binding.
- For bank sizing only, each inbox's cap is water-filled across its campaigns. Each round gives every campaign with remaining demand an equal integer share; the remainder goes to the oldest campaigns. It is clipped by the campaign's cap and by the brand's remaining limit **across all its inboxes**, and repeated until nothing changes.
- Tests: multiple inboxes, a shared inbox, a lower owner cap, and redistribution after a brand binds.

**R4.5 Held stock versus drainable stock (finding 5).**
- `bank_room = target − drainable − waiting`, where *drainable* means at least 5 days before its deadline.
- Contacts inside the margin are shown as "held", still erased at the deadline by OUT-13 core, and never block replenishment.
- Tests: a bank entirely inside the margin is replenished; a brand-new contact (28 days left) drains at once, since the rule is 5 days *remaining*, not a 5-day wait.

**R4.6 Review-held contacts: deferred, stated plainly (finding 6).**
- There is **no** existing operation that makes a review-held contact sendable, and none is invented here. Review-held contacts are stored exactly as today (their own loop, which the existing test allows up to 20), never banked, drained or emailed, and erased at their deadline.
- They count in the 40 a day.
- Promoting a review-held contact, by re-verification with evidence, is a later ticket.
- B3's qualification rule applies to eligible storage only.

**R4.7 The drain's lock sequence (finding 7).**
1. Resolve the business's active owner (`business_members`, role owner, active). With none, the business is skipped and logged.
2. `outreach_manage.start(session, business, owner)` and `growth()`. These roll back first, then take the locks and re-read the business.
3. Then, **with no further rollback** until commit: re-read pause, brand payment, campaigns, candidates and the R4.2 balances; enrol; commit.
4. `plan()`, card preparation and every other helper that owns its rollback stay outside this phase.

**Manual enrolment is unchanged.** "The only path in" means the only *automatic* placement from research.

**Tests replaced:** the immediate-enrolment and card assertions in `test_outreach_research.py`, `test_outreach_research_capacity.py` and the PostgreSQL research test become research → drain → preparation.

## Part A design, revision 3 (11 Nov 2026): built on OUT-13 core

It answers `audits/OUT-23-CODEX-DESIGN-REVIEW-2.md`, and supersedes revision 2 where they differ. **OUT-13 core** (PR #95) now owns the deadline, hiding, erasure, interrupted claims and the re-collection guard. The bank uses its predicates and adds none of its own.

| Review 2 finding | Answer |
|---|---|
| 1 Unsent contacts kept, failed messages | OUT-13 core erases every never-contacted contact (failed, cancelled, draft and proposed messages included); uncertain ones are owner-visible exceptions |
| 2 Copies (cards of any status, tokens, outcomes, logs) | OUT-13 core R5/T7/T9; chats and memory by Mike's boundary |
| 3 Cutoff on reads and manual enrolment | OUT-13 core R3 (every reader, browser clock) and `qualified()` |
| 4 30 vs 28 days; follow-ups | OUT-13 core T1/T2: deadline = min(notice_due_at, captured + 28 days); follow-ups exempt |
| 5 Drain budget versus send admission | **B4**: the drain is bounded by the send path's own limits |
| 6 Research at 06:00 before the drain | **B3**: research only banks; the drain alone enrols |
| 7 Card creation and autopilot | OUT-24: the one-card guard under the lock in `build_payload`; `_prepare_cards` gives an autopilot campaign no card |
| 8 Review-held contacts versus qualification | **B5** |

### B1. Banked
A contact stored by research, `eligibility = 'eligible'`, **with no enrolment and no message**. Review-held contacts (`'review'`) are not banked (B5). The bank empties only by the drain (B4) or by OUT-13 core's erasure at the deadline.

### B2. Bank size per audience (review 1's allocation, unchanged)
- Each inbox's warm-up cap (`mailbox_daily_cap`, with boost) is split across the ready and running campaigns on it, of any brand: an equal share, bounded by each campaign's own cap, with leftover redistributed. The brand's 20 (or boosted) cap binds the sum.
- `audience_cap` is the sum over the brand's campaigns matching the audience. It is 0 without one, in which case **no research and no banking**.
- **`bank_target = 5 × audience_cap`**, shown as an *estimated* buffer of about 3 weeks of first emails (a third of steady-state sends): 5 → 25, 10 → 50, 20 → 100.
- `bank_room = bank_target − banked(audience) − waiting(audience)`, where waiting means enrolled at step 0 and never contacted.

### B3. Research only banks (finding 6)
- Research no longer enrols anything. Every verified, qualified contact goes to the bank if `bank_room > 0`; otherwise it is rejected as "bank full".
- **Qualification first:** `qualified()` is checked against a matching campaign before storing. A refusal means the contact is not stored, and "no place today" is no longer a reason. The OUT-13 core guard (`recently_erased`) and suppression checks apply as today.
- **Gate:** research searches only if `bank_room > 0` for its audience. This is checked before spend and again under the store lock.
- **Per day:** at most `DAILY_RESEARCH_MAX = 40` contacts per brand, eligible and review-held together. Gatekeepers are at most half. The monthly spend cap and the OUT-19 H overrun rule are unchanged.
- **Timing:** research keeps its 06:00 weekday run. Because it never takes a place, the old bank-versus-new priority problem is gone. The oldest banked contact is enrolled first (B4).

### B4. The drain: the only path into a campaign (findings 5, 6)
`outreach_bank.drain_due(session, moment)` runs on the hourly automations pass, weekdays 07:00–18:00 UK, after OUT-13 core's erasure and the health checks.

For each business with banked contacts, under the business lock (selection to commit), it re-reads authority:
- `pause_all` is off;
- `outreach_manage.start` and `growth()` pass: entitlement, setup, growth;
- the brand is paid (`outreach_billing.brand_live`).

**Budget per campaign,** recomputed under the lock, as the **smallest** of:
1. the campaign's free places from `capacity()` (its cap less today's sends, follow-ups due, step-0 waiting and reserved or unknown sends, with the inbox shared across every campaign and brand on it);
2. the inbox's remaining room today, replies included: `metering.reply_headroom(...)["left"]`. It is **0 when `blocked`** (today's health check is not yet passing), so a drain before the check enrols nothing and retries next hour;
3. the brand's monthly allowance remaining: the same count as `_cold_limits` (daily limit × weekdays, less this month's cold sends), less step-0 waiting;
4. the brand's daily cap less its use.

Each enrolment decrements every bound it touches.

**Each contact:**
- the **oldest banked first**, by deadline;
- only with **at least 5 days** before its deadline (`outreach_erasure.deadline`), leaving time for approval;
- `qualified()` re-checked;
- enrolled at step 0.

Then `prepare_due_cards` runs **after the commit** (OUT-24's guarded card creation; none for an autopilot campaign).

**Retries:** the drain retries every hour while places are free, so a late health check never strands the bank. There is no day-claim.

### B5. Review-held contacts (finding 8)
- Stored as today (`eligibility = 'review'`, no lawful basis), counted in the 40 per day and capped at 10 per brand per day (`MAX_GATEKEEPERS`'s sibling, unchanged).
- **Never banked, drained or emailed** until the owner's existing review makes them eligible, at which point they join the bank.
- Erased at their deadline by OUT-13 core like anyone never contacted.

### B6. The owner sees it
`status()` gives, per audience:
- `{target (estimate), banked, review_held, waiting, oldest_days_left}`;
- whatever blocks the drain: no campaign, inbox check not passed, monthly allowance used, unpaid, or paused.

The research panel shows, for example: "Prospect bank: 42 of about 100 · oldest must be emailed within 9 days".

### B7. Tests first (RED: paid research, personal data)
- **Bank size:** each warm-up stage; inbox shared between brands; a campaign capped at 3; an audience without a campaign.
- **Research:**
  - fills past today's places and stops at the target;
  - never enrols;
  - qualification refusal is not stored;
  - recently erased and suppressed contacts are not stored;
  - 40 a day; gatekeepers at most half; the spend cap.
- **Drain:**
  - oldest first; matching brand and audience only;
  - every bound binds alone: places, reply headroom, health not yet checked (enrols nothing, then does at the next pass once it passes), monthly allowance, brand daily cap;
  - two inboxes with a brand cap of 20;
  - pause, unpaid, entitlement;
  - within 5 days of the deadline it skips;
  - cards only after commit, none for autopilot;
  - interleaving with manual enrolment, approval, unsubscribe and erasure (PostgreSQL).
- **Review-held:** never drained; becomes banked when made eligible.

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

---

## Part A — Implementation (revision 4, built 11 Nov 2026)

| Design | Code | Tests |
|---|---|---|
| B1/R4.4 bank size, water-filled per inbox, brand limit as the send path | `outreach_bank.audience_caps`, `bank`, `_brand_limit` | `test_outreach_bank.py` bank size |
| R4.5 drainable vs held (5-day margin), `room = target − drainable − waiting` | `outreach_bank._stock`, `bank` | margin tests |
| B3 research banks only: 40 a day per brand, ≥20 decision-makers, ≤20 gatekeepers; no search when the bank is full; qualification refusal not stored | `outreach_research._bank_room`, `_unqualified`, the store loop; `capacity()`/`_take_place` removed | research tests, `test_outreach_research_brands.py`, today's-40 gate tests |
| R4.2 the drain's ledger: campaign, inbox cold, inbox total (reply headroom; 0 if blocked), brand day, brand month, pilot | `outreach_bank._ledger`, `_room`, `_take` | each bound alone, combined, carried OUT-19 D accounting (in-flight once, unknown once, UK day, paused campaign, released usage, over-cap campaign) |
| R4.7 drain order: owner → `start()` + `growth()` → pause → paid campaigns → ledger → oldest first → `qualified` → insert → commit | `outreach_bank.drain_business` | skip, unpaid, oldest first, review-held never drained |
| Weekdays 07:00–18:59 UK, every hourly pass, no day claim | `outreach_bank.drain_due`, wired in `automations.run_all_due` after research | drain hours, hourly-pass order |
| R4.3 cards for every due enrolment, independently | `outreach_bank.prepare_all_due`, wired after the drain | cards with an empty bank and research off |
| B6 the owner sees it | `outreach_bank.audiences` → `research.status()["brands"][i]["bank"]`; `ProspectBank` in `OutreachSetupWizard.tsx` | B6 tests (figures, review-held apart, each blocker) |
| PostgreSQL | — | `test_outreach_bank_pg.py` (sizing, ledger, drain, cards, `drain_due`) |

No migration: the bank is the existing `outreach_prospects` rows that have no enrolment.

---

# Part B — the Hunter.io add-on (design, revision 1, 11 Nov 2026)

## B-0. Why
Research keeps an address only if it is published on the company's own website, so most companies Aria finds yield only a gatekeeper (`info@`) or nothing. Hunter supplies the **named people** at a company's domain: their role, seniority, the public pages where each address was found, and a verification status. Mike is connecting it for MSC first.

## B-1. Mike's decisions (11 Nov 2026)
1. **Which emails:** only addresses Hunter **found published publicly** (at least one source) **and** that verify as **`valid`**. No Email Finder guesses and no `accept_all` addresses: bounces would damage inbox health and the boost.
2. **Key:** one Hunter API key per business, switched on **per brand**.
3. **Credits:** the Hunter plan's quota is the hard limit, plus an **optional monthly credit cap per brand**. The app shows credits used and left.
4. **Plans:** any plan with outreach. It costs Business Hero nothing; the customer pays Hunter, and AI drafting stays inside the per-brand allowance (profit rule).

Facts checked against Hunter's documentation on 11 Nov 2026:
- Base URL `https://api.hunter.io/v2/`, key sent in the `X-API-KEY` header.
- Domain Search costs 1 credit per request returning 1–10 addresses; Verifier costs 0.5. `X-Credits-Used` reports the actual charge.
- Errors: 401 bad key, 403 rate limit, 429 quota used, 451 the person has claimed their address with Hunter (opted out).
- Starter plan: £28/month, 2,000 credits. Estimated use at 40 contacts a day for one brand: 1,300–1,800 credits.

## B-2. Where Hunter sits in a research run
Nothing changes for a candidate with a published email: it follows today's `_verify`.

With Hunter on for the brand:
1. **The brief** also asks Aria for *company leads*: real, fitting limited companies with their website domain and Companies House number, even when no named email is published (`contact_email` empty, `website` given). A lead whose only published address is a role address is also a lead.
2. **Free checks first, before any credit is spent**, in this order:
   - a business domain, not webmail;
   - not already held or contacted;
   - the domain is not suppressed or recently erased;
   - the **corporate checks**, run on the company's home page: Companies House active and corporate, the name matches, the website discloses its registration, and the domain fits the name.

   A lead that would only be kept for review (a sole trader or partnership) never reaches Hunter.
3. **The room and credit gate**, under the business lock with the spend reservation:
   - today's 40 and the bank have room;
   - the brand's credit cap is not reached;
   - the business is not quota-blocked.

   At most `2 × room` Hunter searches are made in a run, and calls stop as soon as the room is filled.
4. **Domain Search:** `domain`, `type=personal`, `seniority=executive,senior`, `limit=10`. From the results, keep only an address that meets all of these:
   - its domain is the company's;
   - it has at least one source with `still_on_page = true` (found published);
   - it is **valid**: Hunter's own `verification.status == "valid"` dated within the last 90 days, otherwise an Email Verifier call that returns `valid`. Anything else is dropped (`accept_all`, `unknown`, `invalid`, `webmail`, `disposable`). A 202 means "still verifying"; poll it within the run's time budget, then drop it if unresolved.
5. **One person per company**, as today. Pick by:
   - decision-maker role (the existing `_contact_type` applied to `position`);
   - then seniority, executive before senior;
   - then Hunter's confidence.

   Then the existing per-contact checks: not suppressed by email key, not recently erased, a mail server exists.
6. **Store** it as today: role from `position`, `role_verified` by the Companies House officer match, confidence 85/65. The evidence is recorded with:
   - `source_type = "hunter"`;
   - `source_url` = the chosen source page;
   - `adapter_version = "out23b-v1"`;
   - the verification fact (`hunter:valid`, with its date);
   - a `source` fact of `hunter` for the learning table.

   Nothing else from Hunter's response is kept: the other people at the domain are discarded in memory.

## B-3. The first email names Hunter (RED: the send path)
For a contact whose source evidence is `source_type = "hunter"`, the footer reads:

`Source: <page> (found via Hunter.io, a business contact database)`

instead of `Source: <page>`. It is computed in `build_payload` from the same evidence row that supplies `source_url`, so the payload hash binds it. Every other contact's footer is byte-for-byte unchanged.

## B-4. Privacy notice gate
Article 14 requires the source categories to be named. Switching Hunter on for a brand needs the owner to confirm that brand's privacy notice names "business contact databases such as Hunter.io" as a source. Suggested wording is shown; `notice_confirmed_at` is recorded. Hunter stays off for the brand until then.

## B-5. The key and credits
- **Connect:** the owner pastes the key. It is validated with `GET /account` (free) and stored **Fernet-encrypted** (`app/email/crypto.encrypt_secret`) in the business settings document under `outreach_hunter`: `{key_ciphertext, last4, plan, connected_at, status}`. It is never returned to the browser or logged. Disconnecting deletes it.
- **Per brand:** `{enabled, monthly_credit_cap (optional), notice_confirmed_at}`.
- **Metering:** each call's `X-Credits-Used` goes to `usage_meters`, `hunter_credits:<brand>` for the month, checked against the brand's cap before each call.
- **Error handling:**
  - 429: the business is blocked until Hunter's `reset_date` and the owner is told;
  - 401: the key is marked invalid, Hunter stops, and the owner is told;
  - 403 (rate limit): this run's Hunter calls stop;
  - 451: that person is skipped and nothing is stored;
  - 5xx or a timeout: that company is skipped, with no retry storm.
- **Speed rule:** the timeout is 15 s per call and the host is fixed. Credits left come from `/account`, cached for at most an hour, and the settings page reads the cache.

## B-6. The owner sees it
- In Outreach settings, under "Hunter.io (optional add-on)": connect or disconnect, the plan, and credits used and left this month.
- Per brand: an on/off switch with the notice confirmation, and the credit cap.
- Research's summary line adds "N found via Hunter". `performance()` splits results by source, so the owner sees whether Hunter contacts reply.

## B-7. Tests first (RED: paid third-party lookups, personal data, the send path)
Hunter is always faked.
- **Gates:**
  - Hunter off for the brand, no key, an unconfirmed notice, the cap reached, quota-blocked, or a full room: no Hunter call;
  - a lead that fails the corporate checks, is held, is suppressed or was recently erased never costs a credit.
- **Selection:**
  - only found and valid addresses are kept;
  - each of `accept_all`, `unknown`, `invalid`, `webmail`, `disposable`, no sources, and a foreign domain is dropped;
  - a stale `valid` is re-verified;
  - 202 is polled, then dropped;
  - a decision-maker beats a more confident gatekeeper;
  - one person per company.
- **Errors:** 401, 403, 429 (blocked until the reset date) and 451 each behave as in B-5.
- **Metering:** credits are recorded from `X-Credits-Used`, the cap binds, and the key never appears in a log, a response or a stored row other than its ciphertext.
- **The send path:** a Hunter contact's footer names Hunter and is bound by the payload hash; every other footer is unchanged; erasure removes Hunter contacts like any other.
- **Bounds:** the day's 40, the bank and the gatekeeper rules are unchanged.

## B-8. No migration
Evidence `source_type` is free text, the key lives in the settings document, and credits use `usage_meters`. `EMAIL_ENCRYPTION_KEY` is already set (mailboxes use it).

---

# Part B — revision 2 (answers Codex design review 1; supersedes revision 1 where they differ)

Revision 1's B-0, B-1 (Mike's decisions), B-6 and B-8's "no migration for evidence" stand. Each item below is numbered by review 1's finding.

**Hunter's contract**, checked on 11 Nov 2026:
- `provenance` is `found` (seen on a public page) or `inferred` (built from a pattern). `previously_found` is coming: found, but not confirmed in the last 90 days. Domain Search accepts `provenance` as a filter.
- Source fields are `domain`, `uri`, `extracted_on`, `last_seen_on` and `still_on_page`, with dates as `YYYY-MM-DD`.
- The verification object has `date` and `status`.
- `X-Credits-Used` may be fractional (0.5). `X-Credits-Unit` is `credit` (one pool) or `search`/`verification` (separate pools).
- Finder and Verifier may return **451 `claimed_email`**: "you shouldn't process it yourself in any way".

## R2.1 "Found published" (finding 1)
- The request carries `provenance=found`. The response must say `provenance == "found"`; anything else, including missing or unknown, is rejected.
- A **publication source** needs all of:
  - `still_on_page == true`;
  - `last_seen_on` parses, is not in the future, and is within 90 days;
  - an `https` `uri`.
- **We confirm it ourselves:** the chosen source page is fetched with the existing SSRF-guarded `fetch_page`, and `_address_on(page, email)` must hold. Sources on the company's own domain are tried first, then others; at most 2 fetches per person.
- A third-party page (a directory) can prove publication, but never company ownership or permission. Those come only from the corporate checks (R2.9).
- Tests: stale, future, malformed, `still_on_page` false, `inferred`, missing provenance, a page that no longer shows the address, and a login wall.

## R2.2 The verification contract (finding 2)
Typed and fail-closed. An address is valid only when one of these holds:
- **(a)** Domain Search's `verification.status == "valid"` with a parsed, non-future `date` within **30 days**; or
- **(b)** an Email Verifier call returns all of:
  - `data.email` equal to the exact address (normalised);
  - `status == "valid"`;
  - `accept_all`, `webmail`, `disposable`, `block` and `gibberish` all `false`;
  - `smtp_check == true`.

If neither holds, the person is dropped. A failed Hunter result **never** falls through to web verification or review storage.

The `email_verification` evidence row records `verification_status = "valid"`, `verified_at` = **Hunter's actual date** (a) or the verifier's date (b) (never `moment`), and `expires_at = verified_at + EVIDENCE_LIFE`. `_store` takes these as parameters; for web contacts it keeps today's values.

Tests: missing or future dates, a mismatched address, contradictory flags, and the stored values checked in the database. A real prepare-and-claim test of a Hunter contact.

## R2.3 Free checks before paid ones (finding 3)
Per lead, in this order:
1. A business domain that is not webmail, not held or contacted, and not suppressed or recently erased.
2. **MX**.
3. The corporate checks (R2.9).
4. Only then the reservation and **Domain Search**.

After the search, with no further charge:
1. drop results whose domain isn't the company's;
2. drop by provenance and publication-source freshness (R2.1 data only, no fetch yet);
3. drop held or suppressed email keys, recently erased addresses, and anything over the gatekeeper quota;
4. **rank** the survivors: decision-maker role, then seniority (executive before senior), then confidence;
5. take each in rank order: fetch its publication page (R2.1), then verify (R2.2). **Stop at the first usable person.**

Tests: an email-only suppression means zero Verifier calls, and nobody ranked lower is verified after a success.

## R2.4 Reservations, leases and budgets (finding 4)
Hunter work runs **per lead**, after the AI search has settled, inside the same run and claim.
- **Before every billable call**, under the business lock in one transaction:
  1. renew and check the search claim (`_claim_search(session, bid, claim) == claim`);
  2. re-check `_still_allowed`, the brand's Hunter switch and notice binding (R2.8), the connection `generation` (R2.5) and the quota blocks (R2.6);
  3. check the room: today's 40 and the bank, less this run's pending stores;
  4. check that the brand cap's remaining credit is **at least the call's maximum cost** (search 1.0, verify 0.5);
  5. **commit a reservation** of that maximum to `hunter_reserved:<unit>:<brand>` for the month.
- **After the call:** settle with `X-Credits-Used`/`X-Credits-Unit` (R2.6), releasing the reservation, independently of whether anyone is stored.
- **On a timeout or crash** the reservation stays as an estimated charge. A daily sweep releases reservations older than 1 hour into charged.
- **Within a run:** a domain is tried once (a `pending_domains` set), and `remaining_slots` is kept in memory and re-checked under the store lock.
- **Run budget:** at most `2 × room` searches, 2 verifications per lead, 60 Hunter calls in all, and **120 s** of Hunter time, polling included. A 202 is polled every 2 s within that budget, then the person is dropped.
- **Tests:** PostgreSQL interleavings of two runs on the same domain; a lease takeover mid-call; disconnecting or pausing during a call; repeated domains; a crash after a charge; an insufficient remainder (0.5 left blocks a search but allows a verify).

## R2.5 The key: a backend-only table (finding 5) — migration 042
`outreach_provider_accounts`:

| Column | Type / rule |
|---|---|
| `business_id` | FK |
| `provider` | `CHECK IN ('hunter')`; `UNIQUE (business_id, provider)` |
| `key_ciphertext` | text |
| `key_last4` | text |
| `generation` | int |
| `status` | `CHECK IN ('connected', 'invalid')` |
| `plan` | text |
| `pools` | jsonb: used/available per unit |
| `account_fetched_at` | timestamptz |
| `blocked` | jsonb: `{unit: until}` |
| `connected_by`, `connected_at`, `updated_at` | — |

Row-level security is on, with no policies and no client grants, as in 041. The key **never** enters `business_settings`, so the generic GET and PUT cannot return or overwrite it. Per-brand settings (switch, cap, notice binding) are not secret and stay in the research config.

- **Connect** (active owner only):
  1. validate with `GET /account`;
  2. encrypt (`encrypt_secret`; refuse if `EMAIL_ENCRYPTION_KEY` is missing);
  3. upsert with `generation + 1`.
- **Disconnect:** delete the row; `generation` is lost with it.
- A run reads the generation at its start, and every reservation and store checks it is unchanged. A changed generation stops Hunter for the run and **discards** results not yet stored.
- **Transport:**
  - header `X-API-KEY` only, never a query string;
  - `follow_redirects=False`;
  - a fixed host;
  - exceptions are logged as type and status code only;
  - the key is redacted from any `repr`.
- Tests: generic settings GET/PUT never show the key; failure logs carry no key or email; a missing encryption key; disconnect and key-replacement races; non-owners refused; another tenant's row never read.

## R2.6 Units, metering and quota (finding 6)
- **Units:** `X-Credits-Unit` ∈ {`credit`, `search`, `verification`}. Each is metered separately in `usage_meters` (`numeric(14,4)`, written exactly, **not** with the integer `_add_meter`): `hunter_credits:<unit>:<brand>` per UK calendar month.
- **Missing or malformed headers:** charge the reserved maximum, marked estimated.
- **The brand cap** is in credits. Under separate pools, a search counts 1 and a verification 0.5 towards it. A zero-cost repeat records 0.
- **429:** block **that unit's pool** in `blocked[unit] = reset_date 00:00 UTC`. A missing or past reset date blocks for 24 h and refreshes `/account`. A failed refresh keeps the block.
- **Blocks are persisted in the row**, never only in the cache.
- **`/account` cache:** only `plan`, per-pool used/available and `reset_date` are kept, with `account_fetched_at` shown as "as of". It refreshes at most hourly and is invalidated on connect.
- **Tests:** fractional charges, separate pools, a month boundary versus Hunter's billing period (shown as Hunter's own figures, labelled), a stale cache after a 429, and a missing header.

## R2.7 Which evidence row the footer uses (finding 7) — RED: the send path
- **The record:** the `email_verification` evidence row (one per prospect, written at acquisition) is authoritative. Its `source_url` is the page publishing the address (R2.1), even a directory. Company-registration facts are separate rows carrying the company page.
- **`build_payload` selection:** `fact_type = 'email_verification' ORDER BY fetched_at DESC, id DESC`. If no such row exists (imported contacts), today's selection is unchanged.
- **The footer** names Hunter only when that row's `source_type = 'hunter'`.
- **Existing contacts:** every web contact's rows share one `source_url`, so their footer and payload hash are byte-identical. A test covers each existing kind: web, imported and manual.
- Already-approved cards and claimed jobs dispatch their stored payload unchanged.
- **Tests:** mixed and tied evidence; a later verification row; an old web card approved after deploy; manual and automatic claims; dispatch of an already-claimed payload.

## R2.8 The notice and assessment binding (finding 8)
- **Confirmation** stores `{owner, notice_hash}` per brand: the SHA-256 of the brand's current approved notice text. The owner confirms the notice states:
  - that business contact details are obtained from public sources and from business contact databases including Hunter.io;
  - the categories collected;
  - retention (28 days unless emailed);
  - the owner's own identity, purposes, legitimate interests, rights and opt-out.

  Suggested wording is shown.
- **Re-confirmation:** any `approve_privacy_notice` that changes the hash invalidates the confirmation, and Hunter stays off until it is re-confirmed.
- **The assessment:** Hunter acquisition runs only for an audience whose **current approved assessment's `sources`** include `hunter.io`. The setup flow offers "re-approve this audience with Hunter as a source", a new version through the existing draft and approve path, with sourcing covered in the balancing test.
- **Checks:** before every Hunter acquisition, and before the **first send** of a Hunter-sourced contact; a mismatch refuses with "This brand's privacy notice changed; confirm it still names Hunter.io".
- Corporate-subscriber checks, sender identity and opt-out are unchanged.
- **Tests:** a confirmed notice then replaced; an assessment without Hunter; a first send after a notice change.

## R2.9 One corporate check, reused (finding 9)
The corporate part of `_verify` becomes `_corporate(fetch, companies, company, number, domain, page_url)`, with today's code paths and every exclusion unchanged:
- the final-host checks;
- visible registration binding the registered name to the number;
- sole trader and partnership detection;
- `TRADING_AS` and designer `CREDIT` exclusions;
- the trading-name domain fit;
- the home-page fallback.

Web candidates call it exactly as today. Hunter leads call it with Aria's cited company-owned page (contact or legal) when given, else the home page. Tests: a disclosure only on the contact page, an off-domain redirect, a designer's registration, and a trading name.

## R2.10 451 is honoured everywhere (finding 10)
- A 451 writes a tenant suppression: `key_type = 'email'`, the keyed digest only, reason `provider_claimed`. Nothing from the profile is stored.
- Every acquisition path already refuses suppressed keys (`_suppressed`, before verification and again under the store lock), so a later web candidate for the same address is refused.
- A pending candidate for that address in the same run is dropped.
- Tests: 451, then web rediscovery; a concurrent pending candidate.

## R2.11 Allowlist and erasure (finding 11)
Everything Hunter-related that is persisted:

| Where | What |
|---|---|
| The prospect row | As today. |
| Evidence rows | `email_verification` (R2.2/R2.7), `contact_type`, `segment`, `region`, `role_verified`, `companies_house`, and `source = hunter`, all linked to the prospect. |
| `usage_meters` | Aggregates only: business, unit, brand and month. |
| `outreach_provider_accounts` | No personal data. |
| Suppressions | A digest (R2.10). |

**Never persisted or logged:** raw responses, other people at the domain, Hunter's profile fields (LinkedIn, phone, twitter), or diagnostic payloads.

OUT-13 erasure already deletes never-contacted prospects with their evidence. Contacted subjects are retained under OUT-13's existing rules; that is a dependency, not something solved here.

Tests: erasing a Hunter contact leaves no source URL, verification fact, learning fact, card or summary text, and nothing in the account row or meters names a person.

## R2.12 Tests first (RED)
Revision 1's B-7 list, plus each finding's tests above, plus migration 042 rehearsed on the local PostgreSQL harness with its runbook (`audits/042-PROD-RUNBOOK.md`, staging first).
