**REQUEST-CHANGES** — four P1 findings.

**P1 — blocking**

1. **Setup cannot finish through the UI.** [OutreachPage.tsx:35](/Users/michaelrickards/dev/bh2-OUT-15-review/frontend/client/src/pages/OutreachPage.tsx:35)  
   After drafting the first campaign, “Open campaigns” still renders the wizard. Completion requires approved templates, but their approval screen is inaccessible. Once templates are approved externally, `complete=true` removes the wizard before “Start outreach” can be clicked.

2. **Daily health can re-enable a retired mailbox.** [outreach_setup.py:302](/Users/michaelrickards/dev/bh2-OUT-15-review/backend/services/outreach_setup.py:302)  
   The scheduler reads mailbox state, performs DNS lookups, then writes using that stale snapshot without the shared business lock or a state recheck. If `replace_mailbox(..., retire_old=True)` commits during the lookup, the scheduler overwrites retirement with `enabled=True, pause_reason=None`. **Reproduced offline.** Reacquire locks and recheck current state before applying results.

3. **DNS checks clear complaint/bounce safety holds.** [outreach_setup.py:246](/Users/michaelrickards/dev/bh2-OUT-15-review/backend/services/outreach_setup.py:246)  
   Only reasons beginning with `Retired` survive a passing check. A mailbox paused by OUT-7 for a complaint or repeated hard bounces becomes enabled after an ordinary DNS recheck, despite no resolution of the reputation issue. **Reproduced with a complaint hold.** Preserve safety holds independently of DNS health.

4. **Invalid DKIM evidence enables sending.** [outreach_setup.py:225](/Users/michaelrickards/dev/bh2-OUT-15-review/backend/services/outreach_setup.py:225)  
   `v=DKIM1; p=`—an empty/revoked key—is accepted as passing DKIM. The service then asserts alignment and enables the mailbox, satisfying OUT-6’s stored health gate. **Reproduced offline.** SPF and DMARC likewise use loose string matching; validate usable records before recording a pass.

**Backlog — non-blocking**

- **Unscoped, stale picker caches:** [OutreachSetupWizard.tsx:206](/Users/michaelrickards/dev/bh2-OUT-15-review/frontend/client/src/components/OutreachSetupWizard.tsx:206), also line 305. Brand/compliance query keys omit business ID and escape setup invalidation. Revisiting after changes can show obsolete choices; switching business without clearing the cache can show previous-business choices. Backend tenant checks still reject foreign writes.
- **Public route lacks promised rate limiting:** [outreach_setup_api.py:163](/Users/michaelrickards/dev/bh2-OUT-15-review/backend/outreach_setup_api.py:163). Repeated anonymous requests reach database lookups without a configured route limit.
- **Interactive DNS runs under locks:** [outreach_setup.py:265](/Users/michaelrickards/dev/bh2-OUT-15-review/backend/services/outreach_setup.py:265). Slow DNS holds business/settings/mailbox locks across several five-second lookups, delaying pause and approval operations. Resolve outside locks, then revalidate before writing.

Both requested checks passed:

- Focused pytest: **262 passed**.
- `./check.sh`: **4 passed, 0 failed, 1 skipped**; backend **3,159 passed, 304 skipped**.

Three additional temporary regression probes exposed findings 2–4. PostgreSQL concurrency and browser interaction were not executed; SQLite probes do not establish PostgreSQL serialization.

No non-owner/cross-tenant backend write, public-notice XSS/disclosure, or copied approval was found in the reviewed paths. Model drafting releases mutation locks first.

Worktree restored clean. No commits, pushes, or network calls were made.