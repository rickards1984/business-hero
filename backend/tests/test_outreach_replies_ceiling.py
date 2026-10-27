"""OUT-19 E — replies are never held back by the cold-email limits (Mike's
decision 2, docs/OUT-19-TICKET.md). RED: customer contact and sending limits.

Answering someone who wrote back is conversation, not cold outreach. A reply
does not count towards the brand's 20 a day, the campaign's cap, the monthly
allowance or the inbox's warm-up limit. It is bounded only by the inbox's
safety ceiling: the warm-up limit plus 20, never above 70. Cold emails are
counted without replies. Synthetic SQLite, the real approval path, no network.
"""
# ruff: noqa: F811 - pytest fixtures imported from the OUT-6/OUT-7 harnesses are parameters by design

import pytest
from sqlalchemy import text

from test_outreach_send import (  # noqa: F401 - fixtures are used by name
    A, BOX, BRAND, CAMPAIGN, NOW, OWNER, STAMP, add, approve, database, h, propose, refused_today, sent_today)
from test_outreach_replies import r, ready_answer  # noqa: F401
from services import metering

TODAY = NOW.astimezone(metering.LONDON).date().isoformat()


def box_cap(h):
    row = h.s.execute(text("SELECT * FROM outreach_mailboxes WHERE mailbox_id = :m"), {"m": BOX}).mappings().one()
    h.s.rollback()
    return metering.mailbox_daily_cap(row)


def emails_today(h, n, *, kind="initial", campaign=CAMPAIGN, state="committed"):
    """n emails of `kind` already sent today from the campaign inbox, in the
    usage events and the inbox's daily row, as the send path records them."""
    for i in range(n):
        message = add(h.s, "messages", campaign_id=campaign, mailbox_id=BOX, direction="outbound",
                      state="accepted", kind=kind)
        add(h.s, "usage_events", operation_key=f"{kind}:{i}:{message}", kind="outreach_emails_sent", quantity=1,
            state=state, mailbox_id=BOX, local_send_date=TODAY, message_id=message, period_start=STAMP, period_end=STAMP)
    row = h.s.execute(text("SELECT id FROM outreach_daily_usage WHERE scope_type = 'mailbox' AND scope_id = :m "
                           "AND local_date = :d"), {"m": BOX, "d": TODAY}).scalar()
    if row:
        h.s.execute(text("UPDATE outreach_daily_usage SET accepted = accepted + :n WHERE id = :id"), {"n": n, "id": row})
    else:
        add(h.s, "daily_usage", scope_type="mailbox", scope_id=BOX, local_date=TODAY, accepted=n, reserved=0, unknown=0)
    h.s.commit()


def send_reply(r):
    from services import aria_actions
    card = ready_answer(r)
    return aria_actions.approve(r.s, r.b, card["id"], OWNER, version=card["version"])


# ------------------------------------------------------- the ceiling itself ---

@pytest.mark.parametrize("cap,ceiling", [(0, 0), (5, 25), (10, 30), (20, 40), (50, 70), (60, 70)])
def test_the_safety_ceiling_is_the_warm_up_limit_plus_twenty_never_above_seventy(cap, ceiling):
    assert metering.reply_ceiling(cap) == ceiling


# --------------------------------------------- replies skip the cold limits ---

def test_a_reply_goes_out_when_the_brands_twenty_are_used(r):
    sent_today(r, 20, BRAND)
    assert send_reply(r)["status"] == "done" and len(r.p.sends) == 1


def test_a_reply_goes_out_when_the_inbox_and_campaign_limits_are_used(r):
    emails_today(r, box_cap(r))                      # the inbox's warm-up limit, all cold
    assert send_reply(r)["status"] == "done" and len(r.p.sends) == 1


def test_a_reply_goes_out_when_the_brands_month_is_used(r):
    from datetime import date
    first, following, weekdays = metering.month_bounds(date.fromisoformat(TODAY))
    sent_today(r, 20 * weekdays, BRAND, day=first.isoformat())
    assert send_reply(r)["status"] == "done"


def test_a_reply_is_refused_at_the_inboxs_safety_ceiling(r):
    cap = box_cap(r)
    emails_today(r, cap)
    emails_today(r, 20, kind="bespoke")
    with pytest.raises(r.a.ActionRefused) as exc:
        send_reply(r)
    assert "safety ceiling" in exc.value.detail and r.p.sends == []


def test_a_reply_goes_out_one_below_the_ceiling(r):
    emails_today(r, box_cap(r))
    emails_today(r, 19, kind="bespoke")
    assert send_reply(r)["status"] == "done"


# ------------------------------------------------- replies take no cold room ---

def test_replies_do_not_use_up_the_inboxs_cold_emails(h):
    card = propose(h)
    emails_today(h, 15, kind="bespoke")              # far more replies than the warm-up limit
    assert approve(h, card)["status"] == "done" and len(h.p.sends) == 1


def test_replies_do_not_use_up_the_brands_twenty_or_the_campaigns_cap(h):
    card = propose(h)
    sent_today(h, 19, BRAND)
    emails_today(h, 10, kind="bespoke")
    assert approve(h, card)["status"] == "done"


def test_cold_emails_still_stop_at_the_warm_up_limit(h):
    card = propose(h)
    emails_today(h, box_cap(h))
    refused_today(h, card, box_cap(h))


def test_cold_emails_also_respect_the_ceiling_when_replies_filled_it(h):
    """The ceiling is for everything the inbox sends; a cold email never
    pushes past it even when the warm-up limit has room."""
    card = propose(h)
    cap = box_cap(h)
    emails_today(h, metering.reply_ceiling(cap), kind="bespoke")
    refused_today(h, card, metering.reply_ceiling(cap))


# -------------------------------------------------- the owner's three choices ---

def test_headroom_says_when_replies_are_close_to_the_ceiling(h):
    cap = box_cap(h)
    room = metering.reply_headroom(h.s, A, BOX, NOW)
    assert room == {"cap": cap, "ceiling": cap + 20, "used": 0, "left": cap + 20, "blocked": None, "near_ceiling": False}
    emails_today(h, cap + 20 - metering.REPLY_NEAR, kind="bespoke")
    near = metering.reply_headroom(h.s, A, BOX, NOW)
    assert near["left"] == metering.REPLY_NEAR and near["near_ceiling"] is True


def test_research_room_ignores_replies(h):
    """OUT-19 D and E together: replies never shrink the room for new contacts."""
    from services import outreach_research
    before = outreach_research.capacity(h.s, A, BRAND, NOW)
    h.s.rollback()
    emails_today(h, 12, kind="bespoke")
    after = outreach_research.capacity(h.s, A, BRAND, NOW)
    assert after["sent_today"] == before["sent_today"] == 0 and after["room"] == before["room"]


# ------------------------------------------ "I'll reply myself" and headroom ---

def test_the_briefing_gives_the_owner_everything_to_answer_themselves(r):
    from test_outreach_replies import answer, fact, incoming, reply_id, scan
    fact(r)
    incoming(r)
    scan(r)
    answer(r)
    out = r.replies.brief(r.s, r.b, reply_id=reply_id(r), user_id=OWNER, moment=NOW)
    assert out["asked"]["text"] == "When are appointments available?"
    assert out["who"]["email"] and out["category"] == "question"
    assert out["suggested_answer"] == "Weekday appointments"
    assert out["facts"] == [{"topic": "availability", "answer": "Weekday appointments",
                             "source": "https://example.invalid/facts"}]
    assert out["mailbox"] and "I'll handle this" in out["how"]


def test_only_the_owner_sees_the_briefing(r):
    from test_outreach_replies import incoming, reply_id, scan
    from test_outreach_send import STAFF
    incoming(r)
    scan(r)
    with pytest.raises(r.a.ActionRefused) as exc:
        r.replies.brief(r.s, r.b, reply_id=reply_id(r), user_id=STAFF, moment=NOW)
    assert exc.value.status_code == 403


def test_headroom_lists_each_inbox_and_flags_the_ones_near_the_ceiling(r):
    from test_outreach_replies import incoming, scan
    incoming(r)
    scan(r)
    cap = box_cap(r)
    calm = r.replies.headroom(r.s, r.b, moment=NOW)
    mine = next(b for b in calm["inboxes"] if b["mailbox_id"] == BOX)
    assert mine["left"] == cap + 20 and mine["pending_replies"] == 1 and calm["near_ceiling"] == []
    emails_today(r, cap)
    emails_today(r, 20 - metering.REPLY_NEAR, kind="bespoke")
    busy = r.replies.headroom(r.s, r.b, moment=NOW)
    assert [b["mailbox_id"] for b in busy["near_ceiling"]] == [BOX]
    assert "email" in busy["near_ceiling"][0] and "@" not in str({k: v for k, v in busy["near_ceiling"][0].items() if k != "email"})


@pytest.mark.parametrize("user", ["owner", "staff"])
def test_the_briefing_and_headroom_over_http(r, monkeypatch, user):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from auth import get_user_business_context
    from db import get_session
    from app.email import router as email_router
    import outreach_read
    from outreach_read import router
    from test_outreach_replies import incoming, reply_id, scan
    from test_outreach_send import STAFF
    monkeypatch.setattr(outreach_read, "_load_business", lambda session, bid: r.b)
    incoming(r)
    scan(r)
    rid = reply_id(r)
    who = OWNER if user == "owner" else STAFF
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_user_business_context] = lambda: {"business_id": A, "user_id": who}
    app.dependency_overrides[get_session] = lambda: r.s
    monkeypatch.setattr(email_router, "get_business_by_id", lambda *_: r.b)
    with TestClient(app) as client:
        brief = client.get(f"/v1/outreach/replies/{rid}/brief")
        room = client.get("/v1/outreach/inboxes/headroom")
    assert brief.status_code == (200 if user == "owner" else 403)
    assert room.status_code == 200 and room.json()["inboxes"]



# ------------------------------------------------------ Codex OUT-19 E review 1 ---

@pytest.mark.parametrize("plan,flags,status,active", [
    ("business", {"outreach": False}, "active", True), ("starter", {}, "active", True),
    ("business", {}, "active", False)])
def test_the_new_reads_are_behind_the_outreach_gate(r, monkeypatch, plan, flags, status, active):
    """P1: explicit denial, no entitlement and suspension refuse both reads."""
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from auth import get_user_business_context
    from db import get_session
    from app.email import router as email_router
    import outreach_read
    from test_outreach_replies import incoming, reply_id, scan
    incoming(r)
    scan(r)
    rid = reply_id(r)
    denied = SimpleNamespace(**{**vars(r.b), "plan_tier": plan, "feature_flags": flags,
                                "subscription_status": status, "is_active": active})
    app = FastAPI()
    app.include_router(outreach_read.router)
    app.dependency_overrides[get_user_business_context] = lambda: {"business_id": A, "user_id": OWNER}
    app.dependency_overrides[get_session] = lambda: r.s
    monkeypatch.setattr(email_router, "get_business_by_id", lambda *_: r.b)
    monkeypatch.setattr(outreach_read, "_load_business", lambda session, bid: denied)
    with TestClient(app) as client:
        brief = client.get(f"/v1/outreach/replies/{rid}/brief").status_code
        room = client.get("/v1/outreach/inboxes/headroom").status_code
    # A briefing is reply history: like every reply read (OUT-7), it survives a
    # downgrade while the account is active and outreach isn't explicitly denied.
    assert brief == (200 if active and not flags else 403)
    assert room == 403


def test_a_suggestion_whose_fact_was_retired_is_not_offered(r):
    """P1: the briefing re-checks Aria's answer against today's approved facts."""
    from sqlalchemy import text as t
    from test_outreach_replies import answer, fact, incoming, reply_id, scan
    fact(r)
    incoming(r)
    scan(r)
    answer(r)
    r.s.execute(t("UPDATE outreach_knowledge SET status = 'retired'"))
    r.s.commit()
    out = r.replies.brief(r.s, r.b, reply_id=reply_id(r), user_id=OWNER, moment=NOW)
    assert out["suggested_answer"] is None and "no longer approved" in out["no_suggestion_reason"]
    assert out["facts"] == []


def test_past_its_retention_date_the_briefing_withholds_the_contact(r):
    """P2: retention minimisation, as on every other read."""
    from datetime import timedelta
    from sqlalchemy import text as t
    from test_outreach_replies import incoming, reply_id, scan
    incoming(r)
    scan(r)
    r.s.execute(t("UPDATE outreach_prospects SET retention_due_at = :d"), {"d": (NOW - timedelta(days=1)).isoformat()})
    r.s.commit()
    out = r.replies.brief(r.s, r.b, reply_id=reply_id(r), user_id=OWNER, moment=NOW)
    assert out["retained"] is False and set(out["who"].values()) == {None} and out["asked"]["text"] is None


def test_headroom_says_when_the_inbox_cannot_send_today(h):
    """P2: allowance left is not the same as able to send."""
    from datetime import timedelta
    h.s.execute(text("UPDATE outreach_mailboxes SET health_checked_at = :d WHERE mailbox_id = :m"),
                {"d": (NOW - timedelta(days=1)).isoformat(), "m": BOX})
    h.s.commit()
    room = metering.reply_headroom(h.s, A, BOX, NOW)
    assert room["blocked"] and "check" in room["blocked"] and room["near_ceiling"] is False


def test_the_warm_up_limit_holds_cold_emails_with_campaign_and_brand_room_to_spare(h):
    """P2: isolate the inbox's own limit — another campaign on the same inbox
    used it up, while this campaign and brand still have room."""
    card = propose(h)
    other = add(h.s, "campaigns", brand_id=BRAND, mailbox_id=BOX, name="Other", target_rules="{}", target_hash="other",
                sequence_version=1, version=1, status="ready", timezone="Europe/London", daily_cap=20)
    h.s.commit()
    emails_today(h, box_cap(h), campaign=other)
    refused_today(h, card, box_cap(h))


@pytest.mark.parametrize("kind", [None, "imported", "followup"])
def test_an_email_of_unknown_or_any_cold_kind_counts_as_cold(h, kind):
    card = propose(h)
    other = add(h.s, "campaigns", brand_id=BRAND, mailbox_id=BOX, name="Other", target_rules="{}", target_hash="other",
                sequence_version=1, version=1, status="ready", timezone="Europe/London", daily_cap=20)
    h.s.commit()
    emails_today(h, box_cap(h), kind=kind, campaign=other)
    refused_today(h, card, box_cap(h))


@pytest.mark.parametrize("state", ["reserved", "unknown"])
def test_held_and_unknown_cold_emails_count_toward_the_warm_up_limit(h, state):
    card = propose(h)
    other = add(h.s, "campaigns", brand_id=BRAND, mailbox_id=BOX, name="Other", target_rules="{}", target_hash="other",
                sequence_version=1, version=1, status="ready", timezone="Europe/London", daily_cap=20)
    h.s.commit()
    emails_today(h, box_cap(h), campaign=other, state=state)
    refused_today(h, card, box_cap(h))


@pytest.mark.parametrize("state", ["committed", "unknown"])
def test_sent_and_unknown_replies_never_count_as_cold(h, state):
    card = propose(h)
    emails_today(h, 10, kind="bespoke", state=state)
    assert approve(h, card)["status"] == "done"


# ------------------------------------------------------ Codex OUT-19 E review 2 ---

def test_a_health_check_dated_in_the_future_does_not_count(h):
    from datetime import timedelta
    h.s.execute(text("UPDATE outreach_mailboxes SET health_checked_at = :d WHERE mailbox_id = :m"),
                {"d": (NOW + timedelta(minutes=30)).isoformat(), "m": BOX})
    h.s.commit()
    assert metering.reply_headroom(h.s, A, BOX, NOW)["blocked"]


def test_briefing_and_headroom_never_reach_another_business(r):
    from services.aria_actions import ActionRefused
    from test_outreach_replies import incoming, reply_id, scan
    from test_outreach_send import B
    from types import SimpleNamespace
    incoming(r)
    scan(r)
    rid = reply_id(r)
    other = SimpleNamespace(**{**vars(r.b), "id": B})
    with pytest.raises(ActionRefused):
        r.replies.brief(r.s, other, reply_id=rid, user_id=OWNER, moment=NOW)
    r.s.rollback()
    assert all(b["mailbox_id"] != BOX for b in r.replies.headroom(r.s, other, moment=NOW)["inboxes"])


def test_the_retention_notice_never_claims_deletion():
    from pathlib import Path
    card = (Path(__file__).parents[2] / "frontend/client/src/components/OutreachReplyCard.tsx").read_text()
    assert "withheld from this briefing" in card and "no longer kept" not in card
