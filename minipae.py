#!/usr/bin/env python3
"""minipae — minimal NIP-AE (Agent Engrams) client in pure Python.

Implements the block/buzz NIP-AE draft (kind:30174) memory bus so any
runtime (Hermes, OpenAgents, Vantage, Gitea agent repos) can read/write the
SAME portable memory on a Nostr relay.

Wire protocol implemented here (per NIP-AE draft):
  - kind 30174 addressable events, author = agent pubkey
  - slug grammar: `core` or `mem/[...]` (hierarchical, <=255 bytes)
  - d-tag = lower_hex(HMAC-SHA256(K_c, "agent-memory/v1/d-tag" || 0x00 || slug))
  - content = NIP-44 v2 ciphertext under the agent<->owner conversation key
  - owner identified by a `p` tag (pubkey_o); symmetric key => owner can
    always decrypt everything the agent remembers
  - tombstone = body {"slug": ..., "value": null}
  - head selection: addressable events, latest per (kind, pubkey, d)

Dependencies: cryptography, websockets (pure-python BIP-340 + NIP-44 here).

Usage (CLI):
  python3 minipae.py gen-key > agent.nsec        # new agent keypair
  python3 minipae.py ls                          # list slugs
  python3 minipae.py get mem/values/honesty      # print value
  python3 minipae.py set mem/values/honesty "be truthful"
  python3 minipae.py rm  mem/values/honesty      # tombstone

Env: NIPAE_NSEC (agent secret, hex or nsec), NIPAE_OWNER (owner pubkey hex,
     default: agent's own pubkey = self-owned memory), NIPAE_RELAY
     (default wss://relay.damus.io).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import re
import unicodedata
import json
import os
import secrets
import sys
import time

# --------------------------------------------------------------------------
# secp256k1 constants
# --------------------------------------------------------------------------
P  = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
N  = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
GX = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
GY = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8


def _inv(a: int, m: int) -> int:
    return pow(a, m - 2, m)


def _point_add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2 and (y1 + y2) % P == 0:
        return None
    if p1 == p2:
        lam = (3 * x1 * x1) * _inv(2 * y1, P) % P
    else:
        lam = (y2 - y1) * _inv(x2 - x1, P) % P
    x3 = (lam * lam - x1 - x2) % P
    y3 = (lam * (x1 - x3) - y1) % P
    return (x3, y3)


def _point_mul(k: int, point=None):
    point = point or (GX, GY)
    r = None
    while k:
        if k & 1:
            r = _point_add(r, point)
        point = _point_add(point, point)
        k >>= 1
    return r


def _lift_x(x: int):
    if x >= P:
        return None
    c = (pow(x, 3, P) + 7) % P
    y = pow(c, (P + 1) // 4, P)
    if pow(y, 2, P) != c:
        return None
    return (x, y if y % 2 == 0 else P - y)


def _validate_seckey(seckey: int) -> None:
    if not (1 <= seckey <= N - 1):
        raise ValueError("invalid secret key: must be in [1, n-1]")


def pubkey_from_secret(seckey: int) -> bytes:
    """BIP-340 x-only pubkey (32 bytes)."""
    _validate_seckey(seckey)
    pt = _point_mul(seckey)
    return pt[0].to_bytes(32, "big")


def _tagged_hash(tag: str, msg: bytes) -> bytes:
    th = hashlib.sha256(tag.encode()).digest()
    return hashlib.sha256(th + th + msg).digest()


def schnorr_sign(msg: bytes, seckey: int, aux: bytes) -> bytes:
    """BIP-340 Schnorr signature (64 bytes: r || s), full spec incl. even-y
    adjustments and tagged hashes — compatible with nostr/buzz."""
    d0 = seckey
    _validate_seckey(d0)
    P = _point_mul(d0)
    d = d0 if P[1] % 2 == 0 else N - d0          # even-y pubkey convention
    t = (d ^ int.from_bytes(_tagged_hash("BIP0340/aux", aux), "big")).to_bytes(32, "big")
    rand = _tagged_hash("BIP0340/nonce", t + P[0].to_bytes(32, "big") + msg)
    k0 = int.from_bytes(rand, "big") % N
    if k0 == 0:
        raise ValueError("bad nonce")
    R = _point_mul(k0)
    k = k0 if R[1] % 2 == 0 else N - k0          # even-y nonce convention
    e = int.from_bytes(_tagged_hash(
        "BIP0340/challenge", R[0].to_bytes(32, "big") + P[0].to_bytes(32, "big") + msg), "big") % N
    s = (k + e * d) % N
    return R[0].to_bytes(32, "big") + s.to_bytes(32, "big")


def schnorr_verify(msg: bytes, pubkey: bytes, sig: bytes) -> bool:
    """BIP-340 verification (used by head-selection validation)."""
    if len(pubkey) != 32 or len(sig) != 64:
        return False
    P_ = _lift_x(int.from_bytes(pubkey, "big"))
    if P_ is None:
        return False
    r = int.from_bytes(sig[:32], "big")
    s = int.from_bytes(sig[32:], "big")
    if r >= P or s >= N:
        return False
    e = int.from_bytes(_tagged_hash(
        "BIP0340/challenge", sig[:32] + pubkey + msg), "big") % N
    R = _point_add(_point_mul(s, None), _point_mul((N - e) % N, P_))
    if R is None or R[0] != r:
        return False
    return True


# --------------------------------------------------------------------------
# NIP-44 v2 (encryption under conversation key) — per nostr-protocol/nips/44.md
# --------------------------------------------------------------------------
_NIP44_VERSION = 2
_NIP44_MIN_PLAINTEXT = 1
_NIP44_EXTENDED_PREFIX_THRESHOLD = 65536
# Spec (NIP-44 44.md) defines max_plaintext_size as 2^32-1 with a 6-byte
# extended-length prefix for len >= extended_prefix_threshold. In practice no
# interop test vector (paulmillr/nip44 reference suite) exercises that
# branch — everything >= 65536 is explicitly listed as invalid, and the
# largest valid vector tops out at 65535 — so real-world tooling caps here.
# Matching that keeps minipae's engrams portable to standard Nostr clients.
_NIP44_MAX_PLAINTEXT = _NIP44_EXTENDED_PREFIX_THRESHOLD - 1


def _hmac_sha256(key: bytes, msg: bytes) -> bytes:
    return hmac.new(key, msg, hashlib.sha256).digest()


def _hkdf_extract(ikm: bytes, salt: bytes) -> bytes:
    """HKDF-extract (RFC 5869): PRK = HMAC(salt, IKM)."""
    return _hmac_sha256(salt, ikm)


def _hkdf_expand(prk: bytes, info: bytes, length: int) -> bytes:
    """HKDF-expand (RFC 5869)."""
    okm = b""
    t = b""
    i = 1
    while len(okm) < length:
        t = _hmac_sha256(prk, t + info + bytes([i]))
        okm += t
        i += 1
    return okm[:length]


def conversation_key(agent_seckey: bytes, owner_pubkey: bytes) -> bytes:
    """NIP-44 conversation key: HKDF-extract(ECDH_x, salt='nip44-v2')."""
    seckey_int = int.from_bytes(agent_seckey, "big")
    _validate_seckey(seckey_int)
    pubkey_point = _lift_x(int.from_bytes(owner_pubkey, "big"))
    if pubkey_point is None:
        raise ValueError("invalid public key: not a valid curve point")
    x = _point_mul(seckey_int, pubkey_point)[0]
    return _hkdf_extract(x.to_bytes(32, "big"), b"nip44-v2")


def _message_keys(conversation_key_: bytes, nonce: bytes) -> tuple:
    okm = _hkdf_expand(conversation_key_, nonce, 76)
    return okm[0:32], okm[32:44], okm[44:76]  # chacha_key, chacha_nonce, hmac_key


def _calc_padded_len(plaintext_len: int) -> int:
    if plaintext_len <= 32:
        return 32
    next_power = 1 << (plaintext_len - 1).bit_length()
    chunk = 32 if next_power <= 256 else next_power // 8
    return chunk * ((plaintext_len - 1) // chunk + 1)


def _pad(plaintext: bytes) -> bytes:
    n = len(plaintext)
    padded_len = _calc_padded_len(n)
    if n < _NIP44_EXTENDED_PREFIX_THRESHOLD:
        return n.to_bytes(2, "big") + plaintext + b"\x00" * (padded_len - n)
    return b"\x00\x00" + n.to_bytes(4, "big") + plaintext + b"\x00" * (padded_len - n)


def _unpad(padded: bytes) -> bytes:
    """Mirrors the spec's unpad(): validates the declared length against the
    expected calc_padded_len() total, not just that trailing bytes are zero —
    a message truncated/extended without touching the trailing zero run would
    otherwise decrypt to a wrong-but-plausible plaintext."""
    prefix = int.from_bytes(padded[0:2], "big")
    if prefix == 0:
        if len(padded) < 6:
            raise ValueError("invalid padding")
        n = int.from_bytes(padded[2:6], "big")
        if n < _NIP44_EXTENDED_PREFIX_THRESHOLD:
            raise ValueError("invalid padding")
        prefix_len = 6
    else:
        n = prefix
        prefix_len = 2
    unpadded = padded[prefix_len:prefix_len + n]
    if n == 0 or len(unpadded) != n or len(padded) != prefix_len + _calc_padded_len(n):
        raise ValueError("invalid padding")
    return unpadded


# --- RFC 8439 ChaCha20 (12-byte nonce, 32-bit counter) in pure Python ---
_CHACHA_CONST = [0x61707865, 0x3320646E, 0x79622D32, 0x6B206574]


def _rotl32(x: int, n: int) -> int:
    return ((x << n) | (x >> (32 - n))) & 0xFFFFFFFF


def _qr(s: list, a: int, b: int, c: int, d: int) -> None:
    """ChaCha quarter round (RFC 8439 §2.1), in place on the 16-word state."""
    s[a] = (s[a] + s[b]) & 0xFFFFFFFF
    s[d] = _rotl32(s[d] ^ s[a], 16)
    s[c] = (s[c] + s[d]) & 0xFFFFFFFF
    s[b] = _rotl32(s[b] ^ s[c], 12)
    s[a] = (s[a] + s[b]) & 0xFFFFFFFF
    s[d] = _rotl32(s[d] ^ s[a], 8)
    s[c] = (s[c] + s[d]) & 0xFFFFFFFF
    s[b] = _rotl32(s[b] ^ s[c], 7)


def _chacha20_block(key: bytes, counter: int, nonce: bytes) -> bytes:
    import struct
    state = (_CHACHA_CONST
             + list(struct.unpack("<8I", key))
             + [counter & 0xFFFFFFFF]
             + list(struct.unpack("<3I", nonce)))
    work = state[:]
    for _ in range(10):  # 20 rounds = 10 double rounds
        # column rounds
        _qr(work, 0, 4, 8, 12)
        _qr(work, 1, 5, 9, 13)
        _qr(work, 2, 6, 10, 14)
        _qr(work, 3, 7, 11, 15)
        # diagonal rounds
        _qr(work, 0, 5, 10, 15)
        _qr(work, 1, 6, 11, 12)
        _qr(work, 2, 7, 8, 13)
        _qr(work, 3, 4, 9, 14)
    out = [(w + s) & 0xFFFFFFFF for w, s in zip(work, state)]
    return struct.pack("<16I", *out)


def _chacha20_encrypt(key: bytes, nonce: bytes, data: bytes) -> bytes:
    """RFC 8439: 12-byte nonce, 32-bit counter starting at 0."""
    out = b""
    for i in range(0, len(data), 64):
        block = _chacha20_block(key, i // 64, nonce)
        chunk = data[i:i + 64]
        out += bytes(a ^ b for a, b in zip(chunk, block))
    return out


def _ct_equal(a: bytes, b: bytes) -> bool:
    return hmac.compare_digest(a, b)


def nip44_encrypt_with_nonce(plaintext: str, conversation_key_: bytes, nonce: bytes) -> str:
    data = plaintext.encode("utf-8")
    if not (_NIP44_MIN_PLAINTEXT <= len(data) <= _NIP44_MAX_PLAINTEXT):
        raise ValueError("plaintext size outside NIP-44 limits")
    chacha_key, chacha_nonce, hmac_key = _message_keys(conversation_key_, nonce)
    padded = _pad(data)
    ciphertext = _chacha20_encrypt(chacha_key, chacha_nonce, padded)
    mac = _hmac_sha256(hmac_key, nonce + ciphertext)  # full 32-byte HMAC over nonce||ct
    return base64.b64encode(bytes([_NIP44_VERSION]) + nonce + ciphertext + mac).decode()


def nip44_encrypt(plaintext: str, conversation_key_: bytes) -> str:
    return nip44_encrypt_with_nonce(plaintext, conversation_key_, secrets.token_bytes(32))


def nip44_decrypt(payload: str, conversation_key_: bytes) -> str:
    if len(payload) < 132:
        raise ValueError("payload too short")
    if payload.startswith("#"):
        raise ValueError("unsupported non-base64 payload")
    raw = base64.b64decode(payload)
    if len(raw) < 99:
        raise ValueError("payload too short")
    if raw[0] != _NIP44_VERSION:
        raise ValueError("unsupported NIP-44 version")
    nonce = raw[1:33]
    ciphertext = raw[33:-32]
    mac = raw[-32:]
    chacha_key, chacha_nonce, hmac_key = _message_keys(conversation_key_, nonce)
    expect = _hmac_sha256(hmac_key, nonce + ciphertext)
    if not _ct_equal(expect, mac):
        raise ValueError("MAC mismatch")
    padded = _chacha20_encrypt(chacha_key, chacha_nonce, ciphertext)
    return _unpad(padded).decode("utf-8")


# --------------------------------------------------------------------------
# NIP-AE event construction
# --------------------------------------------------------------------------
D_TAG_DOMAIN = b"agent-memory/v1/d-tag"
KIND_AGENT_ENGRAM = 30174
CORE_SLUG = "core"
SLUG_RE_PREFIX = "mem/"


def validate_slug(slug: str) -> bool:
    if slug == CORE_SLUG:
        return True
    if len(slug.encode()) > 255:
        return False
    if not slug.startswith(SLUG_RE_PREFIX):
        return False
    rest = slug[len(SLUG_RE_PREFIX):]
    if not rest:
        return False
    for part in rest.split("/"):
        if not part or len(part) > 64:
            return False
        if not (part[0].islower() or part[0] in "0123456789_"):
            return False
        for ch in part:
            if not (ch.islower() or ch in "0123456789_-"):
                return False
    return True


def d_tag(slug: str, conversation_key_: bytes) -> str:
    return hmac.new(conversation_key_,
                    D_TAG_DOMAIN + b"\x00" + slug.encode("utf-8"),
                    hashlib.sha256).hexdigest()


# --------------------------------------------------------------------------
# adapter kit — shared helpers for the organs that write engrams
#
# Mycelium, Loom, Waggle and the other Python organs each need the same three
# things before they can put a domain object on the wire: a slug that satisfies
# validate_slug, an event of a kind this module has no dedicated builder for,
# and agreement with every other implementation about both. Those are contract
# concerns, not organ concerns, so they live here rather than being written
# once per organ -- the contract's failure mode is silent divergence, and four
# copies of this logic is four chances to diverge.
# --------------------------------------------------------------------------


def normalize_slug_segment(segment: str) -> str:
    """Fold arbitrary text into one valid slug segment.

    validate_slug accepts only [a-z0-9_-] per segment, at most 64 BYTES. Organ
    data is free text -- miner names, resource URIs, ritual names in Yoruba --
    so an unnormalised segment yields a slug this module refuses and an engram
    no client can address, failing in some other process rather than at the
    call site.

    Strips combining marks (so "Ọ̀run" folds toward "orun"), case-folds, and
    maps anything still outside the grammar to a single dash.

    Normalising is safe because a slug is HMAC'd into the d tag before it
    reaches the wire: it is an addressing key, never display text. The original
    belongs in the engram content.

    Raises ValueError when nothing survives, rather than returning an empty
    segment that would build a slug failing validate_slug later.
    """
    decomposed = unicodedata.normalize("NFD", str(segment))
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    folded = re.sub(r"[^a-z0-9_-]+", "-", stripped.casefold())
    folded = re.sub(r"-{2,}", "-", folded).strip("-")

    # Truncate on bytes: the 64 limit is bytes, and a multi-byte segment is
    # longer in bytes than in characters, so len() would let it through.
    while len(folded.encode()) > 64:
        folded = folded[:-1]
    folded = folded.strip("-")

    if not folded:
        raise ValueError(
            f"slug segment {segment!r} normalises to nothing; "
            "it cannot be used as an engram address"
        )
    return folded


def build_slug(namespace: str, *segments: str) -> str:
    """Build a validated slug under mem/<namespace>/.

    Register the namespace in NAMESPACES.md before the first write -- that file
    is the source of truth and its own rules require it.
    """
    parts = [normalize_slug_segment(namespace)]
    parts.extend(normalize_slug_segment(s) for s in segments)
    slug = "mem/" + "/".join(parts)
    if not validate_slug(slug):
        raise ValueError(f"built an invalid engram slug: {slug}")
    return slug


def sign_event(kind: int, content: str, tags: list, seckey: bytes) -> dict:
    """Assemble and sign an event of any kind.

    build_event covers kind:30174 and build_auth_event covers kind:22242, but
    an organ publishing a Crucible claim (47001) had no builder and would
    otherwise hand-roll the id-then-sign sequence. Getting that subtly wrong
    produces an event that verifies nowhere, so it belongs here once.

    The signature is over the id, and the id is over the final field set, so
    nothing may be added to the event after this returns.
    """
    pubkey = pubkey_from_secret(int.from_bytes(seckey, "big"))
    ev = {
        "kind": kind,
        "pubkey": pubkey.hex(),
        "created_at": int(time.time()),
        "tags": tags,
        "content": content,
    }
    ev["id"] = event_id(ev)
    ev["sig"] = schnorr_sign(
        bytes.fromhex(ev["id"]), int.from_bytes(seckey, "big"), secrets.token_bytes(32)
    ).hex()
    return ev


def build_event(slug: str, body: dict, seckey: bytes, owner_pubkey: bytes) -> dict:
    kc = conversation_key(seckey, owner_pubkey)
    content = nip44_encrypt(json.dumps(body, separators=(",", ":")), kc)
    pubkey = pubkey_from_secret(int.from_bytes(seckey, "big"))
    ev = {
        "kind": KIND_AGENT_ENGRAM,
        "pubkey": pubkey.hex(),
        "created_at": int(time.time()),
        "tags": [["d", d_tag(slug, kc)], ["p", owner_pubkey.hex()]],
        "content": content,
    }
    # serialize without sig, then sign
    ev["id"] = event_id(ev)
    ev["sig"] = schnorr_sign(bytes.fromhex(ev["id"]), int.from_bytes(seckey, "big"),
                             secrets.token_bytes(32)).hex()
    return ev


def event_id(ev: dict) -> str:
    # ensure_ascii=False is load-bearing, not cosmetic. NIP-01 hashes the
    # canonical serialization as raw UTF-8; Python's json.dumps defaults to
    # ensure_ascii=True and escapes non-ASCII to \uXXXX, which hashes to a
    # DIFFERENT id than every other implementation (JS's JSON.stringify and
    # Rust's serde both emit raw UTF-8). Since the signature is over the id,
    # that mismatch makes this client's events fail verification everywhere
    # else, and other clients' events fail verification here -- with no error
    # anywhere that points at serialization as the cause.
    #
    # Measured, for content "Òrìṣà Ògún":
    #   ensure_ascii=True   -> f5ceda251451b3571736436644e34ca50eca23ad68ea3e067934e5f8668c2337
    #   ensure_ascii=False  -> e24b148552d35adf425c92e2e701ee3be6b4c86dbfd5fa2cc84a4c922250ac3b
    #
    # This was latent while every field reaching the hash happened to be
    # ASCII (engram content is NIP-44 ciphertext in base64, d tags are HMAC
    # hex). It activates for any non-ASCII in a tag value or in an
    # unencrypted event such as a Crucible claim -- and this ecosystem's
    # vocabulary is Yorùbá, so ritual, vessel and Òrìṣà names all carry
    # diacritics. See tests/test_minipae.py::test_event_id_non_ascii.
    serial = json.dumps([
        0,
        ev["pubkey"],
        ev["created_at"],
        ev["kind"],
        ev["tags"],
        ev["content"],
    ], separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(serial.encode()).hexdigest()


# --------------------------------------------------------------------------
# relay client
# --------------------------------------------------------------------------
def _parse_ok_message(msg: list) -> dict:
    """Parse a NIP-01 relay OK frame: ["OK", <event_id>, <accepted:bool>, <message>].
    msg[1] is the event id (always a truthy string — never a valid stand-in
    for the accepted flag); msg[2] is the real accepted flag, msg[3] the
    human-readable message."""
    return {"ok": bool(msg[2]), "message": msg[3] if len(msg) > 3 else ""}


async def publish(relay: str, event: dict) -> dict:
    import websockets
    async with websockets.connect(relay, open_timeout=15, max_size=10 * 1024 * 1024) as ws:
        await ws.send(json.dumps(["EVENT", event]))
        while True:
            msg = json.loads(await asyncio_wait(ws))
            if msg[0] == "OK":
                return _parse_ok_message(msg)


# --------------------------------------------------------------------------
# NIP-42 relay authentication (kind:22242)
# --------------------------------------------------------------------------
KIND_AUTH = 22242


def build_auth_event(challenge: str, relay_url: str, seckey: bytes) -> dict:
    """Build+sign a NIP-42 kind:22242 AUTH response event."""
    pubkey = pubkey_from_secret(int.from_bytes(seckey, "big"))
    ev = {
        "kind": KIND_AUTH,
        "pubkey": pubkey.hex(),
        "created_at": int(time.time()),
        "tags": [["relay", relay_url], ["challenge", challenge]],
        "content": "",
    }
    ev["id"] = event_id(ev)
    ev["sig"] = schnorr_sign(bytes.fromhex(ev["id"]), int.from_bytes(seckey, "big"),
                             secrets.token_bytes(32)).hex()
    return ev


def _presocket_connect_kwargs(connect_url: str | None) -> dict:
    """Build the sock=/ssl= kwargs for websockets.connect() when routing
    around a relay's logical identity via a pre-connected socket.

    The relay URI passed to websockets.connect() still drives the Host
    header and path — that's the whole point of the presocket trick (see
    publish_authenticated's docstring). But websockets ALSO infers whether
    to negotiate TLS from that same URI's scheme, and a relay's logical
    identity is often wss:// (its real public address) even when the
    connect_url reaching it locally is a plain ws:// port (e.g. an
    internal Docker network hop with no TLS termination on that hop).
    Without this, websockets tries a TLS handshake over a plain socket and
    fails with SSLError WRONG_VERSION_NUMBER — found live testing the
    Crucible relay patch (docs/D_2_2_RELAY_KIND_COMPATIBILITY.md), not
    assumed. TLS-or-not must follow connect_url's own scheme, the thing
    actually being connected to, not relay's."""
    if not connect_url:
        return {}
    presock = _open_presocket(connect_url)
    kwargs = {"sock": presock}
    from urllib.parse import urlparse
    if urlparse(connect_url).scheme not in ("wss", "https"):
        kwargs["ssl"] = None
    return kwargs


def _open_presocket(connect_url: str):
    """Open a real, connected, non-blocking TCP socket to connect_url's
    host:port, for use as websockets.connect's `sock=` override."""
    import socket
    from urllib.parse import urlparse
    parsed = urlparse(connect_url)
    port = parsed.port or (443 if parsed.scheme in ("wss", "https") else 80)
    s = socket.create_connection((parsed.hostname, port), timeout=15)
    s.setblocking(False)
    return s


async def publish_authenticated(relay: str, event: dict, seckey: bytes,
                                connect_url: str | None = None) -> dict:
    """Publish an event, transparently handling a NIP-42 AUTH challenge —
    from either the relay (proactive AUTH on connect, observed live on
    buzz-prod-relay-1) or a rejected EVENT ("auth-required: ..."), per
    docs/D3_NIP98_ENVELOPE_DECISION.md's NIP-42-for-relay-websockets
    decision. Resends the original event once AUTH succeeds; returns that
    event's own OK result (not the AUTH event's).

    connect_url: actual address to open the TCP connection to, if different
    from `relay`'s own logical identity (e.g. reaching a relay by a Docker
    container's internal DNS name/IP while the relay only recognizes a
    specific Host header for its virtual-hosted identity — observed live
    against buzz-prod-relay-1, whose NIP-11 self-identity is
    "wss://localhost:3000" regardless of which address actually reaches
    it, and which silently overwrites any Host override passed via
    `additional_headers` since the websockets library always recomputes
    Host from the connection URI). When given, a real TCP socket is opened
    to `connect_url` first and handed to websockets.connect via `sock=`,
    so the URI (`relay`) — not the socket's real destination — determines
    the Host header and path, while the NIP-42 AUTH event's `relay` tag
    still names `relay`'s logical identity too. Both must match what the
    relay itself expects, independent of how the connection is routed.
    """
    import websockets
    connect_kwargs = _presocket_connect_kwargs(connect_url)
    async with websockets.connect(relay, open_timeout=15, max_size=10 * 1024 * 1024,
                                  **connect_kwargs) as ws:
        await ws.send(json.dumps(["EVENT", event]))
        event_resent = False
        while True:
            msg = json.loads(await asyncio_wait(ws))
            if msg[0] == "AUTH":
                auth_ev = build_auth_event(msg[1], relay, seckey)
                await ws.send(json.dumps(["AUTH", auth_ev]))
            elif msg[0] == "OK":
                ok_id, result = msg[1], _parse_ok_message(msg)
                if ok_id == event["id"]:
                    if not result["ok"] and "auth-required" in result["message"] and not event_resent:
                        # rejected pre-auth; wait for the AUTH event's own OK
                        # (handled below) before resending.
                        continue
                    return result
                # an OK for a different id — must be our AUTH event's result.
                if result["ok"] and not event_resent:
                    event_resent = True
                    await ws.send(json.dumps(["EVENT", event]))


async def query(relay: str, authors: list[str], since: int | None = None) -> list[dict]:
    import websockets
    events = []
    filt = {"kinds": [KIND_AGENT_ENGRAM], "authors": authors, "limit": 500}
    if since is not None:
        filt["since"] = since
    async with websockets.connect(relay, open_timeout=15, max_size=10 * 1024 * 1024) as ws:
        await ws.send(json.dumps(["REQ", "minipae", filt]))
        while True:
            msg = json.loads(await asyncio_wait(ws))
            if msg[0] == "EVENT":
                events.append(msg[2])
            elif msg[0] == "EOSE":
                await ws.send(json.dumps(["CLOSE", "minipae"]))
                break
    return events


async def query_authenticated(relay: str, authors: list[str], seckey: bytes,
                              kinds: list[int] | None = None, since: int | None = None,
                              connect_url: str | None = None) -> list[dict]:
    """Like query(), but handles a NIP-42 AUTH challenge first — some relays
    (buzz-prod-relay-1 observed live) close unauthenticated REQ subscriptions
    outright rather than returning empty results, so a plain query() looks
    like a connection error rather than "no events".

    connect_url: see publish_authenticated's docstring — same Host-header
    virtual-routing workaround via a pre-connected socket."""
    import asyncio
    import websockets
    events = []
    filt = {"kinds": kinds or [KIND_AGENT_ENGRAM], "authors": authors, "limit": 500}
    if since is not None:
        filt["since"] = since
    connect_kwargs = _presocket_connect_kwargs(connect_url)
    async with websockets.connect(relay, open_timeout=15, max_size=10 * 1024 * 1024,
                                  **connect_kwargs) as ws:
        req_sent = False

        async def send_req():
            await ws.send(json.dumps(["REQ", "minipae", filt]))

        # some relays challenge before any client message; give them one
        # message-turn to do so before we send REQ ourselves.
        try:
            first = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
            if first[0] == "AUTH":
                auth_ev = build_auth_event(first[1], relay, seckey)
                await ws.send(json.dumps(["AUTH", auth_ev]))
            else:
                # not an AUTH challenge — treat as a normal reply to a REQ
                # we haven't sent yet; send REQ now and requeue this frame
                await send_req()
                req_sent = True
                if first[0] == "EVENT":
                    events.append(first[2])
                elif first[0] == "EOSE":
                    await ws.send(json.dumps(["CLOSE", "minipae"]))
                    return events
        except asyncio.TimeoutError:
            pass

        if not req_sent:
            await send_req()

        while True:
            msg = json.loads(await asyncio_wait(ws))
            if msg[0] == "EVENT":
                events.append(msg[2])
            elif msg[0] == "EOSE":
                await ws.send(json.dumps(["CLOSE", "minipae"]))
                break
            elif msg[0] == "OK":
                # our AUTH event's result; on success (re)send REQ
                if _parse_ok_message(msg)["ok"]:
                    await send_req()
    return events


async def asyncio_wait(ws):
    import asyncio
    return await asyncio.wait_for(ws.recv(), timeout=30)


# --------------------------------------------------------------------------
# NIP-65 relay list (kind:10002) — "outbox model" relay discovery
# --------------------------------------------------------------------------
KIND_RELAY_LIST = 10002


def parse_relay_list(ev: dict) -> list[tuple[str, str | None]]:
    """Parse a kind:10002 event's r-tags into (url, marker) pairs.
    marker is 'read', 'write', or None (both)."""
    out = []
    for t in ev.get("tags", []):
        if len(t) >= 2 and t[0] == "r":
            marker = t[2] if len(t) >= 3 and t[2] in ("read", "write") else None
            out.append((t[1], marker))
    return out


async def fetch_relay_list(relay: str, pubkey_hex: str) -> list[tuple[str, str | None]]:
    """Fetch the newest kind:10002 event for pubkey_hex from `relay`, return
    its parsed relay list. Empty list if the author has never published one."""
    import websockets
    async with websockets.connect(relay, open_timeout=15, max_size=10 * 1024 * 1024) as ws:
        await ws.send(json.dumps(["REQ", "minipae-r", {"kinds": [KIND_RELAY_LIST],
                                                        "authors": [pubkey_hex], "limit": 5}]))
        newest = None
        while True:
            msg = json.loads(await asyncio_wait(ws))
            if msg[0] == "EVENT":
                ev = msg[2]
                if newest is None or ev["created_at"] > newest["created_at"]:
                    newest = ev
            elif msg[0] == "EOSE":
                await ws.send(json.dumps(["CLOSE", "minipae-r"]))
                break
    return parse_relay_list(newest) if newest else []


def relays_for_write(relay_list: list[tuple[str, str | None]]) -> list[str]:
    return [url for url, marker in relay_list if marker in (None, "write")]


def relays_for_read(relay_list: list[tuple[str, str | None]]) -> list[str]:
    return [url for url, marker in relay_list if marker in (None, "read")]


async def query_multi(relays: list[str], authors: list[str], since: int | None = None) -> list[dict]:
    """Query several relays in parallel, dedup by event id, return merged list.
    A single unreachable/slow relay does not fail the whole query."""
    import asyncio

    async def _one(relay: str) -> list[dict]:
        try:
            return await query(relay, authors, since=since)
        except Exception:
            return []

    results = await asyncio.gather(*[_one(r) for r in relays])
    seen: dict[str, dict] = {}
    for evs in results:
        for ev in evs:
            seen[ev["id"]] = ev
    return list(seen.values())


async def subscribe_stream(relay: str, authors: list[str], since: int | None = None):
    """Persistent subscription: yields engram events as they arrive, including
    ones published live AFTER EOSE (does not close on EOSE like query())."""
    import asyncio
    import websockets
    filt = {"kinds": [KIND_AGENT_ENGRAM], "authors": authors, "limit": 500}
    if since is not None:
        filt["since"] = since
    async with websockets.connect(relay, open_timeout=15, max_size=10 * 1024 * 1024,
                                   ping_interval=20, ping_timeout=20) as ws:
        await ws.send(json.dumps(["REQ", "minipae-watch", filt]))
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=None))
            if msg[0] == "EVENT":
                yield msg[2]
            elif msg[0] == "EOSE":
                continue  # historical backlog done; stay open for live events
            elif msg[0] == "NOTICE":
                continue


def build_relay_list_event(relays: list[tuple[str, str | None]], seckey: bytes) -> dict:
    """Build (unsigned-then-signed) an unencrypted kind:10002 relay list event."""
    pubkey = pubkey_from_secret(int.from_bytes(seckey, "big"))
    tags = [["r", url] if marker is None else ["r", url, marker] for url, marker in relays]
    ev = {
        "kind": KIND_RELAY_LIST,
        "pubkey": pubkey.hex(),
        "created_at": int(time.time()),
        "tags": tags,
        "content": "",
    }
    ev["id"] = event_id(ev)
    ev["sig"] = schnorr_sign(bytes.fromhex(ev["id"]), int.from_bytes(seckey, "big"),
                             secrets.token_bytes(32)).hex()
    return ev


# --------------------------------------------------------------------------
# local sync cache — slug/dtag -> head index, so repeat reads only fetch
# events newer than what we've already seen (via NIP-01 `since`)
# --------------------------------------------------------------------------
CACHE_DIR = os.environ.get("NIPAE_CACHE_DIR", os.path.expanduser("~/.minipae/cache"))


def _cache_path(agent_pub_hex: str, owner_pub_hex: str) -> str:
    key = hashlib.sha256(f"{agent_pub_hex}:{owner_pub_hex}".encode()).hexdigest()[:32]
    return os.path.join(CACHE_DIR, f"{key}.json")


def load_cache(agent_pub_hex: str, owner_pub_hex: str) -> dict[str, dict]:
    """Return {dtag: event} of the last known heads, or {} if no cache yet."""
    path = _cache_path(agent_pub_hex, owner_pub_hex)
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def save_cache(agent_pub_hex: str, owner_pub_hex: str, heads: dict[str, dict]) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _cache_path(agent_pub_hex, owner_pub_hex)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(heads, f)
    os.replace(tmp, path)  # atomic on POSIX — no torn/partial cache on crash


def cache_since(cache: dict[str, dict]) -> int | None:
    """Newest created_at across cached heads, used as the `since` filter for
    the next relay query — we only need events strictly newer than this."""
    if not cache:
        return None
    return max(ev["created_at"] for ev in cache.values())


def merge_heads(cached: dict[str, dict], fresh: dict[str, dict]) -> dict[str, dict]:
    """Combine cached heads with freshly queried ones, newest created_at wins
    per dtag. `fresh` is trusted as sig-verified (comes out of select_heads)."""
    merged = dict(cached)
    for dtag, ev in fresh.items():
        cur = merged.get(dtag)
        if cur is None or ev["created_at"] > cur["created_at"]:
            merged[dtag] = ev
    return merged


def synced_heads(relays: list[str], agent_pub_hex: str, owner_pub_hex: str, kc: bytes) -> dict[str, dict]:
    """Incremental read: replay only events newer than the local cache,
    merge into cached heads, persist, return the combined head set."""
    import asyncio
    cache = load_cache(agent_pub_hex, owner_pub_hex)
    since = cache_since(cache)
    # small overlap window: relay propagation delay / multi-relay skew means
    # the exact cached max isn't a safe cutoff — duplicates are harmless
    # (select_heads/merge_heads dedup by created_at), missed updates aren't.
    since_arg = max(0, since - 30) if since is not None else None
    events = asyncio.run(query_multi(relays, [agent_pub_hex], since=since_arg))
    fresh = select_heads(events, kc)
    merged = merge_heads(cache, fresh)
    save_cache(agent_pub_hex, owner_pub_hex, merged)
    return merged


# --------------------------------------------------------------------------
# head selection + decode
# --------------------------------------------------------------------------
def select_heads(events: list[dict], kc: bytes) -> dict[str, dict]:
    """Latest valid event per slug (d-tag), per NIP-AE head selection."""
    heads: dict[str, dict] = {}
    for ev in events:
        dtag = next((t[1] for t in ev.get("tags", []) if t[0] == "d"), None)
        if not dtag:
            continue
        # verify sig
        try:
            if not schnorr_verify(bytes.fromhex(ev["id"]), bytes.fromhex(ev["pubkey"]),
                                  bytes.fromhex(ev["sig"])):
                continue
        except Exception:
            continue
        cur = heads.get(dtag)
        if cur is None or ev["created_at"] > cur["created_at"]:
            heads[dtag] = ev
    return heads


def decode_body(ev: dict, kc: bytes) -> dict:
    return json.loads(nip44_decrypt(ev["content"], kc))


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def _load_keys():
    nsec = os.environ.get("NIPAE_NSEC", "").strip()
    if not nsec:
        print("NIPAE_NSEC not set (agent secret key, hex or nsec1...)", file=sys.stderr)
        sys.exit(2)
    if nsec.startswith("nsec1"):
        seckey = nsec_decode(nsec)
    else:
        seckey = bytes.fromhex(nsec)
    owner = os.environ.get("NIPAE_OWNER", "").strip()
    if not owner:
        owner = pubkey_from_secret(int.from_bytes(seckey, "big")).hex()
    elif owner.startswith("npub1"):
        owner = npub_decode(owner).hex()
    return seckey, bytes.fromhex(owner)


# --------------------------------------------------------------------------
# bech32 (BIP-173) — used by NIP-19 nsec1/npub1 encoding, checksum verified
# --------------------------------------------------------------------------
_BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_BECH32_CONST = 1  # bech32 (not bech32m) per NIP-19


def _bech32_polymod(values: list[int]) -> int:
    gen = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    chk = 1
    for v in values:
        b = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ v
        for i in range(5):
            chk ^= gen[i] if ((b >> i) & 1) else 0
    return chk


def _bech32_hrp_expand(hrp: str) -> list[int]:
    return [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]


def _bech32_create_checksum(hrp: str, data: list[int]) -> list[int]:
    values = _bech32_hrp_expand(hrp) + data
    polymod = _bech32_polymod(values + [0, 0, 0, 0, 0, 0]) ^ _BECH32_CONST
    return [(polymod >> 5 * (5 - i)) & 31 for i in range(6)]


def _convertbits(data: bytes, frombits: int, tobits: int, pad: bool = True) -> list[int]:
    acc = 0
    bits = 0
    ret = []
    maxv = (1 << tobits) - 1
    max_acc = (1 << (frombits + tobits - 1)) - 1
    for value in data:
        if value < 0 or (value >> frombits):
            raise ValueError("invalid byte for base conversion")
        acc = ((acc << frombits) | value) & max_acc
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            ret.append((acc >> bits) & maxv)
    if pad:
        if bits:
            ret.append((acc << (tobits - bits)) & maxv)
    elif bits >= frombits or ((acc << (tobits - bits)) & maxv):
        raise ValueError("invalid padding in base conversion")
    return ret


def bech32_encode(hrp: str, data: bytes) -> str:
    values = _convertbits(data, 8, 5, pad=True)
    checksum = _bech32_create_checksum(hrp, values)
    return hrp + "1" + "".join(_BECH32_CHARSET[d] for d in values + checksum)


def bech32_decode_raw(s: str) -> tuple[str, bytes]:
    """Full bech32 decode: HRP + checksum verified, returns (hrp, payload_bytes)."""
    s_orig = s
    s = s.strip()
    if any(ord(c) < 33 or ord(c) > 126 for c in s):
        raise ValueError("bech32: invalid character range")
    if s.lower() != s and s.upper() != s:
        raise ValueError("bech32: mixed case")
    s = s.lower()
    pos = s.rfind("1")
    if pos < 1 or pos + 7 > len(s):
        raise ValueError("bech32: no separator / too short")
    hrp = s[:pos]
    data_part = s[pos + 1:]
    if any(c not in _BECH32_CHARSET for c in data_part):
        raise ValueError("bech32: invalid data character")
    data = [_BECH32_CHARSET.find(c) for c in data_part]
    if _bech32_polymod(_bech32_hrp_expand(hrp) + data) != _BECH32_CONST:
        raise ValueError(f"bech32: checksum mismatch ({s_orig!r})")
    payload = _convertbits(data[:-6], 5, 8, pad=False)
    return hrp, bytes(payload)


def bech32_decode(s: str) -> str:
    """Legacy helper: decode any bech32 string (nsec1/npub1/etc.) to hex payload,
    with checksum verified — raises on tamper/typo instead of silently truncating."""
    _hrp, payload = bech32_decode_raw(s)
    return payload.hex()


def nsec_encode(seckey: bytes) -> str:
    return bech32_encode("nsec", seckey)


def nsec_decode(nsec: str) -> bytes:
    hrp, payload = bech32_decode_raw(nsec)
    if hrp != "nsec":
        raise ValueError(f"expected nsec1..., got hrp={hrp!r}")
    if len(payload) != 32:
        raise ValueError("nsec: payload must be 32 bytes")
    return payload


def npub_encode(pubkey: bytes) -> str:
    return bech32_encode("npub", pubkey)


def npub_decode(npub: str) -> bytes:
    hrp, payload = bech32_decode_raw(npub)
    if hrp != "npub":
        raise ValueError(f"expected npub1..., got hrp={hrp!r}")
    if len(payload) != 32:
        raise ValueError("npub: payload must be 32 bytes")
    return payload


def main():
    ap = argparse.ArgumentParser(prog="minipae", description="NIP-AE agent engrams")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("gen-key", help="print a fresh nsec (hex) for an agent")
    sub.add_parser("ls")
    p = sub.add_parser("get"); p.add_argument("slug")
    p = sub.add_parser("set"); p.add_argument("slug"); p.add_argument("value")
    p = sub.add_parser("rm");  p.add_argument("slug")
    p = sub.add_parser("self-owner", help="print this agent's own pubkey (owner default)")
    p = sub.add_parser("relays", help="show/publish this agent's NIP-65 relay list")
    p.add_argument("action", choices=["show", "set"], nargs="?", default="show")
    p.add_argument("urls", nargs="*", help="for 'set': relay1[:read|write] relay2 ...")
    sub.add_parser("watch", help="stream live engram updates (Ctrl+C to stop)")
    args = ap.parse_args()

    if args.cmd == "gen-key":
        sk = secrets.token_bytes(32)
        pk = pubkey_from_secret(int.from_bytes(sk, "big"))
        print(sk.hex())
        print("# nsec:", nsec_encode(sk), file=sys.stderr)
        print("# pubkey (owner-facing):", pk.hex(), file=sys.stderr)
        print("# npub:", npub_encode(pk), file=sys.stderr)
        return
    if args.cmd == "self-owner":
        sk, _ = _load_keys()
        pk = pubkey_from_secret(int.from_bytes(sk, "big"))
        print(pk.hex())
        print("# npub:", npub_encode(pk), file=sys.stderr)
        return

    import asyncio
    default_relay = os.environ.get("NIPAE_RELAY", "wss://relay.damus.io")
    sk, owner = _load_keys()
    agent_pub = pubkey_from_secret(int.from_bytes(sk, "big"))
    kc = conversation_key(sk, owner)

    def _configured_relays() -> list[str]:
        """NIPAE_RELAYS (comma-separated) wins if set; else NIP-65 discovery
        against NIPAE_RELAY; else just NIPAE_RELAY/default."""
        env_relays = os.environ.get("NIPAE_RELAYS", "").strip()
        if env_relays:
            return [r.strip() for r in env_relays.split(",") if r.strip()]
        try:
            rl = asyncio.run(fetch_relay_list(default_relay, agent_pub.hex()))
        except Exception:
            rl = []
        if rl:
            urls = relays_for_read(rl) or relays_for_write(rl)
            if urls:
                return urls
        return [default_relay]

    if args.cmd == "ls":
        relays = _configured_relays()
        heads = synced_heads(relays, agent_pub.hex(), owner.hex(), kc)
        for dtag, ev in sorted(heads.items()):
            try:
                body = decode_body(ev, kc)
                slug = body.get("slug")
                val = body.get("value")
                if val is None:
                    continue
                print(f"{slug}\t({len(str(val))} bytes)")
            except Exception:
                continue
    elif args.cmd == "get":
        if not validate_slug(args.slug):
            print(f"invalid slug: {args.slug}", file=sys.stderr); sys.exit(1)
        relays = _configured_relays()
        heads = synced_heads(relays, agent_pub.hex(), owner.hex(), kc)
        want = d_tag(args.slug, kc)
        ev = heads.get(want)
        if not ev:
            print(f"no memory at {args.slug}", file=sys.stderr); sys.exit(1)
        body = decode_body(ev, kc)
        val = body.get("value")
        if val is None:
            print(f"tombstoned: {args.slug}", file=sys.stderr); sys.exit(1)
        print(val)
    elif args.cmd == "set":
        if not validate_slug(args.slug):
            print(f"invalid slug: {args.slug}", file=sys.stderr); sys.exit(1)
        body = {"slug": args.slug, "value": args.value}
        ev = build_event(args.slug, body, sk, owner)
        res = asyncio.run(publish(default_relay, ev))
        print(f"set {args.slug}: accepted={res.get('ok')} {res.get('message','')}")
    elif args.cmd == "rm":
        if not validate_slug(args.slug):
            print(f"invalid slug: {args.slug}", file=sys.stderr); sys.exit(1)
        body = {"slug": args.slug, "value": None}
        ev = build_event(args.slug, body, sk, owner)
        res = asyncio.run(publish(default_relay, ev))
        print(f"rm {args.slug}: accepted={res.get('ok')} {res.get('message','')}")
    elif args.cmd == "relays":
        if args.action == "show":
            rl = asyncio.run(fetch_relay_list(default_relay, agent_pub.hex()))
            if not rl:
                print("no NIP-65 relay list published", file=sys.stderr)
            for url, marker in rl:
                print(f"{url}\t{marker or 'read+write'}")
        else:  # set
            parsed = []
            for u in args.urls:
                if ":" in u.split("//", 1)[-1] and u.rsplit(":", 1)[-1] in ("read", "write"):
                    url, marker = u.rsplit(":", 1)
                    parsed.append((url, marker))
                else:
                    parsed.append((u, None))
            ev = build_relay_list_event(parsed, sk)
            res = asyncio.run(publish(default_relay, ev))
            print(f"relays set: accepted={res.get('ok')} {res.get('message','')}")
    elif args.cmd == "watch":
        relays = _configured_relays()
        print(f"watching {relays} for {agent_pub.hex()} (Ctrl+C to stop)...", file=sys.stderr)

        async def _watch():
            async for ev in subscribe_stream(relays[0], [agent_pub.hex()]):
                try:
                    body = decode_body(ev, kc)
                except Exception:
                    continue
                slug = body.get("slug")
                val = body.get("value")
                if val is None:
                    print(f"[tombstone] {slug}")
                else:
                    print(f"[update]    {slug}\t({len(str(val))} bytes)")

        try:
            asyncio.run(_watch())
        except KeyboardInterrupt:
            pass
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
