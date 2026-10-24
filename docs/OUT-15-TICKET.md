# OUT-15 — Outreach setup: the admin switch and the owner's setup wizard

**Tier:** RED. It covers owner authority, the legal basis for contacting people, the public privacy notice and mailbox health; it creates no sends. **Builder:** Claude (Mike, 24 Oct 2026). **Reviewer:** Codex. **Tests first, approved by Mike before code.**
**Decisions:** Mike, 24 Oct 2026; see memory `outreach-completion-plan`. Wizard steps: brands, several mailboxes, audience, privacy notice, facts, limits, first campaign.

## Why
After OUT-7 and OUT-8, every outreach write says "Outreach setup required". Nothing creates a business's outreach settings, brands, operational mailbox rows or approved audience (the legitimate-interests assessment, "LIA"). Campaigns must target exactly the audience their LIA approved (`target_hash == audience_hash`), and OUT-8's draft campaigns currently hash an empty audience.

## Behaviour (what Mike will see)
**Admin.** The existing **Outreach** switch on the admin business page (`feature_flags.outreach`) is the toggle. A Business-tier plan includes outreach. For any other plan, the switch grants it. Turning it off stops new setup and new sends; it never deletes history. Tested end to end against the backend gate.

**Owner: Comms → Outreach → "Set up outreach"**, one step at a time. Progress is saved after each step, so the owner can leave and return:
1. **Brands.** One or more brands, e.g. "New Body Gym", "FitFutures", "MSC". Each has the sender identity shown in every footer ("Sent on behalf of …").
2. **Mailboxes.** "Connect another mailbox" (MAIL-1) without leaving the wizard. The owner ticks which connected mailboxes may send outreach and picks a brand's usual mailbox. Each ticked mailbox is **checked automatically** on its domain's DNS:
   - SPF includes the provider;
   - DKIM is published for the provider's selector;
   - DMARC exists.

   Results are shown in plain words ("Ready", or "Your domain needs a DMARC record: here's what to add"). Only a passing mailbox is enabled. A free webmail address (gmail.com, outlook.com, …) is refused for outreach, with the reason. Every new mailbox starts at the **warm-up of 5 a day**, then 10 and 20 (OUT-6 rules), and the wizard says so.
3. **Who you'll contact, and why.** The owner describes the audience in their own words and picks sectors and areas. **Aria drafts the legitimate-interests assessment** (purpose, necessity, balancing test, safeguards). The owner edits it and **approves** it. Approval fixes that audience and gives it a review date of 12 months by default, which the owner can change. A changed audience means a new version to approve.
4. **Privacy notice.** Aria drafts each brand's outreach privacy notice from the wizard answers (UK GDPR Article 14 headings: who we are, what data, source, purpose, lawful basis, retention, rights, how to opt out). The owner edits and approves it. Business Hero publishes it at a **public link**, `/p/outreach-privacy/{brand_id}`, which every outreach email includes. Only the approved version is ever shown, and nothing else about the business.
5. **Facts Aria may use** when answering replies: topic, answer, source and review date (OUT-7 knowledge). Optional; can be done later.
6. **Limits.** Business daily cap (1–20), copy me in (off by default), and the warm-up explanation.
7. **First campaign.** Name, brand, an **explicit** sending mailbox (several allowed across campaigns), and the approved audience. **Aria drafts the three emails** (first, then +5 and +7 working days). The owner edits them and taps **Approve these templates** (OUT-8).
8. **Finish: "Start outreach".** This unpauses outreach for the business. **Nothing is sent by finishing.** Every email is still a card the owner approves, until the later auto-approve ticket (OUT-11).

Every step is **owner-only** (the same `start()` rule as OUT-8: active owner, fresh entitlement read and membership recheck under lock) and tenant-scoped. Aria's drafts are suggestions saved as drafts. **Nothing Aria writes takes effect until the owner approves it.**

## Contract — `backend/services/outreach_setup.py`
- `status(session, business) -> {"steps": {name: "done"|"todo"|"blocked"}, "next": name|None, "complete": bool}`, where `name` is one of brand, mailboxes, audience, privacy, knowledge, limits, campaign.
- `begin(session, business, user) -> {"settings_id"}`: creates `outreach_settings` (paused, `retention_policy_version=1`), once.
- `save_brand(session, business, user, {"name", "sender_identity", "default_mailbox_id"?}) -> {"id", "version", "privacy_url"}`. `privacy_url` is `{PUBLIC_BASE_URL}/p/outreach-privacy/{id}`.
- `register_mailbox(session, business, user, {"mailbox_id", "daily_cap"}) -> {"mailbox_id", "enabled", "health"}`: creates or updates `outreach_mailboxes` (warm-up 5, enabled only once health passes).
- `check_mailbox_health(session, business, user, mailbox_id, *, resolve=dns_txt) -> {"status", "evidence", "advice"}`. `resolve(name) -> [txt strings]` can be injected; the default uses dnspython. Evidence: `{domain, provider, spf, dkim, dmarc, domain_control, from_aligned, selectors, checked_at}`, where each of spf/dkim/dmarc is pass or fail.
- `draft_audience(session, business, user, {"brand_id", "description", "segments", "regions"}, *, draft=model) -> compliance draft`. `audience_hash = sha256(canonical target_rules)`.
- `approve_audience(session, business, user, compliance_id, {"purpose", "necessity", "balancing_test", "safeguards", "review_due_at"?}) -> {"id", "audience_hash"}`.
- `draft_privacy_notice(...)` and `approve_privacy_notice(session, business, user, brand_id, {"text"}) -> {"version", "url"}`. Stored in `business_settings.settings["outreach_privacy"][brand_id] = {version, text, approved_by, approved_at}`; `preserve_automations` also keeps `outreach_privacy`. `public_privacy_notice(session, brand_id) -> text | None` is unauthenticated.
- `create_first_campaign(session, business, user, {"name", "brand_id", "mailbox_id", "compliance_id", "daily_cap"}, *, draft=model)`: the campaign's `target_rules` and `target_hash` come from the approved compliance record, and its three steps are drafted (unapproved).
- `finish(session, business, user)`: requires every non-optional step done; sets `pause_all = false`.
- Routes: `POST/GET /v1/outreach/setup/*`, owner-only. `GET /p/outreach-privacy/{brand_id}` is public and rate-limited, and returns text/html of the approved notice or 404.
- Frontend: `OutreachSetupWizard` under the Outreach page, shown until `complete`, then the OUT-8 dashboard.

## Decisions for Mike (each with a recommendation)
- **A. Legal-basis review period:** 12 months by default, editable. *Recommended.*
- **B. Free webmail mailboxes** (gmail.com etc.) **refused for outreach.** *Recommended:* deliverability, and they can't pass alignment.
- **C. Daily health recheck:** OUT-6 requires a same-day health pass before sending, so a weekday 07:00 UK job re-checks every enabled mailbox's DNS. If a check fails, the mailbox pauses with the reason shown. *Recommended.*
- **D. dnspython** added to both requirements files for the DNS lookups. *Recommended* over a third-party DNS-over-HTTPS service.

## Files
- New: `backend/services/outreach_setup.py`, `backend/outreach_setup_api.py`, `backend/tests/test_outreach_setup.py`, `frontend/client/src/components/OutreachSetupWizard.tsx`.
- Edited: `backend/main.py` (routes, the public privacy route, and `preserve_automations`), `backend/services/background_sync.py` or the scheduler (the daily health recheck), the OUT-8 `OutreachPage.tsx` (show the wizard until complete), `requirements.txt` and `backend/requirements.txt`.

No migration: the notice lives in `business_settings`.

## Not in this ticket
- Research and prospect finding (OUT-10).
- Sending adapters and the unsubscribe page (OUT-16).
- Auto-approve (OUT-11).
- Retention (OUT-13).
- Importing history.

## Tests
`backend/tests/test_outreach_setup.py`, strictly xfailed until `services.outreach_setup` exists. Synthetic data, no network: DNS and the model are injected.
