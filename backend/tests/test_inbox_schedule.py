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
    monkeypatch.setattr(router, "_sort_now", lambda bid: {"sorted": 3, "skipped": 5, "waiting": 0, "failed": False})
    monkeypatch.setattr(router, "get_business_by_id", lambda s, bid: SimpleNamespace(id=bid))
    out = asyncio.run(router.analyze_emails.__wrapped__(
        SimpleNamespace(), router.EmailAnalyzeRequest(message_ids=[]), auth_ctx={"business_id": "b1"}, session=None))
    assert (out.sorted_count, out.skipped_count, out.waiting_count, out.failed, out.analyzed_count) == (3, 5, 0, False, 8)


def test_the_status_reads_categories_old_and_new(monkeypatch):
    from sqlalchemy import create_engine, text
    from sqlmodel import Session
    from app.email import router
    engine = create_engine("sqlite://")
    now = datetime.now(timezone.utc)
    with engine.begin() as c:
        c.execute(text("CREATE TABLE email_messages (business_id TEXT, ai_category TEXT, ai_priority INT, "
                       "is_unread BOOLEAN, received_at TIMESTAMP, ai_analyzed_at TIMESTAMP)"))
        for cat, prio, unread, analysed in [("finance", 3, True, now), ("money", 2, False, now),
                                            ("marketing", 1, True, now), ("new_enquiry", 4, True, now),
                                            (None, None, True, None)]:
            c.execute(text("INSERT INTO email_messages VALUES ('b1', :c, :p, :u, :r, :a)"),
                      {"c": cat, "p": prio, "u": unread, "r": now - timedelta(hours=2), "a": analysed})
    with Session(engine) as s:
        out = router.email_sorting_status(auth_ctx={"business_id": "b1"}, session=s)
    counts = {c["key"]: c["count"] for c in out["categories"]}
    assert counts["money"] == 2 and counts["junk"] == 1 and counts["new_enquiry"] == 1
    assert out["waiting"] == 1 and out["important_unread"] == 2 and out["last_sorted_at"]
    assert out["schedule"] == "every 15 minutes, weekdays 7am to 7pm" and out["next_check_at"]


def test_the_message_list_filters_by_mike_s_categories_and_importance():
    from pathlib import Path
    from app.email import router
    source = Path(router.__file__).read_text()
    assert "inbox_sorting.stored_values({wanted})" in source and 'category == "important"' in source
    import inspect
    assert not inspect.iscoroutinefunction(router.list_email_messages)       # its DB work in a worker
