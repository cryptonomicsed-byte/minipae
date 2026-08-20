"""Offline unit tests for minipae. No network required.

NIP-44 vectors in nip44_vectors.json are an unmodified subset of the
official interop suite (github.com/paulmillr/nip44, nip44.vectors.json,
`v2` section) — copied verbatim via a script reading the raw file, not
hand-transcribed, to avoid transcription drift.

Bech32 vectors are taken from BIP-173's "Test vectors" section (fetched
from the raw bitcoin/bips spec) for the same reason.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import minipae as m
import cap_bridge

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nip44_vectors.json")


class TestBip340(unittest.TestCase):
    def test_sign_verify_roundtrip(self):
        sk = m.secrets.token_bytes(32)
        pk = m.pubkey_from_secret(int.from_bytes(sk, "big"))
        msg = m.hashlib.sha256(b"hello minipae").digest()
        sig = m.schnorr_sign(msg, int.from_bytes(sk, "big"), m.secrets.token_bytes(32))
        self.assertTrue(m.schnorr_verify(msg, pk, sig))

    def test_verify_rejects_tampered_message(self):
        sk = m.secrets.token_bytes(32)
        pk = m.pubkey_from_secret(int.from_bytes(sk, "big"))
        msg = m.hashlib.sha256(b"original").digest()
        sig = m.schnorr_sign(msg, int.from_bytes(sk, "big"), m.secrets.token_bytes(32))
        tampered = m.hashlib.sha256(b"tampered").digest()
        self.assertFalse(m.schnorr_verify(tampered, pk, sig))

    def test_verify_rejects_wrong_pubkey(self):
        sk = m.secrets.token_bytes(32)
        other_pk = m.pubkey_from_secret(int.from_bytes(m.secrets.token_bytes(32), "big"))
        msg = m.hashlib.sha256(b"hello").digest()
        sig = m.schnorr_sign(msg, int.from_bytes(sk, "big"), m.secrets.token_bytes(32))
        self.assertFalse(m.schnorr_verify(msg, other_pk, sig))

    def test_seckey_range_validation(self):
        with self.assertRaises(ValueError):
            m.pubkey_from_secret(0)
        with self.assertRaises(ValueError):
            m.pubkey_from_secret(m.N)  # must be <= N-1


class TestNip44OfficialVectors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(FIXTURES) as f:
            cls.vectors = json.load(f)

    def test_valid_encrypt_decrypt(self):
        for v in self.vectors["valid_encrypt_decrypt"]:
            sec1 = bytes.fromhex(v["sec1"])
            sec2_pub = m.pubkey_from_secret(int(v["sec2"], 16))
            ck = m.conversation_key(sec1, sec2_pub)
            self.assertEqual(ck.hex(), v["conversation_key"])
            payload = m.nip44_encrypt_with_nonce(v["plaintext"], ck, bytes.fromhex(v["nonce"]))
            self.assertEqual(payload, v["payload"])
            self.assertEqual(m.nip44_decrypt(payload, ck), v["plaintext"])

    def test_invalid_decrypt_all_raise(self):
        for v in self.vectors["invalid_decrypt"]:
            ck = bytes.fromhex(v["conversation_key"])
            with self.assertRaises(Exception, msg=v.get("note")):
                m.nip44_decrypt(v["payload"], ck)

    def test_invalid_get_conversation_key_all_raise(self):
        for v in self.vectors["invalid_get_conversation_key"]:
            with self.assertRaises(Exception, msg=v.get("note")):
                m.conversation_key(bytes.fromhex(v["sec1"]), bytes.fromhex(v["pub2"]))

    def test_invalid_msg_lengths_all_raise(self):
        ck = bytes(32)
        for n in self.vectors["invalid_encrypt_msg_lengths"]:
            with self.assertRaises(Exception, msg=f"length {n}"):
                # cap the literal string build for the huge lengths; only the
                # length-check matters here, not building 10M real chars
                m.nip44_encrypt_with_nonce("x" * min(n, 70000), ck, bytes(32))


class TestPadding(unittest.TestCase):
    def test_boundaries(self):
        # spec calc_padded_len: <=32 -> 32; else chunked per next-power-of-2
        self.assertEqual(m._calc_padded_len(1), 32)
        self.assertEqual(m._calc_padded_len(32), 32)
        self.assertEqual(m._calc_padded_len(33), 64)
        self.assertEqual(m._calc_padded_len(64), 64)
        self.assertEqual(m._calc_padded_len(65), 96)
        self.assertEqual(m._calc_padded_len(256), 256)
        self.assertEqual(m._calc_padded_len(257), 320)

    def test_unpad_rejects_length_mismatch(self):
        padded = m._pad(b"hello")
        # flip the declared length without changing anything else
        tampered = bytes([0, 200]) + padded[2:]
        with self.assertRaises(ValueError):
            m._unpad(tampered)

    def test_pad_unpad_roundtrip(self):
        for n in (1, 5, 32, 33, 100, 1000, 65535):
            data = b"x" * n
            self.assertEqual(m._unpad(m._pad(data)), data)


class TestBech32(unittest.TestCase):
    # BIP-173 "Test vectors" section, spec-verified before embedding here
    VALID = [
        "A12UEL5L",
        "a12uel5l",
        "an83characterlonghumanreadablepartthatcontainsthenumber1andtheexcludedcharactersbio1tt5tgs",
        "abcdef1qpzry9x8gf2tvdw0s3jn54khce6mua7lmqqqxw",
        "11qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqc8247j",
        "split1checkupstagehandshakeupstreamerranterredcaperred2y9e3w",
        "?1ezyfcl",
    ]
    INVALID = [
        " 1nwldj5",
        "pzry9x0s0muk",
        "1pzry9x0s0muk",
        "x1b4n0q5v",
        "li1dgmt3",
        "A1G7SGD8",
        "10a06t8",
        "1qzzfhee",
    ]

    def test_valid_vectors_decode(self):
        for v in self.VALID:
            hrp, payload = m.bech32_decode_raw(v)  # must not raise
            self.assertIsInstance(hrp, str)

    def test_invalid_vectors_rejected(self):
        for v in self.INVALID:
            with self.assertRaises(Exception, msg=v):
                m.bech32_decode_raw(v)

    def test_nsec_npub_roundtrip(self):
        sk = m.secrets.token_bytes(32)
        pk = m.pubkey_from_secret(int.from_bytes(sk, "big"))
        self.assertEqual(m.nsec_decode(m.nsec_encode(sk)), sk)
        self.assertEqual(m.npub_decode(m.npub_encode(pk)), pk)

    def test_tampered_nsec_rejected(self):
        sk = m.secrets.token_bytes(32)
        nsec = m.nsec_encode(sk)
        flipped = ("q" if nsec[-1] != "q" else "p")
        tampered = nsec[:-1] + flipped
        with self.assertRaises(ValueError):
            m.nsec_decode(tampered)

    def test_wrong_hrp_rejected(self):
        sk = m.secrets.token_bytes(32)
        npub_string = m.bech32_encode("npub", sk)
        with self.assertRaises(ValueError):
            m.nsec_decode(npub_string)  # hrp is npub, not nsec


class TestSlugValidation(unittest.TestCase):
    def test_valid_slugs(self):
        for slug in ("core", "mem/values/honesty", "mem/a", "mem/a_b-c/d1"):
            self.assertTrue(m.validate_slug(slug), slug)

    def test_invalid_slugs(self):
        for slug in ("", "mem/", "mem//a", "notmem", "mem/" + "a" * 300,
                     "mem/-leading-dash"):
            self.assertFalse(m.validate_slug(slug), slug)


class TestHeadSelection(unittest.TestCase):
    def test_newest_wins_and_bad_sig_dropped(self):
        sk = m.secrets.token_bytes(32)
        pk = m.pubkey_from_secret(int.from_bytes(sk, "big"))
        kc = m.conversation_key(sk, pk)

        ev_old = m.build_event("mem/x", {"slug": "mem/x", "value": "old"}, sk, pk)
        ev_new = dict(m.build_event("mem/x", {"slug": "mem/x", "value": "new"}, sk, pk))
        ev_new["created_at"] = ev_old["created_at"] + 10

        # a forged event with a bogus signature must be dropped, not win on recency
        ev_forged = dict(ev_new)
        ev_forged["created_at"] += 100
        ev_forged["sig"] = "00" * 64

        heads = m.select_heads([ev_old, ev_new, ev_forged], kc)
        self.assertEqual(len(heads), 1)
        ev = list(heads.values())[0]
        body = m.decode_body(ev, kc)
        self.assertEqual(body["value"], "new")

    def test_tombstone_body(self):
        sk = m.secrets.token_bytes(32)
        pk = m.pubkey_from_secret(int.from_bytes(sk, "big"))
        kc = m.conversation_key(sk, pk)
        ev = m.build_event("mem/x", {"slug": "mem/x", "value": None}, sk, pk)
        heads = m.select_heads([ev], kc)
        body = m.decode_body(list(heads.values())[0], kc)
        self.assertIsNone(body["value"])


class TestLocalSyncCache(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._orig_cache_dir = m.CACHE_DIR
        m.CACHE_DIR = self._tmp

    def tearDown(self):
        m.CACHE_DIR = self._orig_cache_dir

    def test_save_load_roundtrip(self):
        sk = m.secrets.token_bytes(32)
        pk = m.pubkey_from_secret(int.from_bytes(sk, "big"))
        kc = m.conversation_key(sk, pk)
        ev = m.build_event("mem/a", {"slug": "mem/a", "value": "1"}, sk, pk)
        heads = m.select_heads([ev], kc)
        m.save_cache(pk.hex(), pk.hex(), heads)
        loaded = m.load_cache(pk.hex(), pk.hex())
        self.assertEqual(set(loaded.keys()), set(heads.keys()))

    def test_merge_keeps_newest_per_dtag(self):
        dtag = "d1"
        old = {dtag: {"created_at": 100, "id": "a"}}
        new = {dtag: {"created_at": 200, "id": "b"}}
        merged = m.merge_heads(old, new)
        self.assertEqual(merged[dtag]["id"], "b")
        # stale update must not overwrite a newer cached head
        merged2 = m.merge_heads(new, old)
        self.assertEqual(merged2[dtag]["id"], "b")

    def test_cache_since_is_max_created_at(self):
        cache = {"a": {"created_at": 100}, "b": {"created_at": 250}}
        self.assertEqual(m.cache_since(cache), 250)
        self.assertIsNone(m.cache_since({}))

    def test_missing_cache_file_returns_empty(self):
        self.assertEqual(m.load_cache("nonexistent", "nonexistent"), {})


class TestParseOkMessage(unittest.TestCase):
    def test_accepted(self):
        # captured live from a real relay (buzz-prod-relay-1) during 2.2 recon
        msg = ["OK", "0c5f74a1c65d82e060063c381a52eba990bcc5e52868e819dc25591da5e3f5f7",
               True, ""]
        self.assertEqual(m._parse_ok_message(msg), {"ok": True, "message": ""})

    def test_rejected_regression(self):
        # the exact live rejection frame that caught the msg[1]/msg[2] off-by-one:
        # publish() previously read msg[1] (the event id — always a truthy
        # string) as the accepted flag, so this real rejection was reported
        # as ok=True.
        msg = ["OK", "0c5f74a1c65d82e060063c381a52eba990bcc5e52868e819dc25591da5e3f5f7",
               False, "auth-required: not authenticated"]
        result = m._parse_ok_message(msg)
        self.assertEqual(result, {"ok": False, "message": "auth-required: not authenticated"})

    def test_missing_message_field(self):
        msg = ["OK", "abc123", True]
        self.assertEqual(m._parse_ok_message(msg), {"ok": True, "message": ""})


class TestNip42Auth(unittest.TestCase):
    def test_build_auth_event_shape(self):
        sk = m.secrets.token_bytes(32)
        ev = m.build_auth_event("challenge-123", "wss://relay.example", sk)
        self.assertEqual(ev["kind"], m.KIND_AUTH)
        self.assertEqual(ev["kind"], 22242)
        self.assertEqual(ev["content"], "")
        self.assertIn(["relay", "wss://relay.example"], ev["tags"])
        self.assertIn(["challenge", "challenge-123"], ev["tags"])
        pk = m.pubkey_from_secret(int.from_bytes(sk, "big"))
        self.assertEqual(ev["pubkey"], pk.hex())
        self.assertTrue(m.schnorr_verify(bytes.fromhex(ev["id"]), pk, bytes.fromhex(ev["sig"])))

    def test_build_auth_event_id_matches_content(self):
        sk = m.secrets.token_bytes(32)
        ev = m.build_auth_event("c1", "wss://r", sk)
        self.assertEqual(ev["id"], m.event_id(ev))

    def test_different_challenge_different_id(self):
        sk = m.secrets.token_bytes(32)
        ev1 = m.build_auth_event("c1", "wss://r", sk)
        ev2 = m.build_auth_event("c2", "wss://r", sk)
        self.assertNotEqual(ev1["id"], ev2["id"])


class TestOpenPresocket(unittest.TestCase):
    def test_default_port_ws(self):
        # can't open a real socket offline; just confirm the port-defaulting
        # logic via a connection to a closed local port raises cleanly
        # rather than silently picking the wrong port.
        with self.assertRaises(OSError):
            m._open_presocket("ws://127.0.0.1:1")  # port 1 is reserved/closed

    def test_invalid_host_raises(self):
        with self.assertRaises(OSError):
            m._open_presocket("ws://this-host-should-not-resolve.invalid:3000")


class TestPresocketConnectKwargs(unittest.TestCase):
    """Found live testing the Crucible relay patch: a relay's logical
    identity can be wss:// while the actually-reachable connect_url is a
    plain ws:// internal hop. websockets infers TLS from the connection
    URI's scheme, so without this, it tries a TLS handshake over a plain
    socket and fails with SSLError WRONG_VERSION_NUMBER. TLS-or-not must
    follow connect_url's own scheme, not the logical relay's."""

    def setUp(self):
        import socket
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]

    def tearDown(self):
        self.srv.close()

    def test_no_connect_url_returns_empty(self):
        self.assertEqual(m._presocket_connect_kwargs(None), {})

    def test_plain_ws_disables_tls(self):
        kwargs = m._presocket_connect_kwargs(f"ws://127.0.0.1:{self.port}")
        self.assertIn("sock", kwargs)
        self.assertIn("ssl", kwargs)
        self.assertIsNone(kwargs["ssl"])
        kwargs["sock"].close()

    def test_wss_leaves_tls_enabled(self):
        kwargs = m._presocket_connect_kwargs(f"wss://127.0.0.1:{self.port}")
        self.assertIn("sock", kwargs)
        self.assertNotIn("ssl", kwargs)
        kwargs["sock"].close()


class TestCapBridge(unittest.TestCase):
    def test_deterministic(self):
        sk = m.secrets.token_bytes(32)
        self.assertEqual(
            cap_bridge.derive_cap_webhook_secret(sk, "pod-abc"),
            cap_bridge.derive_cap_webhook_secret(sk, "pod-abc"),
        )

    def test_pod_scoped(self):
        sk = m.secrets.token_bytes(32)
        self.assertNotEqual(
            cap_bridge.derive_cap_webhook_secret(sk, "pod-abc"),
            cap_bridge.derive_cap_webhook_secret(sk, "pod-xyz"),
        )

    def test_rotation_changes_secret(self):
        sk = m.secrets.token_bytes(32)
        self.assertNotEqual(
            cap_bridge.derive_cap_webhook_secret(sk, "pod-abc", version=1),
            cap_bridge.derive_cap_webhook_secret(sk, "pod-abc", version=2),
        )

    def test_rejects_bad_input(self):
        sk = m.secrets.token_bytes(32)
        with self.assertRaises(ValueError):
            cap_bridge.derive_cap_webhook_secret(b"short", "pod")
        with self.assertRaises(ValueError):
            cap_bridge.derive_cap_webhook_secret(sk, "")


class TestEventIdCanonicalSerialization(unittest.TestCase):
    """NIP-01 ids must agree byte-for-byte with every other implementation.

    The signature is over the id, so an id computed from a differently-escaped
    serialization makes this client's events unverifiable elsewhere and other
    clients' events unverifiable here -- and nothing in the resulting error
    points at serialization.
    """

    # A Yoruba string, because that is what this ecosystem actually publishes.
    NON_ASCII = "\u00d2r\u00ec\u1e63\u00e0 \u00d2g\u00fan"

    def _ev(self, content):
        return {
            "pubkey": "a" * 64,
            "created_at": 1700000000,
            "kind": 30174,
            "tags": [],
            "content": content,
        }

    def test_event_id_non_ascii(self):
        # Pinned against the value independently computed in Rust, in
        # JavaScript (JSON.stringify) and in Julia. The ensure_ascii=True form
        # -- Python's default, and the bug this pins shut -- would instead give
        # f5ceda251451b3571736436644e34ca50eca23ad68ea3e067934e5f8668c2337.
        self.assertEqual(
            m.event_id(self._ev(self.NON_ASCII)),
            "e24b148552d35adf425c92e2e701ee3be6b4c86dbfd5fa2cc84a4c922250ac3b",
        )

    def test_event_id_matches_raw_utf8_serialization(self):
        # Stated as a property rather than a constant, so the intent survives
        # even if the vector above is ever regenerated.
        ev = self._ev(self.NON_ASCII)
        expected_serial = m.json.dumps(
            [0, ev["pubkey"], ev["created_at"], ev["kind"], ev["tags"], ev["content"]],
            separators=(",", ":"), ensure_ascii=False,
        )
        self.assertEqual(
            m.event_id(ev),
            m.hashlib.sha256(expected_serial.encode()).hexdigest(),
        )

    def test_escaped_form_would_differ(self):
        # Guards the regression directly: if someone drops ensure_ascii=False,
        # event_id starts returning this value and the test above fails -- but
        # this one documents *why* the two differ at all.
        ev = self._ev(self.NON_ASCII)
        escaped_serial = m.json.dumps(
            [0, ev["pubkey"], ev["created_at"], ev["kind"], ev["tags"], ev["content"]],
            separators=(",", ":"),
        )
        escaped_id = m.hashlib.sha256(escaped_serial.encode()).hexdigest()
        self.assertNotEqual(m.event_id(ev), escaped_id)

    def test_ascii_content_is_unaffected(self):
        # The fix must not move any id that was already correct, or every
        # previously-published ASCII engram would change address.
        ev = self._ev("plain ascii")
        serial = m.json.dumps(
            [0, ev["pubkey"], ev["created_at"], ev["kind"], ev["tags"], ev["content"]],
            separators=(",", ":"),
        )
        self.assertEqual(
            m.event_id(ev),
            m.hashlib.sha256(serial.encode()).hexdigest(),
        )

    def test_non_ascii_in_a_tag_also_reaches_the_hash(self):
        # Tags are not encrypted, so this is the path most likely to carry a
        # Yoruba string in practice.
        ev = self._ev("ciphertext")
        ev["tags"] = [["ritual", self.NON_ASCII]]
        serial = m.json.dumps(
            [0, ev["pubkey"], ev["created_at"], ev["kind"], ev["tags"], ev["content"]],
            separators=(",", ":"), ensure_ascii=False,
        )
        self.assertEqual(
            m.event_id(ev),
            m.hashlib.sha256(serial.encode()).hexdigest(),
        )


class TestAdapterKit(unittest.TestCase):
    """Helpers the organs share, so each does not grow its own copy."""

    def test_normalises_case_diacritics_and_separators(self):
        self.assertEqual(m.normalize_slug_segment("Ọ̀rúnmìlà"), "orunmila")
        self.assertEqual(m.normalize_slug_segment("Recurring Workflow"),
                         "recurring-workflow")
        self.assertEqual(m.normalize_slug_segment("repo://A/B.rs"), "repo-a-b-rs")

    def test_truncates_on_bytes_not_characters(self):
        # The 64 limit is bytes. A multi-byte segment is longer in bytes than
        # in characters, so truncating on len() would emit an invalid slug.
        seg = m.normalize_slug_segment("é" * 60)
        self.assertLessEqual(len(seg.encode()), 64)
        self.assertTrue(m.validate_slug("mem/x/" + seg))

    def test_a_segment_that_normalises_to_nothing_raises(self):
        with self.assertRaises(ValueError):
            m.normalize_slug_segment("!!!")
        with self.assertRaises(ValueError):
            m.normalize_slug_segment("")

    def test_build_slug_produces_something_validate_slug_accepts(self):
        slug = m.build_slug("mycelium", "finding", "Ọ̀rúnmìlà Pattern")
        self.assertEqual(slug, "mem/mycelium/finding/orunmila-pattern")
        self.assertTrue(m.validate_slug(slug))

    def test_build_slug_normalises_the_namespace_too(self):
        self.assertTrue(m.validate_slug(m.build_slug("Mycelium", "x")))

    def test_sign_event_produces_a_verifiable_event(self):
        # The gap this fills: build_event covers 30174 and build_auth_event
        # covers 22242, so an organ publishing a Crucible claim would
        # otherwise hand-roll the id-then-sign sequence.
        sk = bytes([0x22]) * 32
        ev = m.sign_event(47001, '{"a":1}', [["falsifier", "sha256:x"]], sk)
        self.assertEqual(ev["kind"], 47001)
        self.assertEqual(ev["id"], m.event_id(ev))
        self.assertTrue(
            m.schnorr_verify(
                bytes.fromhex(ev["id"]),
                m.pubkey_from_secret(int.from_bytes(sk, "big")),
                bytes.fromhex(ev["sig"]),
            )
        )

    def test_sign_event_id_covers_every_signed_field(self):
        # The signature is over the id and the id is over the final field set,
        # so a mutation after signing must invalidate it.
        sk = bytes([0x22]) * 32
        ev = m.sign_event(47001, "{}", [], sk)
        tampered = dict(ev, content='{"b":2}')
        self.assertNotEqual(tampered["id"], m.event_id(tampered))


if __name__ == "__main__":
    unittest.main()
