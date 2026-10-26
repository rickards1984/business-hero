# OUT-19 part H — Codex review 1

- Commit reviewed: 1b1541b
- Model: gpt-6-astra · session 01a1726e-4454-7570-9a2d-214c98f4d29c · tokens used: 83,450
- Verdict: REQUEST CHANGES

## Prompt

```
You are the independent reviewer for OUT-19 part H in this repository (RED: AI spend and availability). Do not commit, push or modify files.
Read docs/OUT-19-TICKET.md (decision 6 and part H). Review commit 1b1541b (`git show 1b1541b`): backend/services/ai_router.py, its use in backend/services/outreach_research.py and backend/services/outreach_setup.py, backend/tests/test_ai_router.py and backend/tests/conftest.py.
Check:
1. Failover correctness: only provider errors fail over; invalid answers do not; the cooldown breaker (process-local) behaves; all-failed and none-configured paths; nothing is ever sent to a provider without a key or a priced model.
2. Cost accounting: every attempt noted/recorded exactly once (draft path via ai_costs.note inside collect; research via result["calls"] and the exception's calls); failed attempts at a conservative maximum; research's reservation (sum over the available chain) always covers the settled total so a normal failover never trips the overspend pause; context windows per model used for the maximum; unknown windows assumed large.
3. Provider adapters: the xAI base URL and OpenAI-compatible calls; Anthropic Messages API request (headers, version, web_search tool name/type, usage fields incl. server_tool_use.web_search_requests); error handling; timeouts; no SDK retries. Flag anything you believe is wrong for the current provider APIs.
4. Regressions: the removed provider check for injected test drafters in _ai_draft (now only for the real model drafters) — can production reach a drafter that bypasses the provider check? The test conftest resets breakers.
If pytest cannot run in your sandbox, read the tests and say so.
Verdict APPROVE or REQUEST CHANGES with numbered P1/P2/P3 findings.
```

## Review (verbatim)

**REQUEST CHANGES** — reviewed `1b1541b` against decision 6 and part H, serving North Star P7 and spend correctness.

1. **P1 — Cooldown expiry can introduce an unreserved provider.**  
   [ai_router.py:209](/Users/michaelrickards/dev/bh2-OUT-19/backend/services/ai_router.py:209) calculates the reservation from one chain; `web_search()` rebuilds it later. A provider whose cooldown expires between those steps becomes eligible without a reservation. I reproduced **66p reserved, 191p settled** with an OpenAI failure followed by Claude success. This triggers the overspend pause during ordinary failover. Freeze the eligible chain for reservation and execution, or reserve every provider execution could use.

2. **P1 — One context window is not a maximum for agentic research billing.**  
   [ai_router.py:198](/Users/michaelrickards/dev/bh2-OUT-19/backend/services/ai_router.py:198) budgets one context window of input, although server-side search can perform multiple inference iterations. xAI documents cumulative input usage across those iterations; Anthropic also charges search-result input across search iterations. Consequently, both failed-attempt estimates and reservations can be too small. The arbitrary two-million-token fallback does not establish a maximum either. Derive provider-specific bounds from enforced iteration/tool limits and test cumulative usage exceeding one window. [xAI usage documentation](https://docs.x.ai/developers/tools/tool-usage-details), [Anthropic search billing](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool).

3. **P2 — No available provider still consumes the brand’s research budget.**  
   [outreach_research.py:749](/Users/michaelrickards/dev/bh2-OUT-19/backend/services/outreach_research.py:749) substitutes the OpenAI maximum when the available chain is empty and commits that reservation. The exception path skips the AI ledger entry for `AllProvidersFailed`, but never refunds the research meter and still reports the reservation as spend. Missing keys or all providers cooling down can therefore exhaust the monthly budget without any call. Release unused reservations and settle exceptions against actual attempted calls.

4. **P2 — Anthropic search outages inside HTTP 200 responses never fail over.**  
   [ai_router.py:235](/Users/michaelrickards/dev/bh2-OUT-19/backend/services/ai_router.py:235) checks HTTP status, then ignores search-result error blocks. Anthropic explicitly returns HTTP 200 for tool errors including `too_many_requests` and `unavailable`. These currently become an empty/invalid answer rather than a provider failure, so a configured next provider is never tried. Recognise retryable tool failures while preserving usage and distinguishing them from invalid answers and exhausted `max_uses`. [Documented error format](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool#errors).

5. **P2 — Response decoding failures can lose attempt accounting and bypass failover.**  
   [ai_router.py:156](/Users/michaelrickards/dev/bh2-OUT-19/backend/services/ai_router.py:156) accesses `choices[0]` outside error handling; Anthropic JSON/body decoding similarly occurs outside it. I reproduced an empty provider `choices` envelope yielding **`IndexError`, zero recorded attempts**. Research can also lose accumulated attempt details and fall into the generic OpenAI attribution path. Normalise malformed provider envelopes into accounted provider failures; keep malformed *answer text* as a charged, non-failover result.

The ordinary paths otherwise look sound: keyed/priced filtering, process-local cooldown expiry, invalid-answer non-failover, draft collection/finally-save, and research attempt lists. Production API callers use the real default drafters; I found **no production injection path bypassing the provider check**. The shared conftest resets breakers before and after tests.

The xAI base URL is correct. Anthropic’s headers/version, `web_search_20250305` tool definition, `max_uses`, and `server_tool_use.web_search_requests` extraction match the documented interface. Explicit timeouts and disabled SDK retries are present.

**Verification:** 15 router tests passed; the database integration test could not set up because the read-only sandbox has no writable temporary directory. I read that test and ran additional in-memory reproductions. `check.sh` and real-provider smoke tests were not run. No files were modified, committed or pushed.
## Response

1. **P1 1 — taken.** The research reservation counts every keyed, priced provider, including ones cooling down. Test: `test_the_research_reservation_includes_providers_still_cooling_down`.
2. **P1 2 — escalated to Mike, who decided (25 Oct 2026, after the providers' current pricing pages were checked).**
   - **The theoretical maximum:** `max_search_pence` now counts every search pass over a whole context window at the model's highest rate. That is (searches + 1) × window × the higher-tier price + output + tools. It is no longer reserved. Reserving it would make a £20 brand budget unusable: about £15 per search on GPT-4.1 or GPT-6.1 Sol with 8 searches.
   - **Option B:**
     - Each attempt reserves a realistic `RESEARCH_SEARCH_RESERVE_PENCE` (default 75p) per provider it might try.
     - An overrun is recorded, and the brand stops at its next reservation once its budget is used.
     - Only a cost above the theoretical maximum of the whole chain (`impossible_pence`) pauses the brand.
   - **Models (Mike):**
     - GPT-6.1 Sol for research and drafts;
     - Grok 4.20 reasoning as fallback (tiered prices modelled: double above 200k tokens);
     - GPT-6 Luna for reply sorting;
     - at most 4 searches per call.
   - **Prices:** checked on OpenAI's and xAI's pricing pages; Anthropic's are still an estimate.
   - **Request parameter:** OpenAI's reasoning models now get `max_completion_tokens`, which they require; xAI keeps `max_tokens`.
   - **Tests:** `test_ai_models_b.py`. The earlier reservation tests were moved to the new rule with the same intent.
3. **P2 3 — taken.**
   - With no provider available, nothing is reserved or spent; research stops with "no AI provider is available".
   - Exceptions settle against the attempts actually made: a router failure with calls charges those calls, one without any calls charges nothing, and an unknown failure keeps the reserve.
   - Tests cover each case.
4. **P2 4 — taken.**
   - Anthropic `web_search_tool_result_error` blocks with `too_many_requests` or `unavailable` inside a 200 reply raise ProviderError, with the reported usage and search count, so the failure is charged at its real cost.
   - `max_uses_exceeded` is an answer, not a failover.
   - Tests cover both.
5. **P2 5 — taken.**
   - Malformed envelopes (empty `choices`, undecodable bodies, unreadable output) are ProviderErrors that carry any usage reported. They fail over and are charged at the reported usage, or estimated.
   - Malformed answer text stays a charged, non-failover result.
   - Tests cover each.
