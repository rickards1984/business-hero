"""BRIEF-1 on real PostgreSQL (Codex BRIEF-1 review 1): a week runs from local
midnight to local midnight in the business's zone, whatever the database
session's zone. In British Summer Time, Monday 00:30 local is Sunday 23:30 UTC."""
# ruff: noqa: F811 - the pg fixture is a parameter by design
import uuid
from datetime import date

import pytest
from sqlalchemy import text
from sqlmodel import Session

from test_outreach_send_rls import DATABASE_URL, pg  # noqa: F401
from test_outreach_send import A

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="RLS_LOCAL_DATABASE_URL is not set")


def test_the_week_follows_local_midnight_in_summer_time(pg):
    from services import whatsapp_briefings as wb
    with pg.engine.begin() as c:
        c.execute(text("SET TIME ZONE 'UTC'"))
        for when in ("2026-06-14 23:10+00", "2026-06-14 23:30+00", "2026-06-15 08:00+00", "2026-06-19 23:30+00"):
            # Mon 00:10 and 00:30 BST (in), Monday (in), Sat 00:30 BST (out). Bounds read
            # in UTC would give 2 (Monday, and Saturday's), so the two readings disagree.
            c.execute(text("INSERT INTO public.calls (id, business_id, source, outcome, started_at) "
                           "VALUES (:i, :b, 'receptionist', 'handled', CAST(:w AS timestamptz))"),
                      {"i": str(uuid.uuid4()), "b": A, "w": when})
    try:
        with Session(pg.engine) as s:
            s.execute(text("SET TIME ZONE 'UTC'"))
            assert wb._calls(s, A, date(2026, 6, 15), date(2026, 6, 19), "Europe/London").startswith("3 calls,")
    finally:
        with pg.engine.begin() as c:
            c.execute(text("DELETE FROM public.calls WHERE business_id = :b"), {"b": A})
