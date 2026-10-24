"""OUT-15 — outreach setup: the admin switch and the owner's setup wizard.

docs/OUT-15-TICKET.md. Tests first (RED: owner authority, the legal basis
for contact, a public privacy notice, mailbox health). Strict xfail may fail
only because `services.outreach_setup` does not exist yet.

Synthetic data only; DNS and Aria's drafting are injected, so no network and
no model call ever happens here.
"""

import hashlib
import importlib
import importlib.util
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlmodel import Session


class MissingSetup(AssertionError):
    """Only the intentional Stage 1 absence may be xfailed."""


pytestmark = pytest.mark.xfail(strict=True, raises=MissingSetup, reason="OUT-15 not built yet: tests first")


def uid(label):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "out15-test:" + label))


A, B = uid("A"), uid("B")
OWNER, STAFF, OTHER_OWNER, ADMIN = uid("owner"), uid("staff"), uid("other-owner"), uid("platform-admin")
WORKSPACE, WEBMAIL, FOREIGN = uid("workspace-box"), uid("webmail-box"), uid("foreign-box")
NOW = datetime(2026, 10, 26, 10, tzinfo=timezone.utc)


def setup_module_or_missing():
    if importlib.util.find_spec("services.outreach_setup") is None:
        raise MissingSetup("backend/services/outreach_setup.py does not exist yet")
    return importlib.import_module("services.outreach_setup")


def _insert(s, table, **values):
    s.execute(text(f"INSERT INTO {table} ({','.join(values)}) VALUES ({','.join(':' + k for k in values)})"), values)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTREACH_SUPPRESSION_SECRET", "synthetic-key-" * 4)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://app.example.invalid")
    engine = create_engine("sqlite:///" + str(tmp_path / "out15.sqlite"))
    migrations = Path(__file__).parents[1] / "migrations"
    with Session(engine) as s:
        for name in ("037_outreach_core.sql", "038_outreach_replies.sql"):
            sql = (migrations / name).read_text()
            for table, body in re.findall(r"CREATE TABLE IF NOT EXISTS public\.(outreach_\w+) \(\n(.*?)\n\);", sql, re.S):
                cols = []
                for line in body.splitlines():
                    m = re.match(r"  ([a-z_]+) (uuid|text\[\]|text|jsonb|integer|boolean|numeric|timestamptz|date)\b", line)
                    if m:
                        col, kind = m.groups()
                        cols.append(f"{col} {'NUMERIC' if kind in ('integer', 'boolean', 'numeric') else 'TEXT'}"
                                    + (" PRIMARY KEY" if col == "id" else ""))
                s.execute(text(f"CREATE TABLE {table} ({','.join(cols)})"))
        for ddl in (
            "CREATE TABLE businesses (id TEXT PRIMARY KEY, name TEXT, plan_tier TEXT, feature_flags TEXT, "
            "subscription_status TEXT, is_active BOOLEAN, trial_ends_at TIMESTAMP)",
            "CREATE TABLE business_settings (business_id TEXT PRIMARY KEY, settings TEXT, created_at TEXT, updated_at TEXT)",
            "CREATE TABLE business_members (id TEXT, business_id TEXT, user_id TEXT, role TEXT, is_active BOOLEAN)",
            "CREATE TABLE email_accounts (id TEXT PRIMARY KEY, business_id TEXT, user_id TEXT, provider TEXT, "
            "email_address TEXT, display_name TEXT, capabilities TEXT, is_default BOOLEAN, token_ciphertext TEXT, "
            "refresh_token_ciphertext TEXT, token_expires_at TEXT, smtp_config TEXT, created_at TEXT, updated_at TEXT)",
            "CREATE TABLE aria_actions (id TEXT PRIMARY KEY, business_id TEXT, action_type TEXT, payload TEXT, status TEXT)",
            "CREATE UNIQUE INDEX settings_once ON outreach_settings (business_id)",
            "CREATE UNIQUE INDEX brand_name_once ON outreach_brands (business_id, name)",
            "CREATE UNIQUE INDEX mailbox_once ON outreach_mailboxes (business_id, mailbox_id)",
        ):
            s.execute(text(ddl))
        for bid, plan in ((A, "pro"), (B, "business")):
            _insert(s, "businesses", id=bid, name=f"Biz {bid[:4]}", plan_tier=plan, feature_flags="{}",
                    subscription_status="active", is_active=True)
            _insert(s, "business_settings", business_id=bid, settings=json.dumps({"automations": {"keep": 1}}))
        _insert(s, "business_members", business_id=A, user_id=OWNER, role="owner", is_active=True)
        _insert(s, "business_members", business_id=A, user_id=STAFF, role="member", is_active=True)
        _insert(s, "business_members", business_id=B, user_id=OTHER_OWNER, role="owner", is_active=True)
        for box, bid, address, provider in ((WORKSPACE, A, "outreach@newbody.example", "google"),
                                            (WEBMAIL, A, "someone@gmail.com", "google"),
                                            (FOREIGN, B, "ops@msc.example", "microsoft")):
            _insert(s, "email_accounts", id=box, business_id=bid, user_id=OWNER, provider=provider,
                    email_address=address, is_default=False, capabilities="{}", token_ciphertext="fake",
                    created_at=NOW.isoformat())
        s.commit()
    yield engine
    engine.dispose()


def business(bid=A, plan=None, flags=None):
    return SimpleNamespace(id=bid, name="New Body Gym", plan_tier=plan or ("pro" if bid == A else "business"),
                           feature_flags=flags if flags is not None else {}, subscription_status="active",
                           is_active=True, trial_ends_at=None, timezone="Europe/London")


def grant(db, bid=A, flags=None):
    with db.begin() as c:
        c.execute(text("UPDATE businesses SET feature_flags = :f WHERE id = :b"),
                  {"f": json.dumps(flags if flags is not None else {"outreach": True}), "b": bid})
    return business(bid, flags=flags if flags is not None else {"outreach": True})


def dns(records):
    """A fake DNS: name -> list of TXT strings."""
    return lambda name: list(records.get(name.lower().rstrip("."), []))


GOOD_GOOGLE = {"newbody.example": ["v=spf1 include:_spf.google.com ~all"],
               "google._domainkey.newbody.example": ["v=DKIM1; k=rsa; p=MIIB"],
               "_dmarc.newbody.example": ["v=DMARC1; p=quarantine"]}


def draft_lia(context):
    assert "description" in context and "business" in context
    return {"purpose": "Offer gym placements to independent studios.",
            "necessity": "Direct contact is the only practical route.",
            "balancing_test": "Business addresses, relevant offer, easy opt-out.",
            "safeguards": "Opt-out in every email; suppression honoured."}


def draft_emails(context):
    return [{"subject": f"Step {i}", "body": f"Body {i}"} for i in range(3)]


def draft_notice(context):
    return "Who we are: New Body Gym. What data: your business email. How to opt out: reply STOP."


def ready(m, db, biz):
    """Walk the wizard to just before finish."""
    with Session(db) as s:
        m.begin(s, biz, OWNER)
        brand = m.save_brand(s, biz, OWNER, {"name": "New Body Gym", "sender_identity": "New Body Gym Ltd"})
        m.register_mailbox(s, biz, OWNER, {"mailbox_id": WORKSPACE, "daily_cap": 5})
        m.check_mailbox_health(s, biz, OWNER, WORKSPACE, resolve=dns(GOOD_GOOGLE))
        lia = m.draft_audience(s, biz, OWNER, {"brand_id": brand["id"], "description": "Independent gyms",
                                              "segments": ["gym"], "regions": ["Essex"]}, draft=draft_lia)
        m.approve_audience(s, biz, OWNER, lia["id"], {})
        m.approve_privacy_notice(s, biz, OWNER, brand["id"], {"text": draft_notice({})})
        campaign = m.create_first_campaign(s, biz, OWNER, {"name": "Autumn", "brand_id": brand["id"],
                                                           "mailbox_id": WORKSPACE, "compliance_id": lia["id"],
                                                           "daily_cap": 5}, draft=draft_emails)
    return brand, lia, campaign


# ------------------------------------------------------------- the switch ---

@pytest.mark.parametrize("plan,flags,allowed", [
    ("pro", {}, False), ("pro", {"outreach": True}, True), ("business", {}, True),
    ("business", {"outreach": False}, False), ("starter", {"outreach": True}, True),
])
def test_the_admin_switch_decides_who_may_set_up(db, plan, flags, allowed):
    m = setup_module_or_missing()
    with db.begin() as c:
        c.execute(text("UPDATE businesses SET plan_tier = :p, feature_flags = :f WHERE id = :b"),
                  {"p": plan, "f": json.dumps(flags), "b": A})
    with Session(db) as s:
        if allowed:
            assert m.begin(s, business(A, plan, flags), OWNER)["settings_id"]
        else:
            with pytest.raises(Exception) as exc:
                m.begin(s, business(A, plan, flags), OWNER)
            assert getattr(exc.value, "status_code", None) == 403


def test_the_switch_is_read_fresh_not_from_the_callers_copy(db):
    """Turning outreach off in the admin panel takes effect at once."""
    m = setup_module_or_missing()
    stale = grant(db)               # the caller still believes it is granted
    grant(db, flags={})             # the admin has switched it off
    with Session(db) as s, pytest.raises(Exception) as exc:
        m.begin(s, stale, OWNER)
    assert getattr(exc.value, "status_code", None) == 403


@pytest.mark.parametrize("who", [STAFF, ADMIN, OTHER_OWNER, None])
def test_only_an_active_owner_sets_up(db, who):
    m = setup_module_or_missing()
    biz = grant(db)
    with Session(db) as s:
        for call in (lambda: m.begin(s, biz, who),
                     lambda: m.save_brand(s, biz, who, {"name": "X", "sender_identity": "X Ltd"})):
            with pytest.raises(Exception) as exc:
                call()
            assert getattr(exc.value, "status_code", None) == 403
    with db.connect() as c:
        assert c.execute(text("SELECT count(*) FROM outreach_settings")).scalar() == 0
        assert c.execute(text("SELECT count(*) FROM outreach_brands")).scalar() == 0


# ------------------------------------------------------------- the steps ---

def test_begin_is_once_and_starts_paused(db):
    m = setup_module_or_missing()
    biz = grant(db)
    with Session(db) as s:
        first = m.begin(s, biz, OWNER)
        second = m.begin(s, biz, OWNER)
    assert first == second
    with db.connect() as c:
        row = c.execute(text("SELECT pause_all, retention_policy_version FROM outreach_settings")).one()
    assert bool(row[0]) is True and int(row[1]) == 1


def test_a_brand_gets_a_public_privacy_link(db):
    m = setup_module_or_missing()
    biz = grant(db)
    with Session(db) as s:
        m.begin(s, biz, OWNER)
        brand = m.save_brand(s, biz, OWNER, {"name": "New Body Gym", "sender_identity": "New Body Gym Ltd"})
        again = m.save_brand(s, biz, OWNER, {"name": "New Body Gym", "sender_identity": "New Body Gym Ltd"})
    assert brand["privacy_url"] == f"https://app.example.invalid/p/outreach-privacy/{brand['id']}"
    assert again["id"] == brand["id"], "the same brand name is the same brand"


def test_a_healthy_workspace_mailbox_is_enabled_at_warm_up_five(db):
    m = setup_module_or_missing()
    biz = grant(db)
    with Session(db) as s:
        m.begin(s, biz, OWNER)
        m.register_mailbox(s, biz, OWNER, {"mailbox_id": WORKSPACE, "daily_cap": 20})
        out = m.check_mailbox_health(s, biz, OWNER, WORKSPACE, resolve=dns(GOOD_GOOGLE))
    assert out["status"] == "pass"
    ev = out["evidence"]
    assert (ev["spf"], ev["dkim"], ev["dmarc"]) == ("pass", "pass", "pass")
    assert ev["domain_control"] is True and ev["from_aligned"] is True
    with db.connect() as c:
        enabled, stage, status = c.execute(text(
            "SELECT enabled, warmup_stage, health_status FROM outreach_mailboxes WHERE mailbox_id = :m"),
            {"m": WORKSPACE}).one()
    assert bool(enabled) and int(stage) == 5 and status == "pass"


@pytest.mark.parametrize("missing,word", [("_dmarc.newbody.example", "DMARC"),
                                          ("google._domainkey.newbody.example", "DKIM"),
                                          ("newbody.example", "SPF")])
def test_a_missing_record_fails_with_plain_advice_and_stays_disabled(db, missing, word):
    m = setup_module_or_missing()
    biz = grant(db)
    records = {k: v for k, v in GOOD_GOOGLE.items() if k != missing}
    with Session(db) as s:
        m.begin(s, biz, OWNER)
        m.register_mailbox(s, biz, OWNER, {"mailbox_id": WORKSPACE, "daily_cap": 5})
        out = m.check_mailbox_health(s, biz, OWNER, WORKSPACE, resolve=dns(records))
    assert out["status"] == "fail" and word in " ".join(out["advice"])
    with db.connect() as c:
        assert not bool(c.execute(text("SELECT enabled FROM outreach_mailboxes WHERE mailbox_id = :m"),
                                  {"m": WORKSPACE}).scalar())


def test_free_webmail_is_refused_for_outreach(db):
    """Decision B."""
    m = setup_module_or_missing()
    biz = grant(db)
    with Session(db) as s:
        m.begin(s, biz, OWNER)
        m.register_mailbox(s, biz, OWNER, {"mailbox_id": WEBMAIL, "daily_cap": 5})
        out = m.check_mailbox_health(s, biz, OWNER, WEBMAIL, resolve=dns({}))
    assert out["status"] == "fail" and any("business domain" in a for a in out["advice"])


def test_another_business_mailbox_cannot_be_registered(db):
    m = setup_module_or_missing()
    biz = grant(db)
    with Session(db) as s:
        m.begin(s, biz, OWNER)
        with pytest.raises(Exception) as exc:
            m.register_mailbox(s, biz, OWNER, {"mailbox_id": FOREIGN, "daily_cap": 5})
    assert getattr(exc.value, "status_code", None) == 404
    with db.connect() as c:
        assert c.execute(text("SELECT count(*) FROM outreach_mailboxes")).scalar() == 0


def test_aria_drafts_the_audience_and_only_the_owner_approves_it(db):
    m = setup_module_or_missing()
    biz = grant(db)
    rules = {"description": "Independent gyms", "segments": ["gym"], "regions": ["Essex"]}
    with Session(db) as s:
        m.begin(s, biz, OWNER)
        brand = m.save_brand(s, biz, OWNER, {"name": "New Body Gym", "sender_identity": "New Body Gym Ltd"})
        lia = m.draft_audience(s, biz, OWNER, {"brand_id": brand["id"], **rules}, draft=draft_lia)
        with db.connect() as c:
            assert c.execute(text("SELECT decision FROM outreach_compliance")).scalar() == "draft"
        with pytest.raises(Exception):
            m.approve_audience(s, biz, STAFF, lia["id"], {})
        out = m.approve_audience(s, biz, OWNER, lia["id"], {"purpose": "Edited purpose by the owner."})
    canonical = json.dumps(rules, sort_keys=True, separators=(",", ":"))
    assert out["audience_hash"] == hashlib.sha256(canonical.encode()).hexdigest()
    with db.connect() as c:
        decision, reviewer, purpose, due = c.execute(text(
            "SELECT decision, reviewer, purpose, review_due_at FROM outreach_compliance")).one()
    assert decision == "approved" and reviewer == OWNER and purpose == "Edited purpose by the owner."
    due_at = datetime.fromisoformat(str(due).replace(" ", "T").replace("Z", "+00:00"))
    due_at = due_at if due_at.tzinfo else due_at.replace(tzinfo=timezone.utc)
    assert timedelta(days=364) <= due_at - datetime.now(timezone.utc) <= timedelta(days=366), "12 months by default"


def test_the_privacy_notice_is_public_only_once_approved(db):
    m = setup_module_or_missing()
    biz = grant(db)
    with Session(db) as s:
        m.begin(s, biz, OWNER)
        brand = m.save_brand(s, biz, OWNER, {"name": "New Body Gym", "sender_identity": "New Body Gym Ltd"})
        assert m.public_privacy_notice(s, brand["id"]) is None
        out = m.approve_privacy_notice(s, biz, OWNER, brand["id"], {"text": "Our notice."})
        assert out["url"].endswith(brand["id"])
        assert m.public_privacy_notice(s, brand["id"]) == "Our notice."
        assert m.public_privacy_notice(s, uid("no-such-brand")) is None
    with db.connect() as c:
        stored = json.loads(c.execute(text("SELECT settings FROM business_settings WHERE business_id = :b"),
                                      {"b": A}).scalar())
    assert stored["automations"] == {"keep": 1}, "nothing else in the settings document changes"
    assert stored["outreach_privacy"][brand["id"]]["approved_by"] == OWNER


def test_the_generic_settings_save_keeps_the_privacy_notices(db):
    setup_module_or_missing()
    from main import preserve_automations
    existing = {"automations": {"x": 1}, "outreach_privacy": {"b": {"text": "kept"}}}
    out = preserve_automations({"theme": "dark", "outreach_privacy": {}}, existing)
    assert out["outreach_privacy"] == {"b": {"text": "kept"}} and out["theme"] == "dark"


def test_the_first_campaign_targets_exactly_the_approved_audience(db):
    m = setup_module_or_missing()
    biz = grant(db)
    brand, lia, campaign = ready(m, db, biz)
    with db.connect() as c:
        target = c.execute(text("SELECT target_hash, status, mailbox_id FROM outreach_campaigns")).one()
        audience = c.execute(text("SELECT audience_hash FROM outreach_compliance")).scalar()
        steps = c.execute(text("SELECT ordinal, approved_at FROM outreach_sequence_steps ORDER BY ordinal")).all()
    assert target[0] == audience and target[1] == "draft" and target[2] == WORKSPACE
    assert [int(r[0]) for r in steps] == [0, 1, 2] and all(r[1] is None for r in steps), \
        "Aria's drafts wait for the owner's template approval"


def test_a_campaign_needs_an_approved_audience_and_a_registered_mailbox(db):
    m = setup_module_or_missing()
    biz = grant(db)
    with Session(db) as s:
        m.begin(s, biz, OWNER)
        brand = m.save_brand(s, biz, OWNER, {"name": "New Body Gym", "sender_identity": "New Body Gym Ltd"})
        lia = m.draft_audience(s, biz, OWNER, {"brand_id": brand["id"], "description": "x", "segments": [],
                                              "regions": []}, draft=draft_lia)
        with pytest.raises(Exception):
            m.create_first_campaign(s, biz, OWNER, {"name": "A", "brand_id": brand["id"], "mailbox_id": WORKSPACE,
                                                    "compliance_id": lia["id"], "daily_cap": 5}, draft=draft_emails)
        m.approve_audience(s, biz, OWNER, lia["id"], {})
        with pytest.raises(Exception):   # approved audience, but the mailbox was never registered
            m.create_first_campaign(s, biz, OWNER, {"name": "A", "brand_id": brand["id"], "mailbox_id": WORKSPACE,
                                                    "compliance_id": lia["id"], "daily_cap": 5}, draft=draft_emails)
    with db.connect() as c:
        assert c.execute(text("SELECT count(*) FROM outreach_campaigns")).scalar() == 0


def test_status_walks_the_steps_and_finish_starts_outreach_without_sending(db):
    m = setup_module_or_missing()
    biz = grant(db)
    with Session(db) as s:
        assert m.status(s, biz)["complete"] is False
    brand, lia, campaign = ready(m, db, biz)
    with Session(db) as s:
        with pytest.raises(Exception):        # templates not approved yet
            m.finish(s, biz, OWNER)
        s.rollback()
        from services import outreach_manage
        c = s.execute(text("SELECT version, sequence_version FROM outreach_campaigns")).one()
        outreach_manage.approve_templates(s, biz, OWNER, campaign["id"],
                                          {"version": int(c[0]), "sequence_version": int(c[1])})
        state = m.status(s, biz)
        assert state["steps"]["knowledge"] in ("done", "todo") and state["complete"] is True
        m.finish(s, biz, OWNER)
    with db.connect() as c:
        assert not bool(c.execute(text("SELECT pause_all FROM outreach_settings")).scalar())
        assert c.execute(text("SELECT count(*) FROM aria_actions")).scalar() == 0, "finishing sends nothing"


def test_the_daily_recheck_pauses_a_mailbox_whose_records_disappear(db):
    """Decision C: OUT-6 needs a same-day health pass before any send."""
    m = setup_module_or_missing()
    biz = grant(db)
    ready(m, db, biz)
    broken = {k: v for k, v in GOOD_GOOGLE.items() if not k.startswith("_dmarc")}
    with Session(db) as s:
        result = m.recheck_health(s, resolve=dns(broken), moment=NOW + timedelta(days=1))
    assert result["failed"] == [WORKSPACE]
    with db.connect() as c:
        enabled, status, reason = c.execute(text(
            "SELECT enabled, health_status, pause_reason FROM outreach_mailboxes WHERE mailbox_id = :m"),
            {"m": WORKSPACE}).one()
    assert not bool(enabled) and status == "fail" and "DMARC" in reason


def test_setup_never_touches_another_business(db):
    m = setup_module_or_missing()
    biz = grant(db)
    ready(m, db, biz)
    with db.connect() as c:
        for table in ("outreach_settings", "outreach_brands", "outreach_mailboxes", "outreach_compliance",
                      "outreach_campaigns"):
            assert c.execute(text(f"SELECT count(*) FROM {table} WHERE business_id = :b"), {"b": B}).scalar() == 0
