1. **P2 — Size guarantee still fails on the early-return path.** [backend/services/meeting_ledger.py:107](/Users/michaelrickards/dev/bh2-BM-3/backend/services/meeting_ledger.py:107): size is checked before `_refresh_counts()` adds `shown`. Reproduced: a 24,000-character search result returns **24,013 characters** without trimming. Refresh counts before measuring, and add a boundary regression test.

Finding 2 is resolved. No termination, figure-preservation, or brief ledger-section regressions found. **96 targeted tests passed.** Full `check.sh` was not run in this read-only review.

**Verdict: CHANGES.**