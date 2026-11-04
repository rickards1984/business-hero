# OUT-20 Codex review 1

Model gpt-6-astra · verdict **CHANGES REQUIRED** (7 × P2)

## Prompt

```
Read-only review of the uncommitted diff in this worktree (`git diff` plus untracked backend/services/outreach_launch.py, backend/tests/test_outreach_launch.py, docs/OUT-20-TICKET.md). OUT-20: a per-brand Launch checklist for outreach; Launch switches research on only when every approval exists; Pause switches it off. Check: the checklist matches the real conditions under which outreach_research.run_due actually researches and research._take_place enrols (would a brand show "Running" yet still find nothing, or vice versa?); owner-only and entitlement paths (setup._authority, research.configure's own authority with growth=True); no approval is ever skipped; the frontend LaunchPanel (OutreachSetupWizard.tsx, OutreachPage.tsx) shows errors and refreshes correctly; tests prove it. APPROVE or CHANGES REQUIRED with P1/P2 (file:line, concrete failure). Do not edit, commit or push.
```

## Final message (verbatim)

**CHANGES REQUIRED**

- **P2 — Expired audience approvals still permit Launch.** [outreach_launch.py:24](/Users/michaelrickards/dev/bh2-OUT-20/backend/services/outreach_launch.py:24) trusts setup’s `approved` flag, which checks only `decision`. An expired approval therefore passes Launch and shows “Running”, while `research._audience()` and enrolment’s `qualified()` reject it. Check the reviewer and approval dates using the runtime rules.

- **P2 — A stopped campaign can show “Running”.** [outreach_launch.py:25](/Users/michaelrickards/dev/bh2-OUT-20/backend/services/outreach_launch.py:25) trusts setup’s campaign `ready`, which checks approved templates and mailbox health but ignores campaign status. A paused/completed campaign with approved templates passes; `research.capacity()` accepts only `ready`/`running` campaigns, so research finds no available campaign and performs no search.

- **P2 — Payment and allowance blocks are invisible.** [outreach_launch.py:63](/Users/michaelrickards/dev/bh2-OUT-20/backend/services/outreach_launch.py:63) calculates readiness without `brand_live()`, research allowance or remaining research budget. An unpaid additional brand or exhausted brand can launch and display “Running” indefinitely while `_run()` refuses every search. Surface these blocking states separately from the enabled switch.

- **P2 — Pause incorrectly requires growth entitlement.** [outreach_launch.py:96](/Users/michaelrickards/dev/bh2-OUT-20/backend/services/outreach_launch.py:96) calls `_authority()` with its default `growth=True`. An owner with retained access after subscription expiry gets 403 before reaching `research.configure(enabled=False)`, which deliberately uses `growth=False`. Pause should preserve that existing authority path.

- **P2 — Pause disappears while research remains enabled.** [OutreachSetupWizard.tsx:1046](/Users/michaelrickards/dev/bh2-OUT-20/frontend/client/src/components/OutreachSetupWizard.tsx:1046) selects the Pause button using `launched`, rather than `research_enabled`. If a checklist prerequisite fails, the panel replaces Pause with a disabled Launch button without switching research off. The owner cannot disable the brand here, and research can resume when the prerequisite is restored. Keep Pause available whenever research is enabled.

- **P2 — Checklist fetch failures are silently hidden.** [OutreachSetupWizard.tsx:1014](/Users/michaelrickards/dev/bh2-OUT-20/frontend/client/src/components/OutreachSetupWizard.tsx:1014) returns `null` on an initial GET failure; `q.error` is never rendered, and retries are disabled. Mutation errors are displayed, but a failed checklist request removes the entire feature without explanation or retry.

- **P2 — Other controls leave the checklist stale.** [OutreachSetupWizard.tsx:1017](/Users/michaelrickards/dev/bh2-OUT-20/frontend/client/src/components/OutreachSetupWizard.tsx:1017) invalidates the launch query only after its own successful actions. “Pause all outreach” on the same Overview does not invalidate it, so the panel continues showing “Running”. `staleTime` does not schedule a refresh. Invalidate this query when relevant settings, approvals or research controls change.

Owner checks and Launch’s second authority check through `research.configure(growth=True)` remain intact. I found no new bypass of downstream send approvals.

The eight tests do not exercise scheduler/enrolment parity, expired approvals, retained-access Pause, billing blocks or frontend errors/refresh. The missing-template test also leaves setup unfinished, so it does not independently prove the template gate.

Test execution was blocked by the read-only environment’s lack of a writable temporary directory. No files were edited; nothing was committed or pushed.Session: session id: 01a1a758-83ec-7af2-b179-e715f69c658f
