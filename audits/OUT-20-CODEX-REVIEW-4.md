# OUT-20 Codex review 4 (quick targeted)

Model gpt-6-astra · verdict **APPROVE**

## Prompt

```
Read-only QUICK TARGETED check (cycle limit reached) of OUT-20 in this worktree: only `git show HEAD` (fixes for audits/OUT-20-CODEX-REVIEW-3.md: Companies House key as a launch item; audience matched by hash so a newer draft never hides an older approval). Confirm both are fixed and tested, and that the expanding bindparam query is correct on PostgreSQL and SQLite. APPROVE or CHANGES REQUIRED with P1/P2. Brief. Do not edit, commit or push.
```

## Final message (verbatim)

**APPROVE** — `207a88d`, targeted review of `git show HEAD`. No P1/P2 findings.

- Missing Companies House key now blocks launch, with a regression test.
- Audience eligibility now matches by hash, preserving older approvals when a newer draft exists. Regression tests cover this and an older paused campaign.
- `IN :ids` with `bindparam("ids", expanding=True)` is correct for PostgreSQL and SQLite; values remain parameterized and empty lists bypass the query.

Tests inspected, not executed under this read-only scope. The ticket records 21 tests and mutation coverage.