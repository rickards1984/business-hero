"""NS-B10 — Aria drafts, the owner approves with a tap, Aria acts once.

ADR 0001 D9, D11, D12, D15, D18; North Star P4 ("Aria proposes, the owner
decides"); Mike's decisions of 13 Oct 2026 in docs/NS-B10-TICKET.md:
a new `aria_actions` table; sign-off A; 72-hour expiry; at most once; any
member with full access may approve.

Tests first. This is RED work (outbound customer contact about money), so
Mike reviews these before implementation. New-behaviour tests are strict
xfail and may fail only because `services.aria_actions` /
`aria_actions_api` do not exist yet.

The contract (module `backend/services/aria_actions.py`):
  ACTION_TYPES = ("send_email", "send_invoice_chase",
                  "create_calendar_event", "create_task")
  EXPIRY = timedelta(hours=72)
  now() -> aware UTC datetime (tests pin it)
  sign_off(assistant_name, owner_name, business_name) -> str
  propose(session, business, user_id, action_type, args, *, owner_name=None,
          timezone="Europe/London") -> dict      # {"proposal": {...}} | {"error": ...}
  approve(session, business, action_id, user_id) -> dict   # raises ActionRefused
  edit(session, business, action_id, changes) -> dict      # raises ActionRefused
  dismiss(session, business, action_id) -> dict            # raises ActionRefused
  class ActionRefused(Exception): status_code, detail
and router `backend/aria_actions_api.py` (prefix /v1/aria/actions):
  GET "" (open proposals), POST /{id}/approve, PATCH /{id}, POST /{id}/dismiss.
Execution goes through assistant_tools' existing functions (`_send_email`,
`create_calendar_event`, `_create_task`), looked up at call time, so these
tests replace them with recorders and see exactly what would have gone out.

SQLite with production's shapes. It proves the rules and the scoping, not
PostgreSQL concurrency: the once-only guarantee is tested by re-entering
approve DURING execution, which only a claim taken and committed before
acting can survive.
"""

import asyncio
import importlib
import importlib.util
import json
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

for _key in ("SUPABASE_DATABASE_URL", "DATABASE_URL"):
    if os.getenv(_key) and not os.environ[_key].startswith("sqlite"):
        raise RuntimeError("REFUSING TO RUN: non-SQLite database configured")

import pytest  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import Session  # noqa: E402


class MissingActions(AssertionError):
    """Only this precise, intentional Stage 1 absence may be xfailed."""


# Stage 1's strict-xfail marker was removed once the implementation landed:
# every test below must now pass outright.

A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
OWNER = "11111111-1111-4111-8111-111111111111"
INV_A = "33333333-3333-4333-8333-333333333333"
INV_B = "44444444-4444-4444-8444-444444444444"
T0 = datetime(2026, 10, 13, 9, 0, tzinfo=timezone.utc)

EMAIL = {"to": "tom@harperbuilds.example", "subject": "Your quote",
         "body": "Hi Tom, just checking you received our quote."}
CHASE = {"invoice_id": INV_A}
EVENT = {"title": "Site visit, Harper", "date": "2026-10-20", "start_time": "14:00",
         "duration_minutes": 60}
TASK = {"title": "Ring the Harper quote customer", "due_at": "2026-10-14"}
ARGS = {"send_email": EMAIL, "send_invoice_chase": CHASE,
        "create_calendar_event": EVENT, "create_task": TASK}


def actions():
    if importlib.util.find_spec("services.aria_actions") is None:
        raise MissingActions("backend/services/aria_actions.py does not exist yet")
    return importlib.import_module("services.aria_actions")


def business(bid=A, plan="pro", name="New Body Gym", **extra):
    flags = extra.pop("feature_flags", {})
    return SimpleNamespace(id=bid, plan_tier=plan, name=name, timezone="Europe/London",
                           subscription_status="active", is_active=True,
                           trial_ends_at=None, feature_flags=flags, **extra)


@pytest.fixture
def database():
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    with Session(engine) as s:
        s.execute(text("""CREATE TABLE aria_actions (
            id TEXT PRIMARY KEY, business_id TEXT NOT NULL, proposed_by TEXT,
            action_type TEXT NOT NULL CHECK (action_type IN ('send_email',
                'send_invoice_chase','create_calendar_event','create_task')),
            payload TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('proposed','executing','done',
                'failed','dismissed','expired')),
            approved_by TEXT, approved_at TEXT, executed_at TEXT, expires_at TEXT NOT NULL,
            result TEXT, error TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"""))
        s.execute(text("""CREATE TABLE invoices (
            id TEXT PRIMARY KEY, business_id TEXT NOT NULL, invoice_number TEXT,
            customer_name TEXT, customer_email TEXT, amount NUMERIC, status TEXT,
            chase_stage INTEGER, due_date TEXT, archived BOOLEAN DEFAULT 0,
            last_chased_at TEXT, updated_at TEXT)"""))
        s.execute(text("""CREATE TABLE email_accounts (
            id TEXT PRIMARY KEY, business_id TEXT NOT NULL, provider TEXT,
            email_address TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"""))
        s.execute(text("""CREATE TABLE email_outbox (
            id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            business_id TEXT NOT NULL, email_account_id TEXT NOT NULL,
            to_emails TEXT NOT NULL, subject TEXT NOT NULL, body_preview TEXT NOT NULL,
            status TEXT NOT NULL, invoice_id TEXT, chase_stage INTEGER,
            provider_message_id TEXT, sent_at TEXT, error TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP)"""))
        for bid, inv, email in ((A, INV_A, "accounts@harperbuilds.example"),
                                (B, INV_B, "pay@other.example")):
            s.execute(text("INSERT INTO invoices (id, business_id, invoice_number, "
                           "customer_name, customer_email, amount, status, chase_stage, "
                           "due_date) VALUES (:i, :b, 'INV-0038', 'Harper Builds', :e, "
                           "2340.00, 'sent', 0, '2026-09-02')"),
                      {"i": inv, "b": bid, "e": email})
            s.execute(text("INSERT INTO email_accounts (id, business_id, provider, "
                           "email_address) VALUES (:id, :b, 'google', :addr)"),
                      {"id": f"acct-{bid[:4]}", "b": bid, "addr": f"owner@{bid[:4]}.example"})
        s.commit()
    yield engine
    engine.dispose()


@pytest.fixture
def clock(monkeypatch):
    state = {"now": T0}

    def _set(dt):
        state["now"] = dt
    try:
        monkeypatch.setattr(actions(), "now", lambda: state["now"])
    except MissingActions:
        pass
    return _set


class _Calls(list):
    """A list of recorded effects, with the knobs that make them misbehave."""


@pytest.fixture
def doers(monkeypatch):
    """Record every outward effect. Each recorder succeeds unless told to fail."""
    import assistant_tools
    calls = _Calls()
    behaviour = {"fail": None, "during": None}

    def _maybe():
        if behaviour["during"]:
            hook, behaviour["during"] = behaviour["during"], None
            hook()
        if behaviour["fail"]:
            raise behaviour["fail"]

    def _send_email(engine, business_id, args):
        calls.append(("email", business_id, dict(args)))
        _maybe()
        return {"success": True, "sent": True, "gmail_message_id": "gm-1"}

    async def _create_event(business_id, title, start_time, end_time, **kw):
        calls.append(("event", business_id, {"title": title, "start": start_time,
                                             "end": end_time, **kw}))
        _maybe()
        return {"success": True, "event_id": "ev-1"}

    def _create_task(engine, business_id, args):
        calls.append(("task", business_id, dict(args)))
        _maybe()
        return {"success": True, "task": {"id": "task-1", "title": args.get("title")}}

    monkeypatch.setattr(assistant_tools, "_send_email", _send_email)
    monkeypatch.setattr(assistant_tools, "create_calendar_event", _create_event)
    monkeypatch.setattr(assistant_tools, "_create_task", _create_task)
    for fn in ("_send_invoice_chase", "_delete_task", "_send_gmail_message",
               "_send_microsoft_message"):
        monkeypatch.setattr(assistant_tools, fn,
                            lambda *a, _fn=fn, **k: calls.append((_fn,)) or {"success": True})
    calls.behaviour = behaviour
    return calls


def propose(engine, biz, action_type, args=None, owner_name="Mike"):
    with Session(engine) as s:
        return actions().propose(s, biz, OWNER, action_type,
                                 dict(ARGS[action_type] if args is None else args),
                                 owner_name=owner_name)


def proposal_id(result):
    assert "proposal" in result, result
    return result["proposal"]["id"]


def approve(engine, biz, action_id):
    with Session(engine) as s:
        return actions().approve(s, biz, action_id, OWNER)


def refused(fn, *a):
    m = actions()
    with pytest.raises(m.ActionRefused) as exc:
        fn(*a)
    return exc.value


def row(engine, action_id):
    with Session(engine) as s:
        r = s.execute(text("SELECT status, approved_by, error FROM aria_actions WHERE id=:i"),
                      {"i": action_id}).fetchone()
    return r


# ------------------------------------------------------------ proposing ---

@pytest.mark.parametrize("action_type", sorted(ARGS))
def test_proposing_acts_on_nothing(database, clock, doers, action_type):
    """Acceptance 1: a proposal is stored; nothing is sent, booked or created."""
    result = propose(database, business(), action_type)
    aid = proposal_id(result)
    assert doers == [], f"{action_type} acted on proposal: {doers}"
    assert row(database, aid)[0] == "proposed"
    assert result["proposal"]["action_type"] == action_type
    assert result["proposal"]["expires_at"].startswith("2026-10-16T09:00")


def test_the_email_card_shows_exactly_what_will_go_out(database, clock, doers):
    preview = propose(database, business(), "send_email")["proposal"]["preview"]
    assert preview["to"] == EMAIL["to"] and preview["subject"] == EMAIL["subject"]
    assert preview["body"] == EMAIL["body"]
    assert preview["sign_off"] == actions().sign_off("Aria", "Mike", "New Body Gym")


def test_the_sign_off_is_option_a():
    """Mike's decision 2. Every line is true: Aria sends from the owner's own
    mailbox, so a reply reaches them."""
    assert actions().sign_off("Aria", "Mike", "New Body Gym") == (
        "Aria\n"
        "AI assistant to Mike at New Body Gym\n"
        "I pass every message straight to Mike. Reply to this email and it reaches Mike.")


def test_a_chase_card_uses_the_existing_chase_template_and_this_business_invoice(
        database, clock, doers):
    from email_templates import get_chase_email_template
    preview = propose(database, business(), "send_invoice_chase")["proposal"]["preview"]
    with Session(database) as s:
        amount = s.execute(text("SELECT amount FROM invoices WHERE id=:i"), {"i": INV_A}).scalar()
    expected = get_chase_email_template(
        1, {"customer_name": "Harper Builds", "invoice_number": "INV-0038",
            "amount": amount, "due_date": "2026-09-02"}, "New Body Gym")
    assert preview["to"] == "accounts@harperbuilds.example"
    assert preview["subject"] == expected["subject"] and preview["body"] == expected["body"]
    assert preview["chase_stage"] == 1


def test_another_business_invoice_cannot_be_proposed(database, clock, doers):
    result = propose(database, business(A), "send_invoice_chase", {"invoice_id": INV_B})
    assert "proposal" not in result and result.get("error")


def test_a_paid_invoice_cannot_be_proposed(database, clock, doers):
    with Session(database) as s:
        s.execute(text("UPDATE invoices SET status='paid' WHERE id=:i"), {"i": INV_A})
        s.commit()
    assert "proposal" not in propose(database, business(), "send_invoice_chase")


@pytest.mark.parametrize("to", ["Tom Harper", "tom@localhost", ""])
def test_an_email_without_a_real_address_cannot_be_proposed(database, clock, doers, to):
    result = propose(database, business(), "send_email", dict(EMAIL, to=to))
    assert "proposal" not in result and result.get("error")


@pytest.mark.parametrize("day,start", [("2026-03-29", "01:30"),   # spring forward: no such time
                                       ("2026-10-25", "01:30")])  # fall back: happens twice
def test_a_booking_at_a_clock_change_time_cannot_be_proposed(database, clock, doers, day, start):
    """Acceptance 7, the NS-R1 rule: a local time that does not exist, or
    happens twice, is refused rather than guessed."""
    result = propose(database, business(), "create_calendar_event",
                     dict(EVENT, date=day, start_time=start))
    assert "proposal" not in result and result.get("error")


def test_a_feature_the_plan_lacks_cannot_be_proposed(database, clock, doers):
    no_email = business(feature_flags={"email": False})
    assert "proposal" not in propose(database, no_email, "send_email")


# ------------------------------------------------------------ approving ---

def test_approving_sends_exactly_the_stored_email_with_the_sign_off_once(database, clock, doers):
    """Acceptance 2."""
    aid = proposal_id(propose(database, business(), "send_email"))
    result = approve(database, business(), aid)
    sends = [c for c in doers if c[0] == "email"]
    assert len(sends) == 1
    _, bid, sent = sends[0]
    assert bid == A and sent["to"] == EMAIL["to"] and sent["subject"] == EMAIL["subject"]
    assert sent["body"] == EMAIL["body"] + "\n\n" + actions().sign_off("Aria", "Mike", "New Body Gym")
    assert result["status"] == "done"
    status, approved_by, _ = row(database, aid)
    assert status == "done" and approved_by == OWNER


def test_a_second_approval_does_nothing(database, clock, doers):
    aid = proposal_id(propose(database, business(), "send_email"))
    approve(database, business(), aid)
    err = refused(approve, database, business(), aid)
    assert err.status_code == 409
    assert len([c for c in doers if c[0] == "email"]) == 1


def test_an_approval_arriving_while_the_first_is_sending_does_nothing(database, clock, doers):
    """Two taps in flight at once: the second is refused because the first
    CLAIMED the action, and committed that claim, before sending."""
    aid = proposal_id(propose(database, business(), "send_email"))
    nested = {}

    def second_tap():
        try:
            approve(database, business(), aid)
            nested["result"] = "executed"
        except actions().ActionRefused as exc:
            nested["result"] = exc.status_code
    doers.behaviour["during"] = second_tap
    approve(database, business(), aid)
    assert nested["result"] == 409
    assert len([c for c in doers if c[0] == "email"]) == 1


def test_another_business_action_is_not_found(database, clock, doers):
    """Acceptance 3: 404, not 403 — its existence is not leaked."""
    aid = proposal_id(propose(database, business(B), "send_email"))
    assert refused(approve, database, business(A), aid).status_code == 404
    assert doers == [] and row(database, aid)[0] == "proposed"


def test_an_expired_proposal_cannot_be_approved(database, clock, doers):
    aid = proposal_id(propose(database, business(), "send_email"))
    clock(T0 + timedelta(hours=72, minutes=1))
    assert refused(approve, database, business(), aid).status_code == 409
    assert doers == []


def test_a_proposal_can_still_be_approved_just_before_it_expires(database, clock, doers):
    aid = proposal_id(propose(database, business(), "send_email"))
    clock(T0 + timedelta(hours=71, minutes=59))
    assert approve(database, business(), aid)["status"] == "done"


def test_a_dismissed_proposal_cannot_be_approved(database, clock, doers):
    aid = proposal_id(propose(database, business(), "send_email"))
    with Session(database) as s:
        actions().dismiss(s, business(), aid)
    assert refused(approve, database, business(), aid).status_code == 409
    assert doers == [] and row(database, aid)[0] == "dismissed"


def test_a_feature_removed_since_proposing_is_refused_at_approval(database, clock, doers):
    aid = proposal_id(propose(database, business(), "send_email"))
    downgraded = business(feature_flags={"email": False})
    assert refused(approve, database, downgraded, aid).status_code == 403
    assert doers == [] and row(database, aid)[0] == "proposed"


def test_a_failed_send_is_recorded_and_never_retried(database, clock, doers):
    """Acceptance 4."""
    aid = proposal_id(propose(database, business(), "send_email"))
    doers.behaviour["fail"] = RuntimeError("Gmail said no")
    result = approve(database, business(), aid)
    assert result["status"] == "failed" and "Gmail said no" in result["error"]
    doers.behaviour["fail"] = None
    assert refused(approve, database, business(), aid).status_code == 409
    assert len([c for c in doers if c[0] == "email"]) == 1


def test_a_provider_refusal_is_a_failure_not_a_success(database, clock, doers, monkeypatch):
    import assistant_tools
    monkeypatch.setattr(assistant_tools, "_send_email",
                        lambda engine, bid, args: {"success": False, "error": "token expired"})
    aid = proposal_id(propose(database, business(), "send_email"))
    result = approve(database, business(), aid)
    assert result["status"] == "failed" and row(database, aid)[0] == "failed"


class _Crash(BaseException):
    """The process dying mid-send: no handler runs."""


def test_a_crash_mid_send_is_never_sent_again(database, clock, doers):
    """Mike's decision 4, at most once: the action stays `executing`; nothing
    retries it, and a later tap is refused."""
    aid = proposal_id(propose(database, business(), "send_email"))
    doers.behaviour["fail"] = _Crash()
    with pytest.raises(_Crash):
        approve(database, business(), aid)
    assert row(database, aid)[0] == "executing"
    doers.behaviour["fail"] = None
    assert refused(approve, database, business(), aid).status_code == 409
    assert len([c for c in doers if c[0] == "email"]) == 1


# --------------------------------------------------------------- the chase ---

def test_an_approved_chase_is_sent_recorded_and_advances_the_stage_once(database, clock, doers):
    """Acceptance 6."""
    aid = proposal_id(propose(database, business(), "send_invoice_chase"))
    approve(database, business(), aid)
    sends = [c for c in doers if c[0] == "email"]
    assert len(sends) == 1 and sends[0][2]["to"] == "accounts@harperbuilds.example"
    with Session(database) as s:
        stage, chased = s.execute(text("SELECT chase_stage, last_chased_at FROM invoices "
                                       "WHERE id=:i"), {"i": INV_A}).fetchone()
        out = s.execute(text("SELECT invoice_id, chase_stage, status, email_account_id, "
                             "to_emails FROM email_outbox")).fetchall()
    assert stage == 1 and chased is not None
    assert len(out) == 1
    assert out[0][0] == INV_A and out[0][1] == 1 and out[0][2] == "sent"
    assert out[0][3] == "acct-aaaa" and "accounts@harperbuilds.example" in out[0][4]


def test_a_chase_for_an_invoice_paid_since_proposing_is_not_sent(database, clock, doers):
    aid = proposal_id(propose(database, business(), "send_invoice_chase"))
    with Session(database) as s:
        s.execute(text("UPDATE invoices SET status='paid' WHERE id=:i"), {"i": INV_A})
        s.commit()
    err = refused(approve, database, business(), aid)
    assert err.status_code == 409 and "paid" in str(err.detail).lower()
    assert [c for c in doers if c[0] == "email"] == []
    with Session(database) as s:
        assert s.execute(text("SELECT chase_stage FROM invoices WHERE id=:i"),
                         {"i": INV_A}).scalar() == 0


def test_a_plain_email_is_recorded_in_the_outbox(database, clock, doers):
    aid = proposal_id(propose(database, business(), "send_email"))
    approve(database, business(), aid)
    with Session(database) as s:
        out = s.execute(text("SELECT business_id, subject, invoice_id, status "
                             "FROM email_outbox")).fetchall()
    assert out == [(A, EMAIL["subject"], None, "sent")]


# ---------------------------------------------------- bookings and tasks ---

def test_an_approved_booking_is_made_in_the_business_timezone(database, clock, doers):
    """Acceptance 7: 2pm on 20 October is 2pm London time (BST), sent to the
    calendar with the business's timezone."""
    aid = proposal_id(propose(database, business(), "create_calendar_event"))
    approve(database, business(), aid)
    events = [c for c in doers if c[0] == "event"]
    assert len(events) == 1
    _, bid, ev = events[0]
    assert bid == A and ev["title"] == EVENT["title"]
    assert ev["start"].startswith("2026-10-20T14:00") and ev["end"].startswith("2026-10-20T15:00")
    assert ev.get("timezone") == "Europe/London"
    assert ev.get("calendar_id", "primary") == "primary"


def test_an_approved_task_is_created_once(database, clock, doers):
    aid = proposal_id(propose(database, business(), "create_task"))
    approve(database, business(), aid)
    tasks = [c for c in doers if c[0] == "task"]
    assert len(tasks) == 1 and tasks[0][1] == A and tasks[0][2]["title"] == TASK["title"]


# ---------------------------------------------------------------- editing ---

def test_an_edit_is_what_gets_sent(database, clock, doers):
    """Acceptance 5."""
    aid = proposal_id(propose(database, business(), "send_email"))
    with Session(database) as s:
        actions().edit(s, business(), aid, {"body": "Hi Tom, any thoughts on the quote?"})
    approve(database, business(), aid)
    sent = [c for c in doers if c[0] == "email"][0][2]
    assert sent["body"].startswith("Hi Tom, any thoughts on the quote?\n\n")
    assert sent["body"].endswith("Reply to this email and it reaches Mike.")


def test_the_sign_off_cannot_be_edited_away(database, clock, doers):
    aid = proposal_id(propose(database, business(), "send_email"))
    with Session(database) as s:
        err = refused(actions().edit, s, business(), aid, {"sign_off": ""})
    assert err.status_code == 422


def test_an_edit_is_validated_like_a_proposal(database, clock, doers):
    aid = proposal_id(propose(database, business(), "send_email"))
    with Session(database) as s:
        err = refused(actions().edit, s, business(), aid, {"to": "not an address"})
    assert err.status_code == 422


def test_a_sent_action_cannot_be_edited(database, clock, doers):
    aid = proposal_id(propose(database, business(), "send_email"))
    approve(database, business(), aid)
    with Session(database) as s:
        assert refused(actions().edit, s, business(), aid, {"body": "x"}).status_code == 409


# ------------------------------------------------------------- the API ---

def client_for(database, monkeypatch, biz):
    if importlib.util.find_spec("aria_actions_api") is None:
        raise MissingActions("backend/aria_actions_api.py does not exist yet")
    module = importlib.import_module("aria_actions_api")
    import auth
    import db
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    async def _verify(token):
        return SimpleNamespace(id=OWNER, email="owner@example.com")

    monkeypatch.setattr(auth, "verify_supabase_token", _verify)
    monkeypatch.setattr(auth, "is_platform_admin_user", lambda *a, **k: False)
    monkeypatch.setattr(auth, "get_business_for_user",
                        lambda user_id, requested_business_id=None: SimpleNamespace(id=biz.id))
    monkeypatch.setattr(auth, "_load_business", lambda session, bid: biz)
    monkeypatch.setattr(module, "_load_business", lambda session, bid: biz, raising=False)

    class GateSession(Session):
        """The feature gate loads the ORM Business; everything else is SQL.
        (Harness only — the substitute BH-009, BH-010 and BH-012 use.)"""
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
    return client


def test_the_api_approves_once_then_conflicts(database, monkeypatch, clock, doers):
    aid = proposal_id(propose(database, business(), "send_email"))
    client = client_for(database, monkeypatch, business())
    assert client.post(f"/v1/aria/actions/{aid}/approve").status_code == 200
    assert client.post(f"/v1/aria/actions/{aid}/approve").status_code == 409
    assert len([c for c in doers if c[0] == "email"]) == 1


def test_the_api_hides_another_business_action(database, monkeypatch, clock, doers):
    aid = proposal_id(propose(database, business(B), "send_email"))
    client = client_for(database, monkeypatch, business(A))
    assert client.post(f"/v1/aria/actions/{aid}/approve").status_code == 404
    assert client.patch(f"/v1/aria/actions/{aid}", json={"body": "x"}).status_code == 404
    assert client.post(f"/v1/aria/actions/{aid}/dismiss").status_code == 404
    assert [p["id"] for p in client.get("/v1/aria/actions").json()["actions"]] == []
    assert doers == []


@pytest.mark.parametrize("status,active", [("unpaid", True), ("active", False)])
def test_a_read_only_or_suspended_account_cannot_approve(database, monkeypatch, clock, doers,
                                                         status, active):
    """Acceptance 3. `unpaid` resolves to read-only; `is_active = False` is an
    admin suspension. Both are refused for a mutating request."""
    aid = proposal_id(propose(database, business(), "send_email"))
    blocked = business()
    blocked.subscription_status, blocked.is_active = status, active
    client = client_for(database, monkeypatch, blocked)
    assert client.post(f"/v1/aria/actions/{aid}/approve").status_code == 403
    assert doers == [] and row(database, aid)[0] == "proposed"


def test_the_api_lists_this_business_open_proposals_only(database, monkeypatch, clock, doers):
    mine = proposal_id(propose(database, business(A), "create_task"))
    done = proposal_id(propose(database, business(A), "send_email"))
    approve(database, business(A), done)
    propose(database, business(B), "create_task")
    listed = client_for(database, monkeypatch, business(A)).get("/v1/aria/actions").json()
    assert [p["id"] for p in listed["actions"]] == [mine]


# ------------------------------------------------- the chat boundary ---

@pytest.fixture
def chat_db(database, monkeypatch):
    """The chat wrapper opens its own session and loads the business."""
    import contextlib
    import db

    @contextlib.contextmanager
    def _ctx():
        with Session(database) as s:
            yield s
    monkeypatch.setattr(db, "get_session_context", _ctx)
    try:
        monkeypatch.setattr(actions(), "load_business", lambda session, bid: business(bid))
    except MissingActions:
        pass
    return database


@pytest.mark.parametrize("name", sorted(ARGS))
def test_chat_turns_each_action_into_a_proposal(chat_db, clock, doers, name):
    """D9/D11/D15: the NS-A1 refusal becomes a proposal at the chat boundary.
    The model is told plainly that nothing has happened yet."""
    import assistant_chat
    actions()
    result = asyncio.run(assistant_chat._execute_tool_async(
        name, dict(ARGS[name]), A, "Europe/London", user_id=OWNER, user_name="Mike"))
    assert not result.get("refused"), result
    assert result["proposal"]["action_type"] == name
    assert "nothing has been sent" in result["message"].lower() or \
        "not been done" in result["message"].lower()
    assert doers == []


def test_delete_task_is_still_refused_in_chat(chat_db, clock, doers):
    """D11."""
    import assistant_chat
    actions()
    result = asyncio.run(assistant_chat._execute_tool_async(
        "delete_task", {"task_id": "t1"}, A, "Europe/London", user_id=OWNER, user_name="Mike"))
    assert result.get("refused") is True and doers == []


@pytest.mark.parametrize("name", sorted(ARGS))
def test_the_shared_dispatcher_still_refuses(doers, name):
    """Defence in depth: only the chat wrapper, which knows who is asking,
    may propose. Any other caller of execute_tool is still refused. (Passes
    today; it must keep passing.)"""
    import assistant_tools
    result = assistant_tools.execute_tool(name, dict(ARGS[name]), A, "Europe/London")
    assert result.get("refused") is True and doers == []


def test_chat_advertises_the_four_actions_and_not_delete_task():
    """The model must be able to propose; descriptions say a card is shown."""
    import assistant_tools
    actions()
    tools = {t["function"]["name"]: t["function"]["description"]
             for t in assistant_tools.TOOL_DEFINITIONS}
    assert set(ARGS) <= set(tools) and "delete_task" not in tools
    for name in ARGS:
        assert "approv" in tools[name].lower(), f"{name} must say the owner approves it"


def test_a_chat_reply_carries_its_proposals_to_the_app(chat_db, clock, doers, monkeypatch):
    """The card needs the proposal: process_chat_message returns `proposals`."""
    import assistant_chat
    actions()
    replies = iter([
        SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content=None, tool_calls=[SimpleNamespace(
                id="tc1", function=SimpleNamespace(
                    name="send_invoice_chase", arguments=json.dumps(CHASE)))]))]),
        SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content="I've drafted the chase for you to approve.", tool_calls=None))]),
    ])

    class _Client:
        def __init__(self, *a, **k):
            self.chat = SimpleNamespace(completions=SimpleNamespace(
                create=lambda **kw: next(replies)))

    monkeypatch.setattr(assistant_chat, "OpenAI", _Client)
    monkeypatch.setattr(assistant_chat, "OPENAI_API_KEY", "test")
    monkeypatch.setattr(assistant_chat, "is_platform_admin", lambda uid: False)
    monkeypatch.setattr(assistant_chat, "resolve_conversation", lambda *a: ("conv-1", A))
    monkeypatch.setattr(assistant_chat, "get_business_for_user",
                        lambda uid, bid=None: assistant_chat.BusinessContext(
                            id=A, name="New Body Gym", timezone="Europe/London"))
    monkeypatch.setattr(assistant_chat, "load_conversation_history", lambda *a, **k: [])
    monkeypatch.setattr(assistant_chat, "save_message", lambda *a, **k: "m1")
    monkeypatch.setattr(assistant_chat, "get_user_display_name", lambda uid: "Mike")
    result = asyncio.run(assistant_chat.process_chat_message(
        SimpleNamespace(id=OWNER, email="owner@example.com"), "chase Harper"))
    assert [p["action_type"] for p in result["proposals"]] == ["send_invoice_chase"]
    assert doers == []
