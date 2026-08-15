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

## RESOLVED — option 1 chosen, patched and live-verified

Ownership got clarified: `/opt/ares/buzz-relay` (the source behind
`buzz-prod-relay-1`) is a local checkout with an existing divergent
commit (`7c1425a`, a scoped NIP-42 exemption for kind:24134 device
pairing) authored by `cryptonomicsed-byte` — the same account this whole
session has committed under. Not a distant, unreachable upstream party;
already-patched infrastructure with direct precedent for exactly this
shape of change.

Patched `required_scope_for_kind()` with a scope-mapping arm for
`47000..48000` → `Scope::UsersWrite` (same treatment as `KIND_AGENT_ENGRAM`
above it — same shape, agent-authored global state, not channel-scoped).
Committed locally as `1e5ef59` in that repo (not pushed to origin, same
as the precedent commit — this is a VPS-specific operational patch, not
upstream-bound).

**A real incident happened building this, caught and recovered
immediately, zero data loss**: the first build used this checkout's
stale local `main` (339 commits behind `origin/main`), which was missing
migration files `0026`-`0028` that the *actually deployed* binary already
had applied (deployed from `relay-v0.2.1` + the same local patch, not
from this stale branch). Deploying that first build crashed the relay —
"migration 26 was previously applied but is missing in the resolved
migrations." Rolled back within about a minute by recreating the
container from the untouched original image (a binary swap via `docker
cp`/`mv` only ever touches a container's writable layer, never the
underlying image — the pristine image was never at risk). Root-caused
via a read-only query against `_sqlx_migrations` before attempting a
second build, this time from the correct base with the missing
migrations added in (reviewed for safety first — all three are additive:
a new single-row table, an `IF NOT EXISTS` index, a column type widen).

Also found and fixed a second real bug in `minipae.py` itself while
verifying: `_open_presocket`/`connect_url` (built for the earlier
Host-header-routing fix) didn't account for a relay's logical identity
being `wss://` while the actually-reachable `connect_url` is a plain,
non-TLS internal hop — `websockets` infers TLS from the connection URI's
own scheme, so it tried a TLS handshake over a plain socket and failed
with `SSLError WRONG_VERSION_NUMBER`. Fixed via
`_presocket_connect_kwargs()`, which derives TLS-or-not from
`connect_url`'s own scheme, not the logical relay's.

**Live-verified end to end, both ways**: `kind:47001` (Crucible `CLAIM`)
published with `ok: true` using a fresh, unadmitted-but-authenticated
throwaway key, then independently read back via a separate
`query_authenticated()` call with the exact content intact — not just
trusted the publish response, matching this whole session's standard.
`kind:30174` (minipae's own, already-working kind) still correctly
reaches its own downstream `d`-tag validation post-patch, confirming
other kinds' gating is undisturbed.

Built on a separate host (`contabo-vps`) rather than locally — this
box's disk was too tight (2.1G free) for a safe Rust release build,
confirmed by a `cargo check` alone dropping it to 1.2G before being
aborted. Used `rust:1.95-bookworm` to match the relay's own runtime base
image for glibc/ABI compatibility, verified the new migrations were
genuinely embedded in the built binary via `strings` before ever
touching the live container.

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
