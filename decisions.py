"""Trading-decision memory on top of NIP-AE engrams (ticket P3-07).

A trading decision is worth remembering only together with what it was made
from and what came of it. This module stores each decision as one engram at
``mem/decision/<decision-id>`` holding a ``decision_record/1`` JSON body:

    {
      "schema":       "decision_record/1",
      "id":           "<producer id, e.g. a ULID>",
      "decided_at":   1762600000,            # unix seconds, supplied by caller
      "decision":     "long",                # long|short|hold|exit|alert|skip|...
      "asset":        {"symbol": "BONK", "chain": "solana", "address": "..."},
      "mode":         "paper",               # paper|shadow|live (optional)
      "inputs":       ["signal:01J...", "ledger:812", "pool:40211"],
      "decider":      {"component": "jev_decide", "agent_id": "...", "version": "..."},
      "rationale":    "optional short text",
      "context":      {...},                 # optional, <= 8KB JSON
      "outcome_refs": [{"ref": "trace:...", "recorded_at": 1762603600,
                        "outcome": {...}}]
    }

Inputs and outcomes are *references* (``signal:``, ``ledger:``, ``pool:``,
``trace:``, ``tx:``, ``url:`` ...), not copies: the evidence already lives in
the signal ledger / Mycelium, and an engram is the index that ties a decision
back to it.

Rules this module enforces rather than documents:

* **Flag-gated.** Nothing here runs unless ``MINIPAE_DECISIONS_ENABLED`` is
  truthy (or ``enabled=True`` is passed explicitly, e.g. by tests). Off means
  every entry point raises :class:`DecisionsDisabled` before touching a store
  or relay.
* **No invented timestamps.** ``decided_at`` / ``recorded_at`` are required;
  a decision record stamped with read time would be a confident lie about when
  the decision happened (same stance as Vantage's trace_engram).
* **Decisions are immutable.** Re-recording the same id with the same body is
  an idempotent no-op; with a different body it raises
  :class:`DecisionConflict`. The only mutation is appending outcome refs.

Storage is any object with ``set(slug, value) -> bool``, ``get(slug) -> str|None``
and ``list(prefix) -> dict[str, str]`` -- :class:`minipae.NipaeClient`
satisfies it for relay-backed storage; :class:`InMemoryStore` is provided for
offline use and tests.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Iterable, Optional, Protocol

import minipae as m

SCHEMA = "decision_record/1"
NAMESPACE = "decision"
SLUG_PREFIX = f"mem/{NAMESPACE}/"
FLAG = "MINIPAE_DECISIONS_ENABLED"

MAX_DECISION_LEN = 32
MAX_REF_LEN = 200
MAX_INPUTS = 64
MAX_OUTCOMES = 64
MAX_RATIONALE_LEN = 2000
MAX_CONTEXT_BYTES = 8 * 1024
# ids become one slug segment; the grammar folds case, so ULIDs survive intact
# (case-insensitive by construction).
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

_TRUTHY = {"1", "true", "yes", "on"}


class DecisionsDisabled(RuntimeError):
    """Raised by every entry point while MINIPAE_DECISIONS_ENABLED is off."""


class DecisionConflict(ValueError):
    """Raised when an existing decision id would be overwritten with a different body."""


class DecisionStore(Protocol):  # pragma: no cover - typing only
    def set(self, slug: str, value: str) -> bool: ...
    def get(self, slug: str) -> Optional[str]: ...
    def list(self, prefix: Optional[str] = None) -> dict: ...


def enabled() -> bool:
    return os.environ.get(FLAG, "").strip().lower() in _TRUTHY


class InMemoryStore:
    """Process-local store with NipaeClient's set/get/list surface."""

    def __init__(self) -> None:
        self._data: dict[str, Optional[str]] = {}

    def set(self, slug: str, value: Optional[str]) -> bool:
        if not m.validate_slug(slug):
            raise ValueError(f"invalid slug: {slug!r}")
        self._data[slug] = value
        return True

    def get(self, slug: str) -> Optional[str]:
        return self._data.get(slug)

    def list(self, prefix: Optional[str] = None) -> dict:
        return {k: v for k, v in self._data.items()
                if v is not None and (not prefix or k.startswith(prefix))}


# --------------------------------------------------------------------------
# record construction / validation
# --------------------------------------------------------------------------

def decision_slug(decision_id: str) -> str:
    if not isinstance(decision_id, str) or not _ID_RE.match(decision_id):
        raise ValueError(f"decision id must match {_ID_RE.pattern}: {decision_id!r}")
    return m.build_slug(NAMESPACE, decision_id)


def _unix_seconds(name: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be unix seconds (int), got {value!r}")
    if value <= 0:
        raise ValueError(f"{name} must be positive unix seconds")
    if value > 10_000_000_000:  # milliseconds passed by mistake
        raise ValueError(f"{name} looks like milliseconds, expected seconds: {value}")
    return int(value)


def _refs(name: str, values: Optional[Iterable[str]], limit: int) -> list[str]:
    out: list[str] = []
    for v in values or []:
        if not isinstance(v, str) or not v.strip():
            raise ValueError(f"{name} entries must be non-empty strings")
        if len(v) > MAX_REF_LEN:
            raise ValueError(f"{name} entry longer than {MAX_REF_LEN} chars")
        if v not in out:
            out.append(v)
    if len(out) > limit:
        raise ValueError(f"at most {limit} {name}")
    return out


def _json_size(obj: Any) -> int:
    return len(json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode())


def build_decision_record(
    *,
    decision_id: str,
    decided_at: int,
    decision: str,
    decider: dict,
    inputs: Optional[Iterable[str]] = None,
    asset: Optional[dict] = None,
    mode: Optional[str] = None,
    rationale: Optional[str] = None,
    context: Optional[dict] = None,
    outcome_refs: Optional[list] = None,
) -> dict:
    """Validate and assemble a ``decision_record/1`` dict."""
    decision_slug(decision_id)  # validates the id
    if not isinstance(decision, str) or not decision.strip() or len(decision) > MAX_DECISION_LEN:
        raise ValueError(f"decision must be a non-empty string <= {MAX_DECISION_LEN} chars")
    if not isinstance(decider, dict) or not isinstance(decider.get("component"), str) \
            or not decider["component"]:
        raise ValueError("decider must be a dict with a non-empty 'component'")
    rec: dict[str, Any] = {
        "schema": SCHEMA,
        "id": decision_id,
        "decided_at": _unix_seconds("decided_at", decided_at),
        "decision": decision.strip(),
        "decider": dict(decider),
        "inputs": _refs("inputs", inputs, MAX_INPUTS),
    }
    if asset is not None:
        if not isinstance(asset, dict) or not isinstance(asset.get("symbol"), str) \
                or not asset["symbol"] or len(asset["symbol"]) > 20:
            raise ValueError("asset must be a dict with a 'symbol' of 1..20 chars")
        rec["asset"] = {k: v for k, v in asset.items() if k in ("symbol", "chain", "address") and v}
    if mode is not None:
        if mode not in ("paper", "shadow", "live"):
            raise ValueError("mode must be paper|shadow|live")
        rec["mode"] = mode
    if rationale is not None:
        if not isinstance(rationale, str) or len(rationale) > MAX_RATIONALE_LEN:
            raise ValueError(f"rationale must be a string <= {MAX_RATIONALE_LEN} chars")
        rec["rationale"] = rationale
    if context is not None:
        if not isinstance(context, dict):
            raise ValueError("context must be an object")
        if _json_size(context) > MAX_CONTEXT_BYTES:
            raise ValueError(f"context exceeds {MAX_CONTEXT_BYTES} bytes")
        rec["context"] = context
    rec["outcome_refs"] = [_outcome_entry(o) for o in (outcome_refs or [])]
    if len(rec["outcome_refs"]) > MAX_OUTCOMES:
        raise ValueError(f"at most {MAX_OUTCOMES} outcome refs")
    return rec


def _outcome_entry(o: dict) -> dict:
    if not isinstance(o, dict):
        raise ValueError("outcome ref must be an object")
    ref = _refs("outcome ref", [o.get("ref")], 1)[0]
    entry = {"ref": ref, "recorded_at": _unix_seconds("recorded_at", o.get("recorded_at"))}
    if o.get("outcome") is not None:
        if not isinstance(o["outcome"], dict) or _json_size(o["outcome"]) > MAX_CONTEXT_BYTES:
            raise ValueError(f"outcome must be an object <= {MAX_CONTEXT_BYTES} bytes")
        entry["outcome"] = o["outcome"]
    return entry


def _immutable_view(rec: dict) -> dict:
    return {k: v for k, v in rec.items() if k != "outcome_refs"}


# --------------------------------------------------------------------------
# memory
# --------------------------------------------------------------------------

class DecisionMemory:
    """Store / retrieve decision records through an engram store."""

    def __init__(self, store: DecisionStore, *, enabled: Optional[bool] = None) -> None:
        self._store = store
        self._enabled = enabled

    # ---- gate -----------------------------------------------------------
    def _check(self) -> None:
        on = enabled() if self._enabled is None else self._enabled
        if not on:
            raise DecisionsDisabled(f"{FLAG} is off")

    # ---- codec (P3-08 hooks signing in here) ------------------------------
    def _encode(self, rec: dict) -> str:
        return json.dumps(rec, separators=(",", ":"), ensure_ascii=False, sort_keys=True)

    def _decode(self, value: Optional[str]) -> Optional[dict]:
        if value is None:
            return None
        try:
            rec = json.loads(value)
        except ValueError:
            return None
        if not isinstance(rec, dict) or rec.get("schema") != SCHEMA:
            return None
        return rec

    def _write(self, rec: dict) -> dict:
        if not self._store.set(decision_slug(rec["id"]), self._encode(rec)):
            raise IOError(f"store refused decision {rec['id']}")
        return rec

    # ---- API --------------------------------------------------------------
    def record(self, **fields: Any) -> dict:
        """Store a decision (kwargs as :func:`build_decision_record`).

        Idempotent on ``decision_id``; a different body for an existing id
        raises :class:`DecisionConflict`.
        """
        self._check()
        rec = build_decision_record(**fields)
        existing = self._decode(self._store.get(decision_slug(rec["id"])))
        if existing is not None:
            if _immutable_view(existing) != _immutable_view(rec):
                raise DecisionConflict(f"decision {rec['id']} already recorded with a different body")
            return existing
        return self._write(rec)

    def get(self, decision_id: str) -> Optional[dict]:
        self._check()
        return self._decode(self._store.get(decision_slug(decision_id)))

    def attach_outcome(self, decision_id: str, ref: str, *, recorded_at: int,
                       outcome: Optional[dict] = None) -> dict:
        """Append an outcome reference; repeating the same ref is a no-op."""
        self._check()
        rec = self.get(decision_id)
        if rec is None:
            raise KeyError(f"no decision {decision_id}")
        entry = _outcome_entry({"ref": ref, "recorded_at": recorded_at, "outcome": outcome})
        if any(o.get("ref") == entry["ref"] for o in rec.get("outcome_refs", [])):
            return rec
        if len(rec.get("outcome_refs", [])) >= MAX_OUTCOMES:
            raise ValueError(f"decision {decision_id} already has {MAX_OUTCOMES} outcome refs")
        rec = dict(rec)
        rec["outcome_refs"] = list(rec.get("outcome_refs", [])) + [entry]
        return self._write(rec)

    def list(self, *, symbol: Optional[str] = None, since: Optional[int] = None,
             until: Optional[int] = None, input_ref: Optional[str] = None) -> list[dict]:
        """All decisions, oldest first, optionally filtered."""
        self._check()
        out = []
        for value in self._store.list(SLUG_PREFIX).values():
            rec = self._decode(value)
            if rec is None:
                continue
            if symbol is not None and (rec.get("asset") or {}).get("symbol") != symbol:
                continue
            if since is not None and rec["decided_at"] < since:
                continue
            if until is not None and rec["decided_at"] > until:
                continue
            if input_ref is not None and input_ref not in rec.get("inputs", []):
                continue
            out.append(rec)
        out.sort(key=lambda r: (r["decided_at"], r["id"]))
        return out
