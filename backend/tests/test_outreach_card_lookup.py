"""OUT-24 — lifting the pilot limit of 5 contacts per campaign (OUT-10
decision E; OUT-8 note 2; HK-1). Mike, 10 Nov 2026: research found only 1-4
contacts a day; with a 5-a-day inbox a campaign is full on day one.

Before the limit goes, two things: each email's card is found by its
enrolment (indexed, migration 040), never by loading every open card once per
enrolment; and a second card for the same email can never be created, by the
morning preparation, the owner's "prepare" or the autopilot, because the
check is made where the card is created, under the business lock."""
# ruff: noqa: F811 - pytest fixtures imported from test_outreach_setup are parameters by design
import json
import re
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlmodel import Session

from test_outreach_setup import A, _insert, db  # noqa: F401
from test_outreach_research import NOW, World, count, person, research, run, started

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def no_pilot_limit(monkeypatch):
    monkeypatch.setenv("OUTREACH_PILOT_ENROLMENTS", "0")


def _enrolment(db):
    with Session(db) as s:
        return s.execute(text("SELECT id, campaign_id, next_step, sequence_version FROM outreach_enrolments "
                              "WHERE business_id = :b ORDER BY id LIMIT 1"), {"b": A}).first()


def _open_cards(db, enrolment_id=None):
    with Session(db) as s:
        rows = s.execute(text("SELECT payload FROM aria_actions WHERE business_id = :b AND action_type = 'send_outreach' "
                              "AND status IN ('proposed', 'executing')"), {"b": A}).fetchall()
    ids = [json.loads(r[0]).get("enrolment_id") if isinstance(r[0], str) else r[0].get("enrolment_id") for r in rows]
    return ids if enrolment_id is None else [i for i in ids if i == str(enrolment_id)]


def _noise(db, n):
    """n open cards for other emails, as a busy business has."""
    with Session(db) as s:
        for _ in range(n):
            _insert(s, "aria_actions", id=str(uuid.uuid4()), business_id=A, action_type="send_outreach",
                    status="proposed", payload=json.dumps({"enrolment_id": str(uuid.uuid4())}),
                    created_at=NOW.isoformat(), updated_at=NOW.isoformat(),
                    expires_at=NOW.replace(year=NOW.year + 1).isoformat())
        s.commit()


def _step_args(db, e):
    with Session(db) as s:
        step = s.execute(text("SELECT id FROM outreach_sequence_steps WHERE business_id = :b AND campaign_id = :c "
                              "AND sequence_version = :v AND ordinal = :o"),
                         {"b": A, "c": str(e.campaign_id), "v": e.sequence_version, "o": e.next_step}).scalar()
    return {"campaign_id": str(e.campaign_id), "enrolment_id": str(e.id), "step_id": str(step)}


# ------------------------------------------------------------ the lookup ---

def test_the_card_for_one_email_is_found_among_many(db):
    from services import outreach_send
    biz, brand, lia, campaign = started(db)
    run(db, biz, lia, World([[person(1)]]))
    e = _enrolment(db)
    _noise(db, 500)
    with Session(db) as s:
        card = outreach_send.open_card(s, A, str(e.id))
        other = outreach_send.open_card(s, A, str(uuid.uuid4()))
    assert card is not None and json.loads(card["payload"])["enrolment_id"] == str(e.id) and other is None


def test_preparation_never_loads_every_open_card(db, monkeypatch):
    """The scan OUT-8 note 2 names: every open card read once per enrolment."""
    from services import outreach_send
    biz, brand, lia, campaign = started(db)
    run(db, biz, lia, World([[person(i) for i in range(5)]]))
    with db.begin() as c:
        c.execute(text("DELETE FROM aria_actions WHERE business_id = :b"), {"b": A})   # the real cards go
    _noise(db, 200)                                                                  # others' cards stay
    wide = []
    real = outreach_send.rows

    def spy(session, table, bid, where="", params=None, lock=False):
        if table == "aria_actions" and "enrolment_id" not in where:
            wide.append(where)
        return real(session, table, bid, where, params, lock)
    monkeypatch.setattr(outreach_send, "rows", spy)
    with Session(db) as s:
        made = research().prepare_due_cards(s, biz, NOW)
    assert len(made) == 5
    assert wide == [], "a preparation read every open card"


# ---------------------------------------------------- never a second card ---

def test_a_second_card_for_the_same_email_is_refused_where_cards_are_made(db):
    from services import aria_actions
    biz, brand, lia, campaign = started(db)
    run(db, biz, lia, World([[person(1)]]))
    e = _enrolment(db)
    assert len(_open_cards(db, e.id)) == 1
    with Session(db) as s:
        made = aria_actions.propose(s, biz, None, "send_outreach", _step_args(db, e))
    assert "already" in (made.get("error") or "").lower()
    assert len(_open_cards(db, e.id)) == 1
    assert count(db, "SELECT count(*) FROM outreach_unsubscribe_tokens WHERE business_id = :b") == 1, \
        "the refused card left an unsubscribe token behind"


def test_morning_preparation_twice_makes_one_card(db):
    biz, brand, lia, campaign = started(db)
    run(db, biz, lia, World([[person(1)]]))
    with db.begin() as c:
        c.execute(text("DELETE FROM aria_actions WHERE business_id = :b"), {"b": A})
    with Session(db) as s:
        first = research().prepare_due_cards(s, biz, NOW)
    with Session(db) as s:
        second = research().prepare_due_cards(s, biz, NOW)
    assert len(first) == 1 and second == [] and len(_open_cards(db)) == 1


def test_the_owner_s_prepare_still_reports_the_card_already_waiting(db):
    from services import outreach_manage
    import test_outreach_setup as setup_tests
    biz, brand, lia, campaign = started(db)
    run(db, biz, lia, World([[person(1)]]))
    e = _enrolment(db)
    with Session(db) as s:
        out = outreach_manage.prepare(s, biz, setup_tests.OWNER, str(campaign["id"]), {})
    assert [x["preview"]["enrolment_id"] for x in out["existing"]] == [str(e.id)] and out["raised"] == []


def test_a_closed_card_does_not_block_a_new_one(db):
    from services import aria_actions
    biz, brand, lia, campaign = started(db)
    run(db, biz, lia, World([[person(1)]]))
    e = _enrolment(db)
    with db.begin() as c:
        c.execute(text("UPDATE aria_actions SET status = 'dismissed' WHERE business_id = :b"), {"b": A})
    with Session(db) as s:
        made = aria_actions.propose(s, biz, None, "send_outreach", _step_args(db, e))
    assert "proposal" in made, made


# ------------------------------------------------------------ migration 040 ---

def test_migration_040_indexes_exactly_the_lookup_s_expression():
    from services import outreach_send
    sql = (BACKEND / "migrations" / "040_outreach_card_lookup.sql").read_text()
    assert "CREATE INDEX IF NOT EXISTS idx_aria_actions_outreach_enrolment" in sql
    assert "(business_id, ((payload->>'enrolment_id')))" in sql
    assert "WHERE action_type = 'send_outreach'" in sql
    assert "(payload->>'enrolment_id')" in outreach_send.OPEN_CARD_WHERE
    assert "action_type = 'send_outreach'" in outreach_send.OPEN_CARD_WHERE
    assert re.search(r"lock_timeout", sql), "the index waits a bounded time for its lock"
