"""P2 — Multiplicateur d'edge par régime de marché + volume (CODEX_GOAL 2-3).

Un edge brut n'a pas la même valeur selon le contexte: en RANGING les faux signaux
dominent (×0 = ne pas prendre), en TRENDING on presse l'avantage (×1.2). Un volume
anormalement haut confirme (×1.2), anormalement bas doit inquiéter (×0.5). Pur.
Le multiplicateur est borné et sépare RÉGIME × VOLUME (deux effets distincts).
"""

from __future__ import annotations

RANGING, TRENDING, NEUTRAL = "RANGING", "TRENDING", "NEUTRAL"


def regime_multiplier(regime: str) -> float:
    r = str(regime or "").upper()
    if r == RANGING:
        return 0.0     # ne pas prendre: les faux breakouts dominent
    if r == TRENDING:
        return 1.2
    return 1.0


def volume_multiplier(volume_zscore: float, *, high: float = 1.0, low: float = -1.0) -> float:
    try:
        z = float(volume_zscore)
    except (TypeError, ValueError):
        return 1.0
    if z >= high:
        return 1.2     # volume anormalement haut = confirmation
    if z <= low:
        return 0.5     # volume anormalement bas = signal fragile
    return 1.0


def adjusted_edge_bps(raw_edge_bps: float, *, regime: str, volume_zscore: float) -> dict:
    """Edge net ajusté = brut × régime × volume, avec la trace des facteurs."""
    rm = regime_multiplier(regime)
    vm = volume_multiplier(volume_zscore)
    adj = float(raw_edge_bps) * rm * vm
    return {
        "raw_edge_bps": float(raw_edge_bps),
        "regime": str(regime or "").upper() or NEUTRAL,
        "regime_mult": rm,
        "volume_mult": vm,
        "adjusted_edge_bps": round(adj, 4),
        "suppressed": rm == 0.0,   # RANGING annule l'entrée
    }


__all__ = ["RANGING", "TRENDING", "NEUTRAL", "regime_multiplier", "volume_multiplier", "adjusted_edge_bps"]
