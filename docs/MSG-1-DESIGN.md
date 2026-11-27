# MSG — Aria Messenger: our own messaging app (DESIGN, v2)

**Status:** proposed, design only. v2 answers Codex design review 1 (`audits/MSG-1-CODEX-DESIGN-REVIEW-1.md`, REQUEST CHANGES, 16 × P1, 2 × P2); §10 maps each finding to its answer. Next: Codex design review 2, then Mike accepts the boundary (CLAUDE.md: no large implementation stream begins before both). Each ticket then gets its own AGENTS.md §6 task packet (`docs/MSG-n-TICKET.md`) with negative acceptance criteria, required tests and verification commands, reviewed before it starts.
**Owner:** Mike. **Author:** Claude Code. **Date:** 27 Nov 2026.
**Builds on:** NS-B10 (approval cards, `services/aria_actions.py`), AI-1 (router), ARIA-1/1b (inbox, reply learning, 046), BH-012 (metering), PROFIT-1 (`profit_guard`), BRIEF-1 (`services/whatsapp_briefings.py`), OUT top-ups (`services/outreach_billing.py`), the Capacitor shell (commit 357b324).

---

## 1 · Mike's decisions (27 Nov 2026)

1. **Our own messaging app**, Grok/WhatsApp-style. No WhatsApp or Telegram channel: third-party platforms can change their terms under us (Meta's 15 Jan 2026 AI-provider rule).
2. **App stores as soon as possible** (the listing is advertising), with an installable web app first for Mike and beta testers. One codebase.
3. **Aria is agentic:** natural chat *and* tasks — drafts replies to approve, checks finances, adds tasks, creates documents, drafts quotes from photos, saves into Business Hero and the owner's Google Drive / OneDrive.
4. **The assistant can be renamed** for the whole product, including the receptionist's greeting. "Aria" stays the default.
5. **Documents:** any document the business needs. **Quotes:** Aria saves a *draft*; the owner reviews it in Business Hero; only a reviewed quote goes to Drive/OneDrive as a PDF.
6. **Google Drive first, then OneDrive.**
7. **All tiers**; Starter has a smaller allowance, with paid top-ups.
8. **A daily morning brief**, then "what would you like me to do?".

## 2 · Rules this stream must not break

Server-enforced, each with tests; prompt wording is never the control (`test_aria_no_unapproved_actions.py` is the precedent).

- **R1 — Aria never moves money.** No payment, transfer, refund, bank-detail change or payout tool exists in any capability set, card type or job. Not even behind an approval card.
- **R2 — Nothing outward without a tap.** Email, invoice chase, calendar invite, and any save to the owner's Drive/OneDrive is an approval card, approved by the owner on exactly the content and destination shown (the versioned, durable claim in `aria_actions.approve`). There is no "always allow" setting. Quote *sending* stays on the Quotes page as today (`_send_quote_via_aria` already directs the owner there); a chat send-quote card is out of this stream's scope.
- **R3 — Authority comes only from the owner's own message.** Text fetched by tools (emails, transcripts, documents, image text, earlier summaries) is data. It can't add a recipient, change bank details or amounts, create, schedule or alter anything, or widen a job. Mutations in a turn must trace to the owner's message in that turn (§5.3).
- **R4 — Tenant and user isolation** for every row, link, file, cache and queued item (§5.1).
- **R5 — Every figure Aria states comes from a tool or a stored record**, with grounding tests (North Star §8).
- **R6 — No financial detail or customer text on a lock screen.**
- **R7 — Not a general-purpose chatbot.** Aria works on *this* business.

## 3 · What exists today (checked on 08761b6)

| Piece | Where | State |
|---|---|---|
| Tool chat, ~30 tools | `assistant_tools.py`, `assistant_chat.process_chat_message`, `POST /v1/assistant/chat` | One JSON response per turn; the user message, provider calls, tools and reply are separate steps (not idempotent) |
| Conversations | `assistant_conversations` (id, business_id, user_id, created_at, updated_at), `assistant_messages` (role, content) | Exist. `resolve_conversation` / `load_conversation_history` scope by user **and** business. Text only |
| Approval cards | `aria_actions.CHAT_ACTION_TYPES`: `send_email`, `send_invoice_chase`, `create_calendar_event`, `create_task` | Versioned, durable claim on approve |
| Chat quote tool | `assistant_chat.py:176` | Calls OpenAI directly, outside the router; doesn't save a draft |
| Quotes from photos | `quoting_api.generate_ai_quote` | An endpoint that consumes images; not an attachment store |
| Quote PDF | `quoting_api._get_quote_pdf_data`, `POST /v1/quotes/{id}/generate-pdf` | Reads the *current* quote and company settings |
| Router, prices, spend | `ai_router`, `ai_costs` (`ai_pence`, all purposes, includes estimates); `ai_chat.turn` reserves budget only when `budget_business` is given | `require_priced` checks a price exists, nothing more |
| Meter | `metering.py`, `usage_meters` | Receptionist minutes |
| Top-up precedent | `outreach_billing.start_topup` / `apply_page_event` | Reserved purchase, verified paid session, credited once |
| Briefings | BRIEF-1 `whatsapp_briefings.py` via `briefing_scheduler` | Daily pulse already retired; weekly (Fri) and monthly (1st) WhatsApp summaries, no AI; task reminders and alerts are separate |
| Settings | `business_settings.settings` JSONB (`models.BusinessSettings`) | |
| OAuth | Gmail/Calendar and Graph Mail, tokens in `email_accounts`, refreshed by `oauth_utils.get_valid_access_token` | No Drive/Files |
| Sign-out | `AuthContext.signOut` | Signs out only; no cache cleanup |
| Capacitor | `frontend/client/{ios,android}` | Stale, no push tokens stored |
| Login | email + password | No social sign-in (Apple 4.8 n/a) |
| `db.init_db` | calls `create_all()` | New tables must still come by numbered migration, not by model |

## 4 · The product

### 4.1 What the owner sees

- **Full-screen, chat-first** route `/m`, opening into the latest conversation. A conversation list (Aria writes titles; pin, search, archive, delete). Composer with camera, gallery, file, send.
- **Streaming replies** with a typing indicator and *safe* status labels ("Checking your accounts…"), never raw tool inputs or results.
- **Rich messages:** approval cards, draft-quote cards, document cards, task cards with Undo, small finance tables, suggestion chips.
- **Natural style:** short, warm, plain English; one clarifying question rather than a guess; the owner's own reply style when drafting (ARIA-1b).
- **Poor signal:** recent conversations cached; plain text messages typed offline are queued and sent on reconnect, marked "waiting to send". Taps on cards are **never** queued: offline, the buttons are disabled.
- **Same conversations on phone, web and desktop.** Full Business Hero is one tap away.
- **The assistant's name** throughout, including notifications and the brief.

### 4.2 What Aria can do

| Ask | Result | Control |
|---|---|---|
| "How are we doing this month?" | Figures from tools only | read-only |
| "Reply to Smith, Tuesday works" | Draft in the owner's style | card |
| "Chase anything over 30 days" | One chase card per invoice | card each |
| "Add a task to order the skip" | Task created, with Undo (D3) | owner-requested internal write |
| *photos* + "quote this bathroom" | Vision quote via the router, saved as a **draft** quote; card links to it | owner-requested internal write; send stays on the Quotes page |
| "Write a risk assessment for Hill Street" | Document stored in Business Hero; card offers Save to Drive | internal write; Drive save is a card |
| "Put the Smith quote in my Drive" | Only a quote reviewed at its current revision (§5.5) | card bound to that revision and destination |
| "Draft replies to today's enquiries and tell me when done" / "every Friday, who hasn't paid?" | Background job (§5.8) | job capability set; outward steps become cards; ends when cards are prepared |

### 4.3 The morning brief

- **New**, per user, at the user's chosen local time (default 07:30, the business time zone), posted into a "Morning brief" conversation; push: "Your morning brief is ready".
- Content from `briefing_data` and tools: emails needing a reply, missed calls, money in / due / overdue, diary, tasks due; then "What would you like me to do?" with chips.
- One brief per user per local date (unique key); opening the app early generates it once and the scheduled run then skips. Figures carry an "as of" time; a brief older than 12 hours says so.
- Independent of `whatsapp_configs`. BRIEF-1's weekly/monthly WhatsApp summaries, task reminders and alerts keep running unchanged; whether to retire them later is D7.
- Brief model cost is free to the customer but recorded in platform metering and capped per business per day.

### 4.4 Renaming the assistant

- `business_settings.settings.assistant_name` (a JSON key, no migration), default "Aria", 1–24 characters (letters, spaces, apostrophes, hyphens), trimmed; refused list for profanity and obvious impersonation. Set in Settings or onboarding; asked in chat, it shows a confirm card (and jobs can't do it).
- Used by the system prompt, all UI strings, cards, push, the brief, and the receptionist's greeting, which still says it's an automated assistant. Voice unchanged.

## 5 · How it's built

### 5.1 Ownership model (R4)

- **Conversations are private to the user who started them, within one business** (as `resolve_conversation` does now). Morning briefs are private to their user.
- **Records Aria creates belong to the business** (draft quotes, documents, tasks) and record `created_by_user_id` and the conversation they came from.
- **Every link is validated server-side**: a message, attachment, card, document or job referenced by id must belong to the same business, and where it is conversation-scoped, to the same user. Membership is rechecked on every request and every job step; a revoked member loses access immediately.
- **Device storage** (cache, offline queue, drafts) is keyed by user id **and** business id, encrypted where the platform offers it (Capacitor Preferences/secure storage), and purged on sign-out, account switch and business switch. A queued message is revalidated against the current session before it is submitted, and dropped (with a notice) if the user or business changed.
- **Tests:** cross-business, same-business/different-user, revoked membership, account switch with a pending queue.

### 5.2 Conversations, turns and idempotency

**Migration A (alter, not create).** `assistant_conversations` gains `title`, `pinned`, `archived_at`, `last_message_at`, `kind` (`chat` | `brief`). `assistant_messages` gains `kind` (`text`, `card`, `quote_draft`, `document`, `brief`, `job_update`) and `payload jsonb` (ids only, never signed URLs). Existing rows keep their ids and stay readable by the old endpoint. Backfill only `last_message_at`, from the newest message, after checking for orphan messages (reported, not deleted). Live-schema check first, staging rehearsal with rollback, RLS on and no client grants confirmed on every touched table.

**Durable turns.** New `assistant_turns`: id, business_id, user_id, conversation_id, `client_turn_id` (UNIQUE per user + conversation), request fingerprint (hash of text + attachment ids), state (`claimed`, `running`, `done`, `failed`, `unknown`), reserved credits, settled credits, result message id, timestamps.
- Submitting claims the turn atomically. A repeat with the same `client_turn_id` and fingerprint replays the stored result (or attaches to the running stream); the same id with a different fingerprint is refused.
- Every side effect in a turn carries an operation key (`turn_id:tool_call_index`), checked by a unique constraint where it writes: a reconnect can't create a second card, quote, document or task.
- A turn that dies mid-run is marked `unknown` by a sweeper; its effects are reported from their operation keys, never re-run.
- Two turns can't run at once in one conversation (the second waits or is refused with "still answering").

### 5.3 Capabilities: interactive turns vs jobs (R1–R3)

Two server-side tool sets, chosen by the endpoint, not the model:
- **Interactive:** all read tools; card tools; owner-requested internal writes (create task, create document, create draft quote, rename confirm card).
- **Job:** read tools; card tools; internal writes only of the kinds the owner named when starting the job (stored on the job); no rename, settings, connection, job-creation or schedule-changing tools.
- **Internal writes need the owner's request in this turn:** the tool call must cite the owner's message; the server checks the turn was started by the owner (not a brief or job) and the write's kind matches the request classifier for that message. A write prompted only by fetched text is turned into a suggestion chip ("Add 'call Bob back' as a task?"), never performed.
- Tool results are passed to the model wrapped as quoted data with their source.
- **Injection tests**, one per tool family: an email asking to add a recipient, substitute bank details, change an amount, create a task or document, book a meeting, or schedule a job; a poisoned summary; text inside an image. Each must yield no write and no card that the owner didn't ask for.

### 5.4 Streaming (provider layer first)

- `ai_router` gains a streaming call with typed events: `text_delta`, `tool_call_complete`, `usage`, `done`, `error`. A tool call is executed only on `tool_call_complete` with fully parsed arguments.
- Fallback after partial output: the partial text is discarded from the stored message, the user sees "trying again", and the fallback model's answer replaces it; usage from both is settled.
- Cancellation (user taps stop or disconnects) stops the provider stream; usage so far is settled.
- `POST /v1/assistant/conversations/{id}/turns` returns Server-Sent Events from the turn; reconnecting with the same `client_turn_id` resumes from the stored state. The old JSON endpoint stays until the messenger replaces `AssistantChat.tsx`.
- **Cost controls:** prompt caching on the system prompt and tool definitions; images downscaled and re-encoded; history window plus a stored running summary (the summary is data under R3); cheap-model routing for simple turns once AI-1e is in.

### 5.5 Photo quotes and the review rule

- The chat quote tool is rebuilt: through the router; using the turn's image attachments (max 5); saving the draft with `create_quote`'s own code path (server-calculated totals) with `source = aria_chat`. The card shows totals read back from the saved quote (grounding test).
- **Review bound to content.** `quote_revision` (incremented on any material change: line items, prices, customer, terms, VAT, and the company details the PDF prints) and `reviewed_revision`. Reviewing (Save / Mark reviewed on the Quotes page) sets `reviewed_revision = quote_revision`. A material edit raises `quote_revision`, so the review lapses.
- PDF download, generate-pdf and Save-to-Drive for an `aria_chat` quote are refused unless `reviewed_revision = quote_revision`. The Drive card stores the revision; approving a card whose revision is stale is refused ("the quote changed, review it again"). Quotes the owner built by hand are their own work and keep today's behaviour.

### 5.6 Attachments

- **Upload:** the app asks for an upload slot (`POST /attachments`, with type and size); the server checks membership, limits and quotas, creates a `pending` row with a server-generated immutable key (`{business_id}/{attachment_id}`) and returns a short signed upload URL. The client uploads; `POST /attachments/{id}/finalise` makes the server fetch, decode and validate it (real MIME from content; images ≤ 10 MB, ≤ 40 MP, re-encoded to ≤ 1568 px, metadata stripped; PDF/DOCX ≤ 10 MB with page/decompressed-size limits and a parser timeout), then marks it `ready`. Only `ready` attachments owned by the same user and business can be attached to a turn.
- **Storage:** private bucket; storage policies deny all direct client access; reads only via a fresh short-lived signed URL issued per request after the tenant check. Messages store attachment ids, never URLs.
- **Quotas:** per message (5), per day, per business total; abandoned `pending` uploads deleted after 24 hours.
- **Deletion** removes the row and the object; deleting a conversation or the business deletes its attachments.
- **Rendering:** documents are rendered from stored markdown to DOCX/PDF on the server with no remote fetches, no scripts, no embedded active content.

### 5.7 Documents and Drive / OneDrive

- `business_documents` (business-owned; `created_by_user_id`, conversation id, title, kind, body markdown, `revision`, timestamps). Tools: `create_document`, `list_documents`, `get_document`, `update_document` (owner-requested). A Documents page to open, edit, download, delete.
- **Drive connections are their own credential.** `storage_connections` (business_id, user_id, provider `google_drive` | `onedrive`, provider account id and email, scopes granted, encrypted tokens, status, connected_at, revoked_at). Google: a **separate OAuth client** in the same Google Cloud project, so its grant and revocation are independent of the Gmail/Calendar grant (Google revokes scopes of one client's combined grant together). Scope `drive.file` only. Microsoft: `Files.ReadWrite` (delegated), because `Files.ReadWrite.AppFolder` is personal-account-only and most businesses use work accounts. Own callback route and state, own refresh path (not `email_accounts`).
- **Save card** binds connection id, provider account, destination folder and the document or quote revision. If the connection was replaced or reconnected to another account since, the card is refused and shows again for the new account.
- Folder "Business Hero/Documents" and "Business Hero/Quotes". Disconnect revokes at the provider and marks the row revoked. Files already saved stay in the owner's Drive (their copy); Business Hero keeps only the file id.

### 5.8 Background jobs

- **Schedules and runs are separate.** `aria_job_schedules` (owner-created recurring asks: instruction, allowed write kinds, cadence in the business time zone, next_run_at, paused). `aria_jobs` (one run: instruction, allowed write kinds, schedule id + scheduled-for key, UNIQUE (schedule_id, scheduled_for), state, attempt, lease_owner, lease_expires_at, heartbeat_at, fencing token, checkpoint jsonb, tool_calls_used, credits reserved/used, elapsed, result message id, error).
- **Execution:** claim with a lease and fencing token; heartbeat; each step checkpointed with its operation key before and after; a worker whose lease expired can't write (fencing). Attempt limit 3; a step whose outcome is unknown is never repeated, and the job ends `needs_review`.
- **Limits:** ≤ 15 individual tool calls, ≤ 5 minutes elapsed, tool results truncated to a size cap, a credit reservation per run. Cancellation is checked between every tool call.
- **Before each run and step:** membership, plan entitlement, allowance and provider connection are rechecked.
- **Approval ends the run:** a job's outward steps prepare cards; the run then finishes `done` with a summary message listing the cards. It never waits for or resumes on approval.
- **DST:** schedules are local-time; a non-existent local time runs at the next valid minute, a repeated one once; a missed run (downtime) runs once on recovery if it's within 6 hours, else is skipped and noted.
- **Tools for Aria:** `list_jobs`, `get_job`, `cancel_job`, `list_schedules`, `pause_schedule` (owner-requested only).

### 5.9 Allowance, credits and top-ups

- **Unit: fixed credits per action**, never variable pence: chat turn 1, photo quote 3, document 3, job tool call 1, morning brief 0. The owner sees credits left. Our *cost* is tracked separately in `ai_pence` (platform accounting); a per-turn cost ceiling stops a single credit from costing us more than it earns.
- **Admission:** every billable turn, quote, document and job run reserves its credits atomically (a single statement on the business's credit balance, the same pattern as `ai_chat.turn`'s `budget_business` reservation) **before** any provider call, and settles after. Not enough credits: refused before starting, never cut off mid-turn. Concurrent turns can't overspend.
- **Ledger:** `aria_credit_ledger` (business_id, entry type `allowance` | `topup` | `consume` | `refund` | `adjust`, credits, source id, created_at) and `aria_credit_purchases` (immutable terms at purchase: credits, price, currency, Stripe session, status). Consumption order: this month's allowance first, then top-ups oldest first. Allowance doesn't carry over; top-ups last 12 months. Plan change mid-month: the new allowance applies from the change, prorated. Refunds/disputes claw back unspent credits; spent credits are written off, recorded.
- **Purchase:** follows `outreach_billing.start_topup` / `apply_page_event`: reserve, verify session ownership and amount, credit once on the paid webhook, replay-safe, daily reconciliation. Purchases are never one of Aria's tools.
- **Pricing (D6):** priced from explicit margins (target ≥ 60% gross after Stripe fees at the measured cost per credit), not from my earlier estimate. The v1 example (250 for £5 at 2p) had no margin; that's withdrawn.

### 5.10 App-store payments (D9, decided before MSG-5 and MSG-7)

- **Apple:** §3.1.3(b) lets the app use credits bought elsewhere **only if they're also offered by in-app purchase**. The compliant paths are: (a) offer top-ups by Apple in-app purchase in the iOS app too (Small Business Programme 15%), priced to keep the margin; or (b) a different, justified basis, which I haven't found for this case. Recommended: (a).
- **Google:** a consumption-only Android app (no purchase or purchase links in the app) is permitted; Play Billing is needed only if we sell inside the app. Recommended: consumption-only on Android at first.
- **The native bundle** must not reach Stripe checkout or the billing portal (`BillingSettings.tsx` redirects there): a build flag removes those routes and links in the native apps; an audit test lists every route in the native build.

### 5.11 Push notifications

- `push_devices` (user_id, business_id, platform, token, created_at, last_seen_at, disabled_at). APNs and FCM via Capacitor; Web Push (VAPID) for the installed web app (iOS 16.4+ after Add to Home Screen).
- For: brief ready, job finished, card waiting, urgent email or missed call. Quiet hours. Generic wording (R6). Tokens deleted on sign-out, account deletion, and after repeated failures.

### 5.12 Account deletion (RED, its own ticket)

- "Delete my account" in the app and a **public web deletion-request page** (Google requires one outside the app). Authenticated, confirmed, retryable workflow.
- **Account ≠ business.** Deleting a user removes their private conversations, briefs, attachments, push tokens, storage connections and device data, and their membership. If they're the **sole owner**, they choose: delete the business (all its records, jobs, schedules, documents, subscription cancelled) or hand ownership to another member first. Business records they created stay with the business if it continues.
- Retention exceptions (accounting/tax records the law requires, payment records) are listed and justified. Files already saved to the owner's Drive are theirs and are not touched; the deletion confirmation says so.

### 5.13 The app

- **Installable web app:** manifest, service worker (shell cache only; no business data in the service-worker cache), icons.
- **Stores:** refreshed Capacitor shell; camera/photos permissions with plain reasons; push; native-only build flag (§5.10).
- **Store checklist:** not a bare website (4.2: push, camera, offline, the messenger); in-app account deletion (§5.12); first-launch AI disclosure and consent before personal data goes to an outside AI provider, recorded; privacy labels and Data safety form matching reality; "Report this reply" on Aria's messages; a reviewer demo account on a seeded demo business.
- **Mike's accounts, start now:** Apple Developer Program as an organisation (needs the company's D-U-N-S number, days to weeks) and a Google Play Console organisation account (a new personal account must run a 12-tester, 14-day closed test before publishing).

## 6 · Schema changes, in order (one migration in flight at a time)

| # | Ticket | Change | Risk |
|---|---|---|---|
| 046 | ARIA-1b | `inbox_reply_examples` (in flight) | RED |
| 047 | MSG-1 | alter `assistant_conversations`, `assistant_messages`; create `assistant_turns` | RED |
| 048 | MSG-3 | `aria_credit_ledger`, `aria_credit_purchases`, balance | RED |
| 049 | MSG-4 | `assistant_attachments` + private bucket and storage policies; `quotes.source`, `quote_revision`, `reviewed_revision` | RED |
| 050 | MSG-6 | `push_devices` | AMBER (by migration, rehearsed) |
| 051 | MSG-7 | account-deletion support (deletion requests, audit) | RED |
| 052 | MSG-9 | `business_documents`, `storage_connections` | RED |
| 053 | MSG-10 | `aria_job_schedules`, `aria_jobs` | RED |

Each: live-schema check, staging rehearsal with rollback, RLS on, no client grants, verified before the code that uses it is switched on. `assistant_name` is a JSON key (no migration).

## 7 · Tickets

| # | Ticket | Contents | Risk | Band | Depends on |
|---|---|---|---|---|---|
| MSG-0 | Streaming in the router | typed streaming events, fallback, cancel, usage | AMBER | M | — |
| MSG-1 | Messenger core | `/m`, conversations, durable turns, SSE, rich kinds, chips, offline queue with §5.1 rules, capability sets §5.3, **beta gate** (feature flag for named businesses + a hard daily credit cap per business, so beta traffic is bounded before MSG-3) | RED | L | MSG-0, 046 on prod |
| MSG-2 | Rename the assistant | JSON key, validation, every surface, receptionist greeting | AMBER | S | parallel with MSG-0/1 |
| MSG-3 | Credits | ledger, admission/settlement, allowances, top-ups on web, credits-left UI | RED | M | MSG-1; **required before the gate is lifted** |
| MSG-4 | Photos → draft quote | attachments §5.6, router vision quote, review rule §5.5 | RED | M | MSG-1 |
| MSG-5 | Installable web app | manifest, service worker, icons; Mike's beta begins | GREEN | S | MSG-1 |
| MSG-6 | Push + morning brief | push devices, brief §4.3 | AMBER | M | MSG-5 |
| MSG-7 | Account deletion | §5.12 | RED | M | MSG-1 |
| MSG-8 | App store release | Capacitor, native build flag §5.10, consent screen, report-a-reply, demo business, listings, TestFlight / Play internal test; D9 settled; iOS in-app top-ups if D9(a) | AMBER (RED where billing) | M | MSG-3, MSG-6, MSG-7, Mike's accounts |
| MSG-9 | Documents + Google Drive | §5.7 | RED | L | MSG-1, MSG-4 |
| MSG-10 | Background jobs | §5.8 | RED | L | MSG-1, MSG-3, MSG-6 |
| MSG-11 | OneDrive | Graph `Files.ReadWrite`, same cards | AMBER | M | MSG-9 |

Each ticket adds the Aria read tools for its own data and grounding tests for every figure it shows (R5). Builder ≠ reviewer; `./check.sh full`; Codex reviews until approved.

**Fastest safe path to the stores:** MSG-0 + MSG-2 → MSG-1 → MSG-5 (beta) → MSG-3 + MSG-4 + MSG-7 → MSG-6 → MSG-8. Documents/Drive and jobs ship as app updates.

**Alongside:** 046 + PR 118; HK-3 (PR 119); VOICE-MIG before 6 Jan 2027; AI-1e (cheap-model tool use).

## 8 · Decisions for Mike

- **D1 — Layout:** `/m` opens straight into chat on phones; desktop keeps the dashboard with the messenger one click away (recommended).
- **D2 — Threads:** several titled conversations like Grok (recommended), or one continuous thread.
- **D3 — Tasks from chat:** created directly when *you* ask, with Undo (recommended); or keep the current approval card.
- **D6 — Allowances and top-up price:** set from beta cost data at ≥ 60% margin. Starting proposal to be confirmed after two weeks' beta: Starter 300 credits/month, Pro 1,500, Business 4,000.
- **D7 — BRIEF-1 WhatsApp summaries:** keep running alongside the messenger brief for now (recommended), and decide after the beta.
- **D8 — Store name:** "Business Hero", the assistant's name inside (recommended).
- **D9 — iOS payments:** offer top-ups by Apple in-app purchase too, 15% to Apple (recommended); Android consumption-only at first.

(v1's D4 "always allow saving to Drive" and D5 "OneDrive app folder" are withdrawn: R2 forbids the first; the second doesn't work for work accounts.)

## 9 · Risks

- Store rejection on first submission: §5.13 checklist; TestFlight / internal test first.
- AI cost above credit price: per-turn cost ceiling, caching, downscaling, job limits, reconciliation of `ai_pence` against credits sold, `profit_guard`.
- Google OAuth verification of the new Drive client and consent screen.
- Prompt injection: R3 and §5.3 tests.
- Scope creep: each ticket keeps its own acceptance criteria.

## 10 · Codex review 1: where each finding is answered

| Finding | Answer |
|---|---|
| 1 Existing `assistant_conversations` | §5.2 migration A alters it; ids kept; backfill only `last_message_at`; orphans reported |
| 2 Isolation of links and device storage | §5.1 |
| 3 Idempotent turns | §5.2 durable turns, operation keys, `unknown` state; §4.1 card taps never queued |
| 4 No quote-send card; Drive approval | R2: quote send stays on the Quotes page; Drive saves always exact cards; D4 withdrawn |
| 5 Injection criterion | R3, §5.3 capability sets, owner-request rule, test list; R1 excludes money tools from cards too |
| 6 Review bound to content | §5.5 revisions; stale approvals refused; hand-built quotes unchanged |
| 7 Attachment lifecycle | §5.6 |
| 8 Separate Drive credential | §5.7 `storage_connections`, separate Google client, Graph `Files.ReadWrite`; card bound to connection |
| 9 Job recovery | §5.8 leases, fencing, checkpoints, schedules vs runs, DST, approval ends the run |
| 10 Admission | §5.9 atomic reservation and settlement before any provider call; allowance separate from `ai_pence` |
| 11 Credit unit and settlement | §5.9 fixed credits, ledger, purchase terms, `outreach_billing` pattern, margin rule |
| 12 Apple 3.1.3(b) | §5.10, D9; native build flag removes Stripe routes |
| 13 Account deletion | §5.12, RED ticket MSG-7, public web route |
| 14 Read tools and grounding | R5; each ticket adds its read tools and grounding tests |
| 15 Briefing baseline | §3, §4.3 (BRIEF-1 is the current baseline; daily pulse already retired), D7 |
| 16 Dependencies and migrations | §6 inventory; §7 beta gate in MSG-1, MSG-3 before the gate lifts, deletion RED; task packets per ticket |
| 17 Streaming provider layer | §5.4, MSG-0 |
