"""OUT-13 core — a never-contacted contact is erased from every outreach
record at its deadline (docs/OUT-13-CORE-TICKET.md, design approved by Codex
design review 4). RED: deletion of personal data.

UK GDPR Article 14: privacy information within a month of collection. The
first email carries it. A contact never emailed by `captured_at + 28 days` is
hidden at once and erased within the hour, from every outreach table. Aria's
chats and memory notes are the owner's own records and follow the request
flow (Mike, 10 Nov 2026); suppressions always survive.

What may have been sent is never erased: a claim whose transport may have
started, a message in `claimed`/`unknown`, or anything contacted. Each such
case is an owner-visible exception with its reason and age.
"""
from __future__ import annotations

import json
import logging
import re
import time as _time
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import text

from services import outreach_send as send

logger = logging.getLogger(__name__)

DEADLINE = timedelta(days=28)
GUARD_LIFE = timedelta(days=90)
CLAIM_ABANDONED_AFTER = timedelta(hours=1)
RECHECK_AFTER = timedelta(days=1)
PAGE = 100
PASS_SECONDS = 120.0
CANDIDATE_SECONDS = 30.0
RECHECKS_PER_PASS = 20
PRUNE_BATCH = 500

NEVER_SENT = ("draft", "proposed", "cancelled", "failed")
MAY_HAVE_SENT = ("claimed", "unknown")
CONTACTED = ("accepted", "imported")
REASONS = ("may_have_sent", "contacted", "cross_reference", "orphaned_card", "error")


def now() -> datetime:
    return send.now()


_ADDRESS = re.compile(r"[^\s@()<>,;:]+@[^\s@()<>,;:]+")
_DOMAIN = re.compile(r"\b(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}\b", re.I)


def scrub(value: str) -> str:
    """No address or domain in text that is kept (a research summary): they
    identify a contact, and the summary outlives an erasure (R5)."""
    return _DOMAIN.sub("[domain]", _ADDRESS.sub("[address]", str(value or "")))


def _ts(value) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace(" ", "T").replace("Z", "+00:00"))
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


# ------------------------------------------------------------ predicates ---

def deadline(p) -> datetime:
    """A first email no later than this; erasure at it. Never later than 28
    days from collection, whatever an older row's notice_due_at says (U3)."""
    by_capture = _ts(p["captured_at"]) + DEADLINE
    stored = _ts(p.get("notice_due_at") if hasattr(p, "get") else p["notice_due_at"])
    return min(by_capture, stored) if stored else by_capture


def _noticed(p) -> bool:
    value = p.get("notice_provided_at") if hasattr(p, "get") else p["notice_provided_at"]
    return bool(value)


def first_send_allowed(p, moment: datetime) -> bool:
    """Follow-ups (notice already given) are exempt; retention is checked
    separately by the send path."""
    return _noticed(p) or moment < deadline(p)


def hidden(p, moment: datetime) -> bool:
    """Withheld from every screen and tool from the deadline, whatever the
    state of erasure (R3)."""
    return not _noticed(p) and moment >= deadline(p)


PAST_DEADLINE = "This contact's first email is past its deadline"


def contacted_ids(session, bid: str, ids) -> set:
    """Of these prospects, those actually contacted (an accepted or imported
    message, or a reply), whatever their notice_provided_at: imported history
    may lack it. Only these stay visible after the deadline. A send that only
    MAY have happened (claimed, unknown) is protected from erasure by
    `assess`, but its contact is still withheld (Codex code review 1, 3)."""
    ids = sorted({str(i) for i in ids if i})
    if not ids:
        return set()
    clause, params = _in("prospect_id", ids, "q")
    found = set()
    for sql in (f"SELECT DISTINCT prospect_id FROM outreach_messages WHERE business_id = :b AND {clause} "
                f"AND state IN ('accepted', 'imported')",
                # A reply slot always has its reply (migration 038's foreign key).
                f"SELECT DISTINCT prospect_id FROM outreach_replies WHERE business_id = :b AND {clause}"):
        found.update(str(r[0]) for r in session.execute(text(sql), {"b": str(bid), **params}))
    return found


# ------------------------------------------------------------------ locks ---

def _lock(session, bid: str) -> None:
    """The documented order (business_settings, then outreach_settings),
    without creating either: erasure never provisions settings (T8)."""
    if not send.pg(session):
        return
    for table in ("business_settings", "outreach_settings"):
        session.execute(text(f"SELECT 1 FROM {table} WHERE business_id = :b FOR UPDATE"), {"b": bid})


def _limits(session, statement_seconds: int = 15) -> None:
    if send.pg(session):
        session.execute(text("SET LOCAL lock_timeout = '5s'"))
        session.execute(text(f"SET LOCAL statement_timeout = '{int(statement_seconds)}s'"))


class _Budget:
    def __init__(self, seconds: float):
        self.until = _time.monotonic() + seconds

    def check(self) -> None:
        if _time.monotonic() > self.until:
            raise TimeoutError("erasure candidate exceeded its time budget")


# ------------------------------------------------------- the deletion set ---

def _ids(rows) -> list:
    return [str(r[0]) for r in rows]


def _in(column: str, values: list, prefix: str) -> tuple:
    """`column IN (:p0, :p1, …)` and its parameters; FALSE when empty."""
    if not values:
        return "1 = 0", {}
    names = {f"{prefix}{i}": v for i, v in enumerate(values)}
    return f"{column} IN ({', '.join(':' + n for n in names)})", names


def assess(session, bid: str, prospect_id: str) -> dict:
    """Read, under the caller's lock, whether this prospect may be erased and
    exactly what erasing it removes. `reason` is None when it may."""
    p = session.execute(text("SELECT * FROM outreach_prospects WHERE business_id = :b AND id = :p"),
                        {"b": bid, "p": str(prospect_id)}).mappings().first()
    out = {"prospect": dict(p) if p else None, "reason": None, "messages": [], "jobs": [], "cards": [],
           "enrolments": []}
    if p is None:
        out["reason"] = "gone"
        return out
    if p["notice_provided_at"]:
        out["reason"] = "contacted"
        return out
    b = {"b": bid, "p": str(prospect_id)}
    for table in ("outreach_replies", "outreach_reply_slots"):
        if session.execute(text(f"SELECT 1 FROM {table} WHERE business_id = :b AND prospect_id = :p LIMIT 1"), b).first():
            out["reason"] = "contacted"
            return out
    messages = session.execute(text("SELECT id, state, action_id FROM outreach_messages "
                                    "WHERE business_id = :b AND prospect_id = :p"), b).mappings().all()
    states = {m["state"] for m in messages}
    if states & set(CONTACTED):
        out["reason"] = "contacted"
        return out
    if states & set(MAY_HAVE_SENT):
        out["reason"] = "may_have_sent"
        return out
    message_ids = [str(m["id"]) for m in messages]
    out["messages"] = message_ids
    clause, params = _in("message_id", message_ids, "m")
    jobs = session.execute(text(f"SELECT id, status, action_id, dispatch_started_at FROM outreach_dispatch_jobs "
                                f"WHERE business_id = :b AND {clause}"), {"b": bid, **params}).mappings().all()
    if any(j["dispatch_started_at"] and j["status"] not in ("failed", "cancelled") for j in jobs):
        out["reason"] = "may_have_sent"
        return out
    out["jobs"] = [str(j["id"]) for j in jobs]
    out["enrolments"] = _ids(session.execute(text(
        "SELECT id FROM outreach_enrolments WHERE business_id = :b AND prospect_id = :p"), b))
    cards = set()
    for e in out["enrolments"]:
        cards.update(_ids(session.execute(text(
            "SELECT id FROM aria_actions WHERE business_id = :b AND action_type IN ('send_outreach', 'reply_outreach') "
            "AND (payload->>'enrolment_id') = :e"), {"b": bid, "e": e})))
    cards.update(str(m["action_id"]) for m in messages if m["action_id"])
    cards.update(str(j["action_id"]) for j in jobs if j["action_id"])
    out["cards"] = sorted(cards)
    if out["cards"]:
        clause, params = _in("id", out["cards"], "c")
        statuses = {r[0] for r in session.execute(text(
            f"SELECT status FROM aria_actions WHERE business_id = :b AND {clause}"), {"b": bid, **params})}
        if "executing" in statuses:
            # An executing card with a claimed message was caught above; one
            # without any job or message is not ours to decide (T6).
            out["reason"] = "orphaned_card"
            return out
    # Anything outside this set that points into it blocks the erasure (T7).
    mine_m, mp = _in("retry_of", message_ids, "rm")
    mine_t, tp = _in("reply_target_id", message_ids, "tm")
    if message_ids and session.execute(text(
            f"SELECT 1 FROM outreach_messages WHERE business_id = :b AND prospect_id <> :p "
            f"AND ({mine_m} OR {mine_t}) LIMIT 1"), {**b, **mp, **tp}).first():
        out["reason"] = "cross_reference"
        return out
    if out["cards"]:
        cm, cp = _in("action_id", out["cards"], "ca")
        for sql in (f"SELECT 1 FROM outreach_messages WHERE business_id = :b AND prospect_id <> :p AND {cm} LIMIT 1",
                    f"SELECT 1 FROM outreach_reply_slots WHERE business_id = :b AND prospect_id <> :p AND {cm} LIMIT 1"):
            if session.execute(text(sql), {**b, **cp}).first():
                out["reason"] = "cross_reference"
                return out
        own, op = _in("message_id", message_ids, "om")
        if session.execute(text(
                f"SELECT 1 FROM outreach_dispatch_jobs WHERE business_id = :b AND {cm} AND NOT ({own}) LIMIT 1"),
                {"b": bid, **cp, **op}).first():
            out["reason"] = "cross_reference"
            return out
    return out


# --------------------------------------------------------------- erasure ---

def _guard(session, bid: str, p: dict, moment: datetime) -> None:
    """Tenant-keyed digests, never addresses: the same person is not
    re-collected for 90 days (Mike, 10 Nov 2026; R6)."""
    until = moment + GUARD_LIFE
    keys = []
    if p.get("email_key"):
        keys.append(("email", p["email_key"]))
    domain = (p.get("domain") or "").strip().lower()
    if domain:
        keys.append(("domain", send.suppression_digest(bid, "domain", domain)))
    for kind, digest in keys:
        found = session.execute(text("SELECT id, until FROM outreach_recently_erased WHERE business_id = :b "
                                     "AND key_type = :k AND key_digest = :d"),
                                {"b": bid, "k": kind, "d": digest}).first()
        if found is None:
            send.insert(session, "outreach_recently_erased", bid, key_type=kind, key_digest=digest,
                        digest_version=1, until=until)
        elif _ts(found[1]) < until:
            session.execute(text("UPDATE outreach_recently_erased SET until = :u, updated_at = :at "
                                 "WHERE business_id = :b AND id = :id"),
                            {"u": until, "at": moment, "b": bid, "id": str(found[0])})


def recently_erased(session, bid: str, email: Optional[str], domain: Optional[str], moment: datetime) -> bool:
    """Was this person, or their domain, erased in the past 90 days? Checked
    at verification and again under research's store lock (R6)."""
    keys = []
    if email:
        keys.append(("email", send.suppression_digest(bid, "email", email)))
    if domain and str(domain).strip():
        keys.append(("domain", send.suppression_digest(bid, "domain", str(domain).strip().lower())))
    for kind, digest in keys:
        if session.execute(text("SELECT 1 FROM outreach_recently_erased WHERE business_id = :b AND key_type = :k "
                                "AND key_digest = :d AND until > :now LIMIT 1"),
                           {"b": bid, "k": kind, "d": digest, "now": moment}).first():
            return True
    return False


def _forget_outcome(session, bid: str, prospect_id: str) -> None:
    from services import outreach_dashboard, outreach_setup
    doc = outreach_setup._settings_doc(session, bid)
    marks = doc.get(outreach_dashboard.OUTCOMES_KEY)
    if isinstance(marks, dict) and str(prospect_id) in marks:
        marks = dict(marks)
        marks.pop(str(prospect_id))
        doc[outreach_dashboard.OUTCOMES_KEY] = marks
        expr = "CAST(:s AS jsonb)" if send.pg(session) else ":s"
        session.execute(text(f"UPDATE business_settings SET settings = {expr} WHERE business_id = :b"),
                        {"s": json.dumps(doc), "b": bid})


def _note_exception(session, bid: str, prospect_id: str, reason: str, moment: datetime) -> None:
    found = session.execute(text("SELECT id FROM outreach_erasure_exceptions WHERE business_id = :b "
                                 "AND prospect_id = :p"), {"b": bid, "p": str(prospect_id)}).first()
    if found is None:
        send.insert(session, "outreach_erasure_exceptions", bid, prospect_id=str(prospect_id), reason=reason,
                    first_seen_at=moment, last_checked_at=moment)
    else:
        session.execute(text("UPDATE outreach_erasure_exceptions SET reason = :r, last_checked_at = :at, "
                             "updated_at = :at WHERE business_id = :b AND id = :id"),
                        {"r": reason, "at": moment, "b": bid, "id": str(found[0])})


def _repair_references(session, bid: str, prospect_id: str) -> None:
    """T6: another contact's message that points at this one's messages is
    unlinked only when it was itself never sent (draft, proposed, cancelled,
    failed). A sent one stays: it is evidence, and the erasure waits."""
    mine = _ids(session.execute(text("SELECT id FROM outreach_messages WHERE business_id = :b AND prospect_id = :p"),
                                {"b": bid, "p": prospect_id}))
    if not mine:
        return
    states = ", ".join(f"'{s}'" for s in NEVER_SENT)
    for column in ("retry_of", "reply_target_id"):
        clause, params = _in(column, mine, column[:2])
        session.execute(text(f"UPDATE outreach_messages SET {column} = NULL WHERE business_id = :b "
                             f"AND prospect_id <> :p AND state IN ({states}) AND {clause}"),
                        {"b": bid, "p": prospect_id, **params})


def erase_never_contacted(session, bid: str, prospect_id: str, moment: Optional[datetime] = None,
                          budget: Optional[_Budget] = None) -> dict:
    """Erase one never-contacted prospect past its deadline, in one
    transaction under the business lock, or record why not. Commits."""
    moment = moment or now()
    budget = budget or _Budget(CANDIDATE_SECONDS)
    bid, pid = str(bid), str(prospect_id)
    try:
        _limits(session)
        _lock(session, bid)
        _repair_references(session, bid, pid)
        found = assess(session, bid, pid)
        budget.check()
        p = found["prospect"]
        if found["reason"] == "gone":
            session.execute(text("DELETE FROM outreach_erasure_exceptions WHERE business_id = :b AND prospect_id = :p"),
                            {"b": bid, "p": pid})
            session.commit()
            return {"erased": False, "reason": "gone"}
        if found["reason"] is None and not hidden(p, moment):
            session.rollback()
            return {"erased": False, "reason": "not_due"}
        if found["reason"]:
            # 'contacted' is recorded too (not shown to the owner): imported
            # history can lack a notice date, and without this row it would be
            # selected again every pass (Codex code review 1, finding 1).
            _note_exception(session, bid, pid, found["reason"], moment)
            session.commit()
            return {"erased": False, "reason": found["reason"]}
        b = {"b": bid}
        messages, cards = found["messages"], found["cards"]
        # T7's order: nothing still points at a row when it is deleted.
        clause, params = _in("message_id", messages, "m")
        session.execute(text(f"DELETE FROM outreach_dispatch_jobs WHERE business_id = :b AND {clause}"), {**b, **params})
        session.execute(text(f"UPDATE outreach_usage_events SET message_id = NULL WHERE business_id = :b AND {clause}"),
                        {**b, **params})
        budget.check()
        clause, params = _in("id", messages, "i")
        session.execute(text(f"UPDATE outreach_messages SET retry_of = NULL, reply_target_id = NULL "
                             f"WHERE business_id = :b AND {clause}"), {**b, **params})
        session.execute(text(f"DELETE FROM outreach_messages WHERE business_id = :b AND {clause}"), {**b, **params})
        clause, params = _in("id", cards, "c")
        session.execute(text(f"DELETE FROM aria_actions WHERE business_id = :b AND {clause}"), {**b, **params})
        budget.check()
        if p.get("email_key"):
            session.execute(text("DELETE FROM outreach_unsubscribe_tokens WHERE business_id = :b "
                                 "AND prospect_key_digest = :k"), {**b, "k": p["email_key"]})
        for table in ("outreach_enrolments", "outreach_evidence"):
            session.execute(text(f"DELETE FROM {table} WHERE business_id = :b AND prospect_id = :p"), {**b, "p": pid})
        session.execute(text("DELETE FROM outreach_prospects WHERE business_id = :b AND id = :p"), {**b, "p": pid})
        session.execute(text("DELETE FROM outreach_erasure_exceptions WHERE business_id = :b AND prospect_id = :p"),
                        {**b, "p": pid})
        _forget_outcome(session, bid, pid)
        _guard(session, bid, p, moment)
        budget.check()
        session.commit()
        return {"erased": True, "reason": None}
    except Exception as exc:
        session.rollback()
        logger.warning("Erasure of a contact for business %s failed (%s); retried tomorrow", bid, type(exc).__name__)
        try:
            _limits(session)        # SET LOCAL ended with the rollback
            _lock(session, bid)
            _note_exception(session, bid, pid, "error", moment)
            session.commit()
        except Exception:
            session.rollback()
        return {"erased": False, "reason": "error"}


# --------------------------------------------------- abandoned first sends ---

def reconcile_abandoned_claims(session, moment: Optional[datetime] = None, limit: int = 50,
                               stop: Optional[float] = None) -> int:
    """T3/U2: a sequence email's claim that never began sending (its job
    `claimed`, no dispatch marker, over an hour old) is fenced with the
    dispatcher's own compare-and-set, then settled as not sent, in one
    transaction. A dispatcher that resumes loses the compare-and-set and
    raises before transport. Replies are left to their own safeguards."""
    from types import SimpleNamespace
    moment = moment or now()
    _limits(session, 10)
    rows = session.execute(text(
        "SELECT j.business_id, j.id, j.action_id FROM outreach_dispatch_jobs j JOIN aria_actions a "
        "ON a.business_id = j.business_id AND a.id = j.action_id WHERE j.status = 'claimed' "
        "AND j.dispatch_started_at IS NULL AND j.created_at < :old AND a.action_type = 'send_outreach' "
        "ORDER BY j.created_at LIMIT :n"), {"old": moment - CLAIM_ABANDONED_AFTER, "n": limit}).fetchall()
    session.rollback()
    settled = 0
    for bid, job_id, action_id in rows:
        if stop is not None and _time.monotonic() >= stop:
            break
        bid = str(bid)
        try:
            business = SimpleNamespace(id=bid)        # settlement uses only the id
            _limits(session)
            send.lock_business(session, bid)
            fenced = session.execute(text(
                "UPDATE outreach_dispatch_jobs SET dispatch_started_at = :at WHERE business_id = :b AND id = :id "
                "AND status = 'claimed' AND dispatch_started_at IS NULL"), {"at": moment, "b": bid, "id": str(job_id)})
            if fenced.rowcount != 1:
                session.rollback()          # the dispatcher won: it is sending, or has
                continue
            job = send.one(session, "outreach_dispatch_jobs", bid, str(job_id))
            card = send.one(session, "aria_actions", bid, str(action_id))
            payload = send.loads(card["payload"])
            evidence = {"outcome": "definitely_not_accepted", "provider": payload.get("provider"),
                        "mailbox_id": payload.get("mailbox_id"), "reason": "Interrupted before sending started"}
            result = {"status": "failed", "outcome": "definitely_not_accepted",
                      "error": "Sending was interrupted before it started"}
            send._settle(session, business, str(action_id), payload, job, evidence, result)
            session.commit()
            settled += 1
        except Exception as exc:
            session.rollback()
            logger.warning("Could not settle an interrupted claim for business %s (%s)", bid, type(exc).__name__)
    return settled


# ------------------------------------------------------------ the schedule ---

def _prune(session, moment: datetime) -> None:
    """Bounded batches, for every business, idle ones included (R6)."""
    for sql in ("DELETE FROM outreach_recently_erased WHERE id IN (SELECT id FROM outreach_recently_erased "
                "WHERE until <= :now LIMIT :n)",
                "DELETE FROM outreach_erasure_exceptions WHERE id IN (SELECT x.id FROM outreach_erasure_exceptions x "
                "WHERE NOT EXISTS (SELECT 1 FROM outreach_prospects p WHERE p.business_id = x.business_id "
                "AND p.id = x.prospect_id) LIMIT :n)"):
        try:
            _limits(session, 30)
            session.execute(text(sql), {"now": moment, "n": PRUNE_BATCH})
            session.commit()
        except Exception as exc:
            session.rollback()
            logger.warning("Erasure pruning failed (%s)", type(exc).__name__)


LEGACY_REASON = "no mail server for "


def _scrub_summaries(session, stop: Optional[float] = None, limit: int = 50) -> None:
    """Research summaries stored before OUT-13 core could name a domain
    ("no mail server for …"); each is cleaned once, under the settings lock.
    Only rows that can need it are read, and at most `limit` per pass."""
    from services import outreach_research, outreach_setup
    _limits(session, 10)
    # The only identifying text a summary can hold is "no mail server for
    # <domain>" (outreach_research._verify). Only documents still holding it
    # unscrubbed are selected, so each one cleaned drops out and every one is
    # reached in turn (Codex code review 2, finding 1).
    rows = session.execute(text(
        "SELECT business_id, settings FROM business_settings WHERE CAST(settings AS TEXT) LIKE :legacy "
        "AND CAST(settings AS TEXT) NOT LIKE :clean ORDER BY business_id LIMIT :n"),
        {"legacy": f"%{LEGACY_REASON}%", "clean": f"%{LEGACY_REASON}[domain]%", "n": limit}).fetchall()
    session.rollback()
    done = 0
    for bid, raw in rows:
        if done >= limit or (stop is not None and _time.monotonic() >= stop):
            break
        cfg = (send.loads(raw) or {}).get(outreach_research.KEY) or {}
        summary = cfg.get("summary") if isinstance(cfg, dict) else None
        if not isinstance(summary, str) or scrub(summary) == summary:
            continue
        try:
            _limits(session)
            _lock(session, str(bid))
            doc = outreach_setup._settings_doc(session, str(bid))
            fresh = dict(doc.get(outreach_research.KEY) or {})
            fresh["summary"] = scrub(fresh.get("summary") or "")
            doc[outreach_research.KEY] = fresh
            expr = "CAST(:s AS jsonb)" if send.pg(session) else ":s"
            session.execute(text(f"UPDATE business_settings SET settings = {expr} WHERE business_id = :b"),
                            {"s": json.dumps(doc), "b": str(bid)})
            session.commit()
            done += 1
        except Exception as exc:
            session.rollback()
            logger.warning("Could not clean a stored research summary (%s)", type(exc).__name__)


def _new_candidates(session, moment: datetime, after: Optional[tuple]) -> list:
    """Past the deadline, never noticed, and not already an exception (U1)."""
    keyset = "AND (p.captured_at, p.business_id, p.id) > (:c, :b, :i) " if after else ""
    _limits(session, 10)
    rows = session.execute(text(
        "SELECT p.captured_at, p.business_id, p.id FROM outreach_prospects p WHERE p.notice_provided_at IS NULL "
        "AND (p.captured_at <= :cut OR p.notice_due_at <= :now) AND NOT EXISTS (SELECT 1 FROM "
        "outreach_erasure_exceptions x WHERE x.business_id = p.business_id AND x.prospect_id = p.id) "
        + keyset + "ORDER BY p.captured_at, p.business_id, p.id LIMIT :n"),
        {"cut": moment - DEADLINE, "now": moment, "n": PAGE,
         **({"c": after[0], "b": after[1], "i": after[2]} if after else {})}).fetchall()
    session.rollback()
    return [tuple(r) for r in rows]


HOUSEKEEPING_SECONDS = 30.0


def run_due(session, moment: Optional[datetime] = None, *, pass_seconds: float = PASS_SECONDS,
            housekeeping_seconds: float = HOUSEKEEPING_SECONDS) -> dict:
    """Every hourly pass, every day, every business, before anything that
    calls a provider (R4). Housekeeping has its own bounded budget; then new
    candidates have the main budget, starting after it; exceptions are
    re-checked under their own small one. None can starve another (U1;
    Codex code review 1, finding 2)."""
    moment = moment or now()
    out = {"erased": 0, "exceptions": {}, "rechecked": 0, "claims_settled": 0}
    tidy_until = _time.monotonic() + housekeeping_seconds
    _prune(session, moment)
    if _time.monotonic() < tidy_until:
        out["claims_settled"] = reconcile_abandoned_claims(session, moment, stop=tidy_until)
    if _time.monotonic() < tidy_until:
        _scrub_summaries(session, stop=tidy_until)
    stop = _time.monotonic() + pass_seconds          # the candidates' own budget starts now
    after = None
    while _time.monotonic() < stop:
        page = _new_candidates(session, moment, after)
        if not page:
            break
        for captured, bid, pid in page:
            if _time.monotonic() >= stop:
                break
            done = erase_never_contacted(session, str(bid), str(pid), moment)
            if done["erased"]:
                out["erased"] += 1
            elif done["reason"] in REASONS:
                out["exceptions"][done["reason"]] = out["exceptions"].get(done["reason"], 0) + 1
            after = (captured, bid, pid)
    _limits(session, 10)
    due = session.execute(text(
        "SELECT business_id, prospect_id FROM outreach_erasure_exceptions WHERE last_checked_at <= :old "
        "ORDER BY last_checked_at LIMIT :n"), {"old": moment - RECHECK_AFTER, "n": RECHECKS_PER_PASS}).fetchall()
    session.rollback()
    for bid, pid in due:
        erase_never_contacted(session, str(bid), str(pid), moment)
        out["rechecked"] += 1
    # The oldest effective deadline (as `deadline`: the earlier of notice due
    # and capture + 28 days), Codex code review 1, finding 6.
    _limits(session, 10)
    captured, noticed = session.execute(text(
        "SELECT min(p.captured_at), min(CASE WHEN p.notice_due_at <= :now THEN p.notice_due_at END) "
        "FROM outreach_prospects p WHERE p.notice_provided_at IS NULL "
        "AND (p.captured_at <= :cut OR p.notice_due_at <= :now) AND NOT EXISTS (SELECT 1 FROM "
        "outreach_erasure_exceptions x WHERE x.business_id = p.business_id AND x.prospect_id = p.id)"),
        {"cut": moment - DEADLINE, "now": moment}).one()
    session.rollback()
    deadlines = [d for d in ((_ts(captured) + DEADLINE) if captured else None, _ts(noticed)) if d]
    out["oldest_overdue_hours"] = round((moment - min(deadlines)).total_seconds() / 3600, 1) if deadlines else 0
    level = logging.WARNING if out["oldest_overdue_hours"] > 3 else logging.INFO
    logger.log(level, "[Erasure] erased=%d exceptions=%s rechecked=%d claims_settled=%d oldest_overdue_hours=%s",
               out["erased"], out["exceptions"], out["rechecked"], out["claims_settled"], out["oldest_overdue_hours"])
    return out


OWNER_REASONS = ("may_have_sent", "cross_reference", "orphaned_card", "error")   # 'contacted' is not a problem


def exceptions_for(session, bid: str) -> list:
    """The owner's list (T6): reason and age, never the person's details."""
    rows = session.execute(text("SELECT prospect_id, reason, first_seen_at FROM outreach_erasure_exceptions "
                                "WHERE business_id = :b AND reason <> 'contacted' ORDER BY first_seen_at"),
                           {"b": str(bid)}).fetchall()
    return [{"prospect_id": str(r[0]), "reason": r[1], "since": _ts(r[2]).isoformat()} for r in rows]


ESCALATE_AFTER = {"error": timedelta(days=3), "may_have_sent": timedelta(days=7),
                  "cross_reference": timedelta(days=7), "orphaned_card": timedelta(days=3)}


def escalations(conn, bid: str, moment: Optional[datetime] = None) -> dict:
    """T6: held erasures old enough to put in front of the owner on the Aria
    home, by reason. Counts only (Codex code review 1, finding 7)."""
    moment = moment or now()
    out = {}
    for reason, first_seen in conn.execute(text(
            "SELECT reason, first_seen_at FROM outreach_erasure_exceptions WHERE business_id = :b "
            "AND reason <> 'contacted'"), {"b": str(bid)}):
        after = ESCALATE_AFTER.get(reason)
        seen = _ts(first_seen)
        if after and seen and moment - seen >= after:
            out[reason] = out.get(reason, 0) + 1
    return out
