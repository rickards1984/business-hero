# HK-2 — Codex code review 1 (verbatim)

Model gpt-6-astra, read-only sandbox, 22 Nov 2026.

---

APPROVE

1. **Informational — non-blocking: diagnosis is correct.** [ai_models.py:236](/Users/michaelrickards/dev/bh2-HK2/backend/services/ai_models.py:236), [ai_chat.py:324](/Users/michaelrickards/dev/bh2-HK2/backend/services/ai_chat.py:324). Previously, selecting GPT-6 for a briefing sent `max_tokens` and the caller’s temperature; ordinary chat also sent `max_tokens`. Outreach already used `max_completion_tokens` without temperature. HK-2 fixes that mismatch. The ticket slightly overstates “plain fallback every time”: another configured model can answer first.

2. **Medium — non-blocking, existing compatibility limitation: GPT-6 tool support remains incomplete.** [executive_meeting_orchestrator.py:477](/Users/michaelrickards/dev/bh2-HK2/backend/services/executive_meeting_orchestrator.py:477). GPT-6 starts with `low`; `_tools_need_no_reasoning` recognises only GPT-5.x until a refusal is learned. Luna can recover through BM-5’s retry with `none`. GPT-6.1 Sol cannot: its function calls require Responses, and it rejects `none`. A meeting offering ledger tools can therefore still fail over. Ordinary chat/eval has no BM-5 retry, so Luna’s tool requests also remain problematic. These already failed before HK-2; they do not invalidate this parameter hotfix. [Official OpenAI documentation](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-6-astra).

3. **Low — non-blocking: regression tests prove the narrow fix, not all downstream behaviour.** [test_hk2_gpt6_settings.py:30](/Users/michaelrickards/dev/bh2-HK2/backend/tests/test_hk2_gpt6_settings.py:30), [test_hk2_gpt6_settings.py:59](/Users/michaelrickards/dev/bh2-HK2/backend/tests/test_hk2_gpt6_settings.py:59). The adapter fake rejects forbidden parameters, but permits a missing completion limit; the meeting test passes `tools_offered=False`. Thus broken headroom, GPT-6 tool retries, or `-pro` skipping could escape these tests. Add exact-limit assertions and GPT-6 cases for those branches.

4. **Informational — non-blocking: headroom and cost estimates remain aligned.** [ai_text.py:55](/Users/michaelrickards/dev/bh2-HK2/backend/services/ai_text.py:55), [ai_chat.py:448](/Users/michaelrickards/dev/bh2-HK2/backend/services/ai_chat.py:448). GPT-6 now receives `max(4 × requested, 4000)`; meetings receive requested + 2000. Chat’s limit rises from 8192 to 32768. Worst-case estimates, reservations and eval admission follow those limits, so a near-budget request may now be refused earlier—correctly. In-memory assertions confirmed agreement.

5. **Low — non-blocking, previously documented: eval’s current-model validation gap also applies to GPT-6 `-pro`.** [ai_model_admin.py:223](/Users/michaelrickards/dev/bh2-HK2/backend/services/ai_model_admin.py:223). Saved choices and candidate validation now exclude GPT-6 `-pro`; `ai_text` and the meeting override skip it. However, an environment-selected current `-pro` model can still reach “Test this model” and fail its Chat Completions calls. This is the existing follow-up recorded immediately above HK-2.

No classification regression found for GPT-4o, GPT-4.1, GPT-5.x, o-series, fine-tunes, `-chat`, or the existing realtime/TTS models.

Verification: **27/27 HK-2 tests passed**; broader selection: **262 passed, 63 setup errors** from prohibited temporary-file creation. Full `check.sh` was not run in this read-only review. No files changed, committed or pushed.