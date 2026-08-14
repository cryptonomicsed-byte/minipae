#!/usr/bin/env python3
"""cap_bridge — deterministic CAP webhookSecret derivation from a Buzz key.

Plan task 2.4. See docs/D_2_4_CAP_IDENTITY_BRIDGE.md for the full design
and what this does/doesn't achieve — short version: CAP's webhook runtime
authenticates events with a symmetric HMAC secret (`webhookSecret`), not
an asymmetric signature (confirmed against the real, live-verified 2.3
proof in commonly/webhook_agent.py). This module lets that secret be
DERIVED from a Buzz agent's own key instead of independently generated
and redistributed, so there is one seed of truth — not a cryptographic
upgrade to CAP's auth model itself.

Pure function, no network/install side effects. The actual
`POST /api/registry/install` wiring is deliberately not implemented here
pending wC's post-incident hardening pass (see docs, "Status" section).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import minipae as m


def derive_cap_webhook_secret(buzz_seckey: bytes, pod_id: str, version: int = 1) -> str:
    """Deterministic CAP webhookSecret from a Buzz agent's own key.

    Domain-separated per pod (one Buzz identity can hold distinct CAP
    installs per pod without secret reuse) and per version (rotation is
    bumping `version`, matching docs/KEY_MANAGEMENT.md's re-derivation-
    not-redistribution rotation model).
    """
    if len(buzz_seckey) != 32:
        raise ValueError("buzz_seckey must be 32 bytes")
    if not pod_id:
        raise ValueError("pod_id must be non-empty")
    info = f"cap-webhook-secret/v{version}/{pod_id}".encode("utf-8")
    prk = m._hkdf_extract(buzz_seckey, b"commonly-cap-bridge")
    return m._hkdf_expand(prk, info, 32).hex()
