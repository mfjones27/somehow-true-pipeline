"""Offline remaining-balance parsing; no live provider calls."""
import os
import unittest
from unittest.mock import MagicMock, patch

from providers import balances


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class BalancesTest(unittest.TestCase):
    def setUp(self):
        balances._CACHE["at"] = 0.0
        balances._CACHE["data"] = None

    def test_missing_keys_do_not_hit_network(self):
        env = {
            "RUNWAY_API_KEY": "",
            "ELEVENLABS_API_KEY": "",
            "OPENAI_API_KEY": "",
        }
        with patch.dict(os.environ, env, clear=False), patch(
            "providers.balances.requests.get", side_effect=AssertionError("network")
        ):
            data = balances.fetch_balances(force=True)
        labels = {row["id"]: row for row in data["providers"]}
        self.assertEqual(labels["runway"]["display"], "missing API key")
        self.assertFalse(data["low"])
        self.assertEqual(data["warnings"], [])

    @patch("providers.balances.requests.get")
    def test_low_runway_and_elevenlabs_warn(self, get):
        def fake_get(url, **_kwargs):
            if "runwayml" in url:
                return FakeResponse({"creditBalance": 1200})
            if "elevenlabs" in url:
                return FakeResponse({"character_count": 95_000, "character_limit": 100_000})
            raise AssertionError(url)

        get.side_effect = fake_get
        env = {
            "RUNWAY_API_KEY": "rk_test",
            "ELEVENLABS_API_KEY": "el_test",
            "OPENAI_API_KEY": "",
        }
        with patch.dict(os.environ, env, clear=False):
            data = balances.fetch_balances(force=True)
        self.assertTrue(data["low"])
        self.assertEqual(len(data["warnings"]), 2)
        by_id = {row["id"]: row for row in data["providers"]}
        self.assertEqual(by_id["runway"]["remaining"], 1200)
        self.assertEqual(by_id["elevenlabs"]["remaining"], 5000)


if __name__ == "__main__":
    unittest.main()
