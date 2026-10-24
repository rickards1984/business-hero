"""OUT-15 — the setup wizard on real PostgreSQL (035–038 replayed locally):
037/038's CHECKs, JSONB shapes and foreign keys accept what the wizard
writes, and changing the sending mailbox holds together. Synthetic rows only;
DNS and Aria's drafting are injected; nothing is sent."""
# ruff: noqa: F811 - pytest fixtures imported from test_outreach_send_rls are parameters by design

import json
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlmodel import Session

from test_outreach_send_rls import DATABASE_URL, pg  # noqa: F401 - the fixture is used by name
from test_outreach_send import B, OWNER

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="RLS_LOCAL_DATABASE_URL is not set")

BOX_ONE, BOX_TWO = str(uuid.uuid4()), str(uuid.uuid4())
RECORDS = {}
for domain in ("setup-one.example", "setup-two.example"):
    RECORDS[domain] = ["v=spf1 include:_spf.google.com ~all"]
    RECORDS[f"google._domainkey.{domain}"] = ["v=DKIM1; p=MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqIDAQAB"]
    RECORDS[f"_dmarc.{domain}"] = ["v=DMARC1; p=none"]


def resolve(name):
    return RECORDS.get(name, [])


@pytest.fixture
def biz(pg, monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://app.example.invalid")
    with pg.engine.begin() as c:
        c.execute(text("INSERT INTO public.business_members (business_id, user_id, role, is_active) "
                       "VALUES (:b, :u, 'owner', true)"), {"b": B, "u": OWNER})
        for box, address in ((BOX_ONE, "outreach@setup-one.example"), (BOX_TWO, "hello@setup-two.example")):
            c.execute(text("INSERT INTO public.email_accounts (id, business_id, user_id, provider, email_address, "
                           "is_default, token_ciphertext) VALUES (:id, :b, :u, 'google', :e, false, 'fake')"),
                      {"id": box, "b": B, "u": OWNER, "e": address})
    return SimpleNamespace(id=B, name="Setup Biz", plan_tier="business", feature_flags={},
                           subscription_status="active", is_active=True, trial_ends_at=None, timezone="Europe/London")


def test_the_whole_wizard_and_a_mailbox_change_on_postgres(pg, biz):
    from services import outreach_manage, outreach_setup as m
    with Session(pg.engine) as s:
        m.begin(s, biz, OWNER)
        brand = m.save_brand(s, biz, OWNER, {"name": "Setup Brand", "sender_identity": "Setup Brand Ltd"})
        for box in (BOX_ONE, BOX_TWO):
            m.register_mailbox(s, biz, OWNER, {"mailbox_id": box, "daily_cap": 5})
            assert m.check_mailbox_health(s, biz, OWNER, box, resolve=resolve)["status"] == "pass"
        lia = m.draft_audience(s, biz, OWNER, {"brand_id": brand["id"], "description": "Independent gyms",
                                              "segments": ["gym"], "regions": ["Essex"]},
                               draft=lambda ctx: {k: f"{k} text" for k in
                                                  ("purpose", "necessity", "balancing_test", "safeguards")})
        m.approve_audience(s, biz, OWNER, lia["id"], {})
        m.approve_privacy_notice(s, biz, OWNER, brand["id"], {"text": "Our notice."})
        campaign = m.create_first_campaign(
            s, biz, OWNER, {"name": "Autumn", "brand_id": brand["id"], "mailbox_id": BOX_ONE,
                            "compliance_id": lia["id"], "daily_cap": 5},
            draft=lambda ctx: [{"subject": f"S{i}", "body": f"B{i}"} for i in range(3)])
        row = s.execute(text("SELECT version, sequence_version FROM outreach_campaigns WHERE id = :c"),
                        {"c": campaign["id"]}).one()
        outreach_manage.approve_templates(s, biz, OWNER, campaign["id"],
                                          {"version": row[0], "sequence_version": row[1]})
        assert m.status(s, biz)["complete"] is True
        m.finish(s, biz, OWNER)
        assert m.public_privacy_notice(s, brand["id"]) == "Our notice."
        out = m.replace_mailbox(s, biz, OWNER, {"old_mailbox_id": BOX_ONE, "new_mailbox_id": BOX_TWO,
                                                "reason": "Rebrand", "retire_old": True})
        copy = m.copy_campaign_to_mailbox(s, biz, OWNER, campaign["id"], {"mailbox_id": BOX_TWO})
    assert out["switched"] == [campaign["id"]]
    with pg.engine.connect() as c:
        assert c.execute(text("SELECT pause_all FROM outreach_settings WHERE business_id = :b"), {"b": B}).scalar() is False
        hashes = c.execute(text("SELECT DISTINCT target_hash FROM outreach_campaigns WHERE business_id = :b"),
                           {"b": B}).scalars().all()
        assert hashes == [c.execute(text("SELECT audience_hash FROM outreach_compliance WHERE business_id = :b"),
                                    {"b": B}).scalar()]
        evidence = c.execute(text("SELECT health_evidence FROM outreach_mailboxes WHERE mailbox_id = :m"),
                             {"m": BOX_TWO}).scalar()
        assert evidence["spf"] == "pass" and isinstance(evidence, dict)
        enabled, reason = c.execute(text("SELECT enabled, pause_reason FROM outreach_mailboxes WHERE mailbox_id = :m"),
                                    {"m": BOX_ONE}).one()
        assert enabled is False and "Rebrand" in reason
        doc = c.execute(text("SELECT settings FROM business_settings WHERE business_id = :b"), {"b": B}).scalar()
        doc = doc if isinstance(doc, dict) else json.loads(doc)
        assert brand["id"] in doc["outreach_privacy"]
        assert c.execute(text("SELECT count(*) FROM outreach_sequence_steps WHERE campaign_id = :c"),
                         {"c": copy["id"]}).scalar() == 3
