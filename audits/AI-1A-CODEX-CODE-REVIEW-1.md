# AI-1a — Codex code review 1 (verbatim)

Branch ticket/AI-1a-switchboard (d1ca27f..). Model gpt-6-astra, read-only sandbox, 20 Nov 2026.

---

REQUEST CHANGES

1. **P1 — Secret detection can discard a positive match.** [scripts/preflight.sh:189](/Users/michaelrickards/dev/bh2-AI1a/scripts/preflight.sh:189)  
   With `pipefail`, `grep -q` exits after finding a secret, causing upstream processes to receive SIGPIPE on sufficiently large patches. The pipeline then fails, so `&& printf` never records the offending file. Reproduced with a synthetic key followed by 100,000 added lines: status **141**, versus **0** for a small patch. Consume the complete input and distinguish scan errors from clean results.

2. **P1 — Binary patches bypass the revised secret scan.** [scripts/preflight.sh:189](/Users/michaelrickards/dev/bh2-AI1a/scripts/preflight.sh:189)  
   A newly committed file containing a key and a NUL byte produces Git’s “Binary files … differ” output, with no added content lines. TRAP 5 therefore passes it; the previous whole-file grep could detect that key. Scan binary blobs explicitly or force text extraction, and fail closed when content cannot be inspected.

3. **P1 — Priced text choices can break their receiving call sites.** [backend/services/ai_models.py:168](/Users/michaelrickards/dev/bh2-AI1a/backend/services/ai_models.py:168)  
   Saving `openai/gpt-5` for `support`, `briefing`, or `inbox_classify` passes validation. Those callers still send `temperature` and `max_tokens`, which GPT-5 rejects—for example [support_api.py:149](/Users/michaelrickards/dev/bh2-AI1a/backend/support_api.py:149). A valid saved choice therefore disables working functionality. Validate task compatibility or adapt request parameters before accepting these choices.

4. **P1 — Voice choices have neither capability nor model-specific cost validation.** [backend/services/ai_models.py:173](/Users/michaelrickards/dev/bh2-AI1a/backend/services/ai_models.py:173)  
   Any nonempty OpenAI model is accepted for realtime, transcription, and speech. I confirmed that `voice_aria → gpt-5` is accepted; it then reaches a realtime endpoint it cannot serve. Separately, speech choices retain the fixed `TTS_PENCE_PER_1K_CHARS` accounting regardless of selected model, so a more expensive choice does not increase recorded costs. Skipping token pricing needs an explicit compatible-model list and supported alternative pricing.

5. **P2 — An in-flight refresh can undo invalidation.** [backend/services/ai_models.py:164](/Users/michaelrickards/dev/bh2-AI1a/backend/services/ai_models.py:164)  
   A refresh can read the old choice, pause, then publish it after a change calls `invalidate()`, marking the stale result fresh for another minute. Reproduced without a database. Synchronous `_load()` calls also bypass `_refreshing`, allowing older reads to overwrite newer ones. Serialize refreshes and use an invalidation generation to reject obsolete results.

6. **P2 — The hard-coded-model guard misses ordinary Python syntax.** [backend/tests/test_ai_models.py:218](/Users/michaelrickards/dev/bh2-AI1a/backend/tests/test_ai_models.py:218)  
   `create(model = "gpt-5")`, multiline arguments, and a model constant passed into `create()` evade the regex. Conversely, a comment containing `model="example"` is flagged. These cases were reproduced. Use syntax-aware checks with regression examples so routine formatting cannot bypass the acceptance gate.

Five selected tests passed, and `git diff --check` passed. Full checks and PostgreSQL tests were not run under the read-only constraint. No files were modified.