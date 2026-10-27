**PROFIT-1 review 5 — `58daf06`, North Star P8**

**P1:** None found.  
**P2:** None remaining. Both review-4 findings are closed.

- Cancelled quote requests record estimated costs and propagate cancellation. Restoring `except Exception` in memory makes the cancellation regression fail. Independent probing confirmed the second quote path too.
- Both preview endpoints return **503 with zero provider calls**. Disabling either gate independently makes the behavioural regression fail.
- The race-test cleanup now releases the writer and joins the worker before the blocking assertion.

**Backlog:** Unchanged: `research_compare` cost gating/accounting, per-business paid-top-up profitability, and alert-delivery visibility. No new backlog defects found.

**Verification:** 722 tests passed—46 profit-guard and 676 plan-enforcement—with an in-memory database fixture. Changed Python files pass Ruff. No regressions found within these checks. PostgreSQL tests and `check.sh` were not run under the read-only constraint. No files modified, committed or pushed.

**Verdict: APPROVE.**