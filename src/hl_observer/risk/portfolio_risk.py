"""H1/H4/H5/H6 — Risque portefeuille : exposition brute/nette, volatility targeting,
risque par trade, circuit breaker sur anomalie de données. Pur.
"""

from __future__ import annotations


def gross_net_exposure(positions) -> dict:
    """positions: [(notional, side)] avec side 'long'/'short'. Notionnels >= 0."""
    gross = sum(abs(float(n)) for n, _ in positions)
    net = sum((float(n) if str(s).lower() == "long" else -float(n)) for n, s in positions)
    return {"gross": round(gross, 6), "net": round(net, 6)}


def exposure_within_caps(gross: float, net: float, *, max_gross: float, max_net_abs: float) -> bool:
    return gross <= float(max_gross) and abs(net) <= float(max_net_abs)


def vol_target_size_pct(target_vol_bps: float, asset_vol_bps: float, *, base_pct: float = 0.05, cap: float = 0.15) -> float:
    """Taille ∝ vol cible / vol de l'actif (moins de taille si l'actif est volatil)."""
    if asset_vol_bps <= 0:
        return 0.0
    return round(min(float(cap), float(base_pct) * (float(target_vol_bps) / float(asset_vol_bps))), 6)


def risk_per_trade_notional(equity_usdc: float, risk_pct: float, stop_distance_bps: float) -> float:
    """Notionnel tel qu'un stop à stop_distance_bps = risk_pct% de l'equity."""
    if stop_distance_bps <= 0 or equity_usdc <= 0:
        return 0.0
    risk_usd = float(equity_usdc) * float(risk_pct) / 100.0
    return round(risk_usd / (float(stop_distance_bps) / 10000.0), 6)


def data_anomaly(prev_price: float, new_price: float, *, max_jump_pct: float = 20.0) -> bool:
    """Vrai si le prix saute de plus de max_jump_pct (feed corrompu -> pause)."""
    if prev_price <= 0:
        return False
    jump_pct = abs(float(new_price) - float(prev_price)) / float(prev_price) * 100.0
    return jump_pct > float(max_jump_pct)


__all__ = ["gross_net_exposure", "exposure_within_caps", "vol_target_size_pct",
           "risk_per_trade_notional", "data_anomaly"]
