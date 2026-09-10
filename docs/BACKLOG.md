# Backlog — STUB

**Status: stub.** Nothing is duplicated here; this is an index. Items become
tickets only when they enter a release scope.

| Horizon | Source |
|---|---|
| **RC1 P0** — blocks safe launch | `docs/RC1_SCOPE.md` |
| **RC1 P1** — damages first customers | `docs/RC1_SCOPE.md` |
| **P2** — deferred | `docs/RC1_SCOPE.md` |
| **Out of RC1**, with reasons | `docs/RC1_SCOPE.md` |
| Known defects with file:line evidence | `audits/FINDINGS.md` |
| Security findings register | `audits/AUDIT-2026-07-04.md` |
| Post-launch module | `audits/COMPLIANCE-MODULE-BRIEF.md` |
| Deliberate out-of-scope decisions | the "Out of scope" section of each spec in `audits/` |

**Rule:** a backlog item without evidence — a file:line, a failing test, or
an audit reference — is not ready to become a ticket (`AGENTS.md` §6).

## Carried actions with no home yet

| Action | Source |
|---|---|
| Delete `MASTER_ADMIN_KEY` from the Railway environment and remove `verify_master_key` | `030B-SPEC.md` PART C; confirmed unused 8 Sep 2026 |
| Locate the 14-char `sk_` API key generator, or prove it unreachable | `030B-SPEC.md` scope note 4 — still open |
