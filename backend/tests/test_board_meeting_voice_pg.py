"""BM-2 on real PostgreSQL (Codex BM-2 review 1, finding 4): a spoken turn is
saved only into this business's meeting while it is in progress, and a turn
arriving while /end is completing the meeting waits for it and is not saved
into the finished meeting. SQLite's single writer cannot show this."""
# ruff: noqa: F811 - the pg fixture is a parameter by design
import threading
import time
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlmodel import Session

from test_outreach_send_rls import DATABASE_URL, pg  # noqa: F401
from test_outreach_send import A, B

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="RLS_LOCAL_DATABASE_URL is not set")


@pytest.fixture
def meeting(pg):
    mid = str(uuid.uuid4())
    with pg.engine.begin() as c:
        c.execute(text("INSERT INTO public.executive_meetings (id, business_id, status, scheduled_for) "
                       "VALUES (:m, :b, 'in_progress', now())"), {"m": mid, "b": A})
    try:
        yield pg, mid
    finally:
        with pg.engine.begin() as c:
            c.execute(text("DELETE FROM public.executive_meeting_messages WHERE meeting_id = :m"), {"m": mid})
            c.execute(text("DELETE FROM public.executive_meetings WHERE id = :m"), {"m": mid})


def _saved(pg, mid):
    with pg.engine.connect() as c:
        return c.execute(text("SELECT role, content FROM public.executive_meeting_messages "
                              "WHERE meeting_id = :m ORDER BY created_at"), {"m": mid}).fetchall()


def _save(pg, mid, business_id, content):
    from services import executive_meeting_orchestrator as orch
    with Session(pg.engine) as s:
        return orch.save_spoken_turn(mid, business_id, "owner", content, datetime.now(timezone.utc), s)


def test_a_turn_is_saved_into_the_meeting_in_progress(meeting):
    pg, mid = meeting
    assert _save(pg, mid, A, "Let's raise prices.") is True
    assert [tuple(r) for r in _saved(pg, mid)] == [("owner", "Let's raise prices.")]


def test_never_into_another_business_meeting(meeting):
    pg, mid = meeting
    assert _save(pg, mid, B, "Injected.") is False
    assert _saved(pg, mid) == []


def test_never_into_a_finished_meeting(meeting):
    pg, mid = meeting
    with pg.engine.begin() as c:
        c.execute(text("UPDATE public.executive_meetings SET status = 'completed' WHERE id = :m"), {"m": mid})
    assert _save(pg, mid, A, "Too late.") is False
    assert _saved(pg, mid) == []


def test_a_turn_racing_the_end_of_the_meeting_waits_and_is_not_saved(meeting):
    """/end holds the meeting row (its status UPDATE, uncommitted) while the
    turn arrives: the turn waits, sees 'completed', and saves nothing."""
    pg, mid = meeting
    ender = pg.engine.connect()
    tx = ender.begin()
    ender.execute(text("UPDATE public.executive_meetings SET status = 'completed' WHERE id = :m"), {"m": mid})
    result = {}

    def turn():
        result["saved"] = _save(pg, mid, A, "Said as it ended.")
    t = threading.Thread(target=turn, daemon=True)
    t.start()
    try:
        time.sleep(0.5)
        waited = t.is_alive()
        tx.commit()
    finally:
        if tx.is_active:
            tx.rollback()
        ender.close()
    t.join(10)
    assert waited, "the turn must wait for the end of the meeting, not slip in"
    assert result == {"saved": False} and _saved(pg, mid) == []
