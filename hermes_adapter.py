#!/usr/bin/env python3
"""minipae-hermes-adapter — bridge Hermes memory store ↔ NIP-AE engrams.

Plan task 1.3 (mem/hermes/* namespace).

Hermes persistent memory lives as JSON entries in ~/.hermes/memories/
(one file per profile: memories.json etc). This adapter:

  push   — read local Hermes memory entries, write each as an engram under
           mem/hermes/profile/<profile>/memory/<key> (dedupe by slug)
  pull   — read engrams under mem/hermes/* and write any that are missing
           locally into the Hermes memory store (portability direction)
  sync   — push + pull (default)

Usage:
  NIPAE_NSEC=<agent key> [NIPAE_OWNER=<pubkey>] [NIPAE_RELAY=wss://...] \
      python3 hermes_adapter.py [push|pull|sync] [--mem-dir ~/.hermes/memories] [--profile default]

Writes provenance per docs/PROVENANCE.md (schema nip-ae-provenance/v1,
source=hermes, created_by = agent pubkey, turn_id = session id when known).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import minipae as m

# Hermes memory entry structure (as written by the memory tool)
# {"key": "...", "content": "...", "target": "user"|"memory", "ts": epoch, ...}


def load_local_memory(mem_dir: str, profile: str) -> dict[str, dict]:
    """Load Hermes memory entries. Real format on this Hermes version is
    Markdown (MEMORY.md / USER.md) with entries separated by '§' lines,
    one block per stored memory. Falls back to JSON files if present."""
    entries: dict[str, dict] = {}
    if not os.path.isdir(mem_dir):
        return entries
    for fn in ("MEMORY.md", "USER.md"):
        path = os.path.join(mem_dir, fn)
        if not os.path.exists(path):
            continue
        try:
            with open(path) as fh:
                text = fh.read()
        except Exception:
            continue
        blocks = [b.strip() for b in text.split("§") if b.strip()]
        for i, block in enumerate(blocks):
            # first line is the key; rest is content
            lines = block.split("\n")
            key = lines[0].strip().strip(":").strip() or f"block-{i}"
            content = "\n".join(lines[1:]).strip() or block
            entries[f"{profile}/{fn.replace('.md','').lower()}/{key}"] = {
                "key": key,
                "content": content,
                "ts": int(time.time()),
            }
    # JSON fallback for other layouts
    for fn in os.listdir(mem_dir):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(mem_dir, fn)) as fh:
                data = json.load(fh)
        except Exception:
            continue
        items = data.items() if isinstance(data, dict) else [(d.get("key", fn), d) for d in data if isinstance(d, dict)]
        for key, val in items:
            if isinstance(val, dict) and val.get("content"):
                entries[f"{profile}/{fn.replace('.json','')}/{key}"] = val
    return entries


def slug_for(profile: str, key: str) -> str:
    """mem/hermes/profile/<profile>/memory/<short-hash-of-key>.

    Keys are free-text (long, unicode) — not slug-safe. Use a deterministic
    short digest so the segment stays within NIP-AE's 64-char limit.
    """
    import hashlib
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    safe_profile = "".join(c if (c.islower() or c in "0123456789_-") else "_" for c in profile)[:32] or "default"
    return f"mem/hermes/profile/{safe_profile}/memory/{digest}"


def publish_entry(sk: bytes, owner: bytes, relay: str, profile: str,
                  key: str, entry: dict) -> str | None:
    import asyncio
    slug = slug_for(profile, key)
    if not m.validate_slug(slug):
        return None
    kc = m.conversation_key(sk, owner)
    agent_pub = m.pubkey_from_secret(int.from_bytes(sk, "big")).hex()
    now = int(time.time())
    body = {
        "slug": slug,
        "value": entry.get("content", ""),
        "provenance": {
            "schema": "nip-ae-provenance/v1",
            "source": "hermes",
            "source_version": "0.18.0",
            "created_by": agent_pub,
            "created_at": entry.get("ts", now),
            "turn_id": entry.get("session_id"),
            "key": key,  # original readable key (slug carries only the digest)
        },
    }
    ev = m.build_event(slug, body, sk, owner)
    import asyncio, time as _time
    for attempt in range(3):
        try:
            res = asyncio.run(m.publish(relay, ev))
            return slug if res.get("ok") else None
        except Exception as e:
            if attempt == 2:
                print(f"  FAIL {slug}: {type(e).__name__}", flush=True)
                return None
            _time.sleep(2 * (attempt + 1))  # backoff


def push(sk: bytes, owner: bytes, relay: str, mem_dir: str, profile: str) -> int:
    entries = load_local_memory(mem_dir, profile)
    published = 0
    for key, entry in entries.items():
        slug = publish_entry(sk, owner, relay, profile, key, entry)
        if slug:
            published += 1
            print(f"  pushed {slug}", flush=True)
    print(f"[hermes-adapter] push: {published}/{len(entries)} entries published")
    return published


def pull(sk: bytes, owner: bytes, relay: str, mem_dir: str, profile: str) -> int:
    import asyncio
    kc = m.conversation_key(sk, owner)
    agent_pub = m.pubkey_from_secret(int.from_bytes(sk, "big")).hex()
    events = asyncio.run(m.query(relay, [agent_pub]))
    heads = m.select_heads(events, kc)
    local = load_local_memory(mem_dir, profile)
    os.makedirs(mem_dir, exist_ok=True)
    out_path = os.path.join(mem_dir, "MEMORY.md")
    existing = ""
    if os.path.exists(out_path):
        try:
            with open(out_path) as fh:
                existing = fh.read()
        except Exception:
            existing = ""
    pulled = 0
    for dtag, ev in heads.items():
        try:
            body = m.decode_body(ev, kc)
        except Exception:
            continue
        slug = body.get("slug", "")
        if not slug.startswith(f"mem/hermes/profile/{profile}/"):
            continue
        if body.get("value") is None:
            continue  # tombstoned
        key = body.get("provenance", {}).get("key") or slug.rsplit("/", 1)[-1]
        if key in existing:
            continue
        existing += f"\n§ {key}\n{body.get('value', '')}\n"
        pulled += 1
    if pulled:
        with open(out_path, "w") as fh:
            fh.write(existing)
    print(f"[hermes-adapter] pull: {pulled} new entries appended to {out_path}")
    return pulled


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", nargs="?", default="sync", choices=["push", "pull", "sync"])
    ap.add_argument("--mem-dir", default=os.path.expanduser("~/.hermes/memories"))
    ap.add_argument("--profile", default="default")
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

    if args.mode in ("push", "sync"):
        push(sk, owner, relay, args.mem_dir, args.profile)
    if args.mode in ("pull", "sync"):
        pull(sk, owner, relay, args.mem_dir, args.profile)


if __name__ == "__main__":
    main()
