**REQUEST-CHANGES — two P1 findings.**

**P1 — blocking**

1. **Invalid DNS evidence still enables sending.** [outreach_setup.py:215](/Users/michaelrickards/dev/bh2-OUT-15-review/backend/services/outreach_setup.py:215), also lines 248 and 259. Offline probes each returned `pass` and persisted `enabled=True` for:
   - DKIM `p=` containing 64 `A` characters—invalid RSA key material.
   - SPF `v=spf1 -all include:_spf.google.com`—the rejecting mechanism precedes the include.
   - Two conflicting DMARC records.

   These results satisfy OUT-6’s stored health gate. Review 1 P1 #4 remains open: validate usable keys and record semantics before asserting a pass.

2. **Pausing outreach hides its operational and safety controls.** [outreach_setup.py:550](/Users/michaelrickards/dev/bh2-OUT-15-review/backend/services/outreach_setup.py:550), [OutreachPage.tsx:35](/Users/michaelrickards/dev/bh2-OUT-15-review/frontend/client/src/pages/OutreachPage.tsx:35). `started` means `not pause_all`. After setup finishes, clicking **Pause all outreach** makes it false; on status refresh, every outreach route renders the wizard. Replies, manual suppression and mailbox replacement become inaccessible while paused. Returning requires unpausing; a downgraded owner cannot do that. Reproduced the state transition offline. Setup completion must be independent of the safety pause.

**Backlog — non-blocking**

- **Campaign approval cannot resume after leaving setup.** [OutreachSetupWizard.tsx:311](/Users/michaelrickards/dev/bh2-OUT-15-review/frontend/client/src/components/OutreachSetupWizard.tsx:311). Reload after drafting: `created` is lost, so the saved campaign’s editor disappears. The owner must create another campaign to continue.
- **Setup settings links loop into the wizard.** [OutreachSetupWizard.tsx:287](/Users/michaelrickards/dev/bh2-OUT-15-review/frontend/client/src/components/OutreachSetupWizard.tsx:287), also line 301. “Add facts” and “Change limits” navigate to a route intercepted by the wizard, preventing those choices during setup.
- **Overlapping daily checks repeat work.** [outreach_setup.py:345](/Users/michaelrickards/dev/bh2-OUT-15-review/backend/services/outreach_setup.py:345). Two runs select the same unchecked mailbox; after acquiring the lock, neither rechecks `health_checked_at`. Both apply results. Reproduced with interleaved synthetic sessions.

Review 1: retirement race **closed**; safety-hold preservation **closed**; initial template approval/finish path **fixed**, with the pause regression above; invalid DNS evidence **not closed**. The three previous backlog fixes are present.

Both requested checks passed:

- Focused pytest: **274 passed**.
- `./check.sh`: **4 passed, 0 failed, 1 skipped**; backend **3,171 passed, 304 skipped**.

No additional owner/tenant-write, public disclosure/XSS, copied-approval, settings-preservation or shared-lock-order defect found. Model drafting releases locks. PostgreSQL concurrency and browser interaction were not executed.

Worktree clean. No commits, pushes or network calls made.