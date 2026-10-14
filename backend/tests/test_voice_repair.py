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


pending = pytest.mark.xfail(
    strict=True, raises=MissingVoiceRepair,
    reason="NS-V1: tests first; implementation follows Mike's review",
)


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

@pending
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


@pending
def test_quiet_mode_is_less_sensitive():
    rv = repaired()
    loud = rv.build_session_config("i", "v", False, [])["session"]["audio"]["input"]["turn_detection"]
    quiet = rv.build_session_config("i", "v", True, [])["session"]["audio"]["input"]["turn_detection"]
    assert quiet["threshold"] > loud["threshold"]
    assert quiet["silence_duration_ms"] > loud["silence_duration_ms"]


@pending
def test_voice_tools_are_in_the_ga_function_shape():
    rv = repaired()
    for tool in rv.REALTIME_TOOLS:
        assert tool["type"] == "function" and tool["name"] and "parameters" in tool


@pending
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
        monkeypatch.setattr(
            metering, "record_call",
            lambda session, business, seconds, call_id=None, at=None, source="receptionist":
            state["recorded"].append((seconds, call_id, source)))
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


@pending
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


@pending
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


@pending
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


@pending
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


@pending
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


@pending
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


@pending
def test_voice_advertises_the_four_card_actions_and_not_delete_task():
    rv = repaired()
    names = {t["name"] for t in rv.REALTIME_TOOLS}
    assert {"send_email", "send_invoice_chase", "create_calendar_event", "create_task"} <= names
    assert "delete_task" not in names
    assert set(rv.VOICE_TOOL_MAP.values()).isdisjoint(
        {"send_email", "send_invoice_chase", "create_calendar_event", "create_task", "delete_task"}), \
        "card actions must never reach the shared executor through the voice map"


# --------------------------------------------------------------- grounding ---

@pending
def test_voice_never_tells_aria_that_absent_data_does_not_exist():
    """Acceptance 7: absent from a tool result means 'I couldn't find it' or
    'not connected', never a claim that it does not exist."""
    rv = repaired()
    text_ = rv.build_system_instructions("New Body Gym", "Mike")
    assert "does not exist" not in text_.lower()


@pending
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


@pending
def test_aria_voice_and_the_receptionist_share_one_allowance(meters):
    """V1: 70 minutes of calls plus 50 of Aria voice use up Pro's 120."""
    accrue(meters, biz(), 70 * 60, "receptionist", "call-1")
    after = accrue(meters, biz(), 50 * 60, "aria_voice", "voice-1")
    assert after["used_minutes"] == D("120.0000")
    assert after["state"] == "allowance_exhausted"
    with Session(meters) as s:
        assert pool().admit_call(s, biz())[0] is False, "the receptionist is blocked too"


@pending
def test_usage_shows_the_split(meters):
    accrue(meters, biz(), 30 * 60, "receptionist", "call-1")
    accrue(meters, biz(), 12 * 60, "aria_voice", "voice-1")
    with Session(meters) as s:
        u = pool().usage(s, biz())
    assert u["by_source"] == {"receptionist": D("30.0000"), "aria_voice": D("12.0000")}
    shown = pool().display(u)
    assert shown["by_source"] == {"receptionist": "30.0", "aria_voice": "12.0"}


@pending
def test_aria_voice_overage_is_billed_and_capped_with_the_pool(meters):
    accrue(meters, biz(metered=True, cap="100"), 118 * 60, "receptionist", "call-1")
    after = accrue(meters, biz(metered=True, cap="100"), 10 * 60, "aria_voice", "voice-1")
    assert after["used_minutes"] == D("120.0000")
    assert after["overage_minutes"] == D("8.0000")
    assert after["overage_spend_gbp"] == D("3.60")


@pending
def test_a_voice_session_is_counted_once(meters):
    accrue(meters, biz(), 10 * 60, "aria_voice", "voice-1")
    again = accrue(meters, biz(), 10 * 60, "aria_voice", "voice-1")
    assert again["used_minutes"] == D("10.0000")


@pending
def test_receptionist_accruals_are_unchanged_by_the_pool(meters):
    """BH-012's meters keep their names and meaning: no migration, no
    rewrite of existing rows."""
    accrue(meters, biz(), 5 * 60, "receptionist", "call-1")
    with Session(meters) as s:
        rows = {m: D(v) for m, v in s.execute(text("SELECT meter, value FROM usage_meters "
                                   "WHERE meter NOT LIKE '%:%'")).fetchall()}
    assert rows == {"receptionist_minutes": D("5")}
