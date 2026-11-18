"""STAB-1 — every authenticated request uses ONE database connection, and its
database work never runs on the event loop (docs/STAB-1-TICKET.md).

Production, 18 Nov 2026: `QueuePool limit of size 5 overflow 10 reached` at
16:00:52. Each request's auth dependency held its session's connection AND
opened a second one (assistant_chat.get_business_for_user's engine.connect),
and did both synchronously inside `async def`, so when the pool ran dry the
30-second wait froze the whole server.
"""
import asyncio
import json
import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, text
from sqlalchemy.pool import QueuePool
from sqlmodel import Session

import assistant_chat
import auth
import db
import dependencies

OWNER = "11111111-1111-4111-8111-111111111111"
ADMIN = "99999999-9999-4999-8999-999999999999"
A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


@pytest.fixture
def pg_like(tmp_path, monkeypatch):
    """A file SQLite behind a real QueuePool, counting connections in use."""
    engine = create_engine("sqlite:///" + str(tmp_path / "stab1.sqlite"), poolclass=QueuePool,
                           pool_size=5, max_overflow=0, connect_args={"check_same_thread": False})
    with engine.begin() as c:
        c.execute(text("CREATE TABLE platform_admins (user_id TEXT)"))
        c.execute(text("CREATE TABLE businesses (id TEXT PRIMARY KEY, name TEXT, timezone TEXT, logo_url TEXT, "
                       "api_key TEXT, plan_tier TEXT, feature_flags TEXT, subscription_status TEXT, "
                       "is_active BOOLEAN, trial_ends_at TEXT)"))
        c.execute(text("CREATE TABLE business_members (business_id TEXT, user_id TEXT, role TEXT, "
                       "is_active BOOLEAN, created_at TEXT)"))
        for bid in (A, B):
            c.execute(text("INSERT INTO businesses VALUES (:b, 'Biz', 'Europe/London', NULL, :k, 'pro', '{}', "
                           "'active', 1, NULL)"), {"b": bid, "k": "key-" + bid})
        c.execute(text("INSERT INTO business_members VALUES (:b, :u, 'owner', 1, '2026-01-01')"), {"b": A, "u": OWNER})
        c.execute(text("INSERT INTO platform_admins VALUES (:u)"), {"u": ADMIN})
    state = SimpleNamespace(engine=engine, in_use=0, peak=0)

    @event.listens_for(engine, "checkout")
    def _out(*a):
        state.in_use += 1
        state.peak = max(state.peak, state.in_use)

    @event.listens_for(engine, "checkin")
    def _in(*a):
        state.in_use -= 1

    monkeypatch.setattr(assistant_chat, "engine", engine)
    monkeypatch.setattr(db, "engine", engine)

    async def verify(token):
        return SimpleNamespace(id={"owner": OWNER, "admin": ADMIN}[token], email=f"{token}@example.invalid")
    monkeypatch.setattr(auth, "verify_supabase_token", verify)
    monkeypatch.setattr(dependencies, "verify_supabase_token", verify)
    # The Business model's UUID columns don't bind plain strings on SQLite: load
    # it the way the dependencies do, through the session, as a namespace.
    monkeypatch.setattr(dependencies, "_load_business_row", _sqlite_business, raising=False)
    monkeypatch.setattr(auth, "_load_business", lambda session, bid: _sqlite_business(session, bid))
    yield state
    engine.dispose()


def _sqlite_business(session, bid):
    if not bid:
        return None
    r = session.execute(text("SELECT id, plan_tier, feature_flags, subscription_status, is_active, trial_ends_at "
                             "FROM businesses WHERE id = :b"), {"b": str(bid)}).first()
    if not r:
        return None
    return SimpleNamespace(id=r[0], plan_tier=r[1], feature_flags=json.loads(r[2] or "{}"),
                           subscription_status=r[3], is_active=bool(r[4]), trial_ends_at=r[5])


def used(engine):
    """A request session that already holds its connection, as it does once an
    earlier dependency has queried. An unused one checks out nothing, so a
    second, standalone connection would finish first and never overlap it
    (Codex code review 1, finding 2)."""
    s = Session(engine)
    s.execute(text("SELECT 1"))
    return s


def request(method="GET", path="/v1/home/summary"):
    return SimpleNamespace(method=method, url=SimpleNamespace(path=path), state=SimpleNamespace())


def run(coro_fn):
    return asyncio.run(coro_fn())


# ------------------------------------------------------ one connection ---

@pytest.mark.parametrize("token,business_id", [("owner", None), ("owner", A), ("admin", None), ("admin", B)])
def test_the_business_context_uses_one_connection(pg_like, token, business_id):
    async def go():
        with used(pg_like.engine) as s:
            return await auth.get_user_business_context(request(), token=token, business_id=business_id, session=s)
    out = run(go)
    assert pg_like.peak == 1, f"{pg_like.peak} connections held at once"
    assert out["business_id"] in (A, B, None)


def test_the_business_lookup_can_share_the_session(pg_like):
    with used(pg_like.engine) as s:
        ctx = assistant_chat.get_business_for_user(OWNER, session=s)
        assert assistant_chat.is_platform_admin(ADMIN, session=s) is True
        assert assistant_chat.get_business_by_id(B, session=s).id == B
    assert ctx.id == A and pg_like.peak == 1


def test_the_business_lookup_still_works_alone(pg_like):
    assert assistant_chat.get_business_for_user(OWNER).id == A      # other callers are unchanged


def test_a_non_member_is_still_refused(pg_like):
    async def go():
        with used(pg_like.engine) as s:
            return await auth.get_user_business_context(request(), token="owner", business_id=B, session=s)
    with pytest.raises(HTTPException) as exc:
        run(go)
    assert exc.value.status_code == 403


@pytest.mark.parametrize("dep", ["get_current_user_business", "get_current_user_and_business"])
def test_the_other_owner_dependencies_use_one_connection(pg_like, monkeypatch, dep):
    async def go():
        with used(pg_like.engine) as s:
            return await getattr(dependencies, dep)(request(), token="owner", session=s)
    run(go)
    assert pg_like.peak == 1


def test_the_admin_and_auth_contexts_use_one_connection(pg_like):
    async def go():
        with used(pg_like.engine) as s:
            ctx = await auth.get_user_auth_context(request(), token="admin", session=s)
            admin = await auth.get_platform_admin_context({"user_id": ADMIN}, session=s)
            return ctx, admin
    ctx, admin = run(go)
    assert ctx["is_platform_admin"] is True and admin["user_id"] == ADMIN and pg_like.peak == 1


# ------------------------------------------- never on the event loop ---

def _slow(monkeypatch, seconds=0.4):
    real = auth.is_platform_admin_user

    def slow(*a, **k):
        time.sleep(seconds)
        return real(*a, **k)
    monkeypatch.setattr(auth, "is_platform_admin_user", slow)
    monkeypatch.setattr(dependencies, "is_platform_admin_user", slow)


async def _with_heartbeat(coro):
    delays = []

    async def beat():
        for _ in range(25):
            start = time.monotonic()
            await asyncio.sleep(0.01)
            delays.append(time.monotonic() - start)
    task = asyncio.create_task(beat())
    await asyncio.sleep(0.03)                      # beating before the request starts
    out = await coro
    await task
    return out, max(delays)


@pytest.mark.parametrize("which", ["business_context", "current_user_business", "user_and_business",
                                   "auth_context", "platform_admin"])
def test_a_slow_database_never_freezes_the_server(pg_like, monkeypatch, which):
    """The pool wait that froze production: other requests must keep moving."""
    _slow(monkeypatch)

    async def go():
        with used(pg_like.engine) as s:
            call = {
                "business_context": lambda: auth.get_user_business_context(request(), token="owner", business_id=None,
                                                                           session=s),
                "current_user_business": lambda: dependencies.get_current_user_business(request(), token="owner",
                                                                                        session=s),
                "user_and_business": lambda: dependencies.get_current_user_and_business(request(), token="owner",
                                                                                        session=s),
                "auth_context": lambda: auth.get_user_auth_context(request(), token="owner", session=s),
                "platform_admin": lambda: auth.get_platform_admin_context({"user_id": ADMIN}, session=s),
            }[which]
            return await _with_heartbeat(call())
    _, worst = run(go)
    assert worst < 0.2, f"the event loop stalled for {worst:.2f}s"


def test_require_feature_never_freezes_the_server(pg_like, monkeypatch):
    _slow(monkeypatch)
    dep = auth.require_feature("receptionist")

    async def go():
        with used(pg_like.engine) as s:
            return await _with_heartbeat(dep({"user_id": OWNER, "business_id": A}, session=s))
    monkeypatch.setattr(auth, "assert_feature_access", lambda *a, **k: None)
    monkeypatch.setattr(auth, "_load_business", lambda session, bid: _sqlite_business(session, bid))
    out, worst = run(go)
    assert out is True and worst < 0.2


def test_the_api_key_business_never_freezes_the_server(pg_like, monkeypatch):
    def slow(session, token):
        time.sleep(0.4)
        return _sqlite_business(session, A) if token == "key-" + A else None
    monkeypatch.setattr(auth, "_business_by_api_key", slow)

    async def go():
        with used(pg_like.engine) as s:
            return await _with_heartbeat(auth.get_current_business(x_api_key="key-" + A, authorization=None,
                                                                   auth_header=None, session=s))
    out, worst = run(go)
    assert out.id == A and worst < 0.2


# ------------------------------------- /v1/me and the AI gate (review 1) ---

@pytest.fixture
def main_module(pg_like, monkeypatch):
    import main
    return main


def test_me_uses_the_requests_connection(pg_like, main_module):
    """The admin has no membership: the lookup runs both its queries and the
    page still answers, on the one connection the request already holds."""
    async def go():
        with used(pg_like.engine) as s:
            return await main_module.get_my_profile({"user_id": ADMIN, "is_platform_admin": True}, session=s)
    out = run(go)
    assert out["business_id"] is None and pg_like.peak == 1


def test_me_never_freezes_the_server(pg_like, main_module, monkeypatch):
    real = main_module.get_business_for_user

    def slow(*a, **k):
        time.sleep(0.4)
        return real(*a, **k)
    monkeypatch.setattr(main_module, "get_business_for_user", slow)

    async def go():
        with used(pg_like.engine) as s:
            return await _with_heartbeat(main_module.get_my_profile({"user_id": ADMIN}, session=s))
    _, worst = run(go)
    assert worst < 0.2


def test_the_ai_gate_uses_the_requests_connection(pg_like, main_module):
    with used(pg_like.engine) as s:
        with pytest.raises(HTTPException) as exc:
            main_module._assert_ai_access(s, OWNER, B, "aria_chat")      # not a member of B
    assert exc.value.status_code == 404 and pg_like.peak == 1


@pytest.mark.parametrize("endpoint", ["chat", "tts"])
def test_the_ai_gate_never_freezes_the_server(pg_like, main_module, monkeypatch, endpoint):
    def slow(*a, **k):
        time.sleep(0.4)
        raise HTTPException(status_code=403, detail="stop here")
    monkeypatch.setattr(main_module, "_assert_ai_access", slow)

    async def verify(token):
        return SimpleNamespace(id=OWNER, email="owner@example.invalid")
    monkeypatch.setattr(main_module, "verify_supabase_token", verify)

    async def go():
        with used(pg_like.engine) as s:
            if endpoint == "chat":
                call = main_module.assistant_chat.__wrapped__ if hasattr(main_module.assistant_chat, "__wrapped__") \
                    else main_module.assistant_chat
                coro = call(request(), SimpleNamespace(business_id=None), token="t", session=s)
            else:
                call = main_module.text_to_speech.__wrapped__ if hasattr(main_module.text_to_speech, "__wrapped__") \
                    else main_module.text_to_speech
                coro = call(request(), token="t", session=s)

            async def guarded():
                try:
                    return await coro
                except HTTPException as exc:
                    return exc.status_code
            return await _with_heartbeat(guarded())
    status_code, worst = run(go)
    assert status_code == 403 and worst < 0.2


def test_aria_chat_looks_up_off_the_event_loop(pg_like, monkeypatch):
    def slow_admin(*a, **k):
        time.sleep(0.4)
        raise RuntimeError("stop here")
    monkeypatch.setattr(assistant_chat, "is_platform_admin", slow_admin)

    async def go():
        async def guarded():
            try:
                await assistant_chat.process_chat_message(user=SimpleNamespace(id=OWNER, email=None), message="hi")
            except RuntimeError:
                return "stopped"
        return await _with_heartbeat(guarded())
    out, worst = run(go)
    assert out == "stopped" and worst < 0.2


# ------------------------------------------------------------ the pool ---

def test_the_pool_is_sized_for_a_direct_supabase_connection(monkeypatch):
    for key in ("DB_POOL_SIZE", "DB_MAX_OVERFLOW", "DB_POOL_TIMEOUT"):
        monkeypatch.delenv(key, raising=False)
    assert db.pool_options() == {"pool_size": 10, "max_overflow": 10, "pool_timeout": 10,
                                 "pool_pre_ping": True, "pool_recycle": 1800}


def test_the_pool_can_be_tuned_without_a_release(monkeypatch):
    monkeypatch.setenv("DB_POOL_SIZE", "15")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "5")
    monkeypatch.setenv("DB_POOL_TIMEOUT", "8")
    opts = db.pool_options()
    assert (opts["pool_size"], opts["max_overflow"], opts["pool_timeout"]) == (15, 5, 8)


@pytest.mark.parametrize("size,overflow", [("30", "10"), ("40", "40"), ("25", "6")])
def test_a_pool_over_the_budget_falls_back_to_the_defaults(monkeypatch, size, overflow):
    monkeypatch.setenv("DB_POOL_SIZE", size)
    monkeypatch.setenv("DB_MAX_OVERFLOW", overflow)
    opts = db.pool_options()
    assert (opts["pool_size"], opts["max_overflow"]) == (10, 10)
    assert opts["pool_size"] + opts["max_overflow"] <= db.POOL_BUDGET


def test_production_runs_one_process_so_the_budget_holds():
    """POOL_BUDGET is per process. A second worker doubles the total."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2]
    for name in ("Procfile", "railway.json"):
        text_ = (root / name).read_text()
        assert "uvicorn main:app" in text_ and "--workers" not in text_, name


@pytest.mark.parametrize("bad", ["0", "-1", "abc", "500"])
def test_silly_pool_settings_fall_back_to_the_defaults(monkeypatch, bad):
    monkeypatch.setenv("DB_POOL_SIZE", bad)
    assert db.pool_options()["pool_size"] == 10
