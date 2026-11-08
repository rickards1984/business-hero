"""BM-2 — board meetings by voice: their own minutes (docs/BM-2-TICKET.md).

Mike's decisions of 6 Nov 2026: board-meeting voice has its own monthly
allowance (Pro 60, Business 150), separate from the receptionist and Aria
voice pool; past it, the existing opt-in overage at £0.45/min under ONE spend
cap for all extra minutes. RED (money): tests first.
"""
# ruff: noqa: F811 - fixtures are parameters by design
from decimal import Decimal

import pytest
from sqlmodel import Session

from test_metering import A, OCT, business, clock, database, notices  # noqa: F401

from services import metering as m

D = Decimal


@pytest.mark.parametrize("plan,minutes", [("starter", 0), ("pro", 60), ("business", 150), ("beta", 150),
                                          (None, 0), ("unknown", 0)])
def test_each_plan_has_its_board_meeting_allowance(plan, minutes):
    assert m.allowance_minutes(plan, pool="board_meeting") == D(minutes)


def test_the_receptionist_allowance_is_unchanged():
    assert m.allowance_minutes("pro") == D(120) and m.allowance_minutes("business") == D(350)


def test_board_minutes_never_touch_the_receptionist_pool(database, clock):
    biz = business(plan="pro")
    with Session(database) as s:
        m.accrue_session(s, biz, "bm-1", 45 * 60, source="board_meeting")
        voice, board = m.usage(s, biz), m.usage(s, biz, pool="board_meeting")
    assert voice["used_minutes"] == 0 and voice["remaining_minutes"] == 120
    assert board["used_minutes"] == 45 and board["remaining_minutes"] == 15 and board["allowance_minutes"] == 60


def test_receptionist_minutes_never_touch_the_board_pool(database, clock):
    biz = business(plan="pro")
    with Session(database) as s:
        m.record_call(s, biz, 120 * 60, call_id="c1")
        assert m.usage(s, biz)["state"] == m.STATE_ALLOWANCE
        board = m.usage(s, biz, pool="board_meeting")
        assert board["remaining_minutes"] == 60 and board["state"] == m.STATE_OK
        assert m.admit_call(s, biz, pool="board_meeting") == (True, None)
        assert m.admit_call(s, biz)[0] is False


def test_a_used_up_board_allowance_refuses_a_new_spoken_meeting(database, clock, notices):
    biz = business(plan="pro")
    with Session(database) as s:
        m.accrue_session(s, biz, "bm-1", 60 * 60, source="board_meeting")
        assert m.admit_call(s, biz, pool="board_meeting") == (False, m.STATE_ALLOWANCE)
        assert m.admit_call(s, biz) == (True, None), "the receptionist still answers"


def test_past_the_allowance_with_extras_on_it_is_overage(database, clock):
    biz = business(plan="pro", metered=True)
    with Session(database) as s:
        m.accrue_session(s, biz, "bm-1", 70 * 60, source="board_meeting")
        board = m.usage(s, biz, pool="board_meeting")
    assert board["used_minutes"] == 60 and board["overage_minutes"] == 10
    assert board["overage_spend_gbp"] == D("4.50")


def test_one_spend_cap_covers_every_extra_minute(database, clock):
    """Decision 3: £10 cap; £9 of receptionist extras leaves £1 for meetings."""
    biz = business(plan="pro", metered=True, cap="10")
    with Session(database) as s:
        m.record_call(s, biz, 140 * 60, call_id="c1")                    # 20 extra = £9.00
        board = m.usage(s, biz, pool="board_meeting")
        assert board["overage_spend_gbp"] == D("9.00")
        m.accrue_session(s, biz, "bm-1", 63 * 60, source="board_meeting")  # 60 in, 3 extra
        board = m.usage(s, biz, pool="board_meeting")
        assert board["overage_spend_gbp"] == D("10.35") and board["state"] == m.STATE_CAP
        assert m.usage(s, biz)["state"] == m.STATE_CAP, "the receptionist pool sees the same cap"


def test_a_board_session_is_allowed_only_the_minutes_left(database, clock):
    biz = business(plan="pro")
    with Session(database) as s:
        assert m.seconds_allowed(m.usage(s, biz, pool="board_meeting")) == 3600
        m.accrue_session(s, biz, "bm-1", 50 * 60, source="board_meeting")
        assert m.seconds_allowed(m.usage(s, biz, pool="board_meeting")) == 600


def test_with_extras_on_a_session_may_run_on_until_the_cap(database, clock):
    biz = business(plan="pro", metered=True, cap="9")
    with Session(database) as s:
        m.accrue_session(s, biz, "bm-1", 60 * 60, source="board_meeting")
        assert m.seconds_allowed(m.usage(s, biz, pool="board_meeting")) == 20 * 60   # £9 / £0.45
        biz.monthly_spend_cap_gbp = D("1000")
        assert m.seconds_allowed(m.usage(s, biz, pool="board_meeting")) == 3600, "never past an hour"


def test_a_starter_business_is_allowed_no_spoken_meeting(database, clock):
    biz = business(plan="starter")
    with Session(database) as s:
        assert m.seconds_allowed(m.usage(s, biz, pool="board_meeting")) == 0


def test_a_lost_board_session_is_recovered_into_the_board_pool(database, clock):
    from datetime import timedelta
    biz = business(plan="pro")
    with Session(database) as s:
        m.voice_session_heartbeat(s, biz, "bm-lost", 12 * 60)
        later = m.now() + timedelta(minutes=30)
        assert m.reconcile_open_voice_sessions(s, lookup=lambda _s, _b: biz, at=later) == 1
        assert m.usage(s, biz, pool="board_meeting")["used_minutes"] == 12
        assert m.usage(s, biz)["used_minutes"] == 0


def test_the_80_percent_warning(database, clock):
    biz = business(plan="pro")
    with Session(database) as s:
        m.accrue_session(s, biz, "bm-1", 47 * 60, source="board_meeting")
        assert m.usage(s, biz, pool="board_meeting")["warn"] is False
        m.accrue_session(s, biz, "bm-2", 1 * 60, source="board_meeting")
        assert m.usage(s, biz, pool="board_meeting")["warn"] is True


def test_the_board_pool_sends_no_allowance_email(database, clock, notices):
    """The meeting screen says it; email is for the customer-facing pool."""
    biz = business(plan="pro")
    with Session(database) as s:
        m.accrue_session(s, biz, "bm-1", 61 * 60, source="board_meeting")
        m.admit_call(s, biz, pool="board_meeting")
        from sqlalchemy import text
        pending = s.execute(text("SELECT meter FROM usage_meters WHERE meter LIKE 'pending:%'")).fetchall()
        m.deliver_pending_notices(s, lookup=lambda _s, _b: biz)
    assert pending == [] and notices == []


def test_board_voice_is_counted_as_a_cost():
    from services import profit_guard
    assert m.BOARD_VOICE_METER in profit_guard.VOICE_METERS
    assert m.BOARD_VOICE_OVERAGE_METER in profit_guard.VOICE_METERS


# ------------------------------------------------------- the voice socket ---
# The real endpoint with OpenAI, auth and the database faked at their edges
# (test_voice_repair's harness). A meetingId in the auth message makes it a
# board-meeting session.

import json  # noqa: E402
import time  # noqa: E402

from test_voice_repair import _wait, voice  # noqa: E402,F401
import realtime_voice  # noqa: E402

MEETING = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"


@pytest.fixture
def meeting(voice, monkeypatch):
    """A board-meeting session: records the feature asked for, the pool
    admitted against, and every spoken turn saved."""
    st = {"features": [], "pools": [], "saved": [], "allowed": 1800, "context": "MEETING PROMPT",
          "admit": (True, None)}

    def make(script=()):
        client = voice["make"](script=script)
        import auth
        from fastapi import HTTPException

        def _gate(business, feature):
            st["features"].append(feature)
            if st.get("refuse_feature") == feature:
                raise HTTPException(status_code=403, detail=f"Feature '{feature}' not enabled")
        monkeypatch.setattr(auth, "assert_feature_access", _gate)

        def _admit(session, business, pool="voice"):
            st["pools"].append(pool)
            return st["admit"]
        monkeypatch.setattr(m, "admit_call", _admit)
        monkeypatch.setattr(m, "usage", lambda session, business, pool="voice": {"pool": pool})
        monkeypatch.setattr(m, "seconds_allowed",
                            lambda u: st["allowed"].pop(0) if isinstance(st["allowed"], list) else st["allowed"])
        monkeypatch.setattr(m, "lock_board_admission", lambda session, bid: st.setdefault("locks", []).append(bid))
        monkeypatch.setattr(m, "live_board_session", lambda session, bid: st.get("live", False))
        from services import executive_meeting_orchestrator as orch

        def _context(meeting_id, business_id, session):
            if st["context"] is None:
                raise ValueError("This meeting isn't in progress")
            return st["context"]
        monkeypatch.setattr(orch, "voice_context", _context)
        monkeypatch.setattr(orch, "save_spoken_turn",
                            lambda meeting_id, business_id, role, content, at, session:
                            st["saved"].append((meeting_id, role, content)))
        return client
    st["make"] = make
    st["voice"] = voice
    return st


def _open(ws, meeting_id=MEETING):
    ws.send_json({"type": "auth", "token": "t", "meetingId": meeting_id})
    return ws.receive_json()


def test_a_spoken_meeting_is_a_board_meeting_session(meeting):
    client = meeting["make"]()
    with client.websocket_connect("/v1/realtime/voice") as ws:
        assert _open(ws) == {"type": "ready"}
        config = json.loads(meeting["voice"]["connects"][0].sent[0])["session"]
    assert meeting["features"] == ["board_meetings"] and meeting["pools"] == ["board_meeting"]
    from services import meeting_ledger
    assert config["instructions"].startswith("MEETING PROMPT")
    assert config["tools"] == meeting_ledger.REALTIME_TOOLS, "BM-3: only the read-only ledger look-ups"
    assert _wait(lambda: len(meeting["voice"]["recorded"]) == 1)
    seconds, key, source = meeting["voice"]["recorded"][0]
    assert source == "board_meeting" and key.startswith(m.BOARD_SESSION_PREFIX)


def test_ordinary_aria_voice_is_unchanged(meeting):
    client = meeting["make"]()
    with client.websocket_connect("/v1/realtime/voice") as ws:
        ws.send_json({"type": "auth", "token": "t"})
        assert ws.receive_json() == {"type": "ready"}
    assert meeting["features"] == ["aria_voice"] and meeting["pools"] == ["voice"]
    assert _wait(lambda: len(meeting["voice"]["recorded"]) == 1)
    assert meeting["voice"]["recorded"][0][2] == "aria_voice"


@pytest.mark.parametrize("why", ["feature", "not_in_progress", "allowance", "no_minutes_left", "bad_id"])
def test_a_refused_spoken_meeting_never_reaches_openai(meeting, why):
    if why == "feature":
        meeting["refuse_feature"] = "board_meetings"
    if why == "not_in_progress":
        meeting["context"] = None
    if why == "allowance":
        meeting["admit"] = (False, m.STATE_ALLOWANCE)
    if why == "no_minutes_left":
        meeting["allowed"] = 10
    client = meeting["make"]()
    with client.websocket_connect("/v1/realtime/voice") as ws:
        with pytest.raises(Exception):
            _open(ws, meeting_id="not-a-uuid" if why == "bad_id" else MEETING)
            ws.receive_json()
    assert meeting["voice"]["connects"] == [], why
    assert meeting["voice"]["recorded"] == []


def test_both_sides_of_the_conversation_are_saved_in_order(meeting):
    script = [{"type": "input_audio_buffer.speech_stopped"},
              {"type": "response.created"},
              {"type": "response.output_audio_transcript.done", "transcript": "Revenue is up 4%."},
              {"type": "response.done"},
              {"type": "conversation.item.input_audio_transcription.completed",
               "transcript": "How did we do last month?"}]
    client = meeting["make"](script=script)
    with client.websocket_connect("/v1/realtime/voice") as ws:
        assert _open(ws) == {"type": "ready"}
        assert _wait(lambda: len(meeting["saved"]) == 2)
    assert sorted(meeting["saved"], key=lambda t: t[1] != "owner") == [
        (MEETING, "owner", "How did we do last month?"), (MEETING, "aria", "Revenue is up 4%.")]


def test_spoken_turns_keep_the_order_they_were_spoken(meeting, monkeypatch):
    """The owner's transcription arrives AFTER Aria's reply; its time is when
    the owner stopped speaking, so the transcript reads in spoken order."""
    times = []
    from services import executive_meeting_orchestrator as orch
    monkeypatch.setattr(orch, "save_spoken_turn",
                        lambda meeting_id, business_id, role, content, at, session: times.append((role, at)))
    script = [{"type": "input_audio_buffer.speech_stopped"},
              {"type": "response.created"},
              {"type": "response.output_audio_transcript.done", "transcript": "Answer."},
              {"type": "conversation.item.input_audio_transcription.completed", "transcript": "Question?"}]
    client = meeting["make"](script=script)
    # make() re-patches save_spoken_turn; patch again after it
    monkeypatch.setattr(orch, "save_spoken_turn",
                        lambda meeting_id, business_id, role, content, at, session: times.append((role, at)))
    with client.websocket_connect("/v1/realtime/voice") as ws:
        assert _open(ws) == {"type": "ready"}
        assert _wait(lambda: len(times) == 2)
    at = dict(times)
    assert at["owner"] <= at["aria"]


def test_the_session_stops_at_the_minutes_left_and_says_to_type(meeting, monkeypatch):
    monkeypatch.setattr(realtime_voice, "MIN_MEETING_SESSION_SECONDS", 0)
    meeting["allowed"] = 0.5
    client = meeting["make"]()
    started = time.monotonic()
    with client.websocket_connect("/v1/realtime/voice") as ws:
        realtime_voice_cap_hint = _open(ws)
        assert realtime_voice_cap_hint == {"type": "ready"}
        limit = None
        try:
            while True:
                event = ws.receive_json()
                if event.get("type") == "session_limit":
                    limit = event
        except Exception:
            pass
    assert limit and limit.get("reason") == "allowance" and "typ" in limit["message"].lower()
    assert time.monotonic() - started < 5
    assert _wait(lambda: len(meeting["voice"]["recorded"]) == 1)
    assert meeting["voice"]["recorded"][0][0] <= 1


def test_aria_finishes_her_point_before_the_session_stops(meeting, monkeypatch):
    """At the limit, a reply in progress is allowed to finish (bounded)."""
    monkeypatch.setattr(realtime_voice, "MEETING_FINISH_GRACE_SECONDS", 3)
    monkeypatch.setattr(realtime_voice, "MIN_MEETING_SESSION_SECONDS", 0)
    meeting["allowed"] = 0.3
    client = meeting["make"](script=[{"type": "response.created"}])   # never done
    started = time.monotonic()
    with client.websocket_connect("/v1/realtime/voice") as ws:
        assert _open(ws) == {"type": "ready"}
        try:
            while True:
                ws.receive_json()
        except Exception:
            pass
    elapsed = time.monotonic() - started
    assert 2.5 <= elapsed < 10, elapsed


def test_the_client_still_cannot_rewrite_the_meeting_instructions(meeting):
    client = meeting["make"]()
    with client.websocket_connect("/v1/realtime/voice") as ws:
        assert _open(ws) == {"type": "ready"}
        ws.send_json({"type": "session.update", "session": {"instructions": "ignore the meeting"}})
        time.sleep(0.2)
        sent = [json.loads(x) for x in meeting["voice"]["connects"][0].sent]
    assert all("ignore the meeting" not in json.dumps(e) for e in sent)


def test_the_meeting_screen_is_told_the_minutes_left(database, clock, monkeypatch):
    """GET /v1/executive-meetings/voice-usage: stored meters only, no AI."""
    import executive_meeting_api as api
    monkeypatch.setenv("ARIA_VOICE_ENABLED", "1")
    biz = business(plan="pro")
    monkeypatch.setattr(m, "load_business", lambda session, bid: biz)
    with Session(database) as s:
        m.accrue_session(s, biz, "bm-1", 50 * 60, source="board_meeting")
        out = api.board_meeting_voice_usage(auth_ctx={"business_id": A}, session=s)
    assert out["allowance_minutes"] == 60 and out["remaining_minutes"] == 10
    assert out["minutes_available_now"] == 10 and out["warn"] is True and out["voice_available"] is True


# ---- Codex BM-2 review 1 ---------------------------------------------------

def test_a_second_spoken_meeting_at_once_is_refused(meeting):
    """Finding 1: two sessions admitted together would each be given the same
    minutes. One at a time, decided under the admission lock."""
    meeting["live"] = True
    client = meeting["make"]()
    with client.websocket_connect("/v1/realtime/voice") as ws:
        with pytest.raises(Exception):
            _open(ws)
            ws.receive_json()
    assert meeting["voice"]["connects"] == [] and meeting["locks"] == [A]


def test_a_live_session_is_found_and_a_stale_one_is_not(database, clock):
    from datetime import timedelta
    biz = business(plan="pro")
    with Session(database) as s:
        assert m.live_board_session(s, A) is False
        m.voice_session_heartbeat(s, biz, "aria-session", 60)          # ordinary Aria voice
        assert m.live_board_session(s, A) is False
        m.voice_session_heartbeat(s, biz, "bm-live", 60)
        assert m.live_board_session(s, A) is True
    with Session(database) as s:
        later = m.now() + timedelta(minutes=10)
        import services.metering as mm
        mm_now = mm.now
        try:
            mm.now = lambda: later
            assert m.live_board_session(s, A) is False, "a crashed session's beat goes stale"
        finally:
            mm.now = mm_now


def test_spending_elsewhere_shortens_a_live_spoken_meeting(meeting, monkeypatch):
    """Finding 1, across pools: each heartbeat re-reads what may still be
    spent, and the session's deadline only ever moves earlier."""
    monkeypatch.setattr(realtime_voice, "VOICE_HEARTBEAT_SECONDS", 0.2)
    monkeypatch.setattr(realtime_voice, "MEETING_FINISH_GRACE_SECONDS", 0)
    meeting["allowed"] = [1800, 0, 0, 0, 0, 0, 0, 0, 0, 0]   # admission, then the cap is gone
    client = meeting["make"]()
    started = time.monotonic()
    reasons = []
    with client.websocket_connect("/v1/realtime/voice") as ws:
        assert _open(ws) == {"type": "ready"}
        try:
            while True:
                event = ws.receive_json()
                if event.get("type") == "session_limit":
                    reasons.append(event.get("reason"))
        except Exception:
            pass
    assert time.monotonic() - started < 5 and reasons == ["allowance"]


def test_a_cap_reached_through_meetings_is_still_told(database, clock, notices):
    """Finding 2: the receptionist pool has minutes left, so its own state is
    'ok'; the shared cap is still reached and the owner is told."""
    biz = business(plan="pro", metered=True, cap="1")
    with Session(database) as s:
        m.accrue_session(s, biz, "bm-1", 63 * 60, source="board_meeting")   # 3 extra = £1.35
        assert m.usage(s, biz)["state"] == m.STATE_OK          # minutes inside its allowance remain
        assert m.usage(s, biz, pool="board_meeting")["state"] == m.STATE_CAP
        m.deliver_pending_notices(s, lookup=lambda _s, _b: biz)
    assert notices == [(A, m.STATE_CAP)]


def test_the_owner_is_told_the_minutes_left_while_talking(meeting, monkeypatch):
    """Finding 7: live, including this session's own minutes."""
    monkeypatch.setattr(realtime_voice, "VOICE_HEARTBEAT_SECONDS", 0.2)
    meeting["allowed"] = 600
    client = meeting["make"]()
    with client.websocket_connect("/v1/realtime/voice") as ws:
        assert _open(ws) == {"type": "ready"}
        first = ws.receive_json()
        second = ws.receive_json()
    assert first["type"] == "voice_minutes" and 0 < first["seconds_left"] <= 600
    assert second["type"] == "voice_minutes" and second["seconds_left"] <= first["seconds_left"]


def test_aria_is_heard_to_the_end_of_her_reply(meeting, monkeypatch):
    """Finding 6: generation ends before the audio has played; two seconds of
    audio sent means two more seconds before the session stops."""
    monkeypatch.setattr(realtime_voice, "MIN_MEETING_SESSION_SECONDS", 0)
    meeting["allowed"] = 0.2
    two_seconds = "A" * (2 * 48000 * 4 // 3)        # base64 of 2s of PCM16 at 24 kHz
    script = [{"type": "response.created"}, {"type": "response.output_audio.delta", "delta": two_seconds},
              {"type": "response.done"}]
    client = meeting["make"](script=script)
    started = time.monotonic()
    with client.websocket_connect("/v1/realtime/voice") as ws:
        assert _open(ws) == {"type": "ready"}
        try:
            while True:
                ws.receive_json()
        except Exception:
            pass
    assert 1.8 <= time.monotonic() - started < 8


def test_a_passing_database_fault_does_not_lose_what_was_said(meeting, monkeypatch):
    """Finding 5: a failed save is retried."""
    from services import executive_meeting_orchestrator as orch
    monkeypatch.setattr(realtime_voice, "TURN_SAVE_RETRY_SECONDS", 0.01)
    script = [{"type": "conversation.item.input_audio_transcription.completed", "transcript": "Raise prices 5%."}]
    client = meeting["make"](script=script)
    calls = []

    def flaky(meeting_id, business_id, role, content, at, session):
        calls.append(content)
        if len(calls) == 1:
            raise RuntimeError("connection reset")
        meeting["saved"].append((meeting_id, role, content))
    monkeypatch.setattr(orch, "save_spoken_turn", flaky)
    with client.websocket_connect("/v1/realtime/voice") as ws:
        assert _open(ws) == {"type": "ready"}
        assert _wait(lambda: len(meeting["saved"]) == 1)
    assert meeting["saved"] == [(MEETING, "owner", "Raise prices 5%.")]


def test_turns_still_queued_at_the_end_are_saved_after_the_socket_goes(meeting, monkeypatch):
    """Finding 5: teardown stays bounded; what is still queued is saved by the
    worker pool afterwards, not dropped."""
    from services import executive_meeting_orchestrator as orch
    monkeypatch.setattr(realtime_voice, "_CLOSE_TIMEOUT_SECONDS", 0.2)
    script = [{"type": "conversation.item.input_audio_transcription.completed", "transcript": "First."},
              {"type": "response.output_audio_transcript.done", "transcript": "Second."}]
    client = meeting["make"](script=script)

    def slow(meeting_id, business_id, role, content, at, session):
        if content == "First.":
            time.sleep(1.0)               # longer than the teardown bound
        meeting["saved"].append((meeting_id, role, content))
    monkeypatch.setattr(orch, "save_spoken_turn", slow)
    with client.websocket_connect("/v1/realtime/voice") as ws:
        assert _open(ws) == {"type": "ready"}
        time.sleep(0.1)
    assert _wait(lambda: len(meeting["saved"]) == 2, timeout=10)
    assert {c for _, _, c in meeting["saved"]} == {"First.", "Second."}


def test_the_browser_can_ask_for_what_was_said_to_be_saved_before_ending(meeting, monkeypatch):
    """Finding 3: before /end, `flush` waits for the queued turns, then says so."""
    from services import executive_meeting_orchestrator as orch
    monkeypatch.setattr(realtime_voice, "FLUSH_TRANSCRIPTION_WAIT_SECONDS", 0.05)
    script = [{"type": "response.output_audio_transcript.done", "transcript": "Agreed: hire a coach."}]
    client = meeting["make"](script=script)

    def slow(meeting_id, business_id, role, content, at, session):
        time.sleep(0.5)
        meeting["saved"].append((meeting_id, role, content))
    monkeypatch.setattr(orch, "save_spoken_turn", slow)
    with client.websocket_connect("/v1/realtime/voice") as ws:
        assert _open(ws) == {"type": "ready"}
        time.sleep(0.1)
        ws.send_json({"type": "flush"})
        while True:
            event = ws.receive_json()
            if event.get("type") == "flushed":
                break
        assert meeting["saved"] == [(MEETING, "aria", "Agreed: hire a coach.")]


# ---- Codex BM-2 review 2 ---------------------------------------------------

def test_an_earlier_stop_never_erases_time_already_spoken(meeting, monkeypatch):
    """Finding 1: the cap vanishes mid-session; the session stops, but the
    time it ran is still billed."""
    monkeypatch.setattr(realtime_voice, "VOICE_HEARTBEAT_SECONDS", 0.3)
    monkeypatch.setattr(realtime_voice, "MEETING_FINISH_GRACE_SECONDS", 0)
    meeting["allowed"] = [600, 600, 600, 600, 600] + [0] * 20
    client = meeting["make"]()
    started = time.monotonic()
    with client.websocket_connect("/v1/realtime/voice") as ws:
        assert _open(ws) == {"type": "ready"}
        try:
            while True:
                ws.receive_json()
        except Exception:
            pass
    ran = time.monotonic() - started
    assert ran >= 1.2
    assert _wait(lambda: len(meeting["voice"]["recorded"]) == 1)
    assert meeting["voice"]["recorded"][0][0] >= int(ran) - 1 >= 1


def _flush(ws):
    ws.send_json({"type": "flush"})
    while True:
        event = ws.receive_json()
        if event.get("type") == "flushed":
            return event


def test_flush_says_so_when_a_save_is_still_running(meeting, monkeypatch):
    """Finding 2: 'flushed' is a promise that everything said is saved."""
    from services import executive_meeting_orchestrator as orch
    monkeypatch.setattr(realtime_voice, "FLUSH_TRANSCRIPTION_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(realtime_voice, "FLUSH_SAVE_TIMEOUT_SECONDS", 0.2)
    client = meeting["make"](script=[{"type": "response.output_audio_transcript.done", "transcript": "Slow."}])

    def slow(meeting_id, business_id, role, content, at, session):
        time.sleep(1.0)
        meeting["saved"].append(content)
    monkeypatch.setattr(orch, "save_spoken_turn", slow)
    with client.websocket_connect("/v1/realtime/voice") as ws:
        assert _open(ws) == {"type": "ready"}
        time.sleep(0.1)
        assert _flush(ws)["ok"] is False


def test_flush_is_ok_only_when_everything_is_saved(meeting, monkeypatch):
    monkeypatch.setattr(realtime_voice, "FLUSH_TRANSCRIPTION_WAIT_SECONDS", 0.05)
    client = meeting["make"](script=[{"type": "response.output_audio_transcript.done", "transcript": "Quick."}])
    with client.websocket_connect("/v1/realtime/voice") as ws:
        assert _open(ws) == {"type": "ready"}
        time.sleep(0.1)
        assert _flush(ws)["ok"] is True
    assert meeting["saved"] == [(MEETING, "aria", "Quick.")]


def test_a_turn_that_fails_every_retry_is_kept_and_saved_later(meeting, monkeypatch):
    """Finding 3: three failures do not drop it; flush reports it unsaved;
    once the database is back it is saved, after the socket has gone."""
    from services import executive_meeting_orchestrator as orch
    monkeypatch.setattr(realtime_voice, "TURN_SAVE_RETRY_SECONDS", 0.01)
    monkeypatch.setattr(realtime_voice, "FLUSH_TRANSCRIPTION_WAIT_SECONDS", 0.05)
    client = meeting["make"](script=[{"type": "conversation.item.input_audio_transcription.completed",
                                      "transcript": "Target 400 members."}])
    down = {"yes": True}

    def flaky(meeting_id, business_id, role, content, at, session):
        if down["yes"]:
            raise RuntimeError("database unavailable")
        meeting["saved"].append(content)
    monkeypatch.setattr(orch, "save_spoken_turn", flaky)
    with client.websocket_connect("/v1/realtime/voice") as ws:
        assert _open(ws) == {"type": "ready"}
        time.sleep(0.2)
        assert _flush(ws)["ok"] is False
        down["yes"] = False
    assert _wait(lambda: meeting["saved"] == ["Target 400 members."], timeout=10)


def test_ending_tries_a_failed_turn_again_and_then_says_ok(meeting, monkeypatch):
    from services import executive_meeting_orchestrator as orch
    monkeypatch.setattr(realtime_voice, "TURN_SAVE_RETRY_SECONDS", 0.01)
    monkeypatch.setattr(realtime_voice, "FLUSH_TRANSCRIPTION_WAIT_SECONDS", 0.05)
    client = meeting["make"](script=[{"type": "response.output_audio_transcript.done", "transcript": "Noted."}])
    down = {"yes": True}

    def flaky(meeting_id, business_id, role, content, at, session):
        if down["yes"]:
            raise RuntimeError("database unavailable")
        meeting["saved"].append(content)
    monkeypatch.setattr(orch, "save_spoken_turn", flaky)
    with client.websocket_connect("/v1/realtime/voice") as ws:
        assert _open(ws) == {"type": "ready"}
        time.sleep(0.3)                    # all three attempts fail
        down["yes"] = False
        assert _flush(ws)["ok"] is True
        assert meeting["saved"] == ["Noted."]


# ---- Codex BM-2 review 3 ---------------------------------------------------

def test_a_turn_whose_save_never_started_is_saved_after_the_session(meeting, monkeypatch):
    """Finding 1: the worker pool is busy, so the writer's save has not begun
    when the session ends. The turn is still pending in the ledger and the
    final save writes it."""
    from services import executive_meeting_orchestrator as orch
    real = realtime_voice.asyncio.to_thread

    async def busy_pool(func, *a, **k):
        if getattr(func, "__name__", "") == "_save_entry":
            await asyncio_sleep_forever()
        return await real(func, *a, **k)
    monkeypatch.setattr(realtime_voice.asyncio, "to_thread", busy_pool)
    client = meeting["make"](script=[{"type": "response.output_audio_transcript.done",
                                      "transcript": "Membership target: 400."}])
    monkeypatch.setattr(orch, "save_spoken_turn",
                        lambda meeting_id, business_id, role, content, at, session: meeting["saved"].append(content))
    with client.websocket_connect("/v1/realtime/voice") as ws:
        assert _open(ws) == {"type": "ready"}
        time.sleep(0.2)
    assert _wait(lambda: meeting["saved"] == ["Membership target: 400."], timeout=10)


async def asyncio_sleep_forever():
    import asyncio
    await asyncio.sleep(3600)


def test_the_final_save_stops_at_its_deadline(meeting, monkeypatch):
    """Finding 2: a database that keeps failing is not retried for ever; the
    deadline is checked before every save."""
    from services import executive_meeting_orchestrator as orch
    monkeypatch.setattr(realtime_voice, "FINAL_SAVE_SECONDS", 0.3)
    monkeypatch.setattr(realtime_voice, "TURN_SAVE_ATTEMPTS", 1)
    monkeypatch.setattr(realtime_voice, "TURN_SAVE_RETRY_SECONDS", 0.01)
    script = [{"type": "response.output_audio_transcript.done", "transcript": f"Turn {i}."} for i in range(5)]
    client = meeting["make"](script=script)
    calls = []

    def failing(meeting_id, business_id, role, content, at, session):
        calls.append(time.monotonic())
        time.sleep(0.1)
        raise RuntimeError("database unavailable")
    monkeypatch.setattr(orch, "save_spoken_turn", failing)
    with client.websocket_connect("/v1/realtime/voice") as ws:
        assert _open(ws) == {"type": "ready"}
        time.sleep(0.2)
    time.sleep(1.5)
    # The writer tries each of the 5 turns once; every call after that is the
    # final save, which must start no save once its 0.3s are up.
    final = calls[5:]
    assert final, "the final save ran"
    assert final[-1] - final[0] < 0.3 + 0.05, "no save starts after the deadline"


def test_a_turn_is_saved_once_even_when_the_final_save_overlaps_it(meeting, monkeypatch):
    """The final save starts while the writer's save of the same turn is
    still running: the turn is claimed, so it is not written twice."""
    from services import executive_meeting_orchestrator as orch
    monkeypatch.setattr(realtime_voice, "_CLOSE_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(realtime_voice, "TURN_SAVE_RETRY_SECONDS", 0.01)
    client = meeting["make"](script=[{"type": "response.output_audio_transcript.done", "transcript": "Once."}])

    def slow(meeting_id, business_id, role, content, at, session):
        time.sleep(0.8)
        meeting["saved"].append(content)
    monkeypatch.setattr(orch, "save_spoken_turn", slow)
    with client.websocket_connect("/v1/realtime/voice") as ws:
        assert _open(ws) == {"type": "ready"}
        time.sleep(0.05)
    time.sleep(2.0)
    assert meeting["saved"] == ["Once."]


# ---- Codex BM-2 review 4 ---------------------------------------------------

def test_the_final_save_retries_a_save_that_fails_while_it_is_looking(meeting, monkeypatch):
    """The writer's save of the only turn is running (state 'saving') when the
    final save starts, then fails. The final save must see it as outstanding
    and retry it, not return between two separate looks."""
    from services import executive_meeting_orchestrator as orch
    monkeypatch.setattr(realtime_voice, "_CLOSE_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(realtime_voice, "TURN_SAVE_ATTEMPTS", 1)
    monkeypatch.setattr(realtime_voice, "TURN_SAVE_RETRY_SECONDS", 0.05)
    client = meeting["make"](script=[{"type": "response.output_audio_transcript.done", "transcript": "Kept."}])
    attempts = []

    def first_fails_late(meeting_id, business_id, role, content, at, session):
        attempts.append(content)
        if len(attempts) == 1:
            time.sleep(0.6)              # still 'saving' when the final save first looks
            raise RuntimeError("connection reset")
        meeting["saved"].append(content)
    monkeypatch.setattr(orch, "save_spoken_turn", first_fails_late)
    with client.websocket_connect("/v1/realtime/voice") as ws:
        assert _open(ws) == {"type": "ready"}
        time.sleep(0.05)
    assert _wait(lambda: meeting["saved"] == ["Kept."], timeout=10)


# ---- BM-3: spoken meetings can look up the ledger -------------------------

@pytest.mark.parametrize("name,allowed", [("search_transactions", True), ("send_email", False)])
def test_a_spoken_meeting_looks_up_only_the_ledger_for_its_business(meeting, monkeypatch, name, allowed):
    from services import meeting_ledger
    ran = []
    monkeypatch.setattr(meeting_ledger, "run_tool",
                        lambda n, args, session, bid, today: ran.append((n, args, bid)) or '{"matched": 1}')
    script = [{"type": "response.function_call_arguments.done", "call_id": "k1", "name": name,
               "arguments": '{"text": "gocardless", "business_id": "someone-else"}'}]
    client = meeting["make"](script=script)
    with client.websocket_connect("/v1/realtime/voice") as ws:
        assert _open(ws) == {"type": "ready"}
        up = meeting["voice"]["connects"][0]
        assert _wait(lambda: any('"function_call_output"' in x for x in up.sent))
    output = next(json.loads(x) for x in up.sent if '"function_call_output"' in x)["item"]["output"]
    if allowed:
        assert ran == [("search_transactions", {"text": "gocardless", "business_id": "someone-else"}, A)]
        assert output == '{"matched": 1}'
    else:
        assert ran == [] and "no tool" in output.lower()


# ---- Codex BM-3 review 5 ---------------------------------------------------

def test_speech_during_a_look_up_is_saved_before_ending(meeting, monkeypatch):
    """A slow ledger look-up must not stop the stream being read: the owner's
    transcription that arrives meanwhile is saved, and flush says ok only
    once the look-up and every turn are done."""
    from services import executive_meeting_orchestrator as orch
    from services import meeting_ledger
    monkeypatch.setattr(realtime_voice, "FLUSH_TRANSCRIPTION_WAIT_SECONDS", 0.05)
    events = []

    def slow_tool(n, args, session, bid, today):
        time.sleep(1.0)
        events.append("tool done")
        return '{"matched": 0}'
    monkeypatch.setattr(meeting_ledger, "run_tool", slow_tool)
    import sys as _sys
    up = _RealtimeLike()       # BM-5: the provider answers Aria's go-on, as OpenAI does
    client = meeting["make"]()

    async def connect(url, additional_headers=None, **k):
        return up
    monkeypatch.setattr(_sys.modules["websockets"], "connect", connect)
    up.inbox.extend([{"type": "response.function_call_arguments.done", "call_id": "k1",
                      "name": "search_transactions", "arguments": "{}"},
                     {"type": "conversation.item.input_audio_transcription.completed",
                      "transcript": "And put the course price up too."}])
    monkeypatch.setattr(orch, "save_spoken_turn",
                        lambda meeting_id, business_id, role, content, at, session:
                        events.append(("saved", content)))
    with client.websocket_connect("/v1/realtime/voice") as ws:
        assert _open(ws) == {"type": "ready"}
        time.sleep(0.2)
        assert ("saved", "And put the course price up too.") in events, "read and saved while the look-up runs"
        ws.send_json({"type": "flush"})
        assert _wait(lambda: len(up.accepted) == 1, timeout=5)
        up.finish(transcript="Nothing matched.")
        while True:
            event = ws.receive_json()
            if event.get("type") == "flushed":
                break
    assert event["ok"] is True and "tool done" in events
    assert events.index(("saved", "And put the course price up too.")) < events.index("tool done")


def test_flush_is_not_ok_while_a_look_up_is_still_running(meeting, monkeypatch):
    from services import meeting_ledger
    monkeypatch.setattr(realtime_voice, "FLUSH_TRANSCRIPTION_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(realtime_voice, "FLUSH_SAVE_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(meeting_ledger, "run_tool", lambda *a: time.sleep(2.0) or "{}")
    client = meeting["make"](script=[{"type": "response.function_call_arguments.done", "call_id": "k1",
                                      "name": "ledger_summary", "arguments": "{}"}])
    with client.websocket_connect("/v1/realtime/voice") as ws:
        assert _open(ws) == {"type": "ready"}
        time.sleep(0.1)
        ws.send_json({"type": "flush"})
        while True:
            event = ws.receive_json()
            if event.get("type") == "flushed":
                break
    assert event["ok"] is False


class _PushUpstream:
    """A fake OpenAI socket the test can push events into at any moment."""

    def __init__(self):
        self.sent, self.inbox, self.open = [], [], True

    async def send(self, data):
        self.sent.append(data)

    async def close(self):
        self.open = False

    def __aiter__(self):
        return self._events()

    async def _events(self):
        import asyncio as _asyncio
        while self.open:
            while self.inbox:
                yield json.dumps(self.inbox.pop(0))
            await _asyncio.sleep(0.02)


def test_a_look_up_that_starts_during_the_flush_is_not_missed(meeting, monkeypatch):
    """Codex BM-3 review 6: the look-up arrives during the flush's own waits."""
    import sys as _sys
    from services import meeting_ledger
    monkeypatch.setattr(realtime_voice, "FLUSH_TRANSCRIPTION_WAIT_SECONDS", 0.6)
    monkeypatch.setattr(meeting_ledger, "run_tool", lambda *a: time.sleep(3.0) or "{}")
    client = meeting["make"]()
    up = _PushUpstream()

    async def connect(url, additional_headers=None, **k):
        return up
    monkeypatch.setattr(_sys.modules["websockets"], "connect", connect)
    with client.websocket_connect("/v1/realtime/voice") as ws:
        assert _open(ws) == {"type": "ready"}
        ws.send_json({"type": "flush"})
        time.sleep(0.2)                 # flush is now in its transcription wait
        up.inbox.append({"type": "response.function_call_arguments.done", "call_id": "k9",
                         "name": "ledger_summary", "arguments": "{}"})
        while True:
            event = ws.receive_json()
            if event.get("type") == "flushed":
                break
    assert event["ok"] is False


# ---- BM-4: ordinary Aria voice knows the owner's notes ---------------------

def test_ordinary_aria_voice_includes_the_owner_s_notes(meeting, monkeypatch):
    from services import aria_memory
    monkeypatch.setattr(aria_memory, "confirmed", lambda session, bid: [
        {"about": "TPS", "meaning": "Main parts supplier", "group": "Parts", "status": "confirmed"}])
    client = meeting["make"]()
    with client.websocket_connect("/v1/realtime/voice") as ws:
        ws.send_json({"type": "auth", "token": "t"})
        assert ws.receive_json() == {"type": "ready"}
        config = json.loads(meeting["voice"]["connects"][0].sent[0])["session"]
    assert "TPS: Main parts supplier (group: Parts)" in config["instructions"]


def test_ordinary_aria_voice_still_starts_if_the_notes_cannot_be_read(meeting, monkeypatch):
    from services import aria_memory

    def broken(session, bid):
        raise RuntimeError("database unavailable")
    monkeypatch.setattr(aria_memory, "confirmed", broken)
    client = meeting["make"]()
    with client.websocket_connect("/v1/realtime/voice") as ws:
        ws.send_json({"type": "auth", "token": "t"})
        assert ws.receive_json() == {"type": "ready"}


# ---- BM-5: several look-ups in one reply (Mike's logs, 8 Nov 17:35) --------
# Aria asked for two `remember`s in one reply; each answer sent its own
# response.create while that reply was still running, OpenAI refused one
# ("conversation already has an active response") and the talk went silent.

import threading  # noqa: E402


class _RealtimeLike(_PushUpstream):
    """Behaves like OpenAI where BM-5 matters: one reply at a time. A
    response.create while a reply runs is refused with the request's
    event_id; otherwise a reply starts. The test ends replies itself."""

    def __init__(self):
        super().__init__()
        self.active, self.accepted, self.refused = False, [], []

    async def send(self, data):
        self.sent.append(data)
        e = json.loads(data)
        if e.get("type") == "response.create":
            if self.active:
                self.refused.append(e.get("event_id"))
                self.inbox.append({"type": "error", "error": {
                    "code": "conversation_already_has_active_response", "event_id": e.get("event_id")}})
            else:
                self.active = True
                self.accepted.append(e.get("event_id"))
                self.inbox.append({"type": "response.created", "response": {"id": f"r{len(self.accepted)}"}})

    def start(self, *calls):
        """A reply begins and asks for these look-ups (call_id, about)."""
        self.active = True
        self.inbox.append({"type": "response.created", "response": {"id": "r0"}})
        for call_id, about in calls:
            self.inbox.append({"type": "response.function_call_arguments.done", "call_id": call_id,
                               "name": "remember", "arguments": json.dumps({"about": about, "meaning": "m"})})

    def finish(self, status="completed", transcript=None):
        if transcript:
            self.inbox.append({"type": "response.output_audio_transcript.done", "transcript": transcript})
        self.active = False
        self.inbox.append({"type": "response.done", "response": {"status": status}})

    def owner_speaks(self):
        """Server VAD: the owner cuts in, the running reply is cancelled, and
        when they stop the provider starts its own reply to them."""
        self.inbox.append({"type": "input_audio_buffer.speech_started"})
        if self.active:
            self.finish("cancelled")
        self.inbox.append({"type": "input_audio_buffer.speech_stopped"})
        self.active = True
        self.inbox.append({"type": "response.created", "response": {"id": "vad"}})

    def answers(self):
        out = []
        for x in self.sent:
            e = json.loads(x)
            if e.get("type") == "conversation.item.create" and e["item"].get("type") == "function_call_output":
                out.append(e["item"]["call_id"])
        return out

    def drained(self):
        return not self.inbox


@pytest.fixture
def realtime(meeting, monkeypatch):
    """The meeting harness on a _RealtimeLike upstream, with look-ups that
    finish only when the test releases them."""
    import asyncio
    import sys as _sys
    from services import meeting_ledger
    up = _RealtimeLike()
    client = meeting["make"]()     # installs the fake websockets module first

    async def connect(url, additional_headers=None, **k):
        return up
    monkeypatch.setattr(_sys.modules["websockets"], "connect", connect)
    gates, broken = {}, set()

    def gate(about):
        return gates.setdefault(about, threading.Event())

    def held(n, args, session, bid, today):
        if args.get("about") in broken:
            raise RuntimeError("database unavailable")
        assert gate(args.get("about")).wait(10), "never released"
        return '{"ok": true}'
    monkeypatch.setattr(meeting_ledger, "run_tool", held)

    async def ordinary(name, args, user_id, business_id):
        await asyncio.to_thread(held, name, args, None, business_id, None)
        return '{"ok": true}'
    monkeypatch.setattr(realtime_voice, "execute_tool", ordinary)
    monkeypatch.setattr(realtime_voice, "CONTINUE_AFTER_SPEECH_SECONDS", 0.1)
    return {"up": up, "release": lambda *abouts: [gate(a).set() for a in abouts], "broken": broken,
            "client": client, "meeting": meeting}


def _connect(ws, spoken_meeting=True):
    if spoken_meeting:
        assert _open(ws) == {"type": "ready"}
    else:
        ws.send_json({"type": "auth", "token": "t"})
        assert ws.receive_json() == {"type": "ready"}


@pytest.mark.parametrize("spoken_meeting", [True, False])
def test_several_look_ups_in_one_reply_ask_aria_to_go_on_once(realtime, spoken_meeting):
    up = realtime["up"]
    with realtime["client"].websocket_connect("/v1/realtime/voice") as ws:
        _connect(ws, spoken_meeting)
        up.start(("k1", "A"), ("k2", "B"))
        realtime["release"]("A", "B")
        assert _wait(lambda: set(up.answers()) == {"k1", "k2"} and up.drained())
        assert up.accepted == [] and up.refused == [], "not while the reply that asked is running"
        up.finish()
        assert _wait(lambda: len(up.accepted) == 1)
        up.finish()
        time.sleep(0.2)
    assert len(up.accepted) == 1 and up.refused == []


def test_aria_goes_on_only_when_the_last_answer_is_in(realtime):
    up = realtime["up"]
    with realtime["client"].websocket_connect("/v1/realtime/voice") as ws:
        _connect(ws)
        up.start(("k1", "A"), ("k2", "B"))
        up.finish()
        realtime["release"]("A")
        assert _wait(lambda: up.answers() == ["k1"] and up.drained())
        assert up.accepted == [], "B is still being looked up"
        realtime["release"]("B")
        assert _wait(lambda: len(up.accepted) == 1)
    assert up.answers() == ["k1", "k2"] and up.refused == []


@pytest.mark.parametrize("spoken_meeting", [True, False])
def test_the_owner_cutting_in_during_the_look_ups_loses_nothing(realtime, spoken_meeting):
    """The owner talks over Aria while her look-ups run: the provider's own
    reply to them is never collided with, and Aria still goes on, once."""
    up = realtime["up"]
    with realtime["client"].websocket_connect("/v1/realtime/voice") as ws:
        _connect(ws, spoken_meeting)
        up.start(("k1", "A"), ("k2", "B"))
        assert _wait(lambda: up.drained())
        up.owner_speaks()                     # r0 cancelled, the provider's reply running
        realtime["release"]("A", "B")
        assert _wait(lambda: len(up.answers()) == 2 and up.drained())
        time.sleep(0.3)
        assert up.accepted == [] and up.refused == []
        up.finish()                           # the provider's reply to the owner ends
        assert _wait(lambda: len(up.accepted) == 1)
        up.finish()
        time.sleep(0.2)
    assert len(up.accepted) == 1 and up.refused == []


def test_a_refused_go_on_is_asked_again_after_the_other_reply(realtime):
    """A reply the server began that we had not yet heard about: our request
    is refused, the debt is kept, and Aria goes on after that reply."""
    up = realtime["up"]
    with realtime["client"].websocket_connect("/v1/realtime/voice") as ws:
        _connect(ws)
        up.start(("k1", "A"))
        up.finish()
        assert _wait(lambda: up.drained())
        up.active = True                      # running on the server, not yet announced
        realtime["release"]("A")
        assert _wait(lambda: len(up.refused) == 1 and up.drained())
        up.inbox.append({"type": "response.created", "response": {"id": "hidden"}})
        up.finish()
        assert _wait(lambda: len(up.accepted) == 1)
    assert up.refused[0].startswith(realtime_voice.CONTINUE_EVENT_PREFIX)


def test_a_look_up_that_breaks_is_still_answered(realtime):
    """An unanswered call leaves the model waiting for it for ever."""
    up = realtime["up"]
    realtime["broken"].add("A")
    with realtime["client"].websocket_connect("/v1/realtime/voice") as ws:
        _connect(ws)
        up.start(("k1", "A"))
        up.finish()
        assert _wait(lambda: up.answers() == ["k1"] and len(up.accepted) == 1)


def test_at_the_limit_aria_still_gives_the_answers_she_looked_up(realtime, monkeypatch):
    """Codex BM-5 review 1, finding 2: the allowance runs out after the reply
    that asked has ended but before the answers are in. The finishing grace
    covers the look-ups and her reply with them."""
    monkeypatch.setattr(realtime_voice, "MEETING_FINISH_GRACE_SECONDS", 5)
    monkeypatch.setattr(realtime_voice, "MIN_MEETING_SESSION_SECONDS", 0)
    realtime["meeting"]["allowed"] = 0.4
    up = realtime["up"]
    with realtime["client"].websocket_connect("/v1/realtime/voice") as ws:
        _connect(ws)
        up.start(("k1", "A"))
        up.finish()
        time.sleep(0.8)                       # past the limit, look-up still running
        assert up.open, "ended while Aria still owed an answer"
        realtime["release"]("A")
        assert _wait(lambda: len(up.accepted) == 1)
        time.sleep(0.3)
        assert up.open, "ended before her reply with the answers finished"
        up.finish(transcript="Here is what I found.")
        assert _wait(lambda: not up.open, timeout=5)


def test_flush_waits_for_aria_s_reply_with_the_answers(realtime, monkeypatch):
    """Codex BM-5 review 1, finding 3: the look-ups are done but the reply
    that asked has not ended; flush is ok only once her reply with the
    answers is over and saved."""
    monkeypatch.setattr(realtime_voice, "FLUSH_TRANSCRIPTION_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(realtime_voice, "FLUSH_SAVE_TIMEOUT_SECONDS", 3)
    up, saved = realtime["up"], realtime["meeting"]["saved"]
    with realtime["client"].websocket_connect("/v1/realtime/voice") as ws:
        _connect(ws)
        up.start(("k1", "A"))
        realtime["release"]("A")
        assert _wait(lambda: up.answers() == ["k1"] and up.drained())
        ws.send_json({"type": "flush"})
        time.sleep(0.2)
        up.finish()
        assert _wait(lambda: len(up.accepted) == 1)
        time.sleep(0.5)                       # her reply with the answers is still being spoken
        up.finish(transcript="Both are booked in.")
        while True:
            event = ws.receive_json()
            if event.get("type") == "flushed":
                saved_then = list(saved)
                break
    assert event["ok"] is True
    assert any(content == "Both are booked in." for _, _, content in saved_then), "flushed before it was saved"


def test_flush_is_not_ok_while_aria_still_owes_the_answers(realtime, monkeypatch):
    monkeypatch.setattr(realtime_voice, "FLUSH_TRANSCRIPTION_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(realtime_voice, "FLUSH_SAVE_TIMEOUT_SECONDS", 0.3)
    up = realtime["up"]
    with realtime["client"].websocket_connect("/v1/realtime/voice") as ws:
        _connect(ws)
        up.start(("k1", "A"))
        realtime["release"]("A")
        assert _wait(lambda: up.answers() == ["k1"] and up.drained())
        ws.send_json({"type": "flush"})       # the reply that asked never ends
        while True:
            event = ws.receive_json()
            if event.get("type") == "flushed":
                break
    assert event["ok"] is False


def test_a_failed_spoken_reply_is_told_to_the_owner_and_logged(meeting, monkeypatch, caplog):
    import logging
    import sys as _sys
    client = meeting["make"]()
    up = _PushUpstream()

    async def connect(url, additional_headers=None, **k):
        return up
    monkeypatch.setattr(_sys.modules["websockets"], "connect", connect)
    with caplog.at_level(logging.WARNING, logger="realtime_voice"):
        with client.websocket_connect("/v1/realtime/voice") as ws:
            assert _open(ws) == {"type": "ready"}
            up.inbox.extend([{"type": "response.created"},
                             {"type": "response.done", "response": {"status": "failed", "status_details": {
                                 "error": {"type": "rate_limit_exceeded"}}}},
                             {"type": "response.output_audio_transcript.done", "transcript": "after"}])
            while True:
                event = ws.receive_json()
                if event.get("type") in ("error", "response.output_audio_transcript.done"):
                    break
    assert event["type"] == "error" and "say that again" in event["message"]
    assert any("rate_limit_exceeded" in r.getMessage() for r in caplog.records)


def test_the_active_response_refusal_is_not_shown_as_an_error(meeting, monkeypatch):
    import sys as _sys
    client = meeting["make"]()
    up = _PushUpstream()

    async def connect(url, additional_headers=None, **k):
        return up
    monkeypatch.setattr(_sys.modules["websockets"], "connect", connect)
    with client.websocket_connect("/v1/realtime/voice") as ws:
        assert _open(ws) == {"type": "ready"}
        up.inbox.extend([{"type": "error", "error": {"code": "conversation_already_has_active_response"}},
                         {"type": "response.output_audio_transcript.done", "transcript": "Hello"}])
        while True:
            event = ws.receive_json()
            if event.get("type") in ("error", "response.output_audio_transcript.done"):
                break
    assert event["type"] == "response.output_audio_transcript.done"


def test_aria_still_goes_on_if_no_reply_follows_the_owner_s_words(realtime):
    """The owner makes a sound while the look-ups run, and the provider starts
    no reply to it: Aria is not left owing the answers for ever."""
    up = realtime["up"]
    with realtime["client"].websocket_connect("/v1/realtime/voice") as ws:
        _connect(ws)
        up.start(("k1", "A"))
        up.finish()
        up.inbox.append({"type": "input_audio_buffer.speech_started"})
        realtime["release"]("A")
        assert _wait(lambda: up.answers() == ["k1"] and up.drained())
        time.sleep(0.3)
        assert up.accepted == [], "not while the owner is talking"
        up.inbox.append({"type": "input_audio_buffer.speech_stopped"})
        assert _wait(lambda: len(up.accepted) == 1)


def test_ordinary_voice_keeps_talking_to_the_screen_while_a_look_up_runs(realtime):
    """In ordinary Aria voice the look-up no longer holds the stream: what
    arrives meanwhile still reaches the browser."""
    up = realtime["up"]
    with realtime["client"].websocket_connect("/v1/realtime/voice") as ws:
        _connect(ws, spoken_meeting=False)
        up.start(("k1", "A"))
        up.inbox.append({"type": "response.output_audio_transcript.done", "transcript": "One moment."})
        while True:
            event = ws.receive_json()
            if event.get("type") == "response.output_audio_transcript.done":
                break
        assert up.answers() == [], "seen while the look-up is still running"
        realtime["release"]("A")
