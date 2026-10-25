# OUT-18 part C (monthly allowance) — Codex review 3

- Commit reviewed: 9b2b94c
- Model: gpt-6-astra · session 01a17037-a007-7dd0-a06e-359278d5b32a · tokens used: 48,857
- Verdict: REQUEST CHANGES

## Prompt

```
You are the independent reviewer for an OUT-18 part C addition (RED: outreach monthly allowance). Do not commit, push or modify files.
Read docs/OUT-18-TICKET.md part C. Review commit 9b2b94c (`git show 9b2b94c`), mainly backend/services/metering.py reserve_outreach_usage.
Mike's decision (25 Oct 2026): the monthly allowance is per brand — its daily limit min(20, business_daily_cap) times the UK weekdays in the month — replacing the fixed 500 per business. It counts the brand's reserved/committed/unknown outreach_usage_events with local_send_date in the UK month, under the business lock.
Check:
1. Correctness: month boundaries (first day, last day, December rollover), weekday count, the Europe/London date, states counted, released excluded, other brands never counted; concurrency (business lock held through count and reservation in every caller); nothing else still enforces or promises 500 per business (code, Aria tools, copy, docs).
2. Billing/reporting: the business-wide sent/held usage_meters are still maintained by reserve and settle; does anything bill or report from them in a way that now misleads?
3. Tests: backend/tests/test_outreach_send.py monthly tests and the rebuilt Postgres concurrency test in backend/tests/test_outreach_send_rls.py (test_the_last_monthly_slot_goes_to_exactly_one) prove it.
If pytest cannot run in your sandbox, read the tests and say so.
Verdict APPROVE or REQUEST CHANGES with numbered P1/P2/P3 findings.
```

## Review (verbatim)

**REQUEST CHANGES** — three P2 findings; no P1 runtime defect found.

1. **P2 — The concurrency test lost its steady-state setup.** [test_outreach_send_rls.py:222](/Users/michaelrickards/dev/bh2-OUT-18/backend/tests/test_outreach_send_rls.py:222) removes the pre-existing sent/held meter rows without replacing them. `lock_outreach_usage` therefore inserts them during approval; unique-key contention can serialize the transactions independently of the explicit locks. This contradicts the test’s “every row … already exists” comment and weakens its concurrency evidence. Pre-create both October meters before racing approvals, and assert the loser receives the monthly-allowance refusal.

2. **P2 — Monthly regression coverage omits required cases.** [test_outreach_send.py:501](/Users/michaelrickards/dev/bh2-OUT-18/backend/tests/test_outreach_send.py:501) tests October committed events, the previous month, another brand and a lower cap. It does not test monthly reserved/unknown inclusion, released exclusion, last-day inclusion, next-month exclusion, December rollover or different month lengths. Daily-state tests exercise a separate query and cannot protect the monthly query. Add these cases with explicit expected allowances.

3. **P2 — Existing contracts still prescribe 500 per business.** [OUT-2-CONTRACTS.md:77](/Users/michaelrickards/dev/bh2-OUT-18/docs/OUT-2-CONTRACTS.md:77), [OUT-3-TICKET.md:81](/Users/michaelrickards/dev/bh2-OUT-18/docs/OUT-3-TICKET.md:81), [OUT-4-TICKET.md:109](/Users/michaelrickards/dev/bh2-OUT-18/docs/OUT-4-TICKET.md:109) and [OUT-6-TICKET.md:186](/Users/michaelrickards/dev/bh2-OUT-18/docs/OUT-6-TICKET.md:186) retain the old allowance and meter-authority requirements. Mark these superseded by Mike’s 25 October decision and link part C, so subsequent billing work does not restore the old rule.

On inspection, the implementation correctly uses Europe/London, an inclusive month start and exclusive following-month start, December rollover, Monday–Friday counting, tenant/brand filtering and the three chargeable states. The sole reservation caller holds the business lock through counting, insertion and action claim. Reserve/settle retain business-wide sent/held accounting, including original-period settlement. I found no remaining executable 500 gate or billing/reporting consumer interpreting those totals as a 500 allowance; Aria’s settings guidance is updated.

**Verification:** attempted both test files with bytecode/cache writes disabled: **104 setup errors** because the read-only sandbox has no writable temporary directory; **8 PostgreSQL tests skipped** because `RLS_LOCAL_DATABASE_URL` is unset. Tests were reviewed statically, not verified passing. No files modified, commits or pushes.
## Response

1. **Taken.** The Postgres race pre-creates October's sent and held meters, so only the locks can serialise it. It also asserts the loser's refusal is the brand's monthly allowance.
2. **Taken.**
   - The month window and weekday count moved into `metering.month_bounds()`. It is tested for October (22), December rolling into January (23), a 28-day February (20), a leap February (21), and a month starting on a Sunday (21).
   - Query tests: reserved, unknown and mixed states count; released doesn't; 31 October counts and 1 November doesn't.
3. **Taken.** OUT-2-CONTRACTS (three places), OUT-3, OUT-4 and OUT-6 (two places) mark the 500-per-business email allowance superseded by OUT-18 part C, with the reason.
