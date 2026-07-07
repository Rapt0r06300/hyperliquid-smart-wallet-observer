"""V13 — Model inference (pure-python, no numpy) + shadow→authoritative gate.

Lazily loads the persisted model (JSON) and scores decision-time features. Default
behaviour is SHADOW: P(profit) is exposed for context, the decision is unchanged.
Authoritative promotion is opt-in and can only TIGHTEN (turn an accept into a reject),
never create a trade — same discipline as the V12 gate. Read-only / paper-only.
"""

from __future__ import annotations

import os
from pathlib import Path

from hl_observer.ml.model import LogisticModel

DEFAULT_MODEL_PATH = "runtime/models/trade_model_v13.json"
ACCEPT_MARKER = "EDGE_OK_FOR_LOCAL_SIMULATION"

_CACHE: dict = {"path": None, "mtime": None, "model": None}


def get_model(path: str | None = None) -> LogisticModel | None:
    """Load + cache the trained model by mtime. Returns None if absent/untrained."""
    p = str(path or os.environ.get("HYPERSMART_V13_MODEL_PATH") or DEFAULT_MODEL_PATH)
    try:
        fp = Path(p)
        if not fp.exists():
            return None
        mtime = fp.stat().st_mtime
        if _CACHE["path"] == p and _CACHE["mtime"] == mtime:
            return _CACHE["model"]
        m = LogisticModel.load(p)
        if m is not None and not m.trained:
            m = None                       # an untrained refusal model never scores live
        _CACHE.update({"path": p, "mtime": mtime, "model": m})
        return m
    except Exception:
        return None


def predict_p_profit(features: dict, *, path: str | None = None) -> float | None:
    """Calibrated P(profit) for these features, or None when no trained model exists."""
    m = get_model(path)
    if m is None:
        return None
    try:
        return float(m.predict_proba_one(features))
    except Exception:
        return None


def model_min_p() -> float:
    try:
        return float(os.environ.get("HYPERSMART_V13_MODEL_MIN_P", "0.5") or 0.5)
    except (TypeError, ValueError):
        return 0.5


def model_accepts(p_profit: float | None, *, min_p: float | None = None) -> bool | None:
    """True/False once a model exists; None (= no opinion, don't block) when no model."""
    if p_profit is None:
        return None
    thr = model_min_p() if min_p is None else float(min_p)
    return bool(p_profit >= thr)


def apply_model_promotion(
    *, score_reason: str, model_accept: bool | None, authoritative: bool,
    accept_marker: str = ACCEPT_MARKER,
) -> str:
    """Authoritative = stricter intersection: only turns an ACCEPT into a reject when the
    model says no. Never turns a reject into an accept. Shadow (authoritative=False) is a no-op.
    """
    if authoritative and score_reason == accept_marker and model_accept is False:
        return "REJECT_MODEL_LOW_P"
    return score_reason


__all__ = [
    "DEFAULT_MODEL_PATH", "get_model", "predict_p_profit", "model_min_p",
    "model_accepts", "apply_model_promotion",
]
