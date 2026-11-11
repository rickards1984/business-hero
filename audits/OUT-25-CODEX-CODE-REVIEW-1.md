# OUT-25 — Codex code review 1 (verbatim)

Commit reviewed: e79e794.

---

1. **P1 — Cleanup silently deletes real content.** [outreach_setup.py:957](/Users/michaelrickards/dev/bh2-PH/backend/services/outreach_setup.py:957): reproduced `Our monthly fee is £20.\n[Prices exclude VAT]` becoming `Our monthly fee is £20.` It also deletes a standalone bracketed booking URL. No valediction is required, and `_insert_steps` applies this to submitted emails. **Fix:** restrict removal to recognised sender-signature placeholders in a clearly identified signature block; preserve other content.

2. **P2 — Legitimate prose and URLs are refused.** [outreach_send.py:53](/Users/michaelrickards/dev/bh2-PH/backend/services/outreach_send.py:53): `[ex VAT]` and `https://example.com/?filter[sector]=gyms` both match. Consequently, valid emails cannot be saved, approved or sent. **Fix:** detect placeholder-shaped names rather than every bracketed expression, with regression cases for prices, editorial brackets and URL parameters.

3. **P2 — Common placeholders bypass every guard.** [outreach_send.py:53](/Users/michaelrickards/dev/bh2-PH/backend/services/outreach_send.py:53): `Hi <NAME>,` returns `None`, as does `[Insert the first name of the recipient here]` because of the 40-character cap. These can reach transport unchanged. `[First Name]`, `{{name}}` and `{first_name}` are detected. **Fix:** support recognised angle-bracket placeholders without rejecting ordinary markup/addresses, and remove the arbitrary length escape for recognised placeholder phrases.

4. **P3 — Draft-output test can pass vacuously.** [test_outreach_placeholders.py:65](/Users/michaelrickards/dev/bh2-PH/backend/tests/test_outreach_placeholders.py:65): `all(...)` passes if drafting returns `[]`; the prompt assertion still passes. **Fix:** assert three returned emails and their expected contents; cover redrafting too.

The exception handling, pre-reservation claim check and dispatch blocked-path placement are correct on inspection. Findings above were reproduced in memory using the actual detector/cleanup definitions. Full tests were not run because their fixtures write temporary databases; `check.sh` also writes compiled files. Nothing was modified, committed or pushed.

VERDICT: CHANGES REQUESTED