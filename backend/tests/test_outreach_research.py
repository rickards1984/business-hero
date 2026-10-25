"""OUT-10 — Aria-led prospect research (docs/OUT-10-TICKET.md).

Tests first (RED: personal data collection, the lawful basis for contact,
spend). Strict xfail may fail only because `services.outreach_research` does
not exist yet. Every adapter is faked — web search, page fetch, MX,
Companies House — so no network and no model call ever happens here.
"""
# ruff: noqa: F811 - pytest fixtures imported from test_outreach_setup are parameters by design

import importlib
import json
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
    """Fake web, DNS and Companies House. Everything is real unless told
    otherwise. Like a real UK company site, each page shows the company's
    registered name and number (Companies Act 2006 trading disclosures)."""

    def __init__(self, batches, *, cost=10):
        self.batches = list(batches)   # one list of candidates per search attempt
        self.briefs, self.cost = [], cost
        self.missing_pages, self.no_mx, self.not_companies, self.dissolved = set(), set(), set(), set()
        self.no_disclosure, self.registry, self.pages, self.types = set(), {}, {}, {}
        self.officers, self.site_company = {}, {}
        self.search_error = None

    @staticmethod
    def number_for(name):
        import zlib
        return str(zlib.crc32(name.encode()) % 10 ** 8).zfill(8)

    def search(self, brief):
        self.briefs.append(brief)
        if self.search_error:
            raise self.search_error
        found = self.batches.pop(0) if self.batches else []
        for c in found:
            self.site_company.setdefault(c["source_url"].split("/")[2], c["company"])
        return {"candidates": found, "cost_pence": self.cost}

    def fetch(self, url):
        if url in self.pages:
            return self.pages[url]
        if url in self.missing_pages:
            return "<html>Contact us via the form.</html>"
        domain = url.split("/")[2]
        company = self.site_company.get(domain, "")
        footer = "" if domain in self.no_disclosure else \
            f"<footer>{company} is registered in England and Wales, company number {self.number_for(company)}.</footer>"
        return f"<html>Team: sam@{domain} info@{domain} owner@{domain} jo@{domain}{footer}</html>"

    def mx(self, domain):
        return domain not in self.no_mx

    def companies(self, query):
        query = str(query)
        if query in self.registry:
            return self.registry[query]
        if query in self.not_companies:
            return None
        return {"number": self.number_for(query), "name": query,
                "status": "dissolved" if query in self.dissolved else "active",
                "type": self.types.get(query, "ltd"), "officers": self.officers.get(query, ["TAYLOR, Sam"])}

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
        research().configure(s, biz, OWNER, {"brand_id": brand["id"], "enabled": True, "monthly_cap_pence": 2000})
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
    world.officers["Studio 1 Ltd"] = ["ELSE, Someone"]
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
            r.save_lessons(s, biz, STAFF, ["Avoid chains"], brand_id=brand["id"])
        r.save_lessons(s, biz, OWNER, ["Avoid national chains; independents reply."], brand_id=brand["id"])
        assert "Avoid national chains" in r.plan(s, biz, lia["id"], moment=NOW)["brief"]


# ------------------------------------------------------- spend and running ---

def test_the_monthly_cap_stops_research_before_it_spends(db):
    biz, brand, lia, campaign = started(db)
    with db.begin() as c:
        c.execute(text("INSERT INTO usage_meters (business_id, meter, period, value, updated_at) VALUES "
                       "(:b, :m, '2026-10', 1995, :at)"), {"b": A, "m": f"outreach_research_pence:{brand['id']}", "at": NOW.isoformat()})
    world = World([[person(1)]], cost=10)
    out = run(db, biz, lia, world)
    assert out["stopped"] and "budget" in out["stopped"] and world.briefs == []


def test_spend_is_recorded_per_month(db):
    biz, brand, lia, campaign = started(db)
    run(db, biz, lia, World([[person(i) for i in range(20)]], cost=37))
    assert int(float(count(db, "SELECT value FROM usage_meters WHERE business_id = :b "
                               "AND meter = :m AND period = '2026-10'", m=f"outreach_research_pence:{brand['id']}"))) == 37


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
        r.configure(s, biz, OWNER, {"brand_id": brand["id"], "enabled": False})
        assert r.run_due(s, moment=NOW, runner=lambda *a, **k: pytest.fail("ran while switched off")) == []


def test_new_contacts_are_enrolled_into_the_audience_campaign_within_its_limit(db):
    """Decision E: verified contacts join the active campaign for their
    audience (pilot limit 5 for now); research never sends."""
    biz, brand, lia, campaign = started(db)
    run(db, biz, lia, World([[person(i) for i in range(8)]]))
    assert count(db, "SELECT count(*) FROM outreach_enrolments WHERE business_id = :b AND campaign_id = :c",
                 c=campaign["id"]) == 5
    assert count(db, "SELECT count(*) FROM aria_actions WHERE business_id = :b AND status <> 'proposed'") == 0


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


# ------------------------------------------------ Codex OUT-10 review 1 (P1s) ---

def test_the_fetcher_connects_only_to_the_address_it_checked():
    """P1 1, DNS rebinding: a name that answers public then private must be
    fetched from the public address it was checked against, never re-resolved."""
    import httpx
    r = research()
    answers = iter([[("93.184.216.34",)], [("127.0.0.1",)]])
    seen = []

    def resolve(host):
        return next(answers)

    def handler(request):
        seen.append((request.url.host, request.headers.get("host")))
        return httpx.Response(200, text="<html>hello@site.example</html>")
    out = r.fetch_page("https://site.example/team", resolve=resolve, transport=httpx.MockTransport(handler))
    assert out and out["text"].startswith("<html>")
    assert seen == [("93.184.216.34", "site.example")], "connected to the checked address, with the real Host"


def test_a_redirect_to_a_private_address_is_refused():
    import httpx
    r = research()

    def resolve(host):
        return [("93.184.216.34",)] if host == "site.example" else [("10.0.0.5",)]

    def handler(request):
        return httpx.Response(302, headers={"location": "https://internal.example/admin"})
    assert r.fetch_page("https://site.example/team", resolve=resolve, transport=httpx.MockTransport(handler)) is None


def test_an_unrelated_company_number_never_makes_a_contact_eligible(db):
    """P1 2: the model names an active PLC's number for a sole trader."""
    biz, brand, lia, campaign = started(db)
    world = World([[person(1, company="Sam's Studio", number="99999999")]])
    world.registry["99999999"] = {"number": "99999999", "name": "BIG HOLDINGS PLC", "status": "active",
                                  "type": "plc", "officers": ["TAYLOR, Sam"]}
    world.not_companies.add("Sam's Studio")   # a sole trader: not on the register by name
    out = run(db, biz, lia, world)
    assert out["accepted"] == []
    assert count(db, "SELECT count(*) FROM outreach_prospects WHERE business_id = :b AND eligibility = 'eligible'") == 0


def test_the_companys_own_site_must_show_its_registration(db):
    """P1 2: Companies House and the website must agree on the legal entity."""
    biz, brand, lia, campaign = started(db)
    world = World([[person(1)]])
    world.no_disclosure.add("studio1.example")
    out = run(db, biz, lia, world)
    assert out["accepted"] == [] and "review" in out["rejected"][0]["reason"].lower()


def test_a_limited_partnership_is_not_a_corporate_subscriber(db):
    biz, brand, lia, campaign = started(db)
    world = World([[person(1)]])
    world.types["Studio 1 Ltd"] = "limited-partnership"
    assert run(db, biz, lia, world)["accepted"] == []


@pytest.mark.parametrize("page", [
    "<html>notsam@studio1.example.evil.example</html>",     # a longer, different address
    "<html>xsam@studio1.example</html>",
])
def test_the_email_must_appear_as_a_complete_address(db, page):
    """P1 3."""
    biz, brand, lia, campaign = started(db)
    world = World([[person(1)]])
    world.pages["https://studio1.example/team"] = page
    assert run(db, biz, lia, world)["accepted"] == []


def test_the_source_must_be_the_companys_own_website(db):
    """P1 3: an attacker's page listing the address proves nothing."""
    biz, brand, lia, campaign = started(db)
    candidate = {**person(1), "source_url": "https://attacker.example/list"}
    world = World([[candidate]])
    world.pages["https://attacker.example/list"] = "<html>sam@studio1.example Studio 1 Ltd company number " \
        + World.number_for("Studio 1 Ltd") + "</html>"
    out = run(db, biz, lia, world)
    assert out["accepted"] == [] and "own website" in out["rejected"][0]["reason"]


def test_spend_is_reserved_before_each_search_so_the_cap_holds(db):
    """P1 4: with 1,990p of 2,000p spent, a search that could cost more than
    the 10p left never starts."""
    biz, brand, lia, campaign = started(db)
    with db.begin() as c:
        c.execute(text("INSERT INTO usage_meters (business_id, meter, period, value, updated_at) VALUES "
                       "(:b, :m, '2026-10', 1990, :at)"), {"b": A, "m": f"outreach_research_pence:{brand['id']}", "at": NOW.isoformat()})
    world = World([[person(1)]], cost=37)
    out = run(db, biz, lia, world)
    assert world.briefs == [] and "budget" in out["stopped"]


def test_a_failed_search_keeps_its_reserved_spend_and_never_retries(db):
    """P1 4: billable work may have happened; it stays counted, no retry."""
    biz, brand, lia, campaign = started(db)
    world = World([[person(1)]])
    world.search_error = TimeoutError("provider timeout")
    out = run(db, biz, lia, world)
    assert len(world.briefs) == 1 and out["stopped"]
    held = int(float(count(db, "SELECT value FROM usage_meters WHERE business_id = :b AND meter = :m", m=f"outreach_research_pence:{brand['id']}")))
    assert held == research().MAX_SEARCH_PENCE


def test_the_daily_quota_is_shared_across_audiences(db):
    """P1 5: two audiences never make more than 20 a day, 10 gatekeepers."""
    m = setup_module_or_missing()
    biz, brand, lia, campaign = started(db)
    with Session(db) as s:
        lia2 = m.draft_audience(s, biz, OWNER, {"brand_id": brand["id"], "description": "Studios in Kent",
                                               "segments": ["gym"], "regions": ["Kent"]},
                                draft=lambda ctx: {k: k for k in ("purpose", "necessity", "balancing_test", "safeguards")})
        m.approve_audience(s, biz, OWNER, lia2["id"], {})
    run(db, biz, lia, World([[person(i) for i in range(15)] + [gatekeeper(100 + i) for i in range(10)]]))
    second = run(db, biz, lia2, World([[person(200 + i) for i in range(15)] + [gatekeeper(300 + i) for i in range(10)]]))
    assert len(second["accepted"]) == 0
    assert count(db, "SELECT count(*) FROM outreach_prospects WHERE business_id = :b AND eligibility = 'eligible'") == 20


@pytest.mark.parametrize("change", ["inactive", "cancelled", "grant_removed", "lia_expired", "not_finished"])
def test_research_needs_current_authority_before_it_spends(db, change):
    """P1 6."""
    biz, brand, lia, campaign = started(db)
    with db.begin() as c:
        if change == "inactive":
            c.execute(text("UPDATE businesses SET is_active = 0 WHERE id = :b"), {"b": A})
        elif change == "cancelled":
            c.execute(text("UPDATE businesses SET subscription_status = 'canceled' WHERE id = :b"), {"b": A})
        elif change == "grant_removed":
            c.execute(text("UPDATE businesses SET feature_flags = '{}' WHERE id = :b"), {"b": A})
        elif change == "lia_expired":
            c.execute(text("UPDATE outreach_compliance SET review_due_at = :t"), {"t": (NOW - timedelta(days=1)).isoformat()})
        else:
            doc = json.loads(c.execute(text("SELECT settings FROM business_settings WHERE business_id = :b"), {"b": A}).scalar())
            doc.pop("outreach_setup", None)
            c.execute(text("UPDATE business_settings SET settings = :s WHERE business_id = :b"), {"s": json.dumps(doc), "b": A})
    world = World([[person(1)]])
    out = run(db, biz, lia, world)
    assert world.briefs == [] and out["stopped"] and out["accepted"] == []


def test_an_opt_out_during_verification_wins(db):
    """P1 7: re-checked under the business lock just before storing."""
    from services.outreach_send import suppression_digest
    biz, brand, lia, campaign = started(db)
    world = World([[person(1)]])
    real_mx = world.mx

    def mx_then_opt_out(domain):
        with db.begin() as c:
            c.execute(text("INSERT INTO outreach_suppressions (id, business_id, key_type, key_digest, digest_version, "
                           "reason, suppressed_at) VALUES (:id, :b, 'email', :d, 1, 'unsubscribe', :at)"),
                      {"id": str(uuid.uuid4()), "b": A, "d": suppression_digest(A, "email", "sam@studio1.example"),
                       "at": NOW.isoformat()})
        return real_mx(domain)
    world.mx = mx_then_opt_out
    run(db, biz, lia, world)
    assert count(db, "SELECT count(*) FROM outreach_prospects WHERE business_id = :b AND eligibility = 'eligible'") == 0


# ---------------------------------------------------------- review 1 backlog ---

def test_two_addresses_at_one_company_in_one_batch_store_only_one(db):
    biz, brand, lia, campaign = started(db)
    out = run(db, biz, lia, World([[person(1), person(1, name="Jo Bloggs", role="Director", email="jo@studio1.example")]]))
    assert len(out["accepted"]) == 1


def test_a_first_name_alone_never_verifies_a_role(db):
    biz, brand, lia, campaign = started(db)
    world = World([[person(1, name="Sam", role="Director")]])
    world.officers["Studio 1 Ltd"] = ["OTHERPERSON, Sam"]
    run(db, biz, lia, world)
    assert count(db, "SELECT fact_value FROM outreach_evidence WHERE business_id = :b AND fact_type = 'role_verified'") == "false"


def test_new_contacts_have_their_first_email_waiting_for_approval(db):
    """Decision E: enrolled contacts get their morning card (never sent)."""
    biz, brand, lia, campaign = started(db)
    run(db, biz, lia, World([[person(i) for i in range(3)]]))
    assert count(db, "SELECT count(*) FROM aria_actions WHERE business_id = :b AND action_type = 'send_outreach' "
                     "AND status = 'proposed'") == 3


# ------------------------------------------------ Codex OUT-10 review 2 (P1s) ---

@pytest.mark.parametrize("footer", [
    "<footer>Sam Taylor, sole trader trading as Studio 1.</footer>",     # the name, not the company
    "<footer>Studio 10 Ltd is registered in England, company number 87654321.</footer>",
])
def test_the_site_must_show_the_registered_company_number(db, footer):
    """P1 1: only the registered number is an unambiguous disclosure."""
    biz, brand, lia, campaign = started(db)
    world = World([[person(1)]])
    world.pages["https://studio1.example/team"] = "<html>sam@studio1.example " + footer + "</html>"
    world.pages["https://studio1.example/"] = "<html>" + footer + "</html>"
    assert run(db, biz, lia, world)["accepted"] == []


def test_a_company_with_no_status_is_not_active(db):
    biz, brand, lia, campaign = started(db)
    world = World([[person(1)]])
    record = world.companies("Studio 1 Ltd")
    world.registry["Studio 1 Ltd"] = {**record, "status": ""}
    assert run(db, biz, lia, world)["accepted"] == []


@pytest.mark.parametrize("prefix", ["!", "/", "=", "#", "$", "%", "&", "'", "*", "+", "-", "?", "^", "_", "`",
                                    "{", "|", "}", "~", "."])
def test_part_of_a_longer_address_is_never_proof(db, prefix):
    """P1 2: every character legal in an address belongs to it."""
    biz, brand, lia, campaign = started(db)
    world = World([[person(1)]])
    number = World.number_for("Studio 1 Ltd")
    world.pages["https://studio1.example/team"] = f"<html>{prefix}sam@studio1.example company number {number}</html>"
    assert run(db, biz, lia, world)["accepted"] == []


def test_the_research_call_never_retries_by_itself_and_bounds_its_search_context():
    """P1 3: an SDK retry after a timeout would double uncertain spend."""
    import inspect
    from services import ai_router   # OUT-19 H: research's provider calls live in the router
    source = inspect.getsource(ai_router._openai_compatible_search)
    assert "max_retries=0" in source and '"search_context_size": "low"' in source


def test_a_search_costing_more_than_its_reservation_pauses_research(db):
    """P1 3: the reservation must hold; if it ever doesn't, research stops
    for the business until the owner looks, and the full cost is kept."""
    biz, brand, lia, campaign = started(db)
    r = research()
    world = World([[person(1)]], cost=r.MAX_SEARCH_PENCE + 9)
    out = run(db, biz, lia, world)
    assert "paused" in out["stopped"]
    assert int(float(count(db, "SELECT value FROM usage_meters WHERE business_id = :b "
                               "AND meter = :m", m=f"outreach_research_pence:{brand['id']}"))) == r.MAX_SEARCH_PENCE + 9
    with Session(db) as s:
        assert r.status(s, biz)["brands"][0]["enabled"] is False


def test_lowering_the_budget_mid_run_stops_the_next_search(db):
    biz, brand, lia, campaign = started(db)
    world = World([[person(1)], [person(2)], [person(3)]])
    real = world.search

    def search_then_lower(brief):
        out = real(brief)
        with db.begin() as c:
            doc = json.loads(c.execute(text("SELECT settings FROM business_settings WHERE business_id = :b"),
                                       {"b": A}).scalar())
            doc["outreach_research"]["brands"][brand["id"]]["monthly_cap_pence"] = 0
            c.execute(text("UPDATE business_settings SET settings = :s WHERE business_id = :b"),
                      {"s": json.dumps(doc), "b": A})
        return out
    world.search = search_then_lower
    run(db, biz, lia, world)
    assert len(world.briefs) == 1


# ---------------------------------------------------------- review 2 backlog ---

def test_a_role_is_verified_only_when_the_surname_matches(db):
    biz, brand, lia, campaign = started(db)
    world = World([[person(1, name="Sam James", role="Director")]])
    world.officers["Studio 1 Ltd"] = ["SMITH, Sam James"]
    run(db, biz, lia, world)
    assert count(db, "SELECT fact_value FROM outreach_evidence WHERE business_id = :b AND fact_type = 'role_verified'") == "false"


def test_followups_due_on_existing_enrolments_get_their_morning_card(db):
    biz, brand, lia, campaign = started(db)
    run(db, biz, lia, World([[person(1)]]))
    with db.begin() as c:
        c.execute(text("DELETE FROM aria_actions WHERE business_id = :b"), {"b": A})
    with Session(db) as s:
        made = research().prepare_due_cards(s, biz, NOW)
    assert len(made) == 1


def test_aria_can_read_the_research_status_and_lessons():
    research()
    import assistant_tools
    names = [t["function"]["name"] for t in assistant_tools.TOOL_DEFINITIONS]
    assert "get_outreach_research" in names


# ------------------------------------------------ Codex OUT-10 review 3 (P1s) ---

@pytest.mark.parametrize("page", [
    # an unrelated company's number in the credits of a sole trader's site
    "<html><p>Sam Taylor is a sole trader. Email sam@studio1.example.</p>"
    "<footer>Website built by Studio 1 Ltd (company number {n})</footer></html>",
    # the number only inside markup, not visible text
    "<html><p>Email sam@studio1.example</p><img src=\"/img/{n}.png\" alt=\"logo\"></html>",
    # name and number, but no registration statement binding them
    "<html><p>Studio 1 Ltd. Email sam@studio1.example. Ref {n}</p></html>",
    # a proper disclosure, but the page says the business trades as a sole trader
    "<html><p>Sam trading as Studio 1. Email sam@studio1.example.</p>"
    "<footer>Studio 1 Ltd is registered in England and Wales, company number {n}.</footer></html>",
])
def test_only_a_proper_legal_disclosure_binds_the_company(db, page):
    biz, brand, lia, campaign = started(db)
    world = World([[person(1)]])
    n = World.number_for("Studio 1 Ltd")
    world.pages["https://studio1.example/team"] = page.format(n=n)
    world.pages["https://studio1.example/"] = page.format(n=n)
    assert run(db, biz, lia, world)["accepted"] == []


def test_a_proper_disclosure_is_accepted(db):
    biz, brand, lia, campaign = started(db)
    world = World([[person(1)]])
    n = World.number_for("Studio 1 Ltd")
    world.pages["https://studio1.example/team"] = (
        "<html><p>Email sam@studio1.example</p><footer>Studio 1 Limited. Registered in England and Wales. "
        f"Company registration number: {n}. Registered office: 1 High St.</footer></html>")
    assert len(run(db, biz, lia, world)["accepted"]) == 1


def test_a_quoted_local_part_is_never_proof(db):
    biz, brand, lia, campaign = started(db)
    world = World([[person(1)]])
    n = World.number_for("Studio 1 Ltd")
    world.pages["https://studio1.example/team"] = (
        f'<html>"sam@studio1.example"@other.example Studio 1 Ltd is registered in England, company number {n}.</html>')
    assert run(db, biz, lia, world)["accepted"] == []


def test_the_reserve_covers_the_models_hard_maximum():
    """P1 3: the reservation is computed from limits the provider enforces:
    the model's whole context window, the output cap and the tool-call cap."""
    r = research()
    worst = (r.MODEL_CONTEXT_TOKENS * r.PRICE_IN_PER_M + r.MAX_OUTPUT_TOKENS * r.PRICE_OUT_PER_M) / 1_000_000 \
        + r.MAX_TOOL_CALLS * r.PRICE_PER_SEARCH
    assert r.MAX_SEARCH_PENCE >= worst


def test_a_compound_surname_is_not_a_match(db):
    biz, brand, lia, campaign = started(db)
    world = World([[person(1, name="Sam Jones", role="Director")]])
    world.officers["Studio 1 Ltd"] = ["SMITH-JONES, Sam"]
    run(db, biz, lia, world)
    assert count(db, "SELECT fact_value FROM outreach_evidence WHERE business_id = :b AND fact_type = 'role_verified'") == "false"


# ------------------------------- Codex OUT-10 review 4 (Mike chose: recommended) ---

@pytest.mark.parametrize("credit", [
    "Website designed and hosted by Studio 1 Ltd. Company registration number {n}.",
    "Site by Studio 1 Ltd, registered in England, company number {n}.",
    "Powered by Studio 1 Ltd (registered in England and Wales, company no. {n})",
    "Web design: Studio 1 Ltd, company number {n}",
])
def test_a_third_party_credit_never_establishes_the_operator(db, credit):
    """The designer's disclosure is about the designer, not the site's owner."""
    biz, brand, lia, campaign = started(db)
    world = World([[person(1)]])
    n = World.number_for("Studio 1 Ltd")
    page = f"<html><p>Personal training with Sam. Email sam@studio1.example</p><footer>{credit.format(n=n)}</footer></html>"
    world.pages["https://studio1.example/team"] = page
    world.pages["https://studio1.example/"] = page
    assert run(db, biz, lia, world)["accepted"] == []


def test_a_company_trading_under_another_name_is_accepted(db):
    """Review 4 backlog: the company itself trading as a brand is fine."""
    biz, brand, lia, campaign = started(db)
    world = World([[person(1)]])
    n = World.number_for("Studio 1 Ltd")
    world.pages["https://studio1.example/team"] = (
        "<html><p>Email sam@studio1.example</p><footer>Studio 1 Ltd trading as Fitness Club. "
        f"Registered in England and Wales, company number {n}.</footer></html>")
    assert len(run(db, biz, lia, world)["accepted"]) == 1


def test_the_email_domain_must_fit_the_company_or_its_trading_name(db):
    """Mike's added sanity check: a personal trainer's own domain does not fit a
    design agency's name, so even an unusual credit cannot make them eligible."""
    biz, brand, lia, campaign = started(db)
    candidate = {**person(1, company="Pixel Forge Ltd", email="sam@samtaylorpt.example"),
                 "source_url": "https://samtaylorpt.example/contact"}
    world = World([[candidate]])
    n = World.number_for("Pixel Forge Ltd")
    world.pages["https://samtaylorpt.example/contact"] = (
        f"<html><p>Email sam@samtaylorpt.example</p><footer>Pixel Forge Ltd is registered in England, "
        f"company number {n}.</footer></html>")
    out = run(db, biz, lia, world)
    assert out["accepted"] == [] and "review" in out["rejected"][0]["reason"]


@pytest.mark.parametrize("company,domain", [
    ("Studio 1 Ltd", "studio1.example"), ("Harbour Lettings Limited", "harbourlettings.example"),
    ("Peak Form Studios Ltd", "peakform.example"), ("MSC Company Ltd", "msccompany.example"),
])
def test_ordinary_company_domains_fit(company, domain):
    assert research()._domain_fits(domain, company, [])


# ------------------------------------- Codex OUT-10 review 5 backlog: false rejections ---

def _accepted_with(db, team, home=None, company="Studio 1 Ltd", domain="studio1.example"):
    biz, brand, lia, campaign = started(db)
    candidate = {**person(1, company=company, email=f"sam@{domain}"), "source_url": f"https://{domain}/team"}
    world = World([[candidate]])
    n = World.number_for(company)
    world.pages[f"https://{domain}/team"] = team.format(n=n)
    world.pages[f"https://{domain}/"] = (home or team).format(n=n)
    return len(run(db, biz, lia, world)["accepted"]) == 1


def test_a_real_disclosure_followed_by_a_designer_credit_is_accepted(db):
    assert _accepted_with(db, "<html><p>Email sam@studio1.example</p><footer>Studio 1 Ltd is registered in England, "
                              "company number {n}. Website designed by Pixel Forge Ltd.</footer></html>")


@pytest.mark.parametrize("phrase", ["Trading As", "t/a", "trading as"])
def test_trading_names_are_recognised_however_written_and_on_the_home_page(db, phrase):
    team = "<html><p>Email sam@fitnessclub.example</p></html>"
    home = ("<html><footer>Studio 1 Ltd " + phrase + " Fitness Club. Registered in England and Wales, "
            "company number {n}.</footer></html>")
    assert _accepted_with(db, team, home=home, domain="fitnessclub.example")


def test_ordinary_partnership_wording_is_not_a_partnership(db):
    assert _accepted_with(db, "<html><p>We work in partnership with local schools. Email sam@studio1.example</p>"
                              "<footer>Studio 1 Ltd is registered in England, company number {n}.</footer></html>")


def test_a_business_that_is_a_partnership_is_still_review(db):
    assert not _accepted_with(db, "<html><p>We are a partnership of two coaches. Email sam@studio1.example</p>"
                                  "<footer>Studio 1 Ltd is registered in England, company number {n}.</footer></html>")
