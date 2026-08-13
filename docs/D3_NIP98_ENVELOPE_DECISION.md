# D3 — NIP-98 envelope decision, resolved against real Crucible/Buzz source

Task 2.2 deliverable (plan-v3). Written against the actual fork:
`cryptonomicsed-byte/Buzz`, branch `claude/agent-native-buzz-arch-e8pte9`
(NOT the upstream `block/buzz` checkout at `~/Buzz` — that has none of this;
confirmed by grepping for `crucible`/`47001`-`47007` there and finding
nothing). Kind numbers, event model, and auth statement below are copied
from source, not from the task brief's description of them.

## What's actually there

`crates/crucible-core/src/kinds.rs`: Crucible reserves the `47000..48000`
block on top of Buzz's own kind usage (`7, 9, 22242, 27235, 40002, 40003,
40100, 43001, 45001, 45003, 46001..=46012`). Two of Buzz's own kinds are
directly relevant to D3: **`22242` is NIP-42** ("AUTH" — relay-level
challenge/response auth over the websocket connection) and **`27235` is
NIP-98** (HTTP Authorization-header auth, an event signed and base64'd into
an `Authorization: Nostr <...>` header). Both are already in Buzz's kind
list, i.e. already implemented and in active use — not something this
bridge introduces.

`crates/crucible-core/src/event.rs`: Crucible events are wire-identical
NIP-01 events — `id = sha256(canonical [0,pubkey,created_at,kind,tags,content])`,
signature = BIP-340 Schnorr over that id, verified via `k256::schnorr`. Same
signing model as minipae's own `build_event`/`event_id` — a Buzz/Crucible
identity is just a secp256k1 keypair, same primitive minipae uses.

`docs/BUZZ.md` (line 17, table row): **"NIP-42 / NIP-98 authentication |
Access control; Crucible adds none of its own."** This is the actual D3
answer, already decided by the Buzz/Crucible authors — not a gap for this
bridge to fill in. Crucible deliberately did not invent its own auth
envelope; it reuses whatever Buzz already does.

**One structural difference from minipae worth flagging explicitly**:
Crucible's `ClaimBody` (`claim.rs`) content is a plain, unencrypted
`serde_json::Value` — claims must be publicly readable and checkable by
the whole community (falsifiability requires visibility). minipae engrams
are NIP-44-encrypted, owner-only-decryptable by design. These are opposite
confidentiality models. Phase 3's "merged memory read view" (3.3) must
not treat `mem/*` engrams and Buzz claim events as the same trust class —
noting this now so it isn't silently conflated later.

## The decision

Match Buzz's existing split by transport surface, since that's what
Crucible already does and there's no reason for the bridge to diverge:

- **OpenAgents↔Buzz bridge posting/reading events via a direct relay
  websocket connection** (NIP-01 `REQ`/`EVENT`, same shape minipae already
  speaks): use **NIP-42 AUTH** (kind `22242`) for the relay-level
  challenge/response, exactly as Buzz's own relay expects.
- **OpenAgents↔Buzz bridge calling an HTTP API surface** (if the bridge
  extends `buzz_bridge.py`'s blueprint via HTTP rather than a raw relay
  connection): use **NIP-98** (kind `27235`, `Authorization: Nostr <...>`
  header) — same envelope the round-2 negotiation already leaned toward
  ("signature-based, relay-portable"), now confirmed to be literally what
  Buzz's own HTTP surface expects rather than a new invention.

Both reduce to the same identity primitive either way: a signed Nostr
event proving control of the keypair. No new auth code for minipae/the
bridge to write — just point the existing NIP-01 signing minipae already
has (`build_event`/`schnorr_sign` — same primitives) at the right kind
(22242 vs 27235) depending on which surface is used.

## The actual gate is community admission, not the envelope

Per `docs/BUZZ.md`: *"agents are community members an operator admitted
with `buzz-admin`, and a key nobody admitted has no standing in the
room."* Signing the right kind of auth event proves key ownership; it does
NOT get an OpenAgents-side agent into a Buzz community. **A human operator
must run `buzz-admin` to add the bridge agent's pubkey to the target
community's roster before any of this works — that's an operational step,
not something 2.2's code can satisfy on its own.** Flagging this explicitly
so it isn't missed when 2.2 gets deployed — a correctly-signed NIP-98/
NIP-42 request from an unadmitted key will be correctly rejected, and
that's Buzz's Sybil defense working as designed, not a bug in the bridge.

## Unblocks 2.4 (Commonly↔Buzz identity bridge)

Per the task brief, 2.4 asks whether a Buzz identity can authenticate as a
CAP agent without a second keypair. With the above confirmed, that
question reduces to: does Commonly's CAP protocol accept a Nostr-signed
event (NIP-98-shaped) as proof of identity, or does it always mint its own
`cm_agent_` token regardless of how the caller proves who they are? That's
a Commonly-side question — I have not touched Commonly's code per this
task's explicit lane boundary (wC owns 2.3/Commonly). Handing this framing
to whoever picks up 2.4.

## Not yet done here (out of scope for this doc)

- No interface code written for the actual OpenAgents↔Buzz bridge itself
  (extending `buzz_bridge.py`'s blueprint) — that's 2.2's remaining
  implementation work, not this decision doc. This resolves *which*
  envelope, not the bridge's transport/dispatch code.
