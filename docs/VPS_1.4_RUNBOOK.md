# 1.4 Cross-relay demo — VPS execution runbook

Artifact: `cross_relay_read.py` (repo root). Written + dry-run verified with a
throwaway self-owned key against `relay.primal.net` + `relay.damus.io` (2
relays merged, entry decoded correctly) before this commit. Real proof
still requires the Fold 4 daemon's actual agent key on the VPS — that step
is Hermes's, per role boundaries in ORCHESTRATION.md (panels code, Hermes
deploys + verifies).

## Why the VPS needs the *same* key, not a different one

`daemon_adapter.py` publishes self-owned by default (`NIPAE_OWNER` unset →
owner = agent's own pubkey). NIP-44's conversation key is
`ECDH(agent_sk, owner_pk)`; when `owner_pk == agent_pk`, decrypting requires
knowing `agent_sk` itself — there's no way to derive the same conversation
key from the public key alone. So this demo proves **cross-relay,
cross-machine, cross-process portability with the identical key material**,
not cross-identity access. That's the correct scope for 1.4's success
criterion ("two agents on two machines exchange memory via engrams, no
shared code beyond minipae") — the *code* is independent (this script
shares nothing with `daemon_adapter.py` but `minipae.py`), only the key
crosses machines.

## Key delivery (per docs/KEY_MANAGEMENT.md — pick ONE)

**Option A — copy the exact key** (fastest, matches "copy into gtstate via
helper container chown uid-1001" instruction):
1. On Fold 4, locate the daemon adapter's `NIPAE_NSEC` value (wherever it's
   currently sourced from — vault/launcher env, per the daemon's existing
   convention).
2. Use the same helper-container chown pattern already used for
   `claude-creds` in `/opt/genteam/docker/run_genteam.sh` to place the key
   into the `gtstate` Docker volume on the VPS, owned by uid-1001, mode 0600.
   Do NOT place it on the VPS host filesystem and do NOT pass it as a
   container argv — both are explicitly excluded by KEY_MANAGEMENT.md.
3. Inside the container/session that will run `cross_relay_read.py`, export
   `NIPAE_NSEC` by reading that file, e.g.:
   `export NIPAE_NSEC="$(cat /gtstate/keys/genteam-agent.nsec)"`

**Option B — re-derive the identical key** (no key ever leaves Fold 4):
1. Confirm the `agent_index`/`owner_index` the Fold 4 daemon's key was
   originally derived at (registry entry, per KEY_MANAGEMENT.md's rotation
   note — "no redistribution").
2. On the VPS, with access to the same master seed, run:
   `python3 -c "from derive import derive_agent_key; print(derive_agent_key(master, agent_index, owner_index).hex())"`
3. This reproduces the exact same 32-byte secret deterministically — no
   key file needs to cross the network at all.

Either path ends with a valid `NIPAE_NSEC` in the VPS session's environment
only (never a file the container doesn't own, never a CLI arg, never a repo).

## Running the demo

```bash
cd minipae   # this repo, cloned/pulled on the VPS (Python 3.12.3 +
             # websockets 11.0.3 + cryptography 49.0.0 — no installs needed
             # per the task brief)
export NIPAE_NSEC="<delivered via Option A or B above>"
python3 cross_relay_read.py --machine <fold-4 machine_id, e.g. be644354...>
```

## Success signal

- Exit code 0
- At least one `mem/genteam/computer/<machine_id>/{state,last-turn}` block
  printed with matching `value`/`provenance` to what Fold 4 last published
  (cross-check against Fold 4's own `minipae.py ls`/`get` output or the
  daemon adapter's publish logs)
- `[cross-relay-read] N entries decoded across 2 relays` with N ≥ 1

If it prints nothing / exits 1, the two most likely causes: (a) wrong key
(doesn't match the agent that published — conversation key won't decrypt,
`decode_body` raises silently caught per-event, nothing prints), or (b) the
`--machine` filter doesn't match the real `machine_id` — rerun without
`--machine` to see all `mem/genteam/*` entries this key can decrypt.
