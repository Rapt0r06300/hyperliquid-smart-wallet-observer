from __future__ import annotations

SCAN_FEATURE_WINDOWS: tuple[int, ...] = (1, 2, 3, 5, 8, 10, 13, 15, 20, 30, 45, 60)

CORE_SCAN_FEATURE_COLUMNS: tuple[str, ...] = (
    "coin",
    "schema_version",
    "feature_hash",
    "ts_ms",
    "age_ms",
    "is_fresh",
    "freshness_score",
    "mid",
    "leader_price",
    "microprice",
    "spread_bps",
    "microprice_dev_bps",
    "bid_depth_usdc",
    "ask_depth_usdc",
    "depth_total_usdc",
    "depth_imbalance",
    "vwap",
    "vwap_dev_bps",
    "cvd",
    "cvd_norm",
    "buy_vol",
    "sell_vol",
    "n_trades",
    "trade_flow_imbalance",
    "rvol",
    "leader_notional_usdc",
    "leader_score",
    "consensus_wallets",
    "quality",
    "missing_count",
    "read_only",
    "execution",
)


def window_feature_columns(windows: tuple[int, ...] = SCAN_FEATURE_WINDOWS) -> tuple[str, ...]:
    out: list[str] = []
    for window in windows:
        out.extend(
            (
                f"ret_{window}",
                f"vol_{window}",
                f"range_bps_{window}",
                f"lag_px_{window}",
            )
        )
    return tuple(out)


EXPECTED_SCAN_FEATURE_COLUMNS: tuple[str, ...] = CORE_SCAN_FEATURE_COLUMNS + window_feature_columns()


def missing_scan_feature_columns(row: dict[str, object]) -> tuple[str, ...]:
    return tuple(column for column in EXPECTED_SCAN_FEATURE_COLUMNS if column not in row)


def validate_scan_feature_row(row: dict[str, object]) -> tuple[bool, tuple[str, ...]]:
    missing = missing_scan_feature_columns(row)
    if missing:
        return False, missing
    if row.get("read_only") is not True:
        return False, ("READ_ONLY_FLAG_NOT_TRUE",)
    if row.get("execution") != "forbidden":
        return False, ("EXECUTION_NOT_FORBIDDEN",)
    feature_hash = row.get("feature_hash")
    if not isinstance(feature_hash, str) or not feature_hash.startswith("feat:"):
        return False, ("FEATURE_HASH_INVALID",)
    return True, ()


__all__ = [
    "CORE_SCAN_FEATURE_COLUMNS",
    "EXPECTED_SCAN_FEATURE_COLUMNS",
    "SCAN_FEATURE_WINDOWS",
    "missing_scan_feature_columns",
    "validate_scan_feature_row",
    "window_feature_columns",
]
