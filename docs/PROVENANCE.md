# Engram Provenance-Tag Schema (plan task 1.5, D4 deliverable)

Specified NOW (per negotiation — the partner's accepted pushback) so Crucible
can evaluate engram-backed claims without retrofitting. Memory bus stays
unfiltered storage; provenance tags make claims *evaluable*, not gated.

## Design constraint

NIP-AE body fields are permissive ("bodies MAY contain fields beyond those
defined; unknown fields MUST be ignored") — provenance rides in body fields,
NOT new tags. This keeps a stock relay (which only sees kind/`d`/`p` tags)
agnostic and lets unknown-kind viewers skip decryption. The `d`-tag remains
pure HMAC(slug); no slug/provenance leakage to observers.

## Body shape (memory body, extended)

```jsonc
{
  "slug": "mem/genteam/computer/<id>/last-turn",
  "value": "<utf-8 string>",
  "provenance": {
    "schema": "nip-ae-provenance/v1",
    "source": "genteam-daemon",          // producer adapter
    "source_version": "0.13.0",
    "created_by": "<pubkey hex of agent that originated the content>",
    "created_at": 1723512345,            // origin unix time (may differ from event created_at)
    "turn_id": "<GenTeam turn id or hermes session id>",
    "claim_refs": ["<engram slug or event id of the claim this supports>"],
    "falsifier": {                       // OPTIONAL — present only if a Crucible falsifier applies
      "module_digest": "<sha256 of falsifier wasm>",
      "manifest_digest": "<sha256 of manifest>",
      "purity": "pure"                   // "pure" | "impure" (per Crucible falsifier manifest)
    },
    "witness_note": "single-agent output; not yet cross-verified"  // OPTIONAL free text
  }
}
```

## Field rules

- `schema` REQUIRED and must be `nip-ae-provenance/v1` for this version.
  Future revisions bump it; readers MUST ignore unknown schemas' extra fields.
- `source` / `source_version` REQUIRED (adapter + version that wrote the engram).
- `created_by` REQUIRED — the *content* originator pubkey (may differ from the
  event author pubkey in relayed/re-encrypted cases).
- `created_at` REQUIRED (origin time).
- `turn_id` OPTIONAL — links the engram to a specific turn/session in the
  producing runtime.
- `claim_refs` OPTIONAL — slugs or event ids of engrams this value supports or
  contradicts. This is the edge Crucible walks to assemble belief.
- `falsifier` OPTIONAL — present when the value is a claim that can be falsified.
  `module_digest` + `manifest_digest` are SHA-256 hex; `purity` mirrors the
  Crucible falsifier manifest field.
- `witness_note` OPTIONAL — free text, never machine-trusted.

## Crucible mapping

| Crucible kind  | Engram role                                        |
|----------------|----------------------------------------------------|
| 47001 claim    | engram with `provenance.falsifier` + `claim_refs`  |
| 47002 attestation | cross-verified engram with `witness_note`       |
| 47007 falsifier-manifest | engram whose value embeds the manifest     |

A Crucible prober reads engrams under a claim's `claim_refs`, checks the
`falsifier` block, runs the module, and records 47002. `n_eff` uses
`created_by` (distinct originators) — NOT event authors — so relayed copies
don't inflate witness counts.

## Writer responsibility (per adapter)

- Daemon adapter (1.2): `source=genteam-daemon`, `created_by` = the agent
  pubkey, `turn_id` = daemon turn id.
- Hermes adapter (1.3): `source=hermes`, `created_by` = hermes agent pubkey,
  `turn_id` = session id.
- Never fabricate `created_by`; if the runtime does not have a stable agent
  pubkey, omit `created_by` and set `witness_note` accordingly (missing
  `created_by` means the engram cannot contribute to n_eff).

## Addendum: `content_trust_class` for the Phase 3 merged read view (3.3)

Added per the orchestrator's endorsement of the confidentiality-model
mismatch flagged in `docs/D3_NIP98_ENVELOPE_DECISION.md`: minipae engrams
are NIP-44-encrypted (owner-only decryptable) by protocol; Crucible claims
(kinds 47001-47007, see that repo's `crates/crucible-core/src/claim.rs`)
are intentionally plaintext NIP-01 events, visible to the whole Buzz
community, because falsifiability requires public checkability. These are
opposite confidentiality models sitting under one merged view — the view
must label which class each entry belongs to, never present them
uniformly.

New OPTIONAL body field, backward-compatible with `nip-ae-provenance/v1`
(NIP-AE's own permissive-body-fields rule means old readers ignore it
safely — no schema version bump needed):

```jsonc
"provenance": {
  // ...existing v1 fields...
  "content_trust_class": "private"   // "private" | "public"
}
```

- `"private"` — the default for every minipae-native engram. The engram
  itself is always NIP-44-encrypted regardless of this field (that's the
  transport, not the content's origin visibility); `"private"` here means
  the *underlying content* is also private — the common case (Hermes
  memory, daemon state, anything an adapter wrote directly from its own
  runtime's data).
- `"public"` — set ONLY on an engram that mirrors or points at content
  whose origin is inherently public, e.g. a future adapter that projects
  a Crucible claim/attestation's existence into `mem/buzz/*` for
  discoverability. The engram wrapper is still NIP-44-encrypted (only the
  owner can read the *pointer*), but the field records that the
  underlying claim it references is public on the Buzz relay to anyone
  admitted to that community — so a reader must not treat decrypting the
  engram as equivalent to the content being confidential.
- RECOMMENDED (not required) for any engram carrying `claim_refs` or a
  `falsifier` block, since those are exactly the entries most likely to
  reference Crucible-side public content.
- Omitted = `"private"` by default. No existing adapter (1.2/1.3) needs to
  change; this only matters once a Buzz-facing adapter (`mem/buzz/*`,
  currently `planned` in `NAMESPACES.md`) exists.

**3.3 obligation**: the merged read view MUST render `content_trust_class`
per entry (e.g., a visible badge/tag in any UI, a field in any API
response) and MUST NOT merge private and public entries into a single
undifferentiated feed. This is a design constraint on 3.3's implementation,
not just documentation — noting it here now, before 3.3 is built, so it
isn't retrofitted after a merged view already ships without the
distinction.
