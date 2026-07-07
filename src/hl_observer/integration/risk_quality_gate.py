"""A1 — Gate composite risque/qualité: UN point d'appel pré-trade.

Compose les briques pures livrées (corrélation portefeuille, qualité données, seuils
par classe, calendrier de marché, régime/volume) en une seule décision d'ouverture.
Le runtime appelle evaluate_pre_trade() AVANT d'ouvrir; si un composant refuse, on
renvoie NO_TRADE avec la raison précise. Chaque composant est activable par flag
(deny-by-default OFF → composant neutre). Pur, testé; câblage = un import + un appel.
"""

from __future__ import annotations

import os

from hl_observer.data_quality.guards import evaluate_data_quality
from hl_observer.market.calendar_gate import adjusted_min_edge_bps, gate_tightening_factor
from hl_observer.market.classification import thresholds_for_market
from hl_observer.edge.regime_volume import adjusted_edge_bps
from hl_observer.risk.portfolio_correlation import correlation_open_refusal


def _on(flag: str) -> bool:
    return str(os.getenv(flag, "0")).strip().lower() in {"1", "true", "yes", "on"}


def evaluate_pre_trade(
    *,
    coin: str,
    side: str,
    raw_edge_bps: float,
    notional_usdt: float,
    open_positions: list[dict],
    market: dict,           # {l2_depth_usdt, daily_volume_usdt, regime, volume_zscore}
    data: dict,             # {price, recent_prices, prices_by_source, last_update_ms, now_ms}
    calendar: dict | None = None,   # {utc_weekday, utc_hour, now_ms, macro_events_ms}
) -> dict:
    """Décision composite d'ouverture. reasons vide = autorisé."""

    reasons: list[str] = []
    applied: list[str] = []

    # 1) Qualité des données (flag HYPERSMART_GATE_DATA_QUALITY)
    if _on("HYPERSMART_GATE_DATA_QUALITY"):
        dq = evaluate_data_quality(
            coin, data.get("price"), data.get("recent_prices") or [],
            data.get("prices_by_source") or {}, data.get("last_update_ms") or 0, data.get("now_ms") or 0,
        )
        applied.append("DATA_QUALITY")
        if not dq["tradeable"]:
            reasons.extend(dq["reasons"])

    # 2) Régime + volume → edge ajusté (flag HYPERSMART_GATE_REGIME_VOLUME)
    effective_edge = float(raw_edge_bps)
    if _on("HYPERSMART_GATE_REGIME_VOLUME"):
        adj = adjusted_edge_bps(raw_edge_bps, regime=str(market.get("regime") or ""), volume_zscore=float(market.get("volume_zscore") or 0.0))
        effective_edge = adj["adjusted_edge_bps"]
        applied.append("REGIME_VOLUME")
        if adj["suppressed"]:
            reasons.append("REGIME_RANGING_SUPPRESSED")

    # 3) Seuils par classe de marché (flag HYPERSMART_GATE_MARKET_CLASS)
    min_edge = 0.0
    if _on("HYPERSMART_GATE_MARKET_CLASS"):
        th = thresholds_for_market(l2_depth_usdt=float(market.get("l2_depth_usdt") or 0.0), daily_volume_usdt=float(market.get("daily_volume_usdt") or 0.0))
        min_edge = th["min_edge_bps"]
        applied.append(f"MARKET_CLASS:{th['market_class']}")

    # 4) Calendrier → resserrement du seuil (flag HYPERSMART_GATE_CALENDAR)
    if _on("HYPERSMART_GATE_CALENDAR") and calendar:
        tight = gate_tightening_factor(
            utc_weekday=int(calendar.get("utc_weekday", 0)), utc_hour=int(calendar.get("utc_hour", 12)),
            now_ms=int(calendar.get("now_ms", 0)), macro_events_ms=calendar.get("macro_events_ms") or [],
        )
        applied.append("CALENDAR")
        if min_edge > 0:
            min_edge = adjusted_min_edge_bps(min_edge, tight)

    if min_edge > 0 and effective_edge < min_edge:
        reasons.append(f"EDGE_BELOW_CLASS_MINIMUM ({round(effective_edge,1)}<{round(min_edge,1)})")

    # 5) Corrélation portefeuille (flag HYPERSMART_GATE_CORRELATION)
    if _on("HYPERSMART_GATE_CORRELATION"):
        applied.append("CORRELATION")
        corr = correlation_open_refusal(open_positions, coin=coin, side=side, new_notional_usdt=notional_usdt)
        if corr:
            reasons.append(corr)

    return {
        "allowed": not reasons,
        "verdict": "OPEN_ALLOWED" if not reasons else "NO_TRADE",
        "reasons": reasons,
        "effective_edge_bps": round(effective_edge, 4),
        "min_edge_required_bps": round(min_edge, 4),
        "gates_applied": applied,
        "paper_only": True,
        "real_execution": False,
    }


__all__ = ["evaluate_pre_trade"]
