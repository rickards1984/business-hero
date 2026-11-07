"""BM-3 — Aria sees the business's own transactions in a board meeting.

Mike's meeting of 7 Nov 2026: Aria could see only P&L totals, not the
transactions Business Hero holds, so she could not separate Ashbourne
(membership) from GoCardless (student) income or model price rises.
Decisions: the brief carries the last 6 full months by default; 12 on
request, with a short advisory; when the records start later (a new
business), Aria says how many months there are. Figures come from the same
ledger as the accountancy pack (accountancy_pack._ledger), so they agree.

Tests first. SQLite with the columns the ledger reads.
"""
import json
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session

A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
TODAY = date(2026, 11, 7)          # window: 1 May – 31 Oct 2026
D = Decimal


@pytest.fixture
def db():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    with Session(engine) as s:
        s.execute(text("""CREATE TABLE accounting_categories (id TEXT PRIMARY KEY, business_id TEXT, name TEXT)"""))
        s.execute(text("""CREATE TABLE accounting_transactions (
            id TEXT PRIMARY KEY, business_id TEXT NOT NULL, transaction_date DATE NOT NULL,
            description TEXT NOT NULL, payee_payer TEXT, category_id TEXT, type TEXT NOT NULL,
            amount NUMERIC NOT NULL, reference TEXT, external_source TEXT, external_id TEXT,
            import_id TEXT, is_reconciled BOOLEAN DEFAULT 0, is_archived BOOLEAN DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP)"""))
        for cid, name in (("c-mem", "Membership income"), ("c-course", "Course income"),
                          ("c-rent", "Rent"), ("c-wages", "Wages")):
            s.execute(text("INSERT INTO accounting_categories VALUES (:i, :b, :n)"), {"i": cid, "b": A, "n": name})
        s.commit()
    yield engine
    engine.dispose()


_n = [0]


def tx(engine, day, kind, amount, payee="", desc="", ref="", cat=None, bid=A, archived=False):
    _n[0] += 1
    with Session(engine) as s:
        s.execute(text("""INSERT INTO accounting_transactions (id, business_id, transaction_date, description,
            payee_payer, category_id, type, amount, reference, external_source, external_id, is_archived)
            VALUES (:i, :b, :d, :desc, :p, :c, :t, :a, :r, 'xero', :x, :arch)"""),
                  {"i": f"t{_n[0]}", "b": bid, "d": day.isoformat(), "desc": desc or payee, "p": payee,
                   "c": cat, "t": kind, "a": str(amount), "r": ref, "x": f"x{_n[0]}", "arch": archived})
        s.commit()


def gym(engine):
    """Six months of New Body: Ashbourne memberships, GoCardless students,
    a couple of full course payments, rent and wages."""
    for month in range(5, 11):
        tx(engine, date(2026, month, 3), "income", 9800 + month * 10, "Ashbourne Management", cat="c-mem")
        tx(engine, date(2026, month, 8), "income", 2100, "GoCardless", cat="c-course")
        tx(engine, date(2026, month, 1), "expense", 3200, "Landlord Ltd", cat="c-rent")
        tx(engine, date(2026, month, 28), "expense", 2950, "Payroll", cat="c-wages")
    tx(engine, date(2026, 7, 14), "income", 1325, "J Smith", ref="J SMITH COURSE", cat="c-course")
    tx(engine, date(2026, 9, 2), "income", 1625, "", desc="Bank transfer", ref="A JONES", cat=None)
    # outside the window, archived, and another business: never counted
    tx(engine, date(2026, 4, 30), "income", 99999, "Ashbourne Management")
    tx(engine, date(2026, 11, 3), "income", 5000, "Ashbourne Management")   # this month so far
    tx(engine, date(2026, 6, 5), "income", 77777, "Ashbourne Management", archived=True)
    tx(engine, date(2026, 6, 5), "income", 55555, "Ashbourne Management", bid=B)


def summary(engine, months=6):
    from services import meeting_ledger
    with Session(engine) as s:
        return meeting_ledger.summary(s, A, TODAY, months=months)


def test_the_window_is_the_last_six_full_months(db):
    gym(db)
    out = summary(db)
    assert out["available"] is True
    assert (out["period_start"], out["period_end"]) == ("2026-05-01", "2026-10-31")
    assert [m["month"] for m in out["monthly_totals"]] == [f"2026-{m:02d}" for m in range(5, 11)]
    assert out["month_to_date"]["income"] == 5000 and out["month_to_date"]["through"] == "2026-11-07"


def test_income_is_split_by_payer_month_by_month(db):
    gym(db)
    payers = {p["payer"]: p for p in summary(db)["income_by_payer"]}
    assert payers["Ashbourne Management"]["by_month"]["2026-05"] == 9850
    assert payers["Ashbourne Management"]["count"] == 6
    assert payers["GoCardless"]["total"] == 6 * 2100
    assert "(no payer recorded)" in payers, "income without a payer is shown, never blended in"


def test_the_totals_agree_with_the_accountancy_pack(db):
    """The same ledger, so the same figures: no second version of the truth."""
    gym(db)
    from services import accountancy_pack as pack
    out = summary(db)
    with Session(db) as s:
        pnl = pack.ledger_pnl(pack._ledger(s, A, date(2026, 5, 1), date(2026, 10, 31)))
    assert D(str(out["total_income"])) == pnl["total_income"]
    assert D(str(out["total_expense"])) == pnl["total_expense"]
    assert sum(m["income"] for m in out["monthly_totals"]) == pytest.approx(float(pnl["total_income"]))
    assert sum(p["total"] for p in out["income_by_payer"]) == pytest.approx(float(pnl["total_income"]))


def test_archived_other_business_and_out_of_window_lines_never_count(db):
    gym(db)
    out = summary(db)
    blob = json.dumps(out)
    for amount in ("99999", "77777", "55555"):
        assert amount not in blob


def test_spending_is_split_by_supplier_and_category(db):
    gym(db)
    out = summary(db)
    suppliers = {p["payee"]: p for p in out["expense_by_supplier"]}
    assert suppliers["Landlord Ltd"]["total"] == 6 * 3200
    cats = {c["category"]: c for c in out["expense_by_category"]}
    assert cats["Wages"]["by_month"]["2026-10"] == 2950


def test_large_one_off_income_is_listed_with_its_reference(db):
    """Full course payments (£1,325 / £1,625) with the student's name as the
    reference can be picked out."""
    gym(db)
    large = summary(db)["large_one_off_income"]["lines"]
    refs = {(l["amount"], l["reference"]) for l in large}
    assert (1325, "J SMITH COURSE") in refs and (1625, "A JONES") in refs


def test_the_many_small_payers_are_grouped_without_losing_money(db):
    from services import meeting_ledger
    for i in range(meeting_ledger.TOP_PAYERS + 7):
        tx(db, date(2026, 8, 10), "income", 10 + i, f"Member {i}")
    out = summary(db)
    rows = out["income_by_payer"]
    assert len(rows) == meeting_ledger.TOP_PAYERS + 1
    assert rows[-1]["payer"].startswith("All other payers") and rows[-1]["payers"] == 7
    assert sum(r["total"] for r in rows) == pytest.approx(out["total_income"])


def test_a_new_business_is_told_how_many_months_there_are(db):
    tx(db, date(2026, 8, 12), "income", 500, "First client")
    out = summary(db)
    assert out["coverage"]["first_record"] == "2026-08-12"
    assert out["coverage"]["full_months"] == 2           # September, October
    assert "12 August 2026" in out["coverage"]["note"]


def test_no_records_is_said_plainly(db):
    out = summary(db)
    assert out["available"] is False and "no transactions" in out["reason"].lower()


@pytest.mark.parametrize("asked,used", [(12, 12), (24, 12), (0, 1), (3, 3)])
def test_months_are_kept_between_one_and_twelve(db, asked, used):
    gym(db)
    assert summary(db, months=asked)["months"] == used


def test_twelve_months_comes_with_an_advisory(db):
    gym(db)
    assert "advisory" not in summary(db, months=6)
    assert "allowance" in summary(db, months=12)["advisory"].lower()


# --------------------------------------------------------------- search ---

def search(engine, **kw):
    from services import meeting_ledger
    with Session(engine) as s:
        return meeting_ledger.search(s, A, TODAY, **kw)


def test_search_by_payer_words(db):
    gym(db)
    out = search(db, text="gocardless", date_from="2026-09-01", date_to="2026-09-30")
    assert out["matched"] == 1 and out["total_income"] == 2100
    assert out["transactions"][0]["payer"] == "GoCardless"


def test_search_by_exact_amount_finds_full_course_payments(db):
    gym(db)
    out = search(db, min_amount=1625, max_amount=1625, direction="income")
    assert [t["reference"] for t in out["transactions"]] == ["A JONES"]


def test_search_never_reaches_another_business_or_archived_lines(db):
    gym(db)
    out = search(db, text="ashbourne", date_from="2026-01-01", date_to="2026-12-31")
    assert all(t["amount"] not in (55555, 77777) for t in out["transactions"])


def test_search_returns_at_most_fifty_lines_but_counts_them_all(db):
    for i in range(70):
        tx(db, date(2026, 10, 1 + i % 28), "income", 20, "Member pay")
    out = search(db, text="member pay")
    assert out["matched"] == 70 and len(out["transactions"]) == 50 and out["truncated"] is True
    assert out["total_income"] == 1400


def test_search_is_limited_to_two_years(db):
    from services import meeting_ledger
    out = search(db, date_from="2019-01-01")
    assert out["date_from"] >= (TODAY.replace(year=TODAY.year - meeting_ledger.SEARCH_YEARS)).isoformat()


# ---------------------------------------------------------------- tools ---

def run(engine, name, args):
    from services import meeting_ledger
    with Session(engine) as s:
        return json.loads(meeting_ledger.run_tool(name, args, s, A, TODAY))


def test_the_tools_run_for_the_meeting_business_only(db):
    """The business is the meeting's, never something the model passes in."""
    gym(db)
    out = run(db, "search_transactions", {"text": "ashbourne", "business_id": B,
                                          "date_from": "2026-06-01", "date_to": "2026-06-30"})
    assert out["matched"] == 1 and out["transactions"][0]["amount"] != 55555


def test_an_unknown_tool_or_bad_arguments_is_an_answer_not_a_crash(db):
    assert "error" in run(db, "delete_everything", {})
    assert "error" in run(db, "search_transactions", {"min_amount": "lots"})


def test_ledger_summary_tool_honours_months(db):
    gym(db)
    out = run(db, "ledger_summary", {"months": 12})
    assert out["months"] == 12 and "advisory" in out


def test_tool_definitions_exist_for_chat_and_voice():
    from services import meeting_ledger
    chat = {t["function"]["name"] for t in meeting_ledger.CHAT_TOOLS}
    voice = {t["name"] for t in meeting_ledger.REALTIME_TOOLS}
    assert chat == voice == {"search_transactions", "ledger_summary"}


# ------------------------------------------------------- wired into Aria ---

def test_the_meeting_brief_carries_the_ledger(db, monkeypatch):
    gym(db)
    from services import executive_meeting_prep as prep
    with Session(db) as s:
        out = prep._ledger_loader("Europe/London")(A, None, s)
    assert out["available"] is True and out["months"] == 6


def test_aria_is_told_how_to_use_the_ledger():
    from services.executive_meeting_prompts import build_system_prompt
    prompt = build_system_prompt({"business": {"name": "New Body"}}, {})
    assert "search_transactions" in prompt and "twelve months" in prompt.lower()
    assert "never invent a figure" in prompt.lower()


class _Call:
    def __init__(self, cid, name, args):
        from types import SimpleNamespace
        self.id = cid
        self.function = SimpleNamespace(name=name, arguments=args)


def _reply(content=None, calls=None):
    from types import SimpleNamespace
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=calls),
                                                    finish_reason="stop")],
                           usage=SimpleNamespace(total_tokens=10))


@pytest.fixture
def chat(monkeypatch):
    import asyncio  # noqa: F401
    from types import SimpleNamespace
    from services import executive_meeting_orchestrator as orch
    from services import profit_guard
    state = {"sent": [], "script": []}

    async def create(**kwargs):
        state["sent"].append({**kwargs, "messages": list(kwargs["messages"])})
        return state["script"].pop(0)
    monkeypatch.setattr(orch, "_get_async_client",
                        lambda: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    monkeypatch.setattr(profit_guard, "permits", lambda purpose: True)
    return state


def test_aria_looks_up_transactions_then_answers(chat):
    import asyncio
    from services import executive_meeting_orchestrator as orch
    from services import meeting_ledger
    chat["script"] = [_reply(calls=[_Call("c1", "search_transactions", '{"text": "gocardless"}')]),
                      _reply(content="GoCardless brought in £12,600 over six months.")]
    looked = []

    async def run_tool(name, arguments):
        looked.append((name, arguments))
        return '{"matched": 6, "total_income": 12600}'
    content, tokens = asyncio.run(orch._gpt_chat_completion(
        messages=[{"role": "user", "content": "How much from GoCardless?"}], business_id=A,
        tools=meeting_ledger.CHAT_TOOLS, run_tool=run_tool))
    assert content.startswith("GoCardless brought in") and tokens == 20
    assert looked == [("search_transactions", '{"text": "gocardless"}')]
    second = chat["sent"][1]["messages"]
    assert second[-1] == {"role": "tool", "tool_call_id": "c1", "content": '{"matched": 6, "total_income": 12600}'}
    assert chat["sent"][0]["tools"] == meeting_ledger.CHAT_TOOLS


def test_look_ups_are_bounded_then_aria_must_answer(chat):
    import asyncio
    from services import executive_meeting_orchestrator as orch
    from services import meeting_ledger
    rounds = orch.MAX_TOOL_ROUNDS
    chat["script"] = [_reply(calls=[_Call(f"c{i}", "ledger_summary", "{}")]) for i in range(rounds)] + \
                     [_reply(content="Here is what I found.")]

    async def run_tool(name, arguments):
        return "{}"
    content, _ = asyncio.run(orch._gpt_chat_completion(
        messages=[{"role": "user", "content": "x"}], tools=meeting_ledger.CHAT_TOOLS, run_tool=run_tool))
    assert content == "Here is what I found." and len(chat["sent"]) == rounds + 1
    assert "tools" not in chat["sent"][-1], "the last call offers no tools, so it has to answer"


def test_a_typed_turn_offers_the_ledger_for_the_meeting_business(chat, monkeypatch):
    """handle_turn passes the meeting's own business to the look-ups."""
    import asyncio
    from services import executive_meeting_orchestrator as orch
    monkeypatch.setattr(orch, "_load_meeting", lambda mid, s: {"business_id": A, "status": "in_progress",
                                                               "prep_data": {"business": {"name": "NB"}},
                                                               "total_tokens_used": 0})
    monkeypatch.setattr(orch, "_load_settings", lambda bid, s: {"timezone": "Europe/London"})
    monkeypatch.setattr(orch, "_save_message", lambda **kw: None)
    monkeypatch.setattr(orch, "_load_message_history", lambda mid, s: [{"role": "owner", "content": "Hi"}])
    monkeypatch.setattr(orch, "_increment_total_tokens", lambda *a: None)
    seen = []
    monkeypatch.setattr(orch, "_ledger_tool_runner", lambda bid, tz: seen.append((bid, tz)) or (lambda n, a: None))
    chat["script"] = [_reply(content="Hello.")]
    session = type("S", (), {"commit": lambda self: None})()
    out = asyncio.run(orch.handle_turn("m1", "Hi", session))
    assert out["content"] == "Hello." and seen == [(A, "Europe/London")]
    assert chat["sent"][0]["tools"]


def test_search_by_direction_returns_only_that_side(db):
    gym(db)
    out = search(db, direction="expense", date_from="2026-10-01", date_to="2026-10-31")
    assert {t["direction"] for t in out["transactions"]} == {"expense"}
    assert out["total_income"] == 0 and out["total_expense"] == 3200 + 2950


def test_every_search_word_must_match(db):
    gym(db)
    assert search(db, text="ashbourne gocardless")["matched"] == 0
    assert search(db, text="ashbourne management", date_from="2026-10-01", date_to="2026-10-31")["matched"] == 1


# ---- Codex BM-3 review 1 ---------------------------------------------------

def test_regular_receipts_never_crowd_out_a_course_payment(db):
    """Finding 3: 60 weekly £600 payouts from one provider, and one earlier
    £1,625 full payment: the full payment is the one-off shown."""
    from datetime import timedelta
    for i in range(60):
        tx(db, date(2026, 5, 1) + timedelta(days=3 * i), "income", 600, "GoCardless Payouts")
    tx(db, date(2026, 5, 2), "income", 1625, "R Patel", ref="R PATEL FULL")
    one_off = summary(db)["large_one_off_income"]
    assert [l["reference"] for l in one_off["lines"]] == ["R PATEL FULL"]
    assert one_off["count"] == one_off["shown"] == 1


def test_a_large_result_is_trimmed_to_valid_json_with_totals_kept(db):
    """Finding 1: whatever its size, a result fits, stays valid JSON, keeps
    its totals, coverage and advisory, and says what was shortened."""
    from services import meeting_ledger
    gym(db)
    with Session(db) as s:
        full = meeting_ledger.summary(s, A, TODAY, months=12)
    big = json.loads(json.dumps(full))
    big["large_one_off_income"]["lines"] = [{"reference": "R" * 120, "amount": 900}] * 400
    out = meeting_ledger.fit(big, limit=6000)
    assert len(json.dumps(out)) <= 6000
    assert out["total_income"] == full["total_income"] and out["coverage"] == full["coverage"]
    assert out["advisory"] == full["advisory"] and out["large_one_off_income"]["count"] == full[
        "large_one_off_income"]["count"]
    assert out["trimmed"]["large_one_off_income.lines"] > 0 and "search_transactions" in out["trimmed_note"]


def test_every_tool_result_fits(db, monkeypatch):
    from services import meeting_ledger
    monkeypatch.setattr(meeting_ledger, "RESULT_CHARS", 4000)
    for i in range(300):
        tx(db, date(2026, 10, 1 + i % 28), "income", 20, f"Member {i}", desc="d" * 500, ref="r" * 90)
    assert len(_raw(db, "search_transactions", {"text": "member"})) <= 4000
    assert len(_raw(db, "ledger_summary", {"months": 12})) <= 4000


def _raw(engine, name, args):
    from services import meeting_ledger
    with Session(engine) as s:
        return meeting_ledger.run_tool(name, args, s, A, TODAY)


def test_descriptions_are_kept_short(db):
    from services import meeting_ledger
    tx(db, date(2026, 10, 2), "income", 50, "Member", desc="y" * 1000)
    line = search(db, text="member")["transactions"][0]
    assert len(line["description"]) <= meeting_ledger.DESCRIPTION_CHARS


def test_search_works_on_leap_day(db):
    """Finding 5: 29 February two years back does not exist."""
    from services import meeting_ledger
    with Session(db) as s:
        out = meeting_ledger.search(s, A, date(2028, 2, 29), text="anything")
    assert out["date_from"] == "2026-02-28"


def test_a_slow_look_up_is_an_answer_not_a_hang(chat, monkeypatch):
    """Finding 4: a stalled lookup gives Aria an error to work from."""
    import asyncio
    from services import executive_meeting_orchestrator as orch
    from services import meeting_ledger
    monkeypatch.setattr(orch, "TOOL_TIMEOUT_SECONDS", 0.2)
    chat["script"] = [_reply(calls=[_Call("c1", "search_transactions", "{}")]),
                      _reply(content="I couldn't check the detail just now.")]

    async def stalled(name, arguments):
        await asyncio.sleep(30)
    content, _ = asyncio.run(asyncio.wait_for(orch._gpt_chat_completion(
        messages=[{"role": "user", "content": "x"}], tools=meeting_ledger.CHAT_TOOLS, run_tool=stalled), 5))
    assert content.startswith("I couldn't")
    assert "too long" in chat["sent"][1]["messages"][-1]["content"]


def test_an_oversized_result_is_never_cut_mid_json(chat, monkeypatch):
    import asyncio
    from services import executive_meeting_orchestrator as orch
    from services import meeting_ledger
    chat["script"] = [_reply(calls=[_Call("c1", "ledger_summary", "{}")]), _reply(content="ok")]

    async def huge(name, arguments):
        return json.dumps({"lines": ["z" * 100] * 1000})
    asyncio.run(orch._gpt_chat_completion(messages=[{"role": "user", "content": "x"}],
                                          tools=meeting_ledger.CHAT_TOOLS, run_tool=huge))
    sent = chat["sent"][1]["messages"][-1]["content"]
    assert json.loads(sent)["error"]


def test_preparing_a_meeting_runs_off_the_event_loop(monkeypatch):
    """Finding 2."""
    import asyncio
    import contextlib
    import threading
    import db as dbmod
    import executive_meeting_api as api
    from services import executive_meeting_prep as prep
    threads = []

    @contextlib.contextmanager
    def ctx():
        yield object()
    monkeypatch.setattr(dbmod, "get_session_context", ctx)
    monkeypatch.setattr(prep, "generate_prep_data",
                        lambda **kw: threads.append(threading.current_thread()) or {"ok": True})

    async def main():
        loop_thread = threading.current_thread()
        out = await api.prep_off_loop(A)
        return out, loop_thread
    out, loop_thread = asyncio.run(main())
    assert out == {"ok": True} and threads and threads[0] is not loop_thread


# ---- Codex BM-3 review 2 ---------------------------------------------------

@pytest.mark.parametrize("limit", [24000, 6000, 1500])
def test_fit_always_fits_even_with_huge_fields(db, limit):
    """Finding 1: the note counts, and one huge field cannot break the limit."""
    from services import meeting_ledger
    result = {"matched": 50, "truncated": False, "total_income": 1.0,
              "transactions": [{"reference": "R" * 624, "description": "D" * 5000} for _ in range(50)]}
    out = meeting_ledger.fit(result, limit=limit)
    assert len(json.dumps(out)) <= limit and out["matched"] == 50 and out["total_income"] == 1.0


def test_what_is_shown_is_said_truthfully_after_trimming(db):
    """Finding 2: `shown` and `truncated` describe the lines actually kept."""
    from services import meeting_ledger
    search_result = {"matched": 50, "truncated": False, "total_income": 1.0,
                     "transactions": [{"reference": "r" * 150} for _ in range(50)]}
    out = meeting_ledger.fit(search_result, limit=4000)
    assert out["shown"] == len(out["transactions"]) < 50 and out["truncated"] is True
    summary_result = {"total_income": 1.0, "large_one_off_income": {"count": 40, "shown": 40,
                                                                    "lines": [{"reference": "x" * 150}] * 40}}
    out = meeting_ledger.fit(summary_result, limit=3000)
    one_off = out["large_one_off_income"]
    assert one_off["shown"] == len(one_off["lines"]) < 40 and one_off["count"] == 40


def test_a_long_field_outside_the_lists_is_clipped(db):
    from services import meeting_ledger
    out = meeting_ledger.fit({"total_income": 1.0, "coverage": {"note": "N" * 5000}}, limit=1500)
    assert len(json.dumps(out)) <= 1500 and out["total_income"] == 1.0


def test_a_list_can_shrink_to_nothing_when_one_line_is_too_big(db):
    from services import meeting_ledger
    line = {f"field{i}": "v" * 190 for i in range(20)}       # ~4,000 characters, each field already short
    out = meeting_ledger.fit({"matched": 1, "transactions": [line]}, limit=1500)
    assert len(json.dumps(out)) <= 1500 and out["transactions"] == [] and out["truncated"] is True


# ---- Codex BM-3 review 3 ---------------------------------------------------

def test_a_result_right_at_the_limit_still_fits_once_counts_are_added(db):
    from services import meeting_ledger
    base = {"matched": 3, "truncated": False, "transactions": [{"reference": "r"}] * 3}
    pad = 5000 - len(json.dumps(base)) - len(', "x": ""')
    base["x"] = "p" * pad
    assert len(json.dumps(base)) == 5000
    out = meeting_ledger.fit(base, limit=5000)
    assert len(json.dumps(out)) <= 5000 and out["shown"] == len(out["transactions"])


# ---- Codex BM-3 review 4 ---------------------------------------------------

@pytest.mark.parametrize("limit", [400, 100, 40, 2])
def test_fit_never_returns_json_over_the_limit_whatever_the_limit(db, limit):
    from services import meeting_ledger
    gym(db)
    with Session(db) as s:
        full = meeting_ledger.summary(s, A, TODAY, months=12)
    out = meeting_ledger.fit(json.loads(json.dumps(full)), limit=limit)
    assert len(json.dumps(out)) <= limit
    if limit >= 400:
        assert out["total_income"] == full["total_income"] and "narrow" in out["error"].lower()


def test_aria_is_given_no_one_business_s_examples():
    """BM-3b: the instructions are for every business, so they name no
    business's payers or prices."""
    from services import meeting_ledger
    from services.executive_meeting_prompts import build_system_prompt
    text = (build_system_prompt({"business": {"name": "Any"}}, {}) + json.dumps(meeting_ledger.CHAT_TOOLS)).lower()
    for word in ("gocardless", "ashbourne", "1,625", "1625", "smith", "gym", "student"):
        assert word not in text, word
