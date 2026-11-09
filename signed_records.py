"""Signed records (ticket P3-08): records anyone can verify elsewhere.

Engrams are NIP-44 encrypted to the owner, so a third party can't check what
an agent remembered. A signed record is the public, checkable form: a
detached BIP-340 Schnorr signature over a canonical encoding of the record,
verifiable with nothing but the agent's x-only public key and the envelope.

    {
      "schema":        "signed_record/1",
      "record_schema": "decision_record/1",      # the record's own schema
      "pubkey":        "<x-only hex>",
      "signed_at":     1762600000,
      "record_sha256": "<hex of sha256(canonical(record))>",
      "sig":           "<128 hex>",
      "record":        { ... }
    }

    canonical(x)  = JSON, sorted keys, no whitespace, UTF-8 (ensure_ascii off)
    digest        = sha256("signed_record/1\\n" || canonical(header))
    header        = {schema, record_schema, pubkey, signed_at, record_sha256}
    sig           = BIP-340 Schnorr(digest, seckey)

Binding the header (not only the record) means the signer, the time and the
record hash can't be swapped under a valid signature. Any BIP-340
implementation verifies it: the tests check minipae's signatures with an
independent library (coincurve / libsecp256k1) when it is installed.

For decisions (P3-07) only the immutable part is signed -- outcome refs are
appended later and would otherwise break the signature.

Flag MINIPAE_SIGNED_RECORDS_ENABLED gates *signing* (default off);
verification always works -- checking a signature never needs permission.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from typing import Any, Optional

import minipae

SCHEMA = "signed_record/1"
_DOMAIN = b"signed_record/1\n"


class SigningDisabled(RuntimeError):
    pass


def enabled() -> bool:
    return os.environ.get("MINIPAE_SIGNED_RECORDS_ENABLED", "0").strip().lower() in ("1", "true", "yes", "on")


def canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _header(env: dict) -> dict:
    return {k: env[k] for k in ("schema", "record_schema", "pubkey", "signed_at", "record_sha256")}


def digest(env: dict) -> bytes:
    return hashlib.sha256(_DOMAIN + canonical(_header(env))).digest()


def sign_record(record: dict, seckey: bytes, *, signed_at: Optional[int] = None,
                enabled_override: Optional[bool] = None) -> dict:
    on = enabled() if enabled_override is None else enabled_override
    if not on:
        raise SigningDisabled("MINIPAE_SIGNED_RECORDS_ENABLED is off")
    if not isinstance(record, dict):
        raise TypeError("record must be a dict")
    sk = int.from_bytes(seckey, "big")
    env = {
        "schema": SCHEMA,
        "record_schema": str(record.get("schema") or "unknown"),
        "pubkey": minipae.pubkey_from_secret(sk).hex(),
        "signed_at": int(signed_at if signed_at is not None else time.time()),
        "record_sha256": hashlib.sha256(canonical(record)).hexdigest(),
        "record": record,
    }
    env["sig"] = minipae.schnorr_sign(digest(env), sk, secrets.token_bytes(32)).hex()
    return env


def verify_record(env: Any, *, expected_pubkey: Optional[str] = None) -> bool:
    """True only if the record, header and signature all check out."""
    try:
        if not isinstance(env, dict) or env.get("schema") != SCHEMA or not isinstance(env.get("record"), dict):
            return False
        if hashlib.sha256(canonical(env["record"])).hexdigest() != env["record_sha256"]:
            return False
        if expected_pubkey is not None and env["pubkey"].lower() != expected_pubkey.lower():
            return False
        return minipae.schnorr_verify(digest(env), bytes.fromhex(env["pubkey"]), bytes.fromhex(env["sig"]))
    except (KeyError, ValueError, TypeError, AttributeError):
        return False


def sign_decision(memory: Any, decision_id: str, seckey: bytes, **kw: Any) -> Optional[dict]:
    """Sign the immutable part of a stored decision (P3-07); None if absent."""
    from decisions import _immutable_view
    rec = memory.get(decision_id)
    return sign_record(_immutable_view(rec), seckey, **kw) if rec else None
