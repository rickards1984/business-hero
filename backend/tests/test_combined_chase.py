# ruff: noqa: F811 - pytest fixtures imported from test_auto_chase are parameters by design
"""AUTO-3 — one chase email per customer, listing all their overdue invoices.

docs/AUTO-3-TICKET.md. Mike's decision of 23 Oct 2026. RED (automatic
customer contact about money): tests first, approved by Mike before any code.

These reuse AUTO-1's harness (test_auto_chase.py): the same database, clock
(Tuesday 20 Oct 2026, 10:00 UK), send recorder and empty reply search. So
every AUTO-1 and AUTO-2 rule still applies around them.

Strict xfail may fail only because the combined template does not exist yet.
"""

import importlib
import json

import pytest
from sqlalchemy import text
from sqlmodel import Session

from test_auto_chase import (  # noqa: F401 - fixtures are used by name
    A, B, TUE_10, business, db, invoice, mailboxes_hold_no_replies, on, run, sent, stage_of)


class MissingCombined(AssertionError):
    """Only the intentional Stage 1 absence may be xfailed."""


# Stage 1's strict-xfail marker was removed once the implementation landed.


def combined():
    templates = importlib.import_module("email_templates")
    if not hasattr(templates, "get_combined_chase_email_template"):
        raise MissingCombined("email_templates.get_combined_chase_email_template does not exist yet")
    return templates.get_combined_chase_email_template


def number(db, iid):
    with db.connect() as c:
        return c.execute(text("SELECT invoice_number FROM invoices WHERE id = :i"), {"i": iid}).scalar()


def cards(db):
    with db.connect() as c:
        return [json.loads(r[0]) for r in c.execute(text(
            "SELECT payload FROM aria_actions WHERE status = 'proposed'"))]


def body_of(mail):
    return mail["subject"] + "\n" + mail["body"]


# ---------------------------------------------------------- one email each ---

def test_two_overdue_invoices_one_customer_one_email(db, sent):
    """Replaces AUTO-1's test_one_chase_per_customer_per_week (see the ticket)."""
    combined()
    a = invoice(db, days_overdue=30, email="pay@harper.example")
    b = invoice(db, days_overdue=20, email="PAY@harper.example")
    result = run(db, on())
    assert len(sent) == 1, "one email, not one per invoice"
    assert sorted(result["sent"]) == sorted([a, b])
    text_ = body_of(sent[0][1])
    assert number(db, a) in text_ and number(db, b) in text_
    assert stage_of(db, a) == 1 and stage_of(db, b) == 1


def test_every_overdue_invoice_is_listed_even_one_not_yet_due_a_chase(db, sent):
    """Decision A (recommended): all overdue invoices, even one a day late.
    An invoice not yet due is never listed."""
    combined()
    old = invoice(db, days_overdue=30)
    fresh = invoice(db, days_overdue=1)
    upcoming = invoice(db, days_overdue=-5)
    run(db, on())
    text_ = body_of(sent[0][1])
    assert number(db, old) in text_ and number(db, fresh) in text_
    assert number(db, upcoming) not in text_
    assert stage_of(db, fresh) == 1 and stage_of(db, upcoming) == 0


def test_nothing_is_sent_when_no_invoice_is_due_a_chase(db, sent):
    """Overdue invoices alone are not enough: one must be due under today's
    rules (7 days overdue for stage 1)."""
    combined()
    invoice(db, days_overdue=3)
    invoice(db, days_overdue=5)
    assert run(db, on())["sent"] == [] and sent == []


def test_invoices_are_listed_oldest_first(db, sent):
    combined()
    newer = invoice(db, days_overdue=10)
    older = invoice(db, days_overdue=40)
    run(db, on())
    text_ = sent[0][1]["body"]
    assert text_.index(number(db, older)) < text_.index(number(db, newer))


# ---------------------------------------------------------------- the stage ---

def test_the_email_is_at_the_most_overdue_invoices_next_stage(db, sent):
    from email_templates import get_chase_email_template
    combined()
    old = invoice(db, days_overdue=40, stage=2, last_chased_days_ago=8)
    new = invoice(db, days_overdue=10)
    run(db, on())
    stage3 = get_chase_email_template(3, {"customer_name": "Harper Builds", "invoice_number": "X",
                                          "amount": 1, "due_date": "d"}, "New Body Gym")
    first_words = stage3["subject"].split(":")[0]           # "URGENT"
    assert sent[0][1]["subject"].startswith(first_words)
    assert stage_of(db, old) == 3 and stage_of(db, new) == 1, "each invoice moves up one stage"


def test_stage_four_makes_one_card_listing_every_invoice_and_sends_nothing(db, sent):
    combined()
    old = invoice(db, days_overdue=60, stage=3, last_chased_days_ago=8)
    new = invoice(db, days_overdue=10)
    result = run(db, on())
    assert sent == [] and sorted(result["cards"]) == sorted([old, new])
    (card,) = cards(db)
    assert card["invoice_ids"] == [old, new] and card["chase_stage"] == 4
    assert stage_of(db, old) == 3 and stage_of(db, new) == 0, "nothing moves until the owner approves"


def test_an_owner_approving_the_stage_four_card_sends_one_email_and_advances_all(db, sent):
    import services.aria_actions as aa
    combined()
    old = invoice(db, days_overdue=60, stage=3, last_chased_days_ago=8)
    new = invoice(db, days_overdue=10)
    run(db, on())
    with db.connect() as c:
        aid, payload = c.execute(text("SELECT id, payload FROM aria_actions")).one()
    with Session(db) as s:
        aa.approve(s, business(), aid, "owner", aa.version_of(json.loads(payload)))
    assert len(sent) == 1
    assert stage_of(db, old) == 4 and stage_of(db, new) == 1


# -------------------------------------------------------------- the amounts ---

def test_amounts_are_what_is_still_owed_with_a_total(db, sent):
    combined()
    invoice(db, days_overdue=30, amount=500, paid=200)
    invoice(db, days_overdue=20, amount=120)
    run(db, on())
    text_ = sent[0][1]["body"]
    assert "300.00" in text_ and "120.00" in text_ and "420.00" in text_
    assert "500.00" not in text_, "never the full amount of a part-paid invoice"


def test_a_single_invoice_chase_shows_what_is_still_owed(db, sent):
    """Decision C (recommended): today's single chase quotes the full amount."""
    combined()
    invoice(db, days_overdue=30, amount=500, paid=200)
    run(db, on())
    text_ = sent[0][1]["body"]
    assert "300.00" in text_ and "500.00" not in text_


def test_a_single_overdue_invoice_keeps_todays_email(db, sent):
    from email_templates import get_chase_email_template
    combined()
    iid = invoice(db, days_overdue=10, amount=500)
    run(db, on())
    expected = get_chase_email_template(
        1, {"customer_name": "Harper Builds", "invoice_number": number(db, iid), "amount": 500,
            "due_date": (TUE_10.date().fromordinal(TUE_10.date().toordinal() - 10)).isoformat()},
        "New Body Gym")
    assert sent[0][1]["subject"] == expected["subject"]
    assert sent[0][1]["body"].startswith(expected["body"])


# ------------------------------------------------- what holds a customer back ---

def test_an_invoice_the_owner_stopped_is_left_out_and_the_rest_still_go(db, sent):
    combined()
    stopped = invoice(db, days_overdue=30)
    other = invoice(db, days_overdue=20)
    with db.begin() as c:
        c.execute(text("INSERT INTO chase_replies (id, business_id, email_message_id, customer_email, "
                       "invoice_ids, category, status) VALUES ('r1', :b, 'm1', 'pay@harper.example', "
                       ":ids, 'dispute', 'stopped')"), {"b": A, "ids": json.dumps([stopped])})
    result = run(db, on())
    assert result["sent"] == [other]
    text_ = body_of(sent[0][1])
    assert number(db, other) in text_ and number(db, stopped) not in text_
    assert stage_of(db, stopped) == 0


def test_an_open_card_for_one_invoice_holds_the_whole_customer(db, sent):
    """Decision B (recommended): never two emails about the same debt."""
    import services.aria_actions as aa
    combined()
    carded = invoice(db, days_overdue=30)
    other = invoice(db, days_overdue=20)
    with Session(db) as s:
        aa.propose(s, business(), "owner", "send_invoice_chase", {"invoice_id": carded}, owner_name="Mike")
    result = run(db, on())
    assert sent == [] and result["skipped"][other] == "card_waiting"


def test_the_daily_cap_counts_emails_not_invoices(db, sent):
    combined()
    for i in range(3):
        invoice(db, days_overdue=30, email=f"c{i}@example.com")
        invoice(db, days_overdue=20, email=f"c{i}@example.com")
    result = run(db, on(daily_cap=2))
    assert len(sent) == 2 and len(result["sent"]) == 4


def test_each_customer_gets_only_their_own_invoices(db, sent):
    combined()
    mine = invoice(db, days_overdue=30, email="one@example.com")
    theirs = invoice(db, days_overdue=30, email="two@example.com")
    other_business = invoice(db, bid=B, days_overdue=30, email="one@example.com")
    run(db, on())
    by_to = {m["to"]: body_of(m) for _, m in sent}
    assert set(by_to) == {"one@example.com", "two@example.com"}
    assert number(db, theirs) not in by_to["one@example.com"]
    assert number(db, mine) not in by_to["two@example.com"]
    assert stage_of(db, other_business) == 0


# --------------------------------------------------------- settled meanwhile ---

def test_one_invoice_settled_just_before_sending_sends_nothing(db, sent, monkeypatch):
    """Decision: the email must be exactly what was drafted; the next run
    drafts a fresh one."""
    import services.aria_actions as aa
    combined()
    a = invoice(db, days_overdue=30, amount=500)
    invoice(db, days_overdue=20, amount=100)
    real_propose = aa.propose

    def pay_then_propose(*args, **kwargs):
        out = real_propose(*args, **kwargs)
        with db.begin() as c:
            c.execute(text("UPDATE invoices SET paid_amount = 500 WHERE id = :i"), {"i": a})
        return out
    monkeypatch.setattr(aa, "propose", pay_then_propose)
    run(db, on())
    assert sent == []


def test_a_combined_card_with_a_settled_invoice_cannot_be_approved_by_hand(db, sent):
    import services.aria_actions as aa
    combined()
    a = invoice(db, days_overdue=30)
    b = invoice(db, days_overdue=20)
    with Session(db) as s:
        card = aa.propose(s, business(), "owner", "send_invoice_chase",
                          {"invoice_ids": [a, b], "chase_stage": 1}, owner_name="Mike")["proposal"]
    with db.begin() as c:
        c.execute(text("UPDATE invoices SET status = 'cancelled' WHERE id = :i"), {"i": b})
    with Session(db) as s, pytest.raises(aa.ActionRefused):
        aa.approve(s, business(), card["id"], "owner", card["version"])
    assert sent == [] and stage_of(db, a) == 0


# ------------------------------------------------------------- the card itself ---

def test_a_combined_card_may_only_hold_one_customers_invoices_of_this_business(db, sent):
    import services.aria_actions as aa
    combined()
    a = invoice(db, days_overdue=30, email="one@example.com")
    other_customer = invoice(db, days_overdue=30, email="two@example.com")
    other_business = invoice(db, bid=B, days_overdue=30, email="one@example.com")
    with Session(db) as s:
        for ids in ([a, other_customer], [a, other_business], []):
            out = aa.propose(s, business(), "owner", "send_invoice_chase",
                             {"invoice_ids": ids, "chase_stage": 1}, owner_name="Mike")
            assert "error" in out, ids
    assert cards(db) == []


def test_recorded_once_and_every_listed_invoice_advances(db, sent):
    combined()
    a = invoice(db, days_overdue=30)
    b = invoice(db, days_overdue=20)
    run(db, on())
    with db.connect() as c:
        rows = c.execute(text("SELECT invoice_id, chase_stage FROM email_outbox")).fetchall()
        chased = c.execute(text("SELECT COUNT(*) FROM invoices WHERE last_chased_at IS NOT NULL")).scalar()
    assert rows == [(a, 1)] and chased == 2
    assert stage_of(db, b) == 1


def test_running_twice_still_sends_once(db, sent):
    combined()
    invoice(db, days_overdue=30)
    invoice(db, days_overdue=20)
    run(db, on())
    run(db, on())
    assert len(sent) == 1


def test_aria_chat_chases_stay_one_invoice(db, sent):
    """Decision D (recommended): only the autopilot combines."""
    import services.aria_actions as aa
    combined()
    a = invoice(db, days_overdue=30)
    invoice(db, days_overdue=20)
    with Session(db) as s:
        card = aa.propose(s, business(), "owner", "send_invoice_chase", {"invoice_id": a},
                          owner_name="Mike")["proposal"]
    assert "invoices" not in card["preview"] and card["preview"]["invoice_id"] == a


# ---------------------------------------------------------------- the wording ---

@pytest.mark.parametrize("stage", [1, 2, 3, 4])
def test_the_combined_wording_lists_every_invoice_and_the_total(stage):
    template = combined()
    out = template(stage, "Harper Builds",
                   [{"invoice_number": "INV-1", "amount": 300, "due_date": "2026-09-20"},
                    {"invoice_number": "INV-2", "amount": 120.5, "due_date": "2026-10-10"}],
                   "New Body Gym")
    assert set(out) == {"subject", "body"}
    for piece in ("INV-1", "INV-2", "300.00", "120.50", "420.50", "2026-09-20", "2026-10-10",
                  "Harper Builds"):
        assert piece in out["body"], piece
    assert "\n" not in out["subject"] and "\r" not in out["subject"]


# ------------------------------------------- Aria's chat chase (Mike, 23 Oct) ---
# "If she's already chased that invoice in the last seven days, she advises
# it's already been chased: do you want to chase it again?"

def test_a_chat_chase_of_an_invoice_chased_this_week_asks_first(db, sent):
    import services.aria_actions as aa
    combined()
    iid = invoice(db, days_overdue=30, stage=1, last_chased_days_ago=3)
    with Session(db) as s:
        out = aa.propose(s, business(), "owner", "send_invoice_chase", {"invoice_id": iid},
                         owner_name="Mike")
    assert "proposal" not in out
    message = out["error"]
    assert "already" in message and number(db, iid) in message
    assert "17 October" in message, "says when"
    assert "chase_again" in message, "tells Aria how to go ahead if the owner says yes"
    assert cards(db) == []


def test_after_the_owner_says_yes_the_card_is_drafted(db, sent):
    import services.aria_actions as aa
    combined()
    iid = invoice(db, days_overdue=30, stage=1, last_chased_days_ago=3)
    with Session(db) as s:
        out = aa.propose(s, business(), "owner", "send_invoice_chase",
                         {"invoice_id": iid, "chase_again": True}, owner_name="Mike")
    assert "proposal" in out
    assert "chase_again" not in out["proposal"]["preview"]
    assert sent == [], "still only a card: the owner's tap sends it"


@pytest.mark.parametrize("ago", [None, 7, 30])
def test_an_invoice_not_chased_this_week_needs_no_question(db, sent, ago):
    import services.aria_actions as aa
    combined()
    iid = invoice(db, days_overdue=40, stage=1 if ago else 0, last_chased_days_ago=ago)
    with Session(db) as s:
        out = aa.propose(s, business(), "owner", "send_invoice_chase", {"invoice_id": iid},
                         owner_name="Mike")
    assert "proposal" in out


def test_aria_can_say_chase_again(db):
    combined()
    import assistant_tools
    (tool,) = [t for t in assistant_tools.TOOL_DEFINITIONS
               if t["function"]["name"] == "send_invoice_chase"]
    props = tool["function"]["parameters"]["properties"]
    assert props["chase_again"]["type"] == "boolean"
    assert "chase_again" not in tool["function"]["parameters"].get("required", [])


def test_the_home_shows_every_invoice_in_a_combined_chase(db, sent):
    from datetime import timezone
    from services import home_summary
    combined()
    a = invoice(db, days_overdue=30)
    b = invoice(db, days_overdue=20)
    run(db, on())
    with db.connect() as c:
        (entry,) = home_summary.recent_automated(c, A, TUE_10.astimezone(timezone.utc))
    assert entry["invoice_count"] == 2
    assert number(db, a) in entry["invoice_number"] and number(db, b) in entry["invoice_number"]
