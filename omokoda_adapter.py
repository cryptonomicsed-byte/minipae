#!/usr/bin/env python3
"""minipae-omokoda-adapter — bridge Omo-Koda2's GlyphIndex memory <-> NIP-AE engrams.

Task D (mem/omokoda/* namespace). Omo-Koda2's kernel already projects the
agent's Odù memory into a content-addressed GlyphIndex graph
(larql_glyph::GlyphGraph) at GET /v1/vault/glyph -- deliberately
metadata-only (canonical_id, glyph, Odù linkage, tags, an optional Walrus
blob id); plaintext memory content stays sealed in the vault by design (see
server.rs's get_glyph_memory doc comment). This adapter respects that
boundary: it mirrors each GlyphNode's metadata as a NIP-AE engram, never raw
memory content -- a real, honest export of "these memories exist, addressed
by hash" rather than a leak of what they say.

  push — GET the agent's GlyphGraph, write one engram per node under
         mem/omokoda/glyph/<canonical_id> (value = json of every GlyphNode
         field so pull() can round-trip it, dedupe by slug via NIP-AE's own
         upsert-by-dtag semantics)
  pull — read engrams under mem/omokoda/glyph/* back and POST them as a
         synthetic GlyphGraph snapshot to Omo-Koda2's real agent-to-agent
         merge endpoint, POST /v1/vault/glyph/merge (idempotent, read-safe
         per that endpoint's own contract: the agent's sealed vault is
         untouched, only the returned projection reflects the merge)
  sync — push + pull (default)

Identity: the agent's minipae key is a sibling derivation from the same
BIPON39 mnemonic every Omo-Koda2 agent gets at birth
(m/44'/30174'/<agent_index>'/<owner_index>', see
omokoda-core/src/identity/wallet.rs::derive_minipae_key) -- not a second
unrelated key. Provide it via NIPAE_NSEC the same way every other adapter
in this repo does; this adapter does not derive it itself (that stays
inside Omo-Koda2's own self-sealed vault).

Usage:
  NIPAE_NSEC=<agent key> [NIPAE_OWNER=<pubkey>] [NIPAE_RELAY=wss://...] \
      OMOKODA_URL=http://127.0.0.1:8787 \
      python3 omokoda_adapter.py [push|pull|sync] [--agent-id <guest id>]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import minipae as m


def _get_json(url: str, agent_id: str | None) -> dict:
    req = urllib.request.Request(url)
    if agent_id:
        req.add_header("x-agent-id", agent_id)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def _post_json(url: str, body: dict, agent_id: str | None) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if agent_id:
        req.add_header("x-agent-id", agent_id)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode() or "null")


def slug_for(canonical_id: str) -> str:
    """mem/omokoda/glyph/<short-digest-of-canonical_id> -- canonical_id is
    already a sha256 hex digest but can be longer than NIP-AE's 64-char slug
    segment limit once namespaced, so re-digest it short, same treatment
    hermes_adapter.py gives its own long, non-slug-safe keys."""
    digest = hashlib.sha256(canonical_id.encode("utf-8")).hexdigest()[:16]
    return f"mem/omokoda/glyph/{digest}"


def push(sk: bytes, owner: bytes, relay: str, omokoda_url: str, agent_id: str | None) -> int:
    import asyncio
    graph = _get_json(f"{omokoda_url}/v1/vault/glyph", agent_id)
    # larql_glyph::GlyphGraph serializes as {"nodes": {canonical_id: GlyphNode},
    # "edges": [GlyphEdge, ...]} -- nodes is a map keyed by canonical_id, not
    # a list (see larql-glyph crate lib.rs GlyphGraph{nodes: BTreeMap, ...}).
    nodes = graph.get("nodes", {})
    agent_pub = m.pubkey_from_secret(int.from_bytes(sk, "big")).hex()
    now = int(time.time())
    published = 0
    for canonical_id, node in nodes.items():
        slug = slug_for(canonical_id)
        if not m.validate_slug(slug):
            continue
        body = {
            "slug": slug,
            # Full GlyphNode metadata (no plaintext memory content crosses
            # this boundary, matching Omo-Koda2's own sealed-vault design) --
            # every field GlyphNode needs so pull() can round-trip it back
            # into a real merge without recomputing glyph/seed derivations.
            # Universal wording on the wire (OSOVM_CODEX §42, locked
            # 2026-08-22): Omo-Koda2's own GlyphNode struct names these
            # fields odu_base/odu_composed internally, but any minipae
            # client reading this engram is an external, user-facing
            # surface -- translated to seed_base/seed_composed here
            # (Odù -> Signature/Seed per the locked mapping). pull()
            # translates back before calling Omo-Koda2's own merge API,
            # which still requires the real odu_base/odu_composed names.
            "value": json.dumps({
                "canonical_id": canonical_id,
                "glyph": node.get("glyph"),
                "seed_base": node.get("odu_base"),
                "seed_composed": node.get("odu_composed"),
                "ts": node.get("ts"),
                "tags": node.get("tags", []),
                "walrus_blob_id": node.get("walrus_blob_id"),
            }),
            "provenance": {
                "schema": "nip-ae-provenance/v1",
                "source": "omokoda",
                "source_version": "glyphindex/v1",
                "created_by": agent_pub,
                "created_at": now,
                "key": canonical_id,
            },
        }
        ev = m.build_event(slug, body, sk, owner)
        for attempt in range(3):
            try:
                res = asyncio.run(m.publish(relay, ev))
                if res.get("ok"):
                    published += 1
                    print(f"  pushed {slug}", flush=True)
                break
            except Exception as e:
                if attempt == 2:
                    print(f"  FAIL {slug}: {type(e).__name__}", flush=True)
                else:
                    time.sleep(2 * (attempt + 1))
    print(f"[omokoda-adapter] push: {published}/{len(nodes)} glyph nodes published")
    return published


def pull(sk: bytes, owner: bytes, relay: str, omokoda_url: str, agent_id: str | None) -> int:
    import asyncio
    kc = m.conversation_key(sk, owner)
    agent_pub = m.pubkey_from_secret(int.from_bytes(sk, "big")).hex()
    events = asyncio.run(m.query(relay, [agent_pub]))
    heads = m.select_heads(events, kc)

    # larql_glyph::GlyphGraph deserializes {"nodes": {canonical_id: GlyphNode},
    # "edges": [...]} -- nodes must be a map keyed by canonical_id with every
    # GlyphNode field present (glyph/odu_base/odu_composed/ts/tags/
    # walrus_blob_id), same shape push() reads back out below. The engram
    # itself carries the universal seed_base/seed_composed names (see
    # push()); translated back to odu_base/odu_composed here because that's
    # what Omo-Koda2's own merge API (Rust GlyphNode struct) requires.
    nodes: dict = {}
    for dtag, ev in heads.items():
        try:
            body = m.decode_body(ev, kc)
        except Exception:
            continue
        slug = body.get("slug", "")
        if not slug.startswith("mem/omokoda/glyph/"):
            continue
        if body.get("value") is None:
            continue  # tombstoned
        try:
            payload = json.loads(body["value"])
        except (json.JSONDecodeError, TypeError):
            continue
        canonical_id = payload.get("canonical_id")
        if not canonical_id:
            continue
        nodes[canonical_id] = {
            "canonical_id": canonical_id,
            "glyph": payload.get("glyph"),
            "odu_base": payload.get("seed_base"),
            "odu_composed": payload.get("seed_composed"),
            "ts": payload.get("ts"),
            "tags": payload.get("tags", []),
            "walrus_blob_id": payload.get("walrus_blob_id"),
        }

    if not nodes:
        print("[omokoda-adapter] pull: no mem/omokoda/glyph/* engrams found")
        return 0

    # Real agent-to-agent merge path: Omo-Koda2's own contract for accepting
    # another agent's GlyphGraph snapshot -- read-safe (sealed vault
    # untouched), idempotent, so re-pulling the same engrams is harmless.
    result = _post_json(f"{omokoda_url}/v1/vault/glyph/merge", {"nodes": nodes, "edges": []}, agent_id)
    merged = len(result.get("nodes", nodes)) if isinstance(result, dict) else len(nodes)
    print(f"[omokoda-adapter] pull: merged {len(nodes)} engram(s) into live glyph projection ({merged} nodes now)")
    return len(nodes)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", nargs="?", default="sync", choices=["push", "pull", "sync"])
    ap.add_argument("--agent-id", default=None, help="x-agent-id header for a guest agent; omit for the owner")
    args = ap.parse_args()

    nsec = os.environ.get("NIPAE_NSEC", "").strip()
    if not nsec:
        print("NIPAE_NSEC required (agent key, hex or nsec1)", file=sys.stderr)
        sys.exit(2)
    if nsec.startswith("nsec1"):
        nsec = m.bech32_decode(nsec)
    sk = bytes.fromhex(nsec)
    owner_hex = os.environ.get("NIPAE_OWNER", "").strip()
    owner = bytes.fromhex(owner_hex) if owner_hex else m.pubkey_from_secret(int.from_bytes(sk, "big"))
    relay = os.environ.get("NIPAE_RELAY", "wss://relay.damus.io")
    omokoda_url = os.environ.get("OMOKODA_URL", "http://127.0.0.1:8787").rstrip("/")

    if args.mode in ("push", "sync"):
        push(sk, owner, relay, omokoda_url, args.agent_id)
    if args.mode in ("pull", "sync"):
        pull(sk, owner, relay, omokoda_url, args.agent_id)


if __name__ == "__main__":
    main()
