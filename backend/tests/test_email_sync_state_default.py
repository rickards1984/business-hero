"""EM-1: a newly connected mailbox could never sync (Mike's logs, 8 Nov 17:08
and 17:13): "null value in column sync_status of relation email_sync_states
violates not-null constraint". Production has sync_status NOT NULL DEFAULT
'idle'; the model's field defaults to None and the ORM sent that None."""
import re
from pathlib import Path
from uuid import uuid4

from services import email_sync_state

BACKEND = Path(__file__).resolve().parents[1]


def test_a_new_sync_record_is_idle_not_null():
    state = email_sync_state.new(uuid4())
    assert state.sync_status == "idle" and state.cursor == {}


def test_idle_is_what_production_defaults_to():
    schema = (BACKEND.parent / "audits" / "live-schema-public.txt").read_text()
    line = next(l for l in schema.splitlines() if "email_sync_states.sync_status " in l)
    assert "null=NO" in line and f"'{email_sync_state.INITIAL_STATUS}'" in line


def test_no_code_creates_a_sync_record_any_other_way():
    """A direct EmailSyncState(...) leaves sync_status None: the bug again."""
    offenders = []
    for path in BACKEND.rglob("*.py"):
        rel = path.relative_to(BACKEND).as_posix()
        if rel.startswith(("tests/", ".venv/")) or rel in ("models.py", "services/email_sync_state.py"):
            continue
        if re.search(r"\bEmailSyncState\(", path.read_text(encoding="utf-8", errors="ignore")):
            offenders.append(rel)
    assert offenders == []
