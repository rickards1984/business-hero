# OUT-20 — Codex review 1

- Commit reviewed: 7afc8d6
- Model: gpt-6-astra · session 01a174fe-e1af-7670-895f-88112c6ed2ab · tokens used: 62,839
- Verdict: REQUEST CHANGES

## Prompt

```
You are the independent reviewer for OUT-20 in this repository. Do not commit, push or modify files.
Read docs/OUT-20-TICKET.md. Review commit 7afc8d6 (`git show 7afc8d6`): backend/services/outreach_setup.py (brand profiles, update_brand, redraft_emails, the DNS guide in _evaluate/_guide/_dns_host/_helper_email), backend/outreach_setup_api.py, backend/tests/test_outreach_setup_help.py and frontend/client/src/components/OutreachSetupWizard.tsx.
Check: owner-only and tenant isolation on the new endpoints; redraft never saves and its AI cost is recorded through _ai_draft (and the provider check applies to it); the SPF value is always the existing record plus the provider include, never dropping existing mechanisms, and never produces two SPF records; the guide degrades safely with failing DNS lookups; settings-doc key outreach_brand_profiles is preserved by the generic settings save (preserve_automations keeps outreach_* keys — verify); the wizard: spinner labels, narrowed query invalidation (does any screen now go stale?), the auto re-check interval (cleanup, cap, no runaway requests), the paid set-up support request, copy buttons, hooks rules; and that no copy claims something untrue.
If pytest cannot run in your sandbox, read the tests and say so.
Verdict APPROVE or REQUEST CHANGES with numbered P1/P2/P3 findings.
```

## Review (verbatim)

**REQUEST CHANGES** — reviewed commit `7afc8d6`.

1. **P1 — DNS failures can instruct owners to add a second SPF record.** In [outreach_setup.py:497](/Users/michaelrickards/dev/bh2-OUT-19/backend/services/outreach_setup.py:497), lookup exceptions become empty results, then “Your domain has no SPF record yet” with an **Add** instruction. A timeout cannot establish absence. Confirmed with a synthetic timeout. Preserve an “unknown” lookup state and withhold replacement/add instructions until existing records are known.

2. **P2 — DNS-host detection never works through the production resolver.** [_dns_host:481](/Users/michaelrickards/dev/bh2-OUT-19/backend/services/outreach_setup.py:481) requests NS records, but `dns_other` handles only A/AAAA/MX/PTR and returns `[]` for NS. Tests inject nameservers directly, bypassing this defect. Implement NS conversion and test through `dns_other`.

3. **P2 — SPF include detection can return an unchanged, failing record.** [Line 506](/Users/michaelrickards/dev/bh2-OUT-19/backend/services/outreach_setup.py:506) uses substring matching: `include:_spf.google.com.evil.test` incorrectly counts as Google’s include. Qualified negative includes have the same problem. Parse complete mechanisms and qualifiers. Also, the helper email’s multiple-record branch omits the required provider include, unlike the onscreen instructions.

4. **P2 — The DMARC guide adds records when existing records need repair.** [Line 522](/Users/michaelrickards/dev/bh2-OUT-19/backend/services/outreach_setup.py:522) always recommends adding `p=none` for any failure. Two existing DMARC records therefore produce instructions to add a third; an invalid existing record similarly remains alongside the new one. Distinguish absent, invalid, duplicate and unknown states; preserve existing policy when suggesting repairs.

5. **P2 — Cache invalidation leaves visible state stale.** [useCall:92](/Users/michaelrickards/dev/bh2-OUT-19/frontend/client/src/components/OutreachSetupWizard.tsx:92) excludes `finish`, although it changes `outreach_settings.pause_all`; the mounted department settings query can continue showing “paused.” Separately, [automatic checks:434](/Users/michaelrickards/dev/bh2-OUT-19/frontend/client/src/components/OutreachSetupWizard.tsx:434) update only local results. A successful automatic check leaves wizard readiness and mailbox lists stale. Invalidate the affected queries for both paths.

6. **P2 — Redrafting can overwrite edits made while Aria is working.** [Line 861](/Users/michaelrickards/dev/bh2-OUT-19/frontend/client/src/components/OutreachSetupWizard.tsx:861) unconditionally replaces `edits` when the response arrives. Text fields and Save/Approve remain usable during rewriting, so intervening changes can be silently discarded. Disable conflicting controls or detect intervening edits before applying the response.

7. **P2 — “Connect my domain now” advertises an unavailable action.** [Line 543](/Users/michaelrickards/dev/bh2-OUT-19/frontend/client/src/components/OutreachSetupWizard.tsx:543) displays this option when the flag is enabled, but provides only explanatory text—no connection flow. The ticket explicitly says that flow is unimplemented. Keep it unavailable until functional, or label it as forthcoming.

8. **P3 — Paid-support requests lack pending and failure handling.** [Line 560](/Users/michaelrickards/dev/bh2-OUT-19/frontend/client/src/components/OutreachSetupWizard.tsx:560) leaves the button enabled during both requests, allowing repeated clicks to create duplicate conversations. Failures are then displayed in a green success alert and remove the retry button. Add pending state, disable duplicate submission, and render failures separately.

**Checks that passed inspection:** both new endpoints enforce active-owner authority and tenant-scoped record access. Redrafting saves no email wording, calls `_ai_draft`, records collected AI costs, and includes `model_redraft_emails` in the provider check. Generic settings saves preserve `outreach_brand_profiles` through the `outreach_*` protection and row lock.

Hooks are unconditional. Polling clears its interval and caps at 20 rounds, but does not cancel in-flight batches or prevent overlapping rounds. Copy buttons report success only after clipboard completion. Spinner coverage remains incomplete for template saves/approvals and the standalone mailbox screen.

**Verification:** targeted pytest produced **12 passed, 11 fixture errors** because the sandbox prohibits temporary database files. I read the blocked tests and confirmed findings 1–4 with read-only probes. No files modified, commits made, or pushes performed.
## Response

1. **P1 — taken.**
   - The guide uses its own lookup, which returns None on failure. A failed SPF or DMARC lookup gives an `unknown` item, with no value and no add or replace instruction.
   - Test: timeouts on both records.
2. **P2 — taken.** `dns_other` answers NS queries. Test: through `dns_other`, with dns.resolver faked, names.co.uk is detected.
3. **P2 — taken.**
   - `_spf_with` matches whole mechanisms (qualifier stripped) and never substrings.
   - A qualified include (-, ~, ?) is replaced with a passing one.
   - The helper email's merge line names the include.
   - Tests cover three records and the merge email.
4. **P2 — taken.**
   - DMARC is handled as absent (add), duplicate (merge, no value), invalid (edit to a repaired record keeping a valid policy and report address) or unknown.
   - Tests cover duplicates and three invalid records.
5. **P2 — taken.**
   - `finish` refreshes the outreach views.
   - An automatic check that passes refreshes setup status and the outreach lists.
   - Rounds never overlap, and a round stops when the page unmounts.
6. **P2 — taken.** While Aria rewrites, the email fields and the Save and Approve buttons are disabled, so no edit can be overwritten.
7. **P2 — taken.** "Connect my domain now" is removed from the screen until the Domain Connect flow exists. Detection stays in the guide data.
8. **P3 — taken.**
   - The request is pending while sending, and the button is disabled.
   - It escalates only if the chat didn't already escalate.
   - A failure shows in a red alert and keeps the button available.

**Spinners** were added for template saves and approvals and for the standalone mailbox screen.
