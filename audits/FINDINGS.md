# Findings — ruff cleanup pass (2026-08-16)

Surfaced while clearing `ruff check backend` from 92 findings to 0
(`select = ["F", "E9"]`, see root `ruff.toml`). These are not fixed — each
is either a real behavioural gap or a signal of one, and needs a product/eng
call before touching the code. All three F841 leaves carry an inline
`# noqa: F841` with the same TODO text as below, so ruff stays green without
hiding them.

---

## 1. Daily pulse discards its AI-generated text

**File:** `backend/services/briefing_scheduler.py:553`

```python
pulse_text = await generate_daily_pulse(business_name, owner_name, data)
```

`generate_daily_pulse` makes a real OpenAI call to write the daily pulse
narrative. `pulse_text` is never read afterward — `_send_daily_pulse` builds
and sends a separate hardcoded structured summary instead
(`calls_summary` / `emails_summary` / `tasks_summary` / `snapshot`, all
built directly from `data`).

The weekly sibling does this correctly: `_send_weekly_briefing`
(same file, `~line 741`) calls `generate_weekly_briefing`, and all three of
its outputs (`briefing_text`, `action_options`, `ai_analysis`) are used —
stored, and used to build reply-action buttons. The daily path is the
outlier.

**Why it matters:** every scheduled daily pulse run pays for an OpenAI
call whose output is thrown away. Either the daily pulse should incorporate
`pulse_text` the way the weekly one does, or the call should be deleted
entirely — as written it's pure cost with no effect.

---

## 2. Gmail body extraction may decode non-text parts as text

**File:** `backend/assistant_tools.py:971` (inside `_extract_gmail_body` →
`get_body_from_part`)

```python
mime_type = part.get("mimeType", "")
body = part.get("body", {})
if body.get("data"):
    decoded = base64.urlsafe_b64decode(body["data"]).decode("utf-8", errors="ignore")
    ...
```

`mime_type` is read but never checked before decoding. Any message part
with `body.data` — including a non-text attachment — gets base64-decoded
and treated as UTF-8 body text. The unused variable, sitting exactly where
a `mime_type in ("text/plain", "text/html")` guard would go, looks like a
dropped filter rather than dead code.

**Why it matters:** low severity today (`errors="ignore"` means it degrades
to garbled text rather than crashing), but any email with a non-text first
part could show mangled content in the assistant's email summaries.

---

## 3. Palette colour defined but never applied in quote PDFs

**File:** `backend/services/quote_pdf.py:49`

```python
primary = HexColor('#7c5cfc')
dark_bg = HexColor('#1a1c22')
light_text = HexColor('#e8e6e1')   # never referenced again
muted = HexColor('#6b7280')
border_color = HexColor('#e5e7eb')
```

Every other colour in this palette is applied to a style somewhere in the
function; `light_text` isn't. The one place it would plausibly belong — the
line-items table header, which sits on `dark_bg` — already uses `white`
for its text colour (`quote_pdf.py:213`), so there's no live readability
bug. Reads as unfinished styling, not a functional gap.

**Why it matters:** lowest priority of the three — flagging for
completeness. Worth a quick look to confirm nothing was meant to render in
this colour before deleting it.

---

## 4. `accounting.py` does money math in `float`, not `Decimal`

**File:** `backend/accounting.py` (schema fields `amount: float` /
`amount: Optional[float]`, plus `float(row[3])`, `_parse_amount` returns
float, etc.)

The file previously had an unused `from decimal import Decimal` import
(removed in this pass). It's unused because nothing in the file does money
math with `Decimal` — every amount field, parse, and aggregate uses
`float`.

**Why it matters:** this is the known gap — CLAUDE.md's own roadmap already
scopes a "money engine (Decimal, per-line VAT...)" as the next RED-tier
piece of work, blocking Stripe. Flagging here as confirmation of scope, not
as a new discovery: the stray `Decimal` import was very likely a marker
left from planning that work, not evidence it was ever started.

---

## 5. `nova` voice is supported but missing from the customer-facing picker

**File:** `backend/receptionist_api.py` — `AVAILABLE_VOICES` (~line 164) vs.
`backend/services/voice_presets.py:26` `KNOWN_STABLE_REALTIME_VOICES`

```python
# voice_presets.py
KNOWN_STABLE_REALTIME_VOICES = {
    "shimmer", "alloy", "echo", "ash", "ballad", "coral", "sage", "verse", "nova",
}
```

`receptionist_api.py` imported `KNOWN_STABLE_REALTIME_VOICES` but never
used it — not to validate `AVAILABLE_VOICES`, not to build it. Diffing the
two by hand: `AVAILABLE_VOICES` lists 8 of the 9 known-stable voices.
**`nova` is missing entirely** — not offered anywhere in the receptionist
voice picker.

**Why it matters:** a real, currently-supported OpenAI realtime voice that
customers can't select. Either add it to `AVAILABLE_VOICES` with a
name/description/accent entry matching the others, or — if `nova` was
deliberately excluded (e.g. quality/accent concerns) — the constant should
reflect that so this doesn't look like a bug again next time someone reads
the import.

---

## 6. `DEFAULT_PRESET_ID` duplicated as a hand-typed literal

**File:** `backend/receptionist_api.py:74` vs.
`backend/services/voice_presets.py:30`

```python
# voice_presets.py
DEFAULT_PRESET_ID = "shimmer_british"

# receptionist_api.py — the constant above is imported but this is hardcoded instead:
voice_preset_id: Optional[str] = SQLField(default="shimmer_british")
```

`DEFAULT_PRESET_ID` was imported but never referenced; the SQLModel field
default duplicates its value by hand instead. Matches today — but it's a
silent-drift trap: if `DEFAULT_PRESET_ID` ever changes, this default won't
follow, and nothing will flag the mismatch.

**Why it matters:** low urgency, easy fix (`default=DEFAULT_PRESET_ID`) —
left alone here only because touching a `SQLField` default is
schema-adjacent per the working agreement's RED tier, not because there's
any doubt about the right answer.

---

## 7. `get_or_create_smtp_account` is fully built but never called

**File:** `backend/app/email/service.py:288` (definition); previously
imported unused in `backend/app/email/router.py` and `backend/main.py`
(both removed in this pass)

```python
def get_or_create_smtp_account(
    session: Session, business: Business, user_id: str, connection: EmailConnection,
) -> EmailAccount:
    """Create a shadow SMTP account so email_outbox can link to an account."""
```

Grepped the whole backend — this function is defined once and called
nowhere. It was imported in two places (router and main) but never invoked
in either.

**Why it matters:** the docstring describes a specific purpose (linking
SMTP-sent mail to an `email_outbox` account record) that sounds like it
matters for chase-email tracking, but whatever was supposed to call this
during SMTP account setup doesn't. Worth checking whether SMTP-connected
businesses are actually missing outbox linkage today, or whether this was
superseded by something else and is just dead.
