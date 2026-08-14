// de_package_docx's real generator — headless .docx assembly via
// @genoffice/docx-engine (no Electron app required). Proven against the
// real package source, not assumed from its README (which only documents
// the Electron GUI apps; the engine packages underneath are separately
// usable headlessly — see docs/D_PHASE4_GENOFFICE.md).
//
// Does NOT vendor genoffice's source into this repo — imports it at
// runtime from a local clone via GENOFFICE_REPO, so this skill never goes
// stale relative to upstream and respects genoffice's own repo/license
// boundary (Apache-2.0, but vendoring would still mean carrying a copy
// this repo would have to keep in sync by hand).
//
// Usage: GENOFFICE_REPO=/path/to/genoffice \
//   node --import tsx generate.ts <template.docx> <output.docx> <paragraphs.json>
// paragraphs.json: string[] — one entry per paragraph appended after the
// template's existing content.
import { readFileSync, writeFileSync } from 'fs'

async function main() {
  const genofficeRepo = process.env.GENOFFICE_REPO
  if (!genofficeRepo) {
    console.error(JSON.stringify({ ok: false, error: 'GENOFFICE_REPO env var required (path to a local genspark-ai/genoffice clone)' }))
    process.exit(2)
  }
  const engineSrc = `${genofficeRepo}/packages/docx-engine/src`

  const [templatePath, outputPath, paragraphsJsonPath] = process.argv.slice(2)
  if (!templatePath || !outputPath || !paragraphsJsonPath) {
    console.error('usage: generate.ts <template.docx> <output.docx> <paragraphs.json>')
    process.exit(2)
  }

  const { parseDocx } = await import(`${engineSrc}/parse.ts`)
  const { saveDocx } = await import(`${engineSrc}/patch.ts`)
  const { generateParagraphXml } = await import(`${engineSrc}/generate.ts`)

  const bytes = new Uint8Array(readFileSync(templatePath))
  const parsed = await parseDocx(bytes)

  const visible = parsed.blocks.filter((b: any) => !b.hidden)
  const finalBlocks: any[] = visible.map((b: any) => ({ kind: 'original', docxIndex: b.docxIndex }))

  const ctx = {
    headingStyleIds: new Map(),
    listParagraphStyleId: undefined,
    allocateHyperlinkRel: () => { throw new Error('hyperlinks not supported by this skill yet') },
  }

  const paragraphs: string[] = JSON.parse(readFileSync(paragraphsJsonPath, 'utf-8'))
  for (const text of paragraphs) {
    const block = { type: 'paragraph', runs: [{ text }] }
    finalBlocks.push({ kind: 'xml', xml: generateParagraphXml(block, ctx) })
  }

  const out = await saveDocx(parsed, finalBlocks, {})
  writeFileSync(outputPath, out)
  console.log(JSON.stringify({ ok: true, output: outputPath, bytes: out.length }))
}

main().catch((e) => {
  console.error(JSON.stringify({ ok: false, error: String(e) }))
  process.exit(1)
})
