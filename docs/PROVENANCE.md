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
