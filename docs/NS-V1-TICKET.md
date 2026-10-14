# NS-V1 — Aria's voice restored: current OpenAI format, metered, cards by tap

**Tier:** RED (the most expensive thing the app does; metering; outbound
actions). **Builder:** Claude. **Reviewer:** Codex. **Tests first, reviewed by
Mike.** Mike, 14 Oct 2026: "yes please, let's restore the voice".
**Decisions it builds on:**
- ADR 0001 D2: voice off until repaired, the repair after metering;
- D18: approval by tap, even in voice;
- BH-012's meter;
- NS-B10's approval cards.

## Why voice is off

NS-A2 switched it off server-side on 2 Oct 2026 after Mike's test showed it
broken.

Cause: `realtime_voice.py` still speaks OpenAI's **beta** Realtime protocol.
It sends the `OpenAI-Beta: realtime=v1` header and the beta `session.update`
shape (`modalities`, `input_audio_format`, `voice` at the top level). The GA
API rejects this. The phone receptionist was moved to GA in July
(`receptionist_call_handler.py`, PHASE 3, the worked example).

## What changes

1. **The current (GA) protocol, end to end:**
   - no beta header;
   - `session.type = "realtime"`, `session.model`;
   - `session.audio.input` / `session.audio.output`, including the format,
     transcription, turn detection and voice;
   - the GA server event names (e.g. `response.output_audio.delta`).
   The browser (`RealtimeVoice.tsx`) is updated to match, so nothing the
   owner sees depends on a beta event name.
2. **Metered**, using BH-012's generic meter:
   - minutes are counted per second, in the UK calendar month, from the
     session's actual length;
   - a session is refused when the allowance is used up and extra minutes are
     off, with the same notices and banner as the receptionist;
   - usage is shown in the app.
3. **A hard cap on every session**, using BH-012's watchdog pattern:
   - the session ends at the cap, setup included;
   - teardown is never billed.
4. **Voice can raise approval cards (D18).** When Aria, speaking, prepares an
   email, chase, booking or task:
   - it becomes the same NS-B10 card, shown on screen;
   - Aria reads the draft aloud and says it's on the screen to approve;
   - the owner taps;
   - "yes" said aloud is never an approval.
   Voice still never sends anything itself. `delete_task` stays refused.
5. **Grounding fixes that must land before voice returns** (backlog,
   Codex NS-A1 review 2):
   - the voice instructions' "DOES NOT EXIST" wording for absent data;
   - the `list_emails` wrapper dropping `error`, so a connection failure reads
     as an empty inbox.
6. **Switching it on is Mike's step:** `ARIA_VOICE_ENABLED=1` in Railway,
   after the deploy and the click tests.

## Decisions for Mike

- **V1 — One pool of voice minutes, or two?** The pricing model prices one
  "voice allowance" per plan (Pro 120 min, Business 350, Starter none), and
  BH-012 put the receptionist on it.
  - *Recommended:* **one pool**. Aria voice and the receptionist both draw
    from it. The usage card becomes "Voice minutes", with a split showing
    receptionist and Aria. One number for the customer; it matches the
    pricing.
  - *Alternative:* a separate Aria-voice allowance, with numbers you set.
- **V2 — Per-session cap.**
  - *Recommended:* **20 minutes**, as for phone calls. A longer chat simply
    starts again.
- **V3 — If the meter can't be read.**
  - *Recommended:* **refuse the voice session** (fail closed). The owner can
    still type to Aria, and no customer is affected.
  - This is deliberately different from the receptionist, which fails open
    so a customer's call is never missed.
- **V4 — Starter plans.**
  - *Recommended:* **no voice**, as the pricing model says (`aria_voice` is
    off for Starter). With V1, a Starter business that switches on extra
    minutes would still not get Aria voice; the feature gate decides first.

## Acceptance (the tests encode these)

1. **The session is configured in the GA shape:**
   - no `OpenAI-Beta` header;
   - the instructions, tools, voice, formats, transcription and turn
     detection are where GA expects them.
   - Tested against a fake OpenAI socket.
2. **The browser receives the GA events it renders:** audio, transcripts,
   speech start/stop and errors. Beta-only names are gone from both sides.
3. **No session opens when:**
   - the business lacks `aria_voice`;
   - the account is read-only or suspended;
   - the voice minutes are used up (and extra minutes are off);
   - the meter can't be read (V3).
   No connection is made to OpenAI in any of these cases.
4. **A session's minutes are recorded once**, against the month it ended in.
   Two businesses never share minutes. Under V1, the receptionist and Aria
   accrue to the same allowance and are shown split.
5. **The session ends at the cap**, setup included, and only its time up to
   the cap is billed.
6. **Voice actions:**
   - a voice tool call for any of the four approvable actions creates an
     NS-B10 proposal, sends a `proposal` event to the browser, and acts on
     nothing;
   - the browser shows the card;
   - `delete_task` and unknown tool names are refused;
   - only audio and `config` from the client ever reach OpenAI (the NS-A1
     tests stay green).
7. **Grounding:** absent data is described as "I couldn't find…" or "that
   isn't connected", never "does not exist", and an email error reaches Aria
   as an error.
8. **`ARIA_VOICE_ENABLED` still switches voice off completely**, before any
   provider connection.
