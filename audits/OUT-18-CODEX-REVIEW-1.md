# OUT-18 part A — Codex review 1

- Commit reviewed: 18fb47d
- Model: gpt-6-astra · session 01a17002-b46e-7012-8a00-2dfb6e986fc1 · tokens used: 73,612
- Verdict: REQUEST CHANGES

## Prompt

```
You are the independent reviewer for OUT-18 part A in this repository (RED: research spend caps and the daily limits on collecting personal data). Do not commit, push or modify files.
Read docs/OUT-18-TICKET.md (part A) first. Review commit 18fb47d on branch ticket/OUT-18-multi-brand (`git show 18fb47d`).

Check:
1. Spend: each brand's budget holds under every path — reserve before search, settle after, failure keeps the reservation, overspend pauses only that brand, mid-run budget re-read, legacy meter counted (fail closed). Can a brand spend past its cap, or can one brand's spend be charged to another? Is anything left reading the old business-level config or meter in a way that now silently does nothing?
2. Quota: 20 per brand per UK day and at most 10 gatekeepers per brand, counted from the database (prospect.lia_id -> outreach_compliance.brand_id). Any prospect path where lia_id is missing or wrong so a contact escapes its brand's count? The store step still re-checks under the business lock.
3. Authority: configure and save_lessons are owner-only and reject another business's brand (404); _still_allowed now checks the audience's brand switch; run_due runs only audiences of switched-on brands and still claims the day once.
4. Legacy migration: a pre-OUT-18 business-level enabled/monthly_cap_pence/lessons becomes each brand's starting value, never below £20.
5. Tests: test_outreach_research_brands.py proves each point and the existing research tests kept their assertions (diff them).
Run: .venv/bin/python -m pytest backend/tests/test_outreach_research.py backend/tests/test_outreach_research_brands.py -q (if the sandbox blocks temp files, read the tests carefully and say so).
Verdict APPROVE or REQUEST CHANGES with numbered P1/P2/P3 findings.
```

## Review (verbatim)

**REQUEST CHANGES** — reviewed `18fb47d` on `ticket/OUT-18-multi-brand`. These affect the correctness and security prerequisites.

1. **P1 — Research can overwrite another brand’s switch or budget.**  
   The overspend handler and final summary save read and replace the whole research configuration without the business lock. If the owner disables brand B or lowers its budget after that read, brand A’s subsequent save restores B’s old settings. Lock before reading and retain the lock through saving; add an interleaved owner-update regression test. See [overspend save](/Users/michaelrickards/dev/bh2-OUT-18/backend/services/outreach_research.py:740) and [summary save](/Users/michaelrickards/dev/bh2-OUT-18/backend/services/outreach_research.py:807).

2. **P1 — Review-only contacts escape the personal-data collection limits.**  
   `_today_counts` excludes `eligibility='review'`, while the review-store loop applies neither quota. A batch containing 25 distinct sole-trader contacts can therefore store all 25, and subsequent attempts still see zero quota consumed. Their `lia_id` is populated correctly; the eligibility filter is the bypass. Count retained review contacts and enforce limits before storing them. This is a retained defect in the reviewed paths. See [count filter](/Users/michaelrickards/dev/bh2-OUT-18/backend/services/outreach_research.py:610) and [review storage](/Users/michaelrickards/dev/bh2-OUT-18/backend/services/outreach_research.py:776).

3. **P1 — Budget check and reservation are not atomic.**  
   The current budget and spend are read without the business lock before reserving. Concurrent runs can both pass against the same balance; an owner’s budget reduction can also commit between the check and reservation. The daily scheduler claim limits ordinary duplicate scheduling but does not make this operation atomic against configuration changes. Lock, re-read authority/budget/spend, reserve, then commit before searching. Add a concurrency regression test. See [reservation path](/Users/michaelrickards/dev/bh2-OUT-18/backend/services/outreach_research.py:717).

4. **P2 — Aria still receives combined, unlabelled results lessons.**  
   The research tool calls `lessons(session, business)` without a brand, so outcomes from different brands remain pooled despite the new per-brand contract. Return results lessons within each brand’s entry and test two brands with different outcomes. See [tool adapter](/Users/michaelrickards/dev/bh2-OUT-18/backend/assistant_tools.py:641).

Otherwise, inspection supports brand-specific meter attribution, settlement and failure reservations, legacy-meter inclusion, owner authority and tenant-scoped brand lookup, legacy settings inheritance with the £20 floor, and switched-on audience selection with the daily claim retained. Eligible-contact storage still rechecks under the business lock.

The existing research-test assertions were preserved, with brand-specific inputs and expectations substituted. The new tests do **not** prove every requested point: notably, foreign-brand rejection uses a nonexistent ID rather than another tenant’s actual brand, and legacy inheritance tests only a below-minimum cap with empty lessons.

The requested pytest command failed **before collection** because the sandbox has no writable temporary directory. I reviewed the tests statically; no passing execution is claimed. No files were modified, committed or pushed.
## Response

All four findings and both test gaps were taken. Each new test was run against 18fb47d's code and fails there.

1. **P1 1 — taken.**
   - `configure` and `save_lessons` take the business lock before reading the config.
   - Research's own saves (the overspend pause and the end-of-run summary/rotation) lock, re-read and save. The summary text is composed before the lock.
   - Test: `test_a_research_run_never_undoes_the_owners_change_to_another_brand` (the owner changes FitFutures while the gym's run is finishing).
2. **P1 2 — taken.**
   - Contacts held for review count toward the brand's daily total and gatekeeper limit (`_today_counts` reads eligible and review).
   - They are stored after eligible contacts, only while room remains.
   - Tests: 25 sole traders store 20 and a later run stores none; with eligible and review contacts in one batch, eligible ones come first.
3. **P1 3 — taken.**
   - The authority re-check, budget read, spend read and reservation are one step under the business lock, committed before the search.
   - Test: two simultaneous runs with room for exactly one search make one search between them, and the meter stays within budget.
4. **P2 4 — taken.**
   - `status()` carries `lessons_from_results` inside each brand's entry.
   - Aria's tool no longer adds pooled lessons.
   - Test: two brands with different outcomes.

**Test gaps — taken.**
- Foreign-brand rejection now uses another business's real brand, for both `configure` and `save_lessons`.
- Legacy inheritance is tested with a cap above £20 and with legacy notes.
