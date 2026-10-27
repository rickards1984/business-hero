Reviewed `905f288`, PR #61, strictly for D/E × OUT-11 integration under **North Star P8**. No files modified, committed or pushed.

- **P1:** None found.
- **P2:** None found.
- **Backlog:** Persist the seven integration probes run during this review. Add PostgreSQL concurrency coverage for research enrolment/card preparation racing autopilot claims; in-memory SQLite cannot verify those locks.

Verified:

1. Automatic sends remain cold initial/follow-up emails, never replies. Campaign, brand-daily, monthly, mailbox warm-up and combined reply-ceiling limits hold. Pacing tests pass.
2. Research commits contacts and audience-matched enrolments together. `_prepare_cards` skips valid auto-approved campaigns, leaving enrolments available to autopilot. Claim checks retain duplicate-send protection.
3. Capacity counts today’s reserved/unknown cold sends once, without also counting their enrolments as waiting. Other waiting enrolments consume capacity; replies remain excluded.
4. Both `AutopilotSwitch` and `ReplyCeilingBanner` imports/usages survive the merge. D’s clock helpers cover runtime qualification while preserving explicit research-clock advances.

**Verification:** 258 focused tests plus seven additional autopilot integration probes passed using in-memory databases. TypeScript checking passed. `check.sh` was not run because it writes files; browser and PostgreSQL concurrency behaviour remain unverified.

**Verdict: APPROVE.**