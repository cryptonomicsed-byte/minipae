"""Schema + consistency checks for runtime_registry.json (Phase 3.1).

Offline, no network. Checks structural validity and the minimum-fields
rule from docs/RUNTIME_REGISTRY.md §3, plus cross-checks against
NAMESPACES.md so the registry can't silently drift from the namespace
source of truth.
"""
from __future__ import annotations

import json
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRY_PATH = os.path.join(ROOT, "runtime_registry.json")
NAMESPACES_PATH = os.path.join(ROOT, "NAMESPACES.md")

REQUIRED_TOP_FIELDS = {
    "runtime_id", "name", "layer", "kind", "status", "identity",
    "credentials", "hosts", "namespaces", "provenance", "adapter",
    "owner_pane", "registered_at", "verified",
}
VALID_STATUS = {"active", "planned", "deprecated"}
VALID_LAYER = {"1-identity", "2-dispatch", "3-execute", "4-deliver"}


def _load_registry() -> dict:
    with open(REGISTRY_PATH) as f:
        return json.load(f)


def _registered_namespaces() -> set[str]:
    with open(NAMESPACES_PATH) as f:
        text = f.read()
    # table rows look like: | `mem/foo/*` | ... | active |
    return set(re.findall(r"`(mem/[a-z0-9_]+/\*)`", text))


class TestRuntimeRegistrySchema(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = _load_registry()
        cls.namespaces = _registered_namespaces()

    def test_schema_field_present(self):
        self.assertEqual(self.registry.get("schema"), "runtime-registry/v1")

    def test_entries_is_nonempty_list(self):
        entries = self.registry.get("entries")
        self.assertIsInstance(entries, list)
        self.assertGreater(len(entries), 0)

    def test_every_entry_has_required_fields(self):
        for entry in self.registry["entries"]:
            missing = REQUIRED_TOP_FIELDS - entry.keys()
            self.assertEqual(missing, set(), f"{entry.get('runtime_id')} missing {missing}")

    def test_status_values_valid(self):
        for entry in self.registry["entries"]:
            self.assertIn(entry["status"], VALID_STATUS, entry["runtime_id"])

    def test_layer_values_valid(self):
        for entry in self.registry["entries"]:
            self.assertIn(entry["layer"], VALID_LAYER, entry["runtime_id"])

    def test_runtime_ids_unique(self):
        ids = [e["runtime_id"] for e in self.registry["entries"]]
        self.assertEqual(len(ids), len(set(ids)), "duplicate runtime_id")

    def test_active_entries_have_verification_evidence(self):
        # docs/RUNTIME_REGISTRY.md §4: status:active REQUIRES verification
        # evidence — panels never self-certify, but the registry entry must
        # at least carry evidence fields, not just an unverified claim.
        for entry in self.registry["entries"]:
            if entry["status"] != "active":
                continue
            v = entry["verified"]
            self.assertTrue(v.get("health"), f"{entry['runtime_id']}: active but health not verified")
            self.assertTrue(v.get("engram_roundtrip"), f"{entry['runtime_id']}: active but no engram roundtrip evidence")
            self.assertIsNotNone(v.get("last_check"), f"{entry['runtime_id']}: active but no last_check timestamp")

    def test_active_entries_have_at_least_one_host(self):
        for entry in self.registry["entries"]:
            if entry["status"] == "active":
                self.assertGreater(len(entry["hosts"]), 0, entry["runtime_id"])

    def test_namespaces_are_registered_in_namespaces_md(self):
        # every namespace an entry claims must exist in NAMESPACES.md —
        # catches the exact class of drift G1 called out (OpenClaw almost
        # got a namespace referenced before it was registered).
        for entry in self.registry["entries"]:
            for ns in entry["namespaces"]:
                self.assertIn(ns, self.namespaces,
                             f"{entry['runtime_id']} claims {ns}, not in NAMESPACES.md")

    def test_planned_entries_not_marked_verified(self):
        for entry in self.registry["entries"]:
            if entry["status"] == "planned":
                v = entry["verified"]
                self.assertFalse(v.get("health"), f"{entry['runtime_id']}: planned but health=true")
                self.assertFalse(v.get("engram_roundtrip"), f"{entry['runtime_id']}: planned but engram_roundtrip=true")


if __name__ == "__main__":
    unittest.main()
