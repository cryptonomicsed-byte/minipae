"""Tests for de_package_docx (Phase 4). Requires a local genspark-ai/genoffice
clone with `npm install` run — skipped (not failed) if GENOFFICE_REPO isn't
set, since that's a large external dependency this repo doesn't vendor.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "skills", "de_package_docx"))

GENOFFICE_REPO = os.environ.get("GENOFFICE_REPO")
TEMPLATE = os.path.join(GENOFFICE_REPO or "", "fixtures", "generated", "simple.docx")


@unittest.skipUnless(GENOFFICE_REPO and os.path.exists(TEMPLATE),
                     "GENOFFICE_REPO not set or fixture missing - external dependency, not vendored")
class TestDePackageDocx(unittest.TestCase):
    def test_generates_valid_docx_with_content(self):
        import de_package_docx
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            out_path = f.name
        try:
            result = de_package_docx.generate_docx(
                TEMPLATE, out_path,
                ["offline test paragraph: de_package_docx unit test"],
                genoffice_repo=GENOFFICE_REPO,
            )
            self.assertTrue(result["ok"])
            self.assertTrue(os.path.exists(out_path))

            z = zipfile.ZipFile(out_path)
            self.assertIn("word/document.xml", z.namelist())
            doc = z.read("word/document.xml").decode("utf-8")
            self.assertIn("offline test paragraph: de_package_docx unit test", doc)
        finally:
            os.unlink(out_path)

    def test_multiple_paragraphs_all_present(self):
        import de_package_docx
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            out_path = f.name
        try:
            de_package_docx.generate_docx(
                TEMPLATE, out_path, ["first paragraph unique text", "second paragraph unique text"],
                genoffice_repo=GENOFFICE_REPO,
            )
            z = zipfile.ZipFile(out_path)
            doc = z.read("word/document.xml").decode("utf-8")
            self.assertIn("first paragraph unique text", doc)
            self.assertIn("second paragraph unique text", doc)
        finally:
            os.unlink(out_path)

    def test_missing_genoffice_repo_raises(self):
        import de_package_docx
        old = os.environ.pop("GENOFFICE_REPO", None)
        try:
            with self.assertRaises(RuntimeError):
                de_package_docx.generate_docx(TEMPLATE, "/tmp/x.docx", ["x"])
        finally:
            if old is not None:
                os.environ["GENOFFICE_REPO"] = old


if __name__ == "__main__":
    unittest.main()
