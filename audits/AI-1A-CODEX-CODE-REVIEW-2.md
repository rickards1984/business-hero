# AI-1a — Codex code review 2 (verbatim)

Model gpt-6-astra, read-only sandbox, 20 Nov 2026.

---

REQUEST CHANGES

1. **Partially resolved — P1 scan-error bypass remains.** [scripts/preflight.sh:198](/Users/michaelrickards/dev/bh2-AI1a/scripts/preflight.sh:198)
   Capturing the whole patch and using `grep -c` fixes the SIGPIPE failure. The 100,000-line regression exists at `backend/tests/test_harness_gates.py:440`; an in-memory reproduction caught the secret. Git failures correctly produce `UNREADABLE`. However, `|| true` also suppresses **grep errors**: I injected exit status 2 and the scan reported PASS. Distinguish “no match” from scanner failure.

2. **Resolved — original P1 binary-patch bypass.** [scripts/preflight.sh:194](/Users/michaelrickards/dev/bh2-AI1a/scripts/preflight.sh:194)
   Both diffs use `--text`, and all filters use `-a`. The NUL-containing regression exists at `backend/tests/test_harness_gates.py:448`. The extracted scan caught the equivalent binary payload. The original “Binary files differ” failure scenario is addressed, subject to item 1’s error handling.

3. **Resolved for the reviewed parameter failures — original P1.** [backend/services/ai_models.py:202](/Users/michaelrickards/dev/bh2-AI1a/backend/services/ai_models.py:202)
   Reasoning models receive `max_completion_tokens = max(4 × limit, 4000)` without temperature; `_usable()` excludes reasoning `-pro` choices at line 230. This agrees with GPT-5 Pro’s [Responses-only restriction](https://developers.openai.com/api/docs/models/gpt-5-pro).

   All requested sites are adapted: `app/email/service.py:407,499,559,628`, `support_api.py:148,666`, `openai_utils.py:36`, `services/briefing_generator.py:106,164`, `assistant_tools.py:2909`, and `assistant_chat.py:208`.

   The existing GPT-5 email briefing and two three-tone draft calls correctly gain limits of **4,800 / 4,800 / 4,000**, respectively. Prompts, parsing and fallbacks remain unchanged. This removes the rejected-parameter failure; it does increase potential output spend and does not guarantee complete output, because [reasoning consumes the same token allowance](https://developers.openai.com/api/docs/guides/token-counting). No live API calls were made.

4. **Partially resolved — P1 preview cost validation remains missing.** [backend/services/ai_models.py:81](/Users/michaelrickards/dev/bh2-AI1a/backend/services/ai_models.py:81)
   Realtime, transcription and `speak` are appropriately restricted. But `voice_preview` still accepts `tts-1-hd` and `gpt-4o-mini-tts`, while [profit_guard.py:541](/Users/michaelrickards/dev/bh2-AI1a/backend/services/profit_guard.py:541) charges every model at the fixed `tts-1` character rate. Selecting a more expensive preview model still under-records cost; the new test at `test_ai_models.py:177` explicitly accepts that selection without checking accounting.

5. **Partially resolved — P2 invalidation race remains.** [backend/services/ai_models.py:167](/Users/michaelrickards/dev/bh2-AI1a/backend/services/ai_models.py:167)
   `_loading` serializes loads, and the generation counter handles invalidation during `_read()`. Both regression tests cover those cases. However, `invalidate()` shares no lock with the generation check and publication. I paused a loader **after line 167**, invalidated, then resumed: it published the old choices with a fresh timestamp. The stale choice can still persist for another minute. Make invalidation and conditional publication atomic under a shared state lock.

6. **Partially resolved — P2 ordinary constants still evade the guard.** [backend/tests/test_ai_models.py:237](/Users/michaelrickards/dev/bh2-AI1a/backend/tests/test_ai_models.py:237)
   All 12 examples pass; spacing, multiline literals and comments are handled correctly. Constant discovery only examines module-level `ast.Assign`, however. Both reproduced examples return no findings:
   - `M: str = "gpt-5"` followed by `client.create(model=M)`.
   - A function-local `M = "gpt-5"` followed by that call.

   Routine annotations or moving a constant into a function therefore bypass the acceptance gate.

**Verification:** 20 selected tests passed. Full checks and filesystem-backed regression tests were not run under the read-only constraint. `git diff --check HEAD~1` reports trailing whitespace in the newly added review document. No files were modified; the existing untracked `data.db` was untouched.