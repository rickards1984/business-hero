"""OUT-20 — making outreach setup easy (Mike's click test, 25 Oct 2026).

1. Brand details (what you offer, who it's for, proof, tone, the ask) are saved,
   editable at any time, and given to Aria when she drafts the emails.
2. The owner works with Aria on the emails: notes in, a redraft out, nothing
   saved until the owner saves and approves it.
3. A failed mailbox check comes with a plain guide built from the domain's
   real records: who runs the DNS, the exact SPF value (added to the existing
   record, never replacing it), the signature-key steps for their mail
   provider, a ready-written email for their web person, and whether one-click
   connection is possible.
"""
# ruff: noqa: F811 - pytest fixtures imported from test_outreach_setup are parameters by design
import pytest
from sqlmodel import Session

from test_outreach_setup import (A, B, GOOD_GOOGLE, OTHER_OWNER, OWNER, STAFF, WORKSPACE, db, dns,  # noqa: F401
                                 draft_emails, grant, ready, setup_module_or_missing)

PROFILE = {"offer": "Free 12-week Level 3 fitness interns for your gym", "audience": "Independent gyms and health clubs",
           "proof": "120 interns placed since 2019; Ofsted-rated provider", "tone": "Friendly and direct",
           "ask": "A 15-minute call this week", "website": "https://newbodyhf.co.uk/fitfutures"}


def brand_row(state, brand_id):
    return next(b for b in state["brands"] if b["id"] == brand_id)


# ------------------------------------------------------------ brand details ---

def test_brand_details_are_saved_and_shown_in_status(db):
    m = setup_module_or_missing()
    biz = grant(db)
    with Session(db) as s:
        m.begin(s, biz, OWNER)
        brand = m.save_brand(s, biz, OWNER, {"name": "FitFutures", "sender_identity": "UKFI", "profile": PROFILE})
        assert brand_row(m.status(s, biz), brand["id"])["profile"] == PROFILE


def test_a_brand_can_be_edited_later_name_identity_and_details(db):
    m = setup_module_or_missing()
    biz = grant(db)
    with Session(db) as s:
        m.begin(s, biz, OWNER)
        brand = m.save_brand(s, biz, OWNER, {"name": "FitFutures", "sender_identity": "UKFI"})
        m.update_brand(s, biz, OWNER, brand["id"], {"name": "FitFutures by UKFI", "sender_identity": "UKFI Ltd",
                                                     "profile": {"offer": "Interns"}})
        row = brand_row(m.status(s, biz), brand["id"])
    assert (row["name"], row["sender_identity"], row["profile"]["offer"]) == ("FitFutures by UKFI", "UKFI Ltd", "Interns")


@pytest.mark.parametrize("who,code", [("staff", 403), ("other_business", 404)])
def test_only_the_owner_edits_only_their_own_brands(db, who, code):
    m = setup_module_or_missing()
    biz, other = grant(db), grant(db, bid=B)
    with Session(db) as s:
        m.begin(s, biz, OWNER)
        mine = m.save_brand(s, biz, OWNER, {"name": "FitFutures", "sender_identity": "UKFI"})
        m.begin(s, other, OTHER_OWNER)
        theirs = m.save_brand(s, other, OTHER_OWNER, {"name": "MSC", "sender_identity": "MSC Ltd"})
        with pytest.raises(Exception) as caught:
            if who == "staff":
                m.update_brand(s, biz, STAFF, mine["id"], {"name": "X"})
            else:
                m.update_brand(s, biz, OWNER, theirs["id"], {"name": "X"})
    assert getattr(caught.value, "status_code", None) == code


def test_a_brand_cannot_take_another_brands_name(db):
    m = setup_module_or_missing()
    biz = grant(db)
    with Session(db) as s:
        m.begin(s, biz, OWNER)
        m.save_brand(s, biz, OWNER, {"name": "New Body Gym", "sender_identity": "NB"})
        fit = m.save_brand(s, biz, OWNER, {"name": "FitFutures", "sender_identity": "UKFI"})
        with pytest.raises(Exception) as caught:
            m.update_brand(s, biz, OWNER, fit["id"], {"name": "New Body Gym"})
    assert getattr(caught.value, "status_code", None) == 409


def test_aria_drafts_the_emails_from_the_brand_details(db):
    m = setup_module_or_missing()
    biz = grant(db)
    seen = {}

    def capture(context):
        seen.update(context)
        return draft_emails(context)
    brand, lia, campaign = ready(m, db, biz)
    with Session(db) as s:
        m.update_brand(s, biz, OWNER, brand["id"], {"profile": PROFILE})
        m.create_first_campaign(s, biz, OWNER, {"name": "Second", "brand_id": brand["id"], "mailbox_id": WORKSPACE,
                                                "compliance_id": lia["id"], "daily_cap": 5}, draft=capture)
    assert seen["brand_details"] == PROFILE and seen["sender_identity"]


# --------------------------------------------------- working with Aria on copy ---

CURRENT = [{"subject": f"S{i}", "body": f"B{i}"} for i in range(3)]


def test_aria_redrafts_with_the_owners_notes_and_saves_nothing(db):
    from sqlalchemy import text
    m = setup_module_or_missing()
    biz = grant(db)
    brand, lia, campaign = ready(m, db, biz)
    seen = {}

    def redraft(context):
        seen.update(context)
        return [{"subject": f"New {i}", "body": f"Better {i}"} for i in range(3)]
    with db.connect() as c:
        before = c.execute(text("SELECT template_text FROM outreach_sequence_steps ORDER BY ordinal")).fetchall()
    with Session(db) as s:
        m.update_brand(s, biz, OWNER, brand["id"], {"profile": PROFILE})
        out = m.redraft_emails(s, biz, OWNER, campaign["id"], {"notes": "Mention the free trial week", "current": CURRENT},
                               draft=redraft)
    assert [e["subject"] for e in out["emails"]] == ["New 0", "New 1", "New 2"]
    assert seen["owner_notes"] == "Mention the free trial week" and seen["current_emails"] == CURRENT
    assert seen["brand_details"] == PROFILE and seen["audience"]
    with db.connect() as c:
        assert c.execute(text("SELECT template_text FROM outreach_sequence_steps ORDER BY ordinal")).fetchall() == before


@pytest.mark.parametrize("who,code", [("staff", 403), ("other_business", 404)])
def test_only_the_owner_redrafts_only_their_own_campaigns(db, who, code):
    m = setup_module_or_missing()
    biz, other = grant(db), grant(db, bid=B)
    brand, lia, campaign = ready(m, db, biz)
    with Session(db) as s:
        with pytest.raises(Exception) as caught:
            if who == "staff":
                m.redraft_emails(s, biz, STAFF, campaign["id"], {"notes": "x", "current": CURRENT},
                                 draft=lambda c: pytest.fail("drafted"))
            else:
                m.begin(s, other, OTHER_OWNER)
                m.redraft_emails(s, other, OTHER_OWNER, campaign["id"], {"notes": "x", "current": CURRENT},
                                 draft=lambda c: pytest.fail("drafted"))
    assert getattr(caught.value, "status_code", None) == code


def test_a_redraft_must_return_three_emails(db):
    m = setup_module_or_missing()
    biz = grant(db)
    brand, lia, campaign = ready(m, db, biz)
    with Session(db) as s:
        with pytest.raises(Exception) as caught:
            m.redraft_emails(s, biz, OWNER, campaign["id"], {"notes": "x", "current": CURRENT},
                             draft=lambda c: [{"subject": "only one", "body": "b"}])
    assert getattr(caught.value, "status_code", None) in (422, 503)


# ------------------------------------------------------ the DNS fix guide ---

NAMESCO = {"newbody.example": ["v=spf1 +a +mx include:spf.protection.outlook.com ~all"],
           "_dmarc.newbody.example": ["v=DMARC1; p=none;"]}


def ns(*servers):
    return lambda name, qtype: list(servers) if qtype == "NS" else []


def evaluate(records, other=ns()):
    m = setup_module_or_missing()
    account = {"email_address": "partners-ukfi@newbody.example", "provider": "google", "token_ciphertext": "x"}
    return m._evaluate(account, dns(records), other)


def test_the_guide_adds_google_to_the_existing_spf_record_never_replacing_it():
    guide = evaluate(NAMESCO)["guide"]
    spf = next(r for r in guide["records"] if r["what"] == "spf")
    assert spf["action"] == "edit" and spf["host"] == "@" and spf["type"] == "TXT"
    assert spf["value"] == "v=spf1 include:_spf.google.com +a +mx include:spf.protection.outlook.com ~all"
    assert spf["current"] == "v=spf1 +a +mx include:spf.protection.outlook.com ~all"


def test_with_no_spf_record_the_guide_adds_one():
    guide = evaluate({"_dmarc.newbody.example": ["v=DMARC1; p=none;"]})["guide"]
    spf = next(r for r in guide["records"] if r["what"] == "spf")
    assert spf["action"] == "add" and spf["value"] == "v=spf1 include:_spf.google.com ~all"


def test_two_spf_records_are_explained_as_needing_to_become_one():
    records = dict(NAMESCO, **{"newbody.example": ["v=spf1 include:a.example ~all", "v=spf1 include:b.example ~all"]})
    spf = next(r for r in evaluate(records)["guide"]["records"] if r["what"] == "spf")
    assert spf["action"] == "merge" and "only one" in spf["why"].lower()


def test_the_signature_key_steps_match_the_mail_provider():
    dkim = next(r for r in evaluate(NAMESCO)["guide"]["records"] if r["what"] == "dkim")
    assert dkim["host"] == "google._domainkey" and dkim["value"] is None
    assert any("Authenticate email" in step for step in dkim["steps"]) and "support.google.com" in dkim["help_url"]


def test_records_that_already_pass_are_left_out_of_the_guide():
    guide = evaluate(GOOD_GOOGLE)
    assert guide["status"] == "pass" and guide["guide"]["records"] == []


@pytest.mark.parametrize("servers,key,name", [
    (["ns0.phase8.net.", "ns1.phase8.net."], "namesco", "names.co.uk"),
    (["ns51.domaincontrol.com."], "godaddy", "GoDaddy"),
    (["kai.ns.cloudflare.com."], "cloudflare", "Cloudflare"),
    (["ns1047.ui-dns.co.uk."], "ionos", "IONOS"),
    (["ns.unknown-host.example."], "unknown", None),
])
def test_who_runs_the_domain_is_worked_out_from_its_nameservers(servers, key, name):
    host = evaluate(NAMESCO, ns(*servers))["guide"]["dns_host"]
    assert (host["key"], host["name"]) == (key, name)


def test_one_click_connection_is_offered_only_where_the_provider_supports_it_and_it_is_switched_on(monkeypatch):
    records = dict(NAMESCO, **{"_domainconnect.newbody.example": ["api.domainconnect.godaddy.com"]})
    monkeypatch.delenv("DOMAIN_CONNECT_ENABLED", raising=False)
    host = evaluate(records, ns("ns51.domaincontrol.com."))["guide"]["dns_host"]
    assert host["domain_connect"] == {"supported": True, "available": False}
    monkeypatch.setenv("DOMAIN_CONNECT_ENABLED", "1")
    host = evaluate(records, ns("ns51.domaincontrol.com."))["guide"]["dns_host"]
    assert host["domain_connect"] == {"supported": True, "available": True}
    assert evaluate(NAMESCO, ns("ns0.phase8.net."))["guide"]["dns_host"]["domain_connect"]["supported"] is False


def test_the_email_for_the_web_person_carries_every_value_and_the_domain():
    guide = evaluate(NAMESCO, ns("ns0.phase8.net."))["guide"]
    email = guide["email_to_helper"]
    assert "newbody.example" in email["subject"] + email["body"]
    assert "v=spf1 include:_spf.google.com +a +mx include:spf.protection.outlook.com ~all" in email["body"]
    assert "google._domainkey" in email["body"] and "names.co.uk" in email["body"]


def test_the_check_result_carries_the_guide(db):
    m = setup_module_or_missing()
    biz = grant(db)
    with Session(db) as s:
        m.begin(s, biz, OWNER)
        m.register_mailbox(s, biz, OWNER, {"mailbox_id": WORKSPACE, "daily_cap": 5})
        out = m.check_mailbox_health(s, biz, OWNER, WORKSPACE, resolve=dns({"newbody.example": ["v=spf1 ~all"]}))
    assert out["status"] == "fail" and out["guide"]["records"]


# ------------------------------------------------------ Codex OUT-20 review 1 ---

def failing_dns(records, fail):
    def resolve(name):
        name = name.lower().rstrip(".")
        if name in fail:
            raise TimeoutError("DNS timeout")
        return list(records.get(name, []))
    return resolve


def guide_for(resolve, other=ns()):
    m = setup_module_or_missing()
    account = {"email_address": "partners-ukfi@newbody.example", "provider": "google", "token_ciphertext": "x"}
    return m._evaluate(account, resolve, other)["guide"]


def test_a_failed_lookup_never_tells_anyone_to_add_a_record():
    """P1 1: a timeout cannot prove a record is missing."""
    guide = guide_for(failing_dns(NAMESCO, {"newbody.example", "_dmarc.newbody.example"}))
    spf = next(r for r in guide["records"] if r["what"] == "spf")
    dmarc = next(r for r in guide["records"] if r["what"] == "dmarc")
    assert (spf["action"], spf["value"]) == ("unknown", None) and (dmarc["action"], dmarc["value"]) == ("unknown", None)
    assert "v=spf1" not in guide["email_to_helper"]["body"]


def test_nameservers_are_read_by_the_production_resolver(monkeypatch):
    """P2 2: NS records through dns_other, not only injected."""
    import dns.resolver as resolver
    from types import SimpleNamespace
    m = setup_module_or_missing()
    monkeypatch.setattr(resolver, "resolve", lambda name, qtype, lifetime=5: [
        SimpleNamespace(target=SimpleNamespace(to_text=lambda omit=True: "ns0.phase8.net"))] if qtype == "NS" else [])
    assert m.dns_other("newbody.example", "NS") == ["ns0.phase8.net"]
    assert guide_for(dns(NAMESCO), m.dns_other)["dns_host"]["name"] == "names.co.uk"


@pytest.mark.parametrize("record,expected", [
    ("v=spf1 include:_spf.google.com.evil.test ~all",
     "v=spf1 include:_spf.google.com include:_spf.google.com.evil.test ~all"),
    ("v=spf1 -include:_spf.google.com ~all", "v=spf1 include:_spf.google.com ~all"),
    ("v=spf1 ~include:_spf.google.com mx ~all", "v=spf1 include:_spf.google.com mx ~all"),
])
def test_spf_mechanisms_are_matched_whole_and_a_failing_include_is_fixed(record, expected):
    """P2 3."""
    guide = guide_for(dns(dict(NAMESCO, **{"newbody.example": [record]})))
    assert next(r for r in guide["records"] if r["what"] == "spf")["value"] == expected


def test_the_email_for_two_spf_records_says_to_include_the_provider():
    records = dict(NAMESCO, **{"newbody.example": ["v=spf1 include:a.example ~all", "v=spf1 include:b.example ~all"]})
    assert "include:_spf.google.com" in guide_for(dns(records))["email_to_helper"]["body"]


def test_two_dmarc_records_are_merged_never_joined_by_a_third():
    """P2 4."""
    records = dict(NAMESCO, **{"_dmarc.newbody.example": ["v=DMARC1; p=none;", "v=DMARC1; p=reject;"]})
    dmarc = next(r for r in guide_for(dns(records))["records"] if r["what"] == "dmarc")
    assert dmarc["action"] == "merge" and dmarc["value"] is None


@pytest.mark.parametrize("record,expected", [
    ("V=dmarc1; p=quarantine; rua=mailto:dmarc@newbody.example",      # invalid (tag case) but a valid policy
     "v=DMARC1; p=quarantine; rua=mailto:dmarc@newbody.example"),
    ("v=DMARC1; p=sometimes", "v=DMARC1; p=none; rua=mailto:partners-ukfi@newbody.example"),
    ("v=DMARC1", "v=DMARC1; p=none; rua=mailto:partners-ukfi@newbody.example"),
])
def test_an_invalid_dmarc_record_is_repaired_keeping_a_valid_policy(record, expected):
    m = setup_module_or_missing()
    assert not m._usable_dmarc(record)
    guide = guide_for(dns(dict(NAMESCO, **{"_dmarc.newbody.example": [record]})))
    dmarc = next(r for r in guide["records"] if r["what"] == "dmarc")
    assert (dmarc["action"], dmarc["value"], dmarc["current"]) == ("edit", expected, record)


# ------------------------------------------------------ Codex OUT-20 review 2 ---

def test_an_include_stranded_after_all_is_moved_where_it_counts():
    guide = guide_for(dns(dict(NAMESCO, **{"newbody.example": ["v=spf1 -all include:_spf.google.com"]})))
    assert next(r for r in guide["records"] if r["what"] == "spf")["value"] == "v=spf1 include:_spf.google.com -all"


def test_repairing_dmarc_keeps_every_valid_setting():
    record = "V=DMARC1; p=none; sp=reject; rua=mailto:reports@newbody.example; adkim=s; aspf=s; pct=bogus"
    guide = guide_for(dns(dict(NAMESCO, **{"_dmarc.newbody.example": [record]})))
    dmarc = next(r for r in guide["records"] if r["what"] == "dmarc")
    assert dmarc["value"] == "v=DMARC1; p=none; sp=reject; rua=mailto:reports@newbody.example; adkim=s; aspf=s"
