# Codex review — Aria gap analysis and RC1 scope proposal

| | |
|---|---|
| Reviewed commit | `2b54b546cf7dabb39a92107825f15413192a106f` (`docs/north-star-adoption`) |
| Code baseline | `main` at `2cc2b62` |
| Request | `docs/reviews/REVIEW_REQUEST_aria-gap-analysis.md` |
| Tool | Codex CLI 0.153.4, `codex exec --sandbox read-only`, prompt on stdin |
| Model | `gpt-6-astra` |
| Session id | `01a0ea0e-5fcc-7582-ba0a-bd23aa54e584` |
| Worktree | `~/dev/bh2-aria-review`, detached at the reviewed commit; reviewer made no edits |
| Usage, as reported | `tokens used 92,456` — the tool's figure, not a bill |
| **Verdict** | **REQUEST-CHANGES** |

The report below is **verbatim and stays unedited.** What was done about it
is recorded in the response section at the end.

---

**Verdict: REQUEST-CHANGES.**

The core diagnosis is supported: Aria has substantial existing tools, external actions lack enforced approval, and chat, voice and board meetings have separate orchestration. The proposal nevertheless needs corrections before approval. Most importantly, A1’s advertised-tool removal is not an execution boundary, retaining task writes contradicts Phase 1, and B7 assumes capabilities and correctness the existing loaders do not provide.

Reviewed read-only at `2b54b546cf7dabb39a92107825f15413192a106f`. The diff against `2cc2b62` contains documentation only, so the implementation inspected matches the stated code baseline. No files changed; no network, database, migrations or model calls used. `check.sh` was not run: this report establishes static evidence, not runtime verification. The North Star was treated as adopted authority, not reviewed for content.

**The 14 claims**

| # | Assessment | Evidence and qualification |
|---|---|---|
| 1 | **CONFIRMED**, with an architectural qualification | `backend/assistant_tools.py:33` contains 27 definitions; its shared executor starts at `:532`. Chat delegates to it at `backend/assistant_chat.py:189`; voice at `backend/realtime_voice.py:381`. However, chat’s `_execute_tool_async` at `assistant_chat.py:19` separately handles calendar availability, calendar creation, calendar listing and AI quote generation. “One dispatcher” must not imply that the shared executor handles all 27 tools. |
| 2 | **CONFIRMED** | Chat executes model calls at `assistant_chat.py:802`. Email sends at `assistant_tools.py:1442`, invoice chases at `:2499`, and calendar creation at `:1950`, reached through `assistant_chat.py:65`. Voice maps `send_email_reply` and `send_chase` at `realtime_voice.py:291` and `:302`. No confirmation state/token is checked on these paths. WhatsApp has a separate reply-driven action path; it does not guard chat or voice. |
| 3 | **CONFIRMED by static inspection** | No unscoped SQL read or cross-business join found in `assistant_tools.py`. The category join constrains both tenants at `:2140`; the Xero/business join at `:2332` joins the business primary key to the scoped integration’s business. Account-token updates at `:863` and `:913`, and invoice update at `:2515`, use identifiers obtained from scoped reads. This is not proof against all runtime isolation failures. |
| 4 | **CONFIRMED** | Chat resolves conversation/business at `assistant_chat.py:685`, `:705`, `:709`, then passes `business.id` at `:802`. Active membership is checked at `:478` and `:495`, subject to the explicit platform-admin exception. Voice resolves at `realtime_voice.py:667` and passes the captured server business at `:880`. Model arguments do not replace that business ID. |
| 5 | **UNVERIFIABLE FROM THE REPO** as an unconditional deployed-role claim | Use of `db.engine` is confirmed at `assistant_tools.py:12`. But `backend/db.py:14` selects an environment-provided connection URL; the code does not establish the connected role’s live privileges. Repository architecture records describe that role as elevated. Correct wording: “On the documented elevated backend connection, these tools bypass RLS; the code supplies no caller-role/JWT database context.” |
| 6 | **UNVERIFIABLE FROM THE REPO** for production failure; protocol mismatch **confirmed** | Beta header and session shape occur at `realtime_voice.py:721` and `:751`. The removal date is asserted in `receptionist_call_handler.py:48`, not independently demonstrated by executable code. “Suspected broken because it retains Beta protocol; production unverified” is justified. “Very probably broken” and “no reason to expect it to connect” overstate repository-only evidence. |
| 7 | **CONFIRMED** | Voice gates and fails closed at `realtime_voice.py:689` and `:695`. Chat calls its gate at `backend/main.py:2320`; `:2346` defines the helper. `CURRENT_STATE.md:361` and `:362` remain stale, although its new introductory note already acknowledges this. |
| 8 | **WRONG as a literal call-site count** | The table describes **19 grouped operations across 12 modules**, but **24 provider invocation expressions**: chat has two calls (`assistant_chat.py:758`, `:825`), and each preview operation has three TTS calls (`receptionist_api.py:614`, `:624`, `:633`, `:741`, `:755`, `:764`). The inventory omits the `tts-1` fallback within both preview rows. Ten distinct configured/default model names and four environment-selected model settings are supported. No additional provider or frontend model invocation was found. |
| 9 | **CONFIRMED** for the three named implementations | Independent aggregation exists in `executive_meeting_prep.py:52`, `briefing_data.py:17`, and `assistant_tools.py:717`/`:2718`. Only the first provides the described `data_quality`; its staleness calculation checks financials at `executive_meeting_prep.py:190`. This is not an exhaustive count: `main.py:2194` independently assembles another tasks/calls briefing. |
| 10 | **CONFIRMED** | `frontend/client/src/components/CeoBriefingTab.tsx:411` and `:573` implement WhatsApp configuration/history. This describes the tab, not the absence of a briefing backend: `main.py:2194` already exposes an in-app briefing source. |
| 11 | **CONFIRMED against the recorded schema** | `audits/live-schema-public.txt:754` lists the task columns without assignee; `backend/models.py:63` agrees. Explicit persisted assignment needs schema work under the proposed design. A normalized, read-only union does not inherently require a migration. The dump cannot establish subsequent live schema changes. |
| 12 | **CONFIRMED** | `Accounting.tsx:393` and `:403` call `buildProviderInsights()` on backend failure and display the resulting insights through the existing Aria panel. |
| 13 | **CONFIRMED** | Reference search finds no consumer of `pages/BusinessDashboard.tsx`; it alone imports `components/BottomNav.tsx` at `BusinessDashboard.tsx:66`. The routed shell uses `MobileBottomNav` at `components/AppShell.tsx:11`. |
| 14 | **CONFIRMED for the precise claim** | Repository test/spec searches found no imports or references to the five named modules. Avoid expanding this to “no AI-related tests whatsoever”; it establishes the missing coverage of these implementations. |

**Findings, most severe first**

1. **High — A1 does not specify an enforceable execution boundary.**

   `docs/RC1_SCOPE_PROPOSAL.md:65` permits removing tools from their advertised lists while leaving their implementations executable.

   Voice forwards arbitrary non-`config` client messages upstream at `backend/realtime_voice.py:838`. Its executor accepts unmapped names via `tool_name_map.get(tool_name, tool_name)` at `:310`, then calls the shared dispatcher at `:381`. Neither checks an allowed-tool registry. Chat likewise dispatches returned names directly at `assistant_chat.py:802`.

   **Correction:** require server-side rejection or draft-only handling at both execution boundaries, including chat’s async wrapper. Tool-list removal is supplementary. Add tests showing that prohibited calls cannot invoke email, calendar or database mutations even when supplied directly. Provider-dependent exploitation was not exercised, but absence of a server enforcement boundary is visible in the code.

2. **High — A1 conflicts with the adopted “no write actions” Phase 1 rule.**

   `RC1_SCOPE_PROPOSAL.md:68` explicitly retains `create_task` and `delete_task`. Those perform an insert and soft delete at `assistant_tools.py:648` and `:810`.

   **Correction:** disable those model-triggered mutations for Phase 1, or explicitly request a North Star exception from Michael. Approval of removing the three external actions is not approval of this separate exception.

   Also correct `ARIA_GAP_ANALYSIS.md` Headline 1: **three**, not seven, advertised tools perform the identified external actions. There are additionally two task mutations; `send_quote` is a hand-off, not a send.

3. **High — B7’s “working pieces” and “grounded by construction” claims omit observable loader gaps.**

   `RC1_SCOPE_PROPOSAL.md:142` promises open quotes and tasks due from existing prep loaders. The quotes loader returns issued/accepted period aggregates, not an open-quote list/count (`executive_meeting_data_loaders/quotes.py:50`, `:98`). The tasks loader returns open/overdue aggregates, not tasks due today (`tasks.py:94`).

   There is also a reproducible vocabulary mismatch: `main.py:1749` completes tasks as `done`, while the prep loader counts only `completed` at `tasks.py:73`. The frontend writes `completed` at `TasksPanel.tsx:120`. Deterministic output can therefore still be wrong.

   **Correction:** specify required loader extensions, status normalization and regression tests. Test the actual home data path, not only `assistant_tools`. Define missing/stale handling per source; current financial-only freshness cannot substantiate freshness across all home tiles. Replace “grounded by construction” with “deterministic, with grounding verified by tests.”

4. **High — The proposal omits entitlement and Aria-read requirements for the new unified task/home paths.**

   B5 at `RC1_SCOPE_PROPOSAL.md:126` introduces access to board-meeting action items. The existing endpoint applies `require_tier_feature(..., "executive_board_meeting", ...)` at `executive_meeting_api.py:257`. Business scoping alone does not preserve that gate.

   Meanwhile, the existing Aria task tool only reads `tasks`. The proposed endpoint adds data access without explicitly providing Aria the corresponding read tool, contrary to the adopted rule for new fetched data.

   **Correction:** require active-membership resolution, an explicit entitlement decision consistent with existing access, and a tenant-scoped Aria read interface. For union results, return a source discriminator plus source ID, normalize statuses and dates, and filter deleted tasks. B7 needs equivalent access and grounding acceptance criteria.

5. **Medium — A2 hides voice rather than disabling its backend exposure.**

   `RC1_SCOPE_PROPOSAL.md:78` says to turn voice off “in the UI.” An eligible account can still connect directly to `realtime_voice.py:634`; its existing entitlement gate does not constitute a global operational disable.

   **Correction:** if containment is the intended outcome, require a server-enforced disable before opening the provider connection, with matching UI state. Explicitly schedule any entitlement or `businesses` flag changes as RED work. Keeping repair behind P0-2 metering is reasonable.

6. **Medium — Existing token accounting is incorrectly described as absent.**

   `ARIA_GAP_ANALYSIS.md:280` says nothing records tokens, minutes or cost. Board meetings read provider usage at `executive_meeting_orchestrator.py:447`, persist a running total at `:899`, and reject further conversational turns at the meeting token cap at `:145`.

   **Correction:** distinguish existing meeting-level token accounting/caps from missing platform-wide monetary metering and plan allowances. B3 should preserve the former and coordinate with P0-2.

7. **Medium — The no-conflict build sequence overlooks router registration and metering dependencies.**

   `RC1_SCOPE_PROPOSAL.md:210` sequences B3/B4 against `main.py`, but placing B5/B7 endpoints in separate modules does not automatically register them. The application explicitly includes routers in `backend/main.py:412` onward.

   **Correction:** reserve a serialized router-registration change, or specify an already-registered router. B3 also touches model-call interfaces needed by P0-2 metering, even if neither modifies `main.py`.

   No admitted item inherently needs a migration or an additional model operation. However, “no migrations” does **not** establish resource independence, and draft-only A1 must not quietly add a new model call.

8. **Medium — Snapshot deferral rests on an unsupported mandatory-migration claim.**

   `RC1_SCOPE_PROPOSAL.md:170` says cached snapshots necessarily require migration. The recorded table already contains `business_id`, `created_at`, `full_data jsonb`, period bounds and `snapshot_type` (`audits/live-schema-public.txt:154`, `:158`, `:162`, `:169`). The scheduler already serializes aggregate data into `full_data` at `briefing_scheduler.py:631`.

   **Correction:** state that storage reuse is structurally plausible without migration. Retention, writer/read semantics, live constraints and isolation still need validation. This does not make snapshots mandatory for RC1; it removes the asserted schema necessity.

9. **Medium — B1/B2 overpromise universal database grounding and citations.**

   `RC1_SCOPE_PROPOSAL.md:91` asks every read tool’s figures to equal database values. Some read tools fetch Gmail, Microsoft, Google Calendar or Xero directly; `generate_ai_quote` obtains estimated prices from a model (`assistant_chat.py:137`). Those estimates are not business database facts.

   B2’s “no new data is read” at `:103` is also too strong: aggregate queries do not necessarily retrieve the contributing record identifiers. For example, the prep quote aggregates select only count/sum.

   **Correction:** classify database reads, external-provider reads and generative tools separately. Use deterministic provider fixtures for external tools; explicitly handle model-derived estimates under P2/P8. Define aggregate citation contracts, pagination and provider identifiers before committing to “every figure.” Replace “no leak, proven” at `:98` with a statement bounded to tested cases.

10. **Medium — Live-state certainty and the P9 recommendation need narrower wording.**

    `ARIA_GAP_ANALYSIS.md` Headline 1 asserts the action paths are live in production; §E5 calls voice a live defect. Neither deployment nor external API behaviour was established by this inspection.

    §E1 at `:656` correctly identifies a mismatch between the documented elevated connection and P9. However, caller JWT claims plus `SET LOCAL` are **one possible architecture**, not the only conceivable RLS design.

    **Correction:** describe the present connection model and the required architectural/security decision. D5 should present an explicit proposed change to an adopted requirement, not an unavoidable correction dictated by the code. Two-tenant tests do not provide the same enforcement mechanism as RLS.

**Repository-settleable UNVERIFIED items**

| Item | Resolution |
|---|---|
| `me.id` | **Business ID.** `useMe.ts:30` fetches `/v1/me`; `main.py:1330` assigns `id = business.id`, separately from `user_id`. Remove this concern from GA §C5 and the proposal’s deferral rationale. |
| WhatsApp persona | Neither weekly nor daily prompt names Aria. Both explicitly use emoji (`briefing_generator.py:40`, `:142`). Actual generated wording remains model-dependent. |
| Voice presence/waveform | Presence exists: animated orb and connection/listening/speaking indicators at `RealtimeVoice.tsx:324`, `:355`, `:386`. No audio-amplitude waveform was found. Narrow “no streaming anywhere” in GA §C6 to text chat: realtime voice forwards audio/transcript deltas at `realtime_voice.py:902`. |
| Quote views | `quotes.viewed_at` exists in the dump at `:654` and is serialized at `quoting_api.py:232`. No application writer or repeated-open event/count implementation was found. “Opened twice” is unsupported by the inspected implementation; presence of `viewed_at` alone does not prove tracking works. |
| Snapshot storage | The existing JSON storage can represent a snapshot; deployment constraints and safe reuse remain separate questions. |
| WhatsApp pending actions | A user’s numbered reply selects a business-scoped pending action and executes it (`whatsapp_briefing_api.py:516`, `:544`). It is a useful precedent, not a ready-made safe approval service: selection lacks an expiry predicate, and execution precedes marking the action executed at `:551`. Concurrent/repeated execution needs consideration before reuse. |
| Task statuses | Writers already disagree: backend `done`, frontend `completed`, frontend also `pending`. Board action loaders treat `open`, `in_progress`, `blocked`, `deferred` as outstanding (`goals_actions.py:190`). B5 must normalize them. |

Production model settings, provider terms, actual voice operation and current database privileges remain unverified. GA §D should also include `RECEPTIONIST_REALTIME_MODEL` among deployment-dependent settings.

**Additional isolation risks**

- Voice’s per-tool membership lookup catches all exceptions and proceeds with a fallback timezone (`realtime_voice.py:375`). Membership revoked during an established session does not fail closed at that point. Add a revocation test and an explicit session authorization policy.
- Client record hints require scoped lookup whether introduced by a dock, home tile or citation. That protection does not inherently require the full Core orchestrator.
- Backend-serving tasks does not repair existing permissive RLS policies or eliminate other direct client readers. BH-001 remediation remains necessary.
- A reused snapshot table needs tenant-scoped reads, cache keys and reviewed exposure of newly stored content. A new SQLModel table retains the documented boot-time `create_all()` risk; the GA already correctly flags that.
- External email/calendar access is bounded by the selected OAuth account’s permissions. Business-scoped credential selection does not independently prove ownership of every externally accessible shared resource.

**RC1 disposition and effort**

Keep A1, A2 and B1, with the corrections above. Keep B6 as the small navigation improvement. Keep B3 at its existing P1 priority and coordinate it with metering.

Make B5 conditional on normalized statuses, preserved authorization and an Aria read tool. Make B7 conditional on verified loader contracts and available capacity after P0 commitments. B8 can remain optional. Keep cached snapshots deferred if desired, but use scope/freshness complexity as the rationale.

I would revise these estimates:

- **A1:** S for narrow dispatcher-level denial; **M** for the proposed draft-and-hand-off behaviour plus chat/voice regression coverage.
- **B5:** **L**, rather than M, if it includes endpoint, normalized union, authorization, Aria access and tests.
- **B7:** **L × 2** is more credible than L for the stated backend movement, loader additions, grounding, missing/stale states and mobile home.
- **B1:** use **L** as the planning baseline; all-tool coverage includes external-provider fixtures and async wrapper paths.

These are review estimates, not repository-verifiable facts.

The proposal does **not explicitly deprioritise** 030b Release 2, 033 STEP 21, BH-001 or the P0 list. Its stated ordering protects them. What is missing is evidence that the parallel stream has independent capacity and files; correct the dependency map before claiming it cannot delay security.

Finally, GA §E’s five tensions are mostly useful but need qualification: the current RLS mismatch is real under the documented deployment; Phase 1 removes **five implemented mutations**, not merely three external actions; CEO Briefing has reusable backend machinery despite its settings-oriented UI; assignee-based tasks need schema work while the Phase 1 view does not; and voice is a **suspected stability defect**, not a verified production outage. None of these findings authorizes changing the adopted North Star.