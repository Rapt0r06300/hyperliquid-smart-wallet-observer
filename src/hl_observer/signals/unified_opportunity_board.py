"""Tableau d'opportunités UNIFIÉ cross-stratégie (comble un vrai trou).

Constat: les rankers existants (copy, funding-arb, arbitrage) sont SILOTÉS —
rien ne classe une opportunité de copy face à une de funding face à une d'arbitrage
sur la MÊME échelle. Le grinder ne peut donc pas choisir la meilleure opportunité
GLOBALE. Ce module réutilise le power-scorer V9 existant (`opportunity_ranker`,
zéro duplication) pour fusionner toutes les stratégies en un seul tableau classé
par edge net après coûts, avec diversification par coin ET par stratégie (pour ne
pas empiler que du funding ou que du copy).

Pur, déterministe, paper-only. Un score élevé = classement de recherche, jamais un
ordre ni une promesse de gain. Les candidats sous plancher (edge, liquidité,
fraîcheur) sont éliminés par le scorer réutilisé.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hl_observer.signals.opportunity_ranker import (
    OpportunityInput,
    RankerConfig,
    power_score,
)


@dataclass(frozen=True, slots=True)
class BoardEntry:
    coin: str
    side: str
    strategy: str          # COPY | FUNDING_ARB | ARBITRAGE | DISTILLED | ...
    power_score: float     # 0..100 (échelle commune)
    net_edge_bps: float


def build_opportunity_board(
    tagged_candidates: list[tuple[str, OpportunityInput]],
    config: RankerConfig | None = None,
    *,
    limit: int | None = None,
    max_per_coin: int | None = None,
    max_per_strategy: int | None = None,
) -> list[BoardEntry]:
    """Fusionne des candidats étiquetés (stratégie, OpportunityInput) en un tableau
    classé par power score (edge net après coûts) sur une échelle commune.

    Diversification: au plus `max_per_coin` par coin (défaut = RankerConfig) et,
    si fourni, `max_per_strategy` par stratégie — pour que le tableau ne soit pas
    monopolisé par une seule source. Provenance (stratégie) préservée.
    """
    cfg = config or RankerConfig()
    mpc = cfg.max_per_coin if max_per_coin is None else int(max_per_coin)

    scored: list[BoardEntry] = []
    for strat, c in tagged_candidates or ():
        s = power_score(c, cfg)
        if s <= 0.0:
            continue                      # plancher échoué -> éliminé (par le scorer réutilisé)
        scored.append(BoardEntry(
            coin=str(c.coin or "").upper(), side=str(c.side or "").upper(),
            strategy=str(strat or "?").upper(), power_score=s, net_edge_bps=round(c.net_edge_bps, 4),
        ))
    scored.sort(key=lambda r: -r.power_score)

    per_coin: dict[str, int] = {}
    per_strat: dict[str, int] = {}
    kept: list[BoardEntry] = []
    for r in scored:
        if per_coin.get(r.coin, 0) >= mpc:
            continue
        if max_per_strategy is not None and per_strat.get(r.strategy, 0) >= int(max_per_strategy):
            continue
        per_coin[r.coin] = per_coin.get(r.coin, 0) + 1
        per_strat[r.strategy] = per_strat.get(r.strategy, 0) + 1
        kept.append(r)
        if limit is not None and len(kept) >= int(limit):
            break
    return kept


def summarize_board(board: list[BoardEntry]) -> dict:
    """Résumé pour le dashboard: nb par stratégie, meilleure entrée, edge médian."""
    if not board:
        return {"total": 0, "by_strategy": {}, "top": None, "best_net_edge_bps": 0.0}
    by_strategy: dict[str, int] = {}
    for e in board:
        by_strategy[e.strategy] = by_strategy.get(e.strategy, 0) + 1
    top = board[0]
    return {
        "total": len(board),
        "by_strategy": by_strategy,
        "top": {"coin": top.coin, "side": top.side, "strategy": top.strategy,
                "power_score": top.power_score, "net_edge_bps": top.net_edge_bps},
        "best_net_edge_bps": max(e.net_edge_bps for e in board),
    }


__all__ = ["BoardEntry", "build_opportunity_board", "summarize_board"]
