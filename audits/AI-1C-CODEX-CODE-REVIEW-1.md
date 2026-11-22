# AI-1c — Codex code review 1 (verbatim)

Model gpt-6-astra, read-only sandbox, 22 Nov 2026.

---

REQUEST CHANGES

1. **High — Choices can disagree with the model actually used.** [ai_models.py:234](/Users/michaelrickards/dev/bh2-AI1c/backend/services/ai_models.py:234). Validation accepts Anthropic/xAI for tasks still using `chat_request()` and OpenAI-only clients. Reproduced: saving `support → anthropic/claude-opus-5-5` succeeds and advertises Claude as effective, but the support call uses `gpt-4o`. Those call sites also ignore additional OpenAI fallbacks despite the editor promising failover. Restrict choices and fallback controls to each task’s implemented capabilities until AI-1d. Tests need to compare accepted choices with actual call-site requests.

2. **High — Paid evaluations bypass the spending guard.** [ai_eval.py:99](/Users/michaelrickards/dev/bh2-AI1c/backend/services/ai_eval.py:99), [admin_ai_api.py:59](/Users/michaelrickards/dev/bh2-AI1c/backend/admin_ai_api.py:59). Each request directly invokes ten paid adapter calls without checking `profit_guard.permits("eval")`, reserving a budget, or limiting concurrent/repeated runs. OpenAI’s adapter uses `accounted()`, which bypasses the SDK guard too. An admin can keep spending after the platform kill threshold, including through simultaneous tabs. Token limits bound individual calls, not aggregate spending. Add server-side admission controls and tests proving paused/exhausted evaluations make zero provider calls.

3. **Medium — One test request can occupy a worker for roughly ten minutes.** [ai_model_admin.py:208](/Users/michaelrickards/dev/bh2-AI1c/backend/services/ai_model_admin.py:208), [ai_eval.py:95](/Users/michaelrickards/dev/bh2-AI1c/backend/services/ai_eval.py:95). Candidate and current run sequentially, each with five separate 60-second calls. When both providers time out, processing continues through all ten cases without an overall deadline. A disconnected browser can leave this work running; retries add more work and spending. Use a bounded overall deadline or a deduplicated background job with progress/results.

4. **High — Grounding checks pass demonstrably unsafe answers.** [ai_eval.py:38](/Users/michaelrickards/dev/bh2-AI1c/backend/services/ai_eval.py:38), [ai_eval.py:50](/Users/michaelrickards/dev/bh2-AI1c/backend/services/ai_eval.py:50). Reproduced passing results for:
   - “Charge £4,500” accompanied by any tool call.
   - “Charge 4500 GBP” without tools.
   - An empty answer.
   - “You are owed £91,250, not £1,250.”

   The price check exempts tool-bearing replies; the total check merely searches for a substring. These can endorse a model that violates P2. Validate grounded amounts and tool arguments, reject empty/truncated answers, and add adversarial regression cases. Existing scripted tests miss these false positives.

5. **Medium — Spend cards attribute costs to the wrong tasks.** [ai_model_admin.py:54](/Users/michaelrickards/dev/bh2-AI1c/backend/services/ai_model_admin.py:54). The query assumes meter purposes equal switchboard task names. Actual inbox classification records `classify`, email briefing records `briefing`, and support chat records `chat`. Consequently, inbox/support cards can show £0 while their costs inflate outreach/chat cards. Existing tests insert idealised meter names rather than exercising real attribution. Align ledger attribution with task identity or explicitly represent the aggregation; historical shared purposes cannot reliably be split.

Authorization dependencies and provider-error sanitisation looked sound. Read-only, in-memory probes confirmed the routing/check failures and SQLite LIKE escaping across both meter tables. Full tests, PostgreSQL execution, and browser behaviour were not run in this read-only session. No files were modified.