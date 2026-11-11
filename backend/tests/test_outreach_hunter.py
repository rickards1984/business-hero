"""OUT-23 Part B — the Hunter.io add-on (docs/OUT-23-TICKET.md Part B,
revisions 1-4; design approved by Codex design review 4). RED: paid
third-party lookups, personal data, the send path.

Hunter is always faked. Only an address Hunter FOUND published, that we see
on the page ourselves, and that verifies VALID is kept (Mike, 11 Nov 2026).
"""
# ruff: noqa: F811 - pytest fixtures imported from test_outreach_setup are parameters by design
import json
import logging
from contextlib import contextmanager
from datetime import timedelta
from unittest import mock

import pytest
from sqlalchemy import text
from sqlmodel import Session

from test_outreach_setup import A, OWNER, STAFF, db  # noqa: F401
from test_outreach_research import NOW, World, count, person, research, run_clock, started

KEY = "hunterTESTkey0123456789abcdef"
TODAY = NOW.date()


def hunter():
    from services import outreach_hunter
    return outreach_hunter


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    from cryptography.fernet import Fernet
    from app.email import crypto
    monkeypatch.setenv("OUTREACH_PILOT_ENROLMENTS", "0")
    monkeypatch.setattr(crypto, "_EMAIL_ENCRYPTION_KEY", Fernet.generate_key().decode())


# ------------------------------------------------------------------ fakes ---

def found(email, *, first="Jo", last="Smith", position="Managing Director", seniority="executive", confidence=90,
          provenance="found", kind="personal", status="valid", verified=TODAY, sources=None):
    """One Domain Search result, as Hunter documents it."""
    domain = email.split("@")[1]
    return {"value": email, "type": kind, "confidence": confidence, "first_name": first, "last_name": last,
            "position": position, "seniority": seniority, "provenance": provenance, "linkedin": "https://x/jo",
            "phone_number": "+44 1", "verification": {"status": status, "date": verified.isoformat() if verified else None},
            "sources": sources if sources is not None else [
                {"domain": domain, "uri": f"https://{domain}/team", "extracted_on": "2026-01-01",
                 "last_seen_on": (TODAY - timedelta(days=3)).isoformat(), "still_on_page": True}]}


def verdict(email, *, status="valid", date=TODAY, **flags):
    data = {"email": email, "status": status, "result": "deliverable", "score": 95, "regexp": True,
            "gibberish": False, "disposable": False, "webmail": False, "mx_records": True, "smtp_server": True,
            "smtp_check": True, "accept_all": False, "block": False,
            "verification": {"status": status, "date": date.isoformat() if date else None}}
    data.update(flags)
    return data


class Hunter:
    """A fake Hunter API: the transport research is given."""

    def __init__(self, *, model="single"):
        self.calls, self.people, self.verdicts, self.fail, self.during = [], {}, {}, {}, {}
        self.credits = {"domain-search": ("1", "credit" if model == "single" else "search"),
                        "email-verifier": ("0.5", "credit") if model == "single" else ("1", "verification"),
                        "account": ("0", "credit")}
        self.account = ({"plan_name": "Starter", "reset_date": "2026-11-15",
                         "requests": {"credits": {"used": 10, "available": 1990}}} if model == "single" else
                        {"plan_name": "Legacy", "reset_date": "2026-11-15",
                         "requests": {"searches": {"used": 1, "available": 500},
                                      "verifications": {"used": 1, "available": 1000}}})
        self.pending = {}

    def __call__(self, method, path, params, key, timeout):
        assert method == "GET" and key == KEY and "api_key" not in params
        self.calls.append((path, dict(params)))
        if path in self.during:
            self.during.pop(path)()
        used, unit = self.credits[path]
        headers = {"X-Credits-Used": used, "X-Credits-Unit": unit}
        if path in self.fail:
            status = self.fail[path]
            return status, {"errors": [{"id": "x", "code": status, "details": "no"}]}, headers
        if path == "account":
            return 200, {"data": self.account}, {}
        if path == "domain-search":
            return 200, {"data": {"domain": params["domain"], "pattern": "{first}",
                                  "emails": self.people.get(params["domain"], [])}}, headers
        email = params["email"]
        if self.pending.get(email, 0) > 0:
            self.pending[email] -= 1
            return 202, {"data": {"email": email, "status": "unknown"}}, headers
        return 200, {"data": self.verdicts.get(email, verdict(email))}, headers

    def count(self, path):
        return sum(1 for p, _ in self.calls if p == path)


def lead(i, **kw):
    """A company Aria found with no published named email (a Hunter lead)."""
    c = person(i, **kw)
    c.update(contact_email="", contact_name="", role="", website=f"https://studio{i}.example",
             source_url=f"https://studio{i}.example/contact")
    return c


def jo(i):
    return f"jo@studio{i}.example"


@contextmanager
def clocks():
    """The run's clocks, research's own included (the Hunter gate reads fresh time)."""
    with run_clock(), mock.patch.object(research(), "now", lambda: NOW):
        yield


def connect_row(db, *, model="single", generation=1, status="connected", available="1990", blocked=None):
    from app.email.crypto import encrypt_secret
    from services import outreach_send as send
    pools = ({"credit": {"used": "10", "available": available}, "model": "single", "reset_date": "2026-11-15"}
             if model == "single" else
             {"search": {"used": "1", "available": available}, "verification": {"used": "1", "available": available},
              "model": "separate", "reset_date": "2026-11-15"})
    with Session(db) as s:
        s.execute(text("DELETE FROM outreach_provider_accounts WHERE business_id = :b"), {"b": A})
        send.insert(s, "outreach_provider_accounts", A, provider="hunter", generation=generation, status=status,
                    key_ciphertext=encrypt_secret(KEY), key_last4=KEY[-4:], plan="Starter", pools=pools,
                    account_fetched_at=NOW, blocked=blocked or {}, connected_by=OWNER, connected_at=NOW)
        s.commit()


def with_hunter(db, *, model="single", sources=("public_websites", "hunter.io"), enable=True, **row):
    """A started business with Hunter connected, its audience approved with
    Hunter as a source, and the brand's notice confirmed and switched on."""
    biz, brand, lia, campaign = started(db)
    connect_row(db, model=model, **row)
    with Session(db) as s:
        s.execute(text("UPDATE outreach_compliance SET sources = :s WHERE id = :l"),
                  {"s": json.dumps(list(sources)), "l": lia["id"]})
        s.commit()
    if enable:
        with clocks(), Session(db) as s:
            hunter().configure_brand(s, biz, OWNER, brand["id"], {"confirm_notice": True, "enabled": True})
    return biz, brand, lia, campaign


def hrun(db, biz, lia, world, fake, *, drain=False):
    with clocks(), Session(db) as s:
        out = research().run(s, biz, lia["id"], **world.kwargs(), hunter=fake, sleep=lambda _s: None)
    if drain:
        from services import outreach_bank
        with clocks(), Session(db) as s:
            out["drained"] = outreach_bank.drain_business(s, biz, NOW)
        with clocks(), Session(db) as s:
            out["cards"] = research().prepare_due_cards(s, biz, NOW)
    return out


def evidence(db, fact, prospect=None):
    with db.connect() as c:
        return [dict(r) for r in c.execute(text(
            "SELECT * FROM outreach_evidence WHERE business_id = :b AND fact_type = :f"
            + (" AND prospect_id = :p" if prospect else "")), {"b": A, "f": fact, "p": prospect}).mappings()]


def charges(db):
    with db.connect() as c:
        return [dict(r) for r in c.execute(text(
            "SELECT * FROM outreach_provider_charges WHERE business_id = :b ORDER BY created_at"), {"b": A}).mappings()]


# --------------------------------------------------------- the happy path ---

def test_a_found_and_valid_decision_maker_is_stored_with_its_provenance(db):
    biz, brand, lia, campaign = with_hunter(db)
    fake = Hunter()
    fake.people["studio1.example"] = [found(jo(1))]
    out = hrun(db, biz, lia, World([[lead(1)]]), fake)
    assert len(out["accepted"]) == 1 and out["via_hunter"] == 1 and out["decision_makers"] == 1
    pid = out["accepted"][0]
    acquisition = evidence(db, "acquisition", pid)
    assert len(acquisition) == 1 and acquisition[0]["source_type"] == "hunter" and acquisition[0]["fact_value"] == "hunter"
    assert acquisition[0]["source_url"] == "https://studio1.example/team"          # where we saw the address
    verification = evidence(db, "email_verification", pid)[0]
    assert verification["verification_status"] == "valid" and verification["source_type"] == "hunter"
    assert str(verification["verified_at"])[:10] == TODAY.isoformat()             # Hunter's date, not the run's
    assert evidence(db, "source", pid)[0]["fact_value"] == "hunter"
    assert fake.count("domain-search") == 1 and fake.count("email-verifier") == 0     # searched valid, fresh
    assert "found via Hunter" in research().summary(biz, {**research()._EMPTY_RUN, **out})


def test_nothing_else_from_hunter_is_kept(db):
    biz, brand, lia, campaign = with_hunter(db)
    fake = Hunter()
    fake.people["studio1.example"] = [found(jo(1)), found("owner@studio1.example", first="Pat", position="Director")]
    out = hrun(db, biz, lia, World([[lead(1)]]), fake)
    assert len(out["accepted"]) == 1
    with db.connect() as c:
        dump = json.dumps([dict(r) for r in c.execute(text("SELECT * FROM outreach_evidence")).mappings()], default=str)
        dump += json.dumps([dict(r) for r in c.execute(text("SELECT * FROM outreach_prospects")).mappings()], default=str)
        dump += json.dumps([dict(r) for r in c.execute(text("SELECT * FROM outreach_provider_charges")).mappings()], default=str)
    for gone in ("owner@studio1.example", "Pat", "linkedin", "+44 1", "https://x/jo"):
        assert gone not in dump


def test_the_first_email_names_hunter_and_a_web_contact_s_footer_is_unchanged(db):
    biz, brand, lia, campaign = with_hunter(db)
    fake = Hunter()
    fake.people["studio1.example"] = [found(jo(1))]
    hrun(db, biz, lia, World([[lead(1), person(2)]]), fake, drain=True)
    with db.connect() as c:
        payloads = [json.loads(r[0]) for r in c.execute(text(
            "SELECT payload FROM aria_actions WHERE business_id = :b AND action_type = 'send_outreach'"), {"b": A})]
    footers = {p["to"]: p["footer"] for p in payloads}
    assert "Source: https://studio1.example/team (found via Hunter.io, a business contact database)\n" in footers[jo(1)]
    assert "Source: https://studio2.example/team\nPrivacy:" in footers["sam@studio2.example"]
    assert "Hunter" not in footers["sam@studio2.example"]


def test_a_role_address_lead_gives_way_to_a_named_decision_maker(db):
    """A company whose site publishes only info@: Hunter's named director is
    kept instead (one per company), not both."""
    biz, brand, lia, campaign = with_hunter(db)
    fake = Hunter()
    fake.people["studio1.example"] = [found(jo(1))]
    gk = person(1, name="", role="", email="info@studio1.example", kind="gatekeeper")
    gk["website"] = "https://studio1.example"
    out = hrun(db, biz, lia, World([[gk]]), fake)
    with db.connect() as c:
        emails = [r[0] for r in c.execute(text("SELECT email FROM outreach_prospects WHERE business_id = :b"), {"b": A})]
    assert emails == [jo(1)] and out["decision_makers"] == 1


def test_without_hunter_a_lead_with_no_email_is_rejected_as_today(db):
    biz, brand, lia, campaign = started(db)
    world = World([[lead(1)]])
    with clocks(), Session(db) as s:
        out = research().run(s, biz, lia["id"], **world.kwargs(), hunter=Hunter(), sleep=lambda _s: None)
    assert out["accepted"] == [] and {r["reason"] for r in out["rejected"]} == {"no usable company or email"}


def test_the_brief_asks_for_company_leads_only_when_hunter_is_on(db):
    biz, brand, lia, campaign = with_hunter(db)
    world = World([[]])
    hrun(db, biz, lia, world, Hunter())
    assert "COMPANY LEADS" in world.briefs[0]
    biz2 = biz
    with clocks(), Session(db) as s:
        hunter().configure_brand(s, biz2, OWNER, brand["id"], {"enabled": False})
    world = World([[]])
    hrun(db, biz, lia, world, Hunter())
    assert world.briefs and "COMPANY LEADS" not in world.briefs[0]


# -------------------------------------------------- what is never accepted ---

@pytest.mark.parametrize("change", [
    dict(provenance="inferred"),
    dict(provenance=None),
    dict(provenance="previously_found"),
    dict(kind="generic"),
    dict(sources=[]),
    dict(sources=[{"domain": "studio1.example", "uri": "https://studio1.example/team", "still_on_page": False,
                   "last_seen_on": TODAY.isoformat()}]),
    dict(sources=[{"domain": "studio1.example", "uri": "https://studio1.example/team", "still_on_page": True,
                   "last_seen_on": (TODAY - timedelta(days=91)).isoformat()}]),
    dict(sources=[{"domain": "studio1.example", "uri": "https://studio1.example/team", "still_on_page": True,
                   "last_seen_on": (TODAY + timedelta(days=1)).isoformat()}]),
    dict(sources=[{"domain": "studio1.example", "uri": "https://studio1.example/team", "still_on_page": True,
                   "last_seen_on": "last week"}]),
    dict(sources=[{"domain": "studio1.example", "uri": "http://studio1.example/team", "still_on_page": True,
                   "last_seen_on": TODAY.isoformat()}]),
])
def test_only_an_address_hunter_found_published_recently_is_considered(db, change):
    biz, brand, lia, campaign = with_hunter(db)
    fake = Hunter()
    fake.people["studio1.example"] = [found(jo(1), **change)]
    out = hrun(db, biz, lia, World([[lead(1)]]), fake)
    assert out["accepted"] == [] and fake.count("email-verifier") == 0


def test_an_address_on_another_domain_is_never_taken(db):
    biz, brand, lia, campaign = with_hunter(db)
    fake = Hunter()
    fake.people["studio1.example"] = [found("jo@elsewhere.example")]
    assert hrun(db, biz, lia, World([[lead(1)]]), fake)["accepted"] == []


def test_an_address_no_longer_on_its_page_is_dropped(db):
    biz, brand, lia, campaign = with_hunter(db)
    fake = Hunter()
    fake.people["studio1.example"] = [found("kim@studio1.example", first="Kim")]   # the page shows no kim@
    out = hrun(db, biz, lia, World([[lead(1)]]), fake)
    assert out["accepted"] == [] and fake.count("email-verifier") == 0


@pytest.mark.parametrize("status", ["accept_all", "unknown", "invalid", "webmail", "disposable"])
def test_only_valid_is_kept(db, status):
    """Hunter's own status is not valid: the Verifier is asked, and says the same."""
    biz, brand, lia, campaign = with_hunter(db)
    fake = Hunter()
    fake.people["studio1.example"] = [found(jo(1), status=status)]
    fake.verdicts[jo(1)] = verdict(jo(1), status=status)
    out = hrun(db, biz, lia, World([[lead(1)]]), fake)
    assert out["accepted"] == [] and fake.count("email-verifier") == 1


def test_a_stale_valid_is_verified_again_and_stored_with_the_verifier_s_date(db):
    biz, brand, lia, campaign = with_hunter(db)
    fake = Hunter()
    fake.people["studio1.example"] = [found(jo(1), verified=TODAY - timedelta(days=45))]
    fake.verdicts[jo(1)] = verdict(jo(1), date=TODAY - timedelta(days=2))
    out = hrun(db, biz, lia, World([[lead(1)]]), fake)
    assert len(out["accepted"]) == 1 and fake.count("email-verifier") == 1
    assert str(evidence(db, "email_verification")[0]["verified_at"])[:10] == (TODAY - timedelta(days=2)).isoformat()


@pytest.mark.parametrize("change", [
    dict(email="someone@studio1.example"),          # another address
    dict(date=None), dict(date=TODAY + timedelta(days=1)), dict(date=TODAY - timedelta(days=31)),
    dict(accept_all=True), dict(webmail=True), dict(disposable=True), dict(block=True), dict(gibberish=True),
    dict(smtp_check=False), dict(accept_all=None),
    dict(verification={"status": "accept_all", "date": TODAY.isoformat()}),   # contradicts the top level
    dict(verification=None),
])
def test_the_verifier_must_agree_on_every_field(db, change):
    biz, brand, lia, campaign = with_hunter(db)
    fake = Hunter()
    fake.people["studio1.example"] = [found(jo(1), status="unknown")]
    date = change.pop("date", TODAY)
    other = change.pop("email", None)
    fake.verdicts[jo(1)] = {**verdict(jo(1), date=date, **change), **({"email": other} if other else {})}
    out = hrun(db, biz, lia, World([[lead(1)]]), fake)
    assert out["accepted"] == [] and fake.count("email-verifier") == 1


def test_still_verifying_is_polled_then_kept(db):
    biz, brand, lia, campaign = with_hunter(db)
    fake = Hunter()
    fake.people["studio1.example"] = [found(jo(1), status="unknown")]
    fake.pending[jo(1)] = 2
    out = hrun(db, biz, lia, World([[lead(1)]]), fake)
    assert len(out["accepted"]) == 1 and fake.count("email-verifier") == 3
    verify = [c for c in charges(db) if c["operation"] == "verify"]
    # Every request is its own gated, reserved and settled charge (Codex code review 1).
    assert len(verify) == 3 and {c["state"] for c in verify} == {"settled"}
    with Session(db) as s:
        assert float(hunter().used_credits(s, A, brand["id"], NOW)) == 1 + 3 * 0.5


def test_still_verifying_past_the_call_budget_is_dropped_each_poll_charged(db, monkeypatch):
    biz, brand, lia, campaign = with_hunter(db)
    monkeypatch.setattr(hunter(), "MAX_CALLS", 3)
    fake = Hunter()
    fake.people["studio1.example"] = [found(jo(1), status="unknown")]
    fake.pending[jo(1)] = 99
    out = hrun(db, biz, lia, World([[lead(1)]]), fake)
    assert out["accepted"] == []
    verify = [c for c in charges(db) if c["operation"] == "verify"]
    assert len(verify) == fake.count("email-verifier") == 2 and {c["state"] for c in verify} == {"settled"}


def test_a_decision_maker_beats_a_more_confident_gatekeeper_and_no_one_lower_is_verified(db):
    biz, brand, lia, campaign = with_hunter(db)
    fake = Hunter()
    fake.people["studio1.example"] = [
        found("owner@studio1.example", first="Pat", position="Receptionist", seniority="executive", confidence=99,
              status="unknown"),
        found(jo(1), position="Managing Director", seniority="executive", confidence=70, status="unknown"),
        found("sam@studio1.example", first="Sam", last="Taylor", position="Director", seniority="senior",
              confidence=80, status="unknown")]
    out = hrun(db, biz, lia, World([[lead(1)]]), fake)
    with db.connect() as c:
        assert c.execute(text("SELECT email FROM outreach_prospects")).scalar() == jo(1)
    assert len(out["accepted"]) == 1
    assert [p["email"] for path, p in fake.calls if path == "email-verifier"] == [jo(1)]


def test_a_failed_hunter_result_never_falls_back_to_review_or_web(db):
    biz, brand, lia, campaign = with_hunter(db)
    fake = Hunter()
    fake.people["studio1.example"] = [found(jo(1), status="invalid")]
    fake.verdicts[jo(1)] = verdict(jo(1), status="invalid")
    out = hrun(db, biz, lia, World([[lead(1)]]), fake)
    assert out["accepted"] == []
    assert count(db, "SELECT count(*) FROM outreach_prospects WHERE business_id = :b") == 0


# ---------------------------------------------- no credit spent for nothing ---

@pytest.mark.parametrize("why", ["off", "no_key", "no_notice", "notice_changed", "no_source", "newer_version",
                                 "disconnected", "invalid_key"])
def test_no_hunter_call_unless_every_gate_holds(db, why):
    biz, brand, lia, campaign = with_hunter(db, enable=why != "no_notice", sources=(
        ("public_websites",) if why == "no_source" else ("public_websites", "hunter.io")))
    if why == "off":
        with clocks(), Session(db) as s:
            hunter().configure_brand(s, biz, OWNER, brand["id"], {"enabled": False})
    if why == "no_key":
        with Session(db) as s:
            s.execute(text("DELETE FROM outreach_provider_accounts"))
            s.commit()
    if why in ("disconnected", "invalid_key"):
        with Session(db) as s:
            s.execute(text("UPDATE outreach_provider_accounts SET status = :s"),
                      {"s": "disconnected" if why == "disconnected" else "invalid"})
            s.commit()
    if why == "notice_changed":
        from services import outreach_setup
        with clocks(), Session(db) as s:
            outreach_setup.approve_privacy_notice(s, biz, OWNER, brand["id"], {"text": "A different notice."})
    if why == "newer_version":
        with Session(db) as s:
            row = dict(s.execute(text("SELECT * FROM outreach_compliance WHERE id = :l"), {"l": lia["id"]}).mappings().one())
            from test_outreach_setup import _insert
            _insert(s, "outreach_compliance", **{**row, "id": "11111111-1111-1111-1111-111111111111",
                                                 "version": int(row["version"]) + 1,
                                                 "sources": json.dumps(["public_websites"])})
            s.commit()
    fake = Hunter()
    fake.people["studio1.example"] = [found(jo(1))]
    hrun(db, biz, lia, World([[lead(1)]]), fake)
    assert fake.count("domain-search") == 0 and fake.count("email-verifier") == 0 and charges(db) == []


def test_switching_hunter_on_needs_the_notice_confirmed(db):
    biz, brand, lia, campaign = with_hunter(db, enable=False)
    from services.aria_actions import ActionRefused
    with clocks(), Session(db) as s, pytest.raises(ActionRefused) as exc:
        hunter().configure_brand(s, biz, OWNER, brand["id"], {"enabled": True})
    assert "privacy notice" in exc.value.detail


@pytest.mark.parametrize("why", ["held", "suppressed_domain", "erased_domain", "no_mx", "sole_trader", "not_company",
                                 "dissolved", "off_site"])
def test_a_lead_that_could_never_be_kept_costs_no_credit(db, why):
    from services import outreach_send as send
    biz, brand, lia, campaign = with_hunter(db)
    world = World([[lead(1)]])
    if why == "held":
        from test_outreach_setup import _insert
        with Session(db) as s:
            _insert(s, "outreach_prospects", id="22222222-2222-2222-2222-222222222222", business_id=A, company="Old",
                    domain="studio1.example", email="old@studio1.example", email_key="k", eligibility="eligible",
                    captured_at=NOW.isoformat(), created_at=NOW.isoformat(), updated_at=NOW.isoformat())
            s.commit()
    if why == "suppressed_domain":
        with Session(db) as s:
            send.insert(s, "outreach_suppressions", A, key_type="domain", digest_version=1, reason="manual_opt_out",
                        key_digest=send.suppression_digest(A, "domain", "studio1.example"), suppressed_at=NOW)
            s.commit()
    if why == "erased_domain":
        with Session(db) as s:
            send.insert(s, "outreach_recently_erased", A, key_type="domain", digest_version=1,
                        key_digest=send.suppression_digest(A, "domain", "studio1.example"), until=NOW + timedelta(days=30))
            s.commit()
    if why == "no_mx":
        world.no_mx.add("studio1.example")
    if why == "sole_trader":
        for page in ("https://studio1.example/contact", "https://studio1.example/"):
            world.pages[page] = "<html>Studio 1 is run by Sam, a sole trader.</html>"
    if why == "not_company":
        world.not_companies.add("Studio 1 Ltd")
    if why == "dissolved":
        world.dissolved.add("Studio 1 Ltd")
    if why == "off_site":                  # redirected away, to a page that does disclose the company
        world.site_company["studio1.example"] = "Studio 1 Ltd"
        world.pages["https://studio1.example/contact"] = {
            "url": "https://elsewhere.example/", "text": world.fetch("https://studio1.example/x")}
        assert "registered in England" in world.pages["https://studio1.example/contact"]["text"]
    fake = Hunter()
    fake.people["studio1.example"] = [found(jo(1))]
    hrun(db, biz, lia, world, fake)
    assert fake.count("domain-search") == 0 and charges(db) == []


def test_a_suppressed_person_costs_no_verification(db):
    from services import outreach_send as send
    biz, brand, lia, campaign = with_hunter(db)
    with Session(db) as s:
        send.insert(s, "outreach_suppressions", A, key_type="email", digest_version=1, reason="manual_opt_out",
                    key_digest=send.suppression_digest(A, "email", jo(1)), suppressed_at=NOW)
        s.commit()
    fake = Hunter()
    fake.people["studio1.example"] = [found(jo(1), status="unknown")]
    out = hrun(db, biz, lia, World([[lead(1)]]), fake)
    assert out["accepted"] == [] and fake.count("domain-search") == 1 and fake.count("email-verifier") == 0


def test_hunter_stops_when_today_s_places_are_found(db):
    """The gate re-reads the room before every call: with 2 places left today,
    two companies are searched, not five."""
    from test_outreach_setup import _insert
    biz, brand, lia, campaign = with_hunter(db)
    with Session(db) as s:            # 38 contacts already found today for this brand
        for i in range(38):
            pid = f"00000000-0000-0000-0000-{i:012d}"
            _insert(s, "outreach_prospects", id=pid, business_id=A, company=f"Old {i}", domain=f"old{i}.example",
                    email=f"a@old{i}.example", email_key=f"k{i}", eligibility="eligible", lia_id=lia["id"],
                    captured_at=NOW.isoformat(), created_at=NOW.isoformat(), updated_at=NOW.isoformat())
            _insert(s, "outreach_evidence", id=f"10000000-0000-0000-0000-{i:012d}", business_id=A, prospect_id=pid,
                    source_type="web", fact_type="contact_type", fact_value="decision_maker",
                    created_at=NOW.isoformat(), updated_at=NOW.isoformat())
        s.commit()
    fake = Hunter()
    for i in range(1, 6):
        fake.people[f"studio{i}.example"] = [found(jo(i))]
    out = hrun(db, biz, lia, World([[lead(i) for i in range(1, 6)]]), fake)
    assert fake.count("domain-search") == 2 and len(out["accepted"]) == 2


# ----------------------------------------------------------------- errors ---

def test_a_rejected_key_is_marked_and_hunter_stops(db):
    biz, brand, lia, campaign = with_hunter(db)
    fake = Hunter()
    fake.fail["domain-search"] = 401
    out = hrun(db, biz, lia, World([[lead(1), lead(2)]]), fake)
    assert fake.count("domain-search") == 1 and out["accepted"] == []
    with db.connect() as c:
        assert c.execute(text("SELECT status FROM outreach_provider_accounts")).scalar() == "invalid"
    assert "reconnect" in out["hunter_stopped"]


def test_used_up_credits_block_that_pool_until_the_reset_date(db):
    biz, brand, lia, campaign = with_hunter(db)
    fake = Hunter()
    fake.fail["domain-search"] = 429
    hrun(db, biz, lia, World([[lead(1), lead(2)]]), fake)
    assert fake.count("domain-search") == 1
    with db.connect() as c:
        blocked = json.loads(c.execute(text("SELECT blocked FROM outreach_provider_accounts")).scalar())
    assert blocked["credit"].startswith("2026-11-15T00:00:00")
    fake2 = Hunter()
    fake2.people["studio3.example"] = [found(jo(3))]
    hrun(db, biz, lia, World([[lead(3)]]), fake2)
    assert fake2.count("domain-search") == 0                         # still blocked


def test_a_rate_limit_stops_this_run_only(db):
    biz, brand, lia, campaign = with_hunter(db)
    fake = Hunter()
    fake.fail["domain-search"] = 403
    hrun(db, biz, lia, World([[lead(1), lead(2)]]), fake)
    assert fake.count("domain-search") == 1
    with db.connect() as c:
        assert c.execute(text("SELECT status FROM outreach_provider_accounts")).scalar() == "connected"


def test_a_server_error_skips_that_company_only(db):
    biz, brand, lia, campaign = with_hunter(db)
    fake = Hunter()
    fake.people["studio2.example"] = [found(jo(2))]
    calls = []

    def flaky(method, path, params, key, timeout):
        calls.append(params.get("domain"))
        if params.get("domain") == "studio1.example":
            return 503, None, {}
        return fake(method, path, params, key, timeout)
    out = hrun(db, biz, lia, World([[lead(1), lead(2)]]), flaky)
    assert len(out["accepted"]) == 1 and calls.count("studio1.example") == 1
    assert {c["state"] for c in charges(db)} == {"charged", "settled"}      # the failed call keeps its reservation


def test_a_person_who_asked_hunter_to_stop_is_suppressed_everywhere(db):
    """451 on verification: only a digest is kept, and a later ordinary web
    candidate with the same address is refused (R2.10)."""
    biz, brand, lia, campaign = with_hunter(db)
    fake = Hunter()
    fake.people["studio1.example"] = [found(jo(1), status="unknown")]
    fake.fail["email-verifier"] = 451
    out = hrun(db, biz, lia, World([[lead(1)]]), fake)
    assert out["accepted"] == []
    with db.connect() as c:
        rows = [dict(r) for r in c.execute(text("SELECT * FROM outreach_suppressions WHERE business_id = :b"), {"b": A}).mappings()]
    assert len(rows) == 1 and rows[0]["reason"] == "provider_claimed" and jo(1) not in json.dumps(rows, default=str)
    web = person(1, name="Jo Smith", email=jo(1))
    out = hrun(db, biz, lia, World([[web]]), Hunter())
    assert out["accepted"] == [] and any(r["reason"] == "opted out" for r in out["rejected"])


# --------------------------------------------------------------- metering ---

def test_each_call_is_reserved_then_settled_from_hunter_s_own_figures(db):
    biz, brand, lia, campaign = with_hunter(db)
    fake = Hunter()
    fake.people["studio1.example"] = [found(jo(1), status="unknown")]
    hrun(db, biz, lia, World([[lead(1)]]), fake)
    rows = {c["operation"]: c for c in charges(db)}
    assert rows["search"]["state"] == "settled" and str(rows["search"]["brand_credits"]) in ("1", "1.0", "1.0000")
    assert float(rows["verify"]["used_native"]) == 0.5 and float(rows["verify"]["brand_credits"]) == 0.5
    assert {c["period"] for c in charges(db)} == {"2026-10"}
    with Session(db) as s:
        assert float(hunter().used_credits(s, A, brand["id"], NOW)) == 1.5


def test_separate_pools_reserve_their_own_units_and_the_cap_stays_in_credits(db):
    biz, brand, lia, campaign = with_hunter(db, model="separate")
    fake = Hunter(model="separate")
    fake.people["studio1.example"] = [found(jo(1), status="unknown")]
    hrun(db, biz, lia, World([[lead(1)]]), fake)
    rows = {c["operation"]: c for c in charges(db)}
    assert rows["search"]["pool"] == "search" and float(rows["search"]["reserved_native"]) == 1
    assert rows["verify"]["pool"] == "verification" and float(rows["verify"]["reserved_native"]) == 1
    assert float(rows["verify"]["brand_credits"]) == 0.5


@pytest.mark.parametrize("headers,state,credits", [
    ({"X-Credits-Used": "0", "X-Credits-Unit": "credit"}, "settled", 0.0),          # a free repeat frees the cap
    ({}, "charged", 1.0),                                                            # missing: the reservation stands
    ({"X-Credits-Used": "lots", "X-Credits-Unit": "credit"}, "charged", 1.0),
    ({"X-Credits-Used": "1", "X-Credits-Unit": "verification"}, "settled", 1.0),    # mismatched unit: the larger
])
def test_settlement_follows_the_headers(db, headers, state, credits):
    biz, brand, lia, campaign = with_hunter(db)
    fake = Hunter()

    def transport(method, path, params, key, timeout):
        status, body, _ = fake(method, path, params, key, timeout)
        return status, body, headers
    hrun(db, biz, lia, World([[lead(1)]]), transport)
    search = [c for c in charges(db) if c["operation"] == "search"][0]
    assert search["state"] == state and float(search["brand_credits"]) == credits


def test_settling_twice_or_after_the_sweep_changes_nothing(db):
    biz, brand, lia, campaign = with_hunter(db)
    with clocks(), Session(db) as s:
        hunter()._lock(s, A)
        conn = hunter().connection(s, A)
        charge, why = hunter().reserve(s, A, brand["id"], conn, "search", NOW)
        s.commit()
    with clocks(), Session(db) as s:
        assert hunter().sweep(s, NOW + timedelta(hours=2)) == 1
    with clocks(), Session(db) as s:
        hunter().settle(s, A, charge, (hunter()._number("0"), "credit"))       # late: ignored
        hunter().settle(s, A, charge, (hunter()._number("0"), "credit"))
    row = charges(db)[0]
    assert row["state"] == "charged" and float(row["brand_credits"]) == 1


def test_the_brand_cap_binds_and_half_a_credit_allows_a_verify_but_not_a_search(db):
    biz, brand, lia, campaign = with_hunter(db)
    with clocks(), Session(db) as s:
        hunter().configure_brand(s, biz, OWNER, brand["id"], {"cap_credits": "1.5"})
    with clocks(), Session(db) as s:
        hunter()._lock(s, A)
        conn = hunter().connection(s, A)
        assert hunter().reserve(s, A, brand["id"], conn, "search", NOW)[0]
        s.commit()
        hunter()._lock(s, A)
        assert hunter().reserve(s, A, brand["id"], conn, "search", NOW)[1] == \
            "This brand's Hunter credit cap for the month is reached"
        assert hunter().reserve(s, A, brand["id"], conn, "verify", NOW)[0]
        s.commit()
        hunter()._lock(s, A)
        assert hunter().reserve(s, A, brand["id"], conn, "verify", NOW)[0] is None


def test_the_account_s_balance_counts_outstanding_reservations(db):
    biz, brand, lia, campaign = with_hunter(db, available="1.5")
    with clocks(), Session(db) as s:
        hunter()._lock(s, A)
        conn = hunter().connection(s, A)
        assert hunter().reserve(s, A, brand["id"], conn, "search", NOW)[0]
        assert hunter().reserve(s, A, brand["id"], conn, "search", NOW)[1] == "Hunter's monthly credits are used"
        s.rollback()


def test_an_unknown_account_model_makes_no_call(db):
    biz, brand, lia, campaign = with_hunter(db)
    with Session(db) as s:
        s.execute(text("UPDATE outreach_provider_accounts SET pools = '{}'"))
        s.commit()
    fake = Hunter()
    fake.people["studio1.example"] = [found(jo(1))]
    hrun(db, biz, lia, World([[lead(1)]]), fake)
    assert fake.count("domain-search") == 0


# ------------------------------------------------------- the key and epoch ---

def test_connecting_checks_the_key_and_never_shows_it(db, caplog):
    biz, brand, lia, campaign = started(db)
    caplog.set_level(logging.DEBUG)
    with clocks(), Session(db) as s:
        out = hunter().connect(s, biz, OWNER, KEY, transport=Hunter())
    assert out["connected"] and out["last4"] == KEY[-4:] and out["plan"] == "Starter"
    assert out["pools"]["model"] == "single"
    with db.connect() as c:
        row = dict(c.execute(text("SELECT * FROM outreach_provider_accounts")).mappings().one())
        settings = c.execute(text("SELECT settings FROM business_settings WHERE business_id = :b"), {"b": A}).scalar()
    assert KEY not in json.dumps(row, default=str) and row["key_ciphertext"]
    assert KEY not in settings and "ciphertext" not in settings
    assert KEY not in json.dumps(out) and KEY not in caplog.text
    from app.email.crypto import decrypt_secret
    assert decrypt_secret(row["key_ciphertext"]) == KEY


def test_a_bad_key_is_refused_without_repeating_it(db):
    from services.aria_actions import ActionRefused
    biz, brand, lia, campaign = started(db)
    fake = Hunter()
    fake.fail["account"] = 401
    with clocks(), Session(db) as s, pytest.raises(ActionRefused) as exc:
        hunter().connect(s, biz, OWNER, KEY, transport=fake)
    assert KEY not in exc.value.detail and "didn't accept" in exc.value.detail
    with clocks(), Session(db) as s, pytest.raises(ActionRefused):
        hunter().connect(s, biz, OWNER, "short", transport=fake)
    assert count(db, "SELECT count(*) FROM outreach_provider_accounts") == 0


def test_without_an_encryption_key_nothing_is_stored(db, monkeypatch):
    from app.email import crypto
    from services.aria_actions import ActionRefused
    biz, brand, lia, campaign = started(db)
    monkeypatch.setattr(crypto, "_EMAIL_ENCRYPTION_KEY", None)
    with clocks(), Session(db) as s, pytest.raises(ActionRefused) as exc:
        hunter().connect(s, biz, OWNER, KEY, transport=Hunter())
    assert exc.value.status_code == 503
    assert count(db, "SELECT count(*) FROM outreach_provider_accounts") == 0


def test_only_the_owner_connects_or_disconnects(db):
    from fastapi import HTTPException
    from services.aria_actions import ActionRefused
    biz, brand, lia, campaign = started(db)
    for act in (lambda s: hunter().connect(s, biz, STAFF, KEY, transport=Hunter()),
                lambda s: hunter().disconnect(s, biz, STAFF)):
        with clocks(), Session(db) as s, pytest.raises((ActionRefused, HTTPException)):
            act(s)
    assert count(db, "SELECT count(*) FROM outreach_provider_accounts") == 0


def test_disconnect_leaves_a_tombstone_and_the_generation_never_repeats(db):
    biz, brand, lia, campaign = started(db)
    with clocks(), Session(db) as s:
        hunter().disconnect(s, biz, OWNER)                       # no row yet: a tombstone
    with clocks(), Session(db) as s:
        hunter().connect(s, biz, OWNER, KEY, transport=Hunter())
    with clocks(), Session(db) as s:
        hunter().disconnect(s, biz, OWNER)
    with clocks(), Session(db) as s:
        hunter().connect(s, biz, OWNER, KEY, transport=Hunter())
    with db.connect() as c:
        rows = c.execute(text("SELECT generation, status FROM outreach_provider_accounts")).fetchall()
    assert rows == [(4, "connected")]


def test_a_first_connect_finishing_after_a_disconnect_is_refused(db):
    from services.aria_actions import ActionRefused
    biz, brand, lia, campaign = started(db)
    fake = Hunter()

    def disconnect_meanwhile():
        with clocks(), Session(db) as s:
            hunter().disconnect(s, biz, OWNER)
    fake.during["account"] = disconnect_meanwhile
    with clocks(), Session(db) as s, pytest.raises(ActionRefused) as exc:
        hunter().connect(s, biz, OWNER, KEY, transport=fake)
    assert exc.value.status_code == 409
    with db.connect() as c:
        assert c.execute(text("SELECT status FROM outreach_provider_accounts")).fetchall() == [("disconnected",)]


def test_a_reconnect_finishing_after_a_disconnect_is_refused(db):
    from services.aria_actions import ActionRefused
    biz, brand, lia, campaign = with_hunter(db)
    fake = Hunter()

    def disconnect_meanwhile():
        with clocks(), Session(db) as s:
            hunter().disconnect(s, biz, OWNER)
    fake.during["account"] = disconnect_meanwhile
    with clocks(), Session(db) as s, pytest.raises(ActionRefused):
        hunter().connect(s, biz, OWNER, KEY, transport=fake)
    with db.connect() as c:
        assert c.execute(text("SELECT status FROM outreach_provider_accounts")).scalar() == "disconnected"


def test_disconnecting_mid_run_stores_nothing_hunter_found(db):
    """R3.1/R4.1: the run's generation is checked again under the store lock."""
    biz, brand, lia, campaign = with_hunter(db)
    fake = Hunter()
    fake.people["studio1.example"] = [found(jo(1), status="unknown")]

    def disconnect_and_reconnect():
        with Session(db) as s:            # a new connection: the generation moves on
            s.execute(text("UPDATE outreach_provider_accounts SET generation = generation + 2"))
            s.commit()
    fake.during["email-verifier"] = disconnect_and_reconnect
    out = hrun(db, biz, lia, World([[lead(1)]]), fake)
    assert out["accepted"] == [] and any("Hunter isn't connected" in r["reason"] for r in out["rejected"])


def test_status_never_shows_a_key_or_a_person(db):
    biz, brand, lia, campaign = with_hunter(db)
    fake = Hunter()
    fake.people["studio1.example"] = [found(jo(1))]
    hrun(db, biz, lia, World([[lead(1)]]), fake)
    with clocks(), Session(db) as s:
        shown = json.dumps(hunter().status(s, biz), default=str)
    assert KEY not in shown and "ciphertext" not in shown and jo(1) not in shown
    assert '"used_credits": "1' in shown


def test_the_key_goes_only_in_a_header_and_never_follows_a_redirect():
    import inspect
    source = inspect.getsource(hunter()._http)
    assert 'headers={"X-API-KEY": key}' in source and "follow_redirects=False" in source
    assert "api_key" not in source
    assert "KEY" not in repr(hunter().HunterError("key", 401))


# -------------------------------------------------------- the send path ---

def _hunter_contact(db):
    biz, brand, lia, campaign = with_hunter(db)
    fake = Hunter()
    fake.people["studio1.example"] = [found(jo(1))]
    out = hrun(db, biz, lia, World([[lead(1)]]), fake, drain=True)
    with db.connect() as c:
        prospect = dict(c.execute(text("SELECT * FROM outreach_prospects WHERE id = :p"),
                                  {"p": out["accepted"][0]}).mappings().one())
    return biz, brand, lia, prospect


def test_a_hunter_contact_s_first_email_needs_the_notice_unchanged(db):
    from services import outreach_setup
    biz, brand, lia, prospect = _hunter_contact(db)
    with clocks(), Session(db) as s:
        assert hunter().send_refused(s, A, prospect) is None
        outreach_setup.approve_privacy_notice(s, biz, OWNER, brand["id"], {"text": "A new notice."})
    with clocks(), Session(db) as s:
        assert hunter().send_refused(s, A, prospect) == hunter().NOTICE_CHANGED
        hunter().configure_brand(s, biz, OWNER, brand["id"], {"confirm_notice": True})
    with clocks(), Session(db) as s:
        assert hunter().send_refused(s, A, prospect) is None


def test_a_hunter_contact_needs_its_own_assessment_to_name_hunter(db):
    biz, brand, lia, prospect = _hunter_contact(db)
    with Session(db) as s:
        s.execute(text("UPDATE outreach_compliance SET sources = :s WHERE id = :l"),
                  {"s": json.dumps(["public_websites"]), "l": lia["id"]})
        s.commit()
    with clocks(), Session(db) as s:
        assert "doesn't cover Hunter" in hunter().send_refused(s, A, prospect)


def test_web_and_already_contacted_contacts_are_never_held_by_the_notice(db):
    from services import outreach_setup
    biz, brand, lia, prospect = _hunter_contact(db)
    with clocks(), Session(db) as s:
        outreach_setup.approve_privacy_notice(s, biz, OWNER, brand["id"], {"text": "A new notice."})
    with clocks(), Session(db) as s:
        assert hunter().send_refused(s, A, {**prospect, "notice_provided_at": NOW}) is None
        web = s.execute(text("SELECT * FROM outreach_prospects WHERE email <> :e"), {"e": jo(1)}).mappings().first()
        assert web is None or hunter().send_refused(s, A, dict(web)) is None


# The real send path (test_outreach_send's harness): its seeded contact made a Hunter contact.

from test_outreach_send import database, h  # noqa: E402,F401
import test_outreach_send as sendh  # noqa: E402


def _as_hunter_contact(h, *, confirmed=True):
    import hashlib
    sendh.add(h.s, "evidence", prospect_id=sendh.PROSPECT, source_type="hunter", operation="verify",
              source_url="https://example.invalid/people", fact_type="acquisition", fact_value="hunter", flags="[]",
              fetched_at=sendh.STAMP, expires_at=(sendh.NOW + timedelta(days=7)).isoformat())
    h.s.execute(text("UPDATE outreach_compliance SET sources = :s WHERE id = :l"),
                {"s": json.dumps(["public_websites", "hunter.io"]), "l": sendh.LIA})
    notice = "Synthetic notice naming Hunter.io."
    doc = {"outreach_privacy": {sendh.BRAND: {"version": 1, "text": notice}},
           "outreach_hunter": {"brands": {sendh.BRAND: {"enabled": True, "notice": {
               "by": sendh.OWNER, "hash": hashlib.sha256(notice.encode()).hexdigest() if confirmed else "old"}}}}}
    h.s.execute(text("DELETE FROM business_settings WHERE business_id = :b"), {"b": sendh.A})
    h.s.execute(text("INSERT INTO business_settings (business_id, settings) VALUES (:b, :s)"),
                {"b": sendh.A, "s": json.dumps(doc)})
    h.s.commit()


def _change_notice(h):
    doc = json.loads(h.s.execute(text("SELECT settings FROM business_settings")).scalar())
    doc["outreach_privacy"][sendh.BRAND]["text"] = "A changed notice."
    h.s.execute(text("UPDATE business_settings SET settings = :s"), {"s": json.dumps(doc)})
    h.s.commit()


def test_the_real_footer_names_hunter_from_the_acquisition_row(h):
    _as_hunter_contact(h)
    card = sendh.propose(h)
    assert "Source: https://example.invalid/people (found via Hunter.io, a business contact database)\n" \
        in card["preview"]["footer"]


def test_a_claim_is_refused_once_the_notice_changed(h):
    _as_hunter_contact(h)
    card = sendh.propose(h)
    _change_notice(h)
    with pytest.raises(h.a.ActionRefused, match="privacy notice changed"):
        sendh.approve(h, card)
    assert not h.p.sends


def test_a_notice_changed_between_claim_and_dispatch_takes_the_blocked_path(h):
    _as_hunter_contact(h)
    card = sendh.propose(h)
    sendh.claimed_only(h, card)
    _change_notice(h)
    result = h.m.dispatch(h.s, h.b, action_id=card["id"], payload=card["preview"])
    assert result["status"] == "failed" and result["outcome"] == "definitely_not_accepted"
    assert not h.p.sends
    assert h.s.execute(text("SELECT state FROM outreach_usage_events")).scalar() == "released"


def test_an_unconfirmed_brand_s_hunter_contact_gets_no_card_approved(h):
    _as_hunter_contact(h, confirmed=False)
    card = sendh.propose(h)
    with pytest.raises(h.a.ActionRefused, match="privacy notice changed"):
        sendh.approve(h, card)


def test_the_dispatch_gate_re_checks_the_notice_on_the_blocked_path():
    import inspect
    from services import outreach_send
    source = inspect.getsource(outreach_send.dispatch)
    gate = source.index("outreach_hunter.send_refused")
    assert source.index("try:") < gate < source.index("except ActionRefused:\n        blocked = True")
    assert "outreach_hunter.send_refused" in inspect.getsource(outreach_send.prepare_claim)


# ---------------------------------------------------- erasure and versions ---

def test_erasure_removes_a_hunter_contact_completely(db):
    from services import outreach_erasure
    biz, brand, lia, campaign = with_hunter(db)
    fake = Hunter()
    fake.people["studio1.example"] = [found(jo(1))]
    out = hrun(db, biz, lia, World([[lead(1)]]), fake)
    pid = out["accepted"][0]
    with clocks(), Session(db) as s:
        assert outreach_erasure.erase_never_contacted(s, A, pid, NOW + timedelta(days=29))["erased"] is True
    with db.connect() as c:
        for table in ("outreach_prospects", "outreach_evidence"):
            assert c.execute(text(f"SELECT count(*) FROM {table} WHERE business_id = :b"), {"b": A}).scalar() == 0
        left = json.dumps([dict(r) for r in c.execute(text("SELECT * FROM outreach_provider_charges")).mappings()]
                          + [dict(r) for r in c.execute(text("SELECT * FROM outreach_provider_accounts")).mappings()],
                          default=str)
    assert jo(1) not in left and "studio1" not in left


def test_research_runs_each_audience_once_on_its_latest_approval(db):
    from test_outreach_setup import _insert
    biz, brand, lia, campaign = with_hunter(db)
    newer = "33333333-3333-3333-3333-333333333333"
    with Session(db) as s:
        row = dict(s.execute(text("SELECT * FROM outreach_compliance WHERE id = :l"), {"l": lia["id"]}).mappings().one())
        _insert(s, "outreach_compliance", **{**row, "id": newer, "version": int(row["version"]) + 1})
        s.commit()
    ran = []
    with clocks(), Session(db) as s:
        research().run_due(s, moment=NOW, runner=lambda session, business, cid, **kw: ran.append(cid) or {})
    assert ran == [newer]


def test_an_audience_draft_keeps_its_sources_and_its_hash(db):
    from services import outreach_setup
    from test_outreach_setup import draft_lia
    biz, brand, lia, campaign = started(db)
    rules = {"brand_id": brand["id"], "description": "Independent gyms", "segments": ["gym"], "regions": ["Essex"]}
    seen = {}

    def drafting(context):
        seen.update(context)
        return draft_lia(context)
    with clocks(), Session(db) as s:
        plain = outreach_setup.draft_audience(s, biz, OWNER, dict(rules), draft=draft_lia)
        with_h = outreach_setup.draft_audience(s, biz, OWNER, {**rules, "sources": ["hunter.io"]}, draft=drafting)
    assert plain["audience_hash"] == with_h["audience_hash"]
    assert any("Hunter.io" in label for label in seen["sources"])
    with db.connect() as c:
        stored = json.loads(c.execute(text("SELECT sources FROM outreach_compliance WHERE id = :i"),
                                      {"i": with_h["id"]}).scalar())
    assert stored == ["public_websites", "hunter.io"]
    from services.aria_actions import ActionRefused
    with clocks(), Session(db) as s, pytest.raises(ActionRefused):
        outreach_setup.draft_audience(s, biz, OWNER, {**rules, "sources": ["apollo"]}, draft=draft_lia)


# --------------------------------------------------------------- deadline ---

def test_a_slow_site_stops_at_the_enrichment_deadline(db, monkeypatch):
    biz, brand, lia, campaign = with_hunter(db)
    clock = [0.0]
    monkeypatch.setattr(hunter().time, "monotonic", lambda: clock[0])
    world = World([[lead(i) for i in range(1, 6)]])
    real = world.fetch

    def slow(url):
        clock[0] += 100                        # each page takes 100 s
        return real(url)
    world.fetch = slow
    fake = Hunter()
    for i in range(1, 6):
        fake.people[f"studio{i}.example"] = [found(jo(i))]
    hrun(db, biz, lia, world, fake)
    assert fake.count("domain-search") <= 1


def test_the_hourly_pass_sweeps_hunter_reservations():
    import inspect
    from services import automations
    assert "outreach_hunter.sweep(session)" in inspect.getsource(automations.run_all_due)


def test_the_budget_stops_calls_at_the_deadline_and_the_call_limit():
    clock = [0.0]
    b = hunter().Budget(seconds=20, calls=3, clock=lambda: clock[0])
    assert b.take_call() and b.timeout() == hunter().CALL_TIMEOUT
    clock[0] = 10
    assert b.timeout() == 10 and b.take_call()
    clock[0] = 16                                  # 4 s left: under the minimum
    assert not b.ok() and not b.take_call()
    b2 = hunter().Budget(seconds=100, calls=1, clock=lambda: 0.0)
    assert b2.take_call() and not b2.take_call()


def test_only_a_reservation_older_than_an_hour_is_swept(db):
    biz, brand, lia, campaign = with_hunter(db)
    with clocks(), Session(db) as s:
        hunter()._lock(s, A)
        old = hunter().reserve(s, A, brand["id"], hunter().connection(s, A), "search", NOW)[0]
        fresh = hunter().reserve(s, A, brand["id"], hunter().connection(s, A), "verify", NOW)[0]
        s.execute(text("UPDATE outreach_provider_charges SET created_at = :t WHERE id = :i"),
                  {"t": NOW - timedelta(minutes=90), "i": old})
        s.commit()
    with clocks(), Session(db) as s:
        assert hunter().sweep(s, NOW) == 1
    states = {c["id"]: c["state"] for c in charges(db)}
    assert states == {old: "charged", fresh: "reserved"}


def test_without_migration_042_research_carries_on_with_the_web(db):
    biz, brand, lia, campaign = with_hunter(db)
    with Session(db) as s:
        s.execute(text("DROP TABLE outreach_provider_charges"))
        s.execute(text("DROP TABLE outreach_provider_accounts"))
        s.commit()
    out = hrun(db, biz, lia, World([[person(1)]]), Hunter())
    assert len(out["accepted"]) == 1


# ------------------------------------------------- the API never echoes the key ---

@pytest.fixture
def api(db, monkeypatch):
    import auth
    import db as dbmod
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import outreach_setup_api
    from rate_limiting import limiter
    biz, brand, lia, campaign = started(db)
    app = FastAPI()
    app.state.limiter = limiter
    app.include_router(outreach_setup_api.router)
    session = Session(db)
    app.dependency_overrides[auth.get_user_business_context] = lambda: {"business_id": A, "user_id": OWNER}
    app.dependency_overrides[dbmod.get_session] = lambda: session
    monkeypatch.setattr(auth, "_load_business", lambda s, bid: biz)
    monkeypatch.setattr(hunter(), "_http", Hunter())
    limiter.reset()
    with clocks(), TestClient(app) as client:
        yield client
    session.close()


@pytest.mark.parametrize("body", [
    {"key": KEY * 100},                  # too long
    {"key": 12345678901234567890123},    # not a string
    {"key": KEY, "extra": KEY},          # an extra field
    [KEY],                               # not an object
])
def test_a_malformed_connect_never_echoes_the_key(api, body):
    response = api.post("/v1/outreach/setup/hunter/connect", json=body)
    assert response.status_code == 422
    assert KEY not in response.text and "12345678901234567890123" not in response.text


def test_invalid_json_is_refused_without_echo(api):
    response = api.post("/v1/outreach/setup/hunter/connect", content=b'{"key": "' + KEY.encode() + b'"',
                        headers={"content-type": "application/json"})
    assert response.status_code == 422 and KEY not in response.text


def test_a_good_connect_through_the_api_shows_only_the_last_four(api):
    response = api.post("/v1/outreach/setup/hunter/connect", json={"key": KEY})
    assert response.status_code == 200, response.text
    assert response.json()["last4"] == KEY[-4:] and KEY not in response.text
    shown = api.get("/v1/outreach/setup/hunter")
    assert shown.status_code == 200 and KEY not in shown.text


# ------------------------------------------------ Codex code review 1 findings ---

def test_a_disconnect_mid_poll_stops_the_next_poll_before_it_is_made(db):
    biz, brand, lia, campaign = with_hunter(db)
    fake = Hunter()
    fake.people["studio1.example"] = [found(jo(1), status="unknown")]
    fake.pending[jo(1)] = 5

    def disconnect():
        with Session(db) as s:
            s.execute(text("UPDATE outreach_provider_accounts SET status = 'disconnected', generation = generation + 1"))
            s.commit()
    fake.during["email-verifier"] = disconnect
    out = hrun(db, biz, lia, World([[lead(1)]]), fake)
    assert out["accepted"] == [] and fake.count("email-verifier") == 1
    assert len([c for c in charges(db) if c["operation"] == "verify"]) == 1


def test_a_settled_call_never_frees_its_credit_in_the_cached_balance(db):
    biz, brand, lia, campaign = with_hunter(db, available="1")
    with clocks(), Session(db) as s:
        hunter()._lock(s, A)
        conn = hunter().connection(s, A)
        charge = hunter().reserve(s, A, brand["id"], conn, "search", NOW)[0]
        s.commit()
    with clocks(), Session(db) as s:
        hunter().settle(s, A, charge, (hunter()._number("1"), "credit"))
    with clocks(), Session(db) as s:
        hunter()._lock(s, A)
        assert hunter().reserve(s, A, brand["id"], conn, "search", NOW)[1] == "Hunter's monthly credits are used"
        s.rollback()
    # A fresh snapshot (taken after that call) already includes it: not counted twice.
    with Session(db) as s:
        s.execute(text("UPDATE outreach_provider_accounts SET account_fetched_at = :t, pools = :p"),
                  {"t": (NOW + timedelta(minutes=1)).isoformat(),
                   "p": json.dumps({"credit": {"used": "11", "available": "1"}, "model": "single"})})
        s.commit()
    with clocks(), Session(db) as s:
        hunter()._lock(s, A)
        assert hunter().reserve(s, A, brand["id"], conn, "search", NOW + timedelta(minutes=2))[0]
        s.rollback()


def test_a_mismatched_unit_refreshes_the_account(db):
    biz, brand, lia, campaign = with_hunter(db)
    fake = Hunter()

    def transport(method, path, params, key, timeout):
        status, body, headers = fake(method, path, params, key, timeout)
        if path == "domain-search":
            headers = {"X-Credits-Used": "1", "X-Credits-Unit": "search"}
        return status, body, headers
    hrun(db, biz, lia, World([[lead(1)]]), transport)
    assert fake.count("account") == 1


@pytest.mark.parametrize("reset,refreshed", [("2026-11-15", 0), (None, 1), ("2026-10-01", 1)])
def test_a_429_with_no_usable_reset_date_refreshes_the_account(db, reset, refreshed):
    biz, brand, lia, campaign = with_hunter(db)
    with Session(db) as s:
        pools = {"credit": {"used": "10", "available": "1990"}, "model": "single", "reset_date": reset}
        s.execute(text("UPDATE outreach_provider_accounts SET pools = :p"), {"p": json.dumps(pools)})
        s.commit()
    fake = Hunter()
    fake.fail["domain-search"] = 429
    hrun(db, biz, lia, World([[lead(1)]]), fake)
    assert fake.count("account") == refreshed


def test_one_domain_is_looked_up_once_across_a_run_s_attempts(db):
    biz, brand, lia, campaign = with_hunter(db)
    fake = Hunter()                                   # Hunter knows no one there: each attempt retries wider
    world = World([[lead(1)], [lead(1)], [lead(1)]])
    hrun(db, biz, lia, world, fake)
    assert len(world.briefs) == 3 and fake.count("domain-search") == 1


def test_a_run_searches_at_most_twice_its_room(db):
    from test_outreach_setup import _insert
    biz, brand, lia, campaign = with_hunter(db)
    with Session(db) as s:                            # 39 found today: one place left
        for i in range(39):
            pid = f"00000000-0000-0000-0000-{i:012d}"
            _insert(s, "outreach_prospects", id=pid, business_id=A, company=f"Old {i}", domain=f"old{i}.example",
                    email=f"a@old{i}.example", email_key=f"k{i}", eligibility="eligible", lia_id=lia["id"],
                    captured_at=NOW.isoformat(), created_at=NOW.isoformat(), updated_at=NOW.isoformat())
            _insert(s, "outreach_evidence", id=f"10000000-0000-0000-0000-{i:012d}", business_id=A, prospect_id=pid,
                    source_type="web", fact_type="contact_type", fact_value="decision_maker",
                    created_at=NOW.isoformat(), updated_at=NOW.isoformat())
        s.commit()
    fake = Hunter()                                   # no one usable anywhere
    hrun(db, biz, lia, World([[lead(i) for i in range(1, 8)]]), fake)
    assert fake.count("domain-search") == 2


def test_no_gatekeeper_is_fetched_or_verified_once_today_s_twenty_are_found(db, monkeypatch):
    biz, brand, lia, campaign = with_hunter(db)
    monkeypatch.setattr(research(), "_today_counts", lambda *a, **k: {"decision_maker": 5, "gatekeeper": 20})
    world = World([[lead(1)]])
    fetched = []
    real = world.fetch
    world.fetch = lambda url: fetched.append(url) or real(url)
    fake = Hunter()
    fake.people["studio1.example"] = [found(jo(1), position="Receptionist", status="unknown")]
    out = hrun(db, biz, lia, world, fake)
    assert out["accepted"] == [] and fake.count("email-verifier") == 0
    assert "https://studio1.example/team" not in fetched


def test_a_slowly_streamed_response_stops_at_the_deadline():
    import time as _time
    import httpx
    from services.outreach_research import get_json_within

    def slow():
        for _ in range(10):
            _time.sleep(0.15)
            yield b" "
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=slow()))
    # Enough time to start (it is not refused up front), too little to finish.
    with httpx.Client(transport=transport) as client, pytest.raises(TimeoutError):
        get_json_within(client, "https://api.example/x", end=_time.monotonic() + 0.8)


def test_every_network_step_is_bounded_by_the_run_s_deadline(monkeypatch):
    rs = research()
    clock = [0.0]
    budget = hunter().Budget(seconds=20, clock=lambda: clock[0])
    seen = {}
    monkeypatch.setattr(rs, "has_mail_server", lambda domain, lifetime=5.0: seen.update(mx=lifetime) or True)
    monkeypatch.setattr(rs, "companies_house", lambda q, end=None, clock=None: seen.update(ch=end) or None)
    clock[0] = 14                                   # 6 s left
    rs._bounded(rs.has_mail_server, budget)("x.example")
    rs._bounded(rs.companies_house, budget)("X Ltd")
    assert seen == {"mx": 5.0, "ch": budget.end} and seen["mx"] <= budget.left()
    clock[0] = 16.5
    assert rs._bounded(rs.has_mail_server, budget)("x.example") is None     # under the minimum: never started
