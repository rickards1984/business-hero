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

## Mike's approval — 24 October 2026
**Approved:** the tests and decisions A–E, all as recommended.

## Build — 24 October 2026 (Claude)
- **Service:** `services/outreach_research.py`: plan, run, verification, quota, rotation, spend meter, enrolment, lessons, `run_due`, and the default adapters:
  - OpenAI Responses `web_search`;
  - `fetch_page`, which refuses private, loopback, link-local and non-web addresses and checks every redirect hop;
  - dnspython MX;
  - the Companies House REST API.
- **Scheduling:** `run_due` runs from the hourly `automations.run_all_due` pass.
- **Routes:** `GET/POST /v1/outreach/setup/research` and `POST …/research/lessons`.
- **Frontend:** `ResearchPanel` (the switch, budget against spend, lessons notes) in Outreach settings, and Aria's latest line on the Overview.
- **Fixes along the way:** the business load moved to `outreach_setup.load_business_row`, so the research module never reads `feature_flags` (it satisfies `test_entitlement_reads`' guard). The OUT-15 SQLite fixture gained `usage_meters`.
- **Verification:**
  - `test_outreach_research.py` has **33 passed**;
  - `./check.sh full` is green;
  - the Postgres run (setup, then research with faked adapters: 12 accepted, 1 sole trader kept for review, 5 enrolled, spend recorded per attempt) passes with the OUT-6/8 races and isolation suites (48).
- **Production settings:** `COMPANIES_HOUSE_API_KEY` is required; without it, research stops and nothing is made eligible. `ARIA_RESEARCH_MODEL` defaults to gpt-4.1. The price variables are optional.

## Codex review 1: REQUEST-CHANGES, seven P1s (repair cycle 1)
Preserved verbatim in `audits/OUT-10-CODEX-REVIEW-1.md`. Tests first for each:
1. **SSRF / DNS rebinding:** `fetch_page` resolves each hop once, refuses any non-public address, and connects to exactly that address (Host header and TLS name kept, so certificates are still verified). Bodies are streamed to a 2 MB limit. Live: gov.uk fetched over verified TLS; localhost and the metadata address refused.
2. **Corporate identity:** a model-supplied number is used only if Companies House's registered name matches the candidate company; otherwise the lookup is by name. The registered name must match, the type must be a corporate body (limited partnership removed), and **the company's own site must show its registered number or name** (Companies Act trading disclosures) on the cited page or home page. Anything uncertain is kept for review, never eligible.
3. **Email proof:** complete addresses are extracted and compared exactly. The source page, and its final URL after redirects, must be on the company's own domain.
4. **Spend:** each search reserves `MAX_SEARCH_PENCE` (60p) before it is sent, and the provider call is bounded (8,000 output tokens, 8 tool calls). The reservation is settled to the real cost; a failed search keeps it and is not retried.
5. **Quota across audiences:** each UK day's totals are read from the database (eligible contacts by type) and shared by every audience.
6. **Authority:** `_still_allowed` re-reads the business (active, entitled), setup finished, outreach not paused, research on, and a current, unexpired audience approval. It runs before any spend and again under lock before storing.
7. **Opt-out during verification:** storing happens under the shared business lock, re-checking suppression, holdings, quota and authority.

Backlog, also done:
- one company per batch;
- a role is verified only on a first-and-last-name match;
- rotation advances only after a run that found something new;
- the daily claim is made under lock;
- streamed size limit;
- **decision E's morning cards:** new enrolments get their first email as a waiting card, never sent.

Tests: research **53 passed**, setup **86 passed**; `./check.sh full` is green; the Postgres research run passes.

**Cost note for Mike:** a search is bounded at about 60p, and a day can use up to 3. The £20 default allows roughly 11–33 research days a month, depending on how quickly each day's target is met, so a higher monthly cap may suit daily use.

## Codex review 2: REQUEST-CHANGES, three P1s (repair cycle 2)
Preserved verbatim in `audits/OUT-10-CODEX-REVIEW-2.md`. DNS pinning, the shared quota and the locked suppression check were confirmed. Fixes, tests first:
1. **Identity:**
   - Companies House status must be exactly `active` (an empty status fails);
   - the site must show the **registered company number**, as a whole token, on the cited page or the home page. A short form such as "Company No. 1234567" counts only beside a registration word.

   Name-based disclosure is gone, because a name can be partly matched or borrowed and a number can't.
2. **Email proof:** `_address_on` requires the complete address. The character before it can't be any RFC 5322 atext character or a dot, and the domain mustn't continue after it.
3. **Spend:**
   - the OpenAI client has `max_retries=0`, so no silent second billable request;
   - web search uses `search_context_size: "low"`, plus the existing output and tool-call limits;
   - the reserve is now 100p per search;
   - the cap and the on/off switch are **re-read before every reservation**;
   - if a search ever costs more than its reserve, the full cost is kept and **research pauses** for the business until the owner switches it back on.

Backlog, also done:
- role verification needs the surname to match the officer's surname, and the first name to be among their forenames;
- `prepare_due_cards` gives follow-ups on existing enrolments their morning card, daily from `run_due`;
- the Aria tool `get_outreach_research` (status, spend, summary, lessons; outreach access checked; this business only).

Tests: research **82 passed**, setup **86 passed**; `./check.sh full` is green; Postgres passes. The installed OpenAI SDK (3.9.0) supports `max_tool_calls` and `search_context_size`.

## Codex review 3: REQUEST-CHANGES, three P1s (repair cycle 3 of 3, the last before escalating to Mike)
Preserved verbatim in `audits/OUT-10-CODEX-REVIEW-3.md`. Fixes, tests first:
1. **A proper legal disclosure binds the entity.** In the page's **visible text** (scripts, styles and markup removed, so image names don't count), the registered number must sit within a registration statement ("registered in England…", "company number…", "registered office"…), together with the **registered name**. A page describing a sole trader, "trading as", "t/a", self-employment or a partnership is always review.
2. **Quoted local parts:** a quote or backslash before the address disqualifies it (`"x@y"@z`).
3. **The reserve is a true maximum,** computed from limits the provider enforces: the model's whole context window (1,047,576 tokens) × the input price, plus the output cap × the output price, plus the tool-call cap × the search price. That's **189p** per search. Only the real cost is kept once a search settles.

Backlog, also done: surnames compare as a whole, so "Sam Jones" no longer matches "SMITH-JONES, Sam".

Tests: research **90 passed**, setup **86 passed**; `./check.sh full` is green; Postgres passes.

## Codex review 4: one P1 left; escalated to Mike after three cycles
Preserved verbatim in `audits/OUT-10-CODEX-REVIEW-4.md`. The P1 was a web designer's legal disclosure in a footer being accepted as the prospect's. **Mike's decision (24 Oct 2026): "Recommended":**
1. **Third-party credits never count.** A number beside "designed/built/hosted/powered/made… by", "site by", "web design:" and the like is the third party's disclosure, not the operator's.
2. **A company's own trading name is fine:** "Studio 1 Ltd trading as Fitness Club" is accepted. Any other "trading as" still means review. "Sole trader", self-employed and partnership are always review.
3. **Mike's added sanity check:** the email's domain must fit the registered name, or a trading name the site discloses (whole name, first two words, a distinctive word of five letters or more, or initials). A personal domain that fits neither is review, so even an unusually worded credit can't make someone eligible.

Tests: research **100 passed**, setup **86 passed**; `./check.sh full` is green; Postgres passes.

## Codex review 5: APPROVE, no P1
Preserved verbatim in `audits/OUT-10-CODEX-REVIEW-5.md`. Its three false rejections are fixed, with tests:
- a designer credit **after** the company's own disclosure no longer cancels it; only a credit leading up to the number does;
- trading names are recognised in any case, as "trading as" or "t/a", on the cited page or the home page;
- only the business describing itself as a partnership is review, not "in partnership with local schools".

Research tests: **106 passed**.
