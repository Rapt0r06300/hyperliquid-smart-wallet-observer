"""Read-only consumer for Alina SmartFlow dataset V2 GitHub Releases."""
from __future__ import annotations

import hashlib
import gzip
import json
import math
import shutil
import zipfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from hl_observer.datasets.github_api_transport import (
    GitHubTransportError,
    download_release_asset,
    get_json,
)
from hl_observer.datasets.github_release_bridge import (
    DatasetBridgeError,
    ReleaseAsset,
    verify_asset,
)
from hl_observer.datasets.v2_pipeline import V2_REPOSITORY

RUN_MANIFEST_NAME = "RUN_MANIFEST.json"
RUN_SCHEMA = "alina.dataset_run_manifest.v2"
TAG_PREFIX = "data-v2-run-"


def list_run_releases(
    *,
    repository: str = V2_REPOSITORY,
    max_pages: int = 20,
    per_page: int = 100,
) -> list[dict[str, Any]]:
    releases: list[dict[str, Any]] = []
    for page in range(1, max(1, int(max_pages)) + 1):
        raw = get_json(
            f"repos/{repository}/releases?per_page={int(per_page)}&page={page}"
        )
        if not isinstance(raw, list):
            raise DatasetBridgeError("Dataset V2 release listing is invalid.")
        for row in raw:
            if not isinstance(row, Mapping):
                continue
            tag = str(row.get("tag_name") or "")
            if (
                tag.startswith(TAG_PREFIX)
                and row.get("draft") is not True
                and int(row.get("id") or 0) > 0
            ):
                releases.append(dict(row))
        if len(raw) < int(per_page):
            break
    return sorted(
        releases,
        key=lambda row: str(row.get("published_at") or row.get("created_at") or ""),
        reverse=True,
    )


def _asset_from_release(
    release: Mapping[str, Any],
    name: str,
) -> ReleaseAsset | None:
    assets = release.get("assets")
    if not isinstance(assets, list):
        return None
    for raw in assets:
        if not isinstance(raw, Mapping) or str(raw.get("name") or "") != name:
            continue
        return ReleaseAsset(
            asset_id=int(raw.get("id") or 0),
            name=name,
            size=int(raw.get("size") or 0),
            digest=str(raw.get("digest") or ""),
        )
    return None


def load_run_manifest(
    cache_root: str | Path,
    release: Mapping[str, Any],
    *,
    repository: str = V2_REPOSITORY,
    force: bool = False,
) -> dict[str, Any]:
    release_id = int(release.get("id") or 0)
    tag = str(release.get("tag_name") or "")
    if release_id <= 0 or not tag.startswith(TAG_PREFIX):
        raise DatasetBridgeError("Invalid V2 dataset release.")
    asset = _asset_from_release(release, RUN_MANIFEST_NAME)
    if asset is None:
        raise DatasetBridgeError(f"{tag} has no {RUN_MANIFEST_NAME}.")

    directory = Path(cache_root) / "run_manifests" / str(release_id)
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / RUN_MANIFEST_NAME
    if destination.is_file() and not force:
        try:
            verify_asset(destination, asset)
        except DatasetBridgeError:
            destination.unlink(missing_ok=True)
    if not destination.is_file():
        temporary = destination.with_suffix(".json.part")
        temporary.unlink(missing_ok=True)
        try:
            download_release_asset(
                repository=repository,
                asset_id=asset.asset_id,
                destination=temporary,
            )
        except GitHubTransportError as exc:
            temporary.unlink(missing_ok=True)
            raise DatasetBridgeError(str(exc)) from exc
        temporary.replace(destination)
        verify_asset(destination, asset)

    payload = json.loads(destination.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != RUN_SCHEMA:
        raise DatasetBridgeError(f"Invalid V2 run manifest in {tag}.")
    if str(payload.get("repository") or "") != repository:
        raise DatasetBridgeError("V2 run manifest points at another repository.")
    if int(payload.get("release_id") or 0) != release_id:
        raise DatasetBridgeError("V2 run manifest release id mismatch.")
    return payload


def iter_safe_manifests(
    run_manifests: Iterable[Mapping[str, Any]],
    *,
    venues: Iterable[str] = (),
    families: Iterable[str] = (),
    symbols: Iterable[str] = (),
    start_ts_ms: int | None = None,
    end_ts_ms: int | None = None,
) -> Iterable[dict[str, Any]]:
    venue_filter = {str(v).lower() for v in venues if str(v).strip()}
    family_filter = {str(v) for v in families if str(v).strip()}
    symbol_filter = {str(v).upper() for v in symbols if str(v).strip()}
    for run in run_manifests:
        rows = run.get("manifests")
        if not isinstance(rows, list):
            continue
        for raw in rows:
            if not isinstance(raw, Mapping):
                continue
            if raw.get("quality_status") != "SAFE":
                continue
            if raw.get("replay_compatible") is not True:
                continue
            if raw.get("validation_allowed") is not True:
                continue
            if raw.get("asset_verified") is not True:
                continue
            venue = str(raw.get("venue") or "").lower()
            family = str(raw.get("family") or "")
            symbol = str(raw.get("symbol") or "").upper()
            if venue_filter and venue not in venue_filter:
                continue
            if family_filter and family not in family_filter:
                continue
            if symbol_filter and symbol not in symbol_filter:
                continue
            start = _int(raw.get("start_ts_ms"))
            end = _int(raw.get("end_ts_ms"))
            if start is None or end is None:
                continue
            if start_ts_ms is not None and end < int(start_ts_ms):
                continue
            if end_ts_ms is not None and start > int(end_ts_ms):
                continue
            yield dict(raw)


def discover_safe_manifests(
    cache_root: str | Path,
    *,
    repository: str = V2_REPOSITORY,
    venues: Iterable[str] = (),
    families: Iterable[str] = (),
    symbols: Iterable[str] = (),
    start_ts_ms: int | None = None,
    end_ts_ms: int | None = None,
    max_releases: int = 500,
) -> list[dict[str, Any]]:
    releases = list_run_releases(repository=repository)
    runs: list[dict[str, Any]] = []
    for release in releases[: max(1, int(max_releases))]:
        try:
            runs.append(
                load_run_manifest(
                    cache_root,
                    release,
                    repository=repository,
                )
            )
        except DatasetBridgeError:
            # A malformed/incomplete release is ignored, never promoted implicitly.
            continue
    rows = list(
        iter_safe_manifests(
            runs,
            venues=venues,
            families=families,
            symbols=symbols,
            start_ts_ms=start_ts_ms,
            end_ts_ms=end_ts_ms,
        )
    )
    return sorted(
        rows,
        key=lambda row: (
            int(row.get("start_ts_ms") or 0),
            str(row.get("venue") or ""),
            str(row.get("family") or ""),
            str(row.get("symbol") or ""),
        ),
    )


def materialize_safe_shards(
    manifests: Iterable[Mapping[str, Any]],
    cache_root: str | Path,
    *,
    repository: str = V2_REPOSITORY,
    force: bool = False,
) -> dict[str, Path]:
    """Download only selected SAFE assets and verify manifest SHA + GitHub digest."""
    result: dict[str, Path] = {}
    root = Path(cache_root) / "shards"
    root.mkdir(parents=True, exist_ok=True)
    for manifest in manifests:
        if (
            manifest.get("quality_status") != "SAFE"
            or manifest.get("replay_compatible") is not True
            or manifest.get("validation_allowed") is not True
            or manifest.get("asset_verified") is not True
        ):
            raise DatasetBridgeError("Replay requested a non-SAFE V2 shard.")
        release = manifest.get("release")
        if not isinstance(release, Mapping):
            raise DatasetBridgeError("SAFE V2 shard has no release evidence.")
        if str(release.get("repository") or "") != repository:
            raise DatasetBridgeError("SAFE V2 shard points at another repository.")
        asset = ReleaseAsset(
            asset_id=int(release.get("asset_id") or 0),
            name=str(release.get("asset_name") or ""),
            size=int(release.get("remote_size") or 0),
            digest=str(release.get("remote_digest") or ""),
        )
        expected_sha = str(manifest.get("sha256") or "").lower()
        member_name = str(release.get("member_name") or "")
        if not member_name and (not asset.sha256 or asset.sha256.lower() != expected_sha):
            raise DatasetBridgeError("Manifest SHA and GitHub asset digest disagree.")
        destination = root / f"{manifest.get('dataset_id')}.jsonl.gz"
        expected_size = _int(manifest.get("bytes"))
        if destination.is_file() and not force:
            try:
                if destination.stat().st_size != expected_size or _sha256(destination) != expected_sha:
                    raise DatasetBridgeError("Cached shard identity mismatch.")
            except (DatasetBridgeError, OSError):
                destination.unlink(missing_ok=True)
        if not destination.is_file():
            temporary = destination.with_suffix(".gz.part")
            temporary.unlink(missing_ok=True)
            if member_name:
                containers = root / "_containers"
                containers.mkdir(parents=True, exist_ok=True)
                container = containers / f"{asset.asset_id}-{Path(asset.name).name}"
                if not container.is_file() or force:
                    part = container.with_suffix(container.suffix + ".part")
                    part.unlink(missing_ok=True)
                    try:
                        download_release_asset(
                            repository=repository,
                            asset_id=asset.asset_id,
                            destination=part,
                        )
                    except GitHubTransportError as exc:
                        part.unlink(missing_ok=True)
                        raise DatasetBridgeError(str(exc)) from exc
                    part.replace(container)
                verify_asset(container, asset)
                if Path(member_name).name != member_name:
                    raise DatasetBridgeError("Unsafe compacted shard member name.")
                try:
                    with (
                        zipfile.ZipFile(container) as archive,
                        archive.open(member_name) as source,
                        temporary.open("wb") as target,
                    ):
                        shutil.copyfileobj(source, target)
                except (KeyError, OSError, zipfile.BadZipFile) as exc:
                    temporary.unlink(missing_ok=True)
                    raise DatasetBridgeError("Compacted shard is missing or corrupt.") from exc
            else:
                try:
                    download_release_asset(
                        repository=repository,
                        asset_id=asset.asset_id,
                        destination=temporary,
                    )
                except GitHubTransportError as exc:
                    temporary.unlink(missing_ok=True)
                    raise DatasetBridgeError(str(exc)) from exc
            if temporary.stat().st_size != expected_size or _sha256(temporary) != expected_sha:
                temporary.unlink(missing_ok=True)
                raise DatasetBridgeError("Materialized shard identity mismatch.")
            temporary.replace(destination)
        result[str(manifest.get("dataset_id"))] = destination
    return result


def recount_shard_lines_receipt(path: str | Path, *, expected_event_count: object) -> dict[str, object]:
    """Recount non-empty gzip JSONL rows after indexing and compare exactly."""
    if isinstance(expected_event_count, bool) or not isinstance(expected_event_count, int) or expected_event_count < 0:
        return {"status": "UNMEASURABLE", "reason": "EXPECTED_COUNT_INVALID"}
    try:
        with gzip.open(Path(path), "rt", encoding="utf-8") as handle:
            actual = sum(1 for line in handle if line.strip())
    except (OSError, EOFError, gzip.BadGzipFile) as exc:
        return {"status": "REJECTED", "reason": f"SHARD_READ_FAILED:{exc}"}
    return {"status": "PROVEN" if actual == expected_event_count else "REJECTED", "actual_event_count": actual, "expected_event_count": expected_event_count, "exact": actual == expected_event_count}


def _reader_base(status: str, **values: Any) -> dict[str, Any]:
    return {
        "status": status,
        "paper_read_only": True,
        "real_execution": False,
        "promotion": "DISABLED_UNTIL_REVIEW",
        **values,
    }


def _reader_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _reader_finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def reader_safety_receipt(manifest: Mapping[str, Any]) -> dict[str, Any]:
    release = manifest.get("release") if isinstance(manifest, Mapping) else None
    valid = (
        isinstance(manifest, Mapping)
        and manifest.get("quality_status") == "SAFE"
        and manifest.get("replay_compatible") is True
        and manifest.get("validation_allowed") is True
        and manifest.get("asset_verified") is True
        and isinstance(release, Mapping)
        and str(release.get("repository") or "") == V2_REPOSITORY
        and int(release.get("asset_id") or 0) > 0
        and bool(str(release.get("asset_name") or "").strip())
    )
    return _reader_base("PROVEN" if valid else "REJECTED", verdict="READER_SAFE_MANIFEST" if valid else "READER_UNSAFE_MANIFEST", fail_closed=not valid)


def reader_required_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) not in (None, "")
    return _reader_base("PROVEN" if valid else "REJECTED", verdict="READER_FIELD_PRESENT" if valid else "READER_FIELD_MISSING", field=field, fail_closed=not valid)


def reader_null_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) is not None
    return _reader_base("PROVEN" if valid else "REJECTED", verdict="READER_FIELD_NON_NULL" if valid else "READER_FIELD_NULL", field=field, fail_closed=not valid)


def reader_field_type_receipt(row: Mapping[str, Any], *, field: str, expected_type: type) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(expected_type, type) and isinstance(row.get(field), expected_type)
    return _reader_base("PROVEN" if valid else "REJECTED", verdict="READER_FIELD_TYPE_VALID" if valid else "READER_FIELD_TYPE_INVALID", field=field, fail_closed=not valid)


def reader_finite_receipt(value: Any) -> dict[str, Any]:
    valid = _reader_finite(value)
    return _reader_base("PROVEN" if valid else "REJECTED", verdict="READER_VALUE_FINITE" if valid else "READER_VALUE_NON_FINITE", value=float(value) if valid else None, fail_closed=not valid)


def reader_cutoff_receipt(*, event_ts_ms: Any, cutoff_ts_ms: Any) -> dict[str, Any]:
    valid = _reader_integer(event_ts_ms) and _reader_integer(cutoff_ts_ms) and event_ts_ms <= cutoff_ts_ms
    return _reader_base("PROVEN" if valid else "REJECTED", verdict="READER_EVENT_WITHIN_CUTOFF" if valid else "READER_EVENT_AFTER_CUTOFF", fail_closed=not valid)


def reader_age_receipt(*, event_ts_ms: Any, oldest_allowed_ts_ms: Any) -> dict[str, Any]:
    valid = _reader_integer(event_ts_ms) and _reader_integer(oldest_allowed_ts_ms) and event_ts_ms >= oldest_allowed_ts_ms
    return _reader_base("PROVEN" if valid else "REJECTED", verdict="READER_EVENT_AGE_VALID" if valid else "READER_EVENT_TOO_OLD", fail_closed=not valid)


def reader_duplicate_receipt(*, event_ids: list[Any]) -> dict[str, Any]:
    valid = bool(event_ids) and all(str(value).strip() for value in event_ids) and len(event_ids) == len(set(event_ids))
    return _reader_base("PROVEN" if valid else "REJECTED", verdict="READER_EVENTS_UNIQUE" if valid else "READER_EVENT_DUPLICATE_OR_EMPTY", fail_closed=not valid)


def reader_retry_receipt(*, attempts: Any, max_attempts: Any, checkpoint_saved: bool) -> dict[str, Any]:
    valid = _reader_integer(attempts) and _reader_integer(max_attempts) and 1 <= attempts <= max_attempts and checkpoint_saved is True
    return _reader_base("PROVEN" if valid else "REJECTED", verdict="READER_RETRY_BOUNDED" if valid else "READER_RETRY_UNSAFE", fail_closed=not valid)


def reader_replay_receipt(*, outputs: list[Any]) -> dict[str, Any]:
    valid = bool(outputs) and len({repr(value) for value in outputs}) == 1
    return _reader_base("PROVEN" if valid else "REJECTED", verdict="READER_REPLAY_DETERMINISTIC" if valid else "READER_REPLAY_DIVERGED", fail_closed=not valid)


def reader_http_error_receipt(*, status_code: Any, retry_after_seconds: Any = None) -> dict[str, Any]:
    valid_status = _reader_integer(status_code) and status_code in {404, 408, 429, 500, 502, 503, 504}
    retryable = status_code in {408, 429, 500, 502, 503, 504} and _reader_finite(retry_after_seconds) and float(retry_after_seconds) > 0
    valid = status_code == 404 or retryable
    return _reader_base("PROVEN" if valid and valid_status else "REJECTED", verdict="READER_REMOTE_ERROR_QUARANTINED" if valid and valid_status else "READER_REMOTE_ERROR_UNSAFE", status_code=status_code, retryable=retryable, fail_closed=not (valid and valid_status))


def reader_range_receipt(*, requested_start: Any, observed_start: Any, range_honored: bool) -> dict[str, Any]:
    valid = _reader_integer(requested_start) and _reader_integer(observed_start) and requested_start == observed_start and range_honored is True
    return _reader_base("PROVEN" if valid else "REJECTED", verdict="READER_RANGE_HONORED" if valid else "READER_RANGE_IGNORED", fail_closed=not valid)


def reader_content_range_receipt(*, expected_start: Any, observed_start: Any, expected_end: Any, observed_end: Any) -> dict[str, Any]:
    valid = all(_reader_integer(value) for value in (expected_start, observed_start, expected_end, observed_end)) and expected_start == observed_start and expected_end == observed_end and observed_end >= observed_start
    return _reader_base("PROVEN" if valid else "REJECTED", verdict="READER_CONTENT_RANGE_MATCH" if valid else "READER_CONTENT_RANGE_MISMATCH", fail_closed=not valid)


def reader_etag_receipt(*, previous_etag: Any, current_etag: Any) -> dict[str, Any]:
    previous = str(previous_etag or "").strip(); current = str(current_etag or "").strip()
    changed = bool(previous and current and previous != current)
    return _reader_base("PROVEN" if changed else "REJECTED", verdict="READER_ETAG_CHANGE_INVALIDATES_CACHE" if changed else "READER_ETAG_CHANGE_UNPROVEN", cache_invalidated=changed, fail_closed=not changed)


def reader_disk_space_receipt(*, required_bytes: Any, available_bytes: Any) -> dict[str, Any]:
    valid = _reader_integer(required_bytes) and _reader_integer(available_bytes) and required_bytes >= 0 and available_bytes >= 0 and available_bytes >= required_bytes
    return _reader_base("PROVEN" if valid else "REJECTED", verdict="READER_DISK_SPACE_SUFFICIENT" if valid else "READER_DISK_SPACE_INSUFFICIENT", fail_closed=not valid)


def reader_zip_slip_receipt(member: Any) -> dict[str, Any]:
    text = str(member or "").replace("\\", "/")
    unsafe = text.startswith("/") or ":" in text.split("/")[0] or ".." in text.split("/")
    return _reader_base("PROVEN" if unsafe else "REJECTED", verdict="READER_ZIP_SLIP_REFUSED" if unsafe else "READER_ZIP_SLIP_NOT_REFUSED", fail_closed=not unsafe)


def reader_expansion_receipt(*, observed_bytes: Any, max_bytes: Any, complete: bool) -> dict[str, Any]:
    valid = _reader_integer(observed_bytes) and _reader_integer(max_bytes) and observed_bytes >= 0 and max_bytes >= 0 and observed_bytes <= max_bytes and complete is True
    return _reader_base("PROVEN" if valid else "REJECTED", verdict="READER_EXPANSION_BOUNDED" if valid else "READER_EXPANSION_UNSAFE", fail_closed=not valid)


def reader_lease_receipt(*, active_leases: Any, lease_token_present: bool) -> dict[str, Any]:
    valid = _reader_integer(active_leases) and active_leases == 1 and lease_token_present is True
    return _reader_base("PROVEN" if valid else "REJECTED", verdict="READER_SINGLE_LEASE" if valid else "READER_SPLIT_BRAIN_RISK", fail_closed=not valid)


def reader_preflight_receipt(manifest: Mapping[str, Any]) -> dict[str, Any]:
    return reader_safety_receipt(manifest)


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None and not isinstance(value, bool) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


__all__ = [
    "RUN_MANIFEST_NAME",
    "RUN_SCHEMA",
    "TAG_PREFIX",
    "discover_safe_manifests",
    "iter_safe_manifests",
    "list_run_releases",
    "load_run_manifest",
    "materialize_safe_shards",
    "recount_shard_lines_receipt",
    "reader_safety_receipt",
    "reader_required_field_receipt",
    "reader_null_field_receipt",
    "reader_field_type_receipt",
    "reader_finite_receipt",
    "reader_cutoff_receipt",
    "reader_age_receipt",
    "reader_duplicate_receipt",
    "reader_retry_receipt",
    "reader_replay_receipt",
    "reader_http_error_receipt",
    "reader_range_receipt",
    "reader_content_range_receipt",
    "reader_etag_receipt",
    "reader_disk_space_receipt",
    "reader_zip_slip_receipt",
    "reader_expansion_receipt",
    "reader_lease_receipt",
    "reader_preflight_receipt",
]
