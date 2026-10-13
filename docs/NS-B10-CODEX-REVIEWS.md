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