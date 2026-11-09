"""P3-08: signed records verify elsewhere -- with only the pubkey + envelope,
and with an independent BIP-340 implementation (coincurve) when available."""
import copy
import hashlib
import os
import secrets
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import minipae  # noqa: E402
import signed_records as sr  # noqa: E402
from decisions import DecisionMemory, InMemoryStore  # noqa: E402

try:
    from coincurve import PrivateKey, PublicKeyXOnly
except ImportError:  # pragma: no cover
    PrivateKey = PublicKeyXOnly = None

REC = {"schema": "decision_record/1", "id": "01JTEST", "decided_at": 1762600000, "decision": "long",
       "asset": {"symbol": "BÖNK", "chain": "solana"}, "inputs": ["signal:1"]}


def _key():
    while True:
        k = secrets.token_bytes(32)
        if 0 < int.from_bytes(k, "big") < minipae.N:
            return k


class TestSignedRecords(unittest.TestCase):
    def setUp(self):
        self.sk = _key()
        self.pk = minipae.pubkey_from_secret(int.from_bytes(self.sk, "big")).hex()

    def test_off_by_default_but_verify_always_works(self):
        os.environ.pop("MINIPAE_SIGNED_RECORDS_ENABLED", None)
        with self.assertRaises(sr.SigningDisabled):
            sr.sign_record(REC, self.sk)
        env = sr.sign_record(REC, self.sk, enabled_override=True)
        self.assertTrue(sr.verify_record(env))

    def test_roundtrip_and_pubkey_pin(self):
        env = sr.sign_record(REC, self.sk, signed_at=5, enabled_override=True)
        self.assertEqual(env["pubkey"], self.pk)
        self.assertEqual(env["record_schema"], "decision_record/1")
        self.assertTrue(sr.verify_record(env, expected_pubkey=self.pk))
        self.assertFalse(sr.verify_record(env, expected_pubkey="00" * 32))

    def test_every_tamper_fails(self):
        env = sr.sign_record(REC, self.sk, signed_at=5, enabled_override=True)
        for mutate in (lambda e: e["record"].__setitem__("decision", "short"),
                       lambda e: e.__setitem__("signed_at", 6),
                       lambda e: e.__setitem__("record_schema", "x"),
                       lambda e: e.__setitem__("pubkey", minipae.pubkey_from_secret(
                           int.from_bytes(_key(), "big")).hex()),
                       lambda e: e.__setitem__("sig", "00" * 64),
                       lambda e: e.__setitem__("record_sha256", "00" * 32)):
            bad = copy.deepcopy(env)
            mutate(bad)
            self.assertFalse(sr.verify_record(bad))
        self.assertFalse(sr.verify_record({"schema": "nope"}))
        self.assertFalse(sr.verify_record(None))

    @unittest.skipIf(PublicKeyXOnly is None, "coincurve not installed")
    def test_verifies_with_an_independent_library(self):
        env = sr.sign_record(REC, self.sk, enabled_override=True)
        msg = hashlib.sha256(b"signed_record/1\n" + sr.canonical(
            {k: env[k] for k in ("schema", "record_schema", "pubkey", "signed_at", "record_sha256")})).digest()
        self.assertTrue(PublicKeyXOnly(bytes.fromhex(env["pubkey"])).verify(bytes.fromhex(env["sig"]), msg))
        # and the other way: libsecp256k1 signs, minipae verifies
        other = PrivateKey(self.sk).sign_schnorr(msg, secrets.token_bytes(32))
        self.assertTrue(sr.verify_record({**env, "sig": other.hex()}))

    def test_sign_decision_signs_only_the_immutable_part(self):
        mem = DecisionMemory(InMemoryStore(), enabled=True)
        mem.record(decision_id="d1", decided_at=1762600000, decision="long",
                   decider={"component": "jev_decide"}, asset={"symbol": "SOL", "chain": "solana"},
                   inputs=["signal:9"])
        env = sr.sign_decision(mem, "d1", self.sk, enabled_override=True)
        mem.attach_outcome("d1", "trace:abc", recorded_at=1762603600, outcome={"hit": True})
        again = sr.sign_decision(mem, "d1", self.sk, signed_at=env["signed_at"], enabled_override=True)
        self.assertEqual(env["record_sha256"], again["record_sha256"])  # outcome append doesn't change it
        self.assertNotIn("outcome_refs", env["record"])
        self.assertTrue(sr.verify_record(env))
        self.assertIsNone(sr.sign_decision(mem, "missing", self.sk, enabled_override=True))


if __name__ == "__main__":
    unittest.main()
