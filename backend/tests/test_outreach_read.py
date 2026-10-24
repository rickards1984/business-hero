"""OUT-4 Stage A: proposed read contract; no implementation or external IO.

SQLite mirrors the 037 columns used by these projections, not its Postgres
constraints/RLS (OUT-3 owns those). test_auto_chase.py is absent on this branch;
the GateSession pattern follows test_aria_actions.py. Only the precise absence
of outreach_read may xfail; import/dependency/assertion errors must stay red.
"""

import importlib
import importlib.util
import json
import os
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

for _key in ("SUPABASE_DATABASE_URL", "DATABASE_URL"):
    if os.getenv(_key) and not os.environ[_key].startswith("sqlite"):
        raise RuntimeError("REFUSING TO RUN: non-SQLite database configured")

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event, text  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import Session  # noqa: E402


class MissingOutreachRead(AssertionError):
    """The sole intentional Stage A failure."""


A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
EMPTY = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
STAMP = NOW.isoformat()
SECRET = "NEVER_EXPOSE_SECRET_SENTINEL"


def uid(bid, kind, index=0):
    return str(uuid5(NAMESPACE_URL, f"out4/{bid}/{kind}/{index}"))


def implementation():
    if importlib.util.find_spec("outreach_read") is None:
        raise MissingOutreachRead("backend/outreach_read.py does not exist")
    return importlib.import_module("outreach_read")


# (path, tool name, path argument, source table, exact item allowlist)
SURFACES = [
    ("brands", "list_outreach_brands", None, "brands", "id name privacy_url sender_identity version"),
    ("prospects", "list_outreach_prospects", None, "prospects", "id company name role domain stage eligibility subscriber_type fit_score confidence evidence_checked_at"),
    ("prospects/{prospect_id}", "get_outreach_prospect", "prospect_id", "prospects", "id company name role domain stage eligibility subscriber_type fit_score confidence evidence_checked_at"),
    ("prospects/{prospect_id}/evidence", "get_outreach_evidence", "prospect_id", "evidence", "id prospect_id source_type source_url excerpt fact_type fact_value confidence fetched_at expires_at"),
    ("prospects/{prospect_id}/timeline", "get_outreach_prospect_timeline", "prospect_id", "messages", "id prospect_id campaign_id mailbox_id kind origin direction state accepted_at created_at"),
    ("campaigns", "list_outreach_campaigns", None, "campaigns", "id brand_id mailbox_id name sequence_version version status timezone daily_cap"),
    ("campaigns/{campaign_id}", "get_outreach_campaign", "campaign_id", "campaigns", "id brand_id mailbox_id name sequence_version version status timezone daily_cap"),
    ("campaigns/{campaign_id}/sequence", "get_outreach_sequence", "campaign_id", "sequence_steps", "id campaign_id sequence_version ordinal delay_business_days approved_at approved_by subject body"),
    ("replies", "list_outreach_replies", None, "replies", "id prospect_id mailbox_id inbound_email_id matched_message_id owner_id category confidence resolution received_at"),
    ("replies/{reply_id}", "get_outreach_reply", "reply_id", "replies", "id prospect_id mailbox_id inbound_email_id matched_message_id owner_id category confidence resolution received_at subject body_text from_email original_received_at original_status original_message enrolments enrolments_total"),
    ("suppressions", "list_outreach_suppressions", None, "suppressions", "id key_type reason suppressed_at review_at prospect_id"),
    ("mailboxes", "list_outreach_mailboxes", None, "mailboxes", "id mailbox_id enabled daily_cap warmup_stage sending_days health_status health_checked_at"),
    ("compliance", "get_outreach_compliance_status", None, "compliance", "id brand_id version decision reviewed_at review_due_at"),
    ("settings", "get_outreach_settings_and_permissions", None, "settings", "id pause_all timezone business_daily_cap owner_cc_default owner_cc_address retention_policy_version"),
    ("summary", "outreach_summary", None, None, ""),
    ("knowledge", "get_outreach_knowledge", None, "knowledge", "id brand_id topic answer source_reference version status approved_at review_due_at retired_at"),
    ("reply-slots", "list_outreach_reply_slots", None, "reply_slots", "id prospect_id reply_id mailbox_id action_id state generation reserved_at dispatched_at settled_at released_at"),
]
DETAILS = {"get_outreach_reply", "get_outreach_prospect", "get_outreach_campaign", "get_outreach_settings_and_permissions"}
LISTS = [s for s in SURFACES if s[1] not in DETAILS and s[1] != "outreach_summary"]
WITH_PARENT = [s for s in SURFACES if s[2]]

# Only 037 columns needed by the reads, plus sensitive columns to catch SELECT *.
COLUMNS = {
    "enrolments": "prospect_id TEXT, campaign_id TEXT, state TEXT, takeover_at TEXT, stop_reason TEXT",
    "knowledge": "brand_id TEXT, topic TEXT, answer TEXT, source_reference TEXT, version INTEGER, status TEXT, approved_at TEXT, review_due_at TEXT, retired_at TEXT",
    "reply_slots": "prospect_id TEXT, reply_id TEXT, mailbox_id TEXT, action_id TEXT, state TEXT, generation INTEGER, reserved_at TEXT, dispatched_at TEXT, settled_at TEXT, released_at TEXT, outcome_evidence TEXT, payload_hash TEXT",
    "brands": "name TEXT, default_mailbox_id TEXT, privacy_url TEXT, sender_identity TEXT, version INTEGER",
    "prospects": "company TEXT, name TEXT, role TEXT, domain TEXT, number TEXT, email TEXT, email_key TEXT, subscriber_type TEXT, eligibility TEXT, lawful_basis TEXT, lia_id TEXT, stage TEXT, fit_score NUMERIC, confidence NUMERIC, why_now TEXT, evidence_checked_at TEXT, captured_at TEXT, first_contact_at TEXT, last_contact_at TEXT, notice_due_at TEXT, notice_provided_at TEXT, retention_due_at TEXT, owner_user_id TEXT",
    "evidence": "prospect_id TEXT, source_type TEXT, operation TEXT, source_url TEXT, excerpt TEXT, fact_type TEXT, fact_value TEXT, provider_record_id TEXT, confidence NUMERIC, scale TEXT, verification_status TEXT, verification_subject_email_key TEXT, raw_verdict TEXT, flags TEXT, fetched_at TEXT, verified_at TEXT, expires_at TEXT, adapter_version TEXT, model_config_version TEXT",
    "campaigns": "brand_id TEXT, mailbox_id TEXT, name TEXT, target_rules TEXT, target_hash TEXT, sequence_version INTEGER, version INTEGER, status TEXT, timezone TEXT, daily_cap INTEGER, first_batch_review_id TEXT",
    "sequence_steps": "campaign_id TEXT, sequence_version INTEGER, ordinal INTEGER, delay_business_days INTEGER, template_text TEXT, template_hash TEXT, allowed_variables TEXT, approved_by TEXT, approved_at TEXT",
    "messages": "prospect_id TEXT, campaign_id TEXT, enrolment_id TEXT, step_id TEXT, sequence_version INTEGER, mailbox_id TEXT, batch_review_id TEXT, action_id TEXT, outbox_id TEXT, kind TEXT, origin TEXT, direction TEXT, to_emails TEXT, cc_emails TEXT, subject TEXT, body TEXT, payload_hash TEXT, payload_version INTEGER, state TEXT, provider TEXT, provider_message_id TEXT, provider_thread_id TEXT, rfc_message_id TEXT, reply_target_id TEXT, accepted_at TEXT, idempotency_key TEXT, retry_of TEXT, authority_snapshot TEXT",
    "replies": "prospect_id TEXT, mailbox_id TEXT, inbound_email_id TEXT, matched_message_id TEXT, category TEXT, confidence NUMERIC, classification_version INTEGER, knowledge_refs TEXT, suggested_body TEXT, owner_id TEXT, resolution TEXT, received_at TEXT",
    "mailboxes": "mailbox_id TEXT, enabled BOOLEAN, pause_reason TEXT, daily_cap INTEGER, warmup_stage INTEGER, sending_days INTEGER, health_status TEXT, health_checked_at TEXT, health_evidence TEXT, health_reviewed_by TEXT, health_reviewed_at TEXT",
    "compliance": "brand_id TEXT, audience_hash TEXT, version INTEGER, purpose TEXT, necessity TEXT, balancing_test TEXT, safeguards TEXT, sources TEXT, decision TEXT, reviewer TEXT, reviewed_at TEXT, review_due_at TEXT",
    "settings": "pause_all BOOLEAN, timezone TEXT, business_daily_cap INTEGER, owner_cc_default BOOLEAN, owner_cc_address TEXT, retention_policy_version INTEGER",
    "suppressions": "key_type TEXT, key_digest TEXT, digest_version INTEGER, reason TEXT, source_ref TEXT, suppressed_at TEXT, review_at TEXT",
    "unsubscribe_tokens": "token_digest TEXT, prospect_key_digest TEXT, digest_version INTEGER, issued_at TEXT, revoked_at TEXT",
}


def add(conn, table, bid, index=0, **values):
    row = dict(id=uid(bid, table, index), business_id=bid,
               created_at=STAMP, updated_at=STAMP, **values)
    conn.execute(text(f"INSERT INTO outreach_{table} ({','.join(row)}) "
                      f"VALUES ({','.join(':' + key for key in row)})"), row)
    return row["id"]


@pytest.fixture
def database():
    eng = create_engine("sqlite://", poolclass=StaticPool,
                        connect_args={"check_same_thread": False})
    with eng.begin() as conn:
        for table, columns in COLUMNS.items():
            conn.execute(text(f"CREATE TABLE outreach_{table} (id TEXT PRIMARY KEY, "
                              "business_id TEXT NOT NULL, created_at TEXT, updated_at TEXT, "
                              f"{columns})"))
        conn.execute(text("CREATE TABLE email_accounts (id TEXT PRIMARY KEY, business_id TEXT, "
                          "token_ciphertext TEXT, refresh_token_ciphertext TEXT, smtp_config TEXT)"))
        conn.execute(text("CREATE TABLE email_messages (id TEXT PRIMARY KEY, business_id TEXT, email_account_id TEXT, subject TEXT, body_text TEXT, from_email TEXT, received_at TEXT)"))
        for bid in (A, B):
            mailbox = uid(bid, "account")
            conn.execute(text("INSERT INTO email_accounts VALUES (:id,:bid,:s,:s,:s)"),
                         dict(id=mailbox, bid=bid, s=SECRET))
            brand = add(conn, "brands", bid, name=f"Brand {bid}", privacy_url="https://example.test/privacy",
                        sender_identity="Example Ltd", version=1, default_mailbox_id=mailbox)
            prospect = add(conn, "prospects", bid, company=f"Company {bid}", name="Synthetic Person",
                           role="Director", domain="example.test", stage="new", eligibility="blocked",
                           subscriber_type="unknown", email="private@example.test", email_key=SECRET,
                           fit_score=94, confidence=94, captured_at=STAMP,
                           retention_due_at="2027-10-20T12:00:00+00:00")
            add(conn, "knowledge", bid, brand_id=brand, topic="availability", answer="Weekday appointments",
                source_reference="https://example.test/facts", version=2, status="approved", approved_at=STAMP,
                review_due_at="2027-10-20T12:00:00+00:00")
            add(conn, "reply_slots", bid, prospect_id=prospect, reply_id=uid(bid, "replies"),
                mailbox_id=mailbox, action_id=uid(bid, "action"), state="unknown", generation=2,
                reserved_at=STAMP, dispatched_at=STAMP, outcome_evidence=SECRET, payload_hash=SECRET)
            campaign = add(conn, "campaigns", bid, brand_id=brand, mailbox_id=mailbox,
                           name=f"Campaign {bid}", sequence_version=1, version=1, status="draft",
                           timezone="Europe/London", daily_cap=5, target_rules=json.dumps({"raw": SECRET}),
                           target_hash=SECRET)
            add(conn, "sequence_steps", bid, campaign_id=campaign, sequence_version=1, ordinal=0,
                delay_business_days=0, template_text=SECRET, template_hash=SECRET, allowed_variables="[]")
            add(conn, "evidence", bid, prospect_id=prospect, source_type="company_page", operation="read",
                source_url="https://example.test/about", excerpt="Synthetic evidence", fact_type="role",
                fact_value="Director", confidence=94, fetched_at=STAMP,
                expires_at="2027-01-18T12:00:00+00:00", provider_record_id=SECRET,
                verification_subject_email_key=SECRET, raw_verdict=SECRET, flags=json.dumps([SECRET]))
            add(conn, "mailboxes", bid, mailbox_id=mailbox, enabled=False, daily_cap=5,
                warmup_stage=5, sending_days=0, health_status="unknown", health_evidence=json.dumps({"raw": SECRET}))
            add(conn, "compliance", bid, brand_id=brand, audience_hash=SECRET, version=1,
                purpose=SECRET, necessity=SECRET, balancing_test=SECRET, safeguards=SECRET,
                sources=json.dumps([SECRET]), decision="draft", review_due_at=STAMP)
            add(conn, "settings", bid, pause_all=True, timezone="Europe/London", business_daily_cap=20,
                owner_cc_default=False, owner_cc_address="owner@example.test", retention_policy_version=1)
            for index, (state, origin) in enumerate((("accepted", "live"), ("unknown", "live"),
                                                     ("imported", "import"), ("failed", "live"))):
                add(conn, "messages", bid, index, prospect_id=prospect, campaign_id=campaign,
                    mailbox_id=mailbox, kind="imported" if origin == "import" else "initial",
                    origin=origin, direction="outbound", state=state,
                    accepted_at=STAMP if state == "accepted" else None, to_emails=json.dumps([SECRET]),
                    cc_emails="[]", subject=SECRET, body=SECRET, payload_hash=SECRET, payload_version=1,
                    provider_message_id="same-provider-id", provider_thread_id="same-thread-id",
                    idempotency_key=f"{bid}-{index}", authority_snapshot=json.dumps({"raw": SECRET}))
            for index, category in enumerate(("interested", "out_of_office", "bounce", "complaint", "self")):
                add(conn, "replies", bid, index, prospect_id=prospect, mailbox_id=mailbox,
                    inbound_email_id=uid(bid, "inbound", index), category=category,
                    confidence=90, classification_version=1, knowledge_refs=json.dumps([SECRET]),
                    suggested_body=SECRET, resolution="pending", received_at=STAMP)
            add(conn, "suppressions", bid, key_type="email", key_digest=SECRET, digest_version=1,
                reason="objection", suppressed_at=STAMP)
            add(conn, "unsubscribe_tokens", bid, token_digest=SECRET + bid,
                prospect_key_digest=SECRET, digest_version=1, issued_at=STAMP)
    yield eng
    eng.dispose()


@pytest.fixture
def harness(database, monkeypatch):
    module = implementation()
    import auth
    import assistant_tools
    import db

    biz = SimpleNamespace(id=A, name="Synthetic", timezone="Europe/London", plan_tier="business",
                          feature_flags={}, subscription_status="active", is_active=True, trial_ends_at=None)

    class GateSession(Session):
        def exec(self, statement, *args, **kwargs):
            from models import Business
            descriptions = getattr(statement, "column_descriptions", [])
            if descriptions and descriptions[0].get("entity") is Business:
                return SimpleNamespace(first=lambda: biz)
            return super().exec(statement, *args, **kwargs)

    def sessions():
        with GateSession(database) as session:
            yield session

    async def context():
        return {"business_id": biz.id, "user_id": uid(biz.id, "owner")}

    monkeypatch.setattr(auth, "is_platform_admin_user", lambda *args: False)
    monkeypatch.setattr(auth, "_load_business", lambda session, bid: biz if str(bid) == biz.id else None)
    monkeypatch.setattr(module, "_load_business", lambda session, bid: biz if str(bid) == biz.id else None)
    monkeypatch.setattr(module, "now", lambda: NOW)
    monkeypatch.setattr(module, "engine", database)
    monkeypatch.setattr(assistant_tools, "engine", database)
    app = FastAPI()
    app.include_router(module.router)
    app.dependency_overrides[auth.get_user_business_context] = context
    app.dependency_overrides[db.get_session] = sessions
    with TestClient(app) as client:
        yield SimpleNamespace(module=module, biz=biz, client=client, tools=assistant_tools, engine=database)


def invoke(harness, surface, via, *, bid=None, **arguments):
    path, tool, parent, _, _ = surface
    if parent:
        kind = {"prospect_id": "prospects", "campaign_id": "campaigns", "reply_id": "replies"}[parent]
        arguments.setdefault(parent, uid(bid or harness.biz.id, kind))
    if via == "tool":
        result = harness.tools.execute_tool(tool, arguments, harness.biz.id)
        return result.get("status_code", 200), result
    path_args = {parent: arguments.pop(parent)} if parent else {}
    response = harness.client.get("/v1/outreach/" + path.format(**path_args), params=arguments)
    return response.status_code, response.json()


def items(surface, result):
    if surface[1] in DETAILS:
        return [result["item"]] if result["item"] else []
    return result.get("items", [])


@pytest.mark.parametrize("via", ["api", "tool"])
@pytest.mark.parametrize("surface", SURFACES, ids=lambda s: s[1])
def test_each_read_is_scoped_and_redacted(harness, surface, via):
    """OUT-2 F01/F12, P9: every API/tool uses tenant scope and an exact safe projection."""
    for tenant in (A, B):
        harness.biz.id = tenant
        status, result = invoke(harness, surface, via)
        assert status == 200
        encoded = json.dumps(result)
        other = B if tenant == A else A
        assert other not in encoded and SECRET not in encoded
        for table in COLUMNS:
            for index in range(5):
                assert uid(other, table, index) not in encoded
        for item in items(surface, result):
            assert set(item) == set(surface[4].split())
        if surface[3]:
            assert items(surface, result), "Positive control: tenant's seeded row must be visible"
        assert "data_quality" in result


@pytest.mark.parametrize("via", ["api", "tool"])
@pytest.mark.parametrize("surface", WITH_PARENT, ids=lambda s: s[1])
def test_guessed_parent_ids_are_indistinguishable_from_missing(harness, surface, via):
    """OUT-2 F01: foreign and nonexistent prospect/campaign IDs both return not-found."""
    foreign_status, foreign = invoke(harness, surface, via, bid=B)
    missing_status, missing = invoke(harness, surface, via, bid=EMPTY)
    assert foreign_status == missing_status == 404
    assert foreign == missing
    assert B not in json.dumps(foreign)


@pytest.mark.parametrize("via", ["api", "tool"])
@pytest.mark.parametrize("surface", SURFACES, ids=lambda s: s[1])
@pytest.mark.parametrize("plan,flags,status,active", [
    ("starter", {}, "active", True), ("pro", {}, "active", True),
    ("business", {"outreach": False}, "active", True),
    ("business", {}, "unpaid", True), ("business", {}, "canceled", True),
    ("business", {}, "active", False), ("business", {}, "canceled", False),
])
def test_feature_and_access_gate_on_every_surface(harness, surface, via, plan, flags, status, active):
    """DECISION 3: outreach refuses absent entitlement, explicit denial, read-only and suspension."""
    harness.biz.plan_tier, harness.biz.feature_flags = plan, flags
    harness.biz.subscription_status, harness.biz.is_active = status, active
    code, result = invoke(harness, surface, via)
    if surface[3] in ("replies", "reply_slots", "knowledge", "suppressions") and active and not flags:
        assert code == 200  # OUT-7: retained inbound history survives downgrade/read-only.
        return
    assert code == 403
    assert not result.get("items") and not result.get("item") and "totals" not in result
    assert SECRET not in json.dumps(result)


@pytest.mark.parametrize("via", ["api", "tool"])
@pytest.mark.parametrize("surface", SURFACES, ids=lambda s: s[1])
@pytest.mark.parametrize("status", ["active", "trialing", "past_due"])
def test_paid_and_dunning_reads_work(harness, surface, via, status):
    """DECISION 3: paid, trialing and past-due Business access remains full."""
    harness.biz.subscription_status = status
    assert invoke(harness, surface, via)[0] == 200


@pytest.mark.parametrize("via", ["api", "tool"])
@pytest.mark.parametrize("surface", SURFACES, ids=lambda s: s[1])
def test_business_argument_cannot_override_context(harness, surface, via):
    """OUT-2 F01: business_id is not a client/model argument; reject it before reading."""
    code, result = invoke(harness, surface, via, business_id=B)
    assert code == 422
    assert not result.get("items") and not result.get("item")


@pytest.mark.parametrize("via", ["api", "tool"])
@pytest.mark.parametrize("surface", LISTS, ids=lambda s: s[1])
@pytest.mark.parametrize("arguments", [{"limit": 0}, {"limit": 51}, {"limit": -1}, {"offset": -1}, {"offset": 10001}])
def test_invalid_pagination_fails_closed(harness, surface, via, arguments):
    """OUT-2 bounded reads: limit 1..50 and offset 0..10000 are enforced at both boundaries."""
    assert invoke(harness, surface, via, **arguments)[0] == 422


@pytest.mark.parametrize("via", ["api", "tool"])
@pytest.mark.parametrize("surface", LISTS, ids=lambda s: s[1])
def test_pagination_total_is_not_page_length(harness, surface, via):
    """P2/P8/F18: pagination bounds rows while total counts all matching tenant rows."""
    code, result = invoke(harness, surface, via, limit=1, offset=0)
    assert code == 200 and len(result["items"]) <= 1
    if surface[3]:
        with harness.engine.connect() as conn:
            expected = conn.execute(text(f"SELECT count(*) FROM outreach_{surface[3]} WHERE business_id=:b"), {"b": A}).scalar_one()
        assert result["total"] == expected
    assert result["limit"] == 1 and result["offset"] == 0


@pytest.mark.parametrize("via", ["api", "tool"])
@pytest.mark.parametrize("surface", [s for s in SURFACES if not s[2]], ids=lambda s: s[1])
def test_empty_tenant_reports_none(harness, surface, via):
    """P2/P8: absent records say none; missing knowledge/permissions never become invented facts."""
    harness.biz.id = EMPTY
    code, result = invoke(harness, surface, via)
    assert code == 200
    assert "none" in result["message"].lower()
    assert not items(surface, result)
    if "total" in result:
        assert result["total"] == 0
    if "totals" in result:
        assert all(value == 0 for value in result["totals"].values())


@pytest.mark.parametrize("via", ["api", "tool"])
def test_grounded_summary_separates_outcomes(harness, via):
    """F18/P2/P8: count stored rows, not pages; unknown/imported are not live accepted or won."""
    surface = next(s for s in SURFACES if s[1] == "outreach_summary")
    code, result = invoke(harness, surface, via)
    assert code == 200
    with harness.engine.connect() as conn:
        def count(table, predicate="1=1"):
            return conn.execute(text(f"SELECT count(*) FROM outreach_{table} WHERE business_id=:b AND {predicate}"), {"b": A}).scalar_one()
        expected = {
            "prospects": count("prospects"), "campaigns": count("campaigns"),
            "accepted_live": count("messages", "origin='live' AND direction='outbound' AND state='accepted'"),
            "unknown_live": count("messages", "origin='live' AND direction='outbound' AND state='unknown'"),
            "imported_messages": count("messages", "origin='import'"),
            "human_replies": count("replies", "category IN ('interested','question','not_now','unsubscribe','objection','wrong_person','referral')"),
            "unresolved_replies": count("replies", "resolution IN ('pending','handed_over')"),
            "stage_meeting": count("prospects", "stage='meeting'"),
            "stage_won": count("prospects", "stage='won'"),
        }
    assert result["totals"] == expected
    assert expected["accepted_live"] == 1 and expected["human_replies"] == 1
    assert expected["stage_meeting"] == expected["stage_won"] == 0
    assert "confirmed_meetings" not in result and "revenue" not in result
    assert set(result["sources"]) == set(expected)
    for path in result["sources"].values():
        assert path.startswith("/v1/outreach/")
        assert harness.client.get(path).status_code == 200


@pytest.mark.parametrize("via", ["api", "tool"])
def test_large_population_is_bounded_but_fully_counted(harness, via):
    """P2/P8: 61 prospects yield at most 50 rows but total and summary must equal 61."""
    with harness.engine.begin() as conn:
        for index in range(1, 61):
            add(conn, "prospects", A, index, stage="new", eligibility="blocked", subscriber_type="unknown",
                captured_at=STAMP, retention_due_at="2027-10-20T12:00:00+00:00")
    surface = next(s for s in SURFACES if s[1] == "list_outreach_prospects")
    _, default = invoke(harness, surface, via)
    assert len(default["items"]) == 20 and default["limit"] == 20
    _, first = invoke(harness, surface, via, limit=50)
    _, second = invoke(harness, surface, via, limit=50, offset=50)
    assert len(first["items"]) == 50 and len(second["items"]) == 11
    assert first["total"] == second["total"] == 61
    assert not ({i["id"] for i in first["items"]} & {i["id"] for i in second["items"]})
    _, summary = invoke(harness, next(s for s in SURFACES if s[1] == "outreach_summary"), via)
    assert summary["totals"]["prospects"] == 61


@pytest.mark.parametrize("via", ["api", "tool"])
def test_mailbox_filter_scopes_replies_and_guessed_ids(harness, via):
    """F01/F04: reply mailbox filters use owned account IDs; foreign IDs return 404, not an empty leak."""
    surface = next(s for s in SURFACES if s[1] == "list_outreach_replies")
    with harness.engine.begin() as conn:
        conn.execute(text("INSERT INTO email_accounts (id,business_id) VALUES (:id,:b)"),
                     {"id": uid(A, "account", 1), "b": A})
        add(conn, "replies", A, 9, prospect_id=uid(A, "prospects"), mailbox_id=uid(A, "account", 1),
            inbound_email_id=uid(A, "inbound", 9), category="question", resolution="pending",
            received_at=STAMP, knowledge_refs="[]")
    assert invoke(harness, surface, via, mailbox_id=uid(B, "account"))[0] == 404
    assert invoke(harness, surface, via, mailbox_id=uid(EMPTY, "account"))[0] == 404
    _, result = invoke(harness, surface, via, mailbox_id=uid(A, "account"))
    assert result["total"] == 5
    assert all(row["mailbox_id"] == uid(A, "account") for row in result["items"])


@pytest.mark.parametrize("via", ["api", "tool"])
def test_knowledge_and_slot_grounding(harness, via):
    """OUT-7 pins IDs/versions/state to stored tenant rows; no transport secrets."""
    for tool, table in (("get_outreach_knowledge", "knowledge"), ("list_outreach_reply_slots", "reply_slots")):
        surface = next(s for s in SURFACES if s[1] == tool)
        _, result = invoke(harness, surface, via)
        with harness.engine.connect() as conn:
            row = conn.execute(text(f"SELECT * FROM outreach_{table} WHERE business_id=:b"), {"b": A}).mappings().one()
        item = result["items"][0]
        assert item["id"] == row["id"]
        assert item.get("version", item.get("generation")) == row.get("version", row.get("generation"))
        assert item.get("status", item.get("state")) == row.get("status", row.get("state"))
        assert SECRET not in json.dumps(result)
        assert result["total"] == 1


def test_tools_registered_with_strict_argument_schemas(harness):
    """P1/P9: all read tools register in TOOL_DEFINITIONS, with no business/authority input."""
    definitions = {d["function"]["name"]: d["function"] for d in harness.tools.TOOL_DEFINITIONS}
    for _, name, parent, _, _ in SURFACES:
        schema = definitions[name]["parameters"]
        assert schema["additionalProperties"] is False
        assert not {"business_id", "user_id", "authority", "token"} & set(schema["properties"])
        if parent:
            assert parent in schema["required"]


@pytest.mark.parametrize("via", ["api", "tool"])
def test_read_paths_do_not_mutate_or_dispatch(harness, via, monkeypatch):
    """OUT-4 scope/P4: every read is SELECT-only; no actions, provider sends or model calls."""
    import socket

    def refuse(*args, **kwargs):
        raise AssertionError("Read attempted an outbound action or network call")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)

    for name in ("_send_email", "_send_invoice_chase", "_send_quote_via_aria"):
        monkeypatch.setattr(harness.tools, name, refuse)
    from services import aria_actions
    monkeypatch.setattr(aria_actions, "propose", refuse)
    monkeypatch.setattr(aria_actions, "approve", refuse)
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.lstrip().upper())

    event.listen(harness.engine, "before_cursor_execute", record)
    try:
        for surface in SURFACES:
            assert invoke(harness, surface, via)[0] == 200
    finally:
        event.remove(harness.engine, "before_cursor_execute", record)
    assert statements and all(s.startswith("SELECT") for s in statements)
    read_names = {surface[1] for surface in SURFACES}
    assert all(route.methods <= {"GET", "HEAD"} for route in harness.module.router.routes if route.name in read_names)


@pytest.mark.parametrize("via", ["api", "tool"])
def test_expired_evidence_and_prospect_fields_are_redacted(harness, via):
    """F19/P8: reading expired evidence/PII cannot revive it or reset retention."""
    with harness.engine.begin() as conn:
        conn.execute(text("UPDATE outreach_evidence SET expires_at=:now WHERE business_id=:b"), {"now": STAMP, "b": A})
        conn.execute(text("UPDATE outreach_prospects SET retention_due_at=:now WHERE business_id=:b"), {"now": STAMP, "b": A})
    evidence = next(s for s in SURFACES if s[1] == "get_outreach_evidence")
    _, result = invoke(harness, evidence, via)
    assert result["data_quality"] == "stale"
    assert result["items"][0]["excerpt"] is None
    assert result["items"][0]["fact_value"] is None
    prospect = next(s for s in SURFACES if s[1] == "get_outreach_prospect")
    _, result = invoke(harness, prospect, via)
    for field in ("company", "name", "role", "domain"):
        assert result["item"][field] is None
    with harness.engine.connect() as conn:
        assert conn.execute(text("SELECT retention_due_at FROM outreach_prospects WHERE id=:id"),
                            {"id": uid(A, "prospects")}).scalar_one() == STAMP


@pytest.mark.parametrize("via", ["api", "tool"])
def test_projection_text_is_bounded(harness, via):
    """OUT-2 bounded context: evidence excerpts cap at 2000 chars and ordinary text at 1000."""
    with harness.engine.begin() as conn:
        conn.execute(text("UPDATE outreach_evidence SET excerpt=:value, fact_value=:value WHERE business_id=:b"),
                     {"value": "x" * 4000, "b": A})
        conn.execute(text("UPDATE outreach_prospects SET company=:value WHERE business_id=:b"),
                     {"value": "y" * 10000, "b": A})
    _, result = invoke(harness, next(s for s in SURFACES if s[1] == "get_outreach_evidence"), via)
    assert len(result["items"][0]["excerpt"]) == 2000
    assert len(result["items"][0]["fact_value"]) == 2000
    _, result = invoke(harness, next(s for s in SURFACES if s[1] == "get_outreach_prospect"), via)
    assert len(result["item"]["company"]) == 1000


@pytest.mark.parametrize("via", ["api", "tool"])
def test_sequence_only_returns_bound_current_version(harness, via):
    """OUT-2 version binding: old templates and same-tenant other campaigns cannot bleed into a sequence."""
    with harness.engine.begin() as conn:
        add(conn, "sequence_steps", A, 1, campaign_id=uid(A, "campaigns"), sequence_version=2,
            ordinal=0, delay_business_days=0, template_text=SECRET)
        other = add(conn, "campaigns", A, 1, brand_id=uid(A, "brands"), mailbox_id=uid(A, "account"),
                    name="Other", sequence_version=1, version=1, status="draft", timezone="Europe/London", daily_cap=5)
        add(conn, "sequence_steps", A, 2, campaign_id=other, sequence_version=1,
            ordinal=0, delay_business_days=0, template_text=SECRET)
    _, result = invoke(harness, next(s for s in SURFACES if s[1] == "get_outreach_sequence"), via)
    assert result["total"] == 1
    assert [item["id"] for item in result["items"]] == [uid(A, "sequence_steps")]


@pytest.mark.parametrize("via", ["api", "tool"])
def test_nested_reads_do_not_include_other_owned_prospects(harness, via):
    """F01: tenant scope alone is insufficient; nested collections also scope their parent ID."""
    with harness.engine.begin() as conn:
        other = add(conn, "prospects", A, 1, stage="new", captured_at=STAMP,
                    retention_due_at="2027-10-20T12:00:00+00:00")
        add(conn, "evidence", A, 1, prospect_id=other, source_type="company_page", fact_type="role",
            fact_value="Other record", fetched_at=STAMP, expires_at="2027-01-18T12:00:00+00:00")
        add(conn, "messages", A, 9, prospect_id=other, origin="live", kind="initial",
            direction="outbound", state="draft", idempotency_key="other-owned", body=SECRET)
    for name, count in (("get_outreach_evidence", 1), ("get_outreach_prospect_timeline", 4)):
        _, result = invoke(harness, next(s for s in SURFACES if s[1] == name), via)
        assert result["total"] == count
        assert all(row["prospect_id"] == uid(A, "prospects") for row in result["items"])


@pytest.mark.parametrize("via", ["api", "tool"])
def test_settings_never_invents_standing_permission(harness, via):
    """P4/OUT-2 AUTO agreement: pause/settings/approval are not a grant of standing authority."""
    _, result = invoke(harness, next(s for s in SURFACES if s[1] == "get_outreach_settings_and_permissions"), via)
    assert result["permissions"] == {
        "status": "not_available",
        "message": "None available: outreach permission projection awaits OUT-6/OUT-11.",
    }


@pytest.mark.parametrize("plan,flags", [("starter", {}), ("pro", {}), ("business", {"outreach": False})])
def test_aria_is_told_plainly_what_outreach_is_and_is_not(harness, plan, flags):
    """Mike, 23 Oct 2026: told only "not enabled for your plan", Aria invented
    an "Outreach add-on" with "dashboards and sequence performance". The tool
    result must state the facts and forbid inventing an offer."""
    harness.biz.plan_tier, harness.biz.feature_flags = plan, flags
    code, result = invoke(harness, SURFACES[0], "tool")
    assert code == 403
    text_ = json.dumps(result).lower()
    assert "business plan" in text_
    guidance = result["aria_guidance"].lower()
    assert "add-on" in guidance and "do not invent" in guidance
    assert "not available yet" in text_ or "still being built" in text_
    # Mike, 23 Oct: an owner may send outreach by hand; Aria may offer to
    # look for replies to THOSE emails in their inbox.
    assert "send outreach emails themselves" in guidance and "replies" in guidance


@pytest.mark.parametrize("plan,flags,status,active", [
    ("business", {}, "unpaid", True), ("business", {}, "active", False)])
def test_read_only_or_suspended_is_not_described_as_a_plan_problem(harness, plan, flags, status, active):
    harness.biz.plan_tier, harness.biz.feature_flags = plan, flags
    harness.biz.subscription_status, harness.biz.is_active = status, active
    code, result = invoke(harness, SURFACES[0], "tool")
    assert code == 403 and "aria_guidance" not in result


@pytest.mark.parametrize('via', ['api', 'tool'])
def test_out7_knowledge_status_and_source_are_database_grounded(harness, via):
    surface = next(s for s in SURFACES if s[1] == 'get_outreach_knowledge')
    with harness.engine.begin() as conn:
        conn.execute(text("UPDATE outreach_knowledge SET status='retired',retired_at=:at WHERE business_id=:b"), {'at': STAMP, 'b': A})
    code, result = invoke(harness, surface, via)
    assert code == 200 and result['data_quality'] == 'stale'
    assert result['items'][0]['status'] == 'retired'
    assert result['items'][0]['answer'] == 'Weekday appointments'
    assert result['items'][0]['source_reference'] == 'https://example.test/facts'
    foreign, _ = invoke(harness, surface, via, brand_id=uid(B, 'brands'))
    assert foreign == 404


@pytest.mark.parametrize('via', ['api', 'tool'])
def test_out8_unresolved_count_and_filter_are_grounded_across_pages(harness, via):
    with harness.engine.begin() as conn:
        for bid in (A, B):
            for index in range(10, 76):
                add(conn, 'replies', bid, index, mailbox_id=uid(bid, 'account'),
                    resolution='handed_over' if index % 2 else 'resolved', received_at=STAMP)
    surface = next(s for s in SURFACES if s[1] == 'list_outreach_replies')
    for bid in (A, B):
        harness.biz.id = bid
        _, result = invoke(harness, surface, via, resolution='unresolved')
        with harness.engine.connect() as conn:
            expected = conn.execute(text("SELECT count(*) FROM outreach_replies WHERE business_id=:b AND resolution IN ('pending','handed_over')"), {'b': bid}).scalar_one()
        assert result['total'] == expected == 38
        assert len(result['items']) == 20
        assert all(row['resolution'] in ('pending', 'handed_over') for row in result['items'])
        _, summary = invoke(harness, next(s for s in SURFACES if s[1] == 'outreach_summary'), via)
        assert summary['totals']['unresolved_replies'] == expected
        assert summary['as_of'] == STAMP
        for resolution in ('pending', 'handed_over', 'resolved', 'dismissed'):
            _, filtered = invoke(harness, surface, via, resolution=resolution)
            assert all(row['resolution'] == resolution for row in filtered['items'])
    assert invoke(harness, surface, via, resolution='anything')[0] == 422


@pytest.mark.parametrize('via', ['api', 'tool'])
@pytest.mark.parametrize('mismatch', [None, 'business', 'mailbox', 'missing'])
def test_out8_original_requires_exact_business_mailbox_and_id(harness, via, mismatch):
    with harness.engine.begin() as conn:
        conn.execute(text('INSERT INTO email_messages VALUES (:id,:b,:m,:s,:body,:sender,:at)'), {
            'id': uid(A, 'inbound') if mismatch != 'missing' else uid(A, 'other'),
            'b': B if mismatch == 'business' else A,
            'm': uid(B, 'account') if mismatch == 'mailbox' else uid(A, 'account'),
            's': 'Stored subject', 'body': 'x' * 14000, 'sender': 'sender@example.test', 'at': STAMP})
    _, result = invoke(harness, next(s for s in SURFACES if s[1] == 'get_outreach_reply'), via)
    item = result['item']
    if mismatch:
        assert item['body_text'] is None and item['subject'] is None
        assert item['original_status'] == 'unavailable'
    else:
        assert item['body_text'] == 'x' * 12000
        assert item['subject'] == 'Stored subject'
        assert item['from_email'] == 'sender@example.test'
        assert item['original_received_at'] == STAMP


@pytest.mark.parametrize('via', ['api', 'tool'])
def test_out8_suppression_link_retention_and_templates(harness, via):
    suppression = next(s for s in SURFACES if s[1] == 'list_outreach_suppressions')
    _, result = invoke(harness, suppression, via)
    assert result['items'][0]['prospect_id'] == uid(A, 'prospects')
    with harness.engine.begin() as conn:
        conn.execute(text('UPDATE outreach_prospects SET retention_due_at=:at WHERE business_id=:b'), {'at': STAMP, 'b': A})
        conn.execute(text('UPDATE outreach_sequence_steps SET template_text=:t, approved_by=:owner WHERE business_id=:b'),
                     {'t': json.dumps({'schema_version': 1, 'subject': 'Stored subject', 'body': 'b' * 13000}), 'owner': uid(A, 'owner'), 'b': A})
    _, result = invoke(harness, suppression, via)
    assert result['items'][0]['prospect_id'] is None
    _, result = invoke(harness, next(s for s in SURFACES if s[1] == 'get_outreach_sequence'), via)
    assert result['items'][0]['subject'] == 'Stored subject'
    assert result['items'][0]['body'] == 'b' * 13000
    assert result['items'][0]['approved_by'] == uid(A, 'owner')


def test_out8_tool_and_http_argument_schemas_match(harness):
    definitions = {d['function']['name']: d['function']['parameters'] for d in harness.tools.TOOL_DEFINITIONS}
    for read in harness.module.READS:
        assert definitions[read.tool] == harness.module.argument_schema(read)


@pytest.mark.parametrize('via', ['api', 'tool'])
def test_out8_reply_detail_shows_scoped_stopped_sequences_and_takeover(harness, via):
    with harness.engine.begin() as conn:
        for bid in (A, B):
            for index in range(55):
                add(conn, 'enrolments', bid, index, prospect_id=uid(bid, 'prospects'),
                    campaign_id=uid(bid, 'campaigns'), state='paused', takeover_at=STAMP,
                    stop_reason='Owner took over')
        add(conn, 'enrolments', A, 100, prospect_id=uid(A, 'other'),
            campaign_id=uid(A, 'campaigns'), state='active')
    _, result = invoke(harness, next(s for s in SURFACES if s[1] == 'get_outreach_reply'), via)
    item = result['item']
    assert item['enrolments_total'] == 55 and len(item['enrolments']) == 50
    for enrolment in item['enrolments']:
        assert enrolment['campaign_id'] == uid(A, 'campaigns')
        assert enrolment['state'] == 'paused'
        assert enrolment['takeover_at'] == STAMP
        assert enrolment['stop_reason'] == 'Owner took over'
    assert uid(B, 'campaigns') not in json.dumps(result)
