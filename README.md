# minipae — portable agent memory over Nostr (NIP-AE, kind:30174)

Portable memory for AI agents, implemented in pure Python.

NIP-AE (block/buzz draft, kind:30174) is a wire protocol that lets memory
transfer across ANY platform/framework: agents write signed, NIP-44-encrypted
engrams to a Nostr relay, and any runtime that knows the agent's key can read
or write the same memory. No vendor store, no framework lock-in — memory is
just events on your relays.

This repo is the reference implementation plus a set of real, live-verified
integrations built on top of it (bridge agent, skills, cross-relay proof,
runtime registry). See `PLAN.md` for the full phase-by-phase build record and
what's genuinely done vs. still open.

## What's inside

**Core protocol library (`minipae.py`)**
- **BIP-340** Schnorr signing/verification (secp256k1, tagged hashes, even-y convention) — pure Python
- **BIP-173** bech32 (`nsec`/`npub` encode+decode) — pure Python
- **NIP-44 v2** encryption (HKDF conversation key, RFC 8439 ChaCha20, HMAC-SHA256, powers-of-two padding) — pure Python
- **NIP-42** relay AUTH (kind:22242 challenge/response) — `build_auth_event`, `publish_authenticated`, `query_authenticated`
- **NIP-65** relay lists — `fetch_relay_list`, `relays_for_read/write`, `build_relay_list_event`
- **kind:30174** event construction: HMAC d-tags, `p` owner tag, tombstone bodies
- **Head selection** (addressable events, newest per slug wins) + signature validation
- **Relay client** (websockets): publish + query, multi-relay `query_multi`, streaming `subscribe_stream`
- **Pre-connected-socket support** (`connect_url=`) for relays that do Host-header virtual routing or where the logical relay identity's TLS scheme doesn't match the reachable network path
- **Local sync cache**: `load_cache`, `save_cache`, `merge_heads`, `cache_since`, `synced_heads`
- **CLI**: `gen-key`, `ls`, `get`, `set`, `rm`, `self-owner`

Verified against the official NIP-44 test vectors and pycryptodome's ChaCha20.

**Live integrations built on the core library**
- `ga_bridge.py` — a real, SDK-connected OpenAgents↔Buzz bridge agent. Mirrors
  OpenAgents channel messages into authenticated `mem/ga/channel/<channel>/<event_id>`
  engrams on a production Buzz relay. Runs as a supervised long-lived Docker
  service (`restart: unless-stopped`), not a one-shot script. See
  `docs/D_2_2_GA_BRIDGE.md` for the full build/debug record.
- `cross_relay_read.py` — proves engrams are portable across relays (write on
  one, read correctly on another).
- `cap_bridge.py` — deterministic HKDF-derived CAP webhook secret from a Buzz
  seckey (symmetric-bearer identity bridge, explicitly not a cryptographic
  identity upgrade to CAP itself — see `docs/D_2_4_CAP_IDENTITY_BRIDGE.md`).
- `hermes_adapter.py`, `daemon_adapter.py` — mirror genteam-daemon/Hermes
  runtime state into `mem/genteam/*` engrams.
- `merged_view.py` — namespace + trust-class separation so private
  NIP-44-encrypted engrams and intentionally-public Crucible claims never get
  flattened into one undifferentiated list.
- `runtime_registry.json` / `docs/RUNTIME_REGISTRY.md` — which runtimes have a
  real, live-checked adapter (`active`) vs. none yet (`planned`).
- `skills/` (`docs/SKILL_CATALOG.md`) — day-one `de_*` skill catalog plus three
  fully working skills: `de_verify_skill` (catalog well-formedness meta-check),
  `de_package_docx` (headless docx generation via GenOffice's engine), and
  `de_deliver_client_artifact` (BPO deliverable + delivery-receipt engram).
- `docker/` — container build for the bridge agent / GenTeam daemon deployment.

**What's real vs. open**: Phases 1–3 of `PLAN.md` are done with live
verification, not just design. Phase 4's two skills are done and live-verified;
the one remaining open item ecosystem-wide is wiring either skill to a real
Vantage broadcast-intent trigger — that trigger's schema isn't defined yet
(tracked with wD/Vantage), not a minipae-side gap.

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
python3 -m pytest tests/ -q
```

70 passed, 4 skipped (the 4 skips need an external `GENOFFICE_REPO` checkout
and are not run in CI without it). Covers BIP-340 roundtrip, NIP-44 official
test vectors, padding boundaries, tamper/wrong-key rejection, head selection,
NIP-42 auth frame parsing against captured live relay frames, the bridge
agent, both live skills, the runtime registry schema, and the merged-view
namespace separation.
