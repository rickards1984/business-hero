# OUT-18 part B — Codex review 2

- Commit reviewed: a8a7487
- Model: gpt-6-astra · session 01a17018-f621-7181-a091-c2d03ad9618a · tokens used: 46,035
- Verdict: REQUEST CHANGES

## Prompt

```
You are the independent reviewer for OUT-18 part B, cycle 2. Do not commit, push or modify files.
Review 1 and the builder's response are in audits/OUT-18-B-CODEX-REVIEW-1.md. Review commit a8a7487 (`git show a8a7487`) with backend/services/outreach_setup.py and frontend/client/src/components/OutreachSetupWizard.tsx at HEAD.
Check findings 1–4 are resolved without new problems (campaign selection order; brand-keyed remounts; the ready summary reached in the normal flow and the revisit path; the other-inbox state and the copy action, which uses the existing POST /v1/outreach/setup/campaigns/{id}/copy). Judge whether deferring finding 5 (dashboard brand switcher) to OUT-14, now written in docs/OUT-18-TICKET.md, is acceptable.
Run (cd frontend/client && npx tsc --noEmit -p .); if pytest cannot run in the sandbox, read the tests and say so.
Verdict APPROVE or REQUEST CHANGES with numbered P1/P2/P3 findings.
```

## Review (verbatim)

**REQUEST CHANGES**

1. **P2 — The ready summary makes revisiting steps unreachable.** [OutreachSetupWizard.tsx:144](/Users/michaelrickards/dev/bh2-OUT-18/frontend/client/src/components/OutreachSetupWizard.tsx:144) replaces the stepper with `BrandReady`. Only the hidden step labels can set `revisiting=true`; the summary has no edit/setup action. Normal completion now reaches the summary, but owners cannot reopen the ready brand’s inbox, privacy notice or audiences. Add an explicit summary-to-steps action and verify returning via “Back to …’s summary”.

2. **P2 — Legacy mailbox fallback can still hide a valid ready campaign.** [outreach_setup.py:688](/Users/michaelrickards/dev/bh2-OUT-18/backend/services/outreach_setup.py:688) selects the first healthy, template-approved campaign without checking its latest audience approval. Reproduced using the actual `_brand_status()` in memory: an older campaign whose audience’s latest LIA is draft selects inbox A, making a fully approved campaign on healthy inbox B `other_inbox` and the brand not ready. Select fallback from campaigns satisfying the latest audience approval too, and add this regression test.

Brand-keyed audience/privacy/email remounts resolve finding 2. Explicit-mailbox campaign ordering and the other-inbox copy action look correct; copying uses the existing endpoint and requires fresh template approval.

Deferring the dashboard switcher to OUT-14 is acceptable under the now-explicit [ticket scope](/Users/michaelrickards/dev/bh2-OUT-18/docs/OUT-18-TICKET.md:56); it is deferred, not implemented.

Verification: TypeScript **passed**. Pytest was **blocked before collection** by unavailable writable temporary storage. Read the relevant regression tests and existing copy test. No files modified.
## Response

1. **Taken.**
   - The ready summary has "Review or change {brand}'s setup". It opens the steps (starting at the sending inbox) in revisit mode.
   - "Back to {brand}'s summary" returns to the summary.
2. **Taken.**
   - A legacy brand's inbox fallback now requires a sendable campaign whose audience's LATEST version is approved.
   - Test `test_a_legacy_brands_inbox_never_comes_from_an_audience_no_longer_approved` reproduces the reviewer's case. It fails on a8a7487.

**Finding 5 (the dashboard switcher):** accepted as deferred to OUT-14, as the reviewer confirmed.
