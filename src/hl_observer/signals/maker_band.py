"""V13 #161 — Maker/LP band-positioning SIM (polymarket_lp_tool) — SIMULATION uniquement.

Modélise le positionnement d'un ordre maker par rapport au mid via la demi-largeur δ :
distance_ratio = |prix - mid| / δ. Règle : [0.4,0.6] garder ; <0.4 s'éloigner ; >0.6 se
rapprocher (cible 0.5·δ). Skip si on a déjà une position (inventory-aware). Pur / 0 ordre réel.
"""

from __future__ import annotations


def band_distance_ratio(price: float, mid: float, delta: float) -> float | None:
    d = float(delta)
    if d <= 0:
        return None
    return round(abs(float(price) - float(mid)) / d, 6)


def classify_tick(tick: float) -> str:
    t = abs(float(tick))
    if t in (0.01, 1.0) or abs(t - 0.01) < 1e-9 or abs(t - 1.0) < 1e-9:
        return "coarse"
    if t in (0.001, 0.1) or abs(t - 0.001) < 1e-9 or abs(t - 0.1) < 1e-9:
        return "fine"
    return "other"


def reprice_decision(*, price: float, mid: float, delta: float, side: str = "BUY",
                     has_position: bool = False, min_replace_ratio: float = 0.05) -> dict:
    """action: skip_inventory / keep / move_in / move_out (+ prix cible 0.5·δ). SIMULATION."""
    if has_position:
        return {"action": "skip_inventory", "reason": "INVENTORY_PRESENT", "target_price": None}
    ratio = band_distance_ratio(price, mid, delta)
    if ratio is None:
        return {"action": "keep", "reason": "NO_DELTA", "target_price": None}
    sgn = 1.0 if str(side).upper() in {"SELL", "ASK", "SHORT"} else -1.0   # BUY sits below mid
    target = round(float(mid) + sgn * 0.5 * float(delta), 8)
    if 0.4 <= ratio <= 0.6:
        return {"action": "keep", "reason": "IN_BAND", "ratio": ratio, "target_price": None}
    if ratio < 0.4:
        return {"action": "move_out", "reason": "TOO_CLOSE_TO_MID", "ratio": ratio, "target_price": target}
    return {"action": "move_in", "reason": "TOO_FAR_FROM_MID", "ratio": ratio, "target_price": target}


__all__ = ["band_distance_ratio", "classify_tick", "reprice_decision"]
