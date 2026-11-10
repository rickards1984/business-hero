# EM-1 — A newly connected mailbox can never sync

**Found:** Mike's Railway logs, 8 Nov 2026, 17:08 and 17:13. Mailbox 319e5a5f was connected for outreach at 17:07, and every background sync since has failed:

> null value in column "sync_status" of relation "email_sync_states" violates not-null constraint

**Cause:** production has `email_sync_states.sync_status NOT NULL DEFAULT 'idle'` (audits/live-schema-public.txt:380). `models.EmailSyncState.sync_status` defaulted to `None`, and the ORM sends that `None` explicitly in the INSERT, so the column default never applies. Mailboxes that already had a sync row were unaffected; only a mailbox's first row failed. That is why existing inboxes kept syncing.

**Fix:** the model defaults `sync_status` to `"idle"`, matching production. No migration. All four creators (`main.py`, `app/email/router.py` ×2, `services/background_sync.py`) rely on the default.

**Effect:** replies to outreach from that mailbox reach the app once this deploys. The next background sync creates its row.

**Tests:** `backend/tests/test_email_sync_state_default.py` (3). Two fail without the fix.
