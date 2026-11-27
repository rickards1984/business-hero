# HK-3 — Codex code review 1 (verbatim)

Model gpt-6-astra, read-only sandbox, 26 Nov 2026.

---

REQUEST CHANGES

1. **P1 — Blocking: an entirely retired environment chain is restored.** [backend/services/ai_models.py:374](/Users/michaelrickards/dev/bh2-HK3/backend/services/ai_models.py:374)
   With `QUOTE_AI_MODEL=gpt-5`, on 11 December `resolve("quote")` and `openai_model("quote")` still return `gpt-5`: `live or chain` restores the retired entry. Reproduced locally. Quote estimation therefore continues calling a shutdown model. Fall back to the unmodified, live task defaults when the override leaves nothing usable; ensure `openai_models()` cannot restore retired defaults either.

2. **P1 — Blocking: outreach environment overrides bypass retirement filtering.** [backend/services/ai_router.py:158](/Users/michaelrickards/dev/bh2-HK3/backend/services/ai_router.py:158)
   `chain()` filters saved choices through `choice()`, but only checks keys, prices and cooldown for `AI_MODELS_JSON` and legacy environment settings. Reproduced `ARIA_DRAFT_MODEL=gpt-5` remaining in the chain on 11 December. With only OpenAI configured, drafting fails; with other providers, it attempts the dead model before failing over. Apply retirement filtering to this path too. The built-in `DEFAULT_MODELS` themselves are clear of the targeted retirements.

3. **P2 — Blocking: GPT-5.4’s long-context cost is understated.** [backend/services/ai_costs.py:66](/Users/michaelrickards/dev/bh2-HK3/backend/services/ai_costs.py:66)
   The ordinary `197 / 1181` pence rates correctly represent $2.50 / $15, but the entry omits the surcharge above 272K input tokens: 2× input and 1.5× output. A 300K-input, 1K-output call records **60.281p instead of approximately 119.97p**, understating spend and cost-based reservations. Add the long-context tier. [OpenAI GPT-5.4 documentation](https://developers.openai.com/api/docs/models/gpt-5.4). GPT-6.2 Sol’s ordinary and long-context rates are correct; its comment claiming the latter are unpublished is stale. [OpenAI GPT-6.2 Sol documentation](https://developers.openai.com/api/docs/models/gpt-6.2-sol).

4. **P2 — Non-blocking: environment-selected models receive no admin warning.** [backend/services/ai_model_admin.py:123](/Users/michaelrickards/dev/bh2-HK3/backend/services/ai_model_admin.py:123)
   `retiring` examines only the saved database chain. With no saved choice and `EXECUTIVE_MEETING_AI_MODEL=gpt-5`, the effective model is retiring but the task row has no “Stops working … Change it” warning. Include the effective configuration when no saved choice exists.

5. **P1 — Non-blocking for the specified December/14 January scope; requires a follow-up: speech defaults also retire.** [backend/services/ai_models.py:114](/Users/michaelrickards/dev/bh2-HK3/backend/services/ai_models.py:114)
   `speak` uses `tts-1`; every `voice_preview` fallback is among `gpt-4o-mini-tts`, `tts-1-hd` and `tts-1`. OpenAI lists all three for **6 January 2027**, but `RETIRING` omits them. Speech and uncached voice previews will have no working model, without an advance warning. This needs a speech migration, beyond replacing the text defaults. [OpenAI deprecations](https://developers.openai.com/api/docs/deprecations).

6. **P2 — Non-blocking test gap: the fixed date masks untested shutdown paths.** [backend/tests/conftest.py:20](/Users/michaelrickards/dev/bh2-HK3/backend/tests/conftest.py:20)
   Freezing historical sample data is reasonable, but the suite stays before retirement unless a test explicitly advances the clock. Findings 1 and 2 survive while the retirement tests pass. Add boundary tests for single-entry environment overrides, outreach configuration and January retirements. The modified chat fixture also forces old GPT-5 choices, so its success does not establish the new default-chain behavior.

The Claude tool conversion, GPT-5.4 reasoning settings, text adapters and Opus reservation path appear compatible. Sonnet fallback costs are recorded using its own higher rates. The listed December/14 January snapshot IDs, fine-tune base extraction and retirement refusal messages check out.

Verification: **38 retirement tests and 12 selected adapter/budget tests passed**; both routing failures reproduced without network calls. Full `check.sh` was not run under the read-only constraint. No files changed.