"""Modèle de coûts réaliste — pur, testé. Coûts VARIABLES par coin/liquidité (IMPROVE-47) et
latence d'entrée simulée (IMPROVE-48). Remplace le forfait unique par plus de réalisme. Aucun ordre.
"""
from __future__ import annotations

DEFAULT_COST_BPS = 6.0
# coûts aller-retour approximatifs par palier de liquidité (bps) : plus liquide = moins cher
_TIER_BPS = {"major": 4.0, "mid": 8.0, "exotic": 16.0}


def cost_bps_for(coin, *, liquidity_score: float | None = None, overrides: dict | None = None) -> float:
    """Coût aller-retour (bps) pour un coin. Priorité : override explicite > palier de liquidité > défaut."""
    overrides = overrides or {}
    c = str(coin or "").upper()
    if c in overrides:
        return float(overrides[c])
    if liquidity_score is not None:
        ls = float(liquidity_score)
        if ls >= 0.85:
            return _TIER_BPS["major"]
        if ls >= 0.6:
            return _TIER_BPS["mid"]
        return _TIER_BPS["exotic"]
    return DEFAULT_COST_BPS


def apply_latency(signal_ts_ms, path, *, latency_ms: float):
    """Entrée RETARDÉE : renvoie (ts, prix) du 1er point du chemin à ts >= signal_ts + latence.
    None si aucun point après le délai (on ne fabrique pas de prix)."""
    target = float(signal_ts_ms) + float(latency_ms)
    for ts, px in path:
        if float(ts) >= target:
            return (float(ts), float(px))
    return None
