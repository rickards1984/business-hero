"""OUT-7 RED contract. Loopback PostgreSQL only; missing schema is a failure."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import psycopg2
from psycopg2 import errors
import pytest

from test_outreach_schema_rls import (
    DATABASE_URL, acting_as, db, graphs, insert, rejected, tenants, update,
)

# Imported fixtures deliberately share OUT-3's loopback guard and seed graph.
__all__ = ["db", "graphs", "tenants"]
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="RLS_LOCAL_DATABASE_URL unset; no PostgreSQL proof")


def knowledge(t, g):
    return dict(business_id=t["business"], brand_id=g["brands"], topic="availability",
                answer="Weekday appointments", source_reference="https://example.invalid/facts",
                version=1, status="draft", review_due_at="2027-01-01T00:00:00Z")


def slot(t, g):
    return dict(business_id=t["business"], prospect_id=g["prospects"],
                reply_id=g["replies"], mailbox_id=g["account"], action_id=g["action"],
                state="reserved", generation=1, reserved_at="2026-10-23T11:00:00Z")


@pytest.mark.parametrize("table,columns", [("knowledge", 14), ("reply_slots", 18)])
def test_catalogue_and_effective_grants(db, table, columns):
    name = "public.outreach_" + table
    db.execute("SELECT relrowsecurity FROM pg_class WHERE oid=to_regclass(%s)", (name,))
    assert db.fetchone() == (True,)
    db.execute("SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND table_name=%s",
               ("outreach_" + table,))
    assert db.fetchone() == (columns,)
    for role in ("anon", "authenticated", "service_role"):
        for priv in ("SELECT", "INSERT", "UPDATE", "DELETE", "REFERENCES", "TRIGGER", "TRUNCATE"):
            fn = "has_any_column_privilege" if priv in ("SELECT", "INSERT", "UPDATE", "REFERENCES") else "has_table_privilege"
            db.execute(f"SELECT {fn}(%s,%s,%s)", (role, name, priv))
            expected = (role == "service_role" and priv != "TRUNCATE") or (
                role == "authenticated" and table == "knowledge" and priv == "SELECT")
            assert db.fetchone()[0] is expected
    db.execute("SELECT policyname,cmd,roles::text,qual,with_check FROM pg_policies WHERE schemaname='public' AND tablename=%s",
               ("outreach_" + table,))
    policies = db.fetchall()
    assert len(policies) == (1 if table == "knowledge" else 0)
    if policies:
        assert policies[0][:3] == ("outreach_knowledge_member_read", "SELECT", "{authenticated}")
        assert "is_business_member(auth.uid(), business_id)" in policies[0][3]
        assert policies[0][4] is None


def test_member_reads_and_denied_browser_operations(db, tenants, graphs):
    ids = [insert(db, "outreach_knowledge", knowledge(t, g[0])) for t, g in zip(tenants, graphs)]
    sid = insert(db, "outreach_reply_slots", slot(tenants[0], graphs[0][0]))
    for t, kid in zip(tenants, ids):
        with acting_as(db, "authenticated", t["user"]):
            db.execute("SELECT id FROM public.outreach_knowledge")
            assert {str(r[0]) for r in db.fetchall()} == {kid}
    for role in ("anon", "authenticated"):
        with acting_as(db, role, tenants[0]["user"] if role == "authenticated" else None):
            for table, ident, values in (("knowledge", ids[0], knowledge(tenants[0], graphs[0][0])),
                                          ("reply_slots", sid, slot(tenants[0], graphs[0][0]))):
                with rejected(db, errors.InsufficientPrivilege):
                    insert(db, "outreach_" + table, values)
                with rejected(db, errors.InsufficientPrivilege):
                    update(db, "outreach_" + table, ident, {"updated_at": "2026-10-24"})
                with rejected(db, errors.InsufficientPrivilege):
                    db.execute(f"DELETE FROM public.outreach_{table} WHERE id=%s", (ident,))
                if role == "anon" or table == "reply_slots":
                    with rejected(db, errors.InsufficientPrivilege):
                        db.execute(f"SELECT * FROM public.outreach_{table}")


@pytest.mark.parametrize("column,parent", [("prospect_id", "prospects"), ("reply_id", "replies"),
    ("mailbox_id", "account"), ("action_id", "action"), ("message_id", "messages")])
def test_slot_composite_tenant_fks(db, tenants, graphs, column, parent):
    values = slot(tenants[0], graphs[0][0])
    values[column] = graphs[1][0][parent]
    with rejected(db, errors.ForeignKeyViolation):
        insert(db, "outreach_reply_slots", values)


def test_knowledge_brand_tenant_fk_and_version_uniqueness(db, tenants, graphs):
    values = knowledge(tenants[0], graphs[0][0])
    insert(db, "outreach_knowledge", values)
    with rejected(db, errors.UniqueViolation):
        insert(db, "outreach_knowledge", values)
    with rejected(db, errors.ForeignKeyViolation):
        insert(db, "outreach_knowledge", {**values, "brand_id": graphs[1][0]["brands"]})
    insert(db, "outreach_knowledge", {**values, "version": 2})


@pytest.mark.parametrize("changes", [{"version": 0}, {"status": "invented"},
    {"status": "approved"}, {"status": "retired"}, {"topic": ""}, {"answer": ""},
    {"source_reference": ""}])
def test_knowledge_checks(db, tenants, graphs, changes):
    with rejected(db, errors.CheckViolation):
        insert(db, "outreach_knowledge", {**knowledge(tenants[0], graphs[0][0]), **changes})


def test_approved_facts_are_immutable_but_can_retire(db, tenants, graphs):
    values = {**knowledge(tenants[0], graphs[0][0]), "status": "approved",
              "approved_by": tenants[0]["user"], "approved_at": "2026-10-23T11:00:00Z"}
    kid = insert(db, "outreach_knowledge", values)
    for fields in ({"answer": "Unreviewed replacement"}, {"status": "draft"}, {"review_due_at": "2028-01-01"}):
        with rejected(db, errors.CheckViolation):
            update(db, "outreach_knowledge", kid, fields)
    update(db, "outreach_knowledge", kid, {"status": "retired", "retired_at": "2026-10-24T11:00:00Z"})
    with rejected(db, errors.CheckViolation):
        update(db, "outreach_knowledge", kid, {"status": "approved", "retired_at": None})


@pytest.mark.parametrize("changes", [{"state": "invented"}, {"generation": 0},
    {"state": "released"}, {"state": "accepted"}, {"state": "unknown"},
    {"state": "reserved", "released_at": "2026-10-23T11:00:00Z"}])
def test_slot_checks(db, tenants, graphs, changes):
    with rejected(db, errors.CheckViolation):
        insert(db, "outreach_reply_slots", {**slot(tenants[0], graphs[0][0]), **changes})


def test_same_tenant_wrong_mailbox_is_not_a_valid_reply_binding(db, tenants, graphs):
    values = slot(tenants[0], graphs[0][0])
    other = insert(db, "email_accounts", {"business_id": tenants[0]["business"],
        "user_id": tenants[0]["user"], "provider": "google", "email_address": "other@example.invalid"})
    with rejected(db, errors.ForeignKeyViolation):
        insert(db, "outreach_reply_slots", {**values, "mailbox_id": other})


def test_one_slot_under_concurrent_transactions(db, tenants, graphs):
    """Actual two-connection race; committed synthetic parents cleaned in finally."""
    values = slot(tenants[0], graphs[0][0])
    # Distinct reply/action/mailbox identities: only the prospect key can win
    # this race, not the narrower duplicate-reply/action keys.
    t, g = tenants[0], graphs[0][0]
    box = insert(db, 'email_accounts', {'business_id': t['business'], 'user_id': t['user'],
        'provider': 'google', 'email_address': 'second@example.invalid', 'is_default': False})
    inbound = insert(db, 'email_messages', {'business_id': t['business'], 'email_account_id': box,
        'provider_message_id': 'second-inbound', 'provider_thread_id': 'second-thread'})
    from psycopg2.extras import Json
    reply = insert(db, 'outreach_replies', {'business_id': t['business'], 'prospect_id': g['prospects'],
        'mailbox_id': box, 'inbound_email_id': inbound, 'knowledge_refs': Json([]),
        'received_at': '2026-10-23T11:00:00Z'})
    action = insert(db, 'aria_actions', {'business_id': t['business'], 'action_type': 'reply_outreach',
        'payload': Json({'version': 1}), 'expires_at': '2026-10-24T11:00:00Z'})
    candidates = [values, {**values, 'reply_id': reply, 'mailbox_id': box, 'action_id': action}]
    # The parent's shared connection must commit so both workers see its graph.
    db.connection.commit()
    barrier = Barrier(2)

    def reserve(candidate):
        with psycopg2.connect(DATABASE_URL, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute("SET statement_timeout='5s'")
                barrier.wait(timeout=5)
                try:
                    insert(cur, "outreach_reply_slots", {**candidate, "id": str(uuid4())})
                    conn.commit()
                    return "won"
                except errors.UniqueViolation:
                    conn.rollback()
                    return "duplicate"
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(reserve, candidates))
        assert sorted(outcomes) == ["duplicate", "won"]
        db.execute("SELECT count(*) FROM public.outreach_reply_slots WHERE business_id=%s", (tenants[0]["business"],))
        assert db.fetchone() == (1,)
    finally:
        db.connection.rollback()
        for tenant, (g, _) in zip(tenants, graphs):
            for table in ("outreach_reply_slots", "outreach_usage_events", "outreach_daily_usage",
                "outreach_dispatch_jobs", "outreach_replies", "outreach_messages", "outreach_enrolments",
                "outreach_sequence_steps", "outreach_batch_reviews", "outreach_campaigns", "outreach_evidence",
                "outreach_prospects", "outreach_compliance", "outreach_brands", "outreach_mailboxes",
                "outreach_settings", "outreach_suppressions", "outreach_unsubscribe_tokens",
                "email_messages", "aria_actions", "email_accounts", "business_members"):
                db.execute(f"DELETE FROM public.{table} WHERE business_id=%s", (tenant["business"],))
            db.execute("DELETE FROM public.businesses WHERE id=%s", (tenant["business"],))
            db.execute("DELETE FROM auth.users WHERE id=%s", (tenant["user"],))
        db.connection.commit()


def test_only_one_approved_version_and_retire_before_replacement(db, tenants, graphs):
    values = {**knowledge(tenants[0], graphs[0][0]), 'status': 'approved',
              'approved_by': tenants[0]['user'], 'approved_at': '2026-10-23T11:00:00Z'}
    kid = insert(db, 'outreach_knowledge', values)
    with rejected(db, errors.UniqueViolation):
        insert(db, 'outreach_knowledge', {**values, 'version': 2})
    update(db, 'outreach_knowledge', kid, {'status': 'retired', 'retired_at': '2026-10-24T11:00:00Z'})
    insert(db, 'outreach_knowledge', {**values, 'version': 2})


@pytest.mark.parametrize('state', ['reserved', 'accepted', 'unknown', 'released'])
def test_valid_slot_states_and_message_action_binding(db, tenants, graphs, state):
    from psycopg2.extras import Json
    g = graphs[0][0]
    update(db, 'outreach_messages', g['messages'], {'action_id': g['action']})
    values = {**slot(tenants[0], g), 'state': state}
    if state in ('accepted', 'unknown'):
        values.update(message_id=g['messages'], payload_hash='a' * 64,
                      dispatched_at='2026-10-23T11:01:00Z')
    if state == 'accepted':
        values.update(settled_at='2026-10-23T11:02:00Z')
    if state == 'released':
        values.update(settled_at='2026-10-23T11:02:00Z', released_at='2026-10-23T11:02:00Z',
                      release_reason='definitely_not_accepted', outcome_evidence=Json({'source': 'synthetic rejection'}))
    insert(db, 'outreach_reply_slots', values)
