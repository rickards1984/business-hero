# OUT-18 part C (monthly allowance) — Codex review 4

- Commit reviewed: 75ece62
- Model: gpt-6-astra · session 01a17247-ddb9-78b2-9c9c-00dee27456e0 · tokens used: 34,320
- Verdict: REQUEST CHANGES

## Prompt

```
You are the independent reviewer for the OUT-18 part C monthly allowance, cycle 2. Do not commit, push or modify files.
The previous review and the builder's response are in audits/OUT-18-C-CODEX-REVIEW-3.md. Review commit 75ece62 (`git show 75ece62`).
Confirm the three findings are resolved: the Postgres race pre-creates the meters and asserts the monthly refusal; month_bounds() and the monthly query are tested at the listed edges; the old 500-per-business provisions are marked superseded. Check the refactor to month_bounds() changed no behaviour.
If pytest cannot run in your sandbox, read the tests and say so.
Verdict APPROVE or REQUEST CHANGES with numbered P1/P2/P3 findings.
```

## Review (verbatim)

**REQUEST CHANGES** — commit `75ece62`; one remaining P2 finding.

1. **P2 — Last-day inclusion is still not proved.** [test_outreach_send.py:570](/Users/michaelrickards/dev/bh2-OUT-18/backend/tests/test_outreach_send.py:570) seeds 439 events on 31 October and expects approval. Approval succeeds whether the production query counts 439 or incorrectly counts zero. The subsequent independent SQL assertion passes in either case. Add a case with 440 last-day events and assert the monthly-allowance refusal. Keep the existing next-month exclusion case.

The other findings are resolved: the PostgreSQL race pre-creates both meters and asserts the monthly refusal; the old provisions are marked superseded. State coverage and the five calendar-edge cases are added. The `month_bounds()` extraction preserves the original expressions, input and behaviour.

**Verification:** 5 passed, 109 setup errors because the read-only sandbox lacks a writable temporary directory, and 8 PostgreSQL tests skipped because `RLS_LOCAL_DATABASE_URL` is unset. Remaining tests reviewed statically. No files modified, commits or pushes.
## Response

1. Taken. `test_a_brand_whose_month_filled_on_its_last_day_is_refused` seeds 440 events on 31 October and asserts the brand's monthly-allowance refusal. Mutation-checked: with the query's upper bound moved to exclude the 31st, the test fails. The next-month exclusion case is kept.
