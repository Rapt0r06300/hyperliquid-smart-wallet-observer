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


# --- Anti adverse-selection (microprice + toxicité) : tracker process-local ---
_TOX = None


def _toxicity_tracker():
    global _TOX
    if _TOX is None:
        from hl_observer.signals.microprice_toxicity import ToxicityTracker
        _TOX = ToxicityTracker(alpha=0.2)
    return _TOX


def record_fill_markout(coin: str, side: str, entry_price: float, mark_after: float) -> float:
    """Après un fill: mesure le markout et met à jour la toxicité du coin. Retourne la toxicité."""
    from hl_observer.signals.microprice_toxicity import markout_bps
    mo = markout_bps(side, entry_price, mark_after)
    return _toxicity_tracker().record_markout(coin, mo)


def microstructure_entry_gate(
    *, coin: str, side: str, intended_price: float,
    bid: float, ask: float, bid_size: float, ask_size: float,
    base_min_edge_bps: float, volatility_bps: float = 0.0,
    max_micro_gap_bps: float = 8.0,
) -> dict:
    """Gate anti adverse-selection avant une entrée (flag HYPERSMART_MICROSTRUCTURE_GATE).

    OFF → passe tout (neutre). ON → refuse si le microprice est déjà défavorable, et
    relève l'edge minimum requis selon vol + toxicité mesurée du coin.
    """
    if not _on("HYPERSMART_MICROSTRUCTURE_GATE"):
        return {"allowed": True, "applied": False, "min_edge_required_bps": base_min_edge_bps, "reason": "GATE_OFF"}
    from hl_observer.signals.microprice_toxicity import (
        entry_price_refusal, microprice, toxicity_adjusted_min_edge_bps,
    )
    mp = microprice(bid, ask, bid_size, ask_size)
    refusal = entry_price_refusal(side=side, intended_price=intended_price, micro_price=mp, max_micro_gap_bps=max_micro_gap_bps)
    tox = _toxicity_tracker().toxicity(coin)
    min_edge = toxicity_adjusted_min_edge_bps(base_min_edge_bps, volatility_bps=volatility_bps, toxicity_bps=tox)
    return {
        "allowed": refusal == "",
        "applied": True,
        "microprice": mp,
        "toxicity_bps": tox,
        "min_edge_required_bps": min_edge,
        "reason": refusal or "MICROSTRUCTURE_OK",
    }
