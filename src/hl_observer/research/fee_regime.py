"""ALPHA P34 — MATRICE de frais par régime, depuis l'UNIQUE source (config/frais_venues). Aucun frais imaginaire.

taker (source unique) / maker (défaut = taker × ratio, surchargé par env) / rebate (None sauf réellement
applicable) / adverse (add-on stressé). Un rebate n'est jamais supposé sans preuve. Pur, 0 réseau.
"""
from __future__ import annotations

import os
from typing import Any

from hl_observer.config.frais_venues import frais_taker_bps


def matrice_frais_bps(venue: object) -> dict[str, Any]:
    """Frais par régime pour une venue. maker via env `HYPERSMART_MAKER_RATIO_<V>` (défaut 0.33 du taker)."""
    taker = frais_taker_bps(venue)
    v = str(venue or "").strip().upper()
    ratio = os.environ.get(f"HYPERSMART_MAKER_RATIO_{v}")
    try:
        r = float(ratio) if ratio is not None else 0.33
    except ValueError:
        r = 0.33
    maker = round(max(0.0, taker * r), 4)
    rebate_env = os.environ.get(f"HYPERSMART_REBATE_{v}_BPS")   # None sauf preuve explicite via env
    rebate = None
    if rebate_env is not None:
        try:
            rebate = -abs(float(rebate_env))                   # un rebate est un crédit (négatif)
        except ValueError:
            rebate = None
    return {"taker_bps": taker, "maker_bps": maker, "rebate_bps": rebate,
            "adverse_add_bps": 2.0, "source": "config/frais_venues (unique)"}


__all__ = ["matrice_frais_bps"]
