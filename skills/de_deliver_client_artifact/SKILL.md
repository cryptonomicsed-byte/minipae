---
id: de_deliver_client_artifact
verb: de_deliver
name: Deliver a client artifact
description: Package {parts} into a real .docx deliverable for {client} via de_package_docx, then write a signed delivery-receipt engram under mem/skills/de_deliver/{client}/.
version: 1.0.0
status: active
trigger:
  kind: prompt
  pattern: "deliver {parts} to {client}"
inputs:
  type: object
  required: [client, template_path, output_path, parts]
  properties:
    client: { type: string }
    template_path: { type: string, description: "existing .docx to append parts to" }
    output_path: { type: string }
    parts: { type: array, items: { type: string } }
outputs:
  schema:
    type: object
    properties:
      artifact: { type: object, description: "de_package_docx's own result: {ok, output, bytes}" }
      receipt: { type: object, description: "{slug, published: {ok, message}}" }
  artifacts:
    - mime: application/vnd.openxmlformats-officedocument.wordprocessingml.document
      note: "via de_package_docx (GenOffice's real docx-engine)"
  engrams:
    - write: "mem/skills/de_deliver/<client>/<digest>"
      provenance: { source: "de_deliver_client_artifact", created_by: "<agent pubkey>" }
verification:
  kind: test
  run: "GENOFFICE_REPO=<path> python3 -m unittest tests.test_de_deliver -v"
  pass_when: "exit 0 AND the receipt engram is independently readable via minipae.py get/ls on the publishing relay, showing the exact client/parts/artifact_bytes recorded"
runtimes:
  - runtime: hermes
    invoke: "GENOFFICE_REPO=<path> NIPAE_NSEC=<key> python3 skills/de_deliver_client_artifact/de_deliver_client_artifact.py <client> <template> <output> <part>..."
memory:
  reads: []
  writes: ["mem/skills/de_deliver/*"]
  namespaces: ["mem/skills/*"]
owner: wM
license: MIT
---

# de_deliver_client_artifact

## When to use

The BPO pilot day-one case (plan-v3 4.2): "one agent produces a real
client deliverable end-to-end." Wraps `de_package_docx` (document
generation) with the delivery-receipt half — the two are separate skills
because generation and delivery are separately verifiable and reusable
(a future `de_package_pptx` could plug into the same receipt pattern
without duplicating it).

## Steps

1. Have a template `.docx` and the text parts to deliver (same
   requirements as `de_package_docx` — see that skill's own pitfalls,
   particularly the `GENOFFICE_REPO` external-dependency requirement).
2. Call `de_deliver_client_artifact.py <client> <template> <output> <part 1> [...]`.
   Internally: generates the real artifact via `de_package_docx.generate_docx()`,
   then builds and publishes a receipt engram recording client, parts,
   artifact size, and delivery timestamp.
3. The receipt slug is `mem/skills/de_deliver/<client>/<digest>` — a
   16-hex digest derived from `client:output_path:timestamp`, so repeated
   deliveries to the same client don't collide.

## Pitfalls

- **Namespace note**: the original design sketch in
  `docs/SKILL_CATALOG.md` used `mem/genteam/computer/<machine_id>/deliveries/<client>`
  for the receipt — that would have violated `NAMESPACES.md`'s ownership
  rule (this skill isn't the genteam-daemon adapter, so it can't write
  into `mem/genteam/*`). Uses `mem/skills/de_deliver/*` instead, which was
  already reserved for exactly this kind of skill-produced engram at
  Phase 3.2.
- The receipt is written **plaintext-published** (`minipae.publish`, not
  `publish_authenticated`) to a public relay by default
  (`wss://relay.damus.io`) — same NIP-44 encryption as any other engram
  (owner-only decryptable), just no NIP-42 auth needed for a standard
  public relay. If delivering through an auth-gated relay (like
  `buzz-prod-relay-1`), swap in `publish_authenticated` — not done here
  since the BPO pilot's actual target relay isn't decided yet.
- Delivery does not currently verify the artifact opens correctly in
  Word/LibreOffice — same limitation as `de_package_docx`, stated there,
  inherited here.

## Verification steps

Offline: `build_receipt_body()` is a pure function, fully unit tested
(slug shape, uniqueness, provenance, delivery details in the value).
Live (requires `GENOFFICE_REPO` + network): generates a real artifact,
publishes a real receipt engram, and an independent readback (separate
`minipae.py get`/`query` call, not trusting the publish response alone)
confirms the exact content — this is the standard this whole plan holds
every live claim to, not a special exception for this skill.
