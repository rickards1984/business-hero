# Backlog — STUB

**Status: stub.** Nothing is duplicated here; this is an index. Items become
tickets only when they enter a release scope.

| Horizon | Source |
|---|---|
| **RC1 P0** — blocks safe launch | `docs/RC1_SCOPE.md` |
| **RC1 P1** — damages first customers | `docs/RC1_SCOPE.md` |
| **P2** — deferred | `docs/RC1_SCOPE.md` |
| **Out of RC1**, with reasons | `docs/RC1_SCOPE.md` |
| Known defects with file:line evidence | `audits/FINDINGS.md` |
| Security findings register | `audits/AUDIT-2026-07-04.md` |
| Post-launch module | `audits/COMPLIANCE-MODULE-BRIEF.md` |
| Deliberate out-of-scope decisions | the "Out of scope" section of each spec in `audits/` |

**Rule:** a backlog item without evidence — a file:line, a failing test, or
an audit reference — is not ready to become a ticket (`AGENTS.md` §6).

## Carried actions with no home yet

| Action | Source |
|---|---|
| Delete `MASTER_ADMIN_KEY` from the Railway environment and remove `verify_master_key` | `030B-SPEC.md` PART C; confirmed unused 8 Sep 2026 |
| Locate the 14-char `sk_` API key generator, or prove it unreachable | `030B-SPEC.md` scope note 4 — still open |
| Let owners rename the AI phone receptionist — post-RC1, once users ask for it | ADR 0001 D10 / proposal D14 (Mike, 28 Sep 2026). Receptionist identity today: `receptionist_configs.personality_prompt`, `greeting_message` |
| Task completion is written `done` by the API and counted only as `completed` by the board meeting, so API-completed tasks go uncounted | `main.py:1797` vs `executive_meeting_data_loaders/tasks.py:73`; Codex review 1. Fixed within proposal B5 if admitted |
| Voice WebSocket forwards arbitrary client messages to the model and executes unmapped tool names | `realtime_voice.py:838`, `:310`; Codex review 1. Fixed within proposal A1 |
| Every INFO log line is labelled `severity: error` in Railway (logging writes to stderr), so real errors are buried and an error alert would fire constantly | Railway logs, 2 Oct 2026 (e.g. "Uvicorn running", "Successfully connected" as error). Small: route INFO to stdout or emit structured levels |
| Aria voice GA migration, then set `ARIA_VOICE_ENABLED=1` in Railway | NS-A2 switched it off; ADR 0001 D2 puts the repair after P0-2 metering. `receptionist_call_handler.py:720-733` is the worked GA example |

---

## TICKET  BH-005 — Bulk category assignment in the accounting UI

**Priority: P1.** Product scope, not security or correctness — categorising
one transaction at a time is slower, not wrong. It must not compete with the
Part A items in `docs/RC1-DECISIONS.md`.

*(BH-003 is reserved for the tenant-isolation negative tests in
`docs/BH-001-TICKET.md`; BH-004 is used as the worked example in
`docs/DEVELOPMENT_WORKFLOW.md`, so this ticket takes BH-005.)*

| Field | Value |
|---|---|
| **Outcome** | A user can select several transactions and assign a category to all of them in one action, instead of opening each transaction in turn. |
| **Current evidence** | `POST /v1/accounting/transactions/bulk-update-category` exists and works (`backend/accounting.py`), but has **no frontend caller** — confirmed 2026-09-11, `grep` over `frontend/client/src/` returns nothing. The only bulk action wired to `selectedTransactions` is bulk-delete (`frontend/client/src/pages/Accounting.tsx:1960`). Found while running the BH-002 post-deploy checks: the verification step for it could not be performed. |
| **Scope** | Frontend only. Add a category picker to the existing multi-select toolbar in `Accounting.tsx` and call the existing endpoint. |
| **Non-goals** | **No backend change.** The endpoint is complete, tenant-scoped and reviewed (BH-002). Do not alter `bulk_update_category`, `require_own_category`, or any category join. No change to the single-transaction edit popup. |
| **Dependencies** | None. BH-002 is merged; the backend it needs is already live on `main`. |
| **Affected systems** | Frontend only. |
| **Security & data risk** | **GREEN** — UI wiring to an endpoint that already enforces tenant ownership server-side. The gate does not move; a new caller appears in front of it. |
| **Acceptance criteria** | ☐ With 2+ transactions selected, a category action appears alongside the existing delete action. ☐ Choosing a category assigns it to every selected transaction and the list reflects it without a manual refresh. ☐ The picker offers **only the current business's categories** — see the note below. ☐ Selecting none, or choosing "no category", behaves predictably and is stated in the ticket before building. ☐ The existing bulk-delete action is unchanged. ☐ A failed request surfaces an error rather than silently doing nothing. |
| **Required tests** | Frontend tests do not exist yet (`docs/TESTING.md`), so this ships with the manual checks below until P1-5 lands. If P1-5 Playwright work lands first, this journey joins it. |
| **Verification** | `./check.sh full`, plus: select two transactions, assign a category, confirm both update; confirm bulk-delete still works; confirm a single-transaction edit still works. |
| **Likely files** | `frontend/client/src/pages/Accounting.tsx` (the multi-select toolbar around `:1910`–`:1975`). |
| **Builder** | Either |
| **Reviewer** | The other one |
| **Branch** | `ticket/BH-005-bulk-category-ui` |
| **Budget band** | S |
| **Max repair cycles** | 3 |
| **Status** | **proposed** |

**Carry this into the build.** BH-002 made the endpoint return **404** for a
category belonging to another business. This UI will be the first thing that
can surface that. If the picker is populated from the current business's
categories — which it should be — a user can never trigger it. Stated here so
it is a designed-out case rather than a surprise in testing.
