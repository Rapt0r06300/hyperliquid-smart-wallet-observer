"""Preuve journaliere d un candidat gele : construction, LCB, moyenne de jours actifs.

EXTRAIT DE copy_vault_local_lab.py LE 21/11/2026. Ce fichier etait a 5 124 lignes pour un
plafond historique de 5 009 : je l avais moi-meme fait grossir de ~115 lignes la veille en
y ajoutant la comparaison de segments. L invariant #13 du depot refuse exactement cela, et
sa regle est d EXTRAIRE, jamais de relever le plafond -- le plafond est donc BAISSE a la
taille reelle apres extraction, ce qui rend le gain definitif.

POURQUOI CES HUIT-LA. Elles forment une seule etape du pipeline : geler un candidat et
porter la preuve journaliere qui l accompagne. _candidate batit l enregistrement ;
_daily_lcb et _daily_lcb_rank en tirent la borne inferieure de confiance ;
_train_active_day_mean la moyenne des jours actifs ; _pnl_uplift_freeze_count le nombre de
gels ; _latest_daily, _daily_du_segment et _segment_commun_le_plus_profond comparent deux
cotes sur le segment commun le plus profond (sans quoi on comparait des periodes
differentes). record_frozen_candidate, qui reste dans le module d origine, les consomme.

AUCUN CYCLE POSSIBLE : mesure avant de deplacer, ces huit fonctions ne dependent d aucun
nom interne du module d origine (la seule dependance, _segment_commun_le_plus_profond vers
_daily_du_segment, part elle aussi). La dependance ne va donc que dans un sens.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from hl_observer.backtesting.leader_quality_signal import SEUIL_LEADER_OFF_USD
from hl_observer.backtesting.train_statistics import summarize_daily_values
from hl_observer.economics.numeric import decimal_sum, decimal_value
from hl_observer.simulation.economic_freeze_registry import parameter_hash



def _candidate(
    params: dict[str, Any], bounds: Mapping[str, Any], frozen_at_ms: int,
    candidate_id: str, trial_count: int,
) -> dict[str, Any]:
    parameters = {
        "protocol": "copy_v21_entry_capacity_daily_lock_v1",
        "training_selection_eligible": True,
        "paper_read_only": True,
        "real_execution": False,
        "minimum_leader_fill_notional_usd": params["minimum_leader_fill_notional_usd"],
        "signed_depth_imbalance_minimum": params["signed_depth_imbalance_minimum"],
        "core_notional_usd": params["core_notional_usd"],
        "probe_notional_usd": params["probe_notional_usd"],
        "daily_profit_lock_usd": params["daily_profit_lock_usd"],
        "daily_loss_cap_usd": params["daily_loss_cap_usd"],
        "vol_target_move_frac": params["vol_target_move_frac"],
        "stop_loss_bps": params["stop_loss_bps"],
        "take_profit_bps": params["take_profit_bps"],
        "horizon_ms": params["horizon_ms"],
        "vault_daily_limit": params["vault_daily_limit"],
        "coin_daily_limit": params["coin_daily_limit"],
        "max_open_positions": params["max_open_positions"],
        # défaut 1_000_000 (= sans filtre) pour les candidats gelés d'AVANT cette dimension.
        "overshoot_seuil_bps": params.get("overshoot_seuil_bps", 1_000_000.0),
        # #6 — concentration cherchable. Défauts = constantes gelées (0.65/0.60/0.60) ->
        # les candidats d'AVANT cette dimension reproduisent v21 à l'identique.
        "max_coin_trade_share": params.get("max_coin_trade_share", 0.65),
        "max_vault_trade_share": params.get("max_vault_trade_share", 0.60),
        "max_top_positive_share": params.get("max_top_positive_share", 0.60),
        # #3 — levier cherchable. Défaut 1.0 (= v21 pur) pour les candidats d'AVANT ;
        # le cliquet peut prouver une stratégie au levier du moteur (10x) -> preuve = déploiement.
        "paper_leverage": params.get("paper_leverage", 1.0),
        # #5 — fenêtre causale (lag L2) cherchable. Défaut 30_000 ms (= v21 pur) ; un lag
        # plus large admet un carnet de référence plus ancien (toujours causal) quand le L2
        # frais manque -> moins de fills jetés, sans fuite look-ahead.
        "reference_lag_ms": params.get("reference_lag_ms", 30_000),
        # #10 — sélection des leaders cherchable. Défaut OFF (= copie tous les leaders, v21
        # pur) ; un seuil > OFF ne copie qu'un leader au track-record causal (closedPnl cumulé
        # <= signal) prouvé >= seuil. Signal causal, gelable.
        "leader_min_prior_closed_pnl_usd": params.get(
            "leader_min_prior_closed_pnl_usd", SEUIL_LEADER_OFF_USD
        ),
        "bonferroni_trial_count": max(1, int(trial_count)),
        "bounds": dict(bounds),
    }
    return {"freeze": {
        "schema_version": "hypersmart.economic_parameter_freeze.v1",
        "campaign_id": candidate_id,
        "family": "copy_vault",
        "frozen_at_ms": frozen_at_ms,
        "selected_before_final_evaluation": True,
        "parameters": parameters,
        "parameters_sha256": parameter_hash(parameters),
    }}

def _daily_lcb(daily_values: object, trial_count: int) -> dict[str, Any]:
    if not isinstance(daily_values, (list, tuple)):
        return summarize_daily_values((), trial_count=trial_count)
    return summarize_daily_values(daily_values, trial_count=trial_count)

def _daily_lcb_rank(summary: Mapping[str, Any]) -> dict[str, Any]:
    """Adapt the active-day score and error bound to the shared rank guard."""
    return {
        "total_lcb_usd_exact_decimal": summary.get(
            "daily_mean_lcb_usd_exact_decimal"
        ),
        "total_lcb_numeric_error_bound_usd_exact_decimal": summary.get(
            "daily_mean_lcb_numeric_error_bound_usd_exact_decimal"
        ),
    }

def _train_active_day_mean(train: object) -> Decimal | None:
    if not isinstance(train, Mapping):
        return None
    statistics = train.get("statistics")
    statistics = statistics if isinstance(statistics, Mapping) else {}
    exact_values = statistics.get("daily_net_pnl_usd_exact_decimal")
    distinct_days = statistics.get("distinct_days")
    if "daily_net_pnl_usd_exact_decimal" in statistics:
        if (
            not isinstance(exact_values, list)
            or not exact_values
            or type(distinct_days) is not int
            or distinct_days != len(exact_values)
        ):
            return None
        values = [decimal_value(value) for value in exact_values]
        if not all(value is not None for value in values):
            return None
        total = decimal_sum(values)
        if total is None:
            return None
        return total / Decimal(len(values))
    mean = train.get("active_day_mean_net_pnl_usd")
    if mean is None:
        mean = statistics.get("mean_net_pnl_usd_per_active_day")
    return decimal_value(mean)

def _pnl_uplift_freeze_count(rows: Sequence[Mapping[str, Any]]) -> int:
    return sum(
        (
            row.get("train_pnl_improved_vs_baseline") is True
            or row.get("new_train_pnl_high") is True
        )
        and isinstance(row.get("frozen_record"), Mapping)
        for row in rows
    )

def _latest_daily(source: Mapping[str, Any]) -> tuple[str | None, float | None]:
    for segment in ("forward", "oos", "validation", "train"):
        row = source.get(segment)
        if not isinstance(row, Mapping):
            continue
        measured = row.get("daily_mean_net_pnl_usd")
        if measured is not None:
            try:
                value = float(measured)
            except (TypeError, ValueError, OverflowError):
                continue
            if math.isfinite(value):
                return segment, value
    return None, None

def _daily_du_segment(source: Mapping[str, Any], segment: str) -> float | None:
    """Le PnL journalier net d un segment donne, ou None s il est absent/non fini."""
    row = source.get(segment)
    if not isinstance(row, Mapping):
        return None
    measured = row.get("daily_mean_net_pnl_usd")
    if measured is None:
        return None
    try:
        value = float(measured)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if math.isfinite(value) else None

def _segment_commun_le_plus_profond(
    baseline: Mapping[str, Any], candidat: Mapping[str, Any],
) -> tuple[str | None, float | None, float | None]:
    """Le segment le plus profond MESURE DES DEUX COTES, et ses deux chiffres.

    LE DEFAUT CORRIGE (20/11/2026). La comparaison prenait le segment le plus profond
    de CHAQUE cote, independamment : un candidat evalue jusqu au `forward` face a une
    baseline arretee a `validation` etait declare NON COMPARABLE, alors que les deux
    portaient un chiffre de `validation` parfaitement comparable. Pire, le recu
    publiait alors deux montants issus de segments DIFFERENTS. On compare desormais
    sur le plus profond segment commun -- jamais des pommes et des poires, et jamais
    un refus de comparer quand il y a de quoi comparer.
    """
    for segment in ("forward", "oos", "validation", "train"):
        valeur_baseline = _daily_du_segment(baseline, segment)
        valeur_candidat = _daily_du_segment(candidat, segment)
        if valeur_baseline is not None and valeur_candidat is not None:
            return segment, valeur_baseline, valeur_candidat
    return None, None, None
