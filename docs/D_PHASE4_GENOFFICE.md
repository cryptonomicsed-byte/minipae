# Phase 4 — GenOffice finding + de_package_docx

## The finding

Plan-v3 describes Phase 4 as "GenOffice document-worker service on VPS
(headless, API: generate/edit docx/xlsx/pptx from agent instructions)."
Cloned the real repo (`genspark-ai/genoffice`) to check this against
source before designing anything — **GenOffice's README only documents
six Electron desktop GUI apps** (macOS/Windows/Linux installers), not a
headless service or CLI. Taken at face value, this looked like it might
block Phase 4's premise entirely.

It doesn't. `packages/` splits the product into engine libraries
(`docx-engine`, `pptx-engine`, `agent-core`, etc.) and the Electron shell
separately. `docx-engine` has zero Electron dependency — three plain npm
deps (`fast-xml-parser`, `jszip`, `utif2`) — and is genuinely usable
headlessly. Verified this by actually running it, not just reading:
parsed a real fixture (`fixtures/generated/simple.docx`), generated a new
paragraph via the real `generateParagraphXml`/`saveDocx` API, wrote a
real `.docx`, and confirmed structurally (valid zip, `word/document.xml`
present, contains the exact text requested).

**One real constraint**: `@genoffice/docx-engine` is not published to npm
standalone (`npm view` → 404) — it's a workspace-internal package. Using
it headlessly requires a local clone of the full `genoffice` monorepo
with `npm install` run (827 packages, ~1 minute), not a lightweight
`npm install @genoffice/docx-engine`.

## What got built

`skills/de_package_docx/` — a real, tested skill:

- `generate.ts`: dynamically imports `docx-engine`'s `parse`/`patch`/
  `generate` modules from a `GENOFFICE_REPO` path at runtime — **does not
  vendor genoffice's source into this repo**, so it can't go stale
  relative to upstream and doesn't duplicate Apache-2.0 code this repo
  would otherwise have to keep in sync by hand.
- `de_package_docx.py`: Python wrapper (subprocess → `npx tsx
  generate.ts`), matching the `hermes_adapter.py` pattern of shelling out
  to an external CLI rather than reimplementing it.
- `SKILL.md`: registered as `de_package_docx` implementing the `de_package`
  verb in `skills/catalog.yaml`, passes `de_verify_skill`'s structural
  checker.
- `tests/test_de_package_docx.py`: 3 tests, skip gracefully (not fail) if
  `GENOFFICE_REPO` isn't set — matches the "external dependency, not
  vendored" reality rather than pretending it's always available. Run for
  real against the actual cloned+installed repo: all 3 pass, output
  verified structurally (valid docx, exact requested text present in
  `word/document.xml`).

## What this does NOT prove

- Not tested against Word/LibreOffice directly — no such tooling in this
  environment. Structural validation (valid zip, correct core part,
  exact text present) is real evidence but isn't the same as "Word opens
  it without complaint." `SKILL.md`'s verification section says so
  explicitly and recommends a human open a sample output before treating
  a real client deliverable as done — matches Phase 4's own `de_deliver`
  verification note ("owner confirms artifact").
- Hyperlinks aren't supported in generated paragraphs yet
  (`allocateHyperlinkRel` is stubbed to throw) — plain text only. Real
  scope boundary, stated in `SKILL.md`, not silently dropped.
- No VPS deployment of this — it's a skill invoked on-demand (subprocess),
  not a running service. Whether Phase 4 still wants a persistent
  "document-worker service" (vs. an on-demand skill invocation, which is
  what actually got built) is worth an explicit decision, not assumed
  either way.

## BPO pilot status

This closes the concrete half of plan-v3's Phase 4 success criterion
("a Vantage agent can produce a real .docx deliverable from a broadcast
intent") at the document-generation layer — the missing piece is wiring
this skill to an actual Vantage broadcast-intent trigger, which depends
on Vantage's own adapter work (not yet built, per
`runtime_registry.json`'s `vantage` entry, `status: planned`). Document
generation itself is real and proven; the end-to-end BPO pilot still
needs that wiring on the Vantage side.
