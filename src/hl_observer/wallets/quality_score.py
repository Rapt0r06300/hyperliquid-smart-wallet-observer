"""SCAN-QUALITY — Couche de qualité wallet (distillée Nansen/whaleportal/freqtrade + X).

Le scan actuel privilégie PnL brut + activité récente. Piège documenté (recherche
2026): classer au profit brut récompense la TAILLE et la CHANCE à parts égales.
Cette couche ADDITIVE raffine le score par des signaux de VRAI talent:

  - consistance multi-fenêtres (7j/30j/90j toutes positives = edge répétable);
  - max drawdown (un talent contrôle son risque);
  - profit factor net (gains/pertes);
  - garde-fou anti-"un seul gros coup" (concentration du profit);
  - type de comportement (swing copiable; scalper/MM/HFT non copiables via latence HL).

Pur, déterministe, flag-gated. Retourne un multiplicateur [0.2, 1.25] à appliquer
au score de découverte + les raisons. Aucune donnée inventée: signal absent = neutre.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

FLAG = "HYPERSMART_WALLET_QUALITY_SCORING"
_COPYABLE_KINDS = {"SWING"}
_UNCOPYABLE_KINDS = {"HFT", "SCALPER", "MARKET_MAKER", "MANIPULATOR"}


def quality_scoring_enabled() -> bool:
    return str(os.getenv(FLAG, "0")).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class WalletQuality:
    multiplier: float
    consistency_score: float
    drawdown_score: float
    profit_factor_score: float
    concentration_penalty: float
    behavior_factor: float
    reasons: tuple[str, ...]


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def compute_wallet_quality(
    *,
    pnl_7d: float | None = None,
    pnl_30d: float | None = None,
    pnl_90d: float | None = None,
    max_drawdown_pct: float | None = None,
    profit_factor: float | None = None,
    largest_trade_pnl: float | None = None,
    total_gross_profit: float | None = None,
    behavior_kind: str | None = None,
    trade_switch_rate_per_day: float | None = None,
) -> WalletQuality:
    reasons: list[str] = []

    # 1) Consistance multi-fenêtres: un edge répétable est positif sur 7j ET 30j ET 90j.
    windows = [w for w in (pnl_7d, pnl_30d, pnl_90d) if w is not None]
    if len(windows) >= 2:
        pos = sum(1 for w in windows if w > 0)
        consistency = pos / len(windows)
        if consistency == 1.0:
            reasons.append("CONSISTENT_ALL_WINDOWS")
        elif consistency <= 0.34:
            reasons.append("INCONSISTENT_MOSTLY_NEGATIVE")
        consistency_score = consistency  # 0..1
    else:
        consistency_score = 0.5  # inconnu -> neutre
        reasons.append("WINDOWS_UNKNOWN")

    # 2) Max drawdown: pénalise le risque non maîtrisé.
    if max_drawdown_pct is None:
        drawdown_score = 0.5
    else:
        dd = abs(float(max_drawdown_pct))
        drawdown_score = _clamp(1.0 - dd / 60.0, 0.0, 1.0)  # 60%+ DD -> 0
        if dd >= 50:
            reasons.append("HIGH_DRAWDOWN")

    # 3) Profit factor (gains/pertes).
    if profit_factor is None:
        pf_score = 0.5
    else:
        pf = float(profit_factor)
        pf_score = _clamp((pf - 1.0) / 1.5, 0.0, 1.0)  # PF 1.0->0, 2.5+->1
        if pf < 1.0:
            reasons.append("PROFIT_FACTOR_BELOW_1")

    # 4) Garde-fou anti-"un seul gros coup" (concentration).
    concentration_penalty = 1.0
    if largest_trade_pnl is not None and total_gross_profit and total_gross_profit > 0:
        share = _clamp(float(largest_trade_pnl) / float(total_gross_profit), 0.0, 1.0)
        if share >= 0.7:
            concentration_penalty = 0.45
            reasons.append("SINGLE_TRADE_CONCENTRATION")  # profit vient d'un coup = chance
        elif share >= 0.5:
            concentration_penalty = 0.75
            reasons.append("CONCENTRATED_PROFIT")

    # 5) Comportement: seul le SWING est copiable (latence HL 200-500ms).
    kind = str(behavior_kind or "").upper()
    if kind in _COPYABLE_KINDS:
        behavior_factor = 1.15
        reasons.append("SWING_COPYABLE")
    elif kind in _UNCOPYABLE_KINDS:
        behavior_factor = 0.35
        reasons.append("UNCOPYABLE_BEHAVIOR_" + kind)
    else:
        behavior_factor = 1.0

    # 6) Churn (X/ApexLiquid): un wallet qui change TROP souvent de trade = haut risque,
    #    non copiable proprement (latence). > ~40 switches/jour = scalping/bruit.
    churn_factor = 1.0
    if trade_switch_rate_per_day is not None and trade_switch_rate_per_day > 40:
        churn_factor = 0.6
        reasons.append("HIGH_TRADE_CHURN")

    base = 0.42 * consistency_score + 0.28 * pf_score + 0.30 * drawdown_score  # 0..1
    multiplier = _clamp((0.6 + 0.65 * base) * concentration_penalty * behavior_factor * churn_factor, 0.2, 1.25)
    return WalletQuality(
        multiplier=round(multiplier, 4),
        consistency_score=round(consistency_score, 4),
        drawdown_score=round(drawdown_score, 4),
        profit_factor_score=round(pf_score, 4),
        concentration_penalty=concentration_penalty,
        behavior_factor=behavior_factor,
        reasons=tuple(reasons),
    )


def refine_discovery_score(base_discovery_score: float, quality: WalletQuality) -> float:
    """Applique le multiplicateur de qualité au score de découverte (borné 0..100)."""
    return round(_clamp(float(base_discovery_score) * quality.multiplier, 0.0, 100.0), 4)


__all__ = ["FLAG", "WalletQuality", "quality_scoring_enabled", "compute_wallet_quality", "refine_discovery_score"]
