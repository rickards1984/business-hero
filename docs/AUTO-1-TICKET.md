# AUTO-1 — Aria chases overdue invoices on autopilot (standing permission)

**Tier:** RED (automatic outbound customer contact about money).
**Builder:** Claude. **Reviewer:** Codex. **Tests first, reviewed by Mike.**
**Decisions:** `docs/AUTOMATION-AND-OUTREACH-PLAN.md`, Mike's decisions of 19
Oct 2026 (order agreed; chasing defaults agreed). North Star P4: autonomy is
earned one action type at a time.

## Behaviour

**Off by default.** The owner switches it on in **Settings → Aria → What Aria
can do on her own** (stored in `business_settings.settings.automations
.invoice_chasing`; no migration).

**Mike's defaults:**
- **When to start:** stage 1 once an invoice is **7 days** overdue.
- **How often:** then every **7 days**, up to **stage 3**.
- **Stage 4:** always proposed as a **card** for a tap, never sent
  automatically.
- **Per customer:** at most **one chase per customer** (by email address)
  every **7 days**, across all their invoices.
- **When:** **weekdays, 09:00–17:00 UK** only.
- **Daily cap:** at most **20** automatic chases per business per day.

**Never chases:**
- an invoice that is paid, cancelled, draft, archived, or has no balance owed
  (the same receivables rule as the home, `services/home_summary.py`);
- an invoice with no customer email;
- a customer on the owner's **paused** list;
- an invoice with an open card already waiting;
- for a read-only or suspended account;
- for a plan without invoicing and email.

**How a chase is sent.** Through NS-B10 unchanged: `propose()`, then
`approve()` by the system. So the same guarantees apply:
- the stored template is exactly what is sent;
- it is sent once (the claim);
- it is recorded in `email_outbox`;
- the invoice's `chase_stage` and `last_chased_at` move forward;
- it has the AI-assistant sign-off.

The action is marked `payload.automation = "invoice_chasing"`, with
`approved_by` empty, so the audit trail shows it was a standing permission.

**The home tells the owner.** A **"While you were away"** line and list (the
last 7 days of automatic chases) appear in the briefing and under the hero.

**The scheduler** runs it hourly, off the event loop, with no overlapping
runs.

## Not in this ticket

- Watching replies, and pausing on reply (that's AUTO-2).
- Late-payment interest (a later stage-4 option).
- Other automations.
