# Review request — Aria gap analysis and RC1 scope proposal

**For:** Codex, as independent reviewer (`AGENTS.md` §5, §7 — the builder
must not be the sole approver of cross-cutting work).
**From:** Claude Code, 28 September 2026.
**Branch:** `docs/north-star-adoption`. **Code the analysis describes:**
`main` at `2cc2b62`.
**Under review:**

- `docs/ARIA_GAP_ANALYSIS.md`
- `docs/RC1_SCOPE_PROPOSAL.md`

Also in the branch, for context only: `docs/NORTH_STAR.md` (adopted by
Michael — **do not review it for content**; flag only where the analysis
misreads it), the North Star section of `AGENTS.md`, and Gate 7 of
`docs/DEFINITION_OF_DONE.md`.

This file doubles as the prompt: pass it on stdin
(`codex exec --sandbox read-only -C <worktree> -o <final.md> - < this-file`).

---

## What I am asking

**Verify the two documents independently against the code.** Not "does this
read well" — does the code say what the documents say it says. The history
of this repository is documents making honest claims the code did not
support (review 001 findings 4, 7, 8). Treat every claim here the same way.

Read-only. Do not edit files, run migrations, or touch any network or
database. `./check.sh` may be run; nothing else needs executing.

## Specific claims to check

Each is a claim I made. For each, say **CONFIRMED**, **WRONG** (with the
file:line that shows it), or **UNVERIFIABLE FROM THE REPO**.

1. **Tool inventory.** `backend/assistant_tools.py` defines 27 tools in
   `TOOL_DEFINITIONS` and one dispatcher `execute_tool` (`:532`) used by both
   chat and realtime voice.
2. **Unapproved external actions.** `send_email`, `send_invoice_chase` and
   `create_calendar_event` execute directly when the model calls them, in
   chat; `send_email` and `send_invoice_chase` are also reachable from voice
   via `REALTIME_TOOLS`. No code-level approval step exists — only prompt
   text. Is there any code path I missed that requires confirmation?
3. **Scoping.** Every tool query in `assistant_tools.py` is scoped by
   `business_id`, directly or transitively (GA §A8 lists the transitive
   ones). **Try to find a tool query that is not.** Joins matter most — BH-002
   was a scoped primary table with an unscoped join.
4. **`business_id` provenance.** No Aria tool accepts `business_id` from the
   model; it is always the server-resolved business. Check chat
   (`assistant_chat.py:660` onward) and voice (`realtime_voice.py:280`,
   `:634` onward).
5. **RLS bypass.** Aria tools run on `db.engine`, the elevated role, so RLS
   plays no part on this path.
6. **Voice protocol.** `realtime_voice.py` uses the Realtime Beta protocol
   (`:721`, `:751-766`) while `receptionist_call_handler.py:48` records that
   Beta was removed on 12 May 2026. I concluded voice is *expected broken* in
   production and marked it UNVERIFIED. Is that conclusion supported, and is
   the UNVERIFIED label the right strength?
7. **Voice gating.** `realtime_voice.py:689` gates on `aria_voice`, failing
   closed; `main.py:2346` gates chat on `aria_chat`. So `CURRENT_STATE.md` §5's
   "none" for both is stale.
8. **Provider inventory (GA §A7).** 19 direct call sites across 12 modules,
   all OpenAI, 10 distinct models, 4 configurable by environment. **Find any
   I missed** — including raw HTTP, WebSocket, or a provider reached through a
   helper. Check the frontend too.
9. **Three aggregators.** `generate_prep_data`, `gather_business_data`, and
   chat's `get_today_briefing` / `get_business_overview` aggregate the
   business independently; only `prep_data` has `data_quality`, and its
   staleness check covers financials only.
10. **CEO Briefing** is a WhatsApp settings-and-history page, not an in-app
    briefing.
11. **Tasks.** `tasks` has no assignee column (check
    `audits/live-schema-public.txt`), so "Aria's tasks vs yours by assignee"
    needs a migration; a read-only union with
    `executive_meeting_action_items` does not.
12. **Client-side Aria figures.** `Accounting.tsx:393-405` falls back to
    insights built in the browser, shown under Aria's name.
13. **Dead code.** `pages/BusinessDashboard.tsx` and `components/BottomNav.tsx`
    are unreachable from any route.
14. **No Aria tests.** No test imports `assistant_tools`, `assistant_chat`,
    `realtime_voice`, `executive_meeting_prep` or `briefing_data`.

## Adversarial asks

- **The scope proposal's entry test** is "no migration, no new provider call
  site, runs beside the security sequence". Does any item it admits to RC1
  (A1, A2, B1–B8) actually need a migration, touch a security-sequence
  resource (`main.py` hot spot, the migration slot, `businesses`), or add a
  provider call? Name it.
- **Does anything in the proposal deprioritise security work** — 030b
  Release 2, 033 STEP 21, the BH-001 §6 findings, or the P0 list? The North
  Star forbids that; so do the new AGENTS.md rules.
- **Isolation risks I did not list.** Especially: the dock or home passing
  record ids from the client (GA §C2), the unified task view, and any new
  table a snapshot would need (`create_all()` — `AGENTS.md` §3.3).
- **Effort bands.** Any estimate you believe is off by a band or more.
- **Anything marked UNVERIFIED that the repository can in fact settle** —
  settle it. Anything I stated as fact that the repository cannot settle —
  say so.
- **§E of the gap analysis** raises five tensions with the North Star, and
  the proposal's D5 suggests amending P9's "enforced by RLS". Are those
  fair readings of the code, or am I overstating them?

## What I want back

1. Verdict: **ACCEPT**, **ACCEPT-WITH-CHANGES** or **REQUEST-CHANGES**.
2. The 14 claims, each CONFIRMED / WRONG / UNVERIFIABLE, with evidence.
3. Findings, most severe first, each with file:line and the correction.
4. Anything you would move into or out of the RC1 proposal, and why.

The report will be preserved **verbatim** in
`docs/reviews/aria-gap-analysis-codex-review.md`, as every review in this
repository is. Defects return to this branch, not a new one.
