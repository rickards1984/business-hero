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

Tests first: strict xfail until services.outreach_boost exists and Mike
approves. Synthetic SQLite, the real send path, no network.
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
    A, BOX, BRAND, CAMPAIGN, NOW, OWNER, PROSPECT, STAFF, STAMP, add, approve, database, h, propose,
    refused_today, sent_today)
from test_outreach_replies_ceiling import emails_today
from services import metering


class MissingBoost(AssertionError):
    """Only the intentional absence of the module may be xfailed."""


pytestmark = pytest.mark.xfail(strict=True, raises=MissingBoost,
                               reason="OUT-19 G: tests first, until Mike approves and the module exists")


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
    """n cold emails sent from the campaign inbox over the `days` before today."""
    for i in range(n):
        when = day(1 + i % (days - 1))
        message = add(h.s, "messages", campaign_id=CAMPAIGN, mailbox_id=BOX, prospect_id=PROSPECT,
                      direction="outbound", state="accepted", kind=kind)
        add(h.s, "usage_events", operation_key=f"history:{i}:{message}", kind="outreach_emails_sent", quantity=1,
            state="committed", mailbox_id=BOX, local_send_date=when, message_id=message,
            period_start=STAMP, period_end=STAMP)
    h.s.commit()


def replies(h, category, n=1, *, days_ago=3):
    for _ in range(n):
        add(h.s, "replies", prospect_id=PROSPECT, mailbox_id=BOX, inbound_email_id=str(uuid.uuid4()),
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

def test_a_boosted_inbox_sends_up_to_its_new_limit_and_no_further(h):
    qualified(h)
    do_boost(h)
    emails_today(h, 29)
    assert approve(h, propose(h))["status"] == "done"
    card = propose(h)
    refused_today(h, card, 30)


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
    set_level(h, 40, since_days=20)
    review(h)
    assert level(h) == 40


@pytest.mark.parametrize("spoil", [
    lambda h: replies(h, "bounce", 5, days_ago=2),
    lambda h: replies(h, "unsubscribe", 3, days_ago=2),
    lambda h: (boost().record_check(h.s, A, BOX, NOW - timedelta(days=2), passed=False), h.s.commit()),
])
def test_a_worse_fortnight_drops_one_step_and_holds_fourteen_days(h, spoil):
    qualified(h)
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
    out = boost().evidence(h.s, A, BOX, NOW + timedelta(hours=1), days=14)
    h.s.rollback()
    assert out["failed_checks"] == 1


def test_the_daily_inbox_check_records_failures_and_reviews_the_boost():
    import inspect
    boost()
    from services import outreach_setup
    source = inspect.getsource(outreach_setup._apply_health)
    assert "outreach_boost.record_check" in source and "outreach_boost.review" in source


def test_another_business_cannot_see_or_boost_this_inbox(h):
    qualified(h)
    from test_outreach_send import B
    other = boost().eligibility(h.s, B, BOX, NOW)
    h.s.rollback()
    assert other["eligible"] is False and other["evidence"]["cold"] == 0
