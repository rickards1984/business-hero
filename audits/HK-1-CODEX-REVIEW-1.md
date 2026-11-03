# HK-1 Codex review 1

Model gpt-6-astra · session 01a19eb0-8d14-79d3-b85f-4d902a7e8604 · 61,665 tokens · verdict **CHANGES REQUIRED**

## Prompt

```
Read-only review of ticket HK-1 in this worktree, branch ticket/HK-1-housekeeping: `git diff origin/main...HEAD`, described in docs/HK-1-TICKET.md. Four fixes:
1. services/backend_main.backend_main() replaces `from main import` in invoice_chase_helper and profit_guard.send_alert (production loads backend/main.py as "backend_main" via the root main.py shim). Is the resolver correct and safe (sys.modules iteration, path comparison, fallback), and are there other ways code reaches main.py by name that would also break in production (importlib, getattr on sys.modules['main'], etc.)?
2. realtime_voice.py: the final accrual now uses loop.run_in_executor with a copied context instead of ensure_future(to_thread(...)). Check it preserves every teardown property the voice tests and reviews established (cancellation, bounded waits, add_done_callback logging, _bounded on a Future, no double accrual) and that the test-wait change is harmless.
3. scripts/preflight.sh TRAP 4: exact backend/models.py or an added `table=True` line in backend Python. Any false negative/positive, quoting/glob problems, behaviour on diff error?
4. Light-mode skeleton tokens in frontend/client/src/styles/design-system.css: correct in both themes (how is dark mode applied — .dark class on which element?), any layout regression from display:block on the spans in DashboardPage.tsx.
Output: APPROVE or CHANGES REQUIRED; P1/P2 with file:line and a concrete failure. Do not edit, commit or push.
```

## Final message (verbatim)

**CHANGES REQUIRED**

- **P1 — Production resolver still returns the root shim.** [backend/services/backend_main.py:21](/Users/michaelrickards/dev/bh2-HK-1/backend/services/backend_main.py:21). The root [main.py:18](/Users/michaelrickards/dev/bh2-HK-1/main.py:18) creates and executes `backend_main` without registering it in `sys.modules`. The scan therefore misses it, and the fallback returns the shim. Both callers still fail with missing attributes. Reproduced using the actual shim with a stub backend loader. The new test masks this by explicitly registering the module. Resolve the shim’s backend module or register it during loading, and test the actual loading pattern.

- **P2 — TRAP 4 can report PASS despite a matching table addition or a failed diff.** [scripts/preflight.sh:141](/Users/michaelrickards/dev/bh2-HK-1/scripts/preflight.sh:141). With `pipefail`, `grep -q` can exit after finding a match while a large diff is still being written; the producer receives SIGPIPE, making the condition false. Separately, a failed patch diff also leaves `MODELS_CHANGED=0`; the earlier name-only diff does not verify this second command. Reproduced both outcomes against the extracted condition. Capture and check the diff’s status separately, then scan without an early-closing pipeline.

Other checks:

- No additional production imports or dynamic lookups of `main` by name found. Snapshot iteration and resolved-path comparison are otherwise appropriate.
- Voice teardown retains cancellation shielding, bounded closes, callback logging and single accrual. `ensure_future` accepts a Future; the longer polling timeout does not weaken assertions.
- Dark mode applies `.dark` to `<html>`. Tokens resolve correctly in both themes. Dashboard tile spans are already flex items; `display:block` introduces no identified layout regression.
- The quoted Git pathspec includes nested backend Python files. The regex remains textual: comments/string literals can trigger it, and split-line assignments can evade it.

**Validation:** 48 voice/resolver tests passed; `git diff --check` passed. Full `check.sh` and browser visual verification were not run. No edits, commits or pushes.