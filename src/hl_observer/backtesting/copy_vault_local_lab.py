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
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from hl_observer.backtesting import copy_vault_executable as cv
from hl_observer.backtesting.copy_vault_v21_frozen import (
    evaluate_frozen_v21,
    evaluate_frozen_v21_segment,
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
    cuts = [ordered[min(len(ordered) - 1, max(0, int(len(ordered) * fraction)))] for fraction in (0.5, 0.7, 0.85)]
    if not (ordered[0] < cuts[0] < cuts[1] < cuts[2] < ordered[-1]):
        return None
    return {
        "train_start_ms": ordered[0], "train_end_ms": cuts[0],
        "validation_start_ms": cuts[0] + 1, "validation_end_ms": cuts[1],
        "oos_start_ms": cuts[1] + 1, "oos_end_ms": cuts[2],
        "purge_ms": 0, "validation_empty_after_purge": False,
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
        "daily_profit_lock_usd": OBJECTIVE_USD_PER_DAY,
        "stop_loss_bps": params["stop_loss_bps"],
        "take_profit_bps": params["take_profit_bps"],
        "horizon_ms": 3_600_000,
        "vault_daily_limit": 1,
        "coin_daily_limit": 1,
        "max_open_positions": 2,
        "bonferroni_trial_count": 12,
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


def run_local_campaign(
    workspace: str | Path,
    *,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    workspace = Path(workspace)
    say = progress or (lambda _message: None)
    pipeline = _load_pipeline()
    say("Reconstruction des cycles leader OPEN/ADD/REDUCE/CLOSE")
    entries, entries_audit = pipeline.charger_entrees_alpha_notional_fixe_avec_audit(workspace)
    metaorders, meta_audit = cv.cluster_metaorders(entries)
    books, books_audit = cv.load_observed_books(workspace, coins={str(row["coin"]) for row in metaorders})
    timestamps = [int(row["signal_ts_ms"]) for row in metaorders]
    bounds = _bounds(timestamps)
    base = {
        "paper_read_only": True, "real_execution": False,
        "objective_usd_per_day": OBJECTIVE_USD_PER_DAY,
        "paper_capital_usd": PAPER_CAPITAL_USD,
        "entries": len(entries), "metaorders": len(metaorders),
        "book_rows": sum(len(rows) for rows in books.values()),
        "input_audit": {"entries": entries_audit, "metaorders": meta_audit, "books": books_audit},
    }
    if not metaorders or not books or bounds is None:
        return {**base, "status": "UNMEASURABLE", "reason": "INSUFFICIENT_TEMPORAL_REPLAY_INPUTS", "candidates_tested": 0, "freeze_created": False}
    aligned_adds = 0
    for row in metaorders:
        if str(row.get("action") or "").upper() != "ADD":
            continue
        timestamps_for_coin = [int(book["ts_ms"]) for book in books.get(str(row["coin"]), [])]
        signal_ms = int(row["signal_ts_ms"])
        index = bisect.bisect_right(timestamps_for_coin, signal_ms) - 1
        if index >= 0 and signal_ms - timestamps_for_coin[index] <= 30_000:
            aligned_adds += 1
    base["temporally_aligned_add_signals"] = aligned_adds
    if aligned_adds == 0:
        return {
            **base,
            "status": "UNMEASURABLE",
            "reason": "NO_CAUSAL_L2_AT_OR_BEFORE_SIGNAL_WITHIN_30_SECONDS",
            "candidates_tested": 0,
            "freeze_created": False,
        }
    grid = []
    for core, probe in ((100.0, 25.0), (125.0, 25.0), (150.0, 50.0)):
        for minimum in (25.0, 100.0):
            for stop, take in ((50.0, 100.0), (75.0, 150.0)):
                grid.append({
                    "core_notional_usd": core, "probe_notional_usd": probe,
                    "minimum_leader_fill_notional_usd": minimum,
                    "signed_depth_imbalance_minimum": 0.0,
                    "stop_loss_bps": stop, "take_profit_bps": take,
                })
    train_results = []
    frozen_at = max(timestamps) + 1
    for index, params in enumerate(grid, 1):
        say(f"Replay TRAIN {index}/{len(grid)} — capital exposé {params['core_notional_usd'] + params['probe_notional_usd']:.0f}/200 USD")
        freeze = _candidate(params, bounds, frozen_at, f"local-{index:02d}")
        result = evaluate_frozen_v21_segment(metaorders, books, freeze, segment="train")
        train_results.append({"candidate": freeze, "train": result})
    eligible = [row for row in train_results if row["train"].get("eligible") is True]
    if not eligible:
        no_reference_count = sum(
            int((row["train"].get("candidate_audit") or {}).get(
                "REFERENCE_DEPTH_FEATURE_UNMEASURABLE", 0
            ))
            for row in train_results
        )
        total_candidates = sum(int(row["train"].get("candidate_count") or 0) for row in train_results)
        reason = (
            "NO_CAUSAL_L2_AT_OR_BEFORE_SIGNAL_WITHIN_30_SECONDS"
            if total_candidates == 0 and no_reference_count > 0
            else "NO_TRAIN_CANDIDATE_PASSED_GATES"
        )
        return {
            **base, "status": "UNMEASURABLE" if reason.startswith("NO_CAUSAL") else "MORE_DATA",
            "reason": reason,
            "candidates_tested": len(grid), "freeze_created": False,
            "reference_depth_unmeasurable_across_trials": no_reference_count,
            "train_results": train_results,
        }
    selected = max(eligible, key=lambda row: float(row["train"].get("daily_mean_net_pnl_usd") or -1e100))
    say("Meilleur candidat TRAIN sélectionné; validation séparée en cours")
    validation = evaluate_frozen_v21_segment(metaorders, books, selected["candidate"], segment="validation")
    oos = (
        evaluate_frozen_v21_segment(metaorders, books, selected["candidate"], segment="oos")
        if validation.get("eligible") is True else None
    )
    forward = (
        evaluate_frozen_v21_segment(metaorders, books, selected["candidate"], segment="forward")
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
        "candidates_tested": len(grid),
        "selected_candidate": selected["candidate"],
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
        books, books_audit = cv.load_observed_books(
            Path(workspace), coins={str(row["coin"]) for row in metaorders}
        )
        result = evaluate_frozen_v21(
            metaorders,
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
        "schema_version": "hypersmart.copy_vault_local_improvement.v1",
        "run_id": str(run_id),
        "family": "copy_vault",
        "classification": classification,
        "comparison_segment": candidate_segment if comparable else None,
        "baseline_daily_net_usd": baseline_daily,
        "candidate_daily_net_usd": candidate_daily,
        "improvement_usd_per_day": improvement,
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
    history = load_improvement_history(root)
    if not any(str(row.get("run_id")) == str(run_id) for row in history):
        ledger = registry / "HISTORY.jsonl"
        with ledger.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    if classification == "ECONOMICALLY_PROVEN_IMPROVEMENT":
        (registry / "CURRENT_CHAMPION.json").write_text(serialized, encoding="utf-8")
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
