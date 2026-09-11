# BH-003 — Codex reviews (ORIGINAL, UNEDITED)

Two passes, both mutation-driven. Nothing edited or softened.

| | Review 1 | Re-review |
|---|---|---|
| Commit | `dd0574a` | `ca8df9a` |
| Session | `01a0928b-5361-7dc1-9236-94a8aabcada1` | `01a09292-8100-77b1-8685-e5e45ca2afc8` |
| Tokens reported | 30,609 | 40,417 |
| Verdict | REQUEST-CHANGES | REQUEST-CHANGES |

Reviewer: Codex CLI 0.153.4, `gpt-6-astra`, ChatGPT auth, sandboxed to the
worktree, no network, no database. Both declined `./check.sh full`.

**The re-review's mutation table is the most important thing here.**
It is the honest measure of what this harness detects.

---

## REVIEW 1 — dd0574a

**VERDICT: REQUEST-CHANGES.** This is useful executable regression coverage, but its assertions and coverage claims need tightening. I found harness defects, not a demonstrated production leak.

1. **Reviewed commit and verification**

Reviewed `dd0574a539cc8be7d6595cb38641db7e6c58f9f4`, parent `fb804549277c0e2e3d739cc18232a48f44e18c2e`. The diff contains only the specified test file. Working tree was clean before and after.

I ran:

- Git diff/status and source inspection of the tests, endpoints, database setup, and recorded schema.
- Targeted pytest with in-memory SQLite forced, network connections blocked, bytecode disabled, and pytest’s cache disabled: **9 passed**, 77 date-adapter/converter deprecation warnings.
- Five in-memory mutations, each followed by all nine tests.
- A direct check of the foreign-category filter result.
- Docker discovery through PATH and standard installation locations.

No file edits, commits, database services, or network calls. I did not run `check.sh`: this was a read-only targeted review, and that script writes compilation/cache artifacts and runs the broader suite.

2. **Confirmed findings**

Line references below refer to `backend/tests/test_tenant_isolation_backend_path.py` unless otherwise specified.

| Severity | Location | Finding and evidence |
|---|---|---|
| High | `:185–196`, `:213–242` | **Foreign IDs and aggregate leaks pass.** Changing the real endpoint’s count query to count every tenant’s transactions left **9/9 green**. Appending an actual B transaction ID obtained from SQLite also left **9/9 green**. The helper checks five strings and B’s business ID, not B’s resource IDs or expected totals. |
| Medium | `:234–238` | **“Returns nothing” is not asserted and is not what happens.** The actual filtered response contains **one A transaction**, `total=1`, `category=None`. That can be legitimate ownership-based behaviour, but the test name promises something else. Assert the intended contract explicitly. |
| Medium | `:224–242` | **Positive and structural assertions are incomplete.** The contaminated row need not actually have `category=None`; only its description and absence of B’s name are checked. Replacing the category endpoint with an empty response left **9/9 green**. |
| Medium | `:273–306` | **The uncovered registry omits accounting gaps and overstates prior coverage.** Accounting import history (`backend/accounting.py:1100`) is neither exercised nor explicitly registered. Summary, insight, assistant-tool and dashboard accounting reads lack endpoint execution here. BH-002’s category-validator tests do not establish ownership of transaction IDs in bulk operations; there is no bulk-delete test in that file. |
| Medium | `:47` | **Synthetic execution is not self-contained at import time.** `import accounting` imports `db`, whose configured PostgreSQL branch immediately connects and executes `SELECT 1` (`backend/db.py`). Supplying SQLite later does not prevent this. I neutralised this during review; the committed harness itself does not. |
| Low | `:313–324` | **Registry tests cannot establish honesty or detect Docker installation.** They check description length and the literal word `BLOCKED`. Installing Docker would leave them green, contrary to the comment’s suggested reminder. |

The high-severity designation concerns false assurance from the harness, not a newly confirmed application vulnerability.

3. **Detection strength and ways leaks can pass**

The committed self-tests exercise **seeded SQLite → handwritten unsafe query → assertion helper**. They establish that those query results contain detectable markers. They do not pass through the endpoint’s query construction or response mapping.

However, my mutations of the real endpoint body provide useful additional evidence:

| In-memory mutation | Result |
|---|---|
| Remove transaction tenant predicate | 3 tests failed |
| Remove category join tenant predicate | 3 tests failed |
| Count transactions across all tenants | All 9 passed |
| Append B’s transaction ID | All 9 passed |
| Return no categories | All 9 passed |

Other gaps, inferred from the assertions rather than reproduced as application defects:

- B’s amounts, dates, colours, resource IDs, or partial fields can leak without any marker.
- Case conversion, encoding, truncation, or an opaque object representation can hide markers from `repr()`. Ordinary JSON formatting alone would generally preserve these particular strings.
- Incorrect row counts, duplicates, pagination metadata, or cross-tenant influence on ordering are not checked.
- There are no later-page, date-range, reconciliation, archive, or reverse B→A cases.
- HTTP error responses and existence disclosures are untested. An unexpected exception in an exercised call would fail; an unexercised error path remains invisible.
- Authentication and business selection are bypassed by injecting the caller tuple directly.

4. **SQLite fidelity and `UNCOVERED` honesty**

For the specific canonical UUID strings and ordinary equality joins exercised here, SQLite provides meaningful evidence: it demonstrably catches removal of either tenant predicate. I found no demonstrated SQLite/Postgres discrepancy that makes these exact scoped queries leak.

It does not establish Postgres equivalence. UUID typing/casts, arrays, `ILIKE`, numeric precision, timezone handling, constraints, defaults, policies and database roles differ or are absent. The handcrafted schema uses TEXT IDs, omits foreign keys and several recorded columns, and relaxes required fields. The recorded schema itself is not proof of current production state.

The two workarounds are reasonable for this limited test:

- Explicit arguments reproduce the intended default inputs, but bypass FastAPI parsing, validation and dependency resolution. Search remains excluded.
- `PARSE_DECLTYPES` provides date objects expected by the endpoint; it does not reproduce Postgres timezone or driver behaviour.

Docker was **not discoverable in PATH**, and Docker Desktop plus standard CLI locations were absent. That supports “Docker unavailable in this environment”; an exhaustive claim that it exists nowhere is **UNVERIFIED**. Docker absence blocks the stated `supabase start` approach, not every possible local Postgres approach.

The registry is candid about major exclusions but **incomplete and occasionally overstated**:

- It should explicitly inventory remaining accounting reads, metadata assertions, HTTP/authentication, and filter/pagination gaps.
- Search uses a bound `:search` parameter; “interpolates caller-supplied text into a query” is misleading.
- Calling the RLS path the “larger half” of risk is unsupported by this harness.
- The claim about fake tests should be narrowed to category ownership validation.

5. **Ranked next coverage**

1. **Strengthen these two readers first:** exact returned ID sets, exact totals, `category=None`, positive category visibility, both caller directions, pagination and distinct numeric values. Add endpoint-path mutations that must fail.
2. **Finish accounting reads:** import history, summary totals, category aggregates, dashboard and assistant reads. Verify numerical results, not just marker absence.
3. **Cover targeted writes:** B transaction IDs in patch/delete/bulk requests; mixed A/B batches; assert B’s stored rows remain unchanged.
4. **Add local synthetic Postgres execution:** search, UUID ownership checks, bulk arrays, and representative schema constraints. Keep external integrations disabled.
5. **Test HTTP business selection, then extend to other resources:** quotes/invoices and linked customers, followed by communications and operational records.
6. **Deliver the separate RLS suite:** anonymous and authenticated roles with explicitly documented policy provenance. Treat this as a separate P0-9 requirement.

The two-tenant pattern is reusable, but “add a table and reader” understates the work. Accounting-specific seeding, fixed B markers and one-way assertions need resource-specific expectations. Incremental extraction of tenant fixtures and structural assertions should suffice; a wholesale rebuild is unnecessary.

6. **UNVERIFIED**

Production/staging schema, policies and behaviour; Postgres execution; HTTP authentication and serialization; live RLS; exhaustive Docker absence; full repository checks. No behavioural UI test was performed or is needed to substantiate these harness findings.

7. **Exact claim justified by green**

A green run supports only:

> With these synthetic rows in SQLite and an explicitly supplied A business context, the tested transaction/category calls omit the five B marker strings and B business UUID; the default transaction response retains both seeded A descriptions.

My additional mutation checks show that these tests detect removal of the exercised transaction scope and category join scope.

**It does not justify “tenant isolation is verified,” “accounting is isolated,” or completion of P0-9.**
---
## RE-REVIEW — ca8df9a

Reviewed **ca8df9a5e34e305b98b7898f42d82ae41f5106e5**, scoped to `dd0574a..ca8df9a`.

**VERDICT — REQUEST-CHANGES**

The three previously surviving mutations now fail independently, exactly as reported. Two issues remain: category IDs can leak while green despite the registry’s claim, and the import guard does not enforce synthetic-only database configuration.

I ran `.venv/bin/python -B` with in-memory source mutations and `unittest` discovery. Each variant ran all 11 tests against synthetic SQLite; socket connections were blocked. No files, commits, or remote systems were changed.

| Mutation | Failures / errors |
|---|---:|
| Unmutated control | **0 / 0** |
| Remove transaction tenant predicate | 4 / 0 |
| Remove category-join tenant predicate | 3 / 0 |
| Count across tenants | **2 / 0** |
| Append foreign transaction ID | **2 / 0** |
| Return no categories | **1 / 0** |
| Return no transactions | 3 / 1 |
| Replace category-list ID with B’s ID | **0 / 0 — survives** |
| Replace own nested category ID with B’s ID | **0 / 0 — survives** |
| Add B’s transaction ID as response metadata | **0 / 0 — survives** |
| Duplicate a returned transaction | 0 / 0 — survives |
| Reverse transaction ordering | 0 / 0 — survives |
| Set `total_pages=999` | 0 / 0 — survives |
| Ignore pagination offset | 0 / 0 — survives |
| Remove tenant restriction only beyond page one | **0 / 0 — survives** |

The first five mutations reproduce the described previous mutation classes; the previous executable mutation scripts were not available.

**Disposition of prior findings**

- **Three mutation escapes: fixed.** Exact transaction IDs, totals, and positive category visibility assertions now detect them.
- **Filter contract: corrected.** Filtering by B’s category returns A’s contaminated transaction, with its category suppressed. The assertions match current behavior.
- **Over-constraint: no material problem found.** Fixture-specific IDs, names, and counts are appropriate. A future change to foreign-category filtering would require an intentional contract update. Remaining weaknesses are under-assertion: sets discard duplicates, and `.get("category")` also accepts a missing key.
- **Import safety: partly fixed.** Synthetic PostgreSQL URLs in either primary environment variable were refused before application import. However, an unchecked `SQLITE_DATABASE_URL=postgresql://…` reached `db.create_engine` in an intercepted probe. That fallback does **not** itself connect at import in current `db.py`; this is not evidence of an immediate PostgreSQL connection. Conversely, a file-backed `DATABASE_URL=sqlite:///…` passes the guard and follows the import-time `connect()`/`SELECT 1` path. Therefore the guard does not guarantee synthetic-only execution.
- **Registry: substantially improved, still overstated.** [Lines 380–382](/Users/michaelrickards/dev/bh2-BH-003-isolation/backend/tests/test_tenant_isolation_backend_path.py:380) claim exact IDs for both readers. The category test asserts only name and count; both foreign-category-ID mutations survive. The ordering, pagination, duplicate, HTTP/auth, and PostgreSQL limitations are now acknowledged accurately.

Partial-field disclosure remains possible beyond IDs: tenants share fixture values for amounts, dates, category colors, and other fields, so provenance cannot be distinguished for those values.

**UNVERIFIED:** PostgreSQL/RLS, HTTP/authentication, actual external database connections, and full-suite `./check.sh` results. I did not run the repository-wide command under the no-file-edits/local-synthetic-only constraints. Docker was absent from PATH and the three standard locations checked; other installation locations remain unverified.

**Single most valuable next addition:** Add an exact full-response assertion using tenant-distinct field values, including category IDs and response metadata.

**What green now justifies:** “For the seeded SQLite fixture and directly injected A caller, the tested first-page transaction calls return the expected transaction-ID sets and totals, suppress the contaminated category, preserve A’s category name, and return the expected category name/count without the configured B markers.”