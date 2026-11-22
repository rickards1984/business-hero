# AI-1: one model switchboard for all of Aria

**Tier:** RED. It changes every AI call: cost, and what Aria may do. It has a migration, and an admin control. **Builder:** Claude. **Reviewer:** Codex. **Tests first.**

## Why (Mike, 20 Nov 2026)

Mike wants Aria "more like Grok Bot". That means:
- "excellent intelligence";
- "switching between models relevant to specific tasks, with the best models for complex tasks";
- "robust, reliable … good security and future proofed (able to upgrade Aria easily as new models come out)".

**Decided (20 Nov):**
- AI-1 comes **first**, before ARIA-1 and ARIA-2, so the inbox and everything after it is built on it.
- Models are chosen on an **admin panel page**, not through Railway variables.

## What exists (checked in code, 20 Nov)

**`services/ai_router.py`** (OUT-19 H) is used by outreach only. It provides:
- providers in an order (OpenAI → xAI → Anthropic);
- a model per purpose (`draft`, `research`, `classify`, `wording`);
- failover with a cooldown;
- refusal of an unpriced model;
- cost recording.

**Everything else hard-codes its model:**

| Where | Model today |
|---|---|
| Aria chat, `assistant_chat.process_chat_message` | `gpt-5` |
| Quote drafting (`assistant_chat`) | `gpt-4o` |
| Assistant tool (`assistant_tools` ~2909) | `gpt-5` |
| Inbox sorting, `app/email/service.analyze_email_batch` | `gpt-4o-mini` |
| Email briefing (`app/email/service`) | `gpt-5` |
| CEO briefings (`services/briefing_generator`) | `gpt-4o` |
| Board meeting (`executive_meeting_orchestrator`) | `gpt-5`, or `EXECUTIVE_MEETING_AI_MODEL` |
| Support assistant (`support_api`) | `gpt-4o` |
| `openai_utils` | `gpt-4o-mini` |
| Outreach drafts (`outreach_setup`) | `ARIA_DRAFT_MODEL`, default `gpt-4o` |
| Voice: Aria and the receptionist (realtime) | `gpt-realtime-2` |
| Speech to text | `whisper-1` |
| Text to speech, voice previews | `gpt-4o-mini-tts`, then `tts-1-hd`, then `tts-1` |

Upgrading Aria today means a code change in about 14 files. Outside outreach, nothing fails over, so one provider outage takes Aria's chat down.

## What AI-1 builds

**M1. Every AI call names a task, never a model.** One module (the router, extended) answers: "for task T, which provider and model, then which fallbacks?"

| Task | Used for | Default on day one: today's model, so no change |
|---|---|---|
| `chat` | Everyday Aria chat and quick questions | `gpt-5` |
| `chat_complex` | Multi-step jobs, money, finance analysis, long documents | `gpt-5` (Mike chooses; Claude Opus 5.5 suggested) |
| `quote` | The trade quotation estimator | `gpt-4o` |
| `draft` / `research` / `classify` / `wording` | As today in outreach | Unchanged |
| `inbox_classify` / `inbox_draft` | ARIA-1 | Set when ARIA-1 lands |
| `briefing` | CEO briefings and the email briefing | `gpt-4o` / `gpt-5` |
| `meeting` | The board meeting | `gpt-5` |
| `support` | The help assistant | `gpt-4o` |
| `voice_realtime` | Aria's voice and the receptionist | `gpt-realtime-2`. **OpenAI only**: no other provider offers realtime voice, so there is no failover; the model name is still a setting |
| `transcribe` / `speak` | Speech to text, text to speech | `whisper-1` / `gpt-4o-mini-tts` |

**M2. The admin page (platform admins only).**
- One row per task: primary provider and model, the fallback order, its price per million tokens (from `ai_costs`), and "last used".
- A model can't be chosen unless it is priced (OUT-19's rule) and its provider's key is set.
- Every change records who made it and when, and can be undone ("Revert").
- **Before switching, "Test this model"** runs the fixed evaluation set for that task (M5) on the candidate and the current model, side by side, with cost, and saves nothing.

**M3. Chat picks `chat` or `chat_complex` per message, by rules rather than another AI call.**
- **Complex when:**
  - the message asks for analysis, planning or comparison;
  - it involves money: invoices, quotes, accounts, pricing;
  - a previous round used three or more tools;
  - the conversation is long (more than about 30,000 tokens);
  - or the owner taps **"Think harder"**.
- **Otherwise `chat`.**
- The reply shows which model answered (small print, admin only).

**M4. Failover across providers for chat.**
- Aria's tools are written in OpenAI's format. The router translates tool definitions and tool calls to and from Anthropic's and xAI's formats, so a provider failure mid-chat hands the **whole turn** to the next provider.
- It never retries a turn after a tool has acted. Approval cards are proposals, so a retry can at most propose again, and the one-open-card guards already refuse duplicates.

**M5. The evaluation set** (`scripts/aria-eval/`, extending `scripts/compare-research-ai.py`):
- about 10 fixed, synthetic cases per task, using real-shaped data but never customer data;
- each with expected checks: the right tool called, no invented prices, valid JSON, the reply in the right tone;
- run by M2's "Test this model", and before any release that changes a default.

**M6. Storage:** migration 045 adds `public.ai_model_choices`, platform-wide and backend-only (REVOKE, RLS on). It holds the task, an ordered list of (provider, model), `changed_by`, `changed_at`, and the previous value for Revert. **If the table is empty, the code's defaults are used**, so nothing changes until Mike picks.

**M7. Cost and safety, unchanged:**
- every call goes through the profit guard;
- `chat_complex` has a **monthly budget per business**. This was corrected on 21 Nov: no per-business AI allowance existed, only platform-wide limits (Codex AI-1b review 1, finding 2). Mike's figures: Starter £5, Pro £12, Business £30;
- after the budget is used, or while the platform's profit guard pauses non-essential AI, Aria uses `chat` and says which;
- no model choice can make Aria send anything without the owner's approval.

## Build in three PRs

- **AI-1a (this PR): foundations.**
  - `services/ai_models.py`: the tasks, their day-one defaults (today's models and old Railway settings), saved choices (cached for a minute; never read on the event loop), and the key and price rules.
  - Every call site now names a task. A guard test fails on any hard-coded model.
  - Outreach's router reads saved choices.
  - Migration 045, with a runbook.
  - Prices added: gpt-5, Claude Opus 5.5, Sonnet 5.5. Before this, gpt-5 had no price, so chats were recorded at the "unknown model" rate.
  - **The preflight secret scan (TRAP 5) was fixed so it could push at all.**
    - **The problem:** the scan flagged any changed file that *names* the Supabase service-role key setting, so `app/email/service.py`, which has always imported that setting, could never be edited.
    - **The fix:** it now scans only the lines a change adds, both committed and staged. A pasted key on any added line, or in a new file, is still caught.
    - **The test:** `test_harness_gates.py` TRAP 5 has 7 tests. The old behaviour fails the false-positive test.
- **Codex AI-1a review 1 requested changes**, and all six findings were acted on:
  - **Findings 1 and 2, TRAP 5.** It captures the whole patch before counting matches (no SIGPIPE loss), scans binary files with `--text`, and fails closed when a patch can't be read. It's tested with a 100,000-line patch and a binary file.
  - **Finding 3, settings.** `ai_models.chat_params` sends each OpenAI chat call the settings its model accepts: reasoning models get `max_completion_tokens`, with room to reason, and no temperature (BM-1). Every OpenAI chat call site now uses `chat_request` or `chat_params`. **This also mends three features that already ran on `gpt-5` with settings it refuses: the email briefing, the inbox's three-tone reply drafts, and Aria's reply-drafts tool.** Responses-only `-pro` models are never chosen for a chat site.
  - **Finding 4, voice and speech.** These are pinned to models their code is known to serve (`compatible`). Speech stays on `tts-1`, because it's costed at that rate.
  - **Finding 5, the refresh race.** `invalidate()` bumps a generation, so a load that began before a change is dropped. Loads are serialised, so an older read never overwrites a newer one.
  - **Finding 6, the guard.** It is now syntax-aware (it parses the code): spacing, line breaks and constants are caught, comments and plain text are not, with 12 regression examples.
- **Codex AI-1a review 2:** findings 2 and 3 confirmed. Changes made for:
  - **finding 1:** a scanner error now fails TRAP 5, tested with a failing `grep` shim;
  - **finding 4:** speech is costed per model (`tts-1-hd` and `gpt-4o-mini-tts` at 2.4p per 1,000 characters, an unknown model at the highest rate). That also mends voice previews' existing under-recording;
  - **finding 5:** invalidation and a load's publication share one lock;
  - **finding 6:** the guard resolves model-id constants anywhere, annotated or not.

  All are mutation-checked.
- **Codex AI-1a review 3:** findings 1, 4 and 5 were confirmed resolved. The one finding left (fine-tuned `ft:` model IDs held in a constant slipped past the guard) was escalated after three repair cycles. Mike chose to fix it and run one more review: the guard now matches `ft:` IDs, with an example.
- **Codex AI-1a review 4: APPROVE.**
- **AI-1b: chat on the router.**
  - `chat` / `chat_complex` rules and "Think harder";
  - tool calls translated for Anthropic and xAI;
  - whole-turn failover.
- **AI-1b, as built:**
  - `services/ai_chat.py`:
    - `pick_task` applies the M3 rules: money, analysis, planning and pricing words; more than about 30,000 tokens of conversation; three or more tool rounds; or "Think harder".
    - `turn` runs one round on the first provider in the task's chain that answers. OpenAI gets settings per model; xAI goes through its OpenAI-compatible API; Anthropic's Messages API gets the conversation and tools translated, with consecutive tool results merged into one user turn.
    - A failure trips the router's cooldown and moves to the next provider.
    - Every attempt is recorded for the business as `chat`. A failed attempt is recorded at its maximum, marked estimated.
  - The chat loop (`assistant_chat.process_chat_message`):
    - runs each round through `turn` in a thread;
    - after three tool rounds, moves the rest of the turn to `chat_complex`;
    - never re-runs a tool on failover;
    - falls back to `chat` when the profit guard holds `chat_complex`, and says so in the reply.
  - "Think harder" is the `think_harder` request field and a button in the chat bar. It applies to the next message.
  - `model` in the reply is shown to platform admins only.
- **Codex AI-1b review 1 requested changes**, and all eight findings were acted on:
  1. The budget and the profit guard are checked before **every** round that would use `chat_complex`: the first, the move up after three tool rounds, and the final answer. Once refused, the rest of the turn stays on the everyday model.
  2. A **per-business monthly budget** (`ai_chat.complex_refusal`): spend recorded under `chat_complex` this UK month, against Mike's figures by plan, and changeable with `AI_COMPLEX_MONTHLY_PENCE_JSON`. A check that fails counts as paused, never as allowed. Each round is recorded under its own task.
  3. A request the provider refuses (400, 404, 413 or 422) is **`Rejected`**: not billed, never trips the provider for everyone, and the next provider may still take it. 429, 5xx and timeouts are outages, as before.
  4. A tool call cut off at the output limit (Anthropic `stop_reason: max_tokens`, OpenAI `finish_reason: length`) is **`Truncated`**: never run, and the next provider is tried. A cut-off text answer says so.
  5. OpenAI chat requests carry an explicit output limit. Failure estimates use that limit and everything sent, tool calls included. A usage report missing either figure is estimated.
  6. An empty answer goes to the final round instead of being saved empty, and empty assistant messages are left out for Claude.
  7. Chat needs any provider in its chain with a key, not specifically OpenAI.
  8. Routing: words such as made, afford, hire and money count; account, why and review on their own don't; a short follow-up keeps its money topic.

  Every fix has a test and is mutation-checked.
- **Codex AI-1b review 2:** findings 1, 3, 5, 6 and 7 confirmed resolved. Changes made for:
  - **2, the budget:** every attempt on the stronger model, failovers included, first **reserves its most possible cost** (`ai_chat.RESERVATIONS`). Recorded spend this month, plus what attempts in flight hold, plus this attempt's maximum, must fit the budget. A cost that couldn't be recorded stays counted. So concurrent turns can't all pass a check made just under the limit, and overspend is bounded by how far the estimates fall short of real usage. The reservations are in memory because production runs one process (pinned by a STAB-1 test). A refusal mid-turn answers that round with the everyday model and adds the note.
  - **4:** a cut-off final answer now says so.
  - **9 (new):** an empty answer never claims anything was done. It points to the card if one was made, or says plainly that Aria couldn't answer.
  - **8, routing:** a chain of short follow-ups keeps the topic of the question that started it, and a short message that starts a new job (change, add, send…) isn't a follow-up.

  All are mutation-checked.
- **Codex AI-1b review 3:** findings 4 and 9 were confirmed resolved. The two left on the budget were escalated after three cycles, and Mike chose to fix them and run one more review:
  - the recorded spend is read **under** the reservation lock, so an attempt that records and releases can't slip between the read and the decision;
  - unrecorded costs are kept per UK month, so they never block the next month.

  Also, the optional point: a politely asked new job ("Can you change my account name?") isn't a follow-up. All three are mutation-checked.
- **Codex AI-1b review 4: APPROVE.** Two optional points were noted for later:
  - one reservation lock for all businesses: a slow database read delays every business's admission. A per-business lock with a bounded wait would fix it;
  - an attempt that straddles midnight on the 1st could file an unrecorded cost under the new month.
- **AI-1c: the admin page** (as built). Briefings, support and the board meeting moving onto the router is now **AI-1d**, to keep this PR reviewable.
  - **`admin_ai_api.py`:** `GET /v1/admin/ai/models`, plus `PUT /models/{task}`, `POST /models/{task}/revert`, `/reset` and `/test`. Platform admins only, plain `def` routes (run in the threadpool).
  - **`services/ai_model_admin.py`:**
    - the overview lists every task with its default, the choice (who, when, the previous one), what's used now, this month's spend (business and platform meters), and the models it can use, with prices or the reason each can't (`ai_models.why_unusable`);
    - provider keys are shown only as set or not;
    - Choose validates every entry: at most 6, no duplicates, and the reason if a model can't serve the task;
    - Revert restores the previous chain, or the default;
    - Reset saves the default as a choice, so it can be reverted;
    - writes take an advisory lock per task on Postgres and invalidate the cache, so they apply at once.
  - **`services/ai_eval.py`:** five synthetic chat cases (looks up invoices, looks up the calendar, never invents a price, keeps it short, uses what it looked up). Each runs on one provider and model directly, never trips a provider, records its cost as platform `eval`, and saves nothing.
  - **`AdminAIModels.tsx`:** at `/admin/ai`, under "Aria's AI models" in the admin menu. It shows a card per task, provider key status, and a Change dialog with fallbacks, prices and "Test this model" side by side.
  - **Codex review 1** (`audits/AI-1C-CODEX-CODE-REVIEW-1.md`, REQUEST CHANGES, 5 findings), all fixed:
    1. A choice could disagree with the model the code really uses (support accepted Claude, still called gpt-4o). Each task now declares what its call site can take (`max_chain`, `providers`). The sites still calling OpenAI once take one OpenAI model and no fallbacks until AI-1d. Tests compare the page's "used now" with the call site's request.
    2. Tests ignored the spending guard. `ai_eval.admit` now refuses before any call when the profit guard holds `eval`, or when the test's most possible cost is over £3.00. Only one test runs at a time, and at most 10 an hour.
    3. One test could hold a worker for about ten minutes. Calls now time out at 25 s, the whole test has a 150 s deadline (cases not started are reported as not run), and the slot is always released.
    4. The checks passed unsafe answers. Money is now read in any form (£, GBP, pounds, quid). "Never invents a price" fails any amount and any empty answer, tool call or not. "Uses what it looked up" fails any amount not in the data. The invoice lookup must ask for overdue invoices, and a cut-off answer fails.
    5. Spend was keyed on task names that the ledger doesn't use. Each task now lists the ledger purposes it is recorded under. The card says when those are shared (support and chat both record `chat`), or that the task is not costed separately.
  - **Codex review 2** (`audits/AI-1C-CODEX-CODE-REVIEW-2.md`, REQUEST CHANGES; each finding partly fixed), now completed:
    1. A row saved before the limit could still show a fallback that the site ignores. `choice()` now cuts a saved chain to `max_chain`. The call-site test also checks that the site really asks through `chat_request("<task>")`.
    2. The hourly list is now read and written under one lock; a test that slows the read reproduces Codex's stale-copy race. The profit guard is checked again before every case, so a test stops once spending is held.
    3. Each call's timeout is what's left before the deadline, and no call starts with under 3 s left.
    4. A missing or non-object argument now fails without crashing, and so does an amount stated beside a lookup. Each customer's balance must sit with that customer. Honest answers with dates, invoice numbers and pence are covered as passing.
    5. The ledger purposes were checked against the code: `reply_draft` records `draft`, `email_briefing` records `briefing`, and `wording` records `accountancy_pack`. A test reads those attributions from the source.
  - **Codex review 3** (`audits/AI-1C-CODEX-CODE-REVIEW-3.md`): **APPROVE**, no blocking defect. Follow-up hardening (non-blocking, not in this PR):
    - Compute each call's remaining time *after* the per-case guard check, so a slow guard query can't push a call past the 150 s deadline. Re-scale the slow-call test so it runs some cases before stopping (MIN_CALL_SECONDS now skips them all).
    - Grading edge cases:
      - "£750 and £500 respectively" is a false failure;
      - "Harbour £500 / Northgate £750" in one clause is a false pass;
      - the total named against one customer is a false pass.

      Consider grading the grounding case by asking for structured output rather than reading free text.
    - There's no reservation for eval spend: a test admitted just under the kill threshold can overshoot it by at most one test's cost (≤ £3).
- **AI-1d, part 1: the text jobs onto any provider** (as built). The board meeting is part 2: it has its own tool loop and OpenAI-specific workarounds, so it gets its own PR.
  - **`services/ai_text.py`:** `complete(task, messages, max_tokens, temperature)`, with `acomplete` running it in a worker thread. It uses the task's chosen models in order through `ai_chat`'s adapters.
    - **Failover:** an outage switches that provider off for a while. A refused request (400/404/413/422) moves on without being billed or switching the provider off. An empty answer is billed and moves on.
    - **Costs:** each attempt is costed under the business and purpose of the surrounding `profit_guard.attributed` block, so the ledger and the admin page's spend read as before. A failure with no usage reported is charged at most what that request could cost, at the site's own limit.
    - **Kill switch:** a non-essential purpose is refused before any call with `profit_guard.Paused`, which every site already falls back on.
    - **Settings:** OpenAI takes `chat_params`, so reasoning models get no temperature. xAI takes the limit and temperature. Claude takes the limit and no temperature, because newer Claude models may refuse sampling settings.
    - Each site's single OpenAI retry is kept. `strip_fences` reads JSON that a model wrapped in a code block.
  - **Moved:**
    - the weekly briefing and daily pulse;
    - the help assistant's chat (essential `chat`) and the admin's draft (`support_draft`);
    - call summaries;
    - Aria's three reply drafts;
    - email: inbox sorting, the email briefing, and the single and three-tone reply drafts.

    Their prompts, parsing and plain fallbacks are unchanged. Key checks now ask whether any model in the chain has a key (`ai_chat.available`). The five tasks drop `ONE_OPENAI`, so on the admin page they take any provider and fallbacks.
  - **Off the event loop:** the four email endpoints called the sync model functions directly, so a 30-second answer froze every request. They now use `asyncio.to_thread`, which carries the attribution. The call summary was an async function making a sync OpenAI call; it now awaits `acomplete`.
  - **Still OpenAI-only:**
    - quotes and quote chat: the price rules are RED and belong with the quote estimator ticket;
    - the board meeting: part 2;
    - voice, transcription and speech: there are no equivalents elsewhere.
  - **Test this model:** new sets for the help assistant (answers from the knowledge base, hands over to a person, never invents a policy, quotes the given price) and the briefings (the pulse's shape, flagging the overdue invoice, the weekly JSON the app reads, the right numbers and the 20% change). Text sets send no tools and use the site's own output limit.
  - **The AI-1c review 3 follow-ups:**
    - each call's remaining time is now worked out after the per-case guard query;
    - the slow-call test was re-scaled so some cases run before it stops;
    - grading handles "respectively", dashes, slashes, two customers in one clause, and a total named against one customer.

    The eval spend reservation stays bounded at one test's cost (≤ £3) and is not added.
  - **Codex review 1** (`audits/AI-1D-CODEX-CODE-REVIEW-1.md`, REQUEST CHANGES; 5 blocking, 3 not), all fixed:
    1. A failure that closed the kill switch didn't stop the next attempt. The guard is now checked before every attempt, because the SDK hook can't see these calls.
    2. Fence stripping mangled valid JSON with a fence inside a string. Valid JSON is now returned as it is. Otherwise a fence is taken only if it wraps the whole answer, or follows prose and contains JSON.
    3. The help-assistant set passed a promised refund and swapped plan prices. The refund case now needs "I don't know", no promise and a handoff. The price case needs each plan's own price: names match as whole words, and "Business Hero" is not the Business plan.
    4. The briefing set passed "fell 20%" and `[1,2,3]` actions. The change must go up, last week's figure must be £3,500, each action needs a number and a label, and a briefing must come before the JSON.
    5. The daily pulse was tested at 2,000 tokens against production's 400. Each case now carries its site's limit, used in its cost too, and a cut-off answer fails.
    6. The SDK's own retry was never costed. Retries are now made in `ai_text`, one per model after an outage, and each attempt is costed. The adapters get `retries=0`.
    7. A chain of timeouts had no overall limit. The whole call now ends within twice one attempt's limit: 60 s by default, the same as the old attempt plus its SDK retry.
    8. "Harbour owes £1,250 in total" passed. The total now counts with one customer only beside that customer's own balance, or in a sentence naming several.

    Unchanged: a daily pulse cut off in production is still sent as it is, as before. It isn't a regression.
  - **Codex review 2** (`audits/AI-1D-CODEX-CODE-REVIEW-2.md`, REQUEST CHANGES; 1 blocking, 5 hardening), all fixed:
    1. **Blocking:** JSON in a block followed by a closing remark, or inline after prose, was no longer found, so the email draft showed the whole answer. `strip_fences` now:
       - returns valid JSON as it is;
       - otherwise takes the first fenced block that holds JSON, wherever it sits;
       - otherwise drops an opening fence that was cut off, as the sites did.

       The draft site is now tested end to end.
    2. Honest refund answers failed. A promise now counts only where no hedge comes before it in the same clause, so "I can't confirm whether a full refund is available" passes and "I'm not sure, but you'll get a full refund" still fails. Curly apostrophes are made straight first.
    3. The weekly check judged wording rather than meaning. The direction is now read in the clause that holds the 20%, so "…, so it did not fall" is fine. Each amount is checked against what it's said to be: last week's (`from`, `on`, `previous`, `last week's`) or this week's (`this week`, `to`). "Compared with" and "against" are not read.
    4. "Your business" was read as the Business plan. An ordinary business (yours, small, the…) is not the plan unless "plan" or "tier" follows.
    5. "Harbour owes £1,250 in total and Northgate owes £500" passed. A total is shared only when every name comes before it, with no other amount between the first name and the total.
    6. The guard's own query ran past the deadline. Time left is now checked before the guard, and the guard's time counts against the attempt. This bounds the attempts, not total wall-clock time (see the follow-ups).
  - **Codex review 3** (`audits/AI-1D-CODEX-CODE-REVIEW-3.md`, REQUEST CHANGES; 1 blocking, 5 hardening). This was the third cycle, so it was escalated to Mike, who chose to fix the blocker and get one more targeted review.
    1. **Blocking, fixed:** JSON with only a closing fence, a bare `json` label, or stray backticks no longer parsed. Those are formats the sites' own stripping accepted before AI-1d, so inbox sorting and two kinds of draft would have fallen back. `strip_fences` now tries the old lenient stripping after the fenced-block search, and uses its result only if it is JSON. Every wrapper is tested at all four JSON sites: inbox sorting, the one and three-tone email drafts, and Aria's draft tool.
  - **Codex review 4, targeted** (`audits/AI-1D-CODEX-CODE-REVIEW-4.md`, REQUEST CHANGES; 2 blocking, both fixed). Both came from running the new fenced-block search before the old stripping:
    - an answer that opens with "```json[" lost the bracket on the fence line;
    - a summary quoting "```[]```", followed by a lone closing fence, gave up the embedded `[]`.

    `strip_fences` now:
    1. returns valid JSON as it is;
    2. otherwise runs each site's stripping from before AI-1d, exactly as it was, and uses the result if it is JSON;
    3. only then tries the new fenced-block search.

    A test copies both old functions from HEAD~4. Across 4 payloads × 10 prefixes × 6 suffixes, plus Codex's example, whatever either old function parsed, `strip_fences` parses to the same value. It fails on the review-3 code and passes now.
  - **Codex review 5, narrow and final** (`audits/AI-1D-CODEX-CODE-REVIEW-5.md`): **APPROVE**, no findings. Mike chose this last review after review 4.
  - **Follow-ups, non-blocking** (grading of "Test this model", and one latency claim). Not in this PR:
    - **Refund case:** an honest hedge over a comma-separated list ("…a full refund, a partial refund or no refund…") is read as a promise.
    - **Weekly case:**
      - "up 20% compared to £3,500 last week" is mis-read through `to £`;
      - "up — 20% to £4,200" loses its direction at the dash.
    - **Plans:** "a growing business" is read as the Business plan. The exclusion list is phrase-based, not general.
    - **Shared total:** "The total owed is £1,250 by Harbour and Northgate" fails because the names come after the total.
    - **Latency:** the 60 s bound covers attempts, not wall-clock time. A slow model-choices refresh before the first attempt, or slow response reads within an adapter's timeout, can exceed it.

    Grading would be more robust with structured output than with reading free text. That was suggested in AI-1c review 3 and is still open.

## Out of scope

- Choosing models per business, which is platform-wide for now.
- Fine-tuning.
- New providers beyond OpenAI, Anthropic and xAI.

## Acceptance

- [ ] No AI call outside the router names a model. A test scans the code, as `test_entitlement_reads` does.
- [ ] With the table empty, every task uses today's model, and behaviour is unchanged.
- [ ] A choice made on the admin page takes effect within a minute, with no deploy. Revert restores the previous one.
- [ ] Chat sends a money question to `chat_complex`, and "what's on today" to `chat`.
- [ ] If the primary provider fails mid-chat, the next provider answers the whole turn, and costs are recorded for both.
- [ ] "Test this model" runs the evaluation set side by side, and saves nothing.
- [ ] Codex review preserved. Migration 045 runbook rehearsed on staging, then production.
