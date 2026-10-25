# OUT-18 part A — Codex review 2

- Commit reviewed: 8cce5c7
- Model: gpt-6-astra · session 01a17009-459c-7ef0-b319-b1c34bfefd53 · tokens used: 48,823
- Verdict: REQUEST CHANGES

## Prompt

```
You are the independent reviewer for OUT-18 part A, cycle 2 (RED: research spend caps and daily personal-data limits). Do not commit, push or modify files.
Review 1 and the builder's response are in audits/OUT-18-CODEX-REVIEW-1.md. Review commit 8cce5c7 (`git show 8cce5c7`) against the findings, in the context of backend/services/outreach_research.py at HEAD.
Check each finding is resolved and that the fixes introduce no new problem:
- lock order and held-lock duration (is anything slow — network, model, DNS — now done while holding the business lock? _still_allowed is called under the lock before reserving);
- that nothing between _lock and commit calls session.rollback()/commit() in a way that silently releases the lock early;
- that review contacts counting toward the daily total cannot let more than 20 contacts per brand per UK day be stored, and gatekeepers stay at most 10;
- that the new tests would fail against 18fb47d (the builder says they do; reason about it).
The later commit on the branch (OUT-18 part B setup status) is out of scope for this cycle.
If pytest cannot run in your sandbox, read the tests and say so.
Verdict APPROVE or REQUEST CHANGES with numbered P1/P2/P3 findings.
```

## Review (verbatim)

**REQUEST CHANGES** — reviewed `8cce5c7` against review 1 and `outreach_research.py` at HEAD. Part B excluded. This review serves correctness and security prerequisites.

1. **P1 — Overspend settlement reverses the lock order and can lose the excess charge and pause.**  
   At [outreach_research.py:749](/Users/michaelrickards/dev/bh2-OUT-18/backend/services/outreach_research.py:749), `_spend()` updates—and locks—the meter before the overspend handler acquires the business lock at line 754. A concurrent reservation takes the business lock first, then waits for that same meter. The overspend transaction waits for its business lock: a PostgreSQL deadlock. If settlement is aborted, its excess charge and brand pause roll back, leaving only the original reservation recorded.

   Acquire the business lock **before settlement’s meter update**, retaining it through the overspend pause and commit. Add a regression covering this interleaving; SQLite’s single-writer locking does not reproduce PostgreSQL’s row-lock cycle.

2. **P2 — The reservation concurrency regression does not reliably fail against the old code.**  
   The [test barrier](/Users/michaelrickards/dev/bh2-OUT-18/backend/tests/test_outreach_research_brands.py:366) runs **before** `_spent()` reads the balance. After both threads cross it, one can read, reserve and commit before the other reads. Consequently, `18fb47d` can pass. Coordinate completed balance reads or explicitly assert that the business lock remains held through reservation, and cover the PostgreSQL settlement interleaving above.

The remaining checks support the fixes:

- **Review 1 finding 1:** config saves now lock before reading and retain the lock through saving; overspend has the new ordering defect above.
- **Finding 2:** review contacts now consume the shared brand/day total and gatekeeper allowance. Both storage loops recheck under the business lock. `_contact_type()` produces the same two recognised values stored as evidence, so review contacts cannot escape subsequent counts.
- **Finding 3:** authority, budget, spend and reservation are now atomic under the business lock.
- **Finding 4:** Aria receives lessons within each brand’s entry.
- `_still_allowed()` performs database reads and local checks, with no network, model or DNS work and no hidden commit/rollback. The inspected successful locked paths retain their locks until the explicit commit.

Statically, the owner-update, review-limit, eligible-first and per-brand lessons tests would fail against `18fb47d`. The foreign-brand and legacy-inheritance additions should already pass there; they close coverage gaps rather than demonstrate changed behaviour. The builder’s blanket “each new test fails” claim is therefore too broad.

Pytest failed **before collection** because the sandbox has no writable temporary directory. Tests were reviewed statically; no passing execution is claimed. No files were modified, committed or pushed.
## Response

1. **P1 1 — taken.**
   - The settlement now takes the business lock before its meter update. It holds the lock through any overspend pause and the commit.
   - Every meter write now takes the business lock first: the reservation, the settlement and the pause. There is no second ordering left.
2. **P2 2 — taken.**
   - The barrier test is replaced by `test_every_meter_write_happens_under_the_business_lock`, parametrised for a normal search and for an overspend.
   - It records the order of lock acquisitions, meter writes and transaction ends (commit or rollback on a tracking Session). It fails if any meter write happens without the business lock held since the transaction began.
   - It is deterministic and checks the lock-order property itself, which SQLite's single writer can't reproduce. It fails against both 18fb47d and 8cce5c7 (both cases) and passes now.
3. **The builder's earlier claim — corrected.** The foreign-brand and legacy-inheritance additions close coverage gaps and pass on 18fb47d; they don't demonstrate changed behaviour. The earlier response overstated this.
