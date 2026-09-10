"""TRAIN-only timing search on a pinned causal Lead-Lag shock index."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from statistics import median
from typing import Any

from hl_observer.backtesting.economic_hypotheses_v3 import (
    qualify_lead_lag_queue_maker_train_only,
)
from hl_observer.backtesting.lead_lag_maker_queue_train import (
    load_train_microstructure_history,
)
from hl_observer.backtesting.lead_lag_queue_replay import replay_lead_lag_queue_maker
from hl_observer.backtesting.lead_lag_streaming_train import (
    _merge_ranges,
    load_pinned_source_manifest,
)
from hl_observer.simulation.lead_lag_measured_replay import (
    load_runtime_latency_evidence,
)

_TIMING_CACHE: dict[str, dict[str, Any]] = {}


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")


def load_pinned_shock_index(
    root: str | Path,
    index_path: str | Path,
    *,
    expected_sha256: str,
) -> dict[str, Any]:
    """Load an immutable TRAIN event index and verify its canonical hash."""

    project_root = Path(root).resolve()
    path = Path(index_path)
    if not path.is_absolute():
        path = project_root / path
    path = path.resolve()
    if not path.is_relative_to(project_root):
        raise ValueError("pinned shock index must stay inside the project root")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if hashlib.sha256(_canonical_bytes(payload)).hexdigest() != str(expected_sha256):
        raise ValueError("pinned shock index hash mismatch")
    if payload.get("paper_read_only") is not True or payload.get("real_execution") is not False:
        raise ValueError("pinned shock index safety contract mismatch")
    threshold = payload.get("threshold_bps")
    events = payload.get("events")
    if not isinstance(threshold, (int, float)) or float(threshold) <= 0:
        raise ValueError("pinned shock index threshold invalid")
    if not isinstance(events, list) or not events:
        raise ValueError("pinned shock index has no events")
    return dict(payload)


def _prepare(root: Path, context: dict[str, Any]) -> dict[str, Any]:
    split = dict(context.get("split_config") or {})
    manifest = load_pinned_source_manifest(
        root,
        str(split.get("pinned_manifest_path") or ""),
        expected_manifest_sha256=str(split.get("pinned_manifest_sha256") or ""),
    )
    index = load_pinned_shock_index(
        root,
        str(split.get("pinned_shock_index_path") or ""),
        expected_sha256=str(split.get("pinned_shock_index_sha256") or ""),
    )
    for payload in (manifest, index):
        if payload.get("data_fingerprint") != context.get("data_fingerprint"):
            raise ValueError("pinned TRAIN data fingerprint differs from experiment spec")
        if payload.get("data_cutoff_utc") != context.get("data_cutoff_utc"):
            raise ValueError("pinned TRAIN cutoff differs from experiment spec")
    train_ranges = _merge_ranges(manifest["market_windows"])
    events = list(index["events"])
    after_ms = int(split.get("microstructure_after_ms") or 35_000)
    books, public_trades, microstructure = load_train_microstructure_history(
        root,
        [int(row["trigger_ts_ms"]) for row in events],
        train_ranges=train_ranges,
        before_ms=1_000,
        after_ms=after_ms,
    )
    return {
        "manifest": manifest,
        "index": index,
        "events": events,
        "train_ranges": train_ranges,
        "microstructure_after_ms": after_ms,
        "books": books,
        "public_trades": public_trades,
        "microstructure": microstructure,
        "latency": load_runtime_latency_evidence(root),
    }


def _write_detail(
    root: Path,
    context: dict[str, Any],
    params: dict[str, int],
    payload: dict[str, Any],
) -> tuple[Path, str]:
    name = "_".join(f"{key}-{value}" for key, value in sorted(params.items()))
    target = (
        root
        / "runtime"
        / "codex_experiments"
        / str(context.get("experiment_id") or "lead-lag-maker-timing")
        / f"TIMING_REPLAY_{name}.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8"
    )
    temporary.replace(target)
    return target.resolve(), digest


def evaluate_maker_timing_grid(
    params: dict[str, Any],
    *,
    budget: float = 1.0,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Measure timing candidates from one pinned event and microstructure set."""

    del budget
    root = Path.cwd()
    experiment_context = dict(context or {})
    signature = str(experiment_context.get("signature") or "")
    if signature not in _TIMING_CACHE:
        _TIMING_CACHE[signature] = _prepare(root, experiment_context)
    cached = _TIMING_CACHE[signature]
    selected = {
        "maker_lifetime_ms": int(params.get("maker_lifetime_ms") or 0),
        "hold_ms": int(params.get("hold_ms") or 0),
        "max_book_delay_ms": int(params.get("max_book_delay_ms") or 0),
    }
    if any(value <= 0 for value in selected.values()):
        raise ValueError("maker timing parameters must be positive")
    if (
        selected["maker_lifetime_ms"]
        + selected["hold_ms"]
        + 1_000
        > int(cached["microstructure_after_ms"])
    ):
        raise ValueError("maker timing exceeds the pinned microstructure horizon")
    train_ranges = list(cached["train_ranges"])
    bounds = {
        "train": (
            min((start for start, _ in train_ranges), default=None),
            max((end for _, end in train_ranges), default=None),
        ),
        "validation": (None, None),
        "oos": (None, None),
        "forward": (None, None),
    }
    threshold = float(cached["index"]["threshold_bps"])
    replay = replay_lead_lag_queue_maker(
        {"ETH": {"TRADE": []}},
        cached["books"],
        cached["public_trades"],
        latency_evidence=cached["latency"],
        shock_threshold_bps=threshold,
        maker_lifetime_ms=selected["maker_lifetime_ms"],
        hold_ms=selected["hold_ms"],
        max_book_delay_ms=selected["max_book_delay_ms"],
        segment_bounds=bounds,
        precomputed_shocks=cached["events"],
    )
    qualification = qualify_lead_lag_queue_maker_train_only(
        {
            "maker_queue_candidates": replay["maker_queue_candidates"],
            "maker_queue_replay": replay,
        },
        minimum_abs_shock_bps=threshold,
    )
    rows = list(replay.get("maker_queue_candidates") or [])
    nets = [float(row.get("net_pnl_usd") or 0.0) for row in rows]
    notionals = [float(row.get("notional_usd") or 0.0) for row in rows]
    per_trade_bps = [
        net / notional * 10_000.0
        for net, notional in zip(nets, notionals, strict=True)
        if notional > 0
    ]
    total_notional = sum(notionals)
    total_cost = sum(
        sum(
            float(row.get(name) or 0.0)
            for name in (
                "fees_usd",
                "spread_cost_usd",
                "slippage_cost_usd",
                "latency_cost_usd",
            )
        )
        for row in rows
    )
    cumulative = peak = maximum_drawdown = 0.0
    for value in nets:
        cumulative += value
        peak = max(peak, cumulative)
        maximum_drawdown = max(maximum_drawdown, peak - cumulative)
    train_summary = dict((replay.get("segment_summaries") or {}).get("train") or {})
    raw_pf = train_summary.get("profit_factor")
    finite_pf = (
        float(raw_pf)
        if isinstance(raw_pf, (int, float)) and math.isfinite(float(raw_pf))
        else None
    )
    detail = {
        "schema_version": "hypersmart.lead_lag_maker_timing_train.v1",
        "base_sha": experiment_context.get("base_sha"),
        "data_fingerprint": experiment_context.get("data_fingerprint"),
        "data_cutoff_utc": experiment_context.get("data_cutoff_utc"),
        "threshold_bps": threshold,
        "parameters": selected,
        "replay": replay,
        "qualification": qualification,
        "microstructure": cached["microstructure"],
        "paper_read_only": True,
        "real_execution": False,
    }
    detail_path, detail_sha256 = _write_detail(
        root, experiment_context, selected, detail
    )
    eligible = qualification.get("selection_eligible") is True
    return {
        "net_median_bps": round(median(per_trade_bps), 8) if per_trade_bps else 0.0,
        "roi_immobilise_pct": round(sum(nets) / total_notional * 100.0, 8)
        if total_notional > 0
        else 0.0,
        "pf": finite_pf,
        "profit_factor_infinite": raw_pf == float("inf"),
        "drawdown_bps": round(maximum_drawdown / total_notional * 10_000.0, 8)
        if total_notional > 0
        else 0.0,
        "cout_bps": round(total_cost / total_notional * 10_000.0, 8)
        if total_notional > 0
        else 0.0,
        "regularite": sum(value > 0 for value in nets) / len(nets) if nets else 0.0,
        "candidate_verdict": "FREEZE_CANDIDATE" if eligible else "ITERATE",
        "threshold_bps": threshold,
        **selected,
        "shock_count": len(cached["events"]),
        "queue_proven_fills": int(qualification.get("queue_proven_fills") or 0),
        "train_net_pnl_usd": round(sum(nets), 8),
        "qualification_status": qualification.get("status"),
        "selection_evidence_sha256": qualification.get("selection_evidence_sha256"),
        "diagnostics": replay.get("diagnostics"),
        "source_time_filter_verified": cached["microstructure"].get(
            "source_time_filter_verified"
        ),
        "detail_artifact": str(detail_path),
        "detail_sha256": detail_sha256,
        "paper_read_only": True,
        "real_execution": False,
    }


__all__ = ["evaluate_maker_timing_grid", "load_pinned_shock_index"]
