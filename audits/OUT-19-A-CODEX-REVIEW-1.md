# OUT-19 part A — Codex review 1

- Commit reviewed: ee75c10
- Model: gpt-6-astra · session 01a17251-5692-7d13-a071-5deadb354f23 · tokens used: 48,491
- Verdict: REQUEST CHANGES

## Prompt

```
You are the independent reviewer for OUT-19 part A in this repository (RED: AI spend). Do not commit, push or modify files.
Read docs/OUT-19-TICKET.md first (part A and decisions). Review commit ee75c10 (`git show ee75c10`): backend/services/ai_costs.py, backend/services/outreach_pricing.py, backend/admin_outreach_api.py, the instrumentation in backend/services/outreach_research.py and backend/services/outreach_setup.py, and the admin panel.
Check:
1. Every outreach AI call that costs money is recorded exactly once with the right business, brand and purpose; nothing double-counts (research also meters its own budget meter — is that intended and clear?); the record happens in a transaction that commits on success paths and is not lost on refusal paths; lock order (the research record runs under the business lock after the reservation; the platform total read scans usage_meters across businesses — any contention or deadlock risk on PostgreSQL?).
2. Pricing: unpriced models fail closed; AI_PRICES_JSON parsing is safe; the default prices are plausible (state that they need checking against provider pages).
3. The kill switch: research stops before reserving, drafts refuse before calling the model; the alarm logs once on crossing; with nothing set nothing is blocked.
4. The economics report and route: platform-admin only; revenue follows Mike's prices (first brand included in Business, £79 extra, £99 Pro add-on); no data from one business leaks to another in a non-admin path; losing-money flag correct.
5. Tests in backend/tests/test_ai_costs.py prove each point.
If pytest cannot run in your sandbox, read the tests and say so.
Verdict APPROVE or REQUEST CHANGES with numbered P1/P2/P3 findings.
```

## Review (verbatim)

**REQUEST CHANGES** — commit `ee75c10`. This review serves the North Star’s correctness and stability prerequisites.

1. **P1 — Paid drafts can disappear from the ledger.** In [outreach_setup.py:554](/Users/michaelrickards/dev/bh2-OUT-19/backend/services/outreach_setup.py:554), audience-field validation and renewed authority checks happen before recording. Campaign validation happens after recording but before committing. Invalid model JSON also escapes `_ai_draft` without saving collected usage. Consequently, malformed output, revoked authority or rejected campaign content can incur spend without advancing the kill switch. Persist usage independently of whether the generated content is accepted. Add regression tests for each refusal path.

2. **P1 — Failed research can evade platform accounting.** [outreach_research.py:747](/Users/michaelrickards/dev/bh2-OUT-19/backend/services/outreach_research.py:747) retains the budget reservation after an exception because billable work may have occurred, but records nothing in `ai_pence`. Repeated billable timeouts therefore remain invisible to the platform limit. Record an explicitly estimated charge pending reconciliation. Drafting’s SDK retry also needs accounting for potentially billed attempts.

3. **P1 — Pricing does not fail closed.** [ai_costs.py:43](/Users/michaelrickards/dev/bh2-OUT-19/backend/services/ai_costs.py:43) accepts negative, non-finite and incorrectly sized price arrays; malformed later entries leave earlier overrides applied despite logging that built-ins are used. An unknown model is allowed at an arbitrary known rate, which cannot bound its actual cost. Moreover, research bypasses this table entirely through `pence=cost`, retaining separate model-independent pricing. Validate the whole configuration atomically and reject unpriced models before spending; use the same model-specific prices for research reservations and settlement.

4. **P2 — The alarm is not once-per-crossing under concurrency.** [ai_costs.py:94](/Users/michaelrickards/dev/bh2-OUT-19/backend/services/ai_costs.py:94) reads an unlocked total and logs before commit. With total 40p and alarm 50p, two concurrent 6p records can both omit the alarm; two 10p records can both emit it. Rollback can also leave a false alarm. Use durable, atomic crossing detection. The kill switch likewise excludes in-flight spend: it is a check of settled costs, not a guaranteed monthly ceiling.

5. **P2 — Concurrent privacy drafts can lose a completed call’s cost.** [outreach_setup.py:593](/Users/michaelrickards/dev/bh2-OUT-19/backend/services/outreach_setup.py:593) saves without reacquiring the shared business lock. `_add` uses UPDATE-then-INSERT, so concurrent first writes to a monthly meter can collide on the unique constraint and roll back one charge. Use an atomic upsert or consistently serialize recording; verify with PostgreSQL concurrency tests.

6. **P2 — Required usage detail is discarded.** [ai_costs.py:95](/Users/michaelrickards/dev/bh2-OUT-19/backend/services/ai_costs.py:95) stores cost aggregates and business-level model call counts, but no token or tool-call counts. Model identity cannot be associated with a particular brand/purpose charge. Research does not pass its usage through at all. Part A explicitly requires these details for every call; retain enough information to audit and reconcile them.

7. **P2 — Historical economics uses today’s configuration.** [outreach_pricing.py:47](/Users/michaelrickards/dev/bh2-OUT-19/backend/services/outreach_pricing.py:47) applies current plans, entitlement flags and all current brands to whichever month is requested. A brand created this month can add £79 to last month’s reported revenue. Label projected revenue clearly and use period-appropriate evidence for historical figures. The losing-money arithmetic is correct against the calculated revenue, but that revenue is not reliable historical earnings. A Business account’s included brand also has £0 allocated revenue, so any spend flags it; describe this as incremental outreach margin rather than whole-account profitability.

8. **P2 — The admin panel omits last month.** [AdminDashboard.tsx:237](/Users/michaelrickards/dev/bh2-OUT-19/frontend/client/src/pages/AdminDashboard.tsx:237) only fetches the default current period. Part A requires this month and last month. Add a period selector or comparison, including per-brand margin.

What checks out:

- Successful research settlement commits before later contact refusals. Recording both `outreach_research_pence` and `ai_pence` is intentional: one enforces the brand research budget, the other reports platform costs. The economics query does **not** sum both.
- Research checks the kill switch before reservation; drafts check before invoking the model. An unset kill setting allows calls.
- The economics route uses `get_platform_admin_context`. I found no new non-admin path exposing another business’s economics.
- The pricing rules implement £0 incremental charge for Business’s first brand, £79 extras and £99 for Pro’s first add-on brand.
- The platform SUM does not acquire row locks across businesses. I found no deadlock introduced by that scan; it can add query load while the business lock is held. PostgreSQL documents that plain reads use locks compatible with ordinary writes. [PostgreSQL locking documentation](https://www.postgresql.org/docs/current/explicit-locking.html)
- Default token prices look plausible as approximate conversions, **but all defaults—especially web-search/tool charges—and the exchange rate need checking against current provider pages before approval.** They are not verified here.

**Tests:** I read all 17 tests. They establish basic successful accounting, sequential alarm behavior, kill-switch placement, price arithmetic and the route’s dependency declaration; they do not prove the failure and concurrency cases above. Pytest could not start: `No usable temporary directory found` in this read-only sandbox. No files were modified, committed or pushed.
## Response

1. **P1 1 — taken.**
   - `_ai_draft` records and commits a draft's usage as soon as the model returns (in a `finally`), before the content is validated or authority re-checked.
   - Invalid JSON, refused fields and refused campaign emails are all charged.
   - `_model_json` uses no SDK retries and bounded output. A call that raises is recorded at an estimate (every input character a token, the full output) and marked estimated.
   - Tests: invalid JSON, a refused field, a refused campaign, a failed call, and no retries.
2. **P1 2 — taken.**
   - A failed search records its reserve in the ledger as an estimated charge, under the business lock.
   - Test: `test_a_failed_search_is_recorded_at_its_reserve_as_an_estimate`.
3. **P1 3 — taken.**
   - AI_PRICES_JSON is validated as a whole: three finite non-negative numbers per provider/model key, or the entire setting is ignored.
   - An unpriced model raises `Unpriced`. Drafts refuse 503 before the model runs; research stops before reserving.
   - Research's reserve (`max_search_pence`), its settlement and web_search's cost all use the one ai_costs table. The old `ARIA_RESEARCH_PRICE_*` settings are removed.
   - Tests cover each point.
4. **P2 4 — taken.**
   - Ledger writes are serialised platform-wide with one PostgreSQL advisory transaction lock, always the last lock taken.
   - The alarm is raised by an after-commit hook: once per crossing, never on rollback.
   - Test (PostgreSQL): two calls crossing together raise one alarm; it fails with the lock removed.
   - The kill switch's semantics are stated in the ticket and the module: a check of recorded spend; in-flight calls can exceed it by their own cost.
5. **P2 5 — taken.**
   - Meter writes are one atomic `INSERT … ON CONFLICT DO UPDATE`.
   - Test (PostgreSQL): two first writes both count. It fails against update-then-insert when the race window is widened; on its own it is probabilistic.
6. **P2 6 — taken.**
   - Each call adds to `ai_pence`, `ai_calls`, `ai_estimated`, `ai_tokens_in`, `ai_tokens_out` and `ai_tools`, keyed by purpose × brand × provider/model. Research passes its token and tool counts.
   - Monthly aggregates at that grain are the stated audit record (ticket A).
7. **P2 7 — taken.**
   - A period counts only brands created before its end.
   - The report states that revenue is projected from the current plan, not invoices, and that the margin is the incremental outreach margin.
   - Test: `test_a_past_month_counts_only_brands_that_existed_then`.
8. **P2 8 — taken.** The panel switches between this month and last month, and shows each brand's price, cost and margin.

**Default prices:** they remain approximate and must be checked against the provider pages; both the ticket and the module say so.
