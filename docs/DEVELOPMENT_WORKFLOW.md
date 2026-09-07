# Development workflow — STUB

**Status: stub. The real content is `AGENTS.md` §§6–8** — task packet,
multi-agent workflow, contested-resource rules and escalation triggers. It
lives there because every agent reads that file first.

Quick reference:

```
ticket approved → builder implements on its own branch
  → ./check.sh full, output pasted into the ticket
  → a DIFFERENT agent reviews the diff
  → defects return to the same ticket
  → CI green → Definition of Done passes → merge
  → post-merge smoke check
```

- Ticket format: `AGENTS.md` §6
- Merge gate: `docs/DEFINITION_OF_DONE.md`
- Branch naming: `ticket/BH-000-short-name`; foundation work on
  `foundation/*`
- **Mike pushes to `main`.** Push and deploy are RED tier
- One migration in flight at a time. Only one ticket may touch
  `backend/main.py`

**Not yet decided** — flagged for Mike in the first-output questions: whether
Codex works in this same clone via git worktrees or a separate checkout, and
whether review happens on GitHub PRs or in-repo.
