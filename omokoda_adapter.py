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
    """Push all glyph nodes from Omo-Koda2 to Nostr via batch_set."""
    from minipae import NipaeClient
    graph = _get_json(f"{omokoda_url}/v1/vault/glyph", agent_id)
    # larql_glyph::GlyphGraph serializes as {"nodes": {canonical_id: GlyphNode},
    # "edges": [GlyphEdge, ...]} -- nodes is a map keyed by canonical_id, not
    # a list (see larql-glyph crate lib.rs GlyphGraph{nodes: BTreeMap, ...}).
    nodes = graph.get("nodes", {})
    agent_pub = m.pubkey_from_secret(int.from_bytes(sk, "big")).hex()
    now = int(time.time())

    # Build the batch of (slug, value) pairs, skipping invalid slugs.
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
    entries: list[tuple[str, str]] = []
    skipped = 0
    for canonical_id, node in nodes.items():
        slug = slug_for(canonical_id)
        if not m.validate_slug(slug):
            skipped += 1
            continue
        value = json.dumps({
            "canonical_id": canonical_id,
            "glyph": node.get("glyph"),
            "seed_base": node.get("odu_base"),
            "seed_composed": node.get("odu_composed"),
            "ts": node.get("ts"),
            "tags": node.get("tags", []),
            "walrus_blob_id": node.get("walrus_blob_id"),
            "provenance": {
                "schema": "nip-ae-provenance/v1",
                "source": "omokoda",
                "source_version": "glyphindex/v1",
                "created_by": agent_pub,
                "created_at": now,
                "key": canonical_id,
            },
        })
        entries.append((slug, value))

    if not entries:
        print(f"[omokoda-adapter] push: no valid glyph nodes to publish (skipped={skipped})")
        return 0

    client = NipaeClient(seckey=sk, owner_pubkey=owner)
    results = client.batch_set(entries)
    published = sum(1 for ok in results if ok)
    print(f"[omokoda-adapter] push: {published}/{len(entries)} glyph nodes published"
          f" (skipped={skipped})")
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


def pull_glyphs(sk: bytes, owner: bytes, relays: list[str], since_ts: float = 0.0) -> list[dict]:
    """Fetch glyph engrams from Nostr since *since_ts* (Unix timestamp).

    Queries all relays in parallel and returns a list of decoded glyph-node
    dicts (the parsed payload inside each engram), deduplicated by
    canonical_id, with the most-recently-published copy winning.

    If *since_ts* is 0.0 (the default), all available engrams are returned.
    Callers can pass ``NipaeClient.get_sync_cursor()`` to resume from the
    last known good checkpoint.
    """
    import asyncio
    kc = m.conversation_key(sk, owner)
    agent_pub = m.pubkey_from_secret(int.from_bytes(sk, "big")).hex()
    since_int = int(since_ts) if since_ts > 0 else None
    events = asyncio.run(m.query_multi(relays, [agent_pub], since=since_int))
    heads = m.select_heads(events, kc)

    glyphs: dict[str, dict] = {}  # canonical_id -> payload
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
        existing = glyphs.get(canonical_id)
        ev_ts = ev.get("created_at", 0)
        if existing is None or ev_ts > existing.get("_ev_created_at", 0):
            payload["_ev_created_at"] = ev_ts
            glyphs[canonical_id] = payload

    # Strip the internal sort key before returning
    result = []
    for payload in glyphs.values():
        payload.pop("_ev_created_at", None)
        result.append(payload)
    return result


def sync_glyphs(
    sk: bytes,
    owner: bytes,
    relay: str,
    relays: list[str],
    omokoda_url: str,
    agent_id: str | None,
    index_snapshot: dict,
) -> dict:
    """Push new local glyph entries to Nostr and pull remote entries back.

    *index_snapshot* is a dict mapping canonical_id -> GlyphNode (the same
    shape returned by GET /v1/vault/glyph's "nodes" field).

    Steps:
      1. Read the sync cursor to know where we last left off.
      2. Push entries from *index_snapshot* whose canonical_id is not
         already published (checked by slug presence).
      3. Pull remote engrams published since the cursor; merge any that are
         not in *index_snapshot* into Omo-Koda2 via the merge endpoint.
      4. Advance the cursor to now.

    Returns {"pushed": N, "pulled": M, "errors": K}.
    """
    from minipae import NipaeClient
    client = NipaeClient(seckey=sk, owner_pubkey=owner)
    cursor_ts = client.get_sync_cursor()

    agent_pub = m.pubkey_from_secret(int.from_bytes(sk, "big")).hex()
    now = int(time.time())

    # --- Phase 1: push new local entries ---
    push_entries: list[tuple[str, str]] = []
    for canonical_id, node in index_snapshot.items():
        slug = slug_for(canonical_id)
        if not m.validate_slug(slug):
            continue
        value = json.dumps({
            "canonical_id": canonical_id,
            "glyph": node.get("glyph"),
            "seed_base": node.get("odu_base"),
            "seed_composed": node.get("odu_composed"),
            "ts": node.get("ts"),
            "tags": node.get("tags", []),
            "walrus_blob_id": node.get("walrus_blob_id"),
            "provenance": {
                "schema": "nip-ae-provenance/v1",
                "source": "omokoda",
                "source_version": "glyphindex/v1",
                "created_by": agent_pub,
                "created_at": now,
                "key": canonical_id,
            },
        })
        push_entries.append((slug, value))

    push_results = client.batch_set(push_entries) if push_entries else []
    pushed = sum(1 for ok in push_results if ok)
    errors = sum(1 for ok in push_results if not ok)

    # --- Phase 2: pull remote entries not in local index ---
    remote_glyphs = pull_glyphs(sk, owner, relays, since_ts=cursor_ts)
    new_remote = [g for g in remote_glyphs if g.get("canonical_id") not in index_snapshot]

    pulled = 0
    if new_remote:
        # Re-map seed_* names back to odu_* for Omo-Koda2's merge API
        merge_nodes: dict = {}
        for payload in new_remote:
            cid = payload.get("canonical_id")
            if cid:
                merge_nodes[cid] = {
                    "canonical_id": cid,
                    "glyph": payload.get("glyph"),
                    "odu_base": payload.get("seed_base"),
                    "odu_composed": payload.get("seed_composed"),
                    "ts": payload.get("ts"),
                    "tags": payload.get("tags", []),
                    "walrus_blob_id": payload.get("walrus_blob_id"),
                }
        try:
            result = _post_json(
                f"{omokoda_url}/v1/vault/glyph/merge",
                {"nodes": merge_nodes, "edges": []},
                agent_id,
            )
            pulled = len(merge_nodes)
            print(f"[omokoda-adapter] sync: pulled {pulled} remote glyph(s) into merge")
        except Exception as exc:
            print(f"[omokoda-adapter] sync: merge FAILED: {type(exc).__name__}: {exc}")
            errors += len(merge_nodes)

    # --- Phase 3: advance cursor ---
    client.set_sync_cursor(float(now))

    print(f"[omokoda-adapter] sync: pushed={pushed} pulled={pulled} errors={errors}")
    return {"pushed": pushed, "pulled": pulled, "errors": errors}


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
    # Multi-relay support: NIPAE_RELAYS wins over NIPAE_RELAY
    relays = m._load_relays()
    relay = relays[0]  # legacy single-relay path for push/pull
    omokoda_url = os.environ.get("OMOKODA_URL", "http://127.0.0.1:8787").rstrip("/")

    if args.mode in ("push", "sync"):
        push(sk, owner, relay, omokoda_url, args.agent_id)
    if args.mode in ("pull", "sync"):
        pull(sk, owner, relay, omokoda_url, args.agent_id)


if __name__ == "__main__":
    main()
