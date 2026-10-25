"""OUT-6 service contract through a local transaction seam.

Only Claude-owned integration cases await the real aria_actions hook. SQLite
mirrors 037 columns and the action status CHECK, not PostgreSQL locks/RLS/FKs.
All identities and providers are synthetic; sockets are forbidden.
"""
import hashlib
import hmac
import importlib
import json
import re
import socket
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlmodel import Session


class MissingSharedHook(AssertionError):
    """Only the absent Claude-owned registration is expected to fail."""


# These cases run through the REAL services.aria_actions path. They were
# strict-xfailed until Claude's hook landed; the marks are gone and they must pass.
HOOK = pytest.mark.usefixtures('real_aria_actions')


@pytest.fixture
def real_aria_actions():
    """Marker fixture: the `h` fixture below hands these tests real aria_actions."""
NOW = datetime(2026, 10, 23, 11, tzinfo=timezone.utc)
LAST = NOW - timedelta(days=10)
STAMP = NOW.isoformat()


def uid(label):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, 'out6-test:' + label))


A, B, OWNER, STAFF = uid('A'), uid('B'), uid('owner'), uid('staff')
BOX, DEFAULT, FOREIGN = uid('box'), uid('default'), uid('foreign')
PROSPECT, CAMPAIGN, STEP, ENROLMENT, BRAND, LIA = map(
    uid, ('prospect', 'campaign', 'step', 'enrolment', 'brand', 'lia'))
EMAIL = 'person@example.invalid'
KEY = hmac.new(('synthetic-key-' * 4).encode(), f'v1:{A}:email:{EMAIL}'.encode(), hashlib.sha256).hexdigest()


def insert(session, table, **values):
    session.execute(text(f"INSERT INTO {table} ({','.join(values)}) VALUES "
                         f"({','.join(':' + k for k in values)})"), values)


def add(session, table, **values):
    row = dict(id=str(uuid.uuid4()), business_id=A, created_at=STAMP, updated_at=STAMP)
    row.update(values)
    insert(session, 'outreach_' + table, **row)
    return row['id']


def seed(s, foreign=True):
    """The synthetic campaign, shared by the SQLite suite and the Postgres
    one (test_outreach_send_rls.py). Never real data. `foreign` adds another
    business's half-formed rows for the SQLite isolation cases; 037's foreign
    keys would rightly refuse them."""
    # Codex hook review 1 (P1): only an active OWNER of this business may
    # approve outreach. Staff and platform admins may not.
    insert(s, 'business_members', business_id=A, user_id=OWNER, role='owner', is_active=True)
    insert(s, 'business_members', business_id=A, user_id=STAFF, role='member', is_active=True)
    for box, bid, default in ((BOX, A, False), (DEFAULT, A, True), (FOREIGN, B, True)):
        insert(s, 'email_accounts', id=box, business_id=bid, user_id=OWNER,
               provider='google', email_address=f'{box}@example.invalid', is_default=default,
               capabilities='{}', token_ciphertext='fake-token', refresh_token_ciphertext='fake-refresh',
               created_at=(NOW + timedelta(days=1) if default else LAST).isoformat())
    add(s, 'brands', id=BRAND, name='Synthetic Ltd', default_mailbox_id=DEFAULT,
        privacy_url='https://example.invalid/privacy', sender_identity='Synthetic Ltd', version=1)
    add(s, 'settings', pause_all=False, timezone='Europe/London', business_daily_cap=20,
        owner_cc_default=False, retention_policy_version=1)
    add(s, 'mailboxes', mailbox_id=BOX, enabled=True, daily_cap=5, warmup_stage=5,
        sending_days=0, health_status='pass', health_checked_at=STAMP,
        health_evidence=json.dumps({'domain_control': True, 'spf': 'pass', 'dkim': 'pass',
                                    'dmarc': 'pass', 'from_aligned': True}))
    add(s, 'compliance', id=LIA, brand_id=BRAND, audience_hash='audience-v1', version=1,
        purpose='Relevant synthetic offer', necessity='Synthetic', balancing_test='Synthetic',
        safeguards='Opt out', sources='[]', decision='approved', reviewer=OWNER,
        reviewed_at=STAMP, review_due_at=(NOW + timedelta(days=30)).isoformat())
    add(s, 'prospects', id=PROSPECT, company='Synthetic Ltd', name='Person',
        role='Director', domain='example.invalid', email=EMAIL, email_key=KEY,
        subscriber_type='corporate', eligibility='eligible', lawful_basis='legitimate_interests',
        lia_id=LIA, stage='ready', captured_at=LAST.isoformat(), evidence_checked_at=STAMP,
        notice_due_at=(NOW + timedelta(days=10)).isoformat(),
        retention_due_at=(NOW + timedelta(days=300)).isoformat())
    add(s, 'evidence', prospect_id=PROSPECT, source_type='synthetic', operation='verify',
        source_url='https://example.invalid/team', fact_type='email_verification', fact_value='valid',
        verification_status='valid', verification_subject_email_key=KEY, flags='[]',
        fetched_at=STAMP, verified_at=STAMP, expires_at=(NOW + timedelta(days=7)).isoformat())
    add(s, 'campaigns', id=CAMPAIGN, brand_id=BRAND, mailbox_id=BOX, name='Synthetic',
        target_rules='{}', target_hash='audience-v1', sequence_version=1, version=1,
        status='ready', timezone='Europe/London', daily_cap=5)
    add(s, 'sequence_steps', id=STEP, campaign_id=CAMPAIGN, sequence_version=1,
        ordinal=0, delay_business_days=0, template_text=json.dumps({'schema_version': 1, 'subject': 'Synthetic offer',
                                  'body': 'A relevant synthetic offer.'}),
        template_hash=hashlib.sha256(json.dumps({'schema_version': 1, 'subject': 'Synthetic offer',
                                               'body': 'A relevant synthetic offer.'}).encode()).hexdigest(),
        allowed_variables='[]', approved_by=OWNER, approved_at=STAMP)
    add(s, 'enrolments', id=ENROLMENT, prospect_id=PROSPECT, campaign_id=CAMPAIGN,
        sequence_version=1, state='active', next_step=0, next_due_at=LAST.isoformat())
    if not foreign:
        return
    add(s, 'campaigns', id=uid('foreign-campaign'), business_id=B, mailbox_id=FOREIGN,
        brand_id=uid('foreign-brand'), name='FOREIGN SECRET', target_rules='{}',
        target_hash='foreign', sequence_version=1, version=1, status='ready',
        timezone='Europe/London', daily_cap=5)
    add(s, 'enrolments', id=uid('foreign-enrolment'), business_id=B,
        campaign_id=uid('foreign-campaign'), prospect_id=uid('foreign-prospect'),
        sequence_version=1, state='active', next_step=0, next_due_at=LAST.isoformat())
    add(s, 'sequence_steps', id=uid('foreign-step'), business_id=B,
        campaign_id=uid('foreign-campaign'), sequence_version=1, ordinal=0,
        delay_business_days=0, template_text='FOREIGN SECRET', template_hash='foreign',
        allowed_variables='[]', approved_by=uid('foreign-owner'), approved_at=STAMP)


@pytest.fixture
def database(tmp_path):
    # Extract ONLY declarations of columns, never execute PostgreSQL SQL in SQLite.
    # Fixed migration is the schema reference; no SQL against any external DB.
    migration = (Path(__file__).parents[1] / 'migrations/037_outreach_core.sql').read_text()
    engine = create_engine('sqlite:///' + str(tmp_path / 'out6.sqlite'))
    with Session(engine) as s:
        tables = re.findall(r'CREATE TABLE IF NOT EXISTS public\.(outreach_\w+) \(\n(.*?)\n\);',
                            migration, re.S)
        assert len(tables) == 17
        for name, body in tables:
            cols = []
            for line in body.splitlines():
                match = re.match(r'  ([a-z_]+) (uuid|text\[\]|text|jsonb|integer|boolean|numeric|timestamptz|date)\b', line)
                if match:
                    col, kind = match.groups()
                    affinity = 'NUMERIC' if kind in ('integer', 'boolean', 'numeric') else 'TEXT'
                    cols.append(f'{col} {affinity}' + (' PRIMARY KEY' if col == 'id' else ''))
            s.execute(text(f"CREATE TABLE {name} ({','.join(cols)})"))
        for ddl in (
            'CREATE TABLE businesses (id TEXT PRIMARY KEY, plan_tier TEXT, feature_flags TEXT, subscription_status TEXT, is_active BOOLEAN, trial_ends_at TIMESTAMP)',
            'CREATE TABLE aria_actions (id TEXT PRIMARY KEY, business_id TEXT, proposed_by TEXT, action_type TEXT, payload TEXT, status TEXT CHECK (status IN ("proposed","executing","done","failed","dismissed","expired")), expires_at TIMESTAMP, error TEXT, result TEXT, created_at TIMESTAMP, updated_at TIMESTAMP, approved_by TEXT, approved_at TIMESTAMP, executed_at TIMESTAMP)',
            'CREATE TABLE email_accounts (id TEXT PRIMARY KEY, business_id TEXT, user_id TEXT, provider TEXT, email_address TEXT, display_name TEXT, capabilities TEXT, is_default BOOLEAN, token_ciphertext TEXT, refresh_token_ciphertext TEXT, token_expires_at TEXT, smtp_config TEXT, created_at TEXT, updated_at TEXT)',
            'CREATE TABLE email_messages (id TEXT PRIMARY KEY, business_id TEXT, email_account_id TEXT, provider_message_id TEXT, provider_thread_id TEXT, folder TEXT, from_email TEXT, from_name TEXT, to_emails TEXT, cc_emails TEXT, raw_headers TEXT, subject TEXT, snippet TEXT, body_text TEXT, received_at TIMESTAMP, created_at TIMESTAMP, updated_at TIMESTAMP)',
            'CREATE TABLE email_outbox (id TEXT PRIMARY KEY, business_id TEXT, email_account_id TEXT, invoice_id TEXT, chase_stage INTEGER, to_emails TEXT, subject TEXT, body_preview TEXT, provider_message_id TEXT, status TEXT, error TEXT, sent_at TEXT, created_at TEXT)',
            'CREATE TABLE usage_meters (business_id TEXT, meter TEXT, period TEXT, value NUMERIC, updated_at TEXT, UNIQUE(business_id,meter,period))',
            'CREATE TABLE business_settings (business_id TEXT PRIMARY KEY, settings TEXT)',
            'CREATE TABLE business_members (id TEXT, business_id TEXT, user_id TEXT, role TEXT, is_active BOOLEAN)',
            'CREATE UNIQUE INDEX operation_once ON outreach_usage_events (business_id, operation_key, kind)',
            'CREATE UNIQUE INDEX logical_once ON outreach_dispatch_jobs (business_id, logical_key)',
            'CREATE UNIQUE INDEX message_once ON outreach_messages (business_id, idempotency_key)',
            'CREATE UNIQUE INDEX daily_once ON outreach_daily_usage (business_id, scope_type, scope_id, local_date)',
        ):
            s.execute(text(ddl))
        seed(s)
        insert(s, 'businesses', id=A, plan_tier='business', feature_flags='{}', subscription_status='active', is_active=True)
        insert(s, 'business_settings', business_id=A, settings='{}')
        s.commit()
    yield engine
    engine.dispose()


@pytest.fixture
def h(database, monkeypatch, request):
    def forbidden(*args, **kwargs):
        raise AssertionError('OUT-6 tests must never use network or generic email sender')

    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setenv('OUTREACH_SUPPRESSION_SECRET', 'synthetic-key-' * 4)
    monkeypatch.setenv('OUTREACH_UNSUBSCRIBE_BASE_URL', 'https://example.invalid/unsubscribe')
    module = importlib.import_module('services.outreach_send')
    from services import aria_actions as actions
    import assistant_tools
    monkeypatch.setattr(assistant_tools, '_send_email', forbidden)
    monkeypatch.setattr(actions, 'now', lambda: NOW)
    monkeypatch.setattr(module, 'now', lambda: NOW)
    business = SimpleNamespace(id=A, name='Synthetic', timezone='Europe/London', plan_tier='business',
                               feature_flags={}, subscription_status='active', is_active=True,
                               trial_ends_at=None)
    fake = FakeProvider(database)
    # Proposed seam, no replacement of builder/claim/metering/eligibility code.
    monkeypatch.setattr(module, 'get_provider_for_account', lambda account: fake)
    with Session(database) as session:
        api = LocalActions(module, actions)
        if 'real_aria_actions' in request.fixturenames:
            if 'send_outreach' not in actions.ACTION_TYPES:
                raise MissingSharedHook('shared registration absent')
            api = actions
        yield SimpleNamespace(s=session, engine=database, m=module, a=api, b=business, p=fake)


class LocalActions:
    """Test-only transaction seam; never installed in production aria_actions.

    Exercises real builder/search/claim/dispatcher. Shared-hook-specific tests
    below still use real aria_actions and strictly await Claude's registration.
    """
    def __init__(self, module, actions):
        self.module, self.actions = module, actions
        self.ActionRefused = actions.ActionRefused
        self.version_of = actions.version_of
        self.now = actions.now

    def propose(self, session, business, user_id, action_type, args, **kwargs):
        try:
            payload = self.module.build_payload(session, business, args, kwargs.get('owner_name'))
        except self.ActionRefused as exc:
            session.rollback()
            return {'error': exc.detail}
        aid = str(uuid.uuid4())
        insert(session, 'aria_actions', id=aid, business_id=str(business.id),
               proposed_by=user_id, action_type=action_type, payload=json.dumps(payload),
               status='proposed', expires_at=payload['expires_at'], created_at=self.module.now())
        session.commit()
        return {'proposal': {'id': aid, 'preview': payload, 'version': self.version_of(payload)}}

    def approve(self, session, business, action_id, user_id, version=None):
        try:
            row = self.module.one(session, 'aria_actions', business.id, action_id)
            payload = json.loads(row['payload'])
            self.module.require(row['status'] == 'proposed' and user_id and version == self.version_of(payload))
            self.module.search_before_claim(session, business, action_id=action_id, payload=payload)
            self.module.prepare_claim(session, business, action_id=action_id, payload=payload,
                                      user_id=user_id, version=version, moment=self.module.now())
            changed = session.execute(text("UPDATE aria_actions SET status='executing' WHERE id=:id AND business_id=:b AND status='proposed' AND payload=:p"),
                                      {'id': action_id, 'b': str(business.id), 'p': row['payload']})
            self.module.require(changed.rowcount == 1)
            session.commit()
        except Exception:
            session.rollback()
            raise
        return self.module.dispatch(session, business, action_id=action_id, payload=payload)


class FakeProvider:
    def __init__(self, engine):
        self.engine = engine
        self.searches, self.sends = [], []
        self.replies = []
        self.search_error = None
        self.outcome = 'accepted'
        self.message_id = 'accepted-id'
        self.during_send = None

    def search_from(self, *, account, senders, since):
        self.searches.append((str(account.id), senders, since))
        if self.search_error:
            raise self.search_error
        return self.replies

    def send_outreach(self, *, account, **message):
        # A separate connection must see BOTH durable claim and capacity before I/O.
        with Session(self.engine) as s:
            assert s.execute(text("SELECT count(*) FROM aria_actions WHERE status='executing'")).scalar() == 1
            assert s.execute(text("SELECT count(*) FROM outreach_usage_events WHERE state='reserved'")).scalar() == 1
            assert s.execute(text("SELECT count(*) FROM outreach_dispatch_jobs WHERE status='claimed'")).scalar() == 1
        self.sends.append((str(account.id), message))
        if self.during_send:
            self.during_send()
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return dict(outcome=self.outcome, mailbox_id=str(account.id), provider=account.provider,
                    provider_message_id=self.message_id, provider_thread_id='thread' if self.message_id else None,
                    rfc_message_id=message['rfc_message_id'], accepted_at=STAMP,
                    error_code='rejected' if self.outcome == 'definitely_not_accepted' else None)


def propose(h, **changes):
    args = dict(campaign_id=CAMPAIGN, enrolment_id=ENROLMENT, step_id=STEP)
    args.update(changes)
    result = h.a.propose(h.s, h.b, OWNER, 'send_outreach', args, owner_name='Owner')
    assert 'proposal' in result, result
    assert not h.p.sends
    return result['proposal']


def approve(h, card, **kwargs):
    return h.a.approve(h.s, h.b, card['id'], kwargs.get('user_id', OWNER),
                       version=kwargs.get('version', card['version']))


def change(h, table, **fields):
    h.s.execute(text(f"UPDATE {table} SET " + ','.join(f'{k}=:{k}' for k in fields)
                     + ' WHERE business_id=:bid'), dict(fields, bid=A))
    h.s.commit()


def refused(h, card, **kwargs):
    with pytest.raises(h.a.ActionRefused) as exc:
        approve(h, card, **kwargs)
    assert exc.value.status_code in (403, 404, 409, 422)
    assert not h.p.sends
    assert h.s.execute(text('SELECT count(*) FROM outreach_usage_events')).scalar() == 0
    assert h.s.execute(text("SELECT count(*) FROM aria_actions WHERE status='executing'")).scalar() == 0


def test_campaign_mailbox_overrides_newest_business_and_brand_default(h):
    card = propose(h)
    payload = card['preview']
    assert payload['mailbox_id'] == BOX
    assert payload['campaign_version'] == payload['sequence_version'] == 1
    assert payload['prospect_id'] == PROSPECT
    assert payload['to'] == EMAIL
    assert payload['idempotency_key']
    assert 'automation' not in payload
    assert approve(h, card)['status'] == 'done'
    assert h.p.sends[0][0] == BOX
    assert h.s.execute(text('SELECT email_account_id FROM email_outbox')).scalar() == BOX
    assert h.s.execute(text("SELECT mailbox_id FROM outreach_messages WHERE state='accepted'")).scalar() == BOX


@pytest.mark.parametrize('field', ['campaign_id', 'enrolment_id', 'step_id', 'mailbox_id'])
def test_foreign_or_injected_identity_cannot_build_card(h, field):
    args = dict(campaign_id=CAMPAIGN, enrolment_id=ENROLMENT, step_id=STEP)
    args[field] = {'campaign_id': uid('foreign-campaign'),
                   'enrolment_id': uid('foreign-enrolment'),
                   'step_id': uid('foreign-step'), 'mailbox_id': FOREIGN}[field]
    result = h.a.propose(h.s, h.b, OWNER, 'send_outreach', args)
    assert 'error' in result
    assert 'FOREIGN SECRET' not in json.dumps(result)
    assert not h.p.searches and not h.p.sends


@pytest.mark.parametrize('table,fields', [
    ('outreach_campaigns', {'mailbox_id': FOREIGN}),
    ('outreach_campaigns', {'status': 'paused'}),
    ('outreach_campaigns', {'version': 2}),
    ('outreach_campaigns', {'target_hash': 'edited'}),
    ('outreach_settings', {'pause_all': True}),
    ('outreach_enrolments', {'takeover_at': STAMP}),
    ('outreach_enrolments', {'state': 'replied'}),
    ('outreach_prospects', {'eligibility': 'blocked'}),
    ('outreach_prospects', {'subscriber_type': 'individual'}),
    ('outreach_prospects', {'subscriber_type': 'unknown'}),
    ('outreach_prospects', {'email': 'changed@example.invalid', 'email_key': 'changed'}),
    ('outreach_prospects', {'retention_due_at': LAST.isoformat()}),
    ('outreach_compliance', {'decision': 'rejected'}),
    ('outreach_compliance', {'review_due_at': LAST.isoformat()}),
    ('outreach_evidence', {'verification_status': 'accept_all'}),
    ('outreach_evidence', {'expires_at': LAST.isoformat()}),
    ('outreach_mailboxes', {'enabled': False}),
    ('outreach_mailboxes', {'health_status': 'unknown'}),
    ('outreach_mailboxes', {'health_checked_at': LAST.isoformat()}),
    ('outreach_sequence_steps', {'template_hash': 'edited'}),
])
def test_approval_rechecks_current_scoped_state(h, table, fields):
    card = propose(h)
    change(h, table, **fields)
    refused(h, card)


def test_disconnected_campaign_mailbox_never_falls_back(h):
    card = propose(h)
    h.s.execute(text('DELETE FROM email_accounts WHERE id=:id'), {'id': BOX})
    h.s.commit()
    refused(h, card)
    assert not h.p.searches


@pytest.mark.parametrize('key_type,key', [('email', KEY), ('domain', 'domain-key')])
def test_tenant_wide_suppression_added_after_proposal_blocks(h, monkeypatch, key_type, key):
    # Proposed deterministic tenant digest seam, production secret never loaded.
    monkeypatch.setattr(h.m, 'suppression_digest', lambda business_id, kind, value: KEY if kind == 'email' else 'domain-key')
    card = propose(h)
    add(h.s, 'suppressions', key_type=key_type, key_digest=key, digest_version=1,
        reason='objection', suppressed_at=STAMP)
    h.s.commit()
    refused(h, card)


def test_other_tenant_suppression_does_not_block(h, monkeypatch):
    monkeypatch.setattr(h.m, 'suppression_digest', lambda *args: KEY)
    add(h.s, 'suppressions', business_id=B, key_type='email', key_digest=KEY,
        digest_version=1, reason='objection', suppressed_at=STAMP)
    h.s.commit()
    assert approve(h, propose(h))['status'] == 'done'


def test_reply_search_at_approval_blocks_even_unclassified_reply(h):
    card = propose(h)
    h.p.replies = [SimpleNamespace(provider_message_id='reply', provider_thread_id='unrelated-thread',
                                  from_email=EMAIL, received_at=NOW, body_text=None)]
    refused(h, card)
    assert h.p.searches[-1][0:2] == (BOX, [EMAIL])


def test_complete_search_failure_is_not_an_empty_inbox(h):
    card = propose(h)
    h.p.search_error = RuntimeError('incomplete pagination')
    refused(h, card)


@pytest.mark.parametrize('version', [None, '', 'wrong-version'])
@HOOK
def test_version_is_mandatory(h, version):
    refused(h, propose(h), version=version)


@HOOK
def test_edited_card_invalidates_old_approval(h):
    card = propose(h)
    updated = h.a.edit(h.s, h.b, card['id'], {'body': 'Owner edited copy'})
    assert updated['version'] != card['version']
    refused(h, card)


@HOOK
def test_expired_card(h):
    card = propose(h)
    change(h, 'aria_actions', expires_at=LAST)
    refused(h, card)


@HOOK
def test_no_null_owner_even_with_forged_standing_permission(h):
    card = propose(h)
    payload = dict(card['preview'], automation='outreach_sequence', authority_snapshot={'enabled': True})
    change(h, 'aria_actions', payload=json.dumps(payload))
    change(h, 'business_settings', settings=json.dumps({'automations': {'outreach_sequence': {'enabled': True}}}))
    refused(h, card, user_id=None, version=h.a.version_of(payload))


def test_entitlement_revoked_after_proposal(h):
    card = propose(h)
    h.s.execute(text('UPDATE businesses SET feature_flags=:flags WHERE id=:b'), {'flags': json.dumps({'outreach': False}), 'b': A})
    h.s.commit()
    refused(h, card)


def test_daily_cap_includes_accepted_reserved_and_unknown(h):
    card = propose(h)
    add(h.s, 'daily_usage', scope_type='mailbox', scope_id=BOX,
        local_date='2026-10-23', accepted=3, reserved=1, unknown=1)
    h.s.commit()
    refused(h, card)


# OUT-18 (Mike, Option A): 20 new emails a day PER BRAND, not per business.

def sent_today(h, n, brand, *, states=('committed',), day='2026-10-23'):
    """n outreach emails already held or sent today for `brand`, from a
    campaign on another mailbox (so only the brand's count is affected)."""
    campaign = add(h.s, 'campaigns', brand_id=brand, mailbox_id=DEFAULT, name=f'Other {brand[:4]}',
                   target_rules='{}', target_hash='other', sequence_version=1, version=1,
                   status='ready', timezone='Europe/London', daily_cap=20)
    for i in range(n):
        message = add(h.s, 'messages', campaign_id=campaign, mailbox_id=DEFAULT, direction='outbound',
                      state='accepted')
        add(h.s, 'usage_events', operation_key=f'{campaign}:{i}', kind='outreach_emails_sent', quantity=1,
            state=states[i % len(states)], mailbox_id=DEFAULT, local_send_date=day, message_id=message,
            period_start=STAMP, period_end=STAMP)
    h.s.commit()


def refused_today(h, card, already):
    with pytest.raises(h.a.ActionRefused) as exc:
        approve(h, card)
    assert exc.value.status_code in (403, 404, 409, 422)
    assert not h.p.sends
    assert h.s.execute(text('SELECT count(*) FROM outreach_usage_events')).scalar() == already


def test_a_brand_with_twenty_emails_today_sends_no_more(h):
    card = propose(h)
    sent_today(h, 20, BRAND, states=('committed', 'reserved', 'unknown'))
    refused_today(h, card, 20)


def test_another_brands_twenty_never_uses_up_this_brands_day(h):
    card = propose(h)
    other = uid('other-brand')
    add(h.s, 'brands', id=other, name='FitFutures', privacy_url='https://example.invalid/p2',
        sender_identity='FitFutures', version=1)
    sent_today(h, 20, other)
    add(h.s, 'daily_usage', scope_type='business', scope_id=A, local_date='2026-10-23', accepted=20,
        reserved=0, unknown=0)
    h.s.commit()
    assert approve(h, card)['status'] == 'done'
    assert len(h.p.sends) == 1


def test_released_emails_never_count_toward_a_brands_day(h):
    card = propose(h)
    sent_today(h, 20, BRAND, states=('released',))
    assert approve(h, card)['status'] == 'done'


def test_the_owners_lower_daily_limit_applies_to_each_brand(h):
    card = propose(h)
    change(h, 'outreach_settings', business_daily_cap=5)
    sent_today(h, 5, BRAND)
    refused_today(h, card, 5)


# OUT-18 (Mike, 25 Oct 2026): the monthly allowance is PER BRAND — its daily
# limit times the UK weekdays in the month — so no brand runs out mid-campaign.
OCT_2026_WEEKDAYS = sum(1 for d in range(1, 32) if datetime(2026, 10, d).weekday() < 5)   # 22


def test_the_business_wide_500_no_longer_stops_a_brand(h):
    card = propose(h)
    insert(h.s, 'usage_meters', business_id=A, meter='outreach_emails_sent', period='2026-10',
           value=500, updated_at=STAMP)
    h.s.commit()
    assert approve(h, card)['status'] == 'done'


def test_a_brand_at_its_monthly_allowance_sends_no_more(h):
    card = propose(h)
    sent_today(h, 20 * OCT_2026_WEEKDAYS, BRAND, day='2026-10-01')
    refused_today(h, card, 20 * OCT_2026_WEEKDAYS)


def test_a_brand_one_short_of_its_monthly_allowance_can_still_send(h):
    card = propose(h)
    sent_today(h, 20 * OCT_2026_WEEKDAYS - 1, BRAND, day='2026-10-01')
    assert approve(h, card)['status'] == 'done'


def test_last_months_sends_never_count_toward_this_months_allowance(h):
    card = propose(h)
    sent_today(h, 20 * OCT_2026_WEEKDAYS, BRAND, day='2026-09-30')
    assert approve(h, card)['status'] == 'done'


def test_another_brands_full_month_never_stops_this_brand(h):
    card = propose(h)
    other = uid('other-brand')
    add(h.s, 'brands', id=other, name='FitFutures', privacy_url='https://example.invalid/p2',
        sender_identity='FitFutures', version=1)
    sent_today(h, 20 * OCT_2026_WEEKDAYS, other, day='2026-10-01')
    assert approve(h, card)['status'] == 'done'


@pytest.mark.parametrize('day,first,following,weekdays', [
    ('2026-10-23', '2026-10-01', '2026-11-01', 22),
    ('2026-12-31', '2026-12-01', '2027-01-01', 23),     # December rolls into the next year
    ('2026-02-14', '2026-02-01', '2026-03-01', 20),     # a 28-day month
    ('2028-02-29', '2028-02-01', '2028-03-01', 21),     # a leap-year February
    ('2026-11-01', '2026-11-01', '2026-12-01', 21),     # the first day of a month starting on a Sunday
])
def test_month_bounds_and_weekdays(day, first, following, weekdays):
    from datetime import date
    from services.metering import month_bounds
    got = month_bounds(date.fromisoformat(day))
    assert (got[0].isoformat(), got[1].isoformat(), got[2]) == (first, following, weekdays)


@pytest.mark.parametrize('states', [('reserved',), ('unknown',), ('committed', 'reserved', 'unknown')])
def test_held_and_unknown_emails_count_toward_the_monthly_allowance(h, states):
    card = propose(h)
    sent_today(h, 20 * OCT_2026_WEEKDAYS, BRAND, states=states, day='2026-10-02')
    refused_today(h, card, 20 * OCT_2026_WEEKDAYS)


def test_released_emails_never_count_toward_the_monthly_allowance(h):
    card = propose(h)
    sent_today(h, 20 * OCT_2026_WEEKDAYS, BRAND, states=('released',), day='2026-10-02')
    assert approve(h, card)['status'] == 'done'


def test_the_last_day_of_the_month_counts_and_the_next_month_does_not(h):
    card = propose(h)
    sent_today(h, 20 * OCT_2026_WEEKDAYS - 1, BRAND, day='2026-10-31')
    sent_today(h, 50, BRAND, day='2026-11-01')
    assert approve(h, card)['status'] == 'done'          # 439 counted; November ignored
    assert h.s.execute(text("SELECT count(*) FROM outreach_usage_events WHERE local_send_date >= '2026-10-01' "
                            "AND local_send_date < '2026-11-01' AND state IN ('reserved','committed','unknown')")
                       ).scalar() == 20 * OCT_2026_WEEKDAYS


def test_a_brand_whose_month_filled_on_its_last_day_is_refused(h):
    """Codex C review 4: the 31st is inside the month."""
    card = propose(h)
    sent_today(h, 20 * OCT_2026_WEEKDAYS, BRAND, day='2026-10-31')
    with pytest.raises(h.a.ActionRefused) as exc:
        approve(h, card)
    assert "Monthly outreach allowance for this brand" in str(exc.value.detail)
    assert not h.p.sends


def test_the_owners_lower_daily_limit_lowers_the_monthly_allowance_too(h):
    card = propose(h)
    change(h, 'outreach_settings', business_daily_cap=5)
    sent_today(h, 5 * OCT_2026_WEEKDAYS, BRAND, day='2026-10-01')
    refused_today(h, card, 5 * OCT_2026_WEEKDAYS)


@pytest.mark.parametrize('moment,allowed', [
    ('2026-10-23T07:59:59+00:00', False), ('2026-10-23T08:00:00+00:00', True),
    ('2026-10-23T15:59:59+00:00', True), ('2026-10-23T16:00:00+00:00', False),
    ('2026-10-24T11:00:00+00:00', False), ('2026-10-26T08:59:59+00:00', False),
    ('2026-10-26T09:00:00+00:00', True),
])
def test_uk_weekday_window_and_dst(h, monkeypatch, moment, allowed):
    at = datetime.fromisoformat(moment)
    monkeypatch.setattr(h.a, 'now', lambda: at)
    monkeypatch.setattr(h.m, 'now', lambda: at)
    change(h, 'outreach_mailboxes', health_checked_at=at.isoformat())
    change(h, 'outreach_evidence', verified_at=at.isoformat(), fetched_at=at.isoformat())
    change(h, 'outreach_compliance', reviewed_at=at.isoformat())
    card = propose(h)
    if allowed:
        assert approve(h, card)['status'] == 'done'
    else:
        refused(h, card)


@HOOK
def test_double_approval_during_transport_and_after_completion(h):
    card = propose(h)
    def second_tap():
        with Session(h.engine) as other:
            with pytest.raises(h.a.ActionRefused):
                h.a.approve(other, h.b, card['id'], OWNER, version=card['version'])
    h.p.during_send = second_tap
    approve(h, card)
    second_tap()
    assert len(h.p.sends) == 1
    assert h.s.execute(text('SELECT count(*) FROM outreach_usage_events')).scalar() == 1
    assert h.s.execute(text("SELECT value FROM usage_meters WHERE meter='outreach_emails_sent'")).scalar() == 1


@pytest.mark.parametrize('outcome', ['unknown', TimeoutError('ambiguous timeout')])
def test_unknown_outcome_retains_capacity_and_never_retries(h, outcome):
    card = propose(h)
    h.p.outcome = outcome
    assert approve(h, card)['status'] == 'executing'
    assert h.s.execute(text('SELECT state FROM outreach_usage_events')).scalar() == 'unknown'
    assert h.s.execute(text('SELECT state FROM outreach_messages')).scalar() == 'unknown'
    change(h, 'outreach_dispatch_jobs', lease_until=LAST.isoformat())
    with Session(h.engine) as fresh:
        with pytest.raises(h.a.ActionRefused):
            h.a.approve(fresh, h.b, card['id'], OWNER, version=card['version'])
    assert len(h.p.sends) == 1
    assert h.s.execute(text("SELECT sum(unknown) FROM outreach_daily_usage WHERE scope_type='business'")).scalar() == 1


def test_definite_rejection_releases_capacity_without_replaying_card(h):
    card = propose(h)
    h.p.outcome = 'definitely_not_accepted'
    assert approve(h, card)['status'] == 'failed'
    assert h.s.execute(text('SELECT state FROM outreach_usage_events')).scalar() == 'released'
    with pytest.raises(h.a.ActionRefused):
        approve(h, card)
    assert len(h.p.sends) == 1


def test_acceptance_without_provider_id_counts_once(h):
    h.p.message_id = None
    card = propose(h)
    assert approve(h, card)['status'] == 'done'
    assert h.s.execute(text('SELECT state FROM outreach_usage_events')).scalar() == 'committed'
    assert h.s.execute(text("SELECT value FROM usage_meters WHERE meter='outreach_emails_sent'")).scalar() == 1
    with pytest.raises(h.a.ActionRefused):
        approve(h, card)
    assert len(h.p.sends) == 1


def test_claim_hook_reservations_roll_back_if_hook_fails(h, monkeypatch):
    card = propose(h)
    original = h.m.prepare_claim
    def fail_after_reserving(session, business, **kwargs):
        original(session, business, **kwargs)
        assert session.execute(text("SELECT count(*) FROM outreach_usage_events WHERE state='reserved'")).scalar() == 1
        raise h.a.ActionRefused(409, 'Synthetic refusal after reservation')
    monkeypatch.setattr(h.m, 'prepare_claim', fail_after_reserving)
    refused(h, card)
    with Session(h.engine) as other:
        assert other.execute(text('SELECT count(*) FROM outreach_usage_events')).scalar() == 0
        assert other.execute(text("SELECT status FROM aria_actions WHERE id=:id"), {'id': card['id']}).scalar() == 'proposed'


def test_exact_payload_headers_and_opaque_token(h):
    card = propose(h)
    approve(h, card)
    _, sent = h.p.sends[0]
    assert sent['to_emails'] == [EMAIL]
    assert sent['subject'] == card['preview']['subject']
    assert sent['body_text'] == '\n\n'.join(
        card['preview'][part] for part in ('body', 'sign_off', 'footer'))
    assert sent['cc_emails'] == []
    assert sent['headers']['List-Unsubscribe-Post'] == 'List-Unsubscribe=One-Click'
    url = sent['headers']['List-Unsubscribe'].strip('<>')
    assert url.startswith('https://') and EMAIL not in url and KEY not in url
    assert url in sent['body_text']
    token = url.rsplit('/', 1)[-1]
    assert len(token) >= 32
    assert h.s.execute(text('SELECT token_digest FROM outreach_unsubscribe_tokens')).scalar() != token


def test_unsubscribe_get_no_mutation_post_idempotent_and_tenant_scoped(h):
    # Proposed service seam for the public handler; token derives scope, never caller tenant.
    card = propose(h)
    approve(h, card)
    token = h.p.sends[0][1]['headers']['List-Unsubscribe'].strip('<>').rsplit('/', 1)[-1]
    h.m.unsubscribe(h.s, token=token, method='GET')
    assert h.s.execute(text('SELECT count(*) FROM outreach_suppressions')).scalar() == 0
    for _ in range(2):
        h.m.unsubscribe(h.s, token=token, method='POST')
    assert h.s.execute(text('SELECT business_id FROM outreach_suppressions')).scalars().all() == [A]
    assert h.s.execute(text('SELECT state FROM outreach_enrolments')).scalar() == 'suppressed'
    with pytest.raises(h.a.ActionRefused):
        h.m.unsubscribe(h.s, token=token + 'forged', method='POST')
    assert h.s.execute(text('SELECT count(*) FROM outreach_suppressions')).scalar() == 1


def predecessor(h, *, accepted_at=LAST, provider_id='previous-id'):
    add(h.s, 'messages', prospect_id=PROSPECT, campaign_id=CAMPAIGN, mailbox_id=BOX,
        kind='initial', origin='live', direction='outbound', to_emails=json.dumps([EMAIL]),
        cc_emails='[]', subject='Previous', body='Previous', payload_hash='previous', payload_version=1,
        state='accepted', provider='google', provider_message_id=provider_id,
        provider_thread_id='previous-thread' if provider_id else None,
        rfc_message_id='<previous@example.invalid>', accepted_at=accepted_at.isoformat(),
        idempotency_key='previous-operation', authority_snapshot='{}')
    change(h, 'outreach_sequence_steps', ordinal=1, delay_business_days=5)
    change(h, 'outreach_enrolments', next_step=1)
    change(h, 'outreach_prospects', last_contact_at=accepted_at.isoformat(),
           first_contact_at=accepted_at.isoformat(), notice_provided_at=accepted_at.isoformat())


def test_followup_searches_since_actual_predecessor_and_preserves_thread(h):
    predecessor(h)
    card = propose(h)
    approve(h, card)
    box, senders, since = h.p.searches[-1]
    assert (box, senders, since) == (BOX, [EMAIL], LAST)
    sent = h.p.sends[0][1]
    assert sent['provider_thread_id'] == 'previous-thread'
    assert sent['in_reply_to'] == '<previous@example.invalid>'
    assert '<previous@example.invalid>' in sent['references']


def test_uncorrelated_acceptance_blocks_thread_dependent_followup(h):
    predecessor(h, provider_id=None)
    result = h.a.propose(h.s, h.b, OWNER, 'send_outreach',
                         dict(campaign_id=CAMPAIGN, enrolment_id=ENROLMENT, step_id=STEP))
    if 'proposal' in result:
        refused(h, result['proposal'])
    else:
        assert 'error' in result
    assert not h.p.sends


def test_recent_contact_in_another_campaign_blocks_approval(h):
    card = propose(h)
    # Prospect-level latest contact across campaigns, not just current enrolment.
    change(h, 'outreach_prospects', last_contact_at=(NOW - timedelta(days=6)).isoformat())
    refused(h, card)


@pytest.mark.parametrize('provider', ['google', 'microsoft'])
def test_transport_reports_bound_provider_and_immutable_operation(h, provider):
    change(h, 'email_accounts', provider=provider)
    card = propose(h)
    approve(h, card)
    assert h.p.sends[0][1]['operation_key'] == card['preview']['idempotency_key']
    assert h.s.execute(text('SELECT provider FROM outreach_messages')).scalar() == provider


def test_metering_service_owns_reservation_not_parallel_monthly_counter(h, monkeypatch):
    from services import metering
    calls = []
    original = metering.reserve_outreach_usage
    def record(session, business, **kwargs):
        assert session is h.s
        calls.append(kwargs)
        return original(session, business, **kwargs)
    monkeypatch.setattr(metering, 'reserve_outreach_usage', record)
    card = propose(h)
    approve(h, card)
    assert len(calls) == 1
    assert calls[0]['operation_key'] == card['preview']['idempotency_key']


def test_warmup_twenty_requires_owner_health_review(h):
    card = propose(h)
    change(h, 'outreach_mailboxes', warmup_stage=20, daily_cap=20, sending_days=10,
           health_reviewed_by=None, health_reviewed_at=None)
    refused(h, card)


def presearch(h, card):
    return h.m.search_before_claim(h.s, h.b, action_id=card['id'], payload=card['preview'])


def claim(h, card):
    h.m.prepare_claim(h.s, h.b, action_id=card['id'], payload=card['preview'],
                      user_id=OWNER, version=card['version'], moment=h.m.now())


def test_reply_stored_after_search_is_rechecked_under_claim_locks(h):
    card = propose(h)
    presearch(h, card)
    insert(h.s, 'email_messages', id=uid('late-reply'), business_id=A, email_account_id=BOX,
           from_email=EMAIL, received_at=NOW, provider_message_id='late-reply')
    h.s.commit()
    with pytest.raises(h.a.ActionRefused, match='replied'):
        claim(h, card)
    h.s.rollback()
    assert len(h.p.searches) == 1 and not h.p.sends
    assert h.s.execute(text('SELECT count(*) FROM outreach_usage_events')).scalar() == 0


def test_claim_is_database_only_and_caller_rollback_removes_every_hold(h, monkeypatch):
    card = propose(h)
    presearch(h, card)
    def forbidden(*args, **kwargs):
        raise AssertionError('claim must not commit, rollback or access provider')
    with monkeypatch.context() as patch:
        patch.setattr(h.m, 'get_provider_for_account', forbidden)
        patch.setattr(h.s, 'commit', forbidden)
        patch.setattr(h.s, 'rollback', forbidden)
        claim(h, card)
        assert h.s.execute(text("SELECT value FROM usage_meters WHERE meter='outreach_emails_reserved'")).scalar() == 1
    h.s.rollback()
    for table in ('outreach_messages', 'outreach_usage_events', 'outreach_dispatch_jobs', 'outreach_daily_usage', 'usage_meters'):
        assert h.s.execute(text(f'SELECT count(*) FROM {table}')).scalar() == 0
    assert not h.p.sends


def test_claim_without_fresh_search_receipt_fails_closed(h):
    card = propose(h)
    with pytest.raises(h.a.ActionRefused, match='search required'):
        claim(h, card)
    assert not h.p.sends and not h.p.searches


def test_duplicate_logical_cards_cannot_reserve_twice(h):
    first, second = propose(h), propose(h)
    assert first['preview']['idempotency_key'] == second['preview']['idempotency_key']
    assert approve(h, first)['status'] == 'done'
    with pytest.raises(h.a.ActionRefused):
        approve(h, second)
    assert len(h.p.sends) == 1
    assert h.s.execute(text('SELECT count(*) FROM outreach_usage_events')).scalar() == 1


def test_crashed_claim_cannot_be_dispatched_by_restarted_session(h):
    card = propose(h)
    presearch(h, card)
    claim(h, card)
    change(h, 'aria_actions', status='executing')
    with Session(h.engine) as fresh:
        with pytest.raises(h.a.ActionRefused, match='dispatch authority'):
            h.m.dispatch(fresh, h.b, action_id=card['id'], payload=card['preview'])
    assert not h.p.sends
    assert h.s.execute(text("SELECT value FROM usage_meters WHERE meter='outreach_emails_reserved'")).scalar() == 1


def test_unknown_reconciliation_twice_uses_original_month_and_day(h, monkeypatch):
    from services import metering
    card = propose(h)
    h.p.outcome = 'unknown'
    approve(h, card)
    future = datetime(2026, 11, 2, 11, tzinfo=timezone.utc)
    monkeypatch.setattr(h.m, 'now', lambda: future)
    for _ in range(2):
        metering.settle_outreach_usage(h.s, h.b, operation_key=card['preview']['idempotency_key'],
                                      outcome='accepted', evidence={'accepted_at': STAMP})
        h.s.commit()
    assert h.s.execute(text("SELECT period,value FROM usage_meters WHERE meter='outreach_emails_sent'")).all() == [('2026-10', 1)]
    assert h.s.execute(text("SELECT value FROM usage_meters WHERE meter='outreach_emails_reserved'")).scalar() == 0
    assert h.s.execute(text("SELECT local_date,accepted,unknown FROM outreach_daily_usage WHERE scope_type='business'")).all() == [('2026-10-23', 1, 0)]
    assert h.s.execute(text('SELECT sending_days FROM outreach_mailboxes')).scalar() == 1
    assert len(h.p.sends) == 1


def test_acceptance_projection_failure_holds_unknown_without_retry(h, monkeypatch):
    card = propose(h)
    original = h.s.execute
    def fail_projection(statement, *args, **kwargs):
        if str(statement).startswith('INSERT INTO email_outbox'):
            raise RuntimeError('synthetic projection failure')
        return original(statement, *args, **kwargs)
    monkeypatch.setattr(h.s, 'execute', fail_projection)
    assert approve(h, card)['status'] == 'executing'
    assert h.s.execute(text('SELECT state FROM outreach_usage_events')).scalar() == 'unknown'
    assert h.s.execute(text("SELECT value FROM usage_meters WHERE meter='outreach_emails_sent'")).scalar() == 0
    assert h.s.execute(text("SELECT value FROM usage_meters WHERE meter='outreach_emails_reserved'")).scalar() == 1
    with pytest.raises(h.a.ActionRefused):
        approve(h, card)
    assert len(h.p.sends) == 1


def test_exact_address_digest_cannot_be_replaced_by_old_verification(h):
    card = propose(h)
    change(h, 'outreach_prospects', email='replacement@example.invalid')
    # Even a fresh proposal cannot turn evidence about the old email into valid evidence.
    replacement = propose(h)
    assert replacement['version'] != card['version']
    refused(h, replacement)


def test_self_mail_does_not_block_but_is_stored_by_auto2(h):
    card = propose(h)
    h.p.replies = [SimpleNamespace(provider_message_id='self', provider_thread_id=None,
                                  from_email=f'{BOX}@example.invalid', received_at=NOW, body_text=None)]
    assert approve(h, card)['status'] == 'done'
    assert h.s.execute(text('SELECT count(*) FROM email_messages')).scalar() == 1


def test_revoked_unsubscribe_token_cannot_mutate(h):
    card = propose(h)
    token = card['preview']['headers']['List-Unsubscribe'].strip('<>').rsplit('/', 1)[-1]
    change(h, 'outreach_unsubscribe_tokens', revoked_at=STAMP)
    with pytest.raises(h.a.ActionRefused):
        h.m.unsubscribe(h.s, token=token, method='POST')
    assert h.s.execute(text('SELECT count(*) FROM outreach_suppressions')).scalar() == 0


def test_missing_outreach_adapter_refuses_before_reserving(h, monkeypatch):
    card = propose(h)
    monkeypatch.setattr(h.m, 'get_provider_for_account', lambda account: SimpleNamespace(search_from=h.p.search_from))
    refused(h, card)
    assert not h.p.searches


def test_search_crossing_sending_window_refuses(h, monkeypatch):
    card = propose(h)
    def search(**kwargs):
        monkeypatch.setattr(h.m, 'now', lambda: datetime(2026, 10, 23, 16, tzinfo=timezone.utc))
        return []
    monkeypatch.setattr(h.p, 'search_from', search)
    refused(h, card)


@pytest.mark.parametrize('ordinal,delay,age,allowed', [(1, 5, 7, True), (2, 7, 7, False), (2, 7, 11, True)])
def test_both_followup_business_day_delays(h, ordinal, delay, age, allowed):
    predecessor(h, accepted_at=NOW - timedelta(days=age))
    change(h, 'outreach_sequence_steps', ordinal=ordinal, delay_business_days=delay)
    change(h, 'outreach_enrolments', next_step=ordinal)
    card = propose(h)
    if allowed:
        assert approve(h, card)['status'] == 'done'
    else:
        refused(h, card)


def test_fifth_accepted_day_promotes_ten_but_unknown_does_not(h):
    change(h, 'outreach_mailboxes', sending_days=4)
    h.p.outcome = 'unknown'
    card = propose(h)
    approve(h, card)
    assert h.s.execute(text('SELECT sending_days,warmup_stage FROM outreach_mailboxes')).one() == (4, 5)
    from services import metering
    metering.settle_outreach_usage(h.s, h.b, operation_key=card['preview']['idempotency_key'],
                                  outcome='accepted', evidence={})
    h.s.commit()
    assert h.s.execute(text('SELECT sending_days,warmup_stage FROM outreach_mailboxes')).one() == (5, 10)


def test_unsubscribe_cancels_all_unclaimed_cards_for_same_tenant_prospect(h):
    cards = [propose(h), propose(h)]
    token = cards[0]['preview']['headers']['List-Unsubscribe'].strip('<>').rsplit('/', 1)[-1]
    h.m.unsubscribe(h.s, token=token, method='POST')
    assert h.s.execute(text('SELECT status FROM aria_actions WHERE business_id=:b'), {'b': A}).scalars().all() == ['dismissed', 'dismissed']
    assert not h.p.sends


@pytest.mark.parametrize('part', ['subject', 'headers'])
def test_edited_header_injection_refused_even_with_current_card_hash(h, part):
    card = propose(h)
    payload = dict(card['preview'])
    if part == 'subject':
        payload['subject'] = 'Offer\r\nBcc: injected@example.invalid'
    else:
        payload['headers'] = dict(payload['headers'], Bcc='injected@example.invalid')
    change(h, 'aria_actions', payload=json.dumps(payload))
    card.update(preview=payload, version=h.a.version_of(payload))
    refused(h, card)


# ------------------------------------------------ Claude's aria_actions hook ---
# The real NS-B10 path (services.aria_actions), not the LocalActions seam.

def real(h):
    from services import aria_actions
    return aria_actions


def real_propose(h, **kwargs):
    args = dict(campaign_id=CAMPAIGN, enrolment_id=ENROLMENT, step_id=STEP)
    return real(h).propose(h.s, h.b, OWNER, 'send_outreach', args, owner_name='Owner', **kwargs)


def test_hook_owner_approval_sends_once_through_the_real_path(h):
    card = real_propose(h)['proposal']
    done = real(h).approve(h.s, h.b, card['id'], OWNER, version=card['version'])
    assert done['status'] == 'done' and done['result']['outcome'] == 'accepted'
    assert len(h.p.sends) == 1 and len(h.p.searches) == 1
    with pytest.raises(real(h).ActionRefused):
        real(h).approve(h.s, h.b, card['id'], OWNER, version=card['version'])
    assert len(h.p.sends) == 1


def test_hook_chat_and_voice_cannot_raise_an_outreach_card(h):
    acts = real(h)
    assert 'send_outreach' in acts.ACTION_TYPES
    assert 'send_outreach' not in acts.CHAT_ACTION_TYPES
    out = acts.propose_from_chat(A, OWNER, 'send_outreach',
                                 dict(campaign_id=CAMPAIGN, enrolment_id=ENROLMENT, step_id=STEP))
    assert 'error' in out and 'proposal' not in out
    import inspect
    import assistant_chat
    import realtime_voice
    for module in (assistant_chat, realtime_voice):
        assert 'aria_actions.ACTION_TYPES' not in inspect.getsource(module), module.__name__


@pytest.mark.parametrize('extra', [{'automation': 'outreach_sequence'}, {'raised_by': 'outreach_sequence'}])
def test_hook_no_standing_permission_can_raise_an_outreach_card(h, extra):
    out = real_propose(h, **extra)
    assert 'error' in out
    assert h.s.execute(text("SELECT count(*) FROM aria_actions")).scalar() == 0


def test_hook_a_refused_proposal_leaves_nothing_behind(h):
    change(h, 'outreach_settings', owner_cc_default=True, owner_cc_address='bad\r\nBcc: x@example.invalid')
    out = real_propose(h)
    assert 'error' in out
    h.s.commit()  # a later commit on the same session must not persist half a proposal
    assert h.s.execute(text("SELECT count(*) FROM outreach_unsubscribe_tokens")).scalar() == 0
    assert h.s.execute(text("SELECT count(*) FROM aria_actions")).scalar() == 0


def test_hook_only_subject_and_body_are_editable(h):
    acts = real(h)
    card = real_propose(h)['proposal']
    for field in ('to', 'cc', 'footer', 'headers', 'mailbox_id', 'from_email'):
        with pytest.raises(acts.ActionRefused):
            acts.edit(h.s, h.b, card['id'], {field: 'x@example.invalid'})
    with pytest.raises(acts.ActionRefused):
        acts.edit(h.s, h.b, card['id'], {'subject': 'Hi\r\nBcc: x@example.invalid'})
    with pytest.raises(acts.ActionRefused):
        acts.edit(h.s, h.b, card['id'], {'body': '   '})
    edited = acts.edit(h.s, h.b, card['id'], {'subject': 'A better subject', 'body': 'Owner copy'})
    preview = edited['preview']
    assert preview['subject'] == 'A better subject' and preview['body'] == 'Owner copy'
    assert {k: v for k, v in preview.items() if k not in ('subject', 'body')} == \
        {k: v for k, v in card['preview'].items() if k not in ('subject', 'body')}
    done = acts.approve(h.s, h.b, card['id'], OWNER, version=edited['version'])
    assert done['status'] == 'done' and h.p.sends[0][1]['subject'] == 'A better subject'


def test_hook_lost_claim_rolls_back_every_reservation(h, monkeypatch):
    """The card is dismissed after the eligibility claim but before the
    proposed -> executing update: nothing the claim reserved survives."""
    acts = real(h)
    card = real_propose(h)['proposal']
    original = h.m.prepare_claim

    def then_dismissed(session, business, **kwargs):
        original(session, business, **kwargs)
        session.execute(text("UPDATE aria_actions SET status='dismissed' WHERE id=:id"), {'id': card['id']})
    monkeypatch.setattr(h.m, 'prepare_claim', then_dismissed)
    with pytest.raises(acts.ActionRefused):
        acts.approve(h.s, h.b, card['id'], OWNER, version=card['version'])
    assert not h.p.sends
    for table in ('outreach_usage_events', 'outreach_messages', 'outreach_dispatch_jobs'):
        assert h.s.execute(text(f'SELECT count(*) FROM {table}')).scalar() == 0, table
    assert (h.s.execute(text("SELECT coalesce(sum(value),0) FROM usage_meters WHERE meter LIKE 'outreach%'")).scalar() or 0) == 0
    assert h.s.execute(text('SELECT status FROM aria_actions')).scalar() == 'proposed'


def test_hook_an_unknown_outcome_stays_executing_and_is_never_retried(h):
    acts = real(h)
    h.p.outcome = TimeoutError('ambiguous')
    card = real_propose(h)['proposal']
    out = acts.approve(h.s, h.b, card['id'], OWNER, version=card['version'])
    assert out['status'] == 'executing'
    with pytest.raises(acts.ActionRefused):
        acts.approve(h.s, h.b, card['id'], OWNER, version=card['version'])
    assert len(h.p.sends) == 1


def test_hook_generic_email_bookkeeping_is_never_used(h, monkeypatch):
    acts = real(h)

    def forbidden(*a, **k):
        raise AssertionError('outreach must bypass the generic email path')
    monkeypatch.setattr(acts, '_execute', forbidden)
    monkeypatch.setattr(acts, '_bookkeep_email', forbidden)
    card = real_propose(h)['proposal']
    assert acts.approve(h.s, h.b, card['id'], OWNER, version=card['version'])['status'] == 'done'


# ------------------------------------------- only the owner approves (P1) ---

def _member(h, user, bid=A, role='owner', active=True):
    insert(h.s, 'business_members', business_id=bid, user_id=user, role=role, is_active=active)
    h.s.commit()


@pytest.mark.parametrize('who', ['staff', 'inactive_owner', 'platform_admin', 'other_business_owner'])
def test_hook_only_an_active_owner_of_this_business_approves(h, who):
    acts = real(h)
    card = real_propose(h)['proposal']
    user = STAFF
    if who == 'inactive_owner':
        user = uid('former-owner')
        _member(h, user, active=False)
    elif who == 'platform_admin':
        user = uid('platform-admin')  # authenticated, but no membership of A
    elif who == 'other_business_owner':
        user = uid('owner-of-b')
        _member(h, user, bid=B)
    with pytest.raises(acts.ActionRefused) as exc:
        acts.approve(h.s, h.b, card['id'], user, version=card['version'])
    assert exc.value.status_code == 403
    assert not h.p.sends and not h.p.searches, 'refused before the mailbox is searched'
    assert h.s.execute(text('SELECT count(*) FROM outreach_usage_events')).scalar() == 0
    assert h.s.execute(text("SELECT status FROM aria_actions")).scalar() == 'proposed'


def test_hook_ownership_removed_during_the_search_stops_the_claim(h):
    acts = real(h)
    card = real_propose(h)['proposal']
    original = h.p.search_from

    def demoted(**kwargs):
        with Session(h.engine) as other:
            other.execute(text("UPDATE business_members SET role='member' WHERE user_id=:u"), {'u': OWNER})
            other.commit()
        return original(**kwargs)
    h.p.search_from = demoted
    with pytest.raises(acts.ActionRefused):
        acts.approve(h.s, h.b, card['id'], OWNER, version=card['version'])
    assert not h.p.sends
    assert h.s.execute(text('SELECT count(*) FROM outreach_usage_events')).scalar() == 0
