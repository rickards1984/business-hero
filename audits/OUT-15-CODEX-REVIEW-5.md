**REQUEST-CHANGES — one P1.**

**P1**

- **The pyspf adapter bypasses its empty-lookup limit** — [outreach_setup.py:268](/Users/michaelrickards/dev/bh2-OUT-15-review/backend/services/outreach_setup.py:268). Reproduced offline with:
  ```text
  v=spf1 exists:missing1.example exists:missing2.example exists:missing3.example include:_spf.google.com ~all
  ```
  With the three names returning no records and a valid Google include, native pyspf returns `permerror: Void lookup limit of 2 exceeded`. OUT-15 returns `pass` and persists `enabled=True`. Overriding `query.dns()` removes its void-lookup accounting. This false pass satisfies [OUT-6’s health gate](/Users/michaelrickards/dev/bh2-OUT-15-review/backend/services/metering.py:616), permitting an otherwise eligible, owner-approved send. Preserve pyspf’s DNS safeguards and add this regression case.

**Backlog — non-blocking**

- **An interactive DNS failure prevents automatic recovery** — [outreach_setup.py:369](/Users/michaelrickards/dev/bh2-OUT-15-review/backend/services/outreach_setup.py:369). “Check again” during an outage disables the mailbox without assigning the DNS pause reason. Daily checks then exclude it even after DNS recovers. Reproduced offline; another manual check remains a workaround.

Review-4’s cap-preservation and hold-display fixes are present and tested. TXT/A/MX/PTR adapter shapes work in offline probes; resolver exceptions fail closed, and DKIM tag names are case-sensitive. The chosen provider-IP checks remain preliminary evidence, with actual message authentication deferred to OUT-16.

No additional P1 found in owner/tenant authority, entitlement freshness, public disclosure/XSS, retirement, campaign replacement/copying, settings preservation or shared lock ordering. Model drafting releases locks.

Verification:

- Requested focused suite: **312 passed**.
- `./check.sh`: **4 passed, 0 failed, 1 skipped**; **3,209 backend tests passed**.
- PostgreSQL concurrency, browser behaviour and live DNS were not executed.

Suggested synthetic click check: **Outreach → Settings → Sending mailboxes → Check again**; confirm the cap stays unchanged and safety-held mailboxes show **On hold**.

Worktree restored clean. No network, commits or pushes.