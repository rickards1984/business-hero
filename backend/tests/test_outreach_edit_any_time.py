"""OUT-28a — edit an outreach email at any time without stranding anyone.

Mike, 18 Nov 2026: editing emails "at any time" is essential, to improve them
after watching how they do. Before this, editing a campaign's emails made a
new sequence version, but every enrolment stayed pinned to the old one and
the send path requires enrolment == campaign == step version: everyone part
way through the campaign silently stopped getting emails.

Decided by Mike (18 Nov 2026):
  E1. People already in the campaign get the NEW wording from their next
      email. Emails already sent are never changed.
  E2. "Save and use from now on" is one tap: saving IS approving the wording
      the owner has just written. Placeholders are still refused.
  E3. If Aria was sending the campaign automatically under this owner's
      permission, she carries on with the new wording.
"""
# ruff: noqa: F811 - pytest fixtures imported from the harness are parameters by design
import hashlib
import json
import uuid

import pytest
from sqlalchemy import text

import test_outreach_send as sendh
from test_outreach_send import A, BOX, CAMPAIGN, ENROLMENT, OWNER, PROSPECT, STAFF, STAMP, STEP, add, database, h  # noqa: F401

OLD = [("Synthetic offer", "A relevant synthetic offer."), ("Following up", "A short follow-up."),
       ("Last note", "A last, short note.")]
NEW = [("A better offer", "A clearer, better offer."), ("Quick follow-up", "A clearer follow-up."),
       ("One last note", "A clearer last note.")]


def manage():
    from services import outreach_manage
    return outreach_manage


def _envelope(subject, body):
    return json.dumps({"schema_version": 1, "subject": subject, "body": body})


@pytest.fixture
def three(h):
    """The harness campaign with all three emails at version 1."""
    for ordinal, delay in ((1, 5), (2, 7)):
        env = _envelope(*OLD[ordinal])
        add(h.s, "sequence_steps", id=sendh.uid(f"step{ordinal}"), campaign_id=CAMPAIGN, sequence_version=1,
            ordinal=ordinal, delay_business_days=delay, template_text=env,
            template_hash=hashlib.sha256(env.encode()).hexdigest(), allowed_variables="[]",
            approved_by=OWNER, approved_at=STAMP)
    h.s.commit()
    return h


def campaign_row(h):
    return h.s.execute(text("SELECT version, sequence_version, status FROM outreach_campaigns WHERE id = :c"),
                       {"c": CAMPAIGN}).mappings().one()


def save(h, emails=NEW, user=OWNER, version=None):
    version = campaign_row(h)["version"] if version is None else version
    out = manage().save_emails(h.s, h.b, user, CAMPAIGN, {
        "version": int(version), "emails": [{"ordinal": i, "subject": s, "body": b} for i, (s, b) in enumerate(emails)]})
    h.s.rollback()
    return out


def enrolment(h, ident=ENROLMENT):
    return h.s.execute(text("SELECT sequence_version, next_step, state, next_due_at FROM outreach_enrolments "
                            "WHERE id = :e"), {"e": ident}).mappings().one()


def current_steps(h):
    c = campaign_row(h)
    return h.s.execute(text("SELECT id, ordinal, delay_business_days, template_text, approved_by, approved_at "
                            "FROM outreach_sequence_steps WHERE campaign_id = :c AND sequence_version = :v "
                            "ORDER BY ordinal"), {"c": CAMPAIGN, "v": c["sequence_version"]}).mappings().all()


def refused(h, status, **kwargs):
    from services.aria_actions import ActionRefused
    before = (dict(campaign_row(h)), dict(enrolment(h)),
              h.s.execute(text("SELECT count(*) FROM outreach_sequence_steps")).scalar())
    h.s.rollback()
    with pytest.raises(ActionRefused) as exc:
        save(h, **kwargs)
    h.s.rollback()
    assert exc.value.status_code == status, exc.value.detail
    after = (dict(campaign_row(h)), dict(enrolment(h)),
             h.s.execute(text("SELECT count(*) FROM outreach_sequence_steps")).scalar())
    assert after == before, "a refused save changed something"
    return exc.value.detail


# ------------------------------------------------------- E2: save = approve ---

def test_saving_approves_the_new_wording_in_one_step(three):
    h = three
    out = save(h)
    c = campaign_row(h)
    assert c["status"] == "ready" and c["sequence_version"] == 2 and out["sequence_version"] == 2
    steps = current_steps(h)
    assert [json.loads(s["template_text"])["subject"] for s in steps] == [s for s, _ in NEW]
    assert all(str(s["approved_by"]) == OWNER and s["approved_at"] for s in steps)


def test_the_gaps_between_emails_are_kept(three):
    save(three)
    assert [int(s["delay_business_days"]) for s in current_steps(three)] == [0, 5, 7]


@pytest.mark.parametrize("which", [0, 1, 2])
def test_a_placeholder_is_still_refused_and_nothing_changes(three, which):
    emails = list(NEW)
    emails[which] = (emails[which][0], "Hello,\n\nThanks,\n[Your Name]")
    detail = refused(three, 422, emails=emails)
    assert "[Your Name]" in detail


def test_an_out_of_date_page_is_refused_and_nothing_changes(three):
    refused(three, 409, version=campaign_row(three)["version"] - 1 if campaign_row(three)["version"] > 1 else 99)


def test_staff_cannot_save_and_nothing_changes(three):
    refused(three, 403, user=STAFF)


@pytest.mark.parametrize("emails", [NEW[:2], NEW + NEW[:1]])
def test_exactly_three_emails_are_needed(three, emails):
    refused(three, 422, emails=emails)


@pytest.mark.parametrize("subject,body", [("", "A body."), ("A subject", ""), ("   ", "A body.")])
def test_an_empty_subject_or_message_is_refused(three, subject, body):
    refused(three, 422, emails=[(subject, body)] + NEW[1:])


# --------------------------------------- E1: nobody is stranded by an edit ---

def test_people_part_way_through_move_to_the_new_wording(three):
    h = three
    h.s.execute(text("UPDATE outreach_enrolments SET next_step = 1 WHERE id = :e"), {"e": ENROLMENT})
    h.s.commit()
    before = enrolment(h)
    save(h)
    after = enrolment(h)
    assert after["sequence_version"] == 2
    assert after["next_step"] == 1 and after["state"] == "active" and after["next_due_at"] == before["next_due_at"]


def test_the_next_email_is_sent_with_the_new_wording(three):
    """The regression: before OUT-28a this enrolment could never be sent again."""
    h = three
    save(h)
    step = current_steps(h)[0]
    card = sendh.propose(h, step_id=str(step["id"]))
    sendh.approve(h, card)
    assert len(h.p.sends) == 1
    sent = h.p.sends[0][1]
    assert sent["subject"] == "A better offer" and "A clearer, better offer." in sent["body_text"]


def test_a_waiting_card_with_the_old_wording_is_withdrawn(three):
    h = three
    card = sendh.propose(h)
    save(h)
    status = h.s.execute(text("SELECT status FROM aria_actions WHERE id = :a"), {"a": card["id"]}).scalar()
    assert status == "dismissed"
    with pytest.raises(h.a.ActionRefused):           # it can never be sent
        sendh.approve(h, card)
    assert not h.p.sends


def test_a_new_card_can_be_made_straight_after(three):
    h = three
    sendh.propose(h)
    save(h)
    card = sendh.propose(h, step_id=str(current_steps(h)[0]["id"]))     # OUT-24 allows one open card again
    assert card["preview"]["subject"] == "A better offer"


def test_an_email_being_sent_right_now_blocks_the_save(three):
    h = three
    card = sendh.propose(h)
    sendh.claimed_only(h, card)
    detail = refused(h, 409)
    assert "sending" in detail.lower()


@pytest.mark.parametrize("state", ["replied", "paused", "stopped", "completed", "suppressed"])
def test_stopped_and_finished_people_are_left_alone(three, state):
    h = three
    h.s.execute(text("UPDATE outreach_enrolments SET state = :s WHERE id = :e"), {"s": state, "e": ENROLMENT})
    h.s.commit()
    save(h)
    assert enrolment(h)["sequence_version"] == 1 and enrolment(h)["state"] == state


def test_other_campaigns_and_businesses_are_untouched(three):
    h = three
    other = str(uuid.uuid4())
    add(h.s, "campaigns", id=other, brand_id=sendh.BRAND, mailbox_id=BOX, name="Other", target_rules="{}",
        target_hash="audience-v1", sequence_version=1, version=1, status="ready", timezone="Europe/London", daily_cap=5)
    mine = str(uuid.uuid4())
    add(h.s, "enrolments", id=mine, prospect_id=str(uuid.uuid4()), campaign_id=other, sequence_version=1,
        state="active", next_step=0, next_due_at=STAMP)
    h.s.commit()
    save(h)
    assert enrolment(h, mine)["sequence_version"] == 1
    assert enrolment(h, sendh.uid("foreign-enrolment"))["sequence_version"] == 1


def test_emails_already_sent_never_change(three):
    h = three
    card = sendh.propose(h)
    sendh.approve(h, card)
    sent = h.s.execute(text("SELECT subject, body, sequence_version FROM outreach_messages")).mappings().all()
    save(h)
    assert h.s.execute(text("SELECT subject, body, sequence_version FROM outreach_messages")).mappings().all() == sent


# ------------------------------------------- E3: automatic sending carries on ---

def _grant(h, granted_by=OWNER):
    from services import outreach_autopilot, outreach_setup
    c = campaign_row(h)
    doc = outreach_setup._settings_doc(h.s, A)
    doc[outreach_autopilot.KEY] = {CAMPAIGN: {"granted_by": granted_by, "granted_at": STAMP,
                                              "campaign_version": int(c["version"]),
                                              "sequence_version": int(c["sequence_version"]), "mailbox_id": BOX}}
    outreach_setup._save_settings_doc(h.s, A, doc)
    h.s.commit()


def test_automatic_sending_carries_on_with_the_new_wording(three):
    from services import outreach_autopilot
    h = three
    _grant(h)
    assert outreach_autopilot.valid_grant(h.s, h.b, CAMPAIGN)[0]
    h.s.rollback()
    out = save(h)
    held, why = outreach_autopilot.valid_grant(h.s, h.b, CAMPAIGN)
    assert held, why
    assert held["sequence_version"] == 2 and held["granted_by"] == OWNER and out["automatic"] == "on"


@pytest.mark.parametrize("stale", ["campaign_version", "sequence_version", "mailbox_id"])
def test_a_permission_that_had_already_lapsed_stays_lapsed(three, stale):
    """Codex OUT-28 review 1, finding 1: a daily-limit or sender change had
    already switched automatic sending off; saving wording must not revive it."""
    from services import outreach_autopilot, outreach_setup
    h = three
    _grant(h)
    doc = outreach_setup._settings_doc(h.s, A)
    grant = doc[outreach_autopilot.KEY][CAMPAIGN]
    grant[stale] = str(uuid.uuid4()) if stale == "mailbox_id" else int(grant[stale]) - 1 if int(grant[stale]) > 1 else 99
    outreach_setup._save_settings_doc(h.s, A, doc)
    h.s.commit()
    assert outreach_autopilot.valid_grant(h.s, h.b, CAMPAIGN)[0] is None
    h.s.rollback()
    out = save(h)
    assert outreach_autopilot.valid_grant(h.s, h.b, CAMPAIGN)[0] is None and out["automatic"] == "off"


def test_another_owners_permission_is_not_carried(three):
    """Only the owner saving can vouch for the new wording."""
    from services import outreach_autopilot
    h = three
    _grant(h, granted_by=sendh.uid("former-owner"))
    out = save(h)
    held, _ = outreach_autopilot.valid_grant(h.s, h.b, CAMPAIGN)
    assert held is None and out["automatic"] == "off"


def test_without_a_permission_nothing_is_switched_on(three):
    from services import outreach_autopilot
    out = save(three)
    assert outreach_autopilot.valid_grant(three.s, three.b, CAMPAIGN)[0] is None and out["automatic"] is None


# --------------------------------------------------- what the owner sees ---

def test_the_emails_are_shown_in_plain_words(three):
    view = manage().emails(three.s, three.b, CAMPAIGN)
    assert [e["subject"] for e in view["emails"]] == [s for s, _ in OLD]
    assert [e["body"] for e in view["emails"]] == [b for _, b in OLD]
    assert [e["delay_business_days"] for e in view["emails"]] == [0, 5, 7]
    assert all(e["placeholder"] is None for e in view["emails"])
    assert view["version"] == campaign_row(three)["version"] and view["status"] == "ready"


def test_a_placeholder_is_pointed_out(three):
    env = _envelope("Synthetic offer", "Thanks,\n[Your Name]")
    three.s.execute(text("UPDATE outreach_sequence_steps SET template_text = :t, template_hash = :x WHERE id = :i"),
                    {"t": env, "x": hashlib.sha256(env.encode()).hexdigest(), "i": STEP})
    three.s.commit()
    view = manage().emails(three.s, three.b, CAMPAIGN)
    assert view["emails"][0]["placeholder"] == "[Your Name]" and view["emails"][1]["placeholder"] is None


def _sent(h, version, ordinal, *, reply=None):
    prospect = str(uuid.uuid4())
    step = h.s.execute(text("SELECT id FROM outreach_sequence_steps WHERE campaign_id = :c AND sequence_version = :v "
                            "AND ordinal = :o"), {"c": CAMPAIGN, "v": version, "o": ordinal}).scalar()
    message = add(h.s, "messages", campaign_id=CAMPAIGN, prospect_id=prospect, enrolment_id=str(uuid.uuid4()),
                  step_id=str(step), sequence_version=version, mailbox_id=BOX, kind="followup" if ordinal else "initial",
                  origin="live",
                  direction="outbound", state="accepted", accepted_at=STAMP, subject="s", body="b")
    if reply:
        add(h.s, "replies", prospect_id=prospect, mailbox_id=BOX, matched_message_id=message, category=reply,
            confidence=95, resolution="pending", received_at=STAMP, owner_id=OWNER, classification_version=1)
    h.s.commit()


def test_each_email_shows_how_it_did_for_each_wording(three):
    h = three
    for reply in (None, None, "interested", "not_now"):
        _sent(h, 1, 0, reply=reply)
    _sent(h, 1, 1)
    save(h)
    for reply in (None, "interested"):
        _sent(h, 2, 0, reply=reply)
    first = manage().emails(h.s, h.b, CAMPAIGN)["emails"][0]
    assert first["results"][0] == {"wording": 2, "current": True, "sent": 2, "replied": 1, "interested": 1,
                                   "since": first["results"][0]["since"]}
    assert first["results"][1] == {"wording": 1, "current": False, "sent": 4, "replied": 2, "interested": 1,
                                   "since": first["results"][1]["since"]}
    second = manage().emails(h.s, h.b, CAMPAIGN)["emails"][1]
    assert [(r["wording"], r["sent"], r["replied"]) for r in second["results"]] == [(1, 1, 0)]


@pytest.mark.parametrize("state,accepted", [("failed", None), ("unknown", None), ("claimed", None),
                                            ("failed", STAMP), ("unknown", STAMP)])
def test_unsent_and_failed_emails_are_not_counted(three, state, accepted):
    """Only an email the provider accepted counts as sent, whatever else is set."""
    h = three
    _sent(h, 1, 0)
    h.s.execute(text("UPDATE outreach_messages SET state = :s, accepted_at = :a"), {"s": state, "a": accepted})
    h.s.commit()
    assert manage().emails(h.s, h.b, CAMPAIGN)["emails"][0]["results"] == []


def test_aria_s_answers_to_replies_never_count_as_sends_of_an_email(three):
    """Codex OUT-28 review 1, finding 4: a bespoke reply is stored against the
    first step; it is not a send of that email's wording."""
    h = three
    _sent(h, 1, 0, reply="question")
    h.s.execute(text("UPDATE outreach_messages SET kind = 'bespoke'"))
    _sent(h, 1, 0)
    first = manage().emails(h.s, h.b, CAMPAIGN)["emails"][0]
    assert [(r["sent"], r["replied"]) for r in first["results"]] == [(1, 0)]


def test_another_businesss_campaign_is_not_found(three):
    from services.aria_actions import ActionRefused
    with pytest.raises(ActionRefused) as exc:
        manage().emails(three.s, three.b, sendh.uid("foreign-campaign"))
    assert exc.value.status_code == 404


# --------------------------------------------------------------- the API ---

def _body(**changes):
    body = {"version": 1, "emails": [{"ordinal": i, "subject": s, "body": b} for i, (s, b) in enumerate(NEW)]}
    body.update(changes)
    return body


@pytest.mark.parametrize("change", [
    {"emails": [{"ordinal": 0, "subject": "Hi {first name}", "body": "b"}] + _body()["emails"][1:]},
    {"emails": [{"ordinal": 0, "subject": "two\nlines", "body": "b"}] + _body()["emails"][1:]},
    {"emails": _body()["emails"][:2]},
    {"emails": [dict(e, ordinal=0) for e in _body()["emails"]]},
    {"version": 0},
    {"extra": True},
])
def test_the_api_refuses_a_malformed_save(change):
    from pydantic import ValidationError
    import outreach_manage as api
    with pytest.raises(ValidationError):
        api.SaveEmails(**_body(**change))


def test_saving_answers_first_and_makes_the_cards_just_after(monkeypatch):
    """Mike, 20 Nov 2026: the save took 30 seconds waiting for the cards."""
    from contextlib import contextmanager
    from fastapi import BackgroundTasks
    import outreach_manage as api
    calls = []
    monkeypatch.setattr(api.auth, "_load_business", lambda session, bid: f"business-{bid}")
    monkeypatch.setattr(api, "execute", lambda fn, session, context, body, ident: calls.append(("save", fn)) or {"ok": 1})

    @contextmanager
    def own_session():
        calls.append(("own session",))
        yield "background-session"
    monkeypatch.setattr(api, "get_session_context", own_session)
    from services import outreach_research
    monkeypatch.setattr(outreach_research, "prepare_due_cards",
                        lambda session, business: calls.append(("prepare", session, business)))
    tasks = BackgroundTasks()
    out = api.save_campaign_emails(uuid.uuid4(), api.SaveEmails(**_body()), tasks,
                                   context={"business_id": A, "user_id": OWNER}, session="request-session")
    assert out == {"ok": 1}
    assert calls == [("save", api.manage.save_emails)]            # answered before any card is made
    import asyncio
    asyncio.run(tasks())
    assert calls[1:] == [("own session",), ("prepare", "background-session", f"business-{A}")]


def test_a_card_problem_never_undoes_the_save(monkeypatch):
    import asyncio
    from fastapi import BackgroundTasks
    import outreach_manage as api
    from contextlib import contextmanager
    monkeypatch.setattr(api.auth, "_load_business", lambda session, bid: "business")
    monkeypatch.setattr(api, "execute", lambda *a, **k: {"saved": True})
    seen = []

    @contextmanager
    def own_session():
        seen.append("opened")
        try:
            yield "background-session"
        finally:
            seen.append("closed")
    monkeypatch.setattr(api, "get_session_context", own_session)
    from services import outreach_research

    def broken(session, business):
        seen.append("prepare")
        raise RuntimeError("provider down")
    monkeypatch.setattr(outreach_research, "prepare_due_cards", broken)
    tasks = BackgroundTasks()
    out = api.save_campaign_emails(uuid.uuid4(), api.SaveEmails(**_body()), tasks,
                                   context={"business_id": A, "user_id": OWNER}, session=None)
    assert out == {"saved": True}
    asyncio.run(tasks())                                          # logged, never raised
    assert seen == ["opened", "prepare", "closed"]                # it really ran, and its session closed


def test_reading_the_emails_needs_outreach(monkeypatch):
    from fastapi import HTTPException
    import outreach_manage as api
    monkeypatch.setattr(api.auth, "_load_business", lambda session, bid: "business")

    def refuse(business, feature, **kw):
        raise HTTPException(403, "Outreach isn't on your plan")
    monkeypatch.setattr(api.auth, "assert_feature_access", refuse)
    with pytest.raises(HTTPException) as exc:
        api.campaign_emails(uuid.uuid4(), context={"business_id": A, "user_id": OWNER}, session=None)
    assert exc.value.status_code == 403


# ----------------------- the wizard's two-step path (save, then approve) ---

def _two_step(h):
    c = campaign_row(h)
    steps = [{"ordinal": i, "delay_business_days": d, "subject": s, "body": b}
             for i, ((s, b), d) in enumerate(zip(NEW, (0, 5, 7)))]
    out = manage().sequence(h.s, h.b, OWNER, CAMPAIGN, {"version": int(c["version"]), "steps": steps})
    h.s.rollback()
    return out


def test_approving_in_the_wizard_also_moves_people_on(three):
    h = three
    card = sendh.propose(h)
    out = _two_step(h)
    assert enrolment(h)["sequence_version"] == 1          # saved but not approved: nothing moves yet
    manage().approve_templates(h.s, h.b, OWNER, CAMPAIGN, {"version": out["version"],
                                                          "sequence_version": out["sequence_version"]})
    h.s.rollback()
    assert enrolment(h)["sequence_version"] == 2
    assert h.s.execute(text("SELECT status FROM aria_actions WHERE id = :a"), {"a": card["id"]}).scalar() == "dismissed"
    card = sendh.propose(h, step_id=str(current_steps(h)[0]["id"]))
    sendh.approve(h, card)
    assert h.p.sends[-1][1]["subject"] == "A better offer"


def test_re_approving_the_same_wording_keeps_waiting_cards(three):
    h = three
    card = sendh.propose(h)
    c = campaign_row(h)
    manage().approve_templates(h.s, h.b, OWNER, CAMPAIGN, {"version": int(c["version"]),
                                                          "sequence_version": int(c["sequence_version"])})
    h.s.rollback()
    assert h.s.execute(text("SELECT status FROM aria_actions WHERE id = :a"), {"a": card["id"]}).scalar() == "proposed"
    assert enrolment(h)["sequence_version"] == 1


def test_approving_while_an_email_is_sending_waits(three):
    from services.aria_actions import ActionRefused
    h = three
    card = sendh.propose(h)
    sendh.claimed_only(h, card)
    c = campaign_row(h)
    with pytest.raises(ActionRefused) as exc:
        manage().approve_templates(h.s, h.b, OWNER, CAMPAIGN, {"version": int(c["version"]),
                                                              "sequence_version": int(c["sequence_version"])})
    h.s.rollback()
    assert exc.value.status_code == 409
