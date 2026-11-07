1. **P2 — Exhausted-list path can still exceed the limit.** [backend/services/meeting_ledger.py:125](/Users/michaelrickards/dev/bh2-BM-3/backend/services/meeting_ledger.py:125): when no trimmable items remain, `fit()` breaks and returns without enforcing the limit. Reproduced with an empty search result and `limit=100`: output is **259 characters**. Reject an unsatisfiable limit explicitly instead of returning oversized JSON.

The review-3 ordering issue is resolved. **97 targeted tests passed**, including the new boundary regression; no regression detected. Full `check.sh` was not run in this read-only review.

**Verdict: CHANGES.**