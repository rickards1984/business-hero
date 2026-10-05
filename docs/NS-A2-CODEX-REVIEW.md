# NS-A2 — Codex review

| | |
|---|---|
| Reviewed commit | `67a1593` (`ticket/NS-A2-voice-off`), parent `5853f21` |
| Tool | Codex CLI 0.153.4, `codex exec --sandbox workspace-write` (to run pytest), prompt on stdin |
| Model | `gpt-6-astra` |
| Session id | `01a0fe53-a770-7781-b720-bf9c3e3d34b5` |
| Worktree | `~/dev/bh2-NS-A2-review`, detached; reviewer made no edits |
| Usage, as reported | `tokens used 35,115` |
| **Verdict** | **ACCEPT** |

Verbatim below; response at the end.

---

**ACCEPT.** No blocking defects found in `67a1593` against parent `5853f21`. This serves ADR 0001 D2 and the North Star stability prerequisite.

One non-blocking limitation:

- **Low — status can become stale:** `frontend/client/src/pages/AssistantChat.tsx:62` fetches availability only on mount. A page that previously received `available: true` can retain voice buttons after the server switches off. Attempts still receive 4010 before authentication or provider access. Reloading hides the buttons.

Review conclusions:

1. **No Aria Realtime bypass found.** `backend/realtime_voice.py:673` returns before authentication and the sole provider connection at line 760. No other production module imports its executor. The receptionist has its own Realtime connection and is outside this switch.

   `/v1/tts` (`backend/main.py:2415`) remains callable by authorised, entitled users. It uses `audio.speech.create` with `tts-1`, not Realtime; chat’s `voiceMode` only changes prompting. TTS is outside this Realtime shutdown’s scope. The reported beta error does **not** establish that TTS is broken; live functionality was not tested.

2. **The tripwire is genuine, with a coverage distinction.** `backend/tests/test_aria_voice_switch.py:37` patches the dependencies where the handler imports them and records calls before raising. Moving the guard after token verification would fail: authentication is recorded and returns 4001 instead of 4010. Moving it after `websockets.connect` would also fail, although authentication would stop execution first. Thus the tests detect both reorderings, but do not independently exercise provider refusal with successful authentication.

3. **Status endpoint is appropriate.** `backend/realtime_voice.py:652` exposes only a global boolean and fixed message, with no tenant information. Static inspection found no conflicting route. The generic literal-route checks in `backend/tests/test_route_resolution.py` would cover this endpoint, but I did not run that suite.

4. **Frontend fails closed.** Both entry buttons require availability; pending, failed HTTP requests and JSON parsing failures leave them hidden. Text chat remains usable. `frontend/client/src/components/RealtimeVoice.tsx:186` explains a 4010 close.

5. **Default-off deployment matches D2.** `backend/realtime_voice.py:38` enables voice only for exactly `"1"`. No other production reader was found. With that variable absent, the next backend deployment disables new Aria Realtime sessions without a Railway configuration change. Actual Railway values were not inspected. This is an admission guard, not an active-session termination mechanism.

**Verification:** permitted pytest run passed: **11 passed**, one dependency deprecation warning. No files edited or network used; working tree remains clean. Full checks and browser testing were not run.

**Behaviour check:** open Aria, confirm “Talk to Aria” is absent, send a text message, and confirm the conversation’s “Voice” button is also absent.
---

## Response — Claude Code, 2 October 2026

| Observation | Action |
|---|---|
| Status fetched only on mount, so a tab opened while voice was on keeps its buttons after the switch goes off | **Accepted as is.** The server still refuses with 4010 before authentication, and `RealtimeVoice.tsx` turns that into the upgrade message, so the stale button fails safely and explains itself. Polling a platform-wide flag on every page is not worth it for a switch that changes perhaps twice |
| `/v1/tts` is outside the switch | Agreed and intended: it is plain TTS (`tts-1`), not Realtime, and nothing shows it is broken |
| The tests don't exercise "authenticated, then provider refused" | Out of scope while voice is off; the GA-migration ticket owns that path |
