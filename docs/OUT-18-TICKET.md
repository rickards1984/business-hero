# OUT-18 — Outreach per brand, product or service

**Tier:** RED for part A (research spend caps and personal-data collection limits); part B is YELLOW (wizard and screens).
**Decided by Mike, 24 Oct 2026.**

## The model

A business does outreach for one or more **brands** (a brand, product or service). Each brand has:
- its own sending mailbox;
- its own audiences (organisation types), each with its own legal-basis approval;
- one email sequence per audience;
- its own privacy notice.

This structure is already in the database (037): `outreach_brands`, `outreach_compliance.brand_id`, and `outreach_campaigns` (brand, mailbox and audience). Research already enrols each contact into the campaign for its brand and audience. Part A makes research's limits per brand; part B makes the wizard and the screens per brand.

Examples:
- **New Body**
  - FitFutures (UKFI), from partners-ukfi@: gyms, health centres and facilities with a gym.
  - New Body gym, from outreach@: schools (PE provision), charities, youth organisations and so on.
- **MSC**
  - One brand, from ops@: landlords and managing agents (property maintenance); fabrication buyers (welding).

## Part A — research per brand (RED)

1. **Daily target per brand.** 20 new contacts a UK day for each brand, of which at most 10 are gatekeepers (so at least 10 are decision-makers). The target is shared across that brand's audiences, not across brands.
2. **Spend cap per brand.**
   - Each brand has its own monthly research budget: £20 by default.
   - The owner may raise it. It can never be set below £20 (minimum) or above £1,000.
   - Spend is metered per brand: `usage_meters.meter = 'outreach_research_pence:<brand_id>'`. No migration is needed; `meter` is free text (033).
   - Reserve-before-search, settle-after and keep-on-failure all apply per brand.
3. **On/off per brand.** Research runs for a brand only while that brand is switched on. A search that costs more than its reserve pauses that brand only.
4. **Lessons per brand.**
   - The brief names the brand.
   - The lessons drawn from results count only that brand's contacts.
   - The owner's notes are kept per brand.
5. **Unchanged, business-wide:**
   - suppression and opt-outs;
   - the held-domain exclusions (one active sequence per organisation);
   - authority checks;
   - the once-a-day claim;
   - the business lock.
6. **Legacy, fail closed.** Spend recorded on the old business-wide meter in the current month counts against every brand's budget for that month. A business-level `enabled` / `monthly_cap_pence` from before OUT-18 becomes the starting value for brands without their own settings, never below £20.

## Part B — wizard and screens (YELLOW)

The six agreed steps:
1. **Brands:** a box per brand, "+ Add another".
2. **Mailboxes:** a sending inbox chosen per brand.
3. **Audiences per brand:** each audience's legal basis, drafted by Aria.
4. **A privacy notice per brand.**
5. **Limits.**
6. **A sequence per audience:** Aria drafts, the owner edits and approves.

Setup is finished when one brand is ready. The message then reads: "to set up another business, service or product, repeat the process." After outreach starts, the Outreach overview lists each brand, with "+ Set up another" and "Continue setup".

**Not in OUT-18:** the dashboard brand switcher (All · each brand, each with its own pipeline, replies and results). It is built with the OUT-14 dashboard, from the approved design, on top of the per-brand status this ticket adds.
