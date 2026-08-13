#!/usr/bin/env python3
"""minipae.derive — BIP-32-style hardened key derivation for NIP-AE agent keys.

Derives per-(agent, owner) nsec keys from a master secret without adding a
dependency (pure Python, reuses minipae's secp256k1 point arithmetic).

Path (locked plan, docs/KEY_MANAGEMENT.md):
    m / 44' / 30174' / <agent_index>' / <owner_index>'
Hardened children only: a compromised leaf does not reveal siblings/master.

NOTE: this is BIP-32 *style* derivation on secp256k1 with a custom purpose
constant (30174' = NIP-AE). It is not intended to interoperate with wallet
software; it is a key-organization scheme for the agent bus.
"""

from __future__ import annotations

import hashlib
import hmac

from minipae import _point_mul, N

BIP32_HARDENED = 0x80000000
PURPOSE = 30174  # NIP-AE kind as application constant


def _ckd_priv(privkey: int, chain_code: bytes, index: int) -> tuple[int, bytes]:
    """One BIP-32 private child derivation step (hardened or normal)."""
    data = (b"\x00" + privkey.to_bytes(32, "big")
            + index.to_bytes(4, "big"))
    I = hmac.new(chain_code, data, hashlib.sha512).digest()
    IL, IR = I[:32], I[32:]
    child = (int.from_bytes(IL, "big") + privkey) % N
    if child == 0:
        raise ValueError("invalid child key (IL+par == 0 mod n)")
    return child, IR


def derive_agent_key(master_secret: bytes, agent_index: int,
                     owner_index: int = 0) -> bytes:
    """Derive a per-(agent, owner) nsec from the master secret.

    master_secret: 32 bytes (or the raw BIP39 seed — first 32 bytes used).
    Returns 32-byte secret key.
    """
    if len(master_secret) < 32:
        raise ValueError("master_secret must be >= 32 bytes")
    master = master_secret[:32]

    # m / 44' — purpose (BIP-44 style)
    k, cc = _ckd_priv(int.from_bytes(master, "big"),
                      b"Bitcoin seed", 44 | BIP32_HARDENED)
    # / 30174' — NIP-AE application
    k, cc = _ckd_priv(k, cc, PURPOSE | BIP32_HARDENED)
    # / <agent_index>' — agent
    if not (0 <= agent_index < BIP32_HARDENED):
        raise ValueError("agent_index out of range")
    k, cc = _ckd_priv(k, cc, agent_index | BIP32_HARDENED)
    # / <owner_index>' — owner (0 = self-owned)
    if not (0 <= owner_index < BIP32_HARDENED):
        raise ValueError("owner_index out of range")
    k, cc = _ckd_priv(k, cc, owner_index | BIP32_HARDENED)

    return k.to_bytes(32, "big")


def derive_path(master_secret: bytes, path: str) -> bytes:
    """Derive along a full textual path like m/44'/30174'/0'/1'."""
    parts = path.strip().split("/")
    if parts[0] != "m":
        raise ValueError("path must start with m/")
    k = int.from_bytes(master_secret[:32], "big")
    cc = b"Bitcoin seed"
    for part in parts[1:]:
        hardened = part.endswith("'")
        idx = int(part.rstrip("'"))
        if hardened:
            idx |= BIP32_HARDENED
        k, cc = _ckd_priv(k, cc, idx)
    return k.to_bytes(32, "big")


def path_for(agent_index: int, owner_index: int = 0) -> str:
    return f"m/44'/{PURPOSE}'/{agent_index}'/{owner_index}'"
