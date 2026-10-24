"""OUT-6 — owner-approved outreach on real PostgreSQL, with real concurrency.

SQLite cannot show what two sessions do at once, nor what 037's native types,
composite foreign keys and version triggers accept. These run the REAL
services.aria_actions -> outreach_send path against the local Supabase
Postgres from `scripts/rls-local.sh up` with 035, 036 and 037 replayed
(skipped without RLS_LOCAL_DATABASE_URL; loopback only; synthetic rows only,
torn down). The provider is a fake: nothing is ever sent.
"""

import hashlib
import hmac
import json
import os
import threading
import uuid
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest

DATABASE_URL = os.getenv("RLS_LOCAL_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="RLS_LOCAL_DATABASE_URL is not set: `scripts/rls-local.sh up`, then run this file. "
           "A skip here is a skip, not a pass.",
)

if DATABASE_URL:
    _host = urlparse(DATABASE_URL).hostname
    if _host not in ("127.0.0.1", "localhost", "::1"):
        raise RuntimeError(f"REFUSING TO RUN: RLS_LOCAL_DATABASE_URL points at {_host!r}. Loopback only.")

from sqlalchemy import create_engine, text  # noqa: E402
from sqlmodel import Session  # noqa: E402

import test_outreach_send as base  # noqa: E402
from test_outreach_send import A, B, OWNER, STAFF, CAMPAIGN, STEP, ENROLMENT, LIA, NOW, STAMP  # noqa: E402

SECRET = "synthetic-key-" * 4
TABLES = ("outreach_reply_slots", "outreach_dispatch_jobs", "outreach_usage_events",
          "outreach_daily_usage", "outreach_replies", "outreach_messages", "outreach_knowledge",
          "outreach_unsubscribe_tokens",
          "outreach_suppressions", "outreach_enrolments", "outreach_sequence_steps",
          "outreach_campaigns", "outreach_evidence", "outreach_prospects", "outreach_compliance",
          "outreach_mailboxes", "outreach_brands", "outreach_settings")


def _teardown(engine):
    with engine.begin() as c:
        for bid in (A, B):
            for t in TABLES:
                if c.execute(text("SELECT to_regclass(:t)"), {"t": "public." + t}).scalar():
                    c.execute(text(f"DELETE FROM public.{t} WHERE business_id = :b"), {"b": bid})
            c.execute(text("DELETE FROM public.aria_actions WHERE business_id = :b"), {"b": bid})
            for t in ("email_outbox", "email_messages", "email_accounts", "usage_meters",
                      "business_settings", "business_members"):
                c.execute(text(f"DELETE FROM public.{t} WHERE business_id = :b"), {"b": bid})
            c.execute(text("DELETE FROM public.businesses WHERE id = :b"), {"b": bid})
        c.execute(text("DELETE FROM auth.users WHERE id IN (:u, :s)"), {"u": OWNER, "s": STAFF})


@pytest.fixture
def pg(monkeypatch):
    engine = create_engine(DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1),
                           pool_size=8)
    with engine.connect() as c:
        if not c.execute(text("SELECT to_regclass('public.outreach_messages')")).scalar():
            pytest.skip("037 is not replayed in the local harness")
    _teardown(engine)
    with Session(engine) as s:
        for user, mail in ((OWNER, "out6-owner@example.invalid"), (STAFF, "out6-staff@example.invalid")):
            s.execute(text("INSERT INTO auth.users (id, email, aud, role) VALUES "
                           "(:u, :m, 'authenticated', 'authenticated')"), {"u": user, "m": mail})
        for bid, name in ((A, "Out6 A"), (B, "Out6 B")):
            s.execute(text("INSERT INTO public.businesses (id, name, api_key, plan_tier, subscription_status, "
                           "is_active, feature_flags) VALUES (:b, :n, :k, 'business', 'active', true, '{}'::jsonb)"),
                      {"b": bid, "n": name, "k": f"out6-{uuid.uuid4()}"})
            s.execute(text("INSERT INTO public.business_settings (business_id, settings) VALUES (:b, '{}'::jsonb)"),
                      {"b": bid})
        base.seed(s, foreign=False)
        s.commit()
    monkeypatch.setenv("OUTREACH_SUPPRESSION_SECRET", SECRET)
    monkeypatch.setenv("OUTREACH_UNSUBSCRIBE_BASE_URL", "https://example.invalid/unsubscribe")
    from services import aria_actions, outreach_send
    monkeypatch.setattr(aria_actions, "now", lambda: NOW)
    monkeypatch.setattr(outreach_send, "now", lambda: NOW)
    fake = base.FakeProvider(engine)
    monkeypatch.setattr(outreach_send, "get_provider_for_account", lambda account: fake)
    business = SimpleNamespace(id=A, name="Out6 A", timezone="Europe/London", plan_tier="business",
                               feature_flags={}, subscription_status="active", is_active=True,
                               trial_ends_at=None)
    try:
        yield SimpleNamespace(engine=engine, a=aria_actions, m=outreach_send, b=business, p=fake)
    finally:
        _teardown(engine)
        engine.dispose()


def _propose(pg, enrolment=ENROLMENT):
    with Session(pg.engine) as s:
        out = pg.a.propose(s, pg.b, OWNER, "send_outreach",
                           dict(campaign_id=CAMPAIGN, enrolment_id=enrolment, step_id=STEP),
                           owner_name="Owner")
    assert "proposal" in out, out
    return out["proposal"]


def _approve(pg, card):
    with Session(pg.engine) as s:
        return pg.a.approve(s, pg.b, card["id"], OWNER, version=card["version"])


def _count(pg, sql, **params):
    with pg.engine.connect() as c:
        return c.execute(text(sql), params).scalar()


def _together(pg, *jobs):
    """Run approvals at once, all arriving at the claim together."""
    gate = threading.Barrier(len(jobs))
    original = pg.m.prepare_claim
    arrived = []

    def gated(session, business, **kwargs):
        arrived.append(1)
        gate.wait(10)  # a broken barrier fails the job: no false comfort
        return original(session, business, **kwargs)
    pg.m.prepare_claim = gated
    results, errors = [], []

    crashed = []

    def run(job):
        try:
            results.append(job())
        except pg.a.ActionRefused as exc:
            errors.append(exc)
        except BaseException as exc:  # noqa: BLE001 - any other end fails the test (review 1)
            crashed.append(exc)
    threads = [threading.Thread(target=run, args=(j,)) for j in jobs]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
    finally:
        pg.m.prepare_claim = original
    assert not any(t.is_alive() for t in threads), "an approval never finished"
    assert not crashed, crashed
    assert len(arrived) == len(jobs), "the approvals never reached the claim together"
    assert len(results) + len(errors) == len(jobs)
    return results, errors


def _second_prospect(pg, email=None):
    """Another synthetic recipient in the same campaign (a fresh address each
    call unless one is given)."""
    email = email or f"second-{uuid.uuid4().hex[:8]}@example.invalid"
    key = hmac.new(SECRET.encode(), f"v1:{A}:email:{email}".encode(), hashlib.sha256).hexdigest()
    prospect, enrolment = str(uuid.uuid4()), str(uuid.uuid4())
    with Session(pg.engine) as s:
        base.add(s, "prospects", id=prospect, company="Second Ltd", name="Second", role="Director",
                 domain="example.invalid", email=email, email_key=key, subscriber_type="corporate",
                 eligibility="eligible", lawful_basis="legitimate_interests", lia_id=LIA, stage="ready",
                 captured_at=base.LAST.isoformat(), evidence_checked_at=STAMP,
                 notice_due_at=(NOW + base.timedelta(days=10)).isoformat(),
                 retention_due_at=(NOW + base.timedelta(days=300)).isoformat())
        base.add(s, "evidence", prospect_id=prospect, source_type="synthetic", operation="verify",
                 source_url="https://example.invalid/team", fact_type="email_verification", fact_value="valid",
                 verification_status="valid", verification_subject_email_key=key, flags="[]",
                 fetched_at=STAMP, verified_at=STAMP, expires_at=(NOW + base.timedelta(days=7)).isoformat())
        base.add(s, "enrolments", id=enrolment, prospect_id=prospect, campaign_id=CAMPAIGN,
                 sequence_version=1, state="active", next_step=0, next_due_at=base.LAST.isoformat())
        s.commit()
    return enrolment


# ------------------------------------------------------------------ tests ---

def test_one_approval_sends_once_and_records_native_types(pg):
    card = _propose(pg)
    done = _approve(pg, card)
    assert done["status"] == "done" and len(pg.p.sends) == 1
    with pg.engine.connect() as c:
        to, kind = c.execute(text("SELECT to_emails, pg_typeof(to_emails)::text FROM outreach_messages "
                                  "WHERE business_id = :b"), {"b": A}).one()
        assert to == [base.EMAIL] and kind == "text[]"
        assert c.execute(text("SELECT value FROM usage_meters WHERE business_id = :b "
                              "AND meter = 'outreach_emails_sent' AND period = '2026-10'"), {"b": A}).scalar() == 1
        assert c.execute(text("SELECT value FROM usage_meters WHERE business_id = :b "
                              "AND meter = 'outreach_emails_reserved' AND period = '2026-10'"), {"b": A}).scalar() == 0
        assert c.execute(text("SELECT state FROM outreach_usage_events WHERE business_id = :b"), {"b": A}).scalar() \
            == "committed"
        assert c.execute(text("SELECT status FROM outreach_dispatch_jobs WHERE business_id = :b"), {"b": A}).scalar() \
            == "completed"


def test_two_taps_on_one_card_at_once_send_once(pg):
    card = _propose(pg)
    results, errors = _together(pg, lambda: _approve(pg, card), lambda: _approve(pg, card))
    assert len(pg.p.sends) == 1, (results, errors)
    assert len(results) == 1 and len(errors) == 1
    assert _count(pg, "SELECT count(*) FROM outreach_usage_events WHERE business_id = :b", b=A) == 1


def test_two_cards_for_the_same_email_at_once_send_once(pg):
    first, second = _propose(pg), _propose(pg)
    results, errors = _together(pg, lambda: _approve(pg, first), lambda: _approve(pg, second))
    assert len(pg.p.sends) == 1, (results, errors)
    assert _count(pg, "SELECT count(*) FROM outreach_dispatch_jobs WHERE business_id = :b", b=A) == 1


def test_the_last_monthly_slot_goes_to_exactly_one(pg):
    other = _second_prospect(pg)
    with pg.engine.begin() as c:
        c.execute(text("INSERT INTO usage_meters (business_id, meter, period, value, updated_at) "
                       "VALUES (:b, 'outreach_emails_sent', '2026-10', 499, now()), "
                       "(:b, 'outreach_emails_reserved', '2026-10', 0, now())"), {"b": A})
    # Steady state: every row the claim touches already exists, so no insert
    # conflict quietly serialises the two approvals; only the locks can.
    with Session(pg.engine) as s:
        for scope, ident in (("business", A), ("mailbox", base.BOX)):
            base.add(s, "daily_usage", scope_type=scope, scope_id=ident, local_date="2026-10-23",
                     reserved=0, accepted=0, unknown=0)
        s.commit()
    one, two = _propose(pg), _propose(pg, enrolment=other)
    results, errors = _together(pg, lambda: _approve(pg, one), lambda: _approve(pg, two))
    assert len(pg.p.sends) == 1, (results, errors)
    assert len(errors) == 1
    assert _count(pg, "SELECT value FROM usage_meters WHERE business_id = :b AND meter = 'outreach_emails_sent' "
                      "AND period = '2026-10'", b=A) == 500


def test_a_lost_claim_rolls_everything_back(pg, monkeypatch):
    card = _propose(pg)
    original = pg.m.prepare_claim

    def then_dismissed(session, business, **kwargs):
        original(session, business, **kwargs)
        session.execute(text("UPDATE aria_actions SET status = 'dismissed' WHERE id = :id"), {"id": card["id"]})
    monkeypatch.setattr(pg.m, "prepare_claim", then_dismissed)
    with pytest.raises(pg.a.ActionRefused):
        _approve(pg, card)
    assert not pg.p.sends
    for table in ("outreach_usage_events", "outreach_messages", "outreach_dispatch_jobs", "outreach_daily_usage"):
        assert _count(pg, f"SELECT count(*) FROM {table} WHERE business_id = :b "
                          + ("AND (reserved > 0 OR accepted > 0 OR unknown > 0)" if table == "outreach_daily_usage" else ""),
                      b=A) == 0, table
    assert (_count(pg, "SELECT coalesce(sum(value), 0) FROM usage_meters WHERE business_id = :b "
                       "AND meter LIKE 'outreach%'", b=A) or 0) == 0
    assert _count(pg, "SELECT status FROM aria_actions WHERE id = :id", id=card["id"]) == "proposed"


def test_unsubscribe_before_approval_stops_the_card(pg):
    card = _propose(pg)
    link = json.loads(json.dumps(card["preview"]))["headers"]["List-Unsubscribe"].strip("<>")
    token = link.rsplit("/", 1)[-1]
    with Session(pg.engine) as s:
        assert pg.m.unsubscribe(s, token=token, method="POST") == {"unsubscribed": True}
    with pytest.raises(pg.a.ActionRefused):
        _approve(pg, card)
    assert not pg.p.sends


def test_a_dismiss_from_another_session_during_the_claim_waits_and_loses(pg, monkeypatch):
    """Review 1: a real second session, not a change inside the approval's
    own transaction. The claim holds the card's row, so the dismiss waits,
    then finds the card already executing."""
    import time
    card = _propose(pg)
    original = pg.m.prepare_claim
    outcome = {}

    def dismiss():
        with Session(pg.engine) as other:
            try:
                pg.a.dismiss(other, pg.b, card["id"])
                outcome["dismissed"] = True
            except pg.a.ActionRefused as exc:
                outcome["refused"] = exc.status_code
    worker = threading.Thread(target=dismiss)

    def claim_then_race(session, business, **kwargs):
        original(session, business, **kwargs)
        worker.start()
        # Proof, not a pause (review 2): wait until Postgres shows the dismiss
        # blocked on a lock held by this approval's own backend.
        mine = session.execute(text("SELECT pg_backend_pid()")).scalar()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with pg.engine.connect() as c:
                blocked = c.execute(text(
                    "SELECT count(*) FROM pg_stat_activity WHERE :me = ANY(pg_blocking_pids(pid))"),
                    {"me": mine}).scalar()
            if blocked:
                break
            time.sleep(0.05)
        assert blocked, "the dismiss never waited on the claim"
        assert "dismissed" not in outcome and "refused" not in outcome
    monkeypatch.setattr(pg.m, "prepare_claim", claim_then_race)
    assert _approve(pg, card)["status"] == "done"
    worker.join(30)
    assert not worker.is_alive() and outcome == {"refused": 409}
    assert len(pg.p.sends) == 1


def test_staff_cannot_approve_on_postgres(pg):
    """STAFF is an active 'member' of A in the shared seed."""
    card = _propose(pg)
    with Session(pg.engine) as s:
        with pytest.raises(pg.a.ActionRefused) as exc:
            pg.a.approve(s, pg.b, card["id"], STAFF, version=card["version"])
    assert exc.value.status_code == 403 and not pg.p.sends and not pg.p.searches
