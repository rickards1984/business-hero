# OUT-10 — Aria-led prospect research: quality decision-makers, verified, learning over time

**Tier:** RED. It deals with personal data collection, the lawful basis for contact (PECR/UK GDPR), external research and spend; it creates no sends. **Builder:** Claude (Mike, 24 Oct 2026). **Reviewer:** Codex. **Tests first, approved by Mike before code.**
**Decisions:** Mike, 24 Oct 2026 (memory `outreach-completion-plan`):
- **20 new contacts per business per weekday, at least 10 named decision-makers.** Gatekeepers are allowed at highly relevant firms and are labelled as such.
- OpenAI web search plus Companies House.
- A monthly spend cap, starting at £20.
- A per-business learning memory.
- Aria leads, like Byron.

**Pattern:** Mike's local Byron system (`~/control-tower/engine/lib/research_orchestrator.py`, read as code only): plain, predictable code around one creative research step.

## Behaviour
1. **One business, one brief.** For each business with outreach started and research switched on, Aria builds a tight brief from the owner's **approved audience** (description, sectors, areas), the **area for today** from a rotation wheel that advances only after a successful run, and an **exclusion list** of companies and domains already held, contacted or opted out. A large list steers the model; the guarantee comes from the code checks below.
2. **Research** runs through OpenAI's web search. It asks for real organisations and **real emails found on the organisation's own website, never guessed**, with **named decision-makers first** (owner, director, founder, managing director, practice or operations manager, head of …). Role addresses (info@, hello@, reception@) are allowed only as labelled **gatekeepers**.
3. **Every candidate is verified by code, not trusted:**
   - the email must appear on the cited page when Business Hero fetches it;
   - the domain must have a mail server (MX);
   - it must not be free webmail;
   - it must not already be held, contacted or opted out (by email, and by company domain);
   - **Companies House:** an active company of a corporate type (Ltd, LLP, PLC, …) — see decision A;
   - a decision-maker is counted only when the contact has a name and a senior role, and is marked *role verified* when the name matches a Companies House officer.

   Anything failing is rejected with a reason, and nothing invented is stored.
4. **Quota:** decision-makers are accepted first, up to **20** a day. Then gatekeepers fill up to 20, **never more than 10** (so at least 10 are decision-makers whenever 20 are found). If a run finds fewer than the target, it **retries with a wider area**, up to 3 attempts, and success is judged on **genuinely new** verified contacts.
5. **Stored properly:** each accepted contact becomes an `outreach_prospect`:
   - corporate subscriber, legitimate interests, the approved audience's LIA;
   - fit score and confidence, and "why now";
   - privacy notice due within one month (UK GDPR Article 14);
   - retention date set.

   Each has an `outreach_evidence` row: the source page, the verified email, the Companies House record, and the expiry.
6. **Spend cap:** each run's model cost is recorded against the business's monthly research meter. When the cap (default £20) would be passed, research stops for the month and Aria says so.
7. **Learning memory ("training table"):** before each run, Aria reads the business's own outcomes: sent, replied, positive, bounced and meetings, by sector, area, role and decision-maker versus gatekeeper. The brief gets "**do more of** … / **avoid** …" lessons drawn only from those numbers. Aria also keeps short **lessons notes** per business; the owner can read and edit them in Outreach settings. Research improves as the business's own results build up.
8. **Aria reports, not spams:** after each run, one home or briefing line, e.g. *"I found 14 new contacts for MSC: 11 decision-makers, 3 gatekeepers. 9 were rejected (4 already contacted, 3 sole traders, 2 emails not on their site)."* Nothing is sent: new contacts wait to be enrolled (decision E).

## Contract — `backend/services/outreach_research.py`
- `plan(session, business, compliance_id, *, moment) -> {"area", "attempt", "exclusions", "lessons", "brief", "target": 20, "min_decision_makers": 10}`.
- `run(session, business, compliance_id, *, search, fetch, mx, companies, moment) -> {"accepted": [prospect ids], "decision_makers", "gatekeepers", "rejected": [{company, reason}], "attempts", "spend_pence", "stopped": reason|None}`. The callables are injected, defaulting to real adapters:
  - `search(brief) -> {"candidates": [...], "cost_pence"}`;
  - `fetch(url) -> page text | None`;
  - `mx(domain) -> bool`;
  - `companies(name_or_number) -> {"number", "name", "status", "type", "officers": [names]} | None`.
- `performance(session, business) -> [{"segment", "region", "contact_type", "sent", "replied", "positive", "bounced"}]`, computed from existing tables; no new storage.
- `lessons(session, business) -> [str]` and `save_lessons(session, business, user, [str])`, owner-only, stored in `business_settings.settings["outreach_research"]` alongside the rotation state, the switch, the daily target and the monthly cap. That key is already protected by OUT-15's `outreach_*` rule.
- The scheduler runs `run_due(session, moment)` from the hourly pass, on weekdays from 06:00 UK, once per business per UK day, and only while outreach is started and research is on.
- No migration: spend uses `usage_meters` (`outreach_research_pence`, monthly).

## Decisions for Mike (each with a recommendation)
- **A. Who may be contacted:** only **companies registered at Companies House** (Ltd, LLP, PLC and similar). Sole traders and ordinary partnerships are individuals under PECR and need prior consent. They're kept as "review", **never emailed**. *Recommended:* this is the legal line. It will exclude some small gyms and studios run as sole traders.
- **B. Proof of email:** the email must appear on the cited page when fetched. *Recommended.*
- **C. Spend:** a £20 monthly cap per business by default, editable in settings; research pauses when it's reached. *Recommended.*
- **D. Learning:** automatic, from the business's own results. Aria's lessons notes are visible and editable. *Recommended.*
- **E. After research:** new verified contacts are **automatically enrolled** into the active campaign for that audience, and next emails are prepared each morning, so cards appear on the home page. The pilot limit of 5 enrolments per campaign (OUT-8) **rises to match the daily capacity** once Mike's restart (OUT-9) has gone well. *Recommended:* keep 5 for the first week of the restart, then raise.

## Files
- New: `backend/services/outreach_research.py`, `backend/tests/test_outreach_research.py`, and adapters in the same module (OpenAI Responses web search, httpx page fetch, dnspython MX, Companies House REST with `COMPANIES_HOUSE_API_KEY`).
- Edited: `services/automations.py` (`run_due` from the hourly pass), the `outreach_read` and `assistant_tools` read of the research summary and lessons, and `OutreachPage` settings (switch, target, cap, lessons).

## Not in this ticket
- Auto-approve (OUT-11).
- Sending (OUT-16).
- Import (OUT-5 real run).
- Paid data providers.
- Phone or LinkedIn.

## Tests
`backend/tests/test_outreach_research.py`, strictly xfailed until `services.outreach_research` exists. Synthetic data only; every adapter is faked; no network and no model call.
