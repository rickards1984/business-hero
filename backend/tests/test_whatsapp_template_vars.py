"""LOG-1: every WhatsApp alert was refused by Twilio (Mike's logs, 5 Nov 00:00).

Twilio error 21656, "The Content Variables parameter is invalid": WhatsApp
template variables may not contain new lines, tabs or more than four spaces in
a row. Every alert body is written on several lines ("📋 Invoice now overdue\\n\\n
…"), so every alert failed; the daily pulse, on one line, went through.
"""
import pytest

from services import whatsapp_service as ws

ALERT = "📋 Invoice now overdue\n\nAcme Ltd — £120.00\nInvoice: INV-1001\n\n"


def _legal(value: str) -> bool:
    return "\n" not in value and "\r" not in value and "\t" not in value and "     " not in value


def test_a_multi_line_alert_becomes_one_legal_line_with_nothing_lost():
    out = ws._sanitize_template_vars({"1": "New Body", "2": ALERT, "3": "Reply 1️⃣ to chase"})
    assert all(_legal(v) for v in out.values()), out
    assert out["2"] == "📋 Invoice now overdue · Acme Ltd — £120.00 · Invoice: INV-1001"
    assert out["1"] == "New Body" and out["3"] == "Reply 1️⃣ to chase"


@pytest.mark.parametrize("raw,expected", [
    ("a\r\nb", "a · b"),
    ("a\tb", "a b"),
    ("a          b", "a b"),
    ("   \n  \n", "N/A"),
    ("🤖 Automation: Chase\n\nSend reminders", "🤖 Automation: Chase · Send reminders"),
])
def test_every_illegal_whitespace_is_made_legal(raw, expected):
    assert ws._sanitize_template_vars({"1": raw})["1"] == expected


def test_the_1024_character_limit_still_holds_after_joining():
    out = ws._sanitize_template_vars({"2": ("line\n" * 400)})["2"]
    assert len(out) <= 1024 and _legal(out)


def test_the_alert_twilio_receives_is_legal(monkeypatch):
    import asyncio
    sent = {}

    class Messages:
        def create(self, **kw):
            sent.update(kw)
            return type("M", (), {"sid": "MM1"})()

    monkeypatch.setattr(ws, "get_twilio_client", lambda: type("C", (), {"messages": Messages()})())
    monkeypatch.setattr(ws, "_log_whatsapp_message", lambda **kw: None)
    monkeypatch.setitem(ws.TEMPLATE_SID_MAP, "alert", "HX1")
    import json
    asyncio.run(ws.send_whatsapp_message(to_number="+447700900000",
                                         body=json.dumps({"1": "New Body", "2": ALERT, "3": "View details"}),
                                         business_id="b", message_type="alert"))
    assert sent.get("content_sid") == "HX1", "the alert went as the template"
    variables = json.loads(sent["content_variables"])
    assert all(_legal(v) for v in variables.values()), variables
