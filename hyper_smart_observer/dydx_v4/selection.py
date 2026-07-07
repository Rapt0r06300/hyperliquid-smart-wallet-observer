"""
Sélection v2 — tiers stricts inspirés des standards du bot viral Polymarket.

Tiers:
- ELITE    : copiable taille pleine  (≥50 trades, WR≥55%, PF≥1.5, Sharpe≥1.0, ≥60j)
- STANDARD : copiable taille réduite (≥30 trades, WR≥50%, PF≥1.3, Sharpe≥0.5, ≥30j)
- WATCH    : observé, JAMAIS copié
- REJECTED : ignoré

Règles anti-chance:
- winrate > 90% = suspect → max WATCH (pattern anormal, wash/luck)
- un seul trade ne peut pas dépasser 50% (ELITE) / 60% (STANDARD) du PnL total
- promotion limitée à UN tier par refresh (anti yo-yo), rétrogradation immédiate

PAPER-ONLY / READ-ONLY. Aucun ordre réel. Aucune clé privée.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

try:
    from enum import StrEnum
except ImportError:  # Python 3.10
    from enum import Enum

    class StrEnum(str, Enum):
        def __str__(self) -> str:
            return self.value

logger = logging.getLogger(__name__)

DAY_MS = 86_400_000


class SelectionTier(StrEnum):
    ELITE = "ELITE"
    STANDARD = "STANDARD"
    WATCH = "WATCH"
    REJECTED = "REJECTED"


# Ordre pour la règle de promotion/rétrogradation
_TIER_ORDER = {
    SelectionTier.REJECTED: 0,
    SelectionTier.WATCH: 1,
    SelectionTier.STANDARD: 2,
    SelectionTier.ELITE: 3,
}

# Multiplicateur de taille de copie par tier (paper sizing)
TIER_SIZE_MULTIPLIER = {
    SelectionTier.ELITE: 1.0,
    SelectionTier.STANDARD: 0.5,
    SelectionTier.WATCH: 0.0,
    SelectionTier.REJECTED: 0.0,
}


@dataclass(frozen=True)
class TierThresholds:
    min_closed_trades: int
    min_winrate: float
    min_profit_factor: float
    min_sharpe: float
    min_history_days: float
    max_drawdown_pct: float
    max_single_trade_pnl_share: float
    min_data_confidence: float


@dataclass(frozen=True)
class SelectionCriteria:
    """Seuils standards bot viral (durcis vs scoring v1: 10 trades / WR 40%)."""

    elite: TierThresholds = field(default_factory=lambda: TierThresholds(
        min_closed_trades=50,
        min_winrate=0.55,
        min_profit_factor=1.5,
        min_sharpe=1.0,
        min_history_days=60,
        max_drawdown_pct=25.0,
        max_single_trade_pnl_share=0.50,
        min_data_confidence=0.7,
    ))
    standard: TierThresholds = field(default_factory=lambda: TierThresholds(
        min_closed_trades=30,
        min_winrate=0.50,
        min_profit_factor=1.3,
        min_sharpe=0.5,
        min_history_days=30,
        max_drawdown_pct=35.0,
        max_single_trade_pnl_share=0.60,
        min_data_confidence=0.6,
    ))
    # WR au-dessus duquel le compte est suspect (lottery / wash / données fausses)
    suspicious_winrate: float = 0.90
    # En-dessous → REJECTED direct
    watch_min_trades: int = 10


@dataclass
class AccountMetrics:
    """Métriques consolidées d'un compte (fills + equity curve historicalPnl)."""

    address: str
    subaccount_number: int = 0
    closed_trades: int = 0
    winrate: float = 0.0
    profit_factor: float = 0.0
    total_net_pnl: float = 0.0
    single_trade_pnl_share: float = 1.0  # part du plus gros trade dans le PnL
    sharpe: float = 0.0                  # annualisé, depuis equity curve daily
    max_drawdown_pct: float = 100.0
    history_days: float = 0.0
    data_confidence: float = 0.0
    data_source: str = "REAL_INDEXER"    # REAL_INDEXER | LEGACY_ARTIFICIAL | FIXTURE


@dataclass
class TierDecision:
    tier: SelectionTier
    size_multiplier: float
    reasons: list[str] = field(default_factory=list)

    @property
    def copyable(self) -> bool:
        return self.tier in (SelectionTier.ELITE, SelectionTier.STANDARD)


@dataclass
class EquityMetrics:
    sharpe: float
    max_drawdown_pct: float
    history_days: float
    n_points: int


def compute_equity_metrics(points: list[tuple[int, float]]) -> EquityMetrics:
    """
    Métriques depuis une equity curve [(ts_ms, equity)] (source: /v4/historicalPnl).

    - Sharpe: retours quotidiens (dernier point de chaque jour), annualisé √365
    - Max drawdown: pic-à-creux en % du pic
    - history_days: étendue temporelle couverte
    """
    if not points:
        return EquityMetrics(0.0, 100.0, 0.0, 0)

    daily: dict[int, float] = {}
    for ts_ms, eq in sorted(points):
        daily[ts_ms // DAY_MS] = float(eq)

    days = sorted(daily)
    eqs = [daily[d] for d in days]
    history_days = float(days[-1] - days[0]) if len(days) >= 2 else 0.0

    returns: list[float] = []
    for prev, cur in zip(eqs, eqs[1:]):
        if prev > 0:
            returns.append((cur - prev) / prev)

    sharpe = 0.0
    if len(returns) >= 5:
        mean = sum(returns) / len(returns)
        var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
        std = math.sqrt(var)
        if std > 1e-12:
            sharpe = (mean / std) * math.sqrt(365.0)

    peak = -math.inf
    mdd = 0.0
    for e in eqs:
        peak = max(peak, e)
        if peak > 0:
            mdd = max(mdd, (peak - e) / peak)

    return EquityMetrics(
        sharpe=sharpe,
        max_drawdown_pct=mdd * 100.0,
        history_days=history_days,
        n_points=len(points),
    )


def _check_thresholds(m: AccountMetrics, t: TierThresholds) -> list[str]:
    """Retourne la liste des critères NON remplis (vide = tier atteint)."""
    fails: list[str] = []
    if m.closed_trades < t.min_closed_trades:
        fails.append(f"trades {m.closed_trades}<{t.min_closed_trades}")
    if m.winrate < t.min_winrate:
        fails.append(f"winrate {m.winrate:.0%}<{t.min_winrate:.0%}")
    if m.profit_factor < t.min_profit_factor:
        fails.append(f"pf {m.profit_factor:.2f}<{t.min_profit_factor}")
    if m.sharpe < t.min_sharpe:
        fails.append(f"sharpe {m.sharpe:.2f}<{t.min_sharpe}")
    if m.history_days < t.min_history_days:
        fails.append(f"history {m.history_days:.0f}j<{t.min_history_days:.0f}j")
    if m.max_drawdown_pct > t.max_drawdown_pct:
        fails.append(f"dd {m.max_drawdown_pct:.0f}%>{t.max_drawdown_pct:.0f}%")
    if m.single_trade_pnl_share > t.max_single_trade_pnl_share:
        fails.append(
            f"concentration {m.single_trade_pnl_share:.0%}>{t.max_single_trade_pnl_share:.0%}"
        )
    if m.data_confidence < t.min_data_confidence:
        fails.append(f"confidence {m.data_confidence:.0%}<{t.min_data_confidence:.0%}")
    if m.total_net_pnl <= 0:
        fails.append("pnl_net<=0")
    return fails


def classify_account(
    metrics: AccountMetrics,
    criteria: SelectionCriteria | None = None,
) -> TierDecision:
    """Classer un compte dans un tier. Seuls ELITE et STANDARD sont copiables."""
    c = criteria or SelectionCriteria()
    reasons: list[str] = []

    # Garde anti-données-synthétiques: jamais copiable
    if metrics.data_source != "REAL_INDEXER":
        return TierDecision(
            SelectionTier.WATCH, 0.0,
            [f"DATA_SOURCE_{metrics.data_source}: jamais copiable"],
        )

    # Winrate suspect → max WATCH
    if metrics.winrate > c.suspicious_winrate and metrics.closed_trades >= 10:
        return TierDecision(
            SelectionTier.WATCH, 0.0,
            [f"WINRATE_SUSPICIOUS {metrics.winrate:.0%}>{c.suspicious_winrate:.0%}"],
        )

    elite_fails = _check_thresholds(metrics, c.elite)
    if not elite_fails:
        return TierDecision(SelectionTier.ELITE,
                            TIER_SIZE_MULTIPLIER[SelectionTier.ELITE],
                            ["ELITE: tous critères remplis"])
    reasons.extend(f"ELITE_FAIL: {f}" for f in elite_fails[:3])

    std_fails = _check_thresholds(metrics, c.standard)
    if not std_fails:
        return TierDecision(SelectionTier.STANDARD,
                            TIER_SIZE_MULTIPLIER[SelectionTier.STANDARD],
                            reasons + ["STANDARD: critères remplis"])
    reasons.extend(f"STANDARD_FAIL: {f}" for f in std_fails[:3])

    if metrics.closed_trades >= c.watch_min_trades:
        return TierDecision(SelectionTier.WATCH, 0.0, reasons + ["WATCH"])

    return TierDecision(SelectionTier.REJECTED, 0.0,
                        reasons + [f"trades<{c.watch_min_trades}"])


def apply_tier_transition(
    previous: SelectionTier | None,
    computed: SelectionTier,
) -> SelectionTier:
    """
    Anti yo-yo: la PROMOTION est limitée à un tier par refresh
    (WATCH→STANDARD→ELITE). La RÉTROGRADATION est immédiate.
    """
    if previous is None:
        # Premier passage: jamais ELITE direct — il faut deux refresh consécutifs
        if computed == SelectionTier.ELITE:
            return SelectionTier.STANDARD
        return computed
    prev_o, comp_o = _TIER_ORDER[previous], _TIER_ORDER[computed]
    if comp_o <= prev_o:
        return computed  # rétrogradation (ou stable) immédiate
    # promotion: un seul cran
    for tier, order in _TIER_ORDER.items():
        if order == prev_o + 1:
            return tier
    return computed


def composite_score(m: AccountMetrics) -> float:
    """Score 0-100 Sharpe-pondéré pour le classement (pas pour la copiabilité)."""
    sharpe_n = max(0.0, min(1.0, m.sharpe / 3.0))
    pf_n = max(0.0, min(1.0, (m.profit_factor - 1.0) / 2.0))
    wr_n = max(0.0, min(1.0, (m.winrate - 0.40) / 0.40))
    dd_n = max(0.0, min(1.0, 1.0 - m.max_drawdown_pct / 50.0))
    hist_n = max(0.0, min(1.0, m.history_days / 90.0))
    return round(
        100.0 * (0.40 * sharpe_n + 0.20 * pf_n + 0.15 * wr_n + 0.15 * dd_n + 0.10 * hist_n),
        2,
    )
