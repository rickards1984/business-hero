"""EM-1: the one way to create an email account's sync record.

Production has email_sync_states.sync_status NOT NULL DEFAULT 'idle'. The
model's field is Optional and defaults to None, which the ORM sends
explicitly, so the column default never applies and a newly connected
mailbox's first sync failed (Mike's logs, 8 Nov 17:08). Every creator comes
here so the status is always set.
"""
from models import EmailSyncState

INITIAL_STATUS = "idle"


def new(account_id) -> EmailSyncState:
    return EmailSyncState(email_account_id=account_id, cursor={}, sync_status=INITIAL_STATUS)
