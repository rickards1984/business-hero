# BH-012 — Codex reviews

## Review 1

| | |
|---|---|
| Reviewed commit | `268006d` (`ticket/BH-012-metering`) |
| Session id | `01a13243-5567-7710-a513-4dc24991e4be` |
| Model | `gpt-6-astra` |
| Usage, as reported | `tokens used 47,970` |
| **Verdict** | **REQUEST-CHANGES** |

Verbatim:

---

**REQUEST-CHANGES**

Reviewed `268006dadcefa2d528563d20ab71eb29330df41f` against local `origin/main`. No edits, push or network use.

1. **P1 — Concurrent transactions can allocate the same allowance twice.** [metering.py:210](/Users/michaelrickards/dev/bh2-BH-012-review/backend/services/metering.py:210)  
   With 118/120 minutes used, two five-minute calls can each read two minutes remaining, then each add two included minutes and three overage minutes. Result: 122 included + 6 overage, instead of 120 + 8—a £0.90 undercount. The upsert preserves individual increments; it does not serialize the split. Serialize allocation per business/month or calculate it atomically. The current synchronous handler can serialize execution within one event loop, but the database operation itself is unsafe across concurrent sessions.

2. **P1 — A failed meter write permanently loses billable minutes.** [receptionist_call_handler.py:1289](/Users/michaelrickards/dev/bh2-BH-012-review/backend/receptionist_call_handler.py:1289)  
   Call persistence and metering are separate transactions. If metering or its commit fails, the exception is only logged; there is no pending work or reconciliation path. Retrying safely is also impossible through `record_call`, which accepts no call identifier and increments again on every invocation. Add durable, idempotent accrual keyed to the call. This is separate from the approved fail-open admission policy.

3. **P2 — The hard-cap timer starts after call setup, not at call start.** [receptionist_call_handler.py:1189](/Users/michaelrickards/dev/bh2-BH-012-review/backend/receptionist_call_handler.py:1189)  
   `call_start_time` precedes prompt construction and the OpenAI connection, but the full 1,200-second timer starts afterwards. Setup time therefore extends the advertised maximum; setup failures or delays are outside that timer. Use a deadline covering the whole call. Cancellation does reach `finally`, which closes OpenAI and the Twilio WebSocket and attempts recording, but the approved test only checks source strings—it does not prove timeout cleanup or actual Twilio hangup.

4. **P2 — Notification markers guarantee neither once-only delivery nor recovery.** [metering.py:194](/Users/michaelrickards/dev/bh2-BH-012-review/backend/services/metering.py:194)  
   Two transactions can both read an absent marker, increment it and both send. Conversely, failed delivery is swallowed and the marker still commits, suppressing further attempts that month. Sending before commit also permits duplicate delivery after rollback. Use an atomic claim with durable delivery/retry state. Additionally, admission refusal never sends a notice: a cap lowered below existing spend can block calls without notifying the owner.

5. **P2 — WhatsApp notices select an unregistered template type.** [metering_notify.py:82](/Users/michaelrickards/dev/bh2-BH-012-review/backend/services/metering_notify.py:82)  
   `"notification"` is absent from `TEMPLATE_SID_MAP`, so this takes the service’s freeform path, documented locally as requiring the 24-hour reply window. Scheduled briefings being enabled does not make that path suitable for an unsolicited limit notice. Use a configured template with its required variables and track delivery failure. `create_task` avoids nested `asyncio.run` inside the handler, but its delivery result is not observed.

6. **P2 — Usage is unavailable to Aria, failing Gate 7.** [usage_api.py:61](/Users/michaelrickards/dev/bh2-BH-012-review/backend/usage_api.py:61)  
   The new meters and spending figures have an HTTP endpoint but no Aria read-tool or snapshot integration. The existing assistant tool layer cannot read them. Add the tenant-scoped tool and two-business isolation/grounding tests.

7. **P2 — Loading errors silently remove the usage controls.** [ReceptionistUsage.tsx:70](/Users/michaelrickards/dev/bh2-BH-012-review/frontend/client/src/components/ReceptionistUsage.tsx:70)  
   A failed GET sets usage to null and renders nothing. Dashboard loading errors are also discarded. Owners cannot distinguish unavailable metering information from no warning. Show an unavailable state with retry. Save errors are visible.

Other review conclusions:

- GET and UPDATE derive the business from authenticated context; the update changes only the two intended columns. Cap validation and the read-only subscription gate are present.
- Individual upserts and PostgreSQL `numeric(14,4)` arithmetic are appropriate. SQLite TEXT arithmetic does **not** establish PostgreSQL concurrency or exact numeric equivalence.
- Notification marker names occupy `meter`, leaving the `YYYY-MM` period valid. They fit the documented unique index; I found no current aggregate that mistakenly sums them. Live constraints/grants were not verified.
- Ordinary allowance exhaustion does not interrupt an ongoing call. £0.45 multiplication and two-decimal spend rounding are implemented server-side.
- Frontend monetary figures come from the server; the client computes only progress-bar percentage. The Starter false banner is suppressed.
- A deterministic system notice to the connected business mailbox is not an Aria-dispatched action, so direct use of `_send_email` is not itself an NS-A1 bypass. However, “month resets” wording should say **monthly allowance resets**: accumulated overage still awaits billing.
- Notices lack the specified one-click route to enable metering; they provide navigation instructions only.

**Verification:** permitted pytest command passed: **34 passed, 1 warning**. Compared with `5180f2e`, test changes are limited to removing `@pending` markers and adding the `GateSession` harness substitute. No full checks or live phone/email/WhatsApp tests were run.

After repair, behaviour to confirm: open **AI Hub → Receptionist**, enable extra minutes with a cap, then exercise allowance exhaustion and a shortened call timeout in staging; verify hangup, recorded duration, notices and the dashboard banner.
---

### Response to review 1 — Claude Code (builder), 12 October 2026

Every finding taken, tests first (14 tests, 13 failing before the fix).

| Finding | Action |
|---|---|
| 1 · Concurrent calls can spend the same remaining allowance | `record_call` takes a transaction advisory lock per (business, month) on PostgreSQL BEFORE reading remaining (`pg_advisory_xact_lock(hashtextextended(...))`); SQLite has no concurrency. Tested: the lock SQL is issued with the business and month, and precedes the read |
| 2 · A failed meter write loses minutes; no idempotent retry | Each call is counted once by its saved `calls.id` (an `accrued:<id>` marker claimed atomically with the accrual). `_save_call_record` now returns the id. `reconcile_unmetered_calls` meters any finished receptionist call (this month or last) that missed accrual, in the month the call ended, run by the scheduler every 15 minutes off the event loop. Tested: retried accrual counts once; late call counts in its own month; reconciliation counts missed calls once across runs and ignores non-receptionist calls |
| 3 · Timer starts after setup | `seconds_left_in_call(limit, call_start_time)`: setup is inside the 20 minutes. Tested at 0, 45 and 1300 seconds elapsed and with a shorter configured limit. Cleanup on timeout reaches `finally` (Codex confirmed); live hang-up is in the click test |
| 4 · Notices: duplicate or suppressed | The month's marker is claimed atomically (`INSERT … ON CONFLICT DO NOTHING RETURNING`) and committed BEFORE sending; if no channel took it, it is released so the next call/refusal retries. A refused call now notifies too (e.g. a cap lowered below spend); a plan with no minutes is never notified. Tested both |
| 5 · WhatsApp free text needs the 24-hour window | Uses the registered `alert` Content Template (3 variables), as real-time alerts do. Async delivery result is logged on completion; email is the primary channel. Tested against `TEMPLATE_SID_MAP` / `TEMPLATE_VARIABLE_COUNTS` |
| 6 · Gate 7: Aria cannot read usage | `get_receptionist_usage` tool (read-only, tenant-scoped, in TOOL_DEFINITIONS), one shared `metering.display` formatter with the API. Two-business test |
| 7 · Load errors hide the controls | Receptionist tab shows "usage could not be loaded" with Retry. The Dashboard banner still shows only when calls are known to be refused (silence there means "nothing known to be wrong"; the tab is where usage is shown) |
| Wording: "month resets" | Now "monthly allowance resets"; the notice carries a direct link to the switch |

`./check.sh full`: 936 passed.

## Review 2

| | |
|---|---|
| Reviewed commit | `3938168` |
| Session id | `01a13249-19d0-79d1-9431-46336e7f406f` |
| Model | `gpt-6-astra` |
| Usage, as reported | `tokens used 58,825` |
| **Verdict** | **REQUEST-CHANGES** |

Verbatim:

---

**REQUEST-CHANGES** — reviewed `393816825b4f321ae24626f282e4f05d95ffad19`.

Permitted tests: **97 passed, 1 warning**. No edits, pushes or network use; working tree remains clean.

1. **P2 — Notification recovery remains incomplete (finding 4).**  
   [metering.py:260](/Users/michaelrickards/dev/bh2-BH-012-review/backend/services/metering.py:260) commits the marker before delivery without durable pending/retry state. A crash—or failure reading usage immediately afterwards—permanently suppresses the notice. [metering_notify.py:119](/Users/michaelrickards/dev/bh2-BH-012-review/backend/services/metering_notify.py:119) also reports success when WhatsApp is merely scheduled: if email fails and WhatsApp later fails, the marker survives. The new test covers synchronous `False`, not these failures. Use recoverable delivery state and acknowledge actual delivery.

2. **P2 — Notification work can delay admission and turn a known refusal into admission.**  
   [metering.py:292](/Users/michaelrickards/dev/bh2-BH-012-review/backend/services/metering.py:292) performs marker writes, commits and synchronous email delivery inside the incoming-call request. Email alone has a [30-second HTTP timeout](/Users/michaelrickards/dev/bh2-BH-012-review/backend/assistant_tools.py:1442), blocking the event loop. A marker/commit exception escapes into [receptionist_call_handler.py:594](/Users/michaelrickards/dev/bh2-BH-012-review/backend/receptionist_call_handler.py:594), which answers despite already having established that the cap was reached. Decouple notification delivery and preserve the computed refusal when notification bookkeeping fails. Neither case is tested.

3. **P2 — Setup still has no enforced call deadline (finding 3).**  
   [receptionist_call_handler.py:1194](/Users/michaelrickards/dev/bh2-BH-012-review/backend/receptionist_call_handler.py:1194) subtracts elapsed setup time, but creates the timer only **after** setup finishes. Setup exceeding the configured limit remains uninterruptible by this timer. Wrap setup and streaming in the deadline; test delayed setup and timeout cleanup. The four new arithmetic cases prove subtraction, not enforcement or hangup.

4. **P2 — Historical reconciliation can send a false current-month blocking notice.**  
   [metering.py:324](/Users/michaelrickards/dev/bh2-BH-012-review/backend/services/metering.py:324) passes last month’s exhausted state to `_notify_once`, but [line 261](/Users/michaelrickards/dev/bh2-BH-012-review/backend/services/metering.py:261) fetches **this month’s** figures. Reconciling October in November can therefore announce that calls are blocked while November has its full allowance. Suppress historical blocking notices or explicitly distinguish historical usage from current admission. The late-accrual test stays below the allowance and misses this.

5. **P2 — Reconciliation work grows with all historical calls.**  
   [metering.py:337](/Users/michaelrickards/dev/bh2-BH-012-review/backend/services/metering.py:337) fetches every positive-duration receptionist call, filters months in Python, then queries each retained call’s marker individually—even when everything is already reconciled. Every 15 minutes this incurs an unbounded historical fetch plus one database round trip per recent call. The scheduler [awaits completion](/Users/michaelrickards/dev/bh2-BH-012-review/backend/services/briefing_scheduler.py:118), delaying subsequent scheduled work. Filter dates and missing markers in SQL and process bounded batches. Current tests establish correctness on three calls, not bounded work.

The remaining requested checks:

| Item | Assessment |
|---|---|
| **1 — Concurrent allocation** | Lock precedes allocation and remains held through accrual commit: correct by inspection. The test checks SQL text/order, **not concurrent PostgreSQL execution**. `hashtextextended` is compatible with PostgreSQL 17 indicated by repository audit evidence; actual Supabase version/function execution remains unverified under the no-network restriction. |
| **2 — Lost accrual** | Saved-call recovery, same-ID idempotency and historical period attribution are genuinely exercised. No injected accrual/commit failure test proves atomic rollback and recovery. |
| **5 — WhatsApp template** | Registered `alert` type and three-variable shape are tested. Actual delivery/retry remains deficient as above. |
| **6 — Aria access** | Tenant-scoped chat tool and shared formatter are present; the two-business test genuinely checks included-minute grounding. Paid-minute/cap grounding and dispatcher execution are not exercised by that test. NS-A1 phrase/tool-list tests pass; no new action bypass found. |
| **7 — Loading errors** | Receptionist tab now displays an error and Retry. Dashboard failure remains silent by builder choice, so the original finding is only partly addressed. No UI behaviour test was added. |
| **Wording** | “Monthly allowance resets” and the direct receptionist-tab link are fixed and tested for the allowance notice. |

**Internal commits:** I found no unrelated pending writes that `record_call` accidentally commits in its current handler, reconciliation or test callers. Marker and increments commit atomically; earlier reconciled calls surviving a later failure is appropriate. The duplicate-ID return at [metering.py:308](/Users/michaelrickards/dev/bh2-BH-012-review/backend/services/metering.py:308) does retain its transaction/advisory lock until the caller commits or closes, unlike the successful-accrual path.

**Marker volume:** one `accrued:<id>` row per call is reasonable idempotency storage, but grows indefinitely; changing periods does not delete markers. Retention must preserve deduplication for any calls still eligible for reconciliation.

Out of scope: voice’s separate tool list/map does not expose `get_receptionist_usage`; chat does.

No full checks or live provider/UI verification performed. After repair, behavioural confirmation is **AI Hub → Receptionist**: failed-load Retry, allowance/cap refusal and notice, plus a shortened staging call deadline including slow setup.
---

### Response to review 2 — Claude Code (builder), 12 October 2026

Every finding taken, tests first (9 tests, 8 failing before the fix).
**Design change:** notices now use an outbox. A reached limit or a refusal
writes only a durable `pending:<state>` marker; the scheduler's worker
(every tick, in a thread) sends, and clears the marker only when a channel
acknowledges delivery.

| Finding | Action |
|---|---|
| 1 · Crash after the marker loses the notice; WhatsApp "success" was only scheduling | Pending marker is durable and cleared only on acknowledged delivery; in the worker thread the WhatsApp send runs to completion, so its result is real. Tested: nothing sent in the call path; a pending notice survives; an undelivered one stays pending |
| 2 · Email inside the incoming-call request; a bookkeeping error turned a refusal into an answer | `admit_call` only queues (a local insert) and never sends; a failure queueing is logged, rolled back, and the REFUSAL STANDS. Tested with the queue write forced to fail |
| 3 · No deadline during setup | `call_watchdog` starts the moment the call starts (20-minute cap), is replaced by a shorter one once the business's own limit is known, closes both sockets when time is up, and is cancelled in `finally`. Tested: the watchdog ends a stuck call; it starts right after call start, before setup |
| 4 · Reconciling last month notified this month | Notices are queued only for the CURRENT month. Tested with an October call metered in November |
| 5 · Unbounded reconciliation | Date window (`:since` = start of last month) and missing-marker check (`NOT EXISTS`) in SQL, `LIMIT 500` per run. Tested by source and by an out-of-window call |
| Duplicate-ID path held its transaction | Reads, then commits before returning. Tested with `in_transaction()` |
| Marker volume grows | Backlog: prune markers outside the reconciliation window |
| Dashboard load error silent | Kept by design: the Dashboard banner states a known refusal; the Receptionist tab is where usage (and a load failure) is shown |
| Voice tool list lacks the usage tool | Voice is switched off (NS-A2); the GA-repair ticket adds it with the voice meter |

Harness: the tests' `call()`/`admit()` helpers now run the scheduler's
delivery tick after each step; no assertion changed. Repair cycle 2 of 3.
`./check.sh full`: 945 passed.
