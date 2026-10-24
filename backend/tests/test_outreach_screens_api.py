"""OUT-8 Stage A HTTP contracts. Only an absent route may strictly xfail.

Reuse synthetic 037/038 fixtures; no production schema, sockets or model calls.
No service or authorization implementation is mocked. Auth context/business
loading is the same local seam as OUT-7. SQLite does not prove RLS/row locks.
"""
import importlib
import importlib.util
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from test_outreach_replies import incoming, r, reply_id, scan
from test_outreach_send import (
    A, B, BOX, BRAND, CAMPAIGN, DEFAULT, FOREIGN, OWNER, PROSPECT, STAFF,
    database, h, uid,
)

__all__ = ['database', 'h', 'r']


class MissingRoute(Exception):
    """Only exact method/path absence is expected during Stage A."""


ABSENT = pytest.mark.xfail(strict=True, raises=MissingRoute, reason='OUT-8 Stage A: route absent')
BASE = '/v1/outreach'
WRITES = [
    ('POST', '/campaigns', {'name': 'Pilot', 'brand_id': BRAND, 'mailbox_id': BOX, 'daily_cap': 5}),
    ('PATCH', '/campaigns/{campaign_id}', {'version': 1, 'name': 'Reviewed pilot'}),
    ('PUT', '/campaigns/{campaign_id}/sequence', {'version': 1, 'steps': [
        {'ordinal': 0, 'delay_business_days': 0, 'subject': 'Hello', 'body': 'Synthetic offer'},
        {'ordinal': 1, 'delay_business_days': 5, 'subject': 'Following up', 'body': 'Synthetic follow-up'},
        {'ordinal': 2, 'delay_business_days': 7, 'subject': 'Final follow-up', 'body': 'Synthetic final'}]}),
    ('POST', '/campaigns/{campaign_id}/approve-templates', {'version': 1, 'sequence_version': 1}),
    ('PATCH', '/settings', {'pause_all': True, 'business_daily_cap': 5, 'owner_cc_default': False}),
    ('PATCH', '/mailboxes/{mailbox_id}', {'daily_cap': 3}),
    ('POST', '/suppressions', {'email': 'person@example.invalid', 'reason': 'manual_opt_out'}),
    ('POST', '/replies/{reply_id}/resolve', {}),
]
READS = [('GET', '/suppressions', None), ('GET', '/replies/{reply_id}', None)]


@pytest.fixture
def api(r, monkeypatch):
    import auth
    import db
    import outreach_read
    from app.email import router as email_router

    from test_outreach_send import add
    # OUT-7 predecessor changes the seeded step to ordinal 1. Restore the
    # complete OUT-8 sequence before cloning; duplicate ordinal 1 is invalid in 037.
    r.s.execute(text('UPDATE outreach_sequence_steps SET ordinal=0,delay_business_days=0 WHERE campaign_id=:c'), {'c': CAMPAIGN})
    original = dict(r.s.execute(text('SELECT * FROM outreach_sequence_steps WHERE campaign_id=:c'), {'c': CAMPAIGN}).mappings().one())
    for ordinal, delay in ((1, 5), (2, 7)):
        add(r.s, 'sequence_steps', **{**original, 'id': uid(f'step-{ordinal}'), 'ordinal': ordinal, 'delay_business_days': delay})
    r.s.commit()
    incoming(r)
    scan(r)
    actor = SimpleNamespace(user_id=OWNER)
    app = FastAPI()
    app.include_router(outreach_read.router)
    # Stage B owns this new router. Missing imports inside an existing module
    # are real errors, never confused with the module itself being absent.
    if importlib.util.find_spec('outreach_manage') is not None:
        app.include_router(importlib.import_module('outreach_manage').router)
    app.dependency_overrides[auth.get_user_business_context] = lambda: {
        'business_id': A, 'user_id': actor.user_id}
    app.dependency_overrides[db.get_session] = lambda: r.s
    monkeypatch.setattr(auth, '_load_business', lambda *_: r.b)
    monkeypatch.setattr(email_router, 'get_business_by_id', lambda *_: r.b)
    monkeypatch.setattr(auth, 'is_platform_admin_user', lambda *_: False)
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, app=app, data=r, actor=actor, rid=reply_id(r))
    assert not r.p.sends and not r.p.searches, 'Screen endpoints must not contact providers'


def call(api, spec, *, body=None, campaign=CAMPAIGN, mailbox=BOX, reply=None):
    method, template, default = spec
    if method.lower() not in api.app.openapi()['paths'].get(BASE + template, {}):
        raise MissingRoute(f'{method} {BASE}{template}')
    path = template.format(campaign_id=campaign, mailbox_id=mailbox, reply_id=reply or api.rid)
    return api.client.request(method, BASE + path, json=default if body is None else body)


def scalar(api, sql, **params):
    api.data.s.rollback()  # observe committed HTTP state
    return api.data.s.execute(text(sql), params).scalar_one()


def test_synthetic_http_scaffold_and_existing_read_work(api):
    assert api.client.get(BASE + '/campaigns').status_code == 200
    assert scalar(api, 'SELECT count(*) FROM business_members WHERE business_id=:b', b=A) == 2


@pytest.mark.parametrize('spec', WRITES + READS)
def test_each_endpoint_has_owner_positive_control(api, spec):
    response = call(api, spec)
    assert response.status_code == 200, response.text
    assert 'fake-token' not in response.text and 'fake-refresh' not in response.text
    assert 'FOREIGN SECRET' not in response.text


@pytest.mark.parametrize('spec', WRITES)
@pytest.mark.parametrize('actor', ['staff', 'inactive', 'foreign', 'admin'])
def test_every_write_requires_current_active_tenant_owner(api, monkeypatch, spec, actor):
    import auth
    api.actor.user_id = STAFF if actor in ('staff', 'admin') else uid('foreign-owner')
    if actor == 'inactive':
        api.actor.user_id = OWNER
        api.data.s.execute(text('UPDATE business_members SET is_active=0 WHERE user_id=:u'), {'u': OWNER})
        api.data.s.commit()
    if actor == 'admin':
        monkeypatch.setattr(auth, 'is_platform_admin_user', lambda *_: True)
    assert call(api, spec).status_code == 403


@pytest.mark.parametrize('spec', WRITES)
def test_client_cannot_supply_tenant_or_approver(api, spec):
    assert call(api, spec, body={**spec[2], 'business_id': B, 'approved_by': OWNER}).status_code == 422


@pytest.mark.parametrize('spec', WRITES[:4] + [WRITES[5]])
def test_growth_writes_need_outreach_entitlement(api, spec):
    api.data.b.plan_tier = 'starter'
    body = {'daily_cap': 10} if spec == WRITES[5] else spec[2]
    assert call(api, spec, body=body).status_code == 403


@pytest.mark.parametrize('spec', [WRITES[4], WRITES[5], WRITES[6], WRITES[7]])
def test_owner_safety_writes_survive_plan_downgrade(api, spec):
    api.data.b.plan_tier = 'starter'
    assert call(api, spec).status_code == 200


@pytest.mark.parametrize('spec', WRITES[:4] + [WRITES[5]])
def test_explicit_admin_feature_grant_uses_canonical_gate(api, spec):
    api.data.b.plan_tier = 'pro'
    api.data.b.feature_flags = {'outreach': True}
    assert call(api, spec).status_code == 200


@pytest.mark.parametrize('spec', WRITES[1:4])
def test_foreign_campaign_and_missing_are_indistinguishable(api, spec):
    foreign = call(api, spec, campaign=uid('foreign-campaign'))
    missing = call(api, spec, campaign=uid('missing-campaign'))
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()


@pytest.mark.parametrize('mailbox', [FOREIGN, uid('missing-box')])
def test_campaign_cannot_select_foreign_or_missing_mailbox(api, mailbox):
    assert call(api, WRITES[0], body={**WRITES[0][2], 'mailbox_id': mailbox}).status_code == 404


def test_campaign_creation_pins_chosen_mailbox_and_starts_draft(api):
    response = call(api, WRITES[0])
    assert response.status_code == 200
    ident = response.json()['id']
    assert scalar(api, 'SELECT mailbox_id FROM outreach_campaigns WHERE id=:i', i=ident) == BOX
    assert scalar(api, 'SELECT status FROM outreach_campaigns WHERE id=:i', i=ident) == 'draft'
    assert BOX != DEFAULT  # DEFAULT is deliberately newer in the shared fixture.


def test_dispatch_history_prevents_mailbox_reassignment(api):
    # OUT-7 fixture seeds an accepted predecessor in this campaign.
    assert call(api, WRITES[1], body={'version': 1, 'mailbox_id': DEFAULT}).status_code == 409
    assert scalar(api, 'SELECT mailbox_id FROM outreach_campaigns WHERE id=:i', i=CAMPAIGN) == BOX


@pytest.mark.parametrize('spec', WRITES[1:4])
def test_stale_campaign_version_refuses_mutation(api, spec):
    assert call(api, spec, body={**spec[2], 'version': 999}).status_code == 409


def test_sequence_edit_invalidates_approval_and_increments_versions(api):
    api.data.s.execute(text('UPDATE outreach_campaigns SET first_batch_review_id=:r WHERE id=:i'), {'r': uid('old-review'), 'i': CAMPAIGN})
    api.data.s.commit()
    assert call(api, WRITES[2]).status_code == 200
    assert scalar(api, 'SELECT first_batch_review_id FROM outreach_campaigns WHERE id=:i', i=CAMPAIGN) is None
    assert scalar(api, 'SELECT status FROM outreach_campaigns WHERE id=:i', i=CAMPAIGN) == 'paused'
    assert scalar(api, 'SELECT sequence_version FROM outreach_campaigns WHERE id=:i', i=CAMPAIGN) == 2
    assert scalar(api, 'SELECT version FROM outreach_campaigns WHERE id=:i', i=CAMPAIGN) == 2
    assert scalar(api, 'SELECT count(*) FROM outreach_sequence_steps WHERE campaign_id=:i AND sequence_version=2 AND approved_at IS NOT NULL', i=CAMPAIGN) == 0
    assert scalar(api, 'SELECT count(*) FROM outreach_sequence_steps WHERE campaign_id=:i AND sequence_version=1', i=CAMPAIGN) == 3


def test_template_approval_records_owner_without_dispatch(api):
    api.data.s.execute(text('UPDATE outreach_sequence_steps SET approved_by=NULL,approved_at=NULL WHERE campaign_id=:i'), {'i': CAMPAIGN})
    api.data.s.commit()
    assert call(api, WRITES[3]).status_code == 200
    assert scalar(api, 'SELECT count(*) FROM outreach_sequence_steps WHERE campaign_id=:i AND sequence_version=1 AND approved_by=:u AND approved_at IS NOT NULL', i=CAMPAIGN, u=OWNER) == 3
    assert scalar(api, 'SELECT count(*) FROM outreach_dispatch_jobs') == 0


@pytest.mark.parametrize('cap', [0, 21, -1])
@pytest.mark.parametrize('spec,key', [(WRITES[4], 'business_daily_cap'), (WRITES[5], 'daily_cap')])
def test_caps_stay_inside_pilot_ceiling(api, spec, key, cap):
    assert call(api, spec, body={key: cap}).status_code == 422


def test_cc_requires_explicit_address(api):
    assert call(api, WRITES[4], body={'owner_cc_default': True}).status_code == 422


def test_pause_persists_without_restarting_any_enrolment(api):
    assert call(api, WRITES[4], body={'pause_all': True}).status_code == 200
    assert scalar(api, 'SELECT pause_all FROM outreach_settings WHERE business_id=:b', b=A) == 1
    assert scalar(api, "SELECT count(*) FROM outreach_enrolments WHERE business_id=:b AND state='active'", b=A) == 0


def test_manual_opt_out_is_idempotent_and_stops_contact(api):
    import json
    from test_outreach_send import add, insert
    action = uid('queued-action')
    insert(api.data.s, 'aria_actions', id=action, business_id=A, action_type='send_outreach',
           status='proposed', payload=json.dumps({'prospect_id': PROSPECT}))
    message = add(api.data.s, 'messages', prospect_id=PROSPECT, campaign_id=CAMPAIGN,
                  mailbox_id=BOX, state='pending', origin='live', direction='outbound')
    add(api.data.s, 'dispatch_jobs', message_id=message, status='pending', logical_key='out8-pending')
    api.data.s.commit()
    for _ in range(2):
        assert call(api, WRITES[6]).status_code == 200
    assert scalar(api, 'SELECT count(*) FROM outreach_suppressions WHERE business_id=:b', b=A) == 1
    assert scalar(api, 'SELECT state FROM outreach_enrolments WHERE prospect_id=:p', p=PROSPECT) == 'suppressed'
    assert scalar(api, 'SELECT status FROM aria_actions WHERE id=:i', i=action) == 'dismissed'
    assert scalar(api, 'SELECT status FROM outreach_dispatch_jobs WHERE message_id=:i', i=message) == 'cancelled'
    response = call(api, READS[0])
    assert response.status_code == 200
    assert response.json()['total'] == 1
    assert 'key_digest' not in response.text and 'token_digest' not in response.text


def test_resolve_is_idempotent_and_does_not_resume_sequence(api):
    for _ in range(2):
        assert call(api, WRITES[7]).status_code == 200
    assert scalar(api, 'SELECT resolution FROM outreach_replies WHERE id=:i', i=api.rid) == 'resolved'
    assert scalar(api, "SELECT count(*) FROM outreach_enrolments WHERE business_id=:b AND state='active'", b=A) == 0


def test_reply_detail_uses_stored_original_and_exact_mailbox(api):
    response = call(api, READS[1])
    assert response.status_code == 200
    item = response.json()['item']
    assert item['mailbox_id'] == BOX
    assert item['body_text'] == 'When are appointments available?'
    assert item['prospect_id'] == PROSPECT
    assert call(api, READS[1], reply=uid('missing-reply')).status_code == 404


@pytest.mark.parametrize('spec', WRITES + READS)
@pytest.mark.parametrize('denial', ['explicit', 'suspended'])
def test_no_endpoint_bypasses_explicit_denial_or_suspension(api, spec, denial):
    if denial == 'explicit':
        api.data.b.feature_flags = {'outreach': False}
    else:
        api.data.b.is_active = False
    assert call(api, spec).status_code == 403


@pytest.mark.parametrize('spec', [WRITES[5], WRITES[7], READS[1]])
def test_foreign_nested_records_and_missing_are_identical(api, spec):
    from test_outreach_send import add
    foreign_reply = add(api.data.s, 'replies', business_id=B, mailbox_id=FOREIGN,
                        prospect_id=uid('foreign-prospect'), resolution='handed_over')
    api.data.s.commit()
    foreign = call(api, spec, mailbox=FOREIGN, reply=foreign_reply)
    missing = call(api, spec, mailbox=uid('absent-box'), reply=uid('absent-reply'))
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()


@pytest.mark.parametrize('body', [
    {'pause_all': False}, {'owner_cc_default': True, 'owner_cc_address': 'owner@example.invalid'},
    {'business_daily_cap': 20, 'pause_all': True},
])
def test_safety_exception_cannot_smuggle_growth_settings(api, body):
    api.data.b.plan_tier = 'starter'
    api.data.s.execute(text('UPDATE outreach_settings SET business_daily_cap=5 WHERE business_id=:b'), {'b': A})
    api.data.s.commit()
    assert call(api, WRITES[4], body=body).status_code == 403
    assert scalar(api, 'SELECT business_daily_cap FROM outreach_settings WHERE business_id=:b', b=A) == 5


@pytest.mark.parametrize('body', [
    {'version': 1, 'steps': []},
    {'version': 1, 'steps': [{'ordinal': 0, 'delay_business_days': 5, 'subject': 'Hi', 'body': 'Text'}]},
    {'version': 1, 'steps': [{'ordinal': 0, 'delay_business_days': 0, 'subject': '', 'body': 'Text'}]},
])
def test_invalid_sequence_never_changes_current_version(api, body):
    assert call(api, WRITES[2], body=body).status_code == 422
    assert scalar(api, 'SELECT sequence_version FROM outreach_campaigns WHERE id=:i', i=CAMPAIGN) == 1


def test_suppression_of_unlisted_address_needs_no_prospect_or_send(api):
    assert call(api, WRITES[6], body={'email': 'unlisted@example.invalid', 'reason': 'manual_opt_out'}).status_code == 200
    assert scalar(api, 'SELECT count(*) FROM outreach_suppressions WHERE business_id=:b', b=A) == 1
    assert scalar(api, 'SELECT count(*) FROM outreach_prospects WHERE email=:e', e='unlisted@example.invalid') == 0


def test_suppression_list_is_tenant_scoped_and_paginated(api):
    from test_outreach_send import add
    for bid in (A, B):
        for index in range(55):
            add(api.data.s, 'suppressions', business_id=bid, key_type='email',
                key_digest=f'{bid}-{index}', reason='manual_opt_out')
    api.data.s.commit()
    response = call(api, READS[0])
    assert response.status_code == 200
    result = response.json()
    assert result['total'] == 55 and len(result['items']) == 20
    assert B not in response.text and 'key_digest' not in response.text
    assert api.client.get(BASE + '/suppressions?limit=51').status_code == 422


@pytest.mark.parametrize('brand', [uid('foreign-brand'), uid('absent-brand')])
def test_campaign_cannot_reference_another_business_brand(api, brand):
    assert call(api, WRITES[0], body={**WRITES[0][2], 'brand_id': brand}).status_code == 404


def test_mailbox_cap_changes_only_selected_business_mailbox(api):
    assert call(api, WRITES[5]).status_code == 200
    assert scalar(api, 'SELECT daily_cap FROM outreach_mailboxes WHERE business_id=:b AND mailbox_id=:m', b=A, m=BOX) == 3
    assert scalar(api, 'SELECT warmup_stage FROM outreach_mailboxes WHERE business_id=:b AND mailbox_id=:m', b=A, m=BOX) == 5


def test_campaign_edit_persists_name_with_version_increment(api):
    assert call(api, WRITES[1]).status_code == 200
    assert scalar(api, 'SELECT name FROM outreach_campaigns WHERE id=:i', i=CAMPAIGN) == 'Reviewed pilot'
    assert scalar(api, 'SELECT version FROM outreach_campaigns WHERE id=:i', i=CAMPAIGN) == 2

# Mike's approved addition: written before Stage B implementation. These are
# real failures until the routes exist (no expected-failure marker).
ENROL = ('POST', '/campaigns/{campaign_id}/enrolments', {'prospect_ids': []})
PREPARE = ('POST', '/campaigns/{campaign_id}/prepare', {})


def fresh_prospect(api, index=0):
    from test_outreach_send import add
    from services.outreach_send import suppression_digest
    original = dict(api.data.s.execute(text('SELECT * FROM outreach_prospects WHERE id=:p'), {'p': PROSPECT}).mappings().one())
    email = f'fresh{index}@example.invalid'
    ident = uid(f'fresh-{index}')
    add(api.data.s, 'prospects', **{**original, 'id': ident, 'email': email,
        'email_key': suppression_digest(A, 'email', email)})
    evidence = dict(api.data.s.execute(text('SELECT * FROM outreach_evidence WHERE prospect_id=:p'), {'p': PROSPECT}).mappings().one())
    add(api.data.s, 'evidence', **{**evidence, 'id': uid(f'evidence-{index}'), 'prospect_id': ident,
        'verification_subject_email_key': suppression_digest(A, 'email', email)})
    api.data.s.commit()
    return ident


@pytest.mark.parametrize('spec', [ENROL, PREPARE])
@pytest.mark.parametrize('actor', ['staff', 'admin', 'foreign', 'inactive'])
def test_additions_require_active_owner(api, monkeypatch, spec, actor):
    import auth
    api.actor.user_id = STAFF if actor in ('staff', 'admin') else uid('other-owner')
    if actor == 'inactive':
        api.actor.user_id = OWNER
        api.data.s.execute(text('UPDATE business_members SET is_active=0 WHERE user_id=:u'), {'u': OWNER})
        api.data.s.commit()
    if actor == 'admin':
        monkeypatch.setattr(auth, 'is_platform_admin_user', lambda *_: True)
    body = {'prospect_ids': [PROSPECT]} if spec == ENROL else {}
    assert call(api, spec, body=body).status_code == 403


@pytest.mark.parametrize('spec', [ENROL, PREPARE])
def test_additions_scope_campaign_and_reject_actor_injection(api, spec):
    body = {'prospect_ids': [PROSPECT]} if spec == ENROL else {}
    a = call(api, spec, body=body, campaign=uid('foreign-campaign'))
    b = call(api, spec, body=body, campaign=uid('missing-campaign'))
    assert a.status_code == b.status_code == 404 and a.json() == b.json()
    assert call(api, spec, body={**body, 'business_id': B}).status_code == 422


def test_enrol_is_idempotent_pinned_due_and_never_sends(api):
    from test_outreach_send import NOW
    ident = fresh_prospect(api)
    for _ in range(2):
        response = call(api, ENROL, body={'prospect_ids': [ident, ident]})
        assert response.status_code == 200, response.text
    rows = api.data.s.execute(text('SELECT * FROM outreach_enrolments WHERE prospect_id=:p'), {'p': ident}).mappings().all()
    assert len(rows) == 1
    assert rows[0]['state'] == 'active' and rows[0]['sequence_version'] == 1 and rows[0]['next_step'] == 0
    from services.chase_replies import _parse
    assert _parse(rows[0]['next_due_at']) == NOW
    assert scalar(api, 'SELECT count(*) FROM aria_actions') == 0
    assert scalar(api, 'SELECT count(*) FROM outreach_dispatch_jobs') == 0


def test_enrol_cap_five_and_atomic_refusal(api):
    ids = [fresh_prospect(api, i) for i in range(6)]
    assert call(api, ENROL, body={'prospect_ids': ids}).status_code == 409
    assert scalar(api, "SELECT count(*) FROM outreach_enrolments WHERE business_id=:b AND state='active'", b=A) == 0
    assert call(api, ENROL, body={'prospect_ids': ids[:5]}).status_code == 200
    assert call(api, ENROL, body={'prospect_ids': [ids[5]]}).status_code == 409
    assert call(api, ENROL, body={'prospect_ids': ids[:5]}).status_code == 200


@pytest.mark.parametrize('blocked', ['suppressed', 'ineligible', 'brand', 'audience', 'other_sequence', 'foreign', 'takeover'])
def test_enrol_refuses_unqualified_contacts(api, blocked):
    from test_outreach_send import add
    ident = fresh_prospect(api)
    if blocked == 'suppressed':
        assert call(api, WRITES[6], body={'email': 'fresh0@example.invalid', 'reason': 'manual_opt_out'}).status_code == 200
    elif blocked in ('brand', 'audience'):
        field = 'brand_id' if blocked == 'brand' else 'audience_hash'
        api.data.s.execute(text(f'UPDATE outreach_compliance SET {field}=:v WHERE business_id=:b'), {'v': uid('other-brand') if blocked == 'brand' else 'different', 'b': A})
    elif blocked == 'ineligible':
        api.data.s.execute(text("UPDATE outreach_prospects SET eligibility='review' WHERE id=:p"), {'p': ident})
    elif blocked == 'foreign':
        ident = uid('foreign-prospect')
    else:
        add(api.data.s, 'enrolments', prospect_id=ident, campaign_id=uid('other-campaign'),
            sequence_version=1, state='active' if blocked == 'other_sequence' else 'paused',
            takeover_at=None if blocked == 'other_sequence' else '2026-10-23T10:00:00+00:00')
    api.data.s.commit()
    assert call(api, ENROL, body={'prospect_ids': [ident]}).status_code in (404, 409)


def test_prepare_reuses_card_and_only_owner_hook_can_approve(api):
    from services import aria_actions
    ident = fresh_prospect(api)
    assert call(api, ENROL, body={'prospect_ids': [ident]}).status_code == 200
    first = call(api, PREPARE)
    assert first.status_code == 200, first.text
    assert len(first.json()['raised']) == 1
    second = call(api, PREPARE)
    assert second.status_code == 200
    assert not second.json()['raised'] and len(second.json()['existing']) == 1
    card = first.json()['raised'][0]
    assert second.json()['existing'][0]['id'] == card['id']
    assert scalar(api, 'SELECT count(*) FROM aria_actions') == 1
    assert scalar(api, 'SELECT count(*) FROM outreach_dispatch_jobs') == 0
    assert 'automation' not in card['preview'] and 'raised_by' not in card['preview']
    assert card['status'] == 'proposed'
    with pytest.raises(aria_actions.ActionRefused) as exc:
        aria_actions.approve(api.data.s, api.data.b, card['id'], STAFF, version=card['version'])
    assert exc.value.status_code == 403
    assert not api.data.p.searches and not api.data.p.sends


@pytest.mark.parametrize('blocked', ['paused', 'replied', 'suppressed', 'takeover', 'future', 'campaign', 'template'])
def test_prepare_reports_why_no_card_is_raised(api, blocked):
    ident = fresh_prospect(api)
    assert call(api, ENROL, body={'prospect_ids': [ident]}).status_code == 200
    if blocked in ('paused', 'replied', 'suppressed'):
        api.data.s.execute(text('UPDATE outreach_enrolments SET state=:v WHERE prospect_id=:p'), {'v': blocked, 'p': ident})
    elif blocked in ('takeover', 'future'):
        field = 'takeover_at' if blocked == 'takeover' else 'next_due_at'
        api.data.s.execute(text(f'UPDATE outreach_enrolments SET {field}=:v WHERE prospect_id=:p'), {'v': '2099-01-01T00:00:00+00:00', 'p': ident})
    elif blocked == 'campaign':
        api.data.s.execute(text("UPDATE outreach_campaigns SET status='draft' WHERE id=:c"), {'c': CAMPAIGN})
    else:
        api.data.s.execute(text('UPDATE outreach_sequence_steps SET approved_at=NULL,approved_by=NULL WHERE campaign_id=:c'), {'c': CAMPAIGN})
    api.data.s.commit()
    response = call(api, PREPARE)
    assert response.status_code == 200, response.text
    assert not response.json()['raised']
    assert any(item.get('reason') for item in response.json()['skipped'])
    assert scalar(api, 'SELECT count(*) FROM aria_actions') == 0

@pytest.mark.parametrize('role,expected', [('owner', 200), ('staff', 403), ('admin', 403), ('foreign', 403), ('missing_token', 401)])
def test_real_request_authentication_chain(api, monkeypatch, role, expected):
    import auth
    # Only identity verification and business lookup are local seams. The real
    # bearer dependency, context resolution, access enforcement and owner gate run.
    api.app.dependency_overrides.pop(auth.get_user_business_context)
    user = OWNER if role in ('owner', 'missing_token') else STAFF

    async def verified(token):
        assert token == 'synthetic-jwt'
        return SimpleNamespace(id=user, email='synthetic@example.invalid')

    def business_for_user(user_id, requested_business_id=None):
        assert requested_business_id == A
        if role == 'foreign':
            raise ValueError('FORBIDDEN', 'Not a member')
        return api.data.b

    monkeypatch.setattr(auth, 'verify_supabase_token', verified)
    monkeypatch.setattr(auth, 'get_business_for_user', business_for_user)
    monkeypatch.setattr(auth, 'is_platform_admin_user', lambda *_: role == 'admin')
    headers = {} if role == 'missing_token' else {'Authorization': 'Bearer synthetic-jwt'}
    response = api.client.patch(BASE + '/settings?business_id=' + A, headers=headers, json={'pause_all': True})
    assert response.status_code == expected, response.text


def test_real_access_policy_still_blocks_read_only_safety_writes(api, monkeypatch):
    import auth
    api.app.dependency_overrides.pop(auth.get_user_business_context)

    async def verified(token):
        return SimpleNamespace(id=OWNER, email='owner@example.invalid')

    monkeypatch.setattr(auth, 'verify_supabase_token', verified)
    monkeypatch.setattr(auth, 'get_business_for_user', lambda *a, **k: api.data.b)
    api.data.b.subscription_status = 'unpaid'
    response = api.client.patch(BASE + '/settings', headers={'Authorization': 'Bearer synthetic'}, json={'pause_all': True})
    assert response.status_code == 403


def test_owner_rechecked_after_business_lock(api, monkeypatch):
    from services import outreach_send
    original = outreach_send.lock_business

    def demote(session, bid):
        original(session, bid)
        session.execute(text("UPDATE business_members SET role='staff' WHERE business_id=:b AND user_id=:u"), {'b': A, 'u': OWNER})

    monkeypatch.setattr(outreach_send, 'lock_business', demote)
    assert call(api, WRITES[0]).status_code == 403
    assert scalar(api, 'SELECT count(*) FROM outreach_campaigns WHERE business_id=:b', b=A) == 1


def test_entitlement_rechecked_from_database_under_lock(api):
    api.data.s.execute(text("UPDATE businesses SET plan_tier='starter' WHERE id=:b"), {'b': A})
    api.data.s.commit()
    assert call(api, WRITES[0]).status_code == 403


def test_sequence_partial_failure_rolls_back_every_step(api, monkeypatch):
    from services import outreach_send
    from services.aria_actions import ActionRefused
    original = outreach_send.insert
    count = 0

    def fail_second(session, table, bid, **fields):
        nonlocal count
        if table == 'outreach_sequence_steps':
            count += 1
            if count == 2:
                raise ActionRefused(409, 'Synthetic mid-write failure')
        return original(session, table, bid, **fields)

    monkeypatch.setattr(outreach_send, 'insert', fail_second)
    assert call(api, WRITES[2]).status_code == 409
    assert scalar(api, 'SELECT count(*) FROM outreach_sequence_steps WHERE campaign_id=:c', c=CAMPAIGN) == 3
    assert scalar(api, 'SELECT sequence_version FROM outreach_campaigns WHERE id=:c', c=CAMPAIGN) == 1


def test_failed_proposal_rolls_back_token_and_never_sends(api, monkeypatch):
    from services import aria_actions
    ident = fresh_prospect(api)
    assert call(api, ENROL, body={'prospect_ids': [ident]}).status_code == 200
    original = aria_actions._build

    def fail_after_build(*args, **kwargs):
        original(*args, **kwargs)
        raise aria_actions.ActionRefused(409, 'Synthetic refusal after token insert')

    monkeypatch.setattr(aria_actions, '_build', fail_after_build)
    response = call(api, PREPARE)
    assert response.status_code == 200 and not response.json()['raised']
    assert scalar(api, 'SELECT count(*) FROM outreach_unsubscribe_tokens') == 0
    assert scalar(api, 'SELECT count(*) FROM aria_actions') == 0


@pytest.mark.parametrize('spec', [ENROL, PREPARE])
@pytest.mark.parametrize('denial', ['starter', 'explicit', 'suspended'])
def test_additions_respect_entitlement(api, spec, denial):
    if denial == 'starter':
        api.data.b.plan_tier = 'starter'
    elif denial == 'explicit':
        api.data.b.feature_flags = {'outreach': False}
    else:
        api.data.b.is_active = False
    body = {'prospect_ids': [PROSPECT]} if spec == ENROL else {}
    assert call(api, spec, body=body).status_code == 403
