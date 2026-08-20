# RUNTIME_REGISTRY.md — runtime registration inventory (Phase 3.1 feed)

Status: IMPLEMENTED. Phase 3.1 landed — see `runtime_registry.json` (repo
root) for the real, schema-tested, live-checked registry this doc specified.
This file remains the design rationale/spec; the JSON file is the source of
truth for current registration state.

Scope: the four execution-fleet runtimes named in the Phase-3 brief —
genteam-daemon, OpenClaw, Hermes, Vantage. OpenAgents and Commonly appear here
only as adjacent entries (§6) because they already own namespaces in
NAMESPACES.md; they are the Phase-2 dispatch layer, not Phase-3 registration
targets.

---

## 1. What a registry entry is

A registry entry is the canonical, machine-readable record of ONE runtime as
an agent/computer on the bus. It exists so that:

- the merged read view (Phase 3.3) knows which namespaces to project for which
  agent identity;
- provenance tags (docs/PROVENANCE.md) can be validated against known
  producers (`source` / `source_version` are registry-checked, never
  free-form);
- credential inventory (docs/KEY_MANAGEMENT.md) is machine-reachable —
  rotation, storage location, and per-host placement are recorded, not
  tribal;
- a runtime can be health-checked and, if it stops writing engrams, the
  difference between "runtime down" and "runtime silently not writing" is
  observable.

Every entry is anchored to an agent identity: the NIP-AE agent key
(m/44'/30174'/<agent>'/<owner>', hardened only — KEY_MANAGEMENT.md §Derivation
scheme). The `core` engram (NAMESPACES.md §Reserved) is the identity record;
the runtime registry entry is the *operational* record for each runtime that
speaks for that agent. One agent may run on several runtimes; each
runtime-host combination gets its own entry (see genteam-daemon, two hosts).

---

## 2. Runtime inventory

### 2.1 genteam-daemon

What it is: Layer-3 EXECUTE runtime. GenTeam local-agent daemon (local turns
against genspark.ai) running as a hardened Docker container on the VPS
(2.25.70.156) and in a tmux session on the Fold 4. Version 0.13.0
(image `genteam-daemon:0.13.0`, repo `docker/run_genteam.sh`).

Identity / credential model:

| Item | Value |
|------|-------|
| Runtime-internal id | `machine_id` — ~12-hex, from `~/.genteam/config.json` (e.g. `92dcbf5747d1`); the daemon's identity inside GenTeam's Computers model. NOT cryptographic; changes per install. |
| Machine credential | `gtm_...` per computer, sourced from the GenTeam Computers page; injected as `GENTEAM_KEY` env to the launcher. NEVER in a repo. Rotation: new key from Computers page + launcher update. ADVISORY (open item): a `gtm_` key appeared in ps/history earlier — rotate per KEY_MANAGEMENT. |
| Driver credentials (optional) | `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` passed through env for claude/codex drivers (`run_genteam.sh`); not part of the agent identity. |
| NIP-AE agent key | `nsec1`/hex per (agent, owner) pair, BIP-32 derived (KEY_MANAGEMENT). The SAME key crosses machines (1.4 runbook Option A/B — key crosses machines, identity does not). Placement: `gtstate` volume on VPS (uid-1001, 0600, via helper-container chown pattern); vault on Fold 4. |
| Provenance (PROVENANCE.md) | `source=genteam-daemon`, `source_version=0.13.0`, `created_by=<agent pubkey>`, `turn_id=<daemon turn id>` (TURN_RE patterns in `daemon_adapter.py`). |

Mem namespace it writes/reads (NAMESPACES.md):

- `mem/genteam/*` — ACTIVE.
- Writes (via `daemon_adapter.py`): `mem/genteam/computer/<machine_id>/state`
  (heartbeat: online/ready, ws status), `.../last-turn` (last turn outcome),
  `.../session/<session_id>` (per-session notes).
- Reads: `cross_relay_read.py` (1.4 cross-relay demo), future merged view (3.3).

Hosts:

| host_id | Where | Transport | Health probe |
|---------|-------|-----------|--------------|
| `vps-genteam` | 2.25.70.156, container `genteam-daemon` (gtstate volume; hardened: `--cap-drop ALL`, `--no-new-privileges`, `--read-only` + tmpfs, `--memory 2g --cpus 1 --pids-limit 256`, `--user genteam`, `--restart unless-stopped`) | docker | `docker ps` + `docker logs -f` tail |
| `fold4-genteam` | Fold 4, tmux | ssh/local | `~/.genteam/daemon.lock/owner.json` (pid alive) + daemon log (`~/genteam/daemon.log`) |

Registry entry needs (what must be recorded): runtime_id, kind, layer, status;
both host entries with machine_id per host; gtm_ credential ref + rotation
date; NIP-AE key storage path per host; namespace owned; provenance strings;
adapter module; owner pane; verification evidence (last engram readback per
the testing protocol).

### 2.2 OpenClaw

What it is: Layer-3 EXECUTE runtime — open-source local assistant daemon with
a skill model (`openclaw skill install .`, `openclaw start`), multi-channel
gateway (WhatsApp/Telegram/Slack/Discord/iMessage/Signal/CLI), SHA-256
receipt chain per action, and sovereign Ed25519 identity (BIPỌ̀N39-derived per
The-Aether's generated agents). In this ecosystem it is wired as a bridge
backend (`OPENCLAW_AGENT_KEY` in Vantage-Voice-) and a code-generation target
(Swibe → OpenClaw skills, The-Aether `backends/openclaw.js`).

Identity / credential model:

| Item | Value |
|------|-------|
| Runtime-internal id | OpenClaw agent/install name (e.g. `<agent-name>` from SKILL.md); gateway `ws://127.0.0.1:18789` per generated agent. |
| Runtime identity key | Ed25519 keypair (BIPỌ̀N39, sovereign — "identity is cryptographic, not an API key"). Distinct from NIP-AE keys; not yet reconciled to the m/44'/30174' derivation. FLAG for 3.1: decide whether OpenClaw's Ed25519 key IS the agent key (then map it into the derivation/registry) or a runtime-local key (then NIP-AE key is a separate nsec1). |
| Bridge credential | `OPENCLAW_AGENT_KEY` (used by Vantage-Voice- agent bridge). Transport cred, not identity. |
| NIP-AE agent key | `nsec1` derived per KEY_MANAGEMENT — REQUIRED for engram access; not yet provisioned (no OpenClaw adapter exists). |
| Provenance | `source=openclaw`, `source_version=<install version>`; `created_by` = agent pubkey. |

Mem namespace:

- NONE REGISTERED — GAP (see §6 G1). Proposed: `mem/openclaw/*`
  (e.g. `mem/openclaw/agent/<id>/state`, `mem/openclaw/agent/<id>/skills/<skill-id>`).
  NAMESPACES.md rule: a namespace MUST be registered before its first engram
  write — that amendment lands with 3.1, not before.

Hosts: not pinned in repo docs. The registry entry MUST record where the
instance runs (Fold 4 and/or VPS) + gateway endpoint. Host determination is an
open item for 3.1 (confirm with the pane that operates it).

Registry entry needs: runtime_id, kind, status (planned), host(s) + gateway
endpoint, OpenClaw identity key handling decision (above), bridge key ref,
NIP-AE key ref, namespace (pending amendment), provenance strings, owner pane.

### 2.3 Hermes

What it is: Layer-3 EXECUTE + orchestration runtime. Hermes Agent CLI with
named profiles; in this project it is the orchestrator/tester (ORCHESTRATION
role boundaries). It is also a *managed* agent type upstream in OpenAgents
(builtin `HermesAdapter` spawns `hermes chat -q <prompt> -Q [--resume <id>]
[--yolo] [-p <profile>]` — verified, VPS_2.1_RUNBOOK).

Identity / credential model:

| Item | Value |
|------|-------|
| Runtime-internal id | Profile name: `default`, `bino`, `omokoda`, `oso`, `ourschool`(×4) — 8 valid profiles (session-verified). Each profile = one memory namespace scope. |
| NIP-AE agent key | `nsec1` derived per (agent, owner) (KEY_MANAGEMENT). Stored in the credential vault (`~/.hermes/credential_vault.json`). Hermes adapter (`hermes_adapter.py`) uses the same key for push/pull. |
| Bridge credentials | `HERMES_AGENT_KEY` (hostinger tunnel), `HERMES_CONTABO_AGENT_KEY` (contabo, added via herdr) — live Vantage-Voice- bridge backends; `HERMES_BINO_AGENT_KEY` would add THIS profile as a 4th bridge. Transport creds, not identity. |
| Memory store (local) | Markdown `MEMORY.md` / `USER.md` per profile, `§`-separated blocks (also JSON fallback read by `hermes_adapter.py`). This is the private source-of-truth mirrored to engrams. |
| Provenance | `source=hermes`, `created_by=<agent pubkey>`, `turn_id=<session id> when known`. |

Mem namespace:

- `mem/hermes/*` — ACTIVE. Pattern:
  `mem/hermes/profile/<profile>/memory/<sha256-16-key>`.
  Verified live: 15/15 entries on `wss://relay.primal.net` (damus was HTTP
  503 → publish retry-with-backoff 2/4/6s added; primal is the reliable
  relay). Readback verified via `minipae.py ls`/`get`.

Hosts: this Mac (this session's host), Fold 4 (Hermes pane), VPS (via
OpenAgents HermesAdapter / herdr bridges). Each host running a profile is a
host entry; the namespace pattern is profile-scoped so multiple hosts can
share one profile only if key + profile state are shared (KEY_MANAGEMENT:
derivation, not redistribution).

Registry entry needs: runtime_id, kind, layer, status (active); profile list;
per-profile namespace pattern; NIP-AE key ref + vault path; bridge key refs;
adapter module (`hermes_adapter.py`); owner pane (Hermes = orchestrator);
verification evidence (live readback status + relay health).

### 2.4 Vantage

What it is: Layer-3 EXECUTE / API platform — agent platform with Genesis
(spawn child agents, discover by skill), Collectives (shared workspaces, A2A
delegation), Mesh (trust), MCP surface (~669 tools). Two instances:

| instance | URL | Version | Reachability from agent env |
|----------|-----|---------|------------------------------|
| local | `http://localhost:8000` | 0.2.0 (ffmpeg present) | local |
| remote | `http://omokoda.duckdns.org:8001` | 0.2.1 (extra modules; no ffmpeg) | REST :8001 times out; **MCP at `https://omokoda.duckdns.org/mcp` IS reachable** (verified) |

Identity / credential model:

| Item | Value |
|------|-------|
| Runtime-internal id | Vantage agent name (name-addressed; Genesis mints/spawns, Collectives groups); Buzz registration gives each agent a sealed-seed NIP-01 identity (`/api/agents/me/buzz/register` — buzz-vantage-integration). |
| API credential | `X-API-Key` / `MESH_KEY` (mesh config: `STEWARD_URL` + `MESH_KEY`); bridge via Vantage-Voice- `callVantageAgentBridge()`. |
| NIP-AE agent key | `nsec1` derived per KEY_MANAGEMENT — needed for engram access under `mem/vantage/*`; not yet provisioned (no adapter). |
| Provenance | `source=vantage` (or `buzz_bridge` when the bridge writes, per NAMESPACES.md producer), `created_by=<agent pubkey>`. |

Mem namespace:

- `mem/vantage/*` — PLANNED. Pattern (NAMESPACES.md example):
  `mem/vantage/agent/<agent-id>/state`. Producer: `buzz_bridge`.

Registry entry needs: runtime_id, kind, status (planned); instance entries
with endpoint + reachability caveats (MCP on 443 vs REST on 8001 — record
BOTH; the registry must not assume one transport); auth model + key refs;
agent-id minting ref (Genesis / Buzz registration); namespace; adapter
(`buzz_bridge` planned); owner pane (wD/w3 per plan-v3); verification: MCP
handshake + (once adapter lands) engram readback.

---

## 3. Registry entry schema (proposal for 3.1)

One JSON object per runtime-host. `schema: runtime-registry/v1`.

```jsonc
{
  "schema": "runtime-registry/v1",
  "runtime_id": "genteam-daemon",            // stable slug, matches NAMESPACES producer
  "name": "GenTeam daemon",
  "layer": "3-execute",                       // plan-v3 layer (1 identity, 2 dispatch, 3 execute, 4 deliver)
  "kind": "daemon-container",                 // daemon-container | cli-agent | assistant-daemon | api-platform
  "status": "active",                         // active | planned | deprecated
  "identity": {
    "runtime_id_fields": ["machine_id"],      // runtime-internal identifiers
    "nsec_path": "m/44'/30174'/<agent>'/<owner>'",
    "agent_pubkey_ref": "<vault key or core engram slug>",
    "notes": "OpenClaw Ed25519 reconciliation TBD (G4)"
  },
  "credentials": [                            // refs only — never secrets
    { "type": "gtm_", "ref": "<vault key>", "storage": "gtstate|vault|env",
      "rotation": "per GenTeam Computers page", "last_rotated": "2026-08-12" },
    { "type": "nsec1", "ref": "<vault key>", "storage": "gtstate (uid-1001, 0600)" }
  ],
  "hosts": [
    { "host_id": "vps-genteam", "endpoint": "2.25.70.156",
      "transport": "docker", "health": "docker ps + log tail",
      "machine_id": "92dcbf5747d1" }
  ],
  "namespaces": ["mem/genteam/*"],            // NAMESPACES.md-owned prefixes
  "provenance": { "source": "genteam-daemon", "source_version": "0.13.0" },
  "adapter": "daemon_adapter.py",
  "owner_pane": "wM/wC",
  "registered_at": "2026-08-13T00:00:00Z",
  "verified": { "health": true, "engram_roundtrip": true, "last_check": "2026-08-13T00:00:00Z" }
}
```

Registration requirements (minimum to call an entry "registered"):

1. stable `runtime_id` + `kind` + `layer`;
2. identity: runtime-internal id fields, NIP-AE key derivation path + storage
   location per host, agent pubkey ref (the `core` engram slug or vault key);
3. credentials: type + ref + storage + rotation path (KEY_MANAGEMENT inventory
   is the source of truth for types: `gtm_`, `nsec1`, `cm_agent_`, plus
   bridge keys and Vantage `X-API-Key`/`MESH_KEY`);
4. namespace ownership per NAMESPACES.md (including any pending amendment —
   see G1);
5. provenance `source`/`source_version` per PROVENANCE.md;
6. adapter module ref (the minipae adapter that writes/reads the namespace);
7. hosts with endpoint, transport, health probe;
8. owner pane + registered_at/updated_at (git history is the audit trail).

## 4. Lifecycle + verification

- register → verify → active → (deprecated).
- `status: active` REQUIRES verification evidence per the ORCHESTRATION
  testing protocol (panels never self-certify):
  - health: probe from §2 host tables;
  - engram roundtrip: adapter writes → orchestrator `minipae.py ls`/`get`
    readback shows real content on a live relay;
  - cross-relay (post-1.4): write on A, read on B.
- `status: planned` entries (OpenClaw, Vantage) become `active` only when
  their adapter + namespace amendment land and the same verification passes.

## 5. Delivery shape for 3.1

- This doc is the spec; the panes implement:
  - `runtime_registry.json` (or YAML) in the repo, seeded with the four
    entries from §2; validated by a schema test;
  - NAMESPACES.md amendment for `mem/openclaw/*` (G1) as part of the same
    change set (namespace must precede first write);
  - per-runtime health/verification wiring (host probes).
- The registry stays in git; entries mutate, git history is the audit trail.

## 6. Findings / gaps (this research pass)

- G1 (MUST fix before 3.1 writes): OpenClaw has no namespace. Amend
  NAMESPACES.md with `mem/openclaw/*` (proposed slugs above) in the same
  commit as the registry.
- G2: `mem/vantage/*` is marked `planned` in NAMESPACES.md; Vantage stays
  `status: planned` until `buzz_bridge` lands. Do not register as active on
  the strength of the API platform alone — the bus contract is the engram
  namespace.
- G3: `gtm_` key rotation advisory is open (key appeared in ps/history).
  Registry entry records `last_rotated`; rotate before/with 3.1.
- G4: OpenClaw's Ed25519 runtime identity vs the NIP-AE derived nsec —
  reconciliation decision needed (same key mapped into derivation, or
  separate keys). Until decided, OpenClaw entry stays `planned`.
- G5: deepseek-harness is NOT a registration target — it is an eval candidate
  (ORCHESTRATION §Flagged candidate). If it becomes a Layer-3 runtime after
  the VPS snapshot tests, a 5th entry is added then; schema supports it
  unchanged (`kind: cli-agent`, namespace proposal `mem/deepseek/*`).
- G6: adjacent dispatch-layer runtimes (OpenAgents `mem/ga/*`, Commonly
  `mem/commonly/*` + `cm_agent_` creds) already own namespaces; the schema
  accommodates them — entries land when Phase 2 closes, not in 3.1.
- G7: KEY_MANAGEMENT keeps the per-agent index (`agent_index`) in the vault
  registry; the runtime registry references it (`nsec_path`). Keep the two
  registries linked, not duplicated.
