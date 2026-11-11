"""OUT-23 — the prospect bank (docs/OUT-23-TICKET.md, Part A revision 4,
design approved by Codex design review 5). RED: paid research and personal
data. Research fills a bank ahead of what the inboxes can email today; the
drain alone enrols, oldest first, into places the send path will admit.
Every adapter is faked; contacts come from the real research run."""
# ruff: noqa: F811 - pytest fixtures imported from test_outreach_setup are parameters by design
import json
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlmodel import Session

from test_outreach_setup import A, OWNER, WORKSPACE, _insert, db  # noqa: F401
from test_outreach_research import NOW, World, count, person, research, run, run_clock, started


def bank():
    from services import outreach_bank
    return outreach_bank


@pytest.fixture(autouse=True)
def no_pilot_limit(monkeypatch):
    """As the research tests: the pilot limit is lifted (OUT-24), except where a test sets it."""
    monkeypatch.setenv("OUTREACH_PILOT_ENROLMENTS", "0")


def researched(db, n, *, full=True, drain=False):
    biz, brand, lia, campaign = started(db, full=full)
    out = run(db, biz, lia, World([[person(i) for i in range(n)]]), drain=drain)
    return biz, brand, lia, campaign, out


def drain(db, biz, moment=NOW):
    with run_clock(), Session(db) as s:
        return bank().drain_business(s, biz, moment)


def enrolled(db):
    return count(db, "SELECT count(*) FROM outreach_enrolments WHERE business_id = :b")


def banked(db):
    return count(db, "SELECT count(*) FROM outreach_prospects p WHERE p.business_id = :b AND p.eligibility = 'eligible' "
                     "AND NOT EXISTS (SELECT 1 FROM outreach_enrolments e WHERE e.prospect_id = p.id)")


def sizes(db, brand, lia):
    with run_clock(), Session(db) as s:
        h = s.execute(text("SELECT audience_hash FROM outreach_compliance WHERE id = :l"), {"l": lia["id"]}).scalar()
        return bank().bank(s, A, brand["id"], h, NOW)


def sent_today(db, campaign_id, n, *, state="committed", kind="initial", mailbox=WORKSPACE, day=NOW):
    with Session(db) as s:
        for _ in range(n):
            message = str(uuid.uuid4())
            _insert(s, "outreach_messages", id=message, business_id=A, prospect_id=str(uuid.uuid4()),
                    campaign_id=campaign_id, mailbox_id=mailbox, kind=kind, origin="live", direction="outbound",
                    to_emails="[]", cc_emails="[]", subject="s", body="b", payload_hash="h" + message,
                    payload_version=1, state="accepted", idempotency_key="k" + message, authority_snapshot="{}",
                    created_at=NOW.isoformat(), updated_at=NOW.isoformat())
            _insert(s, "outreach_usage_events", id=str(uuid.uuid4()), business_id=A, operation_key="op" + message,
                    kind="outreach_emails_sent", quantity=1, period_start=NOW.isoformat(),
                    period_end=(NOW + timedelta(days=30)).isoformat(), mailbox_id=mailbox, message_id=message,
                    local_send_date=day.date().isoformat(), state=state,
                    created_at=NOW.isoformat(), updated_at=NOW.isoformat())
        s.commit()


def queued(db, campaign_id, n, *, step=0, due=NOW):
    with Session(db) as s:
        seq = s.execute(text("SELECT sequence_version FROM outreach_campaigns WHERE id = :c"), {"c": campaign_id}).scalar()
        for _ in range(n):
            _insert(s, "outreach_enrolments", id=str(uuid.uuid4()), business_id=A, prospect_id=str(uuid.uuid4()),
                    campaign_id=campaign_id, sequence_version=seq, state="active", next_step=step,
                    next_due_at=due.isoformat(), created_at=NOW.isoformat(), updated_at=NOW.isoformat())
        s.commit()


def setting(db, sql, **params):
    with db.begin() as c:
        c.execute(text(sql), {"b": A, **params})


# ------------------------------------------------------------ bank size ---

def test_the_bank_follows_the_warm_up(db):
    """An estimate of about three weeks of first emails: 5 x daily capacity."""
    biz, brand, lia, campaign = started(db, full=False)          # 5 a day
    assert sizes(db, brand, lia)["target"] == 25


def test_a_full_inbox_banks_about_a_hundred(db):
    biz, brand, lia, campaign = started(db)                       # 20 a day
    assert sizes(db, brand, lia)["target"] == 100


def test_the_owner_s_lower_cap_binds_the_bank(db):
    biz, brand, lia, campaign = started(db)
    setting(db, "UPDATE outreach_settings SET business_daily_cap = 8 WHERE business_id = :b")
    assert sizes(db, brand, lia)["target"] == 40


def test_a_boost_raises_a_brand_left_at_twenty(db):
    """Design review 4: follow(min(20, cap), brand_level), exactly as sending."""
    biz, brand, lia, campaign = started(db)
    raw = count(db, "SELECT settings FROM business_settings WHERE business_id = :b")
    doc = json.loads(raw or "{}")
    doc.setdefault("outreach_boost", {})[WORKSPACE] = {"level": 30, "since": (NOW - timedelta(days=2)).isoformat()}
    setting(db, "UPDATE business_settings SET settings = :s WHERE business_id = :b", s=json.dumps(doc))
    setting(db, "UPDATE outreach_campaigns SET daily_cap = 20 WHERE business_id = :b")
    assert sizes(db, brand, lia)["daily_capacity"] == 30


def test_two_campaigns_capped_at_three_share_a_five_a_day_inbox_as_three_and_two(db):
    biz, brand, lia, campaign = started(db, full=False)
    cols = None
    with Session(db) as s:
        cols = [r[1] for r in s.execute(text("PRAGMA table_info(outreach_campaigns)"))]
        picked = ", ".join(":id" if c == "id" else c for c in cols)
        s.execute(text(f"INSERT INTO outreach_campaigns ({', '.join(cols)}) SELECT {picked} FROM outreach_campaigns "
                       "WHERE id = :src"), {"id": str(uuid.uuid4()), "src": campaign["id"]})
        s.execute(text("UPDATE outreach_campaigns SET daily_cap = 3 WHERE business_id = :b"), {"b": A})
        s.commit()
    assert sizes(db, brand, lia)["daily_capacity"] == 5


# -------------------------------------------------------- research banks ---

def test_research_banks_past_today_s_places_and_the_drain_takes_only_those(db):
    """A 5-a-day inbox: research keeps 25 (the bank), the drain enrols 5."""
    biz, brand, lia, campaign, out = researched(db, 30, full=False)
    assert len(out["accepted"]) == 25 and enrolled(db) == 0          # research never enrols
    assert len(drain(db, biz)["enrolled"]) == 5 and banked(db) == 20


def test_a_full_bank_means_no_search_and_no_spend(db):
    biz, brand, lia, campaign, out = researched(db, 30, full=False)
    world = World([[person(100 + i) for i in range(10)]])
    second = run(db, biz, lia, world, drain=False)
    assert world.briefs == [] and second["spend_pence"] == 0 and "bank is full" in second["stopped"]


def test_a_contact_who_could_never_be_emailed_is_not_kept(db, monkeypatch):
    from services import outreach_manage
    real = outreach_manage.qualified

    def refuses_studio_2(session, bid, c, p):
        if p["company"] == "Studio 2 Ltd":
            raise outreach_manage.send.ActionRefused(409, "Prospect is suppressed")
        return real(session, bid, c, p)
    monkeypatch.setattr(outreach_manage, "qualified", refuses_studio_2)
    biz, brand, lia, campaign, out = researched(db, 3)
    assert len(out["accepted"]) == 2
    assert count(db, "SELECT count(*) FROM outreach_prospects WHERE company = 'Studio 2 Ltd'") == 0
    assert any(r["reason"] == "Prospect is suppressed" for r in out["rejected"])


# --------------------------------------------------- the drain: its bounds ---

def test_the_oldest_banked_contact_goes_first(db):
    biz, brand, lia, campaign, out = researched(db, 8, full=False)
    oldest = out["accepted"][-1]
    setting(db, "UPDATE outreach_prospects SET captured_at = :t WHERE id = :p",
            t=(NOW - timedelta(days=10)).isoformat(), p=oldest)
    drain(db, biz)
    assert count(db, "SELECT count(*) FROM outreach_enrolments WHERE prospect_id = :p", p=oldest) == 1


@pytest.mark.parametrize("bound,expected", [
    ("UPDATE outreach_campaigns SET daily_cap = 2 WHERE business_id = :b", 2),          # campaign
    ("UPDATE outreach_settings SET business_daily_cap = 3 WHERE business_id = :b", 3),  # brand, daily
])
def test_each_daily_bound_binds_alone(db, bound, expected):
    biz, brand, lia, campaign, out = researched(db, 30)
    setting(db, bound)
    assert len(drain(db, biz)["enrolled"]) == expected


def test_the_inbox_warm_up_binds(db):
    biz, brand, lia, campaign, out = researched(db, 30, full=False)
    assert len(drain(db, biz)["enrolled"]) == 5


def test_the_pilot_limit_binds_while_it_lasts(db, monkeypatch):
    monkeypatch.setenv("OUTREACH_PILOT_ENROLMENTS", "3")
    biz, brand, lia, campaign, out = researched(db, 10)
    assert len(drain(db, biz)["enrolled"]) == 3


def test_before_today_s_inbox_check_nothing_is_enrolled_then_it_is(db):
    biz, brand, lia, campaign, out = researched(db, 10)
    setting(db, "UPDATE outreach_mailboxes SET health_checked_at = :t WHERE business_id = :b",
            t=(NOW - timedelta(days=1)).isoformat())
    assert drain(db, biz)["enrolled"] == []
    setting(db, "UPDATE outreach_mailboxes SET health_checked_at = :t WHERE business_id = :b",
            t=(NOW - timedelta(minutes=5)).isoformat())
    assert len(drain(db, biz)["enrolled"]) == 10


def test_the_inbox_s_total_room_counts_replies(db):
    """Replies have used all but 2 of today's total: 2 new contacts at most."""
    from services import metering
    biz, brand, lia, campaign, out = researched(db, 10)
    with Session(db) as s:
        boxes = s.execute(text("SELECT * FROM outreach_mailboxes WHERE business_id = :b"), {"b": A}).mappings().all()
        ceiling = metering.mailbox_ceiling(dict(boxes[0]), 20)
        _insert(s, "outreach_daily_usage", id=str(uuid.uuid4()), business_id=A, scope_type="mailbox",
                scope_id=WORKSPACE, local_date=NOW.date().isoformat(), reserved=0, accepted=ceiling - 2, unknown=0,
                created_at=NOW.isoformat(), updated_at=NOW.isoformat())
        s.commit()
    assert len(drain(db, biz)["enrolled"]) == 2


def test_the_brand_s_monthly_allowance_binds(db):
    from services import metering
    biz, brand, lia, campaign, out = researched(db, 10)
    first, following, weekdays = metering.month_bounds(NOW.date())
    earlier = NOW.replace(day=1)
    sent_today(db, campaign["id"], 20 * weekdays - 4, day=earlier)
    assert len(drain(db, biz)["enrolled"]) == 4


def test_combined_limits_waiting_work_takes_the_last_place(db):
    """One step-0 contact already waits and the inbox has room for one more
    email in total today: no new enrolment (review 3, finding 2)."""
    from services import metering
    biz, brand, lia, campaign, out = researched(db, 5)
    queued(db, campaign["id"], 1, step=0)
    with Session(db) as s:
        boxes = s.execute(text("SELECT * FROM outreach_mailboxes WHERE business_id = :b"), {"b": A}).mappings().all()
        ceiling = metering.mailbox_ceiling(dict(boxes[0]), 20)
        _insert(s, "outreach_daily_usage", id=str(uuid.uuid4()), business_id=A, scope_type="mailbox",
                scope_id=WORKSPACE, local_date=NOW.date().isoformat(), reserved=0, accepted=ceiling - 1, unknown=0,
                created_at=NOW.isoformat(), updated_at=NOW.isoformat())
        s.commit()
    assert drain(db, biz)["enrolled"] == []


def test_repeated_hourly_passes_never_double_count(db):
    biz, brand, lia, campaign, out = researched(db, 30, full=False)
    first = len(drain(db, biz)["enrolled"])
    second = len(drain(db, biz)["enrolled"])
    assert (first, second) == (5, 0)


# ------------------------------- what already uses today (carried from OUT-19 D) ---

def test_sends_already_made_today_take_their_share_and_released_ones_do_not(db):
    biz, brand, lia, campaign, out = researched(db, 30)
    sent_today(db, campaign["id"], 6)
    sent_today(db, campaign["id"], 3, state="released")
    assert len(drain(db, biz)["enrolled"]) == 14


def test_follow_ups_due_today_take_their_share(db):
    biz, brand, lia, campaign, out = researched(db, 30)
    queued(db, campaign["id"], 12, step=1)
    queued(db, campaign["id"], 4, step=2, due=NOW + timedelta(days=3))     # not due today: no share
    assert len(drain(db, biz)["enrolled"]) == 8


def test_an_email_being_sent_counts_once(db):
    """A claimed first email: its reserved usage is counted, its enrolment is not counted again."""
    biz, brand, lia, campaign, out = researched(db, 30)
    with Session(db) as s:
        seq = s.execute(text("SELECT sequence_version FROM outreach_campaigns WHERE id = :c"), {"c": campaign["id"]}).scalar()
        e, pid, message = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
        _insert(s, "outreach_enrolments", id=e, business_id=A, prospect_id=pid, campaign_id=campaign["id"],
                sequence_version=seq, state="active", next_step=0, next_due_at=NOW.isoformat(),
                created_at=NOW.isoformat(), updated_at=NOW.isoformat())
        _insert(s, "outreach_messages", id=message, business_id=A, prospect_id=pid, campaign_id=campaign["id"],
                enrolment_id=e, mailbox_id=WORKSPACE, kind="initial", origin="live", direction="outbound",
                to_emails="[]", cc_emails="[]", subject="s", body="b", payload_hash="h", payload_version=1,
                state="claimed", idempotency_key="k", authority_snapshot="{}",
                created_at=NOW.isoformat(), updated_at=NOW.isoformat())
        _insert(s, "outreach_usage_events", id=str(uuid.uuid4()), business_id=A, operation_key="op", kind="outreach_emails_sent",
                quantity=1, period_start=NOW.isoformat(), period_end=(NOW + timedelta(days=30)).isoformat(),
                mailbox_id=WORKSPACE, message_id=message, local_send_date=NOW.date().isoformat(), state="reserved",
                created_at=NOW.isoformat(), updated_at=NOW.isoformat())
        s.commit()
    assert len(drain(db, biz)["enrolled"]) == 19


def test_a_paused_campaign_s_sends_still_use_the_inbox(db):
    biz, brand, lia, campaign, out = researched(db, 30)
    with Session(db) as s:
        cols = [r[1] for r in s.execute(text("PRAGMA table_info(outreach_campaigns)"))]
        paused = str(uuid.uuid4())
        picked = ", ".join(":id" if c == "id" else "'paused'" if c == "status" else c for c in cols)
        s.execute(text(f"INSERT INTO outreach_campaigns ({', '.join(cols)}) SELECT {picked} FROM outreach_campaigns "
                       "WHERE id = :src"), {"id": paused, "src": campaign["id"]})
        s.commit()
    sent_today(db, paused, 15)
    assert len(drain(db, biz)["enrolled"]) == 5


def test_an_email_of_unknown_outcome_counts_once(db):
    """A follow-up whose outcome is unknown: its usage counts, its enrolment's due step does not count again."""
    biz, brand, lia, campaign, out = researched(db, 30)
    queued(db, campaign["id"], 1, step=1)
    with Session(db) as s:
        e, pid = s.execute(text("SELECT id, prospect_id FROM outreach_enrolments WHERE next_step = 1")).one()
        message = str(uuid.uuid4())
        _insert(s, "outreach_messages", id=message, business_id=A, prospect_id=pid, campaign_id=campaign["id"],
                enrolment_id=e, mailbox_id=WORKSPACE, kind="followup", origin="live", direction="outbound",
                to_emails="[]", cc_emails="[]", subject="s", body="b", payload_hash="h", payload_version=1,
                state="unknown", idempotency_key="k", authority_snapshot="{}",
                created_at=NOW.isoformat(), updated_at=NOW.isoformat())
        _insert(s, "outreach_usage_events", id=str(uuid.uuid4()), business_id=A, operation_key="op", kind="outreach_emails_sent",
                quantity=1, period_start=NOW.isoformat(), period_end=(NOW + timedelta(days=30)).isoformat(),
                mailbox_id=WORKSPACE, message_id=message, local_send_date=NOW.date().isoformat(), state="unknown",
                created_at=NOW.isoformat(), updated_at=NOW.isoformat())
        s.commit()
    assert len(drain(db, biz)["enrolled"]) == 19


def test_follow_ups_count_by_the_uk_day(db):
    """Due before UK midnight tonight counts; due just after does not."""
    from zoneinfo import ZoneInfo
    biz, brand, lia, campaign, out = researched(db, 30)
    tonight = NOW.astimezone(ZoneInfo("Europe/London")).replace(hour=23, minute=59)
    queued(db, campaign["id"], 3, step=1, due=tonight)
    queued(db, campaign["id"], 4, step=1, due=tonight + timedelta(minutes=2))
    assert len(drain(db, biz)["enrolled"]) == 17


def test_a_campaign_over_its_cap_takes_nothing_from_another(db):
    """One campaign's overrun never lowers another's places."""
    from test_outreach_research import own_inbox
    biz, brand, lia, campaign, out = researched(db, 30)
    box = own_inbox(db, brand, lia, address="second@newbody.example")
    setting(db, "UPDATE outreach_campaigns SET daily_cap = 5 WHERE id = :c", c=campaign["id"])
    setting(db, "UPDATE outreach_mailboxes SET warmup_stage = 5, daily_cap = 5, sending_days = 0 WHERE mailbox_id = :m", m=box)
    queued(db, campaign["id"], 8)                       # 3 over its cap of 5
    assert len(drain(db, biz)["enrolled"]) == 5          # the second inbox's 5, untouched


def test_the_hourly_pass_runs_erasure_research_drain_then_cards_each_alone(monkeypatch):
    """Order matters: erasure before anything, the drain after research, cards last;
    one step failing never stops the next."""
    from services import automations, outreach_erasure, outreach_research, outreach_setup
    calls = []

    def step(name, fail=False):
        def run_step(session, *a, **k):
            calls.append(name)
            if fail:
                raise RuntimeError(name)
        return run_step
    monkeypatch.setattr(outreach_erasure, "run_due", step("erasure"))
    monkeypatch.setattr(outreach_setup, "daily_health", step("health"))
    monkeypatch.setattr(outreach_research, "run_due", step("research"))
    monkeypatch.setattr(bank(), "drain_due", step("drain", fail=True))
    monkeypatch.setattr(bank(), "prepare_all_due", step("cards"))

    class Stop(Exception):
        pass

    class Session_:
        def rollback(self):
            pass

        def execute(self, *a, **k):
            raise Stop                      # the invoice-chasing part is not under test
    with pytest.raises(Stop):
        automations.run_all_due(Session_())
    assert calls == ["erasure", "health", "research", "drain", "cards"]


# ----------------------------------------------------------- the margin ---

def test_contacts_too_close_to_their_deadline_are_held_and_never_block_replenishment(db):
    biz, brand, lia, campaign, out = researched(db, 25, full=False)
    setting(db, "UPDATE outreach_prospects SET captured_at = :t, notice_due_at = :n WHERE business_id = :b",
            t=(NOW - timedelta(days=24)).isoformat(), n=(NOW + timedelta(days=4)).isoformat())
    assert drain(db, biz)["enrolled"] == []
    b = sizes(db, brand, lia)
    assert b["held"] == 25 and b["drainable"] == 0 and b["room"] == 25


# -------------------------------------------------------- around the drain ---

def test_review_held_contacts_are_never_drained(db):
    biz, brand, lia, campaign = started(db)
    world = World([[person(1)]])
    world.pages["https://studio1.example/team"] = "<html><p>Sam Taylor is a sole trader. Email sam@studio1.example.</p></html>"
    world.pages["https://studio1.example/"] = world.pages["https://studio1.example/team"]
    run(db, biz, lia, world, drain=False)
    assert count(db, "SELECT count(*) FROM outreach_prospects WHERE eligibility = 'review'") == 1
    assert drain(db, biz)["enrolled"] == []


@pytest.mark.parametrize("change,reason", [
    ("UPDATE outreach_settings SET pause_all = 1 WHERE business_id = :b", "paused"),
    ("UPDATE business_members SET is_active = 0 WHERE business_id = :b", "no active owner"),
])
def test_a_paused_or_ownerless_business_is_skipped(db, change, reason):
    biz, brand, lia, campaign, out = researched(db, 10)
    setting(db, change)
    done = drain(db, biz)
    assert done["enrolled"] == [] and reason in (done["skipped"] or "")


@pytest.mark.parametrize("hours,weekday_shift,ran", [(0, 0, True), (-2, 0, False), (12, 0, False), (0, 4, False)])
def test_the_drain_runs_on_weekdays_from_seven_to_six(db, hours, weekday_shift, ran):
    """NOW is Tuesday 07:30 UK. 05:30 and 19:30 are outside; Saturday too."""
    biz, brand, lia, campaign, out = researched(db, 5)
    moment = NOW + timedelta(hours=hours, days=weekday_shift)
    with run_clock(), Session(db) as s:
        done = bank().drain_due(s, moment)
    assert (done["enrolled"] > 0) is ran


def test_cards_are_made_for_due_emails_even_with_an_empty_bank_and_research_off(db):
    """R4.3: the drain committed, then the process stopped before any card."""
    biz, brand, lia, campaign, out = researched(db, 3)
    drain(db, biz)
    setting(db, "DELETE FROM aria_actions WHERE business_id = :b")
    with Session(db) as s:
        research().configure(s, biz, OWNER, {"brand_id": brand["id"], "enabled": False, "monthly_cap_pence": 2000})
    assert banked(db) == 0
    with run_clock(), Session(db) as s:
        made = bank().prepare_all_due(s, NOW)
    assert made == 3


def test_manual_enrolment_is_unchanged(db):
    """The drain is the only AUTOMATIC path from research; the owner can still enrol."""
    from services import outreach_manage
    biz, brand, lia, campaign, out = researched(db, 2)
    with run_clock(), Session(db) as s:
        result = outreach_manage.enrol(s, biz, OWNER, str(campaign["id"]), {"prospect_ids": out["accepted"][:1]})
    assert result["items"] and enrolled(db) == 1


# ------------------------------------------------------ B6: the owner sees it ---

def shown(db, biz, moment=NOW):
    with run_clock(), Session(db) as s:
        brands = research().status(s, biz)["brands"]
    return brands[0]["bank"][0]


def test_the_owner_sees_the_bank_its_age_and_nothing_personal(db):
    biz, brand, lia, campaign, out = researched(db, 30)
    setting(db, "UPDATE outreach_prospects SET captured_at = :t WHERE business_id = :b AND id IN "
                "(SELECT id FROM outreach_prospects WHERE business_id = :b ORDER BY id LIMIT 3)",
            t=(NOW - timedelta(days=19)).isoformat())
    b = shown(db, biz)
    assert (b["target"], b["banked"], b["drainable"], b["held"], b["waiting"]) == (100, 30, 30, 0, 0)
    assert b["oldest_days_left"] == 9 and b["blocked"] is None and b["description"]
    assert not any("@" in str(v) for v in b.values())
    drain(db, biz)
    b = shown(db, biz)
    assert (b["banked"], b["waiting"]) == (10, 20)


def test_review_held_contacts_are_shown_apart(db):
    biz, brand, lia, campaign = started(db)
    world = World([[person(i, company=f"Sole {i}") for i in range(3)]])
    world.not_companies.update(f"Sole {i}" for i in range(3))
    run(db, biz, lia, world, drain=False)
    b = shown(db, biz)
    assert b["review_held"] == 3 and b["banked"] == 0


@pytest.mark.parametrize("change,blocked", [
    ("UPDATE outreach_settings SET pause_all = 1 WHERE business_id = :b", "paused"),
    ("UPDATE outreach_campaigns SET status = 'paused' WHERE business_id = :b", "No ready campaign"),
    ("UPDATE outreach_mailboxes SET health_checked_at = '2020-01-01T00:00:00+00:00' WHERE business_id = :b",
     "inbox check"),
    ("UPDATE business_members SET is_active = 0 WHERE business_id = :b", "no active owner"),
])
def test_the_owner_sees_what_stops_the_drain(db, change, blocked):
    biz, brand, lia, campaign, out = researched(db, 10)
    setting(db, change)
    assert blocked in shown(db, biz)["blocked"]


def test_an_unpaid_brand_is_never_drained_and_the_owner_is_told(db, monkeypatch):
    from services import outreach_billing
    biz, brand, lia, campaign, out = researched(db, 10)
    monkeypatch.setattr(outreach_billing, "brand_live", lambda *a, **k: False)
    assert drain(db, biz)["enrolled"] == []
    assert "isn't paid for" in shown(db, biz)["blocked"]


def test_once_today_s_forty_are_found_a_second_run_pays_for_no_search(db):
    """The bank still has room (60 of 100), but the brand's 40 for today are found."""
    biz, brand, lia, campaign = started(db)
    assert len(run(db, biz, lia, World([[person(i) for i in range(45)]]), drain=False)["accepted"]) == 40
    world = World([[person(100 + i) for i in range(10)]])
    out = run(db, biz, lia, world, drain=False)
    assert world.briefs == [] and out["spend_pence"] == 0 and "today's 40" in out["stopped"]


def test_a_later_run_asks_only_for_what_is_left_of_today_s_forty(db):
    biz, brand, lia, campaign = started(db)
    run(db, biz, lia, World([[person(i) for i in range(30)]]), drain=False)
    world = World([[person(100 + i) for i in range(20)]])
    out = run(db, biz, lia, world, drain=False)
    assert "find up to 15 NEW" in world.briefs[0]               # 10 left: asks for min(2x, +5)
    assert len(out["accepted"]) == 10


# ------------------------------------------------ Codex code review 1 findings ---

def _paused_clone(db, campaign):
    with Session(db) as s:
        cols = [r[1] for r in s.execute(text("PRAGMA table_info(outreach_campaigns)"))]
        paused = str(uuid.uuid4())
        picked = ", ".join(":id" if c == "id" else "'paused'" if c == "status" else c for c in cols)
        s.execute(text(f"INSERT INTO outreach_campaigns ({', '.join(cols)}) SELECT {picked} FROM outreach_campaigns "
                       "WHERE id = :src"), {"id": paused, "src": campaign["id"]})
        s.commit()
    return paused


def test_a_paused_campaign_s_queue_still_uses_the_inbox_and_brand(db):
    """P1: 15 waiting in a paused campaign on the same inbox leave 5 places, not 20."""
    biz, brand, lia, campaign, out = researched(db, 30)
    queued(db, _paused_clone(db, campaign), 15)
    assert len(drain(db, biz)["enrolled"]) == 5


def test_the_nearest_deadline_goes_first_not_the_oldest_capture(db):
    """P2: a recent contact with 6 days left beats older ones with 18 left."""
    biz, brand, lia, campaign, out = researched(db, 8, full=False)        # 5 places
    urgent = out["accepted"][0]
    setting(db, "UPDATE outreach_prospects SET captured_at = :t WHERE business_id = :b AND id <> :p",
            t=(NOW - timedelta(days=10)).isoformat(), p=urgent)
    setting(db, "UPDATE outreach_prospects SET notice_due_at = :n WHERE id = :p",
            n=(NOW + timedelta(days=6)).isoformat(), p=urgent)
    assert urgent in drain(db, biz)["enrolled"]


def test_the_owner_is_told_when_today_s_places_are_used(db):
    biz, brand, lia, campaign, out = researched(db, 30)
    assert shown(db, biz)["blocked"] is None
    drain(db, biz)
    assert "Today's places are used" in shown(db, biz)["blocked"]


def test_the_owner_is_told_when_the_pilot_is_full(db, monkeypatch):
    biz, brand, lia, campaign, out = researched(db, 30)
    monkeypatch.setenv("OUTREACH_PILOT_ENROLMENTS", "5")
    drain(db, biz)
    assert "at most 5 contacts during the pilot" in shown(db, biz)["blocked"]


def test_the_owner_is_told_when_outreach_is_not_on_their_plan(db, monkeypatch):
    import auth
    from fastapi import HTTPException
    biz, brand, lia, campaign, out = researched(db, 10)

    def refuse(*a, **k):
        raise HTTPException(403, "no")
    monkeypatch.setattr(auth, "assert_feature_access", refuse)
    assert "isn't available on this account" in shown(db, biz)["blocked"]
