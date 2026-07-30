"""§11.2 — SOURCE UNIQUE des frais taker par venue. Aucun hardcode concurrent dans le cross-venue.

Les modules cross-venue portaient chacun leur propre défaut de frais (3.5, 4.5, 6.0…), qui pouvaient
diverger — donc un PnL net incohérent selon le module. Ici UNE seule autorité, surchargée par
l'environnement `HYPERSMART_FEE_<VENUE>_BPS`. Les défauts sont conservateurs et à caler sur le tier
RÉEL du compte ; l'important est qu'il n'existe qu'une source. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import os

#: Défauts taker (bps). À ajuster au tier réel via env ; NE PAS redéfinir ailleurs.
DEFAUTS_TAKER_BPS: dict[str, float] = {
    "HYPERLIQUID": 4.5,
    "BINANCE": 4.5,
}

_ALIAS = {
    "HL": "HYPERLIQUID", "HYPERLIQUID": "HYPERLIQUID", "HYPER": "HYPERLIQUID",
    "BIN": "BINANCE", "BINANCE": "BINANCE",
}


def frais_taker_bps(venue: object, *, defaut: float | None = None) -> float:
    """Frais taker (bps) de la venue, depuis l'unique source. Env `HYPERSMART_FEE_<VENUE>_BPS` prioritaire."""
    v = _ALIAS.get(str(venue or "").strip().upper())
    if v is None:
        return float(defaut) if defaut is not None else max(DEFAUTS_TAKER_BPS.values())
    env = os.environ.get(f"HYPERSMART_FEE_{v}_BPS")
    if env is not None:
        try:
            return max(0.0, float(env))
        except ValueError:
            pass
    return float(DEFAUTS_TAKER_BPS[v])


__all__ = ["DEFAUTS_TAKER_BPS", "frais_taker_bps"]
