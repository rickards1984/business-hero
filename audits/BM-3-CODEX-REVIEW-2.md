1. **P2 — `fit()` does not guarantee its size limit.** `backend/services/meeting_ledger.py:92–103`: it stops trimming at one item per list and adds `trimmed_note` after checking size. Reproduced: 50 search rows with 624-character references return **24,014 characters**, exceeding 24,000. A single oversized reference can exceed even the brief limit. Include metadata in the budget and handle oversized individual fields.

2. **P2 — Trimming leaves misleading completeness metadata.** `backend/services/meeting_ledger.py:100`: shortening lists does not update `large_one_off_income.shown` or search `truncated`. Reproduced: `shown: 40` with only **20 lines**, and `truncated: false` with **25 of 50 matches**. Update these fields while preserving overall counts and totals.

Findings 2, 4 and 5 from review 1 are resolved; recurring-payer filtering is corrected. **90 targeted tests passed.** Full `check.sh` was not run in this read-only review.

**Verdict: CHANGES.**