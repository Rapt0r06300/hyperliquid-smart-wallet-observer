"""A3 — Détecteurs grinder: funding cross-venue, grid, microstructure, liquidations.

Compose les briques pures en un détecteur d'opportunités additionnel. Chaque source
est activable par flag; toutes produisent des CANDIDATS (jamais des ordres directs) qui
repassent par le PaperEngine canonique. Pur, testé. Câblage = importer et appeler à côté
des détecteurs existants; le microstructure/liquidation servent de CONFIRMATION/gate.
"""

from __future__ import annotations

import os

from hl_observer.arbitrage.cross_venue_funding import rank_cross_venue_edges
from hl_observer.signals.liquidation_map import estimate_clusters, proximity_open_refusal
from hl_observer.signals.microstructure import big_trade_boost, obi_confirms
from hl_observer.strategies.grid_paper import build_grid


def _on(flag: str) -> bool:
    return str(os.getenv(flag, "0")).strip().lower() in {"1", "true", "yes", "on"}


def detect_grinder_opportunities(
    *,
    funding_rates_by_coin: dict[str, dict[str, float]],
    prices: dict[str, float],
) -> dict:
    """Candidats funding cross-venue (flag HYPERSMART_DETECT_CROSS_VENUE_FUNDING)."""
    candidates = []
    if _on("HYPERSMART_DETECT_CROSS_VENUE_FUNDING"):
        for edge in rank_cross_venue_edges(funding_rates_by_coin):
            if float(prices.get(edge.coin, 0.0) or 0.0) > 0:
                candidates.append({
                    "type": "CROSS_VENUE_FUNDING", "coin": edge.coin,
                    "short_venue": edge.short_venue, "long_venue": edge.long_venue,
                    "net_edge_bps_per_hour": edge.net_edge_bps_per_hour,
                    "paper_only": True, "real_execution": False,
                })
    return {"candidates": candidates, "count": len(candidates)}


def confirm_entry(
    *, side: str, bid_depth_usdt: float, ask_depth_usdt: float,
    recent_trades: list[dict], entry_price: float,
    oi_buckets: list[dict] | None = None,
) -> dict:
    """Confirmation microstructure + gate proximité liquidation avant une entrée."""
    reasons_block = []
    boost = 1.0
    obi = {"confirmed": True, "reason": "OBI_GATE_OFF"}

    if _on("HYPERSMART_CONFIRM_MICROSTRUCTURE"):
        obi = obi_confirms(side, bid_depth_usdt, ask_depth_usdt)
        if not obi["confirmed"]:
            reasons_block.append("OBI_AGAINST")
        boost = big_trade_boost(recent_trades, side)["boost"]

    if _on("HYPERSMART_GATE_LIQUIDATION_PROXIMITY") and oi_buckets:
        clusters = estimate_clusters(oi_buckets)
        refusal = proximity_open_refusal(side, entry_price, clusters)
        if refusal:
            reasons_block.append(refusal)

    return {
        "confirmed": not reasons_block,
        "signal_boost": boost,
        "obi_reason": obi.get("reason"),
        "block_reasons": reasons_block,
    }


def build_grid_plan(*, mid_price: float, side: str = "LONG") -> dict:
    """Plan de grille cappé (flag HYPERSMART_GRID_PAPER), sinon inactif."""
    if not _on("HYPERSMART_GRID_PAPER"):
        return {"ok": False, "reason": "GRID_OFF", "levels": []}
    return build_grid(mid_price=mid_price, side=side)


__all__ = ["detect_grinder_opportunities", "confirm_entry", "build_grid_plan"]
