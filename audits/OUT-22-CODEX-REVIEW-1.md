# OUT-22 — Codex review 1 (preserved verbatim)

**Changes requested.**

1. **P1 — Concurrent initialization can recreate the 404 permanently.** [outreach_setup.py:154](/Users/michaelrickards/dev/bh2-OUT-22/backend/services/outreach_setup.py:154)  
   Without a unique constraint on `business_id`, two PostgreSQL transactions can both satisfy `NOT EXISTS` and insert different UUIDs. Neither raises `IntegrityError`. Subsequent `send.one()` requires exactly one row, so setup and sending fail with “Outreach record unavailable”. Serialize initialization using a shared protocol across writers, or establish verified uniqueness. The fixture’s `business_id PRIMARY KEY` masks this case; the sequential test does not demonstrate concurrency safety.

2. **P2 — Row creation commits before authoritative owner revalidation.** [outreach_setup.py:159](/Users/michaelrickards/dev/bh2-OUT-22/backend/services/outreach_setup.py:159)  
   An ordinary non-owner is rejected before insertion. However, an owner revoked after the first, unlocked check can still create a committed settings row; the later locked check rejects the request but cannot undo that insertion. This fails the strict “non-owner can never create a row” requirement. Creation needs to remain rollbackable through authoritative authorization.

3. **P2 — Missing-row data loss remains in a bypass path (existing issue).** [outreach_dashboard.py:415](/Users/michaelrickards/dev/bh2-OUT-22/backend/services/outreach_dashboard.py:415)  
   `mark_outcome()` bypasses `_authority()`. With an existing prospect but no settings row, its lock matches nothing, the prospect stage changes, and `_save_settings_doc()` silently updates zero rows. The request succeeds while losing the outcome history. This fix repairs owner setup paths, not the general missing-settings invariant.

Other checks:

- **Transactions and lock order:** `_authority()` already rolled back caller work on entry. I found no additional caller-work loss from this helper; subsequent locks remain `business_settings → outreach_settings`. The independently committed initialization is the authorization issue above.
- **PostgreSQL syntax:** Explicit UUID, naive UTC timestamps and JSONB cast match the recorded column shape. Concurrency is the defect.
- **Research/billing:** Owner configuration paths use `_authority()`. Research’s shared lock fails closed when settings are absent; billing reconciliation/webhooks generally skip absent billing state. Neither provides general initialization.
- **AI cost:** Profile capacity rises from 6,000 to 21,000 total characters, including website. Full profiles enter draft/redraft prompts. Existing `_draft_hold()` sizes its reservation from serialized context, with actual usage recorded afterward; output remains capped at 4,000 tokens. Larger inputs increase spend and allowance reservations, but I found no newly bypassed cost control.

Read-only review completed; nothing modified, committed or pushed. Tests and `check.sh` were not run because they write artifacts; PostgreSQL concurrency was assessed statically.