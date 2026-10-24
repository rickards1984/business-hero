"""OUT-7: stored inbox safety, grounded proposals and permanent answer slots.

No polling or model client. Callbacks run only after the safety transaction has
committed. Without an activated router callback, classification fails closed to
Needs you. All cooperating writers take outreach_send.lock_business first.
"""
import hashlib
import json
import re
import uuid
from datetime import timedelta

from sqlalchemy import text

from services import outreach_send as send
from services.aria_actions import _is_active_owner, version_of
from services.chase_replies import _address, _parse

now = send.now
CATEGORIES = {'interested', 'question', 'not_now', 'unsubscribe', 'objection',
              'out_of_office', 'wrong_person', 'referral', 'unknown'}
OPT_OUT = re.compile(r'\b(unsubscribe|remove me|stop emailing|never email|do not (?:email|contact)|don.t (?:email|contact))\b', re.I)


def _start(session, bid):
    send.require(not session.new and not session.dirty and not session.deleted,
                 'Storage completion requires a clean session')
    session.rollback()
    # SQLite has no row locks: acquire its writer lock BEFORE reading. The
    # production path uses the existing ordered PostgreSQL business locks.
    if not send.pg(session):
        session.execute(text('UPDATE business_settings SET business_id=business_id WHERE business_id=:b'), {'b': str(bid)})
    send.lock_business(session, bid)


def _owner(session, bid, prospect):
    owners = session.execute(text("SELECT user_id FROM business_members WHERE business_id=:b AND role='owner' AND is_active=:t ORDER BY user_id"), {'b': str(bid), 't': True}).scalars().all()
    assigned = prospect.get('owner_user_id')
    return str(assigned) if assigned and str(assigned) in {str(o) for o in owners} else (str(owners[0]) if owners else None)


def _stop(session, bid, pid, state, reason, moment, takeover=False):
    # Never replace suppression or a previous owner's takeover with a label.
    session.execute(text("UPDATE outreach_enrolments SET state=:s,stop_reason=:r,updated_at=:at "
                         + (",takeover_at=COALESCE(takeover_at,:at) " if takeover else '') +
                         "WHERE business_id=:b AND prospect_id=:p AND state IN ('pending','active','paused','replied') "
                         + ('' if takeover or state == 'suppressed' else 'AND takeover_at IS NULL')),
                    {'s': state, 'r': reason, 'at': moment, 'b': str(bid), 'p': str(pid)})
    for action in send.rows(session, 'aria_actions', bid, "AND action_type IN ('send_outreach','reply_outreach') AND status='proposed'", lock=True):
        if str(send.loads(action['payload']).get('prospect_id')) == str(pid):
            send.update(session, 'aria_actions', bid, action['id'], status='dismissed', error=reason, updated_at=moment)
    session.execute(text("UPDATE outreach_dispatch_jobs SET status='cancelled' WHERE business_id=:b AND status='pending' AND message_id IN (SELECT id FROM outreach_messages WHERE business_id=:b AND prospect_id=:p)"), {'b': str(bid), 'p': str(pid)})


def _suppress(session, bid, prospect, reason, moment):
    digest = send.suppression_digest(bid, 'email', prospect['email'])
    if not send.rows(session, 'outreach_suppressions', bid, "AND key_type='email' AND key_digest=:d", {'d': digest}):
        send.insert(session, 'outreach_suppressions', bid, key_type='email', key_digest=digest,
                    digest_version=1, reason=reason, suppressed_at=moment)
    _stop(session, bid, prospect['id'], 'suppressed', reason, moment)


def _hand_over(session, bid, reply, reason, moment):
    if reply['resolution'] in ('resolved', 'dismissed'):
        return {'id': str(reply['id']), 'status': 'handed_over', 'reason': 'Reply already resolved; no draft'}
    p = send.one(session, 'outreach_prospects', bid, reply['prospect_id'])
    _stop(session, bid, p['id'], 'paused', reason, moment, takeover=True)
    send.update(session, 'outreach_replies', bid, reply['id'], resolution='handed_over',
                owner_id=_owner(session, bid, p), updated_at=moment)
    return {'id': str(reply['id']), 'status': 'handed_over', 'reason': reason}


def handover(session, business, *, reply_id, user_id, moment):
    send.require(_is_active_owner(session, business, user_id), 'Active owner required', 403)
    _start(session, business.id)
    reply = send.one(session, 'outreach_replies', business.id, reply_id, True)
    send.require(_is_active_owner(session, business, user_id, lock=True), 'Active owner required', 403)
    result = _hand_over(session, business.id, reply, 'Owner takeover', moment)
    session.commit()
    return result


def _context(inbound):
    return {'body': (inbound.get('body_text') or '')[:12000],
            'subject': (inbound.get('subject') or '')[:998]}


def _matches(message, inbound, account):
    if str(message['mailbox_id']) != str(inbound['email_account_id']):
        return False
    if not inbound.get('provider_thread_id') or message['provider_thread_id'] != inbound['provider_thread_id']:
        return False
    recipients = send.loads(message.get('to_emails') or '[]')
    if _address(inbound['from_email']) not in {_address(v) for v in recipients}:
        return False
    # Older AUTO-2 stored rows lack recipients/headers. When available they
    # are additional evidence and must agree, never subject-only matching.
    to = send.loads(inbound.get('to_emails') or '[]')
    if to and _address(account['email_address']) not in {_address(v) for v in to}:
        return False
    headers = send.loads(inbound.get('raw_headers') or '{}')
    headers = {k.lower(): v for k, v in headers.items()}
    refs = str(headers.get('in-reply-to') or headers.get('references') or '')
    return not refs or bool(message.get('rfc_message_id') and message['rfc_message_id'] in refs.split())


def scan(session, business, *, classify=None, moment=None):
    """Scan existing storage; commit stopping before any optional classifier."""
    moment = moment or now()
    bid = str(business.id)
    _start(session, bid)
    accounts = {str(a['id']): a for a in send.rows(session, 'email_accounts', bid)}
    own = {_address(a['email_address']) for a in accounts.values()}
    captured = []
    inbox = send.rows(session, 'email_messages', bid,
        "AND NOT EXISTS (SELECT 1 FROM outreach_replies r WHERE r.business_id=:bid AND r.inbound_email_id=email_messages.id) ORDER BY received_at,id")
    for incoming in inbox:
        sender = _address(incoming['from_email'])
        if not sender or sender in own or str(incoming['email_account_id']) not in accounts:
            continue
        received = _parse(incoming['received_at'])
        if not received or received > moment:
            continue
        prospects = send.rows(session, 'outreach_prospects', bid, 'AND lower(email) LIKE :e', {'e': '%' + sender + '%'})
        prospects = [p for p in prospects if _address(p['email']) == sender]
        candidates = []
        for p in prospects:
            history = send.rows(session, 'outreach_messages', bid,
                "AND prospect_id=:p AND direction='outbound' AND state='accepted' ORDER BY accepted_at DESC,id",
                {'p': str(p['id'])})
            history = [m for m in history if _parse(m['accepted_at']) and _parse(m['accepted_at']) <= received]
            if history:
                candidates.append((p, history))
        if not candidates:
            continue
        exact = [(p, m) for p, hist in candidates for m in hist
                 if _matches(m, incoming, accounts[str(incoming['email_account_id'])])]
        identities = {(str(p['id']), str(m['campaign_id'])) for p, m in exact}
        matched = exact[0][1] if len(identities) == 1 else None
        p = exact[0][0] if matched else candidates[0][0]
        optout = bool(OPT_OUT.search(incoming.get('body_text') or ''))
        for candidate, _ in candidates:
            if optout:
                _suppress(session, bid, candidate, 'unsubscribe', moment)
            else:
                _stop(session, bid, candidate['id'], 'replied' if matched else 'paused',
                      'Reply received' if matched else 'Uncertain reply attribution', moment)
        rid = send.insert(session, 'outreach_replies', bid, prospect_id=p['id'],
            mailbox_id=incoming['email_account_id'], inbound_email_id=incoming['id'],
            matched_message_id=matched['id'] if matched else None, category='unsubscribe' if optout else 'unknown',
            confidence=100 if optout else 0, classification_version=1, knowledge_refs=[],
            owner_id=_owner(session, bid, p), resolution='pending', received_at=received)
        reply = send.one(session, 'outreach_replies', bid, rid)
        if optout or not matched or not incoming.get('body_text') or not accounts[str(incoming['email_account_id'])]['token_ciphertext']:
            _hand_over(session, bid, reply, 'Opt-out' if optout else 'Reply needs owner review', moment)
        else:
            captured.append((rid, incoming, reply['updated_at']))
    session.commit()
    for rid, incoming, stamp in captured:
        try:
            result = classify(_context(incoming)) if classify else {}
            category, confidence = result.get('category', 'unknown'), result.get('confidence', 0)
            if category not in CATEGORIES or type(confidence) not in (int, float) or not 0 <= confidence <= 100:
                category, confidence = 'unknown', 0
        except Exception:
            category, confidence, result = 'unknown', 0, {}
        _start(session, bid)
        reply = send.one(session, 'outreach_replies', bid, rid, True)
        if reply['resolution'] != 'pending' or reply['updated_at'] != stamp or reply['category'] != 'unknown':
            session.rollback()
            continue
        enrolments = send.rows(session, 'outreach_enrolments', bid, 'AND prospect_id=:p', {'p': str(reply['prospect_id'])})
        if any(e['takeover_at'] or e['state'] == 'suppressed' for e in enrolments):
            _hand_over(session, bid, reply, 'Conversation already taken over', moment)
        else:
            ver = result.get('classification_version', 1)
            send.update(session, 'outreach_replies', bid, rid, category=category, confidence=confidence,
                        classification_version=ver if type(ver) is int and ver > 0 else 1, updated_at=moment)
            if category in ('unsubscribe', 'objection'):
                _suppress(session, bid, send.one(session, 'outreach_prospects', bid, reply['prospect_id']), category, moment)
            if category not in ('question', 'interested') or confidence < 90:
                _hand_over(session, bid, reply, 'Reply needs owner review: ' + category, moment)
        session.commit()
    return [str(r['id']) for r in send.rows(session, 'outreach_replies', bid)]


def _facts(session, bid, brand, moment):
    facts = send.rows(session, 'outreach_knowledge', bid, "AND brand_id=:b AND status='approved' ORDER BY topic,version", {'b': str(brand)})
    facts = [k for k in facts if k['approved_by'] and _parse(k['approved_at']) and
             _parse(k['approved_at']) <= moment < _parse(k['review_due_at'])]
    if len({k['topic'] for k in facts}) != len(facts):
        return []
    return [{'id': str(k['id']), 'version': k['version'], 'answer': k['answer'],
             'source_reference': k['source_reference']} for k in facts]


def _grounded(draft, facts):
    if not isinstance(draft, dict) or set(draft) != {'body', 'knowledge_refs'}:
        return False
    refs = draft['knowledge_refs']
    if not isinstance(refs, list) or not refs or any(not isinstance(r, dict) or set(r) != {'id', 'version'} for r in refs):
        return False
    selected = []
    for ref in refs:
        match = [k for k in facts if ref == {'id': k['id'], 'version': k['version']}]
        if len(match) != 1:
            return False
        selected.append(match[0]['answer'])
    # Deterministic extractive drafting: unsupported factual additions cannot
    # be proved by a model's self-assessment. Only verbatim cited answers pass.
    return isinstance(draft['body'], str) and draft['body'] == '\n\n'.join(selected) and len(draft['body']) <= 20000


def _reply_records(session, bid, rid):
    reply = send.one(session, 'outreach_replies', bid, rid)
    send.require(reply['matched_message_id'], 'Reply attribution unavailable')
    message = send.one(session, 'outreach_messages', bid, reply['matched_message_id'])
    campaign = send.one(session, 'outreach_campaigns', bid, message['campaign_id'])
    return reply, message, campaign


def _eligible(session, bid, reply):
    enrolments = send.rows(session, 'outreach_enrolments', bid, 'AND prospect_id=:p', {'p': str(reply['prospect_id'])})
    return (reply['resolution'] == 'pending' and reply['category'] in ('question', 'interested')
            and reply['confidence'] >= 90 and not any(e['takeover_at'] or e['state'] == 'suppressed' for e in enrolments))


def _card(action):
    payload = send.loads(action['payload'])
    return {'id': str(action['id']), 'status': action['status'], 'version': version_of(payload), 'preview': payload}


def propose_answer(session, business, *, reply_id, draft, moment):
    bid = str(business.id)
    _start(session, bid)
    reply = send.one(session, 'outreach_replies', bid, reply_id, True)
    slots = send.rows(session, 'outreach_reply_slots', bid, 'AND prospect_id=:p', {'p': str(reply['prospect_id'])})
    if slots:
        slot = slots[0]
        action = send.one(session, 'aria_actions', bid, slot['action_id'])
        if str(slot['reply_id']) == str(reply_id) and action['status'] == 'proposed' and _eligible(session, bid, reply):
            session.commit()
            return _card(action)
        result = _hand_over(session, bid, reply, 'One answer already reserved; owner reply required', moment)
        session.commit()
        return result
    if not _eligible(session, bid, reply) or not reply['matched_message_id']:
        result = _hand_over(session, bid, reply, 'Reply needs owner review', moment)
        session.commit()
        return result
    reply, message, campaign = _reply_records(session, bid, reply_id)
    facts = _facts(session, bid, campaign['brand_id'], moment)
    stamp = reply['updated_at']
    inbound = send.one(session, 'email_messages', bid, reply['inbound_email_id'])
    session.commit()
    try:
        drafted = draft({'reply': _context(inbound), 'knowledge': facts}) if facts else None
    except Exception:
        drafted = None
    _start(session, bid)
    reply, message, campaign = _reply_records(session, bid, reply_id)
    slots = send.rows(session, 'outreach_reply_slots', bid, 'AND prospect_id=:p', {'p': str(reply['prospect_id'])})
    if slots:
        session.commit()
        return propose_answer(session, business, reply_id=reply_id, draft=draft, moment=moment)
    fresh = _facts(session, bid, campaign['brand_id'], max(moment, now()))
    if not _eligible(session, bid, reply) or reply['updated_at'] != stamp or fresh != facts or not _grounded(drafted, fresh):
        result = _hand_over(session, bid, reply, 'No current grounded answer', moment)
        session.commit()
        return result
    enrolments = send.rows(session, 'outreach_enrolments', bid, 'AND prospect_id=:p AND campaign_id=:c', {'p': str(reply['prospect_id']), 'c': str(campaign['id'])})
    steps = send.rows(session, 'outreach_sequence_steps', bid, 'AND campaign_id=:c AND sequence_version=:v ORDER BY ordinal', {'c': str(campaign['id']), 'v': campaign['sequence_version']})
    send.require(enrolments and steps and str(campaign['mailbox_id']) == str(reply['mailbox_id']))
    payload = send.build_payload(session, business, {'campaign_id': str(campaign['id']), 'enrolment_id': str(enrolments[0]['id']), 'step_id': str(steps[0]['id'])})
    aid, sid = str(uuid.uuid4()), str(uuid.uuid4())
    headers = send.loads(inbound.get('raw_headers') or '{}')
    rfc = next((v for k, v in headers.items() if k.lower() == 'message-id'), None)
    payload.update(action_kind='reply_outreach', reply_id=str(reply_id), slot_id=sid, slot_generation=1,
                   body=drafted['body'], knowledge_refs=drafted['knowledge_refs'], knowledge=facts,
                   provider_thread_id=inbound['provider_thread_id'], in_reply_to=rfc,
                   references=[rfc] if rfc else [], reply_provider_message_id=inbound['provider_message_id'],
                   subject=send._safe_header('Re: ' + (inbound['subject'] or 'Your reply')[:990]),
                   idempotency_key=hashlib.sha256(f'{bid}:{sid}:1:{aid}'.encode()).hexdigest(),
                   expires_at=(moment + timedelta(hours=72)).isoformat())
    send.insert(session, 'aria_actions', bid, id=aid, action_type='reply_outreach', payload=payload,
                status='proposed', expires_at=_parse(payload['expires_at']))
    send.insert(session, 'outreach_reply_slots', bid, id=sid, prospect_id=reply['prospect_id'], reply_id=reply_id,
                mailbox_id=reply['mailbox_id'], action_id=aid, state='reserved', generation=1,
                reserved_at=moment, outcome_evidence={})
    expr = 'CAST(:refs AS jsonb)' if send.pg(session) else ':refs'
    session.execute(text(f'UPDATE outreach_replies SET knowledge_refs={expr},suggested_body=:body WHERE business_id=:b AND id=:r'),
                    {'refs': json.dumps(drafted['knowledge_refs']), 'body': drafted['body'], 'b': bid, 'r': str(reply_id)})
    session.commit()
    return {'id': aid, 'status': 'proposed', 'version': version_of(payload), 'preview': payload}


def validate_claim(session, business, payload, action_id, moment):
    bid = str(business.id)
    reply, message, campaign = _reply_records(session, bid, payload['reply_id'])
    slot = send.one(session, 'outreach_reply_slots', bid, payload['slot_id'], True)
    send.require(_eligible(session, bid, reply) and slot['state'] == 'reserved' and not slot['message_id'])
    send.require(str(slot['action_id']) == str(action_id) and str(slot['reply_id']) == payload['reply_id']
                 and str(slot['prospect_id']) == payload['prospect_id'] and str(slot['mailbox_id']) == payload['mailbox_id']
                 and slot['generation'] == payload['slot_generation'])
    send.require(str(campaign['id']) == payload['campaign_id'] and str(reply['mailbox_id']) == payload['mailbox_id'])
    facts = _facts(session, bid, campaign['brand_id'], moment)
    send.require(facts == payload['knowledge'] and _grounded({'body': payload['body'], 'knowledge_refs': payload['knowledge_refs']}, facts), 'Knowledge changed or answer unsupported')
    inbound = send.one(session, 'email_messages', bid, reply['inbound_email_id'])
    send.require(inbound['provider_thread_id'] == payload['provider_thread_id'] and inbound['provider_message_id'] == payload['reply_provider_message_id'])
    expected_key = hashlib.sha256(f"{bid}:{slot['id']}:{slot['generation']}:{action_id}".encode()).hexdigest()
    send.require(payload['idempotency_key'] == expected_key)
    headers = send.loads(inbound.get('raw_headers') or '{}')
    rfc = next((v for k, v in headers.items() if k.lower() == 'message-id'), None)
    send.require(payload['in_reply_to'] == rfc and payload['references'] == ([rfc] if rfc else []))
    send.require(not send.rows(session, 'outreach_replies', bid, 'AND prospect_id=:p AND id<>:r', {'p': payload['prospect_id'], 'r': payload['reply_id']}), 'Another reply needs the owner')
    return str(reply['inbound_email_id'])


def observe_health(session, business, *, inbound_email_id, message_id, kind, evidence, moment):
    """Trusted adapter boundary, NOT a model or public webhook payload.

    Adapter must authenticate the event and bind it to the accepted outbound
    provider ID. Human email text alone never proves a bounce or complaint.
    """
    send.require(kind in ('hard_bounce', 'complaint') and isinstance(evidence, dict))
    bid = str(business.id)
    _start(session, bid)
    message = send.one(session, 'outreach_messages', bid, message_id, True)
    inbound = send.one(session, 'email_messages', bid, inbound_email_id)
    send.require(message['state'] == 'accepted' and message['provider_message_id'])
    send.require(evidence.get('provider_message_id') == message['provider_message_id'] and
                 evidence.get('mailbox_id') == str(message['mailbox_id']) and
                 evidence.get('provider') == message['provider'] and evidence.get('authenticated') is True)
    send.require(str(inbound['email_account_id']) == str(message['mailbox_id']) and
                 _parse(message['accepted_at']) <= _parse(inbound['received_at']) <= moment)
    previous = send.rows(session, 'outreach_replies', bid, 'AND inbound_email_id=:i', {'i': str(inbound_email_id)})
    if previous:
        session.commit()
        return {'recorded': False}
    prospect = send.one(session, 'outreach_prospects', bid, message['prospect_id'])
    category = 'bounce' if kind == 'hard_bounce' else 'complaint'
    send.insert(session, 'outreach_replies', bid, prospect_id=prospect['id'], mailbox_id=message['mailbox_id'],
                inbound_email_id=inbound_email_id, matched_message_id=message_id, category=category,
                confidence=100, classification_version=1, knowledge_refs=[], owner_id=_owner(session, bid, prospect),
                resolution='handed_over', received_at=inbound['received_at'])
    if kind == 'hard_bounce':
        _suppress(session, bid, prospect, 'hard_bounce', moment)
    recent = send.rows(session, 'outreach_messages', bid,
        "AND mailbox_id=:m AND state='accepted' AND direction='outbound' ORDER BY accepted_at DESC,id DESC LIMIT 50",
        {'m': str(message['mailbox_id'])})
    ids = {str(m['id']) for m in recent}
    bounces = send.rows(session, 'outreach_replies', bid, "AND mailbox_id=:m AND category='bounce'", {'m': str(message['mailbox_id'])})
    count = len({str(r['matched_message_id']) for r in bounces} & ids)
    if kind == 'complaint' or count >= 3:
        for mailbox in send.rows(session, 'outreach_mailboxes', bid, 'AND mailbox_id=:m', {'m': str(message['mailbox_id'])}, True):
            send.update(session, 'outreach_mailboxes', bid, mailbox['id'], enabled=False, health_status='fail',
                        pause_reason='complaint' if kind == 'complaint' else 'Three distinct hard bounces in latest 50 sends',
                        health_checked_at=moment, updated_at=moment)
        session.execute(text("UPDATE outreach_dispatch_jobs SET status='cancelled' WHERE business_id=:b AND status='pending' AND message_id IN (SELECT id FROM outreach_messages WHERE business_id=:b AND mailbox_id=:m)"), {'b': bid, 'm': str(message['mailbox_id'])})
        # Cancel only work bound to the affected mailbox. Suppression above
        # independently covers this recipient across every campaign.
        for action in send.rows(session, 'aria_actions', bid, "AND status='proposed' AND action_type IN ('send_outreach','reply_outreach')", lock=True):
            if send.loads(action['payload']).get('mailbox_id') == str(message['mailbox_id']):
                send.update(session, 'aria_actions', bid, action['id'], status='dismissed', error='Mailbox health hold')
    session.commit()
    return {'recorded': True, 'distinct_hard_bounces_in_latest_50': count}


def reconcile(session, business, *, action_id, verify, moment):
    """Read-only trusted provider verification OUTSIDE locks; never resend.

    `verify` receives only the original operation/mailbox/message identifiers.
    It must independently establish acceptance or definite non-acceptance.
    Uncertain evidence leaves the durable slot and usage untouched.
    """
    action = send.one(session, 'aria_actions', business.id, action_id)
    payload = send.loads(action['payload'])
    send.require(action['action_type'] == 'reply_outreach')
    job = send.rows(session, 'outreach_dispatch_jobs', business.id, 'AND action_id=:a', {'a': str(action_id)})
    send.require(len(job) == 1 and job[0]['dispatch_started_at'])
    query = {k: payload[k] for k in ('idempotency_key', 'mailbox_id', 'provider', 'rfc_message_id')}
    session.rollback()
    evidence = verify(query)
    send.require(isinstance(evidence, dict) and evidence.get('outcome') in ('accepted', 'definitely_not_accepted'))
    send.require(evidence.get('operation_key') == payload['idempotency_key'] and
                 evidence.get('mailbox_id') == payload['mailbox_id'] and evidence.get('provider') == payload['provider'] and
                 isinstance(evidence.get('verification_reference'), str) and 0 < len(evidence['verification_reference']) <= 1000)
    send.require(len(json.dumps(evidence).encode()) <= 12000)
    _start(session, business.id)
    slot = send.one(session, 'outreach_reply_slots', business.id, payload['slot_id'], True)
    send.require(str(slot['action_id']) == str(action_id) and slot['generation'] == payload['slot_generation'])
    if slot['state'] == 'accepted':
        send.require(evidence['outcome'] == 'accepted', 'Accepted answer is terminal')
        session.commit()
        return {'status': 'done'}
    send.require(slot['state'] in ('reserved', 'unknown'))
    previous = send.loads(slot['outcome_evidence'] or '{}')
    if previous.get('outcome') == 'definitely_not_accepted':
        send.require(evidence['outcome'] == 'definitely_not_accepted', 'Conflicting terminal evidence needs review')
        session.commit()
        return {'status': 'failed', 'outcome': 'definitely_not_accepted'}
    result = {'status': 'done' if evidence['outcome'] == 'accepted' else 'failed',
              'outcome': evidence['outcome'], 'verified_at': moment.isoformat()}
    send._settle(session, business, action_id, payload, job[0], evidence, result)
    session.commit()
    return result


def release_slot(session, business, *, slot_id, user_id, moment):
    """Owner review of already recorded definite non-acceptance. No timeout."""
    send.require(_is_active_owner(session, business, user_id), 'Active owner required', 403)
    _start(session, business.id)
    slot = send.one(session, 'outreach_reply_slots', business.id, slot_id, True)
    action = send.one(session, 'aria_actions', business.id, slot['action_id'], True)
    send.require(_is_active_owner(session, business, user_id, lock=True), 'Active owner required', 403)
    evidence = send.loads(slot['outcome_evidence'])
    send.require(slot['state'] == 'unknown' and evidence.get('outcome') == 'definitely_not_accepted'
                 and action['status'] == 'failed', 'Definite non-acceptance required')
    audit = send.loads(action['result'] or '{}')
    send.require('released_slot' not in audit, 'Release already archived')
    audit['released_slot'] = {k: str(v) if v is not None else None for k, v in slot.items()}
    audit['release_review'] = {'owner_id': str(user_id), 'at': moment.isoformat(), 'evidence': evidence}
    expr = 'CAST(:r AS jsonb)' if send.pg(session) else ':r'
    session.execute(text(f'UPDATE aria_actions SET result={expr} WHERE business_id=:b AND id=:a'),
                    {'r': json.dumps(audit), 'b': str(business.id), 'a': slot['action_id']})
    send.update(session, 'outreach_reply_slots', business.id, slot_id, state='released',
                released_at=moment, release_reason='Owner reviewed definite non-acceptance', settled_at=moment)
    session.commit()
    return {'status': 'released'}


def replace_answer(session, business, *, slot_id, user_id, moment):
    """Explicit owner-reviewed replacement; reuse the same draft, never redraft."""
    send.require(_is_active_owner(session, business, user_id), 'Active owner required', 403)
    _start(session, business.id)
    slot = send.one(session, 'outreach_reply_slots', business.id, slot_id, True)
    old = send.one(session, 'aria_actions', business.id, slot['action_id'], True)
    send.require(_is_active_owner(session, business, user_id, lock=True), 'Active owner required', 403)
    send.require(slot['state'] == 'released' and 'released_slot' in send.loads(old['result']))
    payload = send.loads(old['payload'])
    reply, _, campaign = _reply_records(session, business.id, payload['reply_id'])
    send.require(_eligible(session, business.id, reply), 'Owner takeover prevents replacement')
    send.require(not send.rows(session, 'outreach_replies', business.id, 'AND prospect_id=:p AND id<>:r',
                               {'p': payload['prospect_id'], 'r': payload['reply_id']}), 'Another reply needs the owner')
    facts = _facts(session, business.id, campaign['brand_id'], moment)
    send.require(facts == payload['knowledge'] and _grounded({'body': payload['body'], 'knowledge_refs': payload['knowledge_refs']}, facts))
    aid = str(uuid.uuid4())
    generation = slot['generation'] + 1
    payload.update(slot_generation=generation, expires_at=(moment + timedelta(hours=72)).isoformat(),
                   idempotency_key=hashlib.sha256(f'{business.id}:{slot_id}:{generation}:{aid}'.encode()).hexdigest(),
                   rfc_message_id=f"<{uuid.uuid4()}@{payload['from_email'].split('@')[-1]}>")
    send.insert(session, 'aria_actions', business.id, id=aid, action_type='reply_outreach', status='proposed',
                payload=payload, proposed_by=str(user_id), expires_at=_parse(payload['expires_at']))
    send.update(session, 'outreach_reply_slots', business.id, slot_id, action_id=aid, message_id=None,
                state='reserved', generation=generation, reserved_at=moment, dispatched_at=None,
                settled_at=None, released_at=None, release_reason=None, payload_hash=None)
    expr = "'{}'::jsonb" if send.pg(session) else "'{}'"
    session.execute(text(f'UPDATE outreach_reply_slots SET outcome_evidence={expr} WHERE business_id=:b AND id=:s'),
                    {'b': str(business.id), 's': str(slot_id)})
    session.commit()
    return {'id': aid, 'version': version_of(payload), 'preview': payload, 'status': 'proposed'}


def save_knowledge(session, business, *, brand_id, topic, answer, source_reference, review_due_at, user_id, moment):
    """Approve an immutable new fact version and retire its prior version."""
    from auth import assert_feature_access
    assert_feature_access(business, 'outreach')
    send.require(_is_active_owner(session, business, user_id), 'Active owner required', 403)
    for value, maximum in ((topic, 200), (answer, 4000), (source_reference, 2000)):
        send.require(isinstance(value, str) and 0 < len(value.strip()) <= maximum, 'Invalid knowledge', 422)
    send.require(_parse(review_due_at) and _parse(review_due_at) > moment, 'Explicit future review date required', 422)
    _start(session, business.id)
    send.one(session, 'outreach_brands', business.id, brand_id, True)
    prior = send.rows(session, 'outreach_knowledge', business.id, 'AND brand_id=:b AND topic=:t', {'b': str(brand_id), 't': topic.strip()}, True)
    send.require(_is_active_owner(session, business, user_id, lock=True), 'Active owner required', 403)
    for k in prior:
        if k['status'] == 'approved':
            send.update(session, 'outreach_knowledge', business.id, k['id'], status='retired', retired_at=moment, updated_at=moment)
    ident = send.insert(session, 'outreach_knowledge', business.id, brand_id=brand_id, topic=topic.strip(), answer=answer.strip(),
        source_reference=source_reference.strip(), version=max((k['version'] for k in prior), default=0) + 1,
        status='approved', approved_by=str(user_id), approved_at=moment, review_due_at=_parse(review_due_at))
    session.commit()
    return {'id': ident, 'status': 'approved'}


def storage_completed(session, business):
    """One notification after existing inbox storage commits; no new cursor.

    Safety remains active without outreach entitlement. Missing rollout schema
    or scan failure is logged, never described as an empty inbox. Approval also
    independently rechecks stored inbound, so failed scanning cannot send.
    Router-backed classification/drafting is an explicit later activation gate.
    (Lives here, not in app/email/service.py, so that file stays untouched.)
    """
    import logging
    from services import outreach_send
    try:
        if not outreach_send.rows(session, 'outreach_settings', business.id):
            session.rollback()
            return []
        return scan(session, business)
    except Exception:
        session.rollback()
        logging.getLogger(__name__).exception('Outreach storage scan unavailable')
        return None
