# MSG — Aria Messenger: our own messaging app (DESIGN, v3)

**Status:** proposed, design only. v2 answered Codex design review 1 (`audits/MSG-1-CODEX-DESIGN-REVIEW-1.md`); v3 answers review 2 (`audits/MSG-1-CODEX-DESIGN-REVIEW-2.md`, REQUEST CHANGES, 8 × P1, 1 × P2, no P0). §10 maps every finding to its answer. Next: Codex design review 3, then Mike accepts the boundary (CLAUDE.md: no large implementation stream begins before both). Each ticket then gets its own AGENTS.md §6 task packet (`docs/MSG-n-TICKET.md`) with negative acceptance criteria, required tests and verification commands, reviewed before it starts.
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

- `business_settings.settings.assistant_name` (a JSON key, no migration), default "Aria", 1–24 characters (letters, spaces, apostrophes, hyphens), trimmed; refused list for profanity and obvious impersonation. Set in Settings or onboarding only, by the business owner. Asked in chat, Aria replies with a link to that setting: no rename tool and no new card type, so MSG-2 needs no migration and can run in parallel.
- Used by the system prompt, all UI strings, cards, push, the brief, and the receptionist's greeting, which still says it's an automated assistant. Voice unchanged.

## 5 · How it's built

### 5.1 Ownership model (R4)

- **Conversations are private to the user who started them, within one business** (as `resolve_conversation` does now). Morning briefs are private to their user.
- **Records Aria creates belong to the business** (draft quotes, documents, tasks) and record `created_by_user_id` and the conversation they came from.
- **Every link is validated server-side**: a message, attachment, card, document or job referenced by id must belong to the same business, and where it is conversation-scoped, to the same user. Membership is rechecked on every request and every job step; a revoked member loses access immediately.
- **Device storage** (cache, offline queue, drafts) is keyed by user id **and** business id, encrypted where the platform offers it (Capacitor Preferences/secure storage), and purged on sign-out, account switch and business switch. A queued message is revalidated against the current session before it is submitted, and dropped (with a notice) if the user or business changed.
- **Approval cards follow their conversation.** Today `aria_actions` cards are business-wide (`_scoped`, `list_open`, the approval API, and the 035 RLS policy that lets business members read). Migration 047 adds `conversation_id` and `owner_user_id` to `aria_actions`. A card **with** a conversation is private: only `owner_user_id` can list, get, edit, approve or dismiss it, on every existing card endpoint (not only the messenger's), and the RLS read policy is narrowed to match (business member **and** (no conversation **or** owner)). Cards without a conversation (today's dashboard cards, outreach) keep current behaviour. A private Drive card uses only its owner's storage connection.
- **Tests:** cross-business, same-business/different-user (API **and** a database client with the `authenticated` role against RLS), revoked membership, account switch with a pending queue.

### 5.2 Conversations, turns and idempotency

**Migration A (alter, not create).** `assistant_conversations` gains `title`, `pinned`, `archived_at`, `last_message_at`, `kind` (`chat` | `brief`). `assistant_messages` gains `kind` (`text`, `card`, `quote_draft`, `document`, `brief`, `job_update`) and `payload jsonb` (ids only, never signed URLs). Existing rows keep their ids and stay readable by the old endpoint. Backfill only `last_message_at`, from the newest message, after checking for orphan messages (reported, not deleted). Live-schema check first, staging rehearsal with rollback, RLS on and no client grants confirmed on every touched table.

**Durable turns.** New `assistant_turns`: id, business_id, user_id, conversation_id, `client_turn_id` (UNIQUE per user + conversation), request fingerprint (hash of text + attachment ids), state (`claimed`, `running`, `done`, `failed`, `unknown`), reserved credits, settled credits, result message id, timestamps.
- Submitting claims the turn atomically. A repeat with the same `client_turn_id` and fingerprint replays the stored result (or attaches to the running stream); the same id with a different fingerprint is refused.
- Every side effect carries an **operation key** = `turn_id` (or `job_id`) + hash of the tool name and its canonical arguments, stored in `assistant_tool_calls` (turn/job id, sequence, tool, argument fingerprint, state `started|committed|failed|unknown`, result ref) and on the written row itself under a unique constraint (`aria_actions`, `tasks`, `quotes`, `business_documents` each gain `operation_key` and `created_via` = turn or job id). A repeat of the same operation returns the stored result; it is never written twice.
- A turn that dies mid-run is marked `unknown` by a sweeper; its effects are reported from their operation keys, never re-run.
- Two turns can't run at once in one conversation (the second waits or is refused with "still answering").

### 5.3 Capabilities: interactive turns vs jobs (R1–R3)

**Two tool sets, chosen by the endpoint, not the model:**
- **Interactive turn:** read tools; card tools; internal writes (task, document, draft quote). No settings, rename, connection or billing tools.
- **Job run:** read tools; card tools; internal writes only as its stored authorisation allows; no settings, rename, connection, billing, job-creation or schedule tools.

**A server-held authorisation for each turn and job (argument-level, not just kind):**
- At the start of an interactive turn, before any tool runs, a separate, tool-less model call reads **only the owner's message** (plus the ids of records the owner tapped or attached, never fetched text) and returns a structured **turn authorisation**: the operations requested (`read`, `draft_reply`, `chase`, `book`, `create_task`, `create_document`, `create_quote`, `save_to_drive`), for each a maximum count, and the **targets** the owner named (people, emails, invoices, customers, jobs, dates, amounts). It is stored on the turn. Because it never sees fetched content, injected text can't change it.
- Every write and every card is checked against it by the server:
  - its operation must be in the authorisation and within its count;
  - its target must resolve to a target the owner named, or to a record the owner tapped, or, for a reply, to the email being replied to;
  - **recipients** must be the sender (and existing correspondents) of the email being replied to, an address the owner typed, or a contact the owner named; any other address is refused;
  - **amounts and dates** on chases and bookings come from the stored invoice or the owner's message, never from fetched text;
  - nothing ever carries bank details (R1).
- Anything outside the authorisation becomes a **suggestion chip** ("Add 'call Bob back' as a task?"); tapping it is a new owner instruction, starting a new turn with its own authorisation.
- **Jobs** get their authorisation once, from the owner's creating turn, stored on the schedule/run: operations, targets or target rule (e.g. "enquiries received today"), maximum counts. Each run is checked against that stored authorisation. Jobs are never "owner turns", and don't need to be: the stored authorisation is their authority.
- Tool results reach the model as quoted data with their source.
- **Injection tests** cover unsolicited kinds **and substitutions within an authorised kind**: owner asks for one reply, the email asks to add a recipient or a second reply; owner asks to chase one invoice, the email asks to chase another or change the amount; owner asks for a document, the source text asks for a second document or for bank details in it; a job's fetched email asks to widen its target; a poisoned summary; text inside an image. Each must produce no write and no card beyond the authorisation.

### 5.4 Streaming (provider layer first)

- `ai_router` gains a streaming call with typed events: `text_delta`, `tool_call_complete`, `usage`, `done`, `error`. A tool call is executed only on `tool_call_complete` with fully parsed arguments.
- **Execution boundary.** Each completed tool call is persisted (`assistant_tool_calls`) with its argument fingerprint and result **before** its result is given back to the model. The turn's transcript (owner message, model text, tool calls, results) is therefore durable at every step.
- **Fallback:** if a provider fails *before any tool committed*, the fallback model starts the turn afresh (partial text discarded). If it fails *after* one or more tools committed, the fallback model **continues from the stored transcript**, with the committed calls and results already in it; it can't re-run them, because a call with the same operation key returns the stored result, and any new call is checked against the turn authorisation like any other.
- **Cancellation** (stop button, disconnect, deletion) is terminal: no new tool call starts; a call already running finishes and is recorded; the turn ends `cancelled`.
- **Usage settlement:** provider-reported usage is recorded per attempt; if an attempt's usage is unknown, the platform records its maximum estimated cost to `ai_pence` (our cost) and the customer is charged only for the credits of operations that committed (§5.9).
- Tests: provider failure immediately after a committed tool call; reconnect during a running tool; cancel during a tool.
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
- **Drive connections are their own credential.** `storage_connections` (business_id, user_id, provider `google_drive` | `onedrive`, provider account id and email, scopes granted, encrypted tokens, status, connected_at, revoked_at). Google: an OAuth client in a **separate Google Cloud project** used only for Drive, because revoking a token removes the grants of *every* client in the same project, so a shared project would disconnect Gmail/Calendar too. That project has its own consent screen and its own verification. Scope `drive.file` only. Test: the same Google account connected to both email and Drive; connect, refresh and disconnect Drive; Gmail/Calendar keep working. Microsoft: `Files.ReadWrite` (delegated), because `Files.ReadWrite.AppFolder` is personal-account-only and most businesses use work accounts. Own callback route and state, own refresh path (not `email_accounts`).
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

- **Unit: fixed credits per committed operation**, never variable pence, and they stack: a chat turn 1, plus 3 for each draft quote and 3 for each document it creates; a job run 1 per tool call plus the same creation charges; a morning brief 0. The owner sees credits left.
- **Bounds and quote:** an interactive turn may create at most 2 quotes/documents, so its maximum is **7 credits**; a job run's maximum is 15 + 3 × its authorised creations (at most 3), so **24**. That maximum is reserved before the first provider call; a turn that would need more is refused at the start with the reason, never cut off mid-turn.
- **Durable reservations** (new; the existing `ai_chat._Reservations` is an in-memory, per-attempt guard of *our* AI spend, and it stays as that): `aria_credit_reservations` (id, business_id, turn or job id UNIQUE, credits reserved, the lots it holds, state `held|settled|released`, created_at, expires_at). Reserving is one transaction under a per-business row lock on `aria_credit_balances`: available = allowance left + purchased left − held; the reservation records which lots it holds (allowance first, then purchased oldest first), so an allowance that ends at month-end while the turn runs is still the lot charged.
- **Settlement exactly once**, keyed by the reservation id: charge the credits of operations that **committed** (from `assistant_tool_calls`), release the rest. Failed, cancelled and `unknown` operations are not charged to the customer (an unknown outcome is our cost, recorded in `ai_pence`). A sweeper settles reservations whose turn or job ended without settling, and releases those past `expires_at` (30 minutes).
- **Our spend is bounded separately:** a per-turn ceiling of `ai_pence` across all tool rounds, summaries and fallback attempts, and a per-job ceiling, enforced in the router on top of the existing `_Reservations` guard. The kill switch (`profit_guard`) is platform-wide only.
- **Ledger:** `aria_credit_ledger` (business_id, entry `allowance|purchase|consume|release|refund|adjust`, credits, lot id, reservation id or purchase id, created_at). Allowance resets each UK month and doesn't carry over. **Purchased credits never expire** (Apple §3.1.1 forbids expiry for in-app purchases; we apply one rule to all purchases). Plan change mid-month: the new allowance from that date, prorated. A refund or chargeback removes the purchase's unspent credits; any already spent are recorded as written off.
- **Purchase sources:** `aria_credit_purchases` (immutable terms at purchase: credits, price, currency, `source` `stripe|apple`, the provider's unique transaction id under a unique constraint, status). **Stripe** follows `outreach_billing.start_topup` / `apply_page_event`: reserved purchase, verified session ownership and amount, credited once on the paid webhook, replay-safe. **Apple** (if D9(a)): consumable in-app purchase; the app sends the signed transaction to the backend, which verifies it with the App Store Server API, checks the transaction belongs to this user's account token and credits it once; App Store Server Notifications (refund, revoke) remove unspent credits. Daily reconciliation against Stripe and Apple. Purchases are never one of Aria's tools.
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
- **Barrier first.** Confirming writes a durable `account_deletions` row (state `requested → draining → purging → done`). From that moment the server refuses, for that user: new turns, uploads, brief generation, job runs, card approvals and edits, new purchases, and sign-ins. All their sessions are revoked (Supabase admin sign-out, refresh tokens invalidated).
- **Drain:** running turns are cancelled (§5.4, terminal) and awaited up to the turn time limit; running jobs are fenced (leases revoked, so a still-running worker can't write) and their schedules cancelled; the user's open cards are expired, so none can be approved afterwards. A card already mid-approval completes or fails under its existing durable claim before purge begins; it can't start after the barrier.
- **Purge:** the private data below, storage connections revoked at Google/Microsoft, push tokens, attachment objects (retried until the store confirms), then the **Supabase authentication identity** itself, via the admin API. Each step is idempotent and retried; the row records progress, so a crash resumes where it stopped.
- **All memberships:** every business the user belongs to is processed; sole-owner businesses need the choice below before the barrier is set.
- Tests: deletion racing a running turn, an approval tap, a job run and an upload; crash mid-purge then resume.
- **Account ≠ business.** Deleting a user removes their private conversations, briefs, attachments, push tokens, storage connections and device data, and their membership. If they're the **sole owner**, they choose: delete the business (all its records, jobs, schedules, documents, subscription cancelled) or hand ownership to another member first. Business records they created stay with the business if it continues.
- Retention exceptions (accounting/tax records the law requires, payment records) are listed and justified. Files already saved to the owner's Drive are theirs and are not touched; the deletion confirmation says so.

### 5.13 The app

- **Installable web app:** manifest, service worker (shell cache only; no business data in the service-worker cache), icons.
- **Stores:** refreshed Capacitor shell; camera/photos permissions with plain reasons; push; native-only build flag (§5.10).
- **Store checklist:** not a bare website (4.2: push, camera, offline, the messenger); in-app account deletion (§5.12); first-launch AI disclosure and consent before personal data goes to an outside AI provider, recorded; privacy labels and Data safety form matching reality; "Report this reply" on Aria's messages; a reviewer demo account on a seeded demo business.
- **Mike's accounts, start now:** Apple Developer Program as an organisation (needs the company's D-U-N-S number, days to weeks) and a Google Play Console organisation account (a new personal account must run a 12-tester, 14-day closed test before publishing).

### 5.14 Grounding through history (R5)

- Every rich message stores **typed source references** in `payload.sources`: `{type, id, revision or as_of}` (e.g. `quote:…:rev 4`, `invoice:…`, `xero_summary as_of 2026-11-27T07:30Z`).
- When history is trimmed, the running summary keeps a `sources` list alongside its text; the source refs of trimmed messages are carried into it, never dropped.
- **Historical vs current:** a figure from history is shown as "as of {time}". A question about the current state ("what's owed now?") always calls the tools again; Aria never answers it from history or summary.
- **Access revalidated:** each source ref is re-resolved through the tenant-scoped read tool before Aria uses it; a deleted record or a lost permission turns it into "no longer available".
- Tests: a quote edited after summarisation (the old total isn't presented as current); a source deleted; access revoked; a brief's figures matching the database.

## 6 · Schema changes, in delivery order (one migration in flight at a time; every migration RED)

| # | Ticket | Change |
|---|---|---|
| 046 | ARIA-1b | `inbox_reply_examples` (in flight) |
| 047 | MSG-1 | alter `assistant_conversations` (title, pinned, archived_at, last_message_at, kind), `assistant_messages` (kind, payload); create `assistant_turns`, `assistant_tool_calls`; alter `aria_actions` (conversation_id, owner_user_id, operation_key UNIQUE, created_via) and narrow its RLS read policy (§5.1); alter `tasks` (operation_key UNIQUE, created_via) |
| 048 | MSG-3 | `aria_credit_balances`, `aria_credit_reservations`, `aria_credit_ledger`, `aria_credit_purchases` |
| 049 | MSG-4 | `assistant_attachments`, private bucket and storage policies; alter `quotes` (source, quote_revision, reviewed_revision, operation_key UNIQUE, created_via) |
| 050 | MSG-7 | `account_deletions` |
| 051 | MSG-6 | `push_devices` |
| 052 | MSG-9 | `business_documents` (with operation_key, created_via), `storage_connections`; extend `aria_actions_type_chk` (today set in 037) with `save_to_drive` |
| 053 | MSG-10 | `aria_job_schedules`, `aria_jobs`; `assistant_tool_calls` reused for job steps |

Each: live-schema check, staging rehearsal with rollback, RLS on, no client grants (except the narrowed `aria_actions` policy), verified on production **before** the code that uses it is switched on. MSG-2 needs no migration (`assistant_name` is a JSON key and there's no rename card).

## 7 · Tickets

| # | Ticket | Contents | Risk | Band | Depends on |
|---|---|---|---|---|---|
| MSG-0 | Streaming in the router | typed streaming events, fallback, cancel, usage | AMBER | M | — |
| MSG-1 | Messenger core | `/m`, conversations, durable turns, SSE, rich kinds, chips, offline queue with §5.1 rules, capability sets §5.3, **beta gate** (feature flag for named businesses + a hard daily credit cap per business, so beta traffic is bounded before MSG-3) | RED | L | MSG-0, 046 on prod |
| MSG-2 | Rename the assistant | JSON key, validation, every surface, receptionist greeting | AMBER | S | parallel with MSG-0/1 |
| MSG-3 | Credits | ledger, admission/settlement, allowances, top-ups on web, credits-left UI | RED | M | MSG-1; **required before the gate is lifted** |
| MSG-4 | Photos → draft quote | attachments §5.6, router vision quote, review rule §5.5 | RED | M | MSG-1 |
| MSG-5 | Installable web app | manifest, service worker, icons; Mike's beta begins | GREEN | S | MSG-1 |
| MSG-6 | Push + morning brief | push devices, brief §4.3 | RED (migration 051) | M | MSG-5 |
| MSG-7 | Account deletion | §5.12 | RED | M | MSG-1 |
| MSG-8 | App store release | Capacitor, native build flag §5.10, consent screen, report-a-reply, demo business, listings, TestFlight / Play internal test; D9 settled; iOS in-app top-ups if D9(a) | AMBER (RED where billing) | M | MSG-3, MSG-6, MSG-7, Mike's accounts |
| MSG-9 | Documents + Google Drive | §5.7 | RED | L | MSG-1, MSG-4 |
| MSG-10 | Background jobs | §5.8 | RED | L | MSG-1, MSG-3, MSG-6 |
| MSG-11 | OneDrive | Graph `Files.ReadWrite`, same cards | AMBER | M | MSG-9 |

Each ticket adds the Aria read tools for its own data and grounding tests for every figure it shows (R5). Builder ≠ reviewer; `./check.sh full`; Codex reviews until approved.

**Fastest safe path to the stores** (matches the migration order in §6): MSG-0 + MSG-2 → MSG-1 (047) → MSG-5 (beta, no migration) → MSG-3 (048) → MSG-4 (049) → MSG-7 (050) → MSG-6 (051) → MSG-8. Code work for later tickets can start in parallel, but each migration lands, and is verified on production, in this order. Documents/Drive (052) and jobs (053) ship as app updates. All tickets with a migration are RED.

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

### Codex review 2

| Finding | Answer |
|---|---|
| 1 Private cards reachable via business-wide paths | §5.1: `aria_actions` gains conversation and owner; every existing card endpoint and the RLS read policy enforce it; tests on API and RLS |
| 2 Kind classifier can't enforce argument authority; job conflict | §5.3: server-held turn authorisation from the owner's message alone (operations, counts, targets); recipient, amount and target rules; jobs carry a stored authorisation; substitution tests |
| 3 Same-project revocation | §5.7: Drive in a separate Google Cloud project; cross-integration test |
| 4 Fallback after a committed tool | §5.4: calls persisted before results return; fallback resumes from the stored transcript; operation keys bound to argument fingerprints; terminal cancel; usage settlement |
| 5 Reservation for compound work | §5.9: stacking charges, per-turn (7) and per-job (24) maximums reserved up front, durable reservations holding named lots, exactly-once settlement of committed operations only, sweeper; our spend capped separately. v2's description of `_Reservations` corrected |
| 6 IAP expiry | §5.9: purchased credits never expire; Apple purchases verified with the App Store Server API, unique transaction ids, refund notifications |
| 7 Deletion barrier and identity | §5.12: durable barrier, sessions revoked, drain and fencing, expired cards, idempotent purge including the Supabase identity, race tests |
| 8 Migration inventory and order | §6 now includes the `aria_actions`, `tasks`, `quotes` alterations and the type constraint; delivery order matches the numbers; all RED; MSG-2 genuinely needs none |
| 9 Grounding through trimming | §5.14 typed source refs, carried into summaries, current-state questions re-fetched, access revalidated, tests |
