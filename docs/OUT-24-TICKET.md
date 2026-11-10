# OUT-24 — Lift the limit of 5 contacts per campaign

**Asked for:** Mike, 10 Nov 2026. Research found only 1–4 contacts a day. This is step 1 of the order Mike chose: OUT-24 → OUT-13 erasure → the OUT-23 bank → Hunter → running low.

**Why the limit was there:** OUT-10 decision E kept 5 pending or active contacts per campaign for the pilot. `OUTREACH_PILOT_ENROLMENTS=0` lifts it, but OUT-8 note 2 and HK-1 required one thing first. Each email's card was found by loading, and in `prepare` locking, **every** open card, once per enrolment.

**Effect of the limit today:** with an inbox at 5 a day, a campaign is full on day one and nothing new is emailed for about 12 working days, until those 3-email sequences finish.

## Change
1. **`outreach_send.open_card(session, bid, enrolment_id, lock)`** finds an email's open card by its enrolment: `OPEN_CARD_WHERE`, `(payload->>'enrolment_id') = :enrolment`. It is used by:
   - the owner's `prepare`, which still reports the card already waiting;
   - research's morning `_prepare_cards`.

   The autopilot reads open-card enrolment ids in one query (`open_card_enrolments`), not whole payloads.
2. **No second card for the same email.** The check is made where every card is made, `outreach_send.build_payload`, under the business lock held to commit.
   - Before, the morning preparation, the owner's prepare and the autopilot each checked separately, outside one lock, and two could each create a card.
   - A refused attempt rolls back, so it leaves no unsubscribe token.
   - The send path's own "two cards send once" defence is still tested, with a copied card.
3. **Migration 040** (`backend/migrations/040_outreach_card_lookup.sql`) indexes exactly that expression and predicate.
   - RED; runbook `audits/040-PROD-RUNBOOK.md`; staging first.
   - It waits at most 5 s for its lock and stops at 60 s.
   - Its STEP 3 is Mike setting `OUTREACH_PILOT_ENROLMENTS=0` in Railway once this is deployed.

## Tests
- `backend/tests/test_outreach_card_lookup.py` (7): the right card among 500; preparation never reads every open card; a second card is refused and leaves no token; the morning preparation twice makes one; the owner's prepare reports the waiting card; a closed card doesn't block; migration 040 indexes the lookup's exact expression.
- `backend/tests/test_outreach_send_rls.py` (PostgreSQL harness, migration 040 applied):
  - a second card is refused;
  - two cards asked for at the same moment make exactly one, with one token;
  - the index exists with the lookup's exact definition;
  - two copied cards still send once.
- **Mutation-checked:** without the guard, or without the business lock, the tests fail.
