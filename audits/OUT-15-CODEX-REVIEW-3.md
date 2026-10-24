**REQUEST-CHANGES — two P1s.**

**P1 — blocking**

1. **Invalid DNS evidence still enables sending.** [outreach_setup.py:234](/Users/michaelrickards/dev/bh2-OUT-15-review/backend/services/outreach_setup.py:234), also [line 223](/Users/michaelrickards/dev/bh2-OUT-15-review/backend/services/outreach_setup.py:223) and [line 248](/Users/michaelrickards/dev/bh2-OUT-15-review/backend/services/outreach_setup.py:248). Offline probes returned `pass` and persisted `enabled=True` for:
   - SPF `v=spf1 -include:_spf.google.com include:_spf.google.com ~all`: the first matching include rejects the provider.
   - DKIM with `k=invalid` and a genuine RSA key.
   - DMARC `v=DMARC1invalid; p=reject`.

   The exact review-2 examples are fixed, but its false-health-pass P1 remains open. These results satisfy OUT-6’s stored health gate.

2. **Completing setup removes the only mailbox registration/recheck controls.** [OutreachPage.tsx:35](/Users/michaelrickards/dev/bh2-OUT-15-review/frontend/client/src/pages/OutreachPage.tsx:35), [OutreachSetupWizard.tsx:173](/Users/michaelrickards/dev/bh2-OUT-15-review/frontend/client/src/components/OutreachSetupWizard.tsx:173), [outreach_setup.py:357](/Users/michaelrickards/dev/bh2-OUT-15-review/backend/services/outreach_setup.py:357). After completion, a transient DNS failure disables the mailbox. Subsequent daily checks exclude it, and the owner cannot reach **Check again**. Reproduced: repaired DNS next day yields zero checks, mailbox remains disabled, `started=True`. Likewise, a newly connected replacement cannot be registered and checked from Settings, so **Change mailbox** refuses it. Expose registration/rechecking after setup while preserving safety holds.

**Backlog — non-blocking**

- **Reload recovery misses edited drafts.** [OutreachSetupWizard.tsx:317](/Users/michaelrickards/dev/bh2-OUT-15-review/frontend/client/src/components/OutreachSetupWizard.tsx:317). Save wording changes, then reload: saving makes the campaign `paused`, but recovery selects only `draft`. Its wizard editor disappears; Campaigns remains a workaround.
- **Promised campaign-copy control is absent.** [OutreachSetupWizard.tsx:381](/Users/michaelrickards/dev/bh2-OUT-15-review/frontend/client/src/components/OutreachSetupWizard.tsx:381). After replacement preserves a campaign with dispatch history, the message directs the owner to copy it from Campaigns, but no frontend control invokes the copy endpoint.

Review-2 pause P1: **closed**—pausing preserves setup completion and operational routes. DNS P1: **not fully closed**, as above.

Verification passed:

- Focused pytest: **279 passed**.
- `./check.sh`: **4 passed, 0 failed, 1 skipped**; backend **3,176 passed, 304 skipped**.

No additional owner/tenant-write, stale-entitlement, public disclosure/XSS, retirement, copied-approval, settings-preservation or shared-lock-order defect found. Model drafting releases locks. PostgreSQL concurrency and browser interactions were not executed.

Worktree clean at `c363c98`; no commits, pushes or network calls made.