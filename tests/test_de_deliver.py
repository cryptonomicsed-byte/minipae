"""Tests for de_deliver_client_artifact. The pure receipt-body builder is
tested fully offline; the live generate+publish path requires
GENOFFICE_REPO and network, skipped gracefully otherwise (same pattern as
test_de_package_docx.py)."""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "de_deliver_client_artifact"))
sys.path.insert(0, os.path.join(ROOT, "skills", "de_package_docx"))
sys.path.insert(0, ROOT)

import de_deliver_client_artifact as dd
import minipae as m

GENOFFICE_REPO = os.environ.get("GENOFFICE_REPO")
TEMPLATE = os.path.join(GENOFFICE_REPO or "", "fixtures", "generated", "simple.docx")


class TestBuildReceiptBody(unittest.TestCase):
    def test_slug_shape(self):
        body = dd.build_receipt_body("acme-corp", "/tmp/out.docx", ["part1.md"], "abc123", 2048)
        self.assertTrue(body["slug"].startswith("mem/skills/de_deliver/acme-corp/"))

    def test_slug_is_valid_per_minipae(self):
        body = dd.build_receipt_body("acme-corp", "/tmp/out.docx", ["p1"], "abc123", 100)
        self.assertTrue(m.validate_slug(body["slug"]))

    def test_value_contains_delivery_details(self):
        body = dd.build_receipt_body("acme-corp", "/tmp/out.docx", ["p1", "p2"], "abc123", 512)
        import json
        val = json.loads(body["value"])
        self.assertEqual(val["client"], "acme-corp")
        self.assertEqual(val["parts"], ["p1", "p2"])
        self.assertEqual(val["artifact_bytes"], 512)

    def test_provenance_source(self):
        body = dd.build_receipt_body("acme-corp", "/tmp/out.docx", ["p1"], "abc123", 1)
        self.assertEqual(body["provenance"]["source"], "de_deliver_client_artifact")
        self.assertEqual(body["provenance"]["created_by"], "abc123")

    def test_different_calls_get_different_slugs(self):
        b1 = dd.build_receipt_body("acme-corp", "/tmp/out.docx", ["p1"], "abc123", 1)
        b2 = dd.build_receipt_body("acme-corp", "/tmp/out2.docx", ["p1"], "abc123", 1)
        self.assertNotEqual(b1["slug"], b2["slug"])


@unittest.skipUnless(GENOFFICE_REPO and os.path.exists(TEMPLATE),
                     "GENOFFICE_REPO not set or fixture missing - external dependency, not vendored")
class TestDeliverLive(unittest.TestCase):
    def test_deliver_generates_and_publishes(self):
        import tempfile
        sk = m.secrets.token_bytes(32)
        owner = m.pubkey_from_secret(int.from_bytes(sk, "big"))
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            out_path = f.name
        try:
            result = dd.deliver("test-client", TEMPLATE, out_path, ["a real deliverable paragraph"],
                                sk, owner, "wss://relay.damus.io", genoffice_repo=GENOFFICE_REPO)
            self.assertTrue(result["artifact"]["ok"])
            self.assertTrue(os.path.exists(out_path))
            self.assertTrue(result["receipt"]["published"]["ok"])
        finally:
            os.unlink(out_path)


if __name__ == "__main__":
    unittest.main()
