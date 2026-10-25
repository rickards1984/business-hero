# Outreach scan lock fix — Codex review 2

- Commit reviewed: 7aeb6f4
- Model: gpt-6-astra · session 01a17377-ec12-7d12-8e7b-c5b7a95fed16 · tokens used: 28,670
- Verdict: REQUEST CHANGES

## Prompt

```
You are the independent reviewer for the outreach scan lock fix, cycle 2. Do not commit, push or modify files.
Review 1 and the builder's response are in audits/SCANFIX-CODEX-REVIEW-1.md. Review commit 7aeb6f4 (`git show 7aeb6f4`) with frontend/client/src/components/OutreachSetupWizard.tsx at HEAD.
Confirm: after Save the brands step stays open with its success message (nothing resets active to null on that path); only rows that saved are removed (failed, duplicate-name and half-filled rows kept); the strengthened test assertion. Check for any new problem (e.g. the selected brand after saving several, hooks usage).
Verdict APPROVE or REQUEST CHANGES with numbered P1/P2/P3 findings.
```

## Review (verbatim)

**REQUEST CHANGES**

1. **P2 — Status refresh can still close the brands step during a batch.** [Save handler:277](/Users/michaelrickards/dev/bh2-scanfix/frontend/client/src/components/OutreachSetupWizard.tsx:277) pins `active='brand'` only after all requests finish. On initial setup, `active` remains `null`; the first successful request invalidates status. If that refresh completes while the second save is pending, `current` advances to mailboxes. MUI unmounts the collapsed content, losing the success message and unsaved rows. Pin the brands step **before the first request**. Verify with two rows, a fast status refresh and a delayed second save.

2. **P2 — Saving an existing ready brand hides the success message.** [onSaved:161](/Users/michaelrickards/dev/bh2-scanfix/frontend/client/src/components/OutreachSetupWizard.tsx:161) sets `revisiting=false`. The backend upserts brands by name, so saving an existing ready brand selects it and activates `showReady`, replacing the entire stepper. Keep the brands editor visible after saving, including when the returned brand is already ready.

Otherwise confirmed by inspection:

- No save callback now calls `setActive(null)`.
- Position-based filtering preserves failed, unattempted and half-filled rows, including a failed row sharing a successful row’s name—provided the component stays mounted.
- Multiple successful saves select the **first successful brand**.
- `AND id=:id` fixes the assertion’s accidental match against `business_id=`.
- No new hooks-order violation found.

No files modified. Tests and `check.sh` were not run; this is a static review, without browser verification.
## Response

1. **Taken.** The Save handler calls `onStart()` before its first request. That pins `active='brand'` (and `revisiting`), so a status refresh between saves cannot move the step on or unmount the success message and unsaved rows.
2. **Taken.**
   - `onSaved` no longer clears `revisiting`, so saving a brand that is already ready keeps the brands editor open instead of showing its summary.
   - Only **Next: sending inbox** moves on; it clears `revisiting`.
