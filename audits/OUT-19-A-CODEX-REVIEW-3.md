# OUT-19 part A — Codex review 3

- Commit reviewed: 2aa4e30
- Model: gpt-6-astra · session 01a17261-fd11-73a2-910c-86ad7cde8417 · tokens used: 52,144
- Verdict: APPROVE

## Prompt

```
You are the independent reviewer for OUT-19 part A, cycle 3 (the final repair cycle; RED: AI spend). Do not commit, push or modify files.
Reviews 1 and 2 with responses are in audits/OUT-19-A-CODEX-REVIEW-1.md and -2.md. Review commit 2aa4e30 (`git show 2aa4e30`) with the files at HEAD.
Confirm review 2's five findings and its side notes are resolved without new problems: transaction-scoped alarms (rollback and repeated commits), unreported usage charged at the conservative maximum and marked estimated (drafts and research), UK-midnight brand boundaries, overflow in the price setting, the admin month switch, and the draft path's error handling when recording fails.
If pytest cannot run in your sandbox, read the tests and say so.
Verdict APPROVE or REQUEST CHANGES with numbered P1/P2/P3 findings.
```

## Review (verbatim)

**APPROVE** — `2aa4e30`, also HEAD. This review serves the North Star’s correctness and stability prerequisites. No new P1/P2/P3 findings.

Review 2’s five findings are resolved in the current paths:

1. Rolled-back alarms are discarded; repeated commits do not repeat alarms. An in-memory reproduction passed, including a fresh crossing after rollback on the same session.
2. Missing or incomplete usage receives the conservative maximum and an estimated marker for drafts and research.
3. Brand creation is compared against timezone-aware London midnight.
4. Overflowing price values reject the entire override.
5. Switching months clears the report, displays loading, names the returned period and includes the included brand’s incremental margin.

Draft recording failures now prevent successful drafts being returned; when drafting itself fails, that original error survives and the recording failure is logged. I found no new lock-order cycle.

**Remaining verification limits:** PostgreSQL tests now use two businesses and assert worker completion, but still lack deterministic overlap and mixed draft/research lock-path coverage. Default provider prices remain unverified.

**Checks:** 9 selected tests passed with capture/cache disabled. The initial pytest invocation failed because the sandbox has no writable temporary directory. I read both test files; the full suite, PostgreSQL tests and `check.sh full` were not run.

**Click check:** Admin → Outreach economics → switch between this month and last; confirm loading, returned period and included-brand margin.

No files modified, committed or pushed.