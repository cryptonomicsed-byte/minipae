#!/usr/bin/env python3
"""minipae-daemon-adapter — mirror GenTeam daemon session/turn state to NIP-AE engrams.

Plan task 1.2 (daemon-first adapter, mem/genteam/* namespace).

Reads daemon state + log on the local machine and publishes engrams:
  - mem/genteam/computer/<machine_id>/state      (heartbeat: online/ready, ws status)
  - mem/genteam/computer/<machine_id>/last-turn  (last turn outcome)
  - mem/genteam/computer/<machine_id>/session/<session_id>  (per-session notes)

Usage:
  NIPAE_NSEC=<hex or nsec1> [NIPAE_OWNER=<pubkey>] [NIPAE_RELAY=wss://...] \
      python3 daemon_adapter.py [--state-dir ~/.genteam] [--log ~/genteam/daemon.log] [--once]

  --once   publish current state and exit (cron-friendly)
  default: watch the log tail and publish on new turn boundaries

Writes provenance per docs/PROVENANCE.md (schema nip-ae-provenance/v1,
source=genteam-daemon, created_by = agent pubkey).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import minipae as m

TURN_RE = re.compile(r"\[INFO\].*Turn completed: (\S+) \(outcome=(\w+)\)|"
                     r"\[INFO\].*turn\.done.*outcome[=: ](\w+)|"
                     r"\[INFO\].*Ready for GenTeam local agent turns")
READY_RE = re.compile(r"\[INFO\].*Ready for GenTeam local agent turns")
STATE_RE = re.compile(r"\[INFO\].*Connected to server")


def load_machine_id(state_dir: str) -> str | None:
    cfg = os.path.join(state_dir, "config.json")
    try:
        with open(cfg) as fh:
            return json.load(fh).get("machine_id")
    except Exception:
        return None


def load_ready_state(state_dir: str) -> str | None:
    lock = os.path.join(state_dir, "daemon.lock", "owner.json")
    try:
        with open(lock) as fh:
            owner = json.load(fh)
            return f"running (pid {owner.get('pid')})"
    except Exception:
        return None


def publish_state(sk: bytes, owner: bytes, relay: str, state_dir: str,
                  machine_id: str, ready: str):
    import asyncio
    kc = m.conversation_key(sk, owner)
    agent_pub = m.pubkey_from_secret(int.from_bytes(sk, "big")).hex()
    now = int(time.time())
    base = f"mem/genteam/computer/{machine_id}"
    body = {
        "slug": f"{base}/state",
        "value": json.dumps({"ready": ready, "machine_id": machine_id,
                             "observed_at": now}),
        "provenance": {
            "schema": "nip-ae-provenance/v1",
            "source": "genteam-daemon",
            "source_version": "0.13.0",
            "created_by": agent_pub,
            "created_at": now,
        },
    }
    ev = m.build_event(f"{base}/state", body, sk, owner)
    return asyncio.run(m.publish(relay, ev))


def tail_log(log_path: str, sk: bytes, owner: bytes, relay: str,
             machine_id: str) -> None:
    """Tail the daemon log; publish a last-turn engram on each completed turn."""
    last_turn = None
    with open(log_path, "r") as fh:
        fh.seek(0, 2)  # start at end
        while True:
            line = fh.readline()
            if not line:
                time.sleep(3)
                continue
            tm = TURN_RE.search(line)
            if tm:
                turn_id = tm.group(1) or "unknown"
                outcome = tm.group(2) or tm.group(3) or "completed"
                if turn_id != last_turn:
                    last_turn = turn_id
                    publish_turn(sk, owner, relay, machine_id, turn_id, outcome)
                    print(f"[adapter] published turn {turn_id} ({outcome})", flush=True)
            elif READY_RE.search(line):
                publish_state(sk, owner, relay, machine_id, "ready")
                print("[adapter] published ready state", flush=True)


def publish_turn(sk: bytes, owner: bytes, relay: str, machine_id: str,
                 turn_id: str, outcome: str):
    import asyncio
    kc = m.conversation_key(sk, owner)
    agent_pub = m.pubkey_from_secret(int.from_bytes(sk, "big")).hex()
    now = int(time.time())
    base = f"mem/genteam/computer/{machine_id}"
    slug = f"{base}/session/{turn_id}"
    body = {
        "slug": slug,
        "value": json.dumps({"turn_id": turn_id, "outcome": outcome,
                             "completed_at": now}),
        "provenance": {
            "schema": "nip-ae-provenance/v1",
            "source": "genteam-daemon",
            "source_version": "0.13.0",
            "created_by": agent_pub,
            "created_at": now,
            "turn_id": turn_id,
        },
    }
    ev = m.build_event(slug, body, sk, owner)
    return m.publish(relay, ev)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state-dir", default=os.path.expanduser("~/.genteam"))
    ap.add_argument("--log", default=os.path.expanduser("~/genteam/daemon.log"))
    ap.add_argument("--once", action="store_true")
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

    machine_id = load_machine_id(args.state_dir) or "unknown"
    ready = load_ready_state(args.state_dir) or "not-running"

    if args.once:
        res = publish_state(sk, owner, relay, args.state_dir, machine_id, ready)
        print(f"[adapter] once: state published accepted={res.get('ok')} {res.get('message','')}")
        return

    print(f"[adapter] watching {args.log} (machine {machine_id}) -> {relay}", flush=True)
    tail_log(args.log, sk, owner, relay, machine_id)


if __name__ == "__main__":
    main()
