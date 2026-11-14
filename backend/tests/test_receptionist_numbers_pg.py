"""RCP-1 on real PostgreSQL (the local harness, migration 043): the uuid and
timestamptz SQL, both unique indexes, the running-cost line, and two approves
racing for one request. Skips without the harness; a skip is not a pass."""
import threading
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlmodel import Session

import test_receptionist_numbers as base
from test_outreach_send_rls import DATABASE_URL

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="RLS_LOCAL_DATABASE_URL is not set")

A, B = "a1c0ffee-0000-4000-8000-00000000000a", "a1c0ffee-0000-4000-8000-00000000000b"
PERIOD = "2026-11"


def _clean(engine, meters):
    with engine.begin() as c:
        c.execute(text("DELETE FROM public.receptionist_number_requests WHERE business_id IN (:a, :b)"), {"a": A, "b": B})
        c.execute(text("DELETE FROM public.receptionist_configs WHERE business_id IN (:a, :b)"), {"a": A, "b": B})
        c.execute(text("DELETE FROM public.businesses WHERE id IN (:a, :b)"), {"a": A, "b": B})
        if meters is not None:
            c.execute(text("DELETE FROM public.platform_meters WHERE period = :p"), {"p": PERIOD})
            for meter, value, at in meters:
                c.execute(text("INSERT INTO public.platform_meters (period, meter, value, updated_at) "
                               "VALUES (:p, :m, :v, :at)"), {"p": PERIOD, "m": meter, "v": value, "at": at})


@pytest.fixture
def pg(monkeypatch):
    engine = create_engine(DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1), pool_size=8)
    with engine.connect() as c:
        if not c.execute(text("SELECT to_regclass('public.receptionist_number_requests')")).scalar():
            pytest.skip("migration 043 is not applied in the local harness")
        has_meters = c.execute(text("SELECT to_regclass('public.platform_meters')")).scalar()
        meters = c.execute(text("SELECT meter, value, updated_at FROM public.platform_meters WHERE period = :p"),
                           {"p": PERIOD}).all() if has_meters else None
    _clean(engine, None)
    with engine.begin() as c:
        for bid in (A, B):
            c.execute(text("INSERT INTO public.businesses (id, name, api_key, plan_tier, subscription_status, is_active, "
                           "feature_flags) VALUES (:b, 'RCP-1 test', :k, 'pro', 'active', true, '{}'::jsonb)"),
                      {"b": bid, "k": f"rcp1-{uuid.uuid4()}"})
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://api.example.invalid")
    fake = base.FakeTwilio()
    fake.emails = []
    monkeypatch.setattr(base.rn(), "twilio", lambda: fake)
    monkeypatch.setattr(base.rn(), "_send_owner_email", lambda *a: True)
    try:
        yield type("PG", (), {"engine": engine, "tw": fake, "has_meters": bool(has_meters)})
    finally:
        _clean(engine, meters if has_meters else None)
        engine.dispose()


def test_request_approve_and_go_live_on_postgres(pg):
    out = base.request(pg.engine, A)
    assert out["state"] == "requested" and out["created_at"].endswith("+00:00")
    done = base.approve(pg.engine, out["id"])
    assert done["state"] == "live" and done["phone_number"] == base.NUMBER
    with pg.engine.connect() as c:
        number, sid = c.execute(text("SELECT twilio_phone_number, twilio_phone_sid FROM public.receptionist_configs "
                                     "WHERE business_id = :b"), {"b": A}).one()
        live_at = c.execute(text("SELECT live_at FROM public.receptionist_number_requests WHERE id = :i"),
                            {"i": out["id"]}).scalar()
    assert (number, sid) == (base.NUMBER, done["number_sid"]) and isinstance(live_at, datetime)
    if pg.has_meters:
        with Session(pg.engine) as s:
            from services import running_costs
            items = {i["name"]: i["pence"] for i in running_costs.items(s, PERIOD)}
        assert items[base.rn().COST_NAME] == 98


def test_the_unique_index_refuses_one_number_for_two_businesses(pg):
    with Session(pg.engine) as s:
        base.rn().assign(s, A, base.NUMBER, None)
        s.commit()
    with pg.engine.begin() as c, pytest.raises(Exception) as exc:
        c.execute(text("INSERT INTO public.receptionist_configs (business_id, twilio_phone_number) VALUES (:b, :n)"),
                  {"b": B, "n": base.NUMBER})
    assert "uq_receptionist_configs_twilio_phone_number" in str(exc.value)


def test_the_open_request_index_allows_one_per_business(pg):
    base.request(pg.engine, A)
    row = dict(id=str(uuid.uuid4()), b=A, at=datetime.now(timezone.utc))
    with pg.engine.begin() as c, pytest.raises(Exception) as exc:
        c.execute(text("INSERT INTO public.receptionist_number_requests (id, business_id, state, mode, legal_name, "
                       "address_line1, city, postcode, setup, in_plan) VALUES (:id, :b, 'requested', 'new_local', "
                       "'x', 'x', 'x', 'x', 'self', true)"), row)
    assert "uq_receptionist_number_requests_open" in str(exc.value)


def test_two_approves_racing_buy_one_number(pg):
    out = base.request(pg.engine, A)
    base.prepare(pg.engine, out["id"])
    version = base.row(pg.engine, out["id"])["version"]
    start, results = threading.Barrier(2), []

    def go():
        start.wait()
        try:
            results.append(base.approve(pg.engine, out["id"], version=version, check=False)["state"])
        except base.refused() as exc:
            results.append(exc.status_code)
    threads = [threading.Thread(target=go) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert sorted(map(str, results)) == ["409", "live"] and pg.tw.bought == [base.NUMBER]


def test_two_purchases_at_once_record_the_exact_total(pg, monkeypatch):
    """Codex review 1, finding 3: each total must include the other's number.
    Both purchases are held until both are about to read the total, so they
    overlap every run (without the lock this test fails: checked by mutation)."""
    if not pg.has_meters:
        pytest.skip("platform_meters (039) is not in the local harness")
    meet, record = threading.Barrier(2, timeout=20), base.rn()._record_cost

    def overlapping(session, now, **kw):
        meet.wait()
        return record(session, now, **kw)
    monkeypatch.setattr(base.rn(), "_record_cost", overlapping)
    first, second = base.request(pg.engine, A), base.request(pg.engine, B)
    for rid in (first["id"], second["id"]):
        base.prepare(pg.engine, rid)
    start, errors = threading.Barrier(2), []

    def go(rid, number):
        start.wait()
        try:
            base.approve(pg.engine, rid, number=number, check=False)
        except Exception as exc:          # noqa: BLE001 - reported below
            errors.append(exc)
    threads = [threading.Thread(target=go, args=(first["id"], base.NUMBER)),
               threading.Thread(target=go, args=(second["id"], "+441612345679"))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert not errors
    with Session(pg.engine) as s:
        from services import running_costs
        items = {i["name"]: i["pence"] for i in running_costs.items(s, PERIOD)}
    assert items[base.rn().COST_NAME] == 196


def test_onboarding_s_clashing_write_is_a_409_on_postgres(pg):
    with Session(pg.engine) as s:
        base.rn().assign(s, A, base.NUMBER, None)
        s.commit()
    with Session(pg.engine) as s, pytest.raises(base.refused()) as exc:
        with base.rn().number_writes(s):
            s.execute(text("INSERT INTO public.receptionist_configs (business_id, twilio_phone_number) "
                           "VALUES (CAST(:b AS uuid), :n)"), {"b": B, "n": base.NUMBER})
    assert exc.value.status_code == 409
