"""OUT-14 — the outreach dashboard (docs/OUT-14-TICKET.md). YELLOW.

Mike, 30 Oct 2026: the approved layout (brand switcher, Aria's summary, Needs
you, pipeline, results for a period, spend); meetings and wins are marked by
the owner, never inferred; the spend panel is the owner's only.

Every number comes from one function shared by the screen and Aria, counted
by the design's definitions: accepted is provider acceptance, imports never
count as contact, bounces/out-of-office/self/complaints/unknown are not human
replies, a zero denominator is "unavailable". Synthetic SQLite, no network.
"""
# ruff: noqa: F811 - pytest fixtures imported from the OUT-6 harness are parameters by design

import importlib
import json
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text

from test_outreach_send import (  # noqa: F401 - fixtures are used by name
    A, B, BOX, BRAND, CAMPAIGN, DEFAULT, LIA, NOW, OWNER, PROSPECT, STAFF, STAMP, add, database, h)

BRAND2, LIA2, CAMPAIGN2 = (str(uuid.uuid5(uuid.NAMESPACE_URL, f"out14-{n}")) for n in ("brand2", "lia2", "campaign2"))


def dash():
    return importlib.import_module("services.outreach_dashboard")


def ago(days=0, hours=0):
    return (NOW - timedelta(days=days, hours=hours)).isoformat()


def second_brand(h):
    add(h.s, "brands", id=BRAND2, name="FitFutures", default_mailbox_id=DEFAULT,
        privacy_url="https://example.invalid/p2", sender_identity="FitFutures", version=1)
    add(h.s, "compliance", id=LIA2, brand_id=BRAND2, audience_hash="audience-2", version=1, purpose="x",
        necessity="x", balancing_test="x", safeguards="x", sources="[]", decision="approved", reviewer=OWNER,
        reviewed_at=STAMP, review_due_at=ago(-30))
    add(h.s, "campaigns", id=CAMPAIGN2, brand_id=BRAND2, mailbox_id=DEFAULT, name="Fit", target_rules="{}",
        target_hash="audience-2", sequence_version=1, version=1, status="ready", timezone="Europe/London", daily_cap=5)
    h.s.commit()


def person(h, *, eligibility="eligible", lia=LIA, stage="ready", business=A):
    pid = add(h.s, "prospects", business_id=business, company=f"Co {uuid.uuid4().hex[:4]}", name="Someone",
              role="Director", domain="example.invalid", email=f"{uuid.uuid4().hex[:8]}@example.invalid",
              email_key=uuid.uuid4().hex, subscriber_type="corporate", eligibility=eligibility,
              lawful_basis="legitimate_interests", lia_id=lia, stage=stage, captured_at=ago(40),
              evidence_checked_at=STAMP, notice_due_at=ago(-10), retention_due_at=ago(-300))
    h.s.commit()
    return pid


def sent(h, prospect, *, days_ago=1, campaign=CAMPAIGN, mailbox=BOX, kind="initial", origin="live",
         state="accepted", business=A):
    add(h.s, "messages", business_id=business, prospect_id=prospect, campaign_id=campaign, mailbox_id=mailbox,
        kind=kind, origin=origin, direction="outbound", state=state, accepted_at=ago(days_ago),
        created_at=ago(days_ago))
    h.s.commit()


def replied(h, prospect, category, *, days_ago=1, resolution="resolved", mailbox=BOX, business=A):
    add(h.s, "replies", business_id=business, prospect_id=prospect, mailbox_id=mailbox,
        inbound_email_id=str(uuid.uuid4()), category=category, knowledge_refs="[]", resolution=resolution,
        received_at=ago(days_ago))
    h.s.commit()


def board(h, *, brand=None, period="week", spend=False):
    out = dash().build(h.s, h.b, brand_id=brand, period=period, moment=NOW, include_spend=spend)
    h.s.rollback()
    return out


def mark(h, prospect, outcome, user=OWNER, moment=NOW, expected=None):
    out = dash().mark_outcome(h.s, h.b, user, prospect, outcome, moment=moment, expected=expected)
    h.s.commit()
    return out


# ---------------------------------------------------------------- pipeline ---

def test_each_prospect_is_counted_once_at_its_furthest_stage(h):
    found = person(h, eligibility="review", stage="new")
    contacted = person(h)
    sent(h, contacted)
    plain = person(h)
    sent(h, plain)
    replied(h, plain, "not_now")
    keen = person(h)
    sent(h, keen)
    replied(h, keen, "not_now")
    replied(h, keen, "interested")
    booked = person(h)
    sent(h, booked)
    replied(h, booked, "interested")
    mark(h, booked, "meeting")
    p = board(h)["pipeline"]
    # the seeded prospect is Ready, never contacted
    assert p == {"found": 1, "ready": 1, "contacted": 1, "replied": 1, "interested": 1,
                 "meeting": 1, "won": 0, "closed": 0}
    assert found and contacted


def test_imported_history_is_never_contact(h):
    imported = person(h)
    sent(h, imported, origin="import", state="imported")
    p = board(h)["pipeline"]
    assert p["contacted"] == 0 and p["ready"] == 2


@pytest.mark.parametrize("category", ["bounce", "out_of_office", "self", "complaint", "unknown"])
def test_machine_and_unknown_replies_are_not_human_replies(h, category):
    who = person(h)
    sent(h, who)
    replied(h, who, category)
    p = board(h)["pipeline"]
    assert p["contacted"] == 1 and p["replied"] == 0


@pytest.mark.parametrize("state", ["failed", "unknown", "draft", "cancelled"])
def test_only_accepted_emails_are_contact(h, state):
    who = person(h)
    sent(h, who, state=state)
    assert board(h)["pipeline"]["contacted"] == 0


def test_an_owners_mark_outranks_and_undoing_it_restores_the_evidence(h):
    keen = person(h)
    sent(h, keen)
    replied(h, keen, "referral")
    mark(h, keen, "won")
    assert board(h)["pipeline"]["won"] == 1
    mark(h, keen, None)
    p = board(h)["pipeline"]
    assert p["won"] == 0 and p["interested"] == 1
    stage = h.s.execute(text("SELECT stage FROM outreach_prospects WHERE id = :p"), {"p": keen}).scalar()
    assert stage == "ready"


def test_each_brand_shows_only_its_own_people_and_all_shows_both(h):
    second_brand(h)
    theirs = person(h, lia=LIA2)
    sent(h, theirs, campaign=CAMPAIGN2, mailbox=DEFAULT)
    mine = person(h)
    sent(h, mine)
    assert board(h, brand=BRAND)["pipeline"]["contacted"] == 1
    assert sum(board(h, brand=BRAND)["pipeline"].values()) == 2, "the seeded prospect and mine, not theirs"
    assert sum(board(h, brand=BRAND2)["pipeline"].values()) == 1
    assert board(h, brand=BRAND2)["pipeline"]["contacted"] == 1
    assert board(h)["pipeline"]["contacted"] == 2
    names = {b["id"]: b["name"] for b in board(h)["brands"]}
    assert names == {BRAND: "Synthetic Ltd", BRAND2: "FitFutures"}


def test_another_brands_id_or_another_business_shows_nothing_of_theirs(h):
    other = person(h, business=B, lia=str(uuid.uuid4()))
    sent(h, other, business=B, campaign=str(uuid.uuid4()), mailbox=str(uuid.uuid4()))
    replied(h, other, "interested", business=B, mailbox=str(uuid.uuid4()), resolution="pending")
    out = board(h)
    assert out["pipeline"]["contacted"] == 0 and out["pipeline"]["interested"] == 0
    assert out["needs_you"]["replies_waiting"] == 0
    with pytest.raises(Exception) as exc:
        board(h, brand=str(uuid.uuid4()))
    assert getattr(exc.value, "status_code", None) == 404


def test_another_businesss_rows_never_count_even_when_they_name_our_prospect(h):
    """Every table is read with this business's id, not only joined to our people."""
    mine = person(h)
    sent(h, mine)
    replied(h, mine, "interested", business=B, mailbox=str(uuid.uuid4()), resolution="pending")
    sent(h, mine, business=B, campaign=CAMPAIGN, mailbox=str(uuid.uuid4()), days_ago=0)
    out = board(h)
    assert out["pipeline"]["interested"] == 0 and out["pipeline"]["contacted"] == 1
    assert out["needs_you"]["replies_waiting"] == 0 and out["results"]["emails_sent"] == 1


# ----------------------------------------------------------------- results ---

def test_the_contacted_cohort_is_first_contact_in_the_period(h):
    earlier = person(h)
    sent(h, earlier, days_ago=20)
    sent(h, earlier, days_ago=1, kind="followup")      # a follow-up this week isn't a new contact
    fresh = person(h)
    sent(h, fresh, days_ago=2)
    r = board(h)["results"]
    assert r["contacted"] == 1
    assert board(h, period="all")["results"]["contacted"] == 2


def test_replies_and_rates_belong_to_the_cohort_whenever_they_came(h):
    a, b_, c = person(h), person(h), person(h)
    for who in (a, b_, c):
        sent(h, who, days_ago=3)
    replied(h, a, "interested", days_ago=0)
    replied(h, b_, "objection", days_ago=1)
    old = person(h)
    sent(h, old, days_ago=30)
    replied(h, old, "interested", days_ago=1)        # outside this week's cohort
    r = board(h)["results"]
    assert (r["contacted"], r["replied"], r["positive"]) == (3, 2, 1)
    assert r["reply_rate"] == pytest.approx(2 / 3) and r["positive_rate"] == pytest.approx(1 / 3)


def test_with_nobody_contacted_rates_are_unavailable_not_zero(h):
    r = board(h)["results"]
    assert r["contacted"] == 0 and r["reply_rate"] is None and r["positive_rate"] is None


def test_emails_sent_counts_accepted_live_sends_in_the_period(h):
    who = person(h)
    sent(h, who, days_ago=1)
    sent(h, who, days_ago=2, kind="bespoke")          # a reply to them counts as an email sent
    sent(h, who, days_ago=3, state="unknown")
    sent(h, who, days_ago=3, origin="import", state="imported")
    sent(h, who, days_ago=10)
    assert board(h)["results"]["emails_sent"] == 2
    assert board(h, period="all")["results"]["emails_sent"] == 3


def test_objections_bounces_meetings_and_wins_are_counted_by_their_own_date(h):
    who, other, third = person(h), person(h), person(h)
    for p in (who, other, third):
        sent(h, p, days_ago=30)
    replied(h, who, "objection", days_ago=2)
    replied(h, other, "bounce", days_ago=2)
    replied(h, third, "bounce", days_ago=12)
    mark(h, who, "meeting", moment=NOW - timedelta(days=1))
    mark(h, other, "won", moment=NOW - timedelta(days=9))
    r = board(h)["results"]
    assert (r["objections"], r["bounces"], r["meetings"], r["wins"]) == (1, 1, 1, 0)
    assert board(h, period="all")["results"]["wins"] == 1


def test_this_month_is_the_uk_calendar_month(h):
    who = person(h)
    first_of_month = NOW.replace(day=1, hour=9)
    sent(h, who, days_ago=(NOW - first_of_month).days)
    before = person(h)
    sent(h, before, days_ago=(NOW - first_of_month).days + 2)
    assert board(h, period="month")["results"]["contacted"] == 1


@pytest.mark.parametrize("bad", ["year", "", "WEEK"])
def test_an_unknown_period_is_refused(h, bad):
    with pytest.raises(Exception) as exc:
        board(h, period=bad)
    assert getattr(exc.value, "status_code", None) == 422


# ---------------------------------------------------------------- needs you ---

def test_needs_you_counts_waiting_replies_approvals_and_failures(h):
    who = person(h)
    sent(h, who)
    replied(h, who, "question", resolution="pending")
    replied(h, who, "not_now", resolution="handed_over")
    replied(h, who, "interested", resolution="resolved")
    replied(h, who, "bounce", resolution="pending")       # not a human reply: nothing to answer
    for kind, status in (("send_outreach", "proposed"), ("reply_outreach", "proposed"), ("send_outreach", "done"),
                         ("send_email", "proposed")):
        h.s.execute(text("INSERT INTO aria_actions (id, business_id, action_type, status, payload, created_at) "
                         "VALUES (:i, :b, :k, :s, :p, :t)"),
                    {"i": str(uuid.uuid4()), "b": A, "k": kind, "s": status,
                     "p": json.dumps({"campaign_id": CAMPAIGN}), "t": STAMP})
    sent(h, who, days_ago=2, state="unknown")
    sent(h, who, days_ago=20, state="failed")             # too old to need attention
    h.s.execute(text("UPDATE outreach_mailboxes SET pause_reason = 'complaint' WHERE mailbox_id = :m"), {"m": BOX})
    h.s.commit()
    n = board(h)["needs_you"]
    assert n["replies_waiting"] == 2 and n["approvals"] == 2
    assert n["failures"]["emails"] == 1 and n["failures"]["paused_inboxes"] == 1


def billing_state(h, brand, entry):
    raw = h.s.execute(text("SELECT settings FROM business_settings WHERE business_id = :b"), {"b": A}).scalar()
    doc = json.loads(raw or "{}")
    doc.setdefault("outreach_brand_billing", {}).setdefault("brands", {})[brand] = entry
    h.s.execute(text("UPDATE business_settings SET settings = :s WHERE business_id = :b"), {"s": json.dumps(doc), "b": A})
    h.s.commit()


def paid_brand(monkeypatch):
    from services import outreach_allowance
    monkeypatch.setattr(outreach_allowance, "prices", lambda session, bid: {BRAND: (7900, False)})


@pytest.mark.parametrize("state", ["awaiting_payment", "pending"])
def test_a_brand_waiting_for_payment_needs_the_owner(h, monkeypatch, state):
    paid_brand(monkeypatch)
    billing_state(h, BRAND, {"state": state, "price": 7900})
    assert board(h)["needs_you"]["failures"]["awaiting_payment"] == 1


def test_a_brand_the_owner_stopped_is_not_a_payment_problem(h, monkeypatch):
    """Codex review 1: its paid month has ended; nothing is owed."""
    paid_brand(monkeypatch)
    billing_state(h, BRAND, {"state": "ending", "price": 7900, "ends_at": (NOW - timedelta(days=3)).isoformat()})
    out = board(h, spend=True)
    assert out["needs_you"]["failures"]["awaiting_payment"] == 0
    assert next(b for b in out["spend"]["brands"] if b["brand_id"] == BRAND)["billing"] == "stopped"


# ------------------------------------------------------------------- spend ---

def test_spend_is_given_only_when_asked_for_the_owner(h):
    from services import outreach_allowance
    period = NOW.astimezone(__import__("services.metering", fromlist=["LONDON"]).LONDON).strftime("%Y-%m")
    out = board(h, spend=True)
    row = next(r for r in out["spend"]["brands"] if r["brand_id"] == BRAND)
    assert row["allowance_pence"] == outreach_allowance.allowance_pence(h.s, A, BRAND, period)
    assert row["spent_pence"] == outreach_allowance.spent_pence(h.s, A, BRAND, period)
    assert "budget" in out["spend"]
    h.s.rollback()
    assert "spend" not in board(h, spend=False)


# --------------------------------------------------- the summary and Aria ---

def test_arias_summary_never_gives_the_all_clear_with_a_problem(h):
    """Codex review 1: a failure is something that needs the owner."""
    who = person(h)
    sent(h, who, days_ago=1, state="failed")
    s = board(h)["summary"]
    assert "Nothing needs you" not in s and "1 problem needs a look" in s


def test_arias_summary_is_built_from_the_numbers(h):
    who = person(h)
    sent(h, who, days_ago=1)
    replied(h, who, "interested", resolution="pending")
    out = board(h)
    s = out["summary"]
    assert "1 person contacted" in s and "1 replied" in s and "1 interested" in s
    assert "1 reply needs you" in s


def test_aria_reads_the_same_numbers_without_spend(h, monkeypatch):
    import assistant_tools
    who = person(h)
    sent(h, who)
    assert "get_outreach_dashboard" in {t["function"]["name"] for t in assistant_tools.TOOL_DEFINITIONS}
    monkeypatch.setattr(dash(), "_session_and_business", lambda business_id: (h.s, h.b))
    out = assistant_tools.execute_tool("get_outreach_dashboard", {"period": "week"}, A)
    expected = board(h)
    assert out["pipeline"] == expected["pipeline"] and out["results"] == expected["results"]
    assert "spend" not in out


# ------------------------------------------------- marking meetings and wins ---

def test_only_the_owner_marks_a_meeting_or_a_win(h):
    who = person(h)
    with pytest.raises(Exception) as exc:
        mark(h, who, "meeting", user=STAFF)
    assert getattr(exc.value, "status_code", None) == 403
    assert board(h)["pipeline"]["meeting"] == 0


@pytest.mark.parametrize("bad", ["qualified", "replied", "", "WON"])
def test_only_meeting_won_closed_or_undo_may_be_marked(h, bad):
    who = person(h)
    with pytest.raises(Exception) as exc:
        mark(h, who, bad)
    assert getattr(exc.value, "status_code", None) == 422


def test_another_businesss_prospect_cannot_be_marked(h):
    other = person(h, business=B, lia=str(uuid.uuid4()))
    with pytest.raises(Exception) as exc:
        mark(h, other, "won")
    assert getattr(exc.value, "status_code", None) == 404
    assert h.s.execute(text("SELECT stage FROM outreach_prospects WHERE id = :p"), {"p": other}).scalar() == "ready"


def test_a_meeting_that_becomes_a_win_keeps_its_meeting(h):
    """Codex review 1: marking Won after a meeting doesn't erase the meeting."""
    who = person(h)
    mark(h, who, "meeting", moment=NOW - timedelta(days=2))
    mark(h, who, "won")
    out = board(h)
    assert (out["results"]["meetings"], out["results"]["wins"]) == (1, 1)
    assert out["pipeline"]["won"] == 1 and out["pipeline"]["meeting"] == 0
    mark(h, who, None)                     # undo the win: back to the meeting
    out = board(h)
    assert (out["results"]["meetings"], out["results"]["wins"]) == (1, 0) and out["pipeline"]["meeting"] == 1
    mark(h, who, None)                     # and undo the meeting
    out = board(h)
    assert out["results"]["meetings"] == 0 and out["pipeline"]["ready"] == 2


def test_a_mark_on_a_deleted_prospect_drops_out(h):
    """Retention deletes the prospect; its marks no longer count."""
    who = person(h)
    mark(h, who, "won")
    h.s.execute(text("DELETE FROM outreach_prospects WHERE id = :p"), {"p": who})
    h.s.commit()
    assert board(h, period="all")["results"]["wins"] == 0


def test_a_mark_records_who_and_when_and_nothing_else(h):
    who = person(h)
    mark(h, who, "meeting")
    doc = json.loads(h.s.execute(text("SELECT settings FROM business_settings WHERE business_id = :b"),
                                 {"b": A}).scalar())
    assert doc["outreach_outcomes"][who] == {"events": [{"outcome": "meeting", "by": OWNER, "at": NOW.isoformat()}]}


# ------------------------------------------------------------- stage lists ---

def test_past_retention_a_persons_details_are_withheld_from_the_list(h):
    """Codex review 1 (P1): as the prospect reader does."""
    expired = person(h)
    h.s.execute(text("UPDATE outreach_prospects SET retention_due_at = :t WHERE id = :p"),
                {"t": (NOW - timedelta(days=1)).isoformat(), "p": expired})
    h.s.commit()
    out = dash().stage_list(h.s, A, "ready", brand_id=None, limit=20, offset=0, moment=NOW)
    h.s.rollback()
    row = next(i for i in out["items"] if i["id"] == expired)
    assert row["details_withheld"] is True and row["company"] is None and row["name"] is None and row["role"] is None
    kept = next(i for i in out["items"] if i["id"] == PROSPECT)
    assert kept["details_withheld"] is False and kept["name"] == "Person"


def test_a_mark_is_the_latest_activity(h):
    who = person(h)
    sent(h, who, days_ago=5)
    mark(h, who, "meeting", moment=NOW - timedelta(days=1))
    out = dash().stage_list(h.s, A, "meeting", brand_id=None, limit=20, offset=0, moment=NOW)
    h.s.rollback()
    assert out["items"][0]["last_activity_at"] == (NOW - timedelta(days=1)).isoformat()


def test_approvals_follow_the_brand_chosen(h):
    second_brand(h)
    for campaign in (CAMPAIGN, CAMPAIGN2, CAMPAIGN2):
        h.s.execute(text("INSERT INTO aria_actions (id, business_id, action_type, status, payload, created_at) "
                         "VALUES (:i, :b, 'send_outreach', 'proposed', :p, :t)"),
                    {"i": str(uuid.uuid4()), "b": A, "p": json.dumps({"campaign_id": campaign}), "t": STAMP})
    h.s.commit()
    assert board(h)["needs_you"]["approvals"] == 3
    assert board(h, brand=BRAND)["needs_you"]["approvals"] == 1
    assert board(h, brand=BRAND2)["needs_you"]["approvals"] == 2


def test_paid_top_ups_are_reported_as_paid(h):
    from services import outreach_research
    outreach_research._add_meter(h.s, A, f"outreach_topup_pence:{BRAND}", NOW, 2500)
    h.s.commit()
    row = next(b for b in board(h, spend=True)["spend"]["brands"] if b["brand_id"] == BRAND)
    assert row["topups_pence"] == 2500


def test_a_stage_opens_the_people_in_it(h):
    keen = person(h)
    sent(h, keen)
    replied(h, keen, "interested")
    out = dash().stage_list(h.s, A, "interested", brand_id=None, limit=20, offset=0)
    h.s.rollback()
    assert out["total"] == 1 and out["items"][0]["id"] == keen
    assert set(out["items"][0]) == {"id", "company", "name", "role", "details_withheld", "last_activity_at"}


def test_stage_lists_page_and_refuse_unknown_stages(h):
    for _ in range(3):
        person(h)
    page = dash().stage_list(h.s, A, "ready", brand_id=None, limit=2, offset=2)
    h.s.rollback()
    assert page["total"] == 4 and len(page["items"]) == 2
    with pytest.raises(Exception) as exc:
        dash().stage_list(h.s, A, "everyone", brand_id=None, limit=20, offset=0)
    assert getattr(exc.value, "status_code", None) == 422


# --------------------------------------------------------------- endpoints ---

@pytest.mark.parametrize("who,code,spend", [(OWNER, 200, True), (STAFF, 403, False)])
def test_the_endpoints(h, monkeypatch, who, code, spend):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlmodel import Session
    import auth
    import outreach_dashboard_api as api
    from auth import get_user_business_context
    from db import get_session
    from rate_limiting import limiter
    keen = person(h)
    monkeypatch.setattr(auth, "_load_business", lambda session, bid: h.b)
    monkeypatch.setattr(auth, "assert_feature_access", lambda business, feature, **kw: None)
    monkeypatch.setattr(limiter, "enabled", False)
    monkeypatch.setattr(dash(), "now", lambda: NOW)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[get_user_business_context] = lambda: {"business_id": A, "user_id": who}
    app.dependency_overrides[get_session] = lambda: Session(h.engine)
    with TestClient(app) as client:
        seen = client.get("/v1/outreach/dashboard?period=week")
        listed = client.get("/v1/outreach/dashboard/stage/ready?limit=20&offset=0")
        marked = client.post(f"/v1/outreach/dashboard/prospects/{keen}/outcome", json={"outcome": "won"})
        bad = client.get("/v1/outreach/dashboard?period=decade")
    assert seen.status_code == 200 and listed.status_code == 200 and bad.status_code == 422
    assert ("spend" in seen.json()) is spend
    assert marked.status_code == code



def test_without_outreach_access_the_dashboard_is_refused(h, monkeypatch):
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
    from sqlmodel import Session
    import auth
    import outreach_dashboard_api as api
    from auth import get_user_business_context
    from db import get_session

    def denied(business, feature, **kw):
        raise HTTPException(403, "Outreach isn't on this plan")
    monkeypatch.setattr(auth, "_load_business", lambda session, bid: h.b)
    monkeypatch.setattr(auth, "assert_feature_access", denied)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[get_user_business_context] = lambda: {"business_id": A, "user_id": OWNER}
    app.dependency_overrides[get_session] = lambda: Session(h.engine)
    with TestClient(app) as client:
        assert client.get("/v1/outreach/dashboard").status_code == 403
        assert client.get("/v1/outreach/dashboard/stage/ready").status_code == 403
        assert client.post(f"/v1/outreach/dashboard/prospects/{PROSPECT}/outcome", json={"outcome": "won"}).status_code == 403


def test_arias_tool_checks_outreach_access(monkeypatch):
    from fastapi import HTTPException
    import auth
    from services import outreach_setup

    class Row:
        feature_flags = {}
    monkeypatch.setattr(outreach_setup, "load_business_row", lambda session, bid: Row())

    def denied(business, feature, **kw):
        raise HTTPException(403, "Outreach isn't on this plan")
    monkeypatch.setattr(auth, "assert_feature_access", denied)
    out = dash().aria(A, {"period": "week"})
    assert out["status_code"] == 403 and "pipeline" not in out


# ------------------------------------------------- Codex review 2 regressions ---

def test_a_meeting_moves_straight_to_won_keeping_the_meeting(h):
    """The screen offers Won and Closed on a meeting (no undo needed first)."""
    who = person(h)
    mark(h, who, "meeting", moment=NOW - timedelta(days=1), expected="none")
    mark(h, who, "won", expected="meeting")
    r = board(h)["results"]
    assert (r["meetings"], r["wins"]) == (1, 1)


def test_a_second_undo_of_the_same_mark_changes_nothing(h):
    """A double click (or another tab) undoes one mark, never two."""
    who = person(h)
    mark(h, who, "meeting", moment=NOW - timedelta(days=1))
    mark(h, who, "won")
    mark(h, who, None, expected="won")
    with pytest.raises(Exception) as exc:
        mark(h, who, None, expected="won")
    assert getattr(exc.value, "status_code", None) == 409
    out = board(h)
    assert out["pipeline"]["meeting"] == 1 and out["results"]["meetings"] == 1


def test_an_existing_paid_brand_is_labelled_as_paid(h, monkeypatch):
    """No billing record (it existed before billing) but not included: paid."""
    from services import outreach_allowance
    monkeypatch.setattr(outreach_allowance, "prices", lambda session, bid: {BRAND: (7900, False)})
    row = next(b for b in board(h, spend=True)["spend"]["brands"] if b["brand_id"] == BRAND)
    assert row["billing"].startswith("paid") and "79" in row["billing"]


@pytest.mark.parametrize("prices,label", [({BRAND: (0, True)}, "included in the plan")])
def test_an_included_brand_is_labelled_included(h, monkeypatch, prices, label):
    from services import outreach_allowance
    monkeypatch.setattr(outreach_allowance, "prices", lambda session, bid: prices)
    row = next(b for b in board(h, spend=True)["spend"]["brands"] if b["brand_id"] == BRAND)
    assert row["billing"] == label



def test_an_included_brand_with_an_old_billing_record_is_included(h, monkeypatch):
    """Codex review 3: inclusion wins, as in the billing service (brand_live)."""
    from services import outreach_allowance
    monkeypatch.setattr(outreach_allowance, "prices", lambda session, bid: {BRAND: (0, True)})
    billing_state(h, BRAND, {"state": "awaiting_payment", "price": 7900})
    out = board(h, spend=True)
    assert out["needs_you"]["failures"]["awaiting_payment"] == 0
    assert next(b for b in out["spend"]["brands"] if b["brand_id"] == BRAND)["billing"] == "included in the plan"
