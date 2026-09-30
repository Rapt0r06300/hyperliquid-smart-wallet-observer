"""TRAIN-only taker timing grid on the pinned Lead-Lag shock index."""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hl_observer.backtesting.lead_lag_maker_timing_train import _prepare
from hl_observer.simulation.lead_lag_measured_replay import (
    ADMISSION_PREDECLARED_ALL_SIGNALS,
    replay_measured_lead_lag,
)

_TAKER_CACHE: dict[str, dict[str, Any]] = {}
_NOTIONAL_USD = 25.0


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")


def _write_detail(
    root: Path,
    context: Mapping[str, Any],
    params: Mapping[str, int],
    payload: Mapping[str, Any],
) -> tuple[Path, str]:
    name = "_".join(f"{key}-{value}" for key, value in sorted(params.items()))
    target = (
        root
        / "runtime"
        / "codex_experiments"
        / str(context.get("experiment_id") or "lead-lag-taker-timing")
        / f"TAKER_REPLAY_{name}.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8"
    )
    temporary.replace(target)
    return target.resolve(), digest


def _number(value: object, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return result if math.isfinite(result) else default


def evaluate_taker_timing_grid(
    params: Mapping[str, Any],
    *,
    budget: float = 1.0,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Price continuation/reversal with two causal taker fills and full costs."""

    del budget
    selected = {
        "horizon_ms": int(params.get("horizon_ms") or 0),
        "direction_multiplier": int(params.get("direction_multiplier") or 0),
        "max_book_delay_ms": int(params.get("max_book_delay_ms") or 0),
    }
    if (
        selected["horizon_ms"] <= 0
        or selected["direction_multiplier"] not in {-1, 1}
        or selected["max_book_delay_ms"] <= 0
    ):
        raise ValueError("invalid taker timing parameters")
    experiment_context = dict(context or {})
    signature = str(experiment_context.get("signature") or "")
    root = Path.cwd().resolve()
    if signature not in _TAKER_CACHE:
        _TAKER_CACHE[signature] = _prepare(root, experiment_context)
    cached = _TAKER_CACHE[signature]
    if selected["horizon_ms"] + 2 * selected["max_book_delay_ms"] > int(
        cached.get("microstructure_after_ms") or 35_000
    ):
        raise ValueError("taker timing exceeds the pinned microstructure horizon")
    shocks = {
        "ETH": [
            (
                int(event["trigger_ts_ms"]) * 1_000_000,
                float(event["direction"]),
            )
            for event in cached["events"]
        ]
    }
    replay = replay_measured_lead_lag(
        {"ETH": {"TRADE": [(0, 1.0, 1.0), (1, 1.0, 1.0)]}},
        cached["books"],
        shock_threshold_bps=float(cached["index"]["threshold_bps"]),
        horizon_ms=selected["horizon_ms"],
        latency_evidence=cached["latency"],
        notional_usd=_NOTIONAL_USD,
        min_history=0,
        min_expected_net_bps=0.0,
        direction_multiplier=selected["direction_multiplier"],
        admission_policy=ADMISSION_PREDECLARED_ALL_SIGNALS,
        precomputed_shocks=shocks,
        inputs_sorted=True,
        max_book_age_ms=float(selected["max_book_delay_ms"]),
        max_execution_observation_delay_ms=float(selected["max_book_delay_ms"]),
        min_episodes=1,
    )
    raw = dict(replay.get("raw_observation_diagnostics") or {})
    segments = dict(replay.get("segments") or {})
    net = _number(raw.get("net_pnl_usd_if_all_executable_taken"))
    placebo_net = _number(replay.get("placebo_net"))
    fills = int(raw.get("full_fill_observations") or 0)
    segment_nets = [
        _number((segments.get(label) or {}).get("net"))
        for label in ("IS", "OOS", "FORWARD")
    ]
    segment_drawdowns = [
        _number((segments.get(label) or {}).get("max_drawdown_usd"))
        for label in ("IS", "OOS", "FORWARD")
    ]
    first_trigger = raw.get("first_trigger_ts_ms")
    last_trigger = raw.get("last_trigger_ts_ms")
    observed_span_days = (
        (float(last_trigger) - float(first_trigger)) / 86_400_000.0
        if isinstance(first_trigger, (int, float))
        and isinstance(last_trigger, (int, float))
        and float(last_trigger) >= float(first_trigger)
        else None
    )
    placebo_beaten = fills > 0 and net > placebo_net + 1e-12
    positive_diagnostic = net > 0.0 and placebo_beaten
    verdict = "ITERATE" if positive_diagnostic else "REJECT"
    reasons = (
        ["positive TRAIN taker diagnostic; independent promotion gates still required"]
        if positive_diagnostic
        else ["taker timing has no positive net edge over the direction-flip placebo"]
    )
    detail = {
        "schema_version": "hypersmart.lead_lag_taker_timing_train.v1",
        "base_sha": experiment_context.get("base_sha"),
        "data_fingerprint": experiment_context.get("data_fingerprint"),
        "data_cutoff_utc": experiment_context.get("data_cutoff_utc"),
        "parameters": selected,
        "threshold_bps": cached["index"]["threshold_bps"],
        "replay": replay,
        "microstructure": cached.get("microstructure"),
        "paper_read_only": True,
        "real_execution": False,
    }
    detail_path, detail_sha256 = _write_detail(
        root, experiment_context, selected, detail
    )
    total_notional = fills * _NOTIONAL_USD
    total_cost = sum(
        _number(raw.get(key))
        for key in (
            "fees_usd_if_all_executable_taken",
            "spread_cost_usd_if_all_executable_taken",
            "slippage_cost_usd_if_all_executable_taken",
            "latency_cost_usd_if_all_executable_taken",
        )
    )
    return {
        "net_median_bps": _number(raw.get("median_net_bps")),
        "roi_immobilise_pct": round(net / total_notional * 100.0, 8)
        if total_notional > 0
        else 0.0,
        "pf": raw.get("profit_factor"),
        "drawdown_bps": round(sum(segment_drawdowns) / total_notional * 10_000.0, 8)
        if total_notional > 0
        else 0.0,
        "cout_bps": round(total_cost / total_notional * 10_000.0, 8)
        if total_notional > 0
        else 0.0,
        "regularite": sum(value > 0.0 for value in segment_nets) / 3.0,
        "candidate_verdict": verdict,
        "candidate_reasons": reasons,
        "train_net_pnl_usd": round(net, 8),
        "placebo_net_pnl_usd": round(placebo_net, 8),
        "placebo_beaten": placebo_beaten,
        "full_fill_observations": fills,
        "shock_count": len(cached["events"]),
        "observed_span_days": observed_span_days,
        "diagnostic_net_per_observed_span_day": (
            round(net / observed_span_days, 8)
            if observed_span_days and observed_span_days > 0
            else None
        ),
        "segment_nets": segment_nets,
        "coverage": replay.get("coverage"),
        **selected,
        "detail_artifact": str(detail_path),
        "detail_sha256": detail_sha256,
        "paper_read_only": True,
        "real_execution": False,
    }


__all__ = ["evaluate_taker_timing_grid"]
