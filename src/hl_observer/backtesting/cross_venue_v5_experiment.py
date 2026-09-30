"""Bounded experiment adapter for the existing Cross-Venue v5 TRAIN selector."""
from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hl_observer.backtesting.cross_venue_certified import (
    load_preferred_certified_atomic_series,
)
from hl_observer.backtesting.cross_venue_v5_persistence_train import (
    explore_cross_venue_v5_train,
)


def _write_detail(
    root: Path, context: Mapping[str, Any], payload: Mapping[str, Any]
) -> tuple[Path, str]:
    experiment_id = str(context.get("experiment_id") or "cross-venue-v5-refresh")
    target = (
        root
        / "runtime"
        / "codex_experiments"
        / experiment_id
        / "CROSS_VENUE_V5_TRAIN.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    temporary = target.with_suffix(".json.tmp")
    temporary.write_bytes(encoded)
    os.replace(temporary, target)
    return target.resolve(), hashlib.sha256(encoded).hexdigest()


def _number(value: object, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return result if math.isfinite(result) else default


def evaluate_cross_venue_v5_refresh(
    candidate_params: Mapping[str, Any],
    *,
    budget: float = 1.0,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Read the certified atomic tape once and retain the full TRAIN report."""

    if candidate_params.get("refresh") is not True:
        raise ValueError("refresh must be true")
    if float(budget) != 1.0:
        raise ValueError("cross-venue refresh requires the complete TRAIN budget")
    experiment_context = dict(context or {})
    root = Path.cwd().resolve()
    series, depth, source_meta = load_preferred_certified_atomic_series(root)
    report = explore_cross_venue_v5_train(
        series,
        depth,
        source_mode=str(source_meta.get("source_mode") or ""),
    )
    selected = report.get("selected")
    candidate = (
        selected
        if isinstance(selected, Mapping)
        else report.get("diagnostic_best_train_variant")
    )
    candidate = candidate if isinstance(candidate, Mapping) else {}
    statistics = candidate.get("statistics")
    statistics = statistics if isinstance(statistics, Mapping) else {}
    sample_count = int(statistics.get("sample_count") or 0)
    distinct_days = int(statistics.get("distinct_days") or 0)
    net_pnl = _number(statistics.get("net_pnl_usd"))
    profit_factor = statistics.get("profit_factor")
    finite_profit_factor = (
        float(profit_factor)
        if isinstance(profit_factor, (int, float))
        and math.isfinite(float(profit_factor))
        else None
    )
    eligible = report.get("selection_eligible") is True and isinstance(
        selected, Mapping
    )
    detail = {
        "schema_version": "hypersmart.cross_venue_v5_experiment.v1",
        "base_sha": experiment_context.get("base_sha"),
        "data_fingerprint": experiment_context.get("data_fingerprint"),
        "data_cutoff_utc": experiment_context.get("data_cutoff_utc"),
        "source_meta": source_meta,
        "report": report,
        "paper_read_only": True,
        "real_execution": False,
    }
    detail_path, detail_sha256 = _write_detail(root, experiment_context, detail)
    if eligible:
        verdict = "FREEZE_CANDIDATE"
        reasons = ["existing v5 TRAIN selector satisfied every promotion gate"]
    elif net_pnl > 0.0:
        verdict = "ITERATE"
        reasons = ["positive diagnostic TRAIN net but at least one promotion gate failed"]
    else:
        verdict = "REJECT"
        reasons = ["best v5 TRAIN variant is not net profitable after complete costs"]
    economic_contract = report.get("economic_contract")
    economic_contract = (
        economic_contract if isinstance(economic_contract, Mapping) else {}
    )
    contract_values = economic_contract.get("values")
    contract_values = contract_values if isinstance(contract_values, Mapping) else {}
    notional_per_trade = _number(
        contract_values.get("cross_venue.paper_notional_usd")
    )
    deployed_notional = sample_count * notional_per_trade
    drawdown_usd = _number(statistics.get("max_drawdown_usd"))
    return {
        "net_median_bps": round(net_pnl / deployed_notional * 10_000.0, 8)
        if deployed_notional > 0
        else 0.0,
        "roi_immobilise_pct": round(net_pnl / deployed_notional * 100.0, 8)
        if deployed_notional > 0
        else 0.0,
        "pf": finite_profit_factor,
        "drawdown_bps": round(drawdown_usd / deployed_notional * 10_000.0, 8)
        if deployed_notional > 0
        else 0.0,
        "cout_bps": _number(statistics.get("total_cost_bps")),
        "regularite": max(
            0.0,
            1.0 - _number(statistics.get("top_positive_trade_share"), default=1.0),
        ),
        "candidate_verdict": verdict,
        "candidate_reasons": reasons,
        "qualification_status": report.get("status"),
        "selection_eligible": eligible,
        "sample_count": sample_count,
        "distinct_days": distinct_days,
        "train_net_pnl_usd": round(net_pnl, 8),
        "total_lcb_usd": statistics.get("total_lcb_usd"),
        "top_positive_trade_share": statistics.get("top_positive_trade_share"),
        "certified_snapshots": int(source_meta.get("certified_snapshots") or 0),
        "source_mode": source_meta.get("source_mode"),
        "detail_artifact": str(detail_path),
        "detail_sha256": detail_sha256,
        "paper_read_only": True,
        "real_execution": False,
    }


__all__ = ["evaluate_cross_venue_v5_refresh"]
