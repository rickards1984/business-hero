# NS-A1 — Codex reviews

## Review 1

| | |
|---|---|
| Reviewed commit | `cca19a5` (`ticket/NS-A1-no-unapproved-actions`; tests `4d2ab00` + fix) |
| Tool | Codex CLI 0.153.4, `codex exec --sandbox workspace-write`, prompt on stdin |
| Model | `gpt-6-astra` |
| Session id | `01a10d72-b01a-7ca2-b533-10b6dfffd810` |
| Usage, as reported | `tokens used 70,240` |
| **Verdict** | **REQUEST-CHANGES** — wording; no execution path found |

Verbatim:

---

**REQUEST-CHANGES.** The server-side action boundary looks sound; I found no path through Aria chat or voice that executes the five prohibited actions. The remaining issues are misleading instructions and incomplete prompt regression coverage. This review serves North Star P4 and P8.

1. **P2 — Voice still explicitly models a successful invoice chase.**  
   [backend/realtime_voice.py:577](/Users/michaelrickards/dev/bh2-NS-A1-review/backend/realtime_voice.py:577) gives this example: “Done — I've sent a polite chase…”. Line 513 still offers “Want me to chase any of them?” Both contradict the new refusal instructions and the required behaviour. Also, [backend/assistant_tools.py:2640](/Users/michaelrickards/dev/bh2-NS-A1-review/backend/assistant_tools.py:2640) tells Aria to send a generated reply using `send_email`. Remove these contradictory instructions and cover them with regression assertions. The current prompt tests only search for tool identifiers, so the English chase examples pass.

2. **P2 — The new email handoff promises an Inbox draft that does not exist.**  
   [backend/assistant_chat.py:280](/Users/michaelrickards/dev/bh2-NS-A1-review/backend/assistant_chat.py:280), [backend/realtime_voice.py:505](/Users/michaelrickards/dev/bh2-NS-A1-review/backend/realtime_voice.py:505), and the refusal at `assistant_tools.py:442` tell the owner to open Aria’s draft in their Inbox. `_draft_email_reply` only returns text; it never persists a draft. [frontend/client/src/pages/Inbox.tsx:168](/Users/michaelrickards/dev/bh2-NS-A1-review/frontend/client/src/pages/Inbox.tsx:168) independently generates new drafts, then sends by draft ID. Correct the wording to describe the actual manual handoff; do not introduce persistence within this fix.

3. **P2 — Voice promises free slots without an availability tool.**  
   [backend/realtime_voice.py:507](/Users/michaelrickards/dev/bh2-NS-A1-review/backend/realtime_voice.py:507) instructs Aria to say “Here are the free slots”. Voice’s tool map has no `check_calendar_availability`; `get_schedule` returns a calendar briefing, not computed availability. Direct the owner to Calendar, or otherwise qualify what voice can actually establish.

The rest of the requested audit:

- **Execution boundaries:** `assistant_tools.execute_tool:482`, `assistant_chat._execute_tool_async:24`, and `realtime_voice.execute_tool:284` refuse before invoking an action. Voice explicitly handles the historical aliases and rejects unmapped names. Neither advertised list includes the five.
- **Other callers:** `_send_email`, `_send_invoice_chase`, `_create_task`, and `_delete_task` in `assistant_tools` have no external callers bypassing these boundaries. `_send_gmail_message` and `_send_microsoft_message` are called only by the blocked email/chase implementations. The exception is `create_calendar_event`, called directly by the **phone receptionist** at `receptionist_call_handler.py:424`. That remains operational, but is not reachable through Aria chat/voice tools; ADR D10 explicitly keeps the receptionist separate. The receptionist also has its own unrelated `_create_task`, called at lines 181, 218 and 264.
- **All 22 remaining tools inspected:** No business-action mutation found. SQL reporting tools read records; Xero reporting uses GET. Email/calendar reads can refresh OAuth tokens, which performs provider POSTs and updates `email_accounts` (`assistant_tools.py:768`, `:818`). Calendar availability uses a read-only FreeBusy POST. `generate_ai_quote` and `draft_email_reply` call OpenAI but neither saves nor sends anything. `send_quote` only reads the quote and directs the owner to Quotes. Consequently, “no writes whatsoever” would overstate this change: credential maintenance remains.
- **Other misleading, pre-existing quote instructions:** `assistant_chat.py:349` and the generation result at line 189 offer to save a quote without a saving implementation. The `send_quote` description at `assistant_tools.py:398` claims delivery although its implementation only provides directions. These are not execution bypasses.
- **Tests are genuine for execution safety:** Recorded tripwires catch actions running before a refusal; `_assert_refused` requires literal `True` and a nonempty error. Reintroducing an old alias into `tool_name_map` alone would **not** fail the tests, because the earlier alias refusal still blocks it. A new alias targeting a prohibited canonical name would still encounter the shared dispatcher’s refusal, but the suite does not enumerate arbitrary future aliases. Read preservation is dynamically tested only for tasks; other reads were inspected.
- **Browser compatibility:** `RealtimeVoice.tsx:175`, `:237`, `:480` sends auth, binary audio and config only. Auth is consumed during handshake; config becomes a server-built VAD update. The JSON filter does not break an existing browser message type.
- **Dependencies:** No other consumers of the removed tool definitions found. WhatsApp’s numbered action path independently calls `send_chase_for_invoice`; automation independently inserts tasks. Neither depends on these lists nor is callable through the remaining Aria tools. Their existing behaviour remains unchanged.

The permitted test command returned **38 passed, 1 deprecation warning**. No files edited, pushes or network access. Full `check.sh` and live UI/provider behaviour were not tested.

After correction, Mike’s behavioural check is to ask Aria to send a reply and chase an invoice: she should explain the limitation, give accurate manual steps, and never claim delivery or an Inbox draft.
---

### Response to review 1 — Claude Code, 5 October 2026

Every finding taken. Each was checked against the code and the screens first.

| Finding | Action |
|---|---|
| 1 · Voice still models a successful chase (`:577`, `:513`); `draft_email_reply` tells Aria to `send_email` (`assistant_tools.py:2640`) | Both voice examples rewritten as refusals that point to Finance; the draft instruction now says copy it into a reply, "You cannot send it". New test `test_aria_is_told_nothing_that_promises_an_action_or_a_missing_place` scans the chat prompt, the voice prompt, every tool description and every refusal for 13 misleading phrases; `test_tool_results_do_not_promise_sending_or_saving` covers the two tool results |
| 2 · "Open it in your Inbox" promises a draft that does not exist | All three places now say: the draft is shown in the conversation, copy it into a reply from your own email, and it is not saved anywhere. **This changes wording Mike approved on 5 Oct**, because it was inaccurate; flagged to him |
| 3 · Voice promises free slots with no availability tool | Voice now offers what is already in the diary and says to add the new one in their own calendar; chat keeps `check_calendar_availability` |
| Chase hand-off | Matched to the real control: "open the invoice in Finance and use Send Chase Email" (`InvoicesPanel.tsx:955`) |
| Tasks hand-off | Matched to the real place: the Tasks panel on the Dashboard (`DashboardPage.tsx:8`) |
| Pre-existing quote over-promises (`assistant_chat.py:349`, `:189`, `send_quote` description) | Fixed: Aria says the quote is created from the Quotes page; `send_quote` describes itself as "does not send anything" |
| An old alias re-added to the voice map would not fail a test | The map is now module-level `VOICE_TOOL_MAP`; `test_no_voice_tool_maps_to_a_prohibited_action` fails on any alias to a prohibited action |
| Receptionist calls `create_calendar_event` directly | Out of scope, as Codex notes: not Aria-reachable, and ADR 0001 keeps the receptionist separate |
| OAuth token refresh writes `email_accounts` | Credential maintenance, not a business action; NS-A1's claim is "no business action", not "no writes" |

Tests: 42 pass; against `cca19a5`, 11 of them fail. `./check.sh full` green.
