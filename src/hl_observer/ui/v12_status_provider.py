from __future__ import annotations

from pathlib import Path
from typing import Any

from hl_observer.features.scan_features_schema import EXPECTED_SCAN_FEATURE_COLUMNS
from hl_observer.hyperliquid.rate_weights import (
    HYPERSMART_INFO_TIME_RANGE_PAGE_LIMIT,
    HYPERSMART_WS_MAX_UNIQUE_USERS,
)
from hl_observer.storage.v12_sqlite_store import V12SQLiteStore


def build_v12_status_payload(
    *,
    engine_status: dict[str, Any],
    scanner: dict[str, Any],
) -> dict[str, Any]:
    """Dashboard-ready V12 capability payload.

    This function reports only code capabilities and real runtime counters already
    present in engine_status/scanner. If a live metric is absent it says so; it
    never fabricates health, PnL, positions or graph movement.
    """

    metrics = engine_status.get("metrics") if isinstance(engine_status.get("metrics"), dict) else {}
    source_health = metrics.get("source_health") if isinstance(metrics.get("source_health"), dict) else None
    raw_store = metrics.get("raw_store") if isinstance(metrics.get("raw_store"), dict) else None
    v12_store = _v12_store_payload(metrics.get("v12_sqlite_path"))
    return {
        "runtime": "src/hl_observer",
        "venue_default": "Hyperliquid",
        "mode": "LOCAL_PAPER_SIMULATION_ONLY",
        "data_truth": "real_or_empty",
        "no_fake_data": True,
        "external_action": False,
        "capabilities": {
            "source_registry": "available",
            "raw_store": "available",
            "info_readonly_bounded_pagination": "available",
            "ws_supervisor_provenance": "available",
            "normalized_fills_positions": "available",
            "position_lifecycle": "available",
            "leader_delta": "available",
            "scan_features_schema": "available",
            "paper_engine_wrapper": "available",
            "decision_evidence": "available",
            "decision_pipeline": "available",
            "v12_sqlite_store": "available",
        },
        "limits": {
            "info_time_range_page_limit": HYPERSMART_INFO_TIME_RANGE_PAGE_LIMIT,
            "ws_max_unique_users": HYPERSMART_WS_MAX_UNIQUE_USERS,
        },
        "feature_schema": {
            "columns": len(EXPECTED_SCAN_FEATURE_COLUMNS),
            "feature_hash_required": True,
            "read_only_required": True,
        },
        "source_health": source_health
        or {
            "available": False,
            "reason": "ENGINE_STATUS_SOURCE_HEALTH_NOT_RECORDED_YET",
        },
        "raw_store": raw_store
        or {
            "available": False,
            "reason": "ENGINE_STATUS_RAW_STORE_NOT_RECORDED_YET",
        },
        "v12_store": v12_store,
        "scanner_entry_supply": scanner.get("entry_supply"),
    }


def _v12_store_payload(path_value: Any) -> dict[str, Any]:
    if not path_value:
        return {
            "available": False,
            "reason": "ENGINE_STATUS_V12_SQLITE_PATH_NOT_RECORDED_YET",
        }
    path = Path(str(path_value))
    if not path.exists():
        return {
            "available": False,
            "reason": "V12_SQLITE_PATH_MISSING",
            "path": str(path),
        }
    try:
        store = V12SQLiteStore(path)
        return {
            "available": True,
            "path": str(path),
            "counts": {
                "wallet_scores": store.count("v12_wallet_scores"),
                "signal_clusters": store.count("v12_signal_clusters"),
                "edge_estimates": store.count("v12_edge_estimates"),
                "decision_evidence": store.count("v12_decision_evidence"),
            },
        }
    except Exception as exc:  # noqa: BLE001 - status must not break the dashboard.
        return {
            "available": False,
            "reason": "V12_SQLITE_READ_FAILED",
            "path": str(path),
            "error": type(exc).__name__,
        }


__all__ = ["build_v12_status_payload"]
