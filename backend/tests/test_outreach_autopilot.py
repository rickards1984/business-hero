"""OUT-11 — auto-approve outreach (docs/OUT-11-TICKET.md).

Tests first (RED: automatic customer contact under a standing permission).
Strict xfail may fail only because `services.outreach_autopilot` does not
exist yet. The OUT-6 harness supplies a seeded campaign, a fake provider (no
network) and a pinned clock (Friday 23 Oct 2026, 12:00 UK); every approval
goes through the REAL services.aria_actions path.
"""
# ruff: noqa: F811 - pytest fixtures imported from test_outreach_send are parameters by design

import importlib
import importlib.util
import json
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text

from test_outreach_send import (  # noqa: F401 - fixtures are used by name
    A, BOX, CAMPAIGN, ENROLMENT, NOW, OWNER, STAFF, STEP, database, h, insert, uid)


class MissingAutopilot(AssertionError):
    """Only the intentional Stage 1 absence may be xfailed."""


pytestmark = pytest.mark.xfail(strict=True, raises=MissingAutopilot, reason="OUT-11 not built yet: tests first")


def autopilot():
    if importlib.util.find_spec("services.outreach_autopilot") is None:
        raise MissingAutopilot("backend/services/outreach_autopilot.py does not exist yet")
    return importlib.import_module("services.outreach_autopilot")


def actions():
    from services import aria_actions
    return aria_actions


def earned(h, n=5):
    """n earlier sends in this campaign, approved by the owner and accepted."""
    for i in range(n):
        insert(h.s, "outreach_messages", id=str(uuid.uuid4()), business_id=A, campaign_id=CAMPAIGN,
               prospect_id=uid(f"earlier-{i}"), mailbox_id=BOX, direction="outbound", state="accepted",
               origin="live", kind="initial", authority_snapshot=json.dumps({"user_id": OWNER}),
               accepted_at=(NOW - timedelta(days=3)).isoformat())
    h.s.commit()


def versions(h):
    row = h.s.execute(text("SELECT version, sequence_version FROM outreach_campaigns WHERE id = :c"),
                      {"c": CAMPAIGN}).one()
    return {"version": int(row[0]), "sequence_version": int(row[1])}


def granted(h):
    earned(h)
    return autopilot().grant(h.s, h.b, OWNER, CAMPAIGN, versions(h))


def send(h, moment=None, rng=lambda: 0.0):
    return autopilot().send_next(h.s, h.b, CAMPAIGN, moment=moment or NOW, rng=rng)


def sends(h):
    return len(h.p.sends)


# ------------------------------------------------------------- the grant ---

@pytest.mark.parametrize("who", [STAFF, uid("platform-admin"), None])
def test_only_the_active_owner_grants(h, who):
    m = autopilot()
    earned(h)
    with pytest.raises(actions().ActionRefused) as exc:
        m.grant(h.s, h.b, who, CAMPAIGN, versions(h))
    assert exc.value.status_code == 403


def test_it_unlocks_only_after_five_hand_approved_accepted_sends(h):
    """Decision A."""
    m = autopilot()
    earned(h, 4)
    with pytest.raises(actions().ActionRefused) as exc:
        m.grant(h.s, h.b, OWNER, CAMPAIGN, versions(h))
    assert exc.value.status_code == 409 and "5" in exc.value.detail
    assert m.status(h.s, h.b)[CAMPAIGN]["needed"] == 1
    earned(h, 1)
    assert m.grant(h.s, h.b, OWNER, CAMPAIGN, versions(h))["campaign_id"] == CAMPAIGN


def test_automatic_sends_do_not_count_towards_earning_trust(h):
    m = autopilot()
    for i in range(5):
        insert(h.s, "outreach_messages", id=str(uuid.uuid4()), business_id=A, campaign_id=CAMPAIGN,
               prospect_id=uid(f"auto-{i}"), mailbox_id=BOX, direction="outbound", state="accepted",
               origin="live", kind="initial",
               authority_snapshot=json.dumps({"automation": "outreach_autopilot", "granted_by": OWNER}))
    h.s.commit()
    with pytest.raises(actions().ActionRefused):
        m.grant(h.s, h.b, OWNER, CAMPAIGN, versions(h))


# ------------------------------------------------------------ sending ---

def test_with_a_grant_aria_sends_one_due_email_by_herself(h):
    granted(h)
    out = send(h)
    assert out["sent"] and sends(h) == 1
    row = h.s.execute(text("SELECT status, approved_by, payload FROM aria_actions WHERE id = :id"),
                      {"id": out["sent"]}).one()
    assert row[0] == "done" and row[1] is None
    assert json.loads(row[2])["automation"] == "outreach_autopilot"
    snapshot = json.loads(h.s.execute(text(
        "SELECT authority_snapshot FROM outreach_messages WHERE action_id = :id"), {"id": out["sent"]}).scalar())
    assert snapshot["automation"] == "outreach_autopilot" and snapshot["granted_by"] == OWNER


def test_without_a_grant_nothing_is_sent(h):
    earned(h)
    out = send(h)
    assert out["sent"] is None and out["waiting"] and sends(h) == 0


def test_the_automation_marker_is_refused_without_a_valid_grant(h):
    autopilot()
    a = actions()
    out = a.propose(h.s, h.b, None, "send_outreach",
                    {"campaign_id": CAMPAIGN, "enrolment_id": ENROLMENT, "step_id": STEP},
                    automation="outreach_autopilot")
    assert "error" in out


def test_switching_off_takes_effect_before_the_next_send(h):
    """A card prepared under the grant is refused once the owner revokes it."""
    a, m = actions(), autopilot()
    granted(h)
    card = a.propose(h.s, h.b, None, "send_outreach",
                     {"campaign_id": CAMPAIGN, "enrolment_id": ENROLMENT, "step_id": STEP},
                     automation="outreach_autopilot")["proposal"]
    m.revoke(h.s, h.b, OWNER, CAMPAIGN)
    with pytest.raises(a.ActionRefused):
        a.approve(h.s, h.b, card["id"], None, card["version"])
    assert sends(h) == 0


@pytest.mark.parametrize("change", ["wording", "sender"])
def test_changing_the_wording_or_sender_switches_it_off(h, change):
    """Decision D."""
    m = autopilot()
    granted(h)
    column = "sequence_version" if change == "wording" else "mailbox_id"
    value = 2 if change == "wording" else uid("other-mailbox")
    h.s.execute(text(f"UPDATE outreach_campaigns SET {column} = :v WHERE id = :c"), {"v": value, "c": CAMPAIGN})
    h.s.commit()
    assert m.status(h.s, h.b)[CAMPAIGN]["valid"] is False
    assert send(h)["sent"] is None and sends(h) == 0


def test_an_owner_who_leaves_takes_the_permission_with_them(h):
    m = autopilot()
    granted(h)
    h.s.execute(text("UPDATE business_members SET is_active = 0 WHERE user_id = :u"), {"u": OWNER})
    h.s.commit()
    assert m.status(h.s, h.b)[CAMPAIGN]["valid"] is False
    assert send(h)["sent"] is None and sends(h) == 0


def test_losing_outreach_switches_it_off(h):
    granted(h)
    h.s.execute(text("UPDATE businesses SET feature_flags = :f WHERE id = :b"),
                {"f": json.dumps({"outreach": False}), "b": A})
    h.s.commit()
    assert send(h)["sent"] is None and sends(h) == 0


def test_pause_all_stops_automatic_sending(h):
    granted(h)
    h.s.execute(text("UPDATE outreach_settings SET pause_all = 1 WHERE business_id = :b"), {"b": A})
    h.s.commit()
    assert send(h)["sent"] is None and sends(h) == 0


def test_the_window_and_every_send_rule_still_apply(h):
    granted(h)
    saturday = NOW + timedelta(days=1)
    assert send(h, moment=saturday)["sent"] is None and sends(h) == 0


def test_sends_are_spread_out_never_bunched(h):
    """Decision C: at least 6 minutes apart, plus up to 6 more at random."""
    granted(h)
    assert send(h)["sent"]
    second = send(h, moment=NOW + timedelta(minutes=2))
    assert second["sent"] is None and "minute" in second["waiting"]
    later = send(h, moment=NOW + timedelta(minutes=13), rng=lambda: 0.99)
    assert later["sent"] is None and "minute" not in (later["waiting"] or ""), "nothing else due, not pace"


def test_answers_to_replies_are_never_sent_automatically(h):
    """Decision B."""
    autopilot()
    out = actions().propose(h.s, h.b, None, "reply_outreach", {"body": "x"}, automation="outreach_autopilot")
    assert "error" in out


def test_the_home_page_shows_what_aria_sent_on_her_own(h):
    """Decision E."""
    granted(h)
    send(h)
    from services import home_summary
    with h.engine.connect() as c:
        recent = home_summary.recent_automated(c, A, NOW + timedelta(minutes=1))
    assert any(r["kind"] == "outreach_autopilot" for r in recent)


def test_a_card_the_owner_taps_still_works_with_autopilot_on(h):
    a = actions()
    granted(h)
    card = a.propose(h.s, h.b, OWNER, "send_outreach",
                     {"campaign_id": CAMPAIGN, "enrolment_id": ENROLMENT, "step_id": STEP}, owner_name="Owner")["proposal"]
    assert a.approve(h.s, h.b, card["id"], OWNER, version=card["version"])["status"] == "done"
    assert sends(h) == 1
