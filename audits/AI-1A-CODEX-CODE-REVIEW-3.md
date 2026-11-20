# AI-1a — Codex code review 3 (verbatim)

Model gpt-6-astra, read-only sandbox, 20 Nov 2026. After 3 repair cycles the remaining finding was escalated to Mike, who chose: fix it and run one more review (20 Nov 2026).

---

REQUEST CHANGES

1. **P2 — Blocking regression; review 2 finding 6 partially resolved.** [backend/tests/test_ai_models.py:234](/Users/michaelrickards/dev/bh2-AI1a/backend/tests/test_ai_models.py:234)
   Annotated and function-local constants are now detected, but the new prefix filter excludes fine-tuned model IDs. Reproduced:
   ```python
   M = "ft:gpt-4o-mini:org::id"
   client.create(model=M)
   ```
   The previous guard reports `[2]`; the updated guard reports `[]`. A hard-coded fine-tuned model can therefore bypass the switchboard gate. Include `ft:` IDs and a regression example. **Escalate this remaining acceptance-gate defect to the owner as requested.**

2. **Resolved — review 2 finding 1, formerly P1.** [scripts/preflight.sh:200](/Users/michaelrickards/dev/bh2-AI1a/scripts/preflight.sh:200)
   Scanner errors now produce `UNREADABLE`. In-memory execution of the actual scan block confirmed failure reporting when **each of the three grep stages** returns 2. Clean input passes; ordinary and 100,000-line secret payloads are detected. The reported scanner-error bypass is closed.

3. **Resolved for model-specific estimated accounting — review 2 finding 4, formerly P1.** [backend/services/profit_guard.py:546](/Users/michaelrickards/dev/bh2-AI1a/backend/services/profit_guard.py:546)
   Selecting `tts-1-hd` now records twice the `tts-1` character rate; `gpt-4o-mini-tts` and unknown models use the highest configured rate. All four accounting cases passed. **Optional hardening:** the token-priced model’s character estimate is not a proven upper bound. If audio usage varies for equal-length input, recorded estimates remain identical. Calibrate against observed usage before describing this estimate as reliably conservative.

4. **Resolved — review 2 finding 5, formerly P2.** [backend/services/ai_models.py:169](/Users/michaelrickards/dev/bh2-AI1a/backend/services/ai_models.py:169)
   Invalidation and conditional publication now share `_state`. Reproducing invalidation after the generation check leaves the cache invalidated after both threads finish; the loader no longer restores stale choices for another minute.

Verification: **20 selected tests passed**, additional in-memory reproductions passed, and `git diff --check HEAD~1` passed. Full checks and filesystem-backed regressions were not run under the read-only constraint. No files were modified; existing untracked `data.db` was untouched.