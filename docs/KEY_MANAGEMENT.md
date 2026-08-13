# Key Management & Derivation — minipae (NIP-AE) agent keys

Locked plan item 1.6. This spec MUST land before task 1.2 (daemon adapter)
generates its first real per-pair key.

## Credential inventory

| Credential | Scope | Source | Rotation |
|-----------|-------|--------|----------|
| `gtm_...`    | GenTeam machine credential, per computer | GenTeam Computers page | new key from Computers page; update launcher |
| `nsec1` / hex | NIP-AE agent key, per (agent, owner) pair | DERIVED (below) | re-derivation, not re-distribution |
| `cm_agent_...` | CAP agent token (Commonly) | Commonly instance, Phase 2.3 | per Commonly policy |

## Storage

- Agent secrets live in the credential vault (`~/.hermes/credential_vault.json`)
  on each host, or in the `gtstate` Docker volume on the VPS for the daemon.
- NEVER in git repos. The minipae `.gitignore` excludes key artifacts.
- File permissions 0600 / dirs 0700 (already the daemon's convention).

## Derivation scheme (BIP-32-style, per C4)

Rather than random-per-pair keys, agent nsecs are derived from a MASTER
secret via hardened BIP-32 derivation on secp256k1:

```
master  : from BIP39 seed (existing Omo-Koda2 seed, per locked ecosystem decision)
path    : m / 44' / 30174' / <agent_index>' / <owner_index>'
  - 44'        : BIP-44 purpose (coin-agnostic here; format, not network)
  - 30174'     : NIP-AE kind as the application constant
  - agent_index: per-agent index (registry in vault)
  - owner_index: per-owner index (0 = self-owned)
```

The derivation uses hardened children only (apostrophe) so a compromised
per-pair key does not reveal sibling keys or the master.

Rotation = increment a per-pair `revision` component (or bump the index and
re-encrypt the pair's engrams under the new key). No redistribution.

## Reference implementation

The BIP-32 secp256k1 derivation (HMAC-SHA512 chain code, hardened index
`0x80000000 | i`) is implemented in pure Python in `minipae.derive` and
tested in `tests/test_derive.py`. It reuses the same pure-Python secp256k1
point arithmetic already in `minipae.py` — no new dependency.
