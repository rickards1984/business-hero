# OUT-23 bank — Codex DESIGN review 4 (verbatim, targeted)

Read-only review against North Star P8/P9 and correctness. Nothing modified, committed or pushed; tests were not run.

| Review 3 finding | Resolved? |
|---|---|
| 1. Research accounting blocks drain allocation | Yes — R4.1 separates budgets and allocates per candidate. |
| 2. Inconsistent commitment accounting | Yes — R4.2 subtracts queued work from every applicable bound, once. |
| 3. Card preparation depends on bank/research | Yes — R4.3 provides independent, retryable preparation. |
| 4. Brand-bound allocation and owner caps | Partly — redistribution is specified, but the boost formula is wrong below. |
| 5. Near-deadline stock blocks replenishment | Yes — R4.5 excludes it from replenishment accounting. |
| 6. Invented review quota/promotion workflow | Yes — R4.6 explicitly defers promotion and preserves separate review storage. |
| 7. Rollback invalidates drain locks | Yes — R4.7 acquires authority before selection and preserves the final transaction. |

1. **P2 — R4.2/R4.4 incorrectly cap boosted brands at 20.**  
   [R4.2 line 48 and R4.4 line 58](/Users/michaelrickards/dev/bh2-BANK/docs/OUT-23-TICKET.md:48) specify the lower of the boosted limit and `business_daily_cap`. However, [the send path](/Users/michaelrickards/dev/bh2-BANK/backend/services/metering.py:869) uses `follow(min(20, business_daily_cap), brand_boost)`: an owner setting left at 20 rises with the boost; only settings below 20 remain binding.

   With a 30-email boost and `business_daily_cap=20`, revision 4 allocates only 20 daily places, sizes the bank too small, and understates the monthly allowance. After 20 commitments it drains nothing further although sending could admit ten more.

   **Required change:** specify the exact existing `follow`/`brand_level` policy for both sizing and drain balances. Test a boosted brand with the default 20 setting, plus a lower owner cap that remains binding.

No other new design-level defect found in R4.1–R4.7 affecting wrongful emails or retention, overspend, lost or duplicate sends, avoidable non-sending, or existing behaviour.

VERDICT: CHANGES REQUESTED