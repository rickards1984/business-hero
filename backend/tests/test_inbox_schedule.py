"""ARIA-1a — when Aria checks mail, that the check never holds up the app,
fetches new mail only, and what the Comms page is told."""
import asyncio
import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

UK = ZoneInfo("Europe/London")


def uk(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=UK).astimezone(timezone.utc)


# ------------------------------------------------------------ the window ---

@pytest.mark.parametrize("when,inside", [
    (uk(2026, 11, 23, 6, 59), False),       # Monday, before 7
    (uk(2026, 11, 23, 7, 0), True),
    (uk(2026, 11, 23, 12, 30), True),
    (uk(2026, 11, 23, 18, 59), True),
    (uk(2026, 11, 23, 19, 0), True),        # the 19:00 check
    (uk(2026, 11, 23, 19, 15), False),
    (uk(2026, 11, 28, 10, 0), False),       # Saturday
    (uk(2026, 11, 29, 10, 0), False),       # Sunday
    (uk(2026, 6, 15, 7, 0), True),          # British Summer Time: 06:00 UTC
    (uk(2026, 6, 15, 6, 30), False),
])
def test_the_window_is_weekdays_7_to_7_uk_time(when, inside):
    from services import inbox_schedule
    assert inbox_schedule.in_window(when) is inside


def test_a_quick_check_every_15_minutes_and_a_full_sync_every_2_hours():
    from services import inbox_schedule as s
    t = uk(2026, 11, 23, 9, 0)
    assert s.due(t, None, None) == "full"
    assert s.due(t + timedelta(minutes=5), t, t) is None
    assert s.due(t + timedelta(minutes=15), t, t) == "quick"
    assert s.due(t + timedelta(minutes=30), t, t + timedelta(minutes=15)) == "quick"
    assert s.due(t + timedelta(hours=2), t, t + timedelta(minutes=105)) == "full"   # the full one takes its place
    assert s.due(uk(2026, 11, 28, 10, 0), None, None) is None                      # never at the weekend


@pytest.mark.parametrize("now,last,expected", [
    (uk(2026, 11, 23, 9, 0), uk(2026, 11, 23, 8, 50), uk(2026, 11, 23, 9, 5)),
    (uk(2026, 11, 23, 9, 0), None, uk(2026, 11, 23, 9, 0)),
    (uk(2026, 11, 23, 20, 0), None, uk(2026, 11, 24, 7, 0)),       # Monday evening: Tuesday 7am
    (uk(2026, 11, 27, 19, 30), None, uk(2026, 11, 30, 7, 0)),      # Friday evening: Monday 7am
    (uk(2026, 11, 28, 12, 0), None, uk(2026, 11, 30, 7, 0)),       # Saturday: Monday 7am
    (uk(2026, 11, 23, 6, 0), None, uk(2026, 11, 23, 7, 0)),        # Monday early: 7am today
])
def test_the_next_check_is_when_the_scheduler_will_run(now, last, expected):
    from services import inbox_schedule
    assert inbox_schedule.next_check(now, last) == expected


def test_the_scheduler_uses_the_schedule():
    from pathlib import Path
    from services import briefing_scheduler
    source = Path(briefing_scheduler.__file__).read_bytes().decode()
    assert "inbox_schedule.due(now, _last_email_sync, _last_email_quick)" in source
    assert "_safe_background_email_sync(new_only=True)" in source and "\r\n" in source        # CRLF kept
    assert "7200" not in source


# ---------------------------------------------------- off the event loop ---

def test_each_business_syncs_in_a_worker_thread_not_on_the_event_loop(monkeypatch):
    from services import background_sync
    seen = []
    monkeypatch.setattr(background_sync, "_sync_email_for_business",
                        lambda bid, new_only=False: seen.append((bid, new_only,
                                                                threading.current_thread() is threading.main_thread())))

    class Rows:
        def __enter__(self):
            return SimpleNamespace(execute=lambda *a, **k: SimpleNamespace(fetchall=lambda: [("b1",), ("b2",)]))

        def __exit__(self, *a):
            return False
    import db
    monkeypatch.setattr(db, "get_session_context", lambda: Rows())
    asyncio.run(background_sync.background_email_sync_all(new_only=True))
    assert seen == [("b1", True, False), ("b2", True, False)]


def test_two_syncs_never_run_at_once(monkeypatch):
    from services import background_sync
    calls = []

    async def slow(new_only):
        calls.append(new_only)
        await asyncio.sleep(0.05)
    monkeypatch.setattr(background_sync, "_email_sync_all", slow)

    async def both():
        await asyncio.gather(background_sync.background_email_sync_all(True),
                             background_sync.background_email_sync_all(False))
    asyncio.run(both())
    assert calls == [True] and background_sync._email_sync_running is False


# ------------------------------------------------------ new mail only ---

def test_gmail_fetches_only_mail_it_hasn_t_stored(monkeypatch):
    from providers import google_gmail
    listed = {"messages": [{"id": i} for i in ("n1", "old1", "n2", "old2")]}
    fetched = []

    class Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, headers=None, params=None):
            return SimpleNamespace(status_code=200, json=lambda: listed, text="")
    monkeypatch.setattr(google_gmail.httpx, "Client", Client)
    monkeypatch.setattr(google_gmail, "get_valid_access_token", lambda account: "token")
    monkeypatch.setattr(google_gmail, "_fetch_message_metadata_safe",
                        lambda client, headers, mid: fetched.append(mid) or SimpleNamespace(provider_message_id=mid))
    out = google_gmail.GoogleGmailProvider().sync_inbox_changes(account=None, cursor={}, skip_ids={"old1", "old2"})
    assert sorted(fetched) == ["n1", "n2"] and [m.provider_message_id for m in out.messages] == ["n1", "n2"]
    fetched.clear()
    google_gmail.GoogleGmailProvider().sync_inbox_changes(account=None, cursor={})         # the full sync
    assert sorted(fetched) == ["n1", "n2", "old1", "old2"]


def test_the_quick_check_passes_the_stored_ids_and_the_full_sync_doesn_t():
    from pathlib import Path
    from services import background_sync
    source = Path(background_sync.__file__).read_text()
    assert "if new_only:" in source and "skip_ids=known" in source


@pytest.mark.parametrize("module", ["providers.base", "providers.google_gmail", "providers.microsoft_graph"])
def test_every_provider_accepts_skip_ids(module):
    import importlib
    import inspect
    mod = importlib.import_module(module)
    cls = next(c for _, c in inspect.getmembers(mod, inspect.isclass)
               if "sync_inbox_changes" in c.__dict__ and c.__module__ == mod.__name__)
    assert "skip_ids" in inspect.signature(cls.sync_inbox_changes).parameters


# ------------------------------------------------- what the page is told ---

def test_sort_now_says_what_it_did(monkeypatch):
    from app.email import router
    monkeypatch.setattr(router, "_sort_now", lambda bid, only=None: {"sorted": 3, "skipped": 5, "waiting": 0,
                                                                     "failed": False})
    monkeypatch.setattr(router, "get_business_by_id", lambda s, bid: SimpleNamespace(id=bid))
    out = asyncio.run(router.analyze_emails.__wrapped__(
        SimpleNamespace(), router.EmailAnalyzeRequest(message_ids=[]), auth_ctx={"business_id": "b1"},
        session=SimpleNamespace(rollback=lambda: None)))
    assert (out.sorted_count, out.skipped_count, out.waiting_count, out.failed, out.analyzed_count) == (3, 5, 0, False, 8)


def test_the_status_reads_categories_old_and_new(monkeypatch):
    from sqlalchemy import create_engine, text
    from sqlmodel import Session
    from app.email import router
    engine = create_engine("sqlite://")
    now = datetime.now(timezone.utc)
    with engine.begin() as c:
        c.execute(text("CREATE TABLE email_messages (business_id TEXT, ai_category TEXT, ai_priority INT, "
                       "is_unread BOOLEAN, received_at TIMESTAMP, ai_analyzed_at TIMESTAMP, folder TEXT DEFAULT 'INBOX')"))
        for cat, prio, unread, analysed in [("finance", 3, True, now), ("money", 2, False, now),
                                            ("marketing", 1, True, now), ("new_enquiry", 4, True, now),
                                            (None, None, True, None)]:
            c.execute(text("INSERT INTO email_messages VALUES ('b1', :c, :p, :u, :r, :a, 'INBOX')"),
                      {"c": cat, "p": prio, "u": unread, "r": now - timedelta(hours=2), "a": analysed})
    with Session(engine) as s:
        out = router.email_sorting_status(range="month", auth_ctx={"business_id": "b1"}, session=s)
    counts = {c["key"]: c["count"] for c in out["categories"]}
    assert counts["money"] == 2 and counts["junk"] == 1 and counts["new_enquiry"] == 1
    assert out["waiting"] == 1 and out["important_unread"] == 2 and out["last_sorted_at"]
    assert out["schedule"] == "every 15 minutes, weekdays 7am to 7pm" and out["next_check_at"]


def test_the_message_list_filters_by_mike_s_categories_and_importance():
    from pathlib import Path
    from app.email import router
    source = Path(router.__file__).read_text()
    assert "inbox_sorting.category_sql(category)" in source and 'category == "important"' in source
    import inspect
    assert not inspect.iscoroutinefunction(router.list_email_messages)       # its DB work in a worker


# ------------------------------------------------ Codex ARIA-1a review 1 ---

def test_the_next_check_is_never_outside_the_window():
    """Finding 7: Friday 18:55, last check 18:50, said 19:05."""
    from services import inbox_schedule
    assert inbox_schedule.next_check(uk(2026, 11, 27, 18, 55), uk(2026, 11, 27, 18, 50)) == uk(2026, 11, 30, 7, 0)
    assert inbox_schedule.next_check(uk(2026, 11, 27, 18, 50), uk(2026, 11, 27, 18, 45)) == uk(2026, 11, 27, 19, 0)


def test_a_sync_still_running_means_nothing_is_recorded_as_run(monkeypatch):
    """Finding 6: a full sync skipped by the overlap guard was recorded as
    run, so read state went stale for two more hours."""
    from services import background_sync, briefing_scheduler
    started = []
    monkeypatch.setattr(briefing_scheduler.asyncio, "create_task", lambda coro: started.append(coro) or coro.close())
    monkeypatch.setattr(briefing_scheduler, "_last_email_sync", None)
    monkeypatch.setattr(briefing_scheduler, "_last_email_quick", None)
    monkeypatch.setattr(briefing_scheduler, "_last_financial_sync", datetime.now(timezone.utc))
    from services import inbox_schedule
    monkeypatch.setattr(inbox_schedule, "in_window", lambda now: True)
    monkeypatch.setattr(background_sync, "_email_sync_running", True)
    briefing_scheduler._run_background_sync_jobs_nonblocking()
    assert started == [] and briefing_scheduler._last_email_sync is None
    monkeypatch.setattr(background_sync, "_email_sync_running", False)
    briefing_scheduler._run_background_sync_jobs_nonblocking()
    assert len(started) == 1 and briefing_scheduler._last_email_sync is not None


def test_the_counts_are_for_the_page_s_time_range(monkeypatch):
    """Finding 5: the counts came from the filtered list on screen."""
    from sqlalchemy import create_engine, text
    from sqlmodel import Session
    from app.email import router
    engine = create_engine("sqlite://")
    now = datetime.now(timezone.utc)
    with engine.begin() as c:
        c.execute(text("CREATE TABLE email_messages (business_id TEXT, ai_category TEXT, ai_priority INT, "
                       "is_unread BOOLEAN, received_at TIMESTAMP, ai_analyzed_at TIMESTAMP, folder TEXT)"))
        for cat, unread, age in [("money", True, timedelta(minutes=10)), ("junk", True, timedelta(minutes=5)),
                                 ("new_enquiry", False, timedelta(days=3)), ("customer", True, timedelta(days=20))]:
            c.execute(text("INSERT INTO email_messages VALUES ('b1', :c, 3, :u, :r, :r, 'INBOX')"),
                      {"c": cat, "u": unread, "r": now - age})
    with Session(engine) as s:
        week = router.email_sorting_status(range="week", auth_ctx={"business_id": "b1"}, session=s)
        every = router.email_sorting_status(range="all", auth_ctx={"business_id": "b1"}, session=s)
    counts = {c["key"]: c["count"] for c in week["categories"]}
    assert (week["total"], counts["money"], counts["junk"], counts["new_enquiry"], counts["customer"]) == (3, 1, 1, 1, 0)
    assert week["important"] == 2 and week["important_unread"] == 1 and week["unread"] == 2
    assert every["total"] == 4 and every["important_unread"] == 2


def test_the_page_takes_its_counts_from_the_server_and_the_cards_filter_what_they_say():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2] / "frontend/client/src/components/EmailsTab.tsx").read_text()
    assert "fetchSortingStatus(timeRange)" in src and "needsYou: sorting.important_unread" in src
    assert "showCategory('important', true)" in src and "showCategory('all', true)" in src
    assert "unreadOnly," in src and "setInterval(loadSorting, 60000)" in src


def test_the_postgres_lock_lets_one_pass_run(monkeypatch):
    """Finding 3 across app instances: a session advisory lock on its own
    connection. Run against the local PostgreSQL harness when it's up."""
    import os
    url = os.environ.get("RLS_LOCAL_DATABASE_URL")
    if not url:
        pytest.skip("RLS_LOCAL_DATABASE_URL not set (scripts/rls-local.sh up). A skip is not a pass.")
    from sqlalchemy import create_engine
    from sqlmodel import Session
    from services import inbox_sorting
    engine = create_engine(url)
    with Session(engine) as a, Session(engine) as b:
        with inbox_sorting._one_pass(a, "biz-lock-test") as first:
            with inbox_sorting._one_pass(b, "biz-lock-test") as second:
                assert first is True and second is False
            with inbox_sorting._one_pass(b, "another-business") as other:
                assert other is True
        with inbox_sorting._one_pass(b, "biz-lock-test") as after:
            assert after is True



def test_the_lock_works_for_a_session_bound_to_a_connection_on_postgres():
    """Review 2, finding 10: Session(bind=connection).get_bind() is a
    Connection, which has no connect()."""
    import os
    url = os.environ.get("RLS_LOCAL_DATABASE_URL")
    if not url:
        pytest.skip("RLS_LOCAL_DATABASE_URL not set (scripts/rls-local.sh up). A skip is not a pass.")
    from sqlalchemy import create_engine
    from sqlmodel import Session
    from services import inbox_sorting
    engine = create_engine(url)
    with engine.connect() as conn, Session(bind=conn) as a, Session(engine) as b:
        with inbox_sorting._one_pass(a, "biz-conn-bound") as first, inbox_sorting._one_pass(b, "biz-conn-bound") as second:
            assert first is True and second is False


def test_the_page_never_shows_a_stale_view():
    """Review 2, finding 5: a poll kept an old loadEmails; the periods and
    timezone differed from the server's; the list didn't follow the counts."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2] / "frontend/client/src/components/EmailsTab.tsx").read_text()
    assert "await loadEmailsRef.current();" in src and "if (request !== requestRef.current)" in src
    assert "timeZone: 'Europe/London'" in src and "range === 'week' ? 7 : 30" in src
    assert ".filter(e => !unreadOnly || e.is_unread)" in src
    assert "next.last_sorted_at !== lastSortedRef.current" in src
