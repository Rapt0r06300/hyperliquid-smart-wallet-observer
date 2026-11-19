"""Verification du gel economique V21 : schema, contrat de securite, empreinte, bornes.

SORTIE DU MODULE GELE LE 19/11/2026, et pour une raison mesurable : `copy_vault_v21_frozen.py`
etait passe a 1 561 lignes pour un plafond historique de 1 516, apres l'ajout de la mesure de
funding. L'invariant d'architecture refuse a juste titre qu'une dette historique GRANDISSE -- la
reponse n'est pas de relever le plafond, c'est de sortir du code. Cette verification s'y pretait
mieux que tout le reste : cent vingt lignes autonomes, qui ne touchent ni au replay ni au
funding, et dont le role -- refuser un gel incoherent AVANT de l'evaluer -- se lit mieux seul.

Les constantes du protocole restent chez le moteur et sont importees DANS le corps de la
fonction : un import en tete formerait un cycle, puisque le moteur importe ce module pour
re-exporter `_verified_freeze` et ne rien casser chez ses appelants.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any


def verifier_le_gel(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Le gel, verifie et rendu tel quel -- ou une `ValueError` qui NOMME ce qui ne va pas.

    Chaque refus porte son propre code (`COPY_V21_FREEZE_HASH_MISMATCH`,
    `COPY_V21_SAFETY_CONTRACT_MISMATCH`, `COPY_V21_FREEZE_BOUNDS_INVALID`...) : un gel invalide
    doit dire LEQUEL de ses invariants est rompu, sinon on cherche a l'aveugle.
    """
    from hl_observer.backtesting.copy_vault_v21_frozen import (
        COPY_DELAY_MS,
        FROZEN_COPY_DELAY_MS,
        FROZEN_MAX_REFERENCE_LAG_MS,
        FROZEN_MAX_TARGET_LAG_MS,
        MAX_GROSS_EXPOSURE_USD,
        MAX_REFERENCE_LAG_MS,
        MAX_TARGET_LAG_MS,
        PROTOCOL,
        _strict_positive_int,
    )
    from hl_observer.simulation.economic_freeze_registry import parameter_hash

    freeze = raw.get("freeze") if isinstance(raw.get("freeze"), Mapping) else raw
    if not isinstance(freeze, Mapping):
        raise ValueError("COPY_V21_FREEZE_MISSING")
    row = dict(freeze)
    params = row.get("parameters")
    if (
        row.get("schema_version") != "hypersmart.economic_parameter_freeze.v1"
        or row.get("family") != "copy_vault"
        or row.get("selected_before_final_evaluation") is not True
        or not isinstance(params, Mapping)
    ):
        raise ValueError("COPY_V21_FREEZE_INVALID")
    parameters = dict(params)
    if parameters.get("protocol") != PROTOCOL:
        raise ValueError("COPY_V21_PROTOCOL_MISMATCH")
    if parameters.get("paper_read_only") is not True or parameters.get("real_execution") is not False:
        raise ValueError("COPY_V21_SAFETY_CONTRACT_MISMATCH")
    if parameter_hash(parameters) != str(row.get("parameters_sha256") or ""):
        raise ValueError("COPY_V21_FREEZE_HASH_MISMATCH")
    required_parameters = {
        "training_selection_eligible",
        "minimum_leader_fill_notional_usd",
        "signed_depth_imbalance_minimum",
        "core_notional_usd",
        "probe_notional_usd",
        "daily_profit_lock_usd",
        "stop_loss_bps",
        "take_profit_bps",
        "horizon_ms",
        "vault_daily_limit",
        "coin_daily_limit",
        "max_open_positions",
        "bonferroni_trial_count",
        "bounds",
    }
    if (
        not required_parameters.issubset(parameters)
        or parameters.get("training_selection_eligible") is not True
    ):
        raise ValueError("COPY_V21_FREEZE_PARAMETERS_INVALID")
    positive_parameters = (
        "minimum_leader_fill_notional_usd",
        "daily_profit_lock_usd",
        "stop_loss_bps",
        "take_profit_bps",
        "horizon_ms",
        "vault_daily_limit",
        "coin_daily_limit",
        "max_open_positions",
        "bonferroni_trial_count",
    )
    try:
        positive_values = [float(parameters[name]) for name in positive_parameters]
        signed_imbalance_minimum = float(parameters["signed_depth_imbalance_minimum"])
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("COPY_V21_FREEZE_PARAMETERS_INVALID") from exc
    if (
        any(not math.isfinite(value) or value <= 0.0 for value in positive_values)
        or not math.isfinite(signed_imbalance_minimum)
        or not -1.0 <= signed_imbalance_minimum <= 1.0
        or any(not value.is_integer() for value in positive_values[-5:])
    ):
        raise ValueError("COPY_V21_FREEZE_PARAMETERS_INVALID")
    for name in ("core_notional_usd", "probe_notional_usd"):
        try:
            notional = float(parameters[name])
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError("COPY_V21_PAPER_NOTIONAL_INVALID") from exc
        if (
            not math.isfinite(notional)
            or notional <= 0.0
            or notional > MAX_GROSS_EXPOSURE_USD
        ):
            raise ValueError("COPY_V21_PAPER_GROSS_EXPOSURE_LIMIT_EXCEEDED")
    frozen_at_ms = _strict_positive_int(row.get("frozen_at_ms"))
    if frozen_at_ms is None:
        raise ValueError("COPY_V21_FREEZE_TIMESTAMP_INVALID")
    bounds = parameters.get("bounds")
    if not isinstance(bounds, Mapping):
        raise ValueError("COPY_V21_FREEZE_BOUNDS_INVALID")
    bound_values = {
        name: _strict_positive_int(bounds.get(name))
        for name in (
            "train_start_ms", "train_end_ms", "validation_start_ms",
            "validation_end_ms", "oos_start_ms", "oos_end_ms",
        )
    }
    if any(value is None for value in bound_values.values()):
        raise ValueError("COPY_V21_FREEZE_BOUNDS_INVALID")
    train_start_ms = bound_values["train_start_ms"]
    train_end_ms = bound_values["train_end_ms"]
    validation_start_ms = bound_values["validation_start_ms"]
    validation_end_ms = bound_values["validation_end_ms"]
    oos_start_ms = bound_values["oos_start_ms"]
    oos_end_ms = bound_values["oos_end_ms"]
    if (
        min(
            train_start_ms,
            train_end_ms,
            validation_start_ms,
            validation_end_ms,
            oos_start_ms,
            oos_end_ms,
        ) <= 0
        or train_end_ms < train_start_ms
        or validation_start_ms <= train_end_ms
        or validation_end_ms < validation_start_ms
        or oos_start_ms <= validation_end_ms
        or oos_end_ms < oos_start_ms
        or frozen_at_ms <= oos_end_ms
    ):
        raise ValueError("COPY_V21_FREEZE_BOUNDS_INVALID")
    if (
        int(COPY_DELAY_MS) != FROZEN_COPY_DELAY_MS
        or int(MAX_REFERENCE_LAG_MS) != FROZEN_MAX_REFERENCE_LAG_MS
        or int(MAX_TARGET_LAG_MS) != FROZEN_MAX_TARGET_LAG_MS
    ):
        raise ValueError("COPY_V21_EXECUTION_PROTOCOL_DRIFT")
    return row


#: Ancien nom, conserve pour les appelants existants (console, tests).
_verified_freeze = verifier_le_gel
