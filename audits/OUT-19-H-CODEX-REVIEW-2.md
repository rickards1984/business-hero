# OUT-19 part H — Codex review 2

- Commits reviewed: 33c60db, 130a4cd
- Model: gpt-6-astra · session 01a17324-3dfe-7b22-8a35-2e00176dce69 · tokens used: 78,451
- Verdict: REQUEST CHANGES

## Prompt

```
You are the independent reviewer for OUT-19 part H, cycle 2 (RED: AI spend and availability). Do not commit, push or modify files.
Review 1 and the builder's response (including Mike's decision on finding 2: option B) are in audits/OUT-19-H-CODEX-REVIEW-1.md; the decisions are in docs/OUT-19-TICKET.md part H. Review the two commits since 1b1541b (`git log --oneline 1b1541b..HEAD`, `git diff 1b1541b..HEAD`).
Check: findings 1, 3, 4, 5 are resolved; finding 2 is implemented as Mike decided (realistic per-attempt reserve, overrun recorded and the brand stopping naturally at its next reservation, pause only above the theoretical maximum of the chain); the tiered price support (ai_costs.price/price_max/cost, validation of 3- or 6-number entries); the new default models and prices against the providers' published pages if you can check them; max_completion_tokens for OpenAI reasoning models vs max_tokens for xAI; and that the existing tests were changed only to the new decision, not weakened.
If pytest cannot run in your sandbox, read the tests and say so.
Verdict APPROVE or REQUEST CHANGES with numbered P1/P2/P3 findings.
```

## Review (verbatim)

**REQUEST CHANGES** — reviewed `33c60db` and `130a4cd` against Mike’s option B decision, North Star P7 and spend correctness.

1. **P1 — OpenAI long-context prices are missing.**  
   [ai_costs.py:52](/Users/michaelrickards/dev/bh2-OUT-19/backend/services/ai_costs.py:52) prices Sol and Luna at their base rates for every context length. Both providers’ model pages specify **2× input and 1.5× output above 272K input tokens**. This undercounts spend and understates the theoretical maximum. For example, Sol’s 300K input/1K output costs approximately **95.67p**, whereas the code returns **47.887p**. Add the tiers and boundary tests. Sources: [Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol), [Luna](https://developers.openai.com/api/docs/models/gpt-6-luna).

2. **P2 — Finding 5 is only partly resolved.**  
   [ai_router.py:308](/Users/michaelrickards/dev/bh2-OUT-19/backend/services/ai_router.py:308) discards already-parsed Anthropic usage when content decoding fails; the chat adapter does likewise. I reproduced a malformed text block with **500K reported input tokens and two searches** becoming `ProviderError(usage=None, searches=0)`, so research charges the 75p estimate instead. Also, [line 278](/Users/michaelrickards/dev/bh2-OUT-19/backend/services/ai_router.py:278) accepts a missing Responses envelope as empty answer text, preventing failover. Preserve parsed usage/search counts and validate envelope structure separately from answer validity.

3. **P2 — All-failed searches bypass the impossible-cost pause.**  
   [outreach_research.py:803](/Users/michaelrickards/dev/bh2-OUT-19/backend/services/outreach_research.py:803) settles exception attempts and exits before the `cost > impossible` check. A chain whose reported failed-attempt costs exceed the theoretical maximum therefore leaves the brand enabled. Apply the same pause rule to both settlement paths and test an `_AllFailedWithCost` above the threshold.

4. **P2 — Luna reply sorting is configured but never used.**  
   The new `classify` router default has no production caller. [chase_replies.py:457](/Users/michaelrickards/dev/bh2-OUT-19/backend/services/chase_replies.py:457), used by production automations, still defaults to `gpt-4o-mini` through its direct client. The new test checks only the configuration dictionary. Wire the production classification path to the approved model and test that path.

5. **P2 — `price_max()` does not guarantee the highest accepted rate.**  
   [ai_costs.py:119](/Users/michaelrickards/dev/bh2-OUT-19/backend/services/ai_costs.py:119) always selects the second tier, while validation accepts descending tiers. I reproduced an accepted `[100,200,0,200000,50,100]` returning maximum rates `(50,100,0)`. Either reject descending tiers or calculate component-wise maxima; add validation tests for six-number entries.

Prior findings **1, 3 and 4 are resolved**. Ordinary successful-search overruns follow option B, including stopping at the next reservation. Existing test changes preserve their original intent under the new decision; I found no unrelated weakening.

The published [xAI prices](https://docs.x.ai/developers/pricing) match the Grok entries approximately at the stated exchange rate. The router correctly sends `max_completion_tokens` to OpenAI and `max_tokens` to xAI.

**Verification:** 59 tests passed; 158 encountered fixture setup errors because the sandbox has no writable temporary directory. I inspected the changed tests and ran additional in-memory reproductions. `check.sh` and live-provider smoke tests were not run. No files were modified, committed or pushed.
## Response

Each new test was run against 130a4cd's services and fails there (10 of 10).

1. **P1 1 — taken.**
   - GPT-6.1 Sol and GPT-6 Luna carry their long-context tier: 2× input and 1.5× output above 272k input tokens.
   - Tests check the 271,999 / 300,000 boundary for both and `price_max`.
2. **P2 2 — taken.**
   - Anthropic bodies are decoded, and their usage and search count read, before the content is parsed. A malformed content block raises ProviderError carrying that usage, so it is charged at what was reported.
   - A Responses reply without its `output` list is a ProviderError, not an empty answer.
   - Tests cover both.
3. **P2 3 — taken.** One `_pause_impossible` helper serves both settlement paths. Test: an `_AllFailedWithCost` above the line pauses the brand.
4. **P2 4 — taken.**
   - `chase_replies.classify_with_model`, the production reply reader, now calls `ai_router.json_chat(purpose="classify")`: GPT-6 Luna first, then Grok 4.20 non-reasoning on failure.
   - The reply text is sent as it is (json_chat accepts text). `ARIA_REPLY_MODEL` still chooses OpenAI's model.
   - Tests exercise that path, including failover.
5. **P2 5 — taken.**
   - Six-number entries must start their higher tier above zero and never be cheaper than the base tier, or the whole setting is ignored.
   - `price_max` takes component-wise maxima.
   - Tests cover three bad entries.

**Test updates:** `test_research_reserves_from_the_one_price_table` now doubles every tier of the six-number entry. That is the test's intent; a three-number override would drop the long-context tier.
