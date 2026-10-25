# OUT-20 — Codex review 3 (final repair cycle; escalated to Mike)

- Commit reviewed: 06e72e1
- Model: gpt-6-astra · session 01a17509-f846-7911-a68a-650d8043fdf5 · tokens used: 45,031
- Verdict: REQUEST CHANGES (two P2 edge cases); support-retry finding confirmed resolved

## Prompt

```
You are the independent reviewer for OUT-20, cycle 3 (the final repair cycle). Do not commit, push or modify files.
Review 2 and the response are in audits/OUT-20-CODEX-REVIEW-2.md. Review commit 06e72e1 (`git show 06e72e1`).
Confirm the three findings are resolved without new problems: _spf_with places the include first and removes other copies (any case where the result still fails SPF evaluation for the provider?); _dmarc_repaired keeps valid optional tags and drops invalid ones; the support retry escalates the same conversation.
If pytest cannot run in your sandbox, read the tests and say so.
Verdict APPROVE or REQUEST CHANGES with numbered P1/P2/P3 findings.
```

## Review (verbatim)

**REQUEST CHANGES** — reviewed `06e72e1` (HEAD).

1. **P2 — SPF replacement can still fail provider evaluation.** [_spf_with:566](/Users/michaelrickards/dev/bh2-OUT-19/backend/services/outreach_setup.py:566) correctly moves the include first and removes case-insensitive copies, but preserves malformed terms. Confirmed with the repository’s evaluator: `v=spf1 include:_spf.google.com ip4:garbage ~all` remains unchanged and returns `permerror`, even with a passing Google include. Validate the proposed replacement; if it cannot pass, explain that manual repair is required instead of presenting it as the fix. Add an evaluation-based regression test.

2. **P2 — DMARC repair still retains invalid optional settings.** [DMARC_TAGS:572](/Users/michaelrickards/dev/bh2-OUT-19/backend/services/outreach_setup.py:572) accepts any nonempty `fo`/`rf` and any `mailto:` prefix. Confirmed: repairing `V=DMARC1; p=none; fo=bogus; rf=???; rua=mailto:` preserves all three, including the unusable report destination, which prevents insertion of the fallback address. Validate optional values before retaining them and test invalid reporting options and destinations. `fo=bogus` and `rf=???` violate the [DMARC grammar](https://www.rfc-editor.org/rfc/rfc7489.html#section-6.4).

The original stranded-include example now passes SPF evaluation, and the original DMARC example preserves its valid policy and alignment settings. **The support retry finding is resolved by inspection:** the conversation ID survives escalation failure, and retry skips chat creation and escalates that same conversation.

**Verification:** targeted pytest produced **24 passed, 11 fixture errors** because the sandbox cannot create temporary database files. I read the blocked tests and ran read-only DNS probes. No files modified, commits made, or pushes performed.
## Response (built after the three cycles; re-review is Mike's call)

1. **Taken.**
   - Before an SPF edit is offered, the proposed record is run through the same RFC 7208 evaluator (pyspf) used for the mailbox check, against the provider's sending address.
   - If it would not pass (e.g. `ip4:garbage`), the guide gives action `manual`, with no value. It explains the record needs correcting by hand, and the helper email quotes the current record and the include required.
   - Tests:
     - `test_a_record_that_would_still_fail_is_never_offered_as_the_fix`;
     - `test_every_offered_spf_value_passes_the_evaluator`, run on three records.
2. **Taken.**
   - Optional DMARC tags follow the RFC 7489 §6.4 grammar: `rua`/`ruf` need a full `mailto:local@domain.tld` (optional size), `fo` uses only 0/1/d/s, and `rf` is a token list.
   - Test: `fo=bogus; rf=???; rua=mailto:` are dropped and the fallback report address is added.
