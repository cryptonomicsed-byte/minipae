#!/usr/bin/env python3
"""cross_relay_read — plan task 1.4 cross-relay demo (VPS side).

Reads mem/genteam/* engrams published by the Fold 4 daemon adapter,
merged across multiple relays, proving portability: this script shares
no code with daemon_adapter.py beyond minipae.py itself (the whole point
of NIP-AE — memory transfers across machines/runtimes via the relay, not
via a shared framework).

Key handling (per docs/KEY_MANAGEMENT.md): this script only ever reads
NIPAE_NSEC from the environment. It never accepts a key via argv and
never writes one to disk. On the VPS, NIPAE_NSEC must be sourced from the
gtstate Docker volume (copied in via the helper-container chown uid-1001
pattern, or re-derived from the master via minipae.derive using the same
agent_index/owner_index Fold 4 used) — never placed on host disk.

For SELF-OWNED daemon state (owner == agent, the current default in
daemon_adapter.py), decrypting requires the literal same secret key that
published it — ECDH(sk, pubkey(sk)) cannot be reproduced from the public
key alone. So this only proves cross-relay portability (different
machine, different process, same key material), not cross-identity
reads; that is a separate, harder property this demo does not claim.

Usage:
  NIPAE_NSEC=<Fold-4 daemon agent's hex or nsec1 key> \
      python3 cross_relay_read.py [--machine <machine_id>] \
                                   [--relays wss://relay.damus.io,wss://relay.primal.net]

Exit code 0 with at least one decoded mem/genteam/* entry printed is the
proof-of-portability signal for 1.4's success criterion.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import minipae as m

DEFAULT_RELAYS = ["wss://relay.damus.io", "wss://relay.primal.net"]
NAMESPACE_PREFIX = "mem/genteam/"


def load_key() -> tuple[bytes, bytes]:
    nsec = os.environ.get("NIPAE_NSEC", "").strip()
    if not nsec:
        print("NIPAE_NSEC required (must come from the gtstate volume / vault, "
              "never argv, never host disk) — see docs/KEY_MANAGEMENT.md", file=sys.stderr)
        sys.exit(2)
    sk = m.nsec_decode(nsec) if nsec.startswith("nsec1") else bytes.fromhex(nsec)
    owner_hex = os.environ.get("NIPAE_OWNER", "").strip()
    owner = bytes.fromhex(owner_hex) if owner_hex else m.pubkey_from_secret(int.from_bytes(sk, "big"))
    return sk, owner


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--machine", default=None,
                    help="filter to mem/genteam/computer/<machine>/* only")
    ap.add_argument("--relays", default=",".join(DEFAULT_RELAYS))
    args = ap.parse_args()

    sk, owner = load_key()
    agent_pub = m.pubkey_from_secret(int.from_bytes(sk, "big"))
    kc = m.conversation_key(sk, owner)
    relays = [r.strip() for r in args.relays.split(",") if r.strip()]

    print(f"[cross-relay-read] querying {relays} for agent {agent_pub.hex()}", file=sys.stderr)
    events = asyncio.run(m.query_multi(relays, [agent_pub.hex()]))
    heads = m.select_heads(events, kc)

    want_prefix = NAMESPACE_PREFIX
    if args.machine:
        want_prefix = f"{NAMESPACE_PREFIX}computer/{args.machine}/"

    found = 0
    for dtag, ev in sorted(heads.items()):
        try:
            body = m.decode_body(ev, kc)
        except Exception:
            continue
        slug = body.get("slug", "")
        if not slug.startswith(want_prefix):
            continue
        if body.get("value") is None:
            continue  # tombstoned
        found += 1
        prov = body.get("provenance", {})
        print(f"{slug}")
        print(f"  value:      {body.get('value')}")
        print(f"  source:     {prov.get('source')} v{prov.get('source_version')}")
        print(f"  created_by: {prov.get('created_by')}")
        print(f"  created_at: {prov.get('created_at')}")
        print()

    print(f"[cross-relay-read] {found} mem/genteam/* entries decoded across {len(relays)} relays",
          file=sys.stderr)
    sys.exit(0 if found > 0 else 1)


if __name__ == "__main__":
    main()
