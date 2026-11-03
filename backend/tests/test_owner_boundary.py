"""TRADE-0 §2: owner routes act only for a business the person OWNS.

get_business_for_user is the resolver behind every tenant_owner route (the
three shared dependencies, Aria chat, TTS and voice). Before TRADE-0 it
accepted ANY active membership: safe only while every member was an owner.
"""
import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, text

A, B, C = (str(uuid.uuid4()) for _ in range(3))
OWNER, WORKER, BOTH, TWO_OWNED, NOBODY, ADMIN, INACTIVE, ODD = (str(uuid.uuid4()) for _ in range(8))


@pytest.fixture
def chat(tmp_path, monkeypatch):
    import assistant_chat
    e = create_engine("sqlite:///" + str(tmp_path / "b.sqlite"))
    with e.begin() as c:
        c.execute(text("CREATE TABLE businesses (id TEXT, name TEXT, timezone TEXT, logo_url TEXT)"))
        c.execute(text("CREATE TABLE business_members (id TEXT, business_id TEXT, user_id TEXT, role TEXT, "
                       "is_active BOOLEAN, created_at TEXT)"))
        c.execute(text("CREATE TABLE platform_admins (user_id TEXT)"))
        for b, n in ((A, "Alpha"), (B, "Beta"), (C, "Gamma")):
            c.execute(text("INSERT INTO businesses VALUES (:i, :n, 'Europe/London', NULL)"), {"i": b, "n": n})
        t0 = datetime(2026, 1, 1)
        members = [(OWNER, A, "owner", True), (WORKER, B, "worker", True),
                   (BOTH, A, "owner", True), (BOTH, B, "worker", True),
                   (TWO_OWNED, A, "owner", True), (TWO_OWNED, C, "owner", True),
                   (INACTIVE, A, "owner", False), (ODD, A, "admin", True)]
        for n, (u, b, role, active) in enumerate(members):
            c.execute(text("INSERT INTO business_members VALUES (:i, :b, :u, :r, :a, :t)"),
                      {"i": str(uuid.uuid4()), "b": b, "u": u, "r": role, "a": active,
                       "t": (t0 + timedelta(days=n)).isoformat()})
        c.execute(text("INSERT INTO platform_admins VALUES (:u)"), {"u": ADMIN})
    monkeypatch.setattr(assistant_chat, "engine", e)
    return assistant_chat


def resolves(chat, user, requested=None):
    try:
        return chat.get_business_for_user(user, requested_business_id=requested).id
    except ValueError as exc:
        return exc.args[0]


def test_an_owner_gets_their_business(chat):
    assert resolves(chat, OWNER) == A
    assert resolves(chat, OWNER, A) == A


def test_a_worker_gets_no_owner_authority(chat):
    assert resolves(chat, WORKER) == "FORBIDDEN"
    assert resolves(chat, WORKER, B) == "FORBIDDEN"


def test_owner_of_a_and_worker_in_b_is_an_owner_only_in_a(chat):
    assert resolves(chat, BOTH) == A
    assert resolves(chat, BOTH, A) == A
    assert resolves(chat, BOTH, B) == "FORBIDDEN"


def test_owning_two_businesses_keeps_todays_behaviour(chat):
    """No switcher exists yet: the oldest OWNED business, as before. Never a
    business where the person isn't an owner."""
    assert resolves(chat, TWO_OWNED) == A
    assert resolves(chat, TWO_OWNED, C) == C


def test_unknown_roles_inherit_nothing(chat):
    assert resolves(chat, ODD) == "FORBIDDEN"
    assert resolves(chat, ODD, A) == "FORBIDDEN"


def test_an_inactive_or_unrelated_person_gets_nothing(chat):
    assert resolves(chat, INACTIVE) == "NO_BUSINESS"
    assert resolves(chat, NOBODY) == "NO_BUSINESS"
    assert resolves(chat, NOBODY, A) == "FORBIDDEN"
    assert resolves(chat, OWNER, B) == "FORBIDDEN"


def test_a_platform_admin_keeps_access(chat):
    assert resolves(chat, ADMIN, B) == B
