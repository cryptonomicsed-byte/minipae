#!/usr/bin/env python3
"""minipae test suite — run: python3 tests/run_tests.py

Covers: BIP-340, NIP-44 v2 (official vectors), slug grammar, event build,
head selection, key derivation (BIP-32 style), namespace rules.
"""
import base64
import json
import os
import secrets
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import minipae as m
import derive as d

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL += 1
        print(f"FAIL  {name}")


# ---------------- BIP-340 ----------------
def test_bip340():
    print("BIP-340")
    for _ in range(3):
        sk = secrets.token_bytes(32)
        msg = secrets.token_bytes(32)
        sig = m.schnorr_sign(msg, int.from_bytes(sk, "big"), secrets.token_bytes(32))
        pk = m.pubkey_from_secret(int.from_bytes(sk, "big"))
        check("sign/verify roundtrip", m.schnorr_verify(msg, pk, sig))
        check("rejects wrong message", not m.schnorr_verify(b"x" * 32, pk, sig))


# ---------------- NIP-44 v2 ----------------
def test_nip44_vectors():
    print("NIP-44 v2 official vectors")
    sec1 = bytes.fromhex("00" * 31 + "01")
    sec2 = bytes.fromhex("00" * 31 + "02")
    pub2 = m.pubkey_from_secret(int.from_bytes(sec2, "big"))
    EXPECTED_K = "c41c775356fd92eadc63ff5a0dc1da211b268cbea22316767095b2871ea1412d"
    EXPECTED_PAYLOAD = ("AgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABee0G5VSK0/9YypIObAtDKfYEAjD35uVkHyB0F4DwrcNaCXlCWZKaArsGrY6M9wnuTMxWfp1RTN9Xga8no+kF5Vsb")
    kc = m.conversation_key(sec1, pub2)
    check("conversation key == vector", kc.hex() == EXPECTED_K)
    nonce = bytes.fromhex("00" * 31 + "01")
    ck, cn, hk = m._message_keys(kc, nonce)
    ct = m._chacha20_encrypt(ck, cn, m._pad(b"a"))
    mac = m._hmac_sha256(hk, nonce + ct)
    payload = base64.b64encode(bytes([2]) + nonce + ct + mac).decode()
    check("encrypt == vector", payload == EXPECTED_PAYLOAD)
    check("decrypt vector", m.nip44_decrypt(EXPECTED_PAYLOAD, kc) == "a")

    # roundtrips across padding boundaries
    for size in [1, 5, 31, 32, 33, 64, 100, 200, 1000, 5000]:
        s = "x" * size
        check(f"roundtrip size {size}", m.nip44_decrypt(m.nip44_encrypt(s, kc), kc) == s)

    # tamper + wrong key
    c2 = m.nip44_encrypt("secret", kc)
    tampered = c2[:-4] + ("AAAA" if c2[-4:] != "AAAA" else "BBBB")
    try:
        m.nip44_decrypt(tampered, kc)
        check("tamper detection", False)
    except ValueError:
        check("tamper detection", True)
    kc2 = m.conversation_key(secrets.token_bytes(32), pub2)
    try:
        m.nip44_decrypt(c2, kc2)
        check("wrong-key rejection", False)
    except ValueError:
        check("wrong-key rejection", True)

    # conversation key symmetry
    a_sk = secrets.token_bytes(32)
    o_sk = secrets.token_bytes(32)
    o_pk = m.pubkey_from_secret(int.from_bytes(o_sk, "big"))
    a_pk = m.pubkey_from_secret(int.from_bytes(a_sk, "big"))
    check("conv key symmetric",
          m.conversation_key(a_sk, o_pk) == m.conversation_key(o_sk, a_pk))


# ---------------- slug grammar + events ----------------
def test_slugs_events():
    print("slugs + events")
    for good in ["core", "mem/values/honesty", "mem/a/b/c", "mem/x_y-z"]:
        check(f"valid slug {good}", m.validate_slug(good))
    for bad in ["", "mem/", "mem/..", "mem/UPPER", "other/thing", "mem/values/"]:
        check(f"invalid slug {bad!r}", not m.validate_slug(bad))

    sk = secrets.token_bytes(32)
    owner = m.pubkey_from_secret(int.from_bytes(secrets.token_bytes(32), "big"))
    ev = m.build_event("mem/genteam/computer/test", {"slug": "mem/genteam/computer/test", "value": "v"}, sk, owner)
    check("kind 30174", ev["kind"] == 30174)
    check("sig valid", m.schnorr_verify(bytes.fromhex(ev["id"]), bytes.fromhex(ev["pubkey"]), bytes.fromhex(ev["sig"])))
    check("d-tag first", ev["tags"][0][0] == "d")
    check("owner p-tag", ev["tags"][1][0] == "p" and ev["tags"][1][1] == owner.hex())

    # head selection: newest wins
    ev2 = m.build_event("mem/genteam/computer/test", {"slug": "mem/genteam/computer/test", "value": "v2"}, sk, owner)
    kc = m.conversation_key(sk, owner)
    heads = m.select_heads([ev, ev2], kc)
    dtag = m.d_tag("mem/genteam/computer/test", kc)
    check("head = newest", heads[dtag]["created_at"] == ev2["created_at"])


# ---------------- key derivation ----------------
def test_derive():
    print("key derivation")
    master = secrets.token_bytes(32)
    k1 = d.derive_agent_key(master, agent_index=1, owner_index=0)
    k2 = d.derive_agent_key(master, agent_index=1, owner_index=0)
    k3 = d.derive_agent_key(master, agent_index=2, owner_index=0)
    k4 = d.derive_agent_key(master, agent_index=1, owner_index=1)
    check("deterministic", k1 == k2)
    check("different agent index", k1 != k3)
    check("different owner index", k1 != k4)
    check("32 bytes", len(k1) == 32)
    # path form agrees
    p = d.path_for(1, 0)
    check("path form agrees", d.derive_path(master, p) == k1)
    # derived key produces valid BIP-340 pubkey
    pk = m.pubkey_from_secret(int.from_bytes(k1, "big"))
    sig = m.schnorr_sign(b"test", int.from_bytes(k1, "big"), secrets.token_bytes(32))
    check("derived key signs/verifies", m.schnorr_verify(b"test", pk, sig))


# ---------------- namespaces ----------------
def test_namespaces():
    print("namespaces")
    for ns in ["mem/genteam/", "mem/hermes/", "mem/vantage/", "mem/buzz/"]:
        check(f"namespace {ns} valid", m.validate_slug(ns + "x"))


# ---------------- relay (live, optional) ----------------
def test_relay_live():
    print("relay live roundtrip (set/ls/get/rm)")
    import asyncio
    relay = os.environ.get("NIPAE_RELAY", "wss://relay.damus.io")
    sk = secrets.token_bytes(32)
    owner = m.pubkey_from_secret(int.from_bytes(sk, "big"))  # self-owned
    kc = m.conversation_key(sk, owner)
    slug = "mem/genteam/test-live-" + secrets.token_hex(4)

    ev = m.build_event(slug, {"slug": slug, "value": "live-test"}, sk, owner)
    res = asyncio.run(m.publish(relay, ev))
    check("publish accepted", res.get("ok") is True)
    await_delay = __import__("time").sleep(2)  # relay burst tolerance

    events = asyncio.run(m.query(relay, [owner.hex()]))
    heads = m.select_heads(events, kc)
    dtag = m.d_tag(slug, kc)
    check("query finds our engram", dtag in heads)
    if dtag in heads:
        body = m.decode_body(heads[dtag], kc)
        check("value roundtrips", body.get("value") == "live-test")
        # cleanup: tombstone
        evt = m.build_event(slug, {"slug": slug, "value": None}, sk, owner)
        res2 = asyncio.run(m.publish(relay, evt))
        check("tombstone accepted", res2.get("ok") is True)


def main():
    print("minipae test suite\n")
    test_bip340()
    test_nip44_vectors()
    test_slugs_events()
    test_derive()
    test_namespaces()
    if os.environ.get("NIPAE_LIVE") == "1":
        test_relay_live()
    else:
        print("relay live test skipped (set NIPAE_LIVE=1 to run)")
    print(f"\n{PASS} passed, {FAIL} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
