"""BRIEF-1: Aria's weekly (Fridays 16:00, Monday to Friday) and monthly (the
1st, 08:00, the month just ended) WhatsApp briefings, replacing the daily
pulse (Mike, 5-6 Nov 2026). Built from stored data only; never sent without
its approved template; at most once per day each."""
import asyncio
import json
import uuid
from contextlib import contextmanager
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, text
from sqlmodel import Session

from services import whatsapp_briefings as wb

LONDON = ZoneInfo("Europe/London")
B = str(uuid.uuid4())


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv(wb.WEEKLY_SID_ENV, "HXweekly")
    monkeypatch.setenv(wb.MONTHLY_SID_ENV, "HXmonthly")
    engine = create_engine("sqlite:///" + str(tmp_path / "brief.sqlite"))
    with engine.begin() as c:
        for ddl in (
            "CREATE TABLE calls (id TEXT, business_id TEXT, source TEXT, outcome TEXT, started_at TIMESTAMP)",
            "CREATE TABLE email_messages (id TEXT, business_id TEXT, ai_category TEXT, received_at TIMESTAMP)",
            "CREATE TABLE invoices (id TEXT, business_id TEXT, status TEXT, amount NUMERIC, amount_due NUMERIC, "
            "amount_paid NUMERIC, paid_amount NUMERIC, due_date DATE, archived BOOLEAN)",
            "CREATE TABLE quotes (id TEXT, business_id TEXT, total NUMERIC, sent_at TIMESTAMP, accepted_at TIMESTAMP)",
            "CREATE TABLE accounting_categories (id TEXT, business_id TEXT, name TEXT)",
            "CREATE TABLE accounting_transactions (id TEXT, business_id TEXT, transaction_date DATE, description TEXT, "
            "payee_payer TEXT, category_id TEXT, type TEXT, amount NUMERIC, reference TEXT, external_source TEXT, "
            "external_id TEXT, import_id TEXT, is_reconciled BOOLEAN, is_archived BOOLEAN, created_at TIMESTAMP)",
            "CREATE TABLE whatsapp_messages (id TEXT, business_id TEXT, message_type TEXT, created_at TIMESTAMP, "
            "twilio_message_sid TEXT, related_entity_type TEXT)",
            # As live: id and timestamps have no default (settings_row supplies them).
            "CREATE TABLE business_settings (id TEXT NOT NULL, business_id TEXT PRIMARY KEY, settings TEXT NOT NULL, "
            "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)",
        ):
            c.execute(text(ddl))
    yield engine
    engine.dispose()


def add(db, table, **v):
    v.setdefault("id", str(uuid.uuid4()))
    v.setdefault("business_id", B)
    with db.begin() as c:
        c.execute(text(f"INSERT INTO {table} ({','.join(v)}) VALUES ({','.join(':' + k for k in v)})"), v)


def tx(db, day, kind, amount, category):
    cid = str(uuid.uuid4())
    add(db, "accounting_categories", id=cid, name=category)
    add(db, "accounting_transactions", transaction_date=day, type=kind, amount=amount, category_id=cid,
        is_archived=False, created_at=datetime(2026, 1, 1))


def local(*args):
    return datetime(*args, tzinfo=LONDON)


# ------------------------------------------------------------------ timing ---

@pytest.mark.parametrize("moment,due", [
    (local(2026, 11, 6, 15, 59), None),                                   # Friday, before 4pm
    (local(2026, 11, 6, 16, 0), (date(2026, 11, 2), date(2026, 11, 6))),  # Friday 4pm: Mon-Fri
    (local(2026, 11, 6, 21, 0), (date(2026, 11, 2), date(2026, 11, 6))),  # later the same Friday (restart)
    (local(2026, 11, 7, 16, 0), None),                                    # Saturday
])
def test_the_weekly_is_due_on_fridays_from_four(moment, due):
    assert wb.weekly_due(moment) == due


@pytest.mark.parametrize("moment,due", [
    (local(2026, 12, 1, 7, 59), None),
    (local(2026, 12, 1, 8, 0), (date(2026, 11, 1), date(2026, 11, 30))),
    (local(2027, 1, 1, 9, 0), (date(2026, 12, 1), date(2026, 12, 31))),   # across the year
    (local(2026, 3, 1, 8, 0), (date(2026, 2, 1), date(2026, 2, 28))),
    (local(2026, 12, 2, 8, 0), None),
])
def test_the_monthly_is_due_on_the_first_from_eight(moment, due):
    assert wb.monthly_due(moment) == due


# ----------------------------------------------------------------- content ---

def test_the_weekly_figures(db):
    for outcome in ("handled", "handled", "appointment_booked", "transferred", "missed"):
        add(db, "calls", source="receptionist", outcome=outcome, started_at=datetime(2026, 11, 3, 10))
    add(db, "calls", source="receptionist", outcome="handled", started_at=datetime(2026, 10, 30, 10))  # last week
    for cat in ("Action Required", "Action Required", "FYI", "Newsletter"):
        add(db, "email_messages", ai_category=cat, received_at=datetime(2026, 11, 4, 9))
    tx(db, date(2026, 11, 3), "income", 4210, "Sales")
    tx(db, date(2026, 11, 4), "expense", 2980, "Wages")
    tx(db, date(2026, 11, 9), "income", 999, "Sales")                     # next week: not counted
    add(db, "invoices", status="unpaid", amount=1150, amount_due=1150, due_date=date(2026, 11, 20), archived=False)
    add(db, "invoices", status="unpaid", amount=300, amount_due=300, due_date=date(2026, 10, 1), archived=False)
    add(db, "invoices", status="paid", amount=5000, amount_due=0, due_date=date(2026, 10, 1), archived=False)
    add(db, "quotes", total=6800, sent_at=datetime(2026, 11, 2, 12), accepted_at=None)
    add(db, "quotes", total=2400, sent_at=datetime(2026, 10, 20, 12), accepted_at=datetime(2026, 11, 5, 12))
    with Session(db) as s:
        v = wb.weekly_variables(s, B, "Mike Rickards", "New Body", date(2026, 11, 2), date(2026, 11, 6))
    assert v == {"1": "Mike", "2": "Mon 2 – Fri 6 Nov",
                 "3": "5 calls, 4 answered by Aria (1 booking), 1 missed",
                 "4": "4 received, 2 need action",
                 "5": "£4,210 in, £2,980 out, £1,230 ahead",
                 "6": "2 unpaid (£1,450), 1 overdue (£300)",
                 "7": "1 sent (£6,800), 1 accepted (£2,400)"}


def test_a_quiet_week_says_so_never_a_row_of_zeros(db):
    with Session(db) as s:
        v = wb.weekly_variables(s, B, "", "New Body", date(2026, 11, 2), date(2026, 11, 6))
    assert v["1"] == "New Body"
    assert v["3"] == "No calls" and v["4"] == "None received" and v["7"] == "None sent this week"
    assert v["5"] == "No transactions recorded yet" and v["6"] == "None unpaid"
    assert all(v.values()), "no blank value: WhatsApp refuses a template with one"


def test_a_week_behind(db):
    tx(db, date(2026, 11, 3), "income", 100, "Sales")
    tx(db, date(2026, 11, 3), "expense", 350, "Rent")
    with Session(db) as s:
        assert wb.weekly_variables(s, B, "", "X", date(2026, 11, 2), date(2026, 11, 6))["5"] == "£100 in, £350 out, £250 behind"


def test_the_monthly_figures(db):
    tx(db, date(2026, 10, 3), "income", 18400, "Sales")
    for cat, amount in (("Wages", 7900), ("Rent", 2500), ("Equipment", 1100), ("Phone", 80)):
        tx(db, date(2026, 10, 10), "expense", amount, cat)
    tx(db, date(2026, 9, 3), "income", 5000, "Sales")                     # September: profit 5,000 - 2,520
    tx(db, date(2026, 9, 9), "expense", 2520, "Wages")
    tx(db, date(2026, 11, 1), "income", 777, "Sales")                     # November: not counted
    add(db, "invoices", status="unpaid", amount=1150, amount_due=1150, due_date=date(2026, 11, 20), archived=False)
    add(db, "invoices", status="unpaid", amount=300, amount_due=300, due_date=date(2026, 10, 1), archived=False)
    with Session(db) as s:
        v = wb.monthly_variables(s, B, "Mike", "New Body", date(2026, 10, 1), date(2026, 10, 31))
    assert v == {"1": "Mike", "2": "October",
                 "3": "Profit of £6,820 (up £4,340 on September)",
                 "4": "£18,400", "5": "£11,580",
                 "6": "Wages £7,900, Rent £2,500, Equipment £1,100",
                 "7": "£1,450 unpaid, £300 overdue"}


def test_a_loss_and_no_prior_month(db):
    tx(db, date(2026, 10, 3), "income", 1000, "Sales")
    tx(db, date(2026, 10, 9), "expense", 1500, "Rent")
    with Session(db) as s:
        v = wb.monthly_variables(s, B, "", "X", date(2026, 10, 1), date(2026, 10, 31))
    assert v["3"] == "Loss of £500" and v["7"] == "Nothing outstanding"


def test_an_empty_month_says_so(db):
    with Session(db) as s:
        v = wb.monthly_variables(s, B, "", "X", date(2026, 10, 1), date(2026, 10, 31))
    assert v["3"] == "No transactions recorded for the month" and v["6"] == "None recorded"
    assert all(v.values())


# -------------------------------------------------------------------- send ---

def run(db, config, moment, *, accepted=True):
    sent = []

    async def send(**kw):
        sent.append(kw)
        sid = "MM1" if accepted else None
        with db.begin() as c:   # as whatsapp_service logs every attempt, failed ones without a SID
            c.execute(text("INSERT INTO whatsapp_messages (id, business_id, message_type, created_at, "
                           "twilio_message_sid, related_entity_type) VALUES (:i, :b, :t, :at, :sid, :r)"),
                      {"i": str(uuid.uuid4()), "b": kw["business_id"], "t": kw["message_type"], "at": moment,
                       "sid": sid, "r": kw.get("related_entity_type")})
        return sid

    @contextmanager
    def factory():
        with Session(db) as s:
            yield s
    out = asyncio.run(wb.run_for(config, moment, session_factory=factory, send=send))
    return out, sent


CONFIG = {"business_id": B, "phone_number": "+447700900000", "owner_name": "Mike", "business_name": "New Body",
          "weekly_briefing_enabled": True, "daily_pulse_enabled": False}


def test_the_weekly_is_sent_once_with_its_template(db):
    out, sent = run(db, CONFIG, local(2026, 11, 6, 16, 0))
    assert out == [wb.WEEKLY] and sent[0]["message_type"] == "weekly_summary"
    assert set(json.loads(sent[0]["body"])) == {str(i) for i in range(1, 8)}
    out, sent = run(db, CONFIG, local(2026, 11, 6, 16, 1))
    assert out == [] and sent == [], "never twice the same day"


def test_without_the_template_nothing_is_sent_or_logged(db, monkeypatch):
    monkeypatch.delenv(wb.WEEKLY_SID_ENV)
    out, sent = run(db, CONFIG, local(2026, 11, 6, 16, 0))
    assert out == [] and sent == []
    with db.connect() as c:
        assert c.execute(text("SELECT count(*) FROM whatsapp_messages")).scalar() == 0, \
            "a later approval still sends that day"


def test_the_daily_pulse_switch_still_means_briefings(db):
    out, _ = run(db, {**CONFIG, "weekly_briefing_enabled": False, "daily_pulse_enabled": True},
                 local(2026, 12, 1, 8, 0))
    assert out == [wb.MONTHLY]


def test_both_switches_off_sends_nothing(db):
    out, sent = run(db, {**CONFIG, "weekly_briefing_enabled": False}, local(2026, 11, 6, 16, 0))
    assert out == [] and sent == []


def test_a_friday_the_first_sends_both(db):
    out, _ = run(db, CONFIG, local(2027, 1, 1, 16, 30))       # Friday 1 January 2027
    assert out == [wb.WEEKLY, wb.MONTHLY]


def test_the_templates_are_registered_with_seven_variables():
    from services import whatsapp_service as ws
    assert ws.TEMPLATE_VARIABLE_COUNTS["weekly_summary"] == 7
    assert ws.TEMPLATE_VARIABLE_COUNTS["monthly_financial"] == 7
    assert "weekly_summary" in ws.TEMPLATE_SID_MAP and "monthly_financial" in ws.TEMPLATE_SID_MAP


def test_the_scheduler_no_longer_sends_a_daily_pulse():
    import inspect
    from services import briefing_scheduler as bs
    source = inspect.getsource(bs)
    assert "_send_daily_pulse" not in source and "_send_weekly_briefing" not in source
    assert "whatsapp_briefings.run_for" in source


def test_the_edges_of_the_week_and_of_each_count(db):
    """Friday afternoon counts; a call that failed is missed; a call taken by
    a person isn't credited to Aria; an invoice due today isn't overdue yet."""
    add(db, "calls", source="receptionist", outcome="handled", started_at=datetime(2026, 11, 6, 15, 30))  # Friday
    add(db, "calls", source="receptionist", outcome="error", started_at=datetime(2026, 11, 2, 9))
    add(db, "calls", source="Awaz", outcome="handled", started_at=datetime(2026, 11, 3, 9))
    add(db, "invoices", status="unpaid", amount=200, amount_due=200, due_date=date(2026, 11, 6), archived=False)
    with Session(db) as s:
        v = wb.weekly_variables(s, B, "", "X", date(2026, 11, 2), date(2026, 11, 6))
    assert v["3"] == "3 calls, 1 answered by Aria, 1 missed"
    assert v["6"] == "1 unpaid (£200), 0 overdue"


def _owner(db):
    with db.begin() as c:
        c.execute(text("CREATE TABLE IF NOT EXISTS whatsapp_configs (business_id TEXT, phone_number TEXT, owner_name TEXT)"))
        c.execute(text("CREATE TABLE IF NOT EXISTS businesses (id TEXT, name TEXT)"))
        c.execute(text("INSERT INTO whatsapp_configs VALUES (:b, '+447700900000', 'Mike')"), {"b": B})
        c.execute(text("INSERT INTO businesses VALUES (:b, 'New Body')"), {"b": B})


def test_a_test_send_uses_the_real_template_and_period(db):
    _owner(db)
    tx(db, date(2026, 11, 2), "income", 50, "Sales")       # Monday of this week
    tx(db, date(2026, 10, 15), "income", 900, "Sales")     # last month
    sent = []

    async def send(**kw):
        sent.append(kw)
        return "MM9"
    with Session(db) as s:
        assert asyncio.run(wb.send_test(s, B, wb.WEEKLY, date(2026, 11, 4), send=send))["sent"] is True
        assert asyncio.run(wb.send_test(s, B, wb.MONTHLY, date(2026, 11, 4), send=send))["sent"] is True
    week, month = (json.loads(k["body"]) for k in sent)
    assert week["2"] == "Mon 2 – Wed 4 Nov" and week["5"].startswith("£50 in")
    assert month["2"] == "October" and month["4"] == "£900"
    assert [k["message_type"] for k in sent] == ["weekly_summary", "monthly_financial"]


def test_a_test_send_without_the_template_says_why_and_sends_nothing(db, monkeypatch):
    _owner(db)
    monkeypatch.delenv(wb.MONTHLY_SID_ENV)

    async def send(**kw):
        raise AssertionError("must not send")
    with Session(db) as s:
        out = asyncio.run(wb.send_test(s, B, wb.MONTHLY, date(2026, 11, 4), send=send))
    assert out["sent"] is False and "template" in out["detail"]


# --------------------------------------------- Codex BRIEF-1 review 1 fixes ---

def test_every_kind_of_owed_invoice_counts_at_its_real_balance(db):
    add(db, "invoices", status="partially_paid", amount=1000, amount_due=1000, paid_amount=600,
        due_date=date(2026, 11, 20), archived=False)                        # manual part-payment: £400 left
    add(db, "invoices", status="AUTHORISED", amount=500, amount_due=200, amount_paid=300,
        due_date=date(2026, 10, 1), archived=False)                         # Xero, part-paid, late: £200
    add(db, "invoices", status="overdue", amount=90, amount_due=90, due_date=date(2026, 12, 1), archived=False)
    add(db, "invoices", status="DRAFT", amount=7000, amount_due=7000, due_date=date(2026, 10, 1), archived=False)
    add(db, "invoices", status="PAID", amount=50, amount_due=0, due_date=date(2026, 10, 1), archived=False)
    add(db, "invoices", status="unpaid", amount=60, amount_due=60, due_date=date(2026, 10, 1), archived=True)
    with Session(db) as s:
        assert wb._owed(s, B, date(2026, 11, 6)) == (3, 690, 2, 290)


def test_a_call_with_no_outcome_is_never_credited_to_aria(db):
    add(db, "calls", source="receptionist", outcome=None, started_at=datetime(2026, 11, 3, 10))
    add(db, "calls", source="receptionist", outcome="voicemail", started_at=datetime(2026, 11, 3, 11))
    with Session(db) as s:
        assert wb._calls(s, B, date(2026, 11, 2), date(2026, 11, 6)) == "2 calls, 0 answered by Aria, 0 missed"


def test_a_failed_send_is_retried_but_not_forever(db):
    moment = local(2026, 11, 6, 16, 0)
    for attempt in range(wb.SEND_ATTEMPTS):
        out, sent = run(db, CONFIG, moment, accepted=False)
        assert out == [] and len(sent) == 1, f"attempt {attempt + 1} is made"
    out, sent = run(db, CONFIG, moment, accepted=False)
    assert sent == [], "then it stops for the day"


def test_a_test_send_never_stops_the_scheduled_one(db):
    _owner(db)

    async def send(**kw):
        with db.begin() as c:
            c.execute(text("INSERT INTO whatsapp_messages (id, business_id, message_type, created_at, "
                           "twilio_message_sid, related_entity_type) VALUES (:i, :b, :t, :at, 'MMt', :r)"),
                      {"i": str(uuid.uuid4()), "b": B, "t": kw["message_type"], "at": local(2026, 11, 6, 9, 0),
                       "r": kw["related_entity_type"]})
        return "MMt"
    with Session(db) as s:
        asyncio.run(wb.send_test(s, B, wb.WEEKLY, date(2026, 11, 6), send=send))
    out, _ = run(db, CONFIG, local(2026, 11, 6, 16, 0))
    assert out == [wb.WEEKLY]


def test_an_unaccepted_test_send_says_so(db):
    _owner(db)

    async def send(**kw):
        return None
    with Session(db) as s:
        out = asyncio.run(wb.send_test(s, B, wb.WEEKLY, date(2026, 11, 6), send=send))
    assert out["sent"] is False and out["detail"]


# --------------------------------------------- Codex BRIEF-1 review 2 fixes ---

def test_a_second_scheduler_during_a_send_never_sends_too(db):
    """Two replicas (or two ticks) at once: the claim is taken before sending."""
    inner = []

    async def send(**kw):
        @contextmanager
        def factory():
            with Session(db) as s:
                yield s

        async def never(**kw2):
            inner.append(kw2)
            return "MM2"
        await wb.run_for(CONFIG, local(2026, 11, 6, 16, 1), session_factory=factory, send=never)
        return "MM1"

    @contextmanager
    def factory():
        with Session(db) as s:
            yield s
    out = asyncio.run(wb.run_for(CONFIG, local(2026, 11, 6, 16, 0), session_factory=factory, send=send))
    assert out == [wb.WEEKLY] and inner == []


def test_delivery_never_depends_on_the_message_log(db):
    """WhatsApp accepted it but the log row was lost: still never sent twice."""
    sent = []

    async def send(**kw):
        sent.append(kw)
        return "MM1"       # accepted, and nothing logged

    @contextmanager
    def factory():
        with Session(db) as s:
            yield s
    for minute in (0, 1, 2):
        asyncio.run(wb.run_for(CONFIG, local(2026, 11, 6, 16, minute), session_factory=factory, send=send))
    assert len(sent) == 1


def test_a_crash_mid_send_is_retried_only_after_the_in_flight_window(db):
    @contextmanager
    def factory():
        with Session(db) as s:
            yield s
    with Session(db) as s:   # a claim taken by a process that then died, never settled
        assert wb._claim(s, B, wb.WEEKLY, date(2026, 11, 6), local(2026, 11, 6, 16, 0))
    sent = []

    async def send(**kw):
        sent.append(kw)
        return "MM1"
    asyncio.run(wb.run_for(CONFIG, local(2026, 11, 6, 16, 4), session_factory=factory, send=send))
    assert sent == [], "still in flight"
    asyncio.run(wb.run_for(CONFIG, local(2026, 11, 6, 16, 6), session_factory=factory, send=send))
    assert len(sent) == 1, "then retried"


def test_an_exception_in_the_send_frees_the_claim_for_a_retry(db):
    @contextmanager
    def factory():
        with Session(db) as s:
            yield s

    async def boom(**kw):
        raise RuntimeError("network")
    with pytest.raises(RuntimeError):
        asyncio.run(wb.run_for(CONFIG, local(2026, 11, 6, 16, 0), session_factory=factory, send=boom))
    out, sent = run(db, CONFIG, local(2026, 11, 6, 16, 1))
    assert out == [wb.WEEKLY]


# --------------------------------------------- Codex BRIEF-1 review 3 fixes ---

def test_a_settings_save_never_erases_the_delivery_record():
    from main import preserve_automations
    existing = {"whatsapp_briefings": {"weekly_summary": {"day": "2026-11-06", "delivered": True}}, "theme": "dark"}
    out = preserve_automations({"theme": "light", "whatsapp_briefings": {}}, existing)
    assert out["whatsapp_briefings"] == existing["whatsapp_briefings"] and out["theme"] == "light"


def test_an_expired_attempt_finishing_late_never_frees_its_successors_claim(db):
    day = date(2026, 11, 6)
    with Session(db) as s:
        a = wb._claim(s, B, wb.WEEKLY, day, local(2026, 11, 6, 16, 0))
    with Session(db) as s:
        b = wb._claim(s, B, wb.WEEKLY, day, local(2026, 11, 6, 16, 6))      # after A's window
    assert a and b and a != b
    with Session(db) as s:
        wb._settle(s, B, wb.WEEKLY, day, False, a)                         # A gives up, late
    with Session(db) as s:
        assert not wb._claim(s, B, wb.WEEKLY, day, local(2026, 11, 6, 16, 7)), "B is still in flight"
    with Session(db) as s:
        wb._settle(s, B, wb.WEEKLY, day, True, b)
    with Session(db) as s:
        assert not wb._claim(s, B, wb.WEEKLY, day, local(2026, 11, 6, 16, 8)), "delivered"
