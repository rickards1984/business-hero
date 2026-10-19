# AUTO-2 — Aria watches for replies to invoice chases

**Tier:** RED. It decides whether automatic contact about money continues, and it adds a migration.
**Builder:** Claude. **Reviewer:** Codex. **Tests first, reviewed by Mike.**
**Depends on:** AUTO-1 (PR #36).
**Decisions:** Mike, 19 Oct 2026. Flag the owner on any reply. When a customer says they've paid, show it and close chasing.

## Behaviour

### What counts as a reply

An email that meets all of these:
- it arrives in the business's synced inbox;
- it comes from the address of a customer Aria has chased, by any chase: automatic, or a card the owner approved;
- the chase was in the last 60 days;
- the email was received after that chase.

Matching is on the sender's exact address, ignoring case. These are never treated as replies:
- the business's own addresses;
- other businesses' inboxes;
- emails received before the chase.

**Which invoice it's about:**
1. the chase in the same email thread, if there is one;
2. otherwise, an invoice number of theirs in the subject or preview;
3. otherwise, every invoice of theirs that Aria has chased.

### What Aria does with it

1. **Any reply pauses automatic chasing for that customer**, on all their invoices, until the owner decides. This includes final-stage cards. A person has answered, so a person decides what happens next.
2. **The owner is told.** A "Needs you" card on the home page and a briefing line. Examples:
   - "Harper Builds replied about INV-0001 and says they've paid. I've stopped chasing them."
   - "Harper Builds replied about INV-0001. I've paused chasing until you've looked."
3. **Aria reads the reply** and labels it: *says they've paid*, *promises to pay*, *disputes it*, *has a question*, or *other*. If reading it fails, it's labelled *couldn't read it*, and it is still flagged and still pauses chasing. The label never sends anything: whatever it says, chasing is already paused.
4. **The owner decides** on the card:
   - **Resume chasing.** Normal rules apply again, including the 7-day gap.
   - **Stop chasing this invoice.** The invoice is never chased automatically again. The owner can still chase it by hand.
5. **"Says they've paid" never marks the invoice paid.** Money stays with the owner and the accounts software: payment is recorded in Xero, or with Mark as paid, as today.

### Aria must have read the inbox before chasing

An automatic chase goes only if the sending mailbox's inbox has synced successfully within the last 3 hours, **and** that sync was complete.
- **Microsoft** syncs by delta, which is complete.
- **Gmail** today reads only the latest 50 messages. A Gmail sync counts as complete only if it reached a message it had already stored, and no message failed to fetch. Otherwise there may be unseen replies, so Aria doesn't chase. The reason is shown as "inbox_not_fresh".

Each hourly run syncs the inbox, then reads replies, then chases.

### The right mailbox

Chases are sent from the business's **default** mailbox:
- the one marked default;
- or the only one connected;
- never the newest by date.

The mailbox is fixed into the card when it's drafted. The outbox records the mailbox that actually sent. If several mailboxes are connected and none is marked default, automatic chasing stands down ("no_default_mailbox") and asks the owner to choose one.

This also fixes manual chase cards, and keeps replies landing in the inbox Aria reads.

## Database — migration 036 (RED, runbook for Mike)

A new table, `chase_replies`:
- **Columns:** id, business_id, email_message_id, customer_email, invoice_ids, category, summary, status (`open` / `resumed` / `stopped`), resolved_by, resolved_at, created_at, updated_at.
- **Unique:** one row per business per message.
- **CHECK** on status and category.
- **RLS:** members may SELECT; there are no browser writes.
- **Grants:** as for `aria_actions` (035).

Outreach's OUT-3 then takes 037.

## Not in this ticket

- Full Gmail history sync (the history API with a watermark). That comes before outreach replies (OUT-7), as AUTO-2b. Until then, the completeness rule above means a busy Gmail inbox makes Aria wait rather than guess.
- Replying to the customer. Aria flags; the owner answers.
- Replies that land outside the inbox (filters, other folders).

## Tests

- `backend/tests/test_chase_replies.py` (SQLite, the behaviour above).
- Postgres checks for 036 in `backend/tests/test_chase_replies_rls.py` (skipped without `RLS_LOCAL_DATABASE_URL`).
- AUTO-1's suite gains a fresh, complete inbox sync in its fixture. Its tests are otherwise unchanged.

## Click tests (after merge and the 036 runbook)

1. With chasing on, send yourself a chase, then reply "I paid this yesterday". Within about an hour, the home page shows the reply card labelled *says they've paid*. No further chase goes to that address.
2. Press **Stop chasing this invoice**. The card closes, and the invoice is not chased again.
3. Repeat with a reply that asks a question, and press **Resume chasing**. Chasing continues after the 7-day gap.
