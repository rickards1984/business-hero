1. **P2 — Recovery can exit while a failed turn remains unsaved.** [backend/realtime_voice.py:1046](/Users/michaelrickards/dev/bh2-BM-2/backend/realtime_voice.py:1046). If the first ledger snapshot finds only a `saving` entry, `todo` is empty. If that worker then marks it `failed` before the separate `saving` check, `_final_save` returns without retrying it. Reproduced using the repository functions: recovery returned with one failed entry and zero recovery saves. Check all outstanding states in one locked snapshot before returning, and add this interleaving as a regression test.

Review 3’s original scenarios are addressed, subject to the accepted database-timeout residual. No billing or ordinary Aria voice regression found.

Verification: **94 targeted tests passed**. Full `check.sh` and browser checks were not run. No files changed, commits or pushes.

**Verdict: CHANGES.**