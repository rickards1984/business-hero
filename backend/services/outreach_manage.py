"""OUT-8 owner controls. Existing storage/locks; never transport or automation."""
import hashlib
import json
from types import SimpleNamespace

from sqlalchemy import text

from auth import assert_feature_access
from services import aria_actions, outreach_replies, outreach_send as send
from services.chase_replies import _address, _parse


def start(session, business, user_id):
    send.require(aria_actions._is_active_owner(session, business, user_id), 'Active owner required', 403)
    assert_feature_access(business, 'outreach', retained_history=True)
    session.rollback()
    send.require(send.rows(session, 'outreach_settings', business.id), 'Outreach setup required', 409)
    outreach_replies._start(session, business.id)
    current = session.execute(text('SELECT plan_tier,feature_flags,subscription_status,is_active,trial_ends_at FROM businesses WHERE id=:b' + (' FOR UPDATE' if send.pg(session) else '')), {'b': str(business.id)}).mappings().first()
    send.require(current, 'Business unavailable', 404)
    fresh = SimpleNamespace(**current)
    fresh.feature_flags = send.loads(fresh.feature_flags) or {}
    fresh.trial_ends_at = _parse(fresh.trial_ends_at)
    assert_feature_access(fresh, 'outreach', retained_history=True)
    send.require(aria_actions._is_active_owner(session, business, user_id, lock=True), 'Active owner required', 403)
    return fresh


def growth(business, fresh):
    assert_feature_access(business, 'outreach')
    assert_feature_access(fresh, 'outreach')


def campaign(session, bid, ident, version=None):
    row = send.one(session, 'outreach_campaigns', bid, ident, True)
    if version is not None:
        send.require(row['version'] == version, 'Campaign version changed; reload')
    return row


def mailbox(session, bid, ident):
    row = send.one(session, 'email_accounts', bid, ident, True)
    send.require(row['provider'] in ('google', 'microsoft') and row['token_ciphertext'], 'Connected supported mailbox required')
    return row


def create_campaign(session, business, user, data):
    fresh = start(session, business, user)
    growth(business, fresh)
    bid = business.id
    send.one(session, 'outreach_brands', bid, data['brand_id'])
    mailbox(session, bid, data['mailbox_id'])
    ident = send.insert(session, 'outreach_campaigns', bid, **data, status='draft', version=1,
        sequence_version=1, timezone='Europe/London', target_rules={}, target_hash=hashlib.sha256(b'{}').hexdigest())
    session.commit()
    return {'id': ident, 'version': 1}


def edit_campaign(session, business, user, ident, data):
    fresh = start(session, business, user)
    growth(business, fresh)
    c = campaign(session, business.id, ident, data.pop('version'))
    if 'mailbox_id' in data:
        mailbox(session, business.id, data['mailbox_id'])
        if str(c['mailbox_id']) != data['mailbox_id']:
            send.require(not send.rows(session, 'outreach_messages', business.id, 'AND campaign_id=:c', {'c': ident}) and
                not send.rows(session, 'outreach_batch_reviews', business.id, 'AND campaign_id=:c', {'c': ident}),
                'Sender cannot change after dispatch or batch review history')
    changes = {k: v for k, v in data.items() if str(c[k]) != str(v)}
    if changes:
        send.update(session, 'outreach_campaigns', business.id, ident, **changes,
            version=c['version'] + 1, status='paused', first_batch_review_id=None, updated_at=send.now())
    session.commit()
    return {'id': ident, 'version': c['version'] + bool(changes)}


def sequence(session, business, user, ident, data):
    fresh = start(session, business, user)
    growth(business, fresh)
    c = campaign(session, business.id, ident, data['version'])
    version = c['sequence_version'] + 1
    for step in data['steps']:
        envelope = json.dumps(dict(schema_version=1, subject=step['subject'], body=step['body']))
        send.insert(session, 'outreach_sequence_steps', business.id, campaign_id=ident,
            sequence_version=version, ordinal=step['ordinal'], delay_business_days=step['delay_business_days'],
            template_text=envelope, template_hash=hashlib.sha256(envelope.encode()).hexdigest(), allowed_variables=[])
    send.update(session, 'outreach_campaigns', business.id, ident, sequence_version=version,
        version=c['version'] + 1, status='paused', first_batch_review_id=None, updated_at=send.now())
    session.commit()
    return {'id': ident, 'version': c['version'] + 1, 'sequence_version': version}


def approve_templates(session, business, user, ident, data):
    fresh = start(session, business, user)
    growth(business, fresh)
    c = campaign(session, business.id, ident, data['version'])
    send.require(c['sequence_version'] == data['sequence_version'], 'Sequence version changed; reload')
    steps = send.rows(session, 'outreach_sequence_steps', business.id,
        'AND campaign_id=:c AND sequence_version=:v ORDER BY ordinal', {'c': ident, 'v': c['sequence_version']}, True)
    send.require(len(steps) == 3 and [s['ordinal'] for s in steps] == [0, 1, 2], 'Three sequence steps required')
    for step in steps:
        send.require(hashlib.sha256(step['template_text'].encode()).hexdigest() == step['template_hash'], 'Template hash changed')
        if not step['approved_at']:
            send.update(session, 'outreach_sequence_steps', business.id, step['id'], approved_by=str(user), approved_at=send.now())
    # Ready means approved templates only; no first-batch permission or send.
    send.update(session, 'outreach_campaigns', business.id, ident, status='ready', updated_at=send.now())
    session.commit()
    return {'id': ident, 'version': c['version'], 'sequence_version': c['sequence_version']}


def settings(session, business, user, data):
    fresh = start(session, business, user)
    row = send.one(session, 'outreach_settings', business.id, lock=True)
    safety = all((key == 'pause_all' and value is True) or
        (key == 'owner_cc_default' and value is False) or
        (key == 'business_daily_cap' and value <= row[key]) for key, value in data.items())
    if not safety:
        growth(business, fresh)
    send.update(session, 'outreach_settings', business.id, row['id'], **data, updated_at=send.now())
    session.commit()
    return {'id': str(row['id'])}


def mailbox_cap(session, business, user, ident, data):
    fresh = start(session, business, user)
    send.one(session, 'email_accounts', business.id, ident, True)
    found = send.rows(session, 'outreach_mailboxes', business.id, 'AND mailbox_id=:m', {'m': ident}, True)
    send.require(len(found) == 1, 'Outreach record unavailable', 404)
    row = found[0]
    if data['daily_cap'] > row['daily_cap']:
        growth(business, fresh)
    send.update(session, 'outreach_mailboxes', business.id, row['id'], **data, updated_at=send.now())
    session.commit()
    return {'mailbox_id': ident, **data}


def suppress(session, business, user, data):
    start(session, business, user)
    bid, moment = business.id, send.now()
    email = _address(data['email'])
    digest = send.suppression_digest(bid, 'email', email)
    found = send.rows(session, 'outreach_suppressions', bid, "AND key_type='email' AND key_digest=:d", {'d': digest})
    ident = str(found[0]['id']) if found else send.insert(session, 'outreach_suppressions', bid,
        key_type='email', key_digest=digest, digest_version=1, reason='manual_opt_out', suppressed_at=moment)
    for prospect in send.rows(session, 'outreach_prospects', bid, 'AND (email_key=:d OR lower(trim(email))=:e)', {'d': digest, 'e': email}, True):
        outreach_replies._stop(session, bid, prospect['id'], 'suppressed', 'manual_opt_out', moment)
    session.commit()
    return {'id': ident, 'message': 'Suppressed across this business. Already dispatched mail cannot be recalled.'}


def resolve(session, business, user, ident, data):
    start(session, business, user)
    reply = send.one(session, 'outreach_replies', business.id, ident, True)
    outreach_replies._stop(session, business.id, reply['prospect_id'], 'paused', 'Owner handled reply', send.now(), takeover=True)
    send.update(session, 'outreach_replies', business.id, ident, resolution='resolved', updated_at=send.now())
    session.commit()
    return {'id': ident, 'resolution': 'resolved'}


def qualified(session, bid, c, p):
    """Stored compliance binds both brand and audience; a score is not consent."""
    moment = send.now()
    send.require(p['eligibility'] == 'eligible' and p['subscriber_type'] == 'corporate' and p['lawful_basis'] == 'legitimate_interests', 'Prospect is not eligible')
    send.require(p['email'] and p['email_key'] == send.suppression_digest(bid, 'email', p['email']), 'Address verification binding is stale')
    send.require(_parse(p['retention_due_at']) and _parse(p['retention_due_at']) > moment, 'Prospect retention expired')
    send.require(not send.rows(session, 'outreach_suppressions', bid,
        "AND ((key_type='email' AND key_digest=:e) OR (key_type='domain' AND key_digest=:d))",
        {'e': p['email_key'], 'd': send.suppression_digest(bid, 'domain', _address(p['email']).split('@')[-1])}), 'Prospect is suppressed')
    send.require(p['lia_id'], 'Approved audience required')
    lia = send.one(session, 'outreach_compliance', bid, p['lia_id'])
    send.require(str(lia['brand_id']) == str(c['brand_id']) and lia['audience_hash'] == c['target_hash'], 'Prospect brand or audience does not match')
    send.require(lia['decision'] == 'approved' and lia['reviewer'] and _parse(lia['reviewed_at']) and
        _parse(lia['review_due_at']) and _parse(lia['reviewed_at']) <= moment < _parse(lia['review_due_at']), 'Audience approval unavailable')


def enrol(session, business, user, ident, data):
    fresh = start(session, business, user)
    growth(business, fresh)
    c = campaign(session, business.id, ident)
    send.require(c['status'] != 'completed', 'Campaign completed')
    existing, pending = [], []
    for pid in dict.fromkeys(data['prospect_ids']):
        p = send.one(session, 'outreach_prospects', business.id, pid, True)
        qualified(session, business.id, c, p)
        enrolments = send.rows(session, 'outreach_enrolments', business.id, 'AND prospect_id=:p', {'p': pid}, True)
        same = [e for e in enrolments if str(e['campaign_id']) == ident]
        send.require(not any(e['takeover_at'] or e['state'] in ('paused', 'replied', 'suppressed') for e in enrolments), 'Prospect is stopped or taken over')
        send.require(not any(str(e['campaign_id']) != ident and e['state'] in ('pending', 'active') for e in enrolments), 'Prospect already in another active sequence')
        # Historic contact in another currently active campaign is also a block.
        contacted = session.execute(text("SELECT 1 FROM outreach_messages m JOIN outreach_campaigns c ON c.business_id=m.business_id AND c.id=m.campaign_id WHERE m.business_id=:b AND m.prospect_id=:p AND m.campaign_id<>:c AND m.direction='outbound' AND m.state IN ('accepted','unknown') AND c.status IN ('ready','running') LIMIT 1"), {'b': str(business.id), 'p': pid, 'c': ident}).first()
        send.require(not contacted, 'Prospect contacted in another active campaign')
        if same:
            send.require(same[0]['state'] == 'active' and same[0]['sequence_version'] == c['sequence_version'], 'Existing enrolment cannot be restarted')
            existing.append({'id': str(same[0]['id']), 'prospect_id': pid})
        else:
            pending.append(pid)
    active = send.rows(session, 'outreach_enrolments', business.id, "AND campaign_id=:c AND state IN ('pending','active')", {'c': ident})
    from services.outreach_research import pilot_enrolments
    limit = pilot_enrolments()   # one setting for every enrolment path (Codex OUT-19 D review 1)
    send.require(not limit or len(active) + len(pending) <= limit,
                 f'Pilot limit: {limit} active enrolments per campaign')
    for pid in pending:
        eid = send.insert(session, 'outreach_enrolments', business.id, prospect_id=pid, campaign_id=ident,
            sequence_version=c['sequence_version'], state='active', next_step=0, next_due_at=send.now())
        existing.append({'id': eid, 'prospect_id': pid})
    session.commit()
    return {'items': existing}


def prepare(session, business, user, ident, data):
    result = {'raised': [], 'existing': [], 'skipped': []}
    fresh = start(session, business, user)
    growth(business, fresh)
    campaign(session, business.id, ident)
    enrolments = send.rows(session, 'outreach_enrolments', business.id, 'AND campaign_id=:c ORDER BY id', {'c': ident})
    ids = [str(e['id']) for e in enrolments]
    session.rollback()
    # propose owns commit/rollback: acquire and recheck ALL authority and state
    # for each card. The shared business lock spans deduplication through commit.
    for eid in ids:
        fresh = start(session, business, user)
        growth(business, fresh)
        c = campaign(session, business.id, ident)
        e = send.one(session, 'outreach_enrolments', business.id, eid, True)
        try:
            send.require(not send.one(session, 'outreach_settings', business.id)['pause_all'], 'Outreach paused')
            send.require(c['status'] in ('ready', 'running'), 'Campaign is not approved')
            send.require(e['state'] == 'active' and not e['takeover_at'], 'Enrolment stopped or taken over')
            send.require(_parse(e['next_due_at']) and _parse(e['next_due_at']) <= send.now(), 'Step is not due')
            send.require(e['sequence_version'] == c['sequence_version'], 'Enrolment sequence version is stale')
            p = send.one(session, 'outreach_prospects', business.id, e['prospect_id'], True)
            qualified(session, business.id, c, p)
            cards = send.rows(session, 'aria_actions', business.id, "AND action_type='send_outreach' AND status IN ('proposed','executing')", lock=True)
            card = next((a for a in cards if str(send.loads(a['payload']).get('enrolment_id')) == eid), None)
            if card:
                payload = send.loads(card['payload'])
                result['existing'].append({'id': str(card['id']), 'status': card['status'], 'preview': payload, 'version': aria_actions.version_of(payload)})
                session.rollback()
                continue
            steps = send.rows(session, 'outreach_sequence_steps', business.id, 'AND campaign_id=:c AND sequence_version=:v ORDER BY ordinal', {'c': ident, 'v': c['sequence_version']})
            send.require(len(steps) == 3 and all(s['approved_by'] and s['approved_at'] for s in steps), 'Templates are not approved')
            step = next((s for s in steps if s['ordinal'] == e['next_step']), None)
            send.require(step, 'Step unavailable')
            proposal = aria_actions.propose(session, business, user, 'send_outreach',
                {'campaign_id': ident, 'enrolment_id': eid, 'step_id': str(step['id'])})
            if 'proposal' in proposal:
                result['raised'].append(proposal['proposal'])
            else:
                result['skipped'].append({'enrolment_id': eid, 'reason': proposal['error']})
        except aria_actions.ActionRefused as exc:
            session.rollback()
            result['skipped'].append({'enrolment_id': eid, 'reason': exc.detail})
    session.rollback()
    return result
