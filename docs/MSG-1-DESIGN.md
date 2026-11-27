# MSG — Aria Messenger: our own messaging app (DESIGN)

**Status:** proposed, design only, for Codex design review and then Mike's acceptance of the boundary (CLAUDE.md: no large implementation stream begins before both).
**Owner:** Mike. **Author:** Claude Code. **Date:** 27 Nov 2026.
**Builds on:** NS-B10 (approval cards, `aria_actions`), AI-1 (model router), ARIA-1/1b (inbox, reply learning, migration 046), BH-012 (metering), PROFIT-1 (`profit_guard`), HK-3 (model retirement), the Capacitor shell (`frontend/client/capacitor.config.ts`, commit 357b324).

---

## 1 · Mike's decisions (27 Nov 2026)

1. **Our own messaging app.** One messenger, ours, that looks and feels like Grok / WhatsApp: no WhatsApp or Telegram channel, because third-party platforms (Meta's 15 Jan 2026 AI-provider rule is the example) can change the terms under us.
2. **App stores as soon as possible** (the listing is advertising in itself), with an installable web app first for Mike and the beta testers. One codebase for all three.
3. **Aria is agentic.** She chats naturally *and* takes tasks: drafts email replies to approve, checks finances, adds tasks, creates documents, drafts quotes from job photos, and saves things into Business Hero and into the owner's Google Drive or OneDrive as the task needs.
4. **The assistant can be renamed**, for the whole product (chat, app, briefings, the phone receptionist's greeting). A personalisation; "Aria" stays the default.
5. **Documents:** Aria can create whatever document the business needs (letters, method statements, risk assessments, notes, policies…). **Quotes** are different: Aria saves a *draft* quote in Business Hero; the owner reviews it there, and only then can it go to Drive/OneDrive as a PDF, by download or by asking Aria.
6. **Google Drive first, then OneDrive.**
7. **All tiers** get the messenger. Starter has a smaller monthly allowance, with paid top-ups when it runs out.
8. **A morning brief every day**, Grok-style: emails, calls, money, diary, then "what would you like me to do?". It replaces the current WhatsApp pulse/briefings, which Mike says don't help.

## 2 · What must not happen (unchanged North Star rules, restated for this stream)

- **Aria never moves money.** No payments, transfers, refunds or bank actions, by any tool, ever.
- **Nothing leaves the business without a tap.** Every outward action (email, invoice chase, quote send, calendar invite to a third party, file shared outside the owner's own Drive) is an approval card. A background job may *prepare* cards; it never approves them.
- **Business data stays tenant-scoped.** Every new table carries `business_id`, is backend-only (RLS on, no client grants, as 045/046), and every tool resolves records through the caller's business.
- **Text from outside is data, not instructions.** Email bodies, call transcripts, uploaded images and document contents can't widen what Aria may do (prompt injection). An instruction found in an email ("send the bank details to…") never becomes an action without the owner asking and approving.
- **No financial detail on a lock screen.** Push notifications say *that* something needs you, not the figures or the customer's words.
- **Not a general-purpose chatbot.** Aria answers about *this* business; documents she writes are for the business.

## 3 · What already exists (so we extend, not rebuild)

| Piece | Where | State |
|---|---|---|
| Tool-using chat, ~30 tools (accounting, Xero, invoices, cash flow, emails, calls, calendar, tasks, quotes, outreach) | `backend/assistant_tools.py`, `backend/assistant_chat.py`, `POST /v1/assistant/chat` (`main.py:2443`) | Live; one JSON response per turn, no streaming |
| Approval cards: `send_email`, `send_invoice_chase`, `create_calendar_event`, `create_task` | `aria_actions` + `backend/aria_actions_api.py` | Live (NS-B10) |
| Conversation history | `assistant_messages` (conversation_id, role, content) | Text only; no conversation list, titles or attachments |
| Chat UI | `frontend/client/src/pages/AssistantChat.tsx` (531 lines) | Desktop-first page inside the app shell |
| Quote from photos (vision, up to 5 images) | `quoting_api.generate_ai_quote` (`quoting_api.py:1146`) | Quotes page only |
| Chat's quote tool | `assistant_chat.py:176` | Text only, calls OpenAI directly **outside the AI router**, and returns the quote without saving a draft |
| Model router, prices, per-business AI spend | `services/ai_router.py`, `services/ai_costs.py` (`ai_pence`) | Live |
| Generic usage meter (allowance, overage, caps) | `services/metering.py`, `usage_meters` | Live for receptionist minutes |
| Briefing scheduler + data | `services/briefing_scheduler.py`, `services/briefing_data.py` | Live (WhatsApp/email briefings) |
| Google OAuth (Gmail, Calendar) and Microsoft Graph (Mail) | `backend/app/email/router.py`, `providers/oauth_utils.py` | No Drive / Files scopes yet |
| Capacitor iOS/Android shell, push plugin configured | `frontend/client/{ios,android}`, `capacitor.config.ts` | One early commit; stale; no push tokens stored anywhere |
| Login | email + password (Supabase) | No social sign-in, so Apple's "Sign in with Apple" rule (4.8) doesn't apply |

## 4 · The product

### 4.1 The messenger (what the owner sees)

- **Full-screen, chat-first**, opening straight into the latest conversation, the way WhatsApp opens. A conversation list (titles Aria writes, pin, search, delete). A clean composer with **📷 camera**, **🖼 gallery**, **📎 file**, and send.
- **Replies stream in** word by word, with a typing indicator, and a short status line while she works ("Checking Xero…", "Reading 3 emails…").
- **Rich messages inside the chat:** approval cards (Approve / Edit / Dismiss), draft-quote cards ("Draft quote £2,340 saved, open to review"), document cards (open, save to Drive), task cards, small finance tables, and suggestion chips under her replies ("Chase the 3 overdue", "Reply to Smith").
- **Natural conversation:** short, plain, warm replies by default; she asks one follow-up question when something is ambiguous, rather than guessing; she remembers the thread; she uses the owner's own reply style when drafting (ARIA-1b, migration 046).
- **Works with poor signal:** the last conversations are cached; messages typed offline are queued and sent when the phone reconnects, clearly marked as "waiting to send".
- **The same conversations on phone, web and desktop.** The messenger is a route of the existing React app (`/m`), so the full Business Hero is one tap away for reviewing quotes, documents and finances in detail.
- **The assistant's name and avatar** appear everywhere: header, cards, notifications, the morning brief.

### 4.2 What Aria can do from the messenger

| Ask | What happens | Approval |
|---|---|---|
| "How are we doing this month?" / "Who owes me money?" | Reads accounting/Xero/invoice tools; answers with figures from the tools only | none (read-only) |
| "Reply to the Smith email, say Tuesday works" | Drafts in the owner's style | **card**: send email |
| "Chase anything over 30 days" | Prepares one chase card per invoice | **card** each |
| "Add a task to order the skip" | Task created in Business Hero | see decision D3 |
| "Book the Jones survey Thursday 10am" | Checks availability, proposes booking | **card** |
| *photos* + "quote for this bathroom refit" | Vision quote through the router, **saved as a draft quote** in Business Hero; a card links to it | none to save the draft (it's a draft); **card** to send it, as today |
| "Write a risk assessment for the Hill Street job" | Document created and stored in Business Hero (§5.4); a card offers *Save to Drive* | none to create internally; **card** to save to Drive (D4) |
| "Put the Smith quote in my Drive as a PDF" | Only if the quote has been **reviewed** in Business Hero (§5.3) | **card** |
| "Every Friday, tell me who hasn't paid" / "Go through my inbox and draft replies to the enquiries" | A background job (§5.6) that messages back when done, with cards for anything outward | job runs on ask; outward steps are cards |

### 4.3 The morning brief

- At the time each user chooses (default 07:30, UK time), Aria writes the brief **into the messenger** as a new message, and a push notification says "Your morning brief is ready" (no figures on the lock screen).
- Content: emails needing a reply (with draft-reply chips), missed calls, money in yesterday / due today / overdue, today's diary, open tasks due. Then "What would you like me to do?" with 3–4 suggested actions as chips.
- Built on `briefing_data.py` and `briefing_scheduler.py`. Opening the app before the scheduled time can show it early.
- The current WhatsApp pulse and briefings are switched off for a business once its owner uses the messenger brief (D7).

### 4.4 Renaming the assistant

- `business_settings.assistant_name` (default "Aria"), 1–24 characters, letters/spaces/apostrophes/hyphens, trimmed; plus an optional avatar choice from a small built-in set (no uploads at first).
- Used by: the chat system prompt ("You are {name}…"), every UI string that says Aria, approval cards, push notifications, the morning brief, and the **receptionist's greeting** to callers (Mike: "as a whole"). The receptionist's *voice* doesn't change.
- Refused names: names of real public figures or brands we can detect cheaply, names that claim to be a human member of staff on the phone ("I'm Sarah from accounts" on the receptionist still discloses it's an automated assistant, as today), and profanity.
- The user sets it in Settings and in onboarding; Aria can also be asked in chat ("call yourself Max"), which shows a confirm card.

## 5 · How it's built

### 5.1 Conversations and messages (migration 047, after 046 lands)

One migration in flight at a time (AGENTS.md §7), so 047 waits for 046 on production.

- `assistant_conversations` (id, business_id, user_id, title, pinned, archived, last_message_at, created_at). Backend-only.
- `assistant_messages` gains `kind` (`text`, `card`, `quote_draft`, `document`, `brief`, `job_update`), `payload jsonb` (card ids, quote id, document id, chips), and `client_message_id` (idempotency for the offline queue: a re-sent message is stored once).
- `assistant_attachments` (id, business_id, message_id, storage path, mime, bytes, width, height, sha256, created_at). Images are stored in a **private** Supabase Storage bucket, path-prefixed by business id, served to the app only through short-lived signed URLs the backend issues after the tenant check.
- Existing conversations are backfilled into `assistant_conversations` from `assistant_messages.conversation_id`.

### 5.2 Streaming and the chat turn

- New `POST /v1/assistant/conversations/{id}/messages` returning **Server-Sent Events**: status lines, text deltas, then the final message with its cards. The current JSON endpoint stays for the existing page until the messenger replaces it.
- The tool loop stays in `assistant_chat.py`; tool rounds are capped (existing rule) and the whole turn is priced against the business's allowance (§5.7) **before** the model is called, as `require_priced` does now.
- **Cost controls built in from the start:** prompt caching for the system prompt and tool definitions (the largest, repeated part of every turn); images downscaled to ≤1568 px on the long edge and re-encoded (which also strips EXIF/location); simple conversational turns routed to the cheaper model once AI-1e gives it tool use; history trimmed to the recent window plus a running summary.

### 5.3 Photo quotes from chat

- The chat's `generate_ai_quote` is rebuilt to (a) go **through the AI router** like everything else (today it calls OpenAI directly), (b) accept the message's image attachments (max 5, as the Quotes page), and (c) **save a draft quote** (`status = draft`, `source = aria_chat`, linked to the conversation) using the same code path as the Quotes page, so drafts look identical wherever they were made.
- The chat shows a draft-quote card: total, line count, "Open to review". Nothing is sent to the customer from chat without the existing `send_quote` card.
- **Reviewed before Drive:** a quote gets `reviewed_at` / `reviewed_by` when the owner opens and saves (or explicitly marks reviewed) it in Business Hero. *Save quote to Drive* and *download PDF* are refused for a draft that hasn't been reviewed, and Aria says why. The PDF is the existing quote PDF (`quoting_api._get_quote_pdf_data`, `POST /v1/quotes/{id}/generate-pdf`).

### 5.4 Documents

- `business_documents` (id, business_id, title, kind, body_markdown, created_by `aria|user`, conversation_id, source_refs, created_at, updated_at, drive_file_id, drive_provider). Backend-only.
- Tool `create_document(title, kind, outline/instructions)`: Aria writes the document from the business's own data where relevant (customer, job, quote), stores it in Business Hero, and returns a document card. Owners can open, edit and download it (DOCX and PDF rendered server-side from the stored markdown).
- A **Documents** section in Business Hero lists them; documents are deletable; deletion of the business cascades.
- Documents are business documents. Aria declines to make documents that aren't about the business (consistent with §2) and never puts bank details into a document from an email alone.

### 5.5 Google Drive, then OneDrive

- **Separate connection**, its own "Connect Google Drive" button: never added silently to the existing Gmail/Calendar consent, so existing users aren't forced to re-consent to keep email working.
- **Narrowest scopes:** Google `drive.file` (only files Business Hero creates or the user picks; not the whole Drive). Microsoft `Files.ReadWrite.AppFolder` if its folder location is acceptable to Mike, else `Files.ReadWrite` (decision D5).
- Files go into a **"Business Hero"** folder, with subfolders `Documents` and `Quotes`. Documents are saved as Google Docs (Drive) / DOCX (OneDrive); quotes as PDF.
- Tool `save_to_drive(document_id | quote_id)` creates an approval card (D4). Tokens are stored encrypted like the existing provider tokens; a revoked token is reported once and the card fails clearly.

### 5.6 Background jobs (agentic tasks)

- `aria_jobs` (id, business_id, user_id, conversation_id, instruction, status `queued|running|waiting_approval|done|failed|cancelled`, steps_used, pence_used, budget_steps, budget_pence, schedule (optional cron for recurring asks), result_message_id, error, timestamps). Backend-only.
- A worker (same process pattern as `briefing_scheduler`, with a DB claim so two instances never run the same job) runs the job as a tool loop with **hard limits**: ≤ 15 tool steps and ≤ a pence budget per job (default 25p), read tools free to use, outward tools only produce cards. On finish it posts a `job_update` message into the conversation and sends a push.
- The owner sees running jobs in the chat ("Working on: drafting replies to 6 enquiries — 3 done") and can cancel.
- Recurring asks ("every Friday…") are jobs with a schedule; each run is charged to the allowance; the owner can list and stop them by asking or in Settings.

### 5.7 Allowance, credits and top-ups

- A new meter `aria_ai` on `usage_meters`, counted in **AI pence** from `ai_costs` (true cost), shown to the owner as **messages left** (a "message" = 1 credit ≈ an average turn's cost, e.g. 2p; the conversion is one constant so we can re-price without migration).
- Allowance per tier per month (D6 for numbers). When the allowance is used up: read-only answers that cost nothing (cached brief, lists) still work; new AI turns ask the owner to top up; nothing is cut off mid-turn.
- **Top-ups bought on the website** (Stripe, existing billing in `backend/app/billing`), never inside the iOS/Android app, so Apple/Google take no cut (App Store guideline 3.1.3(b), multiplatform services). The app doesn't link to or advertise the web purchase (Apple's rule); it says "You've used this month's messages".
- `profit_guard` kill switch still pauses non-essential AI platform-wide.

### 5.8 Push notifications

- `push_devices` (id, business_id, user_id, platform `ios|android|web`, token, created_at, last_seen_at, disabled_at). Backend-only.
- iOS via APNs and Android via FCM through Capacitor's PushNotifications plugin; installed web app via Web Push (VAPID). iOS web push works only once the web app is added to the Home Screen (iOS 16.4+), which is fine for the beta.
- Sent for: morning brief ready, job finished, a card waiting, an urgent email or missed call (ARIA-PROACTIVE rules). Quiet hours per user. Generic wording, no figures or customer text (§2).

### 5.9 The app (installable web app → App Store / Google Play)

- **Web install first:** web app manifest + service worker (icons, splash, offline cache of the shell) on the existing Vercel frontend. Mike and testers add it to the Home Screen.
- **Stores straight after:** refresh the Capacitor shell, build the same web bundle into it, add camera/photos permissions with plain-English reasons, push, and app icons/splash.
- Store requirements we must meet:
  - **Not just a website in a wrapper** (Apple 4.2): native push, camera, offline cache and the messenger itself cover this.
  - **Account deletion inside the app** (Apple 5.1.1(v)): a "Delete my account" flow that starts real deletion, not just a link to email support.
  - **Disclosing AI and third-party AI processing** to users with consent before personal data is sent to an outside AI provider (Apple's guidelines as updated in 2025; Google's AI-generated content policy): one clear screen at first launch, recorded.
  - **Privacy labels / Data safety form** matching what we actually collect (emails, financial data, photos, contacts).
  - **Reporting offensive AI output** in-app (Google Play AI policy): a "Report this reply" action on Aria's messages.
  - **Reviewer test account** with demo data (a seeded demo business), since reviewers can't connect Xero/Gmail.
- **Mike's accounts (start now, they take time):** Apple Developer Program as an **organisation** (needs a D-U-N-S number for the company, which can take days to weeks) and a Google Play Console **organisation** account (a new *personal* Play account must first run a closed test with at least 12 testers for 14 days before it can publish; an organisation account avoids that).

### 5.10 Security review points (for Codex to attack)

- Signed URL lifetime and tenant check on every attachment read; no public bucket.
- Upload limits: images only for quotes (JPEG/PNG/HEIC/WebP), ≤ 10 MB each before downscale, ≤ 5 per message; files (PDF/DOCX) for "read this" requests ≤ 10 MB.
- Prompt injection from emails, call transcripts, documents and image text: these are passed as quoted data; the outward-action boundary (cards) is the hard control; a test per outward tool proves an injected instruction yields at most a card.
- Background jobs can't approve cards, can't change settings, can't rename the assistant, can't connect or disconnect providers, can't exceed budget.
- Drive scope minimisation; disconnect revokes the token at Google/Microsoft.
- Push tokens deleted on logout and on repeated delivery failure.

## 6 · Tickets (each its own branch, builder ≠ reviewer, `./check.sh full`, Codex review cycles)

| # | Ticket | Contents | Risk | Band | Depends on |
|---|---|---|---|---|---|
| MSG-1 | Messenger core | `/m` route, conversation list, streaming endpoint, rich message kinds, chips, offline queue, migration 047 | RED (migration) | L | 046 on prod |
| MSG-2 | Rename the assistant | setting, validation, prompt/UI/cards/receptionist greeting | AMBER | S | — (parallel with MSG-1) |
| MSG-3 | Installable web app | manifest, service worker, icons; Mike's beta begins here | GREEN | S | MSG-1 |
| MSG-4 | Photos → draft quote | attachments + storage, router-based vision quote, draft save, reviewed flag | RED (storage, migration) | M | MSG-1 |
| MSG-5 | Allowance and top-ups | `aria_ai` meter, tier allowances, web top-ups, messages-left UI | RED (billing) | M | MSG-1 |
| MSG-6 | Push + morning brief | `push_devices`, APNs/FCM/Web Push, brief in messenger, retire WhatsApp pulse per business | AMBER | M | MSG-3 |
| MSG-7 | App store release | Capacitor refresh, permissions, account deletion, AI consent screen, report-a-reply, demo business, store listings, TestFlight / Play internal test | AMBER | M | MSG-3, MSG-6, Mike's accounts |
| MSG-8 | Documents + Google Drive | `business_documents`, create/edit/download, Drive connection (`drive.file`), save-to-Drive cards, quote PDF to Drive after review | RED (OAuth, migration) | L | MSG-1, MSG-4 |
| MSG-9 | Background jobs | `aria_jobs`, worker with claims and budgets, recurring asks, job messages, cancel | RED | L | MSG-1, MSG-5, MSG-6 |
| MSG-10 | OneDrive | Graph Files scope, same cards | AMBER | M | MSG-8 |

**Order and parallelism:** MSG-1 and MSG-2 start together (different files). Then MSG-3 (beta), MSG-4 and MSG-5. MSG-7 starts as soon as MSG-6 is in, so the store submission isn't waiting on documents or jobs; MSG-8/9/10 ship as app updates. Migrations go one at a time: 047 (MSG-1), then MSG-4's, MSG-5's, MSG-8's, MSG-9's, in that order.

**Other in-flight work that comes first or alongside:** 046 on production and PR 118; HK-3 (PR 119); VOICE-MIG before 6 Jan 2027 (tts-1 retires; whisper-1 on 26 Feb), which also unlocks voice notes in the messenger later; AI-1e (Responses API), which unlocks cheap-model tool use for §5.2.

## 7 · Decisions for Mike

- **D1 — The messenger's place:** a new `/m` route that opens straight into chat on phones (recommended), while desktop keeps the current dashboard with the messenger one click away. Or chat-first on desktop too.
- **D2 — Conversation threads:** several titled conversations like ChatGPT/Grok (recommended), or one continuous thread like WhatsApp.
- **D3 — Tasks:** today `create_task` is an approval card. Recommended: internal, reversible things (task, internal document, draft quote) happen directly with an **Undo** on the message; only outward things are cards. Or keep task cards.
- **D4 — Save to your own Drive:** recommended as a one-tap card the first time per document, with an "always allow saving to my Drive" setting. Or always direct.
- **D5 — OneDrive folder:** the app folder (`Apps/Business Hero`, narrowest permission, recommended) or a top-level "Business Hero" folder (needs full Files permission).
- **D6 — Allowances and top-up price:** proposed starting point, to be tuned from beta data: Starter 300 messages/month, Pro 1,500, Business 4,000; top-up 250 messages for £5. Morning briefs don't count against the allowance.
- **D7 — WhatsApp briefings:** switch off per business once the messenger brief is on (recommended), or keep both for a period.
- **D8 — Store name:** "Business Hero" for the app, with the assistant's name inside it (recommended), or the assistant's name in the store title.

## 8 · Risks

- **Store review delays** (first submissions are often rejected once). Mitigation: §5.9 checklist before submitting; TestFlight and Play internal testing first.
- **AI cost** above allowance assumptions. Mitigation: metering from day one, caching, downscaling, budgets on jobs, `profit_guard`.
- **Google OAuth verification** for the new Drive client. `drive.file` is a non-sensitive scope, but the app's consent screen and privacy policy must be up to date; verification can take days.
- **Prompt injection** via emails and documents. Mitigation: §2 and §5.10; outward actions always cards; tests.
- **Scope creep**: each ticket keeps its own acceptance criteria; anything new is a new ticket, not a bigger one.
