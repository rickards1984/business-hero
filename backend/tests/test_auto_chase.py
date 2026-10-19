"""AUTO-1 — Aria chases overdue invoices on autopilot (standing permission).

docs/AUTO-1-TICKET.md; Mike's decisions of 19 Oct 2026: off by default;
stage 1 at 7 days overdue, then every 7 days to stage 3; stage 4 always a
card; at most one chase per customer per week; weekdays 09:00–17:00 UK.

Tests first (RED: automatic customer contact about money). Strict xfail may
fail only because `services.automations` does not exist yet.

The contract (backend/services/automations.py):
  CHASE_DEFAULTS                      the defaults above (enabled False)
  chase_settings(raw: dict | None) -> dict      defaults merged with saved
  now() -> aware UTC datetime                   tests pin it
  run_invoice_autopilot(session, business, settings, *, owner_name=None)
      -> {"sent": [invoice_id], "cards": [invoice_id], "skipped": {invoice_id: reason}}
  aria_actions.propose(..., automation="invoice_chasing")  marks the payload
  home_summary.recent_automated(conn, business_id, now, days=7) -> list
Sending goes through aria_actions.propose + approve, so the recorders below
see exactly what would leave the building.
"""

import importlib
import importlib.util
import json
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

for _key in ("SUPABASE_DATABASE_URL", "DATABASE_URL"):
    if os.getenv(_key) and not os.environ[_key].startswith("sqlite"):
        raise RuntimeError("REFUSING TO RUN: non-SQLite database configured")

import pytest  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import Session  # noqa: E402


class MissingAutomation(AssertionError):
    """Only this precise, intentional Stage 1 absence may be xfailed."""


# Stage 1's strict-xfail marker was removed once the implementation landed.

A, B = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
LONDON = ZoneInfo("Europe/London")
# Tuesday 20 October 2026, 10:00 UK
TUE_10 = datetime(2026, 10, 20, 10, 0, tzinfo=LONDON)


def automations():
    if importlib.util.find_spec("services.automations") is None:
        raise MissingAutomation("backend/services/automations.py does not exist yet")
    return importlib.import_module("services.automations")


def business(bid=A, **extra):
    return SimpleNamespace(id=bid, plan_tier="pro", name="New Body Gym", timezone="Europe/London",
                           subscription_status="active", is_active=True, trial_ends_at=None,
                           feature_flags=extra.pop("feature_flags", {}), **extra)


def on(**overrides):
    return {**automations().chase_settings(None), "enabled": True, **overrides}


@pytest.fixture
def db():
    eng = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    with eng.begin() as c:
        c.execute(text("""CREATE TABLE aria_actions (id TEXT PRIMARY KEY, business_id TEXT NOT NULL,
            proposed_by TEXT, action_type TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL,
            approved_by TEXT, approved_at TEXT, executed_at TEXT, expires_at TEXT NOT NULL,
            result TEXT, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"""))
        c.execute(text("""CREATE TABLE invoices (id TEXT PRIMARY KEY, business_id TEXT NOT NULL,
            invoice_number TEXT, customer_name TEXT, customer_email TEXT, amount NUMERIC,
            amount_due NUMERIC, amount_paid NUMERIC DEFAULT 0, paid_amount NUMERIC, status TEXT,
            chase_stage INTEGER DEFAULT 0, due_date TEXT, archived BOOLEAN DEFAULT 0,
            last_chased_at TEXT, updated_at TEXT, external_id TEXT)"""))
        c.execute(text("""CREATE TABLE email_accounts (id TEXT PRIMARY KEY, business_id TEXT NOT NULL,
            provider TEXT, email_address TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"""))
        c.execute(text("""CREATE TABLE email_outbox (id TEXT PRIMARY KEY, business_id TEXT NOT NULL,
            email_account_id TEXT NOT NULL, to_emails TEXT NOT NULL, subject TEXT NOT NULL,
            body_preview TEXT NOT NULL, status TEXT NOT NULL, invoice_id TEXT, chase_stage INTEGER,
            provider_message_id TEXT, sent_at TEXT, error TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"""))
        for bid in (A, B):
            c.execute(text("INSERT INTO email_accounts (id, business_id, provider, email_address) "
                           "VALUES (:id, :b, 'google', :e)"), {"id": f"acct-{bid[:4]}", "b": bid,
                                                              "e": f"owner@{bid[:4]}.example"})
    yield eng
    eng.dispose()


_n = {"i": 0}


def invoice(eng, *, bid=A, days_overdue=10, stage=0, last_chased_days_ago=None,
            email="pay@harper.example", status="sent", amount=500, archived=False, paid=None):
    _n["i"] += 1
    iid = f"00000000-0000-4000-8000-{_n['i']:012d}"
    due = (TUE_10 - timedelta(days=days_overdue)).date().isoformat()
    last = None if last_chased_days_ago is None else (
        TUE_10 - timedelta(days=last_chased_days_ago)).astimezone(timezone.utc).isoformat()
    with eng.begin() as c:
        c.execute(text("""INSERT INTO invoices (id, business_id, invoice_number, customer_name,
            customer_email, amount, amount_due, paid_amount, status, chase_stage, due_date, archived,
            last_chased_at) VALUES (:id, :b, :n, 'Harper Builds', :e, :a, :a, :p, :s, :st, :d, :ar, :l)"""),
                  {"id": iid, "b": bid, "n": f"INV-{_n['i']:04d}", "e": email, "a": amount, "p": paid,
                   "s": status, "st": stage, "d": due, "ar": archived, "l": last})
    return iid


@pytest.fixture
def sent(monkeypatch):
    """Records every email that would go out; the clock is pinned."""
    import assistant_tools
    out = []

    def _send(engine, business_id, args):
        out.append((business_id, dict(args)))
        return {"success": True, "sent": True, "gmail_message_id": f"gm-{len(out)}"}
    monkeypatch.setattr(assistant_tools, "_send_email", _send)
    try:
        m = automations()
        monkeypatch.setattr(m, "now", lambda: TUE_10.astimezone(timezone.utc))
        import services.aria_actions as aa
        monkeypatch.setattr(aa, "now", lambda: TUE_10.astimezone(timezone.utc))
    except MissingAutomation:
        pass
    return out


def run(db, settings, biz=None):
    with Session(db) as s:
        return automations().run_invoice_autopilot(s, biz or business(), settings, owner_name="Mike")


def stage_of(db, iid):
    with db.connect() as c:
        return c.execute(text("SELECT chase_stage FROM invoices WHERE id=:i"), {"i": iid}).scalar()


def actions(db):
    with db.connect() as c:
        return c.execute(text("SELECT action_type, status, approved_by, payload FROM aria_actions")).fetchall()


# ---------------------------------------------------------------- switched ---

def test_it_is_off_by_default(db, sent):
    invoice(db, days_overdue=30)
    assert automations().chase_settings(None)["enabled"] is False
    assert run(db, automations().chase_settings(None))["sent"] == [] and sent == []


def test_the_defaults_are_mikes():
    d = automations().chase_settings(None)
    assert (d["first_after_days"], d["every_days"], d["max_auto_stage"]) == (7, 7, 3)
    assert (d["start_hour"], d["end_hour"], d["weekdays_only"]) == (9, 17, True)
    assert (d["customer_gap_days"], d["daily_cap"], d["paused_customers"]) == (7, 20, [])


def test_saved_settings_override_only_what_they_name():
    d = automations().chase_settings({"enabled": True, "every_days": 10})
    assert d["enabled"] is True and d["every_days"] == 10 and d["first_after_days"] == 7


# ---------------------------------------------------------------- the rules ---

@pytest.mark.parametrize("days,expected", [(6, []), (7, ["stage1"])])
def test_stage_one_starts_at_seven_days_overdue(db, sent, days, expected):
    iid = invoice(db, days_overdue=days)
    result = run(db, on())
    assert (result["sent"] == [iid]) == bool(expected)
    assert stage_of(db, iid) == (1 if expected else 0)


@pytest.mark.parametrize("ago,sends", [(6, False), (7, True)])
def test_the_next_stage_waits_seven_days(db, sent, ago, sends):
    iid = invoice(db, days_overdue=30, stage=1, last_chased_days_ago=ago)
    run(db, on())
    assert stage_of(db, iid) == (2 if sends else 1)


def test_stage_four_is_always_a_card_never_sent(db, sent):
    iid = invoice(db, days_overdue=60, stage=3, last_chased_days_ago=8)
    result = run(db, on())
    assert result["sent"] == [] and result["cards"] == [iid] and sent == []
    rows = actions(db)
    assert len(rows) == 1 and rows[0].status == "proposed"
    run(db, on())  # an open card is not proposed twice
    assert len(actions(db)) == 1


def test_a_chase_is_exactly_the_stage_template_with_the_sign_off(db, sent):
    from email_templates import get_chase_email_template
    invoice(db, days_overdue=10)
    run(db, on())
    (_, mail), = sent
    with db.connect() as c:
        amount = c.execute(text("SELECT amount FROM invoices")).scalar()
    expected = get_chase_email_template(1, {"customer_name": "Harper Builds", "invoice_number": "INV-%04d" % _n["i"],
                                            "amount": amount, "due_date": (TUE_10 - timedelta(days=10)).date().isoformat()},
                                        "New Body Gym")
    assert mail["subject"] == expected["subject"]
    assert mail["body"].startswith(expected["body"]) and "AI assistant to Mike" in mail["body"]


def test_it_is_recorded_as_a_standing_permission(db, sent):
    invoice(db, days_overdue=10)
    run(db, on())
    (row,) = actions(db)
    assert row.status == "done" and row.approved_by is None
    assert json.loads(row.payload)["automation"] == "invoice_chasing"


@pytest.mark.parametrize("kwargs", [
    {"status": "paid"}, {"status": "draft"}, {"status": "cancelled"}, {"archived": True},
    {"paid": 500}, {"email": None}, {"email": ""},
])
def test_nothing_settled_or_unaddressable_is_chased(db, sent, kwargs):
    invoice(db, days_overdue=30, **kwargs)
    assert run(db, on())["sent"] == [] and sent == []


def test_one_chase_per_customer_per_week(db, sent):
    a = invoice(db, days_overdue=30, email="pay@harper.example")
    b = invoice(db, days_overdue=20, email="PAY@harper.example")
    result = run(db, on())
    assert len(result["sent"]) == 1 and len(sent) == 1
    assert result["skipped"][b if result["sent"] == [a] else a] == "customer_chased_recently"


def test_a_customer_chased_by_hand_this_week_waits(db, sent):
    invoice(db, days_overdue=30, stage=1, last_chased_days_ago=2, email="pay@harper.example")
    other = invoice(db, days_overdue=30, email="pay@harper.example")
    result = run(db, on())
    assert result["sent"] == [] and result["skipped"][other] == "customer_chased_recently"


def test_a_paused_customer_is_never_chased(db, sent):
    iid = invoice(db, days_overdue=30, email="pay@harper.example")
    result = run(db, on(paused_customers=["Pay@Harper.example"]))
    assert sent == [] and result["skipped"][iid] == "customer_paused"


@pytest.mark.parametrize("moment", [
    datetime(2026, 10, 24, 10, 0, tzinfo=LONDON),   # Saturday
    datetime(2026, 10, 20, 8, 59, tzinfo=LONDON),   # before 9
    datetime(2026, 10, 20, 17, 0, tzinfo=LONDON),   # 17:00 is outside
])
def test_only_weekdays_nine_to_five_uk(db, sent, monkeypatch, moment):
    invoice(db, days_overdue=30)
    monkeypatch.setattr(automations(), "now", lambda: moment.astimezone(timezone.utc))
    assert run(db, on())["sent"] == [] and sent == []


def test_the_daily_cap(db, sent):
    for i in range(25):
        invoice(db, days_overdue=30, email=f"c{i}@example.com")
    assert len(run(db, on(daily_cap=20))["sent"]) == 20
    assert run(db, on(daily_cap=20))["sent"] == [], "the cap is per day, across runs"


def test_running_twice_sends_once(db, sent):
    invoice(db, days_overdue=30)
    run(db, on())
    run(db, on())
    assert len(sent) == 1


@pytest.mark.parametrize("status,active", [("unpaid", True), ("active", False)])
def test_a_read_only_or_suspended_account_is_never_chased_for(db, sent, status, active):
    invoice(db, days_overdue=30)
    biz = business()
    biz.subscription_status, biz.is_active = status, active
    assert run(db, on(), biz)["sent"] == [] and sent == []


def test_a_plan_without_email_sends_nothing(db, sent):
    invoice(db, days_overdue=30)
    assert run(db, on(), business(feature_flags={"email": False}))["sent"] == [] and sent == []


def test_another_business_is_never_touched(db, sent):
    other = invoice(db, bid=B, days_overdue=30)
    run(db, on())
    assert sent == [] and stage_of(db, other) == 0


def test_an_invoice_with_a_card_already_waiting_is_left_alone(db, sent):
    iid = invoice(db, days_overdue=30)
    import services.aria_actions as aa
    with Session(db) as s:
        aa.propose(s, business(), "owner", "send_invoice_chase", {"invoice_id": iid}, owner_name="Mike")
    result = run(db, on())
    assert sent == [] and result["skipped"][iid] == "card_waiting"


# ------------------------------------------------------- the home and timing ---

def test_the_home_lists_what_aria_chased(db, sent):
    invoice(db, days_overdue=30)
    run(db, on())
    from services import home_summary
    with db.connect() as c:
        recent = home_summary.recent_automated(c, A, TUE_10.astimezone(timezone.utc), days=7)
    assert len(recent) == 1
    assert recent[0]["kind"] == "invoice_chasing" and recent[0]["stage"] == 1
    assert recent[0]["customer_name"] == "Harper Builds" and recent[0]["sent_at"]


def test_the_scheduler_runs_it_off_the_loop_and_hourly():
    automations()
    import inspect
    from services import briefing_scheduler
    source = inspect.getsource(briefing_scheduler)
    assert "_run_invoice_autopilot_if_due" in source and "to_thread" in source


# ---------------------------------------------------- the owner's switches ---
# Added during implementation (not in the approved Stage 1 set): the settings
# endpoint the ticket names.

def client_for(db, monkeypatch, biz):
    import automations_api
    import auth
    import db as dbmod
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    with db.begin() as c:
        c.execute(text("""CREATE TABLE IF NOT EXISTS business_settings (id TEXT PRIMARY KEY,
            business_id TEXT UNIQUE, settings TEXT NOT NULL, created_at TEXT, updated_at TEXT)"""))

    async def _verify(token):
        return SimpleNamespace(id="owner", email="owner@example.com")
    monkeypatch.setattr(auth, "verify_supabase_token", _verify)
    monkeypatch.setattr(auth, "is_platform_admin_user", lambda *a, **k: False)
    monkeypatch.setattr(auth, "get_business_for_user",
                        lambda user_id, requested_business_id=None: SimpleNamespace(id=biz.id))
    monkeypatch.setattr(auth, "_load_business", lambda session, bid: biz)

    class GateSession(Session):
        def exec(self, statement, *a, **k):
            from models import Business
            if statement.column_descriptions[0]["entity"] is Business:
                return SimpleNamespace(first=lambda: biz)
            return super().exec(statement, *a, **k)

    def sessions():
        with GateSession(db) as s:
            yield s
    app = FastAPI()
    app.include_router(automations_api.router)
    app.dependency_overrides[dbmod.get_session] = sessions
    client = TestClient(app)
    client.headers["Authorization"] = "Bearer synthetic"
    return client


def test_the_owner_switches_it_on_and_other_settings_are_kept(db, monkeypatch):
    client = client_for(db, monkeypatch, business())
    with db.begin() as c:
        c.execute(text("INSERT INTO business_settings VALUES ('s1', :b, :s, '', '')"),
                  {"b": A, "s": json.dumps({"tone": "warm"})})
    assert client.get("/v1/automations/invoice-chasing").json()["enabled"] is False
    r = client.put("/v1/automations/invoice-chasing", json={"enabled": True, "every_days": 10})
    assert r.status_code == 200 and r.json()["enabled"] is True and r.json()["every_days"] == 10
    with db.connect() as c:
        saved = json.loads(c.execute(text("SELECT settings FROM business_settings")).scalar())
    assert saved["tone"] == "warm" and saved["automations"]["invoice_chasing"]["enabled"] is True


def test_values_are_clamped_wherever_they_come_from(db, monkeypatch):
    client = client_for(db, monkeypatch, business())
    r = client.put("/v1/automations/invoice-chasing",
                   json={"enabled": True, "daily_cap": 10000, "every_days": 0, "max_auto_stage": 4,
                         "start_hour": 18, "end_hour": 8})
    body = r.json()
    assert (body["daily_cap"], body["every_days"], body["max_auto_stage"]) == (50, 3, 3)
    assert (body["start_hour"], body["end_hour"]) == (9, 17)
    assert automations().chase_settings({"enabled": "yes"})["enabled"] is False, \
        "only a real true switches it on"


def test_a_read_only_account_cannot_switch_it_on(db, monkeypatch):
    biz = business()
    biz.subscription_status = "unpaid"
    client = client_for(db, monkeypatch, biz)
    assert client.put("/v1/automations/invoice-chasing", json={"enabled": True}).status_code == 403


# ------------------------------------------- Codex AUTO-1 review 1 additions ---

def test_an_unconfirmed_send_blocks_that_customer_until_resolved(db, sent, monkeypatch):
    """Finding 1: a chase that may have gone (no confirmation) must never be
    followed by another automatic chase to that customer — not next hour,
    not next week — until the owner resolves it."""
    import assistant_tools
    calls = []
    monkeypatch.setattr(assistant_tools, "_send_email", lambda engine, bid, args:
                        calls.append(1) or {"success": False, "error": "Send failed: timed out"})
    iid = invoice(db, days_overdue=30)
    first = run(db, on())
    assert first["sent"] == [] and len(calls) == 1
    later = TUE_10 + timedelta(days=14)
    monkeypatch.setattr(automations(), "now", lambda: later.astimezone(timezone.utc))
    import services.aria_actions as aa
    monkeypatch.setattr(aa, "now", lambda: later.astimezone(timezone.utc))
    second = run(db, on())
    assert len(calls) == 1, "an unresolved attempt was followed by another send"
    assert second["skipped"][iid] == "unresolved_attempt"


def test_a_sent_chase_whose_bookkeeping_failed_still_spaces_the_customer(db, sent):
    """Finding 1: the email went (done) but recording it on the invoice failed,
    so last_chased_at was not updated. The customer is still spaced."""
    with db.begin() as c:
        c.execute(text("DROP TABLE email_outbox"))  # bookkeeping fails after the send
    invoice(db, days_overdue=30)
    run(db, on())
    run(db, on())
    assert len(sent) == 1


def test_overlapping_runs_send_one_chase(db, sent, monkeypatch):
    """Finding 2: a second pass runs between the first pass's checks and its
    send (two processes). Exactly one chase goes; the later claimant stands
    down without needing a lock."""
    import services.aria_actions as aa
    real_propose = aa.propose
    nested = {"done": False}

    def propose_with_a_rival(*a, **k):
        if not nested["done"] and k.get("automation"):
            nested["done"] = True
            run(db, on())  # the rival pass completes in between
        return real_propose(*a, **k)
    monkeypatch.setattr(aa, "propose", propose_with_a_rival)
    # Two invoices for ONE customer: the invoice's own stage check cannot
    # stop the second; only customer spacing across runs can.
    invoice(db, days_overdue=30, email="pay@harper.example")
    invoice(db, days_overdue=20, email="pay@harper.example")
    run(db, on())
    assert len(sent) == 1


def test_overlapping_runs_respect_the_daily_cap(db, sent, monkeypatch):
    import services.aria_actions as aa
    real_propose = aa.propose
    nested = {"done": False}

    def propose_with_a_rival(*a, **k):
        if not nested["done"] and k.get("automation"):
            nested["done"] = True
            run(db, on(daily_cap=2))
        return real_propose(*a, **k)
    monkeypatch.setattr(aa, "propose", propose_with_a_rival)
    for i in range(5):
        invoice(db, days_overdue=30, email=f"c{i}@example.com")
    run(db, on(daily_cap=2))
    assert len(sent) == 2


def test_switching_off_mid_run_stops_the_rest(db, sent):
    """Finding 3: authority is re-read before every send."""
    for i in range(3):
        invoice(db, days_overdue=30, email=f"c{i}@example.com")
    state = {"settings": on()}

    def refresh():
        out = (state["settings"], business())
        state["settings"] = {**state["settings"], "enabled": False}  # owner switches off
        return out
    with Session(db) as s:
        automations().run_invoice_autopilot(s, business(), on(), owner_name="Mike", refresh=refresh)
    assert len(sent) == 1


def test_pausing_a_customer_mid_run_is_honoured(db, sent):
    invoice(db, days_overdue=30, email="first@example.com")
    invoice(db, days_overdue=20, email="second@example.com")
    calls = {"n": 0}

    def refresh():
        calls["n"] += 1
        paused = ["second@example.com"] if calls["n"] > 1 else []
        return on(paused_customers=paused), business()
    with Session(db) as s:
        automations().run_invoice_autopilot(s, business(), on(), owner_name="Mike", refresh=refresh)
    assert [m["to"] for _, m in sent] == ["first@example.com"]


def test_the_window_closing_mid_run_stops_the_rest(db, sent, monkeypatch):
    for i in range(3):
        invoice(db, days_overdue=30, email=f"c{i}@example.com")
    clock = iter([datetime(2026, 10, 20, 16, 59, tzinfo=LONDON)] +
                 [datetime(2026, 10, 20, 17, 0, tzinfo=LONDON)] * 50)
    monkeypatch.setattr(automations(), "now", lambda: next(clock).astimezone(timezone.utc))
    run(db, on())
    assert len(sent) == 1


def test_an_invoice_settled_just_before_sending_is_not_chased(db, sent, monkeypatch):
    """Finding 4: approval re-applies the FULL receivables rule, not just a
    literal 'paid' status."""
    import services.aria_actions as aa
    real_propose = aa.propose
    iid = invoice(db, days_overdue=30, amount=500)

    def pay_then_propose(*a, **k):
        out = real_propose(*a, **k)
        with db.begin() as c:
            c.execute(text("UPDATE invoices SET paid_amount = 500 WHERE id = :i"), {"i": iid})
        return out
    monkeypatch.setattr(aa, "propose", pay_then_propose)
    run(db, on())
    assert sent == []


def test_a_chase_card_for_a_settled_invoice_cannot_be_approved_by_hand_either(db, sent):
    iid = invoice(db, days_overdue=30, amount=500)
    import services.aria_actions as aa
    with Session(db) as s:
        card = aa.propose(s, business(), "owner", "send_invoice_chase", {"invoice_id": iid},
                          owner_name="Mike")["proposal"]
    with db.begin() as c:
        c.execute(text("UPDATE invoices SET status = 'cancelled' WHERE id = :i"), {"i": iid})
    with Session(db) as s, pytest.raises(aa.ActionRefused):
        aa.approve(s, business(), card["id"], "owner", card["version"])
    assert sent == []


def test_a_stage_four_card_approved_by_the_owner_is_not_reported_as_autopilot(db, sent):
    """Finding 6: the home's "on her own" list is automatic SENDS only."""
    iid = invoice(db, days_overdue=60, stage=3, last_chased_days_ago=8)
    run(db, on())
    import services.aria_actions as aa
    with db.connect() as c:
        row = c.execute(text("SELECT id, payload FROM aria_actions")).fetchone()
    with Session(db) as s:
        aa.approve(s, business(), row[0], "owner", aa.version_of(json.loads(row[1])))
    from services import home_summary
    with db.connect() as c:
        assert home_summary.recent_automated(c, A, TUE_10.astimezone(timezone.utc)) == []
    assert stage_of(db, iid) == 4


def test_the_generic_settings_endpoint_cannot_change_the_autopilot(monkeypatch):
    """Finding 5: PUT /v1/business/settings replaces the document; it must
    keep the stored automations, whatever the client sends."""
    import main
    preserved = main.preserve_automations({"tone": "warm"},
                                          {"automations": {"invoice_chasing": {"enabled": True}}, "tone": "x"})
    assert preserved == {"tone": "warm", "automations": {"invoice_chasing": {"enabled": True}}}
    injected = main.preserve_automations({"automations": {"invoice_chasing": {"enabled": True}}}, {})
    assert "automations" not in injected


def test_settings_writes_are_serialised():
    """Finding 5: the automations endpoint locks the settings row it rewrites."""
    import inspect
    import automations_api
    assert "FOR UPDATE" in inspect.getsource(automations_api)
