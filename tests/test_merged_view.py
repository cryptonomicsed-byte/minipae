"""Offline tests for Phase 3.3's merged read view. No network required."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import minipae as m
import merged_view as mv


class TestNamespaceOf(unittest.TestCase):
    def test_mem_namespace(self):
        self.assertEqual(mv.namespace_of("mem/genteam/computer/x/state"), "genteam")
        self.assertEqual(mv.namespace_of("mem/hermes/profile/default/memory/x"), "hermes")

    def test_core_reserved(self):
        self.assertEqual(mv.namespace_of("core"), "core")

    def test_malformed_slug(self):
        self.assertEqual(mv.namespace_of("notmem/x"), "unknown")


class TestBuildMergedView(unittest.TestCase):
    def setUp(self):
        self.sk = m.secrets.token_bytes(32)
        self.pk = m.pubkey_from_secret(int.from_bytes(self.sk, "big"))
        self.kc = m.conversation_key(self.sk, self.pk)

    def _engram(self, slug, value, trust_class=None):
        body = {"slug": slug, "value": value}
        if trust_class is not None:
            body["provenance"] = {"content_trust_class": trust_class}
        ev = m.build_event(slug, body, self.sk, self.pk)
        return ev

    def test_groups_by_namespace(self):
        heads = m.select_heads([
            self._engram("mem/genteam/computer/x/state", "a"),
            self._engram("mem/hermes/profile/default/memory/y", "b"),
        ], self.kc)
        view = mv.build_merged_view(heads, self.kc)
        self.assertEqual(set(view.keys()), {"genteam", "hermes"})

    def test_defaults_to_private_when_unlabeled(self):
        heads = m.select_heads([self._engram("mem/genteam/x", "a")], self.kc)
        view = mv.build_merged_view(heads, self.kc)
        self.assertEqual(list(view["genteam"].keys()), ["private"])

    def test_never_flattens_private_and_public_together(self):
        heads = m.select_heads([
            self._engram("mem/buzz/claim1", "private note", trust_class="private"),
            self._engram("mem/buzz/claim2", "public claim pointer", trust_class="public"),
        ], self.kc)
        view = mv.build_merged_view(heads, self.kc)
        self.assertEqual(set(view["buzz"].keys()), {"private", "public"})
        self.assertEqual(len(view["buzz"]["private"]), 1)
        self.assertEqual(len(view["buzz"]["public"]), 1)
        # the two must never end up in the same list
        self.assertNotEqual(id(view["buzz"]["private"]), id(view["buzz"]["public"]))

    def test_invalid_trust_class_fails_safe_to_private(self):
        heads = m.select_heads([self._engram("mem/x/y", "v", trust_class="somethingelse")], self.kc)
        view = mv.build_merged_view(heads, self.kc)
        self.assertEqual(list(view["x"].keys()), ["private"])

    def test_tombstones_excluded(self):
        heads = m.select_heads([self._engram("mem/genteam/x", None)], self.kc)
        view = mv.build_merged_view(heads, self.kc)
        self.assertEqual(view, {})

    def test_render_text_shows_both_classes_separately(self):
        heads = m.select_heads([
            self._engram("mem/buzz/a", "priv", trust_class="private"),
            self._engram("mem/buzz/b", "pub", trust_class="public"),
        ], self.kc)
        view = mv.build_merged_view(heads, self.kc)
        text = mv.render_text(view)
        self.assertIn("🔒 private", text)
        self.assertIn("🌐 public", text)


if __name__ == "__main__":
    unittest.main()
