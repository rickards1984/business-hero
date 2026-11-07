"""BM-4 — Aria remembers what the owner explains (docs/BM-4-TICKET.md).

Proposed by Aria, confirmed by the owner, used in every meeting and in
ordinary Aria chat and voice; groups shape the meeting ledger. Stored in
business_settings.settings["aria_memory"], so no migration. Tests first.
"""
import json
from datetime import date

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session

A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
TODAY = date(2026, 11, 7)
OWNER = "11111111-1111-4111-8111-111111111111"
STAFF = "22222222-2222-4222-8222-222222222222"


@pytest.fixture(autouse=True)
def own_sessions(db, monkeypatch):
    """Code that opens its own short session reads the same test database."""
    import contextlib
    import db as dbmod

    @contextlib.contextmanager
    def ctx():
        with Session(db) as s:
            yield s
    monkeypatch.setattr(dbmod, "get_session_context", ctx)


@pytest.fixture
def db():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    with Session(engine) as s:
        s.execute(text("""CREATE TABLE business_settings (id TEXT PRIMARY KEY, business_id TEXT,
            settings TEXT, created_at TEXT, updated_at TEXT)"""))
        s.execute(text("CREATE TABLE accounting_categories (id TEXT PRIMARY KEY, business_id TEXT, name TEXT)"))
        s.execute(text("""CREATE TABLE accounting_transactions (
            id TEXT PRIMARY KEY, business_id TEXT NOT NULL, transaction_date DATE NOT NULL,
            description TEXT NOT NULL, payee_payer TEXT, category_id TEXT, type TEXT NOT NULL,
            amount NUMERIC NOT NULL, reference TEXT, external_source TEXT, external_id TEXT,
            import_id TEXT, is_reconciled BOOLEAN DEFAULT 0, is_archived BOOLEAN DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP)"""))
        s.execute(text("""CREATE TABLE business_members (business_id TEXT, user_id TEXT, role TEXT,
            is_active BOOLEAN)"""))
        for uid, role in ((OWNER, "owner"), (STAFF, "staff")):
            s.execute(text("INSERT INTO business_members VALUES (:b, :u, :r, 1)"), {"b": A, "u": uid, "r": role})
        s.execute(text("INSERT INTO business_settings VALUES ('s1', :b, :doc, '2026-01-01', '2026-01-01')"),
                  {"b": A, "doc": json.dumps({"automations": {"x": 1}, "other": "kept"})})
        s.commit()
    yield engine
    engine.dispose()


def mem():
    from services import aria_memory
    return aria_memory


def doc(engine, bid=A):
    with Session(engine) as s:
        row = s.execute(text("SELECT settings FROM business_settings WHERE business_id = :b"), {"b": bid}).fetchone()
    return json.loads(row[0]) if row else None


def propose(engine, about="GoCardless", meaning="Student course income", group="Student courses", bid=A):
    with Session(engine) as s:
        return mem().propose(s, bid, about=about, meaning=meaning, group=group, source="meeting")


def confirm(engine, entry_id, bid=A):
    with Session(engine) as s:
        return mem().confirm(s, bid, entry_id)


def confirmed(engine, bid=A):
    with Session(engine) as s:
        return mem().confirmed(s, bid)


# ------------------------------------------------------------- the store ---

def test_a_proposal_is_not_used_until_the_owner_confirms_it(db):
    entry = propose(db)
    assert entry["status"] == "proposed" and confirmed(db) == []
    assert confirm(db, entry["id"])["status"] == "confirmed"
    assert [e["about"] for e in confirmed(db)] == ["GoCardless"]


def test_the_rest_of_the_settings_document_is_untouched(db):
    propose(db)
    d = doc(db)
    assert d["automations"] == {"x": 1} and d["other"] == "kept" and d["aria_memory"]["entries"]


def test_the_owner_can_add_edit_and_delete(db):
    with Session(db) as s:
        e = mem().add(s, A, about="TPS", meaning="Parts supplier", group="Parts")
    assert e["status"] == "confirmed"
    with Session(db) as s:
        assert mem().update(s, A, e["id"], meaning="Main parts supplier")["meaning"] == "Main parts supplier"
    with Session(db) as s:
        assert mem().delete(s, A, e["id"]) is True
    assert confirmed(db) == []


def test_unknown_ids_change_nothing(db):
    with Session(db) as s:
        assert mem().confirm(s, A, "nope") is None and mem().delete(s, A, "nope") is False
        assert mem().update(s, A, "nope", meaning="x") is None


def test_memories_are_per_business(db):
    entry = propose(db)
    confirm(db, entry["id"])
    assert confirmed(db, B) == []
    with Session(db) as s:
        assert mem().confirm(s, B, entry["id"]) is None, "another business cannot confirm it"


def test_a_repeated_proposal_is_not_duplicated(db):
    first = propose(db)
    again = propose(db, about="gocardless ", meaning="student course income")
    assert again["id"] == first["id"]
    with Session(db) as s:
        assert len(mem().list_entries(s, A)["entries"]) == 1


@pytest.mark.parametrize("field,limit", [("about", 80), ("meaning", 300), ("group", 60)])
def test_long_text_is_kept_within_its_limit(db, field, limit):
    kwargs = {"about": "a", "meaning": "m", "group": "g", field: "x" * (limit + 50)}
    entry = propose(db, **kwargs)
    assert len(entry[field]) <= limit


def test_an_empty_about_or_meaning_is_refused(db):
    with Session(db) as s:
        with pytest.raises(ValueError):
            mem().propose(s, A, about="  ", meaning="x", group=None, source="meeting")
        with pytest.raises(ValueError):
            mem().propose(s, A, about="x", meaning="", group=None, source="meeting")


def test_there_is_a_limit_on_how_much_is_remembered(db, monkeypatch):
    monkeypatch.setattr(mem(), "MAX_PROPOSED", 2)
    propose(db, about="one")
    propose(db, about="two")
    with Session(db) as s:
        with pytest.raises(ValueError):
            mem().propose(s, A, about="three", meaning="m", group=None, source="meeting")


def test_the_one_off_threshold_can_be_set(db):
    with Session(db) as s:
        mem().set_one_off_from(s, A, 2000)
        assert mem().list_entries(s, A)["one_off_from"] == 2000
        mem().set_one_off_from(s, A, None)
        assert mem().list_entries(s, A)["one_off_from"] is None
    with Session(db) as s:
        with pytest.raises(ValueError):
            mem().set_one_off_from(s, A, -5)


def test_the_generic_settings_save_never_erases_it():
    import main
    existing = {"aria_memory": {"entries": [{"id": "1"}]}, "theme": "dark"}
    out = main.preserve_automations({"theme": "light"}, existing)
    assert out["aria_memory"] == existing["aria_memory"] and out["theme"] == "light"
    out = main.preserve_automations({"aria_memory": {"entries": []}}, existing)
    assert out["aria_memory"] == existing["aria_memory"], "a client cannot overwrite it either"


# ----------------------------------------------------------- the prompt ---

def test_the_prompt_block_holds_only_confirmed_notes_and_says_whose(db):
    e = propose(db)
    propose(db, about="Ashbourne", meaning="Gym memberships", group="Memberships")
    confirm(db, e["id"])
    with Session(db) as s:
        everything = mem().list_entries(s, A)["entries"]          # proposed ones included on purpose
    block = mem().prompt_block(everything)
    assert "GoCardless" in block and "Student course income" in block and "Ashbourne" not in block
    assert "owner" in block.lower()
    assert mem().prompt_block([]) == ""


# ------------------------------------------------------------ the ledger ---

_n = [0]


def tx(engine, day, kind, amount, payee="", ref="", bid=A):
    _n[0] += 1
    with Session(engine) as s:
        s.execute(text("""INSERT INTO accounting_transactions (id, business_id, transaction_date, description,
            payee_payer, type, amount, reference, external_source, external_id)
            VALUES (:i, :b, :d, :p, :p, :t, :a, :r, 'xero', :x)"""),
                  {"i": f"t{_n[0]}", "b": bid, "d": day.isoformat(), "p": payee, "t": kind,
                   "a": str(amount), "r": ref, "x": f"x{_n[0]}"})
        s.commit()


def test_the_ledger_shows_income_by_the_owner_s_groups(db):
    for m in range(5, 11):
        tx(db, date(2026, m, 3), "income", 9800, "Ashbourne Management")
        tx(db, date(2026, m, 8), "income", 2100, "GoCardless")
    tx(db, date(2026, 7, 9), "income", 300, "Cash sales")
    for about, meaning, group in (("gocardless", "Students", "Student courses"),
                                  ("ashbourne", "Memberships", "Memberships")):
        confirm(db, propose(db, about=about, meaning=meaning, group=group)["id"])
    from services import meeting_ledger
    with Session(db) as s:
        out = meeting_ledger.summary(s, A, TODAY, memory=mem().confirmed(s, A))
    groups = {g["group"]: g for g in out["income_by_group"]}
    assert groups["Student courses"]["total"] == 6 * 2100
    assert groups["Memberships"]["by_month"]["2026-10"] == 9800
    assert groups["Not grouped"]["total"] == 300
    assert sum(g["total"] for g in out["income_by_group"]) == pytest.approx(out["total_income"])


def test_no_groups_means_no_group_section(db):
    tx(db, date(2026, 8, 3), "income", 100, "Someone")
    from services import meeting_ledger
    with Session(db) as s:
        assert "income_by_group" not in meeting_ledger.summary(s, A, TODAY, memory=[])


def test_the_owner_s_one_off_threshold_is_used(db):
    tx(db, date(2026, 8, 3), "income", 1200, "One client")
    tx(db, date(2026, 8, 4), "income", 4000, "Big client")
    from services import meeting_ledger
    with Session(db) as s:
        default = meeting_ledger.summary(s, A, TODAY)
        raised = meeting_ledger.summary(s, A, TODAY, one_off_from=2000)
    assert default["large_one_off_income"]["count"] == 2
    assert [ln["amount"] for ln in raised["large_one_off_income"]["lines"]] == [4000]
    assert "2000" in raised["large_one_off_income"]["rule"] or "2,000" in raised["large_one_off_income"]["rule"]


# ------------------------------------------------------------- the tools ---

def run(engine, name, args, bid=A):
    from services import meeting_ledger
    with Session(engine) as s:
        return json.loads(meeting_ledger.run_tool(name, args, s, bid, TODAY))


def test_aria_proposes_through_the_remember_tool(db):
    out = run(db, "remember", {"about": "GoCardless", "meaning": "Student income", "group": "Students"})
    assert out["status"] == "proposed" and "confirm" in out["message"].lower()
    assert confirmed(db) == [] and len(doc(db)["aria_memory"]["entries"]) == 1


def test_the_remember_tool_cannot_confirm_or_reach_another_business(db):
    run(db, "remember", {"about": "X", "meaning": "Y", "status": "confirmed", "business_id": B})
    with Session(db) as s:
        entries = mem().list_entries(s, A)["entries"]
    assert [e["status"] for e in entries] == ["proposed"]
    assert doc(db, B) is None


def test_ledger_summary_uses_memory_groups_and_threshold(db):
    tx(db, date(2026, 8, 8), "income", 2100, "GoCardless")
    tx(db, date(2026, 8, 9), "income", 900, "Walk-in")
    confirm(db, propose(db)["id"])
    with Session(db) as s:
        mem().set_one_off_from(s, A, 800)
    out = run(db, "ledger_summary", {})
    assert {g["group"] for g in out["income_by_group"]} == {"Student courses", "Not grouped"}
    assert [ln["amount"] for ln in out["large_one_off_income"]["lines"]] == [900, 2100]   # the owner's £800
    out = run(db, "ledger_summary", {"one_off_from": 2000})
    assert [ln["amount"] for ln in out["large_one_off_income"]["lines"]] == [2100]


def test_the_tools_include_remember_for_chat_and_voice():
    from services import meeting_ledger
    chat = {t["function"]["name"] for t in meeting_ledger.CHAT_TOOLS}
    voice = {t["name"] for t in meeting_ledger.REALTIME_TOOLS}
    assert chat == voice == {"search_transactions", "ledger_summary", "remember"}


# ------------------------------------------------- where Aria uses it ---

def _remember_gocardless(db):
    confirm(db, propose(db)["id"])


def test_a_typed_meeting_turn_includes_the_owner_s_notes(db, monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from services import executive_meeting_orchestrator as orch
    from services import profit_guard
    _remember_gocardless(db)
    sent = []

    async def create(**kwargs):
        sent.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Noted.", tool_calls=None),
                                                        finish_reason="stop")],
                               usage=SimpleNamespace(total_tokens=5))
    monkeypatch.setattr(orch, "_get_async_client",
                        lambda: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    monkeypatch.setattr(profit_guard, "permits", lambda purpose: True)
    monkeypatch.setattr(orch, "_load_meeting", lambda mid, s: {"business_id": A, "status": "in_progress",
                                                               "prep_data": {"business": {"name": "NB"}},
                                                               "total_tokens_used": 0})
    monkeypatch.setattr(orch, "_load_settings", lambda bid, s: {})
    monkeypatch.setattr(orch, "_save_message", lambda **kw: None)
    monkeypatch.setattr(orch, "_load_message_history", lambda mid, s: [{"role": "owner", "content": "Hi"}])
    monkeypatch.setattr(orch, "_increment_total_tokens", lambda *a: None)
    with Session(db) as s:
        asyncio.run(orch.handle_turn("m1", "Hi", s))
    system = sent[0]["messages"][0]["content"]
    assert "GoCardless: Student course income (group: Student courses)" in system


def test_a_spoken_meeting_includes_the_owner_s_notes(db, monkeypatch):
    from services import executive_meeting_orchestrator as orch
    _remember_gocardless(db)
    monkeypatch.setattr(orch, "_load_meeting", lambda mid, s: {"business_id": A, "status": "in_progress",
                                                               "prep_data": {"business": {"name": "NB"}}})
    monkeypatch.setattr(orch, "_load_settings", lambda bid, s: {})
    monkeypatch.setattr(orch, "_load_message_history", lambda mid, s: [])
    with Session(db) as s:
        assert "Student course income" in orch.voice_context("m1", A, s)


def test_ordinary_aria_chat_includes_the_owner_s_notes(db, monkeypatch):
    import contextlib
    import assistant_chat
    import db as dbmod
    _remember_gocardless(db)

    @contextlib.contextmanager
    def ctx():
        with Session(db) as s:
            yield s
    monkeypatch.setattr(dbmod, "get_session_context", ctx)
    assert "Student course income" in assistant_chat._owner_notes(A)
    assert assistant_chat._owner_notes(B) == ""
    prompt = assistant_chat.build_system_prompt(assistant_chat.BusinessContext(id=A, name="NB", timezone="Europe/London"))
    assert "GoCardless: Student course income" in prompt


def test_the_prompt_tells_aria_to_suggest_and_wait_for_the_owner():
    from services.executive_meeting_prompts import build_system_prompt
    prompt = build_system_prompt({"business": {"name": "Any"}}, {}).lower()
    assert "`remember`" in prompt and "confirms the card" in prompt


# --------------------------------------------------------------- the API ---

def test_the_api_lists_confirms_edits_and_deletes(db):
    import executive_meeting_api as api
    from fastapi import HTTPException
    ctx = {"business_id": A, "user_id": OWNER}
    entry = propose(db)
    with Session(db) as s:
        assert [e["status"] for e in api.get_aria_memory(auth_ctx=ctx, session=s)["entries"]] == ["proposed"]
    with Session(db) as s:
        assert api.confirm_aria_memory(entry["id"], auth_ctx=ctx, session=s)["status"] == "confirmed"
    with Session(db) as s:
        out = api.update_aria_memory(entry["id"], api.MemoryChange(clear_group=True), auth_ctx=ctx, session=s)
        assert out["group"] is None and out["meaning"] == "Student course income"
    with Session(db) as s:
        added = api.add_aria_memory(api.MemoryIn(about="Rent", meaning="Unit 4 lease"), auth_ctx=ctx, session=s)
        assert added["status"] == "confirmed"
    with Session(db) as s:
        assert api.update_aria_memory_settings(api.MemorySettings(one_off_from=1500), auth_ctx=ctx,
                                               session=s) == {"one_off_from": 1500}
    with Session(db) as s:
        assert api.delete_aria_memory(entry["id"], auth_ctx=ctx, session=s) == {"deleted": True}
    with Session(db) as s:
        with pytest.raises(HTTPException) as err:
            api.delete_aria_memory(entry["id"], auth_ctx=ctx, session=s)
    assert err.value.status_code == 404


def test_bad_input_is_a_422_not_a_crash(db):
    import executive_meeting_api as api
    from fastapi import HTTPException
    with Session(db) as s:
        with pytest.raises(HTTPException) as err:
            api.add_aria_memory(api.MemoryIn(about=" ", meaning="x"), auth_ctx={"business_id": A, "user_id": OWNER},
                                session=s)
    assert err.value.status_code == 422
    with Session(db) as s:
        with pytest.raises(HTTPException) as err:
            api.update_aria_memory_settings(api.MemorySettings(one_off_from=-1),
                                            auth_ctx={"business_id": A, "user_id": OWNER}, session=s)
    assert err.value.status_code == 422


def test_every_word_of_a_note_must_match_the_line():
    entry = {"about": "Ashbourne Management", "status": "confirmed", "group": "Memberships"}
    assert mem().matches(entry, {"payee": "ASHBOURNE MANAGEMENT SERVICES"})
    assert not mem().matches(entry, {"payee": "Management fee", "reference": "smith"})



# ---- Codex BM-4 review 1 ---------------------------------------------------

@pytest.mark.parametrize("call", ["add", "confirm", "update", "delete", "settings"])
def test_only_the_owner_changes_what_aria_remembers(db, call):
    """Finding 1: staff may see the notes and Aria may suggest, but only an
    active owner confirms, adds, edits or deletes."""
    import executive_meeting_api as api
    from fastapi import HTTPException
    entry = propose(db)
    staff = {"business_id": A, "user_id": STAFF}
    actions = {
        "add": lambda s, c: api.add_aria_memory(api.MemoryIn(about="X", meaning="Y"), auth_ctx=c, session=s),
        "confirm": lambda s, c: api.confirm_aria_memory(entry["id"], auth_ctx=c, session=s),
        "update": lambda s, c: api.update_aria_memory(entry["id"], api.MemoryChange(meaning="Z"), auth_ctx=c,
                                                      session=s),
        "delete": lambda s, c: api.delete_aria_memory(entry["id"], auth_ctx=c, session=s),
        "settings": lambda s, c: api.update_aria_memory_settings(api.MemorySettings(one_off_from=900),
                                                                 auth_ctx=c, session=s),
    }
    with Session(db) as s:
        with pytest.raises(HTTPException) as err:
            actions[call](s, staff)
    assert err.value.status_code == 403
    with Session(db) as s:
        assert api.get_aria_memory(auth_ctx=staff, session=s)["entries"][0]["status"] == "proposed"
    with Session(db) as s:
        actions[call](s, {"business_id": A, "user_id": OWNER})          # the owner may


def test_the_owner_s_own_entry_is_what_gets_confirmed(db):
    """Finding 2: adding the same note without a group confirms it without
    the proposal's group."""
    propose(db, group="A group nobody approved")
    with Session(db) as s:
        out = mem().add(s, A, about="GoCardless", meaning="Student course income", group=None)
    assert out["status"] == "confirmed" and out["group"] is None
    assert [(e["about"], e["group"]) for e in confirmed(db)] == [("GoCardless", None)]


def test_an_unreadable_memory_never_undoes_the_meeting_s_own_work(db, monkeypatch):
    """Finding 3: the notes are read in their own session; a failure there
    leaves the caller's pending change in place."""
    import contextlib
    import db as dbmod
    from services import executive_meeting_orchestrator as orch

    @contextlib.contextmanager
    def broken():
        raise RuntimeError("database unavailable")
        yield
    monkeypatch.setattr(dbmod, "get_session_context", broken)
    with Session(db) as s:
        s.execute(text("UPDATE business_settings SET updated_at = 'pending-change' WHERE business_id = :b"),
                  {"b": A})
        assert orch._memory_block(A, s) == ""
        s.commit()
    with Session(db) as s:
        assert s.execute(text("SELECT updated_at FROM business_settings")).scalar() == "pending-change"


def test_many_groups_over_twelve_months_still_fit_with_detail(db):
    """Finding 4: group lists are trimmed like the others; coverage and the
    monthly totals survive."""
    from services import meeting_ledger
    from datetime import timedelta
    for g in range(100):
        tx(db, date(2026, 1, 1) + timedelta(days=g * 3 % 300), "income", 100 + g, f"Payer {g}")
        tx(db, date(2026, 1, 2) + timedelta(days=g * 3 % 300), "expense", 50 + g, f"Payer {g}")
    memory = [{"about": f"Payer {g}", "meaning": "m", "group": f"Group {g:03d} " + "x" * 40,
               "status": "confirmed"} for g in range(100)]
    with Session(db) as s:
        out = meeting_ledger.fit(meeting_ledger.summary(s, A, TODAY, months=12, memory=memory), limit=4000)
    assert len(json.dumps(out)) <= 4000
    assert "error" not in out and out["coverage"] and len(out["monthly_totals"]) == 12
    assert out["trimmed"].get("income_by_group") or out["trimmed"].get("expense_by_group")


def test_confirming_cannot_pass_the_limit_by_any_path(db, monkeypatch):
    """Finding 5: a duplicate promoted through add, and confirm, are capped."""
    monkeypatch.setattr(mem(), "MAX_CONFIRMED", 1)
    with Session(db) as s:
        mem().add(s, A, about="First", meaning="m")
    waiting = propose(db, about="Second", meaning="m2")
    with Session(db) as s:
        with pytest.raises(ValueError):
            mem().add(s, A, about="Second", meaning="m2")
    with Session(db) as s:
        with pytest.raises(ValueError):
            mem().confirm(s, A, waiting["id"])
    assert len(confirmed(db)) == 1
    with Session(db) as s:
        first = [e for e in mem().list_entries(s, A)["entries"] if e["about"] == "First"][0]
        assert mem().confirm(s, A, first["id"])["status"] == "confirmed", "confirming again is harmless"


@pytest.mark.parametrize("amount", [0.1, 0.49, "nan", "inf", "-inf", "abc", 1e30, "1E+400", 10_000_001])
def test_a_threshold_that_would_round_to_nothing_or_is_not_a_number_is_refused(db, amount):
    """Finding 6."""
    with Session(db) as s:
        with pytest.raises(ValueError):
            mem().set_one_off_from(s, A, amount)
    with Session(db) as s:
        assert mem().set_one_off_from(s, A, 0.5) == 1.0


def test_the_notes_are_never_read_through_the_meeting_s_own_session(db):
    """Finding 3: the caller's session is not touched at all."""
    from services import executive_meeting_orchestrator as orch
    confirm(db, propose(db)["id"])

    class Untouchable:
        def __getattr__(self, name):
            raise AssertionError(f"the meeting's session was used: {name}")
    assert "Student course income" in orch._memory_block(A, Untouchable())


def test_a_huge_threshold_through_the_api_is_a_422_not_a_crash(db):
    """Codex BM-4 review 2."""
    import executive_meeting_api as api
    from fastapi import HTTPException
    with Session(db) as s:
        with pytest.raises(HTTPException) as err:
            api.update_aria_memory_settings(api.MemorySettings(one_off_from=1e30),
                                            auth_ctx={"business_id": A, "user_id": OWNER}, session=s)
    assert err.value.status_code == 422
