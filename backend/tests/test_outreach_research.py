"""OUT-10 — Aria-led prospect research (docs/OUT-10-TICKET.md).

Tests first (RED: personal data collection, the lawful basis for contact,
spend). Strict xfail may fail only because `services.outreach_research` does
not exist yet. Every adapter is faked — web search, page fetch, MX,
Companies House — so no network and no model call ever happens here.
"""
# ruff: noqa: F811 - pytest fixtures imported from test_outreach_setup are parameters by design

import importlib
import importlib.util
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlmodel import Session

from test_outreach_setup import A, B, OWNER, STAFF, db, grant, ready, setup_module_or_missing  # noqa: F401


class MissingResearch(AssertionError):
    """Only the intentional Stage 1 absence may be xfailed."""


# Stage 1's strict-xfail marker was removed once the implementation landed.

NOW = datetime(2026, 10, 27, 7, 30, tzinfo=timezone.utc)   # Tuesday 07:30 UK


def research():
    if importlib.util.find_spec("services.outreach_research") is None:
        raise MissingResearch("backend/services/outreach_research.py does not exist yet")
    return importlib.import_module("services.outreach_research")


# ------------------------------------------------------------------ fakes ---

def person(i, *, company=None, name="Sam Taylor", role="Managing Director", email=None, kind=None,
           segment="gym", region="Essex", number=None):
    company = company or f"Studio {i} Ltd"
    domain = f"studio{i}.example"
    return {"company": company, "contact_name": name, "role": role,
            "contact_email": email or f"sam@{domain}", "contact_type": kind or "decision_maker",
            "source_url": f"https://{domain}/team", "region": region, "segment": segment,
            "fit_reason": "Independent studio that hosts trainees.", "company_number": number}


def gatekeeper(i, **kw):
    return person(i, name="", role="", email=f"info@studio{i}.example", kind="gatekeeper", **kw)


class World:
    """Fake web, DNS and Companies House. Everything is real unless told otherwise."""

    def __init__(self, batches, *, cost=10):
        self.batches = list(batches)   # one list of candidates per search attempt
        self.briefs, self.cost = [], cost
        self.missing_pages, self.no_mx, self.not_companies, self.dissolved = set(), set(), set(), set()
        self.officers = {}

    def search(self, brief):
        self.briefs.append(brief)
        found = self.batches.pop(0) if self.batches else []
        return {"candidates": found, "cost_pence": self.cost}

    def fetch(self, url):
        if url in self.missing_pages:
            return "<html>Contact us via the form.</html>"
        domain = url.split("/")[2]
        return f"<html>Team: sam@{domain} info@{domain} owner@{domain}</html>"

    def mx(self, domain):
        return domain not in self.no_mx

    def companies(self, query):
        name = str(query)
        if name in self.not_companies:
            return None
        return {"number": "01234567", "name": name, "status": "dissolved" if name in self.dissolved else "active",
                "type": "ltd", "officers": self.officers.get(name, ["Sam Taylor"])}

    def kwargs(self):
        return dict(search=self.search, fetch=self.fetch, mx=self.mx, companies=self.companies, moment=NOW)


def started(db):
    """A business with setup complete and research switched on."""
    m = setup_module_or_missing()
    biz = grant(db)
    brand, lia, campaign = ready(m, db, biz)
    with Session(db) as s:
        from services import outreach_manage
        c = s.execute(text("SELECT version, sequence_version FROM outreach_campaigns")).one()
        outreach_manage.approve_templates(s, biz, OWNER, campaign["id"], {"version": int(c[0]), "sequence_version": int(c[1])})
        m.finish(s, biz, OWNER)
        research().configure(s, biz, OWNER, {"enabled": True, "monthly_cap_pence": 2000})
    return biz, brand, lia, campaign


def count(db, sql, **params):
    with db.connect() as c:
        return c.execute(text(sql), {"b": A, **params}).scalar()


def run(db, biz, lia, world):
    with Session(db) as s:
        return research().run(s, biz, lia["id"], **world.kwargs())


# ------------------------------------------------------------ verification ---

def test_a_verified_director_is_stored_as_a_corporate_decision_maker_with_evidence(db):
    research()
    biz, brand, lia, campaign = started(db)
    world = World([[person(1)]])
    out = run(db, biz, lia, world)
    assert len(out["accepted"]) == 1 and out["decision_makers"] == 1 and out["gatekeepers"] == 0
    with db.connect() as c:
        p = c.execute(text("SELECT * FROM outreach_prospects WHERE business_id = :b"), {"b": A}).mappings().one()
        facts = {row[0]: row[1] for row in c.execute(text(
            "SELECT fact_type, fact_value FROM outreach_evidence WHERE prospect_id = :p"), {"p": p["id"]})}
        src = c.execute(text("SELECT source_url, verification_status, verification_subject_email_key FROM "
                             "outreach_evidence WHERE prospect_id = :p AND fact_type = 'email_verification'"),
                        {"p": p["id"]}).one()
    assert (p["subscriber_type"], p["eligibility"], p["lawful_basis"]) == ("corporate", "eligible", "legitimate_interests")
    assert p["lia_id"] == lia["id"] and p["name"] == "Sam Taylor" and p["role"] == "Managing Director"
    from services.outreach_send import suppression_digest
    assert p["email_key"] == suppression_digest(A, "email", "sam@studio1.example")
    assert src[0] == "https://studio1.example/team" and src[1] == "valid" and src[2] == p["email_key"]
    assert facts["contact_type"] == "decision_maker" and facts["role_verified"] == "true"
    assert facts["segment"] == "gym" and facts["region"] == "Essex"
    due = datetime.fromisoformat(str(p["notice_due_at"]).replace(" ", "T"))
    due = due if due.tzinfo else due.replace(tzinfo=timezone.utc)
    assert timedelta(days=27) <= due - NOW <= timedelta(days=31), "Article 14: notice within a month"


@pytest.mark.parametrize("change,reason_word", [
    ("missing_pages", "not on"), ("no_mx", "mail server"), ("dissolved", "active"),
])
def test_candidates_that_fail_verification_are_rejected_and_never_stored(db, change, reason_word):
    biz, brand, lia, campaign = started(db)
    world = World([[person(1)]])
    target = {"missing_pages": "https://studio1.example/team", "no_mx": "studio1.example",
              "dissolved": "Studio 1 Ltd"}[change]
    getattr(world, change).add(target)
    out = run(db, biz, lia, world)
    assert out["accepted"] == [] and reason_word in out["rejected"][0]["reason"]
    assert count(db, "SELECT count(*) FROM outreach_prospects WHERE business_id = :b") == 0


def test_free_webmail_is_rejected(db):
    biz, brand, lia, campaign = started(db)
    out = run(db, biz, lia, World([[person(1, email="sam.taylor@gmail.com")]]))
    assert out["accepted"] == [] and "business" in out["rejected"][0]["reason"]


def test_a_sole_trader_is_kept_for_review_and_never_eligible(db):
    """Decision A: PECR treats sole traders/partnerships as individuals."""
    biz, brand, lia, campaign = started(db)
    world = World([[person(1, company="Sam's Fitness")]])
    world.not_companies.add("Sam's Fitness")
    out = run(db, biz, lia, world)
    assert out["accepted"] == [] and "consent" in out["rejected"][0]["reason"]
    with db.connect() as c:
        row = c.execute(text("SELECT eligibility, subscriber_type FROM outreach_prospects WHERE business_id = :b"),
                        {"b": A}).one()
    assert row[0] == "review" and row[1] != "corporate"


def test_a_name_that_matches_no_officer_is_still_a_decision_maker_but_unverified(db):
    biz, brand, lia, campaign = started(db)
    world = World([[person(1, name="Alex Morgan", role="Operations Manager")]])
    world.officers["Studio 1 Ltd"] = ["Someone Else"]
    out = run(db, biz, lia, world)
    assert out["decision_makers"] == 1
    assert count(db, "SELECT fact_value FROM outreach_evidence WHERE business_id = :b AND fact_type = 'role_verified'") == "false"


def test_a_role_address_is_a_gatekeeper_even_if_called_a_decision_maker(db):
    biz, brand, lia, campaign = started(db)
    out = run(db, biz, lia, World([[person(1, email="info@studio1.example", kind="decision_maker")]]))
    assert out["gatekeepers"] == 1 and out["decision_makers"] == 0


# ------------------------------------------------------------- duplicates ---

@pytest.mark.parametrize("kind", ["same_email", "same_domain", "suppressed_email", "suppressed_domain"])
def test_duplicates_and_opt_outs_are_never_stored_again(db, kind):
    from services.outreach_send import suppression_digest
    biz, brand, lia, campaign = started(db)
    run(db, biz, lia, World([[person(1)]]))
    if kind.startswith("suppressed"):
        with db.begin() as c:
            c.execute(text("DELETE FROM outreach_evidence WHERE business_id = :b"), {"b": A})
            c.execute(text("DELETE FROM outreach_prospects WHERE business_id = :b"), {"b": A})
            key_type, value = ("email", "sam@studio1.example") if kind == "suppressed_email" else ("domain", "studio1.example")
            c.execute(text("INSERT INTO outreach_suppressions (id, business_id, key_type, key_digest, digest_version, "
                           "reason, suppressed_at) VALUES (:id, :b, :t, :d, 1, 'unsubscribe', :at)"),
                      {"id": str(uuid.uuid4()), "b": A, "t": key_type, "d": suppression_digest(A, key_type, value),
                       "at": NOW.isoformat()})
    again = person(1) if kind != "same_domain" else person(1, name="Jo Bloggs", email="jo@studio1.example")
    out = run(db, biz, lia, World([[again]] * 3))
    assert out["accepted"] == []
    assert any(w in out["rejected"][0]["reason"] for w in ("already", "opted out"))


# ------------------------------------------------------------------ quota ---

def test_up_to_twenty_decision_makers_a_day(db):
    biz, brand, lia, campaign = started(db)
    out = run(db, biz, lia, World([[person(i) for i in range(25)]]))
    assert len(out["accepted"]) == 20 and out["decision_makers"] == 20


def test_gatekeepers_never_more_than_ten(db):
    biz, brand, lia, campaign = started(db)
    out = run(db, biz, lia, World([[gatekeeper(i) for i in range(15)]] * 3))
    assert out["gatekeepers"] == 10 and len(out["accepted"]) == 10


def test_decision_makers_first_then_gatekeepers_fill_the_rest(db):
    """Mike: 20 a day, at least 10 decision-makers; gatekeepers only fill."""
    biz, brand, lia, campaign = started(db)
    batch = [person(i) for i in range(12)] + [gatekeeper(100 + i) for i in range(15)]
    out = run(db, biz, lia, World([batch]))
    assert out["decision_makers"] == 12 and out["gatekeepers"] == 8 and len(out["accepted"]) == 20


def test_a_short_run_retries_wider_and_counts_only_new(db):
    biz, brand, lia, campaign = started(db)
    world = World([[person(1)], [person(1), person(2)], [person(3)]])
    out = run(db, biz, lia, world)
    assert out["attempts"] == 3 and len(out["accepted"]) == 3
    assert world.briefs[0] != world.briefs[1], "a wider area on retry"


# --------------------------------------------------------------- the plan ---

def test_the_area_rotates_only_after_a_successful_run(db):
    biz, brand, lia, campaign = started(db)
    r = research()
    with Session(db) as s:
        first = r.plan(s, biz, lia["id"], moment=NOW)["area"]

    def broken(brief):
        raise RuntimeError("model outage")
    world = World([])
    world.search = broken
    run(db, biz, lia, world)
    with Session(db) as s:
        assert r.plan(s, biz, lia["id"], moment=NOW)["area"] == first, "an outage never skips an area"
    run(db, biz, lia, World([[person(i) for i in range(20)]]))
    with Session(db) as s:
        assert r.plan(s, biz, lia["id"], moment=NOW + timedelta(days=1))["area"] != first


def test_the_brief_carries_exclusions_and_lessons_from_the_business_own_results(db):
    biz, brand, lia, campaign = started(db)
    run(db, biz, lia, World([[person(1, segment="property")]]))
    r = research()
    with db.begin() as c:   # the property contact replied positively
        pid = c.execute(text("SELECT id FROM outreach_prospects WHERE business_id = :b"), {"b": A}).scalar()
        c.execute(text("INSERT INTO outreach_messages (id, business_id, campaign_id, prospect_id, direction, state, "
                       "origin, kind) VALUES (:id, :b, :c, :p, 'outbound', 'accepted', 'live', 'initial')"),
                  {"id": str(uuid.uuid4()), "b": A, "c": campaign["id"], "p": pid})
        c.execute(text("INSERT INTO outreach_replies (id, business_id, prospect_id, category) VALUES "
                       "(:id, :b, :p, 'interested')"), {"id": str(uuid.uuid4()), "b": A, "p": pid})
    with Session(db) as s:
        perf = r.performance(s, biz)
        plan = r.plan(s, biz, lia["id"], moment=NOW)
    row = next(x for x in perf if x["segment"] == "property")
    assert (row["sent"], row["replied"], row["positive"]) == (1, 1, 1)
    assert "studio1.example" in plan["brief"], "already-held domains are excluded"
    assert any("property" in lesson for lesson in plan["lessons"])


def test_lesson_notes_are_owner_only_and_reach_the_brief(db):
    biz, brand, lia, campaign = started(db)
    r = research()
    with Session(db) as s:
        with pytest.raises(Exception):
            r.save_lessons(s, biz, STAFF, ["Avoid chains"])
        r.save_lessons(s, biz, OWNER, ["Avoid national chains; independents reply."])
        assert "Avoid national chains" in r.plan(s, biz, lia["id"], moment=NOW)["brief"]


# ------------------------------------------------------- spend and running ---

def test_the_monthly_cap_stops_research_before_it_spends(db):
    biz, brand, lia, campaign = started(db)
    with db.begin() as c:
        c.execute(text("INSERT INTO usage_meters (business_id, meter, period, value, updated_at) VALUES "
                       "(:b, 'outreach_research_pence', '2026-10', 1995, :at)"), {"b": A, "at": NOW.isoformat()})
    world = World([[person(1)]], cost=10)
    out = run(db, biz, lia, world)
    assert out["stopped"] and "budget" in out["stopped"] and world.briefs == []


def test_spend_is_recorded_per_month(db):
    biz, brand, lia, campaign = started(db)
    run(db, biz, lia, World([[person(i) for i in range(20)]], cost=37))
    assert int(float(count(db, "SELECT value FROM usage_meters WHERE business_id = :b "
                               "AND meter = 'outreach_research_pence' AND period = '2026-10'"))) == 37


def test_without_a_companies_house_key_nothing_is_marked_eligible(db, monkeypatch):
    biz, brand, lia, campaign = started(db)
    monkeypatch.delenv("COMPANIES_HOUSE_API_KEY", raising=False)
    world = World([[person(1)]])
    with Session(db) as s:
        out = research().run(s, biz, lia["id"], search=world.search, fetch=world.fetch, mx=world.mx, moment=NOW)
    assert out["stopped"] and "Companies House" in out["stopped"]
    assert count(db, "SELECT count(*) FROM outreach_prospects WHERE business_id = :b AND eligibility = 'eligible'") == 0


def test_run_due_runs_started_businesses_once_a_weekday_from_six(db):
    biz, brand, lia, campaign = started(db)
    r = research()
    calls = []

    def fake_run(session, business, compliance_id, **kw):
        calls.append(str(business.id))
        return {"accepted": [], "decision_makers": 0, "gatekeepers": 0, "rejected": [], "attempts": 1,
                "spend_pence": 0, "stopped": None}
    with Session(db) as s:
        r.run_due(s, moment=datetime(2026, 10, 27, 5, 59, tzinfo=timezone.utc), runner=fake_run)
        r.run_due(s, moment=datetime(2026, 10, 27, 6, 10, tzinfo=timezone.utc), runner=fake_run)
        r.run_due(s, moment=datetime(2026, 10, 27, 9, 10, tzinfo=timezone.utc), runner=fake_run)
        r.run_due(s, moment=datetime(2026, 10, 31, 9, 10, tzinfo=timezone.utc), runner=fake_run)  # Saturday
    assert calls == [A], "once, on a weekday, from 06:00 UK"


def test_research_switched_off_or_outreach_paused_never_runs(db):
    biz, brand, lia, campaign = started(db)
    r = research()
    with Session(db) as s:
        r.configure(s, biz, OWNER, {"enabled": False})
        assert r.run_due(s, moment=NOW, runner=lambda *a, **k: pytest.fail("ran while switched off")) == []


def test_new_contacts_are_enrolled_into_the_audience_campaign_within_its_limit(db):
    """Decision E: verified contacts join the active campaign for their
    audience (pilot limit 5 for now); research never sends or raises cards."""
    biz, brand, lia, campaign = started(db)
    run(db, biz, lia, World([[person(i) for i in range(8)]]))
    assert count(db, "SELECT count(*) FROM outreach_enrolments WHERE business_id = :b AND campaign_id = :c",
                 c=campaign["id"]) == 5
    assert count(db, "SELECT count(*) FROM aria_actions WHERE business_id = :b") == 0


def test_research_never_touches_another_business(db):
    biz, brand, lia, campaign = started(db)
    run(db, biz, lia, World([[person(i) for i in range(5)]]))
    for table in ("outreach_prospects", "outreach_evidence", "outreach_enrolments"):
        assert count(db, f"SELECT count(*) FROM {table} WHERE business_id = :o", o=B) == 0


@pytest.mark.parametrize("url", ["http://127.0.0.1/admin", "http://169.254.169.254/latest/meta-data",
                                 "http://10.0.0.5/", "http://[::1]/", "file:///etc/passwd", "ftp://example.invalid/"])
def test_the_page_fetcher_never_reaches_private_or_non_web_addresses(url):
    """The model names the URLs; none may reach Business Hero's own network."""
    assert research().fetch_page(url) is None


def test_the_hourly_pass_runs_research():
    research()
    import inspect
    from services import automations
    assert "outreach_research" in inspect.getsource(automations.run_all_due)
