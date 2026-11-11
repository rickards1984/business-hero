"""OUT-23 Part B on real PostgreSQL (the local harness, migration 042):
the tables' shape and permissions, the JSONB and numeric SQL, the footer's
acquisition query, and the lock order (R3.4) proven by pg_blocking_pids.
Skips without the harness; a skip is not a pass."""
# ruff: noqa: F811 - the pg fixture is a parameter by design
import hashlib
import json
import threading
import time
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlmodel import Session

from test_outreach_send_rls import DATABASE_URL, OWNER, _count, _propose, pg  # noqa: F401
from test_outreach_send import A, BRAND, LIA, NOW, PROSPECT, STAMP

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="RLS_LOCAL_DATABASE_URL is not set")

KEY = "hunterTESTkey0123456789abcdef"


def hunter():
    from services import outreach_hunter
    return outreach_hunter


class Fake:
    def __call__(self, method, path, params, key, timeout):
        assert key == KEY
        return 200, {"data": {"plan_name": "Starter", "reset_date": "2026-11-15",
                              "requests": {"credits": {"used": 1, "available": 100}}}}, {}


@pytest.fixture
def hpg(pg, monkeypatch):
    from cryptography.fernet import Fernet
    from app.email import crypto
    from services import outreach_setup
    with pg.engine.connect() as c:
        if not c.execute(text("SELECT to_regclass('public.outreach_provider_accounts')")).scalar():
            pytest.skip("migration 042 is not applied in the local harness")
    monkeypatch.setattr(crypto, "_EMAIL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(outreach_setup, "now", lambda: NOW)
    monkeypatch.setattr(outreach_setup, "_authority", lambda session, business, user: None)
    yield pg


def _connected(pg):
    with Session(pg.engine) as s:
        return hunter().connect(s, pg.b, OWNER, KEY, transport=Fake())


def test_042_tables_are_backend_only(hpg):
    with hpg.engine.connect() as c:
        for table in ("outreach_provider_accounts", "outreach_provider_charges"):
            assert c.execute(text("SELECT relrowsecurity FROM pg_class WHERE relname = :t"), {"t": table}).scalar() is True
            assert c.execute(text("SELECT count(*) FROM information_schema.role_table_grants WHERE table_name = :t "
                                  "AND grantee IN ('anon', 'authenticated', 'service_role')"), {"t": table}).scalar() == 0
            assert c.execute(text("SELECT count(*) FROM pg_policies WHERE tablename = :t"), {"t": table}).scalar() == 0


def test_connect_disconnect_and_reconnect_on_postgres(hpg):
    out = _connected(hpg)
    assert out["connected"] and out["pools"]["model"] == "single"
    with Session(hpg.engine) as s:
        hunter().disconnect(s, hpg.b, OWNER)
    out = _connected(hpg)
    assert out["connected"]
    row = _count(hpg, "SELECT generation FROM outreach_provider_accounts WHERE business_id = :b", b=A)
    assert row == 3
    assert KEY not in json.dumps(_count(hpg, "SELECT row_to_json(a)::text FROM outreach_provider_accounts a "
                                             "WHERE business_id = :b", b=A))


def test_the_ledger_on_postgres_numeric(hpg):
    _connected(hpg)
    with Session(hpg.engine) as s:
        hunter()._lock(s, A)
        conn = hunter().connection(s, A)
        search = hunter().reserve(s, A, BRAND, conn, "search", NOW)[0]
        verify = hunter().reserve(s, A, BRAND, conn, "verify", NOW)[0]
        s.commit()
    from decimal import Decimal
    with Session(hpg.engine) as s:
        hunter().settle(s, A, search, (Decimal("0"), "credit"))
        hunter().settle(s, A, verify, (Decimal("0.5"), "credit"))
    with Session(hpg.engine) as s:
        assert hunter().used_credits(s, A, BRAND, NOW) == Decimal("0.5")
    with Session(hpg.engine) as s:
        hunter()._lock(s, A)
        stale = hunter().reserve(s, A, BRAND, hunter().connection(s, A), "search", NOW)[0]
        s.execute(text("UPDATE outreach_provider_charges SET created_at = :t WHERE id = :i"),
                  {"t": NOW - timedelta(hours=2), "i": stale})
        s.commit()
    with Session(hpg.engine) as s:
        assert hunter().sweep(s) == 1


def test_the_footer_query_reads_the_acquisition_row_on_postgres(hpg):
    with hpg.engine.begin() as c:
        c.execute(text("INSERT INTO outreach_evidence (business_id, prospect_id, source_type, operation, source_url, "
                       "fact_type, fact_value, flags, fetched_at, expires_at) VALUES (:b, :p, 'hunter', 'verify', "
                       "'https://example.invalid/people', 'acquisition', 'hunter', '[]'::jsonb, :f, :e)"),
                  {"b": A, "p": PROSPECT, "f": STAMP, "e": NOW + timedelta(days=7)})
        c.execute(text("UPDATE outreach_compliance SET sources = '[\"public_websites\", \"hunter.io\"]'::jsonb WHERE id = :l"),
                  {"l": LIA})
        notice = "Synthetic notice."
        doc = {"outreach_privacy": {BRAND: {"version": 1, "text": notice}},
               "outreach_hunter": {"brands": {BRAND: {"enabled": True, "notice": {
                   "by": OWNER, "hash": hashlib.sha256(notice.encode()).hexdigest()}}}}}
        c.execute(text("UPDATE business_settings SET settings = CAST(:s AS jsonb) WHERE business_id = :b"),
                  {"s": json.dumps(doc), "b": A})
    card = _propose(hpg)
    assert "(found via Hunter.io, a business contact database)" in card["preview"]["footer"]


def _blocked_by(pg, holder_pid, other_pid, thread, seconds=10):
    deadline = time.monotonic() + seconds
    with pg.engine.connect() as watch:
        while time.monotonic() < deadline and thread.is_alive():
            if holder_pid in (watch.execute(text("SELECT pg_blocking_pids(:p)"), {"p": other_pid}).scalar() or []):
                return True
            time.sleep(0.05)
    return False


@pytest.mark.parametrize("writer", ["settle", "sweep", "disconnect"])
def test_every_hunter_writer_waits_on_the_business_lock(hpg, writer):
    """R3.4: research holds the business lock (as a run's reservation does);
    each Hunter writer waits for it rather than racing or deadlocking."""
    _connected(hpg)
    with Session(hpg.engine) as s:
        hunter()._lock(s, A)
        charge = hunter().reserve(s, A, BRAND, hunter().connection(s, A), "search", NOW)[0]
        s.execute(text("UPDATE outreach_provider_charges SET created_at = :t WHERE id = :i"),
                  {"t": NOW - timedelta(hours=2), "i": charge})
        s.commit()
    pids, done = {}, {}
    with hpg.engine.connect() as hold_conn, Session(bind=hold_conn) as holder:
        hunter()._lock(holder, A)
        pids["holder"] = holder.execute(text("SELECT pg_backend_pid()")).scalar()

        def run():
            with hpg.engine.connect() as conn, Session(bind=conn) as s:
                pids["other"] = s.execute(text("SELECT pg_backend_pid()")).scalar()
                s.rollback()
                from decimal import Decimal
                if writer == "settle":
                    hunter().settle(s, A, charge, (Decimal("1"), "credit"))
                elif writer == "sweep":
                    hunter().sweep(s)
                else:
                    hunter().disconnect(s, hpg.b, OWNER)
                done["ok"] = True
        t = threading.Thread(target=run)
        t.start()
        while "other" not in pids and t.is_alive():
            time.sleep(0.01)
        assert _blocked_by(hpg, pids["holder"], pids["other"], t), f"{writer} did not wait on the business lock"
        holder.rollback()
    t.join(10)
    assert done.get("ok") and not t.is_alive()
