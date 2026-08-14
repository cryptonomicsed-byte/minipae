---
id: de_package_docx
verb: de_package
name: Package paragraphs into a real .docx
description: Append one or more text paragraphs to a .docx template and produce a real, valid Word document - headless, no Electron app running. Uses @genoffice/docx-engine directly.
version: 1.0.0
status: active
trigger:
  kind: prompt
  pattern: "package {paragraphs} into a docx for {client}"
inputs:
  type: object
  required: [template_path, output_path, paragraphs]
  properties:
    template_path: { type: string, description: "existing .docx to append to" }
    output_path: { type: string }
    paragraphs: { type: array, items: { type: string } }
outputs:
  schema:
    type: object
    properties:
      ok: { type: boolean }
      output: { type: string }
      bytes: { type: integer }
  artifacts:
    - mime: application/vnd.openxmlformats-officedocument.wordprocessingml.document
      note: "written to output_path"
  engrams: []
verification:
  kind: test
  run: "GENOFFICE_REPO=<path> python3 -m unittest tests.test_de_package_docx -v"
  pass_when: "exit 0 AND the output file is a valid zip containing word/document.xml with the requested paragraph text present (checked directly, not just process exit code)"
runtimes:
  - runtime: hermes
    invoke: "GENOFFICE_REPO=<path> python3 skills/de_package_docx/de_package_docx.py <template> <output> <paragraph>..."
memory:
  reads: []
  writes: []
  namespaces: []
owner: wM
license: MIT
---

# de_package_docx

## When to use

Producing a real .docx deliverable from agent-generated text — the Phase
4 / BPO pilot day-one case ("one agent produces a real client deliverable
end-to-end").

## Steps

1. Have a template `.docx` to start from (any valid docx; a blank one
   works — `docx-engine` parses it and keeps everything except the
   appended paragraphs byte-identical).
2. Call `de_package_docx.py <template> <output> <paragraph 1> [<paragraph 2> ...]`
   with `GENOFFICE_REPO` pointing at a local `genspark-ai/genoffice`
   clone with `npm install` already run (`packages/docx-engine`'s deps —
   `fast-xml-parser`, `jszip`, `utif2` — need to be resolvable; the
   package is not published to npm standalone, see
   `docs/D_PHASE4_GENOFFICE.md`).
3. Each paragraph is appended as a new `w:p` after the template's
   existing visible content; the template's own content is preserved via
   `{kind: 'original', docxIndex}` blocks, unmodified.

## Pitfalls

- **GenOffice's README only documents the Electron desktop apps** — do
  not assume there's a documented headless CLI or server. There isn't
  one (yet); this skill talks directly to the underlying
  `@genoffice/docx-engine` TypeScript package via `tsx`, found by reading
  the actual package source, not the product docs.
- `generateParagraphXml` needs a real `GenerateContext`
  (`allocateHyperlinkRel`, etc.) — this skill's context stubs
  `allocateHyperlinkRel` to throw, so **hyperlinks in generated paragraphs
  are not supported yet**. Plain text only.
- `npx tsx` re-resolves on every call (no persistent process) — fine for
  occasional BPO-pilot-scale document generation, would need a real
  worker process for high-volume use (out of scope for this first skill).

## Verification steps

Structural verification only — confirms the output is a real, valid zip
with `word/document.xml` containing the exact paragraph text requested.
Does not open the file in Word/LibreOffice (no such tooling available in
this environment); a human should still eyeball-open a sample output
before treating a real client deliverable as done, per Phase 4's own
`de_deliver` verification note ("owner confirms artifact").
