"""ALPHA P34 / FIX-07 — MATRICE de frais par régime, depuis l'UNIQUE source (config/frais_venues). Aucun frais inventé.

taker = source unique. maker = **UNMEASURABLE** tant que le vrai tier n'est pas fourni (env
`HYPERSMART_MAKER_<V>_BPS`) — on n'invente PLUS de ratio (ex. 0.33·taker) comme vérité. Pour décider sans
tier connu, on fournit un **scénario conservateur** `maker_conservateur_bps = taker` (aucun rabais maker
supposé). rebate = None sauf preuve explicite (env). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import os
from typing import Any

from hl_observer.config.frais_venues import frais_taker_bps

UNMEASURABLE = "UNMEASURABLE"


def matrice_frais_bps(venue: object) -> dict[str, Any]:
    """Frais par régime. maker connu SEULEMENT via env explicite (vrai tier) ; sinon UNMEASURABLE + conservateur."""
    taker = frais_taker_bps(venue)
    v = str(venue or "").strip().upper()
    maker_env = os.environ.get(f"HYPERSMART_MAKER_{v}_BPS")
    maker: Any = UNMEASURABLE
    tier = "INCONNU"
    if maker_env is not None:
        try:
            maker = round(max(0.0, float(maker_env)), 4)
            tier = "EXPLICITE"
        except ValueError:
            maker = UNMEASURABLE
    rebate_env = os.environ.get(f"HYPERSMART_REBATE_{v}_BPS")
    rebate = None
    if rebate_env is not None:
        try:
            rebate = -abs(float(rebate_env))                 # un rebate est un crédit (négatif), preuve requise
        except ValueError:
            rebate = None
    return {"taker_bps": taker,
            "maker_bps": maker,                              # UNMEASURABLE si tier inconnu (jamais inventé)
            "maker_conservateur_bps": taker,                 # scénario SÛR : aucun rabais maker supposé
            "rebate_bps": rebate, "tier": tier,
            "adverse_add_bps": 2.0, "source": "config/frais_venues (unique)"}


def maker_utilisable_bps(venue: object) -> Any:
    """Coût maker à utiliser pour un verdict : la valeur EXPLICITE si connue, sinon le conservateur (taker)."""
    m = matrice_frais_bps(venue)
    return m["maker_bps"] if isinstance(m["maker_bps"], (int, float)) else m["maker_conservateur_bps"]


__all__ = ["matrice_frais_bps", "maker_utilisable_bps", "UNMEASURABLE"]
