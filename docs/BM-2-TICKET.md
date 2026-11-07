# BM-2 — Board meetings by voice

**Tier:** RED (metering, entitlement, the most expensive model). Tests first.
**Builds on:** BM-1 (PR #86) — the typed meeting works.

## Mike's decisions (6 Nov 2026)

1. A board meeting can be spoken (back-and-forth with Aria) or typed, and the
   owner can switch at any point. Typing stays the cheap default.
2. Board-meeting voice has its **own** monthly allowance, separate from the
   receptionist / Aria voice pool, so meetings can never use up the minutes
   that answer customers' calls: **Pro 60, Business 150, beta 150, Starter 0**.
3. Past the allowance: the existing opt-in overage, **£0.45/min**, under the
   owner's monthly spend cap. The cap is ONE cap for all extra minutes: it is
   judged on the overage of both pools together, so switching board voice on
   never doubles what the owner agreed to spend.
4. The owner sees the minutes left before speaking, a warning at 80% used,
   and, when the minutes run out mid-meeting, Aria finishes what she is saying
   and the meeting carries on typed. Nothing is lost.
5. No top-up packs, no price rise (revisit in the pre-launch pricing review).

## Design

### Metering (`services/metering.py`)
- A second **pool**, `board_meeting`, with its meters
  `board_meeting_voice_minutes` / `board_meeting_voice_overage_minutes` and
  its own allowances. The existing pool (`voice`: receptionist + Aria voice)
  is unchanged in behaviour.
- `usage(session, business, pool="voice")`; `admit_call(..., pool=...)`;
  `accrue_session(..., source="board_meeting")` allocates in the source's pool.
- Spend (and so the cap) = overage of **all** pools x £0.45.
- `seconds_allowed(usage)` for a new board session: the minutes left inside the
  allowance, plus, with overage on, what the remaining cap buys; at most 60 min.
- Board sessions' ids start `bm-`, so heartbeat recovery bills them to the
  board pool.
- No owner email for the board pool's allowance (the meeting screen says it);
  a spend cap reached is told as today.
- `profit_guard.VOICE_METERS` includes the board meters (cost is counted).

### Voice socket (`realtime_voice.py`)
- Auth message may carry `meetingId`. Then:
  - feature `board_meetings` (not `aria_voice`); the meeting must belong to the
    business and be `in_progress`, else refused before OpenAI;
  - admitted against the board pool; session length = `seconds_allowed`;
  - instructions = the meeting's system prompt (prep data) + a voice addendum
    + the transcript so far (switching mid-meeting keeps context); no tools;
  - each completed owner transcription and each finished Aria transcript is
    saved as a meeting message, so `/end` extraction and summary work;
  - at the session's limit, if Aria is mid-reply she finishes (up to 20s), the
    client gets `session_limit` with `reason` and the meeting continues typed.
- Without `meetingId` nothing changes.

### API
- `GET /v1/executive-meetings/voice-usage` → allowance, used, remaining,
  overage on/off, state, `warn` (>= 80% used).

### Frontend
- Meeting chat: **Talk / Type** switch; minutes-left line; 80% warning;
  `RealtimeVoice` gains a `meetingId` prop and reports why it ended; spoken
  turns appear in the chat as they are transcribed.

## Acceptance
- Board minutes never touch the receptionist pool and vice versa.
- One spend cap across both pools.
- A refused meeting session never reaches OpenAI.
- A spoken meeting's transcript is in the meeting's messages; `/end` works.
- A session stops at the allowance and the client is told to type.
