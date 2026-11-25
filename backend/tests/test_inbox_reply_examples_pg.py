"""046 (ARIA-1b): the reply-examples table on real PostgreSQL.
Loopback harness only (scripts/rls-local.sh); every row is written inside a
transaction that is rolled back."""
import os
from urllib.parse import urlparse

import pytest

URL = os.getenv("RLS_LOCAL_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not URL, reason="RLS_LOCAL_DATABASE_URL is not set. A skip is not a pass.")
if URL and urlparse(URL).hostname not in ("127.0.0.1", "localhost", "::1"):
    raise RuntimeError("REFUSING TO RUN: loopback only")      # never production (Codex 046 review 1)

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402


@pytest.fixture
def c():
    engine = create_engine(URL)
    with engine.connect() as conn:
        tx = conn.begin()
        try:
            yield conn
        finally:
            tx.rollback()
    engine.dispose()


def business(c):
    return c.execute(text("INSERT INTO businesses (name, api_key) VALUES ('046 test', 'test-' || gen_random_uuid()) "
                          "RETURNING id")).scalar()


def example(c, biz, **kw):
    row = dict(business_id=biz, category="customer", email_message_id=None, incoming_subject="Roof",
               incoming_excerpt="Can you quote?", draft_body="Hi", sent_body="Hi there", edited=True)
    row.update(kw)
    return c.execute(text("""INSERT INTO inbox_reply_examples (business_id, category, email_message_id,
        incoming_subject, incoming_excerpt, draft_body, sent_body, edited)
        VALUES (:business_id, :category, :email_message_id, :incoming_subject, :incoming_excerpt, :draft_body,
                :sent_body, :edited) RETURNING id"""), row).scalar()


def refused(c, biz, constraint_word, **kw):
    """The insert is refused by this table's own rule, not by anything else."""
    c.execute(text("SAVEPOINT attempt"))
    with pytest.raises(IntegrityError) as exc:
        example(c, biz, **kw)
    c.execute(text("ROLLBACK TO SAVEPOINT attempt"))
    assert constraint_word in str(exc.value.orig), str(exc.value.orig)


def test_the_table_is_backend_only(c):
    assert c.execute(text("SELECT relrowsecurity FROM pg_class WHERE oid = 'public.inbox_reply_examples'::regclass")).scalar()
    assert c.execute(text("SELECT count(*) FROM information_schema.role_table_grants WHERE table_schema='public' "
                          "AND table_name='inbox_reply_examples' AND grantee IN ('anon','authenticated','service_role')"
                          )).scalar() == 0


def test_a_good_row_is_accepted(c):
    assert example(c, business(c))


@pytest.mark.parametrize("kw", [
    dict(category="money"), dict(category="fyi"),                                      # only what Aria drafts for
    dict(draft_body=""), dict(sent_body=""),                                           # never empty
    dict(draft_body="x" * 10001), dict(sent_body="x" * 10001),                         # bounded
    dict(incoming_subject="x" * 501), dict(incoming_excerpt="x" * 2001),
])
def test_rows_breaking_a_rule_are_refused(c, kw):
    refused(c, business(c), "inbox_reply_examples", **kw)


@pytest.mark.parametrize("kw", [dict(incoming_subject="x" * 500), dict(incoming_excerpt="x" * 2000),
                                dict(draft_body="x" * 10000), dict(incoming_subject=None, incoming_excerpt=None)])
def test_the_limits_themselves_are_allowed(c, kw):
    assert example(c, business(c), **kw)


def test_an_unknown_business_or_email_is_refused(c):
    biz = business(c)
    refused(c, "00000000-0000-4000-8000-000000000000", "foreign key")
    refused(c, biz, "foreign key", email_message_id="00000000-0000-4000-8000-000000000000")


def test_deleting_the_business_deletes_its_examples(c):
    biz = business(c)
    example(c, biz)
    c.execute(text("DELETE FROM businesses WHERE id = :b"), {"b": biz})
    assert c.execute(text("SELECT count(*) FROM inbox_reply_examples WHERE business_id = :b"), {"b": biz}).scalar() == 0


def test_deleting_the_email_deletes_its_copied_text(c):
    """Codex 046 review 1, finding 4: SET NULL left the copied subject,
    excerpt and reply bodies behind."""
    biz = business(c)
    user = c.execute(text("INSERT INTO auth.users (id, email) VALUES (gen_random_uuid(), 'owner@046.example') "
                          "RETURNING id")).scalar()
    account = c.execute(text("INSERT INTO email_accounts (business_id, user_id, provider, email_address) "
                             "VALUES (:b, :u, 'google', 'owner@046.example') RETURNING id"),
                        {"b": biz, "u": user}).scalar()
    email = c.execute(text("INSERT INTO email_messages (business_id, email_account_id, provider_message_id) "
                           "VALUES (:b, :a, 'pm-046') RETURNING id"), {"b": biz, "a": account}).scalar()
    example(c, biz, email_message_id=email)
    c.execute(text("DELETE FROM email_messages WHERE id = :e"), {"e": email})
    assert c.execute(text("SELECT count(*) FROM inbox_reply_examples WHERE business_id = :b"), {"b": biz}).scalar() == 0
