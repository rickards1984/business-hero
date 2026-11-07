# BM-4 — Aria remembers what the owner explains

**Builds on:** BM-3 (#89), BM-3b (#90).

## Why (Mike, 7 Nov 2026)
In a meeting Mike told Aria that GoCardless is student course income and that
one-off payments with an initial and surname are full course payments. She used
it for that meeting only; the next meeting starts from scratch. Every kind of
business has the same need (a garage's parts supplier, a builder's merchants, an
estate agent's portals), so this is general, not New Body's.

## Behaviour
1. When the owner explains what a payer, reference, category or pattern means,
   Aria **proposes** a memory: `about` (what it is about), `meaning`, and an
   optional `group` (a label such as "Student courses" or "MOT work").
2. **Nothing is remembered without the owner's OK.** A proposal shows as a card
   in the meeting (typed or spoken): Remember / Not now. Only confirmed
   memories are used.
3. Confirmed memories go into every board meeting (typed and spoken) and into
   ordinary Aria chat and voice, as the owner's own notes about the business.
4. Where memories carry a `group`, the meeting ledger also shows income and
   spending **by group** (matching the `about` words in the payer, reference or
   description), with everything unmatched shown as "Not grouped". Totals are
   unchanged.
5. The owner sees, edits, adds and deletes memories on the board meeting
   settings page.
6. The "large one-off income" threshold (£500 by default) can be set per
   business on the same page; Aria can also look with a different threshold
   for one question (`ledger_summary` `one_off_from`).

## Storage
`business_settings.settings["aria_memory"]` = `{"entries": [...], "one_off_from": n|null}`,
read and written under the row lock (FOR UPDATE) like automations; protected
from the generic settings PUT (`preserve_automations`). **No migration.**
Limits: 100 confirmed + 20 proposed entries; `about` 80, `meaning` 300,
`group` 60 characters.

## API (board meetings feature)
`GET /v1/executive-meetings/memory`; `POST /memory` (owner adds, confirmed);
`PUT /memory/{id}`; `POST /memory/{id}/confirm`; `DELETE /memory/{id}`;
`PUT /memory/settings` (`one_off_from`).
