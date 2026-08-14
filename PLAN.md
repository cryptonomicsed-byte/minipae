# PLAN.md — plan-v3, locked, committed to the repo

This is plan-v3 as PLAN-LOCKed by both parties (minipae-claude wM:p1,
ecosystem orchestrator wC:p1), copied verbatim from `/tmp/plan-v3.md`
(never previously version-controlled — this commit fixes that). Section
7 below is a status appendix added at commit time, tracking what's
actually built and verified against what section 4 planned; it is not
part of the locked negotiation text.

---

## 0. VISION (LOCKED — all parties agree)

Every agent reads/writes the SAME portable memory, lives under the SAME identity
model, dispatches through ONE collaboration layer, produces deliverables on
self-hosted infra. No vendor lock-in, no per-framework silos. Memory survives
runtime changes; ownership cryptographic; claims falsifiable.

## 1. LAYERS (LOCKED)

- **M MEMORY** — NIP-AE via minipae — DONE/proven
- **1 IDENTITY** — Buzz + Crucible — exists
- **2 DISPATCH** — OpenAgents primary, Commonly parallel — Phase 2
- **3 EXECUTE** — genteam-daemon (VPS+Fold4), OpenClaw, Hermes, Vantage — partially live
- **4 DELIVER** — GenOffice — cloned, not wired

**[V2] Layering rule amendment (LOCKED)**: unproven layers within one phase may be
deprecated/swapped — escape hatch on "add layers, never replace".

## 2. DONE/PROVEN (LOCKED — not replanned)

a. minipae — NIP-AE client, github.com/cryptonomicsed-byte/minipae, verified
   vs official vectors, live on relay.damus.io
b. GenTeam daemon — VPS hardened container + Fold 4 tmux, vetted, ETECSA-proof
c. Recon: OpenAgents, Commonly (license VERIFIED Apache-2.0), GenOffice, Buzz NIP-AE

## 3. DECISIONS — FINAL ROUND OUTCOMES

- **D1 DISPATCH** — LOCKED with [V3] Phase-2 split per C3: 2.3 = Commonly webhook
  driver proof (independent of 2.2); 2.4 = Commonly↔Buzz identity bridge, gated
  on 2.2's NIP-98 envelope deliverable.
- **D2 ADAPTER ORDER** — LOCKED: daemon-first (1.2), Hermes second (1.3). 1.4 demo
  uses `mem/genteam/*` explicitly; merged read view across namespaces is 3.3.
- **D3 AUTH ENVELOPE** — collapsed out of the decision list (deliverable of 2.2).
- **D4 CRUCIBLE** — LOCKED: separate layers; provenance-tag schema is 1.5.
- **D5 GENOFFICE** — LOCKED: standalone service first, speaks de_* vocabulary
  from day one, no bespoke API.

## 4. SEQUENCE v3 — FINAL SHAPE

**PHASE 1 — Memory bus maturity**
1.1 minipae hardening (nsec1, NIP-65, sync cache, streaming subscribe, tests)
1.2 daemon session adapter (`mem/genteam/*`)
1.3 Hermes memory adapter (`mem/hermes/*`, profile-scoped)
1.4 cross-relay demo on a public relay
1.5 engram provenance-tag schema
1.6 key management + rotation policy (BIP-32 derived nsec1, NAMESPACES.md,
    relay redundancy)

**PHASE 2 — Dispatch layer**
2.1 OpenAgents on VPS, hermes agents connected
2.2 OpenAgents↔Buzz bridge → NIP-98 envelope decision
2.3 Commonly webhook driver proof (independent of 2.2)
2.4 Commonly↔Buzz identity bridge (gated on 2.2)

**PHASE 3 — Execution fleet**
3.1 register all runtimes as agents/computers
3.2 shared skill catalog (de_* verb vocabulary)
3.3 merged memory read view across namespaces

**PHASE 4 — Deliverables**
4.1 GenOffice document-worker service (headless, de_* vocabulary)
4.2 BPO pilot: one agent produces a real client deliverable end-to-end

## 5. SUCCESS CRITERIA — FINAL

- Two agents on two machines exchange memory via engrams, no shared code beyond
  minipae (1.4, `mem/genteam/*`)
- Memory written before a runtime migration is readable after — portability
- Orchestrator (wM) dispatches to Fold-4 bridge (wK) through the grid
- Vantage agent produces a real .docx deliverable from a broadcast intent
- Crucible evaluates ≥1 engram-backed claim with n_eff > 1 (dependency: ≥2
  independent-witness agents by then — tracked, not assumed)
- Every credential type has documented storage + rotation path before Phase 2
- Namespace + derivation specs exist in repo before the first real engram

## 6. ECOSYSTEM INTEGRATION — orchestrator input [V3, from wC:p1]

Locked decisions from the negotiating session (do not replan):
- NIP-shaped keys are the birth identity primitive inside Omo-Koda2's kernel
  (derived from the existing BIP39 seed; format, not a network dependency)
- Bondhive gated: standalone-with-a-deadline, needs one real caller or archived
- Bondhive's first-caller question resolved: minipae/Hermes must NOT be forced
  to satisfy the gate (shared crypto stack ≠ shared use case); a real caller
  must come from OSOVM/Omo-Koda2/Vantage with an independent need

---

## 7. STATUS APPENDIX (added at commit time, not part of the locked negotiation)

What's actually built and verified, phase by phase, as of this commit:

**Phase 1 — DONE, verified.** 1.1-1.6 all landed with live-relay proof, not just
design: hardening caught and fixed 5 real crypto bugs (bech32 checksum,
NIP-44 padding formula, padding-integrity validation, secret-key range
checks, max-plaintext mismatch) plus a later-found `publish()` OK-frame
parsing bug that silently reported every relay rejection as success. Daemon
+ Hermes adapters live. 1.4's cross-relay proof independently verified by
the orchestrator on the VPS. Key derivation (1.6) closed on the Omo-Koda2
side too — BIPON39's BIP-32 bug found, fixed, official-vector-verified,
differentially verified against an independent library, and now live as a
real tier-0 kernel tool.

**Phase 2 — mostly done, one real architectural blocker open.**
2.1: deployed live on the VPS despite the box being at 100% disk with live
trading infra running alongside; root-caused and fixed the actual grpcio
gap (wrong pyproject extras group). One open blocker: `HermesAdapter`
only speaks OpenAgents' hosted SaaS join API, not the self-hosted
network's native protocol — needs a decision, documented with three
options, not yet chosen.
2.2: DONE — NIP-42 auth implemented and live-proven against the real
production Buzz relay. This incidentally proved Crucible's own docs
wrong — kinds 47001-47007 are rejected by the deployed relay ("restricted:
unknown event kind"), confirmed both from source and live,
post-authentication. The OpenAgents↔Buzz bridge agent itself
(`ga_bridge.py`, a genuine SDK-connected local-network agent, not a REST
poller) was subsequently built, deployed, and live-proven end to end: a
real channel message posted in the local OpenAgents network was mirrored
to a real, authenticated engram on the production Buzz relay and read
back with exact content intact. Getting there required real debugging
against undocumented/inconsistently-documented SDK behavior (full account
in `docs/D_2_2_GA_BRIDGE.md`) — most notably that `agent.start()` doesn't
block and silently drops the message-polling task unless
`agent.wait_for_stop()` is called after it, and that the relay does
Host-header virtual routing requiring a pre-connected-socket workaround
(`minipae._open_presocket`, `connect_url=` on the authenticated
publish/query functions). Not yet done: running it as a supervised
long-lived production process (it was run under a test harness for the
proof, then stopped) — needs a systemd unit or equivalent, not set up as
part of this deliverable.
2.3: Commonly CAP webhook driver proven live by a different pane, survived
and recovered from a real MongoDB ransomware incident (caught by the
orchestrator, root-caused, hardened, re-verified clean).
2.4: Buzz-side identity derivation designed, implemented, tested
(`cap_bridge.py`) — CAP's real auth model turned out to be a symmetric
HMAC bearer secret, not signature verification, so "Buzz identity without
a second keypair" is achievable as deterministic secret derivation, stated
plainly as not a cryptographic identity upgrade to CAP itself. Commonly-side
install wiring is ready for whoever owns that execution lane.

**Phase 3 — DONE, real implementations, not just design docs.**
3.1: `runtime_registry.json` with real, live-checked data (not the design
doc's placeholder examples) for genteam-daemon and Hermes; OpenClaw and
Vantage correctly kept `planned` per their own gating rules (no adapter
exists yet for either). Schema-tested.
3.2: `skills/catalog.yaml` with the 10 day-one de_* verbs plus one fully
working skill (`de_verify_skill`, the meta-skill, genuinely checks catalog
well-formedness and was tested against a deliberately-broken copy to
confirm it actually catches errors).
3.3: `merged_view.py` — a real implementation of the namespace + trust-class
separation the plan's confidentiality-model finding required (minipae
engrams are private/NIP-44-encrypted; Crucible claims are intentionally
public), tested to confirm private and public entries are never flattened
into one undifferentiated list even when both exist.

**Phase 4 — core deliverable done, full BPO pilot still needs Vantage-side
wiring.** GenOffice's README documents only Electron desktop apps, no
headless service — looked like a blocker until the actual package source
was checked: the underlying engine packages are Electron-free and usable
headlessly, just not published to npm standalone. Built and live-verified
`de_package_docx` — parses a real docx, generates new paragraphs via
GenOffice's real API, produces structurally-valid output with exact
requested content confirmed present. What's not done: wiring this to an
actual Vantage broadcast-intent trigger (depends on Vantage's own adapter,
which is `planned`, not built).

**Open items not resolved by anyone yet**: gtm_ credential rotation
(investigated — worse than described, live in `ps auxww` right now, but
actual rotation needs GenTeam dashboard access + the daemon binary has no
non-argv key input at all, so rotation alone won't close the exposure
class); deepseek-harness stays eval-only per explicit instruction.
