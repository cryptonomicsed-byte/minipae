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

## Deploy (VPS: root@2.25.70.156, docker already present per 1.4's VPS profile)

```bash
git clone https://github.com/openagents-org/openagents.git /opt/openagents
cd /opt/openagents
docker compose up -d
curl -f http://localhost:8700/api/health   # wait for healthy before continuing
```

No changes needed to the upstream `docker-compose.yml` for a first deploy —
it has no required env vars (the `OPENAI_API_KEY`/`ANTHROPIC_API_KEY` lines
are commented-out optional extras for LLM-direct agent types, irrelevant to
a Hermes-CLI-driven agent, which shells out to the already-installed
`hermes` binary rather than calling a model API directly).

## Register a workspace + hermes-type agent

The registry entry (`hermes.yaml`) requires the `hermes` binary to be
reachable inside wherever `HermesAdapter` spawns processes. Two shapes,
pick based on where the OpenAgents container can actually reach a working
`hermes` install:

- **VPS-local Hermes**: if a `hermes` CLI is (or will be) installed inside
  the OpenAgents container/host directly, register the agent there — see
  registry install block (`scripts/install.sh` from NousResearch/hermes-agent).
- **Fold 4 / Mac via herdr bridge**: per plan-v3 (2.1: "hermes agents (Fold 4
  + Mac via herdr bridge wK)"), the intent is for OpenAgents on the VPS to
  dispatch to the *existing* Hermes sessions already running on Fold 4/Mac,
  not spin up new local ones. I don't have herdr's bridge-endpoint contract
  in this repo/session — that's orchestrator-side tooling. This half of 2.1
  (wiring the herdr bridge into an OpenAgents agent registration) needs
  Hermes to specify the bridge endpoint/protocol; I can't fabricate it
  without risking a config that looks plausible but doesn't actually route
  anywhere real.

Once a `hermes` binary is reachable, workspace + agent registration is
via OpenAgents' own Studio UI (`:8700/studio`) or its HTTP API — no minipae
code involved at this stage; NIP-AE bridging is 2.2, not 2.1.

## Open item for Hermes

Confirm which shape (VPS-local vs herdr-bridge-to-existing-session) 2.1
should actually register, and if herdr-bridge, hand me the bridge
endpoint/protocol so I can write the actual agent registration config
rather than leaving it as a placeholder.
