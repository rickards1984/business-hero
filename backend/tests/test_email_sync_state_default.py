"""EM-1: a newly connected mailbox could never sync (Mike's logs, 8 Nov 17:08
and 17:13): "null value in column sync_status of relation email_sync_states
violates not-null constraint". Production has sync_status NOT NULL DEFAULT
'idle'; the model defaulted it to None and the ORM sent that None."""
import re
from pathlib import Path
from uuid import uuid4

from models import EmailSyncState


def test_a_new_sync_state_is_idle_not_null():
    state = EmailSyncState(email_account_id=uuid4(), cursor={})
    assert state.sync_status == "idle"


def test_the_model_matches_the_live_schema():
    schema = (Path(__file__).resolve().parents[2] / "audits" / "live-schema-public.txt").read_text()
    line = next(l for l in schema.splitlines() if "email_sync_states.sync_status " in l)
    assert "null=NO" in line and "'idle'" in line
    column = EmailSyncState.__table__.c.sync_status
    assert column.nullable is False


def test_every_place_that_creates_one_relies_on_the_default():
    """None of the four creators passes sync_status=None explicitly."""
    root = Path(__file__).resolve().parents[1]
    for path in ("main.py", "app/email/router.py", "services/background_sync.py"):
        text = (root / path).read_text()
        for call in re.findall(r"EmailSyncState\([^)]*\)", text):
            assert "sync_status=None" not in call, (path, call)
