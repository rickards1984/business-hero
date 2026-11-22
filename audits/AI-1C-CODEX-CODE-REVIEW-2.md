# AI-1c — Codex code review 2 (verbatim)

Model gpt-6-astra, read-only sandbox, 22 Nov 2026.

---

REQUEST CHANGES

Numbering follows review 1.

1. **Medium — Partially fixed: saved fallback chains still misrepresent runtime behaviour.** [ai_models.py:284](/Users/michaelrickards/dev/bh2-AI1c/backend/services/ai_models.py:284). The new provider/chain restrictions match the inspected call sites, but `choice()` never applies `max_chain`. A previously saved support chain `[gpt-4o, gpt-4o-mini]` still appears as effective; `chat_request()` uses only `gpt-4o`, with no fallback on failure. Reproduced in memory. Tests cover new writes only; the “call-site” test calls `chat_request()` directly and never uses its `site` parameter.

2. **High — Partially fixed: eval admission remains vulnerable to concurrency and changing spend.** [ai_eval.py:148](/Users/michaelrickards/dev/bh2-AI1c/backend/services/ai_eval.py:148), [ai_eval.py:155](/Users/michaelrickards/dev/bh2-AI1c/backend/services/ai_eval.py:155).

   The hourly list is read and replaced outside the lock. A deterministic two-thread probe reproduced a refused request overwriting the tenth admission’s timestamp, allowing an eleventh run. Tests exercise sequential refusals, not concurrent access.

   `permits("eval")` correctly checks both spending guards and fails closed, but it checks recorded spending only, once before admission. If the first paid case crosses the kill threshold, the remaining cases still execute; the £3 cap does not reserve available budget. Tests stub `permits` and do not cover this transition.

   **No ordinary refusal-after-acquire slot leak found:** refusal branches precede acquisition, and the caller releases successful admissions in `finally`.

3. **Original Medium — Fixed for the reported repeated-timeout scenario; tests provide partial proof.** [ai_eval.py:179](/Users/michaelrickards/dev/bh2-AI1c/backend/services/ai_eval.py:179), [ai_model_admin.py:227](/Users/michaelrickards/dev/bh2-AI1c/backend/services/ai_model_admin.py:227). Both models share a deadline; later cases are skipped and the slot is released. The test demonstrates those behaviours. It does **not** establish a strict 150-second wall-clock limit: a call starting just before expiry still receives the full 25-second timeout.

4. **High — Partially fixed: grounding still passes unsafe replies; argument validation introduces a crash.** [ai_eval.py:55](/Users/michaelrickards/dev/bh2-AI1c/backend/services/ai_eval.py:55), [ai_eval.py:82](/Users/michaelrickards/dev/bh2-AI1c/backend/services/ai_eval.py:82).

   The original four examples are rejected and covered. However, `{}` passes the overdue lookup because `args.get(k, v)` supplies the expected value when absent. A correct tool call accompanied by “You are owed £91,250” also passes. The total check accepts swapped customer balances: “£1,250 total; Harbour £500; Northgate £750.” These were reproduced; tests omit them.

   Additionally, valid JSON arguments `[]` or `null` raise `AttributeError`, aborting the evaluation before that paid call is recorded. Validate the argument object before accessing it.

   **No false positives reproduced** for dates, `INV-101`, comma punctuation, or `£1,250.00` in grounded answers; those cases lack regression coverage.

5. **Medium — Partially fixed: ledger mappings remain incomplete or wrong.** [ai_models.py:76](/Users/michaelrickards/dev/bh2-AI1c/backend/services/ai_models.py:76), [ai_models.py:101](/Users/michaelrickards/dev/bh2-AI1c/backend/services/ai_models.py:101).

   `reply_draft` omits `draft`, although `app/email/router.py:1401` attributes it there. `email_briefing` omits `briefing`, despite attribution at `app/email/router.py:1173`. Their spending therefore appears under other cards without the corresponding shared-task labels. `wording` lists `wording`, but accountancy-pack generation records `accountancy_pack` at `services/accountancy_pack.py:595`, leaving the wording card at £0. Tests only verify synthetic chat meters and one sharing label.

Verification: **54 admin tests passed using an in-memory SQLite fixture substituted at runtime** because the original fixture requires forbidden temporary-file writes. **Eight PostgreSQL tests skipped**; they do not prove these fixes. No files modified, committed, or pushed.