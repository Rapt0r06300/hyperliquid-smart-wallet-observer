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
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from decimal import ROUND_FLOOR, Decimal, localcontext
from pathlib import Path, PurePosixPath
from typing import Any

from hl_observer.alerts.durability import SingleWriterFileLock, WriterBusy
from hl_observer.backtesting import copy_vault_executable as cv
from hl_observer.backtesting.copy_vault_protocol import canonical_copy_vault_coin
from hl_observer.backtesting.copy_vault_v21_frozen import (
    evaluate_frozen_v21,
    evaluate_frozen_v21_segment,
)
from hl_observer.backtesting.train_statistics import (
    lcb_rank_is_numerically_resolved,
    summarize_daily_values,
)
from hl_observer.collection.userfills_live import userfill_required_fields_reason
from hl_observer.datasets.v2_pipeline import copy_vault_heartbeat_reason
from hl_observer.economics.numeric import (
    USD_RECONCILIATION_ABS_TOLERANCE,
    decimal_difference,
    decimal_sum,
    decimal_value,
    float_not_above,
)
from hl_observer.normalization.l2_book import normalize_l2_levels
from hl_observer.simulation.economic_freeze_registry import parameter_hash
from tools.copy_vault_continuity import load_release_history_audits

OBJECTIVE_USD_PER_DAY = 5.0
PAPER_CAPITAL_USD = 200.0
_SAFE_AUDIT_CACHE_SCHEMA = "hypersmart.copy_vault_local_safe_hash_cache.v1"
_SAFE_FAMILIES = {
    "copy_vault_fills", "copy_vault_l2", "copy_vault_snapshot",
    "copy_vault_bbo", "copy_vault_trades", "copy_vault_active_asset_ctx",
    "copy_vault_funding", "copy_vault_ledger",
}
_CANONICAL_REPOSITORY = "Rapt0r06300/hyperliquid-smart-wallet-observer"
_MATERIALIZED_TAPE_NAMES = (
    "vault_fills.jsonl", "copy_vault_l2_tape.jsonl",
    "copy_vault_bbo_tape.jsonl", "copy_vault_trades_tape.jsonl",
    "copy_vault_active_asset_ctx_tape.jsonl",
    "copy_vault_funding_tape.jsonl", "copy_vault_ledger_tape.jsonl",
)
_MINIMUM_SIGNAL_UTC_DAYS = 6
_LEADER_REVIEW_MAX_EVIDENCE_AGE_MS = 30 * 24 * 60 * 60 * 1000
_TRIAL_CHAIN_GENESIS = "0" * 64
_IMPROVEMENT_CHAIN_GENESIS = "0" * 64
_IMPROVEMENT_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
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


def _canonical_json_sha256(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _campaign_engine_source_sha256(pipeline: object) -> str:
    """Bind a trial to the source files that define its active scoring path."""
    entry_loader = getattr(pipeline, "charger_entrees_alpha_notional_fixe_avec_audit", None)
    if entry_loader is None or not hasattr(entry_loader, "__code__"):
        raise ValueError("COPY_VAULT_PIPELINE_SOURCE_UNAVAILABLE")
    source_paths = {
        "local_lab": Path(__file__),
        "executable_replay": Path(cv.__file__),
        "frozen_v21": Path(evaluate_frozen_v21_segment.__code__.co_filename),
        "train_statistics": Path(summarize_daily_values.__code__.co_filename),
        "numeric_bounds": Path(float_not_above.__code__.co_filename),
        "l2_normalization": Path(normalize_l2_levels.__code__.co_filename),
        "freeze_identity": Path(parameter_hash.__code__.co_filename),
        "safe_release_catalog": Path(load_release_history_audits.__code__.co_filename),
        "entry_reconstruction": Path(entry_loader.__code__.co_filename),
    }
    components: list[dict[str, str]] = []
    for name, raw_path in sorted(source_paths.items()):
        if raw_path.is_symlink():
            raise ValueError(f"COPY_VAULT_ENGINE_SOURCE_INVALID:{name}")
        path = raw_path.resolve(strict=True)
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"COPY_VAULT_ENGINE_SOURCE_INVALID:{name}")
        components.append({"component": name, "sha256": _sha256(path)})
    return _canonical_json_sha256(components)


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
        if family not in _SAFE_FAMILIES
    }
    reasons = {
        family: (
            "RECEIVE_TIME_HTTP_SNAPSHOT_NOT_PER_FILL_PNL_INPUT"
            if family in {"copy_vault_positions", "copy_vault_selection"}
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
            or family in _SAFE_FAMILIES
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
        if any(part.is_symlink() for part in (
            recovery / "usable", usable_root, usable_root / tag, path,
        )):
            family_counts["local_files_unsafe"] += 1
            continue
        try:
            if path.is_file() and path.resolve().is_relative_to(usable_root.resolve()):
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
        index, all_rows = select_index_rows(
            catalog_path,
            lambda row: str(row.get("family") or "").startswith("copy_vault_"),
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
    family_expected = Counter(str(row.get("family")) for row in safe_rows)
    expected_material = [
        f"{row.get('dataset_id')}\0{row.get('family')}\0{row.get('bytes')}\0{row.get('sha256')}"
        for row in sorted(safe_rows, key=lambda item: str(item.get("dataset_id") or ""))
    ]
    expected_digest = hashlib.sha256(
        (catalog_sha + "\n" + "\n".join(expected_material)).encode("utf-8")
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
    catalog_validation_permission_fallbacks = 0
    heartbeat_evidence_missing: list[str] = []
    expected_ids: set[str] = set()
    recovery = Path(recovery_root).resolve()
    ordered_safe_rows = sorted(safe_rows, key=lambda item: str(item.get("dataset_id") or ""))
    auxiliary_inventory = _copy_vault_auxiliary_inventory(all_rows, recovery)
    for row_number, row in enumerate(ordered_safe_rows, 1):
        dataset_id = str(row.get("dataset_id") or "")
        if progress is not None:
            progress(
                f"Audit SAFE {row_number:,}/{len(ordered_safe_rows):,} · "
                f"{len(selected):,} vérifiés · shard {dataset_id or 'sans identifiant'}"
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
                family not in _SAFE_FAMILIES or row.get("replay_compatible") is not True
                or (
                    row.get("validation_allowed") is not None
                    and row.get("validation_allowed") is not True
                )
                or len(sha) != 64
                or any(char not in "0123456789abcdef" for char in sha)
                or type(size) is not int or size <= 0
            ):
                if (
                    row.get("validation_allowed") is not None
                    and row.get("validation_allowed") is not True
                ):
                    raise ValueError("CATALOG_VALIDATION_NOT_ALLOWED")
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
            heartbeat_reason = copy_vault_heartbeat_reason(manifest)
            heartbeat_unproven = False
            if heartbeat_reason is not None:
                if heartbeat_reason != "HEARTBEAT_EVIDENCE_MISSING":
                    raise ValueError(f"SAFE_MANIFEST_{heartbeat_reason}")
                if not _historical_exploratory_heartbeat_fallback_is_safe(
                    manifest, family=family
                ):
                    raise ValueError(
                        "HISTORICAL_EXPLORATORY_HEARTBEAT_FALLBACK_INTEGRITY_UNPROVEN"
                    )
                heartbeat_unproven = True
            if manifest.get("validation_allowed") is not True:
                raise ValueError("SAFE_MANIFEST_VALIDATION_NOT_ALLOWED")
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
            if row.get("validation_allowed") is None:
                # DATA_INDEX currently omits this field on verified SAFE rows;
                # the matching, SHA-bound manifest remains the explicit authority.
                catalog_validation_permission_fallbacks += 1
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
            selected_asset = {**dict(row), "manifest": manifest}
            if heartbeat_unproven:
                heartbeat_evidence_missing.append(dataset_id)
                selected_asset["_heartbeat_evidence_missing"] = True
            selected.append((io_path, selected_asset))
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            rejected.append({"dataset_id": dataset_id, "reason": str(exc)[:180]})

    selection_digest = hashlib.sha256(
        (catalog_sha + "\n" + "\n".join(
            f"{asset['dataset_id']}\0{asset['sha256']}"
            for _path, asset in sorted(selected, key=lambda pair: str(pair[1].get("dataset_id") or ""))
        )).encode("utf-8")
    ).hexdigest()
    audit_status = "SAFE_COMPLETE" if (
        len(selected) == len(safe_rows) and not missing and not rejected
    ) else "SAFE_PARTIAL"
    audit = {
        "schema": "hypersmart.copy_vault_local_safe_audit.v1",
        **_copy_vault_catalog_audit(all_rows),
        "safe_copy_vault_shards_not_used_for_pnl_inventory_by_family": auxiliary_inventory,
        "status": audit_status,
        "reason": None if audit_status == "SAFE_COMPLETE" else "LOCAL_SAFE_SHARDS_MISSING_OR_REJECTED",
        "source_index_sha256": catalog_sha,
        "expected_selection_sha256": expected_digest,
        "selection_digest": selection_digest,
        "expected_safe_shards": len(safe_rows),
        "copy_vault_release_tags": copy_vault_release_tags,
        "verified_safe_shards": len(selected),
        "expected_by_family": dict(sorted(family_expected.items())),
        "quality_counts_by_family": dict(sorted(
            (f"{family}:{quality}", count)
            for (family, quality), count in Counter(
                (str(row.get("family") or ""), str(row.get("quality_status") or "MISSING"))
                for row in selected_rows
            ).items()
        )),
        "partial_rows_excluded": sum(
            1 for row in selected_rows if row.get("quality_status") != "SAFE"
        ),
        "missing_count": len(missing),
        "missing_sample": missing[:50],
        "rejected_count": len(rejected),
        "rejected_sample": rejected[:50],
        "cached_hashes_reused_after_stat_match": stat_reused,
        "hashes_recomputed": hashes_recomputed,
        "catalog_validation_allowed_manifest_fallbacks": catalog_validation_permission_fallbacks,
        "heartbeat_evidence_missing_dataset_ids": sorted(heartbeat_evidence_missing),
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


def _historical_exploratory_heartbeat_fallback_is_safe(
    manifest: Mapping[str, Any], *, family: str,
) -> bool:
    """Allow integrity-checked legacy WS rows into TRAIN exploration only.

    A missing heartbeat never becomes continuity evidence: the caller records
    the missing proof and keeps the SAFE corpus incomplete, which blocks every
    held-out/economic proof gate. This narrow fallback only prevents otherwise
    hash-verified historical fills/books from being silently unusable for
    exploratory TRAIN diagnostics.
    """
    if family not in {"copy_vault_fills", "copy_vault_l2"}:
        return False
    synchronization = manifest.get("synchronization")
    integrity = manifest.get("integrity")
    provenance = manifest.get("provenance")
    if not isinstance(synchronization, Mapping) or not isinstance(integrity, Mapping):
        return False
    if not isinstance(provenance, Mapping):
        return False
    transports = provenance.get("transports")
    if not isinstance(transports, list) or "websocket" not in {
        str(value).lower() for value in transports
    }:
        return False
    connection_ids = synchronization.get("connection_ids")
    if (
        not isinstance(connection_ids, list)
        or len(connection_ids) != 1
        or not isinstance(connection_ids[0], str)
        or not connection_ids[0].strip()
        or type(synchronization.get("connection_count")) is not int
        or synchronization["connection_count"] != 1
        or type(synchronization.get("reconnect_delta")) is not int
        or synchronization["reconnect_delta"] != 0
        or type(synchronization.get("max_reconnect_count")) is not int
        or synchronization["max_reconnect_count"] < 0
    ):
        return False
    required_integrity = (
        "gap_count", "regression_count", "desync_count", "duplicate_count",
        "missing_timestamp_count", "missing_monotonic_count",
    )
    if any(
        type(integrity.get(name)) is not int or integrity[name] != 0
        for name in required_integrity
    ):
        return False
    if "invalid_record_count" in integrity and (
        type(integrity.get("invalid_record_count")) is not int
        or integrity["invalid_record_count"] != 0
    ):
        return False
    event_count = manifest.get("event_count")
    record_count = manifest.get("record_count")
    start = manifest.get("start_ts_ms")
    end = manifest.get("end_ts_ms")
    receive_delta = synchronization.get("receive_minus_exchange_ms")
    return bool(
        type(event_count) is int and event_count > 0
        and type(record_count) is int and record_count == event_count
        and type(start) is int and start > 0
        and type(end) is int and end >= start
        and isinstance(receive_delta, Mapping)
        and type(receive_delta.get("count")) is int
        and receive_delta["count"] == record_count
    )


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
    source_dataset_id: str | None = None,
    source_shard_sha256: str | None = None,
    source_catalog_sha256: str | None = None,
    source_continuity_proven: bool | None = None,
    expected_connection_id: str | None = None,
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
    wrapper_connection_id = wrapper.get("connection_id")
    if expected_connection_id is not None and wrapper_connection_id != expected_connection_id:
        if audit is not None:
            audit["SAFE_WRAPPER_CONNECTION_ID_MISMATCH"] += 1
        return rows
    if expected_connection_id is not None and (
        type(wrapper.get("gap_count")) is not int or wrapper["gap_count"] != 0
    ):
        if audit is not None:
            audit["SAFE_WRAPPER_GAP_EVIDENCE_INVALID"] += 1
        return rows
    if source_dataset_id is not None or source_shard_sha256 is not None:
        digest = str(source_shard_sha256 or "").lower()
        catalog_digest = str(source_catalog_sha256 or "").lower()
        if (
            not isinstance(source_dataset_id, str)
            or not source_dataset_id.strip()
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
        ):
            if audit is not None:
                audit["SAFE_SOURCE_SHARD_PROVENANCE_INVALID"] += 1
            return []
    raw_fills = data.get("fills")
    if not isinstance(raw_fills, list):
        if audit is not None:
            audit["FILL_LIST_INVALID"] += 1
        return []
    for fill in raw_fills:
        try:
            receive_value = wrapper.get("received_ts_ms")
            receive = int(receive_value) if type(receive_value) is int and receive_value > 0 else None
            field_error = userfill_required_fields_reason(
                fill,
                received_at_ms=receive,
                require_receive=True,
            )
            if field_error is not None:
                if audit is not None:
                    audit[field_error] += 1
                continue
            assert isinstance(fill, Mapping)
            event_ts = fill["time"]
            side = str(fill.get("side") or "").upper()
            if side not in {"A", "B"}:
                raise ValueError("fill side missing or invalid")
            fee = _number(fill["fee"])
            start_position = _number(fill["startPosition"]) if fill.get("startPosition") is not None else None
            closed_pnl = _number(fill["closedPnl"]) if fill.get("closedPnl") is not None else None
            price = _number(fill["px"])
            size = _number(fill["sz"])
            if price <= 0 or size <= 0:
                if audit is not None:
                    audit["FILL_EXECUTION_VALUE_INVALID"] += 1
                continue
            row = {
                "vault": vault,
                "ts_ms": event_ts,
                "coin": canonical_copy_vault_coin(fill["coin"]),
                "px": price,
                "sz": size,
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
            }
            if isinstance(wrapper_connection_id, str) and wrapper_connection_id.strip():
                row["connection_id"] = wrapper_connection_id.strip()
            if source_continuity_proven is not None:
                row["source_continuity_proven"] = source_continuity_proven is True
            if source_dataset_id is not None and source_shard_sha256 is not None:
                row["source_dataset_id"] = source_dataset_id.strip()
                row["source_shard_sha256"] = str(source_shard_sha256).lower()
                if (
                    len(catalog_digest) == 64
                    and all(char in "0123456789abcdef" for char in catalog_digest)
                ):
                    row["source_catalog_sha256"] = catalog_digest
                    row["source_quality_status"] = "SAFE"
                    row["source_manifest_verified"] = True
                    row["source_replay_compatible"] = True
            rows.append(row)
        except (KeyError, TypeError, ValueError, OverflowError):
            if audit is not None:
                audit["INVALID_OR_INCOMPLETE_FILL_REJECTED"] += 1
            continue
    return rows


def _book_row(
    wrapper: Mapping[str, Any], *,
    source_dataset_id: str | None = None,
    source_shard_sha256: str | None = None,
    source_catalog_sha256: str | None = None,
    source_continuity_proven: bool | None = None,
    expected_connection_id: str | None = None,
) -> dict[str, Any] | None:
    raw = wrapper["_raw"]
    data = raw.get("data") if isinstance(raw.get("data"), Mapping) else {}
    levels = data.get("levels")
    if raw.get("channel") != "l2Book" or not isinstance(levels, list) or len(levels) != 2:
        return None
    try:
        bids = normalize_l2_levels(
            [[level["px"], level["sz"]] for level in levels[0]], side="bid"
        )
        asks = normalize_l2_levels(
            [[level["px"], level["sz"]] for level in levels[1]], side="ask"
        )
        if not bids or not asks:
            return None
        bids, asks = bids[:5], asks[:5]
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
        row = {
            "schema_version": "hypersmart.copy_vault_l2.v1",
            "coin": canonical_copy_vault_coin(
                data.get("coin") or wrapper.get("instrument")
            ),
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
        connection_id = wrapper.get("connection_id")
        if connection_id is not None:
            if not isinstance(connection_id, str) or not connection_id.strip():
                return None
            row["connection_id"] = connection_id.strip()
        if expected_connection_id is not None and row.get("connection_id") != expected_connection_id:
            return None
        if expected_connection_id is not None and (
            type(wrapper.get("gap_count")) is not int or wrapper["gap_count"] != 0
        ):
            return None
        parsed_summary = wrapper.get("parsed_summary")
        gap_epoch = (
            parsed_summary.get("l2_gap_epoch")
            if isinstance(parsed_summary, Mapping)
            else None
        )
        if gap_epoch is not None:
            if type(gap_epoch) is not int or gap_epoch < 0:
                return None
            row["l2_gap_epoch"] = gap_epoch
        if source_continuity_proven is True and (
            not row.get("connection_id") or type(row.get("l2_gap_epoch")) is not int
        ):
            return None
        if source_continuity_proven is not None:
            row["source_continuity_proven"] = source_continuity_proven is True
        if source_dataset_id is not None or source_shard_sha256 is not None:
            dataset_id = source_dataset_id.strip() if isinstance(source_dataset_id, str) else ""
            shard_sha = source_shard_sha256.lower() if isinstance(source_shard_sha256, str) else ""
            catalog_sha = source_catalog_sha256.lower() if isinstance(source_catalog_sha256, str) else ""
            if (
                not dataset_id
                or len(shard_sha) != 64
                or any(char not in "0123456789abcdef" for char in shard_sha)
            ):
                return None
            row["source_dataset_id"] = dataset_id
            row["source_shard_sha256"] = shard_sha
            if (
                len(catalog_sha) == 64
                and all(char in "0123456789abcdef" for char in catalog_sha)
            ):
                row["source_catalog_sha256"] = catalog_sha
                row["source_quality_status"] = "SAFE"
                row["source_manifest_verified"] = True
                row["source_replay_compatible"] = True
        return row
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def _market_context_row(
    wrapper: Mapping[str, Any], *, family: str, audit: Counter[str],
) -> dict[str, Any] | None:
    """Revalidate SAFE market-context rows; never turn them into leader fills."""
    raw = wrapper.get("_raw")
    provenance = wrapper.get("provenance")
    expected_channel = {
        "copy_vault_bbo": "bbo",
        "copy_vault_trades": "trades",
        "copy_vault_active_asset_ctx": "activeAssetCtx",
    }.get(family)
    if (
        not isinstance(raw, Mapping)
        or raw.get("channel") != expected_channel
        or wrapper.get("source_id") != "hyperliquid_public_copy_vault_market_ws"
        or not isinstance(provenance, Mapping)
        or provenance.get("access") != "read_only"
        or provenance.get("authenticated") is not False
        or provenance.get("transport") != "websocket"
    ):
        audit["COPY_VAULT_MARKET_SOURCE_OR_CHANNEL_INVALID"] += 1
        return None
    data = raw.get("data")
    receive = wrapper.get("received_ts_ms")
    exchange = wrapper.get("exchange_ts_ms")
    mono = wrapper.get("local_monotonic_ns")
    instrument = canonical_copy_vault_coin(wrapper.get("instrument"))
    trade_rows = data if family == "copy_vault_trades" and isinstance(data, list) else None
    trade_first = (
        trade_rows[0]
        if trade_rows is not None and len(trade_rows) == 1
        and isinstance(trade_rows[0], Mapping)
        else None
    )
    data_coin = (
        trade_first.get("coin") if isinstance(trade_first, Mapping)
        else data.get("coin") if isinstance(data, Mapping)
        else None
    )
    if (
        (not isinstance(data, Mapping) and family != "copy_vault_trades")
        or (family == "copy_vault_trades" and trade_first is None)
        or not instrument
        or canonical_copy_vault_coin(data_coin) != instrument
        or type(receive) is not int or receive <= 0
        or type(mono) is not int or mono <= 0
    ):
        audit["COPY_VAULT_MARKET_IDENTITY_OR_CLOCK_INVALID"] += 1
        return None
    common = {
        "coin": instrument,
        "received_at_ms": receive,
        "source_raw_sha256": wrapper.get("raw_sha256"),
        "data_origin": "REAL_OBSERVED_SAFE_CONTEXT",
        "paper_read_only": True,
        "proof_of_pnl_allowed": False,
    }
    if family == "copy_vault_bbo":
        timestamp, levels = data.get("time"), data.get("bbo")
        if (
            type(timestamp) is not int or timestamp <= 0 or timestamp != exchange
            or receive < timestamp or receive - timestamp > 30_000
            or not isinstance(levels, list) or len(levels) != 2
            or not all(isinstance(level, Mapping) for level in levels)
        ):
            audit["COPY_VAULT_BBO_CLOCK_OR_SHAPE_INVALID"] += 1
            return None
        try:
            bid_px, bid_sz = _number(levels[0]["px"]), _number(levels[0]["sz"])
            ask_px, ask_sz = _number(levels[1]["px"]), _number(levels[1]["sz"])
        except (KeyError, TypeError, ValueError, OverflowError):
            audit["COPY_VAULT_BBO_NUMERIC_INVALID"] += 1
            return None
        if bid_px <= 0 or ask_px <= bid_px or bid_sz < 0 or ask_sz < 0:
            audit["COPY_VAULT_BBO_MARKET_INVALID"] += 1
            return None
        return {
            "schema_version": "hypersmart.copy_vault_bbo.v1",
            **common,
            "exchange_ts_ms": timestamp,
            "bid_px": bid_px,
            "bid_sz": bid_sz,
            "ask_px": ask_px,
            "ask_sz": ask_sz,
        }
    if family == "copy_vault_trades":
        row = trade_first
        timestamp = row.get("time")
        try:
            price, size = _number(row.get("px")), _number(row.get("sz"))
        except (TypeError, ValueError, OverflowError):
            audit["COPY_VAULT_TRADE_NUMERIC_INVALID"] += 1
            return None
        identity = str(row.get("hash") or "").strip()
        tid = row.get("tid")
        side = str(row.get("side") or "").upper()
        if (
            canonical_copy_vault_coin(row.get("coin")) != instrument
            or type(timestamp) is not int or timestamp <= 0 or timestamp != exchange
            or receive < timestamp or receive - timestamp > 30_000
            or (not identity and type(tid) is not int)
            or price <= 0 or size <= 0 or side not in {"A", "B"}
        ):
            audit["COPY_VAULT_TRADE_IDENTITY_OR_CLOCK_INVALID"] += 1
            return None
        return {
            "schema_version": "hypersmart.copy_vault_market_trade.v1",
            **common,
            "exchange_ts_ms": timestamp,
            "price": price,
            "size": size,
            "aggressor_side": side,
            "hash": identity or None,
            "tid": tid if type(tid) is int else None,
        }
    if (
        exchange is not None
        or provenance.get("timestamp_semantics") != "receive_observation_time_only"
        or not isinstance(data.get("ctx"), Mapping)
    ):
        audit["COPY_VAULT_ACTIVE_CONTEXT_INVALID"] += 1
        return None
    return {
        "schema_version": "hypersmart.copy_vault_active_asset_ctx.v1",
        **common,
        "timestamp_semantics": "receive_observation_time_only",
        "context": dict(data["ctx"]),
    }


def _accounting_context_row(
    wrapper: Mapping[str, Any], *, family: str, audit: Counter[str],
) -> dict[str, Any] | None:
    """Preserve SAFE leader accounting events separately from follower PnL."""
    raw = wrapper.get("_raw")
    provenance = wrapper.get("provenance")
    expected = {
        "copy_vault_funding": ("userFundings", "fundings"),
        "copy_vault_ledger": (
            "userNonFundingLedgerUpdates", "nonFundingLedgerUpdates",
        ),
    }.get(family)
    transport = str(provenance.get("transport") or "").lower() if isinstance(provenance, Mapping) else ""
    request_type = str(provenance.get("request_type") or "") if isinstance(provenance, Mapping) else ""
    historical_rest = (
        transport == "https"
        and provenance.get("historical_only") is True
        and request_type == ("userFunding" if family == "copy_vault_funding" else "userNonFundingLedgerUpdates")
        and wrapper.get("source_id") == "hl_public_account_backfill"
    ) if isinstance(provenance, Mapping) else False
    live_websocket = (
        transport == "websocket"
        and wrapper.get("source_id") == "hl_public_account"
    )
    if (
        not isinstance(raw, Mapping) or expected is None
        or raw.get("channel") != expected[0]
        or not isinstance(provenance, Mapping)
        or provenance.get("access") != "read_only"
        or provenance.get("authenticated") is not False
        or not (live_websocket or historical_rest)
    ):
        audit["COPY_VAULT_ACCOUNTING_SOURCE_OR_CHANNEL_INVALID"] += 1
        return None
    data = raw.get("data")
    instrument = str(wrapper.get("instrument") or "").strip().lower()
    receive = wrapper.get("received_ts_ms")
    mono = wrapper.get("local_monotonic_ns")
    if (
        not isinstance(data, Mapping)
        or str(data.get("user") or "").strip().lower() != instrument
        or type(data.get("isSnapshot")) is not bool
        or type(receive) is not int or receive <= 0
        or type(mono) is not int or mono <= 0
    ):
        audit["COPY_VAULT_ACCOUNTING_IDENTITY_OR_CLOCK_INVALID"] += 1
        return None
    rows = data.get(expected[1])
    if not isinstance(rows, list):
        audit["COPY_VAULT_ACCOUNTING_ROWS_MISSING"] += 1
        return None
    common = {
        "vault": instrument,
        "received_at_ms": receive,
        "is_snapshot": data["isSnapshot"],
        "snapshot_only_research": data["isSnapshot"] is True,
        "historical_only": provenance.get("historical_only") is True,
        "source_raw_sha256": wrapper.get("raw_sha256"),
        "data_origin": "REAL_OBSERVED_SAFE_CONTEXT",
        "paper_read_only": True,
        "proof_of_pnl_allowed": False,
        "forward_evidence_allowed": False,
    }
    if not rows:
        if (
            wrapper.get("exchange_ts_ms") is not None
            or data["isSnapshot"] is not True
            or provenance.get("timestamp_semantics")
            != "receive_observation_time_only"
        ):
            audit["COPY_VAULT_ACCOUNTING_EMPTY_FRAME_INVALID"] += 1
            return None
        return {
            "schema_version": f"hypersmart.{family}.empty_snapshot.v1",
            **common,
            "empty_snapshot_is_zero_proof": False,
        }
    if len(rows) != 1 or not isinstance(rows[0], Mapping):
        audit["COPY_VAULT_ACCOUNTING_FRAME_NOT_SINGLE_EVENT"] += 1
        return None
    row = rows[0]
    timestamp = row.get("time")
    if (
        type(timestamp) is not int or timestamp <= 0
        or timestamp != wrapper.get("exchange_ts_ms") or receive < timestamp
    ):
        audit["COPY_VAULT_ACCOUNTING_EVENT_CLOCK_INVALID"] += 1
        return None
    if family == "copy_vault_funding":
        detail = row.get("delta") if isinstance(row.get("delta"), Mapping) else row
        coin = canonical_copy_vault_coin(detail.get("coin"))
        try:
            usdc = _number(detail.get("usdc"))
            size = _number(detail.get("szi"))
            rate = _number(detail.get("fundingRate"))
        except (TypeError, ValueError, OverflowError):
            audit["COPY_VAULT_FUNDING_NUMERIC_INVALID"] += 1
            return None
        if not coin:
            audit["COPY_VAULT_FUNDING_INSTRUMENT_INVALID"] += 1
            return None
        return {
            "schema_version": "hypersmart.copy_vault_funding.v1",
            **common,
            "coin": coin,
            "exchange_ts_ms": timestamp,
            "usdc": usdc,
            "size": size,
            "funding_rate": rate,
            "hash": str(row.get("hash") or "").strip() or None,
            "event_raw": dict(row),
        }
    delta = row.get("delta")
    identity = str(row.get("hash") or "").strip()
    if not identity or not isinstance(delta, Mapping) or not str(delta.get("type") or "").strip():
        audit["COPY_VAULT_LEDGER_IDENTITY_OR_DELTA_INVALID"] += 1
        return None
    return {
        "schema_version": "hypersmart.copy_vault_ledger.v1",
        **common,
        "exchange_ts_ms": timestamp,
        "hash": identity,
        "delta_type": str(delta["type"]),
        "event_raw": dict(row),
    }


def materialize_safe_workspace(
    recovery_root: str | Path,
    workspace: str | Path,
    *,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    recovery_root, workspace = Path(recovery_root), Path(workspace)
    assets, audit = _verified_assets(recovery_root, progress=progress)
    repository_root = Path(recovery_root).resolve().parents[2]
    history_audit = load_release_history_audits(
        repository_root / "catalog" / "campaigns",
        release_tags=set(audit.get("copy_vault_release_tags") or []),
    )
    data_dir = workspace / "runtime" / "data"
    if any(part.is_symlink() for part in (workspace, workspace / "runtime", data_dir)):
        raise OSError("refusing symlinked Copy-Vault replay workspace")
    data_dir.mkdir(parents=True, exist_ok=True)
    fills: dict[tuple[Any, ...], dict[str, Any]] = {}
    books: dict[tuple[Any, ...], dict[str, Any]] = {}
    bbo_rows: dict[tuple[Any, ...], dict[str, Any]] = {}
    market_trade_rows: dict[tuple[Any, ...], dict[str, Any]] = {}
    active_context_rows: dict[tuple[Any, ...], dict[str, Any]] = {}
    funding_rows: dict[tuple[Any, ...], dict[str, Any]] = {}
    ledger_rows: dict[tuple[Any, ...], dict[str, Any]] = {}
    wrapper_rejections = 0
    payload_audit: Counter[str] = Counter()
    raw_frames = 0
    historical_snapshot_shards = 0
    historical_fill_observations = 0
    for asset_number, (path, asset) in enumerate(assets, 1):
        try:
            family = str(asset.get("family") or "")
            source_continuity_proven = not bool(
                asset.get("_heartbeat_evidence_missing")
            )
            manifest = asset.get("manifest")
            synchronization = (
                manifest.get("synchronization")
                if isinstance(manifest, Mapping)
                else None
            )
            connection_ids = (
                synchronization.get("connection_ids")
                if isinstance(synchronization, Mapping)
                else None
            )
            expected_connection_id = (
                connection_ids[0]
                if isinstance(connection_ids, list)
                and len(connection_ids) == 1
                and isinstance(connection_ids[0], str)
                else None
            )
            if family == "copy_vault_snapshot":
                historical_snapshot_shards += 1
            for wrapper in _load_wrappers(path):
                raw_frames += 1
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
                    for row in _fill_rows(
                        wrapper,
                        family=family,
                        audit=payload_audit,
                        source_dataset_id=str(asset.get("dataset_id") or ""),
                        source_shard_sha256=str(asset.get("sha256") or ""),
                        source_catalog_sha256=str(audit.get("source_index_sha256") or ""),
                        source_continuity_proven=(
                            source_continuity_proven
                            if family == "copy_vault_fills"
                            else None
                        ),
                        expected_connection_id=(
                            expected_connection_id
                            if family == "copy_vault_fills"
                            else None
                        ),
                    ):
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
                    dataset_id = asset.get("dataset_id")
                    shard_sha256 = asset.get("sha256")
                    row = _book_row(
                        wrapper,
                        source_dataset_id=(
                            str(dataset_id) if isinstance(dataset_id, str) and dataset_id else None
                        ),
                        source_shard_sha256=(
                            str(shard_sha256) if isinstance(shard_sha256, str) and shard_sha256 else None
                        ),
                        source_catalog_sha256=str(audit.get("source_index_sha256") or ""),
                        source_continuity_proven=source_continuity_proven,
                        expected_connection_id=expected_connection_id,
                    )
                    if row:
                        identity = (
                            row["coin"], row["received_at_ms"], row["exchange_ts_ms"],
                            row["bid"], row["ask"],
                            tuple(tuple(level) for level in row["bids5"]),
                            tuple(tuple(level) for level in row["asks5"]),
                        )
                        books[identity] = row
                    else:
                        payload_audit["INVALID_OR_NONCAUSAL_L2_REJECTED"] += 1
                elif family in {
                    "copy_vault_bbo", "copy_vault_trades",
                    "copy_vault_active_asset_ctx",
                }:
                    row = _market_context_row(
                        wrapper, family=family, audit=payload_audit
                    )
                    if row is not None:
                        if family == "copy_vault_bbo":
                            identity = (
                                row["coin"], row["received_at_ms"],
                                row["exchange_ts_ms"], row["bid_px"], row["ask_px"],
                            )
                            bbo_rows[identity] = row
                        elif family == "copy_vault_trades":
                            identity = (
                                row["coin"], row["exchange_ts_ms"],
                                row.get("hash"), row.get("tid"),
                                row["price"], row["size"], row["aggressor_side"],
                            )
                            market_trade_rows[identity] = row
                        else:
                            identity = (
                                row["coin"], row["received_at_ms"],
                                row["source_raw_sha256"],
                            )
                            active_context_rows[identity] = row
                elif family in {"copy_vault_funding", "copy_vault_ledger"}:
                    row = _accounting_context_row(
                        wrapper, family=family, audit=payload_audit
                    )
                    if row is not None:
                        if family == "copy_vault_funding":
                            identity = (
                                row["vault"], row.get("hash") or row.get("exchange_ts_ms"),
                                row.get("coin"), row.get("usdc"), row.get("size"),
                                row.get("funding_rate"),
                            )
                            funding_rows[identity] = row
                        else:
                            identity = (
                                row["vault"], row.get("exchange_ts_ms"), row.get("hash"),
                            )
                            ledger_rows[identity] = row
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
    fill_rows = sorted(fills.values(), key=lambda row: (row["ts_ms"], row["vault"], str(row.get("tid"))))
    book_rows = sorted(books.values(), key=lambda row: (row["received_at_ms"], row["coin"]))
    bbo_tape_rows = sorted(
        bbo_rows.values(), key=lambda row: (row["received_at_ms"], row["coin"])
    )
    market_trade_tape_rows = sorted(
        market_trade_rows.values(),
        key=lambda row: (row["exchange_ts_ms"], row["coin"], str(row.get("tid"))),
    )
    active_context_tape_rows = sorted(
        active_context_rows.values(),
        key=lambda row: (row["received_at_ms"], row["coin"]),
    )
    funding_tape_rows = sorted(
        funding_rows.values(),
        key=lambda row: (row.get("exchange_ts_ms") or row["received_at_ms"], row["vault"]),
    )
    ledger_tape_rows = sorted(
        ledger_rows.values(),
        key=lambda row: (row.get("exchange_ts_ms") or row["received_at_ms"], row["vault"]),
    )
    historical_unique_fills = sum(bool(row.get("isSnapshot")) for row in fill_rows)
    verified_source_assets = [
        {
            "dataset_id": asset.get("dataset_id"),
            "family": asset.get("family"),
            "release_tag": asset.get("release_tag"),
            "release_asset": asset.get("release_asset"),
            "manifest_path": asset.get("manifest_path"),
            "bytes": asset.get("bytes"),
            "sha256": str(asset.get("sha256") or "").lower() or None,
        }
        for _path, asset in sorted(
            assets, key=lambda pair: str(pair[1].get("dataset_id") or "")
        )
    ]
    source_asset_inventory_complete = bool(verified_source_assets) and all(
        isinstance(asset.get("dataset_id"), str)
        and bool(asset["dataset_id"].strip())
        and type(asset.get("bytes")) is int
        and asset["bytes"] > 0
        and isinstance(asset.get("sha256"), str)
        and len(asset["sha256"]) == 64
        and all(char in "0123456789abcdef" for char in asset["sha256"])
        and isinstance(asset.get("manifest_path"), str)
        and bool(asset["manifest_path"])
        for asset in verified_source_assets
    )
    source_asset_inventory_sha256 = _source_asset_inventory_sha256(
        verified_source_assets
    )
    source_asset_inventory_error = _source_asset_inventory_error({
        "verified_source_assets": verified_source_assets,
        "source_asset_inventory_count": len(verified_source_assets),
        "source_asset_inventory_sha256": source_asset_inventory_sha256,
        "source_asset_inventory_complete": source_asset_inventory_complete,
        "source_index_sha256": audit.get("source_index_sha256"),
        "selection_digest": audit.get("selection_digest"),
    })
    materialized_tapes: dict[str, dict[str, Any]] = {}
    for name, rows in (
        ("vault_fills.jsonl", fill_rows),
        ("copy_vault_l2_tape.jsonl", book_rows),
        ("copy_vault_bbo_tape.jsonl", bbo_tape_rows),
        ("copy_vault_trades_tape.jsonl", market_trade_tape_rows),
        ("copy_vault_active_asset_ctx_tape.jsonl", active_context_tape_rows),
        ("copy_vault_funding_tape.jsonl", funding_tape_rows),
        ("copy_vault_ledger_tape.jsonl", ledger_tape_rows),
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
            "bytes": target.stat().st_size,
            "sha256": _sha256(target),
        }
    data_complete = (
        audit.get("status") == "SAFE_COMPLETE"
        and history_audit.get("status") == "COMPLETE"
        and source_asset_inventory_error is None
        and wrapper_rejections == 0
        and not payload_audit
        and not audit.get("heartbeat_evidence_missing_dataset_ids")
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
    elif audit.get("heartbeat_evidence_missing_dataset_ids"):
        reason = "COPY_VAULT_HEARTBEAT_CONTINUITY_UNPROVEN"
    elif history_audit.get("status") != "COMPLETE":
        reason = "HISTORICAL_BACKFILL_COVERAGE_PARTIAL_OR_UNKNOWN"
    elif source_asset_inventory_error is not None:
        reason = source_asset_inventory_error
    else:
        reason = audit.get("reason") or "FILLS_OR_CAUSAL_L2_MISSING"
    result = {
        "status": status,
        "reason": reason,
        "verified_assets": len(assets),
        "expected_safe_shards": audit.get("expected_safe_shards", 0),
        "missing_shards": audit.get("missing_count", 0),
        "partial_shards_excluded": audit.get("partial_rows_excluded", 0),
        "rejected_assets": audit.get("rejected_count", 0),
        "invalid_wrappers": wrapper_rejections,
        "payload_audit": dict(sorted(payload_audit.items())),
        "payload_rejected_records": sum(payload_audit.values()),
        "raw_frames": raw_frames,
        "unique_fills": len(fill_rows),
        "historical_snapshot_shards": historical_snapshot_shards,
        "historical_fill_observations": historical_fill_observations,
        "historical_unique_fills": historical_unique_fills,
        "historical_coverage_audit": history_audit,
        "incremental_unique_fills": len(fill_rows) - historical_unique_fills,
        "historical_fills_train_only": True,
        "snapshots_forward_evidence_allowed": False,
        "unique_books": len(book_rows),
        "unique_bbo_observations": len(bbo_tape_rows),
        "unique_market_trades": len(market_trade_tape_rows),
        "unique_active_asset_contexts": len(active_context_tape_rows),
        "unique_leader_funding_events": len(funding_tape_rows),
        "unique_leader_ledger_events": len(ledger_tape_rows),
        "leader_accounting_tapes_are_follower_pnl_inputs": False,
        "market_context_tapes_are_pnl_inputs": False,
        "fill_start_ms": fill_rows[0]["ts_ms"] if fill_rows else None,
        "fill_end_ms": fill_rows[-1]["ts_ms"] if fill_rows else None,
        "book_start_ms": book_rows[0]["received_at_ms"] if book_rows else None,
        "book_end_ms": book_rows[-1]["received_at_ms"] if book_rows else None,
        "data_complete": data_complete,
        "continuity_evidence_status": (
            "UNPROVEN"
            if audit.get("heartbeat_evidence_missing_dataset_ids")
            else "NO_MISSING_HEARTBEAT_EVIDENCE"
        ),
        "continuity_evidence_missing_shards": len(
            audit.get("heartbeat_evidence_missing_dataset_ids") or []
        ),
        "continuity_evidence_missing_dataset_ids": audit.get(
            "heartbeat_evidence_missing_dataset_ids", []
        ),
        "replay_inputs_available": replay_inputs_available,
        "verified_source_assets": verified_source_assets,
        "source_asset_inventory_count": len(verified_source_assets),
        "source_asset_inventory_sha256": source_asset_inventory_sha256,
        "source_asset_inventory_complete": source_asset_inventory_complete,
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


def _source_asset_inventory_sha256(assets: Sequence[Mapping[str, Any]]) -> str:
    material = "\n".join(
        "\0".join(
            str(asset.get(key) if asset.get(key) is not None else "<MISSING>")
            for key in (
                "dataset_id", "family", "release_tag", "release_asset",
                "manifest_path", "bytes", "sha256",
            )
        )
        for asset in assets
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _source_selection_digest(
    source_index_sha256: str, assets: Sequence[Mapping[str, Any]]
) -> str:
    material = source_index_sha256 + "\n" + "\n".join(
        f"{asset['dataset_id']}\0{asset['sha256']}"
        for asset in sorted(assets, key=lambda row: str(row.get("dataset_id") or ""))
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _source_asset_inventory_error(manifest: Mapping[str, Any]) -> str | None:
    """Check the inventory receipt and bind it to the SAFE selection digest."""

    assets = manifest.get("verified_source_assets")
    if (
        manifest.get("source_asset_inventory_complete") is not True
        or not isinstance(assets, list)
        or not assets
        or type(manifest.get("source_asset_inventory_count")) is not int
        or manifest.get("source_asset_inventory_count") != len(assets)
    ):
        return "SAFE_SOURCE_ASSET_INVENTORY_MISSING_OR_INCOMPLETE"
    seen: set[str] = set()
    for asset in assets:
        if not isinstance(asset, Mapping):
            return "SAFE_SOURCE_ASSET_INVENTORY_ROW_INVALID"
        dataset_id = asset.get("dataset_id")
        digest = asset.get("sha256")
        if (
            not isinstance(dataset_id, str) or not dataset_id.strip()
            or dataset_id in seen
            or asset.get("family") not in _SAFE_FAMILIES
            or type(asset.get("bytes")) is not int or asset["bytes"] <= 0
            or not isinstance(digest, str) or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
            or not isinstance(asset.get("release_tag"), str) or not asset["release_tag"]
            or not isinstance(asset.get("release_asset"), str) or not asset["release_asset"]
            or not isinstance(asset.get("manifest_path"), str) or not asset["manifest_path"]
        ):
            return "SAFE_SOURCE_ASSET_INVENTORY_ROW_INVALID"
        seen.add(dataset_id)
    expected_inventory = _source_asset_inventory_sha256(assets)
    if manifest.get("source_asset_inventory_sha256") != expected_inventory:
        return "SAFE_SOURCE_ASSET_INVENTORY_DIGEST_MISMATCH"
    source_index_sha = str(manifest.get("source_index_sha256") or "").lower()
    if len(source_index_sha) != 64 or any(char not in "0123456789abcdef" for char in source_index_sha):
        return "SAFE_SOURCE_INDEX_SHA256_INVALID"
    expected_selection = _source_selection_digest(source_index_sha, assets)
    if str(manifest.get("selection_digest") or "").lower() != expected_selection:
        return "SAFE_SELECTION_DIGEST_DOES_NOT_BIND_SOURCE_INVENTORY"
    return None


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


def _campaign_search_config(bounds: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    """Freeze the deterministic proposal contract and TRAIN-only time bounds."""
    config = {
        "schema": "hypersmart.copy_vault_search_config.v1",
        "family": "copy_vault",
        "proposal_method": "HALTON_RADICAL_INVERSE_V1",
        "proposal_seed": 0,
        "first_sequence_index": 1,
        "halton_bases": list(_HALTON_BASES),
        "parameter_domains": {
            name: list(domain) for name, domain in _PARAMETER_DOMAINS
        },
        "paper_capital_usd": PAPER_CAPITAL_USD,
        "objective_usd_per_day": OBJECTIVE_USD_PER_DAY,
        "selection_scope": "TRAIN_ONLY_PRE_FREEZE",
        "heldout_tuning_allowed": False,
        "temporal_windows": dict(bounds),
    }
    return config, _canonical_json_sha256(config)


def _trial_receipt_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key != "trial_receipt_sha256"}


def _trial_with_receipt_chain(
    row: Mapping[str, Any], previous_receipt_sha256: str,
) -> dict[str, Any]:
    if (
        not isinstance(previous_receipt_sha256, str)
        or len(previous_receipt_sha256) != 64
        or any(char not in "0123456789abcdef" for char in previous_receipt_sha256)
    ):
        raise ValueError("invalid prior trial receipt chain hash")
    receipt = dict(row)
    receipt["previous_trial_receipt_sha256"] = previous_receipt_sha256
    receipt.pop("trial_receipt_sha256", None)
    receipt["trial_receipt_sha256"] = _canonical_json_sha256(
        _trial_receipt_payload(receipt)
    )
    return receipt


def _campaign_trial_chain(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[str, list[str]]:
    """Validate the append-only receipt chain, including its legacy v1 prefix."""
    previous = _TRIAL_CHAIN_GENESIS
    prefixes: list[str] = []
    for index, row in enumerate(rows, 1):
        if not isinstance(row, Mapping):
            raise ValueError(f"trial receipt chain row {index} is invalid")
        schema = row.get("schema")
        if schema == "hypersmart.copy_vault_local_trial.v1":
            if "previous_trial_receipt_sha256" in row or "trial_receipt_sha256" in row:
                raise ValueError(f"trial receipt chain legacy row {index} has receipt fields")
            digest = _canonical_json_sha256(dict(row))
        elif schema == "hypersmart.copy_vault_local_trial.v2":
            if row.get("previous_trial_receipt_sha256") != previous:
                raise ValueError(f"trial receipt chain predecessor mismatch at row {index}")
            supplied = row.get("trial_receipt_sha256")
            if (
                not isinstance(supplied, str)
                or len(supplied) != 64
                or any(char not in "0123456789abcdef" for char in supplied)
                or supplied != _canonical_json_sha256(_trial_receipt_payload(row))
            ):
                raise ValueError(f"trial receipt chain hash mismatch at row {index}")
            digest = supplied
        else:
            raise ValueError(f"trial receipt chain schema mismatch at row {index}")
        previous = digest
        prefixes.append(digest)
    return previous, prefixes


def _attempt_with_receipt_chain(
    row: Mapping[str, Any], previous_receipt_sha256: str,
) -> dict[str, Any]:
    if (
        not isinstance(previous_receipt_sha256, str)
        or len(previous_receipt_sha256) != 64
        or any(char not in "0123456789abcdef" for char in previous_receipt_sha256)
    ):
        raise ValueError("invalid prior attempt receipt chain hash")
    receipt = dict(row)
    receipt["previous_attempt_receipt_sha256"] = previous_receipt_sha256
    receipt.pop("attempt_receipt_sha256", None)
    receipt["attempt_receipt_sha256"] = _canonical_json_sha256({
        key: value for key, value in receipt.items()
        if key != "attempt_receipt_sha256"
    })
    return receipt


def _campaign_attempt_chain(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[str, list[str]]:
    previous = _TRIAL_CHAIN_GENESIS
    prefixes: list[str] = []
    for index, row in enumerate(rows, 1):
        supplied = row.get("attempt_receipt_sha256")
        payload = {
            key: value for key, value in row.items()
            if key != "attempt_receipt_sha256"
        }
        if (
            row.get("schema") != "hypersmart.copy_vault_local_attempt.v1"
            or row.get("previous_attempt_receipt_sha256") != previous
            or not isinstance(supplied, str)
            or len(supplied) != 64
            or any(char not in "0123456789abcdef" for char in supplied)
            or supplied != _canonical_json_sha256(payload)
        ):
            raise ValueError(f"attempt receipt chain mismatch at row {index}")
        previous = supplied
        prefixes.append(supplied)
    return previous, prefixes


def _load_campaign_attempts(path: Path, selection_digest: str) -> list[dict[str, Any]]:
    if path.is_symlink():
        raise ValueError("unsafe Copy-Vault attempt ledger symlink")
    if not path.exists():
        return []
    if not path.is_file():
        raise ValueError("unsafe Copy-Vault attempt ledger")
    rows: list[dict[str, Any]] = []
    sequences: set[int] = set()
    signatures: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            try:
                row = json.loads(line)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"attempt ledger corrupted at line {number}") from exc
            if (
                not isinstance(row, dict)
                or row.get("schema") != "hypersmart.copy_vault_local_attempt.v1"
                or row.get("selection_digest") != selection_digest
                or type(row.get("sequence_index")) is not int
                or row["sequence_index"] <= 0
                or type(row.get("trial_number")) is not int
                or row["trial_number"] <= 0
                or not isinstance(row.get("parameter_signature"), str)
                or row.get("parameter_signature") != parameter_hash(row.get("parameters"))
                or row["sequence_index"] in sequences
                or row["parameter_signature"] in signatures
                or row.get("paper_read_only") is not True
                or row.get("real_execution") is not False
            ):
                raise ValueError(f"attempt ledger identity mismatch at line {number}")
            for key in (
                "source_catalog_sha256", "source_asset_inventory_sha256",
                "engine_source_sha256", "campaign_config_sha256",
            ):
                value = row.get(key)
                if (
                    not isinstance(value, str)
                    or len(value) != 64
                    or any(char not in "0123456789abcdef" for char in value)
                ):
                    raise ValueError(f"attempt ledger lineage invalid at line {number}: {key}")
            if (
                row.get("proposal_method") != "HALTON_RADICAL_INVERSE_V1"
                or type(row.get("proposal_seed")) is not int
                or row.get("proposal_seed") != 0
                or not isinstance(row.get("temporal_windows"), dict)
            ):
                raise ValueError(f"attempt ledger search config invalid at line {number}")
            sequences.add(row["sequence_index"])
            signatures.add(row["parameter_signature"])
            rows.append(row)
    _campaign_attempt_chain(rows)
    return rows


def _checkpoint_resume_state(
    checkpoint: Mapping[str, Any] | None,
    rows: Sequence[Mapping[str, Any]],
    *,
    attempts: Sequence[Mapping[str, Any]] | None = None,
    selection_digest: str,
    source_catalog_sha256: str,
    source_asset_inventory_sha256: str,
    engine_source_sha256: str,
    campaign_config_sha256: str,
) -> dict[str, Any]:
    final_chain, prefixes = _campaign_trial_chain(rows)
    if attempts is None:
        attempt_chain, attempt_prefixes = _TRIAL_CHAIN_GENESIS, []
        attempt_count = len(rows)
    else:
        attempt_chain, attempt_prefixes = _campaign_attempt_chain(attempts)
        legacy_count = sum(
            row.get("schema") == "hypersmart.copy_vault_local_trial.v1"
            for row in rows
        )
        attempt_count = legacy_count + len(attempts)
        attempts_by_hash = {
            str(row.get("attempt_receipt_sha256")): row for row in attempts
        }
        for index, row in enumerate(rows, 1):
            if row.get("schema") != "hypersmart.copy_vault_local_trial.v2":
                continue
            reservation = attempts_by_hash.get(str(row.get("attempt_receipt_sha256")))
            if (
                reservation is None
                or reservation.get("sequence_index") != row.get("sequence_index")
                or reservation.get("trial_number") != row.get("trial_number")
                or reservation.get("parameter_signature") != row.get("parameter_signature")
                or reservation.get("engine_source_sha256") != row.get("engine_source_sha256")
                or reservation.get("campaign_config_sha256") != row.get("campaign_config_sha256")
            ):
                raise ValueError(f"Copy-Vault trial has no matching durable attempt at row {index}")
    max_sequence = max(
        (
            int(row.get("sequence_index") or 0)
            for row in [*rows, *(attempts or ())]
        ),
        default=0,
    )
    checkpoint_present = checkpoint is not None
    checkpoint = checkpoint or {}
    if checkpoint_present:
        if checkpoint.get("schema") not in {
            "hypersmart.copy_vault_search_checkpoint.v1",
            "hypersmart.copy_vault_search_checkpoint.v2",
        }:
            raise ValueError("Copy-Vault checkpoint schema mismatch")
        if checkpoint.get("selection_digest") != selection_digest:
            raise ValueError("Copy-Vault checkpoint does not match this SAFE selection")
        for key, expected in (
            ("source_catalog_sha256", source_catalog_sha256),
            ("source_asset_inventory_sha256", source_asset_inventory_sha256),
        ):
            recorded = checkpoint.get(key)
            if recorded is not None and recorded != expected:
                raise ValueError(f"Copy-Vault checkpoint data identity mismatch: {key}")
        count = checkpoint.get("campaign_trials", 0)
        if type(count) is not int or count < 0:
            raise ValueError("Copy-Vault checkpoint trial count is invalid")
        if count > len(rows):
            raise ValueError("Copy-Vault checkpoint is ahead of durable trial receipts")
        if checkpoint.get("schema") == "hypersmart.copy_vault_search_checkpoint.v2":
            for key in ("engine_source_sha256", "campaign_config_sha256"):
                value = checkpoint.get(key)
                if (
                    not isinstance(value, str)
                    or len(value) != 64
                    or any(char not in "0123456789abcdef" for char in value)
                ):
                    raise ValueError(f"Copy-Vault checkpoint identity is invalid: {key}")
            checkpoint_attempts = checkpoint.get("campaign_attempts", count)
            if type(checkpoint_attempts) is not int or checkpoint_attempts < count:
                raise ValueError("Copy-Vault checkpoint attempt count is invalid")
            if (
                checkpoint_attempts > attempt_count
                and checkpoint.get("schema") == "hypersmart.copy_vault_search_checkpoint.v2"
            ):
                raise ValueError("Copy-Vault checkpoint is ahead of durable attempt receipts")
            attempt_receipt_count = checkpoint.get("attempt_receipt_count", 0)
            if type(attempt_receipt_count) is not int or attempt_receipt_count < 0:
                raise ValueError("Copy-Vault checkpoint attempt receipt count is invalid")
            if attempt_receipt_count > len(attempt_prefixes):
                raise ValueError("Copy-Vault checkpoint is ahead of durable attempt receipts")
            if checkpoint.get("schema") == "hypersmart.copy_vault_search_checkpoint.v2":
                expected_attempt_chain = (
                    attempt_prefixes[attempt_receipt_count - 1]
                    if attempt_receipt_count else _TRIAL_CHAIN_GENESIS
                )
                if checkpoint.get("attempt_receipt_chain_sha256") != expected_attempt_chain:
                    raise ValueError("Copy-Vault checkpoint attempt receipt chain mismatch")
            expected_chain = prefixes[count - 1] if count else _TRIAL_CHAIN_GENESIS
            if checkpoint.get("trial_receipt_chain_sha256") != expected_chain:
                raise ValueError("Copy-Vault checkpoint receipt chain mismatch")
        else:
            checkpoint_attempts = count
        next_sequence = checkpoint.get("next_sequence_index", 1)
        if type(next_sequence) is not int or next_sequence <= 0:
            raise ValueError("Copy-Vault checkpoint next sequence is invalid")
        next_sequence = max(next_sequence, max_sequence + 1)
    else:
        count = 0
        checkpoint_attempts = attempt_count
        next_sequence = max_sequence + 1
    return {
        "campaign_trials": len(rows),
        "campaign_attempts": max(len(rows), attempt_count, checkpoint_attempts),
        "attempt_receipt_count": len(attempt_prefixes),
        "attempt_receipt_chain_sha256": attempt_chain,
        "incomplete_attempts": max(0, attempt_count - len(rows)),
        "next_sequence_index": next_sequence,
        "trial_receipt_chain_sha256": final_chain,
        "ledger_reconciled": len(rows) > count or attempt_count > checkpoint_attempts,
        "engine_changed": bool(
            checkpoint_present
            and checkpoint.get("engine_source_sha256") != engine_source_sha256
        ),
        "config_changed": bool(
            checkpoint_present
            and checkpoint.get("campaign_config_sha256") != campaign_config_sha256
        ),
    }


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
    if path.is_symlink():
        raise ValueError("unsafe Copy-Vault trial ledger symlink")
    if not path.exists():
        return []
    if not path.is_file():
        raise ValueError("unsafe Copy-Vault trial ledger")
    rows: list[dict[str, Any]] = []
    signatures: set[str] = set()
    sequences: set[int] = set()
    trial_numbers: set[int] = set()
    with path.open("r", encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            try:
                row = json.loads(line)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"trial ledger corrupted at line {number}") from exc
            if (
                not isinstance(row, dict)
                or row.get("schema") not in {
                    "hypersmart.copy_vault_local_trial.v1",
                    "hypersmart.copy_vault_local_trial.v2",
                }
                or row.get("selection_digest") != selection_digest
                or not isinstance(row.get("parameter_signature"), str)
                or not isinstance(row.get("parameters"), dict)
                or row.get("parameter_signature") != parameter_hash(row["parameters"])
                or type(row.get("sequence_index")) is not int
                or row.get("sequence_index", 0) <= 0
                or type(row.get("trial_number")) is not int
                or row.get("trial_number", 0) <= 0
                or row.get("trial_number") in trial_numbers
                or row.get("paper_read_only") is not True
                or row.get("real_execution") is not False
                or row.get("parameter_signature") in signatures
                or row.get("sequence_index") in sequences
            ):
                raise ValueError(f"trial ledger identity mismatch at line {number}")
            if row.get("schema") == "hypersmart.copy_vault_local_trial.v2":
                for key in (
                    "engine_source_sha256", "campaign_config_sha256",
                    "source_catalog_sha256", "source_asset_inventory_sha256",
                    "attempt_receipt_sha256",
                ):
                    value = row.get(key)
                    if (
                        not isinstance(value, str)
                        or len(value) != 64
                        or any(char not in "0123456789abcdef" for char in value)
                    ):
                        raise ValueError(
                            f"trial ledger lineage is invalid at line {number}: {key}"
                        )
                if (
                    type(row.get("proposal_seed")) is not int
                    or row.get("proposal_seed") != 0
                    or row.get("proposal_method") != "HALTON_RADICAL_INVERSE_V1"
                    or not isinstance(row.get("temporal_windows"), dict)
                ):
                    raise ValueError(f"trial ledger search config is invalid at line {number}")
            signatures.add(row["parameter_signature"])
            sequences.add(row["sequence_index"])
            trial_numbers.add(row["trial_number"])
            rows.append(row)
    _campaign_trial_chain(rows)
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
            attempt_path = campaign / "ATTEMPTS.jsonl"
            checkpoint_path = campaign / "CHECKPOINT.json"
            if trial_path.is_symlink() or attempt_path.is_symlink() or checkpoint_path.is_symlink():
                raise ValueError("prior Copy-Vault campaign receipt is symlinked")
            rows = _load_campaign_trials(trial_path, campaign.name)
            attempts = _load_campaign_attempts(attempt_path, campaign.name)
            checkpoint = None
            if checkpoint_path.is_file():
                checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
                if not isinstance(checkpoint, dict):
                    raise ValueError("prior Copy-Vault checkpoint is invalid")
            source_row = (attempts or rows or [{}])[0]
            state = _checkpoint_resume_state(
                checkpoint,
                rows,
                attempts=attempts,
                selection_digest=campaign.name,
                source_catalog_sha256=str(
                    (checkpoint or {}).get("source_catalog_sha256")
                    or source_row.get("source_catalog_sha256") or ""
                ),
                source_asset_inventory_sha256=str(
                    (checkpoint or {}).get("source_asset_inventory_sha256")
                    or source_row.get("source_asset_inventory_sha256") or ""
                ),
                engine_source_sha256=str(
                    (checkpoint or {}).get("engine_source_sha256")
                    or source_row.get("engine_source_sha256") or ""
                ),
                campaign_config_sha256=str(
                    (checkpoint or {}).get("campaign_config_sha256")
                    or source_row.get("campaign_config_sha256") or ""
                ),
            )
            total += state["campaign_attempts"]
    return total


def _daily_lcb(daily_values: object, trial_count: int) -> dict[str, Any]:
    if not isinstance(daily_values, (list, tuple)):
        return summarize_daily_values((), trial_count=trial_count)
    return summarize_daily_values(daily_values, trial_count=trial_count)


def _daily_lcb_rank(summary: Mapping[str, Any]) -> dict[str, Any]:
    """Adapt the active-day score and error bound to the shared rank guard."""
    return {
        "total_lcb_usd_exact_decimal": summary.get(
            "daily_mean_lcb_usd_exact_decimal"
        ),
        "total_lcb_numeric_error_bound_usd_exact_decimal": summary.get(
            "daily_mean_lcb_numeric_error_bound_usd_exact_decimal"
        ),
    }


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
    repository_root: str | Path | None = None,
    max_trials: int = 128,
    on_update: Callable[[Mapping[str, Any]], None] | None = None,
    input_change_check: Callable[[], bool] | None = None,
    leader_review_ledger_path: str | Path | None = None,
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
    source_inventory_error = _source_asset_inventory_error(input_manifest)
    if source_inventory_error is not None:
        return {
            "status": "UNMEASURABLE", "reason": source_inventory_error,
            "selection_digest": selection_digest,
            "source_asset_inventory_sha256": input_manifest.get(
                "source_asset_inventory_sha256"
            ),
            "candidates_tested": 0, "freeze_created": False,
            "economically_proven": False, "paper_read_only": True,
            "real_execution": False,
        }
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
    leader_review_persistence: dict[str, Any] = {"status": "NOT_REQUESTED"}
    leader_quality_train: dict[str, Any] = {}
    if leader_review_ledger_path is not None:
        try:
            from hl_observer.backtesting.copy_vault_v9_online_leader_quality_train import (
                explore_copy_vault_v9_online_leader_quality_train,
            )
            from hl_observer.research.leader_review_ledger import (
                append_copy_vault_v9_leader_reviews,
            )

            v9_metaorders, v9_books, causal_protocol_audit = (
                cv.select_causal_protocol_inputs(metaorders, books)
            )
            lifecycle_events, lifecycle_audit = (
                pipeline.charger_evenements_lifecycle_avec_audit(workspace)
            )
            v9_result = explore_copy_vault_v9_online_leader_quality_train(
                v9_metaorders,
                v9_books,
                lifecycle_events,
                input_audit={
                    "entries": entries_audit,
                    "metaorders": meta_audit,
                    "books": books_audit,
                    "causal_protocol": causal_protocol_audit,
                    "lifecycle": lifecycle_audit,
                },
            )
            v9_source_path = Path(
                explore_copy_vault_v9_online_leader_quality_train.__code__.co_filename
            )
            engine_sha256 = _sha256(v9_source_path)
            leader_review_persistence = append_copy_vault_v9_leader_reviews(
                leader_review_ledger_path,
                v9_result,
                safe_inventory=input_manifest,
                reviewer_id="copy-vault-v9-online-quality-train",
                max_evidence_age_ms=_LEADER_REVIEW_MAX_EVIDENCE_AGE_MS,
                engine_sha256=engine_sha256,
            )
            traces = v9_result.get("leader_decision_traces", {}).get("traces", [])
            leader_quality_train = {
                "schema_version": v9_result.get("schema_version"),
                "status": v9_result.get("status"),
                "selection_scope": v9_result.get("selection_scope"),
                "heldout_evaluated": v9_result.get("heldout_evaluated"),
                "selection_eligible": v9_result.get("selection_eligible"),
                "decision_count": sum(
                    len(trace.get("decisions", []))
                    for trace in traces if isinstance(trace, Mapping)
                ),
                "trace_count": len(traces),
                "engine_sha256": engine_sha256,
                "max_evidence_age_ms": _LEADER_REVIEW_MAX_EVIDENCE_AGE_MS,
                "decision_authority": "CONSULTATIVE_ONLY_CANONICAL_GATES_REMAIN_AUTHORITATIVE",
            }
            say(
                "Revues leaders V9 TRAIN : "
                f"{leader_review_persistence.get('decision_count', 0)} décisions · "
                f"{leader_review_persistence.get('reviewable_count', 0)} mesurables · "
                f"{leader_review_persistence.get('unmeasurable_count', 0)} non mesurables · "
                f"registre {leader_review_persistence.get('status')}"
            )
        except Exception as exc:  # noqa: BLE001 - preserve an explicit failure without granting authority
            leader_review_persistence = {
                "status": "FAILED",
                "reason": f"{type(exc).__name__}: {exc}",
                "ledger_path": str(leader_review_ledger_path),
                "consultative_only": True,
                "can_change_decision": False,
                "can_modify_frozen_candidate": False,
                "can_modify_oos_forward_splits": False,
                "can_select_champion": False,
                "can_prove_pnl": False,
            }
            say("Revues leaders V9 TRAIN : échec de persistance explicite — " + leader_review_persistence["reason"])
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
        "source_asset_inventory_sha256": input_manifest.get(
            "source_asset_inventory_sha256"
        ),
        "source_asset_inventory_count": input_manifest.get(
            "source_asset_inventory_count"
        ),
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
        "leader_quality_v9_train": leader_quality_train,
        "leader_review_persistence": leader_review_persistence,
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
    repository_root = (
        Path(repository_root).resolve()
        if repository_root is not None
        else Path(__file__).resolve().parents[3]
    )
    campaign_config, campaign_config_sha = _campaign_search_config(bounds)
    engine_source_sha = _campaign_engine_source_sha256(pipeline)
    campaign_root = Path(campaign_root) if campaign_root else (
        repository_root / "runtime" / "codex_research" / "copy_vault_continuous_lab" / selection_digest
    )
    campaign_root.mkdir(parents=True, exist_ok=True)
    trial_path = campaign_root / "TRIALS.jsonl"
    attempt_path = campaign_root / "ATTEMPTS.jsonl"
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
        attempt_rows = _load_campaign_attempts(attempt_path, selection_digest)
        seen = {
            str(row["parameter_signature"])
            for row in [*history_rows, *attempt_rows]
        }
        checkpoint = None
        if checkpoint_path.is_symlink():
            raise ValueError("Copy-Vault checkpoint is symlinked")
        if checkpoint_path.is_file():
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            if not isinstance(checkpoint, dict):
                raise ValueError("Copy-Vault checkpoint must be an object")
        resume = _checkpoint_resume_state(
            checkpoint,
            history_rows,
            attempts=attempt_rows,
            selection_digest=selection_digest,
            source_catalog_sha256=source_catalog_sha,
            source_asset_inventory_sha256=str(
                input_manifest.get("source_asset_inventory_sha256") or ""
            ),
            engine_source_sha256=engine_source_sha,
            campaign_config_sha256=campaign_config_sha,
        )
        sequence_index = resume["next_sequence_index"]
        campaign_attempts = resume["campaign_attempts"]
        trial_chain = resume["trial_receipt_chain_sha256"]
        attempt_chain = resume["attempt_receipt_chain_sha256"]
        best = None
        if best is None:
            frozen_rows = [
                row for row in history_rows
                if row.get("strict_improvement_over_baseline_and_prior_best") is True
                and row.get("frozen_record") is not None
                and row.get("numeric_rank_resolved_against_comparators") is True
                and decimal_value(
                    row.get("daily_lcb_usd_per_active_day_exact_decimal")
                ) is not None
            ]
            if frozen_rows:
                recovered = max(
                    frozen_rows,
                    key=lambda row: decimal_value(
                        row["daily_lcb_usd_per_active_day_exact_decimal"]
                    ),
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
                        "daily_net_pnl_usd_exact_decimal": recovered.get(
                            "daily_net_pnl_usd_exact_decimal"
                        ),
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
                    "daily_net_pnl_usd_exact_decimal": list(
                        recovered.get("daily_net_pnl_usd_exact_decimal") or []
                    ),
                    "score_usd_per_active_day": float(recovered["daily_lcb_usd_per_active_day"]),
                    "score_usd_per_active_day_exact_decimal": recovered[
                        "daily_lcb_usd_per_active_day_exact_decimal"
                    ],
                    "trial_number": recovered_trial,
                }
        if resume["ledger_reconciled"]:
            say(
                f"Reprise réconciliée · {len(history_rows):,} essais durables · "
                f"séquence {sequence_index:,}"
            )
        if resume["engine_changed"] or resume["config_changed"]:
            say(
                "Nouvelle empreinte de moteur/configuration · les essais antérieurs "
                "restent archivés et chaque nouvel essai sera lié à ses empreintes."
            )
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
        if isinstance(best, dict) and isinstance(best.get("candidate"), Mapping):
            # Re-score the immutable incumbent on the same current TRAIN input
            # before comparing a challenger; old float-only receipts are not
            # sufficient evidence for a new promotion decision.
            try:
                incumbent_train = evaluate_frozen_v21_segment(
                    metaorders, books, best["candidate"], segment="train"
                )
                best["train"] = incumbent_train
                incumbent_statistics = incumbent_train.get("statistics") or {}
                incumbent_exact_days = incumbent_statistics.get(
                    "daily_net_pnl_usd_exact_decimal"
                )
                if isinstance(incumbent_exact_days, list):
                    best["daily_net_pnl_usd_exact_decimal"] = incumbent_exact_days
                    best["daily_net_pnl_usd"] = incumbent_statistics.get(
                        "daily_net_pnl_usd"
                    )
                else:
                    best["daily_net_pnl_usd_exact_decimal"] = None
                    best["daily_net_pnl_usd"] = None
            except (OSError, ValueError, TypeError, KeyError, RuntimeError):
                # Keep the frozen record, but do not compare or replace it using
                # an unmeasurable incumbent.
                best["incumbent_comparison_unmeasurable"] = True
                best["daily_net_pnl_usd_exact_decimal"] = None
                best["daily_net_pnl_usd"] = None
        base["baseline_comparison_basis"] = baseline_comparison_basis

        completed_this_run = 0
        duplicates_since_checkpoint = 0
        baseline_days = (
            (baseline_train.get("statistics") or {}).get(
                "daily_net_pnl_usd_exact_decimal"
            )
            or (baseline_train.get("statistics") or {}).get("daily_net_pnl_usd")
            if baseline_train else None
        )
        best_days = (
            best.get("daily_net_pnl_usd_exact_decimal")
            or best.get("daily_net_pnl_usd")
            if isinstance(best, dict) else None
        )
        if best_days is None and isinstance(best, dict):
            best_days = (best.get("train") or {}).get("daily_net_pnl_usd")
        status = "SEARCH_RUNNING"
        reason = "TRAIN_ONLY_SEARCH_CONTINUES_UNTIL_CTRL_C" if continuous else "BOUNDED_TRAIN_SEARCH_BATCH_COMPLETE"

        def persist_checkpoint(checkpoint_status: str) -> None:
            _atomic_json(checkpoint_path, {
                "schema": "hypersmart.copy_vault_search_checkpoint.v2",
                "selection_digest": selection_digest,
                "source_catalog_sha256": source_catalog_sha,
                "source_asset_inventory_sha256": input_manifest.get(
                    "source_asset_inventory_sha256"
                ),
                "engine_source_sha256": engine_source_sha,
                "campaign_config_sha256": campaign_config_sha,
                "campaign_config": campaign_config,
                "next_sequence_index": sequence_index,
                "campaign_trials": len(history_rows),
                "campaign_attempts": campaign_attempts,
                "attempt_receipt_count": len(attempt_rows),
                "global_trial_count": prior_trial_count + campaign_attempts,
                "trial_receipt_chain_sha256": trial_chain,
                "attempt_receipt_chain_sha256": attempt_chain,
                "best_candidate": best,
                "status": checkpoint_status,
                "updated_at_utc": datetime.now(UTC).isoformat(),
                "paper_read_only": True,
                "real_execution": False,
            })

        while trial_limit is None or completed_this_run < trial_limit:
            if len(seen) >= search_space_size:
                status, reason = "SEARCH_SPACE_EXHAUSTED", "ALL_VALID_PARAMETER_CONFIGURATIONS_ALREADY_TRIED"
                break
            if _candidate_parameters(sequence_index) is None:
                sequence_index += 1
                duplicates_since_checkpoint += 1
                if duplicates_since_checkpoint >= 1_000:
                    persist_checkpoint(status)
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
            trial_count = prior_trial_count + campaign_attempts + 1
            candidate_id = f"cv-{selection_digest[:12]}-{this_sequence:012d}"
            # Reserve the sequence before scoring/freezing so a crash cannot
            # reuse a candidate ID whose immutable freeze was already written.
            attempt = _attempt_with_receipt_chain({
                "schema": "hypersmart.copy_vault_local_attempt.v1",
                "selection_digest": selection_digest,
                "source_catalog_sha256": source_catalog_sha,
                "source_asset_inventory_sha256": input_manifest.get(
                    "source_asset_inventory_sha256"
                ),
                "engine_source_sha256": engine_source_sha,
                "campaign_config_sha256": campaign_config_sha,
                "proposal_method": campaign_config["proposal_method"],
                "proposal_seed": campaign_config["proposal_seed"],
                "temporal_windows": dict(bounds),
                "sequence_index": this_sequence,
                "trial_number": trial_count,
                "parameter_signature": signature,
                "parameters": params,
                "status": "TRIAL_RESERVED",
                "paper_read_only": True,
                "real_execution": False,
            }, attempt_chain)
            _append_jsonl(attempt_path, attempt)
            attempt_rows.append(attempt)
            attempt_chain = attempt["attempt_receipt_sha256"]
            campaign_attempts += 1
            seen.add(signature)
            persist_checkpoint("TRIAL_RESERVED")
            freeze = _candidate(params, bounds, max(timestamps) + 1, candidate_id, trial_count)
            say(
                f"Essai {trial_count} · séquence {this_sequence:,} · "
                f"{len(_PARAMETER_DOMAINS)} paramètres · capital {params['core_notional_usd'] + params['probe_notional_usd']:.0f}/200 USD"
            )
            train = evaluate_frozen_v21_segment(metaorders, books, freeze, segment="train")
            stats = train.get("statistics") if isinstance(train.get("statistics"), Mapping) else {}
            daily_values = list(stats.get("daily_net_pnl_usd") or [])
            daily_exact_values = list(
                stats.get("daily_net_pnl_usd_exact_decimal") or daily_values
            )
            candidate_lcb = _daily_lcb(daily_exact_values, trial_count)
            baseline_lcb = _daily_lcb(baseline_days, trial_count)
            incumbent_lcb = _daily_lcb(best_days, trial_count)
            candidate_score = decimal_value(
                candidate_lcb.get("daily_mean_lcb_usd_exact_decimal")
            )
            baseline_score = decimal_value(
                baseline_lcb.get("daily_mean_lcb_usd_exact_decimal")
            )
            incumbent_score = decimal_value(
                incumbent_lcb.get("daily_mean_lcb_usd_exact_decimal")
            )
            candidate_score_display = (
                float_not_above(candidate_score) if candidate_score is not None else None
            )
            baseline_score_display = (
                float_not_above(baseline_score) if baseline_score is not None else None
            )
            incumbent_score_display = (
                float_not_above(incumbent_score) if incumbent_score is not None else None
            )
            comparison_summaries = [baseline_lcb]
            if isinstance(best, dict):
                comparison_summaries.append(incumbent_lcb)
            comparison_scores = [
                decimal_value(item.get("daily_mean_lcb_usd_exact_decimal"))
                for item in comparison_summaries
            ]
            comparison_bounds = [
                decimal_value(
                    item.get("daily_mean_lcb_numeric_error_bound_usd_exact_decimal")
                )
                for item in comparison_summaries
            ]
            comparison_floor = (
                max(value for value in comparison_scores if value is not None)
                if comparison_scores and all(value is not None for value in comparison_scores)
                else None
            )
            comparison_rank_resolved = bool(
                candidate_score is not None
                and all(value is not None for value in comparison_scores)
                and all(value is not None for value in comparison_bounds)
                and all(
                    candidate_score > benchmark
                    and lcb_rank_is_numerically_resolved(
                        _daily_lcb_rank(candidate_lcb),
                        _daily_lcb_rank(summary),
                    )
                    for benchmark, summary in zip(
                        comparison_scores, comparison_summaries, strict=True
                    )
                    if benchmark is not None
                )
            )
            improvement_exact = (
                decimal_difference(candidate_score, comparison_floor)
                if candidate_score is not None and comparison_floor is not None
                else None
            )
            improvement_display = (
                float_not_above(improvement_exact)
                if improvement_exact is not None else None
            )
            improvement = (
                train.get("eligible") is True
                and candidate_score is not None
                and candidate_score_display is not None
                and comparison_floor is not None
                and improvement_display is not None
                and comparison_rank_resolved
                and prior_count_known
            )
            trial = {
                "schema": "hypersmart.copy_vault_local_trial.v2",
                "selection_digest": selection_digest,
                "source_asset_inventory_sha256": input_manifest.get(
                    "source_asset_inventory_sha256"
                ),
                "source_catalog_sha256": input_manifest.get("source_index_sha256"),
                "attempt_receipt_sha256": attempt["attempt_receipt_sha256"],
                "engine_source_sha256": engine_source_sha,
                "campaign_config_sha256": campaign_config_sha,
                "proposal_method": campaign_config["proposal_method"],
                "proposal_seed": campaign_config["proposal_seed"],
                "temporal_windows": dict(bounds),
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
                "daily_lcb_usd_per_active_day": candidate_score_display,
                "daily_lcb_usd_per_active_day_exact_decimal": (
                    format(candidate_score, "f") if candidate_score is not None else None
                ),
                "daily_lcb_numeric_error_bound_usd_exact_decimal": candidate_lcb.get(
                    "daily_mean_lcb_numeric_error_bound_usd_exact_decimal"
                ),
                "daily_net_pnl_usd": daily_values,
                "daily_net_pnl_usd_exact_decimal": daily_exact_values,
                "baseline_lcb_usd_per_active_day": baseline_score_display,
                "baseline_lcb_usd_per_active_day_exact_decimal": (
                    format(baseline_score, "f") if baseline_score is not None else None
                ),
                "baseline_comparison_basis": baseline_comparison_basis,
                "numeric_rank_resolved_against_comparators": comparison_rank_resolved,
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
                        "baseline_score": baseline_score_display,
                        "baseline_score_exact_decimal": (
                            format(baseline_score, "f") if baseline_score is not None else None
                        ),
                        "candidate_score": candidate_score_display,
                        "candidate_score_exact_decimal": (
                            format(candidate_score, "f") if candidate_score is not None else None
                        ),
                        "improvement": improvement_display,
                        "improvement_exact_decimal": (
                            format(improvement_exact, "f")
                            if improvement_exact is not None else None
                        ),
                        "baseline_daily_mean": baseline_train.get("active_day_mean_net_pnl_usd") if baseline_train else None,
                        "candidate_daily_mean": train.get("active_day_mean_net_pnl_usd"),
                        "prior_best_score": incumbent_score_display,
                        "prior_best_score_exact_decimal": (
                            format(incumbent_score, "f") if incumbent_score is not None else None
                        ),
                        "trial_count": trial_count,
                        "baseline_comparison_basis": baseline_comparison_basis,
                        "numeric_rank_resolved": comparison_rank_resolved,
                    },
                    "selection_digest": selection_digest,
                    "source_asset_inventory_sha256": input_manifest.get(
                        "source_asset_inventory_sha256"
                    ),
                    "source_asset_inventory_count": input_manifest.get(
                        "source_asset_inventory_count"
                    ),
                    "source_catalog_sha256": input_manifest.get("source_index_sha256"),
                    "engine_source_sha256": engine_source_sha,
                    "campaign_config_sha256": campaign_config_sha,
                    "proposal_method": campaign_config["proposal_method"],
                    "proposal_seed": campaign_config["proposal_seed"],
                    "temporal_windows": dict(bounds),
                    "attempt_receipt_sha256": attempt["attempt_receipt_sha256"],
                    "paper_capital_usd": PAPER_CAPITAL_USD,
                    "paper_read_only": True,
                    "real_execution": False,
                    "candidate_history_path": str(trial_path),
                    "attempt_history_path": str(attempt_path),
                    "checkpoint_path": str(checkpoint_path),
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
                    "daily_net_pnl_usd_exact_decimal": daily_exact_values,
                    "score_usd_per_active_day": candidate_score_display,
                    "score_usd_per_active_day_exact_decimal": (
                        format(candidate_score, "f") if candidate_score is not None else None
                    ),
                    "trial_number": trial_count,
                }
                best_days = daily_exact_values
                say(f"CANDIDAT GELÉ · {candidate_id} · amélioration conservative {improvement_display:+.6f} USD/jour actif TRAIN")
            trial["frozen_record"] = frozen_record
            trial["campaign_config"] = campaign_config
            trial = _trial_with_receipt_chain(trial, trial_chain)
            _append_jsonl(trial_path, trial)
            history_rows.append(trial)
            trial_chain = trial["trial_receipt_sha256"]
            seen.add(signature)
            completed_this_run += 1
            persist_checkpoint(status)
            update = {
                **base,
                "status": status,
                "reason": reason,
                "candidates_tested": len(history_rows),
                "trials_this_run": completed_this_run,
                "campaign_attempts": campaign_attempts,
                "global_trial_count": trial_count,
                "search_space_upper_bound": search_space_size,
                "best_candidate": best,
                "baseline_train": baseline_train,
                "last_trial": trial,
                "last_attempt_receipt_sha256": trial["attempt_receipt_sha256"],
                "freeze_created": best is not None,
                "economically_proven": False,
                "heldout_evaluated": False,
                "candidate_history_path": str(trial_path),
                "attempt_history_path": str(attempt_path),
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
            "global_trial_count": prior_trial_count + campaign_attempts,
            "campaign_attempts": campaign_attempts,
            "global_trial_count_source_known": prior_count_known,
            "search_space_upper_bound": search_space_size,
            "selected_candidate": best.get("candidate") if isinstance(best, dict) else None,
            "train": final_best_train,
            "baseline_train": baseline_train,
            "freeze_created": best is not None,
            "economically_proven": False,
            "heldout_evaluated": False,
            "candidate_history_path": str(trial_path),
            "attempt_history_path": str(attempt_path),
            "checkpoint_path": str(checkpoint_path),
            "resume_reconciled": resume["ledger_reconciled"],
            "engine_source_sha256": engine_source_sha,
            "campaign_config_sha256": campaign_config_sha,
            "data_complete": input_manifest.get("data_complete") is True,
            "paper_read_only": True,
            "real_execution": False,
        }
    except KeyboardInterrupt:
        try:
            durable_rows = _load_campaign_trials(trial_path, selection_digest)
            durable_attempts = _load_campaign_attempts(attempt_path, selection_digest)
            durable_state = _checkpoint_resume_state(
                None,
                durable_rows,
                attempts=durable_attempts,
                selection_digest=selection_digest,
                source_catalog_sha256=source_catalog_sha,
                source_asset_inventory_sha256=str(
                    input_manifest.get("source_asset_inventory_sha256") or ""
                ),
                engine_source_sha256=engine_source_sha,
                campaign_config_sha256=campaign_config_sha,
            )
        except (OSError, ValueError, TypeError) as exc:
            return {
                **base,
                "status": "TECHNICAL_FAILURE",
                "reason": f"INTERRUPTED_TRIAL_LEDGER_UNSAFE:{type(exc).__name__}:{exc}",
                "candidates_tested": 0,
                "freeze_created": False,
                "economically_proven": False,
                "paper_read_only": True,
                "real_execution": False,
            }
        durable_chain, _ = _campaign_trial_chain(durable_rows)
        durable_attempt_chain, _ = _campaign_attempt_chain(durable_attempts)
        durable_sequences = [int(row["sequence_index"]) for row in durable_rows]
        durable_sequences.extend(int(row["sequence_index"]) for row in durable_attempts)
        next_sequence = max(
            sequence_index if "sequence_index" in locals() else 1,
            max(durable_sequences, default=0) + 1,
        )
        best = locals().get("best")
        if isinstance(best, dict):
            durable_trial_numbers = {
                int(row["trial_number"])
                for row in durable_rows
                if row.get("frozen_record") is not None
                and row.get("strict_improvement_over_baseline_and_prior_best") is True
            }
            if best.get("trial_number") not in durable_trial_numbers:
                best = None
        _atomic_json(checkpoint_path, {
            "schema": "hypersmart.copy_vault_search_checkpoint.v2",
            "selection_digest": selection_digest,
            "source_catalog_sha256": source_catalog_sha,
            "source_asset_inventory_sha256": input_manifest.get(
                "source_asset_inventory_sha256"
            ),
            "engine_source_sha256": engine_source_sha,
            "campaign_config_sha256": campaign_config_sha,
            "campaign_config": campaign_config,
            "next_sequence_index": next_sequence,
            "campaign_trials": len(durable_rows),
            "campaign_attempts": durable_state["campaign_attempts"],
            "attempt_receipt_count": len(durable_attempts),
            "global_trial_count": int(locals().get("prior_trial_count") or 0)
            + durable_state["campaign_attempts"],
            "trial_receipt_chain_sha256": durable_chain,
            "attempt_receipt_chain_sha256": durable_attempt_chain,
            "best_candidate": best,
            "status": "INTERRUPTED",
            "updated_at_utc": datetime.now(UTC).isoformat(),
            "paper_read_only": True,
            "real_execution": False,
        })
        return {
            **base,
            "status": "INTERRUPTED",
            "reason": "USER_CTRL_C_COMPLETED_TRIALS_CHECKPOINTED",
            "candidates_tested": len(durable_rows),
            "campaign_attempts": durable_state["campaign_attempts"],
            "global_trial_count": int(locals().get("prior_trial_count") or 0)
            + durable_state["campaign_attempts"],
            "selected_candidate": best.get("candidate")
            if isinstance(best, dict) else None,
            "freeze_created": isinstance(best, dict),
            "economically_proven": False,
            "heldout_evaluated": False,
            "candidate_history_path": str(trial_path),
            "attempt_history_path": str(attempt_path),
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
    source_inventory_error = _source_asset_inventory_error(input_manifest)
    if source_inventory_error is not None:
        return {
            "status": "UNMEASURABLE", "reason": source_inventory_error,
            "selection_digest": input_manifest.get("selection_digest"),
            "source_asset_inventory_sha256": input_manifest.get(
                "source_asset_inventory_sha256"
            ),
            "economically_proven": False,
            "paper_read_only": True,
            "real_execution": False,
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
        "selection_digest": input_manifest.get("selection_digest"),
        "source_asset_inventory_sha256": input_manifest.get(
            "source_asset_inventory_sha256"
        ),
        "source_asset_inventory_count": input_manifest.get(
            "source_asset_inventory_count"
        ),
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


def _improvement_receipt_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in row.items()
        if key != "receipt_sha256"
    }


def _improvement_content(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in row.items()
        if key not in {"previous_receipt_sha256", "receipt_sha256"}
    }


def _load_improvement_history_unlocked(root: str | Path) -> list[dict[str, Any]]:
    ledger = Path(root) / "runtime" / "codex_research" / "copy_vault_improvements" / "HISTORY.jsonl"
    if ledger.is_symlink():
        raise ValueError("COPY_VAULT_IMPROVEMENT_HISTORY_SYMLINKED")
    if not ledger.exists():
        return []
    rows: list[dict[str, Any]] = []
    seen_run_ids: set[str] = set()
    previous = _IMPROVEMENT_CHAIN_GENESIS
    try:
        with ledger.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                try:
                    row = json.loads(line)
                except (TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise ValueError(
                        f"COPY_VAULT_IMPROVEMENT_HISTORY_JSON_INVALID line {line_number}"
                    ) from exc
                if not isinstance(row, dict):
                    raise ValueError(
                        f"COPY_VAULT_IMPROVEMENT_HISTORY_ROW_INVALID line {line_number}"
                    )
                run_id = row.get("run_id")
                if not isinstance(run_id, str) or not run_id or run_id in seen_run_ids:
                    raise ValueError(
                        f"COPY_VAULT_IMPROVEMENT_HISTORY_ID_INVALID line {line_number}"
                    )
                schema = row.get("schema_version")
                if schema == "hypersmart.copy_vault_local_improvement.v1":
                    if "previous_receipt_sha256" in row or "receipt_sha256" in row:
                        raise ValueError(
                            f"COPY_VAULT_IMPROVEMENT_HISTORY_LEGACY_RECEIPT_INVALID line {line_number}"
                        )
                    digest = _canonical_json_sha256(row)
                elif schema == "hypersmart.copy_vault_local_improvement.v2":
                    if row.get("previous_receipt_sha256") != previous:
                        raise ValueError(
                            f"COPY_VAULT_IMPROVEMENT_HISTORY_PREDECESSOR_MISMATCH line {line_number}"
                        )
                    supplied = row.get("receipt_sha256")
                    if (
                        not isinstance(supplied, str)
                        or len(supplied) != 64
                        or any(char not in "0123456789abcdef" for char in supplied)
                        or supplied != _canonical_json_sha256(_improvement_receipt_payload(row))
                    ):
                        raise ValueError(
                            f"COPY_VAULT_IMPROVEMENT_HISTORY_RECEIPT_HASH_MISMATCH line {line_number}"
                        )
                    digest = supplied
                else:
                    raise ValueError(
                        f"COPY_VAULT_IMPROVEMENT_HISTORY_SCHEMA_INVALID line {line_number}"
                    )
                previous = digest
                seen_run_ids.add(run_id)
                rows.append(row)
    except UnicodeDecodeError as exc:
        raise ValueError("COPY_VAULT_IMPROVEMENT_HISTORY_ENCODING_INVALID") from exc
    return rows


def load_improvement_history(root: str | Path) -> list[dict[str, Any]]:
    registry = Path(root) / "runtime" / "codex_research" / "copy_vault_improvements"
    ledger = registry / "HISTORY.jsonl"
    lock_path = registry / ".HISTORY.lock"
    if registry.is_symlink() or ledger.is_symlink() or lock_path.is_symlink():
        raise ValueError("COPY_VAULT_IMPROVEMENT_HISTORY_SYMLINKED")
    if not ledger.exists():
        return []
    try:
        with SingleWriterFileLock(lock_path):
            return _load_improvement_history_unlocked(root)
    except WriterBusy as exc:
        raise ValueError("COPY_VAULT_IMPROVEMENT_HISTORY_LOCK_BUSY") from exc


def _has_complete_economic_proof(result: Mapping[str, Any]) -> bool:
    if (
        result.get("economically_proven") is not True
        or result.get("status") != "PROVEN"
        or result.get("heldout_evaluated") is not True
        or result.get("paper_read_only") is not True
        or result.get("real_execution") is not False
        or result.get("data_complete") is not True
        or decimal_value(result.get("paper_capital_usd")) != Decimal(str(PAPER_CAPITAL_USD))
    ):
        return False
    for segment_name in ("validation", "oos", "forward"):
        segment = result.get(segment_name)
        if (
            not isinstance(segment, Mapping)
            or segment.get("eligible") is not True
            or segment.get("heldout_evaluated") is not True
            or segment.get("retuned_on_heldout") is not False
        ):
            return False
    return True


def _append_improvement_receipt(path: Path, receipt: Mapping[str, Any]) -> None:
    encoded = (
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")
    flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    fd = os.open(path, flags, 0o600)
    try:
        remaining = memoryview(encoded)
        while remaining:
            written = os.write(fd, remaining)
            if written <= 0:
                raise OSError("COPY_VAULT_IMPROVEMENT_HISTORY_APPEND_INCOMPLETE")
            remaining = remaining[written:]
        os.fsync(fd)
    finally:
        os.close(fd)


def record_frozen_candidate(
    root: str | Path,
    run_id: str,
    economic_result: Mapping[str, Any],
    current_copy_vault: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Persist every selected candidate without ever overwriting an older one."""
    if economic_result.get("freeze_created") is not True:
        return None
    if not isinstance(run_id, str) or _IMPROVEMENT_RUN_ID_RE.fullmatch(run_id) is None:
        raise ValueError("COPY_VAULT_IMPROVEMENT_RUN_ID_INVALID")
    root = Path(root)
    registry = root / "runtime" / "codex_research" / "copy_vault_improvements"
    entries = registry / "entries"
    ledger = registry / "HISTORY.jsonl"
    lock_path = registry / ".HISTORY.lock"
    if registry.is_symlink() or entries.is_symlink() or ledger.is_symlink() or lock_path.is_symlink():
        raise OSError("COPY_VAULT_IMPROVEMENT_HISTORY_SYMLINKED")
    registry.mkdir(parents=True, exist_ok=True)
    entries.mkdir(parents=True, exist_ok=True)
    if registry.is_symlink() or entries.is_symlink() or ledger.is_symlink() or lock_path.is_symlink():
        raise OSError("COPY_VAULT_IMPROVEMENT_HISTORY_SYMLINKED")
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
    economic_proven = _has_complete_economic_proof(economic_result)
    classification = (
        "ECONOMICALLY_PROVEN_IMPROVEMENT"
        if economic_proven and improvement is not None and improvement > 0
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
    record: dict[str, Any] = {
        "schema_version": "hypersmart.copy_vault_local_improvement.v2",
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
        "source_asset_inventory_sha256": economic_result.get("source_asset_inventory_sha256"),
        "source_asset_inventory_count": economic_result.get("source_asset_inventory_count"),
        "engine_source_sha256": economic_result.get("engine_source_sha256"),
        "campaign_config_sha256": economic_result.get("campaign_config_sha256"),
        "proposal_method": economic_result.get("proposal_method"),
        "proposal_seed": economic_result.get("proposal_seed"),
        "temporal_windows": economic_result.get("temporal_windows"),
        "attempt_receipt_sha256": economic_result.get("attempt_receipt_sha256"),
        "trial_receipt_sha256": economic_result.get("trial_receipt_sha256"),
        "candidate_history_path": economic_result.get("candidate_history_path"),
        "attempt_history_path": economic_result.get("attempt_history_path"),
        "checkpoint_path": economic_result.get("checkpoint_path"),
        "restoration_receipt": economic_result.get("restoration_receipt"),
        "paper_capital_usd": economic_result.get("paper_capital_usd"),
        "data_complete": economic_result.get("data_complete") is True,
        "heldout_evaluated": economic_result.get("heldout_evaluated") is True,
        "trial_number": comparison.get("trial_count"),
        "economically_proven": economic_proven,
        "candidate_status": economic_result.get("status"),
        "candidate": economic_result.get("selected_candidate"),
        "proof_gates": {
            segment: {
                "eligible": (
                    economic_result.get(segment, {}).get("eligible")
                    if isinstance(economic_result.get(segment), Mapping) else None
                ),
                "heldout_evaluated": (
                    economic_result.get(segment, {}).get("heldout_evaluated")
                    if isinstance(economic_result.get(segment), Mapping) else None
                ),
                "retuned_on_heldout": (
                    economic_result.get(segment, {}).get("retuned_on_heldout")
                    if isinstance(economic_result.get(segment), Mapping) else None
                ),
            }
            for segment in ("validation", "oos", "forward")
        },
        "paper_read_only": True,
        "real_execution": False,
    }
    target = entries / f"{run_id}.json"
    try:
        with SingleWriterFileLock(lock_path):
            history = _load_improvement_history_unlocked(root)
            existing_receipt = next(
                (row for row in history if row.get("run_id") == run_id), None
            )
            if existing_receipt is not None:
                if _improvement_content(existing_receipt) != record:
                    raise RuntimeError("IMMUTABLE_COPY_VAULT_CANDIDATE_CONFLICT")
                record = existing_receipt
            else:
                previous = (
                    str(history[-1].get("receipt_sha256") or "")
                    if history and history[-1].get("schema_version")
                    == "hypersmart.copy_vault_local_improvement.v2"
                    else _canonical_json_sha256(history[-1])
                    if history else _IMPROVEMENT_CHAIN_GENESIS
                )
                record["previous_receipt_sha256"] = previous
                record["receipt_sha256"] = _canonical_json_sha256(
                    _improvement_receipt_payload(record)
                )

            if target.is_symlink():
                raise OSError("IMMUTABLE_COPY_VAULT_CANDIDATE_SYMLINKED")
            if target.exists():
                try:
                    existing_entry = json.loads(target.read_text(encoding="utf-8"))
                except (OSError, ValueError, TypeError) as exc:
                    raise RuntimeError("IMMUTABLE_COPY_VAULT_CANDIDATE_INVALID") from exc
                if existing_entry != record:
                    raise RuntimeError("IMMUTABLE_COPY_VAULT_CANDIDATE_CONFLICT")
            else:
                temporary = entries / (
                    f".{run_id}.{os.getpid()}.{random.getrandbits(64):016x}.partial"
                )
                with temporary.open("x", encoding="utf-8", newline="\n") as handle:
                    handle.write(json.dumps(
                        record, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False
                    ) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, target)

            if existing_receipt is None:
                _append_improvement_receipt(ledger, record)
    except WriterBusy as exc:
        raise RuntimeError("COPY_VAULT_IMPROVEMENT_HISTORY_LOCK_BUSY") from exc

    if classification == "ECONOMICALLY_PROVEN_IMPROVEMENT":
        champion = registry / "CURRENT_CHAMPION.json"
        temporary = registry / (
            f".CURRENT_CHAMPION.{os.getpid()}.{random.getrandbits(64):016x}.partial"
        )
        try:
            with SingleWriterFileLock(lock_path):
                if registry.is_symlink() or champion.is_symlink() or temporary.is_symlink():
                    raise OSError("COPY_VAULT_CURRENT_CHAMPION_SYMLINKED")
                should_promote = True
                if champion.exists():
                    try:
                        incumbent = json.loads(champion.read_text(encoding="utf-8"))
                    except (OSError, ValueError, TypeError) as exc:
                        raise RuntimeError("COPY_VAULT_CURRENT_CHAMPION_INVALID") from exc
                    if not isinstance(incumbent, Mapping):
                        raise RuntimeError("COPY_VAULT_CURRENT_CHAMPION_INVALID")
                    incumbent_daily = incumbent.get("candidate_daily_net_usd")
                    incumbent_segment = incumbent.get("comparison_segment")
                    incumbent_capital = incumbent.get("paper_capital_usd")
                    try:
                        incumbent_daily_value = float(incumbent_daily)
                        incumbent_capital_value = float(incumbent_capital)
                    except (TypeError, ValueError, OverflowError):
                        raise RuntimeError("COPY_VAULT_CURRENT_CHAMPION_INVALID") from None
                    if not math.isfinite(incumbent_daily_value) or not math.isfinite(
                        incumbent_capital_value
                    ):
                        raise RuntimeError("COPY_VAULT_CURRENT_CHAMPION_INVALID")
                    candidate_capital = economic_result.get("paper_capital_usd")
                    try:
                        candidate_capital_value = float(candidate_capital)
                    except (TypeError, ValueError, OverflowError):
                        candidate_capital_value = float("nan")
                    should_promote = (
                        incumbent_segment == record.get("comparison_segment")
                        and incumbent_capital_value == candidate_capital_value
                        and (record.get("candidate_daily_net_usd") or 0)
                        > incumbent_daily_value
                    )
                if should_promote:
                    with temporary.open("x", encoding="utf-8", newline="\n") as handle:
                        handle.write(json.dumps(
                            record, ensure_ascii=False, indent=2, sort_keys=True,
                            allow_nan=False,
                        ) + "\n")
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temporary, champion)
        except WriterBusy as exc:
            raise RuntimeError("COPY_VAULT_CURRENT_CHAMPION_LOCK_BUSY") from exc
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
    seen_trade_ids: set[str] = set()
    economic_keys = (
        "gross_pnl_usd",
        "fees_usd",
        "spread_cost_usd",
        "slippage_cost_usd",
        "latency_cost_usd",
        "net_pnl_usd",
    )
    for index, row in enumerate(trades):
        trade_id = str(row.get("trade_id") or "").strip()
        if not trade_id or trade_id in seen_trade_ids:
            return {
                "status": "UNAVAILABLE",
                "reason": "HISTORICAL_EXECUTABLE_TRADE_ID_INVALID_OR_DUPLICATE",
                "trial_count": 0,
                "economically_proven": False,
            }
        seen_trade_ids.add(trade_id)
        amounts = {key: decimal_value(row.get(key)) for key in economic_keys}
        if any(value is None for value in amounts.values()):
            return {
                "status": "UNAVAILABLE",
                "reason": f"HISTORICAL_EXECUTABLE_ECONOMICS_UNMEASURED:{index}",
                "trial_count": 0,
                "economically_proven": False,
            }
        costs = [amounts[key] for key in economic_keys[1:-1]]
        if any(value < 0 for value in costs):
            return {
                "status": "UNAVAILABLE",
                "reason": f"HISTORICAL_EXECUTABLE_NEGATIVE_COST:{index}",
                "trial_count": 0,
                "economically_proven": False,
            }
        recomputed_net = decimal_sum(
            (
                amounts["gross_pnl_usd"],
                *(value.copy_negate() for value in costs),
            )
        )
        if (
            recomputed_net is None
            or (recomputed_delta := decimal_difference(recomputed_net, amounts["net_pnl_usd"]))
            is None
            or recomputed_delta.copy_abs() > USD_RECONCILIATION_ABS_TOLERANCE
        ):
            return {
                "status": "UNAVAILABLE",
                "reason": f"HISTORICAL_EXECUTABLE_ECONOMIC_RECONCILIATION_FAILED:{index}",
                "trial_count": 0,
                "economically_proven": False,
            }
        row["_exact_costs_usd"] = tuple(costs)
        row["_exact_conservative_net_usd"] = min(
            recomputed_net, amounts["net_pnl_usd"]
        )
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
        with localcontext() as context:
            context.prec = 80
            scale = Decimal(str(capital)) / Decimal(str(exposure))
        fee_factor = Decimal(str(fee))
        spread_factor = Decimal(str(spread))
        latency_factor = Decimal(str(latency))
        slippage_factor = Decimal(str(slippage))
        daily_parts: dict[int, list[Decimal]] = {day: [] for day in all_days}
        for row in rows:
            fees, spread_cost, slippage_cost, latency_cost = row["_exact_costs_usd"]
            with localcontext() as context:
                context.prec = 80
                incremental_cost = (
                    fees * (fee_factor - Decimal(1))
                    + spread_cost * (spread_factor - Decimal(1))
                    + slippage_cost * (slippage_factor - Decimal(1))
                    + latency_cost * (latency_factor - Decimal(1))
                )
                stressed_net = (
                    row["_exact_conservative_net_usd"] - incremental_cost
                ) * scale
            daily_parts[int(row["exit_ts_ms"]) // 86_400_000].append(stressed_net)
        daily = {
            day: decimal_sum(parts) if parts else Decimal(0)
            for day, parts in daily_parts.items()
        }
        total_net = decimal_sum(daily.values())
        if total_net is None:
            raise ValueError("Historical Copy-Vault replay could not sum exact daily PnL")
        with localcontext() as context:
            context.prec = 80
            mean = total_net / Decimal(len(daily)) if daily else None
        mean_float = float_not_above(mean) if mean is not None else None
        total_float = float_not_above(total_net)
        if total_float is None or (mean is not None and mean_float is None):
            raise ValueError("Historical Copy-Vault replay PnL cannot be serialized")
        values = [float_not_above(value) for value in daily.values()]
        if any(value is None for value in values):
            raise ValueError("Historical Copy-Vault daily PnL is not serializable")
        return {
            "sample_count": len(rows), "distinct_complete_days": len(values),
            "daily_net_pnl_usd": mean_float,
            "daily_net_pnl_usd_exact_decimal": format(mean, "f") if mean is not None else None,
            "total_net_pnl_usd": total_float,
            "total_net_pnl_usd_exact_decimal": format(total_net, "f"),
            "_daily_values_exact": [format(value, "f") for value in daily.values()],
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
    def exact_daily_rank(row: Mapping[str, Any]) -> Decimal:
        value = decimal_value(row["daily_net_pnl_usd_exact_decimal"])
        return value if value is not None else Decimal("-Infinity")

    best = max(comparable, key=exact_daily_rank)
    rng = random.Random(21_200_540)
    bootstrap_rows = {id(row): row for row in (baseline, best)}
    for row in bootstrap_rows.values():
        values = [
            value
            for item in row.pop("_daily_values_exact", [])
            if (value := decimal_value(item)) is not None
        ]
        if not values:
            continue
        bootstrap: list[Decimal] = []
        for _ in range(max(100, int(bootstrap_samples))):
            sample_total = decimal_sum(rng.choice(values) for _day in values)
            if sample_total is None:
                continue
            with localcontext() as context:
                context.prec = 80
                context.rounding = ROUND_FLOOR
                bootstrap.append(sample_total / Decimal(len(values)))
        if not bootstrap:
            continue
        bootstrap.sort()
        p05 = bootstrap[int(len(bootstrap) * 0.05)]
        row["bootstrap_p05_usd_per_day"] = float_not_above(p05)
        row["bootstrap_p05_usd_per_day_exact_decimal"] = format(p05, "f")
    for row in trials:
        row.pop("_daily_values_exact", None)
    best_daily_exact = decimal_value(best["daily_net_pnl_usd_exact_decimal"])
    baseline_daily_exact = decimal_value(baseline["daily_net_pnl_usd_exact_decimal"])
    improvement_exact = (
        decimal_difference(best_daily_exact, baseline_daily_exact)
        if best_daily_exact is not None and baseline_daily_exact is not None
        else None
    )
    improvement = (
        float_not_above(improvement_exact) if improvement_exact is not None else None
    )
    if improvement is None:
        return {
            "status": "UNAVAILABLE",
            "reason": "HISTORICAL_EXECUTABLE_IMPROVEMENT_UNREPRESENTABLE",
            "trial_count": len(trials),
            "economically_proven": False,
        }
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
        "improvement_usd_per_day": improvement,
        "improvement_usd_per_day_exact_decimal": format(improvement_exact, "f"),
        "improvement_found": improvement_exact > 0,
        "trials": trials,
        "economically_proven": False,
        "paper_read_only": True, "real_execution": False,
    }


__all__ = [
    "OBJECTIVE_USD_PER_DAY", "PAPER_CAPITAL_USD", "evaluate_current_copy_vault",
    "load_improvement_history", "materialize_safe_workspace", "record_frozen_candidate",
    "run_historical_trade_replay", "run_local_campaign",
]
