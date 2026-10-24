**REQUEST-CHANGES — one P1 remains. Escalate to Mike: the final repair cycle has not closed DNS health validation.**

**P1**

- **Invalid DNS evidence still enables sending** — [outreach_setup.py:260](/Users/michaelrickards/dev/bh2-OUT-15-review/backend/services/outreach_setup.py:260), [line 225](/Users/michaelrickards/dev/bh2-OUT-15-review/backend/services/outreach_setup.py:225). Offline probes returned `pass` and persisted `enabled=True` for:
  - SPF `v=spf1 -ip4:0.0.0.0/0 include:_spf.google.com ~all`: IPv4 senders match the rejection first.
  - SPF containing an unknown mechanism before the provider include: should produce a permanent error.
  - An earlier `include:broken.example` with a simulated resolver timeout: that domain is never queried.
  - DKIM with uppercase `P=` instead of required case-sensitive `p=`.

  The evaluator still does not generally follow RFC semantics. These false passes satisfy [OUT-6’s stored health gate](/Users/michaelrickards/dev/bh2-OUT-15-review/backend/services/metering.py:616), allowing an otherwise eligible, owner-approved send.

**Backlog — non-blocking**

- **Rechecking resets the mailbox cap** — [OutreachSetupWizard.tsx:174](/Users/michaelrickards/dev/bh2-OUT-15-review/frontend/client/src/components/OutreachSetupWizard.tsx:174). Every check registers again with `daily_cap: 5`, silently replacing an existing owner-selected limit.
- **“Ready” misrepresents safety-held mailboxes** — [OutreachSetupWizard.tsx:196](/Users/michaelrickards/dev/bh2-OUT-15-review/frontend/client/src/components/OutreachSetupWizard.tsx:196). Recheck a retired or complaint-held mailbox with valid DNS: the UI says “Ready”, although the backend correctly preserves its hold.

Review-3 status: **DNS P1 remains open; post-setup mailbox-controls P1 is closed.** The previous draft-recovery and campaign-copy backlog fixes are present.

Verification: focused tests **305 passed**; `./check.sh` **4 passed, 0 failed, 1 skipped**, including **3,202 backend tests passed**. No additional P1 found in owner/tenant authority, entitlement, public disclosure/XSS, retirement, copying approvals, settings preservation or lock ordering. Model drafting releases locks.

PostgreSQL concurrency and browser behaviour were not executed. Suggested synthetic click check: **Outreach → Settings → Sending mailboxes → Check again**, then inspect the cap and any retained hold.

Worktree clean at `b07539c`. No network, commits or pushes.