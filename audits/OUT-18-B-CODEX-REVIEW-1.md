# OUT-18 part B — Codex review 1

- Commits reviewed: 518adec, 07435c0
- Model: gpt-6-astra · session 01a17013-e6ae-7873-b945-921bfbc6a4ee · tokens used: 50,430
- Verdict: REQUEST CHANGES

## Prompt

```
You are the independent reviewer for OUT-18 part B in this repository (setup per brand, product or service). Do not commit, push or modify files.
Read docs/OUT-18-TICKET.md (part B) first. Review commits 518adec (backend setup status per brand) and 07435c0 (frontend wizard) on branch ticket/OUT-18-multi-brand.
Check:
1. backend/services/outreach_setup.py status(): per-brand readiness is correct (own mailbox healthy, own privacy notice, an approved audience whose campaign has three approved steps and sends from that brand's healthy mailbox; another brand's ready campaign never counts). complete = any brand ready; finish() still refuses until then. Pre-OUT-18 brands with no default_mailbox_id fall back to their campaign's mailbox. Nothing exposes data from another business. Latest LIA version per audience. Performance is acceptable (queries per campaign).
2. Frontend components/OutreachSetupWizard.tsx and pages/OutreachPage.tsx: the six steps operate on the selected brand; "+ Add another" saves several brands; choosing a brand's inbox; several audiences per brand; one email sequence per audience drafted from the brand's inbox; the ready message and "+ Set up another"; the post-start brands panel. Look for state bugs (brand selection after save, stale status), hooks rules, and copy that claims anything untrue (sending is capped at 20 a day per business today — business_daily_cap — so check nothing promises 20 SENDS per brand).
3. Tests: backend/tests/test_outreach_setup_brands.py proves the status rules; existing setup tests still hold.
Run: .venv/bin/python -m pytest backend/tests/test_outreach_setup_brands.py backend/tests/test_outreach_setup.py -q and (cd frontend/client && npx tsc --noEmit -p .) — if the sandbox blocks them, read carefully and say so.
Verdict APPROVE or REQUEST CHANGES with numbered P1/P2/P3 findings.
```

## Review (verbatim)

**REQUEST CHANGES**

1. **P2 — A valid campaign can be ignored, blocking readiness.** [outreach_setup.py:691](/Users/michaelrickards/dev/bh2-OUT-18/backend/services/outreach_setup.py:691) selects the first campaign with approved steps before checking its mailbox. An older approved campaign on an unhealthy/wrong mailbox hides a newer approved campaign on the brand’s healthy mailbox. Legacy fallback likewise chooses the first campaign’s mailbox. Reproduced both cases using the actual `_brand_status()` function in memory. Select a campaign satisfying all readiness conditions; add regression tests.

2. **P2 — Brand switching can retain another brand’s draft.** [OutreachSetupWizard.tsx:159](/Users/michaelrickards/dev/bh2-OUT-18/frontend/client/src/components/OutreachSetupWizard.tsx:159) renders stateful audience/privacy components without brand keys. Switching between brands needing the same step preserves local state: an audience approval can target the previous brand’s draft ID; a privacy approval can publish the previous brand’s wording under the newly selected brand. Reset/remount forms on brand changes and guard pending responses.

3. **P2 — Normal completion never displays the ready message or “+ Set up another”.** [OutreachSetupWizard.tsx:141](/Users/michaelrickards/dev/bh2-OUT-18/frontend/client/src/components/OutreachSetupWizard.tsx:141) requires `!active`, but saving a brand sets `active='mailboxes'`, and subsequent step clicks keep it non-null. Template approval refreshes status without clearing it. For a single brand, there is no selector to reset this state. Transition explicitly to the ready view after completion.

4. **P2 — Changing the chosen inbox strands an existing sequence.** [OutreachSetupWizard.tsx:460](/Users/michaelrickards/dev/bh2-OUT-18/frontend/client/src/components/OutreachSetupWizard.tsx:460) only offers drafting when no campaign exists. Changing the brand inbox updates the brand but leaves its campaign on the old inbox. The wizard then shows “Waiting for your approval” even for approved templates, with no way there to move/recreate the sequence. Provide a supported mailbox-change path and distinguish mailbox mismatch from missing approval.

5. **P2 — The agreed dashboard brand switcher is missing.** [OutreachPage.tsx:60](/Users/michaelrickards/dev/bh2-OUT-18/frontend/client/src/pages/OutreachPage.tsx:60) adds a brand list and setup controls, but no **All · each brand** dashboard filter required by part B.

Verification: TypeScript **passed**. Requested pytest command was **blocked before collection** by unavailable writable temporary storage; fixtures also require temporary SQLite files. No files were modified.

Static review found tenant-scoped status queries, latest-version LIA selection, `complete = any brand ready`, and `finish()` enforcing that result. No hooks-order violation or promise of 20 sends per brand found. Status performs one additional query per campaign—linear database round trips, without performance coverage. The new tests cover basic readiness but miss the campaign-selection failures above, latest-LIA replacement, and populated cross-business status isolation.
## Response

1. **Taken.**
   - Each audience shows, in order: a campaign that is ready (approved, healthy inbox, the brand's inbox); else the newest on the brand's inbox; else the newest overall.
   - A legacy brand's inbox comes from a sendable campaign, else the newest.
   - Test `test_an_older_campaign_on_a_failing_inbox_never_hides_a_ready_one` fails on 07435c0.
2. **Taken.** The audience, privacy, emails and inbox components are keyed by brand, so switching brands remounts them and no draft or wording carries over. A response arriving after a switch lands on an unmounted component.
3. **Taken.**
   - A ready brand shows its summary ("… is ready", "+ Set up another", "Start outreach") unless the owner opens one of its steps.
   - Saving and stepping through no longer suppress it.
   - "Back to {brand}'s summary" returns to it.
4. **Taken.**
   - Status marks a campaign that is `approved` but on `other_inbox`.
   - The wizard says so ("On another inbox") and offers "Copy the emails to {brand}'s inbox", using the existing copy-campaign endpoint (same wording, approved once more).
   - Test `test_after_changing_a_brands_inbox_its_old_emails_show_as_on_another_inbox` fails on 07435c0.
5. **Not taken, and the ticket is clarified.** The dashboard brand switcher is built with the OUT-14 dashboard (approved design), on top of the per-brand status added here. docs/OUT-18-TICKET.md now says so explicitly; the earlier wording ("as OUT-14") was ambiguous.

**Coverage gaps — taken.** Added tests for latest-LIA replacement and for cross-business isolation in status. Both already passed on 07435c0: they add coverage, not changed behaviour.
