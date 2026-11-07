1. **Resolved P2 — backend/services/aria_memory.py:212–217.** Upper-bound validation precedes rounding; quantization failures become `ValueError`, mapped to 422. No remaining client-input exception path or regression found. Database failures remain separate.

**98 tests passed**, including oversized-input and API 422 regressions; additional boundary probes passed. Full `check.sh` omitted to preserve read-only operation.

**Verdict: APPROVE.**