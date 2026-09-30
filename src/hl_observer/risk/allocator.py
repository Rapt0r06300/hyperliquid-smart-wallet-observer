"""Finite, paper-only allocation helpers."""
from __future__ import annotations

import math
from typing import Mapping


def poids_inverse_vol(vols_par_actif: Mapping[str, float]) -> dict[str, float]:
    valid: dict[str, float] = {}
    for asset, raw in (vols_par_actif or {}).items():
        try:
            value = float(raw)
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(value) and value > 0.0:
            valid[str(asset)] = value
    inverse = {asset: 1.0 / value for asset, value in valid.items()}
    total = sum(inverse.values())
    return {asset: weight / total for asset, weight in inverse.items()} if total > 0.0 else {}


def rebalancement_necessaire(
    poids_actuels: Mapping[str, float],
    poids_cibles: Mapping[str, float],
    *,
    bande: float = 0.05,
) -> bool:
    try:
        band = float(bande)
    except (TypeError, ValueError, OverflowError):
        return True
    if not math.isfinite(band) or band < 0.0:
        return True
    keys = set(poids_actuels or {}) | set(poids_cibles or {})
    for key in keys:
        try:
            current = float((poids_actuels or {}).get(key, 0.0))
            target = float((poids_cibles or {}).get(key, 0.0))
        except (TypeError, ValueError, OverflowError):
            return True
        if not math.isfinite(current) or not math.isfinite(target):
            return True
        if abs(current - target) > band:
            return True
    return False


def capacite_max_usd(
    profondeur_usd: float,
    *,
    impact_max_frac: float = 0.02,
    securite: float = 5.0,
) -> float:
    try:
        depth, impact, safety = map(float, (profondeur_usd, impact_max_frac, securite))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("capacity inputs must be numeric") from exc
    if any(not math.isfinite(value) for value in (depth, impact, safety)) or depth < 0.0 or impact < 0.0 or safety <= 0.0:
        raise ValueError("capacity inputs must be finite and non-negative")
    return depth * impact / safety


__all__ = ["poids_inverse_vol", "rebalancement_necessaire", "capacite_max_usd"]
