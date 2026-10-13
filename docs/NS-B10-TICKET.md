# NS-B10 — Aria drafts, the owner approves with a tap, Aria acts once

**Tier:** RED (outbound customer contact about money; a new table; entitlement).
**Builder:** Claude. **Reviewer:** Codex. **Tests first, reviewed by Mike.**
**Decisions it implements:** ADR 0001 D9 (approve then send), D11
(`create_task` via the card; `delete_task` stays refused), D12 (signed as an
AI assistant), D15 (calendar booking joins the card), D18 (in RC1 approval is
a tap, even in voice). North Star P4: *Aria proposes, the owner decides.*

## What the owner sees

In Aria chat the owner asks: "chase Harper for the overdue invoice." Aria
drafts the chase. A **card** appears under her reply. It shows exactly what
will go out: recipient, subject, the whole body and the sign-off. It has three
buttons: **Approve and send**, **Edit** and **Not now**. One tap sends it
once, from the owner's own mailbox. The card then says "Sent at 10:42". Calendar bookings and
new tasks work the same way, with **Approve booking** or **Add task**.

Aria never sends, books or creates on her own. A "yes" typed or spoken to her
is NOT an approval. Only the tap is.

## The four actions

| Tool Aria calls | Card | On approval |
|---|---|---|
| `send_email` | Email | Sent from the connected mailbox; recorded in `email_outbox` |
| `send_invoice_chase` | Invoice chase | The existing chase template for the stage; recorded in `email_outbox` with `invoice_id` and `chase_stage`; the invoice's `chase_stage` / `last_chased_at` updated |
| `create_calendar_event` | Booking | Created in the calendar named on the card |
| `create_task` | Task | Task created |

`delete_task` stays refused (D11). Event removal is Phase 2 (D16). Quotes
(`_send_quote_via_aria`) are not in this ticket.

## Design

**One new table, `aria_actions`.** Migration 035, with a staging rehearsal and
a production runbook (all production SQL is RED). Why it isn't reused:
- `email_drafts` requires an inbound `email_message_id`, and holds only email.
- `whatsapp_pending_actions` executes before it marks itself executed and
  never checks its expiry (gap analysis §B6, RC1_SCOPE_PROPOSAL B10).

```
aria_actions
  id uuid pk, business_id uuid not null, proposed_by uuid (user in the chat),
  action_type text  CHECK in (send_email, send_invoice_chase,
                              create_calendar_event, create_task),
  payload jsonb     the exact thing that will be done (incl. the sign-off)
  status text       CHECK in (proposed, executing, done, failed,
                              dismissed, expired)
  approved_by uuid, approved_at, executed_at, expires_at,
  result jsonb, error text, created_at, updated_at
```
- RLS on, with a member SELECT policy. Clients get SELECT only; the backend
  writes (the 030b pattern).

**Proposing.** When Aria calls one of the four tools, the server does not
act. It validates the arguments, renders the final content and stores a
`proposed` row:
- *Validating:* the invoice belongs to this business; the recipient's address
  is well-formed; the time is valid in the business's timezone.
- *Rendering:* the chase template plus the sign-off.

The model is told: "Shown to the owner as an approval card. Nothing has been
sent." The chat response gains a `proposals` list, and the frontend renders
the cards. The NS-A1 refusal is replaced by the proposal at both chat
boundaries. **The voice executor keeps refusing**: voice is off, and the voice
repair will route to the same cards (D18).

**Approving.** `POST /v1/aria/actions/{id}/approve`:
1. Checks the business and the plan:
   - The action belongs to the caller's business.
   - The account has full access: `enforce_access` refuses read-only and
     suspended.
   - The plan includes `aria_chat` plus the feature for that action
     (`auth.CANONICAL_FEATURES`): email → `email`; chase → `invoicing` +
     `email`; booking → `calendar_sync`; task → nothing more.
2. Claims the action atomically:
   `UPDATE … SET status='executing', approved_by, approved_at
    WHERE id=:id AND business_id=:b AND status='proposed' AND expires_at > now()
    RETURNING payload`.
   - No row means it was already used, dismissed or expired → 409, and nothing
     happens.
   - Two taps send once.
3. Executes **exactly the stored payload**. The model's words are never
   re-read and nothing is regenerated.
4. Records the outcome: `done` with its result, or `failed` with the error.

**At most once.** If the server dies between the claim and the outcome, the
action stays `executing` and is never retried automatically. The card says
"We can't confirm this was sent. Check your Sent folder before trying again."
For customer contact, a missing chase is cheaper than a double chase.

**Editing.** `PATCH /v1/aria/actions/{id}` works only while the action is
`proposed`:
- The owner edits the subject, body, time or task text.
- The server re-validates and re-renders. The sign-off is not editable.
- Approving is then of the edited version, which is what the card shows.

**Not now.** `POST …/dismiss` sets the action to `dismissed`.

**Expiry.** A proposal expires after **72 hours** and the card then says
"Expired. Ask Aria again".

**Sign-off (D12).** The server appends it to every email and chase. It is a
template (`{assistant_name}`, `{owner_name}`, `{business_name}`) so the B9
rename flows in. Every line in it must be true. Three options for Mike:

> **A.** Aria
> AI assistant to Mike at New Body Gym
> I pass every message straight to Mike. Reply to this email and it reaches him.

> **B.** Best wishes,
> Aria — AI assistant, New Body Gym
> Sent on Mike's behalf; your reply goes straight to him.

> **C.** Aria | AI assistant to Mike Rickards, New Body Gym
> I look after Mike's admin and make sure he sees every reply.

**Not in this ticket:**
- standing permissions ("always let Aria send chases");
- approval cards on the home screen (they arrive with B7; the card component
  is built here for reuse);
- spoken approval (Phase 3, D18);
- WhatsApp approvals.

## Acceptance (the tests encode these)

1. Each of the four tools, called by the model in chat, stores a `proposed`
   action and returns a proposal. Nothing is sent, booked or created:
   no provider call, no `tasks` row, no `email_outbox` row.
2. Approve executes the stored payload once:
   - a second approve, or two concurrent approves, executes nothing and
     returns 409;
   - the provider receives exactly the stored subject, body and recipient.
3. Approve refuses:
   - another business's action (404, not 403: its existence is not leaked);
   - a read-only or suspended account;
   - a plan without the feature;
   - an expired, dismissed, done, failed or executing action.
4. A failed send is recorded `failed` with the error, never retried
   automatically, and the card can show it. A crash mid-send leaves the action
   `executing`, and it is never sent again.
5. Edit works only while `proposed`; it re-validates, and the sign-off cannot
   be removed or altered.
6. Chase: the invoice must belong to the business and be unpaid when proposed
   AND when approved (paid in between → refused, "already paid"). It records
   `email_outbox` with `invoice_id` and `chase_stage`, then advances the
   invoice's chase stage, once.
7. Booking: the time is valid in the business's timezone (summer/winter, and
   clock-change gaps refused as NS-R1 does). It is booked into the calendar
   shown on the card.
8. `delete_task` is still refused; voice still refuses all five actions;
   `test_aria_no_unapproved_actions.py` is updated only where a refusal
   deliberately becomes a proposal.
9. Clients cannot write `aria_actions` (RLS/grants checked in the staging
   rehearsal, as for 034).

## Decisions for Mike

1. **The new `aria_actions` table** (migration 035, runbook as for 034).
   *Recommended.*
2. **The sign-off:** A, B or C (or edit one). *Recommended: A.*
3. **Expiry of 72 hours.** *Recommended.*
4. **At most once:** a crash mid-send is never retried automatically.
   *Recommended.*
5. **Who may approve:**
   - *Recommended:* any member of the business with full access.
   - *Alternative:* owner role only.
