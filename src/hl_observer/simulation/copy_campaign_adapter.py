"""Strict Copy-Vault economic campaign adapter.

The generic campaign builder preserves legacy reporting. This adapter adds the
held-out-vault robustness proof required by the shared economic objective so a
temporal same-vault OOS cannot independently promote Copy-Vault.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from hl_observer.simulation.economic_campaigns import build_copy_campaign
from hl_observer.simulation.economic_objective import evaluate_objective


def build_strict_copy_campaign(
    report: Mapping[str, Any],
    *,
    freeze: Mapping[str, Any] | None,
    datasets: Mapping[str, Any],
) -> dict[str, Any]:
    row = build_copy_campaign(report, freeze=freeze, datasets=datasets)
    measure = report.get("mesure") if isinstance(report.get("mesure"), Mapping) else {}
    generalization = (
        measure.get("generalisation_par_vault")
        if isinstance(measure.get("generalisation_par_vault"), Mapping)
        else None
    )
    row["vault_generalization"] = (
        {
            "sample_count": generalization.get("n"),
            "net_bps": generalization.get("net_bps"),
            "vaults_held_out": list(generalization.get("vaults_held_out") or []),
            "role": "SECONDARY_ROBUSTNESS_REQUIRED_FOR_ECONOMIC_CLAIM",
        }
        if generalization is not None
        else None
    )
    # build_copy_campaign evaluated before the family-specific held-out proof was
    # attached; evaluate again against the complete strict row.
    row.update(evaluate_objective(row))
    return row


__all__ = ["build_strict_copy_campaign"]
