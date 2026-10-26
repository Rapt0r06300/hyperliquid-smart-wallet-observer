"""Local PAPER Copy-Vault laboratory fed only by verified restored shards."""
from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
import math
import random
import statistics
import bisect
import os
import time
from datetime import UTC, datetime
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from hl_observer.backtesting import copy_vault_executable as cv
from hl_observer.backtesting.copy_vault_v21_frozen import (
    FROZEN_COPY_DELAY_MS,
    FROZEN_MAX_TARGET_LAG_MS,
    evaluate_frozen_v21,
    evaluate_frozen_v21_segment,
    evaluate_partial_fill_diagnostic,
)
from hl_observer.simulation.economic_freeze_registry import parameter_hash

OBJECTIVE_USD_PER_DAY = 5.0
PAPER_CAPITAL_USD = 200.0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _engine_sha256() -> str:
    root = Path(__file__).resolve().parents[3]
    engine_root = root / "src" / "hl_observer" / "backtesting"
    engine_files = set(engine_root.glob("*.py"))
    engine_files.update({
        root / "tools" / "pipeline_copie_reel.py",
        root / "tools" / "copy_vault_safe_bridge.py",
        root / "tools" / "alina_quant_lab_console.py",
        root / "tools" / "manifest_policy.py",
        root / "src" / "hl_observer" / "collection" / "vault_fills_backfill.py",
        root / "src" / "hl_observer" / "collection" / "userfills_live.py",
        root / "src" / "hl_observer" / "datasets" / "v2_export.py",
        root / "src" / "hl_observer" / "datasets" / "v2_pipeline.py",
    })
    digest = hashlib.sha256()
    for path in sorted(engine_files, key=lambda item: item.as_posix()):
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(_sha256(path).encode("ascii"))
            digest.update(b"\n")
    return digest.hexdigest()


def _input_sha256(workspace: Path) -> str:
    data_dir = workspace / "runtime" / "data"
    sources = (
        data_dir / "vault_fills.jsonl",
        data_dir / "vault_fills_live.jsonl",
        data_dir / "copy_vault_l2_tape.jsonl",
        workspace / "runtime" / "reports" / "datasets" / "SELECTION_PROVENANCE.json",
        workspace / "SAFE_INPUT_MANIFEST.json",
    )
    if not any(path.is_file() and not path.is_symlink() for path in sources[3:]):
        raise ValueError("SAFE_SELECTION_PROVENANCE_MISSING")
    digest = hashlib.sha256()
    for path in sources:
        name = path.relative_to(workspace).as_posix()
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        if path.is_file() and not path.is_symlink():
            digest.update(_sha256(path).encode("ascii"))
        else:
            digest.update(b"MISSING")
        digest.update(b"\n")
    return digest.hexdigest()


def _forward_only_metaorders(
    metaorders: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Only verified causal signals can enter held-out validation/OOS/forward."""
    eligible: list[dict[str, Any]] = []
    for row in metaorders:
        if row.get("causal_forward_eligible") is not True:
            continue
        source = str(row.get("signal_source") or "")
        if source == "REST_BACKFILL" and not (
            row.get("historical_bootstrap") is False
            and row.get("window_reconciliation_complete") is True
        ):
            continue
        if source not in {"LIVE_WS", "REST_BACKFILL"}:
            continue
        try:
            signal_ms = int(row.get("signal_ts_ms") or 0)
            observed_ms = int(row.get("signal_observed_at_ms") or 0)
            first_fill_ms = int(row.get("first_fill_ts_ms") or 0)
        except (TypeError, ValueError, OverflowError):
            continue
        if signal_ms > 0 and observed_ms >= signal_ms >= first_fill_ms > 0:
            eligible.append(row)
    return eligible


def _number(value: object) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non-finite number")
    return number


def _verified_assets(recovery_root: Path) -> tuple[list[tuple[Path, dict[str, Any]]], dict[str, Any]]:
    report_path = recovery_root / "RESTORE_REPORT.json"
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return [], {"reason": "RESTORE_REPORT_MISSING_OR_INVALID"}
    catalog = report.get("catalog_verification") or {}
    classification = report.get("classification") or {}
    if (
        catalog.get("profile") != "replay-ready"
        or int(catalog.get("safe_catalog_shards") or 0) <= 0
        or int(classification.get("missing_or_corrupt_rows") or 0) != 0
        or int(classification.get("quarantined_shards") or 0) != 0
    ):
        return [], {"reason": "SAFE_REPLAY_CATALOG_NOT_VALID"}
    selected: list[tuple[Path, dict[str, Any]]] = []
    rejected = 0
    for release in report.get("releases") or []:
        tag = str(release.get("tag") or "")
        if "copy-vault" not in tag.lower():
            continue
        for raw in release.get("assets") or []:
            asset = dict(raw)
            name = str(asset.get("name") or "")
            if not name.endswith(".jsonl.gz"):
                continue
            if (
                asset.get("status") != "MATERIALIZED_VERIFIED"
                or asset.get("verification_status") != "VERIFIED"
            ):
                rejected += 1
                continue
            path = recovery_root / "usable" / "shards" / tag / name
            try:
                size_ok = path.stat().st_size == int(asset["size_bytes"])
                hash_ok = _sha256(path) == str(asset["sha256"])
            except (OSError, KeyError, TypeError, ValueError):
                size_ok = hash_ok = False
            if size_ok and hash_ok:
                selected.append((path, asset))
            else:
                rejected += 1
    return selected, {
        "reason": None if selected else "NO_VERIFIED_COPY_VAULT_ASSET",
        "rejected_assets": rejected,
        "safe_catalog_shards": int(catalog.get("safe_catalog_shards") or 0),
        "source_index_sha256": catalog.get("source_index_sha256"),
    }


def _load_wrapper(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        wrapper = json.loads(next(handle))
    if wrapper.get("read_only") is not True or wrapper.get("real_execution") is not False:
        raise ValueError("unsafe wrapper")
    raw_text = str(wrapper["raw_payload"])
    if hashlib.sha256(raw_text.encode("utf-8")).hexdigest() != str(wrapper["raw_sha256"]):
        raise ValueError("raw payload hash mismatch")
    wrapper["_raw"] = json.loads(raw_text)
    return wrapper


def _fill_rows(wrapper: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = wrapper["_raw"]
    if raw.get("channel") != "userFills" or not isinstance(raw.get("data"), Mapping):
        return []
    data = raw["data"]
    vault = str(data.get("user") or wrapper.get("instrument") or "").lower()
    rows: list[dict[str, Any]] = []
    for fill in data.get("fills") or []:
        try:
            side = str(fill.get("side") or "").upper()
            if side not in {"A", "B"}:
                continue
            rows.append({
                "vault": vault,
                "ts_ms": int(fill["time"]),
                "coin": str(fill["coin"]).upper(),
                "px": _number(fill["px"]),
                "sz": _number(fill["sz"]),
                "signe": 1 if side == "B" else -1,
                "dir": str(fill.get("dir") or ""),
                "start_position": _number(fill.get("startPosition") or 0.0),
                "oid": fill.get("oid"),
                "tid": fill.get("tid"),
                "hash": fill.get("hash"),
                "closed_pnl": _number(fill.get("closedPnl") or 0.0),
                "fee": _number(fill.get("fee") or 0.0),
                "isSnapshot": bool(data.get("isSnapshot")),
                "source": "REST_BACKFILL",
                "received_at_ms": int(wrapper.get("received_ts_ms") or 0),
                "source_raw_sha256": wrapper.get("raw_sha256"),
            })
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    return rows


def _book_row(wrapper: Mapping[str, Any]) -> dict[str, Any] | None:
    raw = wrapper["_raw"]
    data = raw.get("data") if isinstance(raw.get("data"), Mapping) else {}
    levels = data.get("levels")
    if raw.get("channel") != "l2Book" or not isinstance(levels, list) or len(levels) != 2:
        return None
    try:
        bids = [[_number(level["px"]), _number(level["sz"])] for level in levels[0]][:5]
        asks = [[_number(level["px"]), _number(level["sz"])] for level in levels[1]][:5]
        if not bids or not asks:
            return None
        bids.sort(key=lambda row: row[0], reverse=True)
        asks.sort(key=lambda row: row[0])
        bid, ask = bids[0][0], asks[0][0]
        if bid <= 0 or ask <= bid:
            return None
        capacity = min(
            sum(price * size for price, size in bids),
            sum(price * size for price, size in asks),
        )
        received = int(wrapper.get("received_ts_ms") or wrapper.get("recv_wall_ts_ms") or 0)
        exchange = int(data.get("time") or wrapper.get("exchange_ts_ms") or 0)
        if received < exchange or exchange <= 0 or received - exchange > 30_000:
            return None
        return {
            "schema_version": "hypersmart.copy_vault_l2.v1",
            "coin": str(data.get("coin") or wrapper.get("instrument") or "").upper(),
            "received_at_ms": received,
            "exchange_ts_ms": exchange,
            "bid": bid,
            "ask": ask,
            "capacity_usd": capacity,
            "bids5": bids,
            "asks5": asks,
            "source": "HYPERLIQUID_L2_WS",
            "data_origin": "REAL_OBSERVED",
            "causal_observation": True,
            "source_raw_sha256": wrapper.get("raw_sha256"),
        }
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def materialize_safe_workspace(recovery_root: str | Path, workspace: str | Path) -> dict[str, Any]:
    recovery_root, workspace = Path(recovery_root), Path(workspace)
    assets, audit = _verified_assets(recovery_root)
    data_dir = workspace / "runtime" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    fills: dict[tuple[Any, ...], dict[str, Any]] = {}
    books: dict[tuple[Any, ...], dict[str, Any]] = {}
    wrapper_rejections = 0
    for path, _asset in assets:
        try:
            wrapper = _load_wrapper(path)
            if "userfills" in path.name.lower():
                for row in _fill_rows(wrapper):
                    identity = (row["vault"], row["coin"], row["ts_ms"], row.get("tid"), row.get("hash"))
                    fills[identity] = row
            elif "copy-l2" in path.name.lower():
                row = _book_row(wrapper)
                if row:
                    identity = (row["coin"], row["received_at_ms"], row["bid"], row["ask"])
                    books[identity] = row
        except (OSError, EOFError, ValueError, TypeError, json.JSONDecodeError):
            wrapper_rejections += 1
    fill_rows = sorted(fills.values(), key=lambda row: (row["ts_ms"], row["vault"], str(row.get("tid"))))
    book_rows = sorted(books.values(), key=lambda row: (row["received_at_ms"], row["coin"]))
    for name, rows in (("vault_fills.jsonl", fill_rows), ("copy_vault_l2_tape.jsonl", book_rows)):
        (data_dir / name).write_text(
            "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
    result = {
        "status": "READY" if fill_rows and book_rows else "UNMEASURABLE",
        "reason": audit.get("reason") if not assets else (
            None if fill_rows and book_rows else "FILLS_OR_L2_MISSING"
        ),
        "verified_assets": len(assets),
        "rejected_assets": audit.get("rejected_assets", 0),
        "invalid_wrappers": wrapper_rejections,
        "unique_fills": len(fill_rows),
        "unique_books": len(book_rows),
        "fill_start_ms": fill_rows[0]["ts_ms"] if fill_rows else None,
        "fill_end_ms": fill_rows[-1]["ts_ms"] if fill_rows else None,
        "book_start_ms": book_rows[0]["received_at_ms"] if book_rows else None,
        "book_end_ms": book_rows[-1]["received_at_ms"] if book_rows else None,
        "paper_read_only": True,
        "real_execution": False,
        **{key: value for key, value in audit.items() if key not in {"reason", "rejected_assets"}},
    }
    (workspace / "SAFE_INPUT_MANIFEST.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def _load_pipeline():
    root = Path(__file__).resolve().parents[3]
    path = root / "tools" / "pipeline_copie_reel.py"
    spec = importlib.util.spec_from_file_location("copy_vault_local_lab_pipeline", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("COPY_VAULT_PIPELINE_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bounds(timestamps: list[int]) -> dict[str, int | bool] | None:
    ordered = sorted(set(timestamps))
    if len(ordered) < 4:
        return None
    cuts = [ordered[min(len(ordered) - 1, max(0, int(len(ordered) * fraction)))] for fraction in (0.50, 0.75, 0.95)]
    # All candidates share one purged TRAIN window sized for the largest horizon
    # in the declared streaming search space, plus frozen entry/target latency.
    purge_ms = 120_000 + FROZEN_COPY_DELAY_MS + FROZEN_MAX_TARGET_LAG_MS
    train_end = cuts[0] - purge_ms
    validation_start = cuts[0] + purge_ms + 1
    validation_end = cuts[1] - purge_ms
    oos_start = cuts[1] + purge_ms + 1
    oos_end = cuts[2] - purge_ms
    if not (
        ordered[0] < train_end
        < validation_start < validation_end
        < oos_start < oos_end < ordered[-1]
    ):
        return None
    return {
        "train_start_ms": ordered[0], "train_end_ms": train_end,
        "validation_start_ms": validation_start, "validation_end_ms": validation_end,
        "oos_start_ms": oos_start, "oos_end_ms": oos_end,
        "purge_ms": purge_ms, "validation_empty_after_purge": False,
    }


def _candidate(params: dict[str, Any], bounds: Mapping[str, Any], frozen_at_ms: int, candidate_id: str) -> dict[str, Any]:
    parameters = {
        "protocol": "copy_v21_entry_capacity_daily_lock_v1",
        "training_selection_eligible": True,
        "paper_read_only": True,
        "real_execution": False,
        "minimum_leader_fill_notional_usd": params["minimum_leader_fill_notional_usd"],
        "signed_depth_imbalance_minimum": params["signed_depth_imbalance_minimum"],
        "core_notional_usd": params["core_notional_usd"],
        "probe_notional_usd": params["probe_notional_usd"],
        "daily_profit_lock_usd": params.get("daily_profit_lock_usd", OBJECTIVE_USD_PER_DAY),
        "stop_loss_bps": params["stop_loss_bps"],
        "take_profit_bps": params["take_profit_bps"],
        "horizon_ms": int(params.get("horizon_ms", 3_600_000)),
        "vault_daily_limit": int(params.get("vault_daily_limit", 1)),
        "coin_daily_limit": int(params.get("coin_daily_limit", 1)),
        "max_open_positions": int(params.get("max_open_positions", 2)),
        "bonferroni_trial_count": int(params.get("bonferroni_trial_count", 12)),
        "bounds": dict(bounds),
    }
    return {"freeze": {
        "schema_version": "hypersmart.economic_parameter_freeze.v1",
        "campaign_id": candidate_id,
        "family": "copy_vault",
        "frozen_at_ms": frozen_at_ms,
        "selected_before_final_evaluation": True,
        "parameters": parameters,
        "parameters_sha256": parameter_hash(parameters),
    }}


def _count_temporally_aligned_signals(
    metaorders: list[dict[str, Any]],
    books: Mapping[str, list[dict[str, Any]]],
    *,
    max_lag_ms: int = 30_000,
) -> int:
    """Count reconstructed signals with an observed causal book.

    ``cluster_metaorders`` deliberately removes the source ``action`` field.  The
    old laboratory required ``action == ADD`` here and therefore rejected every
    otherwise valid reconstructed signal.
    """
    timestamps_by_coin = {
        str(coin): sorted(int(book["ts_ms"]) for book in rows)
        for coin, rows in books.items()
    }
    aligned = 0
    for row in metaorders:
        timestamps = timestamps_by_coin.get(str(row.get("coin") or ""), [])
        signal_ms = int(row["signal_ts_ms"])
        index = bisect.bisect_right(timestamps, signal_ms) - 1
        if index >= 0 and signal_ms - timestamps[index] <= max_lag_ms:
            aligned += 1
    return aligned


def _research_grid() -> list[dict[str, Any]]:
    """Deterministic Copy-Vault search space constrained to 200 USD paper.

    The dimensions change actual replay mechanics.  Cost multipliers are not
    counted as distinct strategies here: economic costs remain conservative and
    identical across candidates.
    """
    exposures = (
        (40.0, 10.0), (60.0, 10.0), (80.0, 20.0), (100.0, 25.0),
        (120.0, 20.0), (125.0, 25.0), (150.0, 25.0), (150.0, 50.0),
    )
    minimum_notionals = (1.0, 10.0, 25.0, 50.0, 100.0)
    imbalance_thresholds = (-1.0, -0.75, -0.5, -0.25, 0.0, 0.25)
    stop_take_pairs = (
        (25.0, 50.0), (50.0, 75.0), (50.0, 100.0), (75.0, 100.0),
        (75.0, 150.0), (100.0, 150.0), (100.0, 200.0), (150.0, 300.0),
    )
    horizons = (5_000, 10_000, 15_000, 30_000, 60_000, 120_000)
    grid: list[dict[str, Any]] = []
    for core, probe in exposures:
        for minimum in minimum_notionals:
            for imbalance in imbalance_thresholds:
                for stop, take in stop_take_pairs:
                    for horizon in horizons:
                        grid.append({
                            "core_notional_usd": core,
                            "probe_notional_usd": probe,
                            "minimum_leader_fill_notional_usd": minimum,
                            "signed_depth_imbalance_minimum": imbalance,
                            "stop_loss_bps": stop,
                            "take_profit_bps": take,
                            "horizon_ms": horizon,
                        })
    return grid


def _stream_candidate(sequence_index: int) -> dict[str, Any]:
    """Map an integer cursor to a unique point in a huge, bounded parameter lattice."""
    dimensions = (181, 9_901, 2_001, 2_901, 3_901, 115_001, 57, 5, 3, 3, 46)
    space_size = math.prod(dimensions)
    # A coprime stride permutes the full mixed-radix space before any point repeats.
    stride = 104_729
    while math.gcd(stride, space_size) != 1:
        stride += 2
    packed = (int(sequence_index) * stride + 71_193) % space_size
    digits: list[int] = []
    for base in dimensions:
        packed, digit = divmod(packed, base)
        digits.append(digit)
    gross_exposure = 20.0 + digits[0]
    core_share_pct = 50 + digits[10]
    core = round(gross_exposure * core_share_pct / 100.0, 2)
    probe = round(gross_exposure - core, 2)
    stop_bps = 10.0 + digits[3] / 10.0
    take_ratio = 1.0 + digits[4] / 1_950.0
    return {
        "core_notional_usd": core,
        "probe_notional_usd": probe,
        "minimum_leader_fill_notional_usd": 1.0 + digits[1] / 100.0,
        "signed_depth_imbalance_minimum": -1.0 + digits[2] / 1_000.0,
        "stop_loss_bps": stop_bps,
        "take_profit_bps": round(stop_bps * take_ratio, 6),
        "horizon_ms": 5_000 + digits[5],
        "daily_profit_lock_usd": 1.0 + digits[6] / 4.0,
        "vault_daily_limit": 1 + digits[7],
        "coin_daily_limit": 1 + digits[8],
        "max_open_positions": 1 + digits[9],
    }


def _search_space_size() -> int:
    return math.prod((181, 9_901, 2_001, 2_901, 3_901, 115_001, 57, 5, 3, 3, 46))


def _adaptive_candidate(sequence_index: int, incumbent: Mapping[str, Any] | None) -> tuple[dict[str, Any], str]:
    """Use four global lattice points then one bounded local refinement."""
    global_params = _stream_candidate(sequence_index)
    if not incumbent or (sequence_index + 1) % 5 != 0:
        return global_params, "GLOBAL_DETERMINISTIC_LATTICE"
    incumbent_params = dict((incumbent.get("freeze") or {}).get("parameters") or {})
    if not incumbent_params:
        return global_params, "GLOBAL_DETERMINISTIC_LATTICE"
    params = {
        "minimum_leader_fill_notional_usd": float(incumbent_params["minimum_leader_fill_notional_usd"]),
        "signed_depth_imbalance_minimum": float(incumbent_params["signed_depth_imbalance_minimum"]),
        "core_notional_usd": float(incumbent_params["core_notional_usd"]),
        "probe_notional_usd": float(incumbent_params["probe_notional_usd"]),
        "daily_profit_lock_usd": float(incumbent_params["daily_profit_lock_usd"]),
        "stop_loss_bps": float(incumbent_params["stop_loss_bps"]),
        "take_profit_bps": float(incumbent_params["take_profit_bps"]),
        "horizon_ms": int(incumbent_params["horizon_ms"]),
        "vault_daily_limit": int(incumbent_params["vault_daily_limit"]),
        "coin_daily_limit": int(incumbent_params["coin_daily_limit"]),
        "max_open_positions": int(incumbent_params["max_open_positions"]),
    }
    step = (sequence_index // 5) % 6
    direction = -1 if (sequence_index // 5) % 2 else 1
    if step == 0:
        exposure = params["core_notional_usd"] + params["probe_notional_usd"]
        share = min(95.0, max(50.0, 100.0 * params["core_notional_usd"] / exposure + direction))
        params["core_notional_usd"] = round(exposure * share / 100.0, 2)
        params["probe_notional_usd"] = round(exposure - params["core_notional_usd"], 2)
    elif step == 1:
        params["minimum_leader_fill_notional_usd"] = min(100.0, max(1.0, params["minimum_leader_fill_notional_usd"] + direction))
    elif step == 2:
        params["signed_depth_imbalance_minimum"] = min(1.0, max(-1.0, params["signed_depth_imbalance_minimum"] + 0.01 * direction))
    elif step == 3:
        ratio = params["take_profit_bps"] / params["stop_loss_bps"]
        params["stop_loss_bps"] = min(300.0, max(10.0, params["stop_loss_bps"] + direction))
        params["take_profit_bps"] = round(params["stop_loss_bps"] * ratio, 6)
    elif step == 4:
        params["horizon_ms"] = min(120_000, max(5_000, params["horizon_ms"] + direction * 1_000))
    else:
        params["daily_profit_lock_usd"] = min(15.0, max(1.0, params["daily_profit_lock_usd"] + direction * 0.25))
    return params, "LOCAL_INCUMBENT_REFINEMENT"


def _train_diagnostic_summary(train: Mapping[str, Any]) -> dict[str, Any]:
    """Summarize costs, risk, coverage and observed slices without imputing data."""
    trades = [dict(row) for row in train.get("trades") or () if isinstance(row, Mapping)]
    summary = cv.summarize(trades)
    costs = {}
    for key, source in (
        ("fees_usd", "fees_usd"),
        ("spread_usd", "spread_cost_usd"),
        ("slippage_usd", "slippage_cost_usd"),
        ("latency_usd", "latency_cost_usd"),
    ):
        values = [row.get(source) for row in trades]
        try:
            numeric_values = [float(value) for value in values]
            costs[key] = (
                round(sum(numeric_values), 8)
                if trades and all(math.isfinite(value) for value in numeric_values)
                else None
            )
        except (TypeError, ValueError, OverflowError):
            costs[key] = None
    groups: dict[str, dict[str, list[dict[str, Any]]]] = {
        "vault_leader": {},
        "coin": {},
        "regime": {},
    }
    for trade in trades:
        for dimension, key in (
            ("vault_leader", "vault"),
            ("coin", "coin"),
            ("regime", "regime_id"),
        ):
            label = str(trade.get(key) or "UNLABELLED")
            groups[dimension].setdefault(label, []).append(trade)
    slices = {
        dimension: {
            label: {
                "sample_count": len(rows),
                "net_pnl_usd": round(sum(float(row["net_pnl_usd"]) for row in rows), 8),
            }
            for label, rows in sorted(values.items())
        }
        for dimension, values in groups.items()
    }
    candidate_count = int(train.get("candidate_count") or 0)
    completed = len(trades)
    return {
        "sample_count": completed,
        "candidate_count": candidate_count,
        "completed_trade_rate": completed / candidate_count if candidate_count else None,
        "replay_rejections": dict(train.get("replay_audit") or {}),
        "costs": costs,
        "max_drawdown_usd": summary.get("max_drawdown_usd"),
        "profit_factor": summary.get("profit_factor"),
        "hit_rate": summary.get("hit_rate"),
        "trade_net_stddev_usd": (
            statistics.stdev(float(row["net_pnl_usd"]) for row in trades)
            if len(trades) >= 2 and all(row.get("net_pnl_usd") is not None for row in trades)
            else None
        ),
        "active_day_net_stddev_usd": (
            statistics.stdev(float(value) for value in (train.get("statistics") or {}).get("daily_net_pnl_usd") or ())
            if len((train.get("statistics") or {}).get("daily_net_pnl_usd") or ()) >= 2
            else None
        ),
        "daily_mean_lcb_usd": (train.get("statistics") or {}).get("daily_mean_lcb_usd"),
        "daily_mean_lcb_scope": "ACTIVE_TRADE_DAYS; NOT CALENDAR_DAY_COVERAGE",
        "distinct_days": (train.get("statistics") or {}).get("distinct_days"),
        "slices": slices,
        "partial_fills": "NOT_MODELED; engine requires complete executable depth; no partial fills are fabricated",
        "paper_read_only": True,
        "real_execution": False,
    }


def _parameter_neighbor_diagnostics(
    metaorders: list[dict[str, Any]],
    books: Mapping[str, list[dict[str, Any]]],
    incumbent: Mapping[str, Any],
    bounds: Mapping[str, Any],
    *,
    frozen_at_ms: int,
    trial_count: int,
    complete_utc_day_starts_ms: Any = None,
) -> list[dict[str, Any]]:
    """Small, predeclared one-factor TRAIN sensitivity check around a new best."""
    incumbent_params = dict((incumbent.get("freeze") or {}).get("parameters") or {})
    if not incumbent_params:
        return []
    definitions = (
        ("minimum_leader_fill_notional_usd", 5.0),
        ("signed_depth_imbalance_minimum", 0.05),
        ("stop_loss_bps", 1.0),
        ("horizon_ms", 1_000),
        ("daily_profit_lock_usd", 1.0),
    )
    rows: list[dict[str, Any]] = []
    for index, (field, delta) in enumerate(definitions):
        for direction in (-1, 1):
            params = {
                "minimum_leader_fill_notional_usd": incumbent_params["minimum_leader_fill_notional_usd"],
                "signed_depth_imbalance_minimum": incumbent_params["signed_depth_imbalance_minimum"],
                "core_notional_usd": incumbent_params["core_notional_usd"],
                "probe_notional_usd": incumbent_params["probe_notional_usd"],
                "daily_profit_lock_usd": incumbent_params["daily_profit_lock_usd"],
                "stop_loss_bps": incumbent_params["stop_loss_bps"],
                "take_profit_bps": incumbent_params["take_profit_bps"],
                "horizon_ms": incumbent_params["horizon_ms"],
                "vault_daily_limit": incumbent_params["vault_daily_limit"],
                "coin_daily_limit": incumbent_params["coin_daily_limit"],
                "max_open_positions": incumbent_params["max_open_positions"],
                "bonferroni_trial_count": trial_count,
            }
            if field == "stop_loss_bps":
                ratio = float(params["take_profit_bps"]) / float(params["stop_loss_bps"])
                params[field] = min(300.0, max(10.0, float(params[field]) + direction * delta))
                params["take_profit_bps"] = round(float(params[field]) * ratio, 6)
            elif field == "horizon_ms":
                params[field] = min(120_000, max(5_000, int(params[field]) + direction * delta))
            elif field == "daily_profit_lock_usd":
                params[field] = min(15.0, max(1.0, float(params[field]) + direction * delta))
            elif field == "minimum_leader_fill_notional_usd":
                params[field] = min(100.0, max(1.0, float(params[field]) + direction * delta))
            else:
                params[field] = min(1.0, max(-1.0, float(params[field]) + direction * delta))
            freeze = _candidate(params, bounds, frozen_at_ms, f"neighbor-{trial_count}-{index}-{direction:+d}")
            result = evaluate_frozen_v21_segment(
                metaorders, books, freeze, segment="train",
                complete_utc_day_starts_ms=complete_utc_day_starts_ms,
            )
            stats = dict(result.get("statistics") or {})
            rows.append({
                "parameter": field,
                "direction": direction,
                "parameters_sha256": freeze["freeze"]["parameters_sha256"],
                "net_pnl_usd": stats.get("net_pnl_usd"),
                "sample_count": stats.get("sample_count"),
                "daily_mean_net_pnl_usd": result.get("daily_mean_net_pnl_usd"),
                "eligible": result.get("eligible") is True,
                "scope": "TRAIN_ONLY_DIAGNOSTIC_NOT_PROMOTION_EVIDENCE",
            })
    return rows


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _last_jsonl_record(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        end = handle.tell()
        if end == 0:
            return None
        handle.seek(end - 1)
        has_final_newline = handle.read(1) == b"\n"
        position = end - 1
        while position >= 0:
            handle.seek(position)
            if handle.read(1) == b"\n" and position != end - 1:
                break
            position -= 1
        start = position + 1
        handle.seek(start)
        raw = handle.read(end - start).strip()
    if not raw:
        return None
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        if has_final_newline:
            raise
        # Recover only an incomplete final append; every newline-terminated
        # receipt remains immutable and intact.
        with path.open("r+b") as handle:
            handle.truncate(start)
            handle.flush()
            os.fsync(handle.fileno())
        return _last_jsonl_record(path)
    if not has_final_newline:
        with path.open("ab") as handle:
            handle.write(b"\n")
            handle.flush()
            os.fsync(handle.fileno())
    if not isinstance(result, dict):
        raise ValueError("continuous trial journal tail is not an object")
    return result


def _continuous_campaign(
    workspace: Path,
    metaorders: list[dict[str, Any]],
    books: Mapping[str, list[dict[str, Any]]],
    bounds: Mapping[str, Any],
    timestamps: list[int],
    base: Mapping[str, Any],
    *,
    prior_trial_count: int,
    input_digest: str,
    engine_digest: str,
    progress: Callable[[str], None],
    on_trial: Callable[[Mapping[str, Any]], None] | None,
    on_improvement: Callable[[Mapping[str, Any]], None] | None,
) -> dict[str, Any]:
    engine_root = Path(__file__).resolve().parents[3]
    state_dir = engine_root / "runtime" / "codex_research" / "copy_vault_continuous" / input_digest / engine_digest
    state_path = state_dir / "STATE.json"
    journal_path = state_dir / "TRIALS.jsonl"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("input_sha256") != input_digest or state.get("engine_sha256") != engine_digest:
            raise ValueError("checkpoint binding mismatch")
    except (OSError, ValueError, TypeError):
        state = {}
    sequence_index = max(0, int(state.get("next_sequence_index") or 0))
    trials_seen = max(int(prior_trial_count), int(state.get("cumulative_trial_count") or 0))
    best_score = state.get("best_train_score")
    score_metric = str(state.get("best_train_score_metric") or "")
    best_net_total = state.get("best_train_net_total_usd")
    best_sample_count = int(state.get("best_train_sample_count") or 0)
    best_diagnostics = state.get("best_train_diagnostics")
    best_parameter_neighbors = state.get("best_parameter_neighbor_diagnostics") or []
    best_partial_fill = state.get("best_partial_fill_diagnostic")
    best_candidate = state.get("best_candidate")
    tail = _last_jsonl_record(journal_path)
    if tail is not None:
        if tail.get("input_sha256") != input_digest or tail.get("engine_sha256") != engine_digest:
            raise ValueError("continuous trial journal is bound to different data or engine")
        sequence_index = max(sequence_index, int(tail["sequence_index"]) + 1)
        trials_seen = max(trials_seen, int(tail["cumulative_trial_count"]))
        tail_score = tail.get("selection_score_value")
        if tail_score is not None and (best_score is None or float(tail_score) > float(best_score)):
            best_score = float(tail_score)
            score_metric = str(tail.get("selection_score_metric") or "")
            best_net_total = tail.get("net_train_usd")
            best_sample_count = int(tail.get("sample_count") or 0)
            best_candidate = tail.get("candidate")
            best_diagnostics = tail.get("train_diagnostics")
            best_parameter_neighbors = tail.get("parameter_neighbor_diagnostics") or []
            best_partial_fill = tail.get("partial_fill_diagnostic")
        if tail.get("is_improvement") is True and on_improvement:
            on_improvement({
                "trial": int(tail["sequence_index"]),
                "candidate": tail.get("candidate"),
                "train": {
                    "daily_mean_net_pnl_usd": tail.get("daily_mean_net_pnl_usd"),
                    "statistics": {
                        "net_pnl_usd": tail.get("net_train_usd"),
                        "sample_count": tail.get("sample_count"),
                    },
                },
                "selection_metric": tail.get("selection_score_metric"),
                "selection_score": tail.get("selection_score_value"),
                "previous_best_train_score": tail.get("previous_best_score"),
                "train_diagnostics": tail.get("train_diagnostics"),
                "parameter_neighbor_diagnostics": tail.get("parameter_neighbor_diagnostics") or [],
                "partial_fill_diagnostic": tail.get("partial_fill_diagnostic"),
                "input_sha256": input_digest,
                "engine_sha256": engine_digest,
            })
    run_start_index = sequence_index
    started = time.monotonic()
    last_dashboard = 0.0
    progress(f"Labo continu prêt — séquence reprise à {sequence_index:,}; correction statistique à {trials_seen:,} essais cumulés.")
    train_start_ms = int(bounds["train_start_ms"])
    train_end_ms = int(bounds["train_end_ms"])
    complete_days = base.get("input_audit", {}).get("complete_utc_day_starts_ms")
    has_complete_train_day = bool(
        isinstance(complete_days, (list, tuple))
        and any(
            isinstance(day, int)
            and not isinstance(day, bool)
            and train_start_ms <= day
            and day + 86_400_000 - 1 <= train_end_ms
            and day % 86_400_000 == 0
            for day in complete_days
        )
    )
    active_score_metric = (
        "daily_mean_net_pnl_usd" if has_complete_train_day else "net_pnl_usd"
    )
    try:
        while True:
            params, search_method = _adaptive_candidate(sequence_index, best_candidate)
            next_trial_count = trials_seen + 1
            params["bonferroni_trial_count"] = next_trial_count
            candidate_id = f"cv-cont-{input_digest[:8]}-{engine_digest[:8]}-{sequence_index:020d}"
            freeze = _candidate(params, bounds, max(timestamps) + 1, candidate_id)
            if on_trial:
                on_trial({
                    "phase": "TRIAL_START",
                    "sequence_index": sequence_index,
                    "candidate_id": candidate_id,
                    "candidate": freeze,
                    "cumulative_trial_count": next_trial_count,
                    "selection_score_metric": active_score_metric,
                    "input_sha256": input_digest,
                    "engine_sha256": engine_digest,
                    "paper_read_only": True,
                    "real_execution": False,
                })
            train = evaluate_frozen_v21_segment(
                metaorders, books, freeze, segment="train",
                complete_utc_day_starts_ms=complete_days,
            )
            statistics_row = train.get("statistics") or {}
            net = statistics_row.get("net_pnl_usd")
            sample_count = int(statistics_row.get("sample_count") or 0)
            daily_score = train.get("daily_mean_net_pnl_usd")
            raw_score = daily_score if active_score_metric == "daily_mean_net_pnl_usd" else net
            score = float(raw_score) if raw_score is not None and math.isfinite(float(raw_score)) else None
            is_improvement = score is not None and sample_count > 0 and (best_score is None or score > float(best_score))
            diagnostic = _train_diagnostic_summary(train)
            neighbors = (
                _parameter_neighbor_diagnostics(
                    metaorders, books, freeze, bounds,
                    frozen_at_ms=max(timestamps) + 1,
                    trial_count=next_trial_count + 10,
                    complete_utc_day_starts_ms=complete_days,
                )
                if is_improvement else []
            )
            partial_fill_diagnostic = None
            if is_improvement:
                try:
                    partial_fill_diagnostic = evaluate_partial_fill_diagnostic(
                        metaorders, books, freeze, segment="train"
                    )
                except (RuntimeError, ValueError, TypeError, KeyError) as exc:
                    partial_fill_diagnostic = {
                        "status": "UNMEASURABLE",
                        "reason": f"{type(exc).__name__}:{exc}",
                        "scope": "DIAGNOSTIC_ONLY",
                        "economic_proof": False,
                    }
            diagnostic_evaluations = len(neighbors)
            completed_trial_count = next_trial_count + diagnostic_evaluations
            row = {
                "schema_version": "hypersmart.copy_vault_continuous_trial.v1",
                "sequence_index": sequence_index,
                "cumulative_trial_count": completed_trial_count,
                "candidate_id": candidate_id,
                "parameters_sha256": freeze["freeze"]["parameters_sha256"],
                "search_method": search_method,
                "input_sha256": input_digest,
                "engine_sha256": engine_digest,
                "net_train_usd": net,
                "selection_score_metric": active_score_metric,
                "selection_score_value": score,
                "previous_best_score": best_score,
                "daily_mean_net_pnl_usd": train.get("daily_mean_net_pnl_usd"),
                "sample_count": sample_count,
                "train_diagnostics": diagnostic,
                "parameter_neighbor_diagnostics": neighbors,
                "partial_fill_diagnostic": partial_fill_diagnostic,
                "diagnostic_trials_counted": diagnostic_evaluations,
                "eligible": train.get("eligible") is True,
                "is_improvement": is_improvement,
                "reasons": train.get("reasons") or [],
                "candidate": freeze,
                "paper_read_only": True,
                "real_execution": False,
            }
            state_dir.mkdir(parents=True, exist_ok=True)
            with journal_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            trials_seen = completed_trial_count
            sequence_index += 1
            if is_improvement:
                previous_best_score = best_score
                best_score = score
                score_metric = active_score_metric
                best_net_total = net
                best_sample_count = sample_count
                best_candidate = freeze
                best_diagnostics = diagnostic
                best_parameter_neighbors = neighbors
                best_partial_fill = partial_fill_diagnostic
                if on_improvement:
                    on_improvement({
                        "trial": row["sequence_index"],
                        "candidate": freeze,
                        "train": train,
                        "selection_metric": active_score_metric,
                        "selection_score": score,
                        "previous_best_score": previous_best_score,
                        "train_diagnostics": diagnostic,
                        "parameter_neighbor_diagnostics": neighbors,
                        "partial_fill_diagnostic": partial_fill_diagnostic,
                        "input_sha256": input_digest,
                        "engine_sha256": engine_digest,
                    })
            _atomic_json(state_path, {
                "schema_version": "hypersmart.copy_vault_continuous_state.v2",
                "input_sha256": input_digest,
                "engine_sha256": engine_digest,
                "next_sequence_index": sequence_index,
                "cumulative_trial_count": trials_seen,
                "best_train_score": best_score,
                "best_train_score_metric": score_metric,
                "best_train_net_total_usd": best_net_total,
                "best_train_sample_count": best_sample_count,
                "best_train_diagnostics": best_diagnostics,
                "best_parameter_neighbor_diagnostics": best_parameter_neighbors,
                "best_partial_fill_diagnostic": best_partial_fill,
                "best_candidate": best_candidate,
                "updated_at_utc": datetime.now(UTC).isoformat(),
                "paper_read_only": True,
                "real_execution": False,
            })
            update = {
                **row,
                "is_improvement": is_improvement,
                "best_train_score": best_score,
                "best_train_score_metric": score_metric,
                "best_train_net_total_usd": best_net_total,
                "best_train_diagnostics": best_diagnostics,
                "best_parameter_neighbor_diagnostics": best_parameter_neighbors,
                "best_partial_fill_diagnostic": best_partial_fill,
                "best_train_sample_count": best_sample_count,
                "next_sequence_index": sequence_index,
                "elapsed_seconds": round(time.monotonic() - started, 1),
                "phase": "TRIAL_COMPLETE",
                "state_path": str(state_path),
                "journal_path": str(journal_path),
            }
            if on_trial:
                on_trial(update)
            if sequence_index == 1 or sequence_index % 10 == 0 or is_improvement:
                progress(
                    f"Replay TRAIN #{sequence_index:,} — {('net/jour' if active_score_metric == 'daily_mean_net_pnl_usd' else 'net total TRAIN')} "
                    f"{('non mesurable' if score is None else f'{score:+.6f} USD')} / "
                    f"{sample_count} trade(s); meilleur {('non mesurable' if best_score is None else f'{float(best_score):+.6f} ' + ('USD/jour' if score_metric == 'daily_mean_net_pnl_usd' else 'USD total TRAIN'))}"
                    + (" — NOUVEAU MEILLEUR TRAIN gelé" if is_improvement else "")
                )
            last_dashboard = time.monotonic()
    except KeyboardInterrupt:
        elapsed = round(time.monotonic() - started, 1)
        return {
            **dict(base),
            "status": "INTERRUPTED",
            "reason": "USER_CTRL_C_CHECKPOINTED",
            "continuous": True,
            "candidates_tested_this_run": sequence_index - run_start_index,
            "cumulative_trial_count": trials_seen,
            "next_sequence_index": sequence_index,
            "best_train_score": best_score,
            "best_train_score_metric": score_metric,
            "best_train_daily_usd": (
                best_score if score_metric == "daily_mean_net_pnl_usd" else None
            ),
            "best_train_net_total_usd": best_net_total,
            "best_train_sample_count": best_sample_count,
            "best_train_diagnostics": best_diagnostics,
            "parameter_neighbor_diagnostics": best_parameter_neighbors,
            "partial_fill_diagnostic": best_partial_fill,
            "selected_candidate": best_candidate,
            "freeze_created": best_candidate is not None,
            "economically_proven": False,
            "heldout_status": "PROTECTED_NOT_USED_DURING_CONTINUOUS_TUNING",
            "elapsed_seconds": elapsed,
            "state_path": str(state_path),
            "trial_journal": str(journal_path),
            "input_sha256": input_digest,
            "engine_sha256": engine_digest,
            "paper_read_only": True,
            "real_execution": False,
        }


def run_local_campaign(
    workspace: str | Path,
    *,
    progress: Callable[[str], None] | None = None,
    continuous: bool = False,
    prior_trial_count: int = 0,
    on_trial: Callable[[Mapping[str, Any]], None] | None = None,
    on_improvement: Callable[[Mapping[str, Any]], None] | None = None,
) -> dict[str, Any]:
    workspace = Path(workspace)
    say = progress or (lambda _message: None)
    pipeline = _load_pipeline()
    say("Reconstruction des cycles leader OPEN/ADD/REDUCE/CLOSE")
    entries, entries_audit = pipeline.charger_entrees_alpha_notional_fixe_avec_audit(workspace)
    metaorders, meta_audit = cv.cluster_metaorders(entries)
    forward_metaorders = _forward_only_metaorders(metaorders)
    books, books_audit = cv.load_observed_books(workspace, coins={str(row["coin"]) for row in metaorders})
    timestamps = [int(row["signal_ts_ms"]) for row in metaorders]
    bounds = _bounds(timestamps)
    input_digest = _input_sha256(workspace)
    engine_digest = _engine_sha256()
    base = {
        "paper_read_only": True, "real_execution": False,
        "objective_usd_per_day": OBJECTIVE_USD_PER_DAY,
        "paper_capital_usd": PAPER_CAPITAL_USD,
        "entries": len(entries), "metaorders": len(metaorders),
        "book_rows": sum(len(rows) for rows in books.values()),
        "input_sha256": input_digest,
        "engine_sha256": engine_digest,
        "temporal_design": {
            "policy": "CHRONOLOGICAL_TRAIN_VALIDATION_OOS_FORWARD",
            "purge_ms": int(bounds["purge_ms"]) if bounds else None,
            "bounds": dict(bounds) if bounds else None,
            "selection_uses_heldout": False,
        },
        "input_audit": {
            "entries": entries_audit,
            "metaorders": meta_audit,
            "forward_evidence_metaorders": len(forward_metaorders),
            "historical_or_nonforward_train_only_metaorders": len(metaorders) - len(forward_metaorders),
            "books": books_audit,
        },
    }
    if not metaorders or not books or bounds is None:
        return {**base, "status": "UNMEASURABLE", "reason": "INSUFFICIENT_TEMPORAL_REPLAY_INPUTS", "candidates_tested": 0, "freeze_created": False}
    aligned_adds = _count_temporally_aligned_signals(metaorders, books)
    base["temporally_aligned_add_signals"] = aligned_adds
    if aligned_adds == 0:
        return {
            **base,
            "status": "UNMEASURABLE",
            "reason": "NO_CAUSAL_L2_AT_OR_BEFORE_SIGNAL_WITHIN_30_SECONDS",
            "candidates_tested": 0,
            "freeze_created": False,
        }
    if continuous:
        return _continuous_campaign(
            workspace, metaorders, books, bounds, timestamps, base,
            prior_trial_count=prior_trial_count,
            input_digest=input_digest,
            engine_digest=engine_digest,
            progress=say,
            on_trial=on_trial,
            on_improvement=on_improvement,
        )
    grid = _research_grid()
    completed_grid_trial_count = len(grid) + int(prior_trial_count)
    for params in grid:
        params["bonferroni_trial_count"] = completed_grid_trial_count + 10
    eligible: list[dict[str, Any]] = []
    train_improvements: list[dict[str, Any]] = []
    best_observed_score = -math.inf
    no_reference_count = 0
    total_candidates = 0
    result_digest = hashlib.sha256()
    frozen_at = max(timestamps) + 1
    for index, params in enumerate(grid, 1):
        if index == 1 or index == len(grid) or index % max(1, len(grid) // 100) == 0:
            say(
                f"Replay TRAIN {index}/{len(grid)} — horizon {params['horizon_ms'] / 1000:.0f}s — "
                f"capital exposé {params['core_notional_usd'] + params['probe_notional_usd']:.0f}/200 USD"
            )
        freeze = _candidate(params, bounds, frozen_at, f"local-{index:02d}")
        result = evaluate_frozen_v21_segment(metaorders, books, freeze, segment="train")
        trial = {"candidate": freeze, "train": result}
        result_digest.update(json.dumps({
            "parameters_sha256": freeze["freeze"]["parameters_sha256"],
            "eligible": result.get("eligible"),
            "statistics": result.get("statistics"),
            "candidate_audit": result.get("candidate_audit"),
            "replay_audit": result.get("replay_audit"),
        }, sort_keys=True, separators=(",", ":")).encode("utf-8"))
        if result.get("eligible") is True:
            eligible.append(trial)
        no_reference_count += int((result.get("candidate_audit") or {}).get(
            "REFERENCE_DEPTH_FEATURE_UNMEASURABLE", 0
        ))
        total_candidates += int(result.get("candidate_count") or 0)
        statistics_row = result.get("statistics") or {}
        sample_count = int(statistics_row.get("sample_count") or 0)
        observed_net = statistics_row.get("net_pnl_usd")
        if sample_count > 0 and observed_net is not None:
            score = float(observed_net)
            if math.isfinite(score) and score > best_observed_score:
                best_observed_score = score
                train_improvements.append({
                    "trial": index,
                    "candidate": freeze,
                    "train": result,
                    "classification": "TRAIN_ONLY_EXPLORATORY_IMPROVEMENT",
                })
    if not eligible:
        reason = (
            "NO_CAUSAL_L2_AT_OR_BEFORE_SIGNAL_WITHIN_30_SECONDS"
            if total_candidates == 0 and no_reference_count > 0
            else "NO_TRAIN_CANDIDATE_PASSED_GATES"
        )
        return {
            **base, "status": "UNMEASURABLE" if reason.startswith("NO_CAUSAL") else "MORE_DATA",
            "reason": reason,
            "candidates_tested": len(grid), "freeze_created": False,
            "train_improvements": train_improvements,
            "trial_results_sha256": result_digest.hexdigest(),
            "reference_depth_unmeasurable_across_trials": no_reference_count,
        }
    selection_metric = (
        "daily_mean_net_pnl_usd"
        if any(row["train"].get("daily_mean_net_pnl_usd") is not None for row in eligible)
        else "net_pnl_usd"
    )
    selected = max(
        eligible,
        key=lambda row: float(
            row["train"].get(selection_metric)
            if row["train"].get(selection_metric) is not None else -1e100
        ),
    )
    selected["train_diagnostics"] = _train_diagnostic_summary(selected["train"])
    try:
        selected["parameter_neighbor_diagnostics"] = _parameter_neighbor_diagnostics(
            metaorders,
            books,
            selected["candidate"],
            bounds,
            frozen_at_ms=frozen_at,
            trial_count=completed_grid_trial_count + 10,
        )
    except (RuntimeError, ValueError, TypeError, KeyError) as exc:
        selected["parameter_neighbor_diagnostics"] = [{
            "status": "UNMEASURABLE", "reason": f"{type(exc).__name__}:{exc}"
        }]
    try:
        selected["partial_fill_diagnostic"] = evaluate_partial_fill_diagnostic(
            metaorders, books, selected["candidate"], segment="train"
        )
    except (RuntimeError, ValueError, TypeError, KeyError) as exc:
        selected["partial_fill_diagnostic"] = {
            "status": "UNMEASURABLE", "reason": f"{type(exc).__name__}:{exc}",
            "scope": "DIAGNOSTIC_ONLY", "economic_proof": False,
        }
    say("Meilleur candidat TRAIN sélectionné; validation séparée en cours")
    validation = evaluate_frozen_v21_segment(
        forward_metaorders, books, selected["candidate"], segment="validation"
    )
    oos = (
        evaluate_frozen_v21_segment(
            forward_metaorders, books, selected["candidate"], segment="oos"
        )
        if validation.get("eligible") is True else None
    )
    forward = (
        evaluate_frozen_v21_segment(
            forward_metaorders, books, selected["candidate"], segment="forward"
        )
        if oos and oos.get("eligible") is True else None
    )
    segments = [selected["train"], validation, oos, forward]
    proven = all(
        row and row.get("eligible") is True
        and float(row.get("daily_mean_net_pnl_usd") or -1e100) >= OBJECTIVE_USD_PER_DAY
        for row in segments
    )
    return {
        **base,
        "status": "PROVEN" if proven else "PROMISING" if validation.get("eligible") is True else "MORE_DATA",
        "reason": None if proven else "HELDOUT_OR_OBJECTIVE_GATES_NOT_ALL_PASSED",
        "candidates_tested": completed_grid_trial_count + 10,
        "train_improvements": train_improvements,
        "trial_results_sha256": result_digest.hexdigest(),
        "selected_candidate": selected["candidate"],
        "selection_score_metric": selection_metric,
        "selection_score": (
            selected["train"].get("daily_mean_net_pnl_usd")
            if selection_metric == "daily_mean_net_pnl_usd"
            else (selected["train"].get("statistics") or {}).get("net_pnl_usd")
        ),
        "train_diagnostics": selected["train_diagnostics"],
        "parameter_neighbor_diagnostics": selected["parameter_neighbor_diagnostics"],
        "partial_fill_diagnostic": selected["partial_fill_diagnostic"],
        "train": selected["train"], "validation": validation, "oos": oos, "forward": forward,
        "freeze_created": True,
        "economically_proven": proven,
    }


def evaluate_current_copy_vault(
    workspace: str | Path,
    freeze_path: str | Path,
) -> dict[str, Any]:
    """Measure the currently frozen Copy-Vault policy on the same local inputs."""
    freeze_path = Path(freeze_path)
    try:
        freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        return {
            "status": "UNMEASURABLE", "reason": f"CURRENT_FREEZE_UNAVAILABLE:{type(exc).__name__}",
            "economically_proven": False, "paper_read_only": True, "real_execution": False,
        }
    try:
        pipeline = _load_pipeline()
        entries, entries_audit = pipeline.charger_entrees_alpha_notional_fixe_avec_audit(Path(workspace))
        metaorders, metaorder_audit = cv.cluster_metaorders(entries)
        forward_metaorders = _forward_only_metaorders(metaorders)
        books, books_audit = cv.load_observed_books(
            Path(workspace), coins={str(row["coin"]) for row in metaorders}
        )
        current_bounds = _bounds([int(row["signal_ts_ms"]) for row in metaorders])
        same_window_train = None
        if current_bounds is not None:
            replay_freeze = dict(freeze)
            inner_key = "freeze" if isinstance(freeze.get("freeze"), Mapping) else None
            inner = dict(freeze.get(inner_key) if inner_key else freeze)
            current_params = dict(inner.get("parameters") or {})
            current_params["bounds"] = current_bounds
            inner["parameters"] = current_params
            inner["parameters_sha256"] = parameter_hash(current_params)
            if inner_key:
                replay_freeze[inner_key] = inner
            else:
                replay_freeze = inner
            same_window_train = evaluate_frozen_v21_segment(
                metaorders, books, replay_freeze, segment="train"
            )
        result = evaluate_frozen_v21(
            forward_metaorders,
            books,
            freeze,
            input_audit={
                "entries": entries_audit,
                "metaorders": metaorder_audit,
                "books": books_audit,
            },
        )
    except (RuntimeError, ValueError, TypeError, KeyError) as exc:
        approximation = _historical_train_proxy(freeze_path.parents[2], freeze)
        return {
            "status": "APPROXIMATE_TRAIN_PROXY" if approximation else "REJECTED",
            "reason": str(exc),
            "approximation": approximation,
            "economically_proven": False, "paper_read_only": True, "real_execution": False,
        }
    return {
        "status": "PROVEN" if result.get("economically_proven") is True else "MEASURED_NOT_PROVEN",
        "reason": result.get("objective_status"),
        "economically_proven": result.get("economically_proven") is True,
        "train": same_window_train,
        "forward_evidence_metaorders": len(forward_metaorders),
        "historical_or_nonforward_train_only_metaorders": max(
            0, len(metaorders) - len(forward_metaorders)
        ),
        "train_comparison_scope": "CURRENT_POLICY_REPLAYED_ON_IDENTICAL_SAFE_EVENTS_AND_CANDIDATE_TRAIN_BOUNDS",
        "validation": result.get("validation"),
        "oos": result.get("oos"),
        "forward": result.get("forward"),
        "parameters_sha256": result.get("parameters_sha256"),
        "paper_read_only": True,
        "real_execution": False,
    }


def _historical_train_proxy(root: Path, freeze: Mapping[str, Any]) -> dict[str, Any] | None:
    """Scale the last immutable TRAIN result to 200 USD as an explicit rough proxy."""
    relative = str(freeze.get("train_report") or "")
    path = root / relative if relative else (
        root / "runtime" / "reports" / "economic_campaigns" / "research_vnext"
        / "copy_vault_v21_entry_capacity_daily_lock_train.json"
    )
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
        selected = report["selected"]
        statistics = selected["statistics"]
        core = float(selected["core_maximum_notional_usd"])
        probe = float(selected["probe_notional_usd"])
        daily = float(selected["daily_mean_net_pnl_usd"])
        lcb = float(statistics["daily_mean_lcb_usd"])
        sample_count = int(statistics["sample_count"])
        distinct_days = int(statistics["distinct_days"])
    except (OSError, KeyError, TypeError, ValueError, OverflowError):
        return None
    exposure = core + probe
    if (
        report.get("selection_scope") != "TRAIN_ONLY_PRE_FREEZE"
        or report.get("heldout_evaluated") is not False
        or report.get("paper_read_only") is not True
        or report.get("real_execution") is not False
        or not all(math.isfinite(value) for value in (core, probe, daily, lcb))
        or exposure <= 0.0
    ):
        return None
    scale = PAPER_CAPITAL_USD / exposure
    return {
        "method": "LINEAR_SCALE_OF_LAST_V21_TRAIN_RESULT_TO_200_USD",
        "daily_net_usd": round(daily * scale, 8),
        "conservative_lcb_usd_per_day": round(lcb * scale, 8),
        "original_daily_net_usd": daily,
        "original_max_exposure_usd": exposure,
        "scale": round(scale, 10),
        "sample_count": sample_count,
        "distinct_days": distinct_days,
        "source": str(path),
        "selection_scope": "TRAIN_ONLY_APPROXIMATION_NOT_HELDOUT_PROOF",
        "economically_proven": False,
    }


def _latest_daily(source: Mapping[str, Any]) -> tuple[str | None, float | None]:
    for segment in ("forward", "oos", "validation", "train"):
        row = source.get(segment)
        if not isinstance(row, Mapping):
            continue
        measured = row.get("daily_mean_net_pnl_usd")
        if measured is not None:
            try:
                value = float(measured)
            except (TypeError, ValueError, OverflowError):
                continue
            if math.isfinite(value):
                return segment, value
    return None, None


def load_improvement_history(root: str | Path) -> list[dict[str, Any]]:
    ledger = Path(root) / "runtime" / "codex_research" / "copy_vault_improvements" / "HISTORY.jsonl"
    if not ledger.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with ledger.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def record_frozen_candidate(
    root: str | Path,
    run_id: str,
    economic_result: Mapping[str, Any],
    current_copy_vault: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Persist every selected candidate without ever overwriting an older one."""
    if economic_result.get("freeze_created") is not True:
        return None
    root = Path(root)
    registry = root / "runtime" / "codex_research" / "copy_vault_improvements"
    entries = registry / "entries"
    entries.mkdir(parents=True, exist_ok=True)
    baseline_segment, baseline_daily = _latest_daily(current_copy_vault)
    candidate_segment, candidate_daily = _latest_daily(economic_result)
    comparable = (
        baseline_daily is not None
        and candidate_daily is not None
        and baseline_segment == candidate_segment
    )
    improvement = candidate_daily - baseline_daily if comparable else None
    classification = (
        "ECONOMICALLY_PROVEN_IMPROVEMENT"
        if economic_result.get("economically_proven") is True and improvement is not None and improvement > 0
        else "CANDIDATE_FROZEN_IMPROVEMENT_MEASURED"
        if improvement is not None and improvement > 0
        else "CANDIDATE_FROZEN_NOT_COMPARABLE"
        if not comparable
        else "CANDIDATE_FROZEN_NO_IMPROVEMENT"
    )
    record = {
        "schema_version": "hypersmart.copy_vault_local_improvement.v2",
        "run_id": str(run_id),
        "family": "copy_vault",
        "classification": classification,
        "comparison_segment": candidate_segment if comparable else None,
        "baseline_daily_net_usd": baseline_daily,
        "candidate_daily_net_usd": candidate_daily,
        "improvement_usd_per_day": improvement,
        "candidate_train_net_total_usd": (economic_result.get("train") or {}).get("statistics", {}).get("net_pnl_usd") if isinstance(economic_result.get("train"), Mapping) else None,
        "candidate_train_sample_count": (economic_result.get("train") or {}).get("statistics", {}).get("sample_count") if isinstance(economic_result.get("train"), Mapping) else None,
        "baseline_train_net_total_same_window_usd": (current_copy_vault.get("train") or {}).get("statistics", {}).get("net_pnl_usd") if isinstance(current_copy_vault.get("train"), Mapping) else None,
        "train_same_window_delta_usd": (
            float((economic_result.get("train") or {}).get("statistics", {}).get("net_pnl_usd"))
            - float((current_copy_vault.get("train") or {}).get("statistics", {}).get("net_pnl_usd"))
            if isinstance(economic_result.get("train"), Mapping)
            and isinstance(current_copy_vault.get("train"), Mapping)
            and (economic_result.get("train") or {}).get("statistics", {}).get("net_pnl_usd") is not None
            and (current_copy_vault.get("train") or {}).get("statistics", {}).get("net_pnl_usd") is not None
            else None
        ),
        "selection_score_metric": economic_result.get("selection_score_metric"),
        "selection_score": economic_result.get("selection_score"),
        "previous_best_train_score": economic_result.get("previous_best_train_score"),
        "input_sha256": economic_result.get("input_sha256"),
        "engine_sha256": economic_result.get("engine_sha256"),
        "train_diagnostics": economic_result.get("train_diagnostics"),
        "parameter_neighbor_diagnostics": economic_result.get("parameter_neighbor_diagnostics") or [],
        "partial_fill_diagnostic": economic_result.get("partial_fill_diagnostic"),
        "economically_proven": economic_result.get("economically_proven") is True,
        "candidate_status": economic_result.get("status"),
        "candidate": economic_result.get("selected_candidate"),
        "paper_read_only": True,
        "real_execution": False,
    }
    target = entries / f"{run_id}.json"
    serialized = json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if target.exists():
        existing = json.loads(target.read_text(encoding="utf-8"))
        if existing != record:
            raise RuntimeError("IMMUTABLE_COPY_VAULT_CANDIDATE_CONFLICT")
    else:
        with target.open("x", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
    history = load_improvement_history(root)
    if not any(str(row.get("run_id")) == str(run_id) for row in history):
        ledger = registry / "HISTORY.jsonl"
        with ledger.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    if classification == "ECONOMICALLY_PROVEN_IMPROVEMENT":
        _atomic_json(registry / "CURRENT_CHAMPION.json", record)
    return record


def run_historical_trade_replay(
    root: str | Path,
    *,
    progress: Callable[[str], None] | None = None,
    bootstrap_samples: int = 50_000,
) -> dict[str, Any]:
    """Replay preserved executable TRAIN trades across capital and cost stresses."""
    root = Path(root)
    say = progress or (lambda _message: None)
    path = (
        root / "runtime" / "reports" / "economic_campaigns" / "research_vnext"
        / "copy_vault_v21_entry_capacity_daily_lock_train.json"
    )
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
        selected = report["selected"]
        trades = [dict(row) for row in selected["trades"]]
        exposure = float(selected["core_maximum_notional_usd"]) + float(selected["probe_notional_usd"])
    except (OSError, KeyError, TypeError, ValueError, OverflowError) as exc:
        return {
            "status": "UNAVAILABLE", "reason": f"HISTORICAL_EXECUTABLE_REPLAY_UNAVAILABLE:{type(exc).__name__}",
            "trial_count": 0, "economically_proven": False,
        }
    if (
        report.get("selection_scope") != "TRAIN_ONLY_PRE_FREEZE"
        or report.get("heldout_evaluated") is not False
        or report.get("paper_read_only") is not True
        or report.get("real_execution") is not False
        or selected.get("eligible") is not True
        or exposure <= 0.0
        or len(trades) < 4
    ):
        return {
            "status": "UNAVAILABLE", "reason": "HISTORICAL_EXECUTABLE_REPLAY_CONTRACT_INVALID",
            "trial_count": 0, "economically_proven": False,
        }
    numeric_features = {
        "spread": [float(row["regime_reference_spread_bps"]) for row in trades],
        "imbalance": [float(row["signed_reference_depth_imbalance"]) for row in trades],
        "latency": [float(row["observed_latency_ms"]) for row in trades],
    }
    numeric_features["leader_notional"] = [
        float(row["first_fill_leader_notional_usd"]) for row in trades
    ]
    numeric_features["capacity"] = [float(row["entry_capacity_usd"]) for row in trades]

    def quantile(values: list[float], fraction: float) -> float:
        ordered = sorted(values)
        return ordered[round((len(ordered) - 1) * fraction)]

    conditions: list[tuple[str, str, Callable[[Mapping[str, Any]], bool]]] = []
    feature_specs = (
        ("EXECUTION_SPREAD", "regime_reference_spread_bps", "le", "spread"),
        ("BOOK_PRESSURE", "signed_reference_depth_imbalance", "ge", "imbalance"),
        ("OBSERVATION_LATENCY", "observed_latency_ms", "le", "latency"),
        ("LEADER_CONVICTION", "first_fill_leader_notional_usd", "ge", "leader_notional"),
        ("CAPACITY_SLACK", "entry_capacity_usd", "ge", "capacity"),
    )
    for archetype, field, direction, values_key in feature_specs:
        for fraction in (0.25, 0.50, 0.75):
            threshold = quantile(numeric_features[values_key], fraction)
            if direction == "le":
                predicate = lambda row, field=field, threshold=threshold: float(row[field]) <= threshold
            else:
                predicate = lambda row, field=field, threshold=threshold: float(row[field]) >= threshold
            conditions.append((f"{archetype}_{direction.upper()}_Q{int(fraction * 100)}", archetype, predicate))

    proposed_filters: list[tuple[str, tuple[str, ...], Callable[[Mapping[str, Any]], bool]]] = [
        ("ALL_EXECUTABLE_TRADES", ("BASELINE",), lambda _row: True)
    ]
    proposed_filters.extend((name, (archetype,), predicate) for name, archetype, predicate in conditions)
    for left_index, (left_name, left_type, left) in enumerate(conditions):
        for right_name, right_type, right in conditions[left_index + 1:]:
            if left_type == right_type:
                continue
            proposed_filters.append((
                f"{left_name}__AND__{right_name}",
                (left_type, right_type),
                lambda row, left=left, right=right: left(row) and right(row),
            ))
    filters: dict[str, tuple[tuple[str, ...], Callable[[Mapping[str, Any]], bool]]] = {}
    seen_subsets: set[tuple[str, ...]] = set()
    for name, archetypes, predicate in proposed_filters:
        identity = tuple(str(row["trade_id"]) for row in trades if predicate(row))
        if not identity or identity in seen_subsets:
            continue
        seen_subsets.add(identity)
        filters[name] = (archetypes, predicate)
        if len(filters) >= 32:
            break
    all_days = sorted({int(row["exit_ts_ms"]) // 86_400_000 for row in trades})
    def evaluate(
        rows: list[dict[str, Any]], *, capital: float, fee: float, spread: float,
        latency: float, slippage: float,
    ) -> dict[str, Any]:
        scale = capital / exposure
        daily = {day: 0.0 for day in all_days}
        for row in rows:
            net = (
                float(row["gross_pnl_usd"])
                - float(row["fees_usd"]) * fee
                - float(row["spread_cost_usd"]) * spread
                - float(row["slippage_cost_usd"]) * slippage
                - float(row["latency_cost_usd"]) * latency
            ) * scale
            daily[int(row["exit_ts_ms"]) // 86_400_000] += net
        values = list(daily.values())
        mean = statistics.mean(values) if values else None
        return {
            "sample_count": len(rows), "distinct_complete_days": len(values),
            "daily_net_pnl_usd": round(mean, 8) if mean is not None else None,
            "total_net_pnl_usd": round(sum(values), 8),
            "_daily_values": values,
        }

    trials: list[dict[str, Any]] = []
    capitals = tuple(float(value) for value in range(40, 201, 20))
    multipliers = (1.0, 1.25, 1.5, 2.0)
    total = len(capitals) * len(multipliers) ** 4 * len(filters)
    progress_step = max(1, total // 20)
    for capital in capitals:
        for fee in multipliers:
            for spread in multipliers:
                for latency in multipliers:
                    for slippage in multipliers:
                        for filter_name, (archetypes, predicate) in filters.items():
                            subset = [row for row in trades if predicate(row)]
                            result = evaluate(
                                subset, capital=capital, fee=fee, spread=spread,
                                latency=latency, slippage=slippage,
                            )
                            trials.append({
                                "trial": len(trials) + 1, "filter": filter_name,
                                "mechanism_archetypes": list(archetypes),
                                "capital_usd": capital, "fee_multiplier": fee,
                                "spread_multiplier": spread, "latency_multiplier": latency,
                                "slippage_multiplier": slippage,
                                **result,
                            })
                            if len(trials) % progress_step == 0:
                                say(f"replay historique/stress {len(trials)}/{total}")
    baseline = next(
        row for row in trials
        if row["filter"] == "ALL_EXECUTABLE_TRADES"
        and row["capital_usd"] == 200.0
        and row["fee_multiplier"] == row["spread_multiplier"] == row["latency_multiplier"] == row["slippage_multiplier"] == 1.0
    )
    comparable = [
        row for row in trials
        if row["capital_usd"] == 200.0
        and row["fee_multiplier"] == row["spread_multiplier"] == row["latency_multiplier"] == row["slippage_multiplier"] == 1.0
        and int(row["sample_count"]) >= 4
    ]
    best = max(comparable, key=lambda row: float(row["daily_net_pnl_usd"] or -1e100))
    rng = random.Random(21_200_540)
    for row in (baseline, best):
        values = list(row.pop("_daily_values", []))
        if not values:
            continue
        bootstrap = sorted(
            statistics.mean(rng.choice(values) for _day in values)
            for _ in range(max(100, int(bootstrap_samples)))
        )
        row["bootstrap_p05_usd_per_day"] = round(
            bootstrap[int(len(bootstrap) * 0.05)], 8
        )
    for row in trials:
        row.pop("_daily_values", None)
    improvement = float(best["daily_net_pnl_usd"]) - float(baseline["daily_net_pnl_usd"])
    return {
        "status": "COMPLETED_EXPLORATORY",
        "reason": "TRAIN_ONLY_PRESERVED_EXECUTABLE_TRADES_NO_HELDOUT_PROOF",
        "source": str(path), "source_trade_count": len(trades),
        "source_distinct_days": len(all_days), "trial_count": len(trials),
        "unique_filter_count": len(filters),
        "mechanism_count": len(feature_specs),
        "mechanisms_with_distinct_trade_subsets": len({
            item for row in filters.values() for item in row[0] if item != "BASELINE"
        }),
        "baseline": baseline, "best_candidate": best,
        "improvement_usd_per_day": round(improvement, 8),
        "improvement_found": improvement > 0.0,
        "trials": trials,
        "economically_proven": False,
        "paper_read_only": True, "real_execution": False,
    }


__all__ = [
    "OBJECTIVE_USD_PER_DAY", "PAPER_CAPITAL_USD", "evaluate_current_copy_vault",
    "load_improvement_history", "materialize_safe_workspace", "record_frozen_candidate",
    "run_historical_trade_replay", "run_local_campaign",
]
