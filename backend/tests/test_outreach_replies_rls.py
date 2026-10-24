"""OUT-7 — outreach replies on real PostgreSQL, through the real service path.

The SQLite suite (test_outreach_replies.py) proves the rules; these prove
them under two sessions at once, on 035–038's real types, keys and RLS-era
schema, through services.outreach_replies and the real aria_actions hook.
Local harness only (`scripts/rls-local.sh up`, 038 replayed); synthetic rows,
torn down. The provider is a fake: nothing is ever sent.
"""
# ruff: noqa: F811 - pytest fixtures imported from test_outreach_send_rls are parameters by design

import hashlib
import threading
import uuid

import pytest
from sqlalchemy import text
from sqlmodel import Session

import test_outreach_send as base
from test_outreach_send_rls import DATABASE_URL, pg  # noqa: F401 - the fixture is used by name
from test_outreach_send import A, BOX, DEFAULT, EMAIL, ENROLMENT, OWNER, PROSPECT, CAMPAIGN, BRAND, NOW, STAMP, LAST

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="RLS_LOCAL_DATABASE_URL is not set")


@pytest.fixture
def pr(pg, monkeypatch):
    with pg.engine.connect() as c:
        # A supplied harness without 038 is a failure, not a skip (review).
        assert c.execute(text("SELECT to_regclass('public.outreach_reply_slots')")).scalar(), \
            "038 is not replayed in the local harness: rebuild with scripts/rls-local.sh up"
    with Session(pg.engine) as s:
        # The accepted initial email the prospect is replying to, and the owner's
        # approved card that sent it (037: a live acceptance names its action).
        previous_action = str(uuid.uuid4())
        s.execute(text(
            "INSERT INTO aria_actions (id, business_id, proposed_by, action_type, payload, status, "
            "approved_by, approved_at, executed_at, expires_at, created_at, updated_at) VALUES "
            "(:id, :b, :u, 'send_outreach', '{}'::jsonb, 'done', :u, :at, :at, :at, :at, :at)"),
            {"id": previous_action, "b": A, "u": OWNER, "at": LAST})
        base.add(s, "messages", action_id=previous_action, prospect_id=PROSPECT, campaign_id=CAMPAIGN, mailbox_id=BOX,
                 kind="initial", origin="live", direction="outbound", to_emails=[EMAIL], cc_emails=[],
                 subject="Previous", body="Previous", payload_hash=hashlib.sha256(b"previous").hexdigest(),
                 payload_version=1, state="accepted", provider="google", provider_message_id="previous-id",
                 provider_thread_id="previous-thread", rfc_message_id="<previous@example.invalid>",
                 accepted_at=LAST.isoformat(), idempotency_key="previous-operation", authority_snapshot="{}")
        h = type("H", (), {"s": s})()
        base.change(h, "outreach_prospects", last_contact_at=LAST.isoformat(),
                    first_contact_at=LAST.isoformat(), notice_provided_at=LAST.isoformat())
        base.add(s, "knowledge", brand_id=BRAND, topic="availability", answer="Weekday appointments",
                 source_reference="https://example.invalid/facts", version=1, status="approved",
                 approved_by=OWNER, approved_at=STAMP, review_due_at="2026-12-01T00:00:00+00:00")
        s.commit()
    import importlib
    replies = importlib.import_module("services.outreach_replies")
    monkeypatch.setattr(replies, "now", lambda: NOW)
    pg.replies = replies
    return pg


def _incoming(pr, ident="incoming", mailbox=BOX, thread="previous-thread"):
    ident = str(uuid.uuid5(uuid.NAMESPACE_URL, "out7-pg:" + ident))
    with pr.engine.begin() as c:
        c.execute(text(
            "INSERT INTO email_messages (id, business_id, email_account_id, provider_message_id, "
            "provider_thread_id, folder, from_email, subject, body_text, received_at, created_at, updated_at) "
            "VALUES (:id, :b, :a, :id, :t, 'INBOX', :f, 'Re: Previous', 'When are appointments available?', "
            ":at, :at, :at)"), {"id": ident, "b": A, "a": mailbox, "t": thread, "f": EMAIL, "at": STAMP})
    return ident


def _scan(pr):
    with Session(pr.engine) as s:
        return pr.replies.scan(s, pr.b, moment=NOW, classify=lambda _: {
            "category": "question", "confidence": 100, "classification_version": 1})


def _reply_ids(pr):
    with pr.engine.connect() as c:
        return [str(r[0]) for r in c.execute(text(
            "SELECT id FROM outreach_replies WHERE business_id = :b ORDER BY created_at, id"), {"b": A})]


def _propose(pr, rid):
    with Session(pr.engine) as s:
        return pr.replies.propose_answer(s, pr.b, reply_id=rid, moment=NOW, draft=lambda ctx: {
            "body": "Weekday appointments",
            "knowledge_refs": [{"id": k["id"], "version": k["version"]} for k in ctx["knowledge"]]})


def _approve(pr, card, user=OWNER):
    with Session(pr.engine) as s:
        return pr.a.approve(s, pr.b, card["id"], user, version=card["version"])


def _count(pr, sql, **params):
    with pr.engine.connect() as c:
        return c.execute(text(sql), dict(params, b=A)).scalar()


def _together(*jobs):
    gate = threading.Barrier(len(jobs))
    results, errors, crashed = [], [], []

    def run(job):
        try:
            gate.wait(10)
            results.append(job())
        except Exception as exc:  # noqa: BLE001 - classified below
            (errors if type(exc).__name__ == "ActionRefused" else crashed).append(exc)
    threads = [threading.Thread(target=run, args=(j,)) for j in jobs]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert not any(t.is_alive() for t in threads), "a job never finished"
    assert not crashed, crashed
    return results, errors


# ------------------------------------------------------------------ tests ---

def test_one_reply_one_answer_card_on_postgres(pr):
    _incoming(pr)
    _scan(pr)
    assert _count(pr, "SELECT state FROM outreach_enrolments WHERE business_id = :b AND id = :e",
                  e=ENROLMENT) == "replied"
    (rid,) = _reply_ids(pr)
    card = _propose(pr, rid)
    assert card["status"] == "proposed"
    done = _approve(pr, card)
    assert done["status"] == "done" and len(pr.p.sends) == 1
    assert _count(pr, "SELECT state FROM outreach_reply_slots WHERE business_id = :b") == "accepted"


def test_two_syncs_drafting_the_same_reply_at_once_make_one_card(pr):
    _incoming(pr)
    _scan(pr)
    (rid,) = _reply_ids(pr)
    results, errors = _together(lambda: _propose(pr, rid), lambda: _propose(pr, rid))
    assert _count(pr, "SELECT count(*) FROM aria_actions WHERE business_id = :b "
                      "AND action_type = 'reply_outreach'") == 1
    assert _count(pr, "SELECT count(*) FROM outreach_reply_slots WHERE business_id = :b") == 1
    ids = {r["id"] for r in results if r.get("status") == "proposed"}
    assert len(ids) == 1, (results, errors)


def test_two_replies_from_one_prospect_in_two_mailboxes_at_once_one_answer(pr):
    _incoming(pr, "first", mailbox=BOX)
    _incoming(pr, "second", mailbox=DEFAULT, thread="other-thread")
    _scan(pr)
    rids = _reply_ids(pr)
    assert len(rids) == 2, "both inbound messages must be recorded as outreach replies"
    results, errors = _together(lambda: _propose(pr, rids[0]), lambda: _propose(pr, rids[1]))
    # Never two answers. Two replies on different threads are ambiguous
    # (decision 3), so both may go to the owner and no answer is drafted.
    slots = _count(pr, "SELECT count(*) FROM outreach_reply_slots WHERE business_id = :b")
    assert slots <= 1
    assert _count(pr, "SELECT count(*) FROM aria_actions WHERE business_id = :b "
                      "AND action_type = 'reply_outreach'") == slots
    if slots == 0:
        assert {r.get("status") for r in results} == {"handed_over"}
        assert _count(pr, "SELECT count(*) FROM outreach_replies WHERE business_id = :b "
                          "AND resolution <> 'handed_over'") == 0


def test_two_taps_on_one_answer_at_once_send_once(pr):
    _incoming(pr)
    _scan(pr)
    (rid,) = _reply_ids(pr)
    card = _propose(pr, rid)
    results, errors = _together(lambda: _approve(pr, card), lambda: _approve(pr, card))
    assert len(pr.p.sends) == 1, (results, errors)
    assert len(results) == 1 and len(errors) == 1


def test_owner_takeover_between_search_and_claim_stops_the_answer(pr, monkeypatch):
    _incoming(pr)
    _scan(pr)
    (rid,) = _reply_ids(pr)
    card = _propose(pr, rid)
    real = pr.m.search_reply_before_claim

    def then_takeover(session, business, **kwargs):
        out = real(session, business, **kwargs)
        with Session(pr.engine) as other:
            pr.replies.handover(other, business, reply_id=rid, user_id=OWNER, moment=NOW)
        return out
    monkeypatch.setattr(pr.m, "search_reply_before_claim", then_takeover)
    with pytest.raises(pr.a.ActionRefused):
        _approve(pr, card)
    assert not pr.p.sends
    assert _count(pr, "SELECT count(*) FROM outreach_usage_events WHERE business_id = :b") == 0


def test_a_lost_reply_claim_rolls_everything_back(pr, monkeypatch):
    _incoming(pr)
    _scan(pr)
    (rid,) = _reply_ids(pr)
    card = _propose(pr, rid)
    real = pr.m.prepare_reply_claim

    def then_dismissed(session, business, **kwargs):
        real(session, business, **kwargs)
        session.execute(text("UPDATE aria_actions SET status = 'dismissed' WHERE id = :id"), {"id": card["id"]})
    monkeypatch.setattr(pr.m, "prepare_reply_claim", then_dismissed)
    with pytest.raises(pr.a.ActionRefused):
        _approve(pr, card)
    assert not pr.p.sends
    assert _count(pr, "SELECT count(*) FROM outreach_usage_events WHERE business_id = :b") == 0
    assert _count(pr, "SELECT count(*) FROM outreach_dispatch_jobs WHERE business_id = :b") == 0
    assert (_count(pr, "SELECT coalesce(sum(reserved + accepted + unknown), 0) FROM outreach_daily_usage "
                       "WHERE business_id = :b") or 0) == 0, "no leaked daily reservation"
    assert _count(pr, "SELECT count(*) FROM outreach_messages WHERE business_id = :b "
                      "AND direction = 'outbound' AND state <> 'accepted'") == 0
    assert _count(pr, "SELECT message_id FROM outreach_reply_slots WHERE business_id = :b") is None
    assert (_count(pr, "SELECT coalesce(sum(value), 0) FROM usage_meters WHERE business_id = :b "
                       "AND meter LIKE 'outreach%'") or 0) == 0
    assert _count(pr, "SELECT status FROM aria_actions WHERE id = :id", id=card["id"]) == "proposed"
