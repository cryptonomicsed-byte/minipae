# minipae — minimal NIP-AE Agent Engrams client

Portable memory for AI agents, implemented in pure Python.

NIP-AE (block/buzz draft, kind:30174) is a wire protocol that lets memory
transfer across ANY platform/framework: agents write signed, NIP-44-encrypted
engrams to a Nostr relay, and any runtime that knows the agent's key can read
or write the same memory. No vendor store, no framework lock-in — memory is
just events on your relays.

## What's inside

- **BIP-340** Schnorr signing/verification (secp256k1, tagged hashes, even-y convention) — pure Python
- **NIP-44 v2** encryption (HKDF conversation key, RFC 8439 ChaCha20, HMAC-SHA256, powers-of-two padding) — pure Python
- **kind:30174** event construction: HMAC d-tags, `p` owner tag, tombstone bodies
- **Head selection** (addressable events, newest per slug wins) + signature validation
- **Relay client** (websockets): publish + query
- **CLI**: `gen-key`, `ls`, `get`, `set`, `rm`, `self-owner`

Verified against the official NIP-44 test vectors and pycryptodome's ChaCha20.

## Usage

```bash
# 1. generate an agent keypair
python3 minipae.py gen-key 2> agent.pub.txt | tee agent.nsec.txt

# 2. write / read / delete memory
export NIPAE_NSEC=$(cat agent.nsec.txt)
export NIPAE_OWNER=$(awk '/pubkey/{print $NF}' agent.pub.txt)   # omit = self-owned
export NIPAE_RELAY=wss://relay.damus.io

python3 minipae.py set mem/values/honesty "be truthful, always"
python3 minipae.py ls
python3 minipae.py get mem/values/honesty
python3 minipae.py rm  mem/values/honesty      # tombstone
```

## Env

| Var | Meaning |
| --- | --- |
| `NIPAE_NSEC` | agent secret key (hex or nsec1...) |
| `NIPAE_OWNER` | owner pubkey hex; defaults to the agent itself (self-owned memory) |
| `NIPAE_RELAY` | relay URL; default `wss://relay.damus.io` |

## Protocol notes (NIP-AE draft)

- Slug grammar: `core` or `mem/[...]` (hierarchical, ≤255 bytes)
- `d` tag = `HMAC-SHA256(K_c, "agent-memory/v1/d-tag" || 0x00 || slug)` — reveals nothing to observers
- `K_c` = NIP-44 conversation key between agent and owner — symmetric, so the
  owner can ALWAYS decrypt everything the agent remembers (governance property)
- Tombstone = body `{"slug": ..., "value": null}`; readers treat the slug as absent
- Richer taxonomies (provenance, trust, working sets) are companion-NIP extensions

## Dependencies

- `cryptography` (AES-GCM not needed anymore — only stdlib crypto used; kept for
  potential future use), `websockets`
- Everything else: Python stdlib

## Tests

```bash
python3 -c "import sys; sys.path.insert(0,'.'); import minipae"  # self-tests inline
```

Run the offline suite (BIP-340 roundtrip, NIP-44 official vectors, padding
boundaries, tamper/wrong-key rejection, head selection) and the live relay
roundtrip (set → ls → get → rm) as shown in the session log.
