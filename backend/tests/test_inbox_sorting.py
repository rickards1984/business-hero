"""ARIA-1a — Aria sorts the inbox (docs/ARIA-PROACTIVE-TICKETS.md, ARIA-1 §1–2).

Categories in Mike's words; free filters before any AI, so newsletters cost
nothing and money emails are never filtered away; one sorting pass shared by
the background and "Sort now"; and the counts that read the categories (the
dashboard, the WhatsApp briefing, the automation trigger) count them right.
"""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlmodel import Session

BIZ = "11111111-1111-4111-8111-111111111111"
ACCOUNT = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    with engine.begin() as c:
        c.execute(text("""CREATE TABLE email_messages (id TEXT PRIMARY KEY, business_id TEXT, email_account_id TEXT,
            provider_message_id TEXT, provider_thread_id TEXT, from_email TEXT, from_name TEXT, subject TEXT,
            snippet TEXT, received_at TIMESTAMP, labels TEXT DEFAULT '[]', raw_headers TEXT DEFAULT '{}',
            is_unread BOOLEAN DEFAULT 1, ai_category TEXT, ai_priority INT, ai_summary TEXT,
            ai_suggested_action TEXT, ai_analyzed_at TIMESTAMP)"""))
        c.execute(text("CREATE TABLE email_accounts (id TEXT, business_id TEXT, email_address TEXT)"))
        c.execute(text("CREATE TABLE outreach_messages (business_id TEXT, provider_thread_id TEXT)"))
        c.execute(text("INSERT INTO email_accounts VALUES (:a, :b, 'mike@newbody.example')"), {"a": ACCOUNT, "b": BIZ})
    return engine


_n = [0]


def mail(engine, **kw):
    _n[0] += 1
    row = dict(id=f"m{_n[0]}", business_id=BIZ, email_account_id=ACCOUNT, provider_message_id=f"p{_n[0]}",
               provider_thread_id=f"t{_n[0]}", from_email="sam@customer.example", from_name="Sam",
               subject="Hello", snippet="Hi there", received_at=datetime.now(timezone.utc) - timedelta(hours=1),
               labels=[], raw_headers={}, is_unread=True, ai_category=None, ai_priority=None, ai_analyzed_at=None)
    row.update(kw)
    row["labels"] = json.dumps(row["labels"])
    row["raw_headers"] = json.dumps(row["raw_headers"])
    with engine.begin() as c:
        c.execute(text("""INSERT INTO email_messages (id, business_id, email_account_id, provider_message_id,
            provider_thread_id, from_email, from_name, subject, snippet, received_at, labels, raw_headers, is_unread,
            ai_category, ai_priority, ai_analyzed_at) VALUES (:id, :business_id, :email_account_id,
            :provider_message_id, :provider_thread_id, :from_email, :from_name, :subject, :snippet, :received_at,
            :labels, :raw_headers, :is_unread, :ai_category, :ai_priority, :ai_analyzed_at)"""), row)
    return row["id"]


def stored(engine, mid):
    with engine.connect() as c:
        r = c.execute(text("SELECT ai_category, ai_priority, ai_summary, ai_analyzed_at FROM email_messages "
                           "WHERE id = :i"), {"i": mid}).first()
    return SimpleNamespace(category=r[0], priority=r[1], summary=r[2], analysed=r[3] is not None)


@pytest.fixture
def ai(monkeypatch):
    """The model's answers, by message id; every batch it was asked about."""
    from app.email import service
    state = SimpleNamespace(answers={}, batches=[], fail=False)

    def analyse(batch):
        state.batches.append([m.id for m in batch])
        if state.fail:
            return []
        from schemas import EmailAnalysis
        out = []
        for m in batch:
            cat, prio = state.answers.get(m.id, ("fyi", 2))
            out.append(EmailAnalysis(message_id=m.id, category=cat, priority=prio, summary=f"about {m.subject}",
                                     suggested_action=None))
        return out
    monkeypatch.setattr(service, "analyze_email_batch", analyse)
    return state


def sort(engine, **kw):
    from services import inbox_sorting
    with Session(engine) as s:
        return inbox_sorting.sort_pending(s, BIZ, **kw)


# ----------------------------------------------------------- categories ---

def test_the_categories_are_mike_s():
    from services import inbox_sorting as i
    assert list(i.CATEGORIES) == ["money", "new_enquiry", "customer", "complaint", "supplier", "scheduling",
                                  "fyi", "junk"]
    assert i.CATEGORIES["new_enquiry"] == "New enquiry"


@pytest.mark.parametrize("raw,new", [
    ("money", "money"), ("New enquiry", "new_enquiry"), ("new-enquiry", "new_enquiry"), ("COMPLAINT", "complaint"),
    ("action_required", "customer"), ("awaiting_reply", "customer"), ("finance", "money"),
    ("marketing", "junk"), ("spam", "junk"), ("fyi", "fyi"), ("scheduling", "scheduling"),
    ("Action Required", "customer"), (None, "fyi"), ("", "fyi"), ("something new", "fyi"),
])
def test_every_value_old_or_new_reads_as_one_of_mike_s(raw, new):
    from services import inbox_sorting
    assert inbox_sorting.normalise(raw) == new


@pytest.mark.parametrize("category,priority,important", [
    ("money", 1, True), ("new_enquiry", 2, True), ("customer", 3, True), ("complaint", 2, True),
    ("supplier", 3, False), ("supplier", 4, True), ("fyi", 5, True), ("junk", 1, False), ("scheduling", 3, False),
    ("action_required", 3, True), ("finance", 2, True), (None, None, False),
])
def test_what_counts_as_important(category, priority, important):
    from services import inbox_sorting
    assert inbox_sorting.is_important(category, priority) is important


def test_the_important_sql_agrees_with_is_important(db):
    from services import inbox_sorting
    cases = [("money", 1), ("supplier", 4), ("supplier", 3), ("junk", 1), ("action_required", 2), ("finance", 1),
             ("marketing", 5), (None, None)]
    ids = {mail(db, ai_category=c, ai_priority=p): (c, p) for c, p in cases}
    with db.connect() as c:
        found = {r[0] for r in c.execute(text(f"SELECT id FROM email_messages WHERE {inbox_sorting.IMPORTANT_SQL}"))}
    assert found == {i for i, (c_, p) in ids.items() if inbox_sorting.is_important(c_, p)}


# -------------------------------------------------------- free filters ---

@pytest.mark.parametrize("kw,category,why", [
    (dict(raw_headers={"List-Unsubscribe": "<mailto:u@x>"}, subject="Our autumn news"), "fyi", "mailing list"),
    (dict(raw_headers={"list-id": "<news.x>"}), "fyi", "mailing list"),
    (dict(raw_headers={"Precedence": "bulk"}), "fyi", "mailing list"),
    (dict(labels=["INBOX", "CATEGORY_PROMOTIONS"], subject="50% off"), "junk", "promotion"),
    (dict(labels=["SPAM"]), "junk", "spam"),
    (dict(labels=["INBOX", "CATEGORY_SOCIAL"]), "fyi", "social"),
    (dict(from_email="no-reply@service.example", subject="Your weekly digest"), "fyi", "automated"),
    (dict(raw_headers={"Auto-Submitted": "auto-replied"}, subject="Out of office"), "fyi", "automated"),
    (dict(from_email="Mike@NewBody.example"), "fyi", "your own"),
])
def test_free_filters_sort_without_any_ai(db, ai, kw, category, why):
    mid = mail(db, **kw)
    out = sort(db)
    got = stored(db, mid)
    assert ai.batches == [] and out["skipped"] == 1 and out["sorted"] == 0
    assert got.category == category and got.priority == 1 and got.analysed and why in got.summary.lower()


@pytest.mark.parametrize("kw", [
    dict(from_email="no-reply@xero.example", subject="Invoice INV-0042 from Harbour Lettings"),
    dict(from_email="notifications@bank.example", subject="Payment received: £750.00"),
    dict(raw_headers={"List-Unsubscribe": "<mailto:u@x>"}, subject="Your remittance advice"),
    dict(labels=["INBOX", "CATEGORY_UPDATES"], subject="Your statement is ready"),
    dict(from_email="noreply@stripe.example", subject="Payout of £1,250 is on its way"),
])
def test_money_emails_are_never_filtered_away(db, ai, kw):
    """A bank notice or an invoice often comes from a no-reply sender with a
    list header: it goes to the AI, which sorts it as Money."""
    mid = mail(db, **kw)
    ai.answers[mid] = ("money", 4)
    sort(db)
    assert ai.batches == [[mid]] and stored(db, mid).category == "money"


def test_promotions_stay_junk_even_with_a_money_word(db, ai):
    mid = mail(db, labels=["INBOX", "CATEGORY_PROMOTIONS"], subject="Save on payment terminals")
    sort(db)
    assert ai.batches == [] and stored(db, mid).category == "junk"


def test_a_reply_to_outreach_is_left_to_the_outreach_scanner(db, ai):
    mid = mail(db, provider_thread_id="th-out")
    with db.begin() as c:
        c.execute(text("INSERT INTO outreach_messages VALUES (:b, 'th-out')"), {"b": BIZ})
    sort(db)
    got = stored(db, mid)
    assert ai.batches == [] and "outreach" in got.summary.lower() and got.analysed


def test_another_business_s_outreach_thread_is_not_ours(db, ai):
    mid = mail(db, provider_thread_id="th-x")
    with db.begin() as c:
        c.execute(text("INSERT INTO outreach_messages VALUES ('other-biz', 'th-x')"))
    sort(db)
    assert ai.batches == [[mid]]


# --------------------------------------------------------- the AI pass ---

def test_ordinary_mail_is_sorted_by_the_ai_in_batches(db, ai):
    ids = [mail(db, subject=f"Question {i}") for i in range(12)]
    for i in ids:
        ai.answers[i] = ("customer", 3)
    out = sort(db, batch_size=5)
    assert [len(b) for b in ai.batches] == [5, 5, 2] and out == {"sorted": 12, "skipped": 0, "waiting": 0,
                                                                  "failed": False}
    assert all(stored(db, i).category == "customer" for i in ids)


def test_the_ai_s_answer_is_read_in_mike_s_categories(db, ai):
    mid = mail(db)
    ai.answers[mid] = ("action_required", 9)
    sort(db)
    got = stored(db, mid)
    assert got.category == "customer" and got.priority == 5


def test_a_failed_batch_stamps_nothing_and_says_so(db, ai):
    mid = mail(db)
    ai.fail = True
    out = sort(db)
    assert out["failed"] is True and out["sorted"] == 0 and out["waiting"] == 1
    assert stored(db, mid).analysed is False                   # tried again next pass


def test_already_sorted_mail_is_left_alone(db, ai):
    mail(db, ai_category="money", ai_priority=4, ai_analyzed_at=datetime.now(timezone.utc))
    assert sort(db) == {"sorted": 0, "skipped": 0, "waiting": 0, "failed": False} and ai.batches == []


def test_only_this_business_s_mail_is_sorted(db, ai):
    mail(db, business_id="other-biz")
    assert sort(db)["sorted"] == 0 and ai.batches == []


def test_the_newest_mail_is_sorted_first_within_the_limit(db, ai):
    old = mail(db, received_at=datetime.now(timezone.utc) - timedelta(days=3))
    new = mail(db, received_at=datetime.now(timezone.utc) - timedelta(minutes=5))
    out = sort(db, limit=1)
    assert ai.batches == [[new]] and out["waiting"] == 1 and stored(db, old).analysed is False


def test_sorting_is_costed_to_the_business_as_inbox_classify(db, monkeypatch):
    from app.email import service
    from services import profit_guard
    seen = []

    def analyse(batch):
        seen.append(profit_guard._attribution.get())
        return []
    monkeypatch.setattr(service, "analyze_email_batch", analyse)
    mail(db)
    sort(db)
    assert seen == [(BIZ, "classify")]


# ------------------------------------------------- the categorise prompt ---

def test_the_prompt_asks_for_mike_s_categories():
    from app.email import service
    prompt = service.CATEGORIZE_SYSTEM_PROMPT
    for key in ("money", "new_enquiry", "customer", "complaint", "supplier", "scheduling", "fyi", "junk"):
        assert f"- {key}:" in prompt
    assert "action_required" not in prompt and "awaiting_reply" not in prompt


def test_the_batch_reader_keeps_only_this_batch_s_messages_and_mike_s_categories(monkeypatch):
    from app.email import service
    from services import ai_text
    monkeypatch.setattr(service.ai_chat, "available", lambda task: True)
    monkeypatch.setattr(ai_text, "complete", lambda *a, **k: SimpleNamespace(content=json.dumps([
        {"message_id": "m1", "category": "finance", "priority": 7, "summary": "Paid", "suggested_action": None},
        {"message_id": "not-in-batch", "category": "money", "priority": 3, "summary": "x"},
        {"message_id": "m2", "category": "weird", "priority": "high", "summary": "y"},
    ])))
    batch = [SimpleNamespace(id="m1", from_email="a", from_name="A", subject="s", snippet="", received_at=None),
             SimpleNamespace(id="m2", from_email="b", from_name="B", subject="s", snippet="", received_at=None)]
    out = {r.message_id: (r.category, r.priority) for r in service.analyze_email_batch(batch)}
    assert out == {"m1": ("money", 5), "m2": ("fyi", 2)}


# --------------------------------------------------- the counts that read ---

def test_the_dashboard_counts_important_mail(db):
    from services import home_summary
    now = datetime.now(timezone.utc)
    for cat, prio in [("money", 3), ("new_enquiry", 2), ("action_required", 3), ("junk", 1), ("supplier", 4),
                      ("fyi", 1)]:
        mail(db, ai_category=cat, ai_priority=prio, ai_analyzed_at=now)
    mail(db, ai_category="money", ai_priority=4, received_at=now - timedelta(days=40))       # outside the window
    with db.connect() as c:
        assert home_summary.emails_needing_action(c, BIZ, now - timedelta(days=7)) == 4
    from pathlib import Path
    source = Path(home_summary.__file__).read_text()
    assert "action_required = emails_needing_action(conn, bid, since)" in source


def test_the_whatsapp_briefing_counts_with_the_same_rule():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "services/briefing_data.py").read_text()
    assert "'Action Required'" not in source and '"Action Required"' not in source
    assert "inbox_sorting.is_important" in source


def test_the_automation_trigger_uses_the_same_rule():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "services/automation_engine.py").read_text()
    assert "'Action Required'" not in source and "inbox_sorting.IMPORTANT_SQL" in source


def test_an_answer_about_mail_outside_the_batch_is_ignored(db, monkeypatch):
    """The model names an email it wasn't given: that email stays unsorted
    (it was never looked at), and isn't counted."""
    from app.email import service
    from schemas import EmailAnalysis
    new = mail(db, received_at=datetime.now(timezone.utc) - timedelta(minutes=5))
    old = mail(db, received_at=datetime.now(timezone.utc) - timedelta(days=2))
    monkeypatch.setattr(service, "analyze_email_batch", lambda batch: [
        EmailAnalysis(message_id=m, category="money", priority=4, summary="x", suggested_action=None) for m in (new, old)])
    out = sort(db, limit=1)
    assert out["sorted"] == 1 and stored(db, new).category == "money" and stored(db, old).analysed is False


def test_with_no_key_mail_is_left_unsorted_not_marked_fyi(monkeypatch, caplog):
    """It used to stamp every email "fyi", freezing it there."""
    from app.email import service
    monkeypatch.setattr(service.ai_chat, "available", lambda task: False)
    batch = [SimpleNamespace(id="m1", from_email="a", from_name="A", subject="Invoice", snippet="", received_at=None)]
    assert service.analyze_email_batch(batch) == [] and "no key" in caplog.text
