"""OUT-7 executable Stage A contract, synthetic SQLite, no network.

Only absence of services.outreach_replies is an expected failure. Once present,
missing APIs, dependency imports, assertions and unexpected errors fail normally.
SQLite proves service predicates, not PostgreSQL locks: schema race is separate.
"""
import importlib
import importlib.util
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlmodel import Session

from test_outreach_send import (
    A, B, BOX, BRAND, CAMPAIGN, DEFAULT, EMAIL, ENROLMENT, NOW, OWNER, PROSPECT,
    STAFF, STAMP, add, claim, database, h, insert, predecessor, presearch, propose, uid,
)

__all__ = ["database", "h"]


class MissingImplementation(Exception):
    """The single allowed expected-failure cause."""


pytestmark = pytest.mark.xfail(strict=True, raises=MissingImplementation,
                              reason="OUT-7 Stage A: services.outreach_replies absent")


@pytest.fixture
def r(h, monkeypatch):
    # Build the scaffold before checking module presence; broken fixtures fail.
    sql = (Path(__file__).parents[1] / 'migrations/038_outreach_replies.sql').read_text()
    tables = re.findall(r'CREATE TABLE IF NOT EXISTS public\.(outreach_\w+) \(\n(.*?)\n\);', sql, re.S)
    assert len(tables) == 2
    for name, body in tables:
        cols = []
        for line in body.splitlines():
            match = re.match(r'  ([a-z_]+) (uuid|text|jsonb|integer|timestamptz)\b', line)
            if match:
                col, kind = match.groups()
                cols.append(f'{col} ' + ('INTEGER' if kind == 'integer' else 'TEXT') +
                            (' PRIMARY KEY' if col == 'id' else ''))
        h.s.execute(text(f"CREATE TABLE {name} ({','.join(cols)})"))
    for ddl in (
        'CREATE UNIQUE INDEX slot_prospect ON outreach_reply_slots(business_id,prospect_id)',
        'CREATE UNIQUE INDEX slot_reply ON outreach_reply_slots(business_id,reply_id)',
        'CREATE UNIQUE INDEX slot_action ON outreach_reply_slots(business_id,action_id)',
        'CREATE UNIQUE INDEX inbound_once ON outreach_replies(business_id,inbound_email_id)',
        'CREATE TABLE chase_replies(id TEXT PRIMARY KEY,business_id TEXT,status TEXT)',
    ):
        h.s.execute(text(ddl))
    insert(h.s, 'chase_replies', id=uid('chase'), business_id=A, status='pending')
    predecessor(h)
    h.s.commit()
    if importlib.util.find_spec('services.outreach_replies') is None:
        raise MissingImplementation()
    h.replies = importlib.import_module('services.outreach_replies')
    monkeypatch.setattr(h.replies, 'now', lambda: NOW)
    return h


def incoming(r, *, ident='incoming', mailbox=BOX, thread='previous-thread', business=A,
             sender=EMAIL, body='When are appointments available?', received=STAMP):
    ident = uid(ident)
    insert(r.s, 'email_messages', id=ident, business_id=business, email_account_id=mailbox,
           provider_message_id=ident, provider_thread_id=thread, folder='INBOX',
           from_email=sender, subject='Re: Previous', body_text=body,
           received_at=received, created_at=STAMP, updated_at=STAMP)
    r.s.commit()
    return ident


def scan(r, category='question', classify=None):
    return r.replies.scan(r.s, r.b, classify=classify or (
        lambda _: {'category': category, 'confidence': 100, 'classification_version': 1}), moment=NOW)


def state(r):
    return r.s.execute(text('SELECT state FROM outreach_enrolments WHERE id=:id'), {'id': ENROLMENT}).scalar_one()


def reply_id(r):
    return r.s.execute(text('SELECT id FROM outreach_replies WHERE business_id=:b'), {'b': A}).scalar_one()


def fact(r, **changes):
    values = dict(brand_id=BRAND, topic='availability', answer='Weekday appointments',
                  source_reference='https://example.invalid/facts', version=1, status='approved',
                  approved_by=OWNER, approved_at=STAMP, review_due_at='2026-12-01T00:00:00+00:00')
    values.update(changes)
    ident = add(r.s, 'knowledge', **values)
    r.s.commit()
    return ident


def answer(r, rid=None, draft=None):
    return r.replies.propose_answer(r.s, r.b, reply_id=rid or reply_id(r), moment=NOW,
        draft=draft or (lambda context: {'body': 'Weekday appointments',
            'knowledge_refs': [{'id': k['id'], 'version': k['version']} for k in context['knowledge']]}))


def test_pause_is_durable_before_classification_and_next_step_cannot_claim(r):
    card = propose(r)
    presearch(r, card)
    incoming(r)
    def classify(_):
        with Session(r.engine) as other:
            assert other.execute(text('SELECT state FROM outreach_enrolments WHERE id=:id'),
                                 {'id': ENROLMENT}).scalar_one() == 'replied'
        return {'category': 'question', 'confidence': 100, 'classification_version': 1}
    scan(r, classify=classify)
    assert state(r) == 'replied'
    with pytest.raises(r.a.ActionRefused):
        claim(r, card)
    r.s.rollback()
    assert not r.p.sends


def test_reply_stored_between_search_and_claim_blocks_without_scan(r):
    card = propose(r)
    presearch(r, card)
    incoming(r)
    with pytest.raises(r.a.ActionRefused):
        claim(r, card)
    r.s.rollback()
    assert r.s.execute(text('SELECT count(*) FROM outreach_usage_events')).scalar_one() == 0


@pytest.mark.parametrize('mailbox,thread', [(DEFAULT, 'previous-thread'), (BOX, 'unrelated-thread')])
def test_thread_ids_are_mailbox_scoped_and_subject_is_not_identity(r, mailbox, thread):
    incoming(r, mailbox=mailbox, thread=thread)
    scan(r)
    assert state(r) == 'paused'  # same sender, uncertain attribution: hold for owner
    assert r.s.execute(text('SELECT count(*) FROM outreach_reply_slots')).scalar_one() == 0
    assert r.s.execute(text('SELECT count(*) FROM aria_actions WHERE action_type=\'reply_outreach\'')).scalar_one() == 0


def test_two_mailboxes_two_threads_keep_attribution_but_share_answer_limit(r):
    fact(r)
    incoming(r)
    scan(r)
    first = answer(r)
    assert first['id']
    add(r.s, 'messages', prospect_id=PROSPECT, campaign_id=CAMPAIGN, mailbox_id=DEFAULT,
        kind='bespoke', origin='live', direction='outbound', to_emails=json.dumps([EMAIL]),
        cc_emails='[]', subject='Other', body='Other', payload_hash='other', payload_version=1,
        state='accepted', provider='google', provider_message_id='other', provider_thread_id='other-thread',
        rfc_message_id='<other@example.invalid>', accepted_at=STAMP, idempotency_key='other', authority_snapshot='{}')
    incoming(r, ident='second', mailbox=DEFAULT, thread='other-thread')
    scan(r)
    rid = r.s.execute(text('SELECT id FROM outreach_replies WHERE mailbox_id=:m'), {'m': DEFAULT}).scalar_one()
    result = answer(r, rid)
    assert result['status'] == 'handed_over'
    assert r.s.execute(text('SELECT count(*) FROM outreach_reply_slots')).scalar_one() == 1


def test_unsubscribe_suppresses_and_cancels_pending_work(r):
    card = propose(r)
    incoming(r, body='Please remove me and never email me again')
    scan(r, 'unsubscribe')
    assert state(r) == 'suppressed'
    assert r.s.execute(text('SELECT count(*) FROM outreach_suppressions WHERE business_id=:b'), {'b': A}).scalar_one() == 1
    assert r.s.execute(text('SELECT status FROM aria_actions WHERE id=:id'), {'id': card['id']}).scalar_one() == 'dismissed'
    scan(r, 'question')
    assert state(r) == 'suppressed'


def test_concurrent_sync_and_proposals_create_exactly_one_card(r):
    fact(r)
    incoming(r)
    r.s.close()
    barrier = Barrier(2)
    def sync(_):
        with Session(r.engine) as session:
            worker = SimpleNamespace(**{**vars(r), 's': session})
            barrier.wait(timeout=5)
            scan(worker)
            return answer(worker)['id']
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(sync, range(2)))
    assert ids[0] == ids[1]
    assert r.s.execute(text('SELECT count(*) FROM outreach_replies WHERE business_id=:b'), {'b': A}).scalar_one() == 1
    assert r.s.execute(text('SELECT count(*) FROM outreach_reply_slots')).scalar_one() == 1
    assert r.s.execute(text("SELECT count(*) FROM aria_actions WHERE action_type='reply_outreach'")).scalar_one() == 1


@pytest.mark.parametrize('changes', [{'status': 'draft'}, {'status': 'retired', 'retired_at': STAMP},
    {'review_due_at': STAMP}, {'business_id': B}, {'brand_id': uid('other-brand')}])
def test_unapproved_retired_expired_or_foreign_knowledge_is_never_given_to_drafter(r, changes):
    fact(r, **changes)
    incoming(r)
    scan(r)
    def forbidden(_):
        pytest.fail('No current approved knowledge: must hand over without drafting')
    assert answer(r, draft=forbidden)['status'] == 'handed_over'
    assert r.s.execute(text('SELECT count(*) FROM outreach_reply_slots')).scalar_one() == 0


def test_answer_pins_only_current_approved_fact_versions(r):
    fact(r, version=1, status='retired', retired_at=STAMP)
    current = fact(r, version=2)
    incoming(r)
    scan(r)
    seen = []
    def draft(context):
        seen.extend(context['knowledge'])
        return {'body': 'Weekday appointments', 'knowledge_refs': [{'id': current, 'version': 2}]}
    card = answer(r, draft=draft)
    assert [(k['id'], k['version']) for k in seen] == [(current, 2)]
    assert card['preview']['knowledge_refs'] == [{'id': current, 'version': 2}]
    assert not r.p.sends


@pytest.mark.parametrize('who', [None, STAFF, uid('inactive-owner'), uid('platform-admin'), uid('foreign-owner')])
def test_answer_card_uses_real_owner_only_approval_boundary(r, who):
    from services import aria_actions
    fact(r)
    incoming(r)
    scan(r)
    card = answer(r)
    if who == uid('inactive-owner'):
        insert(r.s, 'business_members', business_id=A, user_id=who, role='owner', is_active=False)
    if who == uid('foreign-owner'):
        insert(r.s, 'business_members', business_id=B, user_id=who, role='owner', is_active=True)
    r.s.commit()
    with pytest.raises(aria_actions.ActionRefused) as exc:
        aria_actions.approve(r.s, r.b, card['id'], who, version=card['version'])
    assert exc.value.status_code == 403
    assert not r.p.sends


def test_handover_is_terminal_and_stale_classification_cannot_undo_it(r):
    incoming(r)
    scan(r)
    rid = reply_id(r)
    r.replies.handover(r.s, r.b, reply_id=rid, user_id=OWNER, moment=NOW)
    before = r.s.execute(text('SELECT state,takeover_at FROM outreach_enrolments WHERE id=:id'), {'id': ENROLMENT}).one()
    scan(r, 'question')
    assert r.s.execute(text('SELECT state,takeover_at FROM outreach_enrolments WHERE id=:id'), {'id': ENROLMENT}).one() == before
    assert answer(r)['status'] == 'handed_over'
    assert r.s.execute(text('SELECT resolution FROM outreach_replies WHERE id=:id'), {'id': rid}).scalar_one() == 'handed_over'


def test_outreach_scan_never_mutates_invoice_chasing_or_other_business(r):
    before = r.s.execute(text('SELECT * FROM chase_replies')).all()
    other = r.s.execute(text('SELECT * FROM outreach_enrolments WHERE business_id=:b'), {'b': B}).all()
    incoming(r)
    incoming(r, ident='foreign-inbound', business=B)
    scan(r, 'unsubscribe')
    assert r.s.execute(text('SELECT * FROM chase_replies')).all() == before
    assert r.s.execute(text('SELECT * FROM outreach_enrolments WHERE business_id=:b'), {'b': B}).all() == other
    assert r.s.execute(text('SELECT count(*) FROM outreach_replies WHERE business_id=:b'), {'b': B}).scalar_one() == 0


def test_stale_classifier_result_cannot_overwrite_newer_owner_handover(r):
    incoming(r)
    def slow(_):
        with Session(r.engine) as session:
            rid = session.execute(text('SELECT id FROM outreach_replies WHERE business_id=:b'), {'b': A}).scalar_one()
            r.replies.handover(session, r.b, reply_id=rid, user_id=OWNER, moment=NOW)
        return {'category': 'question', 'confidence': 100, 'classification_version': 1}
    scan(r, classify=slow)
    assert r.s.execute(text('SELECT resolution FROM outreach_replies WHERE business_id=:b'), {'b': A}).scalar_one() == 'handed_over'
    assert answer(r)['status'] == 'handed_over'


def test_active_owner_can_approve_one_answer_through_real_hook(r):
    from services import aria_actions
    fact(r)
    incoming(r)
    scan(r)
    card = answer(r)
    result = aria_actions.approve(r.s, r.b, card['id'], OWNER, version=card['version'])
    assert result['status'] == 'done'
    assert len(r.p.sends) == 1
    assert r.s.execute(text('SELECT state FROM outreach_reply_slots')).scalar_one() == 'accepted'


@pytest.mark.parametrize('change', ['retire', 'expire'])
def test_knowledge_changed_after_proposal_refuses_claim(r, monkeypatch, change):
    from datetime import timedelta
    from services import aria_actions
    kid = fact(r, review_due_at=(NOW + timedelta(seconds=30)).isoformat())
    incoming(r)
    scan(r)
    card = answer(r)
    if change == 'retire':
        r.s.execute(text("UPDATE outreach_knowledge SET status='retired',retired_at=:at WHERE id=:id"),
                    {'at': STAMP, 'id': kid})
        r.s.commit()
    else:
        later = NOW + timedelta(seconds=31)
        monkeypatch.setattr(aria_actions, 'now', lambda: later)
        monkeypatch.setattr(r.m, 'now', lambda: later)
        monkeypatch.setattr(r.replies, 'now', lambda: later)
    with pytest.raises(aria_actions.ActionRefused):
        aria_actions.approve(r.s, r.b, card['id'], OWNER, version=card['version'])
    assert not r.p.sends
    assert r.s.execute(text('SELECT count(*) FROM outreach_usage_events')).scalar_one() == 0


def test_older_scan_cannot_replace_newer_suppression(r):
    from datetime import timedelta
    incoming(r)
    scan(r, 'unsubscribe')
    before = r.s.execute(text('SELECT * FROM outreach_enrolments WHERE id=:id'), {'id': ENROLMENT}).one()
    r.replies.scan(r.s, r.b, moment=NOW - timedelta(hours=1), classify=lambda _: {
        'category': 'interested', 'confidence': 100, 'classification_version': 1})
    assert r.s.execute(text('SELECT * FROM outreach_enrolments WHERE id=:id'), {'id': ENROLMENT}).one() == before
    assert state(r) == 'suppressed'
