"""OUT-21: research failed silently in production (Mike, 5 Nov 2026).

UKFI's first run searched (36p) and then stopped with no contacts, no summary
and nothing in the logs: the run raised, and run_due swallowed it. The likely
cause was a missing OUTREACH_SUPPRESSION_SECRET, which the opt-out check needs
for every candidate. These tests pin the repair:
- research refuses BEFORE spending when a setting it needs is missing;
- the launch checklist shows that setting;
- any failure is logged and recorded as Aria's summary, never silent;
- every run's outcome reaches the logs;
- a malformed candidate from the model is rejected, never a crash.
"""
# ruff: noqa: F811 - pytest fixtures imported from test_outreach_setup are parameters by design
import logging

import pytest
from sqlmodel import Session

from test_outreach_setup import A, OWNER, db  # noqa: F401
from test_outreach_research import NOW, World, count, person, research, run, started


@pytest.fixture(autouse=True)
def no_pilot_limit(monkeypatch):
    monkeypatch.setenv("OUTREACH_PILOT_ENROLMENTS", "0")


def _summary(db, biz):
    with Session(db) as s:
        return research().status(s, biz)["summary"] or ""


def test_without_the_suppression_key_research_refuses_before_spending(db, monkeypatch):
    biz, brand, lia, campaign = started(db)
    monkeypatch.delenv("OUTREACH_SUPPRESSION_SECRET")
    world = World([[person(1)]])
    out = run(db, biz, lia, world)
    assert world.briefs == [], "no search may be paid for when its results can't be checked"
    assert out["spend_pence"] == 0 and out["accepted"] == []
    assert "OUTREACH_SUPPRESSION_SECRET" not in out["stopped"]   # owner-facing words, not a variable name
    assert "opt-out" in out["stopped"].lower()
    assert count(db, "SELECT count(*) FROM outreach_prospects WHERE business_id = :b") == 0


def test_a_short_suppression_key_counts_as_missing(db, monkeypatch):
    biz, brand, lia, campaign = started(db)
    monkeypatch.setenv("OUTREACH_SUPPRESSION_SECRET", "too-short")
    world = World([[person(1)]])
    out = run(db, biz, lia, world)
    assert world.briefs == [] and out["stopped"]


def test_the_launch_checklist_shows_a_missing_suppression_key(db, monkeypatch):
    from test_outreach_launch import finished, items
    from services import ai_costs, ai_router
    monkeypatch.setattr(ai_router, "reserve_pence", lambda: 10)
    monkeypatch.setattr(ai_costs, "allowed", lambda session, **kw: True)
    monkeypatch.setenv("COMPANIES_HOUSE_API_KEY", "test-key")
    biz, brand = finished(db)
    from services import outreach_launch
    with Session(db) as s:
        b, it = items(outreach_launch.checklist(s, biz), brand["id"])
    assert it["opt_out_checks"]["done"] is True
    monkeypatch.delenv("OUTREACH_SUPPRESSION_SECRET")
    with Session(db) as s:
        b, it = items(outreach_launch.checklist(s, biz), brand["id"])
    assert it["opt_out_checks"]["done"] is False and it["opt_out_checks"]["fix"]
    assert b["can_launch"] is False


def test_a_crashing_run_is_logged_and_recorded_as_arias_summary(db, caplog):
    biz, brand, lia, campaign = started(db)

    def crash(session, business, compliance_id, **kw):
        # A database error's text can carry a contact's details (Codex OUT-21 review 1).
        raise RuntimeError("INSERT ... ('Sam Taylor', 'sam@studio1.example')")
    with caplog.at_level(logging.INFO, logger="services.outreach_research"), Session(db) as s:
        assert research().run_due(s, moment=NOW, runner=crash) == [A]
    failures = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert failures, "the failure reaches the logs"
    line = failures[0].getMessage()
    assert A in line and "RuntimeError" in line and "test_outreach_research_failures.py:" in line, line
    logged = caplog.text
    assert "sam@studio1.example" not in logged and "Sam Taylor" not in logged, "no personal data in logs"
    assert not any(r.exc_info for r in caplog.records), "no traceback text: it carries the message"
    said = _summary(db, biz)
    assert said and "error" in said.lower(), said


def test_every_run_reports_its_outcome_to_the_logs(db, caplog):
    biz, brand, lia, campaign = started(db)

    def nothing(session, business, compliance_id, **kw):
        return {"accepted": [], "decision_makers": 0, "gatekeepers": 0, "rejected": [{"company": "X", "reason": "r"}],
                "attempts": 1, "spend_pence": 12, "stopped": "Some reason"}
    with caplog.at_level(logging.INFO, logger="services.outreach_research"), Session(db) as s:
        research().run_due(s, moment=NOW, runner=nothing)
    lines = [r.getMessage() for r in caplog.records if r.name == "services.outreach_research"]
    assert any(A in line and "0 new" in line and "12p" in line and "Some reason" in line for line in lines), lines


@pytest.mark.parametrize("bad,kept", [
    ({"contact_email": ["sam@studio1.example"]}, 1),
    ({"company": {"name": "Studio 1 Ltd"}}, 1),
    ({"source_url": "http://[not-a-host/team"}, 1),
    ({"source_url": None}, 1),
    # Still a usable contact: a number given as a number, a contact with no name.
    ({"company_number": 12345678}, 2),
    ({"contact_name": None, "role": None}, 2),
])
def test_a_malformed_candidate_is_rejected_never_a_crash(db, bad, kept):
    biz, brand, lia, campaign = started(db)
    world = World([[person(1), person(2)]])
    real = world.search
    # The fake web reads each source URL; the model's malformed field is
    # applied after it, exactly as a real reply would carry it.
    world.search = lambda brief: {**(found := real(brief)),
                                  "candidates": [{**found["candidates"][0], **bad}, *found["candidates"][1:]]}
    out = run(db, biz, lia, world)
    assert len(out["accepted"]) == kept, out   # the good one is kept; an unusable one never is
    assert _summary(db, biz)


def test_a_refused_run_is_shown_to_the_owner(db, monkeypatch):
    """Codex OUT-21 review 1: a refusal before any search saved no summary."""
    biz, brand, lia, campaign = started(db)
    monkeypatch.delenv("OUTREACH_SUPPRESSION_SECRET")
    monkeypatch.setenv("COMPANIES_HOUSE_API_KEY", "test-key")   # so the opt-out refusal is the one shown
    from test_outreach_research import run_clock
    with run_clock(), Session(db) as s:
        assert research().run_due(s, moment=NOW) == [A]
    assert research().OPT_OUT_UNAVAILABLE in _summary(db, biz)


@pytest.mark.parametrize("url", ["https://studio1.example:bad/team", "http://[broken/team", "https://studio1.example:99999/"])
def test_the_real_fetcher_refuses_a_malformed_address(url):
    """Codex OUT-21 review 1: a bad port raised outside fetch_page's handler."""
    looked_up = []
    assert research().fetch_page(url, resolve=lambda host: looked_up.append(host) or [("93.184.216.34", 0)]) is None
    assert looked_up == [], "refused before any lookup or connection"


def test_a_bad_port_in_a_candidate_is_rejected_and_the_rest_are_kept(db):
    biz, brand, lia, campaign = started(db)
    world = World([[person(1), person(2)]])
    real = world.search
    world.search = lambda brief: {**(found := real(brief)), "candidates": [
        {**found["candidates"][0], "source_url": "https://studio1.example:bad/team"}, *found["candidates"][1:]]}
    out = run(db, biz, lia, world)
    assert len(out["accepted"]) == 1, out
