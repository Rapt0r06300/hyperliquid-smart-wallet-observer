"""Adapte le résultat du fusion runtime en tableau d'opportunités UNIFIÉ.

Convertit les candidats natifs de chaque stratégie (distilled copy, arbitrage
triangulaire, funding) en OpportunityInput sur l'échelle commune, puis appelle
build_opportunity_board. Défensif (getattr + défauts) pour marcher avec des
dataclasses OU des dicts. Honnête: un candidat sans edge net mesurable est ignoré
(jamais de score inventé). Pur, paper-only.
"""

from __future__ import annotations

from typing import Any

from hl_observer.signals.opportunity_ranker import OpportunityInput, RankerConfig
from hl_observer.signals.unified_opportunity_board import (
    BoardEntry,
    build_opportunity_board,
    summarize_board,
)


def _g(obj: Any, *names, default=None):
    for n in names:
        if isinstance(obj, dict) and n in obj:
            return obj[n]
        if hasattr(obj, n):
            return getattr(obj, n)
    return default


def _num(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def _oi_from_distilled(o: Any, now_ms: int) -> OpportunityInput | None:
    coin = _g(o, "coin")
    edge = _g(o, "edge_remaining_bps", "net_edge_bps")
    if not coin or edge is None:
        return None
    ev = _g(o, "event_time_ms", "observed_at_ms", default=now_ms)
    ev = ev if ev is not None else now_ms   # 0 est un ts valide: pas de fallback "or"
    age = max(0, int(now_ms) - int(ev))
    lw = _g(o, "leader_score")
    return OpportunityInput(
        coin=str(coin), side=str(_g(o, "side", default="LONG")), net_edge_bps=_num(edge),
        signal_age_ms=age, consensus_wallets=int(_num(_g(o, "wallet_count", "consensus_wallets", default=2), 2)),
        liquidity_score=_num(_g(o, "liquidity_score", default=0.5), 0.5),
        leader_winrate=(_num(lw) / 100.0 if lw is not None and _num(lw) > 1 else (_num(lw) if lw is not None else None)),
    )


def _oi_from_triangular(t: Any) -> OpportunityInput | None:
    if not _g(t, "accepted", default=False):
        return None
    edge = _g(t, "net_edge_bps")
    if edge is None:
        return None
    cyc = _g(t, "cycle")
    coins = _g(cyc, "coins", "legs", default=None) if cyc is not None else None
    coin = ("-".join(str(c) for c in coins) if coins else _g(t, "coin", default="TRIANGULAR"))
    return OpportunityInput(coin=str(coin)[:16], side="NEUTRAL", net_edge_bps=_num(edge),
                            signal_age_ms=0, consensus_wallets=1, liquidity_score=0.6)


def _oi_from_funding(f: Any, now_ms: int) -> OpportunityInput | None:
    coin = _g(f, "coin")
    edge = _g(f, "net_edge_bps", "edge_bps", "expected_net_edge_bps")
    if not coin or edge is None:
        return None                       # honnête: pas d'edge mesurable -> ignoré
    return OpportunityInput(coin=str(coin), side=str(_g(f, "side", default="LONG")), net_edge_bps=_num(edge),
                            signal_age_ms=0, consensus_wallets=1,
                            liquidity_score=_num(_g(f, "liquidity_score", default=0.55), 0.55))


def board_from_fusion_result(
    result: Any, *, now_ms: int = 0, config: RankerConfig | None = None,
    limit: int = 8, max_per_strategy: int | None = 3,
) -> list[BoardEntry]:
    """Construit le tableau unifié depuis un FusionRuntimeResult (ou objet compatible)."""
    tagged: list[tuple[str, OpportunityInput]] = []
    rep = _g(result, "distilled_opportunity_report")
    for o in (_g(rep, "opportunities", default=None) or []):
        oi = _oi_from_distilled(o, now_ms)
        if oi:
            tagged.append(("DISTILLED", oi))
    for t in (_g(result, "triangular_opportunities", default=None) or []):
        oi = _oi_from_triangular(t)
        if oi:
            tagged.append(("ARBITRAGE", oi))
    for fs in (_g(result, "funding_signals", default=None) or []):
        oi = _oi_from_funding(fs, now_ms)
        if oi:
            tagged.append(("FUNDING_ARB", oi))
    return build_opportunity_board(tagged, config, limit=limit, max_per_strategy=max_per_strategy)


def board_payload_from_fusion_result(result: Any, *, now_ms: int = 0, limit: int = 8) -> dict:
    """Version sérialisable pour le dashboard: liste d'entrées + résumé."""
    board = board_from_fusion_result(result, now_ms=now_ms, limit=limit)
    return {
        "entries": [
            {"coin": e.coin, "side": e.side, "strategy": e.strategy,
             "power_score": e.power_score, "net_edge_bps": e.net_edge_bps}
            for e in board
        ],
        "summary": summarize_board(board),
    }


__all__ = ["board_from_fusion_result", "board_payload_from_fusion_result"]
