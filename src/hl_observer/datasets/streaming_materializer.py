from __future__ import annotations

import shutil
import zipfile
import math
from collections import defaultdict
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence, Any

from hl_observer.datasets.github_release_bridge import (
    DatasetBridgeError,
    DatasetRecord,
    ReleaseAsset,
    verify_asset,
)
from hl_observer.datasets.release_gateway import _download_asset


DownloadAsset = Callable[
    [ReleaseAsset, Path],
    Path,
]


def _safe_destination(root: Path, relative_path: str) -> Path:
    resolved_root = root.resolve()
    destination = (resolved_root / relative_path).resolve()
    try:
        destination.relative_to(resolved_root)
    except ValueError as exc:
        raise DatasetBridgeError(
            f"Chemin dangereux refusé dans le dataset: {relative_path}"
        ) from exc
    return destination


def _verify_reconstructed(path: Path, record: DatasetRecord) -> None:
    from hl_observer.datasets.github_release_bridge import _sha256

    if not path.is_file():
        raise DatasetBridgeError(f"Fichier reconstruit absent: {path}")
    if path.stat().st_size != record.size:
        raise DatasetBridgeError(
            f"Taille reconstruite incorrecte pour {record.relative_path}: "
            f"{path.stat().st_size} != {record.size}"
        )
    if record.sha256 and _sha256(path).lower() != record.sha256.lower():
        raise DatasetBridgeError(
            f"SHA-256 reconstruit incorrect pour {record.relative_path}"
        )


def _default_downloader(
    asset: ReleaseAsset,
    cache_dir: Path,
    *,
    repository: str,
    force: bool,
) -> Path:
    return _download_asset(
        asset,
        cache_dir,
        repository=repository,
        force=force,
    )


def materialize_records_streaming(
    records: Iterable[DatasetRecord],
    assets: Mapping[str, ReleaseAsset],
    output_root: Path,
    cache_dir: Path,
    *,
    repository: str,
    force: bool = False,
    purge_assets_after_use: bool = True,
    downloader: Callable[..., Path] | None = None,
) -> dict[str, object]:
    """Materialize a selection while keeping at most one large asset resident.

    ZIP assets are downloaded one-by-one, all selected members are extracted,
    then the asset can be removed. Raw chunk records are reconstructed in
    chunk order, downloading/deleting each chunk sequentially.

    The source Release remains immutable; only the local cache/workspace is
    written. Final file size and SHA-256 are checked before success.
    """

    rows = list(records)
    output_root.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    fetch = downloader or _default_downloader
    by_zip: dict[str, list[DatasetRecord]] = defaultdict(list)
    raw_records: list[DatasetRecord] = []
    seen_output_paths: set[str] = set()

    for record in rows:
        if not record.relative_path or record.relative_path in seen_output_paths:
            raise DatasetBridgeError(
                f"Chemin de sortie absent ou dupliqué: {record.relative_path}"
            )
        seen_output_paths.add(record.relative_path)
        if record.storage == "zip_entry":
            if not record.asset:
                raise DatasetBridgeError(
                    f"Archive absente du manifeste pour {record.relative_path}"
                )
            by_zip[record.asset].append(record)
        elif record.storage == "raw_chunks":
            raw_records.append(record)
        else:
            raise DatasetBridgeError(
                f"Stockage inconnu pour {record.relative_path}: {record.storage}"
            )

    created: list[Path] = []
    downloaded_names: list[str] = []
    purged_names: list[str] = []
    max_asset_size = 0

    def obtain(name: str) -> tuple[ReleaseAsset, Path]:
        asset = assets.get(name)
        if asset is None:
            raise DatasetBridgeError(
                f"Fichier référencé mais absent de la Release: {name}"
            )
        nonlocal max_asset_size
        max_asset_size = max(max_asset_size, int(asset.size))
        try:
            path = fetch(
                asset,
                cache_dir,
                repository=repository,
                force=force,
            )
        except TypeError:
            # Small injectable fakes used by unit tests may only accept two args.
            path = fetch(asset, cache_dir)
        verify_asset(path, asset)
        downloaded_names.append(name)
        return asset, path

    def purge(path: Path, name: str) -> None:
        if not purge_assets_after_use:
            return
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise DatasetBridgeError(
                f"Impossible de purger l'asset temporaire {name}: {exc}"
            ) from exc
        purged_names.append(name)

    for asset_name in sorted(by_zip):
        _, archive_path = obtain(asset_name)
        group = by_zip[asset_name]
        try:
            with zipfile.ZipFile(archive_path, "r") as archive:
                available = set(archive.namelist())
                for record in group:
                    member = record.relative_path
                    if member not in available:
                        raise DatasetBridgeError(
                            f"{member} est absent de {asset_name}"
                        )
                    destination = _safe_destination(
                        output_root,
                        record.relative_path,
                    )
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    temporary = destination.with_suffix(
                        destination.suffix + ".part"
                    )
                    temporary.unlink(missing_ok=True)
                    try:
                        with archive.open(member, "r") as source, temporary.open(
                            "wb"
                        ) as target:
                            shutil.copyfileobj(
                                source,
                                target,
                                length=8 * 1024 * 1024,
                            )
                        temporary.replace(destination)
                        _verify_reconstructed(destination, record)
                    except Exception:
                        temporary.unlink(missing_ok=True)
                        raise
                    created.append(destination)
        finally:
            purge(archive_path, asset_name)

    for record in raw_records:
        chunks = list(record.chunks)
        if not chunks:
            raise DatasetBridgeError(
                f"Aucun morceau pour {record.relative_path}"
            )
        parts: list[int] = []
        for chunk in chunks:
            part = chunk.get("part")
            if isinstance(part, bool) or not isinstance(part, int) or part <= 0:
                raise DatasetBridgeError(
                    f"Numéro de morceau invalide pour {record.relative_path}"
                )
            if not str(chunk.get("asset") or "").strip():
                raise DatasetBridgeError(
                    f"Nom de morceau absent pour {record.relative_path}"
                )
            parts.append(part)
        expected_parts = list(range(1, len(parts) + 1))
        if sorted(parts) != expected_parts:
            raise DatasetBridgeError(
                f"Morceaux dupliqués ou non contigus pour {record.relative_path}"
            )
        chunks.sort(key=lambda item: item["part"])

        destination = _safe_destination(
            output_root,
            record.relative_path,
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".part")
        temporary.unlink(missing_ok=True)

        try:
            with temporary.open("wb") as target:
                for chunk in chunks:
                    asset_name = str(chunk.get("asset") or "")
                    _, chunk_path = obtain(asset_name)
                    try:
                        with chunk_path.open("rb") as source:
                            shutil.copyfileobj(
                                source,
                                target,
                                length=8 * 1024 * 1024,
                            )
                    finally:
                        purge(chunk_path, asset_name)
            temporary.replace(destination)
            _verify_reconstructed(destination, record)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        created.append(destination)

    return {
        "created_files": len(created),
        "created_paths": [str(path) for path in created],
        "downloaded_asset_count": len(downloaded_names),
        "downloaded_assets": downloaded_names,
        "purged_asset_count": len(purged_names),
        "purged_assets": purged_names,
        "max_asset_size_bytes": max_asset_size,
        "purge_assets_after_use": bool(purge_assets_after_use),
    }


def materialization_safety_receipt(
    output_root: Path,
    records: Iterable[DatasetRecord],
    *,
    max_total_bytes: int = 2_000_000_000,
) -> dict[str, object]:
    """Preflight member paths and declared sizes before any materialization."""
    rows = list(records)
    if max_total_bytes < 0:
        return {"status": "UNMEASURABLE", "reason": "MAX_BYTES_INVALID"}
    total = 0
    seen: set[str] = set()
    try:
        for record in rows:
            if record.relative_path in seen or not record.relative_path:
                return {"status": "REJECTED", "reason": "DUPLICATE_OR_EMPTY_MEMBER"}
            seen.add(record.relative_path)
            if record.size < 0:
                return {"status": "REJECTED", "reason": "NEGATIVE_MEMBER_SIZE"}
            _safe_destination(output_root, record.relative_path)
            total += int(record.size)
            if total > int(max_total_bytes):
                return {"status": "REJECTED", "reason": "DECLARED_EXPANSION_LIMIT_EXCEEDED"}
    except DatasetBridgeError as exc:
        return {"status": "REJECTED", "reason": str(exc)}
    return {"status": "PROVEN", "member_count": len(rows), "declared_bytes": total, "paths_checked": True, "zipbomb_guarded": True}


def streaming_codec_receipt(
    records: Iterable[Mapping[str, object]], *, codec: str,
) -> dict[str, object]:
    """Validate extraction order for supported codecs without decoding guesses."""
    normalized_codec = str(codec).strip().lower()
    if normalized_codec not in {"none", "identity", "gzip"}:
        return {"status": "UNMEASURABLE", "reason": "CODEC_UNSUPPORTED"}
    rows = list(records)
    sequence: list[int] = []
    for row in rows:
        value = row.get("sequence")
        if type(value) is not int or value < 0:
            return {"status": "UNMEASURABLE", "reason": "SEQUENCE_INVALID"}
        sequence.append(value)
    ordered = sequence == sorted(sequence) and len(sequence) == len(set(sequence))
    return {
        "status": "PROVEN" if ordered else "REJECTED",
        "reason": "CODEC_ORDER_PRESERVED" if ordered else "CODEC_ORDER_OR_DUPLICATE_MISMATCH",
        "codec": normalized_codec,
        "records": len(rows),
        "sequence": tuple(sequence),
        "paper_read_only": True,
        "real_execution": False,
    }


def _base(status: str, **values: Any) -> dict[str, Any]:
    return {"status": status, "paper_read_only": True, "real_execution": False, "promotion": "DISABLED_UNTIL_REVIEW", **values}


def _fini(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _entier(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def materialization_required_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) not in (None, "")
    return _base("PROVEN" if valid else "REJECTED", verdict="MATERIALIZATION_FIELD_PRESENT" if valid else "MATERIALIZATION_FIELD_MISSING", field=field, fail_closed=not valid)


def materialization_null_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) is not None
    return _base("PROVEN" if valid else "REJECTED", verdict="MATERIALIZATION_FIELD_NON_NULL" if valid else "MATERIALIZATION_FIELD_NULL", field=field, fail_closed=not valid)


def materialization_field_type_receipt(row: Mapping[str, Any], *, field: str, expected_type: type) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(expected_type, type) and isinstance(row.get(field), expected_type)
    return _base("PROVEN" if valid else "REJECTED", verdict="MATERIALIZATION_FIELD_TYPE_VALID" if valid else "MATERIALIZATION_FIELD_TYPE_INVALID", field=field, fail_closed=not valid)


def materialization_finite_receipt(value: Any) -> dict[str, Any]:
    valid = _fini(value)
    return _base("PROVEN" if valid else "REJECTED", verdict="MATERIALIZATION_VALUE_FINITE" if valid else "MATERIALIZATION_VALUE_NON_FINITE", value=float(value) if valid else None, fail_closed=not valid)


def materialization_cutoff_receipt(*, event_ts_ms: Any, cutoff_ts_ms: Any) -> dict[str, Any]:
    valid = _entier(event_ts_ms) and _entier(cutoff_ts_ms) and event_ts_ms <= cutoff_ts_ms
    return _base("PROVEN" if valid else "REJECTED", verdict="MATERIALIZATION_EVENT_WITHIN_CUTOFF" if valid else "MATERIALIZATION_EVENT_AFTER_CUTOFF", fail_closed=not valid)


def materialization_age_receipt(*, event_ts_ms: Any, oldest_allowed_ts_ms: Any) -> dict[str, Any]:
    valid = _entier(event_ts_ms) and _entier(oldest_allowed_ts_ms) and event_ts_ms >= oldest_allowed_ts_ms
    return _base("PROVEN" if valid else "REJECTED", verdict="MATERIALIZATION_EVENT_AGE_VALID" if valid else "MATERIALIZATION_EVENT_TOO_OLD", fail_closed=not valid)


def materialization_duplicate_receipt(*, event_ids: Sequence[Any]) -> dict[str, Any]:
    valid = bool(event_ids) and all(str(value).strip() for value in event_ids) and len(event_ids) == len(set(event_ids))
    return _base("PROVEN" if valid else "REJECTED", verdict="MATERIALIZATION_EVENTS_UNIQUE" if valid else "MATERIALIZATION_EVENT_DUPLICATE_OR_EMPTY", fail_closed=not valid)


def materialization_retry_receipt(*, attempts: Any, max_attempts: Any, checkpoint_saved: bool) -> dict[str, Any]:
    valid = _entier(attempts) and _entier(max_attempts) and 1 <= attempts <= max_attempts and checkpoint_saved is True
    return _base("PROVEN" if valid else "REJECTED", verdict="MATERIALIZATION_RETRY_BOUNDED" if valid else "MATERIALIZATION_RETRY_UNSAFE", fail_closed=not valid)


def materialization_replay_receipt(*, outputs: Sequence[Any]) -> dict[str, Any]:
    valid = bool(outputs) and len({repr(value) for value in outputs}) == 1
    return _base("PROVEN" if valid else "REJECTED", verdict="MATERIALIZATION_REPLAY_DETERMINISTIC" if valid else "MATERIALIZATION_REPLAY_DIVERGED", fail_closed=not valid)


def materialization_sha256_receipt(*, actual_sha256: Any, expected_sha256: Any) -> dict[str, Any]:
    actual = str(actual_sha256 or ""); expected = str(expected_sha256 or "")
    valid = len(actual) == 64 and len(expected) == 64 and all(char in "0123456789abcdefABCDEF" for char in actual + expected) and actual.casefold() == expected.casefold()
    return _base("PROVEN" if valid else "REJECTED", verdict="MATERIALIZATION_SHA256_MATCH" if valid else "MATERIALIZATION_SHA256_MISMATCH", fail_closed=not valid)


def materialization_size_receipt(*, actual_size: Any, expected_size: Any) -> dict[str, Any]:
    valid = _entier(actual_size) and _entier(expected_size) and actual_size >= 0 and actual_size == expected_size
    return _base("PROVEN" if valid else "REJECTED", verdict="MATERIALIZATION_SIZE_MATCH" if valid else "MATERIALIZATION_SIZE_MISMATCH", fail_closed=not valid)


def materialization_compression_receipt(*, expected_size: Any, observed_size: Any, complete: bool) -> dict[str, Any]:
    valid = _entier(expected_size) and _entier(observed_size) and expected_size >= 0 and observed_size == expected_size and complete is True
    return _base("PROVEN" if valid else "REJECTED", verdict="MATERIALIZATION_COMPRESSION_COMPLETE" if valid else "MATERIALIZATION_COMPRESSION_TRUNCATED", fail_closed=not valid)


def materialization_zip_slip_receipt(member: Any) -> dict[str, Any]:
    text = str(member or "").replace("\\", "/")
    unsafe = text.startswith("/") or ":" in text.split("/")[0] or ".." in text.split("/")
    return _base("PROVEN" if unsafe else "REJECTED", verdict="MATERIALIZATION_ZIP_SLIP_REFUSED" if unsafe else "MATERIALIZATION_ZIP_SLIP_NOT_REFUSED", fail_closed=not unsafe)


def materialization_symlink_receipt(*, is_symlink: bool, within_root: bool) -> dict[str, Any]:
    valid = is_symlink is False and within_root is True
    return _base("PROVEN" if valid else "REJECTED", verdict="MATERIALIZATION_SYMLINK_SAFE" if valid else "MATERIALIZATION_SYMLINK_REFUSED", fail_closed=not valid)


def materialization_partial_replay_receipt(*, status: Any, replayable: bool) -> dict[str, Any]:
    valid = str(status or "").upper() != "PARTIAL" or replayable is False
    return _base("PROVEN" if valid else "REJECTED", verdict="MATERIALIZATION_PARTIAL_NOT_REPLAYABLE" if valid else "MATERIALIZATION_PARTIAL_PROMOTED", fail_closed=not valid)


def materialization_reject_validation_receipt(*, status: Any, validated: bool) -> dict[str, Any]:
    valid = str(status or "").upper() != "REJECT" or validated is False
    return _base("PROVEN" if valid else "REJECTED", verdict="MATERIALIZATION_REJECT_NOT_VALIDATED" if valid else "MATERIALIZATION_REJECT_PROMOTED", fail_closed=not valid)


def materialization_unique_counts_receipt(*, total_count: Any, unique_count: Any, unique_ids: list[Any]) -> dict[str, Any]:
    valid = _entier(total_count) and _entier(unique_count) and total_count > 0 and total_count == unique_count == len(unique_ids) and len(set(unique_ids)) == unique_count
    return _base("PROVEN" if valid else "REJECTED", verdict="MATERIALIZATION_UNIQUE_COUNTS_MATCH" if valid else "MATERIALIZATION_UNIQUE_COUNTS_FALSE", fail_closed=not valid)


def materialization_manifest_compatibility_receipt(*, manifest_version: Any, required_version: Any, compatible: bool) -> dict[str, Any]:
    valid = bool(str(manifest_version or "").strip()) and bool(str(required_version or "").strip()) and compatible is True
    return _base("PROVEN" if valid else "REJECTED", verdict="MATERIALIZATION_MANIFEST_COMPATIBLE" if valid else "MATERIALIZATION_MANIFEST_INCOMPATIBLE", fail_closed=not valid)


def materialization_publication_receipt(*, status: Any, manifest_committed: bool, receipt_written: bool) -> dict[str, Any]:
    valid = str(status or "").upper() in {"COMPLETE", "PUBLISHED"} and manifest_committed is True and receipt_written is True
    return _base("PROVEN" if valid else "REJECTED", verdict="MATERIALIZATION_PUBLICATION_COMPLETE" if valid else "MATERIALIZATION_PUBLICATION_INTERRUPTED", fail_closed=not valid)


__all__ = [
    "materialize_records_streaming", "materialization_safety_receipt", "streaming_codec_receipt",
    "materialization_required_field_receipt", "materialization_null_field_receipt",
    "materialization_field_type_receipt", "materialization_finite_receipt", "materialization_cutoff_receipt",
    "materialization_age_receipt", "materialization_duplicate_receipt", "materialization_retry_receipt",
    "materialization_replay_receipt", "materialization_sha256_receipt", "materialization_size_receipt",
    "materialization_compression_receipt", "materialization_zip_slip_receipt", "materialization_symlink_receipt",
    "materialization_partial_replay_receipt", "materialization_reject_validation_receipt",
    "materialization_unique_counts_receipt", "materialization_manifest_compatibility_receipt",
    "materialization_publication_receipt",
]
