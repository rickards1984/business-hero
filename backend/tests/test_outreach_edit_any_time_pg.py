"""OUT-28a on real PostgreSQL: saving new wording, and a save racing an
approval. Loopback harness only (scripts/rls-local.sh); synthetic rows, torn
down; the provider is a fake, so nothing is ever sent."""
# ruff: noqa: F811 - the pg fixture is imported from the harness
import hashlib
import json
import threading
import uuid

import pytest
from sqlalchemy import text
from sqlmodel import Session

import test_outreach_send as base
from test_outreach_send_rls import DATABASE_URL, _approve, _propose, pg  # noqa: F401
from test_outreach_send import A, CAMPAIGN, ENROLMENT, OWNER, STAMP

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="RLS_LOCAL_DATABASE_URL is not set. A skip is not a pass.")

NEW = [("A better offer", "A clearer, better offer."), ("Quick follow-up", "A clearer follow-up."),
       ("One last note", "A clearer last note.")]


def _three(pg):
    with Session(pg.engine) as s:
        for ordinal, delay in ((1, 5), (2, 7)):
            env = json.dumps({"schema_version": 1, "subject": f"Old {ordinal}", "body": f"Old body {ordinal}."})
            base.add(s, "sequence_steps", id=str(uuid.uuid4()), campaign_id=CAMPAIGN, sequence_version=1,
                     ordinal=ordinal, delay_business_days=delay, template_text=env,
                     template_hash=hashlib.sha256(env.encode()).hexdigest(), allowed_variables="[]",
                     approved_by=OWNER, approved_at=STAMP)
        s.commit()


def _save(pg):
    from services import outreach_manage
    with Session(pg.engine) as s:
        version = s.execute(text("SELECT version FROM outreach_campaigns WHERE id = :c"), {"c": CAMPAIGN}).scalar()
        s.rollback()
        return outreach_manage.save_emails(s, pg.b, OWNER, CAMPAIGN, {
            "version": int(version), "emails": [{"ordinal": i, "subject": a, "body": b} for i, (a, b) in enumerate(NEW)]})


def _one(pg, sql):
    with pg.engine.connect() as c:
        return c.execute(text(sql), {"b": A, "c": CAMPAIGN, "e": ENROLMENT}).one()


def test_a_save_on_postgres_moves_people_and_the_next_email_uses_it(pg):
    _three(pg)
    old = _propose(pg)
    out = _save(pg)
    assert out["moved"] == 1 and out["withdrawn"] == 1 and out["sequence_version"] == 2
    assert _one(pg, "SELECT sequence_version FROM outreach_enrolments WHERE id = :e")[0] == 2
    assert _one(pg, "SELECT status FROM aria_actions WHERE business_id = :b AND id = '%s'" % old["id"])[0] == "dismissed"
    kind, value = _one(pg, "SELECT pg_typeof(allowed_variables)::text, allowed_variables FROM outreach_sequence_steps "
                           "WHERE campaign_id = :c AND sequence_version = 2 AND ordinal = 0")
    assert kind == "jsonb" and value == []          # 037's CHECK: a JSON array; emails take no variables
    step = _one(pg, "SELECT id FROM outreach_sequence_steps WHERE campaign_id = :c AND sequence_version = 2 "
                    "AND ordinal = 0")[0]
    with Session(pg.engine) as s:
        made = pg.a.propose(s, pg.b, OWNER, "send_outreach",
                            dict(campaign_id=CAMPAIGN, enrolment_id=ENROLMENT, step_id=str(step)), owner_name="Owner")
    assert "proposal" in made, made
    done = _approve(pg, made["proposal"])
    assert done["status"] == "done" and pg.p.sends[-1][1]["subject"] == "A better offer"


def test_a_save_racing_an_approval_never_deadlocks_or_sends_stale_wording(pg):
    """Both arrive at the shared business lock together. Either the approval
    wins (the old email goes, then the save moves everyone on) or the save
    wins (the card is withdrawn and nothing is sent). Never both, never stuck."""
    _three(pg)
    card = _propose(pg)
    gate = threading.Barrier(2)
    original, calls = pg.m.lock_business, []

    def gated(session, bid):
        calls.append(1)
        if len(calls) <= 2:
            gate.wait(10)
        return original(session, bid)
    pg.m.lock_business = gated
    results, refused, crashed = {}, {}, []

    def run(name, job):
        try:
            results[name] = job()
        except pg.a.ActionRefused as exc:
            refused[name] = exc
        except BaseException as exc:  # noqa: BLE001 - anything else fails the test
            crashed.append((name, exc))
    threads = [threading.Thread(target=run, args=("approve", lambda: _approve(pg, card))),
               threading.Thread(target=run, args=("save", lambda: _save(pg)))]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
    finally:
        pg.m.lock_business = original
    assert not any(t.is_alive() for t in threads), "stuck: a save and an approval deadlocked"
    assert not crashed, crashed
    assert len(calls) >= 2, "they never met at the lock"
    assert len(pg.p.sends) <= 1
    if pg.p.sends:                                  # the approval won: the email it showed was sent
        assert pg.p.sends[0][1]["subject"] == "Synthetic offer"
        assert _one(pg, "SELECT sequence_version FROM outreach_messages WHERE business_id = :b")[0] == 1
        if "save" in refused:                       # mid-send: the save waits its turn, nothing half-done
            assert "sending right now" in refused["save"].detail
    else:                                           # the save won: nothing was sent from the old wording
        assert "save" in results and "approve" in refused
    if "save" in results:
        assert _one(pg, "SELECT sequence_version FROM outreach_enrolments WHERE id = :e")[0] == 2


def _history(pg, outcome):
    """A real email record for the harness contact on wording v1, made by the
    real send path: accepted (as MSC's), or refused by the provider (as New
    Body's two failed cards of 11 Nov)."""
    pg.p.outcome = outcome
    _approve(pg, _propose(pg))
    pg.p.outcome = "accepted"
    with pg.engine.connect() as c:
        return c.execute(text("SELECT state FROM outreach_messages WHERE business_id = :b"), {"b": A}).scalar()


@pytest.mark.parametrize("outcome", ["definitely_not_accepted", "accepted"])
def test_a_contact_with_email_history_moves_to_the_new_wording(pg, outcome):
    """OUT-28a fix (production, 19 Nov 2026): New Body's save failed with
    ForeignKeyViolation outreach_messages_business_id_campaign_id_sequence_version_fkey,
    because a contact with any email record could not change wording version.
    Migration 044 drops that constraint; each email keeps its own wording."""
    _three(pg)
    recorded = _history(pg, outcome)
    assert recorded in ("accepted", "failed"), recorded
    before = _one(pg, "SELECT next_step FROM outreach_enrolments WHERE id = :e")[0]
    out = _save(pg)
    assert out["moved"] == 1
    assert _one(pg, "SELECT sequence_version, next_step FROM outreach_enrolments WHERE id = :e") == (2, before)
    # the email already recorded keeps the wording it had
    assert _one(pg, "SELECT sequence_version, subject FROM outreach_messages WHERE business_id = :b") == (1, "Synthetic offer")


def test_an_email_record_still_cannot_change_the_wording_it_was_sent_with(pg):
    """The constraint that stays (…_fkey1): an email record's wording version
    must be its step's version."""
    from sqlalchemy.exc import IntegrityError
    _three(pg)
    _history(pg, "accepted")
    _save(pg)                                   # version 2 exists now, but not for this email's step
    with pytest.raises(IntegrityError):
        with pg.engine.begin() as c:
            c.execute(text("UPDATE outreach_messages SET sequence_version = 2 WHERE business_id = :b"), {"b": A})
