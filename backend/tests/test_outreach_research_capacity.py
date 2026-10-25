"""OUT-19 D — research sized to what the brand's inbox can email (Mike's
decision 1, docs/OUT-19-TICKET.md). RED: paid research and the collection of
personal data.

"20 a day" means 20 emails per inbox. Follow-ups use part of that, so once
they run research finds about 8 new contacts a day, not a fixed 20. No paid
search is made for contacts who could only wait. Every adapter is faked.
"""
# ruff: noqa: F811 - pytest fixtures imported from test_outreach_setup are parameters by design

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlmodel import Session

from test_outreach_setup import A, OWNER, WORKSPACE, _insert, db  # noqa: F401
from test_outreach_research import NOW, World, count, full_inbox, person, research, run, started
from test_outreach_research_brands import second_brand


@pytest.fixture(autouse=True)
def no_pilot_limit(monkeypatch):
    monkeypatch.setenv("OUTREACH_PILOT_ENROLMENTS", "0")


def queue(db, campaign_id, n, *, step, due=NOW):
    """n contacts already in the campaign at `step`, due at `due`."""
    with Session(db) as s:
        seq = s.execute(text("SELECT sequence_version FROM outreach_campaigns WHERE id = :c"), {"c": campaign_id}).scalar()
        for _ in range(n):
            _insert(s, "outreach_enrolments", id=str(uuid.uuid4()), business_id=A, prospect_id=str(uuid.uuid4()),
                    campaign_id=campaign_id, sequence_version=seq, state="active", next_step=step,
                    next_due_at=due.isoformat(), created_at=NOW.isoformat(), updated_at=NOW.isoformat())
        s.commit()


def room(db, biz, brand):
    with Session(db) as s:
        return research().capacity(s, str(biz.id), brand["id"], NOW)


def kept(out):
    return len(out["accepted"])


# ------------------------------------------------------------- the inbox ---

def test_a_full_inbox_with_nothing_queued_has_room_for_twenty(db):
    biz, brand, lia, campaign = started(db)
    assert room(db, biz, brand)["room"] == 20
    assert kept(run(db, biz, lia, World([[person(i) for i in range(25)]]))) == 20


def test_an_inbox_warming_up_at_five_a_day_gets_five_new_contacts(db):
    biz, brand, lia, campaign = started(db, full=False)          # new inbox: 5 a day
    world = World([[person(i) for i in range(12)]])
    out = run(db, biz, lia, world)
    assert kept(out) == 5
    assert "find up to 10 NEW" in world.briefs[0] and "At least 5 should be named" in world.briefs[0]


def test_follow_ups_due_today_take_their_share_of_the_inbox(db):
    biz, brand, lia, campaign = started(db)
    queue(db, campaign["id"], 12, step=1)                        # 12 second emails due today
    queue(db, campaign["id"], 4, step=2, due=NOW + timedelta(days=3))   # not due today: no share
    assert room(db, biz, brand)["room"] == 8
    assert kept(run(db, biz, lia, World([[person(i) for i in range(20)]]))) == 8


def test_contacts_waiting_for_their_first_email_take_their_share(db):
    biz, brand, lia, campaign = started(db)
    queue(db, campaign["id"], 15, step=0)
    assert kept(run(db, biz, lia, World([[person(i) for i in range(20)]]))) == 5


def test_no_paid_search_when_the_inbox_is_already_full(db):
    biz, brand, lia, campaign = started(db)
    queue(db, campaign["id"], 20, step=1)
    world = World([[person(i) for i in range(20)]])
    out = run(db, biz, lia, world)
    assert world.briefs == [] and out["spend_pence"] == 0 and kept(out) == 0
    assert "already full" in out["stopped"]
    assert count(db, "SELECT count(*) FROM usage_meters WHERE business_id = :b AND meter LIKE 'outreach_research_pence%'") == 0


def test_a_second_run_the_same_day_finds_nothing_more_once_the_room_is_used(db):
    biz, brand, lia, campaign = started(db, full=False)
    run(db, biz, lia, World([[person(i) for i in range(10)]]))
    world = World([[person(100 + i) for i in range(10)]])
    assert kept(run(db, biz, lia, world)) == 0 and world.briefs == []


def test_sends_already_made_today_take_their_share(db):
    biz, brand, lia, campaign = started(db)
    with Session(db) as s:
        for i in range(6):
            message = str(uuid.uuid4())
            _insert(s, "outreach_messages", id=message, business_id=A, prospect_id=str(uuid.uuid4()),
                    campaign_id=campaign["id"], mailbox_id=WORKSPACE, kind="initial", origin="live",
                    direction="outbound", to_emails="[]", cc_emails="[]", subject="s", body="b",
                    payload_hash=f"h{i}", payload_version=1, state="accepted", idempotency_key=f"k{i}",
                    authority_snapshot="{}", created_at=NOW.isoformat(), updated_at=NOW.isoformat())
            _insert(s, "outreach_usage_events", id=str(uuid.uuid4()), business_id=A, operation_key=f"op{i}",
                    kind="outreach_emails_sent", quantity=1, period_start=NOW.isoformat(),
                    period_end=(NOW + timedelta(days=30)).isoformat(), mailbox_id=WORKSPACE, message_id=message,
                    local_send_date=NOW.date().isoformat(), state="released" if i == 5 else "committed",
                    created_at=NOW.isoformat(), updated_at=NOW.isoformat())
        s.commit()
    # A released reservation (it never went) frees its place.
    assert room(db, biz, brand)["sent_today"] == 5 and room(db, biz, brand)["room"] == 15


# ------------------------------------------- nothing that cannot be emailed ---

def test_no_paid_search_for_a_brand_with_no_ready_campaign(db):
    biz, brand, lia, campaign = started(db)
    fit, fit_lia = second_brand(db, biz, inbox=False)
    world = World([[person(i) for i in range(10)]])
    out = run(db, biz, fit_lia, world)
    assert world.briefs == [] and kept(out) == 0 and "no ready campaign" in out["stopped"]


@pytest.mark.parametrize("change", ["health_status = 'fail'", "enabled = 0", "pause_reason = 'DNS'"])
def test_no_paid_search_while_the_inbox_cannot_send(db, change):
    biz, brand, lia, campaign = started(db)
    with Session(db) as s:
        s.execute(text(f"UPDATE outreach_mailboxes SET {change} WHERE mailbox_id = :m"), {"m": WORKSPACE})
        s.commit()
    world = World([[person(i) for i in range(10)]])
    assert kept(run(db, biz, lia, world)) == 0 and world.briefs == []


def test_an_inbox_shared_by_two_brands_is_counted_once(db):
    """Two brands on one inbox share its daily limit, as the send path does."""
    biz, brand, lia, campaign = started(db)
    fit, fit_lia = second_brand(db, biz, inbox=False)
    from test_outreach_research import own_inbox
    box = own_inbox(db, fit, fit_lia, address="shared@fit.example")
    with Session(db) as s:                                       # move FitFutures' campaign onto the same inbox
        s.execute(text("UPDATE outreach_campaigns SET mailbox_id = :w WHERE mailbox_id = :m"), {"w": WORKSPACE, "m": box})
        s.commit()
    assert kept(run(db, biz, lia, World([[person(i) for i in range(20)]]))) == 20
    world = World([[person(100 + i) for i in range(20)]])
    assert kept(run(db, biz, fit_lia, world)) == 0 and world.briefs == []


def test_the_pilot_limit_bounds_what_research_keeps(db, monkeypatch):
    """Decision E keeps 5 contacts per campaign for now: research finds no
    more than can join, and none once the campaign is full."""
    monkeypatch.setenv("OUTREACH_PILOT_ENROLMENTS", "5")
    biz, brand, lia, campaign = started(db)
    queue(db, campaign["id"], 3, step=1, due=NOW + timedelta(days=4))
    assert kept(run(db, biz, lia, World([[person(i) for i in range(20)]]))) == 2
    world = World([[person(100 + i) for i in range(20)]])
    assert kept(run(db, biz, lia, world)) == 0 and world.briefs == []


@pytest.mark.parametrize("raw,expected", [("", 5), ("0", 0), ("12", 12), ("-1", 5), ("lots", 5)])
def test_the_pilot_limit_setting(monkeypatch, raw, expected):
    monkeypatch.setenv("OUTREACH_PILOT_ENROLMENTS", raw)
    assert research().pilot_enrolments() == expected


def test_research_plans_with_the_send_paths_own_warm_up_limit(db):
    """One number for the warm-up limit: the send path asserts it agrees."""
    import inspect
    from services import metering
    assert "mailbox_daily_cap(box, health)" in inspect.getsource(metering.reserve_outreach_usage)
    biz, brand, lia, campaign = started(db, full=False)
    with Session(db) as s:
        box = s.execute(text("SELECT * FROM outreach_mailboxes WHERE mailbox_id = :m"), {"m": WORKSPACE}).mappings().one()
        assert metering.mailbox_daily_cap(box) == 5
    full_inbox(db)
    with Session(db) as s:
        box = s.execute(text("SELECT * FROM outreach_mailboxes WHERE mailbox_id = :m"), {"m": WORKSPACE}).mappings().one()
        assert metering.mailbox_daily_cap(box) == 20


# ------------------------------------------ Codex OUT-19 D review 1 findings ---

def test_retries_never_keep_more_than_the_pilot_places(db, monkeypatch):
    """P1 1: each kept contact takes its place at once, so later attempts in
    the same run see the places already taken."""
    monkeypatch.setenv("OUTREACH_PILOT_ENROLMENTS", "5")
    biz, brand, lia, campaign = started(db)
    out = run(db, biz, lia, World([[person(i) for i in range(3)], [person(10 + i) for i in range(5)],
                                   [person(20 + i) for i in range(5)]]))
    assert kept(out) == 5 and sorted(out["enrolled"]) == sorted(out["accepted"])
    assert count(db, "SELECT count(*) FROM outreach_enrolments WHERE business_id = :b") == 5


def test_another_audiences_campaign_gives_this_audience_no_room(db):
    """P1 2: only campaigns for this audience count."""
    from test_outreach_setup import draft_lia, setup_module_or_missing
    m = setup_module_or_missing()
    biz, brand, lia, campaign = started(db)
    with Session(db) as s:
        other = m.draft_audience(s, biz, OWNER, {"brand_id": brand["id"], "description": "Schools in Kent",
                                                "segments": ["school"], "regions": ["Kent"]}, draft=draft_lia)
        m.approve_audience(s, biz, OWNER, other["id"], {})
    world = World([[person(i) for i in range(10)]])
    out = run(db, biz, other, world)
    assert world.briefs == [] and kept(out) == 0 and "no ready campaign" in out["stopped"]


def test_sends_from_a_paused_campaign_still_use_today_up(db):
    """P1 3: what was sent today counts whatever the campaign's state now."""
    biz, brand, lia, campaign = started(db)
    sends_today(db, campaign["id"], 5)
    with Session(db) as s:
        row = dict(s.execute(text("SELECT * FROM outreach_campaigns WHERE id = :c"), {"c": campaign["id"]}).mappings().one())
        s.execute(text("UPDATE outreach_campaigns SET status = 'paused' WHERE id = :c"), {"c": campaign["id"]})
        _insert(s, "outreach_campaigns", **{**row, "id": str(uuid.uuid4()), "name": "Winter"})
        s.commit()
    assert room(db, biz, brand)["room"] == 15


def test_a_second_run_during_a_search_waits_and_pays_nothing(db):
    """P1 4/5: one paid search per business at a time, so two runs (another
    audience, or another brand on the same inbox) never pay for the same places."""
    biz, brand, lia, campaign = started(db)
    fit, fit_lia = second_brand(db, biz)
    seen = {}
    first = World([[person(i) for i in range(5)]])
    real_search = first.search

    def search_while_another_runs(brief):
        second = World([[person(100 + i) for i in range(5)]])
        seen["out"] = run(db, biz, fit_lia, second)
        seen["briefs"] = second.briefs
        return real_search(brief)
    first.search = search_while_another_runs
    assert kept(run(db, biz, lia, first)) == 5
    assert seen["briefs"] == [] and "Another search" in seen["out"]["stopped"] and seen["out"]["spend_pence"] == 0
    assert kept(run(db, biz, fit_lia, World([[person(200 + i) for i in range(5)]]))) == 5, "free again afterwards"


def test_room_is_checked_under_the_lock_before_paying(db, monkeypatch):
    """P1 5: the inbox filling just before the reservation stops the search."""
    biz, brand, lia, campaign = started(db)
    r = research()
    real = r._lock
    calls = []

    def lock(session, bid):
        if not calls:
            queue(db, campaign["id"], 20, step=1)     # another run fills today first
        calls.append(1)
        return real(session, bid)
    monkeypatch.setattr(r, "_lock", lock)
    world = World([[person(i) for i in range(10)]])
    out = run(db, biz, lia, world)
    assert world.briefs == [] and out["spend_pence"] == 0 and kept(out) == 0


def test_an_email_being_sent_counts_once(db):
    """P2: a held send counts as a send, not also as a contact waiting."""
    biz, brand, lia, campaign = started(db)
    queue(db, campaign["id"], 1, step=0)
    with Session(db) as s:
        e = s.execute(text("SELECT id, prospect_id FROM outreach_enrolments WHERE campaign_id = :c"), {"c": campaign["id"]}).one()
        message = str(uuid.uuid4())
        _insert(s, "outreach_messages", id=message, business_id=A, prospect_id=e[1], campaign_id=campaign["id"],
                enrolment_id=e[0], mailbox_id=WORKSPACE, kind="initial", origin="live", direction="outbound",
                to_emails="[]", cc_emails="[]", subject="s", body="b", payload_hash="h", payload_version=1,
                state="claimed", idempotency_key="k", authority_snapshot="{}", created_at=NOW.isoformat(),
                updated_at=NOW.isoformat())
        _insert(s, "outreach_usage_events", id=str(uuid.uuid4()), business_id=A, operation_key="op", kind="outreach_emails_sent",
                quantity=1, period_start=NOW.isoformat(), period_end=(NOW + timedelta(days=30)).isoformat(),
                mailbox_id=WORKSPACE, message_id=message, local_send_date=NOW.date().isoformat(), state="reserved",
                created_at=NOW.isoformat(), updated_at=NOW.isoformat())
        s.commit()
    assert room(db, biz, brand)["room"] == 19


def test_follow_ups_count_by_the_uk_day(db):
    """Due before UK midnight tonight counts; due just after does not."""
    from zoneinfo import ZoneInfo
    biz, brand, lia, campaign = started(db)
    uk = NOW.astimezone(ZoneInfo("Europe/London"))
    tonight = uk.replace(hour=23, minute=59)
    queue(db, campaign["id"], 3, step=1, due=tonight)
    queue(db, campaign["id"], 4, step=1, due=tonight + timedelta(minutes=2))
    assert room(db, biz, brand)["followups_due"] == 3 and room(db, biz, brand)["room"] == 17


def test_manual_enrolment_follows_the_same_pilot_setting():
    """P2: one setting for every enrolment path."""
    import inspect
    from services import outreach_manage
    assert "pilot_enrolments()" in inspect.getsource(outreach_manage.enrol)
    assert "<= 5" not in inspect.getsource(outreach_manage.enrol)


def sends_today(db, campaign_id, n):
    with Session(db) as s:
        for i in range(n):
            message = str(uuid.uuid4())
            _insert(s, "outreach_messages", id=message, business_id=A, prospect_id=str(uuid.uuid4()),
                    campaign_id=campaign_id, mailbox_id=WORKSPACE, kind="initial", origin="live",
                    direction="outbound", to_emails="[]", cc_emails="[]", subject="s", body="b",
                    payload_hash=f"h{i}", payload_version=1, state="accepted", idempotency_key=f"k{i}",
                    authority_snapshot="{}", created_at=NOW.isoformat(), updated_at=NOW.isoformat())
            _insert(s, "outreach_usage_events", id=str(uuid.uuid4()), business_id=A, operation_key=f"op{i}",
                    kind="outreach_emails_sent", quantity=1, period_start=NOW.isoformat(),
                    period_end=(NOW + timedelta(days=30)).isoformat(), mailbox_id=WORKSPACE, message_id=message,
                    local_send_date=NOW.date().isoformat(), state="committed",
                    created_at=NOW.isoformat(), updated_at=NOW.isoformat())
        s.commit()
