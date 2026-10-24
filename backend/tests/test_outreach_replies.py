"""OUT-7 executable service contract, synthetic SQLite, no network.

Only the Claude-owned reply registration/owner hook is strictly expected to fail.
Original Stage A assertions remain; direct service tests do not replace the hook.
SQLite proves service predicates, not PostgreSQL locks: schema race is separate.
"""
import importlib
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


class MissingSharedHook(Exception):
    """Only Claude's absent reply registration is expected to fail."""


# Strict-xfailed until Claude's hook landed (24 Oct 2026); now they must pass.
HOOK = pytest.mark.usefixtures()


def require_hook():
    from services import aria_actions
    if 'reply_outreach' not in aria_actions.ACTION_TYPES:
        raise MissingSharedHook()


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
@HOOK
def test_answer_card_uses_real_owner_only_approval_boundary(r, who):
    from services import aria_actions
    fact(r)
    incoming(r)
    scan(r)
    card = answer(r)
    require_hook()
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


@HOOK
def test_active_owner_can_approve_one_answer_through_real_hook(r):
    from services import aria_actions
    fact(r)
    incoming(r)
    scan(r)
    card = answer(r)
    require_hook()
    result = aria_actions.approve(r.s, r.b, card['id'], OWNER, version=card['version'])
    assert result['status'] == 'done'
    assert len(r.p.sends) == 1
    assert r.s.execute(text('SELECT state FROM outreach_reply_slots')).scalar_one() == 'accepted'


@pytest.mark.parametrize('change', ['retire', 'expire'])
@HOOK
def test_knowledge_changed_after_proposal_refuses_claim(r, monkeypatch, change):
    from datetime import timedelta
    from services import aria_actions
    kid = fact(r, review_due_at=(NOW + timedelta(seconds=30)).isoformat())
    incoming(r)
    scan(r)
    card = answer(r)
    require_hook()
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


def service_approve(r, card):
    """Real reply service with local CAS; deliberately not the owner hook."""
    payload = card['preview']
    r.m.search_before_claim(r.s, r.b, action_id=card['id'], payload=payload)
    try:
        r.m.prepare_claim(r.s, r.b, action_id=card['id'], payload=payload,
                          user_id=OWNER, version=card['version'], moment=NOW)
        changed = r.s.execute(text("UPDATE aria_actions SET status='executing' WHERE business_id=:b AND id=:a AND status='proposed'"), {'b': A, 'a': card['id']})
        assert changed.rowcount == 1
        r.s.commit()
    except Exception:
        r.s.rollback()
        raise
    return r.m.dispatch(r.s, r.b, action_id=card['id'], payload=payload)


def ready_answer(r):
    fact(r)
    incoming(r)
    scan(r)
    return answer(r)


@pytest.mark.parametrize('outcome,expected', [('accepted', 'accepted'), ('unknown', 'unknown'),
                                            ('definitely_not_accepted', 'unknown')])
def test_reply_typed_claim_dispatch_and_slot_settlement(r, outcome, expected):
    card = ready_answer(r)
    r.p.outcome = outcome
    service_approve(r, card)
    assert len(r.p.sends) == 1
    assert state(r) == 'replied'
    assert r.s.execute(text('SELECT state FROM outreach_reply_slots')).scalar_one() == expected
    message = r.s.execute(text("SELECT kind,mailbox_id FROM outreach_messages WHERE action_id=:a"), {'a': card['id']}).one()
    assert message == ('bespoke', BOX)
    with pytest.raises(r.a.ActionRefused):
        r.m.dispatch(r.s, r.b, action_id=card['id'], payload=card['preview'])
    assert len(r.p.sends) == 1


def test_unknown_cannot_release_or_timeout_repropose(r):
    from datetime import timedelta
    card = ready_answer(r)
    r.p.outcome = 'unknown'
    service_approve(r, card)
    with pytest.raises(r.a.ActionRefused):
        r.replies.release_slot(r.s, r.b, slot_id=card['preview']['slot_id'], user_id=OWNER, moment=NOW + timedelta(days=90))
    r.s.rollback()
    assert answer(r)['status'] == 'handed_over'
    assert len(r.p.sends) == 1


def test_owner_reviewed_definite_rejection_reuses_slot_with_new_operation(r):
    card = ready_answer(r)
    r.p.outcome = 'definitely_not_accepted'
    service_approve(r, card)
    sid = card['preview']['slot_id']
    r.replies.release_slot(r.s, r.b, slot_id=sid, user_id=OWNER, moment=NOW)
    replacement = r.replies.replace_answer(r.s, r.b, slot_id=sid, user_id=OWNER, moment=NOW)
    assert replacement['preview']['slot_id'] == sid
    assert replacement['preview']['slot_generation'] == 2
    assert replacement['preview']['idempotency_key'] != card['preview']['idempotency_key']
    assert replacement['id'] != card['id']
    audit = json.loads(r.s.execute(text('SELECT result FROM aria_actions WHERE id=:a'), {'a': card['id']}).scalar_one())
    assert audit['released_slot']['generation'] == '1'
    assert r.s.execute(text('SELECT count(*) FROM outreach_reply_slots')).scalar_one() == 1
    assert r.s.execute(text('SELECT count(*) FROM outreach_dispatch_jobs')).scalar_one() == 1
    assert len(r.p.sends) == 1


def test_unknown_reconciliation_is_once_and_never_transports(r):
    card = ready_answer(r)
    r.p.outcome = 'unknown'
    service_approve(r, card)
    def verify(query):
        assert not r.s.in_transaction()
        return dict(outcome='accepted', operation_key=query['idempotency_key'], mailbox_id=BOX,
                    provider='google', verification_reference='synthetic-verified', provider_message_id='verified-id')
    for _ in range(2):
        r.replies.reconcile(r.s, r.b, action_id=card['id'], verify=verify, moment=NOW)
    assert len(r.p.sends) == 1
    assert r.s.execute(text('SELECT state FROM outreach_reply_slots')).scalar_one() == 'accepted'
    assert r.s.execute(text('SELECT count(*) FROM email_outbox')).scalar_one() == 1
    assert r.s.execute(text("SELECT value FROM usage_meters WHERE meter='outreach_emails_sent'")).scalar_one() == 1


def test_reply_claim_rollback_includes_slot_message_and_usage(r):
    card = ready_answer(r)
    r.m.search_before_claim(r.s, r.b, action_id=card['id'], payload=card['preview'])
    r.m.prepare_claim(r.s, r.b, action_id=card['id'], payload=card['preview'],
                      user_id=OWNER, version=card['version'], moment=NOW)
    r.s.rollback()  # shared hook's lost-CAS/exception path
    r.s.info.get('outreach_dispatch', {}).pop(card['id'], None)
    assert r.s.execute(text('SELECT message_id FROM outreach_reply_slots')).scalar_one() is None
    assert r.s.execute(text('SELECT count(*) FROM outreach_usage_events')).scalar_one() == 0
    assert r.s.execute(text('SELECT count(*) FROM outreach_dispatch_jobs')).scalar_one() == 0
    assert not r.p.sends


@pytest.mark.parametrize('change', ['knowledge', 'new_inbound', 'takeover', 'suppression'])
def test_reply_service_rechecks_after_search_before_claim(r, change):
    card = ready_answer(r)
    r.m.search_before_claim(r.s, r.b, action_id=card['id'], payload=card['preview'])
    if change == 'knowledge':
        r.s.execute(text("UPDATE outreach_knowledge SET status='retired'"))
        r.s.commit()
    elif change == 'new_inbound':
        incoming(r, ident='another-question')
    elif change == 'takeover':
        r.replies.handover(r.s, r.b, reply_id=reply_id(r), user_id=OWNER, moment=NOW)
    else:
        r.replies._suppress(r.s, A, r.m.one(r.s, 'outreach_prospects', A, PROSPECT), 'unsubscribe', NOW)
        r.s.commit()
    with pytest.raises(r.a.ActionRefused):
        r.m.prepare_claim(r.s, r.b, action_id=card['id'], payload=card['preview'],
                          user_id=OWNER, version=card['version'], moment=NOW)
    r.s.rollback()
    assert r.s.execute(text('SELECT count(*) FROM outreach_usage_events')).scalar_one() == 0
    assert not r.p.sends


@pytest.mark.parametrize('body,refs', [('Weekday appointments. Price £50', None),
                                     ('Weekday appointments', [{'id': uid('invented'), 'version': 1}])])
def test_unsupported_claims_and_citations_hand_over(r, body, refs):
    kid = fact(r)
    incoming(r)
    scan(r)
    assert answer(r, draft=lambda _: {'body': body, 'knowledge_refs': refs or [{'id': kid, 'version': 1}]})['status'] == 'handed_over'
    assert r.s.execute(text('SELECT count(*) FROM outreach_reply_slots')).scalar_one() == 0


def test_explicit_optout_needs_neither_classifier_nor_entitlement(r):
    r.b.plan_tier = 'starter'
    incoming(r, body='Please unsubscribe me')
    def forbidden(_):
        pytest.fail('Explicit opt-out must not need classification')
    scan(r, classify=forbidden)
    assert state(r) == 'suppressed'


def test_storage_completion_uses_existing_inbox_without_provider(r, monkeypatch):
    from services.outreach_replies import storage_completed as outreach_storage_completed
    incoming(r)
    def forbidden(*args, **kwargs):
        pytest.fail('storage completion must not poll')
    monkeypatch.setattr(r.m, 'get_provider_for_account', forbidden)
    assert outreach_storage_completed(r.s, r.b)
    assert state(r) == 'paused'
    assert r.s.execute(text('SELECT resolution FROM outreach_replies')).scalar_one() == 'handed_over'


@pytest.mark.parametrize('kind', ['hard_bounce', 'complaint'])
def test_authenticated_health_observations_are_scoped_and_idempotent(r, kind):
    ident = incoming(r, sender='mailer-daemon@example.invalid')
    message = r.s.execute(text("SELECT id,provider_message_id FROM outreach_messages WHERE state='accepted'")).one()
    kwargs = dict(inbound_email_id=ident, message_id=message.id, kind=kind,
                  evidence={'authenticated': True, 'mailbox_id': BOX, 'provider': 'google',
                            'provider_message_id': message.provider_message_id}, moment=NOW)
    assert r.replies.observe_health(r.s, r.b, **kwargs)['recorded']
    assert not r.replies.observe_health(r.s, r.b, **kwargs)['recorded']
    assert r.s.execute(text('SELECT count(*) FROM outreach_replies')).scalar_one() == 1
    if kind == 'hard_bounce':
        assert state(r) == 'suppressed'
    else:
        assert r.s.execute(text('SELECT enabled FROM outreach_mailboxes WHERE mailbox_id=:m'), {'m': BOX}).scalar_one() == 0
    assert not r.p.sends


def test_knowledge_owner_write_versions_and_expires_explicitly(r):
    kwargs = dict(brand_id=BRAND, topic='availability', answer='Weekday appointments',
                  source_reference='https://example.invalid/facts', review_due_at='2026-12-01T00:00:00+00:00', moment=NOW)
    with pytest.raises(r.a.ActionRefused):
        r.replies.save_knowledge(r.s, r.b, user_id=STAFF, **kwargs)
    r.s.rollback()
    for _ in range(2):
        r.replies.save_knowledge(r.s, r.b, user_id=OWNER, **kwargs)
    assert r.s.execute(text('SELECT version,status FROM outreach_knowledge ORDER BY version')).all() == [(1, 'retired'), (2, 'approved')]


def test_three_distinct_recent_hard_bounces_pause_only_their_mailbox(r):
    for i in range(3):
        message = add(r.s, 'messages', prospect_id=PROSPECT, campaign_id=CAMPAIGN, mailbox_id=BOX,
                      kind='bespoke', origin='live', direction='outbound', to_emails=json.dumps([EMAIL]),
                      cc_emails='[]', subject='Synthetic', body='Synthetic', payload_hash='hash', payload_version=1,
                      state='accepted', provider='google', provider_message_id=f'bounced-{i}',
                      provider_thread_id=f'bounced-thread-{i}', accepted_at=STAMP, idempotency_key=f'bounced-{i}', authority_snapshot='{}')
        inbound = incoming(r, ident=f'bounce-{i}', sender='mailer-daemon@example.invalid')
        result = r.replies.observe_health(r.s, r.b, inbound_email_id=inbound, message_id=message,
                    kind='hard_bounce', evidence={'authenticated': True, 'mailbox_id': BOX, 'provider': 'google',
                                               'provider_message_id': f'bounced-{i}'}, moment=NOW)
        assert result['distinct_hard_bounces_in_latest_50'] == i + 1
    assert r.s.execute(text('SELECT enabled,health_status FROM outreach_mailboxes WHERE mailbox_id=:m'), {'m': BOX}).one() == (0, 'fail')
    scan(r)
    assert r.s.execute(text('SELECT enabled FROM outreach_mailboxes WHERE mailbox_id=:m'), {'m': BOX}).scalar_one() == 0


def test_owner_takeover_between_claim_and_dispatch_stops_transport(r):
    card = ready_answer(r)
    r.m.search_reply_before_claim(r.s, r.b, action_id=card['id'], payload=card['preview'])
    r.m.prepare_reply_claim(r.s, r.b, action_id=card['id'], payload=card['preview'], user_id=OWNER,
                           version=card['version'], moment=NOW)
    r.s.execute(text("UPDATE aria_actions SET status='executing' WHERE id=:a"), {'a': card['id']})
    r.s.commit()
    with Session(r.engine) as other:
        r.replies.handover(other, r.b, reply_id=card['preview']['reply_id'], user_id=OWNER, moment=NOW)
    result = r.m.dispatch_reply(r.s, r.b, action_id=card['id'], payload=card['preview'])
    assert result['outcome'] == 'definitely_not_accepted'
    assert not r.p.sends


def test_accepted_slot_is_terminal_and_dismissed_proposal_never_redrafts(r):
    card = ready_answer(r)
    service_approve(r, card)
    with pytest.raises(r.a.ActionRefused):
        r.replies.release_slot(r.s, r.b, slot_id=card['preview']['slot_id'], user_id=OWNER, moment=NOW)
    r.s.rollback()
    assert answer(r)['status'] == 'handed_over'
    assert r.s.execute(text('SELECT state FROM outreach_reply_slots')).scalar_one() == 'accepted'


@pytest.mark.parametrize('user', [STAFF, OWNER])
def test_handover_http_authority_and_downgraded_safety(r, user):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from auth import get_user_business_context
    from db import get_session
    from app.email import router as email_router
    from outreach_read import router
    incoming(r)
    scan(r)
    rid = reply_id(r)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_user_business_context] = lambda: {'business_id': A, 'user_id': user}
    app.dependency_overrides[get_session] = lambda: r.s
    original = email_router.get_business_by_id
    email_router.get_business_by_id = lambda *_: r.b
    try:
        r.b.plan_tier = 'starter'
        with TestClient(app) as client:
            response = client.post(f'/v1/outreach/replies/{rid}/handover')
        assert response.status_code == (200 if user == OWNER else 403)
    finally:
        email_router.get_business_by_id = original
    assert not r.p.sends


def test_knowledge_http_rejects_tenant_and_actor_in_body(r, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from auth import get_user_business_context
    from db import get_session
    from app.email import router as email_router
    from outreach_read import router
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_user_business_context] = lambda: {'business_id': A, 'user_id': OWNER}
    app.dependency_overrides[get_session] = lambda: r.s
    monkeypatch.setattr(email_router, 'get_business_by_id', lambda *_: r.b)
    body = {'brand_id': BRAND, 'topic': 'availability', 'answer': 'Weekday appointments',
            'source_reference': 'https://example.invalid/facts', 'review_due_at': '2026-12-01T00:00:00Z'}
    with TestClient(app) as client:
        assert client.post('/v1/outreach/knowledge', json={**body, 'business_id': B, 'user_id': STAFF}).status_code == 422
        assert client.post('/v1/outreach/knowledge', json=body).status_code == 200
    assert r.s.execute(text('SELECT business_id,approved_by FROM outreach_knowledge')).one() == (A, OWNER)


def test_resolved_reply_cannot_be_reopened_by_proposal(r):
    ready_answer(r)
    r.s.execute(text("UPDATE outreach_replies SET resolution='resolved'"))
    r.s.commit()
    assert answer(r)['status'] == 'handed_over'
    assert r.s.execute(text('SELECT resolution FROM outreach_replies')).scalar_one() == 'resolved'


def test_draft_callback_cannot_overwrite_concurrent_takeover(r):
    kid = fact(r)
    incoming(r)
    scan(r)
    rid = reply_id(r)
    def draft(_):
        assert not r.s.in_transaction()
        with Session(r.engine) as other:
            r.replies.handover(other, r.b, reply_id=rid, user_id=OWNER, moment=NOW)
        return {'body': 'Weekday appointments', 'knowledge_refs': [{'id': kid, 'version': 1}]}
    assert answer(r, draft=draft)['status'] == 'handed_over'
    assert r.s.execute(text('SELECT count(*) FROM outreach_reply_slots')).scalar_one() == 0


def test_future_approved_fact_is_not_given_to_drafter(r):
    from datetime import timedelta
    fact(r, approved_at=(NOW + timedelta(minutes=1)).isoformat())
    incoming(r)
    scan(r)
    assert answer(r, draft=lambda _: pytest.fail('Future approval cannot ground an answer'))['status'] == 'handed_over'


def test_sender_sql_prefilter_preserves_rfc_address_forms(r):
    card = propose(r)
    presearch(r, card)
    incoming(r, sender=EMAIL + ' (Person)')
    with pytest.raises(r.a.ActionRefused):
        claim(r, card)
    r.s.rollback()
    assert not r.p.sends


def test_same_thread_across_campaigns_without_rfc_evidence_is_ambiguous(r):
    add(r.s, 'messages', prospect_id=PROSPECT, campaign_id=uid('second-campaign'), mailbox_id=BOX,
        kind='bespoke', origin='live', direction='outbound', to_emails=json.dumps([EMAIL]),
        cc_emails='[]', subject='Different brand', body='Different brand', payload_hash='hash', payload_version=1,
        state='accepted', provider='google', provider_message_id='other-campaign', provider_thread_id='previous-thread',
        rfc_message_id='<other@example.invalid>', accepted_at=STAMP, idempotency_key='other-campaign', authority_snapshot='{}')
    incoming(r)
    scan(r)
    assert state(r) == 'paused'
    assert r.s.execute(text('SELECT matched_message_id FROM outreach_replies')).scalar_one() is None
    assert answer(r)['status'] == 'handed_over'


# ---------------------------------------------- Claude's reply hook (OUT-7) ---

def test_hook_an_answer_card_comes_only_from_a_stored_reply(r):
    from services import aria_actions
    assert 'reply_outreach' in aria_actions.ACTION_TYPES
    assert 'reply_outreach' not in aria_actions.CHAT_ACTION_TYPES
    out = aria_actions.propose(r.s, r.b, OWNER, 'reply_outreach', {'body': 'Anything at all'})
    assert 'error' in out
    assert 'error' in aria_actions.propose_from_chat(A, OWNER, 'reply_outreach', {'body': 'x'})
    assert r.s.execute(text("SELECT count(*) FROM aria_actions WHERE action_type='reply_outreach'")).scalar() == 0


def test_hook_an_answer_card_cannot_be_edited(r):
    from services import aria_actions
    fact(r)
    incoming(r)
    scan(r)
    card = answer(r)
    for change in ({'body': 'Invented claim'}, {}):
        with pytest.raises(aria_actions.ActionRefused) as exc:
            aria_actions.edit(r.s, r.b, card['id'], change)
        assert exc.value.status_code == 422
    assert aria_actions.approve(r.s, r.b, card['id'], OWNER, version=card['version'])['status'] == 'done'
