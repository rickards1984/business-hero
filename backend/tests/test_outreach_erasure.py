"""OUT-13 core — a never-contacted contact is erased from every outreach
record at its deadline (docs/OUT-13-CORE-TICKET.md). RED: deletion of
personal data. Every adapter is faked; contacts are made by the real
research run, so their cards, tokens and evidence are the real ones."""
# ruff: noqa: F811 - pytest fixtures imported from test_outreach_setup are parameters by design
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlmodel import Session

from test_outreach_setup import A, _insert, db  # noqa: F401
from test_outreach_research import NOW, World, count, person, run, started

DAY_28 = NOW + timedelta(days=28)
IDENTIFIERS = ("sam@studio1.example", "Sam Taylor", "Studio 1 Ltd", "studio1.example")


def erasure():
    from services import outreach_erasure
    return outreach_erasure


@pytest.fixture(autouse=True)
def the_clock(monkeypatch):
    from services import aria_actions, outreach_send
    monkeypatch.setattr(outreach_send, "now", lambda: NOW)
    monkeypatch.setattr(aria_actions, "now", lambda: NOW)


def researched(db, n=1):
    biz, brand, lia, campaign = started(db)
    run(db, biz, lia, World([[person(i + 1) for i in range(n)]]))
    with Session(db) as s:
        ids = [str(r[0]) for r in s.execute(text("SELECT id FROM outreach_prospects WHERE business_id = :b "
                                                 "ORDER BY company"), {"b": A})]
    return biz, campaign, ids


def tables(db):
    with db.connect() as c:
        return [r[0] for r in c.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'"))]


def anywhere(db, needle):
    """Every column of every table, as text."""
    hits = []
    with db.connect() as c:
        for t in tables(db):
            for row in c.execute(text(f"SELECT * FROM {t}")).fetchall():
                if any(needle.lower() in str(v).lower() for v in row if v is not None):
                    hits.append(t)
    return hits


def erase(db, pid, moment=DAY_28):
    with Session(db) as s:
        return erasure().erase_never_contacted(s, A, pid, moment)


# ------------------------------------------------------------ predicates ---

@pytest.mark.parametrize("notice_days,expected_days", [(30, 28), (28, 28), (None, 28), (20, 20)])
def test_the_deadline_is_never_later_than_28_days(notice_days, expected_days):
    e = erasure()
    p = {"captured_at": NOW, "notice_due_at": NOW + timedelta(days=notice_days) if notice_days else None,
         "notice_provided_at": None}
    assert e.deadline(p) == NOW + timedelta(days=expected_days)


def test_a_first_email_stops_at_the_deadline_but_a_follow_up_does_not():
    e = erasure()
    first = {"captured_at": NOW, "notice_due_at": NOW + timedelta(days=30), "notice_provided_at": None}
    noticed = dict(first, notice_provided_at=NOW + timedelta(days=2))
    assert e.first_send_allowed(first, DAY_28 - timedelta(seconds=1))
    assert not e.first_send_allowed(first, DAY_28) and e.hidden(first, DAY_28)
    assert e.first_send_allowed(noticed, NOW + timedelta(days=60)) and not e.hidden(noticed, NOW + timedelta(days=60))


# --------------------------------------------------------------- erasure ---

def test_at_the_deadline_the_contact_is_gone_from_every_outreach_record(db):
    biz, campaign, (pid,) = researched(db)
    assert count(db, "SELECT count(*) FROM aria_actions WHERE business_id = :b") == 1
    assert count(db, "SELECT count(*) FROM outreach_unsubscribe_tokens WHERE business_id = :b") == 1
    for needle in IDENTIFIERS:
        assert anywhere(db, needle), f"the scan must see {needle!r} before erasure"
    assert erase(db, pid)["erased"] is True
    for t in ("outreach_prospects", "outreach_evidence", "outreach_enrolments", "aria_actions",
              "outreach_unsubscribe_tokens", "outreach_messages", "outreach_dispatch_jobs"):
        assert count(db, f"SELECT count(*) FROM {t} WHERE business_id = :b") == 0, t
    for needle in IDENTIFIERS:
        assert anywhere(db, needle) == [], (needle, anywhere(db, needle))


def test_nothing_is_erased_before_the_deadline(db):
    biz, campaign, (pid,) = researched(db)
    assert erase(db, pid, DAY_28 - timedelta(minutes=1)) == {"erased": False, "reason": "not_due"}
    assert count(db, "SELECT count(*) FROM outreach_prospects WHERE business_id = :b") == 1


def test_an_opt_out_survives_the_erasure(db):
    biz, campaign, (pid,) = researched(db)
    with Session(db) as s:
        _insert(s, "outreach_suppressions", id=str(uuid.uuid4()), business_id=A, key_type="email",
                key_digest="d" * 64, created_at=NOW.isoformat(), updated_at=NOW.isoformat())
        s.commit()
    erase(db, pid)
    assert count(db, "SELECT count(*) FROM outreach_suppressions WHERE business_id = :b") == 1


def _message(db, pid, state, *, action_id=None, retry_of=None, other_prospect=None):
    mid = str(uuid.uuid4())
    with Session(db) as s:
        _insert(s, "outreach_messages", id=mid, business_id=A, prospect_id=other_prospect or pid,
                kind="initial", origin="live", direction="outbound", to_emails="[]", cc_emails="[]",
                subject="s", body="b", payload_hash="h" + mid, payload_version=1, state=state,
                idempotency_key="k" + mid, authority_snapshot="{}", action_id=action_id, retry_of=retry_of,
                created_at=NOW.isoformat(), updated_at=NOW.isoformat())
        s.commit()
    return mid


@pytest.mark.parametrize("state,reason", [("accepted", "contacted"), ("imported", "contacted"),
                                          ("claimed", "may_have_sent"), ("unknown", "may_have_sent")])
def test_anyone_who_may_have_been_emailed_is_never_erased(db, state, reason):
    biz, campaign, (pid,) = researched(db)
    _message(db, pid, state)
    assert erase(db, pid) == {"erased": False, "reason": reason}
    assert count(db, "SELECT count(*) FROM outreach_prospects WHERE business_id = :b") == 1
    # Recorded either way, so the work list never re-selects it (code review 1,
    # finding 1); a contacted one is not shown to the owner as a problem.
    assert count(db, "SELECT reason FROM outreach_erasure_exceptions WHERE business_id = :b") == reason
    with Session(db) as s:
        shown = [x["reason"] for x in erasure().exceptions_for(s, A)]
    assert shown == ([] if reason == "contacted" else [reason])


def test_a_message_that_never_left_is_erased_and_its_metering_kept_unlinked(db):
    biz, campaign, (pid,) = researched(db)
    with Session(db) as s:
        card = s.execute(text("SELECT id FROM aria_actions WHERE business_id = :b"), {"b": A}).scalar()
    mid = _message(db, pid, "failed", action_id=card)
    with Session(db) as s:
        _insert(s, "outreach_dispatch_jobs", id=str(uuid.uuid4()), business_id=A, message_id=mid,
                logical_key="lk", status="failed", due_at=NOW.isoformat(), action_id=card,
                dispatch_started_at=NOW.isoformat(), created_at=NOW.isoformat(), updated_at=NOW.isoformat())
        _insert(s, "outreach_usage_events", id=str(uuid.uuid4()), business_id=A, operation_key="op",
                kind="outreach_emails_sent", quantity=1, state="released", period_start=NOW.isoformat(),
                period_end=(NOW + timedelta(days=30)).isoformat(), message_id=mid,
                created_at=NOW.isoformat(), updated_at=NOW.isoformat())
        s.commit()
    assert erase(db, pid)["erased"] is True
    assert count(db, "SELECT count(*) FROM outreach_messages WHERE business_id = :b") == 0
    assert count(db, "SELECT count(*) FROM outreach_dispatch_jobs WHERE business_id = :b") == 0
    assert count(db, "SELECT count(*) FROM outreach_usage_events WHERE business_id = :b AND message_id IS NULL") == 1


def test_a_reference_from_another_contact_s_sent_email_blocks_and_is_shown(db):
    biz, campaign, (first, second) = researched(db, 2)
    mine = _message(db, first, "failed")
    _message(db, first, "accepted", retry_of=mine, other_prospect=second)
    assert erase(db, first) == {"erased": False, "reason": "cross_reference"}
    with Session(db) as s:
        assert [x["reason"] for x in erasure().exceptions_for(s, A)] == ["cross_reference"]


def test_the_dashboard_s_marked_outcome_goes_too(db):
    import json
    biz, campaign, (pid,) = researched(db)
    with db.begin() as c:
        doc = json.loads(c.execute(text("SELECT settings FROM business_settings WHERE business_id = :b"),
                                   {"b": A}).scalar() or "{}")
        doc["outreach_outcomes"] = {pid: {"events": [{"outcome": "interested"}]}, "other": {"events": []}}
        c.execute(text("UPDATE business_settings SET settings = :s WHERE business_id = :b"),
                  {"s": json.dumps(doc), "b": A})
    erase(db, pid)
    doc = json.loads(count(db, "SELECT settings FROM business_settings WHERE business_id = :b"))
    assert list(doc["outreach_outcomes"]) == ["other"]


def test_a_failure_part_way_leaves_everything_as_it_was(db, monkeypatch):
    biz, campaign, (pid,) = researched(db)
    e = erasure()
    real = e._forget_outcome

    def boom(*a):
        real(*a)
        raise RuntimeError("database went away")
    monkeypatch.setattr(e, "_forget_outcome", boom)
    assert erase(db, pid) == {"erased": False, "reason": "error"}
    assert count(db, "SELECT count(*) FROM outreach_prospects WHERE business_id = :b") == 1
    assert count(db, "SELECT count(*) FROM aria_actions WHERE business_id = :b") == 1
    assert count(db, "SELECT reason FROM outreach_erasure_exceptions WHERE business_id = :b") == "error"


# ---------------------------------------------------------------- guard ---

def test_an_erased_person_is_not_collected_again_for_90_days(db):
    biz, campaign, (pid,) = researched(db)
    erase(db, pid)
    e = erasure()
    with Session(db) as s:
        assert e.recently_erased(s, A, "sam@studio1.example", None, DAY_28 + timedelta(days=89))
        assert e.recently_erased(s, A, None, "STUDIO1.example ", DAY_28 + timedelta(days=89))
        assert not e.recently_erased(s, A, "sam@studio1.example", "studio1.example", DAY_28 + timedelta(days=91))
    assert anywhere(db, "studio1.example") == [], "the guard keeps digests, never the domain"


# -------------------------------------------------------------- schedule ---

def test_the_hourly_pass_runs_on_a_saturday_for_a_paused_business(db):
    biz, campaign, (pid,) = researched(db)
    with db.begin() as c:
        c.execute(text("UPDATE outreach_settings SET pause_all = :t WHERE business_id = :b"), {"t": True, "b": A})
    saturday = DAY_28 + timedelta(days=(5 - DAY_28.weekday()) % 7)
    with Session(db) as s:
        out = erasure().run_due(s, saturday)
    assert out["erased"] == 1


def test_a_business_with_no_outreach_settings_row_is_still_erased(db):
    biz, campaign, (pid,) = researched(db)
    with db.begin() as c:
        c.execute(text("DELETE FROM outreach_settings WHERE business_id = :b"), {"b": A})
    with Session(db) as s:
        assert erasure().run_due(s, DAY_28)["erased"] == 1


def test_one_failing_contact_never_holds_the_others(db, monkeypatch):
    biz, campaign, ids = researched(db, 3)
    e = erasure()
    real = e.assess

    def flaky(session, bid, pid):
        if pid == ids[0]:
            raise RuntimeError("bad row")
        return real(session, bid, pid)
    monkeypatch.setattr(e, "assess", flaky)
    with Session(db) as s:
        out = e.run_due(s, DAY_28)
    assert out["erased"] == 2 and out["exceptions"] == {"error": 1}


def test_recorded_exceptions_never_starve_a_new_contact(db, monkeypatch):
    """U1: a long prefix of blocked contacts, already exceptions with their
    re-checks overdue, sits ahead of one new contact."""
    biz, campaign, ids = researched(db, 1)
    e = erasure()
    monkeypatch.setattr(e, "RECHECKS_PER_PASS", 2)
    with Session(db) as s:
        for i in range(40):
            blocked = str(uuid.uuid4())
            _insert(s, "outreach_prospects", id=blocked, business_id=A, company=f"Old {i}", email=None,
                    email_key=None, subscriber_type="corporate", eligibility="eligible", stage="ready",
                    captured_at=(NOW - timedelta(days=60 + i)).isoformat(),
                    retention_due_at=(NOW + timedelta(days=300)).isoformat(),
                    created_at=NOW.isoformat(), updated_at=NOW.isoformat())
            _insert(s, "outreach_erasure_exceptions", id=str(uuid.uuid4()), business_id=A, prospect_id=blocked,
                    reason="may_have_sent", first_seen_at=(NOW - timedelta(days=20)).isoformat(),
                    last_checked_at=(NOW - timedelta(days=5)).isoformat(),
                    created_at=NOW.isoformat(), updated_at=NOW.isoformat())
        s.commit()
    with Session(db) as s:
        out = e.run_due(s, DAY_28)
    assert out["erased"] == 1 and out["rechecked"] == 2


def test_an_unclassified_blocked_prefix_is_classified_and_the_new_contact_reached(db):
    biz, campaign, ids = researched(db, 1)
    blocked = []
    with Session(db) as s:
        for i in range(30):
            pid = str(uuid.uuid4())
            blocked.append(pid)
            _insert(s, "outreach_prospects", id=pid, business_id=A, company=f"Old {i}", email=None, email_key=None,
                    subscriber_type="corporate", eligibility="eligible", stage="ready",
                    captured_at=(NOW - timedelta(days=60 + i)).isoformat(),
                    retention_due_at=(NOW + timedelta(days=300)).isoformat(),
                    created_at=NOW.isoformat(), updated_at=NOW.isoformat())
        s.commit()
    for pid in blocked:
        _message(db, pid, "unknown")
    with Session(db) as s:
        out = erasure().run_due(s, DAY_28)
    assert out["erased"] == 1 and out["exceptions"] == {"may_have_sent": 30}


# ------------------------------------------------- hidden at the deadline ---

def test_at_the_deadline_aria_s_tools_and_the_cards_show_nothing_before_any_erasure(db, monkeypatch):
    """R3: withheld from that moment, while the contact is still stored."""
    import outreach_read
    from services import aria_actions, outreach_send
    biz, campaign, (pid,) = researched(db)
    with db.begin() as c:                       # the card is still open at the deadline
        c.execute(text("UPDATE aria_actions SET expires_at = :later WHERE business_id = :b"),
                  {"b": A, "later": DAY_28 + timedelta(days=5)})
    for module in (outreach_send, aria_actions, outreach_read):
        monkeypatch.setattr(module, "now", lambda: DAY_28)
    with Session(db) as s:
        cards = aria_actions.list_open(s, biz)
    assert cards and "withheld" in cards[0]["preview"] and "sam@" not in str(cards[0])
    for needle in IDENTIFIERS:
        assert needle.lower() not in str(cards).lower()
    assert count(db, "SELECT count(*) FROM outreach_prospects WHERE business_id = :b") == 1   # not yet erased
    read = {r.tool: r for r in outreach_read.READS}
    monkeypatch.setattr(outreach_read, "_load_business", lambda session, business_id: biz)
    with Session(db) as s:
        item = outreach_read._read(s, read["get_outreach_prospect"], {"prospect_id": pid}, uuid.UUID(A))["item"]
        evidence = outreach_read._read(s, read["get_outreach_evidence"], {"prospect_id": pid, "limit": 20,
                                                                         "offset": 0}, uuid.UUID(A))["items"]
    assert item["details_withheld"] and not item["company"] and not item["name"] and not item["domain"]
    assert evidence and all(e["details_withheld"] and not e["source_url"] for e in evidence)


def test_someone_who_replied_is_never_hidden_even_without_a_notice_date(db, monkeypatch):
    """Imported history may lack notice_provided_at; a reply is still contact."""
    from services import aria_actions, outreach_send
    biz, campaign, (pid,) = researched(db)
    with Session(db) as s:
        _insert(s, "outreach_replies", id=str(uuid.uuid4()), business_id=A, prospect_id=pid,
                received_at=NOW.isoformat(), created_at=NOW.isoformat(), updated_at=NOW.isoformat())
        s.commit()
    with db.begin() as c:
        c.execute(text("UPDATE aria_actions SET expires_at = :later WHERE business_id = :b"),
                  {"b": A, "later": DAY_28 + timedelta(days=5)})
    for module in (outreach_send, aria_actions):
        monkeypatch.setattr(module, "now", lambda: DAY_28)
    with Session(db) as s:
        cards = aria_actions.list_open(s, biz)
    assert cards and "withheld" not in cards[0]["preview"]
    assert erase(db, pid) == {"erased": False, "reason": "contacted"}



def test_a_reference_from_another_contact_s_unsent_message_is_repaired_and_erased(db):
    biz, campaign, (first, second) = researched(db, 2)
    mine = _message(db, first, "failed")
    theirs = _message(db, first, "failed", retry_of=mine, other_prospect=second)
    assert erase(db, first)["erased"] is True
    assert count(db, "SELECT retry_of FROM outreach_messages WHERE id = :m", m=theirs) is None


# ------------------------------------------------- Codex code review 1 ---

class FakeClock:
    """time.monotonic advancing one second per look, so budgets run out."""

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        self.t += 1.0
        return self.t


def _old_prospect(db, *, days, notice_days=None, company="Old"):
    pid = str(uuid.uuid4())
    with Session(db) as s:
        _insert(s, "outreach_prospects", id=pid, business_id=A, company=company, email=None, email_key=None,
                subscriber_type="corporate", eligibility="eligible", stage="ready",
                captured_at=(DAY_28 - timedelta(days=days)).isoformat(),
                notice_due_at=(DAY_28 - timedelta(days=days) + timedelta(days=notice_days)).isoformat()
                if notice_days else None,
                retention_due_at=(DAY_28 + timedelta(days=300)).isoformat(),
                created_at=NOW.isoformat(), updated_at=NOW.isoformat())
        s.commit()
    return pid


def test_contacted_imports_ahead_never_starve_a_never_emailed_contact(db, monkeypatch):
    """Finding 1: imported history (accepted, no notice date) ahead of a
    never-emailed contact, more than one budget-limited pass can classify."""
    e = erasure()
    biz, campaign, (pid,) = researched(db)
    for i in range(25):
        _message(db, _old_prospect(db, days=60 + i), "imported")
    monkeypatch.setattr(e._time, "monotonic", FakeClock())
    monkeypatch.setattr(e, "PAGE", 4)
    for _ in range(12):
        with Session(db) as s:
            e.run_due(s, DAY_28 + timedelta(hours=1), pass_seconds=40, housekeeping_seconds=3)
        if not count(db, "SELECT count(*) FROM outreach_prospects WHERE id = :p", p=pid):
            break
    assert count(db, "SELECT count(*) FROM outreach_prospects WHERE id = :p", p=pid) == 0
    assert count(db, "SELECT count(*) FROM outreach_erasure_exceptions WHERE reason = 'contacted'") == 25


def test_slow_housekeeping_never_takes_the_candidates_budget(db, monkeypatch):
    """Finding 2: reconciliation stuck for minutes; the overdue contact is
    still erased in the same pass."""
    e = erasure()
    biz, campaign, (pid,) = researched(db)
    clock = FakeClock()
    monkeypatch.setattr(e._time, "monotonic", clock)

    def stuck(session, moment, limit=50, stop=None):
        clock.t += 600
        return 0
    monkeypatch.setattr(e, "reconcile_abandoned_claims", stuck)
    with Session(db) as s:
        out = e.run_due(s, DAY_28)
    assert out["erased"] == 1


def test_a_send_that_may_have_happened_is_kept_but_still_withheld(db, monkeypatch):
    """Finding 3: protected from erasure is not permission to show."""
    from services import aria_actions, outreach_send
    biz, campaign, (pid,) = researched(db)
    _message(db, pid, "claimed")
    with db.begin() as c:
        c.execute(text("UPDATE aria_actions SET expires_at = :later WHERE business_id = :b"),
                  {"b": A, "later": DAY_28 + timedelta(days=5)})
    for module in (outreach_send, aria_actions):
        monkeypatch.setattr(module, "now", lambda: DAY_28)
    with Session(db) as s:
        cards = aria_actions.list_open(s, biz)
    assert cards and "withheld" in cards[0]["preview"]
    assert erase(db, pid) == {"erased": False, "reason": "may_have_sent"}


def test_the_backlog_age_uses_an_earlier_notice_deadline(db):
    """Finding 6: a day-20 notice deadline is overdue at day 24 by 96 hours."""
    e = erasure()
    started(db)
    _old_prospect(db, days=24, notice_days=20)
    with Session(db) as s:
        out = e.run_due(s, DAY_28, pass_seconds=0)
    assert out["oldest_overdue_hours"] == 96.0


def test_held_erasures_are_escalated_on_the_home_after_their_threshold(db):
    """Finding 7: an erasure failing for three days, an uncertain send held
    for a week, are put in front of the owner."""
    e = erasure()
    started(db)
    with Session(db) as s:
        for reason, days in (("error", 4), ("error", 1), ("may_have_sent", 8), ("contacted", 30)):
            _insert(s, "outreach_erasure_exceptions", id=str(uuid.uuid4()), business_id=A,
                    prospect_id=str(uuid.uuid4()), reason=reason,
                    first_seen_at=(DAY_28 - timedelta(days=days)).isoformat(),
                    last_checked_at=DAY_28.isoformat(), created_at=NOW.isoformat(), updated_at=NOW.isoformat())
        s.commit()
    with db.connect() as c:
        assert e.escalations(c, A, DAY_28) == {"error": 1, "may_have_sent": 1}
