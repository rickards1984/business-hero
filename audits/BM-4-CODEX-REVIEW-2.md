1. **P2 — Large finite thresholds now raise an uncaught exception.** [backend/services/aria_memory.py:211](/Users/michaelrickards/dev/bh2-BM-4/backend/services/aria_memory.py:211)  
   Submitting `{"one_off_from": 1e30}` passes Pydantic validation but `quantize()` raises `decimal.InvalidOperation` before the upper-bound check. `_memory_call()` only catches `ValueError`, so this produces HTTP 500 instead of 422. Reproduced directly. Catch quantization failures and add a regression test.

The six original scenarios are resolved; this is a regression in fix 6. Targeted suites: **901 passed**. Full `check.sh` omitted to preserve read-only operation.

**Verdict: CHANGES.**