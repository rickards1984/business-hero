"""AUTO-2 — Aria watches for replies to invoice chases.

docs/AUTO-2-TICKET.md; Mike, 19 Oct 2026: flag the owner on any reply; when a
customer says they've paid, show it and close chasing.

Tests first (RED: whether automatic contact about money continues). Strict
xfail may fail only because `services.chase_replies` does not exist yet.

The contract (backend/services/chase_replies.py):
  REPLY_WINDOW_DAYS = 60; FRESH_WITHIN = timedelta(hours=3)
  scan(session, business, *, classify) -> [reply dict]       new replies only
      classify(text) -> {"category": paid|promise|dispute|question|other,
                         "summary": str}; raising means category "unknown"
  open_replies(session, business) -> [reply dict]
  resolve(session, business, reply_id, user_id, decision)     "resume" | "stop"
      LookupError for another business's / unknown reply; ValueError otherwise
  inbox_ready(session, business, account_id, moment) -> None | "inbox_not_fresh"
  default_mailbox(session, business_id) -> account id | None
  sync_complete(provider, listed_ids, fetched_ids, known_ids, page_size=50) -> bool
automations.run_invoice_autopilot gains the skip reasons "customer_replied",
"chasing_stopped", "inbox_not_fresh" and "no_default_mailbox".
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


class MissingReplies(AssertionError):
    """Only this precise, intentional Stage 1 absence may be xfailed."""


# Stage 1's strict-xfail marker was removed once the implementation landed.

A, B = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
LONDON = ZoneInfo("Europe/London")
TUE_10 = datetime(2026, 10, 20, 10, 0, tzinfo=LONDON)   # Tuesday 20 October 2026
UTC_NOW = TUE_10.astimezone(timezone.utc)
CUSTOMER = "pay@harper.example"
ACCT_A, ACCT_B = "acct-aaaa", "acct-bbbb"


def replies():
    if importlib.util.find_spec("services.chase_replies") is None:
        raise MissingReplies("backend/services/chase_replies.py does not exist yet")
    return importlib.import_module("services.chase_replies")


def automations():
    replies()
    return importlib.import_module("services.automations")


def business(bid=A):
    return SimpleNamespace(id=bid, plan_tier="pro", name="New Body Gym", timezone="Europe/London",
                           subscription_status="active", is_active=True, trial_ends_at=None,
                           feature_flags={})


def on(**overrides):
    return {**automations().chase_settings(None), "enabled": True, **overrides}


def iso(moment):
    return moment.astimezone(timezone.utc).isoformat()


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
            last_chased_at TEXT, updated_at TEXT, external_id TEXT, paid_at TEXT, paid_date TEXT)"""))
        c.execute(text("""CREATE TABLE email_accounts (id TEXT PRIMARY KEY, business_id TEXT NOT NULL,
            provider TEXT, email_address TEXT, is_default BOOLEAN DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP)"""))
        c.execute(text("""CREATE TABLE email_outbox (id TEXT PRIMARY KEY, business_id TEXT NOT NULL,
            email_account_id TEXT NOT NULL, to_emails TEXT NOT NULL, subject TEXT NOT NULL,
            body_preview TEXT NOT NULL, status TEXT NOT NULL, invoice_id TEXT, chase_stage INTEGER,
            provider_message_id TEXT, sent_at TEXT, error TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"""))
        c.execute(text("""CREATE TABLE email_messages (id TEXT PRIMARY KEY, business_id TEXT NOT NULL,
            email_account_id TEXT NOT NULL, provider_message_id TEXT NOT NULL,
            provider_thread_id TEXT, folder TEXT, from_email TEXT, from_name TEXT, to_emails TEXT,
            subject TEXT, snippet TEXT, body_text TEXT, received_at TEXT, ai_category TEXT)"""))
        c.execute(text("""CREATE TABLE email_sync_states (id TEXT PRIMARY KEY,
            email_account_id TEXT NOT NULL UNIQUE, cursor TEXT DEFAULT '{}', last_synced_at TEXT,
            sync_status TEXT, last_error TEXT)"""))
        c.execute(text("""CREATE TABLE usage_meters (
            id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            business_id TEXT NOT NULL, meter TEXT NOT NULL, period TEXT NOT NULL,
            value TEXT NOT NULL DEFAULT '0', created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP)"""))
        c.execute(text("CREATE UNIQUE INDEX usage_meters_uq ON usage_meters (business_id, meter, period)"))
        # Read by the home summary (its accounts-sync line).
        c.execute(text("CREATE TABLE xero_connections (business_id TEXT, last_sync_at TEXT)"))
        c.execute(text("CREATE TABLE accounting_connections (business_id TEXT, last_sync_at TEXT)"))
        # Migration 036, as SQLite can hold it.
        c.execute(text("""CREATE TABLE chase_replies (id TEXT PRIMARY KEY, business_id TEXT NOT NULL,
            email_message_id TEXT NOT NULL, customer_email TEXT NOT NULL, invoice_ids TEXT NOT NULL,
            category TEXT NOT NULL, summary TEXT, status TEXT NOT NULL DEFAULT 'open',
            resolved_by TEXT, resolved_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            UNIQUE (business_id, email_message_id))"""))
        for bid, acct in ((A, ACCT_A), (B, ACCT_B)):
            c.execute(text("INSERT INTO email_accounts (id, business_id, provider, email_address, "
                           "is_default, created_at) VALUES (:id, :b, 'google', :e, 1, '2026-01-01')"),
                      {"id": acct, "b": bid, "e": f"owner@{bid[:4]}.example"})
            fresh(c, acct)
    yield eng
    eng.dispose()


def fresh(c, acct, *, ago=timedelta(minutes=20), complete=True, status="ok"):
    c.execute(text("DELETE FROM email_sync_states WHERE email_account_id = :a"), {"a": acct})
    c.execute(text("INSERT INTO email_sync_states (id, email_account_id, cursor, last_synced_at, "
                   "sync_status) VALUES (:id, :a, :cur, :at, :st)"),
              {"id": f"sync-{acct}", "a": acct, "cur": json.dumps({"complete": complete}),
               "at": iso(TUE_10 - ago), "st": status})


_n = {"i": 0}


def invoice(eng, *, bid=A, days_overdue=30, stage=0, last_chased_days_ago=None, email=CUSTOMER):
    _n["i"] += 1
    iid = f"00000000-0000-4000-8000-{_n['i']:012d}"
    due = (TUE_10 - timedelta(days=days_overdue)).date().isoformat()
    last = None if last_chased_days_ago is None else iso(TUE_10 - timedelta(days=last_chased_days_ago))
    with eng.begin() as c:
        c.execute(text("""INSERT INTO invoices (id, business_id, invoice_number, customer_name,
            customer_email, amount, amount_due, status, chase_stage, due_date, last_chased_at)
            VALUES (:id, :b, :n, 'Harper Builds', :e, 500, 500, 'sent', :st, :d, :l)"""),
                  {"id": iid, "b": bid, "n": f"INV-{_n['i']:04d}", "e": email, "st": stage,
                   "d": due, "l": last})
    return iid


def number_of(eng, iid):
    with eng.connect() as c:
        return c.execute(text("SELECT invoice_number FROM invoices WHERE id=:i"), {"i": iid}).scalar()


def chased(eng, iid, *, days_ago=3, bid=A, automatic=True, thread=None, email=CUSTOMER):
    """A chase that went: the action record and the invoice's chase marks."""
    _n["i"] += 1
    at = iso(TUE_10 - timedelta(days=days_ago))
    payload = {"invoice_id": iid, "chase_stage": 1, "to": email, "subject": "Reminder",
               "body": "Please pay", "sign_off": "Aria"}
    if automatic:
        payload["automation"] = "invoice_chasing"
    with eng.begin() as c:
        c.execute(text("""INSERT INTO aria_actions (id, business_id, action_type, payload, status,
            approved_by, expires_at, result, created_at, updated_at) VALUES (:id, :b,
            'send_invoice_chase', :p, 'done', :by, :at, :r, :at, :at)"""),
                  {"id": f"act-{_n['i']}", "b": bid, "p": json.dumps(payload),
                   "by": None if automatic else "owner-uuid", "at": at,
                   "r": json.dumps({"success": True, "gmail_message_id": f"gm-{_n['i']}",
                                    "gmail_thread_id": thread})})
        c.execute(text("UPDATE invoices SET chase_stage = 1, last_chased_at = :at WHERE id = :i"),
                  {"at": at, "i": iid})


def inbound(eng, *, bid=A, acct=None, frm=CUSTOMER, hours_ago=2, subject="Re: Reminder",
            snippet="Thanks", thread=None, mid=None):
    _n["i"] += 1
    mid = mid or f"msg-{_n['i']}"
    with eng.begin() as c:
        c.execute(text("""INSERT INTO email_messages (id, business_id, email_account_id,
            provider_message_id, provider_thread_id, folder, from_email, subject, snippet,
            received_at) VALUES (:id, :b, :a, :m, :t, 'INBOX', :f, :s, :sn, :at)"""),
                  {"id": f"em-{mid}", "b": bid, "a": acct or (ACCT_A if bid == A else ACCT_B),
                   "m": mid, "t": thread, "f": frm, "s": subject, "sn": snippet,
                   "at": iso(TUE_10 - timedelta(hours=hours_ago))})
    return f"em-{mid}"


def says(category, summary="They replied"):
    calls = []

    def classify(text_):
        calls.append(text_)
        return {"category": category, "summary": summary}
    classify.calls = calls
    return classify


def scan(eng, classify=None, bid=A):
    with Session(eng) as s:
        return replies().scan(s, business(bid), classify=classify or says("other"))


def open_now(eng, bid=A):
    with Session(eng) as s:
        return replies().open_replies(s, business(bid))


def resolve(eng, reply_id, decision, bid=A):
    with Session(eng) as s:
        return replies().resolve(s, business(bid), reply_id, "owner-uuid", decision)


@pytest.fixture
def sent(monkeypatch):
    import assistant_tools
    out = []

    def _send(engine, business_id, args):
        out.append((business_id, dict(args)))
        return {"success": True, "sent": True, "gmail_message_id": f"gm-out-{len(out)}",
                "gmail_thread_id": f"gt-out-{len(out)}"}
    monkeypatch.setattr(assistant_tools, "_send_email", _send)
    try:
        monkeypatch.setattr(replies(), "now", lambda: UTC_NOW)
        monkeypatch.setattr(automations(), "now", lambda: UTC_NOW)
        import services.aria_actions as aa
        monkeypatch.setattr(aa, "now", lambda: UTC_NOW)
    except MissingReplies:
        pass
    return out


def autopilot(eng, settings=None, bid=A):
    with Session(eng) as s:
        return automations().run_invoice_autopilot(s, business(bid), settings or on(),
                                                   owner_name="Mike")


# ------------------------------------------------------------ what counts ---

def test_a_reply_from_a_chased_customer_after_the_chase_is_flagged(db, sent):
    iid = invoice(db)
    chased(db, iid)
    mid = inbound(db)
    new = scan(db)
    assert len(new) == 1
    r = new[0]
    assert (r["customer_email"], r["status"], r["email_message_id"]) == (CUSTOMER, "open", mid)
    assert r["invoice_ids"] == [iid]


def test_a_reply_to_a_chase_the_owner_approved_is_flagged_too(db, sent):
    """Mike: flag the owner on ANY reply to a chase — not only automatic ones."""
    iid = invoice(db)
    chased(db, iid, automatic=False)
    inbound(db)
    assert len(scan(db)) == 1


def test_the_sender_match_ignores_case_and_spaces(db, sent):
    iid = invoice(db)
    chased(db, iid)
    inbound(db, frm="  Pay@Harper.Example ")
    assert len(scan(db)) == 1


@pytest.mark.parametrize("frm", ["someone@else.example", "owner@aaaa.example"])
def test_unrelated_senders_and_the_business_itself_are_not_replies(db, sent, frm):
    iid = invoice(db)
    chased(db, iid)
    inbound(db, frm=frm)
    assert scan(db) == []


def test_an_email_from_before_the_chase_is_not_a_reply(db, sent):
    iid = invoice(db)
    chased(db, iid, days_ago=1)
    inbound(db, hours_ago=48)
    assert scan(db) == []


def test_a_chase_more_than_sixty_days_ago_no_longer_matches(db, sent):
    iid = invoice(db, days_overdue=120)
    chased(db, iid, days_ago=61)
    inbound(db)
    assert scan(db) == []


def test_another_business_inbox_never_flags_this_business(db, sent):
    iid = invoice(db)
    chased(db, iid)
    inbound(db, bid=B)             # the same customer wrote to business B
    assert scan(db) == [] and open_now(db) == []


def test_another_business_chase_does_not_make_a_reply_here(db, sent):
    other = invoice(db, bid=B)
    chased(db, other, bid=B)
    inbound(db)                    # the customer wrote to A, whom A never chased
    assert scan(db) == []


def test_scanning_twice_flags_a_message_once(db, sent):
    iid = invoice(db)
    chased(db, iid)
    inbound(db)
    assert len(scan(db)) == 1
    assert scan(db) == []
    assert len(open_now(db)) == 1


# ------------------------------------------------------------ which invoice ---

def test_the_thread_names_the_invoice(db, sent):
    one, two = invoice(db), invoice(db)
    chased(db, one, thread="gt-1")
    chased(db, two, thread="gt-2")
    inbound(db, thread="gt-2", subject="Re: Reminder")
    assert scan(db)[0]["invoice_ids"] == [two]


def test_an_invoice_number_in_the_subject_names_the_invoice(db, sent):
    one, two = invoice(db), invoice(db)
    chased(db, one)
    chased(db, two)
    inbound(db, subject=f"About {number_of(db, one)}")
    assert scan(db)[0]["invoice_ids"] == [one]


def test_otherwise_it_is_about_every_invoice_of_theirs_that_was_chased(db, sent):
    one, two = invoice(db), invoice(db)
    never = invoice(db, days_overdue=2)
    chased(db, one)
    chased(db, two)
    inbound(db, subject="Hello", snippet="Call me")
    ids = scan(db)[0]["invoice_ids"]
    assert sorted(ids) == sorted([one, two]) and never not in ids


# ------------------------------------------------------------ reading it ---

@pytest.mark.parametrize("category", ["paid", "promise", "dispute", "question", "other"])
def test_aria_labels_the_reply(db, sent, category):
    iid = invoice(db)
    chased(db, iid)
    inbound(db, snippet="I paid this yesterday")
    classify = says(category, "Says they paid yesterday")
    r = scan(db, classify)[0]
    assert (r["category"], r["summary"]) == (category, "Says they paid yesterday")
    assert "I paid this yesterday" in classify.calls[0]


def test_if_reading_fails_it_is_still_flagged_as_unknown(db, sent):
    iid = invoice(db)
    chased(db, iid)
    inbound(db)

    def broken(text_):
        raise RuntimeError("model unavailable")
    r = scan(db, broken)[0]
    assert (r["category"], r["status"]) == ("unknown", "open")


def test_a_label_outside_the_list_is_unknown(db, sent):
    iid = invoice(db)
    chased(db, iid)
    inbound(db)
    assert scan(db, says("send_them_a_refund"))[0]["category"] == "unknown"


def test_says_paid_never_marks_the_invoice_paid(db, sent):
    iid = invoice(db)
    chased(db, iid)
    inbound(db, snippet="Paid in full this morning")
    r = scan(db, says("paid"))[0]
    resolve(db, r["id"], "stop")
    with db.connect() as c:
        row = c.execute(text("SELECT status, amount_paid, paid_amount, paid_at, paid_date "
                             "FROM invoices WHERE id=:i"), {"i": iid}).fetchone()
    assert row.status == "sent" and not row.amount_paid and row.paid_amount is None
    assert row.paid_at is None and row.paid_date is None


# ------------------------------------------------------------ chasing pauses ---

def test_any_reply_pauses_automatic_chasing_for_that_customer(db, sent):
    one = invoice(db, stage=1, last_chased_days_ago=10)
    two = invoice(db, days_overdue=40)
    chased(db, one, days_ago=10)
    inbound(db, hours_ago=200)
    scan(db, says("question"))
    result = autopilot(db)
    assert sent == [] and result["sent"] == []
    assert result["skipped"].get(one) == "customer_replied"
    assert result["skipped"].get(two) == "customer_replied"


def test_a_paused_customer_gets_no_final_stage_card_either(db, sent):
    iid = invoice(db, days_overdue=60, stage=3, last_chased_days_ago=8)
    chased(db, iid, days_ago=8)
    inbound(db, hours_ago=100)
    scan(db)
    result = autopilot(db)
    assert result["cards"] == [] and result["skipped"].get(iid) == "customer_replied"


def test_other_customers_are_still_chased(db, sent):
    mine = invoice(db, stage=1, last_chased_days_ago=10)
    chased(db, mine, days_ago=10)
    inbound(db, hours_ago=200)
    scan(db)
    other = invoice(db, email="accounts@other.example")
    assert autopilot(db)["sent"] == [other]


def test_resume_lets_chasing_continue_under_the_normal_rules(db, sent):
    iid = invoice(db, stage=1, last_chased_days_ago=10)
    chased(db, iid, days_ago=10)
    inbound(db, hours_ago=200)
    r = scan(db)[0]
    resolve(db, r["id"], "resume")
    assert open_now(db) == []
    assert autopilot(db)["sent"] == [iid]


def test_stop_ends_automatic_chasing_of_that_invoice_only(db, sent):
    stopped = invoice(db, stage=1, last_chased_days_ago=10)
    chased(db, stopped, days_ago=10)
    inbound(db, hours_ago=200, subject=f"Re: {number_of(db, stopped)}")
    r = scan(db, says("paid"))[0]
    assert r["invoice_ids"] == [stopped]
    resolve(db, r["id"], "stop")
    later = invoice(db, days_overdue=10)
    result = autopilot(db)
    assert result["skipped"].get(stopped) == "chasing_stopped"
    assert result["sent"] == [later]


def test_a_new_reply_after_resuming_pauses_again(db, sent):
    iid = invoice(db, stage=1, last_chased_days_ago=10)
    chased(db, iid, days_ago=10)
    inbound(db, hours_ago=200)
    resolve(db, scan(db)[0]["id"], "resume")
    inbound(db, hours_ago=1)
    scan(db)
    assert autopilot(db)["skipped"].get(iid) == "customer_replied"


# ------------------------------------------------------------ the owner ---

def test_open_replies_are_listed_for_the_owner(db, sent):
    iid = invoice(db)
    chased(db, iid)
    inbound(db, snippet="Paid yesterday")
    scan(db, says("paid", "Says they paid yesterday"))
    [r] = open_now(db)
    assert r["category"] == "paid" and r["summary"] == "Says they paid yesterday"
    assert r["customer_email"] == CUSTOMER and r["invoice_ids"] == [iid]
    assert r["invoice_numbers"] == [number_of(db, iid)]


def test_resolving_records_who_and_when(db, sent):
    iid = invoice(db)
    chased(db, iid)
    inbound(db)
    r = scan(db)[0]
    resolve(db, r["id"], "stop")
    with db.connect() as c:
        row = c.execute(text("SELECT status, resolved_by, resolved_at FROM chase_replies")).fetchone()
    assert row.status == "stopped" and row.resolved_by == "owner-uuid" and row.resolved_at


def test_a_business_cannot_resolve_another_business_reply(db, sent):
    iid = invoice(db)
    chased(db, iid)
    inbound(db)
    r = scan(db)[0]
    with pytest.raises(LookupError):
        resolve(db, r["id"], "resume", bid=B)
    assert open_now(db)[0]["status"] == "open"


def test_an_unknown_decision_is_refused(db, sent):
    iid = invoice(db)
    chased(db, iid)
    inbound(db)
    with pytest.raises(ValueError):
        resolve(db, scan(db)[0]["id"], "mark_paid")


def test_a_resolved_reply_cannot_be_resolved_again(db, sent):
    iid = invoice(db)
    chased(db, iid)
    inbound(db)
    r = scan(db)[0]
    resolve(db, r["id"], "stop")
    with pytest.raises(ValueError):
        resolve(db, r["id"], "resume")


def test_the_home_summary_carries_open_replies(db, sent):
    iid = invoice(db)
    chased(db, iid)
    inbound(db)
    scan(db, says("paid"))
    from services import home_summary
    with db.connect() as c:
        s = home_summary.summary(c, A, UTC_NOW)
    assert [r["category"] for r in s["replies"]] == ["paid"]


# ------------------------------------------------------------ inbox read first ---

@pytest.mark.parametrize("ago,complete,status,ready", [
    (timedelta(minutes=20), True, "ok", True),
    (timedelta(hours=2, minutes=59), True, "ok", True),
    (timedelta(hours=3, minutes=1), True, "ok", False),
    (timedelta(minutes=20), False, "ok", False),
    (timedelta(minutes=20), True, "error", False),
])
def test_chasing_waits_until_the_inbox_has_been_read(db, sent, ago, complete, status, ready):
    with db.begin() as c:
        fresh(c, ACCT_A, ago=ago, complete=complete, status=status)
    iid = invoice(db)
    result = autopilot(db)
    if ready:
        assert result["sent"] == [iid]
    else:
        assert sent == [] and result["skipped"].get(iid) == "inbox_not_fresh"


def test_never_synced_is_not_fresh(db, sent):
    with db.begin() as c:
        c.execute(text("DELETE FROM email_sync_states WHERE email_account_id = :a"), {"a": ACCT_A})
    iid = invoice(db)
    assert autopilot(db)["skipped"].get(iid) == "inbox_not_fresh" and sent == []


@pytest.mark.parametrize("provider,listed,fetched,known,complete", [
    ("microsoft", 80, 80, 0, True),        # delta: complete by construction
    ("google", 12, 12, 0, True),           # fewer than a page: the whole inbox was seen
    ("google", 50, 50, 1, True),           # reached a message already stored
    ("google", 50, 50, 0, False),          # a full page of new mail: there may be more
    ("google", 12, 11, 0, False),          # a fetch failed
])
def test_a_sync_is_complete_only_when_nothing_can_have_been_missed(provider, listed, fetched,
                                                                   known, complete):
    ids = [f"m{i}" for i in range(listed)]
    got = ids[:fetched]
    already = set(ids[-known:]) if known else set()
    assert replies().sync_complete(provider, ids, got, already) is complete


# ------------------------------------------------------------ the right mailbox ---

def test_a_chase_goes_from_the_default_mailbox_not_the_newest(db, sent):
    with db.begin() as c:
        c.execute(text("INSERT INTO email_accounts (id, business_id, provider, email_address, "
                       "is_default, created_at) VALUES ('acct-new', :b, 'google', "
                       "'new@aaaa.example', 0, '2026-10-01')"), {"b": A})
    iid = invoice(db)
    assert autopilot(db)["sent"] == [iid]
    assert sent[0][1]["account_id"] == ACCT_A
    with db.connect() as c:
        assert c.execute(text("SELECT email_account_id FROM email_outbox")).scalar() == ACCT_A


def test_the_only_mailbox_is_the_default_even_unmarked(db, sent):
    with db.begin() as c:
        c.execute(text("UPDATE email_accounts SET is_default = 0 WHERE id = :a"), {"a": ACCT_A})
    with Session(db) as s:
        assert replies().default_mailbox(s, A) == ACCT_A


def test_several_mailboxes_and_no_default_stands_down(db, sent):
    with db.begin() as c:
        c.execute(text("UPDATE email_accounts SET is_default = 0 WHERE id = :a"), {"a": ACCT_A})
        c.execute(text("INSERT INTO email_accounts (id, business_id, provider, email_address, "
                       "is_default) VALUES ('acct-two', :b, 'google', 'two@aaaa.example', 0)"),
                  {"b": A})
        fresh(c, "acct-two")
    iid = invoice(db)
    result = autopilot(db)
    assert sent == [] and result["skipped"].get(iid) == "no_default_mailbox"


def test_a_manual_chase_card_carries_its_mailbox(db, sent):
    replies()
    iid = invoice(db)
    import services.aria_actions as aa
    with Session(db) as s:
        card = aa.propose(s, business(), "owner-uuid", "send_invoice_chase",
                          {"invoice_id": iid, "chase_stage": 1}, owner_name="Mike")
    assert card["proposal"]["preview"]["account_id"] == ACCT_A


def test_the_thread_of_a_sent_chase_is_kept_for_matching(db, sent):
    iid = invoice(db)
    autopilot(db)
    with db.connect() as c:
        result = json.loads(c.execute(text("SELECT result FROM aria_actions")).scalar())
    assert result["gmail_thread_id"] == "gt-out-1"
    inbound(db, thread="gt-out-1", hours_ago=0)
    assert scan(db)[0]["invoice_ids"] == [iid]


# ------------------------------------------------------------ the hourly order ---

def test_each_run_syncs_then_reads_replies_then_chases(monkeypatch):
    m = automations()
    order = []
    monkeypatch.setattr(m, "_sync_inbox", lambda session, bid: order.append("sync"), raising=False)
    monkeypatch.setattr(replies(), "scan", lambda *a, **k: order.append("scan") or [])
    monkeypatch.setattr(m, "run_invoice_autopilot", lambda *a, **k: order.append("chase") or {
        "sent": [], "cards": [], "skipped": {}})
    m.run_business(None, business(), on())
    assert order == ["sync", "scan", "chase"]


def test_a_failed_sync_still_reads_replies_but_does_not_chase(monkeypatch):
    m = automations()
    order = []

    def broken(session, bid):
        raise RuntimeError("Gmail down")
    monkeypatch.setattr(m, "_sync_inbox", broken, raising=False)
    monkeypatch.setattr(replies(), "scan", lambda *a, **k: order.append("scan") or [])
    monkeypatch.setattr(m, "run_invoice_autopilot", lambda *a, **k: order.append("chase") or {})
    m.run_business(None, business(), on())
    assert order == ["scan"]


# ---------------------------------------------------------------------------
# Added during implementation (not in the approved Stage 1 set): the owner's
# endpoints, and the cursor every sync now stores.

def test_the_owner_lists_and_resolves_replies_through_the_api(db, sent, monkeypatch):
    from test_auto_chase import client_for
    iid = invoice(db)
    chased(db, iid)
    inbound(db)
    scan(db, says("paid", "Says they paid"))
    client = client_for(db, monkeypatch, business())
    [r] = client.get("/v1/automations/replies").json()
    assert r["category"] == "paid" and r["invoice_ids"] == [iid]
    assert client.post(f"/v1/automations/replies/{r['id']}/resolve",
                       json={"decision": "mark_paid"}).status_code == 422
    done = client.post(f"/v1/automations/replies/{r['id']}/resolve", json={"decision": "stop"})
    assert done.status_code == 200 and done.json()["status"] == "stopped"
    assert client.post(f"/v1/automations/replies/{r['id']}/resolve",
                       json={"decision": "resume"}).status_code == 409
    assert client.get("/v1/automations/replies").json() == []


def test_the_api_never_shows_or_resolves_another_business_reply(db, sent, monkeypatch):
    from test_auto_chase import client_for
    iid = invoice(db)
    chased(db, iid)
    inbound(db)
    r = scan(db)[0]
    client = client_for(db, monkeypatch, business(B))
    assert client.get("/v1/automations/replies").json() == []
    assert client.post(f"/v1/automations/replies/{r['id']}/resolve",
                       json={"decision": "resume"}).status_code == 404
    assert open_now(db)[0]["status"] == "open"


def test_a_sync_records_whether_it_can_have_missed_anything(db):
    """completed_cursor: a listed message stored BEFORE the sync began is
    "known"; the provider's own cursor is kept, a stale flag is not."""
    started = TUE_10.astimezone(timezone.utc)
    with db.begin() as c:
        c.execute(text("ALTER TABLE email_messages ADD COLUMN created_at TEXT"))
        c.execute(text("INSERT INTO email_messages (id, business_id, email_account_id, "
                       "provider_message_id, created_at) VALUES ('old', :b, :a, 'm-old', :at)"),
                  {"b": A, "a": ACCT_A, "at": iso(TUE_10 - timedelta(days=1))})
    acct = SimpleNamespace(id=ACCT_A, provider="google")
    page = [f"m{i}" for i in range(49)] + ["m-old"]
    msgs = [SimpleNamespace(provider_message_id=m) for m in page]
    with Session(db) as s:
        done = replies().completed_cursor(
            s, acct, SimpleNamespace(messages=msgs, cursor={"complete": True, "x": 1},
                                     listed_ids=page), started)
        assert done == {"x": 1, "complete": True}
        new_only = [f"n{i}" for i in range(50)]
        stale = replies().completed_cursor(
            s, acct, SimpleNamespace(messages=[SimpleNamespace(provider_message_id=m)
                                               for m in new_only],
                                     cursor={"complete": True}, listed_ids=new_only), started)
        assert stale == {"complete": False}
