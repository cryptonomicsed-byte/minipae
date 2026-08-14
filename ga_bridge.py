#!/usr/bin/env python3
"""ga_bridge — the real OpenAgents<->Buzz bridge agent (plan task 2.2).

Connects to the local, self-hosted OpenAgents network as a genuine SDK
agent (native grpc:// connection, NOT HermesAdapter's hosted-workspace
/v1/join API — that path is documented as unavailable for self-hosted
networks in docs/VPS_2.1_RUNBOOK.md). Mirrors channel messages into
mem/ga/channel/<channel>/<event_id> engrams on a Buzz relay, authenticated
via NIP-42 (docs/D3_NIP98_ENVELOPE_DECISION.md's decision, implemented
and live-proven in minipae.py's publish_authenticated()).

Getting the real connection/event flow working required working past
several undocumented (or inconsistently-documented-across-examples) SDK
behaviors, found empirically against the live deployed network, not
assumed from the SDK's example agents (which show conflicting patterns):

1. `AgentRunner.start(host=..., port=...)` triggers network auto-DETECTION
   first, which fails against this deployment. `start(url="grpc://host:port")`
   skips detection and connects directly — this is the one that works.
2. The messaging mod must be explicitly requested via
   `mod_names=["openagents.mods.workspace.messaging"]` in the constructor,
   or the agent never receives channel notifications at all (silently —
   no error, just nothing happens).
3. **The one that cost the most time to find**: `agent.start(...)` returns
   as soon as `setup()` completes — it does NOT block. The background
   polling task it creates (`self._loop_task`) is only kept alive by the
   process staying alive; `agent.start(...)` alone lets the Python script
   reach end-of-file and exit right after, silently killing the loop task
   with it (no exception, no traceback — the process just ends normally).
   The actual channel-message event name observed live is
   `thread.channel_message.notification` — NOT `channel.message.posted`,
   the `EventNames` constant that looked like the right one from a static
   read of event.py. **`agent.wait_for_stop()` must be called after
   `agent.start(...)` to actually block and receive events.**

Run as a genuinely long-lived process (systemd, nohup+disown, or a
supervised container) — `docker exec -d` was unreliable for this in
testing (see docs/D_2_2_GA_BRIDGE.md) even before the wait_for_stop() fix
was found; use a real process supervisor in production.

Usage:
  NIPAE_NSEC=<key> [NIPAE_OWNER=<pubkey>] [NIPAE_RELAY=ws://localhost:3000] \
  [NIPAE_RELAY_CONNECT_URL=ws://buzz-prod-relay-1:3000] \
      python3 ga_bridge.py [--network-url grpc://localhost:8600]

NIPAE_RELAY_CONNECT_URL: set this when the relay's logical identity
(NIPAE_RELAY, used for NIP-42 AUTH's `relay` tag) isn't reachable at that
same address from this process — e.g. this bridge runs in one Docker
container, the relay in another, and the relay does Host-header virtual
routing that only recognizes its own "localhost:3000" identity (observed
live against buzz-prod-relay-1). Omit if NIPAE_RELAY is directly reachable.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import minipae as m

CHANNEL_MESSAGE_NOTIFICATION = "thread.channel_message.notification"


def build_ga_engram_body(channel: str, source_id: str, text: str, event_id: str) -> dict:
    """Pure function: the engram body for one mirrored channel message.
    Separated from the live SDK/relay calls so this is unit-testable
    offline."""
    slug = f"mem/ga/channel/{channel}/{event_id}"
    return {
        "slug": slug,
        "value": text,
        "provenance": {
            "schema": "nip-ae-provenance/v1",
            "source": "openagents-ga-bridge",
            "source_version": "0.1.0",
            "created_by": source_id,
            "created_at": int(time.time()),
        },
    }


async def mirror_to_buzz(channel: str, source_id: str, text: str, event_id: str,
                         sk: bytes, owner: bytes, relay: str, connect_url: str | None = None) -> dict:
    body = build_ga_engram_body(channel, source_id, text, event_id)
    ev = m.build_event(body["slug"], body, sk, owner)
    return await m.publish_authenticated(relay, ev, sk, connect_url=connect_url)


def make_bridge_agent_class(sk: bytes, owner: bytes, relay: str, connect_url: str | None = None):
    """Returns a fresh AgentRunner subclass closing over the Buzz
    credentials/relay — avoids module-level globals for what's otherwise
    reusable, testable logic (build_ga_engram_body / mirror_to_buzz)."""
    from openagents.agents.runner import AgentRunner

    class GABridgeAgent(AgentRunner):
        async def react(self, context):
            ev = context.incoming_event
            if ev.event_name != CHANNEL_MESSAGE_NOTIFICATION:
                return
            payload = ev.payload or {}
            channel = payload.get("channel", "unknown")
            text = (payload.get("content") or {}).get("text", "")
            source_id = payload.get("source_id", ev.source_id)
            event_id = payload.get("original_event_id", ev.event_id)
            if not text:
                return
            try:
                result = await mirror_to_buzz(channel, source_id, text, event_id, sk, owner, relay,
                                              connect_url=connect_url)
                status = "ok" if result["ok"] else f"rejected: {result['message']}"
            except Exception as e:
                status = f"error: {e}"
            print(f"[ga_bridge] mirrored {channel}/{event_id} -> {status}", flush=True)

        async def setup(self):
            print(f"[ga_bridge] connected as {self.client.agent_id}, watching for channel messages", flush=True)

    return GABridgeAgent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--network-url", default="grpc://localhost:8600")
    ap.add_argument("--agent-id", default=None)
    args = ap.parse_args()

    nsec = os.environ.get("NIPAE_NSEC", "").strip()
    if not nsec:
        print("NIPAE_NSEC required", file=sys.stderr)
        sys.exit(2)
    sk = m.nsec_decode(nsec) if nsec.startswith("nsec1") else bytes.fromhex(nsec)
    agent_pub = m.pubkey_from_secret(int.from_bytes(sk, "big"))
    owner_hex = os.environ.get("NIPAE_OWNER", "").strip()
    owner = bytes.fromhex(owner_hex) if owner_hex else agent_pub
    relay = os.environ.get("NIPAE_RELAY", "ws://localhost:3000")
    connect_url = os.environ.get("NIPAE_RELAY_CONNECT_URL", "").strip() or None

    agent_id = args.agent_id or f"minipae-ga-bridge-{int(time.time())}"
    GABridgeAgent = make_bridge_agent_class(sk, owner, relay, connect_url=connect_url)
    agent = GABridgeAgent(agent_id=agent_id, mod_names=["openagents.mods.workspace.messaging"])
    agent.start(url=args.network_url)
    agent.wait_for_stop()


if __name__ == "__main__":
    main()
