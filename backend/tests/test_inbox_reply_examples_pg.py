"""046 (ARIA-1b): the reply-examples table, against the local PostgreSQL harness."""
import os

import pytest
from sqlalchemy import create_engine, text

URL = os.environ.get("RLS_LOCAL_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="RLS_LOCAL_DATABASE_URL not set (scripts/rls-local.sh up). A skip is not a pass.")


@pytest.fixture
def pg():
    engine = create_engine(URL)
    yield engine
    engine.dispose()


def test_the_table_is_backend_only(pg):
    with pg.connect() as c:
        assert c.execute(text("SELECT relrowsecurity FROM pg_class WHERE oid = 'public.inbox_reply_examples'::regclass")).scalar()
        assert c.execute(text("SELECT count(*) FROM information_schema.role_table_grants WHERE table_schema='public' "
                              "AND table_name='inbox_reply_examples' AND grantee IN ('anon','authenticated','service_role')")).scalar() == 0


@pytest.mark.parametrize("category,draft,sent,ok", [
    ("new_enquiry", "Hi", "Hi there", True),
    ("money", "Hi", "Hi", False),                     # only the categories Aria drafts for
    ("customer", "", "Hi", False),                    # never empty
    ("complaint", "x" * 10001, "Hi", False),          # bounded
])
def test_rows_are_checked(pg, category, draft, sent, ok):
    with pg.connect() as c:
        tx = c.begin()
        try:
            biz = c.execute(text("INSERT INTO businesses (name, api_key) VALUES ('046 test', "
                                 "'test-' || gen_random_uuid()) RETURNING id")).scalar()   # rolled back below
            c.execute(text("INSERT INTO inbox_reply_examples (business_id, category, draft_body, sent_body, edited) "
                           "VALUES (:b, :c, :d, :s, true)"), {"b": biz, "c": category, "d": draft, "s": sent})
            assert ok
        except AssertionError:
            raise
        except Exception:
            assert not ok
        finally:
            tx.rollback()


def test_a_business_deleted_takes_its_examples_with_it(pg):
    with pg.connect() as c:
        tx = c.begin()
        try:
            biz = c.execute(text("INSERT INTO businesses (name, api_key) VALUES ('046 test', "
                                 "'test-' || gen_random_uuid()) RETURNING id")).scalar()
            c.execute(text("INSERT INTO inbox_reply_examples (business_id, category, draft_body, sent_body, edited) "
                           "VALUES (:b, 'customer', 'd', 's', false)"), {"b": biz})
            c.execute(text("DELETE FROM businesses WHERE id = :b"), {"b": biz})
            assert c.execute(text("SELECT count(*) FROM inbox_reply_examples WHERE business_id = :b"), {"b": biz}).scalar() == 0
        finally:
            tx.rollback()
