"""Strict Copy-Vault economic campaign adapter.

The generic campaign builder preserves legacy reporting. This adapter adds the
held-out-vault robustness proof required by the shared economic objective so a
temporal same-vault OOS cannot independently promote Copy-Vault.  When the
paper OOS ledger is fully materialised (not truncated), it also partitions that
existing evidence around the immutable physical freeze: trades at/before the
boundary remain OOS and only strictly newer trades may count as FORWARD.
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


def _physical_temporal_proof(
    report: Mapping[str, Any],
    freeze: Mapping[str, Any] | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Partition an already-computed Copy paper ledger without recomputing PnL.

    ``simuler_paper`` stores at most 50 trade rows.  We therefore use those rows
    for physical OOS/FORWARD proof only when the materialised list is complete.
    Otherwise the function fails closed and returns ``(None, None)`` rather than
    pretending the visible prefix represents the whole ledger.
    """
    if not freeze:
        return None, None
    try:
        boundary = int(freeze.get("frozen_at_ms") or 0)
    except (TypeError, ValueError, OverflowError):
        return None, None
    if boundary <= 0:
        return None, None

    simulation = (
        report.get("simulation_paper_oos")
        if isinstance(report.get("simulation_paper_oos"), Mapping)
        else None
    )
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
    oos = {
        "net_pnl_usd": round(sum(trade["pnl_usd"] for trade in pre), 8),
        "sample_count": len(pre),
        "no_lookahead": True,
        "physical_pre_freeze": True,
        "frozen_at_ms": boundary,
    }
    forward = {
        "net_pnl_usd": round(sum(trade["pnl_usd"] for trade in post), 8),
        "sample_count": len(post),
        "post_freeze": bool(post),
        "first_trade_ts_ms": min((trade["ts_ms"] for trade in post), default=None),
        "frozen_at_ms": boundary,
        "source": "MATERIALISED_COPY_PAPER_LEDGER",
    }
    return oos, forward


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

    physical_oos, physical_forward = _physical_temporal_proof(report, freeze)
    if physical_oos is not None and physical_forward is not None:
        row["oos"] = physical_oos
        row["forward"] = physical_forward
        row["physical_forward_proof_complete"] = True
    else:
        row["physical_forward_proof_complete"] = False

    # build_copy_campaign evaluated before the family-specific held-out and
    # physical-forward proofs were attached; evaluate again against the complete
    # strict row.
    row.update(evaluate_objective(row))
    return row


__all__ = ["build_strict_copy_campaign"]
