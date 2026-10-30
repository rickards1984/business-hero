"""OUT-19 G — boosting an inbox with a proven record (decision 5,
docs/OUT-19-TICKET.md). RED: sending limits and deliverability.

Mike, 30 Oct 2026: a boost is FREE (the brand's AI ceiling still caps our
cost) and the OWNER OPTS IN when an inbox qualifies; dropping back is always
automatic. Steps 20 → 30 → 40 → 50 cold emails a day; 50 is the ceiling.

Qualifying for 30: 28 days at warm-up stage 20; in the last 28 days at least
200 cold emails, bounces under 2%, unsubscribes under 1%, no complaints, no
failed daily check, at least one genuine reply; not paused, passing today.
Each later step: 14 days at the current level and the same over 14 days with
at least 150 cold emails. Dropping back: a miss over the last 14 days drops a
step (then a 14-day hold); a complaint or any pause goes back to 20.

Tests first; Mike approved them on 30 Oct 2026. Synthetic SQLite, the real
send path, no network.
"""
# ruff: noqa: F811 - pytest fixtures imported from the OUT-6 harness are parameters by design

import importlib
import importlib.util
import json
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text

from test_outreach_send import (  # noqa: F401 - fixtures are used by name
    A, BOX, BRAND, CAMPAIGN, NOW, OWNER, STAFF, STAMP, add, approve, database, h, propose, sent_today)
from test_outreach_replies_ceiling import emails_today
from test_outreach_replies import r  # noqa: F401 - the reply harness, for the real complaint path
from test_outreach_setup import db  # noqa: F401 - the setup harness, for the real retirement path
from services import metering


class MissingBoost(AssertionError):
    """Only the intentional absence of the module may be xfailed."""




def mock_now(moment):
    from unittest import mock
    from services import outreach_send
    return mock.patch.object(outreach_send, "now", lambda: moment)


def boost():
    if importlib.util.find_spec("services.outreach_boost") is None:
        raise MissingBoost("backend/services/outreach_boost.py does not exist yet")
    return importlib.import_module("services.outreach_boost")


def day(n):
    """n days before NOW, as a UK date."""
    return (NOW - timedelta(days=n)).astimezone(metering.LONDON).date().isoformat()


def stage20(h, *, reviewed_days=29):
    """The campaign inbox at warm-up stage 20, reviewed by the owner
    `reviewed_days` ago, with its own limits at the maximum (20)."""
    boost()
    h.s.execute(text("UPDATE outreach_mailboxes SET warmup_stage = 20, daily_cap = 20, sending_days = 40, "
                     "health_reviewed_by = :o, health_reviewed_at = :t WHERE mailbox_id = :m"),
                {"o": OWNER, "t": (NOW - timedelta(days=reviewed_days)).isoformat(), "m": BOX})
    h.s.execute(text("UPDATE outreach_campaigns SET daily_cap = 20 WHERE id = :c"), {"c": CAMPAIGN})
    h.s.commit()


def history(h, n, *, days=28, kind="initial"):
    """n cold emails sent from the campaign inbox over the `days` before today,
    to other people (never the campaign's own prospect)."""
    others = add(h.s, "prospects", email_key=uuid.uuid4().hex)
    for i in range(n):
        when = day(1 + i % (days - 1))
        message = add(h.s, "messages", campaign_id=CAMPAIGN, mailbox_id=BOX, prospect_id=others,
                      direction="outbound", state="accepted", kind=kind)
        add(h.s, "usage_events", operation_key=f"history:{i}:{message}", kind="outreach_emails_sent", quantity=1,
            state="committed", mailbox_id=BOX, local_send_date=when, message_id=message,
            period_start=STAMP, period_end=STAMP)
    h.s.commit()


def replies(h, category, n=1, *, days_ago=3):
    """n replies of `category` to the campaign inbox, each from a different
    person (never the campaign's own prospect, whom a reply would stop)."""
    for _ in range(n):
        prospect = add(h.s, "prospects", email_key=uuid.uuid4().hex)
        add(h.s, "replies", prospect_id=prospect, mailbox_id=BOX, inbound_email_id=str(uuid.uuid4()),
            category=category, knowledge_refs="[]", resolution="pending",
            received_at=(NOW - timedelta(days=days_ago)).isoformat())
    h.s.commit()


def unsubscribed_by_link(h, n=1, *, days_ago=3):
    """n people this inbox emailed who unsubscribed through the link."""
    for i in range(n):
        key = f"unsub-key-{i}-{uuid.uuid4().hex[:6]}"
        prospect = add(h.s, "prospects", email_key=key)
        add(h.s, "messages", campaign_id=CAMPAIGN, mailbox_id=BOX, prospect_id=prospect, direction="outbound",
            state="accepted", kind="initial")
        add(h.s, "suppressions", key_type="email", key_digest=key, digest_version=1, reason="unsubscribe",
            suppressed_at=(NOW - timedelta(days=days_ago)).isoformat())
    h.s.commit()


def qualified(h):
    """A clean 28 days: 200 cold emails, one genuine reply, nothing wrong."""
    stage20(h)
    history(h, 200)
    replies(h, "interested")


def eligibility(h, moment=NOW):
    out = boost().eligibility(h.s, A, BOX, moment)
    h.s.rollback()
    return out


def set_level(h, level, *, since_days):
    raw = h.s.execute(text("SELECT settings FROM business_settings WHERE business_id = :b"), {"b": A}).scalar()
    doc = json.loads(raw or "{}")
    doc.setdefault("outreach_boost", {})[BOX] = {"level": level, "since": (NOW - timedelta(days=since_days)).isoformat()}
    h.s.execute(text("UPDATE business_settings SET settings = :s WHERE business_id = :b"), {"s": json.dumps(doc), "b": A})
    h.s.commit()


def level(h):
    out = boost().level(h.s, A, BOX)
    h.s.rollback()
    return out


def do_boost(h, user=OWNER, moment=NOW):
    out = boost().boost(h.s, h.b, user, BOX, moment=moment)
    h.s.commit()
    return out


def refused_today(h, card, _limit):
    """The send is refused and nothing goes out."""
    with pytest.raises(h.a.ActionRefused) as exc:
        approve(h, card)
    assert exc.value.status_code in (403, 404, 409, 422) and not h.p.sends


def cap(h):
    row = h.s.execute(text("SELECT * FROM outreach_mailboxes WHERE mailbox_id = :m"), {"m": BOX}).mappings().one()
    out = metering.mailbox_daily_cap(row, boost=boost().level(h.s, A, BOX))
    h.s.rollback()
    return out


# ----------------------------------------------------------- qualifying ---

def test_a_clean_four_weeks_qualifies_for_the_first_step(h):
    qualified(h)
    out = eligibility(h)
    assert out["eligible"] is True and out["level"] == 20 and out["next"] == 30
    assert out["evidence"]["cold"] == 200 and out["evidence"]["genuine_replies"] == 1
    assert "own evidence" in out["notice"] and "can't see" in out["notice"]


@pytest.mark.parametrize("spoil,why", [
    (lambda h: stage20(h, reviewed_days=20), "28 days"),
    (lambda h: history(h, 0), "200"),                                  # placeholder, replaced below
    (lambda h: replies(h, "bounce", 4), "bounce"),                       # 4 of 200 = 2%: not under 2%
    (lambda h: replies(h, "unsubscribe", 2), "unsubscribe"),             # 2 of 200 = 1%
    (lambda h: unsubscribed_by_link(h, 2), "unsubscribe"),               # by link, traced to this inbox
    (lambda h: replies(h, "complaint"), "complaint"),
    (lambda h: boost().record_check(h.s, A, BOX, NOW - timedelta(days=5), passed=False) or h.s.commit(), "check"),
])
def test_each_measure_must_be_met(h, spoil, why):
    qualified(h)
    if why == "200":
        h.s.execute(text("DELETE FROM outreach_usage_events WHERE operation_key LIKE 'history:1:%'"))
        h.s.commit()                       # 199 cold emails
    else:
        spoil(h)
    out = eligibility(h)
    assert out["eligible"] is False and any(why in reason.lower() for reason in out["unmet"]), out["unmet"]


def test_a_genuine_reply_is_needed_and_auto_replies_and_bounces_are_not_one(h):
    stage20(h)
    history(h, 200)
    replies(h, "out_of_office")
    replies(h, "self")
    out = eligibility(h)
    assert out["eligible"] is False and any("reply" in r.lower() for r in out["unmet"])


def test_only_cold_emails_count_towards_the_two_hundred(h):
    stage20(h)
    history(h, 150)
    history(h, 100, kind="bespoke")        # replies to people who wrote back
    replies(h, "question")
    assert eligibility(h)["eligible"] is False


def test_evidence_older_than_four_weeks_is_not_counted(h):
    qualified(h)
    replies(h, "complaint", days_ago=30)
    replies(h, "bounce", 10, days_ago=40)
    assert eligibility(h)["eligible"] is True


@pytest.mark.parametrize("state", ["paused", "failing today"])
def test_a_paused_or_failing_inbox_does_not_qualify(h, state):
    qualified(h)
    if state == "paused":
        h.s.execute(text("UPDATE outreach_mailboxes SET pause_reason = 'held by owner' WHERE mailbox_id = :m"), {"m": BOX})
    else:
        h.s.execute(text("UPDATE outreach_mailboxes SET health_status = 'fail' WHERE mailbox_id = :m"), {"m": BOX})
    h.s.commit()
    assert eligibility(h)["eligible"] is False


def test_an_inbox_still_warming_up_does_not_qualify(h):
    boost()
    history(h, 200)
    replies(h, "interested")
    assert eligibility(h)["eligible"] is False


# --------------------------------------------------------------- boosting ---

def test_the_owner_boosts_a_qualifying_inbox_to_thirty(h):
    qualified(h)
    out = do_boost(h)
    assert out["level"] == 30 and level(h) == 30 and cap(h) == 30


@pytest.mark.parametrize("user,code", [(STAFF, 403)])
def test_only_the_owner_boosts(h, user, code):
    qualified(h)
    with pytest.raises(Exception) as exc:
        do_boost(h, user=user)
    assert getattr(exc.value, "status_code", None) == code and level(h) == 20


def test_an_inbox_that_does_not_qualify_is_never_boosted(h):
    stage20(h)
    history(h, 200)                        # no genuine reply
    with pytest.raises(Exception) as exc:
        do_boost(h)
    assert getattr(exc.value, "status_code", None) == 409 and level(h) == 20


def test_each_later_step_waits_fourteen_days_at_the_current_level(h):
    qualified(h)
    history(h, 150, days=14)               # the later steps look at the last 14 days
    set_level(h, 30, since_days=10)
    out = eligibility(h)
    assert out["next"] == 40 and out["eligible"] is False and any("14 days" in r for r in out["unmet"])
    set_level(h, 30, since_days=15)
    assert eligibility(h)["eligible"] is True
    assert do_boost(h)["level"] == 40


def test_a_later_step_needs_a_hundred_and_fifty_cold_emails_in_fourteen_days(h):
    stage20(h)
    history(h, 149, days=14)
    replies(h, "interested")
    set_level(h, 30, since_days=15)
    assert eligibility(h)["eligible"] is False


def test_fifty_is_the_ceiling(h):
    qualified(h)
    set_level(h, 50, since_days=30)
    out = eligibility(h)
    assert out["next"] is None and out["eligible"] is False
    with pytest.raises(Exception) as exc:
        do_boost(h)
    assert getattr(exc.value, "status_code", None) == 409 and level(h) == 50


# ------------------------------------------------- what a boost changes ---

@pytest.mark.parametrize("already,sends", [(29, True), (30, False)])
def test_a_boosted_inbox_sends_up_to_its_new_limit_and_no_further(h, already, sends):
    qualified(h)
    do_boost(h)
    emails_today(h, already)
    card = propose(h)
    if sends:
        assert approve(h, card)["status"] == "done" and len(h.p.sends) == 1
    else:
        refused_today(h, card, already)


def test_without_a_boost_the_inbox_still_stops_at_twenty(h):
    qualified(h)
    emails_today(h, 20)
    refused_today(h, propose(h), 20)


def test_the_brands_twenty_follows_the_boost(h):
    qualified(h)
    sent_today(h, 25, BRAND)               # from the brand's other inbox
    do_boost(h)
    assert approve(h, propose(h))["status"] == "done"


@pytest.mark.parametrize("limit", ["campaign", "brand", "inbox"])
def test_a_limit_the_owner_set_below_twenty_still_binds(h, limit):
    qualified(h)
    if limit == "campaign":
        h.s.execute(text("UPDATE outreach_campaigns SET daily_cap = 15 WHERE id = :c"), {"c": CAMPAIGN})
    elif limit == "brand":
        h.s.execute(text("UPDATE outreach_settings SET business_daily_cap = 15 WHERE business_id = :b"), {"b": A})
    else:
        h.s.execute(text("UPDATE outreach_mailboxes SET daily_cap = 15 WHERE mailbox_id = :m"), {"m": BOX})
    h.s.commit()
    do_boost(h)
    emails_today(h, 15)
    refused_today(h, propose(h), 15)


def test_the_monthly_allowance_uses_the_boosted_limit(h):
    from datetime import date
    qualified(h)
    first, following, weekdays = metering.month_bounds(date.fromisoformat(day(0)))
    # 200 of the month's history already count; fill the rest of 20 x weekdays
    sent_today(h, 20 * weekdays, BRAND, day=first.isoformat())
    refused_today(h, propose(h), 20 * weekdays)
    do_boost(h)
    assert approve(h, propose(h))["status"] == "done"


def test_a_providers_own_limit_always_binds(h):
    qualified(h)
    h.s.execute(text("UPDATE outreach_mailboxes SET health_evidence = :e WHERE mailbox_id = :m"),
                {"e": json.dumps({"domain_control": True, "from_aligned": True, "spf": "pass", "dkim": "pass",
                                  "dmarc": "pass", "provider_daily_cap": 25}), "m": BOX})
    h.s.commit()
    do_boost(h)
    assert cap(h) == 25


def test_at_fifty_the_reply_ceiling_is_seventy(h):
    qualified(h)
    set_level(h, 50, since_days=1)
    room = metering.reply_headroom(h.s, A, BOX, NOW)
    h.s.rollback()
    assert room["cap"] == 50 and room["ceiling"] == 70


def test_research_sizes_itself_to_the_boosted_inbox(h):
    """Research never finds more contacts than the inbox can email (D), and
    never fewer because of a stale 20."""
    import inspect
    from services import outreach_research
    qualified(h)
    source = inspect.getsource(outreach_research)
    assert "outreach_boost" in source and "mailbox_daily_cap(boxes[0], boost=" in source


# ---------------------------------------------------------- dropping back ---

def review(h, moment=NOW):
    out = boost().review(h.s, A, BOX, moment)
    h.s.commit()
    return out


def test_a_clean_fortnight_keeps_the_boost(h):
    qualified(h)
    history(h, 150, days=14)
    set_level(h, 40, since_days=20)
    review(h)
    assert level(h) == 40


@pytest.mark.parametrize("spoil", [
    lambda h: replies(h, "bounce", 6, days_ago=2),
    lambda h: replies(h, "unsubscribe", 3, days_ago=2),
    lambda h: (boost().record_check(h.s, A, BOX, NOW - timedelta(days=2), passed=False), h.s.commit()),
])
def test_a_worse_fortnight_drops_one_step_and_holds_fourteen_days(h, spoil):
    qualified(h)
    history(h, 150, days=14)
    set_level(h, 40, since_days=20)
    spoil(h)
    review(h)
    assert level(h) == 30
    review(h)
    assert level(h) == 30, "one step per fortnight, not one per check"
    out = eligibility(h)
    assert out["eligible"] is False and any("14 days" in r for r in out["unmet"])


@pytest.mark.parametrize("trouble", ["complaint", "pause"])
def test_a_complaint_or_a_pause_goes_straight_back_to_twenty(h, trouble):
    qualified(h)
    set_level(h, 50, since_days=20)
    if trouble == "complaint":
        replies(h, "complaint", days_ago=1)
    else:
        h.s.execute(text("UPDATE outreach_mailboxes SET pause_reason = 'Three distinct hard bounces' WHERE mailbox_id = :m"),
                    {"m": BOX})
        h.s.commit()
    review(h)
    assert level(h) == 20


def test_a_failed_daily_check_is_recorded_for_the_inbox_that_failed(h):
    boost()
    boost().record_check(h.s, A, BOX, NOW, passed=False)
    boost().record_check(h.s, A, BOX, NOW, passed=True)
    h.s.commit()
    boost().record_check(h.s, A, BOX, NOW, passed=False)        # a second failure the same day
    h.s.commit()
    out = boost().evidence(h.s, A, BOX, NOW + timedelta(hours=1), days=14)
    h.s.rollback()
    assert out["failed_check_days"] == 1, "counted as failed days"


def health_check(h, *, passed, evidence=None):
    """The real daily-check write (outreach_setup._apply_health)."""
    from services import outreach_setup
    row = h.s.execute(text("SELECT * FROM outreach_mailboxes WHERE mailbox_id = :m"), {"m": BOX}).mappings().one()
    evidence = evidence or {"domain_control": True, "from_aligned": True, "spf": "pass", "dkim": "pass", "dmarc": "pass"}
    outreach_setup._apply_health(h.s, A, dict(row), {"status": "pass" if passed else "fail", "evidence": evidence,
                                                     "advice": [] if passed else ["Fix SPF"]}, NOW, daily=True)
    h.s.commit()


def test_a_failed_daily_check_resets_the_boost_and_is_recorded(h):
    qualified(h)
    set_level(h, 40, since_days=20)
    health_check(h, passed=False)
    assert level(h) == 20
    out = boost().evidence(h.s, A, BOX, NOW, days=14)
    h.s.rollback()
    assert out["failed_check_days"] == 1


def test_a_passing_daily_check_reviews_the_boost(h):
    qualified(h)
    set_level(h, 40, since_days=20)
    replies(h, "bounce", 6, days_ago=2)
    health_check(h, passed=True)
    assert level(h) == 30


def test_another_business_cannot_see_or_boost_this_inbox(h):
    qualified(h)
    from test_outreach_send import B
    other = boost().eligibility(h.s, B, BOX, NOW)
    h.s.rollback()
    assert other["eligible"] is False and other["evidence"]["cold"] == 0



# ------------------------------------------------- Codex review 1 regressions ---

def test_a_complaint_resets_the_boost_in_the_transaction_that_pauses_the_inbox(r):
    """P1 1: through the real complaint path, not the daily review."""
    from test_outreach_replies import incoming
    qualified(r)
    set_level(r, 50, since_days=20)
    ident = incoming(r, sender="mailer-daemon@example.invalid")
    message = r.s.execute(text("SELECT id, provider_message_id FROM outreach_messages WHERE state = 'accepted' "
                               "AND provider_message_id IS NOT NULL")).first()
    r.replies.observe_health(r.s, r.b, inbound_email_id=ident, message_id=message.id, kind="complaint",
                             evidence={"authenticated": True, "mailbox_id": BOX, "provider": "google",
                                       "provider_message_id": message.provider_message_id}, moment=NOW)
    r.s.commit()
    assert level(r) == 20


def test_after_a_reset_the_inbox_qualifies_again_from_the_start(h):
    """P1 2: lifting a pause doesn't bring back a boost on old evidence."""
    qualified(h)
    set_level(h, 30, since_days=20)
    boost().reset(h.s, A, BOX, NOW - timedelta(days=2), "paused")
    h.s.commit()
    out = eligibility(h)                   # the pause is lifted; the evidence is still clean
    assert out["eligible"] is False and any("counted from its reset" in u for u in out["unmet"])


def test_dropping_to_twenty_keeps_its_fourteen_day_hold(h):
    """P1 2: a 30 → 20 drop is remembered."""
    qualified(h)
    history(h, 150, days=14)
    set_level(h, 30, since_days=20)
    replies(h, "unsubscribe", 3, days_ago=2)
    review(h)
    assert level(h) == 20
    out = eligibility(h)
    assert out["eligible"] is False and any("dropped back" in u for u in out["unmet"])


def test_the_grant_is_decided_under_the_lock_that_saves_it(h, monkeypatch):
    """P1 3 (review 2: a regression that the old code fails). The evaluation
    runs after the business lock is taken, with no rollback (which would
    release the lock) between it and the save."""
    from services import outreach_setup
    qualified(h)
    events = []
    real_authority, real_evaluate, real_save = outreach_setup._authority, boost()._evaluate, boost()._save
    real_rollback = h.s.rollback
    def locked(*a, **k):
        out = real_authority(*a, **k)      # (it rolls back, then takes the lock)
        events.append("lock")              # recorded once the lock is held
        return out
    monkeypatch.setattr(outreach_setup, "_authority", locked)
    monkeypatch.setattr(boost(), "_evaluate", lambda *a, **k: (events.append("evaluate"), real_evaluate(*a, **k))[1])
    monkeypatch.setattr(boost(), "_save", lambda *a, **k: (events.append("save"), real_save(*a, **k))[1])
    monkeypatch.setattr(h.s, "rollback", lambda: (events.append("rollback"), real_rollback())[1])
    do_boost(h)
    tail = events[len(events) - 1 - events[::-1].index("lock"):]
    assert tail[:2] == ["lock", "evaluate"] and "save" in tail and "rollback" not in tail, events

@pytest.mark.parametrize("quiet", ["no sends", "no genuine reply"])
def test_a_fortnight_that_misses_any_measure_drops_a_step(h, quiet):
    """P1 4: the volume and genuine-reply measures count too."""
    stage20(h)
    if quiet == "no genuine reply":
        history(h, 150, days=14)
    else:
        replies(h, "interested")
    set_level(h, 50, since_days=20)
    review(h)
    assert level(h) == 40


def test_a_recorded_provider_limit_survives_the_daily_check(h):
    """P1 5."""
    qualified(h)
    h.s.execute(text("UPDATE outreach_mailboxes SET health_evidence = :e WHERE mailbox_id = :m"),
                {"e": json.dumps({"domain_control": True, "from_aligned": True, "spf": "pass", "dkim": "pass",
                                  "dmarc": "pass", "provider_daily_cap": 25}), "m": BOX})
    h.s.commit()
    set_level(h, 50, since_days=1)
    health_check(h, passed=True)           # the new evidence has no provider limit in it
    assert cap(h) == 25


def test_a_provider_limit_binds_replies_too(h):
    """P1 5: it is the inbox's whole sending limit."""
    qualified(h)
    h.s.execute(text("UPDATE outreach_mailboxes SET health_evidence = :e WHERE mailbox_id = :m"),
                {"e": json.dumps({"domain_control": True, "from_aligned": True, "spf": "pass", "dkim": "pass",
                                  "dmarc": "pass", "provider_daily_cap": 25}), "m": BOX})
    h.s.commit()
    set_level(h, 50, since_days=1)
    room = metering.reply_headroom(h.s, A, BOX, NOW)
    h.s.rollback()
    assert room["cap"] == 25 and room["ceiling"] == 25


def mixed_brand(h):
    """The brand's other inbox (DEFAULT) is boosted to 50 and has sent 25 today."""
    from test_outreach_send import DEFAULT
    qualified(h)
    if not h.s.execute(text("SELECT count(*) FROM outreach_mailboxes WHERE mailbox_id = :m"), {"m": DEFAULT}).scalar():
        add(h.s, "mailboxes", mailbox_id=DEFAULT, enabled=True, daily_cap=20, warmup_stage=20, sending_days=40,
            health_status="pass", health_checked_at=STAMP, health_reviewed_by=OWNER,
            health_reviewed_at=(NOW - timedelta(days=60)).isoformat(),
            health_evidence=json.dumps({"domain_control": True, "from_aligned": True, "spf": "pass", "dkim": "pass",
                                        "dmarc": "pass"}))
        h.s.commit()
    raw = h.s.execute(text("SELECT settings FROM business_settings WHERE business_id = :b"), {"b": A}).scalar()
    doc = json.loads(raw or "{}")
    doc.setdefault("outreach_boost", {})[DEFAULT] = {"level": 50, "since": STAMP}
    h.s.execute(text("UPDATE business_settings SET settings = :s WHERE business_id = :b"), {"s": json.dumps(doc), "b": A})
    h.s.commit()
    sent_today(h, 25, BRAND)


def test_research_and_sending_agree_for_a_brand_with_mixed_inboxes(h):
    """P2 1: this inbox (unboosted) may still send, because the brand's limit
    follows its highest sending boost."""
    mixed_brand(h)
    assert boost().brand_level(h.s, A, BRAND) == 50
    h.s.rollback()
    assert approve(h, propose(h))["status"] == "done"


@pytest.mark.parametrize("boosted", [True, False])
def test_research_capacity_itself_follows_the_brands_boost(h, boosted):
    """Review 2: research capacity, not only sending, for mixed-level inboxes."""
    from services import outreach_research
    mixed_brand(h)
    if not boosted:
        h.s.execute(text("UPDATE business_settings SET settings = '{}' WHERE business_id = :b"), {"b": A})
        h.s.commit()
    with mock_now(NOW):
        room = outreach_research.capacity(h.s, A, BRAND, NOW)["room"]
    h.s.rollback()
    assert (room > 0) is boosted


def test_the_evidence_window_is_whole_uk_days_for_every_measure(h):
    """P2 2: sends and replies on the window's first day are both counted."""
    stage20(h)
    first_day_morning = (NOW - timedelta(days=28)).astimezone(metering.LONDON).replace(hour=7)
    others = add(h.s, "prospects", email_key=uuid.uuid4().hex)
    message = add(h.s, "messages", campaign_id=CAMPAIGN, mailbox_id=BOX, prospect_id=others, direction="outbound",
                  state="accepted", kind="initial")
    add(h.s, "usage_events", operation_key=f"edge:{message}", kind="outreach_emails_sent", quantity=1,
        state="committed", mailbox_id=BOX, local_send_date=first_day_morning.date().isoformat(), message_id=message,
        period_start=STAMP, period_end=STAMP)
    add(h.s, "replies", prospect_id=others, mailbox_id=BOX, inbound_email_id=str(uuid.uuid4()), category="bounce",
        knowledge_refs="[]", resolution="pending", received_at=first_day_morning.isoformat())
    h.s.commit()
    out = boost().evidence(h.s, A, BOX, NOW, days=28)
    h.s.rollback()
    assert out["cold"] == 1 and out["bounces"] == 1


def test_a_link_unsubscribe_counts_only_against_an_inbox_that_actually_sent(h):
    """P2 3: a draft or failed attempt never ties a person to this inbox."""
    stage20(h)
    key = uuid.uuid4().hex
    prospect = add(h.s, "prospects", email_key=key)
    add(h.s, "messages", campaign_id=CAMPAIGN, mailbox_id=BOX, prospect_id=prospect, direction="outbound",
        state="failed", kind="initial")
    add(h.s, "suppressions", key_type="email", key_digest=key, digest_version=1, reason="unsubscribe",
        suppressed_at=(NOW - timedelta(days=2)).isoformat())
    h.s.commit()
    out = boost().evidence(h.s, A, BOX, NOW, days=28)
    h.s.rollback()
    assert out["unsubscribes"] == 0


def test_the_screen_is_told_what_the_inbox_can_actually_send(h):
    """P2 4: a boost of 30 under an owner's limit of 15 sends 15."""
    qualified(h)
    h.s.execute(text("UPDATE outreach_mailboxes SET daily_cap = 15 WHERE mailbox_id = :m"), {"m": BOX})
    h.s.commit()
    set_level(h, 30, since_days=1)
    out = eligibility(h)
    assert out["level"] == 30 and out["effective"] == 15


# ------------------------------------------------- Codex review 2 regressions ---

def test_a_new_level_with_worsening_deliverability_drops_at_once(h):
    """P2 1: the fresh-level fortnight excuses volume, never bounces or unsubscribes."""
    stage20(h)
    history(h, 150, days=14)
    replies(h, "interested")
    replies(h, "unsubscribe", 2, days_ago=1)      # 2 of ~150: over 1%
    set_level(h, 30, since_days=1)
    review(h)
    assert level(h) == 20


def test_a_new_level_is_not_dropped_for_low_volume_in_its_first_fortnight(h):
    stage20(h)
    history(h, 40, days=14)                       # building up
    set_level(h, 30, since_days=3)
    review(h)
    assert level(h) == 30


@pytest.mark.parametrize("when", ["yesterday", "tomorrow"])
def test_an_inbox_without_todays_passing_check_can_send_nothing(h, when):
    """P2 2: effective capacity follows the send path's freshness rule."""
    qualified(h)
    checked = NOW - timedelta(days=1) if when == "yesterday" else NOW + timedelta(days=1)
    h.s.execute(text("UPDATE outreach_mailboxes SET health_checked_at = :t WHERE mailbox_id = :m"),
                {"t": checked.isoformat(), "m": BOX})
    h.s.commit()
    out = eligibility(h)
    assert out["effective"] == 0 and any("Today's inbox check" in u for u in out["unmet"])


def test_a_reply_is_refused_at_a_recorded_provider_limit(r):
    """Review 2: an attempted send at the provider ceiling, not only headroom."""
    from test_outreach_replies_ceiling import send_reply
    stage20(r)                             # the level comes from the boost record below
    r.s.execute(text("UPDATE outreach_mailboxes SET health_evidence = :e WHERE mailbox_id = :m"),
                {"e": json.dumps({"domain_control": True, "from_aligned": True, "spf": "pass", "dkim": "pass",
                                  "dmarc": "pass", "provider_daily_cap": 25}), "m": BOX})
    r.s.commit()
    set_level(r, 50, since_days=1)
    emails_today(r, 20)
    emails_today(r, 5, kind="bespoke")
    with pytest.raises(r.a.ActionRefused) as exc:
        send_reply(r)
    assert "safety ceiling" in exc.value.detail and r.p.sends == []


def test_a_bounce_hold_resets_a_boost_too(r):
    """Review 2: the three-hard-bounce hold, through the real path."""
    qualified(r)
    set_level(r, 40, since_days=20)
    if True:
        from test_outreach_replies import EMAIL, incoming
        for i in range(3):
            message = add(r.s, "messages", prospect_id=r.s.execute(text("SELECT id FROM outreach_prospects LIMIT 1")).scalar(),
                          campaign_id=CAMPAIGN, mailbox_id=BOX, kind="bespoke", origin="live", direction="outbound",
                          to_emails=json.dumps([EMAIL]), cc_emails="[]", subject="Synthetic", body="Synthetic",
                          payload_hash="hash", payload_version=1, state="accepted", provider="google",
                          provider_message_id=f"boost-bounced-{i}", provider_thread_id=f"boost-thread-{i}",
                          accepted_at=STAMP, idempotency_key=f"boost-bounced-{i}", authority_snapshot="{}")
            inbound = incoming(r, ident=f"boost-bounce-{i}", sender="mailer-daemon@example.invalid")
            r.replies.observe_health(r.s, r.b, inbound_email_id=inbound, message_id=message, kind="hard_bounce",
                                     evidence={"authenticated": True, "mailbox_id": BOX, "provider": "google",
                                               "provider_message_id": f"boost-bounced-{i}"}, moment=NOW)
        r.s.commit()
    assert level(r) == 20


def test_retiring_an_inbox_resets_its_boost(db):
    """Review 2: retirement through the real replace_mailbox path."""
    from sqlmodel import Session
    import test_outreach_setup as t
    boost()
    m = t.setup_module_or_missing()
    biz = t.grant(db)
    t.ready(m, db, biz)
    records = t.second_mailbox(db)
    with db.begin() as c:
        raw = c.execute(text("SELECT settings FROM business_settings WHERE business_id = :b"), {"b": t.A}).scalar()
        doc = json.loads(raw or "{}")
        doc["outreach_boost"] = {t.WORKSPACE: {"level": 40, "since": STAMP}}
        c.execute(text("UPDATE business_settings SET settings = :s WHERE business_id = :b"), {"s": json.dumps(doc), "b": t.A})
    with Session(db) as s:
        m.register_mailbox(s, biz, t.OWNER, {"mailbox_id": t.NEW_BOX, "daily_cap": 5})
        m.check_mailbox_health(s, biz, t.OWNER, t.NEW_BOX, resolve=t.dns(records))
        m.replace_mailbox(s, biz, t.OWNER, {"old_mailbox_id": t.WORKSPACE, "new_mailbox_id": t.NEW_BOX,
                                           "reason": "Reputation dropped", "retire_old": True})
    with Session(db) as s:
        assert boost().level(s, t.A, t.WORKSPACE) == 20

# --------------------------------------------------------------- endpoints ---

@pytest.mark.parametrize("who,code", [(OWNER, 200), (STAFF, 403)])
def test_the_boost_endpoints(h, monkeypatch, who, code):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlmodel import Session
    import auth
    import outreach_setup_api as api
    from auth import get_user_business_context
    from db import get_session
    from rate_limiting import limiter
    from services import outreach_setup
    qualified(h)
    monkeypatch.setattr(auth, "_load_business", lambda session, bid: h.b)
    monkeypatch.setattr(auth, "assert_feature_access", lambda business, feature, **kw: None)
    monkeypatch.setattr(limiter, "enabled", False)
    monkeypatch.setattr(outreach_setup, "now", lambda: NOW)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[get_user_business_context] = lambda: {"business_id": A, "user_id": who}
    app.dependency_overrides[get_session] = lambda: Session(h.engine)
    with TestClient(app) as client:
        seen = client.get(f"/v1/outreach/setup/inboxes/{BOX}/boost")
        stepped = client.post(f"/v1/outreach/setup/inboxes/{BOX}/boost")
    assert seen.status_code == 200 and seen.json()["eligible"] is True and seen.json()["next"] == 30
    assert stepped.status_code == code
    assert level(h) == (30 if code == 200 else 20)
