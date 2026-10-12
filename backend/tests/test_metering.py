"""BH-012 (RC1 P0-2) — receptionist minutes are metered, capped and visible.

Without this, the allowances in audits/PRICING-MODEL.md are decorative: one
customer can run £400 of calls through a £129 plan before anyone notices
(RC1_SCOPE P0-2). `usage_meters` exists in production and no code touches it.

Rules: ENTITLEMENT-SPEC PART E and DECISION 2, plus Mike's decisions of
10 Oct 2026 (ADR 0001 D19): minutes counted to the second; the calendar
month in UK time; the owner told by email + in-app banner (+ WhatsApp when
on); beta = Business; a generic meter, receptionist first.

Stage 1: tests first. Money is RED (AGENTS.md §2); Mike reviews these before
implementation. New-behaviour tests are strict xfail and may fail only
because `services.metering` / `usage_api` do not exist yet.

The contract (module `backend/services/metering.py`):
  RECEPTIONIST_METER = "receptionist_minutes"
  OVERAGE_METER      = "receptionist_overage_minutes"
  CALL_HARD_CAP_SECONDS = 1200
  OVERAGE_RATE_GBP = Decimal("0.45"); DEFAULT_SPEND_CAP_GBP = Decimal("100")
  now() -> aware datetime (tests pin it)
  period_for(dt) -> "YYYY-MM" in Europe/London
  allowance_minutes(plan_tier) -> Decimal
  minutes_from_seconds(seconds) -> Decimal, 4dp (numeric(14,4) storage)
  usage(session, business) -> dict
  admit_call(session, business) -> (bool, reason | None)
  record_call(session, business, duration_seconds) -> dict
  call_time_limit_seconds(configured) -> int
  notify_owner(business, state, usage) -> None   (tests replace it)
and router `backend/usage_api.py`: GET /v1/usage, PUT /v1/usage/metering.

SQLite with production's usage_meters rules (unique (business_id, meter,
period), YYYY-MM check). It proves the arithmetic and the scoping, not
PostgreSQL concurrency.
"""

import importlib
import importlib.util
import os
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

for _key in ("SUPABASE_DATABASE_URL", "DATABASE_URL"):
    if os.getenv(_key) and not os.environ[_key].startswith("sqlite"):
        raise RuntimeError("REFUSING TO RUN: non-SQLite database configured")

import pytest  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import Session  # noqa: E402


class MissingMetering(AssertionError):
    """Only this precise, intentional Stage 1 absence may be xfailed."""


pending = pytest.mark.xfail(
    strict=True, raises=MissingMetering,
    reason="BH-012: tests first; implementation follows Mike's review",
)

D = Decimal
LONDON = ZoneInfo("Europe/London")
A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
OCT = datetime(2026, 10, 10, 12, 0, tzinfo=LONDON)


def metering():
    if importlib.util.find_spec("services.metering") is None:
        raise MissingMetering("backend/services/metering.py does not exist yet")
    return importlib.import_module("services.metering")


def business(bid=A, plan="pro", metered=False, cap=None, **extra):
    return SimpleNamespace(id=bid, plan_tier=plan, metered_usage_enabled=metered,
                           monthly_spend_cap_gbp=None if cap is None else D(cap),
                           subscription_status="active", is_active=True,
                           trial_ends_at=None, feature_flags={}, name="Biz", **extra)


@pytest.fixture
def database():
    import sqlite3
    key = (Decimal, sqlite3.PrepareProtocol)
    previous = sqlite3.adapters.get(key)
    sqlite3.register_adapter(Decimal, str)
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    with Session(engine) as s:
        s.execute(text("""CREATE TABLE usage_meters (
            id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            business_id TEXT NOT NULL, meter TEXT NOT NULL CHECK (length(trim(meter)) > 0),
            period TEXT NOT NULL CHECK (period GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]'),
            value TEXT NOT NULL DEFAULT '0',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)"""))
        s.execute(text("CREATE UNIQUE INDEX usage_meters_biz_meter_period_uq "
                       "ON usage_meters (business_id, meter, period)"))
        s.commit()
    yield engine
    engine.dispose()
    if previous is None:
        sqlite3.adapters.pop(key, None)
    else:
        sqlite3.adapters[key] = previous


@pytest.fixture
def clock(monkeypatch):
    def _set(dt):
        monkeypatch.setattr(metering(), "now", lambda: dt)
    try:
        _set(OCT)
    except MissingMetering:
        pass
    return _set


@pytest.fixture
def notices(monkeypatch):
    sent = []
    try:
        monkeypatch.setattr(metering(), "notify_owner",
                            lambda biz, state, usage: sent.append((biz.id, state)))
    except MissingMetering:
        pass
    return sent


def meter_value(engine, bid, meter, period="2026-10"):
    with Session(engine) as s:
        row = s.execute(text("SELECT value FROM usage_meters WHERE business_id=:b "
                             "AND meter=:m AND period=:p"),
                        {"b": bid, "m": meter, "p": period}).fetchone()
    return D(row[0]) if row else D("0")


def call(engine, biz, seconds):
    with Session(engine) as s:
        result = metering().record_call(s, biz, seconds)
        s.commit()
    return result


def admit(engine, biz):
    with Session(engine) as s:
        return metering().admit_call(s, biz)


def usage(engine, biz):
    with Session(engine) as s:
        return metering().usage(s, biz)


# -------------------------------------------------------------- the rules ---

@pytest.mark.parametrize("plan,minutes", [("starter", "0"), ("pro", "120"),
                                          ("business", "350"), ("beta", "350")])
def test_allowance_per_plan(plan, minutes):
    assert metering().allowance_minutes(plan) == D(minutes)


@pytest.mark.parametrize("utc,period,why", [
    (datetime(2026, 8, 31, 23, 30, tzinfo=ZoneInfo("UTC")), "2026-09",
     "00:30 BST on 1 Sep is September in the UK"),
    (datetime(2026, 10, 31, 23, 30, tzinfo=ZoneInfo("UTC")), "2026-10",
     "23:30 GMT on 31 Oct is still October"),
    (datetime(2026, 12, 31, 23, 59, tzinfo=LONDON), "2026-12", "year end"),
])
def test_the_month_is_the_uk_calendar_month(utc, period, why):
    assert metering().period_for(utc) == period, why


@pytest.mark.parametrize("seconds,minutes", [(60, "1.0000"), (125, "2.0833"),
                                             (1, "0.0167"), (0, "0.0000")])
def test_minutes_are_counted_to_the_second(seconds, minutes):
    assert metering().minutes_from_seconds(seconds) == D(minutes)


def test_a_call_is_never_longer_than_twenty_minutes():
    m = metering()
    assert m.CALL_HARD_CAP_SECONDS == 1200
    assert m.call_time_limit_seconds(None) == 1200
    assert m.call_time_limit_seconds(3600) == 1200, "config cannot raise the cap"
    assert m.call_time_limit_seconds(600) == 600, "config can lower it"


# --------------------------------------------------------- accrual and blocks ---

def test_a_call_accrues_its_actual_minutes(database, clock, notices):
    biz = business()
    call(database, biz, 125)
    call(database, biz, 60)
    assert meter_value(database, A, "receptionist_minutes") == D("3.0833")


def test_under_the_allowance_calls_are_admitted(database, clock, notices):
    biz = business()
    call(database, biz, 60 * 100)
    assert admit(database, biz) == (True, None)


def test_allowance_exhausted_mid_call_the_call_completes_then_the_next_is_blocked(
        database, clock, notices):
    """Never cut a caller off mid-sentence; block the NEXT call."""
    biz = business()
    call(database, biz, 60 * 119)
    assert admit(database, biz)[0] is True
    call(database, biz, 60 * 5)   # runs 4 minutes past the allowance
    assert meter_value(database, A, "receptionist_minutes") == D("124.0000")
    allowed, reason = admit(database, biz)
    assert allowed is False and reason == "allowance_exhausted"
    assert (A, "allowance_exhausted") in notices


def test_the_owner_is_told_once_per_month_not_on_every_call(database, clock, notices):
    biz = business()
    call(database, biz, 60 * 121)
    call(database, biz, 60)
    call(database, biz, 60)
    assert notices.count((A, "allowance_exhausted")) == 1


def test_starter_has_no_minutes_unless_metering_is_on(database, clock, notices):
    assert admit(database, business(plan="starter"))[0] is False
    assert admit(database, business(plan="starter", metered=True, cap="20"))[0] is True


def test_enabling_metering_unblocks_and_overage_accrues_separately(database, clock, notices):
    biz = business()
    call(database, biz, 60 * 120)
    assert admit(database, biz)[0] is False
    metered = business(metered=True, cap="100")
    assert admit(database, metered) == (True, None)
    call(database, metered, 60 * 10)
    assert meter_value(database, A, "receptionist_overage_minutes") == D("10.0000")
    assert usage(database, metered)["overage_spend_gbp"] == D("4.50")   # 10 x £0.45


def test_a_call_that_crosses_the_allowance_with_metering_on_splits(database, clock, notices):
    biz = business(metered=True, cap="100")
    call(database, biz, 60 * 118)
    call(database, biz, 60 * 5)   # 2 inside the allowance, 3 overage
    assert meter_value(database, A, "receptionist_minutes") == D("120.0000")
    assert meter_value(database, A, "receptionist_overage_minutes") == D("3.0000")


def test_the_spend_cap_blocks_again(database, clock, notices):
    biz = business(metered=True, cap="9")       # 20 overage minutes = £9.00
    call(database, biz, 60 * 120)
    call(database, biz, 60 * 20)
    allowed, reason = admit(database, biz)
    assert allowed is False and reason == "spend_cap_reached"
    assert (A, "spend_cap_reached") in notices


def test_metering_on_without_a_cap_uses_the_hundred_pound_default(database, clock, notices):
    biz = business(metered=True, cap=None)
    assert usage(database, biz)["spend_cap_gbp"] == D("100")


def test_a_new_month_resets_everything(database, clock, notices):
    biz = business()
    call(database, biz, 60 * 130)
    assert admit(database, biz)[0] is False
    clock(datetime(2026, 11, 1, 0, 1, tzinfo=LONDON))
    assert admit(database, biz) == (True, None)
    assert usage(database, biz)["used_minutes"] == D("0")


def test_businesses_are_metered_separately(database, clock, notices):
    call(database, business(A), 60 * 120)
    assert admit(database, business(B))[0] is True
    assert meter_value(database, B, "receptionist_minutes") == D("0")


def test_usage_says_what_is_left_before_the_limit(database, clock, notices):
    biz = business()
    call(database, biz, int(60 * 37.4))
    u = usage(database, biz)
    assert u["allowance_minutes"] == D("120")
    assert u["used_minutes"] == D("37.4000")
    assert u["remaining_minutes"] == D("82.6000")
    assert u["state"] == "ok"
    assert u["period"] == "2026-10"


# ----------------------------------------------------------------- the API ---

def client_for(database, monkeypatch, biz):
    if importlib.util.find_spec("usage_api") is None:
        raise MissingMetering("backend/usage_api.py does not exist yet")
    module = importlib.import_module("usage_api")
    import auth
    import db
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    async def _verify(token):
        return SimpleNamespace(id="owner", email="owner@example.com")

    monkeypatch.setattr(auth, "verify_supabase_token", _verify)
    monkeypatch.setattr(auth, "is_platform_admin_user", lambda *a, **k: False)
    monkeypatch.setattr(auth, "get_business_for_user",
                        lambda user_id, requested_business_id=None: SimpleNamespace(id=biz.id))
    monkeypatch.setattr(auth, "_load_business", lambda session, bid: biz)
    writes = []
    monkeypatch.setattr(module, "_load_business", lambda session, bid: biz, raising=False)
    monkeypatch.setattr(module, "_save_metering_settings",
                        lambda session, bid, enabled, cap: writes.append((bid, enabled, cap)),
                        raising=False)

    class GateSession(Session):
        """The feature gate loads the ORM Business; everything else is SQL.
        (Harness only — the same substitute BH-009 and BH-010's tests use.)"""
        def exec(self, statement, *a, **k):
            from models import Business
            if statement.column_descriptions[0]["entity"] is Business:
                return SimpleNamespace(first=lambda: biz)
            return super().exec(statement, *a, **k)

    def sessions():
        with GateSession(database) as s:
            yield s

    app = FastAPI()
    app.include_router(module.router)
    app.dependency_overrides[db.get_session] = sessions
    client = TestClient(app)
    client.headers["Authorization"] = "Bearer synthetic"
    client.writes = writes
    return client


def test_usage_endpoint_shows_the_callers_business_only(database, monkeypatch, clock, notices):
    call(database, business(B), 60 * 99)
    r = client_for(database, monkeypatch, business(A)).get("/v1/usage")
    assert r.status_code == 200
    body = r.json()
    assert body["used_minutes"] == "0.0" and body["allowance_minutes"] == "120"
    assert body["state"] == "ok"


def test_usage_is_shown_to_one_decimal_place(database, monkeypatch, clock, notices):
    call(database, business(A), int(60 * 37.4))
    body = client_for(database, monkeypatch, business(A)).get("/v1/usage").json()
    assert body["used_minutes"] == "37.4" and body["remaining_minutes"] == "82.6"


def test_the_owner_can_switch_metering_on_with_a_cap(database, monkeypatch, clock, notices):
    client = client_for(database, monkeypatch, business(A))
    r = client.put("/v1/usage/metering", json={"enabled": True, "monthly_spend_cap_gbp": "50"})
    assert r.status_code == 200
    assert client.writes == [(A, True, D("50"))]


def test_switching_metering_on_without_a_cap_sets_the_default(database, monkeypatch, clock, notices):
    client = client_for(database, monkeypatch, business(A))
    client.put("/v1/usage/metering", json={"enabled": True})
    assert client.writes == [(A, True, D("100"))]


@pytest.mark.parametrize("cap", ["-1", "0", "NaN", "100000"])
def test_an_invalid_cap_is_refused(database, monkeypatch, clock, notices, cap):
    client = client_for(database, monkeypatch, business(A))
    r = client.put("/v1/usage/metering", json={"enabled": True, "monthly_spend_cap_gbp": cap})
    assert r.status_code == 422
    assert client.writes == []


def test_a_read_only_account_cannot_switch_metering_on(database, monkeypatch, clock, notices):
    unpaid = business(A)
    unpaid.subscription_status = "unpaid"
    unpaid.is_active = False
    client = client_for(database, monkeypatch, unpaid)
    r = client.put("/v1/usage/metering", json={"enabled": True})
    assert r.status_code == 403
    assert client.writes == []


# ------------------------------------------------- the phone receptionist ---

def test_the_incoming_call_path_asks_the_meter_before_answering():
    """Source-level guard (the Twilio handler needs a signed request to run):
    the incoming-call handler must consult metering.admit_call, and the media
    stream must use metering.call_time_limit_seconds and record_call."""
    import inspect
    metering()
    import receptionist_call_handler as rch
    incoming = inspect.getsource(rch.receptionist_incoming_call)
    stream = inspect.getsource(rch.receptionist_media_stream)
    assert "admit_call" in incoming
    assert "call_time_limit_seconds" in stream
    assert "record_call" in stream


# ------------------------------------------- Codex BH-012 review 1 additions ---

@pytest.fixture
def full_db(database):
    """usage_meters plus the businesses and calls rows reconciliation reads."""
    with Session(database) as s:
        s.execute(text("CREATE TABLE businesses (id TEXT PRIMARY KEY, name TEXT, plan_tier TEXT, "
                       "metered_usage_enabled BOOLEAN DEFAULT 0, monthly_spend_cap_gbp TEXT)"))
        s.execute(text("CREATE TABLE calls (id TEXT PRIMARY KEY, business_id TEXT, source TEXT, "
                       "started_at TEXT, ended_at TEXT, duration_seconds INTEGER)"))
        s.execute(text("INSERT INTO businesses VALUES (:a,'A Gym','pro',0,NULL)"), {"a": A})
        s.execute(text("INSERT INTO businesses VALUES (:b,'B Builders','pro',0,NULL)"), {"b": B})
        s.commit()
    return database


def test_a_call_is_counted_once_however_often_it_is_recorded(database, clock, notices):
    """Finding 2: a retried accrual must not add the call twice."""
    biz = business()
    with Session(database) as s:
        metering().record_call(s, biz, 600, call_id="call-1")
        metering().record_call(s, biz, 600, call_id="call-1")
        s.commit()
    assert meter_value(database, A, "receptionist_minutes") == D("10.0000")


def test_a_call_counts_in_the_month_it_happened(database, clock, notices):
    """Reconciling a call from 31 Oct on 1 Nov must charge October."""
    clock(datetime(2026, 11, 1, 9, 0, tzinfo=LONDON))
    with Session(database) as s:
        metering().record_call(s, business(), 300, call_id="late",
                               at=datetime(2026, 10, 31, 23, 50, tzinfo=LONDON))
        s.commit()
    assert meter_value(database, A, "receptionist_minutes", "2026-10") == D("5.0000")
    assert meter_value(database, A, "receptionist_minutes", "2026-11") == D("0")


def test_calls_whose_metering_failed_are_counted_by_reconciliation(full_db, clock, notices):
    """Finding 2: the calls table is the durable record; any finished
    receptionist call with no accrual is counted, once, by reconciliation."""
    with Session(full_db) as s:
        for cid, bid, secs in (("c1", A, 600), ("c2", A, 120), ("c3", B, 60)):
            s.execute(text("INSERT INTO calls VALUES (:i,:b,'receptionist',"
                           "'2026-10-10T10:00:00+01:00','2026-10-10T10:10:00+01:00',:d)"),
                      {"i": cid, "b": bid, "d": secs})
        s.execute(text("INSERT INTO calls VALUES ('c4',:a,'manual',NULL,NULL,999)"), {"a": A})
        s.commit()
        metering().record_call(s, business(A), 600, call_id="c1")   # already metered
        s.commit()
        metering().reconcile_unmetered_calls(s)
        metering().reconcile_unmetered_calls(s)                    # idempotent
        s.commit()
    assert meter_value(full_db, A, "receptionist_minutes") == D("12.0000")
    assert meter_value(full_db, B, "receptionist_minutes") == D("1.0000")


def test_allocation_is_locked_per_business_and_month_on_postgres():
    """Finding 1: two calls ending together must not both spend the same
    remaining allowance. On PostgreSQL the split runs under a transaction
    advisory lock per (business, month); SQLite has no concurrency to lock."""
    m = metering()
    seen = []

    class _Fake:
        bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        def execute(self, statement, params=None):
            seen.append((str(statement), params))

    m._lock(_Fake(), A, "2026-10")
    assert seen and "pg_advisory_xact_lock" in seen[0][0]
    assert A in str(seen[0][1]) and "2026-10" in str(seen[0][1])
    import inspect
    source = inspect.getsource(m.record_call)
    assert source.index("_lock(") < source.index("_usage_for(session"), \
        "the lock must be taken before the remaining allowance is read"


def test_a_failed_notice_is_retried_and_then_sent_once(database, clock, monkeypatch):
    """Finding 4: a notice that fails must not suppress the rest of the month."""
    m = metering()
    attempts = []

    def flaky(biz, state, usage):
        attempts.append(state)
        return len(attempts) > 1   # first attempt fails
    monkeypatch.setattr(m, "notify_owner", flaky)
    biz = business()
    call(database, biz, 60 * 121)
    call(database, biz, 60)
    call(database, biz, 60)
    assert attempts == ["allowance_exhausted", "allowance_exhausted"]


def test_a_refused_call_tells_the_owner(database, clock, notices):
    """Finding 4: lowering the cap below what is already spent blocks calls
    without any call ending past a limit — the refusal itself must notify."""
    call(database, business(metered=True, cap="100"), 60 * 140)   # £9.00 extra
    allowed, reason = admit(database, business(metered=True, cap="5"))
    assert allowed is False and reason == "spend_cap_reached"
    assert notices.count((A, "spend_cap_reached")) == 1
    admit(database, business(metered=True, cap="5"))
    assert notices.count((A, "spend_cap_reached")) == 1


def test_a_plan_with_no_minutes_is_never_sent_a_notice(database, clock, notices):
    admit(database, business(plan="starter"))
    assert notices == []


@pytest.mark.parametrize("elapsed,limit,left", [(0, 1200, 1200), (45, 1200, 1155),
                                               (1300, 1200, 0), (30, 600, 570)])
def test_the_time_limit_counts_from_the_start_of_the_call(elapsed, limit, left):
    """Finding 3: call setup time is inside the 20 minutes, not added to it."""
    started = datetime(2026, 10, 10, 12, 0, tzinfo=ZoneInfo("UTC"))
    from datetime import timedelta
    now_ = started + timedelta(seconds=elapsed)
    assert metering().seconds_left_in_call(limit, started, now_) == left


def test_the_whatsapp_notice_uses_the_approved_alert_template():
    """Finding 5: an unsolicited message must use a registered template; free
    text only reaches a customer inside WhatsApp's 24-hour reply window."""
    import services.metering_notify as notify
    from services.whatsapp_service import TEMPLATE_SID_MAP, TEMPLATE_VARIABLE_COUNTS
    message_type, variables = notify.whatsapp_alert(
        "New Body", "allowance_exhausted",
        {"used_minutes": D("121"), "allowance_minutes": D("120"),
         "spend_cap_gbp": D("100"), "overage_spend_gbp": D("0")})
    assert message_type == "alert" and message_type in TEMPLATE_SID_MAP
    assert len(variables) == TEMPLATE_VARIABLE_COUNTS["alert"]
    assert variables["1"] == "New Body"


def test_the_notice_is_accurate_about_what_resets_and_where_to_act():
    """Review note: the ALLOWANCE resets; extra minutes already used are still
    billed. And the owner gets a link straight to the switch."""
    import services.metering_notify as notify
    subject, body = notify._words("allowance_exhausted", {
        "used_minutes": D("121"), "allowance_minutes": D("120"),
        "spend_cap_gbp": D("100"), "overage_spend_gbp": D("0")})
    assert "monthly allowance resets" in body
    assert "/app/ai?tab=receptionist" in body


def test_aria_can_read_receptionist_usage_for_her_business_only(full_db, clock, notices):
    """Finding 6, North Star Gate 7: usage the app records, Aria can read."""
    import assistant_tools
    call(full_db, business(A), 60 * 30)
    call(full_db, business(B), 60 * 90)
    result = assistant_tools._get_receptionist_usage(full_db, A, {})
    assert result["used_minutes"] == "30.0" and result["allowance_minutes"] == "120"
    assert result["remaining_minutes"] == "90.0"
    assert "90.0" not in str({k: v for k, v in result.items() if k != "remaining_minutes"})
    names = {t["function"]["name"] for t in assistant_tools.TOOL_DEFINITIONS}
    assert "get_receptionist_usage" in names
