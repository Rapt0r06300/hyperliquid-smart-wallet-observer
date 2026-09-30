"""Strict Copy-Vault economic campaign adapter.

The generic campaign builder preserves reporting compatibility. This adapter
adds the physical freeze partition when a complete legacy paper ledger is
materialised, while preserving the canonical executable held-out proof.

Legacy ``generalisation_par_vault`` evidence is diagnostic only: the old path
did not prove that a vault was absent before OOS, so it can never satisfy the
shared economic objective.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from hl_observer.simulation.economic_campaigns import build_copy_campaign
from hl_observer.simulation.economic_objective import evaluate_objective


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if result == result else None


def _physical_temporal_proof(report: Mapping[str, Any], freeze: Mapping[str, Any] | None) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not freeze:
        return None, None
    try:
        boundary = int(freeze.get("frozen_at_ms") or 0)
    except (TypeError, ValueError, OverflowError):
        return None, None
    if boundary <= 0:
        return None, None
    simulation = report.get("simulation_paper_oos") if isinstance(report.get("simulation_paper_oos"), Mapping) else None
    if not simulation:
        return None, None
    trades = simulation.get("trades") if isinstance(simulation.get("trades"), list) else None
    try:
        expected = int(simulation.get("n_trades") or 0)
        identity_count = int(simulation.get("trade_ids_count") or 0)
    except (TypeError, ValueError, OverflowError):
        return None, None
    if trades is None or expected <= 0 or len(trades) != expected or identity_count != expected:
        return None, None
    materialised: list[dict[str, Any]] = []
    for trade in trades:
        if not isinstance(trade, Mapping):
            return None, None
        try:
            ts_ms = int(trade.get("ts_ms") or 0)
        except (TypeError, ValueError, OverflowError):
            return None, None
        pnl_usd = _number(trade.get("pnl_usd"))
        if ts_ms <= 0 or pnl_usd is None:
            return None, None
        materialised.append({"ts_ms": ts_ms, "pnl_usd": pnl_usd})
    pre = [trade for trade in materialised if trade["ts_ms"] <= boundary]
    post = [trade for trade in materialised if trade["ts_ms"] > boundary]
    oos = {"net_pnl_usd": round(sum(trade["pnl_usd"] for trade in pre), 8), "sample_count": len(pre),
           "no_lookahead": True, "physical_pre_freeze": True, "frozen_at_ms": boundary}
    forward = {"net_pnl_usd": round(sum(trade["pnl_usd"] for trade in post), 8), "sample_count": len(post),
               "post_freeze": bool(post), "first_trade_ts_ms": min((trade["ts_ms"] for trade in post), default=None),
               "frozen_at_ms": boundary, "source": "MATERIALISED_COPY_PAPER_LEDGER"}
    return oos, forward


def build_strict_copy_campaign(report: Mapping[str, Any], *, freeze: Mapping[str, Any] | None, datasets: Mapping[str, Any]) -> dict[str, Any]:
    row = build_copy_campaign(report, freeze=freeze, datasets=datasets)
    executable_schema = report.get("schema_version") == "hypersmart.copy_vault_executable_campaign.v1"
    if executable_schema:
        generalization = row.get("vault_generalization")
        if isinstance(generalization, Mapping):
            row["vault_generalization"] = dict(generalization)
    else:
        measure = report.get("mesure") if isinstance(report.get("mesure"), Mapping) else {}
        legacy = measure.get("generalisation_par_vault") if isinstance(measure.get("generalisation_par_vault"), Mapping) else None
        row["legacy_vault_generalization_diagnostic"] = ({
            "sample_count": legacy.get("n"), "net_bps": legacy.get("net_bps"),
            "vaults_reported_as_held_out": list(legacy.get("vaults_held_out") or []),
            "economic_claim_eligible": False,
            "reason": "LEGACY_SPLIT_DID_NOT_PROVE_VAULT_ABSENT_BEFORE_OOS",
        } if legacy is not None else None)
        row["vault_generalization"] = None
    physical_oos, physical_forward = _physical_temporal_proof(report, freeze)
    if physical_oos is not None and physical_forward is not None:
        row["oos"] = physical_oos
        row["forward"] = physical_forward
        row["physical_forward_proof_complete"] = True
    else:
        row["physical_forward_proof_complete"] = False
    row.update(evaluate_objective(row))
    return row


__all__ = ["build_strict_copy_campaign"]
