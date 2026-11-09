"""P3-07: trading-decision memory. Offline; no relay needed.

The engram-backed store below goes through the real wire path (build_event ->
NIP-44 ciphertext -> signature-checked head selection -> decrypt), so
"retrievable later" is exercised on actual kind:30174 events, not a dict.
"""
from __future__ import annotations

import json
import os
import secrets
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import minipae as m
import decisions as d


class EngramEventStore:
    """NipaeClient-shaped store that keeps the signed events a relay would hold."""

    def __init__(self):
        self.sk = secrets.token_bytes(32)  # throwaway test key
        self.pub = m.pubkey_from_secret(int.from_bytes(self.sk, "big"))
        self.kc = m.conversation_key(self.sk, self.pub)
        self.events: list[dict] = []
        self._tick = 1_762_600_000

    def set(self, slug, value):
        ev = m.build_event(slug, {"slug": slug, "value": value}, self.sk, self.pub)
        # deterministic, strictly increasing created_at so head selection is exact
        self._tick += 1
        ev["created_at"] = self._tick
        ev["id"] = m.event_id(ev)
        ev["sig"] = m.schnorr_sign(bytes.fromhex(ev["id"]), int.from_bytes(self.sk, "big"),
                                   secrets.token_bytes(32)).hex()
        self.events.append(ev)
        return True

    def _heads(self):
        out = {}
        for ev in m.select_heads(self.events, self.kc).values():
            body = m.decode_body(ev, self.kc)
            out[body["slug"]] = body.get("value")
        return out

    def get(self, slug):
        return self._heads().get(slug)

    def list(self, prefix=None):
        return {k: v for k, v in self._heads().items()
                if v is not None and (not prefix or k.startswith(prefix))}


def _fields(**over):
    base = dict(
        decision_id="01JC0DEC1S10N0000000000001",
        decided_at=1_762_600_000,
        decision="long",
        decider={"component": "jev_decide", "version": "test"},
        inputs=["signal:01JSIG0000000000000000001", "ledger:812", "pool:40211"],
        asset={"symbol": "BONK", "chain": "solana", "address": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"},
        mode="paper",
    )
    base.update(over)
    return base


class TestFlag(unittest.TestCase):
    def test_off_by_default_and_never_touches_store(self):
        store = mock.MagicMock()
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(d.FLAG, None)
            self.assertFalse(d.enabled())
            mem = d.DecisionMemory(store)
            for call in (lambda: mem.record(**_fields()), lambda: mem.get("x"),
                         lambda: mem.list(), lambda: mem.attach_outcome("x", "trace:1", recorded_at=1)):
                with self.assertRaises(d.DecisionsDisabled):
                    call()
        store.set.assert_not_called()
        store.get.assert_not_called()
        store.list.assert_not_called()

    def test_env_flag_turns_it_on(self):
        with mock.patch.dict(os.environ, {d.FLAG: "1"}):
            self.assertTrue(d.enabled())
            mem = d.DecisionMemory(d.InMemoryStore())
            self.assertEqual(mem.record(**_fields())["decision"], "long")
        with mock.patch.dict(os.environ, {d.FLAG: "0"}):
            self.assertFalse(d.enabled())


class TestRecordValidation(unittest.TestCase):
    def test_slug_is_valid_and_namespaced(self):
        slug = d.decision_slug("01JC0DEC1S10N0000000000001")
        self.assertTrue(m.validate_slug(slug))
        self.assertTrue(slug.startswith("mem/decision/"))

    def test_bad_ids_rejected(self):
        for bad in ("", "a/b", "x" * 65, "sp ace", None):
            with self.assertRaises(ValueError):
                d.decision_slug(bad)

    def test_timestamp_required_never_invented(self):
        f = _fields()
        f.pop("decided_at")
        with self.assertRaises(TypeError):
            d.build_decision_record(**f)
        for bad in (None, "now", 0, -5, True, 1_762_600_000_000):
            with self.assertRaises(ValueError):
                d.build_decision_record(**_fields(decided_at=bad))

    def test_decider_and_decision_required(self):
        with self.assertRaises(ValueError):
            d.build_decision_record(**_fields(decider={}))
        with self.assertRaises(ValueError):
            d.build_decision_record(**_fields(decision=""))
        with self.assertRaises(ValueError):
            d.build_decision_record(**_fields(decision="x" * 40))

    def test_inputs_deduped_and_bounded(self):
        rec = d.build_decision_record(**_fields(inputs=["a:1", "a:1", "b:2"]))
        self.assertEqual(rec["inputs"], ["a:1", "b:2"])
        with self.assertRaises(ValueError):
            d.build_decision_record(**_fields(inputs=[f"s:{i}" for i in range(d.MAX_INPUTS + 1)]))
        with self.assertRaises(ValueError):
            d.build_decision_record(**_fields(inputs=[""]))

    def test_context_size_capped(self):
        with self.assertRaises(ValueError):
            d.build_decision_record(**_fields(context={"x": "y" * (d.MAX_CONTEXT_BYTES + 1)}))

    def test_mode_validated(self):
        with self.assertRaises(ValueError):
            d.build_decision_record(**_fields(mode="yolo"))


class TestMemoryOverEngrams(unittest.TestCase):
    def setUp(self):
        self.store = EngramEventStore()
        self.mem = d.DecisionMemory(self.store, enabled=True)

    def test_record_then_retrieve_later_from_events(self):
        rec = self.mem.record(**_fields(context={"aggregate_score": 0.81}))
        self.assertEqual(len(self.store.events), 1)
        # a fresh DecisionMemory over the same events = "later, elsewhere"
        later = d.DecisionMemory(self.store, enabled=True)
        got = later.get(rec["id"])
        self.assertEqual(got, rec)
        self.assertEqual(got["schema"], d.SCHEMA)
        self.assertEqual(got["inputs"][0], "signal:01JSIG0000000000000000001")
        # ciphertext on the wire, not the record
        self.assertNotIn("BONK", self.store.events[0]["content"])

    def test_idempotent_rerecord(self):
        self.mem.record(**_fields())
        self.mem.record(**_fields())
        self.assertEqual(len(self.store.events), 1)

    def test_conflicting_rerecord_raises(self):
        self.mem.record(**_fields())
        with self.assertRaises(d.DecisionConflict):
            self.mem.record(**_fields(decision="short"))

    def test_attach_outcome_appends_and_dedupes(self):
        self.mem.record(**_fields())
        did = "01JC0DEC1S10N0000000000001"
        r1 = self.mem.attach_outcome(did, "trace:signal_outcome/abc", recorded_at=1_762_603_600,
                                     outcome={"window": "1h", "signed_ret_pct": 2.4, "hit": True})
        self.assertEqual(len(r1["outcome_refs"]), 1)
        r2 = self.mem.attach_outcome(did, "trace:signal_outcome/abc", recorded_at=1_762_603_601)
        self.assertEqual(r2["outcome_refs"], r1["outcome_refs"])
        self.mem.attach_outcome(did, "trace:signal_outcome/def", recorded_at=1_762_621_600)
        got = self.mem.get(did)
        self.assertEqual([o["ref"] for o in got["outcome_refs"]],
                         ["trace:signal_outcome/abc", "trace:signal_outcome/def"])
        # immutable part unchanged after outcomes are attached
        self.assertEqual(got["decision"], "long")
        # a rerecord after outcomes is still idempotent, not a conflict
        self.assertEqual(self.mem.record(**_fields())["outcome_refs"], got["outcome_refs"])

    def test_attach_outcome_unknown_decision(self):
        with self.assertRaises(KeyError):
            self.mem.attach_outcome("nope", "trace:x", recorded_at=1_762_600_000)

    def test_list_filters_and_orders(self):
        self.mem.record(**_fields(decision_id="d2", decided_at=1_762_600_200))
        self.mem.record(**_fields(decision_id="d1", decided_at=1_762_600_100,
                                  asset={"symbol": "WIF", "chain": "solana"}, inputs=["ledger:1"]))
        self.mem.record(**_fields(decision_id="d3", decided_at=1_762_600_300, decision="skip"))
        self.assertEqual([r["id"] for r in self.mem.list()], ["d1", "d2", "d3"])
        self.assertEqual([r["id"] for r in self.mem.list(symbol="BONK")], ["d2", "d3"])
        self.assertEqual([r["id"] for r in self.mem.list(since=1_762_600_150, until=1_762_600_250)], ["d2"])
        self.assertEqual([r["id"] for r in self.mem.list(input_ref="ledger:1")], ["d1"])

    def test_foreign_values_under_namespace_ignored(self):
        self.store.set("mem/decision/garbage", "not json")
        self.store.set("mem/decision/other", json.dumps({"schema": "something_else/1"}))
        self.mem.record(**_fields())
        self.assertEqual(len(self.mem.list()), 1)
        self.assertIsNone(self.mem.get("garbage"))


class TestNamespaceRegistered(unittest.TestCase):
    def test_namespaces_md_lists_decision(self):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "NAMESPACES.md")
        with open(path, encoding="utf-8") as f:
            self.assertIn("`mem/decision/*`", f.read())


if __name__ == "__main__":
    unittest.main()
