"""OUT-6 owner-approved sending. No scheduler, retry or default-mailbox path.

Integration: build_payload -> persist card -> search_before_claim (ends its
read transaction before provider I/O) -> prepare_claim -> action CAS + commit
-> dispatch, on the SAME Session. Claim never commits or calls a provider.
A session-local, single-use dispatch permit deliberately cannot survive a
restart: durable unresolved claims are unknown, never replayable jobs.
"""
import hashlib
import hmac
import json
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import text

from services.aria_actions import ActionRefused, sign_off, version_of
from services.chase_replies import _address, _parse, _store
from services import metering

LONDON = ZoneInfo('Europe/London')


def now():
    return datetime.now(timezone.utc)


def get_provider_for_account(account):
    from app.email.service import get_provider_for_account as factory
    return factory(account)


def require(condition, detail='Outreach is not currently eligible', code=409):
    if not condition:
        raise ActionRefused(code, detail)


def loads(value):
    return json.loads(value) if isinstance(value, str) else value


def pg(session):
    return session.get_bind().dialect.name == 'postgresql'


def rows(session, table, bid, where='', params=None, lock=False):
    return [dict(r) for r in session.execute(text(
        f'SELECT * FROM {table} WHERE business_id=:bid ' + where +
        (' FOR UPDATE' if lock and pg(session) else '')),
        dict(params or {}, bid=str(bid))).mappings()]


def one(session, table, bid, ident=None, lock=False):
    found = rows(session, table, bid, 'AND id=:id' if ident else '',
                 {'id': str(ident)} if ident else {}, lock)
    require(len(found) == 1, 'Outreach record unavailable', 404)
    return found[0]


def insert(session, table, bid, **fields):
    fields = dict(id=str(uuid.uuid4()), business_id=str(bid), created_at=now(),
                  updated_at=now()) | fields
    expressions = []
    for key, value in fields.items():
        if isinstance(value, (dict, list)):
            array = table == 'outreach_messages' and key in ('to_emails', 'cc_emails')
            if not (array and pg(session)):
                fields[key] = json.dumps(value)
            expressions.append(f'CAST(:{key} AS jsonb)' if pg(session) and not array else f':{key}')
        else:
            expressions.append(f':{key}')
    session.execute(text(f"INSERT INTO {table} ({','.join(fields)}) VALUES ({','.join(expressions)})"), fields)
    return fields['id']


def update(session, table, bid, ident, **fields):
    session.execute(text(f"UPDATE {table} SET " + ','.join(f'{k}=:{k}' for k in fields) +
                         ' WHERE business_id=:bid AND id=:id'),
                    dict(fields, bid=str(bid), id=str(ident)))


def suppression_digest(business_id, kind, value):
    """Version 1 tenant-keyed HMAC; missing configuration fails closed."""
    secret = os.environ.get('OUTREACH_SUPPRESSION_SECRET', '')
    require(len(secret) >= 32, 'Outreach suppression key is not configured')
    normalized = _address(value) if kind == 'email' else str(value).strip().lower()
    return hmac.new(secret.encode(), f'v1:{business_id}:{kind}:{normalized}'.encode(), hashlib.sha256).hexdigest()


def lock_business(session, bid):
    # Also used by unsubscribe. External pause/suppression writers must follow
    # this order: business_settings -> outreach_settings -> meter -> daily ->
    # mailbox/contact/enrolment/campaign/step/evidence -> action.
    one(session, 'business_settings', bid, lock=True)
    one(session, 'outreach_settings', bid, lock=True)


def _records(session, business, args, lock=False):
    bid = str(business.id)
    c = one(session, 'outreach_campaigns', bid, args['campaign_id'])
    e = one(session, 'outreach_enrolments', bid, args['enrolment_id'])
    s = one(session, 'outreach_sequence_steps', bid, args['step_id'])
    p = one(session, 'outreach_prospects', bid, e['prospect_id'])
    b = one(session, 'outreach_brands', bid, c['brand_id'])
    a = one(session, 'email_accounts', bid, c['mailbox_id'])
    if lock:
        # Preliminary scoped reads only discover IDs. Re-read after every
        # lock; all cooperating writers first take lock_business.
        a = one(session, 'email_accounts', bid, a['id'], True)
        rows(session, 'outreach_mailboxes', bid, 'AND mailbox_id=:m', {'m': str(a['id'])}, True)
        p = one(session, 'outreach_prospects', bid, p['id'], True)
        e = one(session, 'outreach_enrolments', bid, e['id'], True)
        c = one(session, 'outreach_campaigns', bid, c['id'], True)
        s = one(session, 'outreach_sequence_steps', bid, s['id'], True)
        b = one(session, 'outreach_brands', bid, b['id'], True)
    require(str(e['campaign_id']) == str(c['id']) == str(s['campaign_id']))
    require(str(e['prospect_id']) == str(p['id']) and str(c['brand_id']) == str(b['id']) and str(c['mailbox_id']) == str(a['id']))
    require(e['sequence_version'] == c['sequence_version'] == s['sequence_version'])
    require(a['provider'] in ('google', 'microsoft') and a['token_ciphertext'], 'Campaign mailbox unavailable')
    require(_address(p['email']) and _address(p['email']) != _address(a['email_address']))
    return c, e, s, p, b, a


def _previous(session, bid, c, p):
    history = rows(session, 'outreach_messages', bid,
                   "AND prospect_id=:p AND campaign_id=:c AND state='accepted' AND direction='outbound' "
                   'ORDER BY accepted_at DESC', {'p': str(p['id']), 'c': str(c['id'])})
    return history[0] if history else None


def _binding(c, e, s, p, b, a):
    return dict(campaign_id=str(c['id']), enrolment_id=str(e['id']), step_id=str(s['id']),
                prospect_id=str(p['id']), brand_id=str(b['id']), mailbox_id=str(a['id']),
                campaign_version=c['version'], sequence_version=c['sequence_version'],
                brand_version=b['version'], target_hash=c['target_hash'], template_hash=s['template_hash'],
                email_key=p['email_key'], to=_address(p['email']), provider=a['provider'],
                from_email=_address(a['email_address']), sender_identity=b['sender_identity'],
                privacy_url=b['privacy_url'], ordinal=s['ordinal'],
                idempotency_key=hashlib.sha256(f"{c['business_id']}:{e['id']}:{e['sequence_version']}:{s['id']}".encode()).hexdigest())


def _safe_header(value):
    require(isinstance(value, str) and value and '\r' not in value and '\n' not in value,
            'Invalid outreach header', 422)
    return value


def build_payload(session, business, args, owner_name=None, timezone=None):
    require(set(args) == {'campaign_id', 'enrolment_id', 'step_id'}, 'Only campaign, enrolment and step IDs are accepted', 422)
    c, e, s, p, b, a = _records(session, business, args)
    require(s['approved_by'] and s['approved_at'])
    require(hashlib.sha256(s['template_text'].encode()).hexdigest() == s['template_hash'])
    try:
        template = loads(s['template_text'])
        require(template['schema_version'] == 1 and set(template) == {'schema_version', 'subject', 'body'})
        require(isinstance(template['body'], str) and 0 < len(template['body']) <= 20000)
    except (ValueError, KeyError, TypeError):
        raise ActionRefused(422, 'Approved template envelope unavailable') from None
    settings = one(session, 'outreach_settings', business.id)
    cc = [_safe_header(settings['owner_cc_address'])] if settings['owner_cc_default'] else []
    source = rows(session, 'outreach_evidence', business.id, 'AND prospect_id=:p AND source_url IS NOT NULL ORDER BY fetched_at DESC', {'p': str(p['id'])})
    require(source and urlparse(b['privacy_url']).scheme == 'https')
    base = unsubscribe_base()
    parsed = urlparse(base)
    # A fragment never reaches the server, so the token after it would be lost (Codex OUT-16 review 1).
    require(parsed.scheme == 'https' and parsed.netloc and not parsed.query and not parsed.fragment
            and '#' not in base and '?' not in base, 'Outreach unsubscribe URL is not configured')
    token = secrets.token_urlsafe(32)
    link = base.rstrip('/') + '/' + token
    insert(session, 'outreach_unsubscribe_tokens', business.id,
           token_digest=hashlib.sha256(token.encode()).hexdigest(), prospect_key_digest=p['email_key'],
           digest_version=1, issued_at=now())
    payload = _binding(c, e, s, p, b, a)
    payload.update(source_url=source[0]['source_url'], subject=_safe_header(template['subject']), body=template['body'], cc=cc,
                   sign_off=sign_off('Aria', owner_name, b['name']),
                   footer=f"Sent on behalf of {b['sender_identity']}. Source: {source[0]['source_url']}\nPrivacy: {b['privacy_url']}\nUnsubscribe: {link}",
                   headers={'List-Unsubscribe': f'<{link}>', 'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click'},
                   rfc_message_id=f"<{uuid.uuid4()}@{_address(a['email_address']).split('@')[-1]}>",
                   in_reply_to=None, references=[], provider_thread_id=None,
                   expires_at=(now() + timedelta(hours=72)).isoformat(),
                   sending_window='Europe/London weekdays 09:00-17:00')
    if s['ordinal']:
        prev = _previous(session, business.id, c, p)
        require(prev and prev['provider_message_id'] and prev['provider_thread_id'] and prev['rfc_message_id'] and str(prev['mailbox_id']) == str(a['id']),
                'Previous acceptance needs mailbox/thread correlation')
        # Gmail threads a follow-up only when its subject matches the conversation's,
        # and recipients' clients group by it too: a follow-up is "Re:" the email it
        # follows, whatever subject the step's template carries (Codex OUT-16 review 1),
        # never shortened: the MIME writer folds a long Subject line (review 2).
        earlier = prev['subject'] or ''
        payload.update(subject=_safe_header(earlier if earlier[:3].lower() == 're:' else 'Re: ' + earlier),
                       in_reply_to=prev['rfc_message_id'], references=[prev['rfc_message_id']],
                       provider_thread_id=prev['provider_thread_id'])
    return payload


def _binding_matches(payload, binding):
    # The reply operation belongs to the permanent slot/generation, not step.
    return all(payload.get(k) == v for k, v in binding.items()
               if not (payload.get('action_kind') == 'reply_outreach' and k == 'idempotency_key'))


def recheck_inbound(session, bid, payload, since, allowed_inbound=None):
    own = {_address(r['email_address']) for r in rows(session, 'email_accounts', bid)}
    # SQL sender filter fixes OUT-6's whole-inbox materialization backlog.
    inbox = rows(session, 'email_messages', bid,
        'AND received_at>=:since AND lower(from_email) LIKE :sender_hint',
        {'since': since, 'sender_hint': '%' + payload['to'] + '%'})
    require(not any(str(r['id']) != allowed_inbound and _address(r['from_email']) == payload['to']
                    and _address(r['from_email']) not in own for r in inbox), 'Recipient has replied')


def search_before_claim(session, business, *, action_id, payload):
    """Read-only provider search outside locks, AUTO-2 storage before claim.

    Same-session receipt binds the search to the immutable card; callers cannot
    supply a timestamp to bypass it. No uncommitted caller writes are allowed.
    """
    require(not session.new and not session.dirty and not session.deleted)
    c, e, s, p, b, a = _records(session, business, payload)
    require(_binding_matches(payload, _binding(c, e, s, p, b, a)))
    prev = _previous(session, business.id, c, p)
    since = _parse(prev['accepted_at']) if prev else _parse(p['captured_at'])
    require(since is not None)
    account = SimpleNamespace(**a)
    session.rollback()  # end read transaction; no DB locks during search
    started = now()
    try:
        provider = get_provider_for_account(account)
        require(callable(getattr(provider, 'send_outreach', None)), 'Outreach transport adapter unavailable')
        found = provider.search_from(account=account, senders=[payload['to']], since=since)
        require(isinstance(found, list), 'Incomplete outreach reply search')
        _store(session, business, account.id, found)
    except Exception:
        session.rollback()
        raise ActionRefused(409, 'Campaign mailbox reply search unavailable') from None
    session.info.setdefault('outreach_search', {})[str(action_id)] = (version_of(payload), started, since)
    return started


def _business_days(moment, count):
    local = moment.astimezone(LONDON)
    while count:
        local += timedelta(days=1)
        if local.weekday() < 5:
            count -= 1
    return local.astimezone(timezone.utc)


def prepare_claim(session, business, *, action_id, payload, user_id, version, moment, authority=None):
    """Recheck and reserve inside caller's transaction. NEVER I/O or commit.

    OUT-11: `authority` is the owner's standing permission for an automatic
    send (validated by the caller and re-read under lock after this call).
    Only a sequence email may use it, never a reply; every check below
    applies exactly as for a tapped card."""
    bid = str(business.id)
    automatic = payload.get('automation') == 'outreach_autopilot'
    require(version and version == version_of(payload), 'Owner/version required', 403)
    if automatic:
        require(user_id is None and isinstance(authority, dict) and authority.get('granted_by')
                and payload.get('action_kind') != 'reply_outreach', 'Standing permission required', 403)
    else:
        require(user_id and 'automation' not in payload, 'Manual approval required', 403)
    require('authority_snapshot' not in payload, 'Manual approval required', 403)
    for value in (payload['subject'], payload['to'], payload['from_email'], *payload['cc']):
        _safe_header(value)
    require(set(payload['headers']) == {'List-Unsubscribe', 'List-Unsubscribe-Post'})
    require(payload['headers']['List-Unsubscribe-Post'] == 'List-Unsubscribe=One-Click')
    link = _safe_header(payload['headers']['List-Unsubscribe']).strip('<>')
    require(urlparse(link).scheme == 'https' and link in payload['footer'])
    token_digest = hashlib.sha256(link.rsplit('/', 1)[-1].encode()).hexdigest()
    require(rows(session, 'outreach_unsubscribe_tokens', bid,
                 'AND token_digest=:d AND prospect_key_digest=:p AND revoked_at IS NULL',
                 {'d': token_digest, 'p': payload['email_key']}), 'Unsubscribe token unavailable')
    receipt = session.info.get('outreach_search', {}).pop(str(action_id), None)
    require(receipt and receipt[0] == version and timedelta(0) <= moment - receipt[1] <= timedelta(minutes=2),
            'Fresh campaign mailbox search required')
    lock_business(session, bid)
    from auth import assert_feature_access
    current = session.execute(text('SELECT plan_tier,feature_flags,subscription_status,is_active,trial_ends_at FROM businesses WHERE id=:b' + (' FOR UPDATE' if pg(session) else '')), {'b': bid}).mappings().first()
    require(current, 'Business unavailable', 404)
    current = SimpleNamespace(**current)
    current.feature_flags = loads(current.feature_flags) or {}
    current.trial_ends_at = _parse(current.trial_ends_at)
    try:
        assert_feature_access(current, 'outreach')
    except HTTPException:
        raise ActionRefused(403, 'Outreach entitlement unavailable') from None
    metering.lock_outreach_usage(session, business, moment=moment, mailbox_id=payload['mailbox_id'])
    c, e, s, p, b, a = _records(session, business, payload, lock=True)
    require(_binding_matches(payload, _binding(c, e, s, p, b, a)), 'Outreach preview is stale')
    settings = one(session, 'outreach_settings', bid, lock=True)
    lia = one(session, 'outreach_compliance', bid, p['lia_id'], True)
    evidence = rows(session, 'outreach_evidence', bid, 'AND prospect_id=:p', {'p': str(p['id'])}, True)
    checked_at = max(moment, now())
    require(checked_at.astimezone(LONDON).date() == moment.astimezone(LONDON).date(), 'Sending period changed; search again')
    require(checked_at - receipt[1] <= timedelta(minutes=2), 'Reply search expired while waiting for locks')
    moment = checked_at
    require(not settings['pause_all'] and c['status'] in ('ready', 'running'))
    require(c['timezone'] == settings['timezone'] == 'Europe/London')
    is_reply = payload.get('action_kind') == 'reply_outreach'
    if is_reply:
        from services.outreach_replies import validate_claim
        allowed_inbound = validate_claim(session, business, payload, action_id, moment)
        require(e['state'] == 'replied' and not e['takeover_at'])
    else:
        allowed_inbound = None
        require(e['state'] == 'active' and not e['takeover_at'] and e['next_step'] == s['ordinal'])
        require(_parse(e['next_due_at']) and _parse(e['next_due_at']) <= moment)
    require(p['email_key'] == suppression_digest(bid, 'email', p['email']), 'Address verification binding is stale')
    require(p['eligibility'] == 'eligible' and p['subscriber_type'] == 'corporate' and p['lawful_basis'] == 'legitimate_interests')
    require(_parse(p['retention_due_at']) and moment < _parse(p['retention_due_at']))
    require(p['notice_provided_at'] or (_parse(p['notice_due_at']) and moment < _parse(p['notice_due_at'])))
    require(lia['decision'] == 'approved' and lia['reviewer'] and lia['reviewed_at'] and
            _parse(lia['reviewed_at']) <= moment and str(lia['brand_id']) == str(b['id']) and lia['audience_hash'] == c['target_hash'] and
            _parse(lia['review_due_at']) and moment < _parse(lia['review_due_at']))
    require(any(v['source_url'] == payload['source_url'] for v in evidence), 'Source evidence changed')
    require(any(v['verification_status'] == 'valid' and v['verification_subject_email_key'] == p['email_key'] and
                _parse(v['verified_at']) and _parse(v['verified_at']) <= moment < _parse(v['expires_at']) and
                v['source_url'] and not loads(v['flags'] or '[]') for v in evidence))
    require(s['approved_by'] and s['approved_at'] and hashlib.sha256(s['template_text'].encode()).hexdigest() == s['template_hash'])
    require(payload['cc'] == ([settings['owner_cc_address']] if settings['owner_cc_default'] else []))
    for kind, value in (('email', p['email']), ('domain', _address(p['email']).split('@')[-1])):
        digest = suppression_digest(bid, kind, value)
        blocked = rows(session, 'outreach_suppressions', bid, 'AND key_type=:k AND (key_digest=:d OR key_digest=:stored)',
                       {'k': kind, 'd': digest, 'stored': p['email_key'] if kind == 'email' else digest})
        require(not blocked, 'Recipient is suppressed')
    if not is_reply:
        require(not rows(session, 'outreach_replies', bid, 'AND prospect_id=:p', {'p': str(p['id'])}), 'Recipient has replied')
    recheck_inbound(session, bid, payload, receipt[2], allowed_inbound)
    current_moment = max(moment, now())
    require(current_moment.astimezone(LONDON).date() == moment.astimezone(LONDON).date(), 'Sending period changed; search again')
    moment = current_moment
    local = moment.astimezone(LONDON)
    require(local.weekday() < 5 and 9 <= local.hour < 17, 'Outside outreach sending window')
    require(moment < _parse(payload['expires_at']))
    if p['last_contact_at'] and not is_reply:
        require(moment >= _parse(p['last_contact_at']) + timedelta(days=7), 'Contact spacing')
    if s['ordinal'] and not is_reply:
        prev = _previous(session, bid, c, p)
        require(prev and prev['provider_message_id'] and prev['provider_thread_id'] == payload['provider_thread_id'] and
                prev['rfc_message_id'] == payload['in_reply_to'] and str(prev['mailbox_id']) == payload['mailbox_id'])
        require(moment >= _business_days(_parse(prev['accepted_at']), (5, 7)[s['ordinal'] - 1]))
    require(not rows(session, 'outreach_messages', bid, "AND prospect_id=:p AND direction='outbound' AND state IN ('claimed','unknown')", {'p': str(p['id'])}), 'Earlier contact outcome unresolved')
    require(not rows(session, 'outreach_dispatch_jobs', bid, 'AND logical_key=:k', {'k': payload['idempotency_key']}), 'Operation already claimed')
    message_id = insert(session, 'outreach_messages', bid, prospect_id=p['id'], campaign_id=c['id'],
                        enrolment_id=e['id'], step_id=s['id'], sequence_version=s['sequence_version'],
                        mailbox_id=a['id'], action_id=action_id, kind='bespoke' if is_reply else ('followup' if s['ordinal'] else 'initial'),
                        origin='live', direction='outbound', to_emails=[payload['to']], cc_emails=payload['cc'],
                        subject=payload['subject'], body='\n\n'.join(payload[k] for k in ('body', 'sign_off', 'footer')),
                        payload_hash=version, payload_version=1, state='claimed', provider=a['provider'],
                        rfc_message_id=payload['rfc_message_id'], idempotency_key=payload['idempotency_key'],
                        authority_snapshot=({'automation': 'outreach_autopilot', 'granted_by': str(authority['granted_by']),
                                             'granted_at': authority.get('granted_at'), 'version': version,
                                             'search_at': receipt[1].isoformat()} if automatic else
                                            {'user_id': str(user_id), 'version': version, 'search_at': receipt[1].isoformat()}))
    metering.reserve_outreach_usage(session, business, operation_key=payload['idempotency_key'],
                                   mailbox_id=str(a['id']), prospect_id=str(p['id']), message_id=message_id, moment=moment)
    if is_reply:
        reply = one(session, 'outreach_replies', bid, payload['reply_id'])
        update(session, 'outreach_messages', bid, message_id, reply_target_id=reply['matched_message_id'])
        # 038 stores the full SHA-256; the card version is its first 16 characters.
        full_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'),
                                              default=str).encode()).hexdigest()
        require(full_hash.startswith(version))
        update(session, 'outreach_reply_slots', bid, payload['slot_id'], message_id=message_id,
               payload_hash=full_hash)
    action = one(session, 'aria_actions', bid, action_id, True)
    require(action['action_type'] == ('reply_outreach' if is_reply else 'send_outreach') and action['status'] == 'proposed' and
            loads(action['payload']) == payload and moment < _parse(action['expires_at']))
    insert(session, 'outreach_dispatch_jobs', bid, message_id=message_id, enrolment_id=e['id'], step_id=s['id'],
           logical_key=payload['idempotency_key'], status='claimed', due_at=moment, action_id=action_id)
    session.info.setdefault('outreach_dispatch', {})[str(action_id)] = (version, receipt[1])


def dispatch(session, business, *, action_id, payload):
    """Post-commit only, at most one adapter attempt. No recovery resend."""
    bid = str(business.id)
    permit = session.info.get('outreach_dispatch', {}).pop(str(action_id), None)
    require(permit and permit[0] == version_of(payload), 'No fresh dispatch authority')
    # A caller must have committed the claim. A live transaction here could
    # accidentally commit a failed action CAS: refuse rather than rescue it.
    require(not session.in_transaction(), 'Dispatch requires committed claim')
    action = one(session, 'aria_actions', bid, action_id)
    require(action['status'] == 'executing' and loads(action['payload']) == payload)
    job = rows(session, 'outreach_dispatch_jobs', bid, 'AND action_id=:a', {'a': str(action_id)})
    require(len(job) == 1 and job[0]['status'] == 'claimed' and not job[0]['dispatch_started_at'])
    at = now()
    lock_business(session, bid)
    blocked = False
    try:
        prospect = one(session, 'outreach_prospects', bid, payload['prospect_id'])
        for kind, value in (('email', prospect['email']), ('domain', _address(prospect['email']).split('@')[-1])):
            require(not rows(session, 'outreach_suppressions', bid, 'AND key_type=:k AND key_digest=:d',
                             {'k': kind, 'd': suppression_digest(bid, kind, value)}))
        require(not one(session, 'outreach_settings', bid)['pause_all'])
        boxes = rows(session, 'outreach_mailboxes', bid, 'AND mailbox_id=:m', {'m': payload['mailbox_id']})
        require(len(boxes) == 1 and boxes[0]['enabled'] and boxes[0]['health_status'] == 'pass')
        enrolment = one(session, 'outreach_enrolments', bid, payload['enrolment_id'])
        require(not enrolment['takeover_at'] and enrolment['state'] == ('replied' if payload.get('action_kind') == 'reply_outreach' else 'active'))
        allowed = None
        if payload.get('action_kind') == 'reply_outreach':
            reply = one(session, 'outreach_replies', bid, payload['reply_id'])
            allowed = str(reply['inbound_email_id'])
            from services.outreach_replies import _eligible, _facts, _grounded
            require(_eligible(session, bid, reply))
            facts = _facts(session, bid, payload['brand_id'], at)
            require(facts == payload['knowledge'] and _grounded({'body': payload['body'], 'knowledge_refs': payload['knowledge_refs']}, facts))
        recheck_inbound(session, bid, payload, _parse(prospect['captured_at']), allowed)
    except ActionRefused:
        blocked = True
    claimed = session.execute(text("UPDATE outreach_dispatch_jobs SET dispatch_started_at=:at WHERE business_id=:b AND id=:id AND status='claimed' AND dispatch_started_at IS NULL"),
                              {'at': at, 'b': bid, 'id': job[0]['id']})
    require(claimed.rowcount == 1)
    account = SimpleNamespace(**one(session, 'email_accounts', bid, payload['mailbox_id']))
    require(account.provider == payload['provider'] and _address(account.email_address) == payload['from_email'] and account.token_ciphertext, 'Campaign mailbox changed after claim')
    if payload.get('action_kind') == 'reply_outreach':
        update(session, 'outreach_reply_slots', bid, payload['slot_id'], dispatched_at=at)
    session.commit()
    evidence = {'outcome': 'unknown'}
    try:
        if blocked:
            evidence = {'outcome': 'definitely_not_accepted', 'provider': payload['provider'],
                        'mailbox_id': payload['mailbox_id'], 'reason': 'Stopped before transport'}
        else:
            evidence = get_provider_for_account(account).send_outreach(
                account=account, operation_key=payload['idempotency_key'], to_emails=[payload['to']],
                cc_emails=payload['cc'], subject=payload['subject'],
                body_text='\n\n'.join(payload[k] for k in ('body', 'sign_off', 'footer')), body_html=None,
                rfc_message_id=payload['rfc_message_id'], in_reply_to=payload['in_reply_to'],
                references=payload['references'], provider_thread_id=payload['provider_thread_id'], headers=payload['headers'],
                **({'reply_provider_message_id': payload['reply_provider_message_id']} if payload.get('action_kind') == 'reply_outreach' else {}))
        require(evidence['mailbox_id'] == payload['mailbox_id'] and evidence['provider'] == payload['provider'])
        require(evidence['outcome'] in ('accepted', 'definitely_not_accepted', 'unknown'))
        require(all(evidence.get(k) is None or (isinstance(evidence[k], str) and len(evidence[k]) <= 512) for k in ('provider_message_id', 'provider_thread_id', 'rfc_message_id')))
        require(evidence.get('rfc_message_id') in (None, payload['rfc_message_id']))
    except Exception:
        evidence = {'outcome': 'unknown'}
    outcome = evidence['outcome']
    result = {'status': {'accepted': 'done', 'definitely_not_accepted': 'failed', 'unknown': 'executing'}[outcome],
              'outcome': outcome, 'search_at': permit[1].isoformat(), 'dispatch_at': at.isoformat()}
    if outcome == 'accepted' and isinstance(evidence.get('thread_note'), str):
        result['thread_note'] = evidence['thread_note'][:200]
    try:
        _settle(session, business, action_id, payload, job[0], evidence, result)
        session.commit()
    except Exception:
        session.rollback()
        # Possible provider acceptance must never become a retryable failure.
        result.update(status='executing', outcome='unknown')
        try:
            _settle(session, business, action_id, payload, job[0], {'outcome': 'unknown'}, result)
            session.commit()
        except Exception:
            session.rollback()  # durable reserved/claimed remains conservative
    return result


def _settle(session, business, action_id, payload, job, evidence, result):
    bid = str(business.id)
    outcome = evidence['outcome']
    if not metering.settle_outreach_usage(session, business, operation_key=payload['idempotency_key'], outcome=outcome, evidence=evidence):
        return
    state = {'accepted': 'accepted', 'unknown': 'unknown', 'definitely_not_accepted': 'failed'}[outcome]
    fields = dict(state=state, provider_message_id=evidence.get('provider_message_id'),
                  provider_thread_id=evidence.get('provider_thread_id'))
    if outcome == 'accepted':
        outbox = str(uuid.uuid4())
        session.execute(text('INSERT INTO email_outbox (id,business_id,email_account_id,to_emails,subject,body_preview,provider_message_id,status,sent_at,created_at) VALUES (:id,:b,:a,:to,:s,:body,:pid,\'sent\',:at,:at)'),
                        {'id': outbox, 'b': bid, 'a': payload['mailbox_id'], 'to': [payload['to']] if pg(session) else json.dumps([payload['to']]),
                         's': payload['subject'], 'body': payload['body'][:500], 'pid': evidence.get('provider_message_id'), 'at': now()})
        fields.update(outbox_id=outbox, accepted_at=_parse(evidence.get('accepted_at')) or now())
        session.execute(text('UPDATE outreach_prospects SET first_contact_at=COALESCE(first_contact_at,:at),last_contact_at=:at,notice_provided_at=COALESCE(notice_provided_at,:at) WHERE business_id=:b AND id=:p'), {'at': fields['accepted_at'], 'b': bid, 'p': payload['prospect_id']})
        if payload.get('action_kind') == 'reply_outreach':
            pass  # A reply never advances or restarts a stopped sequence.
        elif payload['ordinal'] < 2:
            update(session, 'outreach_enrolments', bid, payload['enrolment_id'], next_step=payload['ordinal'] + 1,
                   next_due_at=_business_days(fields['accepted_at'], (5, 7)[payload['ordinal']]))
        else:
            update(session, 'outreach_enrolments', bid, payload['enrolment_id'], state='completed')
    if payload.get('action_kind') == 'reply_outreach':
        slot = one(session, 'outreach_reply_slots', bid, payload['slot_id'], True)
        require(str(slot['action_id']) == str(action_id) and slot['generation'] == payload['slot_generation'])
        require(slot['state'] != 'accepted' or outcome == 'accepted', 'Accepted answer is terminal')
        # Definite refusal is recorded but the slot stays held until an owner
        # independently reviews release. No automatic replacement is possible.
        update(session, 'outreach_reply_slots', bid, slot['id'],
               state='accepted' if outcome == 'accepted' else 'unknown', settled_at=now(), updated_at=now())
        expr = 'CAST(:e AS jsonb)' if pg(session) else ':e'
        session.execute(text(f'UPDATE outreach_reply_slots SET outcome_evidence={expr} WHERE business_id=:b AND id=:id'),
                        {'e': json.dumps(evidence), 'b': bid, 'id': slot['id']})
    update(session, 'outreach_messages', bid, job['message_id'], **fields)
    update(session, 'outreach_dispatch_jobs', bid, job['id'], status='completed' if outcome == 'accepted' else state)
    expr = 'CAST(:r AS jsonb)' if pg(session) else ':r'
    # executed_at marks a finished card, as for every other action (OUT-11:
    # the home lists what Aria sent on her own by it).
    finished = result['status'] in ('done', 'failed')
    session.execute(text(f'UPDATE aria_actions SET status=:s,result={expr},updated_at=:at'
                         + (',executed_at=:at' if finished else '') + ' WHERE business_id=:b AND id=:id'),
                    {'s': result['status'], 'r': json.dumps(result), 'at': now(), 'b': bid, 'id': str(action_id)})


def unsubscribe_base():
    """Where unsubscribe links point (OUT-16): OUTREACH_UNSUBSCRIBE_BASE_URL, or
    the app's own public address with /u, which serves the unsubscribe page."""
    explicit = os.environ.get('OUTREACH_UNSUBSCRIBE_BASE_URL', '').strip()
    if explicit:
        return explicit.rstrip('/')
    public = os.environ.get('PUBLIC_BASE_URL', '').strip().rstrip('/')
    return f'{public}/u' if public else ''


def unsubscribe(session, *, token, method):
    require(method in ('GET', 'POST'), 'Unsupported unsubscribe method', 422)
    require(isinstance(token, str) and 32 <= len(token) <= 128, 'Invalid unsubscribe token', 404)
    digest = hashlib.sha256(token.encode()).hexdigest()
    row = session.execute(text('SELECT * FROM outreach_unsubscribe_tokens WHERE token_digest=:d'), {'d': digest}).mappings().first()
    require(row and row['digest_version'] == 1 and not row['revoked_at'], 'Invalid unsubscribe token', 404)
    if method == 'GET':
        return {'confirmation_required': True}
    bid = str(row['business_id'])
    lock_business(session, bid)
    bound = one(session, 'outreach_unsubscribe_tokens', bid, row['id'], True)
    require(not bound['revoked_at'], 'Invalid unsubscribe token', 404)
    existing = rows(session, 'outreach_suppressions', bid, "AND key_type='email' AND key_digest=:d", {'d': row['prospect_key_digest']})
    if not existing:
        insert(session, 'outreach_suppressions', bid, key_type='email', key_digest=row['prospect_key_digest'],
               digest_version=row['digest_version'], reason='unsubscribe', suppressed_at=now())
    prospects = rows(session, 'outreach_prospects', bid, 'AND email_key=:d', {'d': row['prospect_key_digest']}, True)
    for prospect in prospects:
        session.execute(text("UPDATE outreach_enrolments SET state='suppressed', stop_reason='unsubscribe' WHERE business_id=:b AND prospect_id=:p"), {'b': bid, 'p': prospect['id']})
        session.execute(text("UPDATE outreach_dispatch_jobs SET status='cancelled' WHERE business_id=:b AND status='pending' AND message_id IN (SELECT id FROM outreach_messages WHERE business_id=:b AND prospect_id=:p)"), {'b': bid, 'p': prospect['id']})
        for action in rows(session, 'aria_actions', bid, "AND action_type IN ('send_outreach','reply_outreach') AND status='proposed'", lock=True):
            if loads(action['payload']).get('prospect_id') == str(prospect['id']):
                update(session, 'aria_actions', bid, action['id'], status='dismissed', error='Recipient unsubscribed')
    session.commit()
    return {'unsubscribed': True}


def search_reply_before_claim(session, business, *, action_id, payload):
    """Claude's reply registration must use this typed preflight."""
    require(payload.get('action_kind') == 'reply_outreach')
    require(one(session, 'aria_actions', business.id, action_id)['action_type'] == 'reply_outreach')
    return search_before_claim(session, business, action_id=action_id, payload=payload)


def prepare_reply_claim(session, business, *, action_id, payload, user_id, version, moment):
    require(payload.get('action_kind') == 'reply_outreach')
    return prepare_claim(session, business, action_id=action_id, payload=payload,
                         user_id=user_id, version=version, moment=moment)


def dispatch_reply(session, business, *, action_id, payload):
    require(payload.get('action_kind') == 'reply_outreach')
    return dispatch(session, business, action_id=action_id, payload=payload)
