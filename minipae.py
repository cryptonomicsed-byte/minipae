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


def pubkey_from_secret(seckey: int) -> bytes:
    """BIP-340 x-only pubkey (32 bytes)."""
    pt = _point_mul(seckey)
    return pt[0].to_bytes(32, "big")


def _tagged_hash(tag: str, msg: bytes) -> bytes:
    th = hashlib.sha256(tag.encode()).digest()
    return hashlib.sha256(th + th + msg).digest()


def schnorr_sign(msg: bytes, seckey: int, aux: bytes) -> bytes:
    """BIP-340 Schnorr signature (64 bytes: r || s), full spec incl. even-y
    adjustments and tagged hashes — compatible with nostr/buzz."""
    d0 = seckey
    if not (1 <= d0 <= N - 1):
        raise ValueError("invalid secret key")
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
_NIP44_MAX_PLAINTEXT = 0xFFFFFFFF
_NIP44_EXTENDED_PREFIX_THRESHOLD = 65536


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
    x = _point_mul(int.from_bytes(agent_seckey, "big"),
                   _lift_x(int.from_bytes(owner_pubkey, "big")))[0]
    return _hkdf_extract(x.to_bytes(32, "big"), b"nip44-v2")


def _message_keys(conversation_key_: bytes, nonce: bytes) -> tuple:
    okm = _hkdf_expand(conversation_key_, nonce, 76)
    return okm[0:32], okm[32:44], okm[44:76]  # chacha_key, chacha_nonce, hmac_key


def _calc_padded_len(plaintext_len: int) -> int:
    if plaintext_len <= 32:
        return 32
    next_pow2 = 1 << (plaintext_len - 1).bit_length()
    chunk = max(64, next_pow2 // 2)
    return ((plaintext_len + chunk - 1) // chunk) * chunk


def _pad(plaintext: bytes) -> bytes:
    n = len(plaintext)
    padded_len = _calc_padded_len(n)
    if n < _NIP44_EXTENDED_PREFIX_THRESHOLD:
        return n.to_bytes(2, "big") + plaintext + b"\x00" * (padded_len - n)
    return b"\x00\x00" + n.to_bytes(4, "big") + plaintext + b"\x00" * (padded_len - n)


def _unpad(padded: bytes) -> bytes:
    prefix = int.from_bytes(padded[0:2], "big")
    if prefix == 0:
        n = int.from_bytes(padded[2:6], "big")
        body = padded[6:]
    else:
        n = prefix
        body = padded[2:]
    # verify the trailing padding is all zero
    if body[n:] != b"\x00" * (len(body) - n):
        raise ValueError("invalid padding")
    return body[:n]


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


def nip44_encrypt(plaintext: str, conversation_key_: bytes) -> str:
    data = plaintext.encode("utf-8")
    if not (_NIP44_MIN_PLAINTEXT <= len(data) <= _NIP44_MAX_PLAINTEXT):
        raise ValueError("plaintext size outside NIP-44 limits")
    nonce = secrets.token_bytes(32)
    chacha_key, chacha_nonce, hmac_key = _message_keys(conversation_key_, nonce)
    padded = _pad(data)
    ciphertext = _chacha20_encrypt(chacha_key, chacha_nonce, padded)
    mac = _hmac_sha256(hmac_key, nonce + ciphertext)  # full 32-byte HMAC over nonce||ct
    return base64.b64encode(bytes([_NIP44_VERSION]) + nonce + ciphertext + mac).decode()


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
        if not (part[0].isalnum() or part[0] == "_"):
            return False
        for ch in part:
            if not (ch.isalnum() or ch in "_-"):
                return False
    return True


def d_tag(slug: str, conversation_key_: bytes) -> str:
    return hmac.new(conversation_key_,
                    D_TAG_DOMAIN + b"\x00" + slug.encode("utf-8"),
                    hashlib.sha256).hexdigest()


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
    serial = json.dumps([
        0,
        ev["pubkey"],
        ev["created_at"],
        ev["kind"],
        ev["tags"],
        ev["content"],
    ], separators=(",", ":"))
    return hashlib.sha256(serial.encode()).hexdigest()


# --------------------------------------------------------------------------
# relay client
# --------------------------------------------------------------------------
async def publish(relay: str, event: dict) -> dict:
    import websockets
    async with websockets.connect(relay, open_timeout=15, max_size=10 * 1024 * 1024) as ws:
        await ws.send(json.dumps(["EVENT", event]))
        while True:
            msg = json.loads(await asyncio_wait(ws))
            if msg[0] == "OK":
                return {"ok": bool(msg[1]), "message": msg[2] if len(msg) > 2 else ""}


async def query(relay: str, authors: list[str]) -> list[dict]:
    import websockets
    events = []
    async with websockets.connect(relay, open_timeout=15, max_size=10 * 1024 * 1024) as ws:
        await ws.send(json.dumps(["REQ", "minipae", {"kinds": [KIND_AGENT_ENGRAM],
                                                     "authors": authors, "limit": 500}]))
        while True:
            msg = json.loads(await asyncio_wait(ws))
            if msg[0] == "EVENT":
                events.append(msg[2])
            elif msg[0] == "EOSE":
                await ws.send(json.dumps(["CLOSE", "minipae"]))
                break
    return events


async def asyncio_wait(ws):
    import asyncio
    return await asyncio.wait_for(ws.recv(), timeout=30)


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
        nsec = bech32_decode(nsec)
    seckey = bytes.fromhex(nsec)
    owner = os.environ.get("NIPAE_OWNER", "").strip()
    if not owner:
        owner = pubkey_from_secret(int.from_bytes(seckey, "big")).hex()
    return seckey, bytes.fromhex(owner)


def bech32_decode(s: str) -> str:
    import string
    charset = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
    data = [charset.find(c) for c in s.lower() if c in charset]
    # drop checksum (last 6 chars), convert 5-bit -> 8-bit
    data = data[:-6]
    acc = 0
    bits = 0
    out = bytearray()
    for d in data:
        acc = (acc << 5) | d
        bits += 5
        if bits >= 8:
            bits -= 8
            out.append((acc >> bits) & 0xFF)
    return out.hex()


def main():
    ap = argparse.ArgumentParser(prog="minipae", description="NIP-AE agent engrams")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("gen-key", help="print a fresh nsec (hex) for an agent")
    sub.add_parser("ls")
    p = sub.add_parser("get"); p.add_argument("slug")
    p = sub.add_parser("set"); p.add_argument("slug"); p.add_argument("value")
    p = sub.add_parser("rm");  p.add_argument("slug")
    p = sub.add_parser("self-owner", help="print this agent's own pubkey (owner default)")
    args = ap.parse_args()

    if args.cmd == "gen-key":
        sk = secrets.token_bytes(32)
        print(sk.hex())
        print("# pubkey (owner-facing):", pubkey_from_secret(int.from_bytes(sk, "big")).hex(), file=sys.stderr)
        return
    if args.cmd == "self-owner":
        sk, _ = _load_keys()
        print(pubkey_from_secret(int.from_bytes(sk, "big")).hex())
        return

    import asyncio
    relay = os.environ.get("NIPAE_RELAY", "wss://relay.damus.io")
    sk, owner = _load_keys()
    agent_pub = pubkey_from_secret(int.from_bytes(sk, "big"))
    kc = conversation_key(sk, owner)

    if args.cmd == "ls":
        events = asyncio.run(query(relay, [agent_pub.hex()]))
        heads = select_heads(events, kc)
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
        events = asyncio.run(query(relay, [agent_pub.hex()]))
        heads = select_heads(events, kc)
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
        res = asyncio.run(publish(relay, ev))
        print(f"set {args.slug}: accepted={res.get('ok')} {res.get('message','')}")
    elif args.cmd == "rm":
        if not validate_slug(args.slug):
            print(f"invalid slug: {args.slug}", file=sys.stderr); sys.exit(1)
        body = {"slug": args.slug, "value": None}
        ev = build_event(args.slug, body, sk, owner)
        res = asyncio.run(publish(relay, ev))
        print(f"rm {args.slug}: accepted={res.get('ok')} {res.get('message','')}")
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
