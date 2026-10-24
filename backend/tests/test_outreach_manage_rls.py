"""OUT-8 real Postgres serialization contracts; synthetic loopback data only.

Opt-in execution requires 035–038 in RLS_LOCAL_DATABASE_URL. A missing URL
skips; a configured database missing the required schema FAILS. No provider,
approval executor, model or transport is invoked by these tests.
"""
import hashlib
import json
import threading
import time
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlmodel import Session

from services import outreach_manage as manage
from test_outreach_send_rls import (
    A, CAMPAIGN, DATABASE_URL, ENROLMENT, NOW, OWNER, STAMP,
    _count, _propose, _second_prospect, base, pg,  # noqa: F401 fixture registration
)

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="RLS_LOCAL_DATABASE_URL absent; Postgres contention NOT verified")


@pytest.fixture
def management_pg(request):
    engine = create_engine(DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1))
    try:
        with engine.connect() as c:
            for table in ("outreach_messages", "outreach_reply_slots", "outreach_knowledge"):
                assert c.execute(text("SELECT to_regclass(:t)"), {"t": "public." + table}).scalar(), f"Required 035–038 schema missing: {table}"
    finally:
        engine.dispose()
    harness = request.getfixturevalue("pg")
    # prepare requires a complete approved sequence, unlike the sender fixture.
    with Session(harness.engine) as s:
        for ordinal, delay in ((1, 5), (2, 7)):
            envelope = json.dumps(dict(schema_version=1, subject="Synthetic follow-up", body="Synthetic only."))
            base.add(s, "sequence_steps", id=str(uuid.uuid4()), campaign_id=CAMPAIGN,
                     sequence_version=1, ordinal=ordinal, delay_business_days=delay,
                     template_text=envelope, template_hash=hashlib.sha256(envelope.encode()).hexdigest(),
                     allowed_variables="[]", approved_by=OWNER, approved_at=STAMP)
        s.commit()
    yield harness
    assert not harness.p.sends and not harness.p.searches


def _race(h, monkeypatch, first, second):
    """Hold the first management transaction until PG proves the other waits."""
    locked, release, second_started = threading.Event(), threading.Event(), threading.Event()
    original = manage.start
    pids, outcomes = {}, {}

    def held(session, business, user):
        result = original(session, business, user)
        if threading.current_thread().name == "out8-first" and not locked.is_set():
            pids["holder"] = session.execute(text("SELECT pg_backend_pid()")).scalar()
            locked.set()
            assert release.wait(15), "observer did not release the transaction"
        return result

    monkeypatch.setattr(manage, "start", held)

    def run(label, work):
        try:
            with Session(h.engine) as s:
                pids[label] = s.execute(text("SELECT pg_backend_pid()")).scalar()
                if label == "second":
                    second_started.set()
                try:
                    outcomes[label] = work(s)
                finally:
                    s.rollback()
        except BaseException as exc:  # surfaced to the parent thread, never swallowed
            outcomes[label] = exc

    one = threading.Thread(target=run, args=("first", first), name="out8-first")
    two = threading.Thread(target=run, args=("second", second), name="out8-second")
    one.start()
    try:
        assert locked.wait(10), "first management call never acquired locks"
        two.start()
        assert second_started.wait(10)
        deadline = time.monotonic() + 10
        blocked = False
        while time.monotonic() < deadline:
            with h.engine.connect() as c:
                blocked = c.execute(text("SELECT :holder = ANY(pg_blocking_pids(:waiter))"),
                                    {"holder": pids["holder"], "waiter": pids["second"]}).scalar()
            if blocked:
                break
        assert blocked, "Postgres never observed the competing transaction blocked on the first"
        assert "second" not in outcomes
    finally:
        release.set()
        one.join(20)
        if two.ident is not None:
            two.join(20)
    assert not one.is_alive() and not two.is_alive(), "transaction did not finish"
    return outcomes


def _unenrolled(h):
    eid = _second_prospect(h)
    with h.engine.begin() as c:
        pid = c.execute(text("DELETE FROM outreach_enrolments WHERE id=:id RETURNING prospect_id"), {"id": eid}).scalar_one()
    return str(pid)


def test_enrolment_cap_serializes_and_loser_rolls_back(management_pg, monkeypatch):
    h = management_pg
    for _ in range(3):
        _second_prospect(h)
    left, right = _unenrolled(h), _unenrolled(h)
    result = _race(h, monkeypatch,
                   lambda s: manage.enrol(s, h.b, OWNER, CAMPAIGN, {"prospect_ids": [left]}),
                   lambda s: manage.enrol(s, h.b, OWNER, CAMPAIGN, {"prospect_ids": [right]}))
    assert isinstance(result["first"], dict), result
    assert isinstance(result["second"], h.a.ActionRefused), result
    assert "five" in result["second"].detail.lower()
    assert _count(h, "SELECT count(*) FROM outreach_enrolments WHERE campaign_id=:c AND state='active'", c=CAMPAIGN) == 5
    assert _count(h, "SELECT count(*) FROM outreach_enrolments WHERE prospect_id=:p", p=right) == 0


def test_two_prepares_have_one_card_and_return_existing(management_pg, monkeypatch):
    h = management_pg
    result = _race(h, monkeypatch,
                   lambda s: manage.prepare(s, h.b, OWNER, CAMPAIGN, {}),
                   lambda s: manage.prepare(s, h.b, OWNER, CAMPAIGN, {}))
    assert all(isinstance(value, dict) for value in result.values()), result
    raised = [card for value in result.values() for card in value["raised"]]
    existing = [card for value in result.values() for card in value["existing"]]
    assert len(raised) == len(existing) == 1, result
    assert raised[0]["id"] == existing[0]["id"]
    assert _count(h, "SELECT count(*) FROM aria_actions WHERE business_id=:b", b=A) == 1
    assert "automation" not in raised[0]["preview"]
    assert _count(h, "SELECT count(*) FROM outreach_dispatch_jobs WHERE business_id=:b", b=A) == 0


@pytest.mark.parametrize("control", ["pause", "suppress"])
@pytest.mark.parametrize("competitor", ["prepare", "claim"])
def test_safety_write_blocks_then_denies_prepare_or_claim(management_pg, monkeypatch, control, competitor):
    h = management_pg
    card = _propose(h) if competitor == "claim" else None

    def safety(s):
        if control == "pause":
            return manage.settings(s, h.b, OWNER, {"pause_all": True})
        return manage.suppress(s, h.b, OWNER, {"email": base.EMAIL, "reason": "manual_opt_out"})

    def compete(s):
        if competitor == "prepare":
            return manage.prepare(s, h.b, OWNER, CAMPAIGN, {})
        # A synthetic search receipt exercises only the transactional claim;
        # deliberately never call the executor or even the fake provider.
        s.info["outreach_search"] = {card["id"]: (card["version"], NOW)}
        return h.m.prepare_claim(s, h.b, action_id=card["id"], payload=card["preview"],
                                 user_id=OWNER, version=card["version"], moment=NOW)

    result = _race(h, monkeypatch, safety, compete)
    assert isinstance(result["first"], dict), result
    if competitor == "claim":
        assert isinstance(result["second"], h.a.ActionRefused), result
    else:
        assert isinstance(result["second"], dict), result
        assert not result["second"]["raised"] and result["second"]["skipped"], result
    for table in ("outreach_dispatch_jobs", "outreach_usage_events", "outreach_messages"):
        assert _count(h, f"SELECT count(*) FROM {table} WHERE business_id=:b", b=A) == 0
    if control == "suppress":
        assert _count(h, "SELECT state FROM outreach_enrolments WHERE id=:id", id=ENROLMENT) == "suppressed"
