# OUT-25 — Codex code review 2 (targeted, verbatim)

Commit reviewed: cdeb377.

---

1. **P1 — Cleanup still deletes real content.** [outreach_setup.py:955](/Users/michaelrickards/dev/bh2-PH/backend/services/outreach_setup.py:955): `Our pricing is fixed.\n[My prices include VAT]` becomes `Our pricing is fixed.` `_SENDER` accepts any sentence beginning “your”, “my” or “sender”, without requiring a signature block. **Fix:** match complete sender-field labels rather than arbitrary trailing prose; add preservation regressions.

2. **P2 — Ordinary B2B prose is still refused.** [outreach_send.py:75](/Users/michaelrickards/dev/bh2-PH/backend/services/outreach_send.py:75): `Please reply [by email only].` is detected as a placeholder because `_FIELD.search()` matches “email” anywhere. This blocks saving, approval and sending. **Fix:** recognise complete field labels or explicit insertion instructions, with regression coverage for editorial sentences containing field vocabulary.

3. **P2 — Common placeholders now bypass the guards.** [outreach_send.py:67](/Users/michaelrickards/dev/bh2-PH/backend/services/outreach_send.py:67): `Dear {{firstName}},`, `Hi [firstname],` and `Reply to [emailAddress].` all return `None`; the previous detector caught them. **Fix:** recognise common concatenated and camelCase field names and add regression cases.

The original review’s concrete examples pass. Finding 4 is fixed: draft and redraft tests assert exactly three expected subjects and bodies. Findings 1–3 remain incompletely resolved.

Verified 29 existing pure test cases and both drafting outputs in memory using the actual definitions. Full pytest and `check.sh` were not run because they write files. Nothing was modified, committed or pushed.

VERDICT: CHANGES REQUESTED