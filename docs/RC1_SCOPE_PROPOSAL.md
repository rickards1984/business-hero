# RC1 scope proposal — which parts of North Star Phase 1 belong in RC1

**Status:** revision 2, after Codex review 1 (REQUEST-CHANGES,
`docs/reviews/aria-gap-analysis-codex-review.md`) and Michael's decisions of
28 September 2026 (`docs/decisions/0001-north-star-rc1-decisions.md`).
**Accepted by Michael, 28 September 2026, including D11–D14.** Folded into
`docs/RC1_SCOPE.md` § North Star Phase 1 stream, which is now the
authoritative scope; this file keeps the reasoning.
**Evidence:** `docs/ARIA_GAP_ANALYSIS.md` (cited as GA §x).
**Serves:** Phase 0 — "write an RC1 scope proposal for Michael to decide on".

---

## The test

An item goes into RC1 only if it passes all three:

1. **Security.** It does not delay or compete with the security sequence —
   030b Release 2, 033 STEP 21, the BH-001 §6 findings, and the P0 list. It
   adds no migration while one is in flight, and no new unscoped data path.
2. **Stability.** It wraps working code rather than rebuilding it, adds no new
   model-provider operation, and can ship without breaking the existing UI.
3. **Timeline.** It does not push the design-partner release. **No
   design-partner date is recorded in the repository**, so timeline is judged
   by size and by what an item displaces, not against a date.

"No migration" is necessary, **not sufficient**: an item can still contend
for a shared file (`backend/main.py`, where routers are registered at `:412`
onward) or for the model-call interface P0-2 metering needs (Codex review 1,
finding 7). §D sequences those explicitly.

---

## Summary

| | Item | Effort | In RC1? |
|---|---|---|---|
| **A1** | Aria stops acting on her own: all five model-triggered mutations refused **at the server**, in chat and voice | **M** | **Yes — first** |
| **A2** | Establish whether voice works; if not, **disable it server-side** for RC1 | S | **Yes** |
| B1 | Two-tenant and grounding tests over Aria's tools, by tool class | **L** | **Yes** |
| B2 | Tool registry, with citation contracts for record-level tools | L | **Yes** |
| B3 | Model router, request/response calls (already RC1 P1-1) | L | **Yes, as P1** |
| B4 | One Aria persona across chat, voice and board meeting | M | **Yes** |
| **B9** | *(D10)* Owner can rename Aria, choose her voice with a preview, pick one of 2–3 avatars — in settings and onboarding; Aria is the default | M | **Yes, after B4** |
| **B10** | *(D9)* Aria drafts an email or chase; the owner approves with a tap; Aria sends it once, signed with her name | **L** | **Yes, after A1** |
| **B11** | *(D8)* Opening the app refreshes email, accounting and calendar in the background, with "updated N minutes ago" everywhere | M | **Yes** |
| B5 | Unified task view — read-only, backend-served, normalised statuses | **L** | **Yes, conditional** |
| B6 | Board Meeting one tap from home, out of AI Hub | S | **Yes** |
| B7 | Aria home v1 — deterministic briefing, talk bar, tiles, task list | **L × 2** | **Yes, conditional, last** |
| B8 | Text dock, no screen context | M | **Optional** |
| — | Aria Core orchestrator (full), memory, standing permissions, proactive feed, voice on Core, text streaming, department summary strips, dock with screen context, tasks with assignee | — | **No — Phase 2** |

Revision 2 raised A1 (S→M), B1 (M–L→L), B5 (M→L) and B7 (L→L × 2), per
Codex review 1. Those are review estimates, not measurements.

---

## A · Before Phase 1: safety, not features

### A1 · Aria stops acting on her own

Aria can send email, send invoice chases and create calendar events on the
model's own decision, and can create and soft-delete tasks (GA §B2, §B6).
Voice can do it on a misheard sentence, and the voice socket forwards any
client message to the model verbatim and executes unmapped tool names
(GA §A5).

**Removing tools from the advertised lists is not enough** (Codex review 1,
finding 1). A1 requires:

- **Server-side refusal at both execution boundaries** — chat's
  `_execute_tool_async` / `execute_tool` path (`assistant_chat.py:19`, `:802`)
  and voice's executor (`realtime_voice.py:280`) — via an allowed-tool check,
  so a prohibited name is refused even if the model or the client supplies it
  directly.
- **All five mutations covered:** `send_email`, `send_invoice_chase`,
  `create_calendar_event`, **and** `create_task`, `delete_task`. Phase 1 says
  "no write actions"; retaining the task writes would be an exception
  Michael has not granted (Codex review 1, finding 2; decision D11 below).
- **Voice: stop forwarding arbitrary client messages** to the model session;
  forward only audio and the known control messages.
- **Tests** that call each prohibited tool directly, through both paths, and
  assert no email, calendar or database mutation happens.
- No new model call.

**M.** P4, P8; Phase 1. B10 then adds back sending, safely.

### A2 · Find out whether voice works, and disable it server-side if not

`realtime_voice.py` still speaks the Realtime Beta protocol, which the
receptionist's code records as removed on 12 May 2026 (GA §A5). One test
session settles it. If it is broken, disable it **before the provider
connection opens** — a server-side switch checked in the handshake, matched
by the UI — not by hiding a button, because an entitled account can connect
to `/v1/realtime/voice` directly (Codex review 1, finding 5). If the switch is
a `businesses` flag or entitlement change, that part is RED. Repair (GA
migration, M) waits for P0-2 metering. **S.** Decision D2, accepted.

---

## B · Phase 1 items for RC1

### B1 · Tests first: isolation and grounding, by tool class

Extend BH-003's two-tenant harness to Aria's tools, split by class (GA §B2):

- **Database reads** — two-tenant isolation, and grounding: seeded rows, the
  tool's figures equal the database's, to the penny for money.
- **External-provider reads** (Gmail, Microsoft, Google Calendar, Xero) —
  deterministic provider fixtures; assert the right account is selected for
  the business and nothing else's data is returned.
- **Generative tools** (`generate_ai_quote`, `draft_email_reply`) — not
  "grounded"; their output is an estimate, and P2/P8 require it be presented
  as one.
- Chat's async wrapper paths and voice's name map are included.

The claim this earns is **"no cross-tenant read in the tested cases"**, not
"no leak, proven". **L.** P2, P9; Evals.

### B2 · Tool registry and citation contracts

Declare each tool's class (read / external read / generative / write), its
department and its result shape. For record-level tools, return the ids
behind each figure. **Aggregates need their own contract** — a count or sum
does not carry its contributing ids, so each aggregate states whether it
cites a query, a page of ids, or nothing yet (Codex review 1, finding 9). **L.**
P2; Tool layer.

### B3 · Model router — request/response only

RC1 P1-1. Sequence it before B4 so the persona change lands on the router.
Chat and board meeting first; preserve the board meeting's existing token
accounting and per-meeting cap (GA §A7). Coordinate its interface with P0-2
metering, which needs the same hook. OpenAI only until the provider question
is settled (D6). Realtime sockets later. **L.** P7, P9.

### B4 · One Aria persona

One persona block composed into chat, voice and board meeting; name her in
chat; remove "round numbers naturally"; remove the WhatsApp prompts' emoji
instructions; stop labelling templated accounting text "Aria's Financial
Insights" and remove its client-side fallback. The name comes from one place
so B9 can change it. Before/after transcripts on the seeded business. **M.**
P3, P2, P8.

### B9 · Aria's name, voice and avatar *(Michael's D10)*

Settings page and an optional onboarding step: rename, choose a voice with a
preview, choose one of 2–3 bundled avatars. "Keep Aria" is the default and a
single tap. Stored in `business_settings.settings` (JSONB, exists — no
migration). Voice choice reuses the receptionist's presets and preview
(`services/voice_presets.py`, `receptionist_api.py:612`); Aria's voice is one
global setting today (`realtime_voice.py:19`), so per-business voice is new
and only matters once A2 is resolved. Avatars are licensed illustrations, no
uploads. The chosen name flows into prompts (B4) and the email sign-off
(B10). **M.** P3; resolves North Star open question 2.

### B10 · Draft, approve with a tap, Aria sends *(Michael's D9)*

Brings Phase 2's first approval card forward for two actions: an email reply
and an invoice chase.

- Aria drafts; the draft is stored (`email_drafts` exists with `status`,
  `subject`, `body_text`, `to_emails`; grants and RLS to be checked).
- "Send it" shows the final draft with a Send button. **The tap is the
  approval** — never a model's reading of "yes", never a voice transcription.
- The server sends only a draft in `approved` status, exactly as approved,
  **once** (the draft id is the idempotency key). An edit returns it to
  draft.
- Signed with Aria's name (or the B9 name), in a form that does not pass her
  off as a person; whether it says "AI assistant" is decision D12.
- Every send recorded in `email_outbox` against the draft and approving user.
- Invoice chases keep the existing chase templates.
- Do **not** reuse `whatsapp_pending_actions` as-is: it executes before
  marking the action executed and has no expiry check (GA §B6).

Money-adjacent customer contact: **tests first, reviewed by Michael.**
**L.** P4, P8.

### B11 · Fresh data on open *(Michael's D8)*

On app open, each connected source refreshes **in the background** if stale;
nothing blocks the app. Email already does this (`POST /v1/email/sync/ensure`,
`app/email/router.py:917`); extend the pattern to accounting and calendar.
`/v1/accounting/sync-all` (`main.py:4598`) runs synchronously and must not be
what opening the app waits on. Every figure — tiles, home, Aria — carries
"updated N minutes ago", and a failed sync is shown (the `data_quality`
pattern, extended beyond financials). Calls need nothing: the receptionist
writes them live. Bounded by the existing `LIMIT_SYNC` rate limit. **M.** P2.

### B5 · Unified task view — conditional

A backend endpoint returning `tasks` ∪ open `executive_meeting_action_items`.
Admitted to RC1 **only with** (Codex review 1, finding 4):

- active-membership resolution and the **board-meeting entitlement** the
  action-item endpoint enforces today (`executive_meeting_api.py:257`) —
  action items are hidden, not leaked, for tiers without board meetings;
- **status normalisation** — `done` / `completed` / `pending` / `open` /
  `in_progress` / `blocked` / `deferred` mapped explicitly, fixing the
  present defect that API-completed tasks never count as completed in board
  meetings (GA §A4);
- deleted tasks filtered; each row carries a source discriminator and source id;
- a **tenant-scoped Aria read tool** for the same data (the new AGENTS.md rule);
- two-tenant tests.

Serving it from the backend does not fix BH-001's `tasks` policy; that stays
in the security sequence. **L.** Tasks; Phase 1.

### B6 · Board Meeting out of AI Hub

The route exists (`/app/board-meeting`). Add it to `Sidebar`,
`MobileBottomNav` and home. **S.** P1.

### B7 · Aria home v1 — conditional, last

Composed from existing pieces, **with the loader gaps closed first** (Codex
review 1, finding 3):

- **Briefing — deterministic, with grounding verified by tests** (not
  "grounded by construction"). The prep loaders do not yet provide what home
  needs: the quotes loader returns period aggregates, not open quotes
  (`quotes.py:50`, `:98`); the tasks loader returns open/overdue counts, not
  tasks due today (`tasks.py:94`). Those loader extensions, the B5 status
  normalisation, and per-source missing/stale handling (B11) are part of B7.
- Talk/type bar → existing chat. Department tiles → existing KPI queries,
  moved behind the backend. Task list → B5. Board Meeting tile → B6. Avatar
  and name → B9.
- No approval cards on home in RC1; B10's card lives in chat.
- Any record id a tile or citation passes back is re-checked against the
  resolved business on the server.
- Mobile-first.

Admitted if capacity remains after the P0 commitments. **L × 2.** P1, P2.

### B8 · Text dock — optional

A dock in `AppShell` opening existing chat on every page, no screen context.
**M.** P1.

---

## C · What waits, and why

| Item | Why not RC1 |
|---|---|
| Full Aria Core orchestrator | L × 2 minimum and re-plumbs the chat path customers use. B2–B4 are the parts RC1 can take |
| Cached business snapshot | Scope and freshness complexity, not schema: `briefing_snapshots` can plausibly hold it without a migration (GA §B3). B7 uses the loaders live |
| Memory | Migration, and the highest P9 exposure of any pillar (GA §B4) |
| Standing permissions, full action queue, audit trail | B10's single approval path is enough for RC1 |
| Proactive "Aria noticed" feed | In-process scheduler; unmetered model spend |
| Voice on Core, British voice | Depends on Core, P0-2 metering and open question 4 |
| Text streaming | Retrofitting the current loop is wasted work; do it in Core |
| Department summary strips | Each is a new Aria-facing figure with its own grounding test |
| Dock with screen context | Needs server re-checked record ids and Core |
| Tasks with assignee | Migration |
| AI Hub fully dissolved | Touches Receptionist and Booking; moves only, after RC1 |

---

## D · Build order

The security sequence is unchanged, goes first, and owns the migration slot.
The North Star stream runs **beside** it and must have its own builder
capacity — if the same agent would otherwise be on a P0 ticket, the P0 ticket
wins.

```
SECURITY (unchanged; owns the migration slot)
  030b Release 2 apply ─► 033 STEP 21 ─► BH-001 §6 follow-ups ─► remaining P0s

NORTH STAR (no migrations, no new provider operations)
  A2 voice check ─────────────┐
  A1 server-side refusal ─────┼─► B10 draft → tap → send
                              ▼
  B1 tool tests ─► B2 registry ─► B4 persona ─► B9 name/voice/avatar
          B3 router ─────────────────┘
  B11 fresh on open ─┐
  B5 task view ──────┼─► B7 home v1 ─► B8 dock (optional)
  B6 board nav ──────┘
```

Shared resources, serialised explicitly:

- **`backend/main.py`** holds the chat endpoint (B3, B4), `/v1/accounting/sync-all`
  (B11) and every router registration (`:412` onward). New endpoints go in
  their own modules, but **each new router's one-line registration is a
  `main.py` change**, sequenced against whichever P0 ticket holds the file.
- **The model-call interface** — B3 and P0-2 metering both change it; one
  design, agreed before either lands.
- **`assistant_tools.py`** — A1, B1, B2, B5's read tool and B10 all touch it;
  one ticket at a time.

---

## E · Decisions

### Accepted by Michael, 28 September 2026 (ADR 0001)

D1 (Aria stops acting on her own — now server-side and covering all five
mutations, above), D2 (voice off if broken, repaired after metering — now
server-side), D3 (Phase 1 stream beside security), D4 (deterministic home
briefing), D5 (amend P9's wording — Michael's to make), D6 (OpenAI only until
legal review), D7 (remaining isolation work is BH-001 §6), D8 (fresh data on
open → B11), D9 (approve-then-send → B10), D10 (name, voice, avatar → B9).

### Decided after revision 2

| # | Decision | Recommendation |
|---|---|---|
| ~~D11~~ | Aria's task writes | **Decided by Mike, 28 Sep:** `delete_task` refused; `create_task` goes through B10's tap-to-approve card |
| ~~D12~~ | Sign-off says "AI assistant" | **Decided by Mike, 28 Sep:** yes. Confident, and says she passes messages on to the owner (ADR 0001 D9) |
| ~~D13~~ | Revision 2's estimates and conditions | **Decided by Mike, 28 Sep:** accepted. Mike rates the Aria-centred UI (B7) as worth the doubled time — it is not a casual drop; only B8 is optional |
| ~~D14~~ | Receptionist takes Aria's chosen name | **Decided by Mike, 28 Sep:** no, not in RC1. Rename-the-receptionist option added once there are users (backlog) |
