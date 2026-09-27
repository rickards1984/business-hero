# BH-006 implementation — Codex reviews (ORIGINAL, UNEDITED)

The four reviews of the TESTS are in `docs/BH-006-CODEX-REVIEWS.md`. This
file is the review of the IMPLEMENTATION those tests were written for.

| | Review 1 |
|---|---|
| Commits | `6056f44..8e58b1a` (5 commits on `main` @ `fe672a2`) |
| Session | `01a0d502-dfda-73c3-ae72-34c935e8c97d` |
| Tokens reported | 97,584 |
| Verdict | REQUEST-CHANGES — 7 items, all taken |

Reviewer: Codex CLI 0.153.4, `gpt-5.6-sol`, ChatGPT auth, `workspace-write`
so it could mutation-test. It wrote a deliberately incorrect resolver that
**passed all 113 tests**, restored it by exact reverse patch, and left the
tree clean. No database, no `./check.sh`.

**The three findings that mattered most**, all of which were real:

1. **A third shared dependency existed that I had not guarded.**
   `get_current_user_business` (31 endpoints: tasks, calls, business settings,
   integrations, logo, invoice import, the whole receptionist config and
   knowledge base) went through neither guarded dependency. My claim that
   "every authenticated endpoint resolves through one of the two" was simply
   false, and a read-only business could write through all of it.
2. **Admin suspension was not absolute**, exactly as my own docstring said it
   was: `is_active = false` plus a future `trial_ends_at` returned FULL.
3. **`items` in `previous_attributes` is not proof the price changed.**
   Stripe puts it there on a renewal, so a monthly renewal carrying Pro would
   have overwritten a tier an admin had deliberately set to Business — the
   exact class of bug defect 1 exists to prevent, reintroduced by its own fix.

What changed in response, by item: (1) suspension precedence fixed and
`enforce_access` now refuses SUSPENDED too; the full status x is_active x
trial matrix is pinned, and Codex's wrong resolver now fails it. (2) the third
dependency is guarded, plus the four self-authenticating paths — assistant
chat, TTS, realtime voice, inbound receptionist call — and five GETs that
write or spend are refused; the allowlist is exact (method, path) pairs.
(3) the tier moves only when the resolved plan actually differs, with a
freshness guard for out-of-order events and plan-item selection that is not
`items[0]`. (4) `checkout.session.completed` moved inside the
de-duplication and the single transaction. (5) period parsing is UTC-aware
with type validation. (6) 50+ new tests, each named for the failure it
encodes. (7) the runbook's repair is an approved id list captured to a table
with a row-by-row verify and an exact rollback, the unperformable smoke step
is replaced, and the banner is now actually rendered.

**One correction to the review itself:** it reports the read-only-beats-
suspension ordering as following the test rather than the spec. The ordering
is DECISION 3's statutory-retention argument (six-year VAT records, GDPR
Art. 20), and Codex is right that it is an EXCEPTION to suspension rather
than a narrowing — the code and tests now say so in those words.

---

## REVIEW 1 — 8e58b1a

**REQUEST-CHANGES.** Defect 5 is only partially closed, and the claimed read-only enforcement has reachable bypasses.

Reviewed `main..HEAD` at `8e58b1a`, based on `fe672a2`. The requested command passed: **113 passed, 186 warnings**. A deliberately incorrect resolver also passed all 113 tests. I restored it with an exact reverse replacement, reran the suite successfully, and confirmed a clean working tree. No database connections or `check.sh` runs.

**1. Webhook**

**(a) The plan-change predicate is not sufficient.** At [main.py:1075](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/main.py:1075), presence of `previous_attributes.items` is treated as proof of a purchase change.

Stripe documents that billing-period renewal can itself put `items` in `previous_attributes`. Item quantity and other item attributes can also change without changing the purchased price. Consequently:

- A renewal carrying Pro can overwrite a deliberate local Business tier with Pro.
- The same renewal can strip a genuine feature exception against the event’s tier.
- Checking only the first item misses the relevant price if a subscription contains multiple items and the plan item is elsewhere.

The first case directly contradicts DECISION 3’s requirement that payment events preserve the purchased tier. Compare actual old/new plan prices, identifying the relevant item, rather than testing whether `items` exists. [Stripe’s renewal-event guidance](https://support.stripe.com/questions/how-to-determine-when-a-subscription-cycles-using-webhooks?locale=en-GB).

`.created` legitimately needs to establish the initial tier, and `.deleted` correctly preserves it. However, neither establishes event freshness:

- An unseen old `.created` arriving after a downgrade restores the old tier.
- An unseen old price-changing `.updated` does the same.
- An old subscription’s event can match the current business by customer ID, overwrite its current subscription ID/status, and potentially its tier. The lookup uses customer **OR** subscription identity at [main.py:1039](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/main.py:1039).
- An unmatched `.created` is recorded as consumed; linking the business later cannot recover it through replay.

Stripe explicitly does not guarantee delivery order. Event-ID de-duplication cannot solve these distinct-event sequences. [Stripe webhook delivery guidance](https://docs.stripe.com/webhooks#event-ordering).

**(b) De-duplication interleavings**

| Sequence | Result | Does `UNIQUE(event_id)` save it? |
|---|---|---|
| Subscription A commits before duplicate B checks | B skips | Not needed |
| A and B both read “absent,” then both write | Both attempt application | **Yes:** one transaction commits; the losing transaction’s business changes roll back |
| Same concurrent sequence without UNIQUE | Both commit | No |
| Checkout replay, even sequential | Checkout changes commit **before** duplicate lookup | **No** |
| Checkout commits; process fails before audit commit; retry arrives | Checkout applies again | **No** |
| Two distinct event IDs describe stale/new state | Both apply; last writer wins | **No** |

The checkout exception is at [main.py:1000](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/main.py:1000); its commit precedes the check at line 1025. Therefore the “before applying anything” and “same transaction” claims are false for the whole handler.

There is also a more serious failure mode: [main.py:1157](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/main.py:1157) catches **every** commit exception, rolls back, and returns success. A transient database failure now discards both the subscription change and audit row while telling Stripe delivery succeeded. Only a positively identified duplicate-event conflict should receive that treatment; other failures must remain retryable.

**(c) `_resolve_current_period_end` can return incorrect values.** At [main.py:2557](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/main.py:2557):

- `datetime.fromtimestamp()` produces a naive **local-time** value. I reproduced timestamp `1782864000` becoming `2026-07-01 01:00:00` under `Europe/London`, rather than UTC midnight. The existing `.timestamp()` assertion round-trips local time and misses this.
- `True` becomes timestamp `1`; nonintegral numbers are silently truncated by `int()`.
- The first item’s period need not represent the relevant plan item in a multi-item subscription.
- An invalid item period returns `None` immediately, even if the legacy top-level value is valid.

Item-first support and preserving the stored value when absent are correct improvements. Stripe confirms the item-level field change, but it does not establish that the first item always represents this application’s plan. [Stripe billing-period change](https://docs.stripe.com/changelog/basil/2025-03-31/deprecate-subscription-current-period-start-and-end).

**Defect assessment:** cancellation tier preservation is fixed; sequential subscription replay is fixed; item-period handling is improved; exception preservation remains vulnerable to falsely classified plan changes; stopping webhook writes to `is_active` is correct, but access recovery remains incomplete.

**2. Resolver**

**Admin suspension is not absolute.** [auth.py:388](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/auth.py:388) returns full access when `is_active=False` and the trial end is in the future. I reproduced this with `subscription_status="active"`. It also affects `past_due`, `trialing`, and unknown statuses.

Read-only preceding suspension is explicitly required by [test_readonly_resolver.py:161](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/tests/test_readonly_resolver.py:161), so the implementation follows that test. Its explanation is wrong: read-only is **more permissive than suspension**, not narrower. A suspended active business becomes able to access records when its status changes to canceled. That can be an intentional records-access policy, but it must be described as an exception to suspension.

“Fail closed” is qualified at best:

- Unknown status plus absent/expired trial → suspended.
- Unknown status plus future trial → full, **explicitly required by the tests** at [test_readonly_resolver.py:139](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/tests/test_readonly_resolver.py:139).
- Worse, `enforce_read_only` ignores `ACCESS_SUSPENDED` entirely: [auth.py:165](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/auth.py:165). Thus a suspended/unknown-status business can still write through endpoints that use the shared context but lack a separate feature gate.

Stopping the old webhook’s `is_active` writes prevents new dunning lockouts. It does not repair historical ones or guarantee restoration after payment.

**3. Read-only enforcement**

The assertion that every authenticated endpoint uses one of the two protected dependencies is false.

**GET requests with effects:**

- `GET /v1/integrations/awaz` creates an integration and webhook secret when missing: [main.py:1372](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/main.py:1372), [main.py:2387](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/main.py:2387).
- `GET /v1/receptionist/voices/{voice_id}/preview` generates paid OpenAI speech on a cache miss: [receptionist_api.py:580](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/receptionist_api.py:580).
- OAuth callbacks write connections/tokens: Xero, FreeAgent and QuickBooks at [main.py:3434](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/main.py:3434), [main.py:3583](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/main.py:3583), [main.py:3687](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/main.py:3687); Google/Microsoft at [email/router.py:1491](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/app/email/router.py:1491), [email/router.py:1564](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/app/email/router.py:1564). Read-only users can still initiate their GET-based authorization flows.
- `GET /v1/accounting/xero/financial-summary` can refresh and persist provider credentials: [main.py:4631](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/main.py:4631). This may be necessary maintenance for a permitted read, but disproves “GET never mutates.”

**Mutating routes through the unprotected `get_current_user_business`:**

| Reachable operation | Reference |
|---|---|
| PUT business settings | [main.py:1310](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/main.py:1310) |
| PUT integrations | [main.py:1457](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/main.py:1457) |
| POST logo upload URL; PUT logo/brand color | [main.py:1502](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/main.py:1502), [main.py:1531](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/main.py:1531), [main.py:1558](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/main.py:1558) |
| Create, complete, edit, snooze, delete tasks | [main.py:1596](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/main.py:1596), lines 1658, 1684, 1712, 1749 |
| Create calls; archive calls | [main.py:1777](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/main.py:1777), [main.py:2092](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/main.py:2092) |
| Import invoices; mark invoices chased | [main.py:2862](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/main.py:2862), [main.py:2988](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/main.py:2988) |
| PUT receptionist config; PATCH toggle | [receptionist_api.py:422](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/receptionist_api.py:422), line 453 |
| POST/PUT/DELETE receptionist knowledge base | [receptionist_api.py:509](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/receptionist_api.py:509), lines 524, 551 |
| POST receptionist voice preview | [receptionist_api.py:679](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/receptionist_api.py:679) |

The receptionist’s additional check only checks plan/feature entitlement, not subscription access: [receptionist_api.py:317](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/receptionist_api.py:317).

**Other authentication paths:**

- Assistant chat and TTS authenticate JWTs directly, bypassing both dependencies: [main.py:2226](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/main.py:2226), [main.py:2266](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/main.py:2266).
- Realtime voice authenticates independently and opens an OpenAI connection without subscription enforcement: [realtime_voice.py:635](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/realtime_voice.py:635).
- Awaz’s authenticated webhook creates call records and can trigger downstream work: [main.py:1958](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/main.py:1958).
- Signed Twilio receptionist calls check receptionist configuration, not subscription status: [receptionist_call_handler.py:470](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/receptionist_call_handler.py:470).
- Signed WhatsApp callbacks execute actions and send replies without this guard: [whatsapp_briefing_api.py:450](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/whatsapp_briefing_api.py:450), line 540. These require genuine provider traffic; they are not anonymously forgeable merely because they lack JWT dependencies.
- Stripe’s webhook must remain accessible to restore billing.
- `get_current_business` has no endpoint callers in the repository; it is an unguarded dependency, not a demonstrated active bypass.
- `get_platform_admin_context` verifies platform-admin membership. Its mutations are an intentional admin exception, not available to an ordinary read-only customer.

**Allowlist:** [auth.py:149](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/auth.py:149) accepts `/v1/billing/portal-anything` and any path ending `/generate-pdf`, for every mutating method. This is overbroad. For example, `DELETE /v1/quotes/generate-pdf` passes the guard and matches the quote-delete route, although its invalid UUID prevents demonstrating deletion of a real quote. I found no current prefix/suffix trick that deletes an existing valid-ID resource.

Real query strings are excluded from `request.url.path`; appending an allowed path in a query does not bypass it. I found no route/check normalization mismatch establishing a traversal exploit. Use exact method plus matched route identity anyway.

I found no production direct invocation of either protected context dependency that skips its body. The actual bypass is using other dependencies or independent authentication.

Finally, accounting export remains permitted at [main.py:5028](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/main.py:5028), although DECISION 3 restricts read-only exports to quotes/invoices. The test at [test_readonly_resolver.py:308](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/tests/test_readonly_resolver.py:308) explicitly blesses that wrong behavior.

**4. Tests**

The 79 tests constrain several individual functions, but not application-wide enforcement or the complete resolver state matrix.

I replaced the full-status branch with:

```python
if status_value in FULL_ACCESS_STATUSES:
    return ACCESS_SUSPENDED if business.trial_ends_at is not None else ACCESS_FULL
```

**All 113 requested tests passed.** This incorrectly suspends paying businesses with either historical or future trial dates. The tests also miss the existing admin-suspension/future-trial bug, real dependency wiring, callbacks, WebSockets, transaction failures and concurrency.

The two fixture corrections were **legitimate**:

- [test_stripe_webhook_correctness.py:845](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/tests/test_stripe_webhook_correctness.py:845) now models plan changes instead of requiring arbitrary status updates to change the tier.
- [test_stripe_webhook_correctness.py:792](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/tests/test_stripe_webhook_correctness.py:792) makes the initial tier change real, preserving the replay test’s meaning.

The `.created`, `.deleted`, and fake-identity additions strengthen coverage. They do not weaken the approved assertions. However, the simplified item fixtures omit item identities and non-price changes, leaving the incorrect predicate unchallenged.

**5. Fake column identity**

The `_deannotate()`/identity check closes the specific labelled-literal and foreign-table-column hole: [test_stripe_webhook_correctness.py:133](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/tests/test_stripe_webhook_correctness.py:133). I found no ordinary expression that defeats that identity check itself.

The **fake as a whole remains foolable**:

- I reproduced a callable `bindparam` whose `.value` matches the customer but whose actual `effective_value` is another customer. The fake returns the business because [line 205](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/tests/test_stripe_webhook_correctness.py:205) reads `.value`.
- I reproduced `.limit(0)` returning the business; [line 214](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/tests/test_stripe_webhook_correctness.py:214) ignores query modifiers.
- Unsupported StripeEvent predicates are not evaluated when there are no recorded rows.
- Rollback clears pending bookkeeping, not mutations to the shared Business object.

It can also reject legitimate future SQL: aliases, labelled real columns, reversed comparisons, `IN`, and `IS NULL`. Explicit rejection is acceptable for a narrow fake; claiming it answers arbitrary legitimate queries faithfully is not.

**6. Runbook**

Repair **after deployment** is correct: the old webhook can undo repairs on subsequent non-active events. Require the new process to be serving and old workers to have stopped.

The repair itself is not sufficiently bounded:

- [Runbook:56](/Users/michaelrickards/dev/bh2-BH-006-impl/audits/BH-006-PROD-RUNBOOK.md:56) labels all matching rows wrongly locked out despite acknowledging that admin intent is indistinguishable. Future trials also mean some are not locked out.
- Rows currently unpaid/canceled are deliberately excluded. If their stale `is_active=False` remains, a later payment changing status to active leaves them suspended. That breaks “pay to restore.”
- [Runbook:173](/Users/michaelrickards/dev/bh2-BH-006-impl/audits/BH-006-PROD-RUNBOOK.md:173) supplies a complete `BEGIN … COMMIT` block despite saying inspect before committing. Pasting it commits before inspection.
- Comparing counts does not prove the same rows were repaired. Equal-count membership changes can pass.
- The rollback uses the earlier candidate set rather than the exact updated set, and can overwrite subsequent deliberate admin changes: [Runbook:201](/Users/michaelrickards/dev/bh2-BH-006-impl/audits/BH-006-PROD-RUNBOOK.md:201).

Use reviewed explicit IDs, capture the exact changed rows and prior values, and separate the inspection/commit instructions with a verified transaction workflow.

Unsupported claims also need correction:

- Zero current candidates does not prove no previous payment blip.
- “Every write refused” and “admin suspension absolute” are false.
- The frontend does not consume `payment_warning`; Billing reads Supabase directly: [BillingSettings.tsx:54](/Users/michaelrickards/dev/bh2-BH-006-impl/frontend/client/src/pages/BillingSettings.tsx:54). Returning a flag is not the promised banner.
- The admin-UI smoke test cannot edit `subscription_status`: it is excluded from writable overview fields at [admin_business_api.py:49](/Users/michaelrickards/dev/bh2-BH-006-impl/backend/admin_business_api.py:49).
- The production UNIQUE check is appropriately acknowledged as unverified, but concurrency cannot be declared closed without it. Checkout remains unsafe even with it.

**VERDICT: REQUEST-CHANGES**

1. Complete defect 5: enforce suspension precedence, handle historical stale flags through reviewed repair, and prove unpaid/canceled → active recovery.
2. Enforce access across all identified HTTP, AI, WebSocket and provider-action paths; explicitly classify GET side effects and restrict exports/allowlist accurately.
3. Detect actual plan-price changes and prevent stale or superseded subscription events from overwriting current entitlement.
4. Move checkout inside de-duplication/atomic persistence; acknowledge only confirmed duplicate conflicts and preserve retries for other failures.
5. Make period parsing explicitly UTC and validate timestamp/item selection.
6. Add regression tests for these failures, the full status/admin/trial matrix, real dependency wiring, and the demonstrated fake limitations.
7. Correct the runbook’s repair/rollback mechanics and unsupported completion claims; implement the promised visible dunning warning and provide an executable smoke test.