"""OUT-3 Stage A executable schema contract; deliberately red before 037.

Real loopback Supabase Postgres only. No SQLite or schema-absence skips.
All seeds and mutations roll back, including failures. Column names below
resolve §5's shorthand for Stage B review; they are not existing ORM APIs.
These tests prove replay behaviour, never production state or send authority.
"""

import json
import os
from contextlib import contextmanager
from urllib.parse import urlparse
from uuid import uuid4

import psycopg2
from psycopg2 import errors, sql
from psycopg2.extras import Json
import pytest

DATABASE_URL = os.getenv("RLS_LOCAL_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="RLS_LOCAL_DATABASE_URL unset: requires scripts/rls-local.sh up; "
           "a skip is not Postgres verification.",
)
if DATABASE_URL and urlparse(DATABASE_URL).hostname not in ("localhost", "127.0.0.1", "::1"):
    raise RuntimeError("OUT-3 refuses non-loopback Postgres; never staging or production")

READABLE = ("brands", "campaigns", "prospects", "evidence", "compliance", "replies")
PRIVATE = ("settings", "mailboxes", "batch_reviews", "sequence_steps", "enrolments",
           "messages", "suppressions", "unsubscribe_tokens", "dispatch_jobs",
           "daily_usage", "usage_events")
TABLES = READABLE + PRIVATE
NOW = "2026-10-19T10:00:00+00:00"
LATER = "2026-11-19T10:00:00+00:00"


def insert(cur, table, values):
    values = {"id": str(uuid4()), **values}
    cur.execute(sql.SQL("INSERT INTO public.{} ({}) VALUES ({}) RETURNING id").format(
        sql.Identifier(table), sql.SQL(", ").join(map(sql.Identifier, values)),
        sql.SQL(", ").join(sql.Placeholder() for _ in values)), list(values.values()))
    return str(cur.fetchone()[0])


def update(cur, table, row_id, values):
    cur.execute(sql.SQL("UPDATE public.{} SET {} WHERE id = %s").format(
        sql.Identifier(table), sql.SQL(", ").join(
            sql.SQL("{} = %s").format(sql.Identifier(k)) for k in values)),
        [*values.values(), row_id])


@contextmanager
def rejected(cur, error):
    cur.execute("SAVEPOINT rejected_write")
    try:
        with pytest.raises(error):
            yield
    finally:
        cur.execute("ROLLBACK TO SAVEPOINT rejected_write")
        cur.execute("RELEASE SAVEPOINT rejected_write")


@contextmanager
def acting_as(cur, role, user=None):
    """Same transaction-local role and dual JWT settings as BH-003."""
    cur.execute("SAVEPOINT caller")
    claims = {"sub": user, "email": "out3@example.invalid", "role": role} if user else {}
    cur.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (user or "",))
    cur.execute("SELECT set_config('request.jwt.claim.email', %s, true)",
                (claims.get("email", ""),))
    cur.execute("SELECT set_config('request.jwt.claims', %s, true)", (json.dumps(claims),))
    cur.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(role)))
    try:
        yield
    finally:
        cur.execute("ROLLBACK TO SAVEPOINT caller")
        cur.execute("RELEASE SAVEPOINT caller")


@pytest.fixture
def db():
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT rolbypassrls FROM pg_roles WHERE rolname=current_user")
            assert cur.fetchone()[0], "seed connection must bypass RLS, like backend"
            yield cur
    finally:
        conn.rollback()
        conn.close()


@pytest.fixture
def tenants(db):
    result = []
    for label in ("A", "B"):
        user = str(uuid4())
        db.execute("INSERT INTO auth.users (id,email,aud,role) "
                   "VALUES (%s,%s,'authenticated','authenticated')",
                   (user, f"{user}@example.invalid"))
        biz = insert(db, "businesses", {"name": f"OUT3 {label}", "api_key": str(uuid4()),
                                        "plan_tier": "starter"})
        insert(db, "business_members", {"business_id": biz, "user_id": user,
                                        "role": "owner", "is_active": True})
        result.append({"business": biz, "user": user})
    return result


def seed(cur, tenant):
    """One valid graph per tenant, with intentionally colliding external keys."""
    biz, user = tenant["business"], tenant["user"]
    ids, payloads = {}, {}

    def add(name, /, **values):  # positional-only: "name" is also a column
        payloads[name] = {"business_id": biz, **values}
        ids[name] = insert(cur, "outreach_" + name, payloads[name])
        return ids[name]

    ids["account"] = insert(cur, "email_accounts", {
        "business_id": biz, "user_id": user, "provider": "google",
        "email_address": "sender@example.invalid", "is_default": True})
    ids["inbound"] = insert(cur, "email_messages", {
        "business_id": biz, "email_account_id": ids["account"],
        "provider_message_id": "same-inbound", "provider_thread_id": "same-thread"})
    ids["action"] = insert(cur, "aria_actions", {
        "business_id": biz, "action_type": "send_invoice_chase",
        "payload": Json({"version": 1, "invoice_id": str(uuid4())}), "expires_at": LATER})
    add("settings", pause_all=True, timezone="Europe/London", business_daily_cap=20,
        owner_cc_default=False, retention_policy_version=1)
    add("mailboxes", mailbox_id=ids["account"], enabled=False, daily_cap=5,
        warmup_stage=5, sending_days=0, health_status="unknown", health_evidence=Json({}))
    add("brands", name="Pilot", default_mailbox_id=ids["account"],
        privacy_url="https://example.invalid/privacy", sender_identity="Pilot Ltd", version=1)
    add("compliance", brand_id=ids["brands"], audience_hash="audience", version=1,
        purpose="Pilot", necessity="Test", balancing_test="Test", safeguards="Test",
        sources=Json([]), decision="draft", review_due_at=LATER)
    add("prospects", company="Synthetic Ltd", email="person@example.invalid", email_key="digest",
        subscriber_type="corporate", eligibility="blocked", stage="new",
        lia_id=ids["compliance"], captured_at=NOW, retention_due_at=LATER)
    add("evidence", prospect_id=ids["prospects"], source_type="company_website",
        operation="manual", fact_type="company", fact_value="Synthetic Ltd",
        fetched_at=NOW, expires_at=LATER)
    add("campaigns", brand_id=ids["brands"], mailbox_id=ids["account"], name="Pilot",
        target_rules=Json({}), target_hash="target", sequence_version=1, version=1,
        status="draft", timezone="Europe/London", daily_cap=5)
    add("batch_reviews", campaign_id=ids["campaigns"], campaign_version=1,
        mailbox_id=ids["account"], target_hash="target", template_set_hash="templates",
        eligible_count=5, reviewed_count=0)
    add("sequence_steps", campaign_id=ids["campaigns"], sequence_version=1, ordinal=0,
        delay_business_days=0, template_text="Hello", template_hash="template",
        allowed_variables=Json([]))
    add("enrolments", prospect_id=ids["prospects"], campaign_id=ids["campaigns"],
        sequence_version=1, state="pending", next_step=0, next_due_at=LATER)
    add("messages", prospect_id=ids["prospects"], campaign_id=ids["campaigns"],
        enrolment_id=ids["enrolments"], step_id=ids["sequence_steps"],
        mailbox_id=ids["account"], batch_review_id=ids["batch_reviews"],
        kind="initial", origin="live", direction="outbound", to_emails=["person@example.invalid"],
        cc_emails=[], subject="Test", body="Synthetic only", payload_hash="payload",
        payload_version=1, state="draft", idempotency_key="same-operation",
        authority_snapshot=Json({}))
    add("replies", prospect_id=ids["prospects"], mailbox_id=ids["account"],
        inbound_email_id=ids["inbound"], matched_message_id=ids["messages"],
        knowledge_refs=Json([]), resolution="pending", received_at=NOW)
    add("suppressions", key_type="email", key_digest="same-digest", digest_version=1,
        reason="opt_out", suppressed_at=NOW)
    add("unsubscribe_tokens", token_digest=str(uuid4()), prospect_key_digest="digest",
        digest_version=1, issued_at=NOW)
    add("dispatch_jobs", message_id=ids["messages"], enrolment_id=ids["enrolments"],
        step_id=ids["sequence_steps"], logical_key="same-logical", status="pending", due_at=LATER)
    add("daily_usage", scope_type="mailbox", scope_id=ids["account"],
        local_date="2026-10-19", reserved=0, accepted=0, unknown=0)
    add("usage_events", operation_key="same-operation", kind="outreach_emails_sent", quantity=1,
        state="reserved", period_start="2026-10-01T00:00:00+01:00",
        period_end="2026-11-01T00:00:00+00:00", mailbox_id=ids["account"],
        local_send_date="2026-10-19", message_id=ids["messages"], cost=0, currency="GBP")
    return ids, payloads


@pytest.fixture
def graphs(db, tenants):
    return [seed(db, tenant) for tenant in tenants]


@pytest.mark.parametrize("table", TABLES)
def test_rls_and_effective_grants(db, table):
    """F01/F02; §5: RLS on, anon nothing, browser read-only, no authority writes."""
    name = "public.outreach_" + table
    db.execute("SELECT relrowsecurity FROM pg_class WHERE oid=to_regclass(%s)", (name,))
    assert db.fetchone() == (True,), f"missing table or RLS off: {name}"
    for role in ("anon", "authenticated"):
        for privilege in ("SELECT", "INSERT", "UPDATE", "REFERENCES", "DELETE", "TRUNCATE", "TRIGGER"):
            function = "has_any_column_privilege" if privilege in (
                "SELECT", "INSERT", "UPDATE", "REFERENCES") else "has_table_privilege"
            db.execute(f"SELECT {function}(%s,%s,%s)", (role, name, privilege))
            expected = role == "authenticated" and privilege == "SELECT" and table in READABLE
            assert db.fetchone()[0] is expected, (name, role, privilege)


@pytest.mark.parametrize("table", READABLE)
def test_member_select_is_tenant_scoped(db, tenants, graphs, table):
    """F01: each authenticated member sees own rows, never the other tenant's IDs."""
    for tenant, (ids, _) in zip(tenants, graphs):
        with acting_as(db, "authenticated", tenant["user"]):
            db.execute(sql.SQL("SELECT id FROM public.{}").format(sql.Identifier("outreach_" + table)))
            assert {str(row[0]) for row in db.fetchall()} == {ids[table]}


@pytest.mark.parametrize("table", TABLES)
@pytest.mark.parametrize("role", ("anon", "authenticated"))
def test_client_writes_denied(db, tenants, graphs, table, role):
    """F01/F02: even an owner cannot INSERT, UPDATE or DELETE operational/authority rows."""
    ids, payloads = graphs[0]
    with acting_as(db, role, tenants[0]["user"] if role == "authenticated" else None):
        with rejected(db, errors.InsufficientPrivilege):
            insert(db, "outreach_" + table, payloads[table])
        with rejected(db, errors.InsufficientPrivilege):
            update(db, "outreach_" + table, ids[table], {"business_id": tenants[0]["business"]})
        with rejected(db, errors.InsufficientPrivilege):
            db.execute(sql.SQL("DELETE FROM public.{} WHERE id=%s").format(
                sql.Identifier("outreach_" + table)), (ids[table],))


@pytest.mark.parametrize("table", TABLES)
def test_anon_and_private_reads_denied(db, tenants, graphs, table):
    """F01; §5: tokens, payloads, jobs, digests and usage are not browser projections."""
    for role in ("anon", "authenticated"):
        if role == "authenticated" and table in READABLE:
            continue
        with acting_as(db, role, tenants[0]["user"] if role == "authenticated" else None):
            with rejected(db, errors.InsufficientPrivilege):
                db.execute(sql.SQL("SELECT * FROM public.{}").format(
                    sql.Identifier("outreach_" + table)))


FK_CASES = (
    ("brands", "default_mailbox_id", "account"), ("mailboxes", "mailbox_id", "account"),
    ("prospects", "lia_id", "compliance"), ("evidence", "prospect_id", "prospects"),
    ("compliance", "brand_id", "brands"), ("campaigns", "brand_id", "brands"),
    ("campaigns", "mailbox_id", "account"), ("batch_reviews", "campaign_id", "campaigns"),
    ("batch_reviews", "mailbox_id", "account"), ("sequence_steps", "campaign_id", "campaigns"),
    ("enrolments", "campaign_id", "campaigns"), ("enrolments", "prospect_id", "prospects"),
    ("messages", "prospect_id", "prospects"), ("messages", "campaign_id", "campaigns"),
    ("messages", "enrolment_id", "enrolments"), ("messages", "step_id", "sequence_steps"),
    ("messages", "mailbox_id", "account"), ("messages", "action_id", "action"),
    ("messages", "batch_review_id", "batch_reviews"), ("messages", "retry_of", "messages"),
    ("replies", "prospect_id", "prospects"), ("replies", "mailbox_id", "account"),
    ("replies", "inbound_email_id", "inbound"), ("replies", "matched_message_id", "messages"),
    ("dispatch_jobs", "message_id", "messages"), ("dispatch_jobs", "action_id", "action"),
    ("dispatch_jobs", "enrolment_id", "enrolments"), ("dispatch_jobs", "step_id", "sequence_steps"),
    ("usage_events", "message_id", "messages"), ("usage_events", "mailbox_id", "account"),
)


@pytest.mark.parametrize("table,column,parent", FK_CASES)
def test_composite_fks_reject_cross_business(db, graphs, table, column, parent):
    """F01; §5: elevated backend cannot link individually valid IDs across businesses."""
    with rejected(db, errors.ForeignKeyViolation):
        update(db, "outreach_" + table, graphs[0][0][table], {column: graphs[1][0][parent]})


CHECK_CASES = (
    ("settings", "business_daily_cap", 0), ("settings", "business_daily_cap", 21),
    ("mailboxes", "daily_cap", 0), ("mailboxes", "daily_cap", 21),
    ("mailboxes", "warmup_stage", 6), ("mailboxes", "sending_days", -1),
    ("mailboxes", "health_status", "invented"), ("campaigns", "status", "invented"),
    ("campaigns", "daily_cap", 21), ("batch_reviews", "eligible_count", -1),
    ("batch_reviews", "eligible_count", 6), ("batch_reviews", "reviewed_count", -1),
    ("batch_reviews", "reviewed_count", 6), ("sequence_steps", "ordinal", -1),
    ("sequence_steps", "ordinal", 3), ("sequence_steps", "delay_business_days", -1),
    ("sequence_steps", "delay_business_days", 5), ("prospects", "subscriber_type", "invented"),
    ("prospects", "eligibility", "invented"), ("prospects", "fit_score", -1),
    ("prospects", "fit_score", 101), ("prospects", "confidence", 101),
    ("prospects", "email_key", None), ("enrolments", "state", "invented"),
    ("messages", "state", "invented"), ("messages", "origin", "invented"),
    ("messages", "direction", "invented"), ("compliance", "decision", "invented"),
    ("compliance", "decision", "approved"), ("suppressions", "key_type", "invented"),
    ("dispatch_jobs", "status", "invented"), ("daily_usage", "scope_type", "invented"),
    ("daily_usage", "reserved", -1), ("daily_usage", "accepted", -1),
    ("daily_usage", "unknown", -1), ("usage_events", "state", "invented"),
    ("usage_events", "quantity", -1), ("usage_events", "cost", -1),
)


@pytest.mark.parametrize("table,column,value", CHECK_CASES)
def test_state_and_count_checks(db, graphs, table, column, value):
    """§5: enumerations, pilot bounds, nonnegative counts and dependent fields are CHECKed."""
    with rejected(db, errors.CheckViolation):
        update(db, "outreach_" + table, graphs[0][0][table], {column: value})


@pytest.mark.parametrize("table", ("brands", "settings", "mailboxes",
    "batch_reviews", "sequence_steps", "enrolments", "prospects", "suppressions",
    "unsubscribe_tokens", "messages", "replies", "dispatch_jobs", "daily_usage", "usage_events"))
def test_unique_operation_and_identity_keys(db, graphs, table):
    """§5/F07: fresh UUID cannot duplicate recipient, suppression, review or operation identity."""
    with rejected(db, errors.UniqueViolation):
        insert(db, "outreach_" + table, graphs[0][1][table])


def test_one_live_enrolment_across_campaigns(db, graphs):
    """§5: pending/active prospect uniqueness spans campaigns; paused history is allowed."""
    ids, payloads = graphs[0]
    campaign = insert(db, "outreach_campaigns", {**payloads["campaigns"], "name": "Second"})
    for state in ("pending", "active"):
        with rejected(db, errors.UniqueViolation):
            insert(db, "outreach_enrolments", {**payloads["enrolments"],
                                               "campaign_id": campaign, "state": state})
    insert(db, "outreach_enrolments", {**payloads["enrolments"],
                                       "campaign_id": campaign, "state": "paused"})
    assert ids["enrolments"]


def test_review_count_must_not_exceed_eligible(db, graphs):
    """§5: equal counters are not approval; reviewed cannot exceed eligible even below five."""
    with rejected(db, errors.CheckViolation):
        update(db, "outreach_batch_reviews", graphs[0][0]["batch_reviews"],
               {"eligible_count": 2, "reviewed_count": 3})


@pytest.mark.parametrize("table", ("email_accounts", "aria_actions", "email_outbox", "email_messages")
                                 + tuple("outreach_" + t for t in TABLES))
def test_tenant_parent_unique_keys(db, table):
    """§5: every parent exposes an actual UNIQUE(business_id,id), not only a global PK."""
    db.execute("""SELECT array_agg(a.attname ORDER BY k.ord)
        FROM pg_index i CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY k(attnum,ord)
        JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=k.attnum
        WHERE i.indrelid=to_regclass(%s) AND i.indisunique AND i.indisvalid
          AND i.indpred IS NULL AND i.indexprs IS NULL AND k.ord<=i.indnkeyatts
        GROUP BY i.indexrelid""", ("public." + table,))
    assert ["business_id", "id"] in [r[0] for r in db.fetchall()]


@pytest.mark.parametrize("kind", ("send_outreach", "reply_outreach", "send_email",
                                  "send_invoice_chase", "create_calendar_event", "create_task"))
def test_action_type_extension_preserves_existing_types(db, tenants, kind):
    """F02/§5: shared action CHECK admits outreach without replacing invoice-chase types."""
    insert(db, "aria_actions", {"business_id": tenants[0]["business"], "action_type": kind,
                                "payload": Json({"version": 1}), "expires_at": LATER})


def test_action_type_still_rejects_unknown(db, tenants):
    """§5: extending shared action CHECK must not remove its unknown-type rejection."""
    with rejected(db, errors.CheckViolation):
        insert(db, "aria_actions", {"business_id": tenants[0]["business"],
                                    "action_type": "invented", "payload": Json({}),
                                    "expires_at": LATER})


def test_existing_chase_unchanged_by_outreach_rows(db, tenants):
    """F02/§5: legacy chase payload/status/NULL approver survive outreach insertion unchanged.

    This is a coexistence regression, not a before/after migration rehearsal.
    Stage B must separately snapshot actual pre-037 rows and compare after replay.
    """
    chase = insert(db, "aria_actions", {"business_id": tenants[0]["business"],
        "action_type": "send_invoice_chase", "payload": Json({"invoice_id": "legacy", "stage": 1}),
        "status": "executing", "approved_by": None, "expires_at": LATER})
    db.execute("SELECT row_to_json(a) FROM aria_actions a WHERE id=%s", (chase,))
    before = db.fetchone()[0]
    for kind in ("send_outreach", "reply_outreach"):
        insert(db, "aria_actions", {"business_id": tenants[0]["business"],
                                    "action_type": kind, "payload": Json({}), "expires_at": LATER})
    db.execute("SELECT row_to_json(a) FROM aria_actions a WHERE id=%s", (chase,))
    assert db.fetchone()[0] == before


def test_browser_cannot_forge_shared_authority(db, tenants):
    """F02 database boundary: browser cannot forge grant snapshots or claim a NULL-user action.

    Fresh settings, version/revision/expiry validation and revocation races are
    OUT-6 service tests; a JSON snapshot and a NULL approver are never proof.
    """
    biz = tenants[0]["business"]
    action = insert(db, "aria_actions", {"business_id": biz, "action_type": "send_invoice_chase",
                                         "payload": Json({}), "expires_at": LATER})
    with acting_as(db, "authenticated", tenants[0]["user"]):
        with rejected(db, errors.InsufficientPrivilege):
            update(db, "aria_actions", action, {"status": "executing", "approved_by": None,
                "payload": Json({"authority_type": "automation", "automation": "outreach_sequence",
                                 "authority_revision": 999, "authority_snapshot": {"enabled": True}})})


def test_same_tenant_mailbox_identity_is_not_interchangeable(db, tenants, graphs):
    """§5/F04: two tenant-owned mailboxes cannot be swapped independently of their messages."""
    ids = graphs[0][0]
    second = insert(db, "email_accounts", {"business_id": tenants[0]["business"],
        "user_id": tenants[0]["user"], "provider": "google",
        "email_address": "second@example.invalid", "is_default": False})
    for table in ("replies", "messages", "batch_reviews"):
        with rejected(db, errors.ForeignKeyViolation):
            update(db, "outreach_" + table, ids[table], {"mailbox_id": second})


def test_same_tenant_enrolment_membership_is_not_interchangeable(db, graphs):
    """§5: message's enrolment, campaign, prospect and step must describe the same operation."""
    ids, payloads = graphs[0]
    other = insert(db, "outreach_prospects", {**payloads["prospects"],
        "email": "other@example.invalid", "email_key": "other-digest"})
    with rejected(db, errors.ForeignKeyViolation):
        update(db, "outreach_messages", ids["messages"], {"prospect_id": other})
    campaign = insert(db, "outreach_campaigns", {**payloads["campaigns"], "name": "Other"})
    step = insert(db, "outreach_sequence_steps", {**payloads["sequence_steps"], "campaign_id": campaign})
    for table in ("messages", "dispatch_jobs"):
        with rejected(db, errors.ForeignKeyViolation):
            update(db, "outreach_" + table, ids[table], {"step_id": step})


def test_daily_scope_matches_business_or_owned_account(db, tenants, graphs):
    """§5/F09: daily aggregate scope cannot reference another business or its mailbox."""
    ids, payloads = graphs[0]
    for scope_type, scope_id in (("business", tenants[1]["business"]),
                                 ("mailbox", graphs[1][0]["account"])):
        with rejected(db, (errors.CheckViolation, errors.ForeignKeyViolation)):
            update(db, "outreach_daily_usage", ids["daily_usage"],
                   {"scope_type": scope_type, "scope_id": scope_id})
    insert(db, "outreach_daily_usage", {**payloads["daily_usage"],
        "scope_type": "business", "scope_id": tenants[0]["business"]})


def test_live_claim_requires_mailbox_and_action(db, graphs):
    """§5/F02: live outbound cannot become claimed without its bound mailbox and action."""
    ids = graphs[0][0]
    with rejected(db, errors.CheckViolation):
        update(db, "outreach_messages", ids["messages"], {"state": "claimed"})
    with rejected(db, errors.CheckViolation):
        update(db, "outreach_messages", ids["messages"],
               {"state": "claimed", "action_id": ids["action"], "mailbox_id": None})


def test_default_account_unique_without_recency_selection(db, tenants, graphs):
    """§5/F04: at most one default; no default is legal storage, never permission to guess."""
    ids = graphs[0][0]
    values = {"business_id": tenants[0]["business"], "user_id": tenants[0]["user"],
              "provider": "google", "email_address": "second@example.invalid", "is_default": True}
    with rejected(db, errors.UniqueViolation):
        insert(db, "email_accounts", values)
    update(db, "email_accounts", ids["account"], {"is_default": False})
    second = insert(db, "email_accounts", values)
    update(db, "email_accounts", second, {"is_default": False})
    db.execute("SELECT count(*) FROM email_accounts WHERE business_id=%s AND is_default",
               (tenants[0]["business"],))
    assert db.fetchone()[0] == 0


def test_action_and_provider_message_uniqueness(db, graphs):
    """§5/F07: distinct idempotency keys cannot reuse an action or mailbox/provider identity."""
    ids, payloads = graphs[0]
    update(db, "outreach_messages", ids["messages"], {"action_id": ids["action"],
                                                     "provider_message_id": "accepted-id"})
    for field, value in (("action_id", ids["action"]), ("provider_message_id", "accepted-id")):
        with rejected(db, errors.UniqueViolation):
            insert(db, "outreach_messages", {**payloads["messages"],
                "idempotency_key": str(uuid4()), field: value})


def test_dispatch_message_uniqueness_independent_of_logical_key(db, graphs):
    """§5/F07: changing logical key cannot enqueue the same message a second time."""
    with rejected(db, errors.UniqueViolation):
        insert(db, "outreach_dispatch_jobs", {**graphs[0][1]["dispatch_jobs"],
                                              "logical_key": "different-key"})


def test_cross_tenant_insert_is_rejected(db, graphs):
    """F01: INSERT as elevated backend rejects a foreign prospect, not only UPDATE."""
    with rejected(db, errors.ForeignKeyViolation):
        insert(db, "outreach_evidence", {**graphs[0][1]["evidence"],
                                        "prospect_id": graphs[1][0]["prospects"]})


@pytest.mark.parametrize("ordinal,delay", ((1, 5), (2, 7)))
def test_pilot_followup_delays(db, graphs, ordinal, delay):
    """§5: pilot has exactly initial/5-day/7-day step delays, with valid positive controls."""
    values = {**graphs[0][1]["sequence_steps"], "ordinal": ordinal,
              "delay_business_days": delay}
    step = insert(db, "outreach_sequence_steps", values)
    with rejected(db, errors.CheckViolation):
        update(db, "outreach_sequence_steps", step, {"delay_business_days": 0})


def test_suppression_uniqueness_is_per_digest_version(db, graphs):
    """§5: duplicate suppression blocked, but key rotation can retain both digest versions."""
    insert(db, "outreach_suppressions", {**graphs[0][1]["suppressions"], "digest_version": 2})


def test_provider_id_is_scoped_by_mailbox(db, tenants, graphs):
    """§5/F05: identical provider IDs on distinct owned mailboxes are distinct identities."""
    ids, payloads = graphs[0]
    other = insert(db, "email_accounts", {"business_id": tenants[0]["business"],
        "user_id": tenants[0]["user"], "provider": "google",
        "email_address": "other@example.invalid", "is_default": False})
    update(db, "outreach_messages", ids["messages"], {"provider_message_id": "collision"})
    # A standalone inbound history row has no campaign/enrolment binding.
    insert(db, "outreach_messages", {**payloads["messages"], "mailbox_id": other,
        "campaign_id": None, "enrolment_id": None, "step_id": None, "batch_review_id": None,
        "direction": "inbound", "provider_message_id": "collision", "idempotency_key": "other"})


def test_outbox_reference_is_tenant_and_mailbox_bound(db, tenants, graphs):
    """F01/§5: outreach cannot borrow another tenant's outbox audit row."""
    ids = graphs[1][0]
    outbox = insert(db, "email_outbox", {"business_id": tenants[1]["business"],
        "email_account_id": ids["account"], "to_emails": ["recipient@example.invalid"],
        "subject": "Synthetic chase", "body_preview": "Synthetic", "status": "sent",
        "chase_stage": 1})
    with rejected(db, errors.ForeignKeyViolation):
        update(db, "outreach_messages", graphs[0][0]["messages"], {"outbox_id": outbox})
    # A matching owner/account is a positive control and preserves chase data.
    db.execute("SELECT row_to_json(o) FROM email_outbox o WHERE id=%s", (outbox,))
    before = db.fetchone()[0]
    update(db, "outreach_messages", ids["messages"], {"outbox_id": outbox})
    db.execute("SELECT row_to_json(o) FROM email_outbox o WHERE id=%s", (outbox,))
    assert db.fetchone()[0] == before
