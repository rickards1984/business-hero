# BH-003 — Codex reviews (ORIGINAL, UNEDITED)

Three passes, all mutation-driven. Nothing edited or softened.

| | Review 1 | Re-review | Review 3 |
|---|---|---|---|
| Commit | `dd0574a` | `ca8df9a` | `d31a4a3` |
| Session | `01a0928b-5361-7dc1-9236-94a8aabcada1` | `01a09292-8100-77b1-8685-e5e45ca2afc8` | `01a0b62d-d06d-73d3-8303-c765c78d868c` |
| Tokens reported | 30,609 | 40,417 | 127,691 |
| Verdict | REQUEST-CHANGES | REQUEST-CHANGES | REQUEST-CHANGES — 4 items, all taken |

Reviewer: Codex CLI 0.153.4, ChatGPT auth, sandboxed to the worktree, no
network. Reviews 1–2 on `gpt-6-astra`; review 3 on `gpt-5.6-sol` (the CLI's
default had moved). All declined `./check.sh full`. Review 3 was given
`--sandbox workspace-write` so it could mutation-test `accounting.py`; it
restored the file by reverse patch (the sandbox could not write the linked
worktree's `.git/index.lock`) and `git status` was clean afterwards. Its
sandbox could not open loopback TCP, so it could not run the RLS suite
against the container; its findings on that file are from reading it, and
the builder's re-run of its five proposed policy mutations is in the PR.

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

---

## REVIEW 3 — d31a4a3

The eight claimed backend mutations are now detected. However, additional branch-specific tenant leaks survive, and the RLS structural checks admit unsafe states. I recommend changes before approval.

## A. Backend mutation results

Control run: **17 passed**.

| Mutation | Result |
|---|---:|
| Category-list ID replaced with B’s category ID | Detected — **1 failure** |
| Nested transaction category ID replaced with B’s category ID | Detected — **3 failures** |
| B transaction ID added as response metadata | Detected — **2 failures** |
| Duplicate returned transaction | Detected — **4 failures** |
| Reverse transaction ordering | Detected — **4 failures** |
| `total_pages=999` | Detected — **3 failures** |
| Ignore requested offset | Detected — **3 failures** |
| Remove transaction tenant restriction only beyond page one | Detected — **2 failures** |

The builder’s stated claim is accurate.

Additional mutations:

| Additional mutation | Result |
|---|---:|
| `total_pages=999` only after page one | **Survives — 17 passed** |
| Remove transaction tenant restriction only when `type` is supplied | **Survives — 17 passed** |
| Remove category tenant restriction only when `type` is supplied | **Survives — 17 passed** |
| Copy B’s amount onto every returned A transaction | **Survives — 17 passed** |

The type-filter escapes are material: both endpoints expose a caller-controlled `type` branch, but no test invokes it. The current `UNCOVERED` registry discusses search and partial-field provenance, but does not disclose the untested type branches.

The amount mutation confirms the acknowledged fixture-provenance limitation at [test_tenant_isolation_backend_path.py:596](/Users/michaelrickards/dev/bh2-BH-003-isolation/backend/tests/test_tenant_isolation_backend_path.py:596): both tenants use `-100.0`, so the exact-response assertion cannot identify whose amount was returned.

`accounting.py` was restored byte-for-byte to `HEAD`; `cmp` returned zero, final targeted pytest was **17 passed**, and final `git status --short` was empty. The requested `git checkout -- backend/accounting.py` was attempted, but the sandbox could not write the linked worktree’s external `.git/index.lock`; I restored every mutation with exact reverse patches instead.

## B. RLS review

### 1. Impersonation

[acting_as at lines 157–174](/Users/michaelrickards/dev/bh2-BH-003-isolation/backend/tests/test_tenant_isolation_rls_path.py:157) is sufficient for the policies presently replayed:

- `SET LOCAL ROLE authenticated` gives the correct `current_user`.
- Both legacy individual claims and the JSON `request.jwt.claims` value are set transaction-locally.
- Consequently, `auth.uid()` and `auth.email()` should resolve as they do through PostgREST for these fixed inputs.

“Exactly as PostgREST does it” is slightly overstated:

- The connection’s `session_user` remains `postgres`, rather than PostgREST’s authenticator role.
- The harness does not set the full PostgREST request environment: method, path, headers, cookies, or the complete JWT claim set.
- `acting_as("anon")` sets no JSON role claim, whereas PostgREST supplies claims for an anonymous request.

None of the currently replayed policies uses `auth.jwt()`, request metadata, or `session_user`, so these differences should not change `auth.uid()` today. They remain an equivalence limitation worth stating.

### 2. Structural invariants

The current invariants are not all strong enough.

- **RLS-or-unreachable**, [lines 213–234](/Users/michaelrickards/dev/bh2-BH-003-isolation/backend/tests/test_tenant_isolation_rls_path.py:213), considers only direct table grants reported by `role_table_grants`. It can miss access through `PUBLIC`, inherited roles, and column-level privileges. The view check at lines 325–347 has the same direct-grant limitation.

- **Policy-exists**, [lines 237–252](/Users/michaelrickards/dev/bh2-BH-003-isolation/backend/tests/test_tenant_isolation_rls_path.py:237), counts any policy. It does not require the policy to apply to `authenticated` or to any command the role may execute. Conversely, RLS with no policy is secure deny-all, so the test can also produce a functional false red.

- **No unscoped permissive policy**, [lines 265–287](/Users/michaelrickards/dev/bh2-BH-003-isolation/backend/tests/test_tenant_isolation_rls_path.py:265), recognizes only an expression rendered exactly as `true`. Semantically unconditional expressions such as `is_business_member(...) OR business_id IS NOT NULL` evade it.

- **Every policy references membership**, [lines 290–322](/Users/michaelrickards/dev/bh2-BH-003-isolation/backend/tests/test_tenant_isolation_rls_path.py:290), is only a substring check. `NOT is_business_member(...)`, or `is_business_member(...) OR true`, passes. The latter also evades the exact-`true` invariant.

The three `ALLOWED_UNSCOPED_POLICIES` are justified by migration 029’s declared product design: accounting providers and plan definitions are public catalogues, while automation templates are authenticated-user catalogues. But the allowlist remains safe only while those tables remain non-tenant catalogues. The test does not verify that condition.

`users_view_own` is a justified self-scoped exception. `users_link_self` is justified only together with 030a’s exact two-column UPDATE grant. The RLS suite does not assert that grant remains limited to `user_id` and `accepted_at`; restoring table-wide UPDATE would reopen the documented cross-tenant membership pivot while the structural test stayed green.

Expected policy mutations:

| Policy mutation | Assertion that should catch it |
|---|---|
| Grant an RLS-off table’s sensitive column to `PUBLIC` | RLS-or-unreachable |
| Add `FOR INSERT WITH CHECK (is_business_member(...) OR true)` | Unscoped-policy invariant |
| Change a member policy to `NOT is_business_member(...)` | Exact approved-policy-definition check |
| Restore table-wide UPDATE on `business_members` | Exact column-grant invariant |
| Make an allowed catalogue tenant-scoped while retaining `USING(true)` | Catalogue allowlist invariant |

### 3. Entitlement xfails

The required normal and `--runxfail` commands could not connect because this execution sandbox rejects loopback TCP with `Operation not permitted`.

- Normal run: **24 setup errors, 4 xfailed**.
- `--runxfail --tb=short`: **28 setup errors**.

That also demonstrates why `--runxfail` is necessary: ordinary strict-xfail reporting classified the four connection failures as xfails, even though they never reached the entitlement assertion.

Static inspection indicates all four should reach and fail [the `rowcount == 0` assertion at lines 516–525](/Users/michaelrickards/dev/bh2-BH-003-isolation/backend/tests/test_tenant_isolation_rls_path.py:516): migration 033 grants all four columns, `biz_update_if_owner` permits the seeded owner, and the supplied values are valid. Runtime confirmation remains unverified in this sandbox. Read-only `docker exec` was also blocked because the Docker socket is outside the permitted filesystem.

### 4. Replay analysis

The intended high-level order in [rls-local.sh:48](/Users/michaelrickards/dev/bh2-BH-003-isolation/scripts/rls-local.sh:48) is defensible for this unusual history: bootstrap ORM-created tables with 028, replay both migration families, reassert the July baseline, then apply 029 and the runbook migrations.

The principal false-green risk is [the global expected-error regex at line 90](/Users/michaelrickards/dev/bh2-BH-003-isolation/scripts/rls-local.sh:90):

- Expected errors are matched by message alone, not by migration and expected occurrence count.
- `syntax error at or near ","` is especially broad.
- A matching error in an unrelated security statement could be accepted.
- Because replay uses `ON_ERROR_STOP=0` without per-file transactions, the file continues after the error, leaving a partially applied migration.
- Depending on whether the failed statement was an RLS enable, revoke, policy replacement, or grant, this can create either a more-permissive false green or a less-permissive false red.

The ghost-policy prune at [lines 168–208](/Users/michaelrickards/dev/bh2-BH-003-isolation/scripts/rls-local.sh:168) compares only `table|policy-name`. It does not compare command, roles, permissiveness, `USING`, or `WITH CHECK`. A weaker same-named policy can therefore survive as “allowed.” Conversely, a legitimate policy missed by the regex or absent from the selected source set is dropped, generally making the replay less permissive and producing false confidence.

The 031/032 cleanup at [lines 154–166](/Users/michaelrickards/dev/bh2-BH-003-isolation/scripts/rls-local.sh:154) deliberately makes the database less permissive than the literal migration files, but it matches the cited runbook completion steps and recorded September schema. That is reasonable, provided the output continues to describe this as reconstructed runbook state rather than raw migration state.

### 5. What green does not prove

A green RLS run does not prove:

- Current production or staging schema, grants, policies, views, or migration application.
- That migration 029 was actually applied in production.
- PostgREST HTTP/JWT validation, role switching, query translation, or response serialization.
- Isolation for tables other than the five behaviorally seeded resources.
- Every operation on those tables; only selected reads, inserts, updates, and deletes are exercised.
- Pending-invite safety, exact `business_members` column grants, inactive-member behavior, multi-business memberships, or role changes.
- Platform-admin, service-role, SECURITY DEFINER, RPC/function, storage, or auth-schema paths.
- Tenant safety of parent-scoped tables lacking a direct `business_id`.
- Production-only views absent from the replay.
- Backend application isolation; that remains the SQLite endpoint suite’s separate concern.
- Protection from semantically unsafe policies that merely contain one of the accepted membership substrings.

I did not run `./check.sh`, as requested.

VERDICT: **REQUEST-CHANGES**

1. Add mutation-sensitive `type`-filter tests for both transaction and category readers, and update `UNCOVERED` for any intentionally untested filter branches and later-page metadata.
2. Strengthen the structural checks to include effective `PUBLIC`/inherited/column privileges and reject semantically unsafe policy expressions; add an exact `business_members` UPDATE-column invariant before allowing `users_link_self`.
3. Scope each replay-expected error to a specific migration and expected count, and fail on unexpected partial application.
4. Compare allowed ghost policies by complete policy definition—not only table and policy name—so a weaker same-named policy cannot produce a false green.
