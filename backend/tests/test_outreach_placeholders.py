"""OUT-25 — an unfilled placeholder such as "[YOUR NAME]" is never sent.

Templates take no variables (allowed_variables is always []), and the real
sign-off is added by aria_actions.sign_off. Mike, 11 Nov 2026: Aria's drafted
emails ended "[YOUR NAME]". A model's own placeholder sign-off is removed from
drafts; any other placeholder is refused when the emails are saved or approved,
and the send path never makes, claims or dispatches an email containing one.
"""
# ruff: noqa: F811 - pytest fixtures imported from the harnesses are parameters by design
import hashlib
import json

import pytest
from sqlalchemy import text
from sqlmodel import Session

import test_outreach_send as sendh
from test_outreach_send import database, h  # noqa: F401
from test_outreach_setup import OWNER, db, draft_emails, grant, ready, setup_module_or_missing  # noqa: F401


def send():
    from services import outreach_send
    return outreach_send


def setup():
    from services import outreach_setup
    return outreach_setup


# ------------------------------------------------------------- detection ---

@pytest.mark.parametrize("value", ["Thanks,\n[YOUR NAME]", "Hi [First Name],", "Dear {{first_name}}", "Hi {first_name}",
                                   "at [Company] we", "Hi <NAME>,", "Dear {{name}}",
                                   "Hi [Insert the first name of the recipient here], how are you?",
                                   "Visit [your website link]", "[CITY] gyms", "Dear {{firstName}},", "Hi [firstname],",
                                   "Reply to [emailAddress].", "Kind regards, [Sender's name]", "Call [phone number]"])
def test_placeholders_are_found(value):
    assert send().placeholder(value)


@pytest.mark.parametrize("value", ["Fees from £20 a month.", "Our team (six coaches) can help.",
                                   "Reply with a yes or no.", "A 1:1 session", "See https://example.com/a?b=c",
                                   "£20 a month [ex VAT].", "Our monthly fee is £20.\n[Prices exclude VAT]",
                                   "https://example.com/?filter[sector]=gyms", "Write to <sam@example.com>",
                                   "<br>", "[see below]", "We ran 12 sessions [in 2025].", "Please reply [by email only].",
                                   "Our pricing is fixed.\n[My prices include VAT]", "[Sent from my phone]",
                                   "Prices [per person, per session]."])
def test_ordinary_writing_is_not_a_placeholder(value):
    assert send().placeholder(value) is None


@pytest.mark.parametrize("body,expected", [
    ("Hello Sam,\n\nWould a short call help?\n\nBest regards,\n[YOUR NAME]", "Hello Sam,\n\nWould a short call help?"),
    ("Hello Sam,\n\nWorth a chat?\n\nThanks\n\n[Your Name]\n[Company]", "Hello Sam,\n\nWorth a chat?"),
    ("Hello Sam,\n\nWorth a chat?\n[YOUR NAME]", "Hello Sam,\n\nWorth a chat?"),
    ("Hi,\n\nA thought.\n\nCheers,\n{{senderName}}\n[Job Title]", "Hi,\n\nA thought."),
    ("Hello Sam,\n\nWorth a chat?", "Hello Sam,\n\nWorth a chat?"),
])
def test_a_drafted_placeholder_sign_off_is_removed(body, expected):
    assert setup()._drop_placeholder_sign_off(body) == expected


@pytest.mark.parametrize("body", [
    "Our monthly fee is £20.\n[Prices exclude VAT]",
    "Book a slot:\n[https://cal.example/msc]",
    "Hello Sam,\n\nThanks for reading.\n\nBest regards,",
    "Our pricing is fixed.\n[My prices include VAT]",
    "Reply any time.\n[Your call, no pressure]",
])
def test_real_content_is_never_removed(body):
    """Codex OUT-25 review 1, finding 1."""
    assert setup()._drop_placeholder_sign_off(body) == body.rstrip()


def test_a_placeholder_in_the_middle_is_left_for_the_owner():
    body = "Hello Sam,\n\nAt [Company] we coach gyms.\n\nBest,\n[YOUR NAME]"
    assert setup()._drop_placeholder_sign_off(body) == "Hello Sam,\n\nAt [Company] we coach gyms."


@pytest.mark.parametrize("drafter", ["model_draft_emails", "model_redraft_emails"])
def test_the_drafting_model_s_output_is_tidied(monkeypatch, drafter):
    monkeypatch.setattr(setup(), "_model_json", lambda prompt, context: {"emails": [
        {"subject": f"A quick idea {i}", "body": "Hi Sam,\n\nA thought.\n\nKind regards,\n[YOUR NAME]"}
        for i in range(3)]})
    emails = getattr(setup(), drafter)({})
    assert [e["body"] for e in emails] == ["Hi Sam,\n\nA thought."] * 3
    assert [e["subject"] for e in emails] == ["A quick idea 0", "A quick idea 1", "A quick idea 2"]
    assert "Never use placeholders" in setup().EMAIL_CRAFT


# --------------------------------------------------- saving and approving ---

def _placeholder_drafts(context):
    return [{"subject": f"S{i}", "body": "Hello,\n\nAt [Company] we help gyms like yours."} for i in range(3)]


def test_emails_with_a_placeholder_are_not_saved(db):
    from services.aria_actions import ActionRefused
    m = setup_module_or_missing()
    biz = grant(db)
    with Session(db) as s:
        m.begin(s, biz, OWNER)
    with pytest.raises(ActionRefused) as exc:
        with Session(db) as s:
            brand = m.save_brand(s, biz, OWNER, {"name": "B", "sender_identity": "B Ltd"})
            m._insert_steps(s, str(biz.id), "00000000-0000-0000-0000-000000000001", 1, _placeholder_drafts({}))
    assert exc.value.status_code == 422 and "[Company]" in exc.value.detail and brand


def test_a_placeholder_sign_off_from_the_model_is_saved_clean(db):
    m = setup_module_or_missing()
    biz = grant(db)

    def drafts(context):
        return [dict(e, body=e["body"] + "\n\nBest regards,\n[YOUR NAME]") for e in draft_emails(context)]
    import test_outreach_setup as st
    original = st.draft_emails
    st.draft_emails = drafts
    try:
        brand, lia, campaign = ready(m, db, biz)
    finally:
        st.draft_emails = original
    with db.connect() as c:
        bodies = [json.loads(r[0])["body"] for r in c.execute(text("SELECT template_text FROM outreach_sequence_steps"))]
    assert bodies and all("[YOUR NAME]" not in b and "Best regards" not in b for b in bodies)


def test_existing_emails_with_a_placeholder_cannot_be_approved(db):
    from services import outreach_manage
    from services.aria_actions import ActionRefused
    m = setup_module_or_missing()
    biz = grant(db)
    brand, lia, campaign = ready(m, db, biz)
    with Session(db) as s:            # an email saved before this fix
        step = s.execute(text("SELECT id, template_text FROM outreach_sequence_steps ORDER BY ordinal LIMIT 1")).one()
        envelope = json.dumps({**json.loads(step[1]), "body": "Hi,\n\nA thought.\n\nThanks,\n[YOUR NAME]"})
        s.execute(text("UPDATE outreach_sequence_steps SET template_text = :t, template_hash = :h WHERE id = :i"),
                  {"t": envelope, "h": hashlib.sha256(envelope.encode()).hexdigest(), "i": step[0]})
        c = s.execute(text("SELECT version, sequence_version FROM outreach_campaigns")).one()
        s.commit()
    with Session(db) as s, pytest.raises(ActionRefused) as exc:
        outreach_manage.approve_templates(s, biz, OWNER, campaign["id"], {"version": int(c[0]), "sequence_version": int(c[1])})
    assert exc.value.status_code == 422 and "[YOUR NAME]" in exc.value.detail


def test_a_new_sequence_with_a_placeholder_is_refused(db):
    from services import outreach_manage
    from services.aria_actions import ActionRefused
    m = setup_module_or_missing()
    biz = grant(db)
    brand, lia, campaign = ready(m, db, biz)
    with Session(db) as s:
        version = int(s.execute(text("SELECT version FROM outreach_campaigns")).scalar())
    steps = [{"ordinal": i, "delay_business_days": d, "subject": "Hi", "body": "Thanks,\n[YOUR NAME]"}
             for i, d in enumerate((0, 5, 7))]
    with Session(db) as s, pytest.raises(ActionRefused) as exc:
        outreach_manage.sequence(s, biz, OWNER, campaign["id"], {"version": version, "steps": steps})
    assert exc.value.status_code == 422


# ------------------------------------------------------------- the send path ---

def _template_with_placeholder(h):
    envelope = json.dumps({"schema_version": 1, "subject": "Synthetic offer",
                           "body": "A relevant synthetic offer.\n\nThanks,\n[YOUR NAME]"})
    h.s.execute(text("UPDATE outreach_sequence_steps SET template_text = :t, template_hash = :h WHERE id = :i"),
                {"t": envelope, "h": hashlib.sha256(envelope.encode()).hexdigest(), "i": sendh.STEP})
    h.s.commit()


def test_no_card_is_made_from_an_email_with_a_placeholder(h):
    _template_with_placeholder(h)
    result = h.a.propose(h.s, h.b, sendh.OWNER, "send_outreach",
                         dict(campaign_id=sendh.CAMPAIGN, enrolment_id=sendh.ENROLMENT, step_id=sendh.STEP),
                         owner_name="Owner")
    assert "placeholder" in result.get("error", ""), result
    assert not h.p.sends


def test_a_card_made_before_the_fix_is_refused_at_claim(h, monkeypatch):
    _template_with_placeholder(h)
    with monkeypatch.context() as patched:            # as a card made before OUT-25
        patched.setattr(h.m, "placeholder", lambda *texts: None)
        card = sendh.propose(h)
    with pytest.raises(h.a.ActionRefused, match="placeholder"):
        sendh.approve(h, card)
    assert not h.p.sends


def test_a_claimed_email_with_a_placeholder_takes_the_blocked_path(h, monkeypatch):
    _template_with_placeholder(h)
    with monkeypatch.context() as patched:            # made and claimed before OUT-25
        patched.setattr(h.m, "placeholder", lambda *texts: None)
        card = sendh.propose(h)
        sendh.claimed_only(h, card)
    result = h.m.dispatch(h.s, h.b, action_id=card["id"], payload=card["preview"])
    assert result["status"] == "failed" and result["outcome"] == "definitely_not_accepted"
    assert not h.p.sends
