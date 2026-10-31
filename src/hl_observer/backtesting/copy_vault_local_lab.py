"""Local PAPER Copy-Vault laboratory fed only by verified restored shards."""
from __future__ import annotations

import bisect
import gzip
import hashlib
import importlib.util
import json
import math
import os
import random
import statistics
from collections import Counter
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from statistics import NormalDist
from typing import Any

from hl_observer.alerts.durability import SingleWriterFileLock, WriterBusy
from hl_observer.backtesting import copy_vault_executable as cv
from hl_observer.backtesting.copy_vault_v21_frozen import (
    evaluate_frozen_v21,
    evaluate_frozen_v21_segment,
)
from hl_observer.simulation.economic_freeze_registry import parameter_hash
from tools.copy_vault_continuity import load_release_history_audits

OBJECTIVE_USD_PER_DAY = 5.0
PAPER_CAPITAL_USD = 200.0
_SAFE_AUDIT_CACHE_SCHEMA = "hypersmart.copy_vault_local_safe_hash_cache.v1"
_SAFE_PNL_FAMILIES = {
    "copy_vault_fills", "copy_vault_l2", "copy_vault_snapshot",
}
_SAFE_REPLAY_SUPPORT_FAMILIES = {"copy_vault_funding_rates"}
_SAFE_MARKET_CONTEXT_FAMILIES = {
    "copy_vault_bbo", "copy_vault_trades",
    "copy_vault_active_asset_ctx", "copy_vault_instrument_metadata",
}
_SAFE_CONTEXT_FAMILIES = {
    "copy_vault_positions", "copy_vault_selection",
    "copy_vault_user_funding", "copy_vault_ledger",
} | _SAFE_MARKET_CONTEXT_FAMILIES
_SAFE_FAMILIES = _SAFE_PNL_FAMILIES | _SAFE_REPLAY_SUPPORT_FAMILIES | _SAFE_CONTEXT_FAMILIES
_SAFE_EXTERNAL_MARKET_VENUES = frozenset({
    "hyperliquid", "binance", "bybit", "okx", "gate", "bitget",
})
_SAFE_EXTERNAL_MARKET_FAMILIES = frozenset({
    "activeAssetCtx", "agg_trades", "bbo", "capacity_tape", "clock_sync", "funding",
    "funding_settlement", "index_price", "instrument_metadata", "l2Book",
    "liquidations", "mark_price", "native_market", "open_interest", "ticker",
    "trades",
})
_CONTEXT_SOURCE_BY_FAMILY = {
    "copy_vault_positions": "hyperliquid_public_info",
    "copy_vault_selection": "hyperliquid_public_vaults",
}
_CANONICAL_REPOSITORY = "Rapt0r06300/hyperliquid-smart-wallet-observer"
_MATERIALIZED_TAPE_NAMES = (
    "vault_fills.jsonl", "vault_snapshots.jsonl", "copy_vault_l2_tape.jsonl",
    "copy_vault_context.jsonl", "copy_vault_l2_unexecutable.jsonl",
    "copy_vault_unclassified_fills.jsonl", "copy_vault_funding_rates.jsonl",
    "copy_vault_accounting_context.jsonl",
    "copy_vault_market_context.jsonl",
    "external_venue_safe_inventory.jsonl",
)
_MINIMUM_SIGNAL_UTC_DAYS = 6
_HALTON_BASES = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31)
_PARAMETER_DOMAINS: tuple[tuple[str, tuple[Any, ...]], ...] = (
    ("core_notional_usd", tuple(float(value) for value in range(20, 191, 5))),
    ("probe_notional_usd", tuple(float(value) for value in range(5, 101, 5))),
    ("minimum_leader_fill_notional_usd", tuple(float(value) for value in range(5, 201, 5))),
    ("signed_depth_imbalance_minimum", tuple(round(-0.5 + i * 0.025, 3) for i in range(41))),
    ("stop_loss_bps", tuple(float(value) for value in range(20, 501, 20))),
    ("take_profit_bps", tuple(float(value) for value in range(20, 1001, 20))),
    ("daily_profit_lock_usd", (1.0, 2.0, 3.0, 5.0, 7.5, 10.0, 15.0, 20.0)),
    ("horizon_ms", (300_000, 600_000, 900_000, 1_800_000, 3_600_000, 7_200_000, 14_400_000)),
    ("vault_daily_limit", (1, 2, 3, 4, 5)),
    ("coin_daily_limit", (1, 2, 3, 4, 5)),
    ("max_open_positions", (1, 2, 3, 4)),
)


def _windows_io_path(path: Path) -> Path:
    """Add the Win32 extended-length prefix when a local path nears MAX_PATH."""
    path = Path(path)
    if os.name != "nt":
        return path
    absolute = str(path.absolute())
    if absolute.startswith("\\\\?\\") or len(absolute) < 240:
        return path
    if absolute.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + absolute[2:])
    return Path("\\\\?\\" + absolute)


def _sha256(
    path: Path,
    progress: Callable[[int, int], None] | None = None,
) -> str:
    path = _windows_io_path(path)
    digest = hashlib.sha256()
    total = 0
    size = path.stat().st_size
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            total += len(chunk)
            if progress is not None:
                progress(total, size)
    return digest.hexdigest()


def _number(value: object) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non-finite number")
    return number


def _copy_vault_catalog_audit(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Expose SAFE Copy-Vault catalog families omitted from execution replay.

    Position and selection rows are receive-time HTTP snapshots. They remain
    visible in the report, but are not silently presented as per-fill economic
    inputs or as historical PnL evidence.
    """
    safe_counts = Counter(
        str(row.get("family") or "")
        for row in rows
        if str(row.get("family") or "").startswith("copy_vault_")
        and row.get("quality_status") == "SAFE"
    )
    unused = {
        family: count
        for family, count in sorted(safe_counts.items())
        if family not in _SAFE_PNL_FAMILIES
    }
    reasons = {
        family: (
            "RECEIVE_TIME_HTTP_SNAPSHOT_NOT_PER_FILL_PNL_INPUT"
            if family in {"copy_vault_positions", "copy_vault_selection"}
            else "LEADER_FUNDING_IS_CONTEXT_NOT_SCALED_FOLLOWER_PNL"
            if family == "copy_vault_user_funding"
            else "LEDGER_CASHFLOW_IS_CONTEXT_NOT_TRADING_PNL"
            if family == "copy_vault_ledger"
            else "FUNDING_RATE_COLLECTED_BUT_FOLLOWER_PAYMENT_STILL_UNPRICED"
            if family == "copy_vault_funding_rates"
            else "UNSUPPORTED_COPY_VAULT_FAMILY_NOT_REPLAYED"
        )
        for family in unused
    }
    return {
        "copy_vault_safe_catalog_shards": sum(safe_counts.values()),
        "copy_vault_safe_catalog_by_family": dict(sorted(safe_counts.items())),
        "safe_copy_vault_shards_not_used_for_pnl": sum(unused.values()),
        "safe_copy_vault_shards_not_used_for_pnl_by_family": unused,
        "safe_copy_vault_shards_not_used_for_pnl_reason_by_family": reasons,
    }


def _copy_vault_auxiliary_inventory(
    rows: list[Mapping[str, Any]], recovery_root: Path,
) -> dict[str, dict[str, int]]:
    """Count receive-time SAFE context files without claiming their hashes."""
    counts: dict[str, Counter[str]] = {}
    recovery = Path(recovery_root)
    usable_root = recovery / "usable" / "shards"
    for row in rows:
        family = str(row.get("family") or "")
        if (
            not family.startswith("copy_vault_")
            or family in _SAFE_PNL_FAMILIES
            or row.get("quality_status") != "SAFE"
        ):
            continue
        family_counts = counts.setdefault(family, Counter())
        family_counts["catalogue_shards"] += 1
        tag = str(row.get("release_tag") or "")
        asset_name = str(row.get("release_asset") or "")
        if (
            not tag or PurePosixPath(tag).name != tag or tag in {".", ".."}
            or "\\" in tag or ":" in tag
            or not asset_name.endswith(".jsonl.gz")
            or PurePosixPath(asset_name).name != asset_name
            or "\\" in asset_name or ":" in asset_name
        ):
            family_counts["local_files_unsafe"] += 1
            continue
        path = usable_root / tag / asset_name
        io_path = _windows_io_path(path)
        if any(part.is_symlink() for part in (
            _windows_io_path(recovery / "usable"),
            _windows_io_path(usable_root),
            _windows_io_path(usable_root / tag),
            io_path,
        )):
            family_counts["local_files_unsafe"] += 1
            continue
        try:
            if io_path.is_file() and path.resolve().is_relative_to(usable_root.resolve()):
                family_counts["local_files_present_unverified"] += 1
            else:
                family_counts["local_files_missing"] += 1
        except OSError:
            family_counts["local_files_unsafe"] += 1
    return {
        family: {
            "catalogue_shards": values["catalogue_shards"],
            "local_files_present_unverified": values["local_files_present_unverified"],
            "local_files_missing": values["local_files_missing"],
            "local_files_unsafe": values["local_files_unsafe"],
        }
        for family, values in sorted(counts.items())
    }


def _safe_relative_parts(
    value: object, *, expected_prefixes: tuple[tuple[str, ...], ...],
) -> tuple[str, ...]:
    raw = str(value or "")
    parsed = PurePosixPath(raw)
    parts = parsed.parts
    if (
        not parts or not any(parts[:len(prefix)] == prefix for prefix in expected_prefixes)
        or any(part in {"", ".", ".."} or "\\" in part or ":" in part for part in parts)
    ):
        raise ValueError("unsafe catalog-relative path")
    return parts


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    if path.is_symlink() or temporary.is_symlink():
        raise OSError("unsafe symlinked JSON output")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _record_external_market_catalog_row(
    inventory: dict[tuple[str, str], dict[str, Any]], row: Mapping[str, Any],
) -> None:
    """Aggregate bounded index metadata; never load external venue payloads."""
    venue = str(row.get("venue") or "").strip().lower()
    family = str(row.get("family") or "")
    if venue not in _SAFE_EXTERNAL_MARKET_VENUES or family not in _SAFE_EXTERNAL_MARKET_FAMILIES:
        return
    stats = inventory.setdefault((venue, family), {
        "catalog_rows": 0, "safe_catalog_shards": 0,
        "replay_compatible_safe_catalog_shards": 0,
        "safe_catalog_bytes": 0, "safe_catalog_bytes_exact": True,
        "event_count": 0, "event_count_exact": True,
        "trade_count": 0, "trade_count_exact": True,
        "unique_trade_count": 0, "unique_trade_count_exact": True,
        "start_ts_ms": None, "end_ts_ms": None,
    })
    stats["catalog_rows"] += 1
    if row.get("quality_status") != "SAFE":
        return
    stats["safe_catalog_shards"] += 1
    if row.get("replay_compatible") is True and row.get("validation_allowed") is not False:
        stats["replay_compatible_safe_catalog_shards"] += 1
    size = row.get("bytes")
    if type(size) is int and size >= 0:
        stats["safe_catalog_bytes"] += size
    else:
        stats["safe_catalog_bytes_exact"] = False
    event_count = row.get("event_count", row.get("record_count"))
    if type(event_count) is int and event_count >= 0:
        stats["event_count"] += event_count
    else:
        stats["event_count_exact"] = False
    for field, exact_field in (
        ("trade_count", "trade_count_exact"),
        ("unique_trade_count", "unique_trade_count_exact"),
    ):
        value = row.get(field)
        exact = row.get(exact_field) is True and type(value) is int and value >= 0
        stats[exact_field] = bool(stats[exact_field] and exact)
        if exact:
            stats[field] += value
    for field, reducer in (("start_ts_ms", min), ("end_ts_ms", max)):
        value = row.get(field)
        if type(value) is int and value > 0:
            prior = stats[field]
            stats[field] = value if prior is None else reducer(prior, value)


def _external_market_catalog_rows(
    inventory: Mapping[tuple[str, str], Mapping[str, Any]], *,
    source_recovery_root: str | None = None,
    active_data_index: str | None = None,
    catalog_sha256: str | None = None,
) -> list[dict[str, Any]]:
    """Return small catalog references, explicitly not replay observations."""
    rows: list[dict[str, Any]] = []
    for (venue, family), stats in sorted(inventory.items()):
        rows.append({
            "schema_version": "hypersmart.external_venue_safe_catalog_inventory.v1",
            "record_type": "SAFE_CATALOG_INVENTORY_REFERENCE",
            "venue": venue, "family": family,
            "catalog_rows": stats.get("catalog_rows", 0),
            "safe_catalog_shards": stats.get("safe_catalog_shards", 0),
            "replay_compatible_safe_catalog_shards": stats.get(
                "replay_compatible_safe_catalog_shards", 0,
            ),
            "safe_catalog_bytes": (
                stats.get("safe_catalog_bytes")
                if stats.get("safe_catalog_bytes_exact") is True else None
            ),
            "safe_catalog_bytes_exact": stats.get("safe_catalog_bytes_exact") is True,
            "event_count": (
                stats.get("event_count") if stats.get("event_count_exact") is True else None
            ),
            "event_count_exact": stats.get("event_count_exact") is True,
            "trade_count": (
                stats.get("trade_count") if stats.get("trade_count_exact") is True else None
            ),
            "trade_count_exact": stats.get("trade_count_exact") is True,
            "unique_trade_count": (
                stats.get("unique_trade_count")
                if stats.get("unique_trade_count_exact") is True else None
            ),
            "unique_trade_count_exact": stats.get("unique_trade_count_exact") is True,
            "start_ts_ms": stats.get("start_ts_ms"),
            "end_ts_ms": stats.get("end_ts_ms"),
            "source_recovery_root": source_recovery_root,
            "active_data_index": active_data_index,
            "catalog_sha256": catalog_sha256,
            "catalog_safe_declaration_only": True,
            "local_payload_verified": False,
            "loaded_payload_rows": 0,
            "replay_eligible": False,
            "pnl_eligible": False,
            "forward_evidence_allowed": False,
            "strategy_execution_allowed": False,
            "replay_status": "NOT_REPLAYED_BY_COPY_VAULT_ENGINE",
        })
    return rows


def _verify_materialized_tapes(
    workspace: Path,
    manifest: Mapping[str, Any],
) -> str | None:
    tape_manifest = manifest.get("materialized_tapes")
    if not isinstance(tape_manifest, Mapping):
        return "MATERIALIZED_TAPE_MANIFEST_MISSING"
    data_dir = workspace / "runtime" / "data"
    if any(part.is_symlink() for part in (workspace, workspace / "runtime", data_dir)):
        return "MATERIALIZED_TAPE_PATH_SYMLINKED"
    for name in _MATERIALIZED_TAPE_NAMES:
        evidence = tape_manifest.get(name)
        if not isinstance(evidence, Mapping):
            return f"MATERIALIZED_TAPE_IDENTITY_MISSING:{name}"
        expected_bytes = evidence.get("bytes")
        expected_sha = str(evidence.get("sha256") or "").lower()
        path = data_dir / name
        if (
            type(expected_bytes) is not int or expected_bytes < 0
            or len(expected_sha) != 64
            or any(char not in "0123456789abcdef" for char in expected_sha)
            or path.is_symlink() or not path.is_file()
        ):
            return f"MATERIALIZED_TAPE_IDENTITY_INVALID:{name}"
        try:
            if path.stat().st_size != expected_bytes or _sha256(path) != expected_sha:
                return f"MATERIALIZED_TAPE_SIZE_OR_SHA256_MISMATCH:{name}"
        except OSError:
            return f"MATERIALIZED_TAPE_UNREADABLE:{name}"
    return None


def _verified_assets(
    recovery_root: Path,
    *,
    progress: Callable[[str], None] | None = None,
) -> tuple[list[tuple[Path, dict[str, Any]]], dict[str, Any]]:
    """Verify the local Copy-Vault SAFE slice against today's canonical index.

    This is deliberately a local integrity audit, not a replacement AlinaSync
    restore receipt. PARTIAL rows and other families never enter the workspace.
    Existing payloads are reused; no remote inventory or download is attempted.
    """
    root = Path(recovery_root).resolve().parents[2]
    catalog_path = root / "catalog" / "DATA_INDEX.json"
    if catalog_path.is_symlink() or not catalog_path.is_file():
        return [], {"status": "UNMEASURABLE", "reason": "ACTIVE_DATA_INDEX_MISSING"}
    try:
        if progress is not None:
            progress("Lecture du DATA_INDEX actif · vérification SHA-256 du catalogue")
        catalog_sha = _sha256(
            catalog_path,
            progress=(
                lambda done, total: progress(
                    f"SHA-256 DATA_INDEX · {done / 1024**2:,.0f}/{total / 1024**2:,.0f} MiB"
                )
            ) if progress is not None else None,
        )
        from tools.partitioned_data_index import select_index_rows

        if progress is not None:
            progress("Lecture bornée du DATA_INDEX actif, une partition à la fois")
        external_catalog_inventory: dict[tuple[str, str], dict[str, Any]] = {}

        def keep_row(row: Mapping[str, Any]) -> bool:
            if str(row.get("family") or "").startswith("copy_vault_"):
                return True
            _record_external_market_catalog_row(external_catalog_inventory, row)
            return False

        index, all_rows = select_index_rows(
            catalog_path,
            keep_row,
            progress_callback=(
                lambda done, total: progress(
                    f"DATA_INDEX vérifié · partition {done:,}/{total:,}"
                )
            ) if progress is not None else None,
        )
        if progress is not None:
            progress("Relecture SHA-256 du DATA_INDEX · contrôle de cohérence pendant l'audit")
        if _sha256(
            catalog_path,
            progress=(
                lambda done, total: progress(
                    f"Relecture DATA_INDEX · {done / 1024**2:,.0f}/{total / 1024**2:,.0f} MiB"
                )
            ) if progress is not None else None,
        ) != catalog_sha:
            raise ValueError("DATA_INDEX_CHANGED_DURING_AUDIT")
        if index.get("repository") != _CANONICAL_REPOSITORY:
            raise ValueError("NON_CANONICAL_DATA_INDEX")
    except (ImportError, OSError, ValueError, KeyError, TypeError) as exc:
        return [], {
            "status": "UNMEASURABLE", "reason": f"ACTIVE_DATA_INDEX_INVALID:{type(exc).__name__}",
        }

    selected_rows = [row for row in all_rows if row.get("family") in _SAFE_FAMILIES]
    copy_vault_release_tags = sorted({
        str(row.get("release_tag"))
        for row in all_rows
        if str(row.get("family") or "").startswith("copy_vault_")
        and row.get("quality_status") == "SAFE"
        and isinstance(row.get("release_tag"), str)
    })
    safe_rows = [row for row in selected_rows if row.get("quality_status") == "SAFE"]
    core_safe_rows = [row for row in safe_rows if row.get("family") in _SAFE_FAMILIES]
    family_expected = Counter(str(row.get("family")) for row in safe_rows)
    expected_material = [
        f"{row.get('dataset_id')}\0{row.get('family')}\0{row.get('bytes')}\0{row.get('sha256')}"
        for row in sorted(core_safe_rows, key=lambda item: str(item.get("dataset_id") or ""))
    ]
    expected_digest = hashlib.sha256(
        "\n".join(expected_material).encode("utf-8")
    ).hexdigest()
    cache_path = root / "runtime" / "research_lab" / "copy_vault_safe_hash_cache.json"
    cached: dict[str, Any] = {}
    try:
        if cache_path.is_symlink():
            raise OSError("SAFE hash cache is symlinked")
        prior = json.loads(cache_path.read_text(encoding="utf-8"))
        if (
            prior.get("schema") == _SAFE_AUDIT_CACHE_SCHEMA
            and isinstance(prior.get("verified"), dict)
        ):
            # Reuse a previous hash only when the current catalog+manifest
            # still name the same SHA and the local file identity is unchanged.
            # New SAFE shards therefore do not force rehashing every old shard.
            cached = prior["verified"]
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass

    selected: list[tuple[Path, dict[str, Any]]] = []
    missing: list[str] = []
    rejected: list[dict[str, str]] = []
    cache_rows: dict[str, Any] = {}
    stat_reused = 0
    hashes_recomputed = 0
    expected_ids: set[str] = set()
    recovery = Path(recovery_root).resolve()
    ordered_safe_rows = sorted(safe_rows, key=lambda item: str(item.get("dataset_id") or ""))
    safe_context_expected = Counter(
        str(row.get("family")) for row in core_safe_rows
        if row.get("family") in _SAFE_CONTEXT_FAMILIES
    )
    auxiliary_inventory = _copy_vault_auxiliary_inventory(all_rows, recovery)
    progress_every = max(1, (len(ordered_safe_rows) + 99) // 100)
    for row_number, row in enumerate(ordered_safe_rows, 1):
        dataset_id = str(row.get("dataset_id") or "")
        if progress is not None and (
            row_number == 1
            or row_number % progress_every == 0
            or row_number == len(ordered_safe_rows)
        ):
            progress(
                f"Audit SAFE {row_number:,}/{len(ordered_safe_rows):,} · "
                f"{len(selected):,} vérifiés · dernier shard {dataset_id or 'sans identifiant'}"
            )
        if not dataset_id or dataset_id in expected_ids:
            rejected.append({"dataset_id": dataset_id, "reason": "DUPLICATE_OR_MISSING_DATASET_ID"})
            continue
        expected_ids.add(dataset_id)
        family = str(row.get("family") or "")
        sha = str(row.get("sha256") or "").lower()
        size = row.get("bytes")
        tag = str(row.get("release_tag") or "")
        asset_name = str(row.get("release_asset") or "")
        try:
            if (
                family not in _SAFE_FAMILIES
                or row.get("replay_compatible") is not True
                or row.get("validation_allowed") is False or len(sha) != 64
                or any(char not in "0123456789abcdef" for char in sha)
                or type(size) is not int or size <= 0
            ):
                raise ValueError("catalog row is not replay-admissible SAFE")
            if (
                not tag or PurePosixPath(tag).name != tag or tag in {".", ".."}
                or "\\" in tag or ":" in tag
                or not asset_name.endswith(".jsonl.gz")
                or PurePosixPath(asset_name).name != asset_name
                or "\\" in asset_name or ":" in asset_name
            ):
                raise ValueError("unsafe release asset identity")
            manifest_parts = _safe_relative_parts(
                row.get("manifest_path"),
                expected_prefixes=(
                    ("datasets", "safe"),
                    ("datasets", "sharded", "safe"),
                ),
            )
            manifest_path = root.joinpath(*manifest_parts)
            manifest_io_path = _windows_io_path(manifest_path)
            manifest_chain = [_windows_io_path(root / part) for part in manifest_parts]
            if (
                any(part.is_symlink() for part in manifest_chain)
                or not manifest_io_path.is_file()
                or not manifest_path.resolve().is_relative_to(root.resolve())
            ):
                raise ValueError("SAFE manifest missing or symlinked")
            manifest = json.loads(manifest_io_path.read_text(encoding="utf-8"))
            if (
                manifest.get("schema") != "alina.shard_manifest.v2"
                or manifest.get("quality_status") != "SAFE"
                or manifest.get("replay_compatible") is not True
                or manifest.get("asset_verified") is not True
                or manifest.get("proof_of_pnl_allowed") is not False
                or manifest.get("dataset_id") != dataset_id
                or manifest.get("family") != family
                or manifest.get("release_tag") != tag
                or manifest.get("release_asset") != asset_name
                or manifest.get("bytes") != size
                or str(manifest.get("sha256") or "").lower() != sha
            ):
                raise ValueError("SAFE manifest does not match active catalog row")
            usable_root = recovery / "usable" / "shards"
            path = usable_root / tag / asset_name
            if any(part.is_symlink() for part in (
                recovery / "usable", usable_root, usable_root / tag,
                _windows_io_path(path),
            )):
                raise ValueError("LOCAL_SAFE_SHARD_PATH_SYMLINKED")
            io_path = _windows_io_path(path)
            if not io_path.is_file():
                missing.append(dataset_id)
                continue
            if (
                not usable_root.resolve().is_relative_to(recovery.resolve())
                or not path.resolve().is_relative_to(usable_root.resolve())
            ):
                raise ValueError("LOCAL_SAFE_SHARD_PATH_ESCAPES_RECOVERY_ROOT")
            stat = io_path.stat()
            identity = [stat.st_size, stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_ctime_ns]
            prior_row = cached.get(dataset_id)
            reused = bool(
                isinstance(prior_row, dict)
                and prior_row.get("sha256") == sha
                and prior_row.get("identity") == identity
                and stat.st_size == size
            )
            if reused:
                stat_reused += 1
            elif stat.st_size != size or _sha256(
                io_path,
                progress=(
                    lambda done, total, item=dataset_id, current=row_number: progress(
                        f"SHA-256 SAFE {current:,}/{len(ordered_safe_rows):,} · "
                        f"{item} · {done / 1024**2:,.0f}/{total / 1024**2:,.0f} MiB"
                    )
                ) if progress is not None else None,
            ) != sha:
                hashes_recomputed += int(stat.st_size == size)
                rejected.append({"dataset_id": dataset_id, "reason": "LOCAL_SIZE_OR_SHA256_MISMATCH"})
                continue
            else:
                hashes_recomputed += 1
            cache_rows[dataset_id] = {"sha256": sha, "identity": identity}
            selected.append((io_path, {**dict(row), "manifest": manifest}))
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            rejected.append({"dataset_id": dataset_id, "reason": str(exc)[:180]})

    core_selected = [
        asset for asset in selected if asset[1].get("family") in _SAFE_FAMILIES
    ]
    selection_digest = hashlib.sha256(
        "\n".join(
            f"{asset['dataset_id']}\0{asset['family']}\0{asset['bytes']}\0{asset['sha256']}"
            for _path, asset in sorted(
                core_selected, key=lambda pair: str(pair[1].get("dataset_id") or ""),
            )
        ).encode("utf-8")
    ).hexdigest()
    core_ids = {str(row.get("dataset_id") or "") for row in core_safe_rows}
    core_verified = sum(
        str(asset.get("dataset_id") or "") in core_ids for _path, asset in selected
    )
    core_missing_ids = {
        str(row.get("dataset_id") or "") for row in core_safe_rows
    }.intersection(missing)
    core_rejected_ids = {
        str(item.get("dataset_id") or "") for item in rejected
    }.intersection(core_ids)
    audit_status = "SAFE_COMPLETE" if (
        core_verified == len(core_safe_rows)
        and not core_missing_ids and not core_rejected_ids
    ) else "SAFE_PARTIAL"
    safe_context_verified = Counter(
        str(asset.get("family")) for _path, asset in selected
        if asset.get("family") in _SAFE_CONTEXT_FAMILIES
        and str(asset.get("dataset_id") or "") in core_ids
    )
    family_by_id = {
        str(row.get("dataset_id") or ""): str(row.get("family") or "")
        for row in safe_rows
    }
    safe_context_missing = Counter(
        family_by_id[dataset_id] for dataset_id in core_missing_ids
        if family_by_id.get(dataset_id) in _SAFE_CONTEXT_FAMILIES
    )
    safe_context_rejected = Counter(
        family_by_id[dataset_id] for dataset_id in {
            item.get("dataset_id", "") for item in rejected
        }
        if dataset_id in core_ids and family_by_id.get(dataset_id) in _SAFE_CONTEXT_FAMILIES
    )
    audit = {
        "schema": "hypersmart.copy_vault_local_safe_audit.v1",
        **_copy_vault_catalog_audit(all_rows),
        "safe_copy_vault_shards_not_used_for_pnl_inventory_by_family": auxiliary_inventory,
        "status": audit_status,
        "reason": None if audit_status == "SAFE_COMPLETE" else "LOCAL_SAFE_SHARDS_MISSING_OR_REJECTED",
        "source_index_sha256": catalog_sha,
        "expected_selection_sha256": expected_digest,
        "selection_digest": selection_digest,
        "expected_safe_shards": len(core_safe_rows),
        "external_market_catalog_inventory": _external_market_catalog_rows(
            external_catalog_inventory,
            source_recovery_root=str(Path(recovery_root).resolve()),
            active_data_index=str(catalog_path.resolve()),
            catalog_sha256=catalog_sha,
        ),
        "copy_vault_release_tags": copy_vault_release_tags,
        "verified_safe_shards": core_verified,
        "expected_by_family": dict(sorted(family_expected.items())),
        "safe_context_expected_by_family": dict(sorted(safe_context_expected.items())),
        "safe_context_verified_by_family": dict(sorted(safe_context_verified.items())),
        "safe_context_missing_by_family": dict(sorted(safe_context_missing.items())),
        "safe_context_rejected_by_family": dict(sorted(safe_context_rejected.items())),
        "quality_counts_by_family": dict(sorted(
            (f"{family}:{quality}", count)
            for (family, quality), count in Counter(
                (str(row.get("family") or ""), str(row.get("quality_status") or "MISSING"))
                for row in all_rows
            ).items()
        )),
        "partial_rows_excluded": sum(
            1 for row in all_rows
            if row.get("family") in _SAFE_FAMILIES and row.get("quality_status") != "SAFE"
        ),
        "missing_count": len(missing),
        "missing_sample": missing[:50],
        "rejected_count": len(rejected),
        "rejected_sample": rejected[:50],
        "cached_hashes_reused_after_stat_match": stat_reused,
        "hashes_recomputed": hashes_recomputed,
        "no_downloads": True,
        "paper_read_only": True,
        "real_execution": False,
        "_watch_files": [
            str(_windows_io_path(
                recovery / "usable" / "shards"
                / str(row.get("release_tag")) / str(row.get("release_asset"))
            ))
            for row in safe_rows
        ],
    }
    _atomic_json(cache_path, {
        "schema": _SAFE_AUDIT_CACHE_SCHEMA,
        "catalog_sha256": catalog_sha,
        "expected_selection_sha256": expected_digest,
        "verified": cache_rows,
    })
    return selected, audit


def _load_wrappers(path: Path):
    """Yield every authenticated read-only JSONL envelope in one SAFE shard."""
    with gzip.open(_windows_io_path(path), "rt", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                raise ValueError(f"empty JSONL frame at line {line_number}")
            wrapper = json.loads(line)
            if not isinstance(wrapper, dict):
                raise ValueError(f"non-object JSONL frame at line {line_number}")
            if wrapper.get("read_only") is not True or wrapper.get("real_execution") is not False:
                raise ValueError("unsafe wrapper")
            raw_text = wrapper.get("raw_payload")
            if not isinstance(raw_text, str):
                raise ValueError("raw payload missing")
            if hashlib.sha256(raw_text.encode("utf-8")).hexdigest() != str(wrapper.get("raw_sha256") or ""):
                raise ValueError("raw payload hash mismatch")
            raw = json.loads(raw_text)
            if not isinstance(raw, dict):
                raise ValueError("raw payload is not an object")
            wrapper["_raw"] = raw
            yield wrapper


def _fill_rows(
    wrapper: Mapping[str, Any], *, family: str,
    audit: Counter[str] | None = None,
) -> list[dict[str, Any]]:
    raw = wrapper["_raw"]
    if raw.get("channel") != "userFills" or not isinstance(raw.get("data"), Mapping):
        if audit is not None:
            audit["USERFILLS_SNAPSHOT_PAYLOAD_INVALID"] += 1
        return []
    data = raw["data"]
    snapshot = data.get("isSnapshot")
    expected_snapshot = family == "copy_vault_snapshot"
    if type(snapshot) is not bool or snapshot is not expected_snapshot:
        if audit is not None:
            audit["SNAPSHOT_FAMILY_FLAG_MISMATCH"] += 1
        return []
    source_id = str(wrapper.get("source_id") or "")
    provenance = wrapper.get("provenance")
    transport = (
        str(provenance.get("transport") or "").lower()
        if isinstance(provenance, Mapping)
        else ""
    )
    expected_sources = (
        {"hyperliquid_public_userfills", "hyperliquid_public_userfills_backfill"}
        if expected_snapshot
        else {"hyperliquid_public_userfills"}
    )
    if (
        source_id not in expected_sources
        or not isinstance(provenance, Mapping)
        or provenance.get("access") != "read_only"
        or provenance.get("authenticated") is not False
        or transport not in {"websocket", "https"}
        or (source_id.endswith("_backfill") and (
            provenance.get("historical_only") is not True
            or provenance.get("forward_evidence_allowed") is not False
        ))
    ):
        if audit is not None:
            audit["USERFILLS_PROVENANCE_INVALID"] += 1
        return []
    vault = str(data.get("user") or wrapper.get("instrument") or "").lower()
    if vault != str(wrapper.get("instrument") or "").lower():
        if audit is not None:
            audit["USERFILLS_VAULT_IDENTITY_MISMATCH"] += 1
        return []
    rows: list[dict[str, Any]] = []
    raw_fills = data.get("fills")
    if not isinstance(raw_fills, list):
        if audit is not None:
            audit["FILL_LIST_INVALID"] += 1
        return []
    for fill in raw_fills:
        try:
            if not isinstance(fill, Mapping):
                raise TypeError("fill row is not an object")
            side = str(fill.get("side") or "").upper()
            if side not in {"A", "B"}:
                raise ValueError("fill side missing or invalid")
            fee = _number(fill["fee"])
            receive_value = wrapper.get("received_ts_ms")
            receive = int(receive_value) if type(receive_value) is int and receive_value > 0 else None
            event_ts = int(fill["time"])
            if receive is None or not 0 < event_ts <= receive:
                raise ValueError("fill timestamp is missing or noncausal")
            start_position = _number(fill["startPosition"]) if fill.get("startPosition") is not None else None
            closed_pnl = _number(fill["closedPnl"]) if fill.get("closedPnl") is not None else None
            rows.append({
                "vault": vault,
                "ts_ms": event_ts,
                "coin": str(fill["coin"]).strip(),
                "px": _number(fill["px"]),
                "sz": _number(fill["sz"]),
                "signe": 1 if side == "B" else -1,
                "dir": str(fill.get("dir") or ""),
                "start_position": start_position,
                "oid": fill.get("oid"),
                "tid": fill.get("tid"),
                "hash": fill.get("hash"),
                "closed_pnl": closed_pnl,
                "fee": fee,
                "isSnapshot": snapshot,
                "is_snapshot": snapshot,
                "source": (
                    "REST_BACKFILL"
                    if source_id == "hyperliquid_public_userfills_backfill"
                    else "WS_BOOTSTRAP"
                    if snapshot
                    else "LIVE_WS"
                ),
                "source_id": source_id,
                "received_at_ms": receive,
                "observed_at_ms": receive if not snapshot else None,
                "source_raw_sha256": wrapper.get("raw_sha256"),
            })
        except (KeyError, TypeError, ValueError, OverflowError):
            if audit is not None:
                audit["INVALID_OR_INCOMPLETE_FILL_REJECTED"] += 1
            continue
    return rows


def _unclassified_fill_observation(
    wrapper: Mapping[str, Any], *, family: str,
) -> dict[str, Any] | None:
    """Retain a SAFE live fill envelope whose snapshot/event flag is unknown.

    This archive is diagnostic only: the row is deliberately never converted to
    a fill and cannot enter replay or PnL.
    """
    raw = wrapper.get("_raw")
    data = raw.get("data") if isinstance(raw, Mapping) else None
    provenance = wrapper.get("provenance")
    received = wrapper.get("received_ts_ms")
    raw_text = wrapper.get("raw_payload")
    if not isinstance(data, Mapping):
        return None
    snapshot_flag = data.get("isSnapshot")
    if (
        family != "copy_vault_fills"
        or raw.get("channel") != "userFills"
        or wrapper.get("channel") != "copy_vault_fills"
        or wrapper.get("source_id") != "hyperliquid_public_userfills"
        or type(snapshot_flag) is bool
        or not isinstance(provenance, Mapping)
        or provenance.get("access") != "read_only"
        or provenance.get("authenticated") is not False
        or str(provenance.get("transport") or "").lower() != "websocket"
        or type(received) is not int or received <= 0
        or not isinstance(raw_text, str)
        or not str(wrapper.get("instrument") or "").strip()
        or str(data.get("user") or "").lower() != str(wrapper.get("instrument") or "").lower()
    ):
        return None
    return {
        "schema_version": "hypersmart.copy_vault_unclassified_fill.v1",
        "vault": str(wrapper["instrument"]).lower(),
        "source_id": wrapper["source_id"],
        "channel": wrapper["channel"],
        "received_at_ms": received,
        "event_ts_ms": None,
        "snapshot_flag": snapshot_flag,
        "event_kind": str(wrapper.get("event_kind") or "UNCLASSIFIED"),
        "executable": False,
        "pnl_eligible": False,
        "reason": "SNAPSHOT_FLAG_MISSING_OR_INVALID",
        "provenance": {
            "access": provenance.get("access"),
            "authenticated": provenance.get("authenticated"),
            "transport": provenance.get("transport"),
        },
        "raw_payload": raw_text,
        "source_raw_sha256": wrapper.get("raw_sha256"),
    }


def _book_row(
    wrapper: Mapping[str, Any], *, rejection_audit: Counter[str] | None = None,
) -> dict[str, Any] | None:
    def reject(reason: str) -> None:
        if rejection_audit is not None:
            rejection_audit[reason] += 1

    raw = wrapper["_raw"]
    data = raw.get("data") if isinstance(raw.get("data"), Mapping) else {}
    levels = data.get("levels")
    provenance = wrapper.get("provenance")
    if (
        wrapper.get("channel") != "copy_vault_l2"
        or wrapper.get("source_id") != "hyperliquid_public_copy_l2"
        or not isinstance(provenance, Mapping)
        or provenance.get("access") != "read_only"
        or provenance.get("authenticated") is not False
        or provenance.get("copy_vault_execution_evidence") is not True
        or str(provenance.get("transport") or "").lower() != "websocket"
    ):
        reject("L2_PROVENANCE_INVALID")
        return None
    if raw.get("channel") != "l2Book" or not isinstance(levels, list) or len(levels) != 2:
        reject("CHANNEL_OR_LEVELS_INVALID")
        return None
    try:
        if not isinstance(levels[0], list) or not isinstance(levels[1], list):
            reject("DEPTH_LEVELS_NOT_LISTS")
            return None
        bids = [[_number(level["px"]), _number(level["sz"])] for level in levels[0]][:5]
        asks = [[_number(level["px"]), _number(level["sz"])] for level in levels[1]][:5]
        if not bids or not asks:
            reject("EMPTY_BOOK_SIDE")
            return None
        bids.sort(key=lambda row: row[0], reverse=True)
        asks.sort(key=lambda row: row[0])
        bid, ask = bids[0][0], asks[0][0]
        if bid <= 0 or ask <= bid:
            reject("CROSSED_OR_NONPOSITIVE_BOOK")
            return None
        capacity = min(
            sum(price * size for price, size in bids),
            sum(price * size for price, size in asks),
        )
        received_value = wrapper.get("received_ts_ms")
        exchange_value = data.get("time")
        received = received_value if type(received_value) is int else 0
        exchange = exchange_value if type(exchange_value) is int else 0
        coin = str(data.get("coin") or "").strip()
        instrument = str(wrapper.get("instrument") or "").strip()
        if not coin or coin != instrument:
            reject("L2_INSTRUMENT_IDENTITY_MISMATCH")
            return None
        if exchange <= 0:
            reject("EXCHANGE_TIMESTAMP_MISSING")
            return None
        if received <= 0:
            reject("RECEIVE_TIMESTAMP_MISSING")
            return None
        if received < exchange:
            reject("RECEIVE_BEFORE_EXCHANGE")
            return None
        if received - exchange > 30_000:
            reject("EXCHANGE_DATA_STALE_OVER_30S")
            return None
        return {
            "schema_version": "hypersmart.copy_vault_l2.v1",
            "coin": coin,
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
        reject("LEVEL_VALUE_INVALID")
        return None


def _l2_unexecutable_observation(
    wrapper: Mapping[str, Any], *, reason: str,
) -> dict[str, Any] | None:
    """Keep valid empty-side L2 observations without treating them as executable."""
    if reason != "EMPTY_BOOK_SIDE":
        return None
    raw = wrapper.get("_raw")
    data = raw.get("data") if isinstance(raw, Mapping) else None
    levels = data.get("levels") if isinstance(data, Mapping) else None
    provenance = wrapper.get("provenance")
    raw_text = wrapper.get("raw_payload")
    try:
        received_value = wrapper.get("received_ts_ms")
        exchange_value = data.get("time")
        received = received_value if type(received_value) is int else 0
        exchange = exchange_value if type(exchange_value) is int else 0
        instrument = str(wrapper.get("instrument") or "").strip()
        coin = str(data.get("coin") or instrument).strip()
        if (
            raw.get("channel") != "l2Book"
            or wrapper.get("channel") != "copy_vault_l2"
            or wrapper.get("source_id") != "hyperliquid_public_copy_l2"
            or not isinstance(provenance, Mapping)
            or provenance.get("access") != "read_only"
            or provenance.get("authenticated") is not False
            or provenance.get("copy_vault_execution_evidence") is not True
            or not isinstance(levels, list) or len(levels) != 2
            or not all(isinstance(side, list) for side in levels)
            or (levels[0] and levels[1])
            or not instrument or coin != instrument
            or not isinstance(raw_text, str)
            or exchange <= 0 or received < exchange or received - exchange > 30_000
        ):
            return None
    except (TypeError, ValueError, OverflowError):
        return None
    return {
        "schema_version": "hypersmart.copy_vault_l2_observation.v1",
        "coin": coin,
        "received_at_ms": received,
        "exchange_ts_ms": exchange,
        "executable": False,
        "pnl_eligible": False,
        "reason": "EMPTY_BOOK_SIDE",
        "source": "HYPERLIQUID_L2_WS",
        "source_raw_sha256": wrapper.get("raw_sha256"),
        "raw_payload": raw_text,
    }


def _context_row(
    wrapper: Mapping[str, Any], *, family: str, audit: Counter[str] | None = None,
) -> dict[str, Any] | None:
    """Preserve SAFE receive-time vault context without making it PnL evidence."""
    expected_source = _CONTEXT_SOURCE_BY_FAMILY.get(family)
    provenance = wrapper.get("provenance")
    summary = wrapper.get("parsed_summary")
    received = wrapper.get("received_ts_ms")
    raw_text = wrapper.get("raw_payload")
    invalid_reason = None
    if family not in _SAFE_CONTEXT_FAMILIES or not expected_source:
        invalid_reason = "UNKNOWN_CONTEXT_FAMILY"
    elif (
        wrapper.get("channel") != family
        or wrapper.get("source_id") != expected_source
        or not str(wrapper.get("instrument") or "").strip()
    ):
        invalid_reason = "CONTEXT_IDENTITY_MISMATCH"
    elif (
        not isinstance(provenance, Mapping)
        or provenance.get("access") != "read_only"
        or provenance.get("authenticated") is not False
        or str(provenance.get("transport") or "").lower() != "https"
        or provenance.get("timestamp_semantics") != "receive_observation_time_only"
        or (family == "copy_vault_selection" and provenance.get("selection_causal") is not True)
    ):
        invalid_reason = "CONTEXT_PROVENANCE_INVALID"
    elif type(received) is not int or received <= 0:
        invalid_reason = "CONTEXT_RECEIVE_TIME_INVALID"
    elif not isinstance(summary, Mapping) or summary.get("data_gate_ready") is not False:
        invalid_reason = "CONTEXT_SUMMARY_NOT_OBSERVATION_ONLY"
    elif family == "copy_vault_positions" and (
        type(summary.get("position_count")) is not int or summary.get("position_count") < 0
    ):
        invalid_reason = "CONTEXT_POSITION_COUNT_INVALID"
    elif family == "copy_vault_selection" and summary.get("observation_only") is not True:
        invalid_reason = "CONTEXT_SELECTION_NOT_OBSERVATION_ONLY"
    elif not isinstance(raw_text, str):
        invalid_reason = "CONTEXT_RAW_PAYLOAD_MISSING"
    if invalid_reason:
        if audit is not None:
            audit[f"{invalid_reason}_REJECTED"] += 1
        return None
    nav_snapshot = None
    if family == "copy_vault_positions":
        raw_state = wrapper.get("_raw")
        margin_summary = raw_state.get("marginSummary") if isinstance(raw_state, Mapping) else None
        try:
            nav_value = _number(margin_summary["accountValue"])
            if nav_value > 0:
                nav_snapshot = {
                    "vault": str(wrapper["instrument"]).lower(),
                    "ts_ms": received,
                    "nav_usd": nav_value,
                    "source": "SAFE_RECEIVE_TIME_POSITION_SNAPSHOT",
                    "source_id": expected_source,
                    "received_at_ms": received,
                    "timestamp_semantics": "receive_observation_time_only",
                    "pnl_eligible": False,
                    "source_raw_sha256": wrapper.get("raw_sha256"),
                }
        except (KeyError, TypeError, ValueError, OverflowError):
            nav_snapshot = None
    return {
        "schema_version": "hypersmart.copy_vault_context.v1",
        "family": family,
        "source_id": expected_source,
        "channel": family,
        "instrument": str(wrapper["instrument"]).lower(),
        "observed_at_ms": received,
        "timestamp_semantics": "receive_observation_time_only",
        "event_ts_ms": None,
        "exchange_ts_ms": None,
        "pnl_eligible": False,
        "forward_evidence_allowed": False,
        "observation_only": True,
        "provenance": {
            "access": provenance.get("access"),
            "authenticated": provenance.get("authenticated"),
            "transport": provenance.get("transport"),
            "timestamp_semantics": provenance.get("timestamp_semantics"),
            **({"selection_causal": True} if provenance.get("selection_causal") is True else {}),
        },
        "summary": dict(summary),
        "nav_snapshot": nav_snapshot,
        "raw_payload": raw_text,
        "source_raw_sha256": wrapper.get("raw_sha256"),
    }


def _market_context_row(
    wrapper: Mapping[str, Any], *, family: str, audit: Counter[str] | None = None,
) -> dict[str, Any] | None:
    """Validate and preserve same-run market evidence without feeding PnL."""
    expected = {
        "copy_vault_bbo": ("bbo", "hyperliquid_public_copy_vault_market_ws", "causal_event_availability"),
        "copy_vault_trades": ("trades", "hyperliquid_public_copy_vault_market_ws", "causal_event_availability"),
        "copy_vault_active_asset_ctx": (
            "activeAssetCtx", "hyperliquid_public_copy_vault_market_ws",
            "receive_observation_time_only",
        ),
        "copy_vault_instrument_metadata": (
            "instrument_metadata", "hyperliquid_public_copy_vault_instrument_metadata",
            "receive_observation_time_only",
        ),
    }

    def reject(reason: str) -> None:
        if audit is not None:
            audit[f"{reason}_REJECTED"] += 1

    contract = expected.get(family)
    raw = wrapper.get("_raw")
    data = raw.get("data") if isinstance(raw, Mapping) else None
    provenance = wrapper.get("provenance")
    summary = wrapper.get("parsed_summary")
    native_instrument = str(wrapper.get("instrument") or "").strip()
    received = wrapper.get("received_ts_ms")
    exchange = wrapper.get("exchange_ts_ms")
    raw_text = wrapper.get("raw_payload")
    if contract is None:
        reject("UNKNOWN_MARKET_CONTEXT_FAMILY")
        return None
    raw_channel, expected_source, semantics = contract
    if (
        not isinstance(raw, Mapping) or raw.get("channel") != raw_channel
        or not isinstance(data, (Mapping, list))
        or wrapper.get("channel") != family
        or wrapper.get("source_id") != expected_source
    ):
        reject("MARKET_CHANNEL_OR_SOURCE_MISMATCH")
        return None
    if (
        not native_instrument
        or not isinstance(provenance, Mapping)
        or provenance.get("venue") != "hyperliquid"
        or provenance.get("access") != "read_only"
        or provenance.get("authenticated") is not False
        or provenance.get("timestamp_semantics") != semantics
        or wrapper.get("read_only") is not True
        or wrapper.get("real_execution") is not False
        or str(provenance.get("transport") or "").lower()
        != ("https" if family == "copy_vault_instrument_metadata" else "websocket")
        or type(received) is not int or received <= 0
        or not isinstance(summary, Mapping) or summary.get("data_gate_ready") is not False
        or not isinstance(raw_text, str)
        or len(str(wrapper.get("raw_sha256") or "")) != 64
    ):
        reject("MARKET_CONTEXT_PROVENANCE_OR_CLOCK_INVALID")
        return None
    if family in {"copy_vault_active_asset_ctx", "copy_vault_instrument_metadata"}:
        if exchange is not None:
            reject("MARKET_OBSERVATION_HAS_FABRICATED_EXCHANGE_TIME")
            return None
        if (
            not isinstance(data, Mapping)
            or str(data.get("coin") or "").strip() != native_instrument
        ):
            reject("MARKET_NATIVE_INSTRUMENT_MISMATCH")
            return None
        if family == "copy_vault_active_asset_ctx" and not isinstance(data.get("ctx"), Mapping):
            reject("ACTIVE_ASSET_CONTEXT_INVALID")
            return None
        if family == "copy_vault_instrument_metadata":
            metadata = data.get("metadata")
            symbol = native_instrument.split(":", 1)[-1]
            if not isinstance(metadata, Mapping) or str(metadata.get("name") or "") != symbol:
                reject("INSTRUMENT_METADATA_IDENTITY_INVALID")
                return None
    else:
        if (
            type(exchange) is not int or exchange <= 0 or exchange > received
            or received - exchange > 30_000
        ):
            reject("MARKET_EVENT_CLOCK_INVALID_OR_STALE")
            return None
        if family == "copy_vault_bbo":
            bbo = data.get("bbo") if isinstance(data, Mapping) else None
            if not isinstance(data, Mapping) or str(data.get("coin") or "").strip() != native_instrument:
                reject("MARKET_NATIVE_INSTRUMENT_MISMATCH")
                return None
            if (
                type(data.get("time")) is not int or data["time"] != exchange
                or not isinstance(bbo, list) or len(bbo) != 2
                or not all(isinstance(level, Mapping) for level in bbo)
            ):
                reject("BBO_PAYLOAD_INVALID")
                return None
            try:
                prices = [_number(level["px"]) for level in bbo]
                sizes = [_number(level["sz"]) for level in bbo]
                if min(prices) <= 0 or min(sizes) < 0 or prices[0] >= prices[1]:
                    raise ValueError
            except (KeyError, TypeError, ValueError, OverflowError):
                reject("BBO_PRICE_OR_SIZE_INVALID")
                return None
        else:
            if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], Mapping):
                reject("TRADE_ENVELOPE_NOT_SINGLE_EVENT")
                return None
            trade = data[0]
            has_identity = bool(str(trade.get("hash") or "").strip()) or (
                isinstance(trade.get("tid"), int) and not isinstance(trade.get("tid"), bool)
            )
            try:
                price, size = _number(trade["px"]), _number(trade["sz"])
                valid_time = type(trade.get("time")) is int and trade["time"] == exchange
            except (KeyError, TypeError, ValueError, OverflowError):
                price, size, valid_time = 0.0, 0.0, False
            if (
                str(trade.get("coin") or "").strip() != native_instrument
                or not has_identity or price <= 0 or size <= 0
                or str(trade.get("side") or "").upper() not in {"A", "B"}
                or not valid_time
            ):
                reject("TRADE_EVENT_INVALID_OR_NATIVE_INSTRUMENT_MISMATCH")
                return None
    return {
        "schema_version": "hypersmart.copy_vault_market_context.v1",
        "family": family,
        "source_id": expected_source,
        "instrument": native_instrument,
        "observed_at_ms": received,
        "event_ts_ms": exchange if semantics == "causal_event_availability" else None,
        "exchange_ts_ms": exchange if semantics == "causal_event_availability" else None,
        "timestamp_semantics": semantics,
        "observation_only": True,
        "pnl_eligible": False,
        "forward_evidence_allowed": False,
        "connection_id": wrapper.get("connection_id"),
        "provenance": {
            "venue": provenance.get("venue"), "access": provenance.get("access"),
            "authenticated": provenance.get("authenticated"),
            "transport": provenance.get("transport"),
        },
        "raw_payload": raw_text,
        "source_raw_sha256": wrapper.get("raw_sha256"),
    }


def _exact_accounting_contract(
    wrapper: Mapping[str, Any], *, family: str,
) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]] | None:
    """Authenticate exact-window read-only receipts before accepting accounting rows."""
    raw = wrapper.get("_raw")
    provenance = wrapper.get("provenance")
    if not isinstance(raw, Mapping) or not isinstance(provenance, Mapping):
        return None
    expected_request = {
        "copy_vault_user_funding": "userFunding",
        "copy_vault_ledger": "userNonFundingLedgerUpdates",
        "copy_vault_funding_rates": "fundingHistory",
    }.get(family)
    source_prefix = {
        "copy_vault_user_funding": "hyperliquid_public_userFunding_",
        "copy_vault_ledger": "hyperliquid_public_userNonFundingLedgerUpdates_",
        "copy_vault_funding_rates": "hyperliquid_public_funding_history_",
    }.get(family)
    data = raw.get("data")
    if (
        expected_request is None or source_prefix is None
        or wrapper.get("channel") != family
        or raw.get("channel") != expected_request
        or not str(wrapper.get("source_id") or "").startswith(source_prefix)
        or str(wrapper.get("source_id") or "").rsplit("_", 1)[-1]
        not in {"historical", "forward"}
        or not isinstance(data, Mapping)
        or not isinstance(data.get("records"), list)
        or wrapper.get("read_only") is not True
        or wrapper.get("real_execution") is not False
        or provenance.get("network") != "mainnet"
        or provenance.get("access") != "read_only"
        or provenance.get("authenticated") is not False
        or provenance.get("transport") != "https"
        or provenance.get("request_type") != expected_request
    ):
        return None
    received = wrapper.get("received_ts_ms")
    if type(received) is not int or received <= 0:
        return None
    if family in {"copy_vault_user_funding", "copy_vault_ledger"}:
        identity = data.get("user")
        expected_identity = str(wrapper.get("instrument") or "").strip().lower()
        if not isinstance(identity, str) or identity.strip().lower() != expected_identity:
            return None
    else:
        identity = data.get("coin")
        if not isinstance(identity, str) or identity.strip() != str(wrapper.get("instrument") or "").strip():
            return None
    coverage = data.get("coverage")
    if not isinstance(coverage, Mapping):
        return None
    window_kind = coverage.get("window_kind")
    forward_allowed = window_kind == "FORWARD"
    records = data["records"]
    requested_start, requested_end = (
        coverage.get("requested_start_ms"), coverage.get("requested_end_ms")
    )
    lower, upper = coverage.get("leaf_start_ms"), coverage.get("leaf_end_ms")
    response_rows, accepted_rows = (
        coverage.get("leaf_response_rows"), coverage.get("leaf_accepted_rows")
    )
    if (
        coverage.get("schema") != "alina.copy_vault_exact_window_receipt.v1"
        or coverage.get("status") != "COMPLETE"
        or coverage.get("request_type") != expected_request
        or window_kind not in {"FORWARD", "PRE_SELECTION_HISTORICAL_RESEARCH_ONLY"}
        or coverage.get("forward_evidence_allowed") is not forward_allowed
        or provenance.get("window_kind") != window_kind
        or provenance.get("forward_evidence_allowed") is not forward_allowed
        or any(type(value) is not int or value <= 0 for value in (
            requested_start, requested_end, lower, upper,
        ))
        or not requested_start <= lower <= upper <= requested_end
        or type(response_rows) is not int or response_rows < 0
        or type(accepted_rows) is not int or accepted_rows != len(records)
        or response_rows < accepted_rows
    ):
        return None
    for row in records:
        if not isinstance(row, Mapping):
            return None
        ts_ms = row.get("time")
        if type(ts_ms) is not int or not lower <= ts_ms <= upper or ts_ms > received:
            return None
    return data, provenance, coverage


def _funding_rate_rows(
    wrapper: Mapping[str, Any], *, family: str,
    audit: Counter[str] | None = None,
) -> list[dict[str, Any]]:
    def reject(reason: str) -> list[dict[str, Any]]:
        if audit is not None:
            audit[f"{reason}_REJECTED"] += 1
        return []

    contract = _exact_accounting_contract(wrapper, family=family)
    if contract is None:
        return reject("FUNDING_RATE_RECEIPT_OR_PROVENANCE_INVALID")
    data, _provenance, coverage = contract
    output: list[dict[str, Any]] = [{
        "schema_version": "hypersmart.copy_vault_funding_rate_coverage.v1",
        "record_type": "COVERAGE_RECEIPT",
        "coin": str(wrapper.get("instrument") or ""),
        "window_start_ms": int(coverage["leaf_start_ms"]),
        "window_end_ms": int(coverage["leaf_end_ms"]),
        "window_kind": str(coverage["window_kind"]),
        "forward_evidence_allowed": coverage.get("forward_evidence_allowed") is True,
        "received_at_ms": int(wrapper["received_ts_ms"]),
        "response_rows": coverage.get("leaf_response_rows"),
        "accepted_rows": coverage.get("leaf_accepted_rows"),
        "coverage_status": "COMPLETE",
        "pnl_eligible": False,
        "source_id": wrapper.get("source_id"),
        "source_raw_sha256": wrapper.get("raw_sha256"),
    }]
    for raw_row in data["records"]:
        try:
            ts_ms = raw_row["time"]
            rate = _number(raw_row["fundingRate"])
            premium = _number(raw_row["premium"]) if raw_row.get("premium") is not None else None
            if type(ts_ms) is not int or ts_ms <= 0:
                raise ValueError
            output.append({
                "schema_version": "hypersmart.copy_vault_funding_rate.v1",
                "record_type": "SETTLEMENT_RATE",
                "coin": str(wrapper.get("instrument") or ""),
                "ts_ms": ts_ms,
                "funding_rate": rate,
                "premium": premium,
                "window_kind": str(coverage["window_kind"]),
                "forward_evidence_allowed": coverage.get("forward_evidence_allowed") is True,
                "received_at_ms": int(wrapper["received_ts_ms"]),
                "source_id": wrapper.get("source_id"),
                "pnl_eligible": False,
                "source_raw_sha256": wrapper.get("raw_sha256"),
                "raw_record": dict(raw_row),
            })
        except (KeyError, TypeError, ValueError, OverflowError):
            if audit is not None:
                audit["INVALID_FUNDING_RATE_EVENT_REJECTED"] += 1
    return output


def _leader_accounting_rows(
    wrapper: Mapping[str, Any], *, family: str, audit: Counter[str] | None = None,
) -> list[dict[str, Any]]:
    def reject(reason: str) -> list[dict[str, Any]]:
        if audit is not None:
            audit[f"{reason}_REJECTED"] += 1
        return []

    contract = _exact_accounting_contract(wrapper, family=family)
    if contract is None:
        return reject("LEADER_ACCOUNTING_RECEIPT_OR_PROVENANCE_INVALID")
    data, _provenance, coverage = contract
    received = wrapper["received_ts_ms"]
    vault = str(wrapper["instrument"]).lower()
    lower = int(coverage["leaf_start_ms"])
    upper = int(coverage["leaf_end_ms"])
    output: list[dict[str, Any]] = [{
        "schema_version": "hypersmart.copy_vault_leader_accounting_coverage.v1",
        "record_type": "COVERAGE_RECEIPT",
        "family": family,
        "vault": vault,
        "window_start_ms": lower,
        "window_end_ms": upper,
        "window_kind": str(coverage["window_kind"]),
        "forward_evidence_allowed": coverage["forward_evidence_allowed"] is True,
        "received_at_ms": received,
        "response_rows": coverage.get("leaf_response_rows"),
        "accepted_rows": coverage.get("leaf_accepted_rows"),
        "coverage_status": "COMPLETE",
        "pnl_eligible": False,
        "source_id": wrapper.get("source_id"),
        "source_raw_sha256": wrapper.get("raw_sha256"),
    }]
    for raw_row in data["records"]:
        try:
            if not isinstance(raw_row, Mapping):
                raise TypeError
            ts_ms = raw_row["time"]
            transaction_hash = str(raw_row["hash"] or "").strip().lower()
            delta = raw_row["delta"]
            if (
                isinstance(ts_ms, bool) or type(ts_ms) is not int
                or not lower <= ts_ms <= upper or ts_ms > received
                or not transaction_hash or not isinstance(delta, Mapping)
                or not str(delta.get("type") or "").strip()
            ):
                raise ValueError
            if family == "copy_vault_user_funding":
                if str(delta.get("type") or "") != "funding":
                    raise ValueError
                normalized_delta: dict[str, Any] = dict(delta)
                for field in ("fundingRate", "szi", "usdc"):
                    normalized_delta[f"{field}_numeric"] = _number(delta[field])
            else:
                normalized_delta = dict(delta)
            output.append({
                "schema_version": "hypersmart.copy_vault_leader_accounting_event.v1",
                "record_type": "LEADER_ACCOUNTING_EVENT",
                "family": family,
                "vault": vault,
                "ts_ms": ts_ms,
                "hash": transaction_hash,
                "delta": normalized_delta,
                "window_kind": str(coverage["window_kind"]),
                "forward_evidence_allowed": coverage["forward_evidence_allowed"] is True,
                "received_at_ms": received,
                "source_id": wrapper.get("source_id"),
                "pnl_eligible": False,
                "source_raw_sha256": wrapper.get("raw_sha256"),
                "raw_record": dict(raw_row),
            })
        except (KeyError, TypeError, ValueError, OverflowError):
            if audit is not None:
                audit["INVALID_LEADER_ACCOUNTING_EVENT_REJECTED"] += 1
    return output


def materialize_safe_workspace(
    recovery_root: str | Path,
    workspace: str | Path,
    *,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    recovery_root, workspace = Path(recovery_root), Path(workspace)
    assets, audit = _verified_assets(recovery_root, progress=progress)
    repository_root = Path(recovery_root).resolve().parents[2]
    data_dir = workspace / "runtime" / "data"
    if any(part.is_symlink() for part in (workspace, workspace / "runtime", data_dir)):
        raise OSError("refusing symlinked Copy-Vault replay workspace")
    data_dir.mkdir(parents=True, exist_ok=True)
    fills: dict[tuple[Any, ...], dict[str, Any]] = {}
    books: dict[tuple[Any, ...], dict[str, Any]] = {}
    context: dict[tuple[Any, ...], dict[str, Any]] = {}
    unexecutable_l2: dict[tuple[Any, ...], dict[str, Any]] = {}
    unclassified_fills: dict[tuple[Any, ...], dict[str, Any]] = {}
    funding_rates: dict[tuple[Any, ...], dict[str, Any]] = {}
    leader_accounting: dict[tuple[Any, ...], dict[str, Any]] = {}
    market_context: dict[tuple[Any, ...], dict[str, Any]] = {}
    historical_backfill_release_tags: set[str] = set()
    source_counts_by_family: Counter[str] = Counter()
    wrapper_rejections = 0
    payload_audit: Counter[str] = Counter()
    l2_rejection_audit: Counter[str] = Counter()
    payload_rejection_samples: list[dict[str, Any]] = []
    raw_frames = 0
    historical_snapshot_shards = 0
    historical_fill_observations = 0
    for asset_number, (path, asset) in enumerate(assets, 1):
        try:
            family = str(asset.get("family") or "")
            if family == "copy_vault_snapshot":
                historical_snapshot_shards += 1
            for wrapper in _load_wrappers(path):
                wrapper["_manifest_accounting"] = asset.get("copy_vault_accounting")
                raw_frames += 1
                source_counts_by_family[f"{family}:{wrapper.get('source_id') or 'SOURCE_ID_MISSING'}"] += 1
                if (
                    family == "copy_vault_snapshot"
                    and wrapper.get("source_id") == "hyperliquid_public_userfills_backfill"
                    and isinstance(asset.get("release_tag"), str)
                ):
                    historical_backfill_release_tags.add(str(asset["release_tag"]))
                if family in {"copy_vault_fills", "copy_vault_snapshot"}:
                    if family == "copy_vault_snapshot":
                        data = wrapper["_raw"].get("data")
                        raw_fill_list = data.get("fills") if isinstance(data, Mapping) else None
                        if (
                            isinstance(data, Mapping)
                            and data.get("isSnapshot") is True
                            and isinstance(raw_fill_list, list)
                        ):
                            historical_fill_observations += len(raw_fill_list)
                    before_rejections = sum(payload_audit.values())
                    normalized_fills = _fill_rows(wrapper, family=family, audit=payload_audit)
                    unclassified = _unclassified_fill_observation(wrapper, family=family)
                    if unclassified is not None:
                        identity = (
                            unclassified["vault"], unclassified["received_at_ms"],
                            unclassified.get("source_raw_sha256"),
                        )
                        unclassified_fills[identity] = unclassified
                    if (
                        sum(payload_audit.values()) > before_rejections
                        and len(payload_rejection_samples) < 50
                    ):
                        payload_rejection_samples.append({
                            "dataset_id": asset.get("dataset_id"),
                            "family": family,
                            "channel": wrapper.get("channel"),
                            "source_id": wrapper.get("source_id"),
                            "received_ts_ms": wrapper.get("received_ts_ms"),
                            "snapshot_flag": (
                                wrapper.get("_raw", {}).get("data", {}).get("isSnapshot")
                                if isinstance(wrapper.get("_raw"), Mapping)
                                and isinstance(wrapper.get("_raw", {}).get("data"), Mapping)
                                else None
                            ),
                            "raw_sha256": wrapper.get("raw_sha256"),
                            "reason_counts": dict(sorted(payload_audit.items())),
                        })
                    for row in normalized_fills:
                        identity = (
                            row["vault"], row["coin"], row["ts_ms"], row.get("tid"),
                            row.get("hash"), row.get("oid"), row["px"], row["sz"], row["signe"],
                        )
                        prior = fills.get(identity)
                        if prior is None or (
                            bool(prior.get("isSnapshot"))
                            and not bool(row.get("isSnapshot"))
                        ):
                            fills[identity] = row
                elif asset.get("family") == "copy_vault_l2":
                    before_l2_rejections = l2_rejection_audit.copy()
                    row = _book_row(wrapper, rejection_audit=l2_rejection_audit)
                    if row:
                        identity = (
                            row["coin"], row["received_at_ms"], row["exchange_ts_ms"],
                            row["bid"], row["ask"],
                            tuple(tuple(level) for level in row["bids5"]),
                            tuple(tuple(level) for level in row["asks5"]),
                        )
                        books[identity] = row
                    else:
                        l2_reason = next((
                            reason for reason, count in l2_rejection_audit.items()
                            if count > before_l2_rejections.get(reason, 0)
                        ), "UNKNOWN_L2_REJECTION")
                        observation = _l2_unexecutable_observation(
                            wrapper, reason=str(l2_reason),
                        )
                        if observation is not None:
                            identity = (
                                observation["coin"], observation["received_at_ms"],
                                observation["exchange_ts_ms"], observation.get("source_raw_sha256"),
                            )
                            unexecutable_l2[identity] = observation
                        else:
                            payload_audit["INVALID_OR_NONCAUSAL_L2_REJECTED"] += 1
                            if len(payload_rejection_samples) < 50:
                                payload_rejection_samples.append({
                                    "dataset_id": asset.get("dataset_id"),
                                    "family": family,
                                    "channel": wrapper.get("channel"),
                                    "source_id": wrapper.get("source_id"),
                                    "exchange_ts_ms": wrapper.get("exchange_ts_ms"),
                                    "received_ts_ms": wrapper.get("received_ts_ms"),
                                    "raw_sha256": wrapper.get("raw_sha256"),
                                    "l2_rejection_reason": l2_reason,
                                })
                elif family in _SAFE_CONTEXT_FAMILIES:
                    if family in {"copy_vault_user_funding", "copy_vault_ledger"}:
                        rows = _leader_accounting_rows(
                            wrapper, family=family, audit=payload_audit,
                        )
                        for row in rows:
                            identity = (
                                row["family"], row["vault"], row["record_type"],
                                row.get("ts_ms", row.get("window_start_ms")),
                                row.get("hash", row.get("window_end_ms")),
                                row.get("source_raw_sha256"),
                            )
                            leader_accounting[identity] = row
                    elif family in _SAFE_MARKET_CONTEXT_FAMILIES:
                        row = _market_context_row(
                            wrapper, family=family, audit=payload_audit,
                        )
                        if row is not None:
                            identity = (
                                family, row["instrument"], row["event_ts_ms"],
                                row["observed_at_ms"], row["source_raw_sha256"],
                            )
                            market_context[identity] = row
                    else:
                        row = _context_row(wrapper, family=family, audit=payload_audit)
                        if row is not None:
                            identity = (
                                family, row["instrument"], row["observed_at_ms"],
                                row.get("source_raw_sha256"),
                            )
                            context[identity] = row
                elif family == "copy_vault_funding_rates":
                    rows = _funding_rate_rows(
                        wrapper, family=family, audit=payload_audit,
                    )
                    for row in rows:
                        identity = (
                            str(row["coin"]), row["record_type"],
                            row.get("ts_ms", row.get("window_start_ms")),
                            row.get("window_end_ms"), row.get("source_raw_sha256"),
                        )
                        prior = funding_rates.get(identity)
                        if prior is not None and prior != row:
                            payload_audit["CONFLICTING_FUNDING_RATE_OR_RECEIPT"] += 1
                        else:
                            funding_rates[identity] = row
                if progress is not None and raw_frames % 2_000 == 0:
                    progress(
                        f"Reconstruction SAFE {asset_number:,}/{len(assets):,} · "
                        f"{raw_frames:,} enveloppes · {len(fills):,} fills · {len(books):,} carnets"
                    )
        except (OSError, EOFError, ValueError, TypeError, json.JSONDecodeError):
            wrapper_rejections += 1
        if progress is not None:
            progress(
                f"Reconstruction SAFE {asset_number:,}/{len(assets):,} · "
                f"{raw_frames:,} enveloppes · {len(fills):,} fills · {len(books):,} carnets"
            )
    if historical_backfill_release_tags:
        history_audit = load_release_history_audits(
            repository_root / "catalog" / "campaigns",
            release_tags=historical_backfill_release_tags,
        )
        history_audit["scope"] = "SAFE snapshot-family wrappers from the REST backfill source"
        history_audit["applicable"] = True
    else:
        history_audit = {
            "status": "NOT_APPLICABLE",
            "scope": "SAFE snapshot-family wrappers from the REST backfill source",
            "applicable": False,
            "expected_release_count": 0,
            "audited_release_count": 0,
            "durable_receipt_release_count": 0,
            "missing_durable_receipt_tags": [],
            "receipt_without_backfill_audit_tags": [],
            "unknown_release_tags": [],
            "partial_report_count": 0,
            "reports": [],
            "unresolved_gaps": [],
        }
    fill_rows = sorted(fills.values(), key=lambda row: (row["ts_ms"], row["vault"], str(row.get("tid"))))
    book_rows = sorted(books.values(), key=lambda row: (row["received_at_ms"], row["coin"]))
    context_rows = sorted(
        context.values(),
        key=lambda row: (row["observed_at_ms"], row["family"], row["instrument"]),
    )
    unexecutable_l2_rows = sorted(
        unexecutable_l2.values(),
        key=lambda row: (row["received_at_ms"], row["coin"], row["exchange_ts_ms"]),
    )
    unclassified_fill_rows = sorted(
        unclassified_fills.values(),
        key=lambda row: (row["received_at_ms"], row["vault"]),
    )
    funding_rate_rows = sorted(
        funding_rates.values(),
        key=lambda row: (
            str(row["coin"]),
            int(row.get("ts_ms") or row.get("window_start_ms") or 0),
            str(row["record_type"]),
        ),
    )
    leader_accounting_rows = sorted(
        leader_accounting.values(),
        key=lambda row: (
            str(row["vault"]),
            str(row["family"]),
            int(row.get("ts_ms") or row.get("window_start_ms") or 0),
            str(row.get("hash") or ""),
        ),
    )
    market_context_rows = sorted(
        market_context.values(),
        key=lambda row: (
            int(row["observed_at_ms"]), str(row["family"]),
            str(row["instrument"]), int(row.get("event_ts_ms") or 0),
        ),
    )
    external_market_inventory_rows = list(audit.get("external_market_catalog_inventory") or [])
    required_market_families = set(_SAFE_MARKET_CONTEXT_FAMILIES)
    observed_market_families = {str(row["family"]) for row in market_context_rows}
    missing_market_families = sorted(required_market_families - observed_market_families)
    instruments_by_market_family = {
        family: {
            str(row["instrument"]) for row in market_context_rows
            if row.get("family") == family and str(row.get("instrument") or "")
        }
        for family in sorted(required_market_families)
    }
    instruments_with_all_market_families = (
        set.intersection(*instruments_by_market_family.values())
        if instruments_by_market_family and all(instruments_by_market_family.values())
        else set()
    )
    market_context_family_presence_complete = not missing_market_families
    market_context_coverage = {
        "status": (
            "REQUIRED_FAMILIES_PRESENT"
            if market_context_family_presence_complete else "PARTIAL"
        ),
        "family_presence_complete": market_context_family_presence_complete,
        "required_families": sorted(required_market_families),
        "observed_families": sorted(observed_market_families),
        "missing_families": missing_market_families,
        "observation_count": len(market_context_rows),
        "distinct_instruments_by_family": {
            family: len(instruments)
            for family, instruments in sorted(instruments_by_market_family.items())
        },
        "instruments_with_all_required_families": len(instruments_with_all_market_families),
        "temporal_alignment_status": "NOT_PROVEN_BY_FAMILY_PRESENCE",
        "pnl_eligible": False,
    }
    known_external_venues = set(_SAFE_EXTERNAL_MARKET_VENUES)
    external_safe_by_venue = Counter()
    external_safe_by_family = Counter()
    external_catalog_safe_shards = 0
    external_catalog_replay_compatible_shards = 0
    for row in external_market_inventory_rows:
        venue = str(row.get("venue") or "")
        family = str(row.get("family") or "")
        safe_count = int(row.get("safe_catalog_shards", 0) or 0)
        external_catalog_safe_shards += safe_count
        external_catalog_replay_compatible_shards += int(
            row.get("replay_compatible_safe_catalog_shards", 0) or 0
        )
        if safe_count:
            external_safe_by_venue[venue] += safe_count
            external_safe_by_family[family] += safe_count
    external_safe_venues = set(external_safe_by_venue)
    missing_external_venues = sorted(known_external_venues - external_safe_venues)
    external_market_coverage = {
        "status": (
            "CATALOG_INVENTORY_ONLY" if external_catalog_safe_shards else "NO_SAFE_SHARDS"
        ),
        "supported_venues": sorted(known_external_venues),
        "venues_with_safe_catalog_shards": sorted(external_safe_venues),
        "venues_without_safe_catalog_shards": missing_external_venues,
        "catalog_safe_shards": external_catalog_safe_shards,
        "catalog_replay_compatible_safe_shards": external_catalog_replay_compatible_shards,
        "inventory_records": len(external_market_inventory_rows),
        "loaded_payload_rows": 0,
        "local_payloads_verified": False,
        "active_data_index": audit.get("external_market_catalog_inventory", [{}])[0].get(
            "active_data_index"
        ) if external_market_inventory_rows else str(
            (repository_root / "catalog" / "DATA_INDEX.json").resolve()
        ),
        "source_recovery_root": str(recovery_root.resolve()),
        "replay_eligible": False,
        "pnl_eligible": False,
        "forward_evidence_allowed": False,
    }
    nav_rows_by_identity: dict[tuple[Any, ...], dict[str, Any]] = {}
    for context_row in context_rows:
        nav_row = context_row.get("nav_snapshot")
        if not isinstance(nav_row, Mapping):
            continue
        identity = (
            nav_row["vault"], nav_row["ts_ms"], nav_row["nav_usd"],
            nav_row.get("source_raw_sha256"),
        )
        nav_rows_by_identity[identity] = dict(nav_row)
    nav_rows = sorted(nav_rows_by_identity.values(), key=lambda row: (row["ts_ms"], row["vault"]))
    historical_unique_fills = sum(bool(row.get("isSnapshot")) for row in fill_rows)
    materialized_tapes: dict[str, dict[str, Any]] = {}
    for name, rows in (
        ("vault_fills.jsonl", fill_rows),
        ("vault_snapshots.jsonl", nav_rows),
        ("copy_vault_l2_tape.jsonl", book_rows),
        ("copy_vault_context.jsonl", context_rows),
        ("copy_vault_l2_unexecutable.jsonl", unexecutable_l2_rows),
        ("copy_vault_unclassified_fills.jsonl", unclassified_fill_rows),
        ("copy_vault_funding_rates.jsonl", funding_rate_rows),
        ("copy_vault_accounting_context.jsonl", leader_accounting_rows),
        ("copy_vault_market_context.jsonl", market_context_rows),
        ("external_venue_safe_inventory.jsonl", external_market_inventory_rows),
    ):
        target = data_dir / name
        temporary = target.with_suffix(target.suffix + ".partial")
        if target.is_symlink() or temporary.is_symlink():
            raise OSError("refusing symlinked Copy-Vault replay tape")
        temporary.write_text(
            "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
        os.replace(temporary, target)
        materialized_tapes[name] = {
            "path": str(target.resolve()),
            "bytes": target.stat().st_size,
            "sha256": _sha256(target),
        }
    data_complete = (
        audit.get("status") == "SAFE_COMPLETE"
        and history_audit.get("status") in {"COMPLETE", "NOT_APPLICABLE"}
        and market_context_coverage.get("family_presence_complete") is True
        and wrapper_rejections == 0
        and not payload_audit
    )
    replay_inputs_available = bool(fill_rows and book_rows)
    status = (
        "READY" if replay_inputs_available and data_complete
        else "MORE_DATA" if replay_inputs_available
        else "UNMEASURABLE"
    )
    if status == "READY":
        reason = None
    elif audit.get("status") != "SAFE_COMPLETE":
        reason = audit.get("reason") or "LOCAL_SAFE_CORPUS_INCOMPLETE"
    elif wrapper_rejections:
        reason = "SAFE_WRAPPERS_REJECTED"
    elif payload_audit:
        reason = "SAFE_PAYLOAD_ROWS_REJECTED"
    elif market_context_coverage.get("family_presence_complete") is not True:
        reason = "REQUIRED_COPY_VAULT_MARKET_CONTEXT_MISSING_OR_PARTIAL"
    elif history_audit.get("status") not in {"COMPLETE", "NOT_APPLICABLE"}:
        reason = "HISTORICAL_BACKFILL_COVERAGE_PARTIAL_OR_UNKNOWN"
    else:
        reason = audit.get("reason") or "FILLS_OR_CAUSAL_L2_MISSING"
    result = {
        "status": status,
        "reason": reason,
        "source_recovery_root": str(recovery_root.resolve()),
        "active_data_index": str((repository_root / "catalog" / "DATA_INDEX.json").resolve()),
        "workspace_root": str(workspace.resolve()),
        "materialized_data_root": str(data_dir.resolve()),
        "verified_assets": audit.get("verified_safe_shards", len(assets)),
        "verified_copy_vault_assets_total": len(assets),
        "expected_safe_shards": audit.get("expected_safe_shards", 0),
        "missing_shards": audit.get("missing_count", 0),
        "expected_external_market_shards": audit.get("expected_external_market_shards", 0),
        "verified_external_market_shards": audit.get("verified_external_market_shards", 0),
        "missing_external_market_shards": audit.get("missing_external_market_shards", 0),
        "rejected_external_market_shards": audit.get("rejected_external_market_shards", 0),
        "partial_shards_excluded": audit.get("partial_rows_excluded", 0),
        "rejected_assets": audit.get("rejected_count", 0),
        "invalid_wrappers": wrapper_rejections,
        "payload_audit": dict(sorted(payload_audit.items())),
        "l2_rejection_audit": dict(sorted(l2_rejection_audit.items())),
        "payload_rejection_samples": payload_rejection_samples,
        "payload_rejected_records": sum(payload_audit.values()),
        "raw_frames": raw_frames,
        "source_observations_by_family": dict(sorted(source_counts_by_family.items())),
        "unique_fills": len(fill_rows),
        "historical_snapshot_shards": historical_snapshot_shards,
        "historical_fill_observations": historical_fill_observations,
        "historical_unique_fills": historical_unique_fills,
        "historical_coverage_audit": history_audit,
        "safe_funding_rate_observations": sum(
            row["record_type"] == "SETTLEMENT_RATE" for row in funding_rate_rows
        ),
        "safe_funding_coverage_receipts": sum(
            row["record_type"] == "COVERAGE_RECEIPT" for row in funding_rate_rows
        ),
        "safe_funding_rates_by_coin": dict(sorted(Counter(
            str(row["coin"]) for row in funding_rate_rows
            if row["record_type"] == "SETTLEMENT_RATE"
        ).items())),
        "safe_leader_accounting_events": sum(
            row["record_type"] == "LEADER_ACCOUNTING_EVENT"
            for row in leader_accounting_rows
        ),
        "safe_leader_accounting_coverage_receipts": sum(
            row["record_type"] == "COVERAGE_RECEIPT"
            for row in leader_accounting_rows
        ),
        "safe_funding_rate_tape_path": str(
            (data_dir / "copy_vault_funding_rates.jsonl").resolve()
        ),
        "safe_leader_accounting_tape_path": str(
            (data_dir / "copy_vault_accounting_context.jsonl").resolve()
        ),
        "safe_market_context_observations": len(market_context_rows),
        "safe_market_context_by_family": dict(sorted(Counter(
            str(row["family"]) for row in market_context_rows
        ).items())),
        "safe_market_context_coverage": market_context_coverage,
        "safe_market_context_tape_path": str(
            (data_dir / "copy_vault_market_context.jsonl").resolve()
        ),
        "safe_external_market_inventory_shards": external_catalog_safe_shards,
        "safe_external_market_inventory_by_venue": dict(sorted(
            external_safe_by_venue.items()
        )),
        "safe_external_market_inventory_by_family": dict(sorted(
            external_safe_by_family.items()
        )),
        "safe_external_market_inventory_coverage": external_market_coverage,
        "safe_external_market_inventory_tape_path": str(
            (data_dir / "external_venue_safe_inventory.jsonl").resolve()
        ),
        "funding_rate_economic_application": (
            "NOT_APPLIED_V21_REQUIRES_ORACLE_PRICE_AND_POSITION_BOUND_SETTLEMENT"
        ),
        "incremental_unique_fills": len(fill_rows) - historical_unique_fills,
        "historical_fills_train_only": True,
        "snapshots_forward_evidence_allowed": False,
        "unique_books": len(book_rows),
        "unexecutable_l2_observations": len(unexecutable_l2_rows),
        "unexecutable_l2_by_reason": dict(sorted(Counter(
            str(row["reason"]) for row in unexecutable_l2_rows
        ).items())),
        "unexecutable_l2_tape_path": str((data_dir / "copy_vault_l2_unexecutable.jsonl").resolve()),
        "unclassified_fill_observations": len(unclassified_fill_rows),
        "unclassified_fill_by_reason": dict(sorted(Counter(
            str(row["reason"]) for row in unclassified_fill_rows
        ).items())),
        "unclassified_fill_tape_path": str((data_dir / "copy_vault_unclassified_fills.jsonl").resolve()),
        "safe_context_observations": len(context_rows),
        "safe_context_by_family": dict(sorted(Counter(
            str(row["family"]) for row in context_rows
        ).items())),
        "safe_context_tape_path": str((data_dir / "copy_vault_context.jsonl").resolve()),
        "safe_context_start_ms": context_rows[0]["observed_at_ms"] if context_rows else None,
        "safe_context_end_ms": context_rows[-1]["observed_at_ms"] if context_rows else None,
        "nav_snapshot_observations": len(nav_rows),
        "nav_snapshot_start_ms": nav_rows[0]["ts_ms"] if nav_rows else None,
        "nav_snapshot_end_ms": nav_rows[-1]["ts_ms"] if nav_rows else None,
        "nav_snapshot_tape_path": str((data_dir / "vault_snapshots.jsonl").resolve()),
        "fill_start_ms": fill_rows[0]["ts_ms"] if fill_rows else None,
        "fill_end_ms": fill_rows[-1]["ts_ms"] if fill_rows else None,
        "book_start_ms": book_rows[0]["received_at_ms"] if book_rows else None,
        "book_end_ms": book_rows[-1]["received_at_ms"] if book_rows else None,
        "data_complete": data_complete,
        "replay_inputs_available": replay_inputs_available,
        "materialized_tapes": materialized_tapes,
        "safe_catalog_status": audit.get("status"),
        "paper_read_only": True,
        "real_execution": False,
        **{
            key: value for key, value in audit.items()
            if not key.startswith("_") and key not in {"status", "reason"}
        },
    }
    _atomic_json(workspace / "SAFE_INPUT_MANIFEST.json", result)
    if audit.get("_watch_files") is not None:
        result["_watch_files"] = audit["_watch_files"]
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


def _bounds(timestamps: list[int]) -> dict[str, int | bool | str] | None:
    """Split by UTC day and purge the longest searched holding horizon."""
    day_ms = 86_400_000
    # The search includes holding horizons up to four hours. Purge at least
    # the maximum candidate horizon so replayed positions cannot cross a split.
    purge_ms = (
        max(dict(_PARAMETER_DOMAINS)["horizon_ms"])
        + int(cv.COPY_DELAY_MS)
        + int(cv.MAX_TARGET_LAG_MS)
    )
    days = sorted({int(timestamp) // day_ms for timestamp in timestamps if int(timestamp) > 0})
    if len(days) < _MINIMUM_SIGNAL_UTC_DAYS:
        return None
    train_cut = max(2, int(len(days) * 0.60))
    validation_cut = max(train_cut + 1, int(len(days) * 0.80))
    if validation_cut >= len(days):
        return None
    validation_boundary = days[train_cut] * day_ms
    oos_boundary = days[validation_cut] * day_ms
    result: dict[str, int | bool | str] = {
        "train_start_ms": days[0] * day_ms,
        "train_end_ms": validation_boundary - purge_ms - 1,
        "validation_start_ms": validation_boundary + purge_ms,
        "validation_end_ms": oos_boundary - purge_ms - 1,
        "oos_start_ms": oos_boundary + purge_ms,
        "oos_end_ms": max(int(timestamp) for timestamp in timestamps),
        "purge_ms": purge_ms,
        "split_unit": "UTC_DAY",
        "validation_empty_after_purge": False,
    }
    if not (
        int(result["train_start_ms"]) < int(result["train_end_ms"])
        < int(result["validation_start_ms"]) < int(result["validation_end_ms"])
        < int(result["oos_start_ms"]) <= int(result["oos_end_ms"])
    ):
        return None
    return result


def _signal_coverage(timestamps: list[int]) -> dict[str, int | float | None]:
    """Describe actual leader-signal coverage used by the temporal split."""
    valid = sorted(
        {timestamp for timestamp in timestamps if type(timestamp) is int and timestamp > 0}
    )
    day_ms = 86_400_000
    distinct_days = len({timestamp // day_ms for timestamp in valid})
    return {
        "distinct_utc_days": distinct_days,
        "minimum_utc_days_required": _MINIMUM_SIGNAL_UTC_DAYS,
        "signal_start_ms": valid[0] if valid else None,
        "signal_end_ms": valid[-1] if valid else None,
        "signal_span_hours": round((valid[-1] - valid[0]) / 3_600_000, 3) if valid else None,
    }


def _radical_inverse(index: int, base: int) -> float:
    value = 0.0
    factor = 1.0 / base
    remaining = int(index)
    while remaining:
        remaining, digit = divmod(remaining, base)
        value += digit * factor
        factor /= base
    return value


def _candidate_parameters(sequence_index: int) -> dict[str, Any] | None:
    if sequence_index <= 0:
        raise ValueError("candidate sequence index must be positive")
    params: dict[str, Any] = {}
    for (name, domain), base in zip(_PARAMETER_DOMAINS, _HALTON_BASES, strict=True):
        position = min(len(domain) - 1, int(_radical_inverse(sequence_index, base) * len(domain)))
        params[name] = domain[position]
    if params["core_notional_usd"] + params["probe_notional_usd"] > PAPER_CAPITAL_USD:
        return None
    return params


def _search_space_size() -> int:
    core = dict(_PARAMETER_DOMAINS)["core_notional_usd"]
    probe = dict(_PARAMETER_DOMAINS)["probe_notional_usd"]
    valid_size_pairs = sum(1 for left in core for right in probe if left + right <= PAPER_CAPITAL_USD)
    remaining_dimensions = math.prod(len(domain) for _name, domain in _PARAMETER_DOMAINS[2:])
    return valid_size_pairs * remaining_dimensions


def _candidate(
    params: dict[str, Any], bounds: Mapping[str, Any], frozen_at_ms: int,
    candidate_id: str, trial_count: int,
) -> dict[str, Any]:
    parameters = {
        "protocol": "copy_v21_entry_capacity_daily_lock_v1",
        "training_selection_eligible": True,
        "paper_read_only": True,
        "real_execution": False,
        "minimum_leader_fill_notional_usd": params["minimum_leader_fill_notional_usd"],
        "signed_depth_imbalance_minimum": params["signed_depth_imbalance_minimum"],
        "core_notional_usd": params["core_notional_usd"],
        "probe_notional_usd": params["probe_notional_usd"],
        "daily_profit_lock_usd": params["daily_profit_lock_usd"],
        "stop_loss_bps": params["stop_loss_bps"],
        "take_profit_bps": params["take_profit_bps"],
        "horizon_ms": params["horizon_ms"],
        "vault_daily_limit": params["vault_daily_limit"],
        "coin_daily_limit": params["coin_daily_limit"],
        "max_open_positions": params["max_open_positions"],
        "bonferroni_trial_count": max(1, int(trial_count)),
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


def _append_jsonl(path: Path, record: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise OSError("refusing symlinked append-only trial ledger")
    line = json.dumps(record, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def _load_campaign_trials(path: Path, selection_digest: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    if path.is_symlink() or not path.is_file():
        raise ValueError("unsafe Copy-Vault trial ledger")
    rows: list[dict[str, Any]] = []
    signatures: set[str] = set()
    sequences: set[int] = set()
    with path.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            try:
                row = json.loads(line)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"trial ledger corrupted at line {number}") from exc
            if (
                not isinstance(row, dict)
                or row.get("schema") != "hypersmart.copy_vault_local_trial.v1"
                or row.get("selection_digest") != selection_digest
                or not isinstance(row.get("parameter_signature"), str)
                or not isinstance(row.get("parameters"), dict)
                or row.get("parameter_signature") != parameter_hash(row["parameters"])
                or type(row.get("sequence_index")) is not int
                or row.get("sequence_index", 0) <= 0
                or type(row.get("trial_number")) is not int
                or row.get("trial_number", 0) <= 0
                or row.get("paper_read_only") is not True
                or row.get("real_execution") is not False
                or row.get("parameter_signature") in signatures
                or row.get("sequence_index") in sequences
            ):
                raise ValueError(f"trial ledger identity mismatch at line {number}")
            signatures.add(row["parameter_signature"])
            sequences.add(row["sequence_index"])
            rows.append(row)
    return rows


def _prior_copy_vault_trial_count(
    root: Path,
    *,
    exclude_selection_digest: str | None = None,
) -> int | None:
    ledger = root / "runtime" / "codex_research" / "HYPOTHESIS_LEDGER.jsonl"
    if ledger.is_symlink() or not ledger.is_file():
        return None
    total = 0
    with ledger.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            try:
                row = json.loads(line)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"hypothesis ledger corrupted at line {number}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"hypothesis ledger row invalid at line {number}")
            if row.get("family") != "copy_vault":
                continue
            count = row.get("trial_count")
            if type(count) is not int or count < 0:
                raise ValueError(f"Copy-Vault trial count invalid at line {number}")
            total += count
    campaign_root = root / "runtime" / "codex_research" / "copy_vault_continuous_lab"
    if campaign_root.is_symlink():
        raise ValueError("Copy-Vault campaign root is symlinked")
    if campaign_root.is_dir():
        for campaign in campaign_root.iterdir():
            if campaign.is_symlink():
                raise ValueError("prior Copy-Vault campaign directory is symlinked")
            if not campaign.is_dir():
                continue
            if campaign.name == exclude_selection_digest:
                continue
            trial_path = campaign / "TRIALS.jsonl"
            if not trial_path.exists():
                checkpoint_path = campaign / "CHECKPOINT.json"
                if checkpoint_path.is_symlink():
                    raise ValueError("prior Copy-Vault checkpoint is symlinked")
                if checkpoint_path.is_file():
                    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                    if int(checkpoint.get("campaign_trials") or 0) > 0:
                        raise ValueError("prior Copy-Vault trial receipts are missing")
                continue
            if trial_path.is_symlink() or not trial_path.is_file():
                raise ValueError("unsafe prior Copy-Vault trial history")
            campaign_trial_count = len(_load_campaign_trials(trial_path, campaign.name))
            total += campaign_trial_count
            checkpoint_path = campaign / "CHECKPOINT.json"
            if checkpoint_path.is_symlink():
                raise ValueError("prior Copy-Vault checkpoint is symlinked")
            if checkpoint_path.is_file():
                checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                checkpoint_count = checkpoint.get("campaign_trials")
                if (
                    checkpoint.get("schema") != "hypersmart.copy_vault_search_checkpoint.v1"
                    or checkpoint.get("selection_digest") != campaign.name
                    or type(checkpoint_count) is not int
                    or checkpoint_count < 0
                    or checkpoint_count > campaign_trial_count
                ):
                    raise ValueError("prior Copy-Vault checkpoint conflicts with durable trial receipts")
    return total


def _daily_lcb(daily_values: object, trial_count: int) -> float | None:
    if not isinstance(daily_values, (list, tuple)):
        return None
    values: list[float] = []
    for raw in daily_values:
        try:
            value = float(raw)
        except (TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(value):
            return None
        values.append(value)
    if len(values) < 3:
        return None
    alpha = min(0.499999, max(1e-12, 0.05 / max(1, trial_count)))
    z = NormalDist().inv_cdf(1.0 - alpha)
    mean = statistics.mean(values)
    standard_error = statistics.stdev(values) / math.sqrt(len(values))
    return mean - z * standard_error


def _campaign_lock(path: Path) -> SingleWriterFileLock:
    lock = SingleWriterFileLock(path)
    try:
        lock.acquire()
    except WriterBusy as exc:
        raise RuntimeError("COPY_VAULT_CAMPAIGN_ALREADY_RUNNING") from exc
    except OSError as exc:
        raise RuntimeError("COPY_VAULT_CAMPAIGN_LOCK_UNREADABLE") from exc
    return lock


def run_local_campaign(
    workspace: str | Path,
    *,
    progress: Callable[[str], None] | None = None,
    continuous: bool = False,
    campaign_root: str | Path | None = None,
    max_trials: int = 128,
    on_update: Callable[[Mapping[str, Any]], None] | None = None,
    input_change_check: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    workspace = Path(workspace)
    say = progress or (lambda _message: None)
    manifest_path = workspace / "SAFE_INPUT_MANIFEST.json"
    try:
        input_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        return {
            "status": "UNMEASURABLE", "reason": f"LOCAL_SAFE_MANIFEST_UNAVAILABLE:{type(exc).__name__}",
            "candidates_tested": 0, "freeze_created": False, "economically_proven": False,
        }
    selection_digest = str(input_manifest.get("selection_digest") or "")
    source_catalog_sha = str(input_manifest.get("source_index_sha256") or "").lower()
    if (
        input_manifest.get("paper_read_only") is not True
        or input_manifest.get("real_execution") is not False
        or len(selection_digest) != 64
        or any(char not in "0123456789abcdef" for char in selection_digest.lower())
        or len(source_catalog_sha) != 64
        or any(char not in "0123456789abcdef" for char in source_catalog_sha)
        or input_manifest.get("status") not in {"READY", "MORE_DATA"}
        or input_manifest.get("safe_catalog_status") not in {"SAFE_COMPLETE", "SAFE_PARTIAL"}
        or input_manifest.get("replay_inputs_available") is not True
        or type(input_manifest.get("unique_fills")) is not int
        or input_manifest.get("unique_fills", 0) <= 0
        or type(input_manifest.get("unique_books")) is not int
        or input_manifest.get("unique_books", 0) <= 0
    ):
        return {
            "status": "UNMEASURABLE", "reason": "LOCAL_SAFE_MANIFEST_INVALID",
            "candidates_tested": 0, "freeze_created": False, "economically_proven": False,
        }
    tape_error = _verify_materialized_tapes(workspace, input_manifest)
    if tape_error is not None:
        return {
            "status": "UNMEASURABLE", "reason": tape_error,
            "selection_digest": selection_digest,
            "candidates_tested": 0, "freeze_created": False,
            "economically_proven": False, "paper_read_only": True,
            "real_execution": False,
        }
    pipeline = _load_pipeline()
    say("Reconstruction des cycles leader OPEN/ADD/REDUCE/CLOSE")
    entries, entries_audit = pipeline.charger_entrees_alpha_notional_fixe_avec_audit(workspace)
    metaorders, meta_audit = cv.cluster_metaorders(entries)
    books, books_audit = cv.load_observed_books(workspace, coins={str(row["coin"]) for row in metaorders})
    timestamps = [int(row["signal_ts_ms"]) for row in metaorders]
    bounds = _bounds(timestamps)
    signal_coverage = _signal_coverage(timestamps)
    aligned_adds = 0
    if metaorders and books:
        for row in metaorders:
            if str(row.get("action") or "").upper() != "ADD":
                continue
            timestamps_for_coin = [int(book["ts_ms"]) for book in books.get(str(row["coin"]), [])]
            signal_ms = int(row["signal_ts_ms"])
            index = bisect.bisect_right(timestamps_for_coin, signal_ms) - 1
            if index >= 0 and signal_ms - timestamps_for_coin[index] <= 30_000:
                aligned_adds += 1
    base = {
        "paper_read_only": True, "real_execution": False,
        "objective_usd_per_day": OBJECTIVE_USD_PER_DAY,
        "paper_capital_usd": PAPER_CAPITAL_USD,
        "selection_digest": selection_digest,
        "source_catalog_sha256": input_manifest.get("source_index_sha256"),
        "input_data_complete": input_manifest.get("data_complete") is True,
        "expected_safe_shards": input_manifest.get("expected_safe_shards"),
        "copy_vault_safe_catalog_shards": input_manifest.get("copy_vault_safe_catalog_shards"),
        "safe_copy_vault_shards_not_used_for_pnl": input_manifest.get(
            "safe_copy_vault_shards_not_used_for_pnl"
        ),
        "safe_copy_vault_shards_not_used_for_pnl_by_family": input_manifest.get(
            "safe_copy_vault_shards_not_used_for_pnl_by_family", {}
        ),
        "safe_copy_vault_shards_not_used_for_pnl_inventory_by_family": input_manifest.get(
            "safe_copy_vault_shards_not_used_for_pnl_inventory_by_family", {}
        ),
        "safe_copy_vault_shards_not_used_for_pnl_reason_by_family": input_manifest.get(
            "safe_copy_vault_shards_not_used_for_pnl_reason_by_family", {}
        ),
        "safe_context_observations": input_manifest.get("safe_context_observations", 0),
        "safe_context_by_family": input_manifest.get("safe_context_by_family", {}),
        "safe_context_expected_by_family": input_manifest.get("safe_context_expected_by_family", {}),
        "safe_context_verified_by_family": input_manifest.get("safe_context_verified_by_family", {}),
        "safe_context_missing_by_family": input_manifest.get("safe_context_missing_by_family", {}),
        "safe_context_rejected_by_family": input_manifest.get("safe_context_rejected_by_family", {}),
        "safe_context_tape_path": input_manifest.get("safe_context_tape_path"),
        "safe_funding_rate_observations": input_manifest.get(
            "safe_funding_rate_observations", 0
        ),
        "safe_funding_coverage_receipts": input_manifest.get(
            "safe_funding_coverage_receipts", 0
        ),
        "safe_funding_rates_by_coin": input_manifest.get(
            "safe_funding_rates_by_coin", {}
        ),
        "safe_funding_rate_tape_path": input_manifest.get(
            "safe_funding_rate_tape_path"
        ),
        "funding_rate_economic_application": input_manifest.get(
            "funding_rate_economic_application"
        ),
        "safe_leader_accounting_events": input_manifest.get(
            "safe_leader_accounting_events", 0
        ),
        "safe_leader_accounting_coverage_receipts": input_manifest.get(
            "safe_leader_accounting_coverage_receipts", 0
        ),
        "safe_leader_accounting_tape_path": input_manifest.get(
            "safe_leader_accounting_tape_path"
        ),
        "nav_snapshot_observations": input_manifest.get("nav_snapshot_observations", 0),
        "nav_snapshot_tape_path": input_manifest.get("nav_snapshot_tape_path"),
        "verified_safe_shards": input_manifest.get("verified_assets"),
        "missing_safe_shards": input_manifest.get("missing_shards"),
        "entries": len(entries), "metaorders": len(metaorders),
        "live_fill_rows": entries_audit.get("live_fill_rows"),
        "causal_live_fill_rows": entries_audit.get("causal_live_fill_rows"),
        "historical_fill_rows": entries_audit.get("historical_fill_rows"),
        "book_rows": sum(len(rows) for rows in books.values()),
        "signal_coverage": signal_coverage,
        "temporally_aligned_add_signals": aligned_adds,
        "input_audit": {"entries": entries_audit, "metaorders": meta_audit, "books": books_audit},
    }
    if not metaorders or not books:
        return {
            **base, "status": "MORE_DATA" if metaorders or books else "UNMEASURABLE",
            "reason": "INSUFFICIENT_REPLAY_INPUTS", "candidates_tested": 0,
            "freeze_created": False, "economically_proven": False,
        }
    if aligned_adds == 0:
        causal_live_fill_rows = entries_audit.get("causal_live_fill_rows")
        reason = (
            "NO_SAFE_LIVE_FORWARD_FILLS"
            if type(causal_live_fill_rows) is int and causal_live_fill_rows == 0
            else "NO_CAUSAL_L2_AT_OR_BEFORE_SIGNAL_WITHIN_30_SECONDS"
        )
        return {
            **base,
            "status": "MORE_DATA",
            "reason": reason,
            "alignment_reason": "NO_CAUSAL_L2_AT_OR_BEFORE_SIGNAL_WITHIN_30_SECONDS",
            "candidates_tested": 0,
            "freeze_created": False,
            "economically_proven": False,
        }
    if signal_coverage["distinct_utc_days"] < _MINIMUM_SIGNAL_UTC_DAYS:
        return {
            **base,
            "status": "MORE_DATA",
            "reason": "INSUFFICIENT_DISTINCT_SIGNAL_DAYS",
            "candidates_tested": 0,
            "freeze_created": False,
            "economically_proven": False,
        }
    if bounds is None:
        return {
            **base,
            "status": "MORE_DATA",
            "reason": "TEMPORAL_SPLIT_INVALID_AFTER_PURGE",
            "candidates_tested": 0,
            "freeze_created": False,
            "economically_proven": False,
        }
    repository_root = Path(__file__).resolve().parents[3]
    campaign_root = Path(campaign_root) if campaign_root else (
        repository_root / "runtime" / "codex_research" / "copy_vault_continuous_lab" / selection_digest
    )
    campaign_root.mkdir(parents=True, exist_ok=True)
    trial_path = campaign_root / "TRIALS.jsonl"
    checkpoint_path = campaign_root / "CHECKPOINT.json"
    lock_path = (
        repository_root / "runtime" / "codex_research"
        / "copy_vault_continuous_lab" / ".active.lock"
    )
    try:
        campaign_lock = _campaign_lock(lock_path)
    except RuntimeError as exc:
        return {**base, "status": "TECHNICAL_FAILURE", "reason": str(exc), "candidates_tested": 0}
    try:
        prior_trial_count = _prior_copy_vault_trial_count(
            repository_root,
            exclude_selection_digest=selection_digest,
        )
        history_rows = _load_campaign_trials(trial_path, selection_digest)
        seen = {str(row["parameter_signature"]) for row in history_rows}
        sequence_index = max(
            (int(row.get("sequence_index") or 0) for row in history_rows), default=0
        ) + 1
        best = None
        if checkpoint_path.is_file() and not checkpoint_path.is_symlink():
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            if (
                checkpoint.get("schema") != "hypersmart.copy_vault_search_checkpoint.v1"
                or checkpoint.get("selection_digest") != selection_digest
            ):
                raise ValueError("Copy-Vault checkpoint does not match this SAFE selection")
            sequence_index = max(sequence_index, int(checkpoint.get("next_sequence_index") or 1))
            best = checkpoint.get("best_candidate") if isinstance(checkpoint.get("best_candidate"), dict) else None
        if best is None:
            frozen_rows = [
                row for row in history_rows
                if row.get("strict_improvement_over_baseline_and_prior_best") is True
                and row.get("frozen_record") is not None
                and isinstance(row.get("daily_lcb_usd_per_active_day"), (int, float))
                and not isinstance(row.get("daily_lcb_usd_per_active_day"), bool)
                and math.isfinite(float(row.get("daily_lcb_usd_per_active_day")))
            ]
            if frozen_rows:
                recovered = max(
                    frozen_rows,
                    key=lambda row: float(row.get("daily_lcb_usd_per_active_day")),
                )
                recovered_sequence = int(recovered["sequence_index"])
                recovered_trial = int(recovered["trial_number"])
                recovered_id = f"cv-{selection_digest[:12]}-{recovered_sequence:012d}"
                recovered_params = dict(recovered["parameters"])
                recovered_train = {
                    "daily_mean_net_pnl_usd": recovered.get("daily_mean_usd_per_active_day"),
                    "active_day_mean_net_pnl_usd": recovered.get("daily_mean_usd_per_active_day"),
                    "statistics": {
                        "sample_count": recovered.get("closed_trade_count"),
                        "distinct_days": recovered.get("active_day_count"),
                        "daily_net_pnl_usd": recovered.get("daily_net_pnl_usd"),
                    },
                    "eligible": True,
                    "candidate_count": recovered.get("candidate_count"),
                }
                best = {
                    "candidate_id": recovered_id,
                    "candidate": _candidate(
                        recovered_params, bounds, max(timestamps) + 1,
                        recovered_id, recovered_trial,
                    ),
                    "train": recovered_train,
                    "daily_net_pnl_usd": list(recovered.get("daily_net_pnl_usd") or []),
                    "score_usd_per_active_day": float(recovered["daily_lcb_usd_per_active_day"]),
                    "trial_number": recovered_trial,
                }
        trial_limit = None if continuous else max(1, int(max_trials))
        search_space_size = _search_space_size()
        prior_count_known = prior_trial_count is not None
        prior_trial_count = int(prior_trial_count or 0)
        baseline_train: dict[str, Any] | None = None
        baseline_comparison_basis = "CURRENT_COPY_VAULT_SETTINGS_NORMALIZED_TO_200_USD"
        freeze_path = repository_root / "runtime" / "codex_research" / "COPY_V21_PHYSICAL_FREEZE.json"
        try:
            current_freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
            params = dict(current_freeze.get("freeze", current_freeze).get("parameters") or {})
            core_notional = _number(params["core_notional_usd"])
            probe_notional = _number(params["probe_notional_usd"])
            total_notional = core_notional + probe_notional
            if total_notional <= 0.0:
                raise ValueError("CURRENT_COPY_VAULT_BASELINE_NOTIONAL_INVALID")
            sizing_scale = min(1.0, PAPER_CAPITAL_USD / total_notional)
            if sizing_scale < 1.0:
                params["core_notional_usd"] = core_notional * sizing_scale
                params["probe_notional_usd"] = probe_notional * sizing_scale
                params["daily_profit_lock_usd"] = (
                    _number(params["daily_profit_lock_usd"]) * sizing_scale
                )
            params["bounds"] = dict(bounds)
            params["bonferroni_trial_count"] = max(1, prior_trial_count + len(history_rows) + 1)
            rebased = dict(current_freeze.get("freeze", current_freeze))
            rebased.update({
                "frozen_at_ms": max(timestamps) + 1,
                "parameters": params,
                "parameters_sha256": parameter_hash(params),
            })
            baseline_train = evaluate_frozen_v21_segment(
                metaorders, books, {"freeze": rebased}, segment="train"
            )
        except (OSError, ValueError, TypeError, KeyError, RuntimeError):
            baseline_train = None
            baseline_comparison_basis = "CURRENT_COPY_VAULT_BASELINE_UNMEASURABLE"
        base["baseline_comparison_basis"] = baseline_comparison_basis

        completed_this_run = 0
        duplicates_since_checkpoint = 0
        baseline_days = (
            (baseline_train.get("statistics") or {}).get("daily_net_pnl_usd")
            if baseline_train else None
        )
        best_days = (
            best.get("daily_net_pnl_usd") if isinstance(best, dict) else None
        )
        if best_days is None and isinstance(best, dict):
            best_days = (best.get("train") or {}).get("daily_net_pnl_usd")
        status = "SEARCH_RUNNING"
        reason = "TRAIN_ONLY_SEARCH_CONTINUES_UNTIL_CTRL_C" if continuous else "BOUNDED_TRAIN_SEARCH_BATCH_COMPLETE"
        while trial_limit is None or completed_this_run < trial_limit:
            if len(seen) >= search_space_size:
                status, reason = "SEARCH_SPACE_EXHAUSTED", "ALL_VALID_PARAMETER_CONFIGURATIONS_ALREADY_TRIED"
                break
            if _candidate_parameters(sequence_index) is None:
                sequence_index += 1
                duplicates_since_checkpoint += 1
                if duplicates_since_checkpoint >= 1_000:
                    _atomic_json(checkpoint_path, {
                        "schema": "hypersmart.copy_vault_search_checkpoint.v1",
                        "selection_digest": selection_digest,
                        "next_sequence_index": sequence_index,
                        "campaign_trials": len(history_rows),
                        "best_candidate": best,
                        "status": status,
                    })
                    duplicates_since_checkpoint = 0
                continue
            params = _candidate_parameters(sequence_index)
            assert params is not None
            this_sequence = sequence_index
            sequence_index += 1
            signature = parameter_hash(params)
            if signature in seen:
                duplicates_since_checkpoint += 1
                if input_change_check is not None and completed_this_run % 25 == 0 and input_change_check():
                    status, reason = "DATASET_CHANGED", "LOCAL_SAFE_INPUTS_CHANGED_DURING_SEARCH"
                    break
                continue
            trial_count = prior_trial_count + len(history_rows) + 1
            candidate_id = f"cv-{selection_digest[:12]}-{this_sequence:012d}"
            freeze = _candidate(params, bounds, max(timestamps) + 1, candidate_id, trial_count)
            say(
                f"Essai {trial_count} · séquence {this_sequence:,} · "
                f"{len(_PARAMETER_DOMAINS)} paramètres · capital {params['core_notional_usd'] + params['probe_notional_usd']:.0f}/200 USD"
            )
            train = evaluate_frozen_v21_segment(metaorders, books, freeze, segment="train")
            stats = train.get("statistics") if isinstance(train.get("statistics"), Mapping) else {}
            daily_values = list(stats.get("daily_net_pnl_usd") or [])
            candidate_score = _daily_lcb(daily_values, trial_count)
            baseline_score = _daily_lcb(baseline_days, trial_count)
            incumbent_score = _daily_lcb(best_days, trial_count)
            comparison_floor = max(
                value for value in (baseline_score, incumbent_score) if value is not None
            ) if any(value is not None for value in (baseline_score, incumbent_score)) else None
            improvement = (
                train.get("eligible") is True
                and candidate_score is not None
                and comparison_floor is not None
                and candidate_score > comparison_floor + 1e-12
                and prior_count_known
            )
            trial = {
                "schema": "hypersmart.copy_vault_local_trial.v1",
                "selection_digest": selection_digest,
                "source_catalog_sha256": input_manifest.get("source_index_sha256"),
                "sequence_index": this_sequence,
                "trial_number": trial_count,
                "parameter_signature": signature,
                "parameters": params,
                "status": "ELIGIBLE" if train.get("eligible") is True else "REJECTED_BY_TRAIN_GATES",
                "train_reasons": list(train.get("reasons") or []),
                "candidate_count": int(train.get("candidate_count") or 0),
                "closed_trade_count": int(stats.get("sample_count") or 0),
                "active_day_count": int(stats.get("distinct_days") or 0),
                "daily_mean_usd_per_active_day": train.get("active_day_mean_net_pnl_usd"),
                "daily_lcb_usd_per_active_day": candidate_score,
                "daily_net_pnl_usd": daily_values,
                "baseline_lcb_usd_per_active_day": baseline_score,
                "baseline_comparison_basis": baseline_comparison_basis,
                "strict_improvement_over_baseline_and_prior_best": bool(improvement),
                "bonferroni_trial_count": trial_count,
                "data_complete": input_manifest.get("data_complete") is True,
                "paper_read_only": True,
                "real_execution": False,
            }
            frozen_record = None
            if improvement:
                frozen_result = {
                    "freeze_created": True,
                    "economically_proven": False,
                    "status": "CANDIDATE_FROZEN_TRAIN_ONLY" if input_manifest.get("data_complete") is True else "CANDIDATE_FROZEN_INCOMPLETE_SAFE_CORPUS",
                    "selected_candidate": freeze,
                    "train": train,
                    "comparison": {
                        "metric": "BONFERRONI_LCB_USD_PER_ACTIVE_TRAIN_DAY",
                        "baseline_score": baseline_score,
                        "candidate_score": candidate_score,
                        "improvement": candidate_score - comparison_floor,
                        "baseline_daily_mean": baseline_train.get("active_day_mean_net_pnl_usd") if baseline_train else None,
                        "candidate_daily_mean": train.get("active_day_mean_net_pnl_usd"),
                        "prior_best_score": incumbent_score,
                        "trial_count": trial_count,
                        "baseline_comparison_basis": baseline_comparison_basis,
                    },
                    "selection_digest": selection_digest,
                    "source_catalog_sha256": input_manifest.get("source_index_sha256"),
                    "data_complete": input_manifest.get("data_complete") is True,
                    "heldout_evaluated": False,
                }
                current_for_record = {"train": baseline_train or {}}
                frozen_record = record_frozen_candidate(
                    repository_root, candidate_id, frozen_result, current_for_record
                )
                best = {
                    "candidate_id": candidate_id,
                    "candidate": freeze,
                    "train": {
                        "daily_mean_net_pnl_usd": train.get("daily_mean_net_pnl_usd"),
                        "active_day_mean_net_pnl_usd": train.get("active_day_mean_net_pnl_usd"),
                        "statistics": stats,
                        "eligible": train.get("eligible") is True,
                        "candidate_count": train.get("candidate_count"),
                    },
                    "daily_net_pnl_usd": daily_values,
                    "score_usd_per_active_day": candidate_score,
                    "trial_number": trial_count,
                }
                best_days = daily_values
                say(f"CANDIDAT GELÉ · {candidate_id} · amélioration conservative {candidate_score - comparison_floor:+.6f} USD/jour actif TRAIN")
            trial["frozen_record"] = frozen_record
            _append_jsonl(trial_path, trial)
            history_rows.append(trial)
            seen.add(signature)
            completed_this_run += 1
            _atomic_json(checkpoint_path, {
                "schema": "hypersmart.copy_vault_search_checkpoint.v1",
                "selection_digest": selection_digest,
                "source_catalog_sha256": input_manifest.get("source_index_sha256"),
                "next_sequence_index": sequence_index,
                "campaign_trials": len(history_rows),
                "global_trial_count": trial_count,
                "best_candidate": best,
                "status": status,
                "updated_at_utc": datetime.now(UTC).isoformat(),
                "paper_read_only": True,
                "real_execution": False,
            })
            update = {
                **base,
                "status": status,
                "reason": reason,
                "candidates_tested": len(history_rows),
                "trials_this_run": completed_this_run,
                "global_trial_count": trial_count,
                "search_space_upper_bound": search_space_size,
                "best_candidate": best,
                "baseline_train": baseline_train,
                "last_trial": trial,
                "freeze_created": best is not None,
                "economically_proven": False,
                "heldout_evaluated": False,
                "candidate_history_path": str(trial_path),
                "checkpoint_path": str(checkpoint_path),
                "data_complete": input_manifest.get("data_complete") is True,
                "paper_read_only": True,
                "real_execution": False,
            }
            if on_update is not None:
                on_update(update)
            if completed_this_run % 10 == 0:
                say(f"Progression · {len(history_rows):,} configurations uniques testées; tous les essais comptent pour la correction statistique.")
            if input_change_check is not None and completed_this_run % 25 == 0 and input_change_check():
                status, reason = "DATASET_CHANGED", "LOCAL_SAFE_INPUTS_CHANGED_DURING_SEARCH"
                break
        final_best_train = best.get("train") if isinstance(best, dict) else None
        return {
            **base,
            "status": status,
            "reason": reason,
            "candidates_tested": len(history_rows),
            "trials_this_run": completed_this_run,
            "global_trial_count": prior_trial_count + len(history_rows),
            "global_trial_count_source_known": prior_count_known,
            "search_space_upper_bound": search_space_size,
            "selected_candidate": best.get("candidate") if isinstance(best, dict) else None,
            "train": final_best_train,
            "baseline_train": baseline_train,
            "freeze_created": best is not None,
            "economically_proven": False,
            "heldout_evaluated": False,
            "candidate_history_path": str(trial_path),
            "checkpoint_path": str(checkpoint_path),
            "data_complete": input_manifest.get("data_complete") is True,
            "paper_read_only": True,
            "real_execution": False,
        }
    except KeyboardInterrupt:
        checkpoint = {}
        if checkpoint_path.is_file() and not checkpoint_path.is_symlink():
            try:
                checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                checkpoint = {}
        checkpoint.update({
            "schema": "hypersmart.copy_vault_search_checkpoint.v1",
            "selection_digest": selection_digest,
            "next_sequence_index": sequence_index if "sequence_index" in locals() else 1,
            "campaign_trials": len(locals().get("history_rows", [])),
            "best_candidate": locals().get("best"),
            "status": "INTERRUPTED",
            "updated_at_utc": datetime.now(UTC).isoformat(),
            "paper_read_only": True,
            "real_execution": False,
        })
        _atomic_json(checkpoint_path, checkpoint)
        return {
            **base,
            "status": "INTERRUPTED",
            "reason": "USER_CTRL_C_COMPLETED_TRIALS_CHECKPOINTED",
            "candidates_tested": len(locals().get("history_rows", [])),
            "selected_candidate": (locals().get("best") or {}).get("candidate")
            if isinstance(locals().get("best"), dict) else None,
            "freeze_created": bool(locals().get("best")),
            "economically_proven": False,
            "heldout_evaluated": False,
            "candidate_history_path": str(trial_path),
            "checkpoint_path": str(checkpoint_path),
            "paper_read_only": True,
            "real_execution": False,
        }
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        return {
            **base, "status": "TECHNICAL_FAILURE", "reason": f"{type(exc).__name__}:{exc}",
            "candidates_tested": len(locals().get("history_rows", [])),
            "freeze_created": bool(locals().get("best")), "economically_proven": False,
        }
    finally:
        campaign_lock.release()


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
        input_manifest = json.loads((Path(workspace) / "SAFE_INPUT_MANIFEST.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        return {
            "status": "UNMEASURABLE", "reason": f"LOCAL_SAFE_MANIFEST_UNAVAILABLE:{type(exc).__name__}",
            "economically_proven": False, "paper_read_only": True, "real_execution": False,
        }
    tape_error = _verify_materialized_tapes(Path(workspace), input_manifest)
    if tape_error is not None:
        return {
            "status": "UNMEASURABLE", "reason": tape_error,
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


_RESTORATION_SNAPSHOT_FIELDS = (
    "code_sha",
    "config_sha",
    "data_manifest_sha256",
    "seed",
    "parameters",
    "windows",
    "capital_usd",
    "ledger",
    "equity",
    "costs",
    "metrics",
    "trial_count",
    "tests",
    "report",
    "restore_receipt",
)


def _restoration_snapshot(economic_result: Mapping[str, Any]) -> dict[str, Any]:
    """Record reproducibility fields without ever inferring missing evidence."""
    supplied = economic_result.get("reproducibility_snapshot")
    if not isinstance(supplied, Mapping):
        supplied = {}
    values = {
        field: supplied.get(field)
        for field in _RESTORATION_SNAPSHOT_FIELDS
    }
    missing = [
        field for field, value in values.items()
        if value is None or value == "" or value == [] or value == {}
    ]
    return {
        "schema_version": "hypersmart.copy_vault_restoration_snapshot.v1",
        "complete": not missing,
        "missing_fields": missing,
        "fields": values,
    }


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
    comparison = (
        dict(economic_result.get("comparison"))
        if isinstance(economic_result.get("comparison"), Mapping) else {}
    )
    score_improvement = comparison.get("improvement")
    try:
        score_improvement = float(score_improvement) if score_improvement is not None else None
    except (TypeError, ValueError, OverflowError):
        score_improvement = None
    if score_improvement is not None and not math.isfinite(score_improvement):
        score_improvement = None
    classification = (
        "ECONOMICALLY_PROVEN_IMPROVEMENT"
        if economic_result.get("economically_proven") is True and improvement is not None and improvement > 0
        else "CANDIDATE_FROZEN_TRAIN_SCORE_IMPROVEMENT_INCOMPLETE_DATA"
        if score_improvement is not None and score_improvement > 0 and economic_result.get("data_complete") is not True
        else "CANDIDATE_FROZEN_TRAIN_SCORE_IMPROVEMENT"
        if score_improvement is not None and score_improvement > 0
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
        "comparison": comparison,
        "selection_digest": economic_result.get("selection_digest"),
        "source_catalog_sha256": economic_result.get("source_catalog_sha256"),
        "data_complete": economic_result.get("data_complete") is True,
        "heldout_evaluated": economic_result.get("heldout_evaluated") is True,
        "trial_number": comparison.get("trial_count"),
        "economically_proven": economic_result.get("economically_proven") is True,
        "candidate_status": economic_result.get("status"),
        "candidate": economic_result.get("selected_candidate"),
        "restoration_snapshot": _restoration_snapshot(economic_result),
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
        if ledger.is_symlink():
            raise OSError("COPY_VAULT_IMPROVEMENT_HISTORY_SYMLINKED")
        with ledger.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    if classification == "ECONOMICALLY_PROVEN_IMPROVEMENT":
        champion = registry / "CURRENT_CHAMPION.json"
        temporary = champion.with_suffix(".json.partial")
        if champion.is_symlink() or temporary.is_symlink():
            raise OSError("COPY_VAULT_CURRENT_CHAMPION_SYMLINKED")
        temporary.write_text(serialized, encoding="utf-8")
        os.replace(temporary, champion)
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
            def predicate(
                row: Mapping[str, Any],
                field: str = field,
                threshold: float = threshold,
                direction: str = direction,
            ) -> bool:
                value = float(row[field])
                return value <= threshold if direction == "le" else value >= threshold

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
