"""MAIL-1 — the default mailbox under real concurrency, on real Postgres.

Codex review 1 (P1): two OAuth callbacks finishing together could both see
"no default" and each mark their own mailbox, and the only thing stopping it
was migration 037's partial unique index, which main does not have. Two
"Make default" presses together had the same hole. The fix is a per-business
transaction lock; these tests prove it holds WITHOUT any unique index.

Runs against the local Supabase Postgres from `scripts/rls-local.sh up`
(skipped without RLS_LOCAL_DATABASE_URL; loopback only; torn down).
"""

import os
import threading
import uuid
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

USER = "aaaaaaaa-0000-4000-8000-0000000003aa"
BIZ = "aaaaaaaa-3333-4333-8333-33333333331a"
ROUNDS = 15


@pytest.fixture
def eng():
    from sqlalchemy import create_engine, text
    e = create_engine(DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1), pool_size=6)
    _teardown(e)
    with e.begin() as c:
        c.execute(text("INSERT INTO auth.users (id, email, aud, role) VALUES "
                       "(:u, 'mail1@example.invalid', 'authenticated', 'authenticated')"), {"u": USER})
        c.execute(text("INSERT INTO public.businesses (id, name, api_key, plan_tier) "
                       "VALUES (:b, 'Mail1', :k, 'pro')"), {"b": BIZ, "k": f"mail1-{uuid.uuid4()}"})
        # Prove the point: no unique index may do the work for us. The local
        # harness may have 037 replayed; set its index aside for this test only.
        rows = c.execute(text(
            "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' "
            "AND tablename = 'email_accounts' AND indexdef ILIKE '%UNIQUE%' "
            "AND indexdef ILIKE '%is_default%'")).fetchall()
        for name, _ in rows:
            c.execute(text(f'DROP INDEX public."{name}"'))
    try:
        yield e
    finally:
        _teardown(e)
        with e.begin() as c:
            for _, definition in rows:
                c.execute(text(definition))
    e.dispose()


def _teardown(e):
    from sqlalchemy import text
    with e.begin() as c:
        c.execute(text("DELETE FROM public.email_accounts WHERE business_id = :b"), {"b": BIZ})
        c.execute(text("DELETE FROM public.businesses WHERE id = :b"), {"b": BIZ})
        c.execute(text("DELETE FROM auth.users WHERE id = :u"), {"u": USER})


def _clear(e):
    from sqlalchemy import text
    with e.begin() as c:
        c.execute(text("DELETE FROM public.email_accounts WHERE business_id = :b"), {"b": BIZ})


def _add(e, addr, default=False):
    from sqlalchemy import text
    with e.begin() as c:
        return str(c.execute(text(
            "INSERT INTO public.email_accounts (business_id, user_id, provider, email_address, is_default) "
            "VALUES (:b, :u, 'google', :e, :d) RETURNING id"),
            {"b": BIZ, "u": USER, "e": addr, "d": default}).scalar())


def _defaults(e):
    from sqlalchemy import text
    with e.connect() as c:
        return [str(r[0]) for r in c.execute(text(
            "SELECT id FROM public.email_accounts WHERE business_id = :b AND is_default"), {"b": BIZ})]


def _together(*jobs):
    errors = []

    def wrap(job):
        try:
            job()
        except Exception as exc:  # noqa: BLE001 - collected and asserted
            errors.append(exc)
    threads = [threading.Thread(target=wrap, args=(j,)) for j in jobs]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    return errors


def test_two_first_connections_at_once_leave_exactly_one_default(eng):
    from sqlmodel import Session
    from app.email.mailboxes import ensure_default_after_connect, mailboxes_before
    for n in range(ROUNDS):
        _clear(eng)
        looked, saved = threading.Barrier(2), threading.Barrier(2)

        def callback(addr):
            with Session(eng) as s:
                before = mailboxes_before(s, BIZ)
            looked.wait(10)
            _add(eng, addr)
            saved.wait(10)
            with Session(eng) as s:
                ensure_default_after_connect(s, BIZ, addr, "google", before)
        errors = _together(lambda: callback(f"one-{n}@example.invalid"),
                           lambda: callback(f"two-{n}@example.invalid"))
        assert not errors, errors
        assert len(_defaults(eng)) == 1, f"round {n}"


def test_two_make_default_presses_at_once_leave_exactly_one_default(eng):
    from sqlmodel import Session
    from app.email.mailboxes import set_default
    for n in range(ROUNDS):
        _clear(eng)
        _add(eng, f"zero-{n}@example.invalid", default=True)
        one, two = _add(eng, f"one-{n}@example.invalid"), _add(eng, f"two-{n}@example.invalid")
        go = threading.Barrier(2)

        def press(target):
            go.wait(10)
            with Session(eng) as s:
                set_default(s, BIZ, target)
        errors = _together(lambda: press(one), lambda: press(two))
        assert not errors, errors
        assert len(_defaults(eng)) == 1 and _defaults(eng)[0] in (one, two), f"round {n}"
