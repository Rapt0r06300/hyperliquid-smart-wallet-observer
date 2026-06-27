from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from hyper_smart_observer.market_signals.market_signal_features import MarketSignalFeatures


SCAN_FEATURE_COLUMNS: tuple[str, ...] = (
    "timestamp_ms",
    "source_ts",
    "wallet",
    "symbol",
    "current_mid",
    "mid_source",
    "mid_source_endpoint",
    "all_mids_current_mid",
    "best_bid",
    "best_ask",
    "spread_bps",
    "bid_depth_usdc",
    "ask_depth_usdc",
    "microprice",
    "depth_imbalance",
    "depth_slope",
    "l2_levels_per_side",
    "l2_bid_levels_json",
    "l2_ask_levels_json",
    "volatility_context",
    "volatility_range_bps",
    "volatility_realized_bps",
    "volatility_atr_bps",
    "volatility_bucket",
    "volatility_samples",
    "volatility_data_quality",
    "volatility_source_ts",
    "liquidity_score",
    "leader_delta",
    "leader_reference_price",
    "copy_degradation_bps",
    "edge_remaining_bps",
    "data_quality",
    "source_health",
    "is_stale",
    "schema_version",
    "adapter_version",
    "feature_hash",
)


@dataclass(frozen=True)
class ScanFeaturesExportResult:
    run_id: str
    json_path: Path
    csv_path: Path
    rows: int
    columns: tuple[str, ...] = SCAN_FEATURE_COLUMNS


def write_scan_features_export(
    features: Iterable[MarketSignalFeatures],
    output_dir: Path | str,
    *,
    run_id: str,
) -> ScanFeaturesExportResult:
    safe_run_id = _safe_run_id(run_id)
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    rows = [_project_row(item.to_export_row()) for item in features]
    json_path = directory / f"scan_features_{safe_run_id}.json"
    csv_path = directory / f"scan_features_{safe_run_id}.csv"

    json_path.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SCAN_FEATURE_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    return ScanFeaturesExportResult(
        run_id=safe_run_id,
        json_path=json_path,
        csv_path=csv_path,
        rows=len(rows),
    )


def _project_row(row: dict[str, object]) -> dict[str, object]:
    return {column: row.get(column) for column in SCAN_FEATURE_COLUMNS}


def _safe_run_id(run_id: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9_.-]+", "_", run_id).strip("._")
    return sanitized or "run"
