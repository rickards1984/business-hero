# AUTO-3 — One chase email per customer, listing all their overdue invoices

**Tier:** RED: automatic customer contact about money. **Builder:** Claude. **Reviewer:** Codex. **Tests first, approved by Mike before any code.**
**Decision:** Mike, 23 Oct 2026, after his own test invoices on 22 Oct. The autopilot chased an old £1.05 invoice at stage 3, and the one-chase-a-week rule then held back his newer invoice to the same customer.

## Why
Today the autopilot chases one invoice per email, oldest first, and sends at most one email per customer per week. So a customer who owes three invoices hears about only one each week, and a small old invoice can use up the week's chase.

## Behaviour
1. **One email per customer, covering every overdue invoice they owe.**
   - A customer is chased when at least one of their invoices is due for a chase under today's rules (stage 1 at 7 days overdue, then every 7 days).
   - The email lists **every** invoice of theirs that is past its due date and still owed: its number, the amount **still owed**, and its due date, with a total.
2. **The email's stage is the next stage of the customer's most overdue invoice.** Each listed invoice then moves up one stage (never backwards, never above 4). Its "last chased" date becomes today.
3. **At most one email per customer per week, as now.** Every other rule stays:
   - weekdays 09:00–17:00 UK;
   - the daily cap, which counts emails, not invoices;
   - paused customers;
   - replies pause the customer (AUTO-2);
   - the default mailbox only;
   - an unconfirmed send blocks that customer.
4. **Stage 4 is still always a card, never an automatic send.** If the email's stage would be 4, the owner gets a card listing all the invoices.
5. **An invoice the owner stopped chasing** (from a customer's reply) is left out of the email. The customer's other invoices are still chased.
6. **Settled before sending:** if any listed invoice is paid, cancelled, archived or already chased by the time of sending, **nothing is sent**. The next hourly run drafts a fresh email. A card the owner taps follows the same rule.
7. **A single overdue invoice** gives the same email as today, except that it shows the amount still owed (see decision C).

## Decisions for Mike (each with a recommendation)
- **A. Which invoices are listed?** *Recommended: every overdue invoice of that customer, even one only a day overdue.* This matches "all overdue invoices". The alternative lists only invoices 7+ days overdue.
- **B. An open card for one of the customer's invoices** (a stage-4 card, or one Aria drafted in chat). *Recommended: the customer is skipped until that card is approved, dismissed or expires.* This avoids two emails about the same debt. The alternative leaves that invoice out and emails the rest.
- **C. Amount shown.** *Recommended: the amount still owed*, for single-invoice chases too. Today a part-paid invoice is chased for its full amount, which is wrong.
- **D. Aria's chat chases** ("chase invoice 123"). *Recommended: unchanged, one invoice per card, for now.* Only the autopilot combines.

## Contract
- `email_templates.get_combined_chase_email_template(stage, customer_name, invoices, business_name) -> {"subject", "body"}`. `invoices` is a list of `{"invoice_number", "amount", "due_date"}`, where `amount` is the amount still owed. The body lists each invoice and the total.
- `aria_actions.propose(..., "send_invoice_chase", {"invoice_ids": [...], "chase_stage": S})` builds a combined card. Its payload is today's single-invoice payload plus:
  - `invoice_ids`: every listed invoice, ordered by due date;
  - `invoices`: a list of `{invoice_id, invoice_number, amount, due_date, stage}`, where `stage` is that invoice's stage after this send;
  - `total`.
  - `invoice_id` is the most overdue invoice; `chase_stage` is S.
- `{"invoice_id": ...}` alone builds exactly today's single payload, except for the owed amount (decision C).
- `run_invoice_autopilot(...)`: `sent` and `cards` list **every** invoice in a sent email or card. `skipped` is unchanged.
- Recording a sent chase: one `email_outbox` row (invoice_id = the most overdue, chase_stage = S). Then each listed invoice's stage goes up, never backwards, and its `last_chased_at` is set to now.

## Files
- `backend/services/automations.py`
- `backend/services/aria_actions.py`
- `backend/email_templates.py`
- `backend/tests/test_combined_chase.py` (new)
- `backend/tests/test_auto_chase.py`: one test changes meaning (below)

No migration.

## A test that changes meaning (needs Mike's approval)
`test_one_chase_per_customer_per_week` asserted that two overdue invoices for one customer give **one email about one invoice**, with the other skipped. Under AUTO-3 the answer is **one email covering both**. The test is replaced by `test_two_overdue_invoices_one_customer_one_email` in the new file. The one-email-a-week rule itself is still tested, by `test_a_customer_chased_by_hand_this_week_waits` and `test_running_twice_sends_once`.

## Not in this ticket
- Combining Aria's chat chases (decision D).
- Statements or attachments.
- Any change to reply handling (AUTO-2 already matches replies per customer).

## Tests
`backend/tests/test_combined_chase.py`, strictly xfailed until the code exists.

## Mike's approval — 23 October 2026
- The tests and decisions A–D are approved as recommended. The meaning change to `test_one_chase_per_customer_per_week` is approved.
- **Addition to D (Mike):** when the owner asks Aria in chat to chase an invoice that was already chased in the last 7 days, Aria says when it was chased and asks whether to chase it again. Only if the owner says yes does she draft the card (`chase_again: true`). The owner's tap still sends it.
  - Tests: `test_a_chat_chase_of_an_invoice_chased_this_week_asks_first`, `test_after_the_owner_says_yes_the_card_is_drafted`, `test_an_invoice_not_chased_this_week_needs_no_question`, `test_aria_can_say_chase_again`.
  - The autopilot is unaffected: its own spacing rules already apply.

## Build — 23 October 2026
- `email_templates.get_combined_chase_email_template`: the same tone as the existing stage templates, with a list of invoices and a total.
- `aria_actions`:
  - `_combined_chase_payload`: one customer and one business only, two or more different invoices, all still owed; each invoice records `stage_was` and `stage`;
  - single chases now quote the amount **still owed** (decision C);
  - `_combined_out_of_date`: approval refuses if any listed invoice is gone, settled or chased since drafting, or if the customer replied (automatic chases);
  - bookkeeping advances every listed invoice, never backwards;
  - the chat rule: `_recently_chased` plus `chase_again`. Automatic proposals never ask.
- `automations.run_invoice_autopilot`: the customer's listed invoices are every past-due, owed, not-stopped invoice, oldest first. An open card for any of them holds the customer (decision B). The stage is the most overdue invoice's next stage, and stage 4 means a card. `sent`/`cards` list every invoice; invoices already covered this run are skipped silently.
- Home: `recent_automated` gives every invoice number and `invoice_count`, and the home line counts invoices, not emails.
- **A second meaning change in AUTO-1's suite:** `test_an_old_ticket_with_a_waiting_automatic_draft_is_not_reclaimed`. Decision B now holds the customer *before* the ticket check, so the reason may be `card_waiting` instead of `chase_in_progress`. The protected property (nothing sent, stale ticket untouched) is now asserted directly.
- Verification: `test_combined_chase.py` (31) and `test_auto_chase.py` (93 passed in total across both); `./check.sh full` is green.

## Codex review 1: REQUEST-CHANGES, three P1s (repair cycle 1)
Preserved verbatim in `audits/AUTO-3-CODEX-REVIEW-1.md`.
1. **A part-payment after drafting still sent the old amounts.** Every invoice on a card (single or combined) now records the amount owed, the customer, the stage and the last-chased time. Approval refuses ("out of date") if any of these has changed (`_drifted`).
2. **A reply to a combined chase reached only the lead invoice.** `chase_replies._chases` now expands a combined chase into every listed invoice, so "I paid both" and Stop reach them all. Naming one invoice still picks just that one.
3. **An invoice moved to another customer was still emailed to the first.** This is covered by the same check: the invoice's current customer must be the card's recipient.

The P2s are also fixed:
- two stale final-stage cards can no longer both send, because the last-chased time must be unchanged;
- a chat "chase again" for a stage-4 invoice is now approvable, once.

Tests: 7 new. The suites have 227 passing; `./check.sh full` is green.

## Codex review 2: APPROVE, no P1 (`audits/AUTO-3-CODEX-REVIEW-2.md`)
Backlog (P2):
1. Two **separate** cards for overlapping invoices, approved at the same instant, can both send. Each card is claimed only once; overlapping debts are not locked together. The autopilot never makes two such cards (decision B), so this needs the owner to draft two by hand and tap both together. Fix: a per-customer lock at approval.
2. A due-date change after drafting does not invalidate the card. Fix: add the due date to `_drifted`.
