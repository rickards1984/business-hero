# OUT-22 — Codex review 2, targeted (preserved verbatim)

**Findings — do not approve yet.**

1. **P1: New lock-order inversion can deadlock existing writers.** [_save_settings_doc:166](/Users/michaelrickards/dev/bh2-OUT-22/backend/services/outreach_setup.py:166) now acquires the advisory lock after callers such as [mark_outcome:392](/Users/michaelrickards/dev/bh2-OUT-22/backend/services/outreach_dashboard.py:392) have locked `business_settings`. Billing `_update` and autopilot `_reserve_pace` also use this reverse order. Meanwhile, Xero, automations, main PUT and `_authority` acquire advisory → row. Two concurrent transactions can therefore hold one lock each and wait for the other, causing PostgreSQL to abort one. All affected writers must acquire the advisory lock **before their first row lock**.

2. **P2: Missing-row outcome writes can still overwrite concurrent changes.** [mark_outcome:392–394](/Users/michaelrickards/dev/bh2-OUT-22/backend/services/outreach_dashboard.py:392) locks no row when settings are absent, then reads an empty document. Another transaction can create and populate settings before `mark_outcome` reaches `ensure`. Its subsequent whole-document update overwrites that committed content. Two outcome updates for different prospects can likewise lose one event history. Ensure and lock the row **before reading the document**, not only when saving.

Original findings:
- **P1 duplicate creation:** resolved for the traced creator paths.
- **P2 premature commit:** resolved; `ensure` never commits and the authoritative owner refusal rolls back.
- **P3 silent zero-row update:** resolved in isolation, but concurrent preservation remains defective as above.

No additional blocker found in main’s ORM path. The GET sessions are not configured as PostgreSQL read-only transactions: automations’ provisional insertion rolls back on session close; checklist explicitly rolls back.

Static, read-only review only. I did not rerun `check.sh` or the PostgreSQL tests; no files modified, committed or pushed.