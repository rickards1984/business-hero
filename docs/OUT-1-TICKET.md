# OUT-1 — B2B outreach inside Business Hero: the DESIGN (Stage 0)

**Builder:** Codex. **Reviewer:** Claude. **Decides:** Mike.

**Read first:**
- `AGENTS.md`;
- `docs/NORTH_STAR.md`;
- `docs/AUTOMATION-AND-OUTREACH-PLAN.md`, **especially "Mike's decisions —
  19 October 2026"**, which govern this ticket.

**This ticket is a design document only, `docs/OUT-1-DESIGN.md`. No code, no
migrations.** A module of this size needs Mike's agreement on the design
before any tests or code. RED parts (migrations, Stripe, sending email to
third parties) follow as their own tickets.

## What exists to build on (verify in code; cite file:line)

- **NS-B10 approval cards** (`services/aria_actions.py`): send-once, version-
  bound, audit trail; the AI-assistant sign-off.
- **The email sync** (`app/email/`): `email_messages` (`provider_thread_id`,
  `ai_category`); the connected mailbox (Google/Microsoft OAuth);
  `email_outbox`.
- **Metering** (`services/metering.py`, generic meters, the voice pool):
  outreach is the second-largest cost (`audits/PRICING-MODEL.md` §2).
- **Entitlement:** `auth.CANONICAL_FEATURES` already has `outreach`; plan
  gating via `require_feature`.
- **The receptionist's knowledge base** (`receptionist_api.py`) is the model
  for "product knowledge" when answering replies.
- **The scheduler** (`services/briefing_scheduler.py`) and its patterns:
  off-loop work, background tasks, no overlap.
- **The OpenClaw system being replaced, for MSC and New Body/FitFutures:**
  - the queue fields are `id, business, segment, company, contact_name,
    contact_email, subject, body, status (sent / send_failed /
    template_approved), approved_at, sent_at, gmail_message_id,
    gmail_thread_id, reply_status, reply_checked_at,
    last_known_message_count, followup_count, followup_due_at,
    followup_history, last_followup_at, escalation_status, notes,
    created_at`;
  - routing has segments (e.g. `smb_owner`);
  - research, writer and follow-up agents.
  - **Do NOT open the OpenClaw files themselves.** They contain real
    people's personal data. Design from the field list above.

## The design must cover

1. **Information architecture and UI.** Outreach as a department in the
   menu. Survey what leading outreach/CRM tools offer (e.g. Apollo,
   Instantly, Lemlist, HubSpot sales, Pipedrive) from your own knowledge, and
   say what Business Hero matches, beats or deliberately leaves out. Then
   design the screens, as wireframe descriptions:
   - an overview (pipeline and results);
   - prospects (filters and fit scores);
   - a prospect's page (timeline);
   - campaigns and sequences;
   - a replies inbox, with Aria's suggested responses;
   - a suppression list;
   - settings (sending limits, product knowledge, sign-off).

   It must fit the Aria-centred shell (NS-B7) and use approval cards.
2. **The data model.**
   - Tables, columns, constraints, indexes, RLS and grants, following the
     033/035 patterns (RLS on, member SELECT, backend writes).
   - Tenant isolation.
   - A retention policy (e.g. unanswered prospects deleted after 12 months).
3. **Research ("much smarter", Mike).**
   - Finding **decision makers** through Companies House (company and
     officers, free API), the prospect's own website (About / Team pages),
     and public search-result previews.
   - **Never scraping LinkedIn.** Say exactly what is and is not allowed, and
     which search API (and cost) it needs.
   - Fit scoring and a "why now".
   - The model choice: provider-agnostic, using the latest capable models,
     configurable.
   - Costs per prospect, and the meters.
4. **Sending and sequences.**
   - The first batch of each campaign comes as cards.
   - Then an optional standing permission (the AUTO model).
   - Daily caps, mailbox warm-up, quiet hours, follow-up timing, and
     stopping on reply.
   - Deliverability: SPF/DKIM/DMARC checks; one-click unsubscribe headers.
5. **Replies (Mike: "needs to seem more natural").**
   - Sort each reply (interested, question, not now, unsubscribe, out of
     office, wrong person, referral).
   - Answer basic questions from the product knowledge, at most once,
     through an **Approve response** card. Optionally CC the owner.
   - A booking link only on clear interest.
   - Hand over to the owner.
   - Never pretend to be human.
6. **UK compliance** (PECR, UK GDPR):
   - corporate vs individual subscribers, checked through Companies House;
   - the legitimate interests assessment (LIA) template;
   - Article 14 notice;
   - opt-outs and suppression;
   - retention;
   - honouring the right to object.
7. **The import.**
   - MSC history → the MSC account; FitFutures (UKFI) and New Body history →
     the New Body account. Business Hero's own history is **not** imported.
   - Field mapping; de-duplication; opt-outs → suppression; a dry-run
     report; idempotent re-runs.
8. **Plans and billing.**
   - Included in Business; a paid add-on for Starter and Pro; a standalone
     outreach-only product.
   - What that needs in entitlement and Stripe (later RED ticket).
   - Meters (prospects researched, emails sent) and suggested allowances.
9. **Aria integration.**
   - Read tools for outreach data (North Star rule).
   - Outreach items on the home: replies under **Needs you**; results in
     the briefing.
10. **Delivery plan.**
    - Split into tickets (OUT-2…), each sized and tiered GREEN/AMBER/RED.
    - Say which need migrations and runbooks.
    - Say what to build first so New Body/FitFutures and MSC can restart
      outreach soonest.

**Mark anything you could not verify as UNVERIFIED.** End the document with
**Decisions for Mike**: numbered, each with a recommendation.

## Rules

- Your sandbox writes only inside this worktree. **Do not git commit or
  push.** Claude reviews and commits.
- No network; no production; do not read `~/.openclaw`.
