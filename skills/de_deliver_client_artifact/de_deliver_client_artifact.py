#!/usr/bin/env python3
"""de_deliver_client_artifact — package parts into a real .docx deliverable
for a client and write a signed delivery-receipt engram.

Phase 4 (plan-v3 4.2, "BPO pilot"). Wraps de_package_docx (the real
GenOffice-backed generator, see docs/D_PHASE4_GENOFFICE.md) rather than
reimplementing document generation, and writes the receipt under
mem/skills/de_deliver/* — NOT mem/genteam/* as the original design
example in docs/SKILL_CATALOG.md sketched, which would have violated
NAMESPACES.md's ownership rule (this skill isn't the genteam-daemon
adapter). mem/skills/* was already registered `planned` in NAMESPACES.md
at 3.2; this is its first real writer, so it flips to `active` here.

Usage:
  GENOFFICE_REPO=/path/to/genoffice NIPAE_NSEC=<key> [NIPAE_OWNER=<pubkey>] \
  [NIPAE_RELAY=wss://relay.damus.io] \
      python3 de_deliver_client_artifact.py <client> <template.docx> <output.docx> <part 1> [<part 2> ...]
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "de_package_docx"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import de_package_docx
import minipae as m


def build_receipt_body(client: str, output_path: str, parts: list[str],
                       agent_pub_hex: str, artifact_bytes: int) -> dict:
    """Pure function: the delivery-receipt engram body. Separated from the
    live generate+publish calls so it's unit-testable offline."""
    digest = hashlib.sha256(f"{client}:{output_path}:{time.time()}".encode()).hexdigest()[:16]
    slug = f"mem/skills/de_deliver/{client}/{digest}"
    return {
        "slug": slug,
        "value": json.dumps({
            "client": client,
            "output_path": output_path,
            "parts": parts,
            "artifact_bytes": artifact_bytes,
            "delivered_at": int(time.time()),
        }),
        "provenance": {
            "schema": "nip-ae-provenance/v1",
            "source": "de_deliver_client_artifact",
            "source_version": "1.0.0",
            "created_by": agent_pub_hex,
            "created_at": int(time.time()),
        },
    }


def deliver(client: str, template_path: str, output_path: str, parts: list[str],
           sk: bytes, owner: bytes, relay: str, genoffice_repo: str | None = None) -> dict:
    """Generate the real .docx (via de_package_docx) then write+publish the
    delivery-receipt engram. Returns {"artifact": ..., "receipt": ...}."""
    gen_result = de_package_docx.generate_docx(template_path, output_path, parts,
                                               genoffice_repo=genoffice_repo)
    agent_pub = m.pubkey_from_secret(int.from_bytes(sk, "big"))
    body = build_receipt_body(client, output_path, parts, agent_pub.hex(), gen_result["bytes"])
    ev = m.build_event(body["slug"], body, sk, owner)
    import asyncio
    publish_result = asyncio.run(m.publish(relay, ev))
    return {"artifact": gen_result, "receipt": {"slug": body["slug"], "published": publish_result}}


if __name__ == "__main__":
    if len(sys.argv) < 5:
        print("usage: de_deliver_client_artifact.py <client> <template.docx> <output.docx> <part 1> [...]",
              file=sys.stderr)
        sys.exit(2)
    client, template, output, *parts = sys.argv[1:]

    nsec = os.environ.get("NIPAE_NSEC", "").strip()
    if not nsec:
        print("NIPAE_NSEC required", file=sys.stderr)
        sys.exit(2)
    sk = m.nsec_decode(nsec) if nsec.startswith("nsec1") else bytes.fromhex(nsec)
    agent_pub = m.pubkey_from_secret(int.from_bytes(sk, "big"))
    owner_hex = os.environ.get("NIPAE_OWNER", "").strip()
    owner = bytes.fromhex(owner_hex) if owner_hex else agent_pub
    relay = os.environ.get("NIPAE_RELAY", "wss://relay.damus.io")

    result = deliver(client, template, output, parts, sk, owner, relay)
    print(json.dumps(result, indent=2))
