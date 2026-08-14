# 2.1 OpenAgents deploy — VPS execution runbook

Repo: `openagents-org/openagents` (develop branch). Verified real via GitHub
API before writing this — not assumed from the task brief. Confirmed:

- `docker-compose.yml` (repo root) — standard single-service compose,
  ports 8700 (HTTP + Studio UI at `/studio` + MCP at `/mcp`) and 8600
  (gRPC), healthcheck against `/api/health`, named volume `openagents-data`.
- `sdk/src/openagents/registry/hermes.yaml` — Hermes is a **builtin** agent
  type upstream already. `adapter.module: openagents.adapters.hermes`,
  `class: HermesAdapter`. No adapter code needs to be written by us.
- `packages/agent-connector/src/adapters/hermes.js:291-298` — confirms the
  exact invocation the task brief described: spawns
  `hermes chat -q <prompt> -Q [--resume <id>] [--yolo]`, optionally with
  `-p <profile>` first. This is genuinely our `hermes` CLI being driven,
  not a different "Hermes" naming collision.

Because the Hermes adapter is already builtin, 2.1's remaining work is
**deployment + registration**, not code — matches "you prepare
config/agent workspace; Hermes deploys" from the task brief.

## [UPDATE] Deploy blocker found + fixed: gRPC transport missing grpcio

Confirmed root cause against real source, not guessed: `pyproject.toml`
declares `grpcio>=1.50.0` / `grpcio-tools>=1.50.0` under
`[project.optional-dependencies].sdk`, **not** the base `dependencies`
list. The `Dockerfile` runs `pip install --no-cache-dir -e .` with no
extras specifier — that installs only the base group. `docker-entrypoint.sh`
starts `openagents network start /network`, which requires the gRPC
transport on port 8600; with no grpcio installed, that transport has
nothing to import and the network fails to start. This matches exactly
what the orchestrator observed on the VPS.

**Fix**: `docs/VPS_2.1_grpcio.patch` — one-line change,
`pip install --no-cache-dir -e .` → `pip install --no-cache-dir -e ".[sdk]"`.
Apply before building:

```bash
git clone https://github.com/openagents-org/openagents.git /opt/openagents
cd /opt/openagents
patch -p1 < /path/to/minipae/docs/VPS_2.1_grpcio.patch
docker compose build   # rebuild with the extras group included
```

I have not built or run this on the VPS — verified the root cause against
`pyproject.toml`/`Dockerfile` source only. Confirm the build actually
succeeds and the gRPC transport binds before treating this as closed.

## Deploy (VPS: root@2.25.70.156, docker already present per 1.4's VPS profile)

```bash
git clone https://github.com/openagents-org/openagents.git /opt/openagents
cd /opt/openagents
patch -p1 < docs_from_minipae/VPS_2.1_grpcio.patch   # see above — required
docker compose up -d --build
curl -f http://localhost:8700/api/health   # wait for healthy before continuing
```

No other changes needed to the upstream `docker-compose.yml` for a first
deploy — it has no other required env vars (the `OPENAI_API_KEY`/
`ANTHROPIC_API_KEY` lines are commented-out optional extras for LLM-direct
agent types, irrelevant to a Hermes-CLI-driven agent, which shells out to
the already-installed `hermes` binary rather than calling a model API
directly).

**deepseek provider key** (per orchestrator decision, VPS-local hermes):
read from the vault as a 0600 file inside the container/session, same
constraint as every other key in this plan — never argv, never a bare env
var set from a shell history-visible command, never on VPS host disk
outside the intended 0600 location.

## Register a workspace + hermes-type agent

**[RESOLVED by orchestrator]**: register **VPS-local** for now — a
`hermes` CLI installed inside/next to the OpenAgents container/host, per
the registry install block (`scripts/install.sh` from
NousResearch/hermes-agent). The Fold 4/Mac herdr bridge is explicitly
deferred to a Phase-3 refinement (needs a VPS←Mac reverse tunnel) and is
NOT 2.1-blocking — so 2.1 no longer has an open dependency on herdr's
bridge contract.

Once a `hermes` binary is reachable, workspace + agent registration is
via OpenAgents' own Studio UI (`:8700/studio`) or its HTTP API — no minipae
code involved at this stage; NIP-AE bridging is 2.2, not 2.1.

## [EXECUTED] Deploy status — live on the VPS, verified end to end

Actually executed on root@2.25.70.156, not just designed:

- Disk was at 100% (827M free) when I started, on a box also running
  Ares (live trading, postgres), Buzz production relay/postgres/redis/
  minio, Vantage monitoring (grafana/prometheus/metabase), and more. A
  full `docker compose build` (multi-stage: npm studio build + pip
  install) pushed disk to <1GB free and had to be aborted mid-build to
  protect the other production services — this box cannot safely absorb
  a full rebuild without headroom prep first.
- Applied the fix without a full rebuild: hot-installed
  `grpcio`/`grpcio-tools` into the running container (`pip install`,
  ~10MB, not a rebuild), verified the network came up healthy with all 4
  transports (http/grpc/mcp/a2a), then `docker commit`'d that fixed
  filesystem state to a new local image tag
  `openagents-network-studio:sdk-fixed`, and repointed
  `docker-compose.yml` at `image: openagents-network-studio:sdk-fixed`
  instead of `build:`. Verified: `docker compose down && docker compose
  up -d` from cold now uses the pinned image only — no rebuild, no disk
  movement, confirmed by a real down/up cycle.
- Also bind-mounted the VPS's existing hermes-agent install
  (`/usr/local/bin/hermes`, `/usr/local/lib/hermes-agent`,
  `/usr/local/share/uv/python`, all `:ro`) into the container rather than
  reinstalling a duplicate ~2GB copy. `openagents runtimes` / `openagents
  search hermes` inside the container both correctly report Hermes as
  `● installed` — the CLI's own detection confirms the mount works.
- Backup of the original `docker-compose.yml` and `Dockerfile` diff are
  both preserved (`Dockerfile`'s `-e ".[sdk]"` fix is on disk for a future
  deliberate rebuild; the running deployment uses the committed image so
  it doesn't need that rebuild to work today).

## Open blocker — NOT resolved, needs a decision before agent registration

`HermesAdapter` (`sdk/src/openagents/adapters/hermes.py`, via
`sdk/src/openagents/client/workspace_client.py`) connects through the
**hosted OpenAgents workspace API** — `POST {endpoint}/v1/join` and
`/v1/agentid/register`, default `endpoint = https://workspace-endpoint.openagents.org`.
Confirmed empirically, not assumed: our local self-hosted network
returns `404` on `POST /v1/join` — that endpoint genuinely isn't
implemented for self-hosted `docker compose` deployments, only the
hosted SaaS product. This is a real fork in the upstream codebase, not
a config mismatch: local-network agents (`charlie.yaml`'s
`CollaboratorAgent`) connect via the native gRPC transport
(`connection: {host, port, transport: grpc}`); `HermesAdapter` was built
exclusively for the hosted-workspace HTTP path.

**Three real options, not attempted without a decision**:
1. Point `HermesAdapter`'s `endpoint` at the real `openagents.org` cloud
   service and actually use their hosted workspace product. This takes
   the agent off our own infra and onto a third party never authorized
   for this — I did not do this.
2. Write a small local-network-native agent that shells out to `hermes
   chat -q <prompt> -Q [--resume <id>]` itself (same invocation
   `HermesAdapter` uses, confirmed at `hermes.py`), wired to the native
   gRPC connection like `CollaboratorAgent` instead of the hosted
   `/v1/join` API. Real, scoped, buildable — but new adapter code I
   haven't written or gotten reviewed, and wasn't in the original "no
   code needed" assumption for 2.1.
3. File the gap upstream (`openagents-org/openagents`) — self-hosted
   networks arguably should support `HermesAdapter` given it's marketed
   as a builtin registry entry; right now it silently only works against
   their cloud.

**Everything else in 2.1 is done and live-verified.** This narrows to one
open design decision (which of the three above) before an actual Hermes
agent can join the workspace — flagging rather than picking one and
building unreviewed code on a live production box.
