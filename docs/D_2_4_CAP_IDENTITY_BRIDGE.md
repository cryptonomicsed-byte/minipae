# 2.4 — Commonly↔Buzz identity bridge

Task 2.4 (plan-v3), gated on 2.2 (landed, `f87f14b`) and 2.3 (landed,
`ea55f87`). Written against 2.3's real, live-verified artifacts
(`commonly/README.md`, `commonly/webhook_agent.py`) — not the task
brief's description of CAP, which turned out to matter (see below).

## What CAP's actual identity model is (from 2.3's proof, not assumption)

Reading `commonly/webhook_agent.py` and the install call in
`commonly/README.md`:

- **Agent installation** (`POST /api/registry/install`) is gated by a
  **JWT** from a human/operator login (`POST /api/auth/login`) — a
  session credential, not a cryptographic identity the agent itself
  proves.
- **Per-event authentication** is `X-Commonly-Signature: sha256=<hmac>` —
  **HMAC-SHA256 over the raw body, keyed by `webhookSecret`**
  (`verify_signature()`, `webhook_agent.py` lines 21-25). This is a
  **symmetric bearer secret**, not a signature verification of an
  asymmetric keypair. Whoever holds `webhookSecret` can produce valid
  requests as that CAP installation; CAP never sees or verifies a Buzz
  Schnorr signature, a Buzz pubkey, or anything Nostr-shaped.

This means the literal question 2.4 was framed around — "can a Buzz
identity authenticate as a CAP agent without a second keypair" — has a
precise answer: **not via CAP verifying the Buzz keypair directly** (CAP
has no asymmetric-signature verification path at all in the webhook
runtime as built and proven); Commonly's own backend would need a new
signature-verification code path for that, which is out of scope here
(I have not touched Commonly's code, per this task's lane boundary — the
identity-verification primitive itself lives on their side).

## What IS achievable without a second independently-generated secret

CAP's `webhookSecret` is just an opaque string at install time — nothing
requires it to be randomly generated. It can be **deterministically
derived from the Buzz agent's own secret key**, so there is still only
one seed of truth (the Buzz nsec) even though CAP treats the derived
value as an ordinary bearer secret rather than verifying a signature.
Same "shared root, forked trees" pattern already used for the
BIPON39↔NIP-06 key-sharing question earlier in this plan negotiation —
consistent with the project's existing key-management posture
(`docs/KEY_MANAGEMENT.md`: "rotation = re-derivation, not
redistribution").

```python
# cap_bridge.py — sketch, HKDF over minipae's existing primitives
# (reuses _hkdf_extract/_hkdf_expand already in minipae.py; no new dep)

def derive_cap_webhook_secret(buzz_seckey: bytes, pod_id: str, version: int = 1) -> str:
    """Deterministic CAP webhookSecret from a Buzz agent's own key.

    Domain-separated per pod (so one Buzz identity can hold distinct CAP
    installs per pod without secret reuse) and per version (so rotation
    is bumping `version`, not minting and redistributing a new random
    secret — matches KEY_MANAGEMENT.md's rotation model).
    """
    info = f"cap-webhook-secret/v{version}/{pod_id}".encode()
    prk = m._hkdf_extract(buzz_seckey, b"commonly-cap-bridge")
    return m._hkdf_expand(prk, info, 32).hex()
```

## What this does NOT give you — stated plainly, not oversold

- No per-turn cryptographic binding back to the Buzz identity. CAP's reply
  is authored under the CAP installation's own display identity (`README.md`:
  reply posted as user `bondhive-cap-proof`), not signed by the Buzz key
  per-message. The trust chain is still "whoever holds the derived secret
  acts as this installation" — identical bearer-secret trust model CAP
  always has, just with a non-random, non-independently-stored source for
  that secret. That is a real, meaningful improvement for key management
  (one seed to protect and rotate, not two), not a cryptographic identity
  upgrade for CAP itself.
- If genuine signature-verified CAP auth is wanted later (CAP validating a
  NIP-98-shaped signed event instead of only an HMAC secret), that is a
  feature request for Commonly's own webhook runtime, not something a
  bridge sitting outside their codebase can retrofit.

## A local mapping table is still needed (non-sensitive)

CAP assigns its own opaque `installation_id`/pod-scoped identity string on
install (2.3's proof: installation `6a7e54405f61add99795c87f` for pod
`6a7e53785f61add99795c85e`). The bridge needs a small local table:
`buzz_pubkey ↔ cap_installation_id ↔ pod_id`. Both sides of that mapping
are public identifiers already, not secrets — storing it doesn't add a
new key-management burden the way a second random secret would have.

## Status: designed, NOT executed

I have **not** registered anything against a live Commonly instance and am
not going to right now. Per the orchestrator's note, 2.3's proof data was
destroyed by a MongoDB ransomware wipe and re-proving/hardening is
pending on wC's lane — registering a new CAP install against that same
infrastructure before it's hardened would be adding load to a compromised
system mid-incident, not validating anything durable. `derive_cap_webhook_secret`
above is a pure function with no network/install side effects — safe to
land now; the actual install-time wiring should wait for wC's
hardening pass to close out.

## Open question worth surfacing separately (not blocking 2.4)

The ransomware wipe is a real security incident on shared infrastructure.
I don't have visibility into which VPS/host it hit or whether it's
isolated from the VPS minipae's own material lives on (2.25.70.156,
gtstate volume). Worth an explicit confirmation from wC/Hermes that
the compromised MongoDB instance is genuinely isolated from minipae's
key material and the GenTeam daemon container, not just assumed to be —
same root-cause-before-move-on instinct as everything else this session.
