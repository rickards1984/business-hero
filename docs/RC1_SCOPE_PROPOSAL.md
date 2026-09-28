# RC1 scope proposal — which parts of North Star Phase 1 belong in RC1

**Status:** proposal, for Michael's decision. **This does not change
`docs/RC1_SCOPE.md`.** Scope is Michael's call; nothing here is applied until
he says so, and Codex has been asked to check it
(`docs/reviews/REVIEW_REQUEST_aria-gap-analysis.md`).
**Written:** 28 September 2026, by Claude Code.
**Evidence:** `docs/ARIA_GAP_ANALYSIS.md` (cited as GA §x).
**Serves:** Phase 0 — "write an RC1 scope proposal for Michael to decide on".

---

## The test

An item goes into RC1 only if it passes all three:

1. **Security.** It does not delay or compete with the security sequence —
   030b Release 2, 033 STEP 21, the BH-001 findings, and the P0 list. It adds
   no migration while one is in flight, and no new unscoped data path.
2. **Stability.** It wraps working code rather than rebuilding it, adds no new
   direct model-provider call, and can ship behind the existing UI without
   breaking it.
3. **Timeline.** It does not push the design-partner release. **The
   design-partner date is not recorded anywhere in the repository**
   (`docs/PRODUCT.md:21` and `RC1_SCOPE.md:29` name the partners, not a date),
   so this proposal judges timeline by size and by what it displaces, not
   against a date. If there is a date, it may move items below the line.

---

## Summary

| | Item | Effort | In RC1? |
|---|---|---|---|
| **0** | Stop Aria acting outside the app (remove or draft-only `send_email`, `send_invoice_chase`, `create_calendar_event` in chat and voice) | S | **Yes — first** |
| **0** | Establish whether Aria voice works in production; if not, turn it off for RC1 | S | **Yes** |
| 1 | Two-tenant and grounding tests over Aria's existing read tools | M–L | **Yes** |
| 2 | Tool registry with citation ids on existing read tools | L | **Yes** |
| 3 | Model router, request/response calls only (already RC1 P1-1) | L | **Yes, as P1** |
| 4 | One Aria persona across chat and board meeting | M | **Yes** |
| 5 | Unified task view — read-only, backend-served, no migration | M | **Yes** |
| 6 | Board Meeting one tap from home, out of AI Hub | S | **Yes** |
| 7 | Aria home v1 — deterministic briefing, talk bar, tiles, task lists | L | **Yes, last** |
| 8 | Text dock, no screen context | M | **Yes, if time** |
| — | Aria Core orchestrator (full), cached snapshot, memory, actions/approvals, proactive feed, voice on Core, streaming, department summary strips, dock with screen context, tasks with assignee | — | **No — Phase 2** |

Everything marked "yes" needs **no migration and no new provider call site**.
That is the line.

---

## A · Before Phase 1: two items that are safety, not features

These pass the prerequisite test on their own — they are correctness and
trust work — so they belong in RC1 whatever else is decided.

### A1 · Stop Aria acting outside the app

Aria can send email, send invoice chases and create calendar events **on the
model's own decision**; the only guard is an instruction in the prompt
(GA §B2, §A5). Voice can do it on a misheard sentence. The chase path already
has no idempotency key (`CURRENT_STATE.md` §7), so a retried tool call can
chase a customer twice about money.

**Proposal:** remove the three tools from `TOOL_DEFINITIONS` and
`REALTIME_TOOLS`, or make each return a draft plus "open it in Invoices /
Inbox to send", as `send_quote` already does (`assistant_tools.py:2838`).
Keep `create_task` / `delete_task` — they write inside the app and are
reversible. **S.** P4, P8; Phase 1's "Aria takes no write actions yet".

**Cost:** a live capability goes away. If MSC relies on "Aria, chase that
invoice", they will notice. That is decision D1.

### A2 · Find out whether voice works

`realtime_voice.py` still speaks the Realtime Beta protocol that the
receptionist's own code records as removed on 12 May 2026 (GA §A5). One test
session settles it. If it is broken: turn `aria_voice` off in the UI for RC1
and schedule the GA migration (M) **after P0-2 metering**, because voice is
the most expensive unmetered endpoint in the product. Repairing it before
metering reopens the "£400 of voice on a £129 plan" risk
(`RC1_SCOPE.md` P0-2). **S** to check; decision D2.

---

## B · Phase 1 items proposed for RC1

### B1 · Tests first: two-tenant and grounding tests over Aria's read tools

Extend BH-003's two-tenant harness (`test_tenant_isolation_backend_path.py`)
to every read tool in `assistant_tools.py`, and add grounding tests: seed
known rows, call the tool, assert its figures equal the database values to
the penny. No test currently imports any Aria module (GA §B10).

Why it is in RC1: it is **tenant-isolation work** (P0-9 extended to the path
that reads the most data) as much as North Star work, and it is the evidence
Gate 7 will demand of every later Aria change. It also converts "no leak
found by reading" (GA §A8) into "no leak, proven". **M–L.** P2, P9; Evals.

### B2 · Tool registry with citation ids

Declare each tool read or write, its department and its result shape; make
every read tool return the ids of the records behind each figure. No new data
is read. This is the smallest step toward "tap a figure to see the records"
(§2) and the precondition for citations in Core. **L.** P2; Tool layer.

### B3 · Model router — request/response only

Already **RC1 P1-1**. Proposal: keep it P1, but sequence it before B4 so the
persona change moves chat onto the router instead of editing a direct call.
Start with chat and board meeting; migrate the other request/response sites
as they are touched. Leave the two realtime WebSockets for later — they need a
different interface. The router is where a provider allow-list goes, which is
the only way P9's "covered providers only" becomes enforceable. **L.** P7, P9.

### B4 · One Aria persona

One persona block composed into chat, voice and board meeting; name her in
chat (she is currently unnamed, GA §A1); remove "round numbers naturally";
stop labelling templated, emoji-laden accounting text "Aria's Financial
Insights" and remove its client-side fallback (GA Headline 7). Capture
before/after transcripts on the seeded business. **M.** P3, P2, P8.

### B5 · Unified task view

A backend endpoint returning `tasks` ∪ open `executive_meeting_action_items`,
scoped by `business_id`, with a two-tenant test. **No migration** — "Aria's
vs yours by assignee" waits for Phase 2. Served from the backend on purpose:
the dashboard currently reads `tasks` through supabase-js, and BH-001 found
inactive members can still read `tasks` on that path (GA §A4). **M.** Tasks;
Phase 1.

### B6 · Board Meeting out of AI Hub

The route already exists (`/app/board-meeting`). Add it to `Sidebar` and
`MobileBottomNav` and to home; keep the AI Hub tab for now. **S.** P1, §5.

### B7 · Aria home v1

A new home that composes existing, working pieces:

- **Briefing** built **deterministically** from the `prep_data` loaders —
  overdue invoices, open quotes, missed calls, tasks due — with no model
  call. That keeps it grounded by construction, costs nothing per page load,
  and adds no provider call site. `data_quality` shown when a source is
  missing or stale (P2).
- **Talk/type bar** → existing chat.
- **Department tiles** → the existing dashboard KPI queries, moved behind the
  backend.
- **Two task lists** → B5 (one list until assignee exists).
- **Board Meeting tile** → B6.
- **No approval cards** — nothing to approve until Phase 2.

Mobile-first from the start (§5). **L.** P1, P2; Phase 1.

### B8 · Text dock, if time allows

A dock in `AppShell` that opens existing chat on every page. **Without screen
context in RC1**: passing a record id from the client is a lookup-by-id that
must be re-checked against the resolved business, and doing that properly
belongs to Core. **M.** P1.

---

## C · What should wait, and why

| Item | Why not RC1 |
|---|---|
| Full Aria Core orchestrator | L × 2 minimum, and it re-plumbs the chat path customers use. B2–B4 are the parts of it RC1 can take safely |
| Cached business snapshot | Needs storage → migration → RED, queued behind 030b. B7 uses the loaders live instead |
| Memory | Migration, and the highest P9 exposure of any pillar (GA §B4) |
| Actions, approvals, permissions | Migration + audit trail; nothing needs approving once A1 lands |
| Proactive "Aria noticed" feed | Migration; in-process scheduler; unmetered model spend |
| Voice on Core, British voice | Depends on Core, metering (P0-2) and open question 4 |
| Streaming replies | Retrofitting the current loop is wasted work; do it in Core |
| Department summary strips | Each is a new Aria-facing figure needing its own grounding test; one per department is Phase 2 |
| Dock with screen context | Needs Core's server-side re-check of the record id |
| Tasks with assignee | Migration |
| AI Hub fully dissolved | Moves only, but touches Receptionist and Booking, which carry the `me.id` question (GA §C5). After RC1 |

---

## D · Build order

The security sequence is unchanged and goes first. North Star work runs
**alongside** it, never in front of it, and never takes the migration slot.

```
SECURITY (unchanged, owns the migration slot)
  030b Release 2 apply ─► 033 STEP 21 ─► BH-001 follow-ups ─► remaining P0s
                                        (anon views, TRUNCATE,
                                         inactive-member policies)

NORTH STAR (no migrations, no new provider sites)
  A1 stop external actions ─┐
  A2 voice check           ─┤
                            ▼
  B1 tool tests ─► B2 registry + citations ─► B4 one persona
                         B3 router ─────────────┘   │
  B5 task view ─┐                                    │
  B6 board nav ─┴─────────► B7 home v1 ◄────────────┘
                                 │
                                 └─► B8 text dock (if time)
```

- **A1 first**, because it is the only item that reduces a live risk.
- **B1 before any new tool**, so every later change has a test to meet.
- **B3 before B4**, so the persona change lands on the router.
- **B5 and B6** are independent and can run beside B1–B4 with a second agent.
- **`backend/main.py` is a hot spot** (`AGENTS.md` §7): the chat endpoint
  lives there, and so do P0-1's and P0-6's endpoints. New Aria endpoints go in
  their own router module, and B3/B4 are sequenced against whichever P0
  ticket holds `main.py`.

---

## E · Decisions for Michael

| # | Decision | Recommendation |
|---|---|---|
| D1 | Remove Aria's ability to send email, chase invoices and book events (A1), accepting that a live capability goes away | **Yes.** Make them draft-and-hand-off. Unapproved customer contact about money is the P8 failure the North Star exists to prevent |
| D2 | If voice is broken, turn it off for RC1 and repair after metering | **Yes.** Do not repair unmetered voice first |
| D3 | Accept B1–B7 (and B8 if time) into RC1 as a Phase 1 stream running beside the security sequence | **Yes**, with the line "no migration, no new provider call" as the entry test |
| D4 | Home briefing is deterministic (no model call) in RC1 | **Yes.** Grounded by construction, free per load |
| D5 | P9 wording: "enforced by RLS" is not achievable on the backend path without re-architecting database access (GA §E1) | **Amend** to "enforced by business scoping, tested per tool, and by RLS on the client path" |
| D6 | Which model providers are acceptable for UK customer data (open question 5) | **Settle before B3 adds any second provider.** Until then the router allows OpenAI only |
| D7 | The North Star names "RLS batches 4–5" as outstanding security work; BH-001 found 56 of 58 tables already RLS-on in production | **Confirm** that the remaining isolation work is the BH-001 §6 findings, so the sequence names real tickets |
