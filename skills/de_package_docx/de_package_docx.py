#!/usr/bin/env python3
"""de_package_docx — headless .docx generation via @genoffice/docx-engine.

Phase 4 (plan-v3): "GenOffice document-worker service... de_* vocabulary
day one." Real finding along the way: GenOffice ships as six Electron
desktop apps; the underlying OOXML engines (docx-engine, pptx-engine) are
separate, Electron-free packages, genuinely usable headlessly — but not
published to npm standalone, so this requires a local genoffice clone
(GENOFFICE_REPO env var), not just `npm install`. See
docs/D_PHASE4_GENOFFICE.md for the full finding.

Usage:
  GENOFFICE_REPO=/path/to/genoffice python3 de_package_docx.py \
      <template.docx> <output.docx> <paragraph 1> [<paragraph 2> ...]
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile


def generate_docx(template_path: str, output_path: str, paragraphs: list[str],
                  genoffice_repo: str | None = None) -> dict:
    genoffice_repo = genoffice_repo or os.environ.get("GENOFFICE_REPO")
    if not genoffice_repo:
        raise RuntimeError("GENOFFICE_REPO not set (path to a local genspark-ai/genoffice clone)")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(paragraphs, f)
        paragraphs_path = f.name

    try:
        env = dict(os.environ, GENOFFICE_REPO=genoffice_repo)
        result = subprocess.run(
            ["npx", "--yes", "tsx", os.path.join(script_dir, "generate.ts"),
             template_path, output_path, paragraphs_path],
            capture_output=True, text=True, env=env, cwd=script_dir,
        )
    finally:
        os.unlink(paragraphs_path)

    if result.returncode != 0:
        raise RuntimeError(f"generate.ts failed: {result.stderr.strip() or result.stdout.strip()}")
    return json.loads(result.stdout.strip())


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("usage: de_package_docx.py <template.docx> <output.docx> <paragraph 1> [...]", file=sys.stderr)
        sys.exit(2)
    template, output, *paragraphs = sys.argv[1:]
    res = generate_docx(template, output, paragraphs)
    print(json.dumps(res))
