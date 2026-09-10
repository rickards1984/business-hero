# BH-002 — Codex reviews (ORIGINAL, UNEDITED)

Two independent reviews of the accounting tenant-isolation fix. Both are
exactly as Codex returned them.

| | Review 1 | Review 2 |
|---|---|---|
| Reviewed commit | `b768580bb24c15d72998ba6c9f286f7289592cb1` | `c8200f7fa1aa8a1f98b94d0c19495b8896f713a4` |
| Scope | `c72d4fc..b768580` | `b768580..c8200f7` |
| Session id | `01a082ae-6dc0-72c1-a401-2d7ba52eb7f4` | `01a082b3-af84-7053-adcc-250210a9d243` |
| Ended | 2026-09-08T20:23:41Z | 2026-09-08T20:28:41Z |
| Exit | 0 | 0 |
| Usage reported by the tool | `tokens used 46,923` | `tokens used 35,558` |
| **Verdict** | **REQUEST-CHANGES** | **APPROVE** — safe to deploy: YES |

Reviewer: Codex CLI 0.153.4, `gpt-6-astra`, ChatGPT auth, sandbox
`workspace-write` confined to the worktree, no network, no database.

Review 1 found two leaking joins outside `accounting.py` that the original
repair missed. Review 2 confirmed both closed by executing the actual query
strings from both commits against synthetic SQLite, and approved.

Note both reviews declined to run `./check.sh full` — its compilation and
cache steps write files, which their no-edit constraint forbade. Full-gate
results here are Claude Code's, not the reviewer's.

===============================================================================
REVIEW 1 — b768580 — REQUEST-CHANGES
===============================================================================

**VERDICT: REQUEST-CHANGES**

I do **not** consider this commit safe for Mike to deploy as a completed tenant-isolation repair. Two additional reporting paths still expose foreign category names.

1. **Reviewed commit and scope**

   Reviewed `b768580bb24c15d72998ba6c9f286f7289592cb1`, specifically `git diff c72d4fc..b768580`. HEAD matches; the working tree was clean before and after review.

   Examined both changed files, searched repository-wide for category reads/writes, and traced CSV import, provider sync, category endpoints, assistant reporting, accountant-pack export, and frontend NULL handling. No files changed; no network, database service, deployment, or Git mutations used.

2. **Verification results**

   - Submitted test file, run through `pytest` with cache/bytecode disabled and database/auth dependency imports stubbed: **12 passed**, two Pydantic deprecation warnings. Network calls were explicitly blocked.
   - In-memory SQLite execution of the **actual six category-join query strings**, extracted from repository source: all four repaired queries concealed the synthetic foreign name; **both additional queries returned it**.
   - Synthetic endpoint probes confirmed None/empty-string write parameters and PATCH behaviour.
   - SQLAlchemy PostgreSQL compilation of the ownership query: passed. A simulated database `DataError` propagated unchanged.
   - `ruff check --no-cache` on both reviewed files: passed.
   - `git diff --check c72d4fc..b768580`: failed on trailing whitespace at `backend/accounting.py:321`, `:376`, `:465`. Left unchanged under your no-edit constraint.

   **`./check.sh` was not run**: it writes compilation artifacts and runs the broader suite. Verification remained restricted to the reviewed synthetic fixtures and read-only checks.

3. **Confirmed findings**

   **HIGH — Accountant-pack export still leaks foreign category names.**  
   [backend/main.py:4967](/Users/michaelrickards/dev/bh2-BH-002-accounting/backend/main.py:4967) joins categories on ID alone. Its business filter scopes transactions, not category ownership. Existing contaminated transactions still put B’s category name into A’s exported workbook. Confirmed using the actual query on synthetic data.

   **HIGH — Assistant spending analysis still leaks foreign category names.**  
   [backend/assistant_tools.py:2140](/Users/michaelrickards/dev/bh2-BH-002-accounting/backend/assistant_tools.py:2140) has the same unscoped join. The result feeds category breakdowns, `top_category`, and generated insight text. Confirmed using the actual query on synthetic data. Both HIGH findings are pre-existing omissions from this repair.

   **MEDIUM — Tests do not establish the claimed completeness.**  
   `backend/tests/test_accounting_tenant_isolation.py:232` scans only `accounting.py`, missing both leaking consumers. At `:65`, the fake session decides ownership from parameters without evaluating the SQL ownership predicate. Removing that predicate could leave these endpoint tests green. PATCH tests also use `UpdateTransactionRequest` (`:141`, `:152`), while the actual route accepts `TransactionUpdate` (`backend/accounting.py:352`).

   **MEDIUM — Invalid category input has inconsistent, unhandled behaviour.**  
   `backend/accounting.py:97`, `:105`, `:335`, `:364`, `:477`:

   | Input | Create | PATCH | Bulk update |
   |---|---|---|---|
   | `None` | Writes NULL | Ignores field; category-only request returns 400 | Writes NULL |
   | `""` | Writes empty string | Writes empty string | Normalises to NULL |
   | Malformed UUID | Unhandled database error | Unhandled database error | Unhandled database error |

   Against PostgreSQL UUID columns, malformed UUIDs—and empty strings reaching writes—produce **500, not 404**. This follows from the cast/write and absent error translation; actual PostgreSQL execution is **UNVERIFIED**. These input problems largely predate this fix; the new helper does not resolve them. Explicit PATCH null still cannot clear an existing foreign reference.

   **MEDIUM — AI insights misclassify contaminated rows.**  
   `backend/accounting.py:964` counts only raw `category_id IS NULL`; the repaired joins at `:984` and `:1001` exclude foreign references. Consequently, a transaction can appear uncategorised in the list while insights report “All transactions categorized”. The count discrepancy was reproduced synthetically.

   **Suspected findings:** none asserted as additional defects. Production-state and integration uncertainties are listed below.

4. **Completeness and regression judgement**

   Claude’s inventory is correct **within `accounting.py`**: four joins and three request-body write paths. All four joins now enforce category ownership; all three writes invoke validation before mutation when assigning a nonempty category.

   Repository-wide, there are **at least six category joins, with two unfixed**.

   No additional unchecked caller-supplied category-ID write was found. CSV import resolves category **names** through business-scoped lookups or creates categories for the current business. Category endpoints similarly scope reads and assign ownership server-side. The three provider-sync writers also resolve categories within their business; their `COALESCE` updates can preserve existing contaminated references.

   The ownership SQL is structurally correct for PostgreSQL UUID IDs: `CAST(:category_id AS uuid)` is valid parameterised syntax, and the business predicate is appropriate. Valid foreign and nonexistent UUIDs both yield 404, without distinguishing ownership.

   Legitimate own-category joins retain their behaviour. The repaired LEFT JOINs preserve transaction amounts and counts, presenting foreign references as uncategorised; that is appropriate. Summary fallback names/colours and frontend rendering handle NULL. AI category lists omit those rows, while overall totals retain them; the misleading categorisation count needs correction.

   The export located is **Excel, not CSV**. Its renderer already handles NULL as “Uncategorised”, but its join remains vulnerable.

5. **Test adequacy**

   **Useful evidence, insufficient approval evidence.** The tests prove validator call-path behaviour against a fake ownership oracle, demonstrate the relational fix on SQLite, and check four source-text predicates. They do not execute the production validator SQL or prove every consumer is protected.

   The old-join leak guard is sound: it establishes that the fixture still reproduces the original defect. It does **not** connect the hand-written repaired query to every production query.

   Approval needs regression coverage for the two missed consumers, actual route request models, nonexistent/malformed/empty/null inputs, rejection before any write, and contaminated-row totals/categorisation. PostgreSQL-specific behaviour should be checked using isolated synthetic PostgreSQL fixtures.

6. **Existing production data and UNVERIFIED**

   This commit does **not** repair stored foreign `category_id` values. Four consumers conceal their names; two still disclose them.

   Proposed **read-only detection query**, not executed:

   ```sql
   SELECT
       t.id AS transaction_id,
       t.business_id AS transaction_business_id,
       t.category_id,
       c.business_id AS category_business_id,
       t.is_archived
   FROM public.accounting_transactions AS t
   JOIN public.accounting_categories AS c
     ON c.id = t.category_id
   WHERE c.business_id IS DISTINCT FROM t.business_id
   ORDER BY t.business_id, t.id;
   ```

   Include archived rows. Under a separately approved production runbook, record affected references, clear invalid associations or replace them with verified own-business categories, and rerun detection. Do not move category ownership or alter financial amounts. Any historical disclosure also needs assessment.

   **UNVERIFIED:** production contamination, live schema/constraints/RLS, PostgreSQL execution and HTTP error responses, authentication integration, complete export/UI execution, and the full repository verification gate.

7. **What would move this to approval**

   Scope both remaining joins, strengthen regression coverage, define consistent invalid/null input handling, correct contaminated-row categorisation in insights, pass the required verification gate, and prepare the separately authorised data-detection/remediation runbook.

   **REQUEST-CHANGES**

===============================================================================
REVIEW 2 — c8200f7 — APPROVE
===============================================================================

Reviewed **c8200f7fa1aa8a1f98b94d0c19495b8896f713a4**, limited to `b768580..c8200f7`, with backend-wide inspection for completeness.

**Verification results**

- **Both HIGH findings are closed:** `backend/main.py:4967` and `backend/assistant_tools.py:2140`. I extracted and executed the actual query strings from both commits against in-memory SQLite. Previously both returned the foreign category name; now neither does. Own categories remain visible, foreign-business transactions remain excluded, and the spending total is preserved.
- Tenant-isolation tests: **12 passed**, using the actual `TransactionUpdate` model, with network and file writes blocked.
- Ruff on all changed Python files: **passed**. Delta whitespace check: **passed**.
- `accounting.py` has an identical AST before/after: whitespace changes do not change behaviour. The model substitution changes tests only.
- No remaining unscoped category join or newly assigned category-write path was found in backend source. CSV import and the three sync paths resolve categories within the transaction’s business; their upserts can retain existing contaminated references.

**Findings — non-blocking for this bounded fix**

- **MEDIUM — `backend/tests/test_accounting_tenant_isolation.py:245`: scan is not a completeness guarantee.** I demonstrated five bypasses: extra whitespace, lowercase SQL, schema qualification, reversed table order, and the expected predicate appearing only in a comment. Dynamic construction and SQLAlchemy expressions are also outside its coverage. Different aliases can cause false failures. The six-join floor does not detect an additional missed join. Independent source inspection found no such remaining category join in this commit.
- **MEDIUM — `docs/BH-002-DEPLOYMENT.md:50`: unsupported historical conclusion.** Zero matching rows proves only that no matching references currently exist—not that the defect was never exercised.
- **MEDIUM — `docs/BH-002-DEPLOYMENT.md:112`: stale rollback.** Reverting only `b768580` does not undo the two fixes in `c8200f7`; it is not a complete rollback of this branch. Do not use this instruction as a verified rollback procedure.

**MEDIUM split: accepted.** None of the four previously reported items must block this leak fix. Malformed IDs fail rather than disclose foreign category data; inconsistent null handling prevents clearing but does not bypass the scoped reads; the insights count remains misleading; and a composite database constraint is valuable follow-up protection requiring separate migration work. These remain defects, not completed work.

**UNVERIFIED:** PostgreSQL execution and UUID/error semantics; live schema, RLS and constraints; historical/current production contamination; full application/export behaviour; deployment and rollback. `./check.sh full` was not run because its compilation/cache steps write files; no full-gate result is claimed. No network, database service, edits, commits or deployment actions were used. Working tree remains clean.

After deployment, Mike should confirm category display, create/edit/bulk assignment, accountant-pack Category cells, and assistant spending breakdowns.

**VERDICT — APPROVE**

**Safe for Mike to deploy this bounded tenant-isolation fix: YES**, subject to the normal release gate. This approves the code delta, not the stale rollback instructions or unverified live environment.