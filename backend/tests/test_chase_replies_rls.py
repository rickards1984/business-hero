"""AUTO-2 — migration 036 (`chase_replies`) on real Postgres.

Runs against the local Supabase Postgres from `scripts/rls-local.sh up`, with
035 and 036 replayed (skipped without RLS_LOCAL_DATABASE_URL, like
test_tenant_isolation_rls_path.py, whose header explains what a green run
does and does not prove). Loopback only; every write is rolled back or torn
down.

What 036 must guarantee:
  * members of a business can READ its replies; nobody else can, anon nothing;
  * browsers cannot write at all — replies are written by the backend only;
  * one row per business per inbound message;
  * status and category are from the fixed lists;
  * a reply outlives its email message (deleting the message must not lift a
    pause silently: the link is set to NULL, the reply stays).
"""

import os
import uuid
from contextlib import contextmanager
from urllib.parse import urlparse

import pytest

DATABASE_URL = os.getenv("RLS_LOCAL_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="RLS_LOCAL_DATABASE_URL is not set: `scripts/rls-local.sh up`, then run this file. "
           "A skip here is a skip, not a pass.",
)

if DATABASE_URL:
    _host = urlparse(DATABASE_URL).hostname
    if _host not in ("127.0.0.1", "localhost", "::1"):
        raise RuntimeError(f"REFUSING TO RUN: RLS_LOCAL_DATABASE_URL points at {_host!r}. Loopback only.")
    import psycopg2
    import psycopg2.errors

USER_A = "aaaaaaaa-0000-4000-8000-0000000002aa"
USER_B = "bbbbbbbb-0000-4000-8000-0000000002bb"
BIZ_A = "aaaaaaaa-2222-4222-8222-22222222222a"
BIZ_B = "bbbbbbbb-2222-4222-8222-22222222222b"


@pytest.fixture(scope="module")
def db():
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    _teardown(conn)
    seeded = _seed(conn)
    yield conn, seeded
    _teardown(conn)
    conn.close()


def _seed(conn):
    s = {}
    with conn.cursor() as cur:
        for uid, email in ((USER_A, "auto2-a@example.invalid"), (USER_B, "auto2-b@example.invalid")):
            cur.execute("INSERT INTO auth.users (id, email, aud, role) "
                        "VALUES (%s, %s, 'authenticated', 'authenticated')", (uid, email))
        cur.execute("INSERT INTO public.businesses (id, name, api_key, plan_tier) VALUES "
                    "(%s, 'Auto2 A', %s, 'pro'), (%s, 'AUTO2-B-PRIVATE', %s, 'pro')",
                    (BIZ_A, f"auto2-{uuid.uuid4()}", BIZ_B, f"auto2-{uuid.uuid4()}"))
        cur.execute("INSERT INTO public.business_members (business_id, user_id, role, is_active) "
                    "VALUES (%s, %s, 'owner', true), (%s, %s, 'owner', true)",
                    (BIZ_A, USER_A, BIZ_B, USER_B))
        for tag, biz, uid in (("a", BIZ_A, USER_A), ("b", BIZ_B, USER_B)):
            cur.execute("INSERT INTO public.email_accounts (business_id, user_id, provider, "
                        "email_address, is_default) VALUES (%s, %s, 'google', %s, true) RETURNING id",
                        (biz, uid, f"owner-{tag}@example.invalid"))
            s[f"acct_{tag}"] = str(cur.fetchone()[0])
            cur.execute("INSERT INTO public.email_messages (business_id, email_account_id, "
                        "provider_message_id, from_email, snippet) VALUES (%s, %s, %s, "
                        "'pay@harper.example', %s) RETURNING id",
                        (biz, s[f"acct_{tag}"], f"auto2-{tag}-1",
                         "AUTO2-B-PRIVATE-MAIL" if tag == "b" else "paid"))
            s[f"msg_{tag}"] = str(cur.fetchone()[0])
            cur.execute("INSERT INTO public.chase_replies (business_id, email_message_id, "
                        "customer_email, invoice_ids, category, summary) VALUES (%s, %s, "
                        "'pay@harper.example', '[]'::jsonb, 'paid', %s) RETURNING id",
                        (biz, s[f"msg_{tag}"], "AUTO2-B-PRIVATE-SUMMARY" if tag == "b" else "A"))
            s[f"reply_{tag}"] = str(cur.fetchone()[0])
    return s


def _teardown(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.chase_replies')")
        if cur.fetchone()[0]:
            cur.execute("DELETE FROM public.chase_replies WHERE business_id IN (%s, %s)", (BIZ_A, BIZ_B))
        for table in ("email_messages", "email_accounts", "business_members"):
            cur.execute(f"DELETE FROM public.{table} WHERE business_id IN (%s, %s)", (BIZ_A, BIZ_B))
        cur.execute("DELETE FROM public.businesses WHERE id IN (%s, %s)", (BIZ_A, BIZ_B))
        cur.execute("DELETE FROM auth.users WHERE id IN (%s, %s)", (USER_A, USER_B))


@contextmanager
def acting_as(role, user_id=None):
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    try:
        cur = conn.cursor()
        if user_id:
            cur.execute("SELECT set_config('request.jwt.claim.sub', %s, true)", (user_id,))
            cur.execute("SELECT set_config('request.jwt.claims', %s, true)",
                        ('{"sub": "%s", "role": "%s"}' % (user_id, role),))
        cur.execute(f"SET LOCAL ROLE {role}")
        yield cur
    finally:
        conn.rollback()
        conn.close()


@contextmanager
def as_owner():
    """The backend's posture: table owner with BYPASSRLS. Rolled back."""
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    try:
        yield conn.cursor()
    finally:
        conn.rollback()
        conn.close()


def test_rls_is_on(db):
    conn, _ = db
    with conn.cursor() as cur:
        cur.execute("SELECT relrowsecurity FROM pg_class WHERE oid = 'public.chase_replies'::regclass")
        assert cur.fetchone()[0] is True


def test_a_member_reads_only_their_own_replies(db):
    _, s = db
    with acting_as("authenticated", USER_A) as cur:
        cur.execute("SELECT id, summary FROM public.chase_replies")
        got = cur.fetchall()
    assert [str(r[0]) for r in got] == [s["reply_a"]]
    assert "AUTO2-B-PRIVATE" not in repr(got)


def test_anon_reads_nothing(db):
    with acting_as("anon") as cur:
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            cur.execute("SELECT 1 FROM public.chase_replies")


@pytest.mark.parametrize("sql", [
    "UPDATE public.chase_replies SET status = 'stopped' WHERE id = %(own)s",
    "DELETE FROM public.chase_replies WHERE id = %(own)s",
    "INSERT INTO public.chase_replies (business_id, email_message_id, customer_email, invoice_ids, "
    "category) VALUES (%(biz)s, %(msg)s, 'x@y.example', '[]'::jsonb, 'other')",
])
def test_browsers_cannot_write_even_their_own_business(db, sql):
    _, s = db
    with acting_as("authenticated", USER_A) as cur:
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            cur.execute(sql, {"own": s["reply_a"], "biz": BIZ_A, "msg": s["msg_a"]})


def test_one_reply_per_business_per_message(db):
    _, s = db
    with as_owner() as cur:
        with pytest.raises(psycopg2.errors.UniqueViolation):
            cur.execute("INSERT INTO public.chase_replies (business_id, email_message_id, "
                        "customer_email, invoice_ids, category) VALUES (%s, %s, "
                        "'pay@harper.example', '[]'::jsonb, 'other')", (BIZ_A, s["msg_a"]))


@pytest.mark.parametrize("column,value", [("status", "deleted"), ("category", "refund_them")])
def test_status_and_category_come_from_the_lists(db, column, value):
    _, s = db
    with as_owner() as cur:
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute(f"UPDATE public.chase_replies SET {column} = %s WHERE id = %s",
                        (value, s["reply_a"]))


@pytest.mark.parametrize("category", ["paid", "promise", "dispute", "question", "other", "unknown"])
def test_every_listed_category_is_accepted(db, category):
    _, s = db
    with as_owner() as cur:
        cur.execute("UPDATE public.chase_replies SET category = %s WHERE id = %s",
                    (category, s["reply_a"]))


def test_deleting_the_email_keeps_the_reply(db):
    _, s = db
    with as_owner() as cur:
        cur.execute("DELETE FROM public.email_messages WHERE id = %s", (s["msg_a"],))
        cur.execute("SELECT email_message_id, status FROM public.chase_replies WHERE id = %s",
                    (s["reply_a"],))
        assert cur.fetchone() == (None, "open")


def test_deleting_the_business_removes_its_replies(db):
    _, s = db
    with as_owner() as cur:
        cur.execute("DELETE FROM public.chase_replies WHERE business_id = %s AND id <> %s",
                    (BIZ_B, s["reply_b"]))
        cur.execute("DELETE FROM public.email_messages WHERE business_id = %s", (BIZ_B,))
        cur.execute("DELETE FROM public.email_accounts WHERE business_id = %s", (BIZ_B,))
        cur.execute("DELETE FROM public.business_members WHERE business_id = %s", (BIZ_B,))
        cur.execute("DELETE FROM public.businesses WHERE id = %s", (BIZ_B,))
        cur.execute("SELECT count(*) FROM public.chase_replies WHERE business_id = %s", (BIZ_B,))
        assert cur.fetchone()[0] == 0
