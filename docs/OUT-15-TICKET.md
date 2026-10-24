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

## Mike's approval — 24 October 2026
- **Approved:** the tests and decisions A–D, as recommended.
- **Addition (Mike): change the sending mailbox quickly, at any time** (rebrand, name change, lost reputation, or any other reason). Claude's design, recorded here:
  - `replace_mailbox(session, business, user, {"old_mailbox_id", "new_mailbox_id", "reason", "retire_old": bool}) -> {"switched", "kept_on_old", "paused_enrolments", "dismissed_cards"}`.
  - The new mailbox must be registered and passing its health check; otherwise nothing changes.
  - Brands whose usual mailbox is the old one move to the new one.
  - **Campaigns with no dispatch history move** (status kept; version up).
  - **Waiting send cards bound to the old mailbox are dismissed**, to be prepared again from the new one.
  - Campaigns with dispatch history stay on the old mailbox: follow-ups must keep their thread (OUT-6).
  - With `retire_old`, the old mailbox is disabled with the reason shown, and its in-flight enrolments are paused (`stop_reason` "sending mailbox retired") and listed for the owner.
  - The old inbox stays **connected**, so replies are still read.
  - `copy_campaign_to_mailbox(session, business, user, campaign_id, {"mailbox_id", "name"?}) -> {"id"}` creates a new draft campaign with the same brand, audience and wording on the new mailbox. Its steps are unapproved, so one tap re-approves them.
  - Owner-only, tenant-scoped, one transaction under the business lock.

## Build — 24 October 2026 (Claude)
- **Service:** `services/outreach_setup.py`, implementing every step plus `replace_mailbox`, `copy_campaign_to_mailbox`, `recheck_health` and `daily_health`.
- **Routes:** `outreach_setup_api.py`, under `/v1/outreach/setup/*`, plus the public `/p/outreach-privacy/{brand_id}`.
- **Settings protection:** `preserve_automations` keeps every `outreach_*` settings key.
- **Daily check:** decision C runs from the hourly `automations.run_all_due` pass (weekdays from 07:00 UK, mailboxes not yet checked that UK day). `briefing_scheduler.py` (CRLF) is untouched.
- **DNS:** `dnspython>=2.6` added to both requirements files.
- **Frontend:** `OutreachSetupWizard.tsx` (stepper; Aria drafts then the owner approves; mailbox checks show plain advice; "Start outreach"). `ChangeSendingMailbox` sits in Outreach settings. `OutreachPage` shows the wizard to the owner until setup is complete.
- **Verification:**
  - `test_outreach_setup.py` has **34 passed**;
  - `./check.sh full` is green, with tsc;
  - the Postgres `test_outreach_setup_rls.py` runs the whole wizard plus a mailbox change, and passes alongside the OUT-6/8 races and the isolation suite.
- **Production settings needed before use:** `PUBLIC_BASE_URL` (the backend's public HTTPS address, for privacy links) and `OPENAI_API_KEY` (already set). `ARIA_DRAFT_MODEL` is optional and defaults to gpt-4o.

## Codex review 1: REQUEST-CHANGES, four P1s (repair cycle 1)
Preserved verbatim in `audits/OUT-15-CODEX-REVIEW-1.md`. Tests first for each:
1. **Setup couldn't be finished in the app.** The wizard now stays until outreach is **started** (`status.started`), not merely complete. The campaign step shows the three drafted emails to edit, save and "Approve these templates" in place.
2. **The daily check could overwrite a retirement made during its lookups.** DNS now runs with no lock held. Each result is applied only to the mailbox row re-read under the business lock, and only if it's still enabled.
3. **A DNS pass lifted complaint, bounce and retirement holds.** A pass now lifts only a pause the DNS check itself caused (`Daily check failed:`). Every other hold stays.
4. **Unusable records passed.** DKIM needs a real base64 `p=` of usable length (an empty `p=`, meaning a revoked key, fails). SPF needs exactly one record, naming the provider as a whole mechanism. DMARC needs a `p=` of none, quarantine or reject.

From the backlog, also done:
- the wizard's cached lists are keyed by business;
- the public privacy page is limited to 60 requests a minute;
- interactive checks run DNS outside locks and re-read before writing.

Tests: setup **46 passed**; `./check.sh full` is green; the Postgres wizard passes.

## Codex review 2: REQUEST-CHANGES, two P1s (repair cycle 2)
Preserved verbatim in `audits/OUT-15-CODEX-REVIEW-2.md`.
1. **Records are now read for meaning, not just shape:**
   - DKIM `p=` must decode, using `cryptography`, to a real RSA key of at least 1024 bits, or a 32-byte Ed25519 key;
   - SPF terms are read in order, so the provider's pass-qualified include must come before any `all`;
   - there must be exactly one DMARC record, with a valid policy.

   Tests use a genuinely generated 2048-bit RSA key as the good record.
2. **Setup finished is its own fact** (`outreach_setup.finished_at`, written by `finish`). Pausing outreach never brings the wizard back.

From the backlog, also done:
- the wizard intercepts only the main Outreach page, so its settings links work;
- a drafted, unapproved campaign is picked up again after a reload;
- overlapping daily checks skip a mailbox already checked that day once they hold the lock.

Tests: setup **51 passed**; `./check.sh full` is green; the Postgres wizard passes.

## Codex review 3: REQUEST-CHANGES, two P1s (repair cycle 3 of 3, the last before escalating to Mike)
Preserved verbatim in `audits/OUT-15-CODEX-REVIEW-3.md`. The pause P1 is closed.
1. **DNS records are evaluated by their RFC rules, not checked against examples:**
   - **SPF** (RFC 7208): read left to right. The first `include` of the provider decides, and passes only with a + or no qualifier; an `all` before it fails; so does `redirect` without it.
   - **DKIM** (RFC 6376): `v`, if present, is first and exactly `DKIM1`; `k` is rsa or ed25519; testing mode (`t=y`) fails; `s` must allow email; no duplicate tags; `p` decodes to a real key.
   - **DMARC** (RFC 7489): the first tag is exactly `v=DMARC1`, and there must be a valid `p`.

   23 parametrised cases cover pass and fail on each.
2. **Mailbox checks after setup:**
   - a DNS-paused mailbox stays in the daily check, so repaired records re-enable it (safety holds still never lift);
   - Outreach settings has a **Sending mailboxes** panel (register, check, check again) at any time, so a replacement can be prepared and **Change sending mailbox** can use it.

From the backlog, also done:
- edited (paused) drafts are picked up after a reload;
- **Copy to another mailbox** is on each campaign.

Tests: setup **77 passed**; `./check.sh full` is green; the Postgres wizard passes.

## Codex review 4: one P1 left; escalated to Mike after three cycles
Preserved verbatim in `audits/OUT-15-CODEX-REVIEW-4.md`. **Mike's decision (24 Oct 2026): "Recommended — let's be sure everything works as well as it possibly could."** Stop hand-writing SPF:
- **SPF:** evaluated by **pyspf** (the established RFC 7208 implementation). The question asked is the real one: does this domain's SPF authorise a real provider sending address (Google 209.85.220.41; Microsoft 40.107.22.50)? Includes are followed, unknown mechanisms are permanent errors, a failed lookup is a temporary error, and only `pass` passes. Production TXT lookups raise on timeouts, so an outage is never "no record".
- **DKIM:** tag names are case-sensitive (RFC 6376 §3.2).
- **Real-DNS check** (Claude, live): google.com authorises 209.85.220.41 (True) and refuses TEST-NET 192.0.2.10 (False); its DMARC is usable.
- **Backlog fixes:** a recheck without a cap keeps the owner's daily limit; a held mailbox with valid records reports **On hold** with its reason, never "Ready".
- **Still to come in OUT-16, also agreed by Mike:** the definitive check. Each mailbox sends a test email to the owner, and Business Hero reads the receiving server's `Authentication-Results`.
- **Tests:** setup **84 passed**; `./check.sh full` is green; the Postgres wizard passes. `pyspf>=2.0.14` is in both requirements files.
