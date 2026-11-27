# HK-3 — Codex code review 2 (verbatim)

Model gpt-6-astra, read-only sandbox, 26 Nov 2026.

---

APPROVE

1. **Review 1 finding 1 — P1, fixed; no remaining blocker.** [ai_models.py:376](/Users/michaelrickards/dev/bh2-HK3/backend/services/ai_models.py:376) preserves the order: usable saved choice → environment-adjusted defaults → live built-in defaults. The new quote test proves `QUOTE_AI_MODEL=gpt-5` falls back to GPT-5.4. Existing meeting coverage proves surviving fallbacks retain priority. The claim that retired defaults are *never* restored remains too broad: lines 389 and 396 retain them when no live alternative exists, notably speech after its deadline.

2. **Review 1 finding 2 — P1, fixed; no remaining blocker.** [ai_router.py:158](/Users/michaelrickards/dev/bh2-HK3/backend/services/ai_router.py:158) swaps retired environment selections for the same provider’s built-in model, preserving provider order, pricing checks, keys and cooldowns. The legacy-override test proves its case; independent probes also passed for JSON-only configuration, missing keys and `include_down`.

3. **Review 1 finding 3 — P2, fixed; non-blocking.** [ai_costs.py:67](/Users/michaelrickards/dev/bh2-HK3/backend/services/ai_costs.py:67) supplies the long-context tier to both actual costing and maximum-price reservations. The new test proves 300K input/1K output costs **119.972p**. It does not test the exact threshold; the existing shared calculator uses `>= 272000`, despite the comment saying “above”.

4. **Review 1 finding 4 — P2, partially fixed; non-blocking.** [ai_model_admin.py:129](/Users/michaelrickards/dev/bh2-HK3/backend/services/ai_model_admin.py:129) now warns for the meeting environment override and unsaved speech defaults; the new test proves both. **Outreach overrides still receive no warning:** with no saved choice and `ARIA_DRAFT_MODEL=gpt-5`, the router selects GPT-5 before retirement, but the admin row reports `retiring=[]`. `ai_models.default()` does not read outreach’s separate configuration.

5. **Review 1 finding 5 — P1 follow-up, non-blocking for HK-3.** [ai_models.py:292](/Users/michaelrickards/dev/bh2-HK3/backend/services/ai_models.py:292) records the speech deadlines; migration remains **VOICE-MIG**. Direct checks confirmed no premature refusal or removal, including saved choices and preview fallback order. On the deadline, validation refuses those models, but resolution retains the old chain when everything has retired. Consequently, these warnings do not replace the required migration. No pre-deadline voice regression found.

6. **Review 1 finding 6 — P2, partially addressed; non-blocking.** [test_hk3_model_retirement.py:185](/Users/michaelrickards/dev/bh2-HK3/backend/tests/test_hk3_model_retirement.py:185) sets JSON while `ARIA_DRAFT_MODEL=gpt-5` still overrides it, so its `o3` assertion does not exercise JSON retirement filtering. January additions verify date metadata, not routing boundaries. Independent January and speech boundary probes passed, but those checks should become persistent regression tests.

7. **New observation — P3, non-blocking: repeated error logging.** [ai_models.py:386](/Users/michaelrickards/dev/bh2-HK3/backend/services/ai_models.py:386) and [ai_router.py:162](/Users/michaelrickards/dev/bh2-HK3/backend/services/ai_router.py:162) log on every resolution, without deduplication. Three quote resolutions produced three errors; outreach logs even for missing-key or cooling-down providers. Rate-limit these configuration warnings.

Verification: **47 retirement tests and 12 router tests passed**; both database-backed retirement tests also passed when invoked with in-memory SQLite. Additional routing and speech probes passed. Full `check.sh` and live-provider/UI checks were not run under the read-only constraint. No files changed.