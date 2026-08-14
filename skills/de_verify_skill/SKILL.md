---
id: de_verify_skill
verb: de_verify
name: Verify a skill against its contract
description: Check that skills/catalog.yaml and its skill entries are internally well-formed - every skill's verb is registered, required frontmatter fields are present, and namespaces referenced are registered in NAMESPACES.md. Reports pass/fail per skill.
version: 1.0.0
status: active
trigger:
  kind: cron
  pattern: "verify the skill catalog"
inputs:
  type: object
  properties:
    skill_id:
      type: string
      description: "verify one skill only; omit to verify the whole catalog"
outputs:
  schema:
    type: object
    properties:
      checked: { type: integer }
      passed: { type: integer }
      failures: { type: array, items: { type: string } }
  artifacts: []
  engrams: []
verification:
  kind: test
  run: "bash skills/de_verify_skill/verify.sh"
  pass_when: "exit 0"
runtimes:
  - runtime: hermes
    invoke: "bash skills/de_verify_skill/verify.sh [skill_id]"
memory:
  reads: []
  writes: []
  namespaces: []
owner: wM
license: MIT
---

# de_verify_skill

## When to use

Before marking any catalog skill `status: active`, or as a cron/CI check
that the catalog hasn't drifted (a skill referencing a verb that got
renamed, a namespace that was never registered, a missing required
frontmatter field).

## Steps

1. Load `skills/catalog.yaml`; confirm `schema: skill-catalog/v1`.
2. For each entry in `skills:`, load its `file`'s YAML frontmatter.
3. Confirm `verb` is one of the registered verbs in `catalog.yaml`.
4. Confirm required frontmatter fields are present (`id`, `verb`, `name`,
   `description`, `version`, `status`, `trigger`, `inputs`, `outputs`,
   `verification`, `runtimes`, `memory`, `owner`).
5. Confirm every namespace in `memory.reads`/`memory.writes` is registered
   in `NAMESPACES.md` (namespace-precedes-first-write rule).
6. Confirm `id` in the frontmatter matches the `id` in `catalog.yaml`'s
   skill index entry (catches copy-paste drift between the two).

## Pitfalls

- This is a *structural* verifier, not a functional one — it does not run
  the skill or check its engram side effects live. A skill's own
  `verification.run` handles that (per the testing protocol: offline +
  live readback). `de_verify_skill` verifies the *catalog entry itself*
  is well-formed, which every other skill's verification depends on being
  true first.
- Don't skip re-running this after any catalog.yaml edit, even a small
  one — YAML typos in `verbs:` silently orphan a skill's `verb:` reference
  with no error until something tries to invoke it.

## Verification steps

`bash skills/de_verify_skill/verify.sh` — exit 0 = every skill in the
catalog is structurally valid. Exit 1 with failures listed otherwise.
Also exercised by `tests/test_skill_catalog.py` in CI.
