# OUT-27: fewer approval taps for outreach

**Tier:** RED: automatic customer contact, a standing permission, and a bulk approval. **Builder:** Claude. **Reviewer:** Codex. **Tests first.**

## Why (Mike, 14 Nov 2026)

At 20–50 outreach emails a day, approving each one by hand, each as a full-length card on the dashboard, would be unbearable. The dashboard "would be VERY long".

## What exists (OUT-11, origin/main)

- **A switch per campaign**: "Let Aria send this campaign's emails automatically". It's on the campaign page in Outreach.
- **When it unlocks:** after the owner has approved that campaign's first 5 emails by hand, and the provider has accepted them.
- **Once it's on**, Aria sends without asking:
  - one email at a time, at least 6 minutes apart plus a random 0–6 minutes;
  - within warm-up, the caps and weekdays 9–5 UK.
- **It switches itself off** when the wording or sender changes, outreach is paused, entitlement is lost, or the owner leaves.
- **What never changes:** answers to replies are never automatic, and the home page reports "Aria sent N emails on your behalf today".

**What's missing:**
- nothing prompts the owner to switch it on;
- there's no "approve all";
- each email is its own full-length dashboard card;
- a business with several brands and audiences has many switches.

## Decided by Mike (14 Nov 2026)

1. **When:** keep the 5-approvals rule. Once a brand's first 5 hand-approved emails are accepted, **Aria asks once on the dashboard**: "Shall I send the rest of [brand]'s emails without asking?". One tap turns it on, after the same confirmation OUT-11 shows. If the owner dismisses it, Aria **asks again when warm-up ends** (the brand's mailbox reaches its full daily stage), and not before.
2. **Scope: one switch per brand.** It covers all of the brand's campaigns. For a campaign that is new or reworded, the owner approves **its wording once** (the existing template approval, `outreach_manage.approve_templates`), not 5 more sends. Only then does Aria send that campaign automatically.
3. **While approvals are still needed, the dashboard shows one grouped card:** "Outreach: 23 emails ready". It has **Approve all** and a compact list (recipient, company, subject, campaign). Tapping a row opens the full email. Each row can also be approved or skipped on its own.

## Rules (each one tested)

- **G1. The brand grant is checked fresh at every send**, exactly as OUT-11's `valid_grant`:
  - the granting owner is still the active owner;
  - entitlement;
  - mailbox;
  - pause.

  Changing a campaign's wording invalidates **that campaign** until its wording is approved again. The other campaigns of the brand carry on.
- **G2. Trust:** the brand grant needs 5 owner-approved, provider-accepted sends **in that brand**. Automatic sends never count, as in OUT-11 `manual_accepted`.
- **G3. Existing per-campaign grants keep working** until revoked. The brand switch is added alongside them.
- **G4. Approve all is paced, never a burst.** Approved emails go out one at a time, at the autopilot spacing, within the caps and warm-up. Approve all is one owner action, recorded once with the list of emails it covered. A card that changed since the list was shown (version) is left for the owner.
- **G5. The prompt is shown once per trigger:** once at 5 approvals, and once at the end of warm-up. A dismissal is recorded. The prompt never appears for a brand already granted.
- **G6. Answers to replies are never automatic** and never included in Approve all. They stay as individual cards.
- **G7. Visibility:** the home page keeps "Aria sent N emails today" for each brand, and every automatic send records the grant behind it (as OUT-11).

## Out of scope

- Changing the warm-up schedule or the caps.
- Business-wide auto-send (Mike chose per brand).

## Acceptance

- [ ] With a brand at 5 accepted manual sends, the dashboard shows the offer once. Accepting it, after the confirmation, sends that brand's due emails automatically.
- [ ] A reworded campaign stops sending automatically until its wording is approved, and the brand's other campaigns carry on.
- [ ] 23 pending emails show as one card. Approve all sends them paced, not at once.
- [ ] Dismissing the offer, then reaching the end of warm-up, shows it again.
- [ ] G1–G7 have tests. Codex review preserved in `audits/`.
