"""NS-V1 — Aria's voice restored: OpenAI's GA protocol, metered, cards by tap.

docs/NS-V1-TICKET.md; Mike's decisions of 14 Oct 2026: V1 one pool of voice
minutes shared with the receptionist, shown split; V2 a 20-minute cap per
session; V3 fail closed if the meter can't be read; V4 no voice on Starter
(the `aria_voice` feature gate). ADR 0001 D18: approval is a tap, even in
voice.

Tests first. RED work (the app's most expensive feature, metering, outbound
actions), so Mike reviews these before implementation. New-behaviour tests
are strict xfail and may fail only because the repair is absent
(`realtime_voice.build_session_config`, `metering.ARIA_VOICE_METER`).

The contract:
  realtime_voice.build_session_config(instructions, voice, quiet_mode, tools) -> dict
      the GA `session.update` event
  realtime_voice.VOICE_SESSION_CAP_SECONDS = 1200
  realtime_voice.FORWARDED_EVENTS  the GA server events the browser renders
  metering.ARIA_VOICE_METER = "aria_voice_minutes"
  metering.ARIA_VOICE_OVERAGE_METER = "aria_voice_overage_minutes"
  metering.record_call(..., source="receptionist" | "aria_voice")
  metering.usage(...)["by_source"] = {"receptionist": minutes, "aria_voice": minutes}
The endpoint asks `metering.admit_call` before connecting to OpenAI, records
the session with `metering.record_call(source="aria_voice")` once at the end,
and turns the four approvable tool calls into NS-B10 proposals
(`aria_actions.propose_from_chat`), sending the browser a `proposal` event.

All synthetic: OpenAI is an in-process fake socket, the database SQLite.
"""

import asyncio
import importlib
import json
import os
import sys
import time
import types
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

for _key in ("SUPABASE_DATABASE_URL", "DATABASE_URL"):
    if os.getenv(_key) and not os.environ[_key].startswith("sqlite"):
        raise RuntimeError("REFUSING TO RUN: non-SQLite database configured")

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import Session  # noqa: E402

import realtime_voice  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
USER = "11111111-1111-4111-8111-111111111111"
OCT = datetime(2026, 10, 14, 12, 0, tzinfo=ZoneInfo("Europe/London"))
D = Decimal


class MissingVoiceRepair(AssertionError):
    """Only this precise, intentional Stage 1 absence may be xfailed."""


# Stage 1's strict-xfail marker was removed once the repair landed: every
# test below must now pass outright.


def repaired():
    if not hasattr(realtime_voice, "build_session_config"):
        raise MissingVoiceRepair("realtime_voice.build_session_config does not exist yet")
    return realtime_voice


def pool():
    m = importlib.import_module("services.metering")
    if not hasattr(m, "ARIA_VOICE_METER"):
        raise MissingVoiceRepair("metering.ARIA_VOICE_METER does not exist yet")
    return m


# ------------------------------------------------------------ GA protocol ---

def test_the_session_is_configured_in_the_ga_shape():
    """Acceptance 1. The beta shape (`modalities`, top-level `voice`,
    `input_audio_format`, `temperature`) is what broke voice."""
    rv = repaired()
    event = rv.build_session_config("You are Aria.", "marin", False, [{"type": "function", "name": "x"}])
    assert event["type"] == "session.update"
    s = event["session"]
    assert s["type"] == "realtime" and s["model"] == rv.ARIA_REALTIME_MODEL
    assert s["instructions"] == "You are Aria."
    assert s["audio"]["input"]["format"] == {"type": "audio/pcm", "rate": 24000}
    assert s["audio"]["output"]["format"] == {"type": "audio/pcm", "rate": 24000}
    assert s["audio"]["output"]["voice"] == "marin"
    assert s["audio"]["input"]["turn_detection"]["type"] == "server_vad"
    assert s["audio"]["input"]["transcription"]["model"]
    assert s["tools"] == [{"type": "function", "name": "x"}]
    for beta in ("modalities", "voice", "input_audio_format", "output_audio_format",
                 "input_audio_transcription", "turn_detection", "temperature"):
        assert beta not in s, f"beta field {beta!r} in a GA session"


def test_quiet_mode_is_less_sensitive():
    rv = repaired()
    loud = rv.build_session_config("i", "v", False, [])["session"]["audio"]["input"]["turn_detection"]
    quiet = rv.build_session_config("i", "v", True, [])["session"]["audio"]["input"]["turn_detection"]
    assert quiet["threshold"] > loud["threshold"]
    assert quiet["silence_duration_ms"] > loud["silence_duration_ms"]


def test_voice_tools_are_in_the_ga_function_shape():
    rv = repaired()
    for tool in rv.REALTIME_TOOLS:
        assert tool["type"] == "function" and tool["name"] and "parameters" in tool


def test_no_beta_protocol_remains_on_either_side():
    """Acceptance 2: the browser renders GA event names, and neither side
    names the beta ones or sends the beta header."""
    rv = repaired()
    server = Path(rv.__file__).read_text()
    client = (REPO / "frontend/client/src/components/RealtimeVoice.tsx").read_text()
    assert "OpenAI-Beta" not in server
    for beta in ("response.audio.delta", "response.audio_transcript.delta",
                 "response.audio_transcript.done"):
        assert f'"{beta}"' not in server and f"'{beta}'" not in client, beta
    for ga in ("response.output_audio.delta", "response.output_audio_transcript.delta",
               "response.output_audio_transcript.done"):
        assert ga in rv.FORWARDED_EVENTS
        assert ga in client, f"the browser does not render {ga}"
    # The old keepalive committed an empty audio buffer every 20s, which the
    # GA API rejects; the socket's own ping keeps the connection alive.
    assert "input_audio_buffer.commit" not in server


# ------------------------------------------------- the socket, end to end ---

class _FakeUpstream:
    def __init__(self, script, headers):
        self.sent, self.headers, self.open = [], headers, True
        self._script = script

    async def send(self, data):
        self.sent.append(data)

    async def close(self):
        self.open = False

    def __aiter__(self):
        return self._events()

    async def _events(self):
        for event in self._script:
            yield json.dumps(event)
        while self.open:
            await asyncio.sleep(0.02)


@pytest.fixture
def voice(monkeypatch):
    """The real endpoint, switched on; auth, the business, the gate, the meter
    and OpenAI faked at their edges. Records every connect and accrual."""
    monkeypatch.setenv("ARIA_VOICE_ENABLED", "1")
    state = {"connects": [], "recorded": [], "admit": (True, None), "proposed": []}

    def make(script=(), feature_ok=True):
        async def _connect(url, additional_headers=None, **k):
            up = _FakeUpstream(list(script), additional_headers or {})
            state["connects"].append(up)
            return up
        fake_ws = types.ModuleType("websockets")
        fake_ws.connect = _connect
        fake_ws.exceptions = types.SimpleNamespace(ConnectionClosed=Exception,
                                                   ConnectionClosedOK=Exception)
        monkeypatch.setitem(sys.modules, "websockets", fake_ws)

        import supabase_auth

        async def _verify(token):
            return SimpleNamespace(id=USER, user_metadata={"full_name": "Mike"})
        monkeypatch.setattr(supabase_auth, "verify_supabase_token", _verify)
        import assistant_chat
        monkeypatch.setattr(assistant_chat, "get_business_for_user",
                            lambda uid, bid=None: assistant_chat.BusinessContext(
                                id=A, name="New Body Gym", timezone="Europe/London"))
        import auth
        from fastapi import HTTPException

        def _gate(business, feature):
            if not feature_ok:
                raise HTTPException(status_code=403, detail="Feature 'aria_voice' not enabled")
        monkeypatch.setattr(auth, "assert_feature_access", _gate)
        import contextlib
        import db

        @contextlib.contextmanager
        def _ctx():
            yield SimpleNamespace(exec=lambda *a, **k: SimpleNamespace(
                first=lambda: SimpleNamespace(id=A)))
        monkeypatch.setattr(db, "get_session_context", _ctx)

        from services import metering
        monkeypatch.setattr(metering, "load_business",
                            lambda session, bid: SimpleNamespace(id=bid, plan_tier="pro"))

        def _admit(session, business):
            if isinstance(state["admit"], Exception):
                raise state["admit"]
            return state["admit"]
        monkeypatch.setattr(metering, "admit_call", _admit)
        # Voice sessions accrue through accrue_session since Codex review 2
        # (top-up, billed in the month the session started). Harness only.
        monkeypatch.setattr(
            metering, "accrue_session",
            lambda session, business, key, seconds, period=None, source="aria_voice":
            state["recorded"].append((seconds, key, source)))
        monkeypatch.setattr(metering, "voice_session_heartbeat", lambda *a, **k: None)
        monkeypatch.setattr(metering, "voice_session_closed", lambda *a, **k: None)
        from services import aria_actions

        def _propose(business_id, user_id, action_type, args, **kw):
            state["proposed"].append((business_id, action_type, args))
            return {"proposal": {"id": "p1", "action_type": action_type, "status": "proposed",
                                 "preview": args, "version": "v1"},
                    "message": aria_actions.SENT_MESSAGE}
        monkeypatch.setattr(aria_actions, "propose_from_chat", _propose)

        app = FastAPI()
        app.include_router(realtime_voice.router)
        return TestClient(app)

    state["make"] = make
    return state


def _wait(predicate, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_the_live_socket_connects_without_the_beta_header_and_configures_ga(voice):
    repaired()
    client = voice["make"]()
    with client.websocket_connect("/v1/realtime/voice") as ws:
        ws.send_json({"type": "auth", "token": "t"})
        assert ws.receive_json() == {"type": "ready"}
        up = voice["connects"][0]
        assert "OpenAI-Beta" not in up.headers
        first = json.loads(up.sent[0])
        assert first["type"] == "session.update" and first["session"]["type"] == "realtime"


@pytest.mark.parametrize("why", ["feature", "allowance", "meter_unreadable"])
def test_no_openai_connection_when_voice_is_not_allowed(voice, why):
    """Acceptance 3 / V3 / V4: refused before anything is spent."""
    repaired()
    if why == "allowance":
        voice["admit"] = (False, "allowance_exhausted")
    if why == "meter_unreadable":
        voice["admit"] = RuntimeError("database unavailable")
    client = voice["make"](feature_ok=(why != "feature"))
    with client.websocket_connect("/v1/realtime/voice") as ws:
        ws.send_json({"type": "auth", "token": "t"})
        with pytest.raises(Exception):
            ws.receive_json()  # closed with a reason, never "ready"
    assert voice["connects"] == [], f"OpenAI was reached when {why}"
    assert voice["recorded"] == []


def test_a_session_is_metered_once_from_the_aria_voice_source(voice):
    """Acceptance 4: one accrual per session, against the shared pool, with
    an id that makes a retried accrual count once."""
    repaired()
    client = voice["make"]()
    with client.websocket_connect("/v1/realtime/voice") as ws:
        ws.send_json({"type": "auth", "token": "t"})
        assert ws.receive_json() == {"type": "ready"}
    assert _wait(lambda: len(voice["recorded"]) == 1)
    seconds, call_id, source = voice["recorded"][0]
    assert source == "aria_voice" and call_id and isinstance(seconds, int)


def test_a_session_ends_at_the_cap_and_only_the_cap_is_billed(voice, monkeypatch):
    """Acceptance 5 / V2."""
    rv = repaired()
    monkeypatch.setattr(rv, "VOICE_SESSION_CAP_SECONDS", 0.5)
    client = voice["make"]()
    started = time.monotonic()
    with client.websocket_connect("/v1/realtime/voice") as ws:
        ws.send_json({"type": "auth", "token": "t"})
        assert ws.receive_json() == {"type": "ready"}
        with pytest.raises(Exception):
            while True:
                ws.receive_json()  # until the server ends the session
    assert time.monotonic() - started < 4
    assert _wait(lambda: len(voice["recorded"]) == 1)
    assert voice["recorded"][0][0] <= 1


def test_the_browser_receives_the_ga_events_it_renders(voice):
    repaired()
    script = [{"type": "response.output_audio.delta", "delta": "AAAA"},
              {"type": "response.output_audio_transcript.done", "transcript": "Hello Mike"},
              {"type": "session.created", "session": {"secret": "x"}}]
    client = voice["make"](script=script)
    with client.websocket_connect("/v1/realtime/voice") as ws:
        ws.send_json({"type": "auth", "token": "t"})
        assert ws.receive_json() == {"type": "ready"}
        got = [ws.receive_json()["type"], ws.receive_json()["type"]]
    assert got == ["response.output_audio.delta", "response.output_audio_transcript.done"]


@pytest.mark.parametrize("name,args", [
    ("send_email", {"to": "tom@example.com", "subject": "Hi", "body": "Hello"}),
    ("send_invoice_chase", {"invoice_id": "33333333-3333-4333-8333-333333333333"}),
    ("create_calendar_event", {"title": "Visit", "date": "2026-10-20", "start_time": "14:00"}),
    ("create_task", {"title": "Ring the plumber"}),
])
def test_a_spoken_action_becomes_a_card_on_screen(voice, name, args):
    """Acceptance 6 / D18: the model's call becomes an NS-B10 proposal; the
    browser gets a `proposal` event; the model is told nothing has happened
    and to read the draft aloud. Nothing is sent."""
    repaired()
    client = voice["make"](script=[{"type": "response.function_call_arguments.done",
                                    "call_id": "c1", "name": name,
                                    "arguments": json.dumps(args)}])
    with client.websocket_connect("/v1/realtime/voice") as ws:
        ws.send_json({"type": "auth", "token": "t"})
        assert ws.receive_json() == {"type": "ready"}
        event = ws.receive_json()
        assert event["type"] == "proposal" and event["proposal"]["action_type"] == name
        up = voice["connects"][0]

        def _answer():
            for m in up.sent:
                e = json.loads(m)
                if e.get("type") == "conversation.item.create" and e["item"].get("call_id") == "c1":
                    return json.loads(e["item"]["output"])
        assert _wait(lambda: _answer() is not None)
        answer = _answer()
    assert voice["proposed"] == [(A, name, args)]
    assert not answer.get("refused")
    assert "nothing has been sent" in json.dumps(answer).lower()
    assert "screen" in json.dumps(answer).lower()


def test_voice_advertises_the_four_card_actions_and_not_delete_task():
    rv = repaired()
    names = {t["name"] for t in rv.REALTIME_TOOLS}
    assert {"send_email", "send_invoice_chase", "create_calendar_event", "create_task"} <= names
    assert "delete_task" not in names
    assert set(rv.VOICE_TOOL_MAP.values()).isdisjoint(
        {"send_email", "send_invoice_chase", "create_calendar_event", "create_task", "delete_task"}), \
        "card actions must never reach the shared executor through the voice map"


# --------------------------------------------------------------- grounding ---

def test_voice_never_tells_aria_that_absent_data_does_not_exist():
    """Acceptance 7: absent from a tool result means 'I couldn't find it' or
    'not connected', never a claim that it does not exist."""
    rv = repaired()
    text_ = rv.build_system_instructions("New Body Gym", "Mike")
    assert "does not exist" not in text_.lower()


def test_an_email_error_reaches_aria_as_an_error(monkeypatch):
    """Acceptance 7: a connection failure must not read as an empty inbox."""
    rv = repaired()
    import assistant_tools
    monkeypatch.setattr(assistant_tools, "execute_tool",
                        lambda name, args, bid, tz="Europe/London":
                        {"error": "Gmail token expired — reconnect your email"})
    raw = asyncio.run(rv.execute_tool("list_emails", {}, USER, A))
    assert "error" in json.loads(raw) and "token expired" in raw


# ------------------------------------------------------- one pool (V1) ---

@pytest.fixture
def meters(monkeypatch):
    import sqlite3
    key = (Decimal, sqlite3.PrepareProtocol)
    previous = sqlite3.adapters.get(key)
    sqlite3.register_adapter(Decimal, str)
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    with Session(engine) as s:
        s.execute(text("""CREATE TABLE usage_meters (
            id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            business_id TEXT NOT NULL, meter TEXT NOT NULL, period TEXT NOT NULL,
            value TEXT NOT NULL DEFAULT '0',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)"""))
        s.execute(text("CREATE UNIQUE INDEX uq ON usage_meters (business_id, meter, period)"))
        s.commit()
    m = importlib.import_module("services.metering")
    monkeypatch.setattr(m, "now", lambda: OCT)
    monkeypatch.setattr(m, "notify_owner", lambda *a, **k: True)
    yield engine
    engine.dispose()
    if previous is None:
        sqlite3.adapters.pop(key, None)
    else:
        sqlite3.adapters[key] = previous


def biz(metered=False, cap=None):
    return SimpleNamespace(id=A, plan_tier="pro", metered_usage_enabled=metered,
                           monthly_spend_cap_gbp=None if cap is None else D(cap),
                           subscription_status="active", is_active=True,
                           trial_ends_at=None, feature_flags={}, name="New Body Gym")


def accrue(engine, business, seconds, source, call_id):
    with Session(engine) as s:
        return pool().record_call(s, business, seconds, call_id=call_id, source=source)


def test_aria_voice_and_the_receptionist_share_one_allowance(meters):
    """V1: 70 minutes of calls plus 50 of Aria voice use up Pro's 120."""
    accrue(meters, biz(), 70 * 60, "receptionist", "call-1")
    after = accrue(meters, biz(), 50 * 60, "aria_voice", "voice-1")
    assert after["used_minutes"] == D("120.0000")
    assert after["state"] == "allowance_exhausted"
    with Session(meters) as s:
        assert pool().admit_call(s, biz())[0] is False, "the receptionist is blocked too"


def test_usage_shows_the_split(meters):
    accrue(meters, biz(), 30 * 60, "receptionist", "call-1")
    accrue(meters, biz(), 12 * 60, "aria_voice", "voice-1")
    with Session(meters) as s:
        u = pool().usage(s, biz())
    assert u["by_source"] == {"receptionist": D("30.0000"), "aria_voice": D("12.0000")}
    shown = pool().display(u)
    assert shown["by_source"] == {"receptionist": "30.0", "aria_voice": "12.0"}


def test_aria_voice_overage_is_billed_and_capped_with_the_pool(meters):
    accrue(meters, biz(metered=True, cap="100"), 118 * 60, "receptionist", "call-1")
    after = accrue(meters, biz(metered=True, cap="100"), 10 * 60, "aria_voice", "voice-1")
    assert after["used_minutes"] == D("120.0000")
    assert after["overage_minutes"] == D("8.0000")
    assert after["overage_spend_gbp"] == D("3.60")


def test_a_voice_session_is_counted_once(meters):
    accrue(meters, biz(), 10 * 60, "aria_voice", "voice-1")
    again = accrue(meters, biz(), 10 * 60, "aria_voice", "voice-1")
    assert again["used_minutes"] == D("10.0000")


def test_receptionist_accruals_are_unchanged_by_the_pool(meters):
    """BH-012's meters keep their names and meaning: no migration, no
    rewrite of existing rows."""
    accrue(meters, biz(), 5 * 60, "receptionist", "call-1")
    with Session(meters) as s:
        rows = {m: D(v) for m, v in s.execute(text("SELECT meter, value FROM usage_meters "
                                   "WHERE meter NOT LIKE '%:%'")).fetchall()}
    assert rows == {"receptionist_minutes": D("5")}


# ------------------------------------------- Codex NS-V1 review 1 additions ---

def test_a_live_session_leaves_a_durable_heartbeat_that_recovery_bills(meters):
    """Review 1 finding 1: if the end-of-session accrual fails, the minutes
    are not lost. A heartbeat records elapsed time while the session runs;
    recovery bills a session whose heartbeat stopped, once, from the pool."""
    m = pool()
    with Session(meters) as s:
        m.voice_session_heartbeat(s, biz(), "s1", 9 * 60)
        m.voice_session_heartbeat(s, biz(), "s1", 10 * 60)   # the latest wins
        m.voice_session_heartbeat(s, biz(), "s2", 60)        # still alive
    later = OCT.replace(minute=30)
    with Session(meters) as s:
        billed = m.reconcile_open_voice_sessions(
            s, lookup=lambda session, bid: biz(), stale_after_seconds=600,
            at=later, alive={"s2"})
        u = m.usage(s, biz())
    assert billed == 1
    assert u["by_source"]["aria_voice"] == D("10.0000")
    with Session(meters) as s:
        again = m.reconcile_open_voice_sessions(
            s, lookup=lambda session, bid: biz(), stale_after_seconds=600,
            at=later, alive={"s2"})
        assert again == 0 and m.usage(s, biz())["by_source"]["aria_voice"] == D("10.0000")


def test_a_closed_session_is_not_billed_twice_by_recovery(meters):
    m = pool()
    with Session(meters) as s:
        m.voice_session_heartbeat(s, biz(), "s1", 5 * 60)
        m.accrue_session(s, biz(), "s1", 6 * 60, period="2026-10")
        m.voice_session_closed(s, biz(), "s1")
    with Session(meters) as s:
        assert m.reconcile_open_voice_sessions(
            s, lookup=lambda session, bid: biz(), stale_after_seconds=0,
            at=OCT.replace(hour=23), alive=set()) == 0
        assert m.usage(s, biz())["by_source"]["aria_voice"] == D("6.0000")


def test_a_failed_end_accrual_leaves_the_heartbeat_for_recovery(voice, monkeypatch):
    """The endpoint beats at session start and closes the heartbeat only
    after a successful accrual."""
    from services import metering
    beats, closed = [], []
    client = voice["make"]()  # first: it installs its own heartbeat stubs
    monkeypatch.setattr(metering, "voice_session_heartbeat",
                        lambda s, b, sid, seconds, period=None: beats.append((sid, seconds)))
    monkeypatch.setattr(metering, "voice_session_closed",
                        lambda s, b, sid: closed.append(sid))

    def failing_record(*a, **k):
        raise RuntimeError("database unavailable")
    monkeypatch.setattr(metering, "accrue_session", failing_record)
    with client.websocket_connect("/v1/realtime/voice") as ws:
        ws.send_json({"type": "auth", "token": "t"})
        assert ws.receive_json() == {"type": "ready"}
    assert _wait(lambda: beats)
    time.sleep(0.3)
    assert beats[0][1] == 0 and closed == [], "the heartbeat must survive a failed accrual"


def test_a_browser_that_will_not_take_the_limit_notice_cannot_hold_the_session_open(
        voice, monkeypatch):
    """Review 1 finding 2: at the cap, forwarding stops and OpenAI is closed
    BEFORE the notice is attempted; the notice is bounded."""
    rv = repaired()
    monkeypatch.setattr(rv, "VOICE_SESSION_CAP_SECONDS", 0.05)
    from starlette.websockets import WebSocket
    original = WebSocket.send_json

    async def stuck(self, data, mode="text"):
        if isinstance(data, dict) and data.get("type") == "session_limit":
            await asyncio.sleep(3600)
        return await original(self, data, mode)
    monkeypatch.setattr(WebSocket, "send_json", stuck)
    client = voice["make"]()
    with client.websocket_connect("/v1/realtime/voice") as ws:
        ws.send_json({"type": "auth", "token": "t"})
        assert ws.receive_json() == {"type": "ready"}
        assert _wait(lambda: voice["connects"] and not voice["connects"][0].open, timeout=2.0), \
            "OpenAI stayed open behind a stuck notice"
        assert _wait(lambda: len(voice["recorded"]) == 1, timeout=2.0)


def test_slow_tools_do_not_stop_the_cap(voice, monkeypatch):
    """Review 1 finding 3: Aria's tools run off the event loop, so a slow
    database cannot stall the session's deadline."""
    rv = repaired()
    monkeypatch.setattr(rv, "VOICE_SESSION_CAP_SECONDS", 0.3)
    import assistant_tools

    def slow_tool(name, args, bid, tz="Europe/London"):
        time.sleep(1.5)
        return {"tasks": []}
    monkeypatch.setattr(assistant_tools, "execute_tool", slow_tool)
    client = voice["make"](script=[{"type": "response.function_call_arguments.done",
                                    "call_id": "c1", "name": "get_tasks", "arguments": "{}"}])
    with client.websocket_connect("/v1/realtime/voice") as ws:
        ws.send_json({"type": "auth", "token": "t"})
        assert ws.receive_json() == {"type": "ready"}
        # Timed here, inside the session: on exit the test harness waits for
        # the still-sleeping tool thread, which a live server does not.
        assert _wait(lambda: not voice["connects"][0].open, timeout=1.2), \
            "the cap did not fire while a slow tool ran"


def test_a_slow_final_accrual_does_not_hold_the_provider_open(voice, monkeypatch):
    rv = repaired()
    monkeypatch.setattr(rv, "VOICE_SESSION_CAP_SECONDS", 0.05)
    from services import metering
    done = []

    def slow_record(*a, **k):
        time.sleep(1.0)
        done.append(True)
    client = voice["make"]()  # first: it installs its own accrual recorder
    monkeypatch.setattr(metering, "accrue_session", slow_record)
    with client.websocket_connect("/v1/realtime/voice") as ws:
        ws.send_json({"type": "auth", "token": "t"})
        assert ws.receive_json() == {"type": "ready"}
        assert _wait(lambda: not voice["connects"][0].open, timeout=0.6), \
            "a slow accrual held the provider connection open"
    assert _wait(lambda: done, timeout=3.0), "the accrual must still complete"


def test_time_spent_reporting_an_error_is_not_billed(voice, monkeypatch):
    """Review 1 finding 4: the session's end is taken before any notice."""
    repaired()
    from starlette.websockets import WebSocket
    original = WebSocket.send_json

    async def slow_error(self, data, mode="text"):
        if isinstance(data, dict) and data.get("type") == "error":
            await asyncio.sleep(1.2)
        return await original(self, data, mode)
    monkeypatch.setattr(WebSocket, "send_json", slow_error)

    async def broken_send(self, data):
        raise RuntimeError("upstream rejected the session")
    monkeypatch.setattr(_FakeUpstream, "send", broken_send)
    client = voice["make"]()
    with client.websocket_connect("/v1/realtime/voice") as ws:
        ws.send_json({"type": "auth", "token": "t"})
        with pytest.raises(Exception):
            while True:
                ws.receive_json()
    assert _wait(lambda: len(voice["recorded"]) == 1, timeout=3.0)
    assert voice["recorded"][0][0] == 0


def test_aria_receives_the_card_she_is_asked_to_read_aloud(voice):
    """Review 1 finding 5: the canonical draft (for a chase, the server's
    template and recipient) goes to the model as well as to the screen, so
    what she says matches the card."""
    repaired()
    client = voice["make"](script=[{"type": "response.function_call_arguments.done",
                                    "call_id": "c1", "name": "create_task",
                                    "arguments": json.dumps({"title": "Ring the plumber"})}])
    with client.websocket_connect("/v1/realtime/voice") as ws:
        ws.send_json({"type": "auth", "token": "t"})
        assert ws.receive_json() == {"type": "ready"}
        card = ws.receive_json()["proposal"]
        up = voice["connects"][0]

        def _answer():
            for m in up.sent:
                e = json.loads(m)
                if e.get("type") == "conversation.item.create" and e["item"].get("call_id") == "c1":
                    return json.loads(e["item"]["output"])
        assert _wait(lambda: _answer() is not None)
        assert _answer()["card"] == card["preview"]


@pytest.mark.parametrize("phrase", ["does not exist", "only emails that exist",
                                    "only real data that exists", "the only data that exists"])
def test_aria_is_never_told_that_unfetched_data_does_not_exist(phrase):
    """Review 1 finding 6: a sample of recent emails is not every email."""
    rv = repaired()
    import inspect
    told = (rv.build_system_instructions("New Body Gym", "Mike")
            + inspect.getsource(rv.execute_tool)).lower()
    assert phrase not in told



# ------------------------------------------- Codex NS-V1 review 2 additions ---

def test_a_session_across_midnight_at_month_end_is_billed_once_in_its_start_month(
        meters, monkeypatch):
    """Review 2 finding 1: started 31 Oct 23:55, ended 1 Nov 00:07; the
    final accrual succeeded but removing the heartbeat failed. Recovery must
    not bill it again — and both use the session's START month."""
    m = pool()
    london = ZoneInfo("Europe/London")
    monkeypatch.setattr(m, "now", lambda: datetime(2026, 10, 31, 23, 55, tzinfo=london))
    with Session(meters) as s:
        m.voice_session_heartbeat(s, biz(), "s1", 0, period="2026-10")
    monkeypatch.setattr(m, "now", lambda: datetime(2026, 11, 1, 0, 5, tzinfo=london))
    with Session(meters) as s:
        m.voice_session_heartbeat(s, biz(), "s1", 10 * 60, period="2026-10")
    monkeypatch.setattr(m, "now", lambda: datetime(2026, 11, 1, 0, 7, tzinfo=london))
    with Session(meters) as s:
        m.accrue_session(s, biz(), "s1", 12 * 60, period="2026-10")
        # voice_session_closed "failed": the heartbeat is still there
    later = datetime(2026, 11, 1, 1, 0, tzinfo=london)
    monkeypatch.setattr(m, "now", lambda: later)
    with Session(meters) as s:
        m.reconcile_open_voice_sessions(s, lookup=lambda session, bid: biz(),
                                        stale_after_seconds=0, at=later, alive=set())
        october = m._usage_for(s, biz(), "2026-10")["by_source"]["aria_voice"]
        november = m._usage_for(s, biz(), "2026-11")["by_source"]["aria_voice"]
    assert (october, november) == (D("12.0000"), D("0"))


def test_recovery_then_the_real_total_bills_the_real_total(meters):
    """Review 2 finding 4: recovery billed a 10-minute heartbeat; the real
    20-minute accrual arrives later and tops it up — never discarded."""
    m = pool()
    with Session(meters) as s:
        m.voice_session_heartbeat(s, biz(), "s1", 10 * 60, period="2026-10")
    with Session(meters) as s:
        m.reconcile_open_voice_sessions(s, lookup=lambda session, bid: biz(),
                                        stale_after_seconds=0, at=OCT.replace(hour=23),
                                        alive=set())
        m.accrue_session(s, biz(), "s1", 20 * 60, period="2026-10")
        assert m.usage(s, biz())["by_source"]["aria_voice"] == D("20.0000")


def test_the_real_total_then_a_late_heartbeat_adds_nothing(meters):
    """A heartbeat thread that outlived the session recreates its marker
    after the final accrual; recovery then finds less than was billed."""
    m = pool()
    with Session(meters) as s:
        m.accrue_session(s, biz(), "s1", 12 * 60, period="2026-10")
        m.voice_session_closed(s, biz(), "s1")
        m.voice_session_heartbeat(s, biz(), "s1", 10 * 60, period="2026-10")  # late
    with Session(meters) as s:
        m.reconcile_open_voice_sessions(s, lookup=lambda session, bid: biz(),
                                        stale_after_seconds=0, at=OCT.replace(hour=23),
                                        alive=set())
        assert m.usage(s, biz())["by_source"]["aria_voice"] == D("12.0000")


def test_accruing_the_same_session_twice_adds_nothing(meters):
    m = pool()
    with Session(meters) as s:
        m.accrue_session(s, biz(), "s1", 12 * 60, period="2026-10")
        m.accrue_session(s, biz(), "s1", 12 * 60, period="2026-10")
        assert m.usage(s, biz())["by_source"]["aria_voice"] == D("12.0000")


def test_no_session_opens_if_the_first_heartbeat_cannot_be_written(voice, monkeypatch):
    """Review 2 finding 2 / V3: no durable record, no session."""
    repaired()
    from services import metering
    client = voice["make"]()

    def failing_beat(*a, **k):
        raise RuntimeError("database unavailable")
    monkeypatch.setattr(metering, "voice_session_heartbeat", failing_beat)
    with client.websocket_connect("/v1/realtime/voice") as ws:
        ws.send_json({"type": "auth", "token": "t"})
        with pytest.raises(Exception):
            ws.receive_json()
    assert voice["connects"] == []


def test_a_session_whose_heartbeats_keep_failing_is_ended(voice, monkeypatch):
    """Review 2 finding 2: loss is bounded — three failed beats in a row end
    the session rather than let it run unrecorded."""
    rv = repaired()
    monkeypatch.setattr(rv, "VOICE_HEARTBEAT_SECONDS", 0.05)
    from services import metering
    client = voice["make"]()
    calls = []

    def first_only(*a, **k):
        calls.append(1)
        if len(calls) > 1:
            raise RuntimeError("database unavailable")
    monkeypatch.setattr(metering, "voice_session_heartbeat", first_only)
    with client.websocket_connect("/v1/realtime/voice") as ws:
        ws.send_json({"type": "auth", "token": "t"})
        assert ws.receive_json() == {"type": "ready"}
        assert _wait(lambda: not voice["connects"][0].open, timeout=2.0), \
            "the session kept running without a durable record"


class _FakeBrowser:
    """Just enough of Starlette's WebSocket to drive the real handler in ONE
    event loop (the test client gives each connection its own loop, so it
    cannot show one connection stalling another)."""

    def __init__(self):
        self.sent, self.closed = [], False

    async def accept(self):
        pass

    async def receive_json(self):
        return {"type": "auth", "token": "t"}

    async def receive(self):
        while not self.closed:
            await asyncio.sleep(0.01)
        return {"type": "websocket.disconnect"}

    async def send_json(self, data):
        self.sent.append(data)

    async def close(self, code=1000, reason=None):
        self.closed = True


def test_a_slow_sign_in_does_not_stall_the_event_loop(voice, monkeypatch):
    """Review 2 finding 3: sign-in's business lookup and feature-gate query
    run off the event loop. A canary timer on the same loop shows whether a
    slow (0.5s) lookup froze every other session's deadline with it."""
    rv = repaired()
    voice["make"]()  # installs the edge fakes; its test client is not used
    import assistant_chat
    fast = assistant_chat.get_business_for_user

    def slow_lookup(uid, bid=None):
        time.sleep(0.5)
        return fast(uid, bid)
    monkeypatch.setattr(assistant_chat, "get_business_for_user", slow_lookup)

    async def scenario():
        lateness = []

        async def canary():
            for _ in range(30):
                before = time.monotonic()
                await asyncio.sleep(0.02)
                lateness.append(time.monotonic() - before - 0.02)
        browser = _FakeBrowser()
        session = asyncio.create_task(rv.realtime_voice_endpoint(browser))
        await canary()
        browser.closed = True
        await asyncio.wait_for(session, 5)
        return max(lateness)
    assert asyncio.run(scenario()) < 0.2, "a slow sign-in froze the event loop"


def test_a_second_cancellation_during_teardown_still_closes_the_browser(voice, monkeypatch):
    """Review 2 finding 5: if the handler is cancelled again while closing
    OpenAI, the browser is still closed and the session still metered."""
    rv = repaired()
    monkeypatch.setattr(rv, "VOICE_SESSION_CAP_SECONDS", 0.05)

    async def cancelled_close(self):
        asyncio.current_task().cancel()
        self.open = False
        await asyncio.sleep(0.5)
    monkeypatch.setattr(_FakeUpstream, "close", cancelled_close)
    client = voice["make"]()
    with client.websocket_connect("/v1/realtime/voice") as ws:
        ws.send_json({"type": "auth", "token": "t"})
        assert ws.receive_json() == {"type": "ready"}
        with pytest.raises(Exception):
            while True:
                ws.receive_json()  # the browser connection is closed
    assert _wait(lambda: len(voice["recorded"]) == 1, timeout=2.0)


# ------------------------------------------- Codex NS-V1 review 3 additions ---

def test_a_hanging_heartbeat_counts_as_a_failure_and_ends_the_session(voice, monkeypatch):
    """Review 3 finding 1: a write that hangs (not raises) must still count
    toward the three-strikes stop."""
    rv = repaired()
    monkeypatch.setattr(rv, "VOICE_HEARTBEAT_SECONDS", 0.05)
    from services import metering
    client = voice["make"]()
    calls = []

    def first_then_hang(*a, **k):
        calls.append(1)
        if len(calls) > 1:
            time.sleep(3)
    monkeypatch.setattr(metering, "voice_session_heartbeat", first_then_hang)
    with client.websocket_connect("/v1/realtime/voice") as ws:
        ws.send_json({"type": "auth", "token": "t"})
        assert ws.receive_json() == {"type": "ready"}
        assert _wait(lambda: not voice["connects"][0].open, timeout=2.0), \
            "a hanging heartbeat let the session run unrecorded"


def test_cancelling_the_handler_mid_close_still_finishes_closing_openai(voice, monkeypatch):
    """Review 3 finding 2: the handler itself is cancelled while the OpenAI
    close is still in progress; the close must still complete, the browser
    close and the accrual still happen. Driven on one loop with the real
    handler (the earlier test cancelled the close task itself)."""
    rv = repaired()
    monkeypatch.setattr(rv, "VOICE_SESSION_CAP_SECONDS", 0.05)
    voice["make"]()
    closing = {}

    async def slow_close(self):
        closing["started"] = True
        await asyncio.sleep(0.3)
        self.open = False
    monkeypatch.setattr(_FakeUpstream, "close", slow_close)

    async def scenario():
        browser = _FakeBrowser()
        session = asyncio.create_task(rv.realtime_voice_endpoint(browser))
        while not closing.get("started"):
            await asyncio.sleep(0.01)
        session.cancel()  # a second cancellation, mid-close
        try:
            await asyncio.wait_for(session, 5)
        except asyncio.CancelledError:
            pass
        return browser
    browser = asyncio.run(scenario())
    assert not voice["connects"][0].open, "the OpenAI close was abandoned"
    assert browser.closed
    assert _wait(lambda: len(voice["recorded"]) == 1, timeout=2.0)
