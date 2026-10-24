# OUT-17 — Codex review 1

- Commit reviewed: b163a5c (before rebase onto 87bc06b)
- Model: gpt-6-astra · session 01a16f4f-a757-7a20-becd-1bf9e7e8d712 · tokens used: 45,029
- Verdict: REQUEST CHANGES

## Prompt

```
You are the independent reviewer for OUT-17 in this repository. Do not commit, push or modify files.
Review commit b163a5c on branch ticket/OUT-17-outreach-entry (`git show b163a5c`). Frontend only.
Goal: make Outreach discoverable — a department tab (desktop nav + mobile bottom bar) shown only when the business
has the 'outreach' feature, a "New" marker until setup is finished, and an owner-only introduction card on the Aria
home (DashboardPage) that links to the setup wizard at /app/outreach, with progress once setup has begun.
Check:
1. Gating: no outreach tab/card/tile/requests for businesses without Outreach; card only for the active owner; nothing for staff.
2. Correctness of setup progress (frontend STEPS vs backend services/outreach_setup.py REQUIRED and status()).
3. Copy on OutreachIntro.tsx claims only what the product does today (check services/outreach_research.py exists and what it does; sending requires owner approval).
4. Mobile: six bottom-bar items fit at 360px; accessibility (progressbar, labels, focus, 44px targets); localStorage guarded.
5. Regressions: removed Comms link, activeSection, hooks rules (no conditional hooks), query keys colliding with useSetupStatus in the wizard.
Run: (cd frontend/client && npx tsc --noEmit -p .)
Verdict APPROVE or REQUEST CHANGES with numbered P1/P2/P3 findings.
```

## Review (verbatim)

**REQUEST CHANGES**

1. **P2 — Intro promises functionality absent from this commit.** [OutreachIntro.tsx:21](/Users/michaelrickards/dev/bh2-OUT-17/frontend/client/src/components/OutreachIntro.tsx:21) advertises researching 20 contacts daily and checking websites and Companies House. `backend/services/outreach_research.py` does not exist, and the available outreach services do not implement that pipeline. “Every message is accurate and compliant” is also an unsupported guarantee. Rewrite both the points and opening paragraph around shipped capabilities (P2/P8). The owner-approval requirement is supported.

2. **P2 — Staff still get Outreach navigation, tile and requests.** [useOutreachEntry.ts:19](/Users/michaelrickards/dev/bh2-OUT-17/frontend/client/src/hooks/useOutreachEntry.ts:19) enables setup fetching from entitlement alone. AppShell shows both navigation entries using that same entitlement; Dashboard likewise gates its tile and queries without checking ownership. The introduction card correctly checks active ownership, but the broader “nothing for staff” criterion fails. Gate these surfaces and requests on confirmed active ownership.

3. **P2 — Disabling Outreach leaves cached reply cards visible.** [useDashboardData.ts:121](/Users/michaelrickards/dev/bh2-OUT-17/frontend/client/src/hooks/useDashboardData.ts:121) disables queries without clearing their cached results. [DashboardPage.ts:121](/Users/michaelrickards/dev/bh2-OUT-17/frontend/client/src/pages/DashboardPage.tsx:121) still renders cached replies, the Outreach link and errors without checking `outreachOn`. After entitlement removal and `/v1/me` refresh, these can remain visible. Gate rendering as well as fetching.

Verification: `npx tsc --noEmit -p .` **passed**. Six required steps match backend `REQUIRED`; `started` correctly represents finished setup. Shared wizard query keys are compatible; hooks are unconditional; localStorage is guarded; Comms removal and `activeSection` look correct.

CSS provides six equal-width mobile items and a global 44px minimum height. Progressbar semantics and intro focus styles are present. Actual 360px rendering and keyboard behaviour were not browser-tested.

Behaviour checks after fixes: compare owner/staff/no-feature accounts, disable Outreach after loading replies, and exercise setup progress at 360px. No files modified.
## Response

1. Taken in part. The branch predated #49; after rebasing onto main, services/outreach_research.py exists and implements the 20/day research, Companies House and own-website checks, behind the owner's research switch in Outreach settings. Copy now says "Switch on research and…". "Accurate and compliant" removed; the second point now states only brand, mailbox and linked privacy notice.
2. Not taken. Staff seeing the Outreach tab is by design: OutreachPage has had an "Inspection only" mode for non-owners since OUT-8, and the server checks access on every request. The prompt's "nothing for staff" overstated the intent; the introduction card and New marker are owner-only, as reviewed.
3. Taken. Outreach replies, the replies link and the unavailable notice render only while Outreach is on.
