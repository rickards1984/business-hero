import unittest

from providers.microsoft_graph import _map_graph_message


class TestMicrosoftGraphMapping(unittest.TestCase):
    def test_map_basic_scope(self):
        message = {
            "id": "msg-1",
            "subject": "Hello",
            "from": {"emailAddress": {"address": "sender@example.com", "name": "Sender"}},
            "toRecipients": [{"emailAddress": {"address": "to@example.com"}}],
            "ccRecipients": [{"emailAddress": {"address": "cc@example.com"}}],
            "receivedDateTime": "2025-01-01T10:00:00Z",
            "isRead": False,
            "bodyPreview": "Preview text",
        }

        mapped = _map_graph_message(message, "basic")
        self.assertIsNotNone(mapped)
        self.assertEqual(mapped.provider_message_id, "msg-1")
        self.assertEqual(mapped.subject, "Hello")
        self.assertEqual(mapped.from_email, "sender@example.com")
        self.assertEqual(mapped.to_emails, ["to@example.com"])
        self.assertEqual(mapped.cc_emails, ["cc@example.com"])
        self.assertEqual(mapped.snippet, "Preview text")
        self.assertTrue(mapped.is_unread)
        self.assertIsNone(mapped.body_text)
        self.assertIsNone(mapped.body_html)

    def test_map_full_scope_html_body(self):
        message = {
            "id": "msg-2",
            "subject": "HTML Email",
            "from": {"emailAddress": {"address": "sender@example.com"}},
            "toRecipients": [{"emailAddress": {"address": "to@example.com"}}],
            "receivedDateTime": "2025-01-01T10:00:00Z",
            "isRead": True,
            "bodyPreview": "HTML preview",
            "body": {"contentType": "html", "content": "<p>Hello</p>"},
        }

        mapped = _map_graph_message(message, "full")
        self.assertIsNotNone(mapped)
        self.assertEqual(mapped.body_html, "<p>Hello</p>")
        self.assertIsNone(mapped.body_text)
        self.assertFalse(mapped.is_unread)

    def test_map_full_scope_text_body(self):
        message = {
            "id": "msg-3",
            "subject": "Text Email",
            "from": {"emailAddress": {"address": "sender@example.com"}},
            "toRecipients": [{"emailAddress": {"address": "to@example.com"}}],
            "receivedDateTime": "2025-01-01T10:00:00Z",
            "isRead": True,
            "bodyPreview": "Text preview",
            "body": {"contentType": "text", "content": "Hello"},
        }

        mapped = _map_graph_message(message, "full")
        self.assertIsNotNone(mapped)
        self.assertEqual(mapped.body_text, "Hello")
        self.assertIsNone(mapped.body_html)


if __name__ == "__main__":
    unittest.main()
