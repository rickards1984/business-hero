# RCP-1: a receptionist phone number, requested in the app and set up in one click

**Tier:** RED (it spends money with Twilio, and it decides which business answers a phone line). **Builder:** Claude. **Reviewer:** Codex. **Tests first (Opus).**

## Why (Mike, 13 Nov 2026)

Switching the receptionist on in MSC failed: *"Cannot enable receptionist without a phone number assigned. Please contact support."* That is correct behaviour, but the customer is left with nothing to do. Mike's points:
- everything except the number is already the customer's to set up (knowledge, voice, greeting, hours);
- the app should let them ask for a number, and walk them through it in beginner-friendly steps;
- if the receptionist is an add-on, offer a paid "set this up for me" service;
- if the receptionist is in their plan, setup is covered by the setup fee and subscription.

Mike chose **option C (hybrid)**: the customer asks in the app, and Mike approves; the approval buys and configures the number.

## How it works today (origin/main, 13 Nov 2026)

- `PATCH /v1/receptionist/config/toggle` refuses when there is no `twilio_phone_number` (`receptionist_api.py:453`). The UI shows "No phone number assigned — contact support" (`ReceptionistTab.tsx:805`).
- Owners **cannot** set the number. `ReceptionistConfigCreateUpdate` has no number field. This is right: a typed-in number could take another business's calls.
- Only a platform admin sets it, by either:
  - `PUT /v1/admin/receptionist/{business_id}/phone-number` (`AdminReceptionistSection.tsx`), or
  - the admin onboarding wizard's `receptionist_setup` step.
- **Nothing talks to Twilio's number API.** Buying the number and setting its voice webhook to `/v1/receptionist/incoming-call` are done by hand in the Twilio console.
- Incoming calls are routed by `ReceptionistConfig.twilio_phone_number == To AND enabled`, `.first()` (`receptionist_call_handler.py:537`). **`receptionist_configs.twilio_phone_number` has no UNIQUE constraint** (`audits/live-schema-public.txt:1067`), so two businesses given the same number would split its calls arbitrarily.
- A business that is not paying (DECISION 3) has its calls refused (`receptionist_call_handler.py:564`). `docs/BACKLOG.md` line 27 records that **MSC resolved to SUSPENDED** (9 Oct 2026). Re-check this before MSC goes live: a number alone will not make MSC answer calls.

## What the customer gets

In **AI hub → Receptionist**, the "no number" state becomes a short guided panel:

1. **Choose how callers will reach you:**
   - **Keep my existing number** (recommended for most). We give you a new number behind the scenes, and you forward your current line to it, either always or only when you don't answer. Step-by-step forwarding instructions are shown for the common UK providers (BT, Virgin Media, Vodafone, EE, O2, Three, and VoIP systems in general), with links to each provider's own help page.
   - **A new local number:** pick an area (town, or area code).
   - **A new non-geographic number** (03…) **or mobile** (07…), if Twilio offers that type at the time of building.
2. **Business details for the UK regulator:** the business's legal name and registered address, prefilled from the business profile. UK numbers need a Twilio regulatory bundle; the panel explains why in one sentence and says approval can take a few days.
3. **Who sets it up:**
   - receptionist **in the plan**: "We'll set this up for you." No charge.
   - receptionist **as an add-on**: either "I'll follow the steps" (free), or **"Set this up for me"** (paid; price to be decided by Mike, see below).
4. **Submit.** The panel then shows the request's status: *Requested → Waiting for UK approval → Live*, with a **Test call** button once the number is live.

The toggle stays refused until a number is live, but the message points to this panel, not to "contact support".

## What Mike gets (admin)

- An **admin card** for each request: business, plan, number type, area, regulatory details, and paid setup yes or no.
- **Approve** does, in order, each step recorded:
  1. finds an available number of the requested type and area (`AvailablePhoneNumbers`), and shows it before buying;
  2. on Mike's confirm, buys it (`IncomingPhoneNumbers` create), with `VoiceUrl` = the production `incoming-call` URL (POST) and the regulatory bundle / address attached;
  3. assigns it to the business (the same write as today's admin endpoint);
  4. tells the customer it is live (in-app notice and email).
- **Decline**, with a reason the customer sees.
- If the bundle is still pending, the request waits in *Waiting for UK approval*, and Approve completes once Twilio approves it.

**No number is bought without Mike's confirm.** No customer click spends money.

## Rules (each one tested)

- **R1. One number, one business.** Add `UNIQUE (twilio_phone_number)` (with NULLs allowed) in a migration with a runbook. Check for existing duplicates first (read-only STEP 0). The admin assign endpoint and onboarding step return a clear 409 on a clash, not a 500.
- **R2. Owners can never set or change the number themselves.** Requests carry a number *type and area*, never a number.
- **R3. Purchase is idempotent.** Each request has one purchase record. A retried Approve, a double click or a timeout after Twilio has bought the number never buys a second number. Before buying, look for a number already tagged with this request (Twilio `FriendlyName`), and adopt it.
- **R4. Webhook check.** After buying, read the number back from Twilio and confirm `VoiceUrl` and method match. If they don't, the request shows "bought, not configured" with a retry, and the number is not assigned.
- **R5. Entitlement.** A request needs the `receptionist` feature (plan or add-on) and a paying business (the DECISION 3 resolver). A suspended business can't request.
- **R6. Costs.** Each number's monthly Twilio cost goes to the running-costs ledger (`services/running_costs.py`) against the business, so the profit view shows it (profit rule).
- **R7. Release.** When a business stops paying, or the receptionist is removed, the number is listed for Mike to release. It is never released automatically in RCP-1, because a released number can't be got back.
- **R8. No secrets in the browser.** Twilio is called only from the backend, with the existing `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN`.

## Decisions for Mike (defaults proposed)

1. **Price of "Set this up for me" for add-on customers.** Proposed: a one-off fee covering your time plus margin, charged through Stripe like other add-ons. Name a figure.
2. **Who pays the number's monthly cost** (roughly £1–£5 per month depending on type; check current Twilio pricing). Proposed: included in the plan or add-on price, and recorded as a cost (R6).
3. **One Twilio account, or a subaccount per business.** Proposed: **one account** for RC1, which is simpler. Subaccounts later, if per-customer billing or isolation is needed.
4. **Number types offered.** Proposed: local (geographic) only at first, plus "keep my number" by forwarding.

## Out of scope

- Porting a customer's existing number into Twilio. Forwarding covers "keep my number".
- Receptionist metering and allowances. Already a known gap (`docs/CURRENT_STATE.md`: "ungated and unmetered"); **it should land before or with RCP-1**, because easier setup raises the call-cost exposure.
- Automatic number release (R7).

## Acceptance

- [ ] An MSC owner (non-admin) requests a local number in the app, and sees the forwarding steps.
- [ ] Mike approves on staging with Twilio test credentials (test credentials can't buy real numbers; use Twilio's documented test number `+15005550006`). The request reaches *Live*, and the toggle then works.
- [ ] R1–R8 have tests. The purchase path is tested with a fake Twilio client, including a timeout after purchase (R3) and a wrong `VoiceUrl` (R4).
- [ ] The UNIQUE migration is run from a runbook, staging first.
- [ ] Production: one real number bought for MSC through Approve, and Mike's test call is answered.
- [ ] Codex review preserved verbatim in `audits/`.
