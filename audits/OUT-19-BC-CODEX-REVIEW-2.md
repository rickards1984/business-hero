Reviewed `febb427` against `f8a96b3` under **North Star P8**. Worktree unchanged.

**P1 — not closed**

- **The hold does not bound actual concurrent spend.** [draft_hold_pence](/Users/michaelrickards/dev/bh2-OUT-19BC/backend/services/outreach_allowance.py:103) reserves a configurable estimate, unrelated to the provider chain’s maximum cost. A deterministic probe started at **£26.25**, admitted three overlapping **50p holds**, and settled three mocked **£1 costs**: **£29.25 against a £27.75 limit**, exceeding it by three holds. Research sees draft holds, but underestimated costs can still accumulate across overlapping operations. Reserve a defensible cost bound or otherwise enforce the requested overrun bound, including draft/research overlap.
- **Unknown failures can release unaccounted spend.** In [_ai_draft](/Users/michaelrickards/dev/bh2-OUT-19BC/backend/services/outreach_setup.py:837), an exception with an empty `spent` collection still releases the hold. An injected exception left **0p held**. Preserve the hold when incurred cost is unknown. An injected **recording failure correctly retained 50p**.

The hold is committed before the model runs, and successful recording and release share a transaction. PostgreSQL settlement takes the business lock before the ledger lock; I found no new lock-order inversion. SQLite admission takes its write lock before checking allowance. **Actual PostgreSQL execution and concurrent lock contention remain unverified.**

**P2 — original findings closed**

- Legacy business-wide research spend now counts against each brand.
- Refusal messages no longer offer unavailable top-ups.
- Budget copy describes brand monthly prices rather than claiming those amounts have already been committed to billing.

**Backlog and regression quality**

- Literal `LIKE` prefixes now escape `_`, `%` and backslash, with explicit `ESCAPE` in both queries. SQLite behaviour passed; PostgreSQL syntax is consistent on inspection, but was not executed. The regression covers the ledger look-alike, not top-up look-alikes.
- Reply sorting is now tested behaviourally above allowance, **but cost recording is not tested**. Its classifier emits no usage. The test still passed with `ai_costs.save` replaced by a function that raises. Add collected usage and assert the resulting classification ledger cost.
- The D/E integration audit is restored.
- Atomic charging enforcement remains deferred to F; suggested-reply adapter protection remains outstanding.

**Regression sensitivity**

Using process-local substitutions from `f8a96b3`:

| Regression | Without its fix |
|---|---|
| Overlapping draft admission | Fails |
| Legacy research accounting | Fails |
| Literal ledger matching | Fails |
| Finished draft settlement | **Still passes** |

The settlement test accepts an absent hold as zero, so it cannot prove reservation/release. Draft/research overlap, unknown failures, recording failures and PostgreSQL locking need regression coverage.

**Verification:** All **23 allowance tests passed** using an in-memory SQLite adapter. Additional probes exposed the issues above. No files were modified. `check.sh`, browser behaviour and PostgreSQL runtime verification were not performed.

**Verdict: REQUEST CHANGES.**