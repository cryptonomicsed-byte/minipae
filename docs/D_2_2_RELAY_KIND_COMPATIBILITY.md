# Relay kind-compatibility finding (2.2, affects 2.4 and Phase 3)

Discovered while building 2.2's NIP-42 auth support and testing it against
the real deployed relay, not assumed from docs.

## The finding

`buzz-prod-relay-1` (the real, live Buzz relay running on the VPS,
`ws://localhost:3000`) enforces a **strict kind allowlist** via
`required_scope_for_kind()` in `crates/buzz-relay/src/handlers/ingest.rs`:
"Returns `Err` for unknown kinds — the relay rejects them." Checked both
`~/Buzz` (upstream `block/buzz`) and `cryptonomicsed-byte/Buzz` (the
Crucible fork branch, `claude/agent-native-buzz-arch-e8pte9`) — **neither
has a match arm for the 47000-47999 block** Crucible reserves for its own
kinds (`crates/crucible-core/src/kinds.rs`).

This directly contradicts Crucible's own `docs/BUZZ.md`: *"There is no
relay fork, no schema migration, and no change to how Buzz
authenticates anyone... a stock Buzz relay stores and serves these
events untouched — it just has no opinion about them."* That claim does
not hold for this relay's actual code.

**`kind:30174` (minipae's own NIP-AE kind, `KIND_AGENT_ENGRAM`) IS in the
allowlist** — in fact `crates/buzz-relay/src/api/bridge.rs` has
purpose-built, first-class handling for it ("Build a kind:30174 engram
envelope authored by `agent`, tagged with `owner`"). This relay was
evidently built with NIP-AE/minipae compatibility in mind; Crucible's
kinds were added later (a separate integration effort) and never got the
same relay-side allowlist update.

## Live proof, not just source-reading

Built NIP-42 auth support in minipae (`build_auth_event`,
`publish_authenticated`, `query_authenticated` — see the commit alongside
this doc) specifically to test this empirically rather than trust the
source alone, given how many "documented as done" claims this session
turned out to be stale or wrong on inspection. With a fresh, **unadmitted**
throwaway key, authenticated via NIP-42:

- `kind:30174` → `{"ok": true}`, and an authenticated readback decrypted
  to the exact content published. Full round trip.
- `kind:47001` (Crucible `CLAIM`) → `{"ok": false, "message": "restricted:
  unknown event kind"}` — **after** successful authentication, so this is
  specifically a kind rejection, not an auth failure. Matches the exact
  error string the Vantage↔Buzz blueprint (`buzz_vantage_blueprint.md`)
  documented hitting for a different unlisted kind (30166) — same
  mechanism, independently confirmed for Crucible's range too.

## What this means for 2.4 and Phase 3

- **2.4 (Commonly↔Buzz identity bridge)**: unaffected — that design never
  depended on Crucible kinds reaching this relay, it was about CAP's own
  auth model (see `docs/D_2_4_CAP_IDENTITY_BRIDGE.md`).
- **Phase 3's merged read view (3.3)**: the `content_trust_class` addendum
  to `docs/PROVENANCE.md` assumed a *future* adapter could mirror Crucible
  claims into `mem/buzz/*` engrams. That's still fine — engrams describing
  or referencing a claim don't require the claim event itself to be kind
  47001 on *this* relay. But if the actual intent was ever "Crucible
  claims get published directly to this production Buzz relay," that
  needs one of:
  1. A relay-side patch adding 47000-47999 to `required_scope_for_kind()`
     — real code change to `buzz-relay`, not something a bridge outside
     that codebase can do. Given the relay already special-cases 30174,
     this looks like a small, precedented addition, but it's still a
     change to production relay code that should go through whoever owns
     that deployment.
  2. Route Crucible events through a *different*, more permissive relay
     (a plain/stock Nostr relay without this allowlist) — works today,
     no code change, but splits where engrams vs. claims live.
  3. Treat this relay's current behavior as correct-as-designed (maybe
     Crucible claims were never meant to live on the same relay as
     Vantage/minipae/OpenAgents traffic) and leave it alone.

Not picking one of these here — flagging it as a real, verified
architectural fact for whoever owns the Crucible↔relay integration
decision, since Crucible's own docs currently assert something the code
doesn't do.

## 2.2 scope status

The hard, load-bearing part of 2.2 — a working, live-proven NIP-42 auth
layer that lets minipae write/read authenticated events on the real Buzz
relay — is done and verified (see the commit alongside this doc).

**Not yet built**: the actual OpenAgents→Buzz message-mirroring bridge
agent. Checked `sdk/src/openagents/mods/workspace/messaging/adapter.py`
directly — it's a client-side adapter for OpenAgents' own SDK connection
protocol (the same gRPC-based agent-client mechanism `charlie.yaml`-style
local agents use), not a plain REST API a script can poll from outside.
Building this properly means writing a real OpenAgents SDK-connected
agent (using its `AgentClient`/mod-message system to subscribe to
channel messages) that then calls `publish_authenticated()` for each one
— a genuine, separately-scoped increment, not a quick addition on top of
what's here. Flagging as the precise next step rather than rushing an
untested implementation.

## Bonus finding along the way

Building this also caught a real, unrelated correctness bug in
`minipae.publish()` — see the standalone commit "fix: publish() misread
NIP-01 OK frame..." — the live rejection frame from this exact relay
(`auth-required: not authenticated`) is what exposed it; the old code
would have reported that rejection as `ok: True`.
