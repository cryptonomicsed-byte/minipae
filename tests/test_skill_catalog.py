"""Offline tests for the skill catalog (Phase 3.2) and its de_verify_skill
checker. No network required."""
from __future__ import annotations

import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "de_verify_skill"))

import verify_skill  # noqa: E402


class TestSkillCatalog(unittest.TestCase):
    def test_real_catalog_is_valid(self):
        result = verify_skill.verify_catalog(ROOT)
        self.assertEqual(result["failures"], [])
        self.assertGreater(result["checked"], 0)
        self.assertEqual(result["checked"], result["passed"])

    def test_catches_unregistered_verb(self):
        # write a temp skill file with a bad verb, verify it's caught, clean up
        bad_dir = os.path.join(ROOT, "skills", "_test_bad_skill")
        os.makedirs(bad_dir, exist_ok=True)
        bad_file = os.path.join(bad_dir, "SKILL.md")
        try:
            with open(bad_file, "w") as f:
                f.write("---\nid: _test_bad\nverb: de_not_a_real_verb\nname: x\n"
                        "description: x\nversion: 1.0.0\nstatus: active\n"
                        "trigger: {kind: prompt}\ninputs: {}\noutputs: {}\n"
                        "verification: {kind: test}\nruntimes: []\n"
                        "memory: {reads: [], writes: []}\nowner: test\n---\n")
            catalog = {
                "schema": "skill-catalog/v1",
                "verbs": [{"verb": "de_draft"}],
                "skills": [{"id": "_test_bad", "file": "skills/_test_bad_skill/SKILL.md"}],
            }
            import yaml
            catalog_path = os.path.join(ROOT, "skills", "catalog.yaml")
            with open(catalog_path) as f:
                real_catalog = f.read()
            with open(catalog_path, "w") as f:
                yaml.safe_dump(catalog, f)
            try:
                result = verify_skill.verify_catalog(ROOT)
                self.assertEqual(result["failures"],
                                 ["_test_bad: verb 'de_not_a_real_verb' not in catalog verbs"])
            finally:
                with open(catalog_path, "w") as f:
                    f.write(real_catalog)
        finally:
            if os.path.exists(bad_file):
                os.remove(bad_file)
            if os.path.isdir(bad_dir):
                os.rmdir(bad_dir)

    def test_verify_sh_exits_zero_on_real_catalog(self):
        script = os.path.join(ROOT, "skills", "de_verify_skill", "verify.sh")
        result = subprocess.run(["bash", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
