# SKILL_CATALOG.md — shared skill catalog schema (Phase 3.2 feed)

Status: RESEARCH / DESIGN ONLY. No implementation in this lane (role split per
ORCHESTRATION.md). This doc is the design substrate for Phase 3.2 ("shared
skill catalog, de_* verb vocabulary as tool contract"); the coding panes
implement the catalog files + loader when 3.2 lands.

Goal: ONE catalog format that every runtime in the fleet (genteam-daemon,
OpenClaw, Hermes, Vantage — plus OpenAgents/Commonly on the dispatch layer)
can publish skills against, discover skills from, and invoke — with a
verification contract that matches the project's testing protocol (offline
tests, live readback, cross-relay; panels never self-certify).

---

## 1. Design constraints & references (this research pass)

Anchors, in priority order:

1. **Hermes SKILL.md format** — live in this session (frontmatter: `name`,
   `description`, `category`; body: when-to-use, numbered steps, pitfalls,
   verification steps). Hermes is the orchestrator/tester; its skill format
   is the de-facto human+agent-readable baseline.
2. **OpenClaw skill model** — `openclaw skill install .` + `openclaw start`;
   SKILL.md-based skills with channels + receipt chain (The-Aether
   `backends/openclaw.js` shows the exact generated shape: Description /
   Capabilities / Installation / Usage / Gateway / Receipt Chain / Ethics).
3. **Plugin manifest pattern** (omokoda-ecosystem): every plugin ships
   `manifest.json`, health endpoint, API-key auth, rate limiting, OpenAPI.
   Skills are lighter than plugins, but the manifest discipline carries over.
4. **NIP-89 handler advertisement** (kind 31990): capabilities advertised as
   self-authored signed events that other agents query — no central directory,
   hot-swappable by design. The catalog can be *mirrored* to NIP-89 later;
   the repo catalog is the source of truth first.
5. **NIP-AE + NAMESPACES.md + PROVENANCE.md**: a skill's memory contract is
   expressed as engram slugs under owned namespaces, with provenance tags —
   so a skill's side effects are auditable and falsifiable, exactly like
   every other bus write.
6. **NIP-90's collapse** (session-learned): one giant meta-standard died from
   scope. Lesson: keep the catalog a *minimal contract*; skills are
   self-contained and hot-swappable; verbs are narrow and purpose-specific.
7. **External reference (flagged, NOT yet adopted)**: deepseek-ai/
   deepseek-harness ships a skill registry + catalog. It is an eval candidate
   (ORCHESTRATION §Flagged candidate; snapshot tests pending on the VPS,
   Fold-side repo). This schema intentionally anchors on in-house formats so
   the bus does not depend on an unvetted external schema; at 3.2
   implementation time, cross-check deepseek-harness's registry/catalog shape
   and adopt any compatible conventions (e.g. plugin seams) without
   replacing the contract below.

In-house precedents for "bundled catalog of descriptors": oh-my-pi
`packages/catalog` (bundled JSON + provider descriptors) and openhuman
`skill_registry` (Rust skill setup per agent) — different domains, same
pattern: a schema-versioned descriptor set that agents consume at runtime.

## 2. The de_* verb vocabulary (the tool contract)

`de_` = **deliverable-verb**. A verb is a STABLE CONTRACT (name, inputs,
outputs, verification obligation). A skill is an IMPLEMENTATION of a verb on
a specific runtime. One verb may have several skill implementations across
runtimes; the catalog binds verb → implementation. This is what makes the
vocabulary a *tool contract*: any dispatcher (Phase 2 layer) can route to
"whoever implements de_draft" without knowing runtime details.

Proposed day-one verbs (aligned with Phase 4: GenOffice and the BPO pilot
speak de_* from day one):

| verb | contract (what it must do) |
|------|----------------------------|
| `de_draft` | produce a first-draft artifact from inputs (topic, audience, constraints) |
| `de_review` | critique an artifact; return structured findings (strengths, issues, verdict) |
| `de_deliver` | package + deliver a final artifact; write a delivery receipt engram |
| `de_verify` | run the verification contract of another skill; report evidence (pass/fail + artifacts) |
| `de_document` | generate documentation from a codebase/session/artifact |
| `de_summarize` | structured summary of a source (transcript, thread, document) |
| `de_transcribe` | audio → text (note: Vantage local instance has ffmpeg; remote does not) |
| `de_research` | gather + cite evidence for a question; emit claim_refs per PROVENANCE.md |
| `de_plan` | decompose a goal into steps with owners and checkpoints (plan-v3 style) |
| `de_package` | assemble a deliverable bundle (e.g. .docx via GenOffice) from parts |

Governance: verbs are added/renamed/deprecated by plan amendment only
(locked-plan discipline). Skills are added freely by their owner pane, but a
skill may only claim a verb it satisfies — verification evidence required
before `status: active` (matches "panels never self-certify").

## 3. Catalog format

### 3.1 Layout

```
skills/
  catalog.yaml              # the catalog: header + verb registry + skill index
  <skill-id>/SKILL.md       # human/agent-readable skill (Hermes-SKILL.md style)
  <skill-id>/schema.json    # inputs JSON Schema (mirrors frontmatter.inputs)
  <skill-id>/verify.sh      # verification runner (exit 0 = pass) — optional
```

### 3.2 catalog.yaml

```yaml
schema: skill-catalog/v1
revision: 3                          # bump on any catalog change; pin in consumers
verbs:                               # the de_* registry (contracts, not implementations)
  - verb: de_draft
    description: produce a first-draft artifact from inputs
    inputs: object
    outputs: [artifact, engram]
    verification: required
  # ... de_review, de_deliver, de_verify, de_document, de_summarize,
  #     de_transcribe, de_research, de_plan, de_package
skills:
  - id: de_draft_memo
    file: skills/de_draft_memo/SKILL.md
    verb: de_draft
    runtimes: [hermes, openclaw]
    status: active
```

### 3.3 Skill entry — SKILL.md frontmatter (the contract)

```yaml
---
id: de_draft_memo                      # stable slug: <verb>_<object>
verb: de_draft                         # MUST be a registered de_* verb
name: Draft a memo
description: Write a memo draft for {topic} and {audience}; saves draft + engram.
version: 1.0.0
status: active                         # draft | active | deprecated
trigger:
  kind: prompt                         # prompt | webhook | mcp | cron | turn
  pattern: "draft a memo about {topic} for {audience}"
inputs:                                # JSON Schema (draft-07), inline or $ref schema.json
  type: object
  required: [topic]
  properties:
    topic:    { type: string, description: "memo subject" }
    audience: { type: string, enum: [exec, team, client], default: team }
    max_words: { type: integer, minimum: 50, maximum: 2000 }
outputs:
  schema:
    type: object
    properties:
      draft_path: { type: string }
      word_count: { type: integer }
  artifacts:
    - mime: text/markdown
      note: "draft written to <draft_path>"
  engrams:
    - write: "mem/skills/de_draft/memo/<sha256-of-inputs-16>"
      provenance: { source: "<runtime source per RUNTIME_REGISTRY>", created_by: "<agent pubkey>" }
verification:                          # REQUIRED before status: active
  kind: test                           # test | oracle | probe | assert
  run: "bash skills/de_draft_memo/verify.sh"
  pass_when: "exit 0 AND orchestrator minipae ls/get readback shows the engram"
runtimes:
  - runtime: hermes
    invoke: "hermes skill <id> or tool; NIPAE_NSEC from vault; relay wss://relay.primal.net"
  - runtime: openclaw
    invoke: "openclaw skill install ./skills/de_draft_memo && openclaw start"
  - runtime: vantage
    invoke: "MCP tool de_draft_memo (when buzz_bridge adapter lands)"
  - runtime: genteam
    invoke: "turn phrase (out of scope day one — record intent only)"
memory:
  reads: ["mem/values/*"]
  writes: ["mem/skills/de_draft/*"]
  namespaces: ["mem/skills/*"]          # proposal; register in NAMESPACES.md at 3.2
owner: wD                                # pane responsible
license: MIT
---

# Body (Hermes-SKILL.md style)
## When to use
## Steps (numbered)
## Pitfalls
## Verification steps
```

Field rules:

- `id` is immutable once published; changes = new id + deprecate old.
- `verb` MUST exist in `catalog.yaml` verbs (else invalid).
- `inputs`/`outputs` are machine-checkable JSON Schemas — this is what makes
  the catalog invocable by any runtime without per-runtime glue.
- `trigger.pattern` is a hint for prompt/turn dispatch, never a hard
  contract; `kind` is the contract (webhook/mcp/cron are machine-enforced).
- `verification` is REQUIRED for `status: active` and MUST reference an
  executable runner (or a named oracle) plus a `pass_when` that involves
  orchestrator readback for any engram side effects.
- `runtimes[].invoke` is per-runtime invocation detail; `runtimes` entries
  are the 3.1 registry `runtime_id`s, so the catalog and the registry stay
  cross-validated.
- `memory` section must only reference NAMESPACES.md-owned namespaces; new
  namespaces (e.g. `mem/skills/*`) are registered in the same change set
  (NAMESPACES.md rule: namespace precedes first write).

### 3.4 Verification contract (how "verification" is judged)

Every active skill must satisfy, per the ORCHESTRATION testing protocol:

1. offline: the verification runner passes locally (tests in repo);
2. live: any engram the skill writes is read back by the orchestrator
   (`minipae.py ls`/`get`) showing real content — never self-certified;
3. cross-relay (when applicable): write on relay A, read on relay B;
4. provenance: written engrams carry `source`/`source_version`/`created_by`
   per PROVENANCE.md; skills producing claims SHOULD emit `claim_refs` and may
   carry a `falsifier` block (Crucible-ready).

A skill that stops passing verification is demoted to `status: draft` until
fixed — the catalog is a live contract, not an archive.

## 4. Example entries

### de_deliver (BPO pilot — Phase 4 day-one surface)

```yaml
---
id: de_deliver_client_artifact
verb: de_deliver
name: Deliver a client artifact
description: Package {parts} into a deliverable for {client}, write a delivery receipt.
version: 0.1.0
status: draft
trigger: { kind: webhook, pattern: "deliver {parts} to {client}" }
inputs:
  type: object
  required: [client, parts]
  properties:
    client: { type: string }
    parts:  { type: array, items: { type: string, format: uri } }
outputs:
  artifacts:
    - mime: application/vnd.openxmlformats-officedocument.wordprocessingml.document
      note: "via GenOffice de_package"
  engrams:
    - write: "mem/genteam/computer/<machine_id>/deliveries/<client>"
      provenance: { source: "<registry source>", created_by: "<agent pubkey>" }
verification:
  kind: oracle
  run: "delivery receipt engram readable by owner key; artifact opens (docx validation)"
  pass_when: "orchestrator readback shows receipt; owner confirms artifact"
runtimes:
  - runtime: genteam
    invoke: "turn producing the deliverable, adapter writes receipt"
  - runtime: hermes
    invoke: "hermes skill de_deliver_client_artifact"
owner: wM
---
```

### de_verify (the meta-skill — verifies other skills)

```yaml
---
id: de_verify_skill
verb: de_verify
name: Verify a skill against its contract
description: Run the verification contract of {skill_id} and report evidence.
version: 1.0.0
status: active
trigger: { kind: cron, pattern: "verify {skill_id}" }
inputs:
  type: object
  required: [skill_id]
  properties:
    skill_id: { type: string, pattern: "^de_[a-z_]+$" }
outputs:
  engrams:
    - write: "mem/skills/verification/<skill_id>/<rev>"
verification:
  kind: test
  run: "bash skills/de_verify_skill/verify.sh"
  pass_when: "exit 0 AND output JSON has evidence[] with pass=true per check"
runtimes:
  - runtime: hermes
    invoke: "orchestrator testing protocol (default)"
owner: hermes-orchestrator
---
```

## 5. Distribution & discovery

- Source of truth: `skills/` in the minipae repo (git = audit trail, same as
  the runtime registry).
- Discovery within a runtime: runtime-specific (Hermes skill list, OpenClaw
  `openclaw skill list`, Vantage Genesis "discover by skill").
- Cross-runtime discovery (optional, later): NIP-89 style advertisement — a
  kind 31990 event per skill (d-tag = skill id, content = catalog entry),
  so agents on the bus can query "who implements de_draft" against the
  relays. Mirror, never replace, the repo catalog.
- Versioning: catalog `revision` pinning; consumers declare
  `catalog_revision` in their registry entry (RUNTIME_REGISTRY §3) so the
  bus knows which contract generation a runtime was verified against.

## 6. Open questions for the 3.2 implementers

1. Catalog as repo files (above) vs catalog published as NIP-AE engrams
   (`mem/skills/catalog` etc.) — repo-first recommended; engram mirror after
   the first cross-runtime verification.
2. `mem/skills/*` namespace registration (NAMESPACES.md amendment) must land
   in the same change set as the first skill that writes engrams.
3. Verb governance: who approves a new `de_*` verb — propose a lightweight
   rule now (owner pane proposes, orchestrator tests, plan amendment locks)
   so 3.2 doesn't stall on process.
4. Cross-check deepseek-harness catalog conventions at implementation time
   (eval pending; do not block on it).
5. Mapping of existing runtime-native skills (Hermes skills, OpenClaw skills)
   into catalog entries: start with the de_* day-one set only; do NOT try to
   catalog every existing skill in the first pass (NIP-90 lesson — narrow).
