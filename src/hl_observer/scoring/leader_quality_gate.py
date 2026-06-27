"""V9 / S5 — Gate de qualité des leaders (le vrai levier PnL).

Diagnostic prouvé hors-échantillon sur le ledger réel : copier TOUS les wallets
suivis donne ~54 % winrate et un PnL net négatif ; ne copier que les wallets
"smart money" (sélectionnés sur leur historique) donne ~67 % winrate et un PnL net
positif. Ce module calcule la qualité réalisée d'un leader (à partir de ses propres
allers-retours fermés) et décide s'il est copiable.

Sélection sur l'HISTORIQUE, copie sur le FUTUR (walk-forward) — aucun look-ahead,
aucune donnée inventée. read-only / paper-only. Ne promet aucun PnL.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class LeaderQualityConfig:
    min_round_trips: int = 3
    min_winrate: float = 0.60
    min_mean_move_bps: float = 12.0        # doit dépasser le coût round-trip
    round_trip_cost_bps: float = 11.0
    max_one_trade_share: float = 0.60      # un seul trade ne doit pas porter tout le gain


@dataclass(frozen=True, slots=True)
class LeaderQuality:
    wallet: str
    round_trips: int
    winrate: float
    mean_move_bps: float
    net_edge_bps: float                    # mean_move - cost
    one_trade_share: float
    qualified: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)


def assess_leader_quality(
    wallet: str,
    moves_bps: list[float],
    *,
    config: LeaderQualityConfig | None = None,
) -> LeaderQuality:
    cfg = config or LeaderQualityConfig()
    n = len(moves_bps)
    if n == 0:
        return LeaderQuality(wallet, 0, 0.0, 0.0, -cfg.round_trip_cost_bps, 0.0, False, ("NO_HISTORY",))
    wins = sum(1 for m in moves_bps if m > 0)
    winrate = wins / n
    mean_move = sum(moves_bps) / n
    net_edge = mean_move - cfg.round_trip_cost_bps
    gains = [m for m in moves_bps if m > 0]
    total_gain = sum(gains)
    one_trade_share = (max(gains) / total_gain) if total_gain > 0 else 0.0

    reasons: list[str] = []
    if n < cfg.min_round_trips:
        reasons.append(f"TOO_FEW_TRIPS_{n}<{cfg.min_round_trips}")
    if winrate < cfg.min_winrate:
        reasons.append(f"WINRATE_{winrate:.2f}<{cfg.min_winrate:.2f}")
    if mean_move < cfg.min_mean_move_bps:
        reasons.append(f"MEAN_MOVE_{mean_move:.1f}<{cfg.min_mean_move_bps:.1f}bps")
    if one_trade_share > cfg.max_one_trade_share:
        reasons.append("ONE_BIG_WIN_RISK")

    qualified = not reasons
    if qualified:
        reasons.append("SMART_MONEY")
    return LeaderQuality(
        wallet=wallet,
        round_trips=n,
        winrate=round(winrate, 4),
        mean_move_bps=round(mean_move, 4),
        net_edge_bps=round(net_edge, 4),
        one_trade_share=round(one_trade_share, 4),
        qualified=qualified,
        reasons=tuple(reasons),
    )


def select_smart_money(
    wallet_moves: dict[str, list[float]],
    *,
    config: LeaderQualityConfig | None = None,
) -> list[LeaderQuality]:
    """Retourne les leaders QUALIFIÉS uniquement, classés par edge net décroissant."""
    assessed = [assess_leader_quality(w, m, config=config) for w, m in wallet_moves.items()]
    qualified = [a for a in assessed if a.qualified]
    qualified.sort(key=lambda a: -a.net_edge_bps)
    return qualified


__all__ = ["LeaderQualityConfig", "LeaderQuality", "assess_leader_quality", "select_smart_money"]
