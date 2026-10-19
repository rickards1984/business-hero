# AUTO-1 — Codex reviews, verbatim

## Review 1

| | |
|---|---|
| Reviewed commit | `69b6405` |
| Session id | `01a15574-0db9-75c2-9e3e-c3b8e7bea36a` |
| Model | `gpt-6-astra` |
| Usage, as reported | `tokens used 55,816` |
| **Verdict** | **REQUEST-CHANGES** |

Verbatim:

---

**REQUEST-CHANGES** — at `69b6405`. The blocking findings concern North Star P4, P8 and correctness.

1. **P1 — Unknown outcomes are retried through fresh cards.** [automations.py:111](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/services/automations.py:111), [automations.py:227](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/services/automations.py:227). An unconfirmed send remains `executing`, with no invoice timestamp update. The next pass ignores that action and proposes another. `chased_now` protects only the current pass. **Reproduced: two passes produced two provider calls and two `executing` actions.** Persistently block unresolved attempts for that customer; also account for successful sends whose invoice bookkeeping failed.

2. **P1 — Separate runs can send duplicate chases and exceed limits.** [automations.py:165](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/services/automations.py:165), [automations.py:215](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/services/automations.py:215). Both runs can read the same available cap and customer history, then create independently claimable cards. **Reproduced with interleaved passes: two sends for the same invoice, both `done`.** The scheduler’s task guard prevents overlap through its entry point in one process; two processes have separate guards. A database-backed reservation must enforce customer spacing and business cap across runs.

3. **P1 — Permission and time-window checks become stale during a run.** [automations.py:152](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/services/automations.py:152), [automations.py:257](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/services/automations.py:257). Settings, time and account eligibility are captured before sending. If the owner switches off or pauses a customer while earlier emails are being sent, subsequent sends continue under the old settings. A pass beginning at 16:59 can continue after 17:00. Suspension or plan changes likewise leave the loaded business stale. Revalidate current authority and time before each send.

4. **P1 — An invoice settled after candidate selection can still be chased.** [automations.py:171](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/services/automations.py:171), [aria_actions.py:399](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/services/aria_actions.py:399). Candidate selection checks the receivables balance, but approval only rechecks existence, literal `paid` status and stage. **Reproduced: setting `paid_amount = amount` between selection and proposal still sent the chase.** Cancellation or a synced zero balance has the same gap. Apply the full receivables eligibility rule again before execution.

5. **P1 — Concurrent settings saves can restore revoked permission.** [automations_api.py:67](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/automations_api.py:67), [automations_api.py:49](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/automations_api.py:49). The merge reads and rewrites the entire document without concurrency protection. A rules update can read `enabled=true`, an owner’s off request can commit, and the earlier update can then restore `true`. Other settings can also be overwritten. The generic [settings PUT:1475](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/main.py:1475) permits the same stale-document overwrite. Protect both write paths with version checking or coordinated atomic updates.

6. **P2 — Manually approved chases are reported as autonomous.** [automations.py:202](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/services/automations.py:202), [home_summary.py:127](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/services/home_summary.py:127). Stage-4 cards carry the automation marker; the home filters by that marker without checking the approver. **Reproduced: an owner-approved stage-4 chase appeared in `recent_automated`**, feeding “on autopilot” and “on her own” wording. Distinguish automated proposal creation from automated execution.

The existing per-card claim, payload-version binding and already-chased-stage refusal remain intact. They do not establish send-once guarantees across newly created cards. The PostgreSQL JSON casts look appropriate, but the new tests exercise SQLite only.

Verification: `./check.sh full` passed — **1,879 passed, 33 skipped**; AUTO-1 separately **35 passed**. Important missing tests cover the scenarios above, real scheduler overlap behaviour, PostgreSQL concurrency, and generic settings writes. The scheduler test merely checks source strings.

`docs/AUTOMATION-AND-OUTREACH-PLAN.md` is absent from this checkout, so Mike’s referenced decisions could not be independently verified. No source changes, commits or pushes; worktree is clean.
---

### Response to review 1 — Claude Code (builder), 19 October 2026

Every finding taken. Tests first: 12 new tests. Mutation-checked: removing the claim check makes both overlap tests fail.

| Finding | Action |
|---|---|
| 1 · Unknown outcomes retried through fresh cards (P1) | Any chase left `executing` (outcome unknown) blocks that customer from automatic chasing **indefinitely**, until the owner resolves it (`unresolved_attempt`). Customer spacing now also reads the action record (`executing`/`done`, any approver), not only `invoices.last_chased_at`, so a sent chase whose bookkeeping failed still spaces the customer. Both tested, including 14 days later |
| 2 · Separate runs duplicate and exceed limits (P1) | **Insert-then-check claim** (`_won_claim`), with no locks needed across processes. The proposal is stored first, then the run checks the record. Anything already sent or unresolved for the customer within the gap wins outright. Of two in-flight automatic claims, the earlier `(created_at, id)` wins and the other is dismissed. The daily cap counts other runs' sent, failed and earlier in-flight claims. Tested with a rival pass injected mid-run: two invoices for one customer give one send, and the cap holds across interleaved runs |
| 3 · Stale permission and window mid-run (P1) | `refresh()` re-reads the current settings and business before **every** send. Switched off, outside hours, suspended or plan lost stops the run; a newly paused customer is skipped. The scheduler's refresh reloads from the database. Tested: switch-off mid-run, pause mid-run, and the 17:00 boundary mid-run |
| 4 · Settled after selection still chased (P1) | `approve()` re-applies the **full receivables rule** (`home_summary.invoice_owed`: balance above zero, not archived, not a settled status) before sending any chase, automatic or tapped. Tested: a payment recorded between proposal and send; a manual card for an invoice cancelled since |
| 5 · Settings overwrite races (P1) | `/v1/automations` reads the settings row `FOR UPDATE` (on Postgres) for its read-modify-write. The generic `PUT /v1/business/settings` keeps the stored `automations` whatever the client sends (`preserve_automations`), so only the validated endpoint can change a standing permission. Tested (the lock by source; preservation by function) |
| 6 · Owner-approved cards reported as autonomous (P2) | Stage-4 cards carry `raised_by`, not `automation`. `recent_automated` lists only automatic sends with no human approver. Tested |

Harness: two existing fixtures gained the columns the new checks read: the invoice balance columns, and `approved_by` on actions.

## Review 2 (repair cycle 1 of 3)

| | |
|---|---|
| Reviewed commit | `27e0b95` |
| Session id | `01a1557a-df6f-7da1-91f0-bc9117d47d88` |
| Model | `gpt-6-astra` |
| Usage, as reported | `tokens used 58,261` |
| **Verdict** | **REQUEST-CHANGES** |

Verbatim:

---

**REQUEST-CHANGES** — at `27e0b957210662375639e6a291e5fa85d1a0a79d`. Findings concern North Star P4 and correctness.

1. **P1 — Claims can still permit duplicate sends and exceed the cap.** [automations.py:190](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/services/automations.py:190), [automations.py:301](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/services/automations.py:301). Run A passes `_won_claim`, then pauses before approval. Run B inserts a proposal with an earlier timestamp—or an equal timestamp and smaller UUID—and also passes. Both approve distinct cards. **Reproduced with timestamp ties and one-second clock skew: two sends to one customer; separately, two sends with `daily_cap=1`.** The check does not durably reserve permission to send. Existing overlap tests complete the rival before the first check, missing this interleaving.

2. **P1 — Generic settings saves still restore revoked permission.** [main.py:1476](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/main.py:1476), [main.py:1487](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/main.py:1487). A generic save loads `enabled=true`; switch-off commits; the generic save then preserves its **stale** automations document and writes `true` back. **Reproduced through the actual ORM update path.** `FOR UPDATE` on the automation endpoint alone cannot protect an unlocked reader that subsequently overwrites the document. The next scheduled pass can email customers after permission was revoked.

3. **P1 — Refreshed spacing rules are not applied to the current send.** [automations.py:256](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/services/automations.py:256), [automations.py:270](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/services/automations.py:270). Due-date and spacing checks run before `refresh()`. **Reproduced:** changing `first_after_days` from 7 to 14 still sends for an invoice 10 days overdue; changing `every_days` to 14 still sends after eight days. Increasing `customer_gap_days` likewise fails when the previous chase is recorded only on the invoice. Re-evaluate eligibility using the refreshed rules before approving.

4. **P2 — The business refresh can retain stale account eligibility.** [automations.py:360](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/services/automations.py:360), [auth.py:232](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/auth.py:232). `_load_business()` performs an ordinary ORM query without refreshing an already-loaded instance. **Reproduced:** another transaction set `is_active=false`; reloading returned the same object with `is_active=true`, and `_authority()` allowed it. Explicitly refresh or repopulate the instance. Tests supplying fresh `SimpleNamespace` objects do not exercise this path.

Review-1 findings **1, 4 and 6 passed the exercised reproductions**: unresolved attempts remain blocked, bookkeeping failures retain spacing, settled invoices are refused, and owner-approved stage-4 cards are excluded from autonomous reporting. Findings **2, 3 and 5 remain incomplete** as above. Dismissing an already-approved action correctly preserved `done`.

Verification: `./check.sh full` passed — **1,891 passed, 33 skipped**. AUTO-1 separately: **47 passed**. Additional temporary probes exercised the findings above. PostgreSQL types appear consistent with the recorded schema, but **PostgreSQL execution and row-lock concurrency were not verified**; the repository’s lock test only checks source text.

No source edits, commits or pushes. Worktree is clean.
---

### Response to review 2 — Claude Code (builder), 19 October 2026

Every finding taken. Tests first: 7 new cases. Mutation-checked: removing the reservation fails five tests; the rival tests are stable over five runs.

| Finding | Action |
|---|---|
| 1 · Claims permit duplicates and exceed the cap (P1) | The insert-then-check comparison is replaced by **durable, unique tickets** in `usage_meters`, whose `UNIQUE (business_id, meter, period)` lets exactly one run hold each. Before a send, a run must take: (a) `autochase:<customer>:<UK date>` (one automatic chase per customer per day); and (b) the first free `autochase-slot:<UK date>:<n>`, for n from 1 up to the daily cap. Only after that does it propose and approve. The database settles every race, in any interleaving and with any clock skew. Tickets are given back only when nothing was sent (proposal refused, or approval refused before sending). Record-based spacing still covers sequential runs. Tested with a rival run between the first run's check and its send: same customer, one send; daily cap 1, one send |
| 2 · Generic save restores revoked permission (P1) | `PUT /v1/business/settings` now selects the row `with_for_update()`, the same row lock as `/v1/automations`. It reads `automations` only under the lock, so it cannot write back a stale `enabled`. Tested by source; row locks cannot be exercised on SQLite |
| 3 · Refreshed rules not applied to the current send (P1) | The loop now refreshes **first**, then decides due date, spacing, pause, unresolved and waiting with the refreshed rules. Records-based spacing reads a fixed 31-day window, so a widened gap is honoured. Tested: `first_after_days` 7→14, `every_days` 7→14 and `customer_gap_days` 7→14 mid-run each stop the send in hand |
| 4 · Stale business on refresh (P2) | The scheduler's refresh calls `session.expire_all()` before re-loading, so `is_active` and the plan are re-read from the database. Tested by source |

## Review 3 (repair cycle 2 of 3)

| | |
|---|---|
| Reviewed commit | `424a0e7` |
| Session id | `01a15580-ad9b-7cb1-b417-1e4f6bf2411e` |
| Model | `gpt-6-astra` |
| Usage, as reported | `tokens used 58,399` |
| **Verdict** | **REQUEST-CHANGES** |

Verbatim:

---

**REQUEST-CHANGES** — at `424a0e7`. Three reproduced P1 findings concern North Star P4 and correctness.

1. **P1 — Tickets are returned after another caller has sent the chase.** [automations.py:311](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/services/automations.py:311). An owner approves the newly proposed card before autopilot calls `approve()`. Autopilot receives “already done”, releases both tickets and continues without recording that customer in `chased_now`. Its customer-history snapshot predates the send. **Reproduced: the next invoice for the same customer was automatically chased, producing two emails within the seven-day gap.** An `ActionRefused` does not establish that nothing was sent.

2. **P1 — Lowering the daily cap can still permit additional sends beyond it.** [automations.py:186](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/services/automations.py:186). With cap 2, run A holds slot 1 while run B sends using slot 2. A’s invoice becomes paid, so its proposal is refused and slot 1 returned. The owner lowers the cap to 1. A subsequent reservation takes free slot 1 without counting the existing send in slot 2. **Reproduced using the actual paid-invoice refusal: two automatic emails, with the second sent after the cap became 1.**

3. **P1 — Customer reservations do not protect spacing across UK midnight.** [automations.py:179](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/services/automations.py:179), [automations.py:233](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/services/automations.py:233). With the supported all-day window, run A reserves and proposes just before midnight. Before A approves, run B starts just after midnight and chases another invoice for the same customer using a different day ticket. A then sends from its earlier snapshot. **Reproduced across 31 October–1 November: two automatic emails to the same customer despite the seven-day gap.** A one-second clock difference straddling midnight permits the same ordering.

Review-2 status: same-day interleaving, tied timestamps and one-second skew now preserve both customer exclusion and cap 1. Refreshed spacing rules pass. The identity-map reproduction confirms `expire_all()` reloads suspension correctly. Both settings writers now lock the same row; PostgreSQL compilation produces `FOR UPDATE`, but **actual PostgreSQL execution and lock concurrency remain unverified**.

Ticket rows did not affect metered minutes in the probe; usage reads named meters.

Verification: `./check.sh full` passed — **1,898 passed, 33 skipped**. AUTO-1: **54 passed**. Provider calls were mocked; no real emails sent. No source edits, commits or pushes; worktree clean.
---

### Response to review 3 — Claude Code (builder), 19 October 2026

All three taken. Tests first: 4 new tests. Mutation-checked: the lowered-cap and midnight tests fail with their fixes removed.

| Finding | Action |
|---|---|
| 1 · Tickets returned after another caller sent (P1) | When `approve()` refuses, the autopilot reads the action's status. **Tickets are given back only when it shows no send.** If it is `done` or `executing` (e.g. the owner tapped the same card first), the tickets stay used, the customer is marked chased for the run, and an unconfirmed send is marked unresolved. Tested: the owner approves the autopilot's card first; the same customer's next invoice is not chased |
| 2 · A lowered cap reuses a freed early slot (P1) | Before taking a slot, the run counts **every** slot ticket used today; if that is already at or above the current cap, no slot is taken. Tested: slot 2 used, slot 1 free, cap lowered to 1 → nothing sent |
| 3 · Spacing across UK midnight (P1) | A per-customer **in-progress ticket** (`autochase-inflight:<customer>`, not tied to a date) is held from reservation until the attempt resolves. After a send, the action record spaces the customer; with no send, it is given back. A run on the other side of midnight cannot take it. A ticket over an hour old, with nothing unresolved for the customer, is a crashed run's and is reclaimed (conditional delete, then unique re-take). Tested across 31 Oct → 1 Nov-style midnight interleaving, and stale reclaim |

## Review 4 (confirm-only, repair cycle 3 of 3)

| | |
|---|---|
| Reviewed commit | `5ff39b6` |
| Session id | `01a15585-ce4d-79d2-a858-506649de0920` |
| Model | `gpt-6-astra` |
| Usage, as reported | `tokens used 37,777` |
| **Verdict** | **REQUEST-CHANGES** (one P1) |

Verbatim:

---

**REQUEST-CHANGES** — at `5ff39b6`.

Review-3 findings **1 and 2 pass**: owner-first approval produces one email; lowering the cap after an actual paid-invoice refusal frees slot 1 permits no additional send. Finding **3 passes the original short midnight interleaving**, but stale reclaim reopens it.

**P1 — Stale reclaim lets a live run lose its reservation and still send.** [automations.py:207](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/services/automations.py:207), [automations.py:363](/Users/michaelrickards/dev/bh2-AUTO-1-review/backend/services/automations.py:363).

Reproduced with the supported all-day window: A reserves and proposes at **31 October 23:59:50**, then pauses. B starts **1 November 01:01**, reclaims A’s reservation because its card is merely `proposed`, and sends for another invoice belonging to the same customer. A resumes and approves without checking reservation ownership. **Two provider calls; both actions `done`**, violating seven-day customer spacing. Age alone does not prove the original run crashed.

Verification: AUTO-1 **58 passed**; targeted probes confirmed the results above. Providers mocked; no real emails. No repository edits, commits or pushes; worktree clean. This unresolved P1 goes to Mike after the final repair cycle.

Backlog:
- Exercise reservation concurrency and settings row locks against PostgreSQL; SQLite does not verify those guarantees.
---

### Status — 19 October 2026

Three repair cycles used. One P1 remains (stale in-progress reclaim lets a paused live run be overtaken). Escalated to Mike with a recommendation; not fixed without his decision.

---

### Response to review 4 — Claude Code (builder), 19 October 2026 (cycle 4, authorised by Mike: "A")

| Finding | Action |
|---|---|
| Stale reclaim lets a paused live run be overtaken (P1) | Two changes. (1) **No reclaim while a live automatic draft exists** for that customer (`proposed` or `executing`, marked `automation`): its run may be paused, not crashed. Age alone no longer decides; only a ticket with no draft behind it (a run that crashed before proposing) is reclaimed. A run that crashed after proposing leaves its draft on the owner's home as an ordinary card. (2) **Fencing:** just before approving, the run confirms it still holds its own in-progress ticket (the exact stamp it wrote). If not, it dismisses its card, frees only its own daily and cap tickets, and sends nothing. Tests: Codex's reproduction (A proposes at 23:59:50 and pauses; B at 01:01) gives one send; a ticket taken over between proposal and send makes the run stand down; an old ticket with a waiting automatic draft is not reclaimed. Mutation-checked: removing either change fails its tests. Stable over three runs |
