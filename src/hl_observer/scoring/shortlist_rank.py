"""V9 / S5 — Classement (ranking) de la shortlist de leaders.

Trie les wallets candidats par un score composite (qualité smart-money × activité ×
récence) pour que la shortlist BORNÉE suive les MEILLEURS leaders et les PLUS ACTIFS.
Objectif direct : augmenter l'offre de signaux d'entrée frais sans élargir aveuglément.
read-only / paper-only. Aucune donnée inventée.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


@dataclass(frozen=True, slots=True)
class WalletStats:
    address: str
    winrate: float = 0.0              # 0..1
    total_pnl_usdc: float = 0.0
    profit_factor: float = 0.0        # gains/pertes
    consistency: float = 0.0          # 0..1
    one_big_win_share: float = 0.0    # 0..1 (part du PnL venant d'un seul trade)
    recent_fills: int = 0             # activité récente
    last_fill_age_ms: int | None = None


@dataclass(frozen=True, slots=True)
class RankedWallet:
    address: str
    rank: int
    score: float                     # 0..100
    quality: float                   # 0..100 (smart-money)
    activity: float                  # 0..1
    reasons: tuple[str, ...] = field(default_factory=tuple)


def smart_money_quality(s: WalletStats) -> float:
    """Score de qualité 0..100 (mêmes leviers que le filtre smart-money V9)."""
    winrate = _clamp(float(s.winrate))
    pf = _clamp(float(s.profit_factor) / 3.0)          # PF 3.0 -> plein
    consistency = _clamp(float(s.consistency))
    pnl = _clamp(float(s.total_pnl_usdc) / 5_000.0)    # 5k USDC -> plein
    one_big = _clamp(float(s.one_big_win_share))
    # pénalité si un seul gros trade porte tout le PnL
    quality = 100.0 * (
        0.30 * winrate
        + 0.25 * pf
        + 0.20 * consistency
        + 0.15 * pnl
        + 0.10 * (1.0 - one_big)
    )
    return round(_clamp(quality, 0.0, 100.0), 6)


def activity_factor(s: WalletStats, *, recency_window_ms: int = 3_600_000) -> float:
    """Facteur 0..1 : plus le wallet est actif et récent, plus il fournit de signaux frais."""
    fills = _clamp(float(s.recent_fills) / 20.0)       # 20 fills récents -> plein
    if s.last_fill_age_ms is None:
        recency = 0.3
    else:
        recency = _clamp(1.0 - float(s.last_fill_age_ms) / max(1, recency_window_ms))
    return round(_clamp(0.6 * fills + 0.4 * recency), 6)


def rank_shortlist(
    wallets: list[WalletStats],
    *,
    limit: int | None = None,
    activity_weight: float = 0.5,
) -> list[RankedWallet]:
    """Classe les wallets par score composite décroissant. `limit` borne la shortlist."""
    scored: list[RankedWallet] = []
    for s in wallets:
        q = smart_money_quality(s)
        a = activity_factor(s)
        composite = q * (1.0 - activity_weight) + (a * 100.0) * activity_weight
        reasons: list[str] = []
        if q >= 60:
            reasons.append("SMART_MONEY")
        if a >= 0.5:
            reasons.append("ACTIVE")
        if s.one_big_win_share > 0.5:
            reasons.append("ONE_BIG_WIN_RISK")
        scored.append(
            RankedWallet(
                address=s.address,
                rank=0,
                score=round(_clamp(composite, 0.0, 100.0), 6),
                quality=q,
                activity=a,
                reasons=tuple(reasons),
            )
        )
    scored.sort(key=lambda w: (-w.score, w.address))
    ranked = [
        RankedWallet(address=w.address, rank=i + 1, score=w.score, quality=w.quality, activity=w.activity, reasons=w.reasons)
        for i, w in enumerate(scored)
    ]
    return ranked[: int(limit)] if limit is not None else ranked


__all__ = [
    "WalletStats",
    "RankedWallet",
    "smart_money_quality",
    "activity_factor",
    "rank_shortlist",
]
