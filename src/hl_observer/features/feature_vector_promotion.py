"""V14 #185 — Extend the model feature vector with eat_flow / basis / accumulate / sigma.

Pure merge that adds the V13 free features into the canonical feature dict consumed by the
local model. Gated by a flag at the call site so promotion is explicit; here it is a pure,
side-effect-free merge that never drops existing keys. Missing inputs default to 0.0.
"""

from __future__ import annotations

from typing import Mapping

EXTENDED_FEATURE_KEYS = ("eat_flow", "basis_bps", "accumulate", "sigma_blend")


def extended_feature_vector(
    base_feats: Mapping[str, float],
    *,
    eat_flow: float = 0.0,
    basis_bps: float = 0.0,
    accumulate: float = 0.0,
    sigma_blend: float = 0.0,
) -> dict[str, float]:
    out = {str(k): float(v) for k, v in dict(base_feats).items()}
    out["eat_flow"] = float(eat_flow)
    out["basis_bps"] = float(basis_bps)
    out["accumulate"] = float(accumulate)
    out["sigma_blend"] = float(sigma_blend)
    return out


__all__ = ["EXTENDED_FEATURE_KEYS", "extended_feature_vector"]
