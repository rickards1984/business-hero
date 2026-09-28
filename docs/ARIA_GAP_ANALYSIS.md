# Aria gap analysis — the code against the North Star

**Status:** draft, **awaiting Codex review** (`docs/reviews/REVIEW_REQUEST_aria-gap-analysis.md`).
**Written:** 28 September 2026, by Claude Code.
**Code audited:** `main` at `2cc2b62` (after BH-006 and the 030b Release 2 PR
merged). Line numbers refer to that commit.
**Measured against:** `docs/NORTH_STAR.md` §4 (pillars) and §5 (UX).
**Serves:** Phase 0 — "produce a gap analysis of the current code against
this doc".

## How to read this

**Method.** Repository inspection only: `grep`/`sed` over `backend/` and
`frontend/client/src/`, the live column dump `audits/live-schema-public.txt`
(2026-09-03), and `audits/BH-001-FINDINGS.md` for live RLS state. Nothing was
run against production or staging, and no model was called.

**What that can and cannot establish.** Code inspection shows what the code
*does*. It does not show what production *does*: a deployed environment
variable, a live constraint, or a third-party API's current behaviour.
Anything that depends on those is marked **UNVERIFIED**, with what would
settle it. §D collects them.

**Effort** uses `AGENTS.md` §6 bands — **S** under 2 hours, **M** half a day,
**L** 1–2 days. Where one pillar is plainly several tickets, it says
**L × n**. These are rough and assume the tests are written first; RED work
(migrations, security) carries its runbook and rehearsal on top.

**Risk** leads with tenant isolation, because P9 says it must.

---

## Headline findings

1. **Aria is closer than the North Star implies — and further.** A tool layer
   already exists: `backend/assistant_tools.py` defines **27 tools** and one
   dispatcher (`execute_tool`, `:532`) shared by chat and voice. Every tool's
   SQL filters on `business_id`. That is a real foundation. But **seven of
   those tools act outside the app today, with no approval step** — Aria can
   send an email, send an invoice chase and book a calendar event on the
   model's own decision. Confirmation is requested in the prompt, not
   enforced in code. That is live in production now, and it contradicts P4
   and Phase 1's "Aria takes no write actions yet".
2. **There are three Arias, not one.** Chat (`assistant_chat.py:209`) is not
   called Aria at all — it is "a friendly, professional AI executive
   assistant". Voice (`realtime_voice.py:421`) is "Aria, the AI Admin
   assistant". The board meeting (`services/executive_meeting_prompts.py:22`)
   is "Aria, the AI executive business advisor". Three prompts, three tool
   lists, two model protocols (P3).
3. **Aria voice is very probably broken in production.** `realtime_voice.py`
   still speaks the Realtime **Beta** protocol (`"OpenAI-Beta": "realtime=v1"`,
   `:721`; Beta session shape `:751-766`). The receptionist's own code records
   that **OpenAI permanently removed the Beta interface on 12 May 2026**
   (`receptionist_call_handler.py:48`) and was migrated to GA. Voice was not.
   **UNVERIFIED** in production — one test call settles it — but the code
   gives no reason to expect it to connect.
4. **Every model call is a direct OpenAI call.** 12 modules, 19 call sites,
   10 distinct models, no routing layer, no metering (§A7). P7 starts from zero.
5. **Aria's reads bypass RLS, by construction.** The tools use the backend's
   elevated `engine` (`assistant_tools.py:12`). Isolation is application-layer
   `WHERE business_id = :bid` on every query — consistently present, but
   **no test covers any Aria tool** (§A8). P9's "enforced by RLS" is not true
   of this path and cannot be made true cheaply.
6. **The snapshot exists three times over.** Board meeting `prep_data`
   (`services/executive_meeting_prep.py:52`), the WhatsApp briefing's
   `gather_business_data` (`services/briefing_data.py:17`), and chat's
   `get_today_briefing` / `get_business_overview` tools each aggregate the
   business independently. Only `prep_data` carries `data_quality`.
7. **Aria can already state figures nobody computed on the server.**
   Accounting's "Aria's Financial Insights" falls back to insights **built in
   the browser** when the backend call fails (`frontend/client/src/pages/Accounting.tsx:393-405`),
   still under Aria's name. Chat's quote tool computes VAT as a hard-coded
   `total * 0.2` (`assistant_chat.py:178`). The chat prompt tells Aria to
   "round numbers naturally" (`assistant_chat.py:226`). Each conflicts with P2
   or P8.

---

## A · The specific audit items

### A1 · Where Aria's chat and persona prompts live

| Mode | Prompt | Name used | Model |
|---|---|---|---|
| Chat (text, and "voice mode" over TTS) | `backend/assistant_chat.py:207` `build_system_prompt` | none — "AI executive assistant for {business}" (`:209`) | `gpt-5`, hard-coded (`:759`, `:826`) |
| Realtime voice | `backend/realtime_voice.py:401` `build_system_instructions` | "Aria, the AI Admin assistant" (`:421`) | `ARIA_REALTIME_MODEL`, default `gpt-realtime` (`:18`) |
| Board meeting | `backend/services/executive_meeting_prompts.py:22` `EXECUTIVE_MEETING_SYSTEM_PROMPT` | "Aria, the AI executive business advisor" | `EXECUTIVE_MEETING_AI_MODEL`, default `gpt-5` (`executive_meeting_orchestrator.py:39`) |
| WhatsApp pulse / weekly briefing | `backend/services/briefing_generator.py:38`, `:137` | UNVERIFIED whether it names Aria (not read in full) | `gpt-4o`, hard-coded |
| Accounting insights | `backend/accounting.py:931` `get_ai_insights` | "Aria" in the UI only | **no model** — templated text, with emoji (`accounting.py:1014`) |

What already matches P3: the voice prompt specifies "naturally British … £,
UK date formats" (`realtime_voice.py:430`); chat says "No emojis" (`:232`);
the board-meeting prompt says "never falsely positive … proportionate" —
close to P8's wording. The board-meeting module's docstring already asserts
"same Aria as the rest of the product" (`executive_meeting_prompts.py:8`).
It is the only one of the three that says so.

**Gap:** one persona definition, composed into each mode, with the name,
tone and formats in one place. Chat's "round numbers naturally: about 20 not
exactly 23" (`:226`) must go — it is an instruction to state a figure the
tool did not return. Accounting's emoji-laden templated insights must either
become a grounded tool result or stop carrying Aria's name.
**Effort:** M. **Risk:** low for isolation; the risk is behavioural drift in
modes customers already use — a persona change needs before/after transcripts.

### A2 · Board meeting `prep_data` and `data_quality`

`services/executive_meeting_prep.py:52` `generate_prep_data(business_id, …)`
runs nine domain loaders from `services/executive_meeting_data_loaders/`
(financial, invoices, calls, emails, tasks, calendar, quotes, goals_actions,
last_meeting). Each loader "MUST NOT raise" and returns `available=false`
with `errors` on failure (`data_loaders/__init__.py:10-12`), wrapped by
`_safe_loader` (`:260`).

`data_quality` (`:226`) carries `completeness_score` (available / 10
expected sources), `missing_sources`, `stale_sources` and
`errors_during_prep`. **Staleness is computed for financials only** — the
`data_freshness` of the accounting sync, flagged at >24 h (`:189-201`). No
other source has a freshness check.

It is pre-generated by the in-process scheduler (`briefing_scheduler.py:1019`)
and stored on the `executive_meetings` row; the orchestrator reads it back and
places it in the prompt (`executive_meeting_orchestrator.py:78-91`). **The
board meeting has no tools** — it reasons only over `prep_data`. That is the
"loaded snapshot" pattern P2 names, already working.

**Scoping:** every loader query filters on `business_id`, or on a
`meeting_id` taken from a `business_id`-scoped query (`last_meeting.py:74`
then `:105`, `:131`). The API verifies meeting ownership before use
(`executive_meeting_api.py:757`; `_verify_meeting_ownership`, `:792`).

**Gap for the snapshot pillar:** `prep_data` is shaped for a monthly meeting
(a period, with deltas against the previous one), is generated only when a
meeting is scheduled, and has a token-budget warning (`:234`) rather than a
size design. It is the right starting point for a business snapshot, not the
snapshot itself. **Effort:** see B3.

### A3 · CEO Briefing

"CEO Briefing" in the UI is **not an in-app briefing**. `frontend/client/src/components/CeoBriefingTab.tsx`
is the **settings and history page for WhatsApp messages**: weekly briefing
day and detail level, daily pulse on/off, task reminders, real-time alerts,
test-send buttons, and a message log (`:411-503`, `:573`). It calls
`/v1/whatsapp/*` (`backend/whatsapp_briefing_api.py:25`).

The content is produced by `services/briefing_scheduler.py` from
`services/briefing_data.py:17` `gather_business_data` — a **second, separate
aggregator** (calls, emails, tasks, invoices, financial cache, transactions;
all `business_id`-scoped). The weekly briefing uses its model output; **the
daily pulse still discards its model output** and sends templated values
(`briefing_scheduler.py:572`, the recorded `TODO(day2)`; RC1 P1-6). Snapshots
are written to `briefing_snapshots` (`:631`, `:868`).

There is also `GET /v1/briefing/today` (`backend/main.py:2194`), a tasks-and-calls
summary, and chat's own `get_today_briefing` tool (`assistant_tools.py:717`).

**Gap:** Home's "short briefing" (§2, §5) has no in-app source today. The
North Star's "builds on CEO Briefing" is really "builds on
`gather_business_data` and the scheduler"; the tab itself is a WhatsApp
settings page that should move under Comms or Settings as AI Hub dissolves.

### A4 · Action items and goals

Two task systems exist, and neither has an assignee concept that means
"Aria's task":

| Table | Key columns (live dump) | Written by | Read by |
|---|---|---|---|
| `tasks` | `business_id, title, description, status, priority, category, due_at, recurrence, source, source_id, deleted_at` — **no assignee** | `POST /v1/tasks` (`main.py:1670`); Aria `create_task` with `source='assistant'` (`assistant_tools.py:648`); automation engine (`services/automation_engine.py:230`) | Dashboard **via supabase-js/RLS** (`DashboardPage.tsx:107`); `TasksPanel.tsx`; Aria `list_tasks` |
| `executive_meeting_action_items` | `business_id, meeting_id, title, description, status, priority, due_date, assignee_name, assignee_email, success_criteria, rationale, times_reviewed, last_reviewed_at, completed_at` | board-meeting `extract-actions` (`executive_meeting_api.py:955`) | `GET/PUT /v1/executive-meeting/action-items` (`:249`, `:298`); `goals_actions` and `last_meeting` loaders |
| `executive_meeting_goals` | `business_id, title, category, horizon, kpi_name, kpi_target_value, kpi_current_value, progress_history, set_in_meeting_id, status, target_date` | board meeting | `GET/PUT …/goals` (`:333`, `:380`) |

`source='assistant'` marks a task **Aria created for the owner**, not a task
Aria owns. `assignee_name` on action items is free text, defaulting to the
owner. The board meeting already reviews last time's commitments
(`last_meeting.py:131`) — the §2 end-state behaviour, working in one mode.

**Tenant-isolation note that matters here:** BH-001 found **inactive members
can still read `tasks`** on the RLS path — two permissive SELECT policies, the
older omitting `is_active` (`audits/BH-001-FINDINGS.md` §6). The dashboard
reads `tasks` and `calls` directly through supabase-js. A unified task view
built on that path inherits the defect.

**Gap:** a unified task view (Phase 1) can be a **read-only union served by
the backend**, with no schema change. "Aria's tasks vs yours, told apart by
assignee" (the Tasks pillar) needs an assignee column on `tasks` or a new
table — **a migration, therefore RED**, and subject to the one-migration-in-flight
rule (`AGENTS.md` §7) while 030b Release 2 is in flight.

### A5 · `realtime_voice.py`

- WebSocket `/v1/realtime/voice` (`:634`). Authenticates in its own handshake
  (Supabase token in the first message, `:651-661`).
- **Gated** since BH-006: `assert_feature_access(_, "aria_voice")` (`:689`),
  failing closed (`:693-699`). `docs/CURRENT_STATE.md` §5 still lists it as
  ungated — that line is now stale.
- **Beta protocol.** `"OpenAI-Beta": "realtime=v1"` (`:721`); Beta session
  keys `modalities`, `input_audio_format`, `input_audio_transcription`,
  `temperature` (`:751-766`). Compare the receptionist's GA shape and its
  comment that Beta was removed on 12 May 2026 (`receptionist_call_handler.py:48`,
  `:720-733`). **Production status UNVERIFIED; expected broken.**
- **Its own tool list** (`REALTIME_TOOLS`, 18 tools, `:29-275`) with a
  name-mapping table onto `assistant_tools.execute_tool` (`:289-308`). It
  includes `send_email_reply` → `send_email` and `send_chase` →
  `send_invoice_chase` — **voice can send customer email on a misheard
  sentence**, guarded only by "ALWAYS confirm with user first" in the prompt.
- **Business resolution picks for the user.** `get_business_for_user(user_id)`
  with no requested business (`:667`) returns the only membership, else the
  owner membership, else the oldest. A member of two businesses cannot
  choose, and the entitlement gate evaluates that same default. Not a leak —
  membership is checked — but it is not "the business on screen".
- Logs the first 500 characters of every tool result (`:393`) — customer
  email content and financial data in application logs. Chat does the same
  (`assistant_chat.py:808`).
- Separate brain: its own prompt, its own tool list, no conversation
  persistence, no shared context with chat.

**Gap:** GA migration (the receptionist is the template), then wire it to
Aria Core rather than keep a second tool list. **Effort:** GA migration M;
wiring to Core L, after Core exists. **Risk:** the voice write tools (above)
should be removed or approval-gated before voice is repaired, or repairing
it re-enables unapproved sends.

### A6 · AI Hub routes and navigation

Routes (`frontend/client/src/App.tsx:532-551`), all inside `AppShell`:
`/app/dashboard` (index), `comms`, `finance`, `quotes`, `ai` (AI Hub),
`assistant/chat`, `board-meeting`, `board-meeting/meeting/:meetingId`,
`inbox`, `briefings`, `email/outbox`, `accounting`, `help`, and four settings
pages.

AI Hub (`pages/AIHubPage.tsx`) is five client-side sub-tabs selected by
`?tab=`: **Board Meeting** (default, `:24`), **Aria** (embeds
`AssistantChat`), **Receptionist**, **CEO Briefing**, **Booking**.

Navigation: desktop `components/Sidebar.tsx:29-33` — Dashboard, Comms,
Finance, Quotes, AI Hub; mobile `components/MobileBottomNav.tsx:16-20` —
Home, Comms, Finance, Quotes, AI. Dashboard's only route to Aria is a "Talk
to Aria" quick link to `/app/ai?tab=aria` (`DashboardPage.tsx:225`). Emails
have an "Ask Aria" button that deep-links a prompt into chat
(`EmailsTab.tsx:308-312`) — the one context hand-off in the product.

Board Meeting **already has its own route** (`/app/board-meeting`); it is
only the navigation that buries it.

Dead code: `pages/BusinessDashboard.tsx` (1,318 lines) and
`components/BottomNav.tsx` are imported by nothing routed —
`BusinessDashboard` is imported nowhere, and `BottomNav` only by it.

### A7 · Every place the code calls a model provider directly

All are OpenAI. No other provider is called anywhere; the frontend calls none.

| # | File:line | Function / purpose | Model | Transport |
|---|---|---|---|---|
| 1 | `assistant_chat.py:746`, `:758`, `:825` | Aria chat, tool loop + final | `gpt-5` (hard-coded) | SDK |
| 2 | `assistant_chat.py:145` | chat's `generate_ai_quote` tool | `gpt-4o` (hard-coded) | raw `httpx` |
| 3 | `assistant_tools.py:2649` | `_draft_email_reply` tool | `gpt-5` (hard-coded) | SDK |
| 4 | `realtime_voice.py:20`, `:716-725` | Aria realtime voice | `gpt-realtime` (env) + `whisper-1` | WebSocket, **Beta** |
| 5 | `receptionist_call_handler.py:55`, `:733` | phone receptionist | `gpt-realtime-2` (env) + `whisper-1` | WebSocket, GA |
| 6 | `receptionist_api.py:612-633` | `preview_voice` | `gpt-4o-mini-tts`, fallback `tts-1-hd` | SDK |
| 7 | `receptionist_api.py:730-764` | `preview_voice_preset` | same | SDK |
| 8 | `main.py:2408` | `/v1/tts` (chat voice mode) | `tts-1` | SDK |
| 9 | `openai_utils.py:26` | `generate_call_summary` (from `main.py:1872`) | `gpt-4o-mini` | SDK |
| 10 | `app/email/service.py:405` | `analyze_email_batch` | `gpt-4o-mini` | SDK |
| 11 | `app/email/service.py:489` | `generate_email_briefing_markdown` | `gpt-5` | SDK |
| 12 | `app/email/service.py:555` | `generate_email_reply_draft` | `gpt-4o-mini` | SDK |
| 13 | `app/email/service.py:624` | `generate_email_reply_drafts` | `gpt-5` | SDK |
| 14 | `services/briefing_generator.py:38` | `generate_weekly_briefing` | `gpt-4o` | SDK async |
| 15 | `services/briefing_generator.py:137` | `generate_daily_pulse` (output discarded) | `gpt-4o` | SDK async |
| 16 | `services/executive_meeting_orchestrator.py:409`, `:440` | board meeting | `EXECUTIVE_MEETING_AI_MODEL`, default `gpt-5` | SDK async |
| 17 | `quoting_api.py:1227` | `generate_ai_quote` | `QUOTE_AI_MODEL`, default `gpt-5.4` | raw `httpx` |
| 18 | `support_api.py:143` | `_get_ai_support_response` | `gpt-4o` | SDK async |
| 19 | `support_api.py:661` | `admin_ai_draft_response` | `gpt-4o` | SDK async |

Each constructs its own client (`timeout=30, max_retries=1` where it uses
the SDK). Four models are configurable by environment variable; the other
fifteen call sites hard-code theirs. There are **two** independent AI quote
generators with different models and prompts (#2 and #17). Nothing records
tokens, minutes or cost; `usage_meters` is referenced by no code
(`admin_business_api.py:116` is a comment).

### A8 · How Aria reads business data, and whether it respects RLS and business scoping

**Path.** Chat: `POST /v1/assistant/chat` (`main.py:2299`) → verify JWT inline
→ `_assert_ai_access(…, "aria_chat")` (`main.py:2346`) → `process_chat_message`
(`assistant_chat.py:660`) → resolve conversation (ownership by `user_id`,
`:645`) → resolve business by active membership (`get_business_for_user`,
`:450`) → tool loop → `execute_tool(name, args, business.id, tz)`. Voice
reaches the same `execute_tool` through its name map. **`business_id` is
always the server-resolved one; no tool accepts `business_id` from the
model.** That is the property that matters most, and it holds.

**RLS: bypassed.** Tools run on `db.engine` — the backend's elevated
connection (`assistant_tools.py:12`, `AGENTS.md` §4). RLS plays no part.
Isolation is application-layer only.

**Business scoping: present on every tool query.** A pass over every SQL
string in `assistant_tools.py` found `business_id` in each tool's primary
query. The exceptions are all transitive: `_send_invoice_chase`'s final
`UPDATE invoices … WHERE id = :invoice_id` (`:2513`) follows a
`business_id`-scoped read of the same invoice (`:2440`), and
`_draft_email_reply` reads `businesses WHERE id = :id` with the caller's own
id (`:2642`). `_analyze_spending` scopes the category join on both sides
(`:2140-2141`) — the BH-002 pattern, done right. Token refreshes (`:860`, `:910`)
write by account id obtained from a scoped read. **No leak found.**

**What is not established.** No test exercises any Aria tool against two
tenants. `backend/tests/test_tenant_isolation_backend_path.py` (BH-003) is the
harness to extend; it covers accounting only, and its own `UNCOVERED`
registry names "the assistant tool" reads as not yet tested. A text search
for `business_id` is evidence of intent, not proof — BH-002 was exactly a
query that mentioned `business_id` and still leaked.

**Edge worth a test:** chat's entitlement gate evaluates the business named
in the request, or the user's default; the conversation's business is used
for the chat itself (`assistant_chat.py:705`). For a user in two businesses
who sends a `conversation_id` from one and no `business_id`, the gate and the
chat can see different businesses. Membership is still enforced on both, so
this is an entitlement question, not an isolation one.

**Platform admins** can resolve any business and read any conversation
(`assistant_chat.py:465`, `:595`). By design; out of scope here.

---

## B · Architecture pillars (North Star §4)

### B1 · Aria Core

**Current state.** No orchestrator. `assistant_chat.process_chat_message`
(`:660`) is the nearest thing: a synchronous tool loop, up to 5 rounds
(`:752`), returning `{reply, business, conversation_id}`. Voice and board
meeting each run their own loop. No screen context is passed in; no
citations or proposed actions come out; no snapshot or memory is loaded.
Conversation log persists to `assistant_conversations` / `assistant_messages`
(last 20 messages, `:580`).

**Gap.** One service taking `(business, user, screen context, message)`,
loading persona + snapshot + memory, calling the model through the router
with the tool registry, returning answer + citations + proposed actions.
Chat becomes its first client; voice and board meeting follow.

**Effort.** L × 2 for Core with chat as sole client (response contract with
citations, screen-context input, persona composition, tests). Voice and board
meeting migration each add an L later.

**Risks.** Isolation: Core becomes the single place `business_id` is resolved
— good, if it is the *only* place; a second resolution path is how the
voice/chat business mismatch above arises. Behaviour: chat is in customers'
hands; the response contract change must be backward-compatible with
`AssistantChat.tsx`.

**Dependencies.** Router (B7) ideally first, or Core calls the provider in
exactly one place so the router can replace it. Tool layer (B2).

### B2 · Tool layer

**Current state.** Exists — 27 tools, one dispatcher, `business_id` scoped
(§A8). Read tools: `list_tasks`, `list_calls`, `get_today_briefing`,
`list_emails`, `get_email_detail`, `list_calendar_events`,
`get_calendar_briefing`, `check_calendar_availability`,
`list_google_calendars`, `get_accounting_summary`, `list_transactions`,
`analyze_spending`, `list_invoices`, `get_invoice_summary`,
`get_xero_financial_summary`, `get_overdue_invoices`, `get_business_overview`,
`get_cashflow_forecast`, `list_quotes`, plus `generate_ai_quote` and
`draft_email_reply` (which call a model but do not act).
**Tools that act outside the app, directly, today:** `send_email`
(`:1391`), `send_invoice_chase` (`:2431`), `create_calendar_event`
(`:1904`). **Tools that write inside the app:** `create_task` (`:637`),
`delete_task` (`:802`). `send_quote` (`:2838`) only points the user at the
Send button — already the right shape.

Coverage by department (§4 names eight): money ✓, invoices ✓, quotes ✓
(list only), jobs/calendar ✓ (Google only), comms ✓ (email only — **no
WhatsApp**), calls ✓, tasks ✓ (`tasks` only — **no board-meeting action items
or goals**), compliance ✗ (module absent, by design).

**Gap.**
- Tools are untyped dicts in one 2,865-line file; results are free-form
  JSON with **no record ids consistently returned for citation** — some tools
  return ids (invoices, emails), others do not.
- Money is returned as `float` (e.g. `:2525`), not Decimal-as-string.
- No tool reads `executive_meeting_action_items`, `executive_meeting_goals`,
  quote engagement ("opened twice"), WhatsApp, or receptionist call outcomes
  beyond the `calls` row.
- Write tools execute; P4 requires they *propose*.
- Missing entirely: a registry that declares each tool read or write, its
  department, and its citation shape — which the DoD Gate 7 test needs.

**Effort.** Remove or gate the three external-action tools: **S** (and it
should happen first — see §C of the proposal). Typed registry + citation ids
across existing read tools: L. Two-business isolation tests over every read
tool, extending BH-003: M–L. New read tools (action items, goals, quote
events, WhatsApp): M each.

**Risks.** This is where P9 lives. Every new tool is a new `WHERE business_id`
that can be forgotten on one join; the BH-003 harness must cover each tool
before it ships (Gate 7). Quote "opened" tracking may not exist — **UNVERIFIED**
whether any quote-view event is recorded (no column observed in the live
dump's `quotes` table was read for this; check before promising §2's first
example).

**Dependencies.** None to start. Citation ids precede the "tap a figure to
see the records" UX.

### B3 · Business snapshot

**Current state.** Three aggregators (§A2, §A3): `generate_prep_data`
(nine loaders, `data_quality`), `gather_business_data` (WhatsApp), and
chat's `get_today_briefing` / `get_business_overview`. `briefing_snapshots`
and `financial_summary_cache` tables exist. None is cached for Aria's use or
loaded into chat.

**Gap.** One snapshot builder, refreshed on a schedule, stored per business,
loaded into Core, carrying `data_quality` with freshness for every source
(today only financials). Reuse the `prep_data` loaders rather than write a
fourth aggregator.

**Effort.** L. Storage needs a table or a column → migration → RED, unless
an existing table (`briefing_snapshots`) fits — **UNVERIFIED**; its columns
were not examined for fit.

**Risks.** A cached snapshot is a stored copy of a business's data: it must
be keyed and read by `business_id` only, and a new table created via
`create_all()` would be **RLS off with full client grants** from the moment
the process boots (`AGENTS.md` §3.3; FINDINGS §4). Staleness is itself a P2
risk — the snapshot must say how old it is.

**Dependencies.** Scheduler (in-process, single replica — `AGENTS.md` §3.7).

### B4 · Memory

**Current state.** Absent as structured memory. The conversation log exists
(`assistant_messages`, keyed by conversation, user and business). The board
meeting records `executive_meeting_decisions` (decision, rationale,
`aria_recommendation`, `owner_chose_differently`) and action items — the
closest thing to "decisions and commitments as records", confined to one mode.

**Gap.** Tables for facts, decisions, preferences and commitments linked to
source conversation; a "what Aria remembers" page with edit/delete.

**Effort.** L × 2 plus a RED migration.

**Risks.** Highest P9 exposure of any pillar: memory is the one feature
*designed* to carry information forward, so it is the one most able to carry
it across a boundary. It must be keyed by `business_id` (and probably
`user_id`), RLS on, never shared across tenants, and deletable (UK GDPR —
`docs/SECURITY.md` records data export/deletion as absent).

**Dependencies.** Core, migration slot. Phase 2 — not RC1.

### B5 · Tasks

**Current state.** §A4 — two systems, no assignee on `tasks`.

**Gap.** One task system with an assignee (owner / Aria / named person).
**Phase 1's "unified task view"** is a much smaller thing: a backend endpoint
returning `tasks` ∪ open `executive_meeting_action_items`, scoped by
`business_id`, with no schema change.

**Effort.** Unified read view: M. Real unification with assignee: L + RED
migration.

**Risks.** Serve it from the backend, not supabase-js, so it does not inherit
the inactive-member `tasks` policy defect (BH-001 §6). Action items and tasks
have different status vocabularies — **UNVERIFIED** exact values; map them
explicitly rather than assume.

**Dependencies.** None for the view. Migration slot for the real thing.

### B6 · Actions & permissions

**Current state.** Absent. There is no proposed-action queue, no approval
card, no per-action-type permission, no audit trail (`docs/CURRENT_STATE.md`
§4: audit logging absent). `whatsapp_pending_actions` exists for WhatsApp
reply actions — **UNVERIFIED** whether it is a reusable pattern.

**Gap.** All of it. For Phase 1 the North Star only needs the *negative*:
Aria takes no write actions. That means disabling the three external-action
tools in chat and voice (§B2) — the only Phase 1 work in this pillar.

**Effort.** Phase 1 part: S. Full pillar: L × 3 + RED migration (queue and
audit tables). **Risks.** Removing `send_email` / `send_invoice_chase` from
Aria removes a capability MSC may use — Michael's call (proposal §D).

### B7 · Model router

**Current state.** Absent (§A7). RC1 already carries it as **P1-1**.

**Gap.** One module that owns clients, model choice per task (by name, from
config), fallback, timeouts, and metering hooks. Migrate the 19 call sites.
Realtime (WebSocket) calls need a different interface from request/response
calls.

**Effort.** Router + chat + board meeting + briefings (request/response):
L. Remaining sites: M. Realtime abstraction: M.

**Risks.** Low for isolation. P9's "only covered providers" becomes
enforceable here — the router is where an allow-list of providers belongs.
Adding a second provider before the legal review (§10, open question 5) would
itself breach P9.

**Dependencies.** None. It is the cheapest pillar to start and makes P0-2
metering easier.

### B8 · Voice

**Current state.** §A5 — Beta protocol, expected broken; separate brain;
gated. Chat also has a "voice mode" using `/v1/tts` (`main.py:2408`, `tts-1`).

**Gap.** GA migration; then route through Core with the shared tool
registry; British voice choice (open question 4).

**Effort.** GA migration M (receptionist is the worked example). Core wiring
L after B1.

**Risks.** Unmetered and the most expensive endpoint (`CURRENT_STATE.md` §5)
— P0-2 metering applies. Re-enabling voice with its current write tools
re-enables unapproved sends.

**Dependencies.** Voice write tools removed first. P0-2 metering before it is
promoted.

### B9 · Proactive engine

**Current state.** Partial. `services/briefing_scheduler.py` runs an
in-process 60-second loop (`:54`) that sends the daily pulse, weekly
briefing, task reminders and board-meeting prep; `services/alert_dispatcher.py`
and `services/automation_engine.py` exist. Output goes to WhatsApp, not to an
in-app feed. The daily pulse discards its AI output (`:572`).

**Gap.** "Aria noticed" items as records, feeding home, briefing and
WhatsApp from one source.

**Effort.** L + migration. Phase 2.

**Risks.** In-process scheduler breaks silently at 2+ replicas
(`AGENTS.md` §3.7). Every scheduled model call is unmetered spend.

### B10 · Evals

**Current state.** The test harness is strong for money and entitlement and
now has a two-tenant backend harness (BH-003,
`test_tenant_isolation_backend_path.py`) and an RLS harness
(`test_tenant_isolation_rls_path.py`, local Supabase, not in `check.sh`).
**No test imports `assistant_tools`, `assistant_chat`, `realtime_voice`,
`executive_meeting_prep` or `briefing_data`.** There is no seeded business
with known answers and no grounding test.

**Gap.** A seeded test business; grounding tests asserting each tool's
figures equal database-computed values (Gate 7); two-tenant tests for each
tool; later, model-in-the-loop evals run before a model change.

**Effort.** Seeded business + grounding tests for existing read tools: L.
Model-in-the-loop evals: L, and they cost money per run.

**Risks.** Grounding tests over tool *outputs* are deterministic and cheap.
Tests that Aria *repeats* the figure correctly need a model call and are not
deterministic — keep them out of `check.sh`.

**Dependencies.** None. This should precede new read tools, not follow them.

---

## C · UX target (North Star §5)

### C1 · Home is Aria
**Current.** `/app/dashboard` (`DashboardPage.tsx`, 299 lines): KPI tiles for
calls, emails, invoices and tasks, a WhatsApp config check, quick links
including "Talk to Aria". Calls and tasks are read via supabase-js (RLS path,
`:46`, `:107`); emails and invoices via the API. No briefing, no talk bar, no
approval cards, no task lists.
**Gap.** A new home composed of: briefing (needs B3), talk/type bar (Core or
existing chat), department tiles (the existing KPI queries), task lists (B5
view). "Needs you" approval cards are Phase 2 (B6).
**Effort.** L. **Risk.** Move the calls/tasks reads to the backend when
rebuilding — they currently ride the policies BH-001 found leaky for
inactive members. **Dependencies.** B3 for a real briefing; without it the
briefing is a chat turn, and costs a model call per home load.

### C2 · Persistent dock
**Current.** Absent. `AssistantChat.tsx` supports `embedded` and a `?prompt=`
deep link; Email's "Ask Aria" is the only context hand-off.
**Gap.** A dock in `AppShell.tsx` on every page, passing screen context (route
+ record id) to Core. **Effort.** M for a text dock over existing chat; L once
it passes context Core can use. **Risk.** Screen context arrives from the
client: Core must treat the record id as a *hint* and re-check it belongs to
the resolved business, or the dock becomes a cross-tenant lookup by id.

### C3 · Department pages share one layout
**Current.** Comms, Finance, Quotes and AI Hub are independent layouts;
`Accounting.tsx` has an "Aria's Financial Insights" panel (templated, with a
client-side fallback — Headline 7).
**Gap.** A shared page frame: Aria summary strip → data → actions.
**Effort.** M for the frame; M per department for a grounded summary.
**Risk.** Each summary strip is an Aria-facing figure → Gate 7 grounding test.

### C4 · Board Meeting one tap from home
**Current.** Route exists (`/app/board-meeting`), reachable via AI Hub's
default sub-tab. **Gap.** A home entry point and a nav item. **Effort.** S.
**Risk.** None to isolation; board meetings are Pro and above
(`auth.py:522`) — Starter needs an upgrade prompt, which
`components/board-meeting/UpgradePrompt.tsx` already provides.

### C5 · AI Hub dissolves
**Current.** Five sub-tabs (§A6). **Gap.** Receptionist → Calls (Comms);
Booking → Calendar; CEO Briefing (WhatsApp settings) → Comms or Settings;
Aria → home/dock; Board Meeting → own nav item. **Effort.** M, mostly moves.
**Risk.** `AIHubPage.tsx:87` passes `me.id` as `businessId` to
`ReceptionistTab` — **UNVERIFIED** whether `me.id` is the business id or the
user id; check before moving the component.

### C6 · Alive, not gimmicky
**Current.** No streaming anywhere: chat is one POST returning the full reply
after up to five tool rounds (`assistant_chat.py:752`). `RealtimeVoice.tsx`
has a UI for voice; waveform/presence **UNVERIFIED** (not inspected).
**Gap.** Streamed replies (SSE) through Core; presence indicator.
**Effort.** M once Core exists; retrofitting streaming into the current loop
is wasted work. **Risk.** Railway proxy and streaming — `main.py:338` notes a
middleware "with a history of interfering with streaming responses".

### C7 · Built for site, not the desk
**Current.** `AppShell` switches to `MobileBottomNav` on small screens; no
PWA, no offline (`CURRENT_STATE.md` §6: mobile/site workflows absent). Voice
is expected broken (§A5).
**Gap.** Mobile-first layouts for home and dock; working voice.
**Effort.** M for home/dock mobile layouts (build them mobile-first); voice
per B8. **Risk.** No frontend tests exist; Mike is the browser test
(`RC1_SCOPE.md` P1-5) — every UX item above adds manual clicking.

---

## D · UNVERIFIED — what this analysis could not settle

| Item | What would settle it |
|---|---|
| Aria voice is broken in production (Beta protocol) | One voice session on a Pro test account, or Railway logs for `/v1/realtime/voice` |
| `ARIA_REALTIME_MODEL`, `QUOTE_AI_MODEL`, `EXECUTIVE_MEETING_AI_MODEL` production values | Railway environment |
| Whether OpenAI's terms in force cover UK customer financial and email data (P9) | Legal review — North Star open question 5 |
| Whether any quote-view ("opened twice") event is recorded | Read `quotes` columns and `quoting_api.py` send/view path |
| Whether `briefing_snapshots` can hold a business snapshot | Its columns in `audits/live-schema-public.txt` |
| Whether `whatsapp_pending_actions` is a reusable approval pattern | Read `whatsapp_briefing_api.py` action path |
| Task / action-item status vocabularies | Read the writers of both tables |
| `AIHubPage.tsx:87` `me.id` as `businessId` | Read `hooks/useMe.ts` |
| Whether WhatsApp briefings name Aria | Read `briefing_generator.py` prompts |
| Voice UI presence/waveform | Read `RealtimeVoice.tsx` |
| That no Aria tool leaks across tenants | Two-business tests per tool (B10) — text inspection is not proof |

---

## E · Where this analysis sits uneasily with the North Star

Raised for Michael, not edited into `NORTH_STAR.md`.

1. **P9 says "enforced by RLS"; the backend path cannot be.** Aria's tools run
   as the elevated role and RLS never applies. Making it apply means running
   each request under the caller's JWT claims (`SET LOCAL role authenticated`
   plus `request.jwt.claims`) — an architectural change to the backend's
   database access, far beyond Phase 1. The honest RC1 position is
   application-layer scoping **proven by two-tenant tests**. Suggest P9 read
   "enforced by business scoping, tested per tool, and by RLS on the client
   path".
2. **Phase 1 says Aria takes no write actions; she already takes three.**
   Phase 1 therefore *removes* capability from live customers. It is the
   right call for P4, but it is a product change, not a non-event.
3. **"Builds on CEO Briefing"** points at a WhatsApp settings page. The real
   foundation is `gather_business_data` and the scheduler.
4. **The Tasks pillar implies a migration** that the North Star's phase plan
   does not flag, and migrations queue behind 030b Release 2.
5. **Voice is a live defect, not a Phase 2 feature.** If it is sold on Pro and
   broken, the GA migration is a stability prerequisite, not North Star work —
   the North Star's own prerequisite rule puts it ahead of Phase 1 features.
