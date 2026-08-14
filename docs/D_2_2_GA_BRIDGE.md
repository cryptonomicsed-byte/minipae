# 2.2 — the real OpenAgents↔Buzz bridge agent (ga_bridge.py)

The user explicitly authorized building this after the auth-layer half of
2.2 (NIP-42, `docs/D_2_2_RELAY_KIND_COMPATIBILITY.md`) was live-proven.
This doc is the debugging record — getting a genuine SDK-connected local
agent working took real, non-obvious troubleshooting against the live
deployed network, worth keeping for whoever operates this next.

## What it does

`ga_bridge.py` connects to the self-hosted OpenAgents network as a real
SDK agent (native `grpc://` connection — the local-network path, not
`HermesAdapter`'s hosted-workspace `/v1/join` API, which
`docs/VPS_2.1_RUNBOOK.md` already established doesn't work for self-hosted
deployments). It listens for channel messages and mirrors each one into a
`mem/ga/channel/<channel>/<event_id>` engram on a Buzz relay, authenticated
via NIP-42 (`minipae.publish_authenticated`).

**Live-verified end to end, not just unit tested**: a real message posted
into the local network's "general" channel by one agent → received by
`ga_bridge.py` via a genuine connection → mirrored to `buzz-prod-relay-1`
as an authenticated kind:30174 engram → independently read back and
decrypted, exact content confirmed intact.

## Three real bugs found getting there, in the order they blocked progress

### 1. `start(host=, port=)` triggers auto-detection, which fails

`AgentRunner.start()` accepts either `host`/`port` (triggers a network
auto-detect step first) or `url="grpc://host:port"` (skips detection,
connects directly). Only the `url=` form worked against this deployment.
Found by reading `_async_start`'s URL-parsing branch in `runner.py`, not
guessed.

### 2. The messaging mod must be explicitly requested

`mod_names=["openagents.mods.workspace.messaging"]` is required in the
`AgentRunner` constructor, or the agent connects successfully but silently
never receives any channel notifications — no error, just nothing
happens. Confirmed by reading `AgentRunner.__init__`'s mod-loading branch.

### 3. `agent.start()` does not block — `wait_for_stop()` is required (the expensive one)

This one cost the most time. `agent.start(url=...)` returns as soon as
`setup()` completes; it does **not** block waiting for the background
polling task (`self._loop_task`) it creates. A script that calls
`agent.start(...)` and then has nothing else to do reaches end-of-file and
the Python process exits normally — silently killing the polling task
with it. No exception, no traceback, nothing in stderr — the process just
stops, which looked exactly like a process-supervision/detachment problem
(`docker exec -d`, `nohup`, `setsid` were all tried and ruled out as the
cause) before the real explanation was found by reading straight through
`runner.py`'s `start()`/`_async_start()` call chain. **Fix: call
`agent.wait_for_stop()` immediately after `agent.start(...)`.**

Along the way, this also surfaced the real channel-message event name via
live traffic capture: `thread.channel_message.notification` — not
`EventNames.CHANNEL_MESSAGE_POSTED` ("channel.message.posted"), the
constant that looked correct from a static read of `event.py` but turned
out to be unused/aspirational for this code path.

## A fourth issue, found once messages were flowing: Host-header virtual routing

`buzz-prod-relay-1` rejects WebSocket upgrades with HTTP 404 unless the
`Host` header matches its self-identity (`localhost:3000`, per its own
NIP-11 doc) — confirmed directly with `curl -H "Host: localhost:3000"`
returning the real relay info doc, vs. a 404 for any other Host value,
including the container-DNS name that actually reaches it
(`buzz-prod-relay-1`) and the Docker bridge gateway IP.

**First attempt (wrong): `websockets.connect(..., additional_headers={"Host": ...})`.**
Doesn't work — the `websockets` library always recomputes the `Host`
header from the connection URI itself (`headers["Host"] = build_host(...)`
in its own client code), overwriting anything passed via
`additional_headers`.

**Actual fix**: open a real, pre-connected, non-blocking TCP socket to the
address that's actually reachable (`buzz-prod-relay-1:3000`, via
container DNS after joining Buzz's own compose network — see below), then
pass it to `websockets.connect(relay, sock=presocket)`. The `sock=`
kwarg makes the library skip its own connection step and use the socket
as-is, while the `relay` URI (`ws://localhost:3000`, the relay's real
logical identity) still determines the Host header and the NIP-42 AUTH
event's `relay` tag. Implemented as `minipae._open_presocket()` +
`connect_url=` on both `publish_authenticated()` and
`query_authenticated()`.

## Deployment: joined the openagents container to Buzz's own network

`openagents-network-studio` and `buzz-prod-relay-1` are on two different
Docker Compose projects' networks by default. Rather than routing through
the host's published port (where the Host-header problem was first hit),
`docker-compose.yml` now joins the container to `buzz-prod_buzz-net`
directly (external network reference) — cleaner and doesn't depend on
Buzz's port ever being published to the host at all. Verified durable
across a full `docker compose down && up`, not just the live session:
both networks re-attach correctly, disk stayed stable (2.7G, no rebuild
triggered — same `image:`-pinned pattern from 2.1).

`minipae.py` is bind-mounted read-only into the container
(`/opt/genteam/minipae:/opt/minipae:ro`) so `ga_bridge.py` can `import
minipae` directly, same pattern as the hermes CLI mount from 2.1.

## Running it for real

`ga_bridge.py` is not currently running as a supervised long-lived
process — it was run under a test harness for the live proof above and
then stopped/cleaned up. For production use, run it under a real process
supervisor (systemd unit, or a dedicated no-restart-loop container) — a
bare `nohup &` was sufficient for testing but a genuinely long-lived
bridge should be supervised properly (auto-restart on crash, log
rotation), which wasn't set up as part of this deliverable.

```bash
NIPAE_NSEC=<agent key> \
NIPAE_RELAY=ws://localhost:3000 \
NIPAE_RELAY_CONNECT_URL=ws://buzz-prod-relay-1:3000 \
  python3 ga_bridge.py --network-url grpc://localhost:8600
```
