# AI-1b — Codex code review 1 (verbatim)

Commit 8682c2a. Model gpt-6-astra, read-only sandbox, 21 Nov 2026.

---

REQUEST CHANGES

1. **HIGH — Escalation bypasses the allowance guard.** [backend/assistant_chat.py:865](/Users/michaelrickards/dev/bh2-AI1b/backend/assistant_chat.py:865)
   An ordinary message that requires three tool rounds switches to `chat_complex` without calling `permits()`. The final response path at line 926 also bypasses it. I reproduced three everyday-model rounds followed by the expensive model while the guard returned `False`; the guard was never called and no fallback note appeared. Check permission before every complex round, including escalation and finalisation.

2. **HIGH — The promised business allowance is not enforced.** [backend/assistant_chat.py:847](/Users/michaelrickards/dev/bh2-AI1b/backend/assistant_chat.py:847)
   `permits("chat_complex")` accepts the purpose as non-essential, but checks **platform-wide** spending and profitability; it receives no business identifier. A business can repeatedly use “Think harder” after exhausting its own allowance while platform spending remains below the threshold. Conversely, another business’s spending—or a guard database failure—produces a misleading “this month’s allowance … nearly used” message. Implement the tenant allowance required by M7 and distinguish its fallback reason from platform suspension.

3. **HIGH — A request-level 400 disables the provider for everyone and records invented spending.** [backend/services/ai_chat.py:229](/Users/michaelrickards/dev/bh2-AI1b/backend/services/ai_chat.py:229)
   Both adapters turn request errors into undifferentiated `ProviderError`s; `turn()` then records maximum estimated usage and trips the shared provider breaker. One oversized conversation can disable OpenAI for all businesses and router tasks for the default five minutes. With the default OpenAI-only chat chain, unrelated chats then fail immediately. My mocked 400 reproduced both the global cooldown and an 8,192-output-token charge. Preserve error classification; request rejection must not trip an outage breaker. This also regresses PROFIT-1’s explicit exclusion of unbilled 400s.

4. **MEDIUM — Truncated Anthropic tool calls are treated as executable instructions.** [backend/services/ai_chat.py:192](/Users/michaelrickards/dev/bh2-AI1b/backend/services/ai_chat.py:192)
   `stop_reason` is discarded. A `max_tokens` response containing an incomplete `tool_use` is converted into a normal call, with missing input replaced by `{}`, and dispatched by the chat loop. Truncated text is likewise presented as complete. I reproduced the incomplete-call conversion. Preserve termination information and handle truncation before executing tools; Anthropic explicitly requires retrying incomplete tool-use responses with a larger limit. [Anthropic stop-reason documentation](https://platform.claude.com/docs/en/build-with-claude/handling-stop-reasons#incomplete-tool-use-blocks)

5. **MEDIUM — Failure estimates are not bounded by the actual OpenAI request.** [backend/services/ai_chat.py:117](/Users/michaelrickards/dev/bh2-AI1b/backend/services/ai_chat.py:117)
   `chat_params(model)` receives no token limit, so the OpenAI request contains neither output-limit parameter. Nevertheless, failures are estimated at 8,192 output tokens. A reasoning request can consume more before timing out, understating spend. The input estimate also omits assistant tool-call arguments. Set an explicit model-appropriate limit and derive estimates from the complete request. Additionally, `_tokens()` at line 213 treats missing output usage as an exact zero instead of an estimate.

6. **MEDIUM — Empty assistant replies poison subsequent Anthropic requests.** [backend/services/ai_chat.py:171](/Users/michaelrickards/dev/bh2-AI1b/backend/services/ai_chat.py:171)
   An empty response without tools becomes `""`, is saved by the chat loop, and is later translated into an empty assistant message. This is reachable after an Anthropic empty `end_turn` response, which Anthropic documents as possible after tool results. Subsequent requests can fail validation with empty-content errors, then trigger finding 3. Handle empty responses and omit invalid empty history entries. [Anthropic empty-response guidance](https://platform.claude.com/docs/en/build-with-claude/handling-stop-reasons#empty-responses-with-end-turn)

7. **MEDIUM — Chat still requires an OpenAI key even when another provider is selected.** [backend/assistant_chat.py:820](/Users/michaelrickards/dev/bh2-AI1b/backend/assistant_chat.py:820)
   The retained `OPENAI_API_KEY` check returns 500 before reaching the new router. An installation configured with valid Anthropic/xAI choices and credentials cannot chat without an unrelated OpenAI key. Let the resolved provider chain determine availability.

8. **MEDIUM — Routing misses ordinary financial questions and over-escalates support questions.** [backend/services/ai_chat.py:38](/Users/michaelrickards/dev/bh2-AI1b/backend/services/ai_chat.py:38)
   Verified examples: “How much did we make this month?” and “Can we afford another employee?” select `chat`; “Change my account name” and “Why is the button grey?” select `chat_complex`. Financial follow-ups such as “What about last month?” also lose their financial context because history influences only length. Add representative financial paraphrases, contextual follow-ups and ordinary support negatives to the routing tests.

The basic system/tool-schema translation, string tool results and tool IDs look sound. Consecutive same-role messages are supported by Anthropic, and extra history keys are stripped. [Messages API reference](https://platform.claude.com/docs/en/api/messages/create) Failover does not mechanically replay executed tools; however, preserved results alone cannot guarantee that a fallback model never requests the same operation again. Admin caption filtering is enforced server-side. Provider calls and recording run in a worker thread; existing synchronous tool execution still blocks the event loop.

**Verification:** all 32 AI-1b tests passed. The other three requested test files produced 91 passes and 64 setup errors because temporary databases cannot be created in this read-only environment. The new tests mock recording and allowance decisions, omit stop reasons, and do not exercise the failures above. No files were modified; `check.sh` and live-provider validation were not run.