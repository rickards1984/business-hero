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
- `chat_complex` is still bound by the business's AI allowance;
- when the allowance runs short, Aria uses `chat` and says so;
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
- **AI-1b: chat on the router.**
  - `chat` / `chat_complex` rules and "Think harder";
  - tool calls translated for Anthropic and xAI;
  - whole-turn failover.
- **AI-1c: the admin page.**
  - choices, Revert, "Test this model" and the evaluation set;
  - briefings, support and the board meeting moved onto the router, so they can also use other providers.

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
