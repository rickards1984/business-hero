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


# Stage 1's strict-xfail marker was removed once the implementation landed.


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
            "CREATE TABLE aria_actions (id TEXT PRIMARY KEY, business_id TEXT, action_type TEXT, payload TEXT, status TEXT, "
            "error TEXT, updated_at TEXT)",
            "CREATE TABLE usage_meters (business_id TEXT, meter TEXT, period TEXT, value NUMERIC, updated_at TEXT, "
            "UNIQUE (business_id, meter, period))",
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


def dns(records, *, failing=()):
    """A fake DNS: name -> list of TXT strings. A name in `failing` raises,
    as a resolver timeout does."""
    def resolve(name):
        name = name.lower().rstrip(".")
        if name in failing:
            raise TimeoutError(f"DNS timeout for {name}")
        return list(records.get(name, []))
    return resolve


def _real_dkim_key() -> str:
    """A genuine 2048-bit RSA public key, as DKIM publishes it."""
    import base64
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key()
    der = key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return base64.b64encode(der).decode()


REAL_DKIM = _real_dkim_key()

# Google's real SPF chain, in miniature: an include whose netblocks hold the
# representative Google sending address the check tests (209.85.220.41).
GOOGLE_SPF_CHAIN = {"_spf.google.com": ["v=spf1 include:_netblocks.google.com ~all"],
                    "_netblocks.google.com": ["v=spf1 ip4:209.85.128.0/17 ~all"]}

GOOD_GOOGLE = {**GOOGLE_SPF_CHAIN, "newbody.example": ["v=spf1 include:_spf.google.com ~all"],
               "google._domainkey.newbody.example": ["v=DKIM1; k=rsa; p=" + REAL_DKIM + ""],
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


# ------------------------------------- changing the sending mailbox (Mike) ---

NEW_BOX = uid("new-workspace-box")


def second_mailbox(db, healthy=True):
    with db.begin() as c:
        c.execute(text("INSERT INTO email_accounts (id, business_id, user_id, provider, email_address, is_default, "
                       "capabilities, token_ciphertext, created_at) VALUES (:id, :b, :u, 'google', "
                       "'hello@newbody-studio.example', 0, '{}', 'fake', :t)"),
                  {"id": NEW_BOX, "b": A, "u": OWNER, "t": NOW.isoformat()})
    records = {**GOOGLE_SPF_CHAIN, "newbody-studio.example": ["v=spf1 include:_spf.google.com ~all"],
               "google._domainkey.newbody-studio.example": ["v=DKIM1; p=" + REAL_DKIM + ""]}
    if healthy:
        records["_dmarc.newbody-studio.example"] = ["v=DMARC1; p=none"]
    return records


def sent_from(db, campaign_id, mailbox):
    """Dispatch history on a campaign: an accepted outbound message."""
    with db.begin() as c:
        c.execute(text("INSERT INTO outreach_messages (id, business_id, campaign_id, mailbox_id, prospect_id, "
                       "direction, state, origin, kind) VALUES (:id, :b, :c, :m, :p, 'outbound', 'accepted', "
                       "'live', 'initial')"),
                  {"id": str(uuid.uuid4()), "b": A, "c": campaign_id, "m": mailbox, "p": uid("prospect")})
        c.execute(text("INSERT INTO outreach_enrolments (id, business_id, campaign_id, prospect_id, state, "
                       "next_step, sequence_version) VALUES (:id, :b, :c, :p, 'active', 1, 1)"),
                  {"id": uid("enrolment"), "b": A, "c": campaign_id, "p": uid("prospect")})


def test_switching_moves_the_brand_and_unsent_campaigns_at_once(db):
    m = setup_module_or_missing()
    biz = grant(db)
    brand, lia, campaign = ready(m, db, biz)
    records = second_mailbox(db)
    with db.begin() as c:
        c.execute(text("UPDATE outreach_brands SET default_mailbox_id = :m"), {"m": WORKSPACE})
        c.execute(text("INSERT INTO aria_actions (id, business_id, action_type, payload, status) VALUES "
                       "('card-1', :b, 'send_outreach', :p, 'proposed')"),
                  {"b": A, "p": json.dumps({"mailbox_id": WORKSPACE, "campaign_id": campaign["id"]})})
    with Session(db) as s:
        m.register_mailbox(s, biz, OWNER, {"mailbox_id": NEW_BOX, "daily_cap": 5})
        m.check_mailbox_health(s, biz, OWNER, NEW_BOX, resolve=dns(records))
        out = m.replace_mailbox(s, biz, OWNER, {"old_mailbox_id": WORKSPACE, "new_mailbox_id": NEW_BOX,
                                                "reason": "Rebrand", "retire_old": False})
    assert out["switched"] == [campaign["id"]] and out["kept_on_old"] == [] and out["dismissed_cards"] == ["card-1"]
    with db.connect() as c:
        assert c.execute(text("SELECT mailbox_id FROM outreach_campaigns")).scalar() == NEW_BOX
        assert c.execute(text("SELECT default_mailbox_id FROM outreach_brands")).scalar() == NEW_BOX
        assert c.execute(text("SELECT status FROM aria_actions WHERE id = 'card-1'")).scalar() == "dismissed"


def test_switching_to_an_unhealthy_mailbox_changes_nothing(db):
    m = setup_module_or_missing()
    biz = grant(db)
    brand, lia, campaign = ready(m, db, biz)
    records = second_mailbox(db, healthy=False)
    with Session(db) as s:
        m.register_mailbox(s, biz, OWNER, {"mailbox_id": NEW_BOX, "daily_cap": 5})
        m.check_mailbox_health(s, biz, OWNER, NEW_BOX, resolve=dns(records))
        with pytest.raises(Exception) as exc:
            m.replace_mailbox(s, biz, OWNER, {"old_mailbox_id": WORKSPACE, "new_mailbox_id": NEW_BOX,
                                              "reason": "Rebrand", "retire_old": True})
    assert getattr(exc.value, "status_code", None) == 409
    with db.connect() as c:
        assert c.execute(text("SELECT mailbox_id FROM outreach_campaigns")).scalar() == WORKSPACE
        assert bool(c.execute(text("SELECT enabled FROM outreach_mailboxes WHERE mailbox_id = :m"),
                              {"m": WORKSPACE}).scalar())


def test_a_campaign_with_threads_stays_unless_the_old_mailbox_is_retired(db):
    m = setup_module_or_missing()
    biz = grant(db)
    brand, lia, campaign = ready(m, db, biz)
    sent_from(db, campaign["id"], WORKSPACE)
    records = second_mailbox(db)
    with Session(db) as s:
        m.register_mailbox(s, biz, OWNER, {"mailbox_id": NEW_BOX, "daily_cap": 5})
        m.check_mailbox_health(s, biz, OWNER, NEW_BOX, resolve=dns(records))
        kept = m.replace_mailbox(s, biz, OWNER, {"old_mailbox_id": WORKSPACE, "new_mailbox_id": NEW_BOX,
                                                 "reason": "Second brand", "retire_old": False})
    assert kept["kept_on_old"] == [campaign["id"]] and kept["switched"] == [] and kept["paused_enrolments"] == 0
    with Session(db) as s:
        retired = m.replace_mailbox(s, biz, OWNER, {"old_mailbox_id": WORKSPACE, "new_mailbox_id": NEW_BOX,
                                                    "reason": "Reputation dropped", "retire_old": True})
    assert retired["paused_enrolments"] == 1
    with db.connect() as c:
        enabled, reason = c.execute(text("SELECT enabled, pause_reason FROM outreach_mailboxes WHERE mailbox_id = :m"),
                                    {"m": WORKSPACE}).one()
        state, stop = c.execute(text("SELECT state, stop_reason FROM outreach_enrolments")).one()
        still_connected = c.execute(text("SELECT count(*) FROM email_accounts WHERE id = :m"), {"m": WORKSPACE}).scalar()
    assert not bool(enabled) and "Reputation dropped" in reason
    assert state == "paused" and stop == "sending mailbox retired"
    assert still_connected == 1, "replies to the old inbox are still read"


def test_a_campaign_can_be_copied_onto_the_new_mailbox(db):
    m = setup_module_or_missing()
    biz = grant(db)
    brand, lia, campaign = ready(m, db, biz)
    records = second_mailbox(db)
    with Session(db) as s:
        m.register_mailbox(s, biz, OWNER, {"mailbox_id": NEW_BOX, "daily_cap": 5})
        m.check_mailbox_health(s, biz, OWNER, NEW_BOX, resolve=dns(records))
        copy = m.copy_campaign_to_mailbox(s, biz, OWNER, campaign["id"], {"mailbox_id": NEW_BOX})
    with db.connect() as c:
        rows = {r[0]: r[1:] for r in c.execute(text(
            "SELECT id, mailbox_id, target_hash, brand_id, status FROM outreach_campaigns"))}
        steps = c.execute(text("SELECT count(*), sum(CASE WHEN approved_at IS NULL THEN 1 ELSE 0 END) "
                               "FROM outreach_sequence_steps WHERE campaign_id = :c"), {"c": copy["id"]}).one()
    assert rows[copy["id"]][0] == NEW_BOX and rows[copy["id"]][1:3] == rows[campaign["id"]][1:3]
    assert rows[copy["id"]][3] == "draft" and tuple(int(x) for x in steps) == (3, 3), "one tap re-approves"


@pytest.mark.parametrize("who", [STAFF, OTHER_OWNER])
def test_only_the_owner_changes_the_sending_mailbox(db, who):
    m = setup_module_or_missing()
    biz = grant(db)
    ready(m, db, biz)
    with Session(db) as s, pytest.raises(Exception) as exc:
        m.replace_mailbox(s, biz, who, {"old_mailbox_id": WORKSPACE, "new_mailbox_id": WORKSPACE,
                                        "reason": "x", "retire_old": True})
    assert getattr(exc.value, "status_code", None) == 403


def test_the_daily_check_runs_once_from_seven_on_weekdays(db, monkeypatch):
    """Decision C, wired to the hourly scheduler pass: any pass from 07:00 UK
    on a weekday rechecks mailboxes not yet checked that UK day; no more."""
    m = setup_module_or_missing()
    biz = grant(db)
    ready(m, db, biz)
    calls = []
    resolve = dns(GOOD_GOOGLE)

    def counting(name):
        calls.append(name)
        return resolve(name)
    tue = datetime(2026, 10, 27, 6, 59, tzinfo=timezone.utc)        # 06:59 UK (GMT)
    with Session(db) as s:
        assert m.daily_health(s, resolve=counting, moment=tue)["checked"] == []
        assert m.daily_health(s, resolve=counting, moment=tue + timedelta(minutes=31))["checked"] == [WORKSPACE]
        assert m.daily_health(s, resolve=counting, moment=tue + timedelta(hours=3))["checked"] == []
        sat = datetime(2026, 10, 31, 9, tzinfo=timezone.utc)
        assert m.daily_health(s, resolve=counting, moment=sat)["checked"] == []


def test_the_hourly_autopilot_pass_runs_the_daily_check():
    setup_module_or_missing()
    import inspect
    from services import automations
    assert "daily_health" in inspect.getsource(automations.run_all_due)


# ------------------------------------------- Codex OUT-15 review 1 (P1s) ---

@pytest.mark.parametrize("records,word", [
    ({**GOOD_GOOGLE, "google._domainkey.newbody.example": ["v=DKIM1; k=rsa; p="]}, "DKIM"),      # revoked key
    ({**GOOD_GOOGLE, "google._domainkey.newbody.example": ["v=DKIM1; p=!!notbase64!!"]}, "DKIM"),
    ({**GOOD_GOOGLE, "newbody.example": ["v=spf1 include:_spf.google.com ~all",
                                         "v=spf1 include:other.example ~all"]}, "SPF"),      # two SPF = permerror
    ({**GOOD_GOOGLE, "newbody.example": ["v=spf1 include:_spf.google.com.evil.example ~all"]}, "SPF"),
    ({**GOOD_GOOGLE, "_dmarc.newbody.example": ["v=DMARC1"]}, "DMARC"),                       # no policy
    ({**GOOD_GOOGLE, "_dmarc.newbody.example": ["v=DMARC1; p=bogus"]}, "DMARC"),
])
def test_only_genuinely_usable_records_pass(db, records, word):
    """P1 4: loose string matching passed unusable records."""
    m = setup_module_or_missing()
    biz = grant(db)
    with Session(db) as s:
        m.begin(s, biz, OWNER)
        m.register_mailbox(s, biz, OWNER, {"mailbox_id": WORKSPACE, "daily_cap": 5})
        out = m.check_mailbox_health(s, biz, OWNER, WORKSPACE, resolve=dns(records))
    assert out["status"] == "fail" and word in " ".join(out["advice"])
    with db.connect() as c:
        assert not bool(c.execute(text("SELECT enabled FROM outreach_mailboxes")).scalar())


@pytest.mark.parametrize("hold", ["Complaint received: paused", "Hard bounces: 3 of the last 50", "Retired by owner: x"])
def test_a_dns_pass_never_lifts_a_safety_hold(db, hold):
    """P1 3: only a DNS-caused pause may be lifted by a DNS pass."""
    m = setup_module_or_missing()
    biz = grant(db)
    ready(m, db, biz)
    with db.begin() as c:
        c.execute(text("UPDATE outreach_mailboxes SET enabled = 0, pause_reason = :r WHERE mailbox_id = :m"),
                  {"r": hold, "m": WORKSPACE})
    with Session(db) as s:
        m.check_mailbox_health(s, biz, OWNER, WORKSPACE, resolve=dns(GOOD_GOOGLE))
        m.recheck_health(s, resolve=dns(GOOD_GOOGLE), moment=NOW + timedelta(days=1))
    with db.connect() as c:
        enabled, reason = c.execute(text("SELECT enabled, pause_reason FROM outreach_mailboxes WHERE mailbox_id = :m"),
                                    {"m": WORKSPACE}).one()
    assert not bool(enabled) and reason == hold


def test_a_dns_caused_pause_is_lifted_by_a_later_pass(db):
    m = setup_module_or_missing()
    biz = grant(db)
    ready(m, db, biz)
    broken = {k: v for k, v in GOOD_GOOGLE.items() if not k.startswith("_dmarc")}
    with Session(db) as s:
        m.recheck_health(s, resolve=dns(broken), moment=NOW + timedelta(days=1))
        m.check_mailbox_health(s, biz, OWNER, WORKSPACE, resolve=dns(GOOD_GOOGLE))
    with db.connect() as c:
        assert bool(c.execute(text("SELECT enabled FROM outreach_mailboxes WHERE mailbox_id = :m"),
                              {"m": WORKSPACE}).scalar())


def test_the_daily_check_never_overwrites_a_retirement_made_during_its_lookups(db):
    """P1 2: the owner retires the mailbox while DNS is being looked up."""
    m = setup_module_or_missing()
    biz = grant(db)
    ready(m, db, biz)
    calls = {"n": 0}

    def slow(name):
        calls["n"] += 1
        if calls["n"] == 1:   # mid-lookup, from another session
            with db.begin() as c:
                c.execute(text("UPDATE outreach_mailboxes SET enabled = 0, pause_reason = 'Retired by owner: rebrand' "
                               "WHERE mailbox_id = :m"), {"m": WORKSPACE})
        return GOOD_GOOGLE.get(name, [])
    with Session(db) as s:
        m.recheck_health(s, resolve=slow, moment=NOW + timedelta(days=1))
    with db.connect() as c:
        enabled, reason = c.execute(text("SELECT enabled, pause_reason FROM outreach_mailboxes WHERE mailbox_id = :m"),
                                    {"m": WORKSPACE}).one()
    assert not bool(enabled) and reason.startswith("Retired")


def test_setup_stays_on_screen_until_outreach_is_started(db):
    """P1 1: the wizard must not vanish at `complete` before Start outreach."""
    m = setup_module_or_missing()
    biz = grant(db)
    brand, lia, campaign = ready(m, db, biz)
    with Session(db) as s:
        from services import outreach_manage
        c = s.execute(text("SELECT version, sequence_version FROM outreach_campaigns")).one()
        outreach_manage.approve_templates(s, biz, OWNER, campaign["id"], {"version": int(c[0]), "sequence_version": int(c[1])})
        state = m.status(s, biz)
        assert state["complete"] is True and state["started"] is False
        m.finish(s, biz, OWNER)
        assert m.status(s, biz)["started"] is True


# ------------------------------------------- Codex OUT-15 review 2 (P1s) ---

@pytest.mark.parametrize("records,word", [
    ({**GOOD_GOOGLE, "google._domainkey.newbody.example": ["v=DKIM1; k=rsa; p=" + "A" * 64]}, "DKIM"),   # not a key
    ({**GOOD_GOOGLE, "newbody.example": ["v=spf1 -all include:_spf.google.com"]}, "SPF"),               # all first
    ({**GOOD_GOOGLE, "newbody.example": ["v=spf1 -include:_spf.google.com ~all"]}, "SPF"),               # fail-qualified
    ({**GOOD_GOOGLE, "_dmarc.newbody.example": ["v=DMARC1; p=reject", "v=DMARC1; p=none"]}, "DMARC"),   # two records
])
def test_records_are_read_for_meaning_not_just_shape(db, records, word):
    m = setup_module_or_missing()
    biz = grant(db)
    with Session(db) as s:
        m.begin(s, biz, OWNER)
        m.register_mailbox(s, biz, OWNER, {"mailbox_id": WORKSPACE, "daily_cap": 5})
        out = m.check_mailbox_health(s, biz, OWNER, WORKSPACE, resolve=dns(records))
    assert out["status"] == "fail" and word in " ".join(out["advice"])


def test_pausing_after_setup_never_brings_the_wizard_back(db):
    """Review 2 P1: setup finished is its own fact, not the pause switch."""
    m = setup_module_or_missing()
    biz = grant(db)
    brand, lia, campaign = ready(m, db, biz)
    with Session(db) as s:
        from services import outreach_manage
        c = s.execute(text("SELECT version, sequence_version FROM outreach_campaigns")).one()
        outreach_manage.approve_templates(s, biz, OWNER, campaign["id"], {"version": int(c[0]), "sequence_version": int(c[1])})
        m.finish(s, biz, OWNER)
        outreach_manage.settings(s, biz, OWNER, {"pause_all": True})
        state = m.status(s, biz)
    assert state["started"] is True, "paused is still set up"


# ------------------------------------------- Codex OUT-15 review 3 (P1s) ---
# The records are evaluated by their rules, not checked against examples:
# SPF left to right with qualifiers (first match wins), DKIM's v/k/t/s tags,
# DMARC's exact first tag.

def _health(db, records):
    m = setup_module_or_missing()
    biz = grant(db)
    with Session(db) as s:
        m.begin(s, biz, OWNER)
        m.register_mailbox(s, biz, OWNER, {"mailbox_id": WORKSPACE, "daily_cap": 5})
        return m.check_mailbox_health(s, biz, OWNER, WORKSPACE, resolve=dns(records))["status"]


DKIM_NAME, SPF_NAME, DMARC_NAME = "google._domainkey.newbody.example", "newbody.example", "_dmarc.newbody.example"


@pytest.mark.parametrize("spf,expected", [
    ("v=spf1 include:_spf.google.com ~all", "pass"),
    ("v=spf1 include:_spf.google.com -all", "pass"),
    ("v=spf1 +include:_spf.google.com ~all", "pass"),
    ("v=spf1 ip4:192.0.2.1 include:_spf.google.com ~all", "pass"),
    ("v=spf1 -include:_spf.google.com include:_spf.google.com ~all", "fail"),   # first match rejects
    ("v=spf1 ~include:_spf.google.com ~all", "fail"),
    ("v=spf1 ?include:_spf.google.com ~all", "fail"),
    ("v=spf1 ~all include:_spf.google.com", "fail"),
    ("v=spf1 redirect=_spf.other.example", "fail"),
    ("v=spf10 include:_spf.google.com ~all", "fail"),
])
def test_spf_is_evaluated_left_to_right_with_qualifiers(db, spf, expected):
    assert _health(db, {**GOOD_GOOGLE, SPF_NAME: [spf]}) == expected


@pytest.mark.parametrize("dkim,expected", [
    ("v=DKIM1; k=rsa; p={key}", "pass"),
    ("k=rsa; p={key}", "pass"),
    ("v=DKIM1; p={key}", "pass"),
    ("v=DKIM1; k=invalid; p={key}", "fail"),
    ("v=DKIM2; k=rsa; p={key}", "fail"),
    ("v=DKIM1; k=rsa; t=y; p={key}", "fail"),        # testing mode: verifiers treat mail as unsigned
    ("v=DKIM1; k=rsa; s=other; p={key}", "fail"),     # not for email
    ("v=DKIM1; k=rsa; s=email; p={key}", "pass"),
])
def test_dkim_tags_are_respected(db, dkim, expected):
    assert _health(db, {**GOOD_GOOGLE, DKIM_NAME: [dkim.format(key=REAL_DKIM)]}) == expected


@pytest.mark.parametrize("dmarc,expected", [
    ("v=DMARC1; p=none; rua=mailto:x@newbody.example", "pass"),
    ("v=DMARC1;p=quarantine", "pass"),
    ("v=DMARC1invalid; p=reject", "fail"),
    ("p=reject; v=DMARC1", "fail"),                    # v must be the first tag
    ("v=DMARC1; sp=reject", "fail"),                   # no p
])
def test_dmarc_must_start_with_its_exact_version_and_carry_a_policy(db, dmarc, expected):
    assert _health(db, {**GOOD_GOOGLE, DMARC_NAME: [dmarc]}) == expected


def test_a_dns_glitch_after_setup_recovers_by_itself_next_day(db):
    """Review 3 P1: a DNS-paused mailbox stays in the daily check, so
    repaired records re-enable it; safety holds still never lift."""
    m = setup_module_or_missing()
    biz = grant(db)
    ready(m, db, biz)
    broken = {k: v for k, v in GOOD_GOOGLE.items() if not k.startswith("_dmarc")}
    with Session(db) as s:
        m.recheck_health(s, resolve=dns(broken), moment=NOW + timedelta(days=1))
        assert m.daily_health(s, resolve=dns(GOOD_GOOGLE),
                              moment=datetime(2026, 10, 28, 8, tzinfo=timezone.utc))["checked"] == [WORKSPACE]
    with db.connect() as c:
        enabled, reason = c.execute(text("SELECT enabled, pause_reason FROM outreach_mailboxes WHERE mailbox_id = :m"),
                                    {"m": WORKSPACE}).one()
    assert bool(enabled) and reason is None


def test_mailboxes_can_be_added_and_checked_after_setup(db):
    """Review 3 P1: registration and Check again stay available once
    outreach has started, so a replacement can be prepared."""
    m = setup_module_or_missing()
    biz = grant(db)
    brand, lia, campaign = ready(m, db, biz)
    with Session(db) as s:
        from services import outreach_manage
        c = s.execute(text("SELECT version, sequence_version FROM outreach_campaigns")).one()
        outreach_manage.approve_templates(s, biz, OWNER, campaign["id"], {"version": int(c[0]), "sequence_version": int(c[1])})
        m.finish(s, biz, OWNER)
    records = second_mailbox(db)
    with Session(db) as s:
        m.register_mailbox(s, biz, OWNER, {"mailbox_id": NEW_BOX, "daily_cap": 5})
        assert m.check_mailbox_health(s, biz, OWNER, NEW_BOX, resolve=dns(records))["status"] == "pass"
        out = m.replace_mailbox(s, biz, OWNER, {"old_mailbox_id": WORKSPACE, "new_mailbox_id": NEW_BOX,
                                                "reason": "Rebrand", "retire_old": False})
    assert out["switched"] == [campaign["id"]]


def test_the_settings_screen_offers_mailbox_checks_and_campaign_copy():
    setup_module_or_missing()
    from pathlib import Path as _P
    page = (_P(__file__).parents[2] / "frontend/client/src/pages/OutreachPage.tsx").read_text()
    assert "OutreachMailboxes" in page and "CopyCampaign" in page


# ------------------------------------------- Codex OUT-15 review 4 (P1) ---
# Mike, 24 Oct 2026: use the established RFC 7208 implementation (pyspf) and
# test the real question — would this domain's SPF authorise a real Google
# sending address?

@pytest.mark.parametrize("spf", [
    "v=spf1 -ip4:0.0.0.0/0 include:_spf.google.com ~all",    # every IPv4 sender rejected first
    "v=spf1 foo:bar include:_spf.google.com ~all",           # unknown mechanism: permanent error
    "v=spf1 include:broken.example include:_spf.google.com ~all",   # earlier include times out
])
def test_spf_follows_the_standard_through_includes_and_errors(db, spf):
    m = setup_module_or_missing()
    biz = grant(db)
    with Session(db) as s:
        m.begin(s, biz, OWNER)
        m.register_mailbox(s, biz, OWNER, {"mailbox_id": WORKSPACE, "daily_cap": 5})
        out = m.check_mailbox_health(s, biz, OWNER, WORKSPACE,
                                     resolve=dns({**GOOD_GOOGLE, SPF_NAME: [spf]}, failing={"broken.example"}))
    assert out["status"] == "fail" and "SPF" in " ".join(out["advice"])


def test_spf_must_actually_authorise_the_provider_not_just_name_it(db):
    """An include of the provider whose chain does not cover its senders fails."""
    records = {**GOOD_GOOGLE, "_netblocks.google.com": ["v=spf1 ip4:192.0.2.0/24 ~all"]}
    assert _health(db, records) == "fail"


def test_dkim_tag_names_are_case_sensitive(db):
    assert _health(db, {**GOOD_GOOGLE, DKIM_NAME: ["v=DKIM1; k=rsa; P=" + REAL_DKIM]}) == "fail"


def test_checking_again_keeps_the_owners_daily_cap(db):
    """Review 4 backlog: a recheck never resets an owner-chosen limit."""
    m = setup_module_or_missing()
    biz = grant(db)
    with Session(db) as s:
        m.begin(s, biz, OWNER)
        m.register_mailbox(s, biz, OWNER, {"mailbox_id": WORKSPACE, "daily_cap": 12})
        m.register_mailbox(s, biz, OWNER, {"mailbox_id": WORKSPACE})
    with db.connect() as c:
        assert int(c.execute(text("SELECT daily_cap FROM outreach_mailboxes")).scalar()) == 12


def test_a_held_mailbox_is_reported_as_held_not_ready(db):
    """Review 4 backlog: valid DNS on a held mailbox must not read as Ready."""
    m = setup_module_or_missing()
    biz = grant(db)
    ready(m, db, biz)
    with db.begin() as c:
        c.execute(text("UPDATE outreach_mailboxes SET enabled = 0, pause_reason = 'Complaint received: paused'"))
    with Session(db) as s:
        out = m.check_mailbox_health(s, biz, OWNER, WORKSPACE, resolve=dns(GOOD_GOOGLE))
    assert out["status"] == "pass" and out["enabled"] is False and out["hold"] == "Complaint received: paused"


# ------------------------------------------- Codex OUT-15 review 5 (P1) ---

def test_pyspfs_own_safeguards_stay_in_force(db):
    """Overriding the lookup must not bypass pyspf's void-lookup limit
    (RFC 7208 4.6.4: more than two empty lookups is a permanent error)."""
    spf = ("v=spf1 exists:missing1.example exists:missing2.example exists:missing3.example "
           "include:_spf.google.com ~all")
    assert _health(db, {**GOOD_GOOGLE, SPF_NAME: [spf]}) == "fail"


def test_a_failed_check_again_still_recovers_by_itself(db):
    """Review 5 backlog: a manual check during an outage marks a DNS pause, so
    the daily check re-enables the mailbox once records are back."""
    m = setup_module_or_missing()
    biz = grant(db)
    ready(m, db, biz)
    broken = {k: v for k, v in GOOD_GOOGLE.items() if not k.startswith("_dmarc")}
    with Session(db) as s:
        m.check_mailbox_health(s, biz, OWNER, WORKSPACE, resolve=dns(broken))
        m.daily_health(s, resolve=dns(GOOD_GOOGLE), moment=datetime(2026, 10, 28, 8, tzinfo=timezone.utc))
    with db.connect() as c:
        assert bool(c.execute(text("SELECT enabled FROM outreach_mailboxes WHERE mailbox_id = :m"),
                              {"m": WORKSPACE}).scalar())
