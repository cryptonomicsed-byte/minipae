#!/usr/bin/env python3
"""merged_view — Phase 3.3: a merged read view across an agent's mem/*
namespaces, without recreating per-framework silos inside the bus
(NAMESPACES.md's anti-goal) and without conflating private/public trust
classes (docs/PROVENANCE.md's content_trust_class addendum, endorsed by
the orchestrator — see docs/D_2_2_RELAY_KIND_COMPATIBILITY.md's sibling
2.4 doc for the confidentiality-model discussion this responds to).

This is a real design constraint, not just documentation: the view groups
by namespace AND by content_trust_class, and refuses to flatten both
together into one undifferentiated list.

Usage:
  NIPAE_NSEC=<key> [NIPAE_OWNER=<pubkey>] [NIPAE_RELAYS=wss://...,wss://...] \
      python3 merged_view.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import minipae as m


def namespace_of(slug: str) -> str:
    """First path segment after mem/, or 'core' for the reserved identity slug."""
    if slug == "core":
        return "core"
    parts = slug.split("/")
    return parts[1] if len(parts) > 1 and parts[0] == "mem" else "unknown"


def build_merged_view(heads: dict[str, dict], kc: bytes) -> dict:
    """Group decoded engrams by (namespace, content_trust_class). Returns
    {namespace: {trust_class: [entries]}} — never a single flat list, so a
    consumer cannot accidentally render private and public content
    identically without an explicit choice to do so."""
    view: dict[str, dict[str, list]] = {}
    for dtag, ev in heads.items():
        try:
            body = m.decode_body(ev, kc)
        except Exception:
            continue
        if body.get("value") is None:
            continue  # tombstoned
        slug = body.get("slug", "")
        ns = namespace_of(slug)
        provenance = body.get("provenance", {}) or {}
        trust_class = provenance.get("content_trust_class", "private")
        if trust_class not in ("private", "public"):
            trust_class = "private"  # fail safe, never default-open
        view.setdefault(ns, {}).setdefault(trust_class, []).append({
            "slug": slug,
            "value": body.get("value"),
            "created_at": ev.get("created_at"),
            "provenance": provenance,
        })
    return view


def render_text(view: dict) -> str:
    lines = []
    for ns in sorted(view):
        lines.append(f"## mem/{ns}/*")
        for trust_class in sorted(view[ns]):
            entries = view[ns][trust_class]
            badge = "🔒 private" if trust_class == "private" else "🌐 public"
            lines.append(f"  [{badge}] ({len(entries)} entries)")
            for e in sorted(entries, key=lambda x: x["slug"]):
                lines.append(f"    {e['slug']}  ({len(str(e['value']))} bytes)")
        lines.append("")
    return "\n".join(lines)


def main():
    import asyncio
    nsec = os.environ.get("NIPAE_NSEC", "").strip()
    if not nsec:
        print("NIPAE_NSEC required", file=sys.stderr)
        sys.exit(2)
    sk = m.nsec_decode(nsec) if nsec.startswith("nsec1") else bytes.fromhex(nsec)
    agent_pub = m.pubkey_from_secret(int.from_bytes(sk, "big"))
    owner_hex = os.environ.get("NIPAE_OWNER", "").strip()
    owner = bytes.fromhex(owner_hex) if owner_hex else agent_pub
    kc = m.conversation_key(sk, owner)

    relays_env = os.environ.get("NIPAE_RELAYS", "wss://relay.damus.io,wss://relay.primal.net")
    relays = [r.strip() for r in relays_env.split(",") if r.strip()]

    events = asyncio.run(m.query_multi(relays, [agent_pub.hex()]))
    heads = m.select_heads(events, kc)
    view = build_merged_view(heads, kc)
    print(render_text(view))


if __name__ == "__main__":
    main()
