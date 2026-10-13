# NS-B10 — Codex reviews, verbatim

## Review 1

| | |
|---|---|
| Reviewed commit | `4e45237` |
| Session id | `01a13755-b0be-74c1-ac9e-f020f2df291e` |
| Model | `gpt-6-astra` |
| Usage, as reported | `tokens used 78,330` |
| **Verdict** | **REQUEST-CHANGES** |

Verbatim:

---

**REQUEST-CHANGES** — reviewed `4e452375a1ee2ace96c68dd73c408e42563b3006` against `origin/main`. The core claim protects against executing the same action twice, but the approval experience does not yet reliably uphold P4: approving exactly what the owner sees.

1. **P1 — A stale preview can approve different content.** [ApprovalCard.tsx:78](/Users/michaelrickards/dev/bh2-NS-B10-review/frontend/client/src/components/ApprovalCard.tsx:78), [aria_actions.py:339](/Users/michaelrickards/dev/bh2-NS-B10-review/backend/services/aria_actions.py:339).  
   Scenario: an owner changes the recipient, PATCH commits, but its response is lost. They click Cancel, see the original recipient, then approve. Approval submits only the action ID and sends the changed recipient stored on the server. Another member editing the same action creates the same problem. Bind approval to the displayed payload’s version/hash, and reconcile uncertain edits before enabling approval.

2. **P1 — Provider uncertainty is presented as definite failure.** [aria_actions.py:368](/Users/michaelrickards/dev/bh2-NS-B10-review/backend/services/aria_actions.py:368), [ApprovalCard.tsx:176](/Users/michaelrickards/dev/bh2-NS-B10-review/frontend/client/src/components/ApprovalCard.tsx:176).  
   Scenario: Gmail accepts the message but the response times out. `_send_email` converts that exception into failure; approval returns a `failed` card saying **“Not done”**. The owner can reasonably request another chase, duplicating delivery. Calendar timeouts have the same issue. Preserve an uncertain outcome and instruct the owner to check delivery; reserve definite failure wording for confirmed rejection.

3. **P1 — Booking invitations contain undisclosed text.** [ApprovalCard.tsx:129](/Users/michaelrickards/dev/bh2-NS-B10-review/frontend/client/src/components/ApprovalCard.tsx:129), [aria_actions.py:394](/Users/michaelrickards/dev/bh2-NS-B10-review/backend/services/aria_actions.py:394).  
   The card omits `description`, although execution sends it to Google with attendee invitations. A model-generated description containing internal customer notes can therefore leave the business without appearing in the approval preview. Display the complete description before approval.

4. **P2 — Dismissal can overwrite an executing or completed action.** [aria_actions.py:480](/Users/michaelrickards/dev/bh2-NS-B10-review/backend/services/aria_actions.py:480).  
   Scenario: dismissal reads `proposed`; another request claims and commits; dismissal then unconditionally writes `dismissed`. It reports successful cancellation while the send proceeds—or overwrites `done` after delivery. Make dismissal a conditional, tenant-scoped update from `proposed`, checking the returned row. If approval wins, dismissal must return conflict.

5. **P2 — Approval conflicts leave the Approve button active.** [ApprovalCard.tsx:83](/Users/michaelrickards/dev/bh2-NS-B10-review/frontend/client/src/components/ApprovalCard.tsx:83).  
   Scenario: another member has approved an action that remains `executing` after a crash. This card receives 409, displays “already being sent”, but retains local `proposed` status and offers another approval tap. Expired cards similarly retain active controls. Reconcile authoritative status on conflict and disable terminal/uncertain actions. The backend prevents duplicate execution, but the frontend requirement is unmet.

6. **P2 — An old chase can move the invoice’s stage backwards.** [aria_actions.py:437](/Users/michaelrickards/dev/bh2-NS-B10-review/backend/services/aria_actions.py:437).  
   Scenario: a stage-1 proposal remains open while other chases advance the invoice to stage 3. Approving the old card unconditionally writes `chase_stage = 1`; subsequent chasing repeats earlier stages. Reject stale proposals or preserve monotonic stage advancement while recording the actual sent stage in the outbox.

7. **P2 — Aria cannot read the new action records.** [aria_actions.py:490](/Users/michaelrickards/dev/bh2-NS-B10-review/backend/services/aria_actions.py:490).  
   `list_open` is exposed only through the HTTP API; no Aria read tool retrieves action status or outcomes. After approval, “Did that chase send?” cannot be grounded in the action record, especially for failed or interrupted sends. This misses AGENTS.md’s explicit requirement that new stored data ship with a tenant-scoped Aria read tool.

The central approval UPDATE commits before all four execution paths. I found no path that resets an action to `proposed`, nor a bypass for these five prohibited actions through the shared or voice executors. Cross-business API operations are checked through `_scoped`; however, `_set` and the edit UPDATE lack explicit `business_id` predicates, relying on the preceding scoped lookup.

The entitlement gates, paid-since-proposal check, timezone/DST handling, calendar ID forwarding, and synchronous route → worker thread → `asyncio.run` arrangement look correct. The PostgreSQL parameter forms—explicit JSONB casts, aware datetimes, string UUIDs, and `ARRAY[:to_email]`—show no apparent adaptation defect on inspection. **I did not execute the application paths against PostgreSQL.**

Verification passed:

- `./check.sh full`: **1,672 passed, 33 skipped**, 220 subtests; typecheck, compilation, Ruff and preflight passed.
- Focused tests: **96 passed**.

The tests provide useful service and access-boundary evidence, but mock all three executors. Their “concurrent” approval test re-enters through SQLite `StaticPool`, sharing one connection; it does **not prove commit visibility across independent PostgreSQL transactions**. Missing coverage includes the races above, actual PostgreSQL payload/outbox writes, provider-accepted-then-timeout responses, and frontend uncertainty handling.

No files edited, committed, or pushed; working tree remains clean.
---

### Response to review 1 — Claude Code (builder), 13 October 2026

Every finding taken. Tests first: 16 new cases, 11 of which failed before the fix.

| Finding | Action |
|---|---|
| 1 · A stale preview can approve different content (P1) | Each card carries a `version` (a fingerprint of the exact payload). The API requires it on approve (422 without it). A different stored version gets 409, "This card has changed since you saw it", and nothing is sent. The claim UPDATE itself also requires `payload = <the payload just read>` (jsonb equality on Postgres), so an edit landing between the check and the claim is refused too. New `GET /v1/aria/actions/{id}` lets the card re-read its state. Tested in the service and through the API |
| 2 · Provider uncertainty shown as failure (P1) | An exception while sending, or an unconfirmed send (`Send failed…` / `did not confirm`), or a Google 5xx/429 on booking, leaves the action `executing` with "Outcome unknown: …". It is never retried and the card says to check before asking again. `failed` ("Not done") is kept for definite rejections and pre-send failures. One approved test was changed deliberately: it now injects a definite rejection, not an exception |
| 3 · Booking invitations carry undisclosed text (P1) | The card shows the description, labelled "Included in the invitation" when there is an attendee, and says "Google will email an invitation to …". The preview carrying both is tested |
| 4 · Dismissal can overwrite an approval (P2) | Dismissal is a conditional, business-scoped UPDATE from `proposed` with RETURNING. If approval won, dismissal gets 409. Tested by dismissing during sending |
| 5 · Approve stays live after a conflict (P2) | Any 4xx or uncertain outcome re-reads the card from the server. Approve shows only for `proposed` and unexpired cards. Uncertain outcomes switch the controls off |
| 6 · An old chase moves the stage backwards (P2) | Approval refuses a chase whose stage is not ahead of the invoice's current stage ("out of date… ask Aria for a fresh one"), and nothing is sent. The stage update is monotonic as well. Tested |
| 7 · Aria cannot read the action records (P2) | New read tool `list_aria_actions`: this business only, newest first, with each card's status and its meaning. Tested for tenant scope |
| `_set` / edit lack `business_id` predicates | Both now include it |

Not done, with reasons:
- No PostgreSQL execution of the application paths. Staging proved the claim
  and the CHECKs (`audits/035-STAGING-REHEARSAL.md`). End-to-end proof is the
  post-deploy click test.
- No frontend unit tests. The repo has no frontend test harness; the PR click
  tests cover the card.

## Review 2 (repair cycle 1 of 3)

| | |
|---|---|
| Reviewed commit | `6a54b1a` |
| Session id | `01a1375a-e3e2-7da1-93f7-a94bb20c426e` |
| Model | `gpt-6-astra` |
| Usage, as reported | `tokens used 42,672` |
| **Verdict** | **REQUEST-CHANGES** |

Verbatim:

---

**REQUEST-CHANGES** — reviewed `6a54b1a1376585472e40b9f751e77be83ab4eb5c`.

1. **P1 — Calendar uncertainty can still become “Not done”.** `backend/services/aria_actions.py:352`; `backend/assistant_tools.py:2047`.  
   Scenario: Google returns 401, token refresh succeeds, the retried booking creates the event but its response times out. The calendar helper catches that exception and returns “Calendar token expired”. `_unknown_outcome` classifies this as definite failure, inviting another booking and duplicate invitations. Preserve uncertainty for exceptions during the retried POST. The new tests mock the entire calendar helper, missing this path.

2. **P2 — Failed reconciliation leaves Approve enabled after a conflict.** `frontend/client/src/components/ApprovalCard.tsx:81`, `:96`.  
   Scenario: another member approves; this card receives 409; the reconciliation GET fails. Its catch changes nothing, `uncertain` remains false, and local status remains `proposed`. Approve becomes active again. Disable controls until authoritative reconciliation succeeds.

3. **P2 — The regression tests do not exercise the repaired races.** `backend/tests/test_aria_actions.py:712`, `:811`.  
   The version test edits **before** approval reads the row; removing the claim’s payload predicate would still pass. The dismissal test starts dismissal **after** approval claims; the original broken dismissal would also pass. Add interleavings between approval’s read and claim, and between dismissal’s read and UPDATE, respectively.

4. **P3 — The new read tool describes expired cards as awaiting approval.** `backend/assistant_tools.py:2917`.  
   Scenario: an untouched proposal passes its 72-hour expiry. Its stored status remains `proposed`; the tool neither selects nor evaluates `expires_at`, so Aria reports it as awaiting approval although approval is impossible. Derive effective expiry and test it.

Original findings **1, 3, 4 and 6 are fixed in code**; **2 and 5 remain incomplete**. Finding **7’s tenant-scoped tool exists and its scope is tested**, with the expiry defect above. The version fingerprint, PostgreSQL JSONB equality versus SQLite’s preserved stored text, and monotonic chase update look correct on inspection; PostgreSQL execution remains unverified. The stale-chase test covers the reported stage-1/stage-3 scenario.

The deliberate approved-test changes do **not** weaken their contracts: API requests now supply versions, definite rejection remains tested, and exceptions separately assert uncertainty.

Verification: `./check.sh full` passed (**1,687 passed, 33 skipped**); focused tests **111 passed**. Frontend reviewed by inspection, not browser execution.

Otherwise: no additional findings; no files edited, committed or pushed; working tree clean.
---

### Response to review 2 — Claude Code (builder), 13 October 2026

Every finding taken. Tests first: 5 new tests, 2 of which failed before the fix. The 2 race tests were mutation-checked against the bugs they guard.

| Finding | Action |
|---|---|
| 1 · A retried booking's timeout is reported as "token expired" (P1) | `create_calendar_event`: only the token *refresh* is inside the try, so a refresh failure is still a definite "reconnect Google". The retried POST is outside the try, so its timeout propagates and `approve()` records it as an unknown outcome (`executing`). Two tests drive the real helper with only its HTTP client faked: one where the refresh works and the retry times out, and one where the refresh fails. The receptionist's first POST already propagated exceptions the same way, and its booking tests pass unchanged |
| 2 · A failed re-read leaves Approve enabled (P2) | If re-reading the card fails, the controls switch off (`uncertain`). The message now says to check, then refresh the page |
| 3 · The race tests do not exercise the windows (P2) | Both races are now driven at the exact window: an edit between approve's read and its claim, and an approval between dismiss's read and its write. Mutation check: removing the claim's payload predicate fails the first; making dismissal unconditional fails the second |
| 4 · The read tool calls expired cards "awaiting approval" (P3) | The tool reads `expires_at` and reports an untouched card past expiry as `expired`. Tested |
