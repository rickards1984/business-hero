Reviewed `b9eeb08` under **North Star P8**. No files modified, committed or pushed.

**P1**

- **Partial accounting releasing a hold: closed.** Failed drafts retain the whole hold alongside recorded costs. Removing this fix in memory makes its regression fail: **0p retained instead of 536p**.
- **Reported usage above the bound: mitigated, not an absolute guarantee.** The added overhead covers a bounded discrepancy; arbitrary provider-reported usage can still exceed it. Logging detects that after spending. I found no practical overspend path introduced by this diff that warrants retaining P1 solely for anomalous provider billing.

The 25% allowance provides substantial headroom: including the £3 reserve, drafting/research thresholds are £27.75 against £99 and £22.75 against £79. That supports accepting the stated provider anomaly as an operational residual risk. It **does not prove “always net profit”**: other costs and deliberately ungated reply sorting remain outside that guarantee. P8 requires removing claims that actual cost “can never exceed” the hold.

**P2**

- **The overhead regression does not detect removal of its fix.** [The framing test](/Users/michaelrickards/dev/bh2-OUT-19BC/backend/tests/test_outreach_allowance.py:445) still passes with `PROVIDER_OVERHEAD_TOKENS` removed from the hold calculation. It reserves two providers but succeeds on the first, with additional unused system-prompt headroom. Add a boundary test that exhausts those margins and fails without the overhead.
- **Known zero-dispatch failures permanently consume allowance.** [Admission and settlement](/Users/michaelrickards/dev/bh2-OUT-19BC/backend/services/outreach_setup.py:807) reserve cooling providers, but execution can find no available provider. The resulting failure retains its hold despite no dispatch. A probe produced **8p → 16p → 24p held across three zero-call retries**. Near the ceiling, an outage retry can therefore stop a brand for the month after providers recover. Distinguish proven no-dispatch failures from unknown billed attempts, and add a regression.

**Backlog**

- Retaining protection for genuinely unknown charges is acceptable. **Do not arbitrarily cap or expire those holds**, which would reopen spending capacity without resolving liability.
- Reconcile holds using per-attempt evidence of dispatch, recorded usage and settlement. Fully accounted failures need not permanently count both their full hold and their cost.
- Add context-freezing and over-hold logging regressions. Retain PostgreSQL concurrency verification and the previously identified part F charging and reply-adapter follow-through.

**Verification:** All **30 allowance tests passed** with process-local in-memory SQLite and cache/bytecode writes disabled. Mutation checks and the zero-dispatch probe ran without file changes. `check.sh` was not run because it writes compiled files; live providers, PostgreSQL and browser behaviour remain unverified. No UI click proves these accounting guarantees.

**Verdict: REQUEST CHANGES** — for the two P2 findings above, not for hypothetical unlimited provider overbilling.