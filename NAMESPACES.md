# NAMESPACES — engram slug conventions for minipae (NIP-AE)

Every adapter that writes engrams MUST use its own namespace under `mem/`
so adapters never collide on slugs. This file is the source of truth; it
MUST be updated when a new adapter lands (before its first engram write,
per the locked plan).

## Rules

1. A namespace is the FIRST path segment after `mem/`.
2. An adapter owns everything under its namespace.
3. Cross-namespace reads are allowed (merged read view — see 3.3);
   cross-namespace writes are not (without a plan amendment).
4. The `core` engram is reserved for agent identity (never namespaced).

## Namespaces (registered)

| Namespace       | Adapter / producer                        | Status   |
|-----------------|-------------------------------------------|----------|
| `mem/genteam/*` | GenTeam daemon session/turn state adapter | active   |
| `mem/hermes/*`  | Hermes memory tool bridge                 | active   |
| `mem/vantage/*` | Vantage agents via buzz_bridge            | planned  |
| `mem/buzz/*`    | Buzz/Crucible native memory               | planned  |
| `mem/ga/*`      | OpenAgents workspace state                | planned  |
| `mem/commonly/*`| Commonly CAP pod state                    | planned  |
| `mem/openclaw/*`| OpenClaw agent state/skills (Phase 3.1 G1) | planned  |
| `mem/skills/*`  | Shared skill catalog (Phase 3.2)          | planned  |

## Example slugs

- `mem/genteam/computer/92dcbf5747d1/last-turn`
- `mem/genteam/computer/92dcbf5747d1/session/<session-id>`
- `mem/hermes/profile/default/memory/<key>`
- `mem/vantage/agent/<agent-id>/state`
- `mem/openclaw/agent/<id>/state`
- `mem/openclaw/agent/<id>/skills/<skill-id>`

## Reserved

- `core` — agent identity engram (un-namespaced, one per agent-owner pair)

## Merged read view (planned, Phase 3.3)

For a given agent identity, a merged view across namespaces is assembled by
reading all engrams under the agent's `mem/*` and projecting them into a
single logical store, namespaced keys preserved. This prevents per-framework
silos inside the bus (the anti-goal of the vision).
