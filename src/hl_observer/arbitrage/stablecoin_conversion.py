"""[ARB #6] CONVERSION STABLECOIN RÉELLE : ne JAMAIS considérer USDT/USDC/USDe comme exactement 1:1 avec le
dollar. On utilise leur prix RÉELLEMENT exécutable (le carnet, pas la promesse du peg). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"
STABLES = ("USDT", "USDC", "USDE", "DAI", "TUSD", "FDUSD")


def est_stable(asset: str) -> bool:
    return str(asset).upper() in STABLES


def convertir_stable_usd(montant: Any, stable: str, *, prix_executable_usd: Any) -> Any:
    """Convertit `montant` en `stable` vers l'USD via son prix EXÉCUTABLE (jamais 1.0 supposé). Prix absent/≤0
    → UNMEASURABLE (on ne suppose pas le peg)."""
    if not isinstance(montant, (int, float)) or isinstance(montant, bool):
        return UNMEASURABLE
    if not isinstance(prix_executable_usd, (int, float)) or prix_executable_usd <= 0:
        return UNMEASURABLE
    return round(float(montant) * float(prix_executable_usd), 10)


def ecart_au_peg_bps(prix_executable_usd: Any) -> Any:
    """Écart signé du stable au dollar en bps ( >0 = au-dessus du peg, <0 = en dessous ). UNMEASURABLE si absent."""
    if not isinstance(prix_executable_usd, (int, float)) or prix_executable_usd <= 0:
        return UNMEASURABLE
    return round((float(prix_executable_usd) - 1.0) * 1e4, 4)


__all__ = ["est_stable", "convertir_stable_usd", "ecart_au_peg_bps", "STABLES", "UNMEASURABLE"]
