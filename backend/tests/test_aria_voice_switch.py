"""NS-A2 — Aria voice is switched off server-side until it is repaired.

Production evidence, 2 Oct 2026 (Railway logs, six attempts by Mike on New
Body): every session reached OpenAI and was refused with
`beta_api_shape_disabled` — "The Realtime Beta API is no longer supported".
`realtime_voice.py` still speaks the Beta protocol; the receptionist was
migrated to GA and is unaffected.

Decision 0001 D2 (Mike): voice is off for RC1 and repaired after P0-2
metering. Codex review 1 finding 5: "off" must be refused by the SERVER,
before the provider connection opens — hiding the button is not enough,
because an entitled account can open `/v1/realtime/voice` directly.

These tests build a bare app around the voice router only, so nothing here
imports `main` or opens a database connection.
"""

import sys
import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import realtime_voice


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(realtime_voice.router)
    return TestClient(app)


@pytest.fixture
def provider_tripwire(monkeypatch):
    """Fail loudly if anything tries to reach OpenAI or verify a token."""
    calls = []

    async def _connect(*a, **k):
        calls.append("openai")
        raise AssertionError("opened a provider connection while voice is off")

    fake_ws = types.ModuleType("websockets")
    fake_ws.connect = _connect
    monkeypatch.setitem(sys.modules, "websockets", fake_ws)

    import supabase_auth

    async def _verify(*a, **k):
        calls.append("auth")
        raise AssertionError("verified a token while voice is off")

    monkeypatch.setattr(supabase_auth, "verify_supabase_token", _verify)
    return calls


def _close_code(client):
    with client.websocket_connect("/v1/realtime/voice") as ws:
        ws.send_json({"type": "auth", "token": "anything"})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
    return exc.value.code


def test_voice_is_off_when_the_switch_is_unset(client, provider_tripwire, monkeypatch):
    """Off is the default: a deploy that forgets the variable must not
    reopen a broken, unmetered provider path."""
    monkeypatch.delenv("ARIA_VOICE_ENABLED", raising=False)
    assert _close_code(client) == realtime_voice.VOICE_UNAVAILABLE_CODE
    assert provider_tripwire == []


@pytest.mark.parametrize("value", ["0", "", "false", "yes", "true", "TRUE"])
def test_only_an_explicit_1_turns_voice_on(client, provider_tripwire, monkeypatch, value):
    monkeypatch.setenv("ARIA_VOICE_ENABLED", value)
    assert _close_code(client) == realtime_voice.VOICE_UNAVAILABLE_CODE
    assert provider_tripwire == []


def test_refusal_happens_before_authentication(client, provider_tripwire, monkeypatch):
    """No Supabase round-trip and no OpenAI connection — not even for a
    valid user. The tripwire records both."""
    monkeypatch.delenv("ARIA_VOICE_ENABLED", raising=False)
    _close_code(client)
    assert "auth" not in provider_tripwire
    assert "openai" not in provider_tripwire


def test_when_on_the_endpoint_proceeds_to_authentication(client, monkeypatch):
    """The switch must not block a repaired voice: with it on, the handshake
    goes on to demand an auth message (and refuses a wrong one with 4001)."""
    monkeypatch.setenv("ARIA_VOICE_ENABLED", "1")
    with client.websocket_connect("/v1/realtime/voice") as ws:
        ws.send_json({"type": "not-auth"})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
    assert exc.value.code == 4001


def test_status_reports_off_by_default(client, monkeypatch):
    monkeypatch.delenv("ARIA_VOICE_ENABLED", raising=False)
    r = client.get("/v1/realtime/voice/status")
    assert r.status_code == 200
    assert r.json() == {"available": False, "message": realtime_voice.VOICE_UNAVAILABLE_MESSAGE}


def test_status_reports_on_when_switched_on(client, monkeypatch):
    monkeypatch.setenv("ARIA_VOICE_ENABLED", "1")
    assert client.get("/v1/realtime/voice/status").json() == {"available": True, "message": None}
