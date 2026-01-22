import unittest

from main import _select_awaz_token


class TestAwazWebhookAuth(unittest.TestCase):
    def test_select_header_over_query(self):
        token = _select_awaz_token("header-key", "query-key")
        self.assertEqual(token, "header-key")

    def test_select_query_when_header_missing(self):
        token = _select_awaz_token(None, "query-key")
        self.assertEqual(token, "query-key")

    def test_missing_both(self):
        token = _select_awaz_token(None, None)
        self.assertIsNone(token)


if __name__ == "__main__":
    unittest.main()
