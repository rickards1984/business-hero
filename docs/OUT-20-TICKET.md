# OUT-20 — Outreach setup that a small business owner can finish

**Tier:** YELLOW (setup screens and help). The redraft spends AI money, recorded in the OUT-19 ledger. Stacked on #54 (OUT-19).

**From Mike's click test, 25 Oct 2026.**

## What changes

1. **Saying what's happening.** Every save and every Aria draft shows a spinner and what is happening ("Saving your brand…", "Aria is writing your three emails — usually 10–20 seconds…"), with a light "making a little magic…" if it takes longer.
2. **Speed.** A wizard save refreshes only setup status, plus the outreach lists when campaigns or mailboxes change. Before, it refreshed every outreach view.
3. **Guidance at each step.**
   - Step 1 explains that Aria writes from the brand details.
   - The audience step asks for specifics.
   - The emails step points to the brand details when they are missing.
4. **Brand details, editable at any time.**
   - The details are: what you offer, who it's for, why people choose you, tone, the ask, website.
   - They are kept in the settings document under `outreach_brand_profiles`, so no migration.
   - "Edit details" (PATCH /v1/outreach/setup/brands/{id}) changes the name, sender identity or details.
   - Aria's drafts receive them, under better-written drafting instructions.
5. **Working with Aria on the emails.**
   - The owner writes notes; POST /v1/outreach/setup/campaigns/{id}/redraft returns three rewritten emails.
   - Nothing is saved: the new wording appears for the owner to edit, save and approve.
   - The cost is recorded.
6. **A plain DNS fix guide on a failed mailbox check.** It is built from the domain's real records:
   - who runs the DNS (from the nameservers: names.co.uk, GoDaddy, Cloudflare, IONOS and others);
   - the exact SPF value, added to the existing record and never replacing it;
   - the signature-key steps for Google Workspace or Microsoft 365, and DMARC.

   The owner chooses between:
   - I'll do it myself (Copy buttons);
   - Send this to my web person (a ready email);
   - Connect my domain now (only where the provider supports Domain Connect and `DOMAIN_CONNECT_ENABLED=1`);
   - Set it up for me (paid; it opens and escalates a support conversation).

   The page re-checks every 3 minutes while open; the daily check continues as before.

## Not yet

**Domain Connect's one-click flow.** Each provider must accept our template first, and names.co.uk doesn't support it. Detection is built; the flow follows once a provider approves.
