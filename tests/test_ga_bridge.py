"""Offline tests for ga_bridge.py's pure logic. No network, no SDK import
required (the SDK-dependent AgentRunner class is built lazily inside
make_bridge_agent_class, only imported when actually called)."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ga_bridge


class TestBuildGaEngramBody(unittest.TestCase):
    def test_slug_shape(self):
        body = ga_bridge.build_ga_engram_body("general", "agent-1", "hello", "evt-123")
        self.assertEqual(body["slug"], "mem/ga/channel/general/evt-123")

    def test_value_is_the_text(self):
        body = ga_bridge.build_ga_engram_body("general", "agent-1", "hello world", "evt-123")
        self.assertEqual(body["value"], "hello world")

    def test_provenance_fields(self):
        body = ga_bridge.build_ga_engram_body("general", "agent-1", "hi", "evt-1")
        prov = body["provenance"]
        self.assertEqual(prov["schema"], "nip-ae-provenance/v1")
        self.assertEqual(prov["source"], "openagents-ga-bridge")
        self.assertEqual(prov["created_by"], "agent-1")
        self.assertIsInstance(prov["created_at"], int)

    def test_slug_is_valid_per_minipae(self):
        import minipae as m
        body = ga_bridge.build_ga_engram_body("general", "agent-1", "hi", "abc123")
        self.assertTrue(m.validate_slug(body["slug"]))


if __name__ == "__main__":
    unittest.main()
