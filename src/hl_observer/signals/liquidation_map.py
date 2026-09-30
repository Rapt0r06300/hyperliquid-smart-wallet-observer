"""P4 — Carte des clusters de liquidation (gate d'entrée + signal post-cascade).

Les cascades de liquidation se déclenchent à des prix où beaucoup de positions
levées cèdent au même instant. On estime ces zones depuis l'open interest par
bucket de prix/levier, on refuse d'ouvrir juste au-dessus d'un cluster CONTRE
nous, et on lit un signal momentum APRÈS une cascade. Pur, honnête: pas d'OI ⇒
pas de carte (aucune zone inventée).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LiquidationCluster:
    price: float
    notional_at_risk_usd: float
    side_liquidated: str   # LONG = liquidations de longs (pression baissière)


def estimate_clusters(oi_buckets: list[dict], *, min_notional_usd: float = 1_000_000.0) -> tuple[LiquidationCluster, ...]:
    """oi_buckets = [{'liq_price', 'notional_usd', 'side'}] agrégés par prix."""
    clusters = []
    for b in oi_buckets or []:
        if not isinstance(b, dict):
            continue
        price = float(b.get("liq_price") or 0.0)
        notl = float(b.get("notional_usd") or 0.0)
        side = str(b.get("side") or "").upper()
        if price > 0 and notl >= min_notional_usd and side in {"LONG", "SHORT"}:
            clusters.append(LiquidationCluster(price, notl, side))
    return tuple(sorted(clusters, key=lambda c: -c.notional_at_risk_usd))


def proximity_open_refusal(
    side: str, entry_price: float, clusters: tuple[LiquidationCluster, ...],
    *, danger_pct: float = 1.0,
) -> str:
    """Refuse d'ouvrir si une grosse cascade CONTRE nous est à < danger_pct."""
    side = str(side).upper()
    if entry_price <= 0 or side not in {"LONG", "SHORT"}:
        return "LIQ_INVALID_INPUTS"
    for c in clusters:
        dist_pct = abs(c.price - entry_price) / entry_price * 100.0
        if dist_pct > danger_pct:
            continue
        # une cascade de LONGs pousse le prix vers le BAS → dangereux si on est LONG
        if side == "LONG" and c.side_liquidated == "LONG" and c.price <= entry_price:
            return "LIQ_CASCADE_BELOW_AGAINST_LONG"
        if side == "SHORT" and c.side_liquidated == "SHORT" and c.price >= entry_price:
            return "LIQ_CASCADE_ABOVE_AGAINST_SHORT"
    return ""


def post_cascade_momentum(events: list[dict], *, min_liq_usd: float = 2_000_000.0) -> dict:
    """Après une grosse cascade, le rebond est souvent tradeable (mean-revert)."""
    big = [e for e in (events or []) if isinstance(e, dict) and float(e.get("liquidated_usd") or 0.0) >= min_liq_usd]
    if not big:
        return {"signal": False, "reason": "NO_RECENT_CASCADE"}
    last = max(big, key=lambda e: float(e.get("ts_ms") or 0))
    liquidated = str(last.get("side") or "").upper()
    # cascade de LONGs = pression baissière épuisée → biais rebond LONG (contrarian)
    bias = "LONG" if liquidated == "LONG" else "SHORT"
    return {"signal": True, "reason": "POST_CASCADE_MEAN_REVERT", "bias": bias,
            "liquidated_side": liquidated, "liquidated_usd": float(last.get("liquidated_usd") or 0.0)}


__all__ = ["LiquidationCluster", "estimate_clusters", "proximity_open_refusal", "post_cascade_momentum"]
