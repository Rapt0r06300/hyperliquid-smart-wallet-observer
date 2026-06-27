"""
Scoring account/subaccount dYdX v4.

Critères: PnL net, winrate, profit factor, expectancy, drawdown,
régularité, récence, volume, copyability, confiance données.

Rejets automatiques:
- historique insuffisant
- one-big-win
- PnL concentré sur 1 trade
- compte trop rare
- compte perdant après frais
- données incomplètes
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Seuils de scoring
MIN_TRADES_FOR_SCORING = 10
MIN_WIN_RATE = 0.40          # 40% minimum
MIN_PROFIT_FACTOR = 1.2      # 1.2x minimum
MAX_PNL_CONCENTRATION = 0.70  # 1 trade ne peut pas représenter >70% du PnL total
MIN_DATA_CONFIDENCE = 0.5    # confiance minimum sur les données


@dataclass
class AccountScore:
    """Score composite d'un account/subaccount dYdX."""
    account_address: str
    subaccount_number: int
    network: str

    # Métriques brutes
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl_gross: float = 0.0
    total_pnl_net: float = 0.0
    total_fees: float = 0.0
    max_single_win: float = 0.0
    max_drawdown: float = 0.0
    avg_holding_time_ms: float = 0.0
    avg_trade_size: float = 0.0

    # Scores calculés (0.0 à 1.0)
    winrate: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    regularity: float = 0.0       # régularité des gains
    recency_score: float = 0.0    # récence de l'activité
    volume_score: float = 0.0     # volume relatif
    copyability: float = 0.0      # facilité à copier
    data_confidence: float = 0.0  # confiance dans les données

    # Score composite final
    composite_score: float = 0.0

    # Raisons de rejet (vide = score valide)
    rejection_reasons: list[str] = field(default_factory=list)
    is_rejected: bool = False

    computed_at_ms: int = 0

    @property
    def is_valid(self) -> bool:
        return not self.is_rejected and self.composite_score > 0


@dataclass
class TradeRecord:
    """Enregistrement simplifié d'un trade pour scoring."""
    pnl_gross: float
    pnl_net: float
    fees: float
    size: float
    entry_price: float
    closed_at_ms: int
    holding_time_ms: float
    market_id: str


def compute_account_score(
    account_address: str,
    subaccount_number: int,
    network: str,
    trades: list[TradeRecord],
    current_ts_ms: int,
    min_trades: int = MIN_TRADES_FOR_SCORING,
) -> AccountScore:
    """
    Calculer le score composite d'un account/subaccount.

    Ne retourne jamais de score positif si les données sont insuffisantes.
    """
    score = AccountScore(
        account_address=account_address,
        subaccount_number=subaccount_number,
        network=network,
        computed_at_ms=current_ts_ms,
    )

    # --- Vérification minimale ---
    if len(trades) < min_trades:
        score.rejection_reasons.append(
            f"INSUFFICIENT_HISTORY: {len(trades)} trades < {min_trades} minimum"
        )
        score.is_rejected = True
        score.data_confidence = len(trades) / min_trades
        return score

    score.total_trades = len(trades)
    wins = [t for t in trades if t.pnl_net > 0]
    losses = [t for t in trades if t.pnl_net <= 0]
    score.winning_trades = len(wins)
    score.losing_trades = len(losses)

    total_gross = sum(t.pnl_gross for t in trades)
    total_net = sum(t.pnl_net for t in trades)
    total_fees = sum(t.fees for t in trades)

    score.total_pnl_gross = total_gross
    score.total_pnl_net = total_net
    score.total_fees = total_fees

    # Winrate
    score.winrate = len(wins) / len(trades) if trades else 0.0

    # Profit factor
    gross_wins = sum(t.pnl_net for t in wins)
    gross_losses = abs(sum(t.pnl_net for t in losses))
    score.profit_factor = gross_wins / gross_losses if gross_losses > 0 else (
        float("inf") if gross_wins > 0 else 0.0
    )

    # Expectancy (net par trade)
    score.expectancy = total_net / len(trades) if trades else 0.0

    # Max single win
    score.max_single_win = max((t.pnl_net for t in wins), default=0.0)

    # Max drawdown (simplifié — cumul des pertes consécutives)
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in sorted(trades, key=lambda x: x.closed_at_ms):
        cumulative += t.pnl_net
        peak = max(peak, cumulative)
        dd = peak - cumulative
        max_dd = max(max_dd, dd)
    score.max_drawdown = max_dd

    # Avg holding time
    if trades:
        score.avg_holding_time_ms = sum(t.holding_time_ms for t in trades) / len(trades)

    # Avg trade size
    if trades:
        score.avg_trade_size = sum(abs(t.size) for t in trades) / len(trades)

    # --- Rejets automatiques ---

    # Compte perdant après frais
    if total_net <= 0:
        score.rejection_reasons.append(
            f"LOSING_AFTER_COSTS: net_pnl={total_net:.2f} USDC"
        )
        score.is_rejected = True

    # Winrate trop faible
    if score.winrate < MIN_WIN_RATE:
        score.rejection_reasons.append(
            f"WINRATE_TOO_LOW: {score.winrate:.1%} < {MIN_WIN_RATE:.1%}"
        )
        score.is_rejected = True

    # Profit factor trop faible
    if score.profit_factor < MIN_PROFIT_FACTOR:
        score.rejection_reasons.append(
            f"PROFIT_FACTOR_TOO_LOW: {score.profit_factor:.2f} < {MIN_PROFIT_FACTOR}"
        )
        score.is_rejected = True

    # One-big-win: un seul trade représente >70% du PnL total
    if total_net > 0 and score.max_single_win > MAX_PNL_CONCENTRATION * total_net:
        score.rejection_reasons.append(
            f"ONE_BIG_WIN: max_win={score.max_single_win:.2f} = "
            f"{score.max_single_win/total_net:.1%} of total PnL"
        )
        score.is_rejected = True

    if score.is_rejected:
        return score

    # --- Calcul des scores normalisés ---

    # Régularité: stddev des PnL (plus c'est stable, mieux c'est)
    avg_pnl = total_net / len(trades)
    variance = sum((t.pnl_net - avg_pnl) ** 2 for t in trades) / len(trades)
    stddev = math.sqrt(variance)
    cv = stddev / abs(avg_pnl) if avg_pnl != 0 else float("inf")
    score.regularity = max(0.0, 1.0 - min(cv / 2.0, 1.0))

    # Récence: poids sur l'activité récente (7 jours)
    WEEK_MS = 7 * 24 * 3600 * 1000
    recent = [t for t in trades if current_ts_ms - t.closed_at_ms <= WEEK_MS]
    score.recency_score = min(1.0, len(recent) / max(1, min_trades))

    # Volume score (normalisé sur $10k/trade)
    score.volume_score = min(1.0, score.avg_trade_size / 10_000)

    # Copyability: trades ni trop rapides (<5min) ni trop lents (>7j)
    MIN_HOLD = 5 * 60 * 1000      # 5 minutes
    MAX_HOLD = 7 * 24 * 3600 * 1000  # 7 jours
    good_hold = [
        t for t in trades
        if MIN_HOLD <= t.holding_time_ms <= MAX_HOLD
    ]
    score.copyability = len(good_hold) / len(trades) if trades else 0.0

    # Data confidence: ratio trades avec données complètes
    complete = [t for t in trades if t.pnl_gross != 0 and t.fees >= 0 and t.size > 0]
    score.data_confidence = len(complete) / len(trades) if trades else 0.0

    if score.data_confidence < MIN_DATA_CONFIDENCE:
        score.rejection_reasons.append(
            f"LOW_DATA_CONFIDENCE: {score.data_confidence:.1%} < {MIN_DATA_CONFIDENCE:.1%}"
        )
        score.is_rejected = True
        return score

    # --- Score composite ---
    # Pondérations
    weights = {
        "winrate":       0.20,
        "profit_factor": 0.20,
        "regularity":    0.15,
        "recency":       0.15,
        "copyability":   0.15,
        "data_conf":     0.10,
        "volume":        0.05,
    }

    # Normaliser profit_factor (cap à 3.0)
    pf_norm = min(1.0, (score.profit_factor - 1.0) / 2.0) if score.profit_factor > 1.0 else 0.0
    winrate_norm = (score.winrate - MIN_WIN_RATE) / (1.0 - MIN_WIN_RATE)

    composite = (
        winrate_norm         * weights["winrate"]
        + pf_norm            * weights["profit_factor"]
        + score.regularity   * weights["regularity"]
        + score.recency_score * weights["recency"]
        + score.copyability  * weights["copyability"]
        + score.data_confidence * weights["data_conf"]
        + score.volume_score * weights["volume"]
    )

    score.composite_score = max(0.0, min(1.0, composite)) * 100.0

    return score
