# NS-V1 — Codex reviews, verbatim

## Review 1

| | |
|---|---|
| Reviewed commit | `204aaa9` |
| Session id | `01a13b23-e411-7321-9ef1-67ce7c5cf070` |
| Model | `gpt-6-astra` |
| Usage, as reported | `tokens used 88,651` |
| **Verdict** | **REQUEST-CHANGES** |

Verbatim:

---

**REQUEST-CHANGES** for `204aaa953846f18c37b4820ad2504aa48d89f7f0`.

1. **P1 — Failed accrual permanently loses voice usage.** [realtime_voice.py:984](/Users/michaelrickards/dev/bh2-NS-V1-review/backend/realtime_voice.py:984)  
   If the database fails when a ten-minute session ends, the exception is merely logged. The session ID and duration have no durable recovery record; receptionist reconciliation only scans receptionist calls. Those minutes remain unmetered. Persist recoverable session accounting and retry idempotently.

2. **P1 — A blocked limit notice defeats the hard cap.** [realtime_voice.py:955](/Users/michaelrickards/dev/bh2-NS-V1-review/backend/realtime_voice.py:955)  
   After watchdog cancellation, the handler awaits `send_json(session_limit)` without a timeout **before** cancelling forwarders or closing OpenAI. A backpressured browser leaves the provider and forwarders active indefinitely. Reproduced with a 50ms cap: at 250ms, upstream remained open and no accrual had occurred. Stop forwarding and initiate bounded cleanup before attempting the notice.

3. **P1 — Synchronous database work blocks every watchdog on the event loop.** [realtime_voice.py:984](/Users/michaelrickards/dev/bh2-NS-V1-review/backend/realtime_voice.py:984)  
   Final accrual performs database reads, advisory-lock acquisition and commit synchronously, before provider closure. A slow database blocks other voice sessions’ deadlines and socket handling. A simulated 300ms accrual delayed a 20ms heartbeat to 306ms, with upstream still open. The synchronous shared-tool execution at [line 441](/Users/michaelrickards/dev/bh2-NS-V1-review/backend/realtime_voice.py:441) similarly defeats its surrounding timeout. This is not acceptable for the hard-cap guarantee; use bounded off-loop work with cancellation-safe accounting.

4. **P2 — Error notification time is billed as session time.** [realtime_voice.py:960](/Users/michaelrickards/dev/bh2-NS-V1-review/backend/realtime_voice.py:960)  
   Duration is captured only after awaiting the error notification. Reproduced an immediate setup-send failure followed by 1.1 seconds delivering the error: one second was accrued. Capture the session’s end timestamp before notifications or teardown.

5. **P2 — Aria is instructed to read a draft she never receives.** [realtime_voice.py:901](/Users/michaelrickards/dev/bh2-NS-V1-review/backend/realtime_voice.py:901)  
   The browser receives `proposal.preview`, but the model receives only a generic message. For an invoice chase, its input was just `invoice_id`; the server-generated recipient, stage, subject and body are unavailable to it. A probe confirmed the template reached the browser but not OpenAI. Return the canonical preview in the tool result so spoken content matches the approval card.

6. **P2 — The grounding repair leaves contradictory instructions.** [realtime_voice.py:452](/Users/michaelrickards/dev/bh2-NS-V1-review/backend/realtime_voice.py:452), [line 472](/Users/michaelrickards/dev/bh2-NS-V1-review/backend/realtime_voice.py:472)  
   Successful email results still say these are the “ONLY emails that exist”; the system prompt similarly calls returned data the only data that exists. With twenty returned emails and an older relevant email outside that sample, this encourages a false absence claim. The test only excludes the literal phrase “does not exist,” so it misses the same claim expressed differently.

7. **P3 — The cap explanation is immediately overwritten.** [RealtimeVoice.tsx:199](/Users/michaelrickards/dev/bh2-NS-V1-review/frontend/client/src/components/RealtimeVoice.tsx:199)  
   `session_limit` sets an explanatory status, then normal socket closure replaces it with “Disconnected.” Preserve the termination reason so the owner understands why the chat ended.

The shared-pool allocation looks correct: both sources consume the same remaining allowance under the existing business/month lock, with separate overage meters and unchanged receptionist defaults. I found no new admission bypass or action-execution path without approval. The GA configuration, quiet-mode update, flat function definitions and renamed audio events match the receptionist pattern and official [client schema](https://developers.openai.com/api/reference/resources/realtime/client-events) / [event guidance](https://developers.openai.com/api/docs/guides/realtime-conversations).

**Verification:** `./check.sh full` passed: 1,756 tests passed, 33 skipped; all five preflight traps passed. The four focused suites passed **201 tests**. The fault probes above expose paths those tests omit: blocked notices, slow accrual, lost-accrual recovery, error-path billing and canonical draft grounding. The fake provider does not validate schema acceptance; browser rendering and live audio remain unverified.

After repairs, Mike’s behaviour checks should cover voice → proposal → spoken “yes” doing nothing → tap approval, quiet mode, and the visible cap explanation. No source edits, commits or pushes; worktree clean.
---

### Response to review 1 — Claude Code (builder), 14 October 2026

Every finding taken. Tests first: 13 new cases, 10 of which failed before the fix.

| Finding | Action |
|---|---|
| 1 · A failed accrual loses voice usage (P1) | **A durable heartbeat**, `voice-open:<session>` in `usage_meters`. It is a marker row with no migration, kept out of every usage sum by the `:`. It is written before the OpenAI connection opens, then every 60 s, pinned to the month the session started. It is removed only after a successful accrual. `metering.reconcile_open_voice_sessions` runs in the scheduler's existing 15-minute catch-up. It bills any session whose heartbeat stopped (stale more than 5 min, and not live in this process) from its last beat, once, keyed on `voice-<id>`. Worst case, a failure under-bills by less than a minute. Tested at the meter level (recovery bills once; a closed session is never billed twice) and at the socket (a failed accrual leaves the heartbeat) |
| 2 · A blocked limit notice defeats the cap (P1) | `finally` is reordered: (1) cancel the watchdog, heartbeat and forwarders; (2) take the end time; (3) start the accrual in a thread; (4) close OpenAI, bounded; (5) only then the limit notice, bounded to 1 s; (6) close the browser, bounded. Tested with a browser that never takes the notice: OpenAI still closes and the session is metered |
| 3 · Synchronous DB work on the event loop (P1) | Admission, the heartbeat, the final accrual and Aria's shared tools all run in worker threads. The accrual is a shielded thread future, so it completes even if the handler is cancelled, with a callback that logs a failure. Tested: a slow (1.5 s) tool does not stop a 0.3 s cap, and a slow (1 s) accrual does not hold the provider open but still completes |
| 4 · Error-notice time is billed (P2) | The end time is taken before any notice, in every exit path. Tested: a 1.2 s error notice bills 0 s |
| 5 · Aria never receives the card she reads aloud (P2) | The tool result now carries `card` (the proposal's canonical preview, e.g. the chase template and recipient) as well as the message. Tested |
| 6 · Contradictory "only data that exists" instructions (P2) | The email wrapper now says these are the most recent emails, not every email, and that if something isn't there she should say it may be older. The system prompt says the response is "the only business data you have". Tested for four phrasings |
| 7 · The cap explanation is overwritten (P3) | The browser keeps the end reason across the normal close, and resets it when a new chat starts |

**Test-harness notes:**
- The slow-tool test times inside the session. On exit, the test harness waits for the still-sleeping tool thread; a live server does not.
- The slow-accrual test installs its fake after the shared fixture, because the fixture installs its own recorder.
