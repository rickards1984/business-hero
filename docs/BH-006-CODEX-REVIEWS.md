# BH-006 — Codex reviews (ORIGINAL, UNEDITED)

Three passes on the same test file. Nothing edited, softened or reordered.

| | Review 1 | Review 2 | Verification |
|---|---|---|---|
| Commit | `6ab8a70` | `adf30a0` | `f0becd7` |
| Session | `01a09283-45dc-7580-9c79-a16cdfdc8fae` | `01a0928a-f0e4-70d3-9c3f-f18a9eb8f0e6` | `01a09292-cfa1-7ed0-b31c-16c46f3f2849` |
| Tokens reported | 23,951 | 31,684 | 31,604 |
| Verdict | REQUEST-CHANGES | REQUEST-CHANGES | **NO** — one blocker partially open |

Reviewer: Codex CLI 0.153.4, `gpt-6-astra`, ChatGPT auth, sandbox confined
to the worktree, no network, no database. All three declined to run
`./check.sh full` because it writes files; gate results are Claude Code's.

---

## REVIEW 1 — 6ab8a70

**VERDICT: REQUEST-CHANGES.** These tests reproduce the reported local failures, but **this file is not yet a sound basis for Mike to approve the RED implementation work**. The cancellation policy contradicts its own documentation, and important incorrect implementations could satisfy the suite.

1. **Reviewed commit and verification**

Reviewed `6ab8a70620bb2e4a68972aaa9d1284073cefb58d`, parent `35f1f83`, on `ticket/BH-006-stripe-webhook-tests`. The diff contains only the stated new test file. Working tree remained clean.

Ran both commands with database URLs cleared, SQLite configured in memory, bytecode writing disabled, and pytest’s cache disabled:

```text
.venv/bin/python -m pytest -p no:cacheprovider backend/tests/test_stripe_webhook_correctness.py -q
.venv/bin/python -m pytest -p no:cacheprovider backend/tests/test_stripe_webhook_correctness.py --runxfail -q --tb=short
```

Results: **3 passed, 6 xfailed**, then **3 passed, 6 failed**. Every failure was its intended behavioural assertion:

| Test | Failure |
|---|---|
| Cancellation must not upgrade | Tier became `pro`, line 203 |
| Cancellation must not rewrite tier | `business` became `pro`, line 225 |
| Replay applies once | Two business commits, line 273 |
| Replay preserves subsequent state | Tier reverted to `pro`, line 302 |
| Item period is read | Period remained `None`, line 348 |
| Missing period preserves stored value | Period became `None`, line 373 |

No crashes or fixture errors caused these failures. No edits, commits, database connections, network operations, or deployments were performed. `check.sh` was not run; this was a constrained review with no changes.

2. **Defect-by-defect assessment**

**Cancellation: real, but incorrectly bounded by the tests.**  
[main.py:989](/Users/michaelrickards/dev/bh2-BH-006-stripe/backend/main.py:989) handles deleted subscriptions through the same price-resolution and tier-assignment path as updates.

Test 1’s `!= "pro"` does **not** establish “must not raise the tier”: assigning `business`, `None`, or an invalid string would pass.

Test 2 requires the tier to remain exactly `business`. That rejects the documented possibility of downgrading cancellations to `starter`. The file therefore **already chooses a policy while claiming to leave it undecided**. A no-upgrade invariant is reasonable interim evidence, but Mike must resolve—or explicitly delimit—the cancelled-state policy before implementation approval.

**Replay: real, but only sequential behaviour is covered.**  
[main.py:1023](/Users/michaelrickards/dev/bh2-BH-006-stripe/backend/main.py:1023) commits business changes before recording the audit event. The handler never queries previous events. The two replay tests correctly expose repeated application and stale-state resurrection.

They do not establish durable event-ID de-duplication, transaction atomicity, or concurrent delivery safety.

**Period: local defect confirmed; external version claim unverified.**  
[main.py:1008](/Users/michaelrickards/dev/bh2-BH-006-stripe/backend/main.py:1008) reads only the top-level field and assigns `None` when absent. An item-only synthetic event therefore loses its period exactly as reported.

The item test checks the expected timestamp, and the legacy guard protects top-level support. However, the preservation test checks only non-nullness: replacing the stored date with any other date passes. It should assert equality with `known`.

3. **Wrong implementations that could pass**

- **Ignore every cancellation.** Both cancellation tests pass while status, cancellation flags, and other subscription state remain stale.
- **De-duplicate by payload or `(subscription_id, price_id)`.** The different-event guard changes both event ID and price. It cannot distinguish these incorrect keys from event-ID de-duplication.
- **Use an in-process event-ID cache.** All replay deliveries occur within one process. No test proves that a new session/process can find a committed audit row.
- **Record events without committing them.** The fake adds audit rows to `recorded_events` immediately; rollback does not remove them. Subsequent lookups see uncommitted or rolled-back records.
- **Persist the wrong business.** Every non-`stripe_events` query returns the fixture business regardless of its predicates.
- **Replace a missing period with an arbitrary date.** The preservation assertion accepts it.

The fake is truthful for the expected `event_id_1` equality query, but **not generally honest**: if that parameter is absent, it returns the first recorded event regardless of the query’s actual condition. Unsupported queries should fail explicitly.

Suppressing **all** writes would fail the commit-count guards; never assigning any period would fail the two timestamp tests. Nevertheless, mutable object assertions and simulated commit counts do not prove persisted correctness.

4. **Missing cases, ranked by likely cost**

| Priority | Missing contract |
|---|---|
| **Critical** | Atomic business update and event recording; failures before/after persistence; retry after rollback; concurrent duplicate delivery. Otherwise events can be lost or applied repeatedly. |
| **Critical** | Customer/subscription matching and unknown customers. Assert no unrelated business mutation and define whether unmatched events are recorded, retried, or ignored. The fake currently conceals lookup defects. |
| **High** | A previously unseen **older** event arriving after a newer event. The existing stale replay test only covers an already-seen ID. Include event ordering metadata and agree the stale-event policy. |
| **High** | Cancellation status and access semantics: `subscription_status`, `is_active`, `past_due`, `unpaid`, `canceled`, and `trialing`. The upgrade guard starts with `is_active=True`, so it does not prove reactivation. |
| **High** | `cancel_at_period_end=True`: scheduling cancellation must be distinguished from deletion. Assert the relevant tier, status, flag, and period behaviour. |
| **High** | Non-empty `feature_flags` during cancellation. Merely skipping tier assignment while still calling `strip_plan_defaults` with the old event’s price could erase genuine exceptions. |
| **High** | `checkout.session.completed`: correct business/customer/subscription linkage, replay protection, and stale linkage overwrite. It shares the audit problem but has no coverage here. |
| **Medium** | Distinct event IDs with otherwise identical payloads, plus same subscription/price with changed status or period. Assert both are processed and audit IDs are correct. |
| **Medium** | Unknown price mapping and empty items: preserve valid tier/flags while defining which other fields still update. |
| **Medium** | Exact period preservation, replacing an existing period, precedence when both locations exist, and UTC storage semantics. |

[RC1_SCOPE.md:86](/Users/michaelrickards/dev/bh2-BH-006-stripe/docs/RC1_SCOPE.md:86) already states that `past_due` keeps access and `unpaid`/`canceled` become read-only. The storage-tier choice may remain undecided, but access policy is not wholly unspecified.

5. **Judgement on `xfail(strict=True)`**

**Legitimate as a temporary tests-first mechanism, but the documentation overstates its guarantee.**

Strict mode makes a fully passing marked test fail as XPASS, exposing the need to remove its marker. It does **not** guarantee review: an unrelated exception or a different failing assertion can keep the test classified as XFAIL after implementation changes.

Require marker removal for completed fixes and review the ordinary passing tests. Restricting expected exception types can reduce accidental masking, but cannot replace checking the precise failure reason. Today’s `--runxfail` run confirms the intended reasons.

6. **UNVERIFIED**

- Stripe’s current payload/version contract and this deployment’s configured API version.
- Claims about historical redelivery incidents.
- Live audit-table constraints, transaction behaviour, concurrency, and deployed webhook configuration.
- Actual signature verification: intentionally stubbed.
- Full repository checks and end-to-end access behaviour.
- The bypass examples above are reasoned from the tests and fake; no mutation implementations were written or executed.

7. **Final verdict**

**REQUEST-CHANGES.** Preserve these useful reproductions, but resolve the cancellation contradiction, strengthen the fake and de-duplication guards, and assert exact period preservation before presenting the file as the implementation approval contract.
---
## REVIEW 2 — adf30a0

Reviewed **adf30a0b064f58bca342d7bcc9f7a01eed526de5**, scoped to `6ab8a70..adf30a0`, with relevant implementation and entitlement tests inspected.

**VERDICT: REQUEST-CHANGES. This test file is not yet a sound basis for Mike to approve the RED implementation work.** Two blockers remain: the fake still accepts incorrect queries, and the fourth-defect fixture does not establish the genuine exception it claims.

What I ran:

- Target file with `--runxfail`: **7 failed, 7 passed**. All seven failed on their own behavioural assertions, not setup errors.
- Target file plus `test_entitlement_defaults.py`, normal markers: **66 passed, 7 xfailed**.
- In-memory probes of query handling and `strip_plan_defaults`.
- Final Git status/diff: clean.

Runs disabled bytecode/cache writes, blocked socket connections, and cleared production database configuration. No files edited. `check.sh` was not run; this was targeted, read-only verification.

Disposition of the prior findings:

| Finding | Disposition |
|---|---|
| Cancellation assertion too weak or policy-prescriptive | Substantially corrected; qualification below. |
| Fake returns the business regardless of lookup | **Still open.** Bound-value membership is not predicate evaluation. |
| Uncommitted audit row can satisfy deduplication | Closed for this fake’s audit collection; durability remains unproven. |
| Ignoring every cancellation can pass | Closed for wholesale ignoring: status and `is_active` are asserted. Persistence is not. |
| Deduplication by payload/subscription/price can pass | New identical-payload/different-ID guard closes that route. |
| Arbitrary non-null period can pass | Closed at whole-second precision; not literally exact datetime preservation. |
| Feature exceptions untested | Added, but its fixture misidentifies a plan default as an exception. |
| Missing cases and access-policy ambiguity | Better documented; RC1 already specifies canceled access. Documentation does not verify behaviour. |

**1. The fake still permits wrong implementations.**

At [the query dispatcher](/Users/michaelrickards/dev/bh2-BH-006-stripe/backend/tests/test_stripe_webhook_correctness.py:119), I directly verified that all these incorrectly return the fixture business:

- `Business.name == business.stripe_customer_id`
- Correct customer **AND incorrect subscription**
- `Business.stripe_customer_id != business.stripe_customer_id`

A lookup using `Business.name == customer_id` would therefore satisfy the known/unknown fixtures while failing to find the intended business in reality.

Likewise, after committing an audit row, `StripeEvent.type == recorded_event_id` incorrectly returns it. An implementation querying the wrong audit column can appear to deduplicate successfully.

These are demonstrated fake failures, not full-suite implementation mutations. The fake needs to validate the supported expression structure and reject unsupported predicates.

**2. The cancellation invariant is reasonable, but narrower than its name.**

`after in {before, CANCELLED_FLOOR}` correctly permits retaining the tier or resetting to Starter, and rejects Business → Pro in this fixture. I accept it as an outcome constraint pending the stored-tier decision.

It does **not** prove independence from the event’s price. Price-dependent code can still pass whenever the selected price resolves to `before` or Starter. Both tier tests use a Pro price; other prices remain uncovered. The assertion message also overclaims: an invalid result does not necessarily mean it came from the price.

**3. The fourth defect is not established by this fixture.**

[The test](/Users/michaelrickards/dev/bh2-BH-006-stripe/backend/tests/test_stripe_webhook_correctness.py:333) starts with **Pro + `receptionist=True`**. Pro already grants receptionist. [The helper’s contract](/Users/michaelrickards/dev/bh2-BH-006-stripe/backend/auth.py:330) deliberately removes matching defaults, and the existing entitlement test explicitly expects this exact input to become `{}`.

Thus the removal is real, but calling it loss of a genuine exception is unsupported. With the current handler retaining Pro, effective receptionist access remains enabled.

A valid reproducer would start at **Starter + `receptionist=True`**, then deliver cancellation carrying a Pro price. That flag genuinely contradicts Starter’s default, and stripping against the event’s Pro tier removes it. This would isolate the claimed wrong-tier normalization defect.

Other ways incorrect code can pass:

- Mutate cancellation status or period in memory without committing: those assertions inspect the same object.
- Use session-local deduplication, or commit the business and audit separately.
- Mutate unrelated fields on an unknown-customer event: only tier and business commit count are checked.
- Change fractional seconds: `int(timestamp())` discards them.
- Mishandle scheduled cancellations, unseen older events, checkout, unknown prices, or empty items—the documented gaps remain.

**Atomicity/durability split:** I accept deferring real-database proof until implementation verification; it need not block approval to *begin* implementation. However, it must be an explicit completion gate, not merely a permanent `NOT_PINNED` entry. Failure/retry expectations can also be pinned synthetically before implementation, although that cannot prove database concurrency or durability.

**UNVERIFIED:** database atomicity, cross-session/process durability, concurrent delivery, live Stripe payload/signature behaviour, and end-to-end access enforcement. No product clicking is required for this review; the blockers concern the test contract itself.
---
## VERIFICATION — f0becd7

**NO** — the Starter fixture blocker is resolved; the fake-query blocker remains partially open. Mike can receive the PR with that limitation explicit. Closing it requires validating column identity and rejecting unsupported query shapes.

Verification was restricted to `adf30a0..f0becd7`; HEAD matched `f0becd7`.

1. **Are both fixes correct and complete?**  
   The fixture fix is correct. The predicate fix correctly handles all the exact previous counterexamples, but is incomplete:

   | Synthetic probe | Result |
   |---|---|
   | Correct customer/subscription OR lookup | Match |
   | `Business.name == customer_id` | None |
   | Correct customer AND wrong subscription | None |
   | Unknown customer | None |
   | Committed audit lookup by `event_id` | Match |
   | Audit lookup by `type == event_id` | None |
   | Business `in_()` predicate | `UnsupportedQuery` |
   | Absent column | `UnsupportedQuery` |

2. **Can a wrong query still pass? Yes.**  
   At [line 143](/Users/michaelrickards/dev/bh2-BH-006-stripe/backend/tests/test_stripe_webhook_correctness.py:143), the evaluator trusts `.key`, without verifying the expression is an actual column belonging to the selected entity.

   This false predicate returns the business:

   ```python
   select(Business).where(
       literal("wrong").label("stripe_customer_id") == "cus_synthetic"
   )
   ```

   I also replaced every Business predicate column **in memory** with a false literal bearing that column’s label. The entire file retained **7 passed, 7 xfailed**, despite those queries being unable to match in SQL. This demonstrates a surviving false-green bypass; it does not establish that a completed implementation passes.

3. **Is the Starter fixture valid, and the defect real? Yes.**  
   Independently confirmed:

   ```text
   strip_plan_defaults({"receptionist": True}, "starter") → {"receptionist": True}
   strip_plan_defaults({"receptionist": True}, "pro")     → {}
   ```

   Running the revised test with `--runxfail` failed at its intended assertion: cancellation changed Starter to Pro and erased the exception. This reproduces normalization against the cancellation’s price-derived tier; it is not a defect in `strip_plan_defaults`.

4. **Other problems in the changed fake:**  
   Independently reproduced:

   - A foreign table’s column sharing a row attribute name can match.
   - `.limit(0)` is ignored and returns a business.
   - Unsupported audit predicates return `None` when no committed events exist, because validation occurs only inside the row loop at [line 163](/Users/michaelrickards/dev/bh2-BH-006-stripe/backend/tests/test_stripe_webhook_correctness.py:163).

   These belong to the same incomplete fail-closed query boundary, rather than a separate implementation review.

5. **Approval conditions:**  
   Resolve that boundary before treating this file as a sound approval gate. The existing `NOT_PINNED` limitations also remain; passing these synthetic tests cannot establish atomicity, durability, or concurrency correctness.

Baseline result: **7 passed, 7 xfailed**. Network connections were guarded against; database configuration was memory-only. No files were edited, and the working tree remains clean. `check.sh` was not run because it writes compiled files/caches; full verification and live behavior are **UNVERIFIED**.