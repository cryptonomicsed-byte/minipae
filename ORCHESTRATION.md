# ORCHESTRATION.md — coordinator handoff (Hermes = orchestrator/tester)

## Role boundaries (user mandate, 2026-08-13)
- **Hermes (this file's author)**: orchestration + testing ONLY. No code.
- **Claude panels (wM minipae-claude, wC orchestrator)**: all coding.
- No parallel same-work. If a task is assigned to a pane, the other pane does NOT touch it.

## Locked plan (plan-v3, 3-way agreement)
Phases 1-4 as agreed. Full text: /tmp/plan-v3.md (Mac), ~/genteam/plan-v3.md (Fold 4).

## Status at handoff (all verified against live relays unless noted)

### DONE
- 1.1 Hardening: nsec1 checksum decode, NIP-65 relay lists, sync cache, watch mode, padded_len chunk formula (24 official vectors, 71/71 tests). Partner commit 2f2c4f2.
- 1.2 Daemon adapter: `daemon_adapter.py` LIVE — Fold 4 state at `mem/genteam/computer/be644354…/{state,last-turn}` on damus AND primal.
- 1.5 Provenance schema: docs/PROVENANCE.md (body-fields, relay-agnostic).
- 1.6 Keys+namespaces: docs/KEY_MANAGEMENT.md (BIP-32-style m/44'/30174'/<agent>'/<owner>', hardened-only), NAMESPACES.md, derive.py.

### 1.3 — Hermes memory adapter (IN PROGRESS, needs ONE panel commit)
- `hermes_adapter.py` written; loads real Hermes memory (Markdown `§`-format MEMORY.md/USER.md).
- **PUSH VERIFIED by orchestrator 2026-08-13**: 15/15 entries live at
  `mem/hermes/profile/default/memory/<sha256-16>` on wss://relay.primal.net.
  (damus.io was HTTP 503 — rate-limited; retry-with-backoff 2/4/6s added to publish_entry; primal is the reliable relay.)
- Readback VERIFIED via `minipae.py ls` (15 slugs, sizes match) and `get` (decrypts to real USER.md content).
- **BUG to fix (panel)**: `hermes_adapter.py pull` crashes at line 145 —
  `agent_pub.hex()` on a str (line 144 already .hex()'d it).
  Fix: `asyncio.run(m.query(relay, [agent_pub]))`. Then commit 1.3 (incl. ORCHESTRATION.md) and push.

### NEXT (in order)
1. **1.4 Cross-relay demo**: Fold 4 agent writes → VPS container reads `mem/genteam/*`.
   VPS (2.25.70.156, container genteam-daemon Up, claude OAuth driver live) needs minipae.py + a key.
   Key delivery per KEY_MANAGEMENT: derive from master OR copy into gtstate via helper container
   (chown uid-1001 pattern from claude-creds step). Do NOT put keys on VPS host disk.
2. **2.1 OpenAgents on VPS** (docker-compose in repo) + hermes-type agent on a workspace (HermesAdapter exists in upstream).
3. **2.2 OpenAgents↔Buzz bridge** → NIP-98 envelope decision.
4. **2.3 Commonly webhook driver** — one agent joins via webhook, runs a turn (independent of 2.2).
5. **2.4 Commonly↔Buzz identity bridge** (gated on 2.2's NIP-98 deliverable).
6. **Phase 3**: register runtimes (daemon/OpenClaw/Hermes/Vantage), shared skill catalog, merged memory read view (3.3).
7. **Phase 4**: GenOffice document-worker service + BPO pilot (de_* vocabulary day one).
8. **Final**: push locked PLAN.md to repo + full verification pass.

## Flagged candidate (user-approved eval): deepseek-ai/deepseek-harness
- What: DeepSeek's official agent harness, MIT, TypeScript, "everything is a plugin" (vendored Cordis).
  ~40 packages: agent loop (session/tools/plan/todo/subagent/workflow/guard), capability seams
  (shell/fs/lsp/web/e2b sandbox/terminal), skill registry + catalog, Claude Code/Codex hook bridges,
  self-modification, ACP server, JSON-RPC SDK, Python SDK + bundled runtime. Repo: ~/deepseek-harness (198MB).
- Why flagged: the ONLY runtime built for a provider with a live key in our stack (vault /deepseek = working;
  openai dead, claude $0). Chinese origin = embargo-proof by geography — first Layer-3 candidate with no US
  cloud choke point. Plugin seams match the add-layers-never-replace doctrine.
- Engine check: node ^22.19 || >=24 — VPS 22.23.1 and Fold 4 26.2.0 both qualify. Key must be read inside
  the session (vault → file 0600), never argv.
- Candidate uses: (a) Layer-3 runtime in genteam container as DeepSeek-native agent; (b) minipae memory-bus
  plugin via skill/capability seams (mem/genteam/*, mem/hermes/*); (c) shared skill catalog substrate
  (Phase 3); (d) ACP delegate lane from Hermes/herdr; (e) e2b/landlock sandbox for hardened execution;
  (f) BENCHMARK.md for BPO pilot quality gate (Phase 4).
- Caveats: released 2026-08-13 (day zero), pre-release stance — "foundation over blast radius", no compat
  promises (SCHEMA_VERSION/SESSION_FORMAT_VERSION may break). Treat as eval candidate, not a pillar.
- Next move (approved): keyless snapshot tests on VPS (`pnpm run test:snapshot`), verify BENCHMARK claims,
  THEN decide slotting as DeepSeek-native Layer-3 runtime. Do NOT swap anything (add layers, never replace).

## Testing protocol (orchestrator runs, panels never self-certify)
- Offline: `NIPAE_LIVE=1 python3 tests/run_tests.py` (71 tests).
- Live: minipae CLI readback (`ls`/`get`) against the target relay AFTER any write.
- Cross-relay: write on A, read on B, both sides shown.
- Every adapter/feature lands only after orchestrator's readback shows real content.

## Open items
- Fold 4 daemon still running alongside VPS container (user never answered; left live).
- VPS cleanup pending: /root/.anthropic-key, /tmp/creds-backup.json, codex auth state.
- gtm_ key rotation advisory: key appeared in ps/history earlier in the session.
