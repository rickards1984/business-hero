"""OUT-22 on real PostgreSQL (Codex OUT-22 review 1): first-time creators of a
business's settings row queue on one lock, so there is never a second row,
even WITHOUT a unique constraint (production's is unproven); and a creation
inside a refused request rolls back. SQLite's single writer cannot show this."""
# ruff: noqa: F811 - the pg fixture is a parameter by design
import threading

import pytest
from sqlalchemy import text
from sqlmodel import Session

from test_outreach_send_rls import DATABASE_URL, pg  # noqa: F401
from test_outreach_send import A

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="RLS_LOCAL_DATABASE_URL is not set")


def _rows(pg):
    with pg.engine.connect() as c:
        return c.execute(text("SELECT count(*) FROM public.business_settings WHERE business_id = :b"),
                         {"b": A}).scalar()


@pytest.fixture
def no_unique(pg):
    """As production may be: the UNIQUE on business_id removed for the test,
    restored after (the harness is local and disposable)."""
    with pg.engine.begin() as c:
        c.execute(text("DELETE FROM public.business_settings WHERE business_id = :b"), {"b": A})
        c.execute(text("ALTER TABLE public.business_settings DROP CONSTRAINT IF EXISTS business_settings_business_id_key"))
    try:
        yield pg
    finally:
        with pg.engine.begin() as c:
            c.execute(text("DELETE FROM public.business_settings WHERE business_id = :b"), {"b": A})
            c.execute(text("ALTER TABLE public.business_settings ADD CONSTRAINT business_settings_business_id_key "
                           "UNIQUE (business_id)"))


def test_six_first_time_creators_at_once_leave_exactly_one_row(no_unique):
    from services import settings_row
    jobs = 6
    gate, errors = threading.Barrier(jobs), []

    def run():
        try:
            with Session(no_unique.engine) as s:
                s.execute(text("SELECT 1"))
                gate.wait(10)
                settings_row.ensure(s, A)
                s.commit()
        except BaseException as exc:  # noqa: BLE001 - any failure fails the test
            errors.append(exc)
    threads = [threading.Thread(target=run) for _ in range(jobs)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert not errors, errors
    assert _rows(no_unique) == 1


def test_a_creation_in_a_refused_request_leaves_nothing(no_unique):
    from services import settings_row
    with Session(no_unique.engine) as s:
        settings_row.ensure(s, A)
        s.rollback()                      # what _authority does when the owner check fails
    assert _rows(no_unique) == 0


def test_a_writer_holding_the_row_never_waits_for_the_creation_lock(pg):
    """Codex OUT-22 review 2: a lock helper that already holds the row must not
    then queue on the creation lock (the reverse of a creator's order), or two
    writers could deadlock. With the row present, ensure takes no lock at all."""
    from services import settings_row
    with pg.engine.begin() as c:
        if not c.execute(text("SELECT 1 FROM public.business_settings WHERE business_id = :b"), {"b": A}).first():
            settings_row.ensure(c, A)
    other = pg.engine.connect()
    holder = other.begin()
    other.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": f"business_settings:{A}"})
    try:
        with Session(pg.engine) as s:
            s.execute(text("SET LOCAL lock_timeout = '2s'"))
            s.execute(text("SELECT 1 FROM public.business_settings WHERE business_id = :b FOR UPDATE"), {"b": A})
            settings_row.ensure(s, A)     # would time out if it queued behind `other`
            s.rollback()
    finally:
        holder.rollback()
        other.close()
