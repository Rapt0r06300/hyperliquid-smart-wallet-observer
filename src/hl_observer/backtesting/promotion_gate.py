"""F30 — ÉCHELLE PAPER → MICRO-TESTNET : la porte de PROMOTION, deny-by-default.

Une stratégie ne monte au TESTNET (fausse monnaie) QUE si elle est paper-POSITIVE **et** ROBUSTE.
Cette porte compose les vérdicts déjà construits :
  * PnL paper > 0 et profit factor >= barre (juger à la qualité, pas au winrate) ;
  * assez de trades (un chiffre sur 5 trades ment) ;
  * survit à la porte de survie H1 (OOS + régime + liquidité réduite + coûts réalistes) ;
  * parité live<->backtest OK (F28).

Un SEUL échec -> RESTE_PAPER. Donnée manquante -> RESTE_PAPER (on ne promeut jamais dans le doute).
🔒 LIGNE DURE : cette porte ne renvoie JAMAIS « mainnet ». Au mieux le TESTNET. Aucun ordre réel.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math

PROMOUVOIR_TESTNET = "PROMOUVOIR_TESTNET"
RESTE_PAPER = "RESTE_PAPER"


@dataclass(frozen=True, slots=True)
class CriteresPromotion:
    min_trades: int = 30
    min_profit_factor: float = 1.3
    exige_survie: bool = True          # H1 : OOS + régime + liquidité /2 + coûts réalistes
    exige_parite: bool = True          # F28 : live == backtest (~3%)


@dataclass(frozen=True, slots=True)
class VerdictPromotion:
    decision: str                      # PROMOUVOIR_TESTNET | RESTE_PAPER (JAMAIS mainnet)
    motifs: tuple[str, ...] = field(default_factory=tuple)
    real_execution: bool = False       # invariant : cette porte ne déclenche aucun ordre réel


def decision_promotion(
    *,
    pnl_paper: float | None,
    profit_factor: float | None,
    n_trades: int | None,
    survit: bool | None,
    parite_ok: bool | None,
    candidate_id: str | None = None,
    evidence_candidate_id: str | None = None,
    validation_stage: str | None = None,
    frozen_at_ms: int | None = None,
    observed_at_ms: int | None = None,
    replay_pipeline_hash: str | None = None,
    forward_pipeline_hash: str | None = None,
    criteres: CriteresPromotion = CriteresPromotion(),
) -> VerdictPromotion:
    """Compose les critères. Tout critère non satisfait OU manquant -> RESTE_PAPER (deny-by-default)."""
    motifs: list[str] = []
    try:
        trades_value = int(n_trades) if n_trades is not None and not isinstance(n_trades, bool) else None
    except (TypeError, ValueError, OverflowError):
        trades_value = None
    try:
        pnl_value = float(pnl_paper) if pnl_paper is not None else None
    except (TypeError, ValueError, OverflowError):
        pnl_value = None
    try:
        pf_value = float(profit_factor) if profit_factor is not None else None
    except (TypeError, ValueError, OverflowError):
        pf_value = None
    criteria_valid = (
        int(criteres.min_trades) >= 1
        and math.isfinite(float(criteres.min_profit_factor))
        and float(criteres.min_profit_factor) > 0.0
    )
    if not criteria_valid or trades_value is None or trades_value < int(criteres.min_trades):
        motifs.append("PAS_ASSEZ_DE_TRADES")
    if pnl_value is None or not math.isfinite(pnl_value) or pnl_value <= 0.0:
        motifs.append("PNL_PAPER_NON_POSITIF")
    if pf_value is None or not math.isfinite(pf_value) or pf_value < float(criteres.min_profit_factor):
        motifs.append("PROFIT_FACTOR_TROP_BAS")
    if criteres.exige_survie and not bool(survit):
        motifs.append("NE_SURVIT_PAS_AUX_STRESS")
    if criteres.exige_parite and not bool(parite_ok):
        motifs.append("PARITE_LIVE_BACKTEST_KO")
    if not candidate_id or candidate_id != evidence_candidate_id:
        motifs.append("PREUVE_NON_SPECIFIQUE_AU_CANDIDAT")
    if validation_stage != "FORWARD_PAPER_POST_FREEZE":
        motifs.append("HOLDOUT_HISTORIQUE_N_EST_PAS_FORWARD_PAPER")
    if not frozen_at_ms or not observed_at_ms or int(observed_at_ms) <= int(frozen_at_ms):
        motifs.append("OBSERVATION_NON_POSTERIEURE_AU_FREEZE")
    if (
        not replay_pipeline_hash
        or not forward_pipeline_hash
        or replay_pipeline_hash != forward_pipeline_hash
    ):
        motifs.append("PARITE_MOTEUR_EVENEMENTS_NON_PROUVEE")
    decision = PROMOUVOIR_TESTNET if not motifs else RESTE_PAPER
    return VerdictPromotion(decision=decision, motifs=tuple(motifs), real_execution=False)


__all__ = ["PROMOUVOIR_TESTNET", "RESTE_PAPER", "CriteresPromotion", "VerdictPromotion",
           "decision_promotion"]
