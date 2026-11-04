from __future__ import annotations

import threading
import time
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from hl_observer.datasets.github_api_transport import (
    GitHubTransportError,
    download_release_asset,
)
from hl_observer.datasets.github_release_bridge import (
    DEFAULT_REPOSITORY,
    DatasetBridgeError,
    ReleaseAsset,
    verify_asset,
)


def human_bytes(value: int | float) -> str:
    amount = float(max(0.0, value))
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    unit = units[0]
    for candidate in units:
        unit = candidate
        if amount < 1024.0 or candidate == units[-1]:
            break
        amount /= 1024.0
    return f"{amount:.2f} {unit}"


def human_eta(seconds: float | None) -> str:
    if seconds is None or seconds < 0 or seconds == float("inf"):
        return "--:--:--"
    total = int(round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def cache_transfer_plan(
    root: Path,
    assets: Mapping[str, ReleaseAsset],
    names: Iterable[str],
    *,
    force: bool = False,
) -> dict[str, object]:
    """Measure logical, verified-cache, partial and actual remaining network bytes.

    Un asset final déjà présent mais invalide n'est jamais assimilé à du cache.
    Il est exposé explicitement dans ``invalid_cached_names`` afin que le cockpit,
    les tests et les décisions MAX DATA puissent distinguer un vrai cache vérifié
    d'un fichier à retélécharger. La fonction de planification reste non destructive.
    """

    ordered_names = tuple(dict.fromkeys(str(name) for name in names))
    missing = [name for name in ordered_names if name not in assets]
    if missing:
        raise DatasetBridgeError("Assets absents de la Release: " + ", ".join(missing[:20]))
    cache_dir = root / "data" / "hypersmart_datasets" / "assets"
    logical_bytes = verified_bytes = partial_bytes = remaining_bytes = 0
    verified_names: list[str] = []
    partial_names: list[str] = []
    invalid_cached_names: list[str] = []
    for name in ordered_names:
        asset = assets[name]
        logical_bytes += int(asset.size)
        destination = cache_dir / asset.name
        partial = destination.with_suffix(destination.suffix + ".part")
        if destination.is_file() and not force:
            try:
                verify_asset(destination, asset)
                verified_bytes += int(asset.size)
                verified_names.append(name)
                continue
            except DatasetBridgeError:
                invalid_cached_names.append(name)
        if force:
            remaining_bytes += int(asset.size)
            continue
        part_size = 0
        if partial.is_file():
            try:
                part_size = max(0, min(int(partial.stat().st_size), int(asset.size)))
            except OSError:
                part_size = 0
        if part_size:
            partial_bytes += part_size
            partial_names.append(name)
        remaining_bytes += max(0, int(asset.size) - part_size)
    return {
        "asset_count": len(ordered_names),
        "logical_asset_bytes": logical_bytes,
        "verified_cache_bytes": verified_bytes,
        "partial_cache_bytes": partial_bytes,
        "remaining_network_bytes": remaining_bytes,
        "verified_cache_names": verified_names,
        "partial_cache_names": partial_names,
        "invalid_cached_names": invalid_cached_names,
    }


def resume_transfer_receipt(
    root: Path,
    assets: Mapping[str, ReleaseAsset],
    names: Iterable[str],
) -> dict[str, object]:
    """Describe resumable partial assets without downloading or deleting anything."""
    try:
        plan = cache_transfer_plan(root, assets, names)
    except DatasetBridgeError as exc:
        return {"status": "UNMEASURABLE", "reason": str(exc)}
    return {
        "status": "PROVEN",
        "partial_names": list(plan["partial_cache_names"]),
        "remaining_network_bytes": int(plan["remaining_network_bytes"]),
        "verified_cache_bytes": int(plan["verified_cache_bytes"]),
        "non_destructive": True,
    }


def _downloader_base(status: str, **values: Any) -> dict[str, Any]:
    return {
        "status": status,
        "paper_read_only": True,
        "real_execution": False,
        "promotion": "DISABLED_UNTIL_REVIEW",
        **values,
    }


def _downloader_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _downloader_finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def downloader_preflight_receipt(plan: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a non-destructive cache plan before any transfer is attempted."""
    required = {
        "asset_count", "logical_asset_bytes", "verified_cache_bytes",
        "partial_cache_bytes", "remaining_network_bytes",
        "verified_cache_names", "partial_cache_names", "invalid_cached_names",
    }
    valid = isinstance(plan, Mapping) and required.issubset(plan)
    if valid:
        numeric = ("asset_count", "logical_asset_bytes", "verified_cache_bytes", "partial_cache_bytes", "remaining_network_bytes")
        valid = all(_downloader_integer(plan.get(key)) and int(plan[key]) >= 0 for key in numeric)
        valid = valid and not (set(plan.get("verified_cache_names") or ()) & set(plan.get("partial_cache_names") or ()))
        valid = valid and not (set(plan.get("verified_cache_names") or ()) & set(plan.get("invalid_cached_names") or ()))
    return _downloader_base("PROVEN" if valid else "REJECTED", verdict="DOWNLOADER_PREFLIGHT_SAFE" if valid else "DOWNLOADER_PREFLIGHT_INVALID", fail_closed=not valid)


def downloader_required_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) not in (None, "")
    return _downloader_base("PROVEN" if valid else "REJECTED", verdict="DOWNLOADER_FIELD_PRESENT" if valid else "DOWNLOADER_FIELD_MISSING", field=field, fail_closed=not valid)


def downloader_null_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) is not None
    return _downloader_base("PROVEN" if valid else "REJECTED", verdict="DOWNLOADER_FIELD_NON_NULL" if valid else "DOWNLOADER_FIELD_NULL", field=field, fail_closed=not valid)


def downloader_field_type_receipt(row: Mapping[str, Any], *, field: str, expected_type: type) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(expected_type, type) and isinstance(row.get(field), expected_type)
    return _downloader_base("PROVEN" if valid else "REJECTED", verdict="DOWNLOADER_FIELD_TYPE_VALID" if valid else "DOWNLOADER_FIELD_TYPE_INVALID", field=field, fail_closed=not valid)


def downloader_finite_receipt(value: Any) -> dict[str, Any]:
    valid = _downloader_finite(value)
    return _downloader_base("PROVEN" if valid else "REJECTED", verdict="DOWNLOADER_VALUE_FINITE" if valid else "DOWNLOADER_VALUE_NON_FINITE", value=float(value) if valid else None, fail_closed=not valid)


def downloader_cutoff_receipt(*, event_ts_ms: Any, cutoff_ts_ms: Any) -> dict[str, Any]:
    valid = _downloader_integer(event_ts_ms) and _downloader_integer(cutoff_ts_ms) and event_ts_ms <= cutoff_ts_ms
    return _downloader_base("PROVEN" if valid else "REJECTED", verdict="DOWNLOADER_EVENT_WITHIN_CUTOFF" if valid else "DOWNLOADER_EVENT_AFTER_CUTOFF", fail_closed=not valid)


def downloader_age_receipt(*, event_ts_ms: Any, oldest_allowed_ts_ms: Any) -> dict[str, Any]:
    valid = _downloader_integer(event_ts_ms) and _downloader_integer(oldest_allowed_ts_ms) and event_ts_ms >= oldest_allowed_ts_ms
    return _downloader_base("PROVEN" if valid else "REJECTED", verdict="DOWNLOADER_EVENT_AGE_VALID" if valid else "DOWNLOADER_EVENT_TOO_OLD", fail_closed=not valid)


def downloader_duplicate_receipt(*, event_ids: list[Any]) -> dict[str, Any]:
    valid = bool(event_ids) and all(str(value).strip() for value in event_ids) and len(event_ids) == len(set(event_ids))
    return _downloader_base("PROVEN" if valid else "REJECTED", verdict="DOWNLOADER_EVENTS_UNIQUE" if valid else "DOWNLOADER_EVENT_DUPLICATE_OR_EMPTY", fail_closed=not valid)


def downloader_retry_receipt(*, attempts: Any, max_attempts: Any, checkpoint_saved: bool) -> dict[str, Any]:
    valid = _downloader_integer(attempts) and _downloader_integer(max_attempts) and 1 <= attempts <= max_attempts and checkpoint_saved is True
    return _downloader_base("PROVEN" if valid else "REJECTED", verdict="DOWNLOADER_RETRY_BOUNDED" if valid else "DOWNLOADER_RETRY_UNSAFE", fail_closed=not valid)


def downloader_replay_receipt(*, outputs: list[Any]) -> dict[str, Any]:
    valid = bool(outputs) and len({repr(value) for value in outputs}) == 1
    return _downloader_base("PROVEN" if valid else "REJECTED", verdict="DOWNLOADER_REPLAY_DETERMINISTIC" if valid else "DOWNLOADER_REPLAY_DIVERGED", fail_closed=not valid)


def downloader_http_error_receipt(*, status_code: Any, retry_after_seconds: Any = None) -> dict[str, Any]:
    valid_status = _downloader_integer(status_code) and status_code in {404, 408, 429, 500, 502, 503, 504}
    retryable = status_code in {408, 429, 500, 502, 503, 504} and _downloader_finite(retry_after_seconds) and float(retry_after_seconds) > 0
    valid = status_code == 404 or retryable
    return _downloader_base("PROVEN" if valid and valid_status else "REJECTED", verdict="DOWNLOADER_REMOTE_ERROR_QUARANTINED" if valid and valid_status else "DOWNLOADER_REMOTE_ERROR_UNSAFE", status_code=status_code, retryable=retryable, fail_closed=not (valid and valid_status))


def downloader_range_receipt(*, requested_start: Any, observed_start: Any, range_honored: bool) -> dict[str, Any]:
    valid = _downloader_integer(requested_start) and _downloader_integer(observed_start) and requested_start == observed_start and range_honored is True
    return _downloader_base("PROVEN" if valid else "REJECTED", verdict="DOWNLOADER_RANGE_HONORED" if valid else "DOWNLOADER_RANGE_IGNORED", fail_closed=not valid)


def downloader_content_range_receipt(*, expected_start: Any, observed_start: Any, expected_end: Any, observed_end: Any) -> dict[str, Any]:
    valid = all(_downloader_integer(value) for value in (expected_start, observed_start, expected_end, observed_end)) and expected_start == observed_start and expected_end == observed_end and observed_end >= observed_start
    return _downloader_base("PROVEN" if valid else "REJECTED", verdict="DOWNLOADER_CONTENT_RANGE_MATCH" if valid else "DOWNLOADER_CONTENT_RANGE_MISMATCH", fail_closed=not valid)


def downloader_etag_receipt(*, previous_etag: Any, current_etag: Any) -> dict[str, Any]:
    previous = str(previous_etag or "").strip(); current = str(current_etag or "").strip()
    changed = bool(previous and current and previous != current)
    return _downloader_base("PROVEN" if changed else "REJECTED", verdict="DOWNLOADER_ETAG_CHANGE_INVALIDATES_CACHE" if changed else "DOWNLOADER_ETAG_CHANGE_UNPROVEN", cache_invalidated=changed, fail_closed=not changed)


def downloader_disk_space_receipt(*, required_bytes: Any, available_bytes: Any) -> dict[str, Any]:
    valid = _downloader_integer(required_bytes) and _downloader_integer(available_bytes) and required_bytes >= 0 and available_bytes >= 0 and available_bytes >= required_bytes
    return _downloader_base("PROVEN" if valid else "REJECTED", verdict="DOWNLOADER_DISK_SPACE_SUFFICIENT" if valid else "DOWNLOADER_DISK_SPACE_INSUFFICIENT", fail_closed=not valid)


def downloader_zip_slip_receipt(member: Any) -> dict[str, Any]:
    text = str(member or "").replace("\\", "/")
    unsafe = text.startswith("/") or ":" in text.split("/")[0] or ".." in text.split("/")
    return _downloader_base("PROVEN" if unsafe else "REJECTED", verdict="DOWNLOADER_ZIP_SLIP_REFUSED" if unsafe else "DOWNLOADER_ZIP_SLIP_NOT_REFUSED", fail_closed=not unsafe)


def downloader_expansion_receipt(*, observed_bytes: Any, max_bytes: Any, complete: bool) -> dict[str, Any]:
    valid = _downloader_integer(observed_bytes) and _downloader_integer(max_bytes) and observed_bytes >= 0 and max_bytes >= 0 and observed_bytes <= max_bytes and complete is True
    return _downloader_base("PROVEN" if valid else "REJECTED", verdict="DOWNLOADER_EXPANSION_BOUNDED" if valid else "DOWNLOADER_EXPANSION_UNSAFE", fail_closed=not valid)


def downloader_lease_receipt(*, active_leases: Any, lease_token_present: bool) -> dict[str, Any]:
    valid = _downloader_integer(active_leases) and active_leases == 1 and lease_token_present is True
    return _downloader_base("PROVEN" if valid else "REJECTED", verdict="DOWNLOADER_SINGLE_LEASE" if valid else "DOWNLOADER_SPLIT_BRAIN_RISK", fail_closed=not valid)


def downloader_done_receipt(*, checks: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Close downloader review only when every local gate is proven."""

    valid = bool(checks) and all(
        isinstance(check, Mapping)
        and check.get("status") == "PROVEN"
        and check.get("paper_read_only") is True
        and check.get("real_execution") is False
        and check.get("fail_closed") is False
        and bool(str(check.get("verdict") or "").strip())
        for check in checks
    )
    return _downloader_base(
        "PROVEN" if valid else "REJECTED",
        verdict="DOWNLOADER_DONE_COVERED" if valid else "DOWNLOADER_DONE_INCOMPLETE",
        check_count=len(checks) if isinstance(checks, Sequence) else 0,
        fail_closed=not valid,
    )


def _progress_heartbeat(
    *,
    temporary: Path,
    asset: ReleaseAsset,
    index: int,
    count: int,
    completed_before: int,
    total_bytes: int,
    stop: threading.Event,
    heartbeat_seconds: float,
) -> None:
    previous_time = time.monotonic()
    try:
        previous_bytes = temporary.stat().st_size
    except OSError:
        previous_bytes = 0
    smoothed_speed = 0.0
    interval = max(0.2, float(heartbeat_seconds))
    while not stop.wait(interval):
        try:
            current_bytes = temporary.stat().st_size
        except OSError:
            current_bytes = 0
        now = time.monotonic()
        delta_t = max(0.001, now - previous_time)
        instant_speed = max(0.0, current_bytes - previous_bytes) / delta_t
        if instant_speed > 0:
            smoothed_speed = instant_speed if smoothed_speed <= 0 else 0.70 * smoothed_speed + 0.30 * instant_speed
        remaining = max(0, asset.size - current_bytes)
        eta = remaining / smoothed_speed if smoothed_speed > 0 else None
        asset_pct = 100.0 * current_bytes / asset.size if asset.size else 100.0
        overall_done = min(total_bytes, completed_before + current_bytes)
        overall_pct = 100.0 * overall_done / total_bytes if total_bytes else 100.0
        print(
            f"[TELECHARGEMENT] {index}/{count} {asset.name} | "
            f"{human_bytes(current_bytes)}/{human_bytes(asset.size)} "
            f"({asset_pct:5.1f}%) | {human_bytes(smoothed_speed)}/s | "
            f"ETA={human_eta(eta)} | TOTAL={overall_pct:5.1f}%",
            flush=True,
        )
        previous_time = now
        previous_bytes = current_bytes


def _download_one_with_progress(
    asset: ReleaseAsset,
    destination: Path,
    *,
    repository: str,
    index: int,
    count: int,
    completed_before: int,
    total_bytes: int,
    force: bool,
    heartbeat_seconds: float = 1.0,
) -> Path:
    if destination.is_file() and not force:
        try:
            verify_asset(destination, asset)
            print(
                f"[CACHE OK] {index}/{count} {asset.name} | {human_bytes(asset.size)} déjà vérifiés",
                flush=True,
            )
            return destination
        except DatasetBridgeError:
            destination.unlink(missing_ok=True)

    if asset.asset_id <= 0:
        raise DatasetBridgeError(f"Identifiant GitHub invalide pour {asset.name}")

    temporary = destination.with_suffix(destination.suffix + ".part")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if force:
        temporary.unlink(missing_ok=True)
    try:
        resumed_from = temporary.stat().st_size
    except OSError:
        resumed_from = 0
    if resumed_from:
        print(
            f"[REPRISE] {index}/{count} {asset.name} | {human_bytes(resumed_from)} déjà présents dans .part",
            flush=True,
        )

    started = time.monotonic()
    stop = threading.Event()
    heartbeat = threading.Thread(
        target=_progress_heartbeat,
        kwargs={
            "temporary": temporary,
            "asset": asset,
            "index": index,
            "count": count,
            "completed_before": completed_before,
            "total_bytes": total_bytes,
            "stop": stop,
            "heartbeat_seconds": heartbeat_seconds,
        },
        name=f"alina-download-heartbeat-{index}",
        daemon=True,
    )
    heartbeat.start()
    try:
        download_release_asset(
            repository=repository,
            asset_id=asset.asset_id,
            destination=temporary,
        )
    except (GitHubTransportError, OSError) as exc:
        # Preserve partial bytes so the next execution resumes with HTTP Range.
        raise DatasetBridgeError(
            f"Téléchargement GitHub échoué pour {asset.name}; .part conservé pour reprise: {exc}"
        ) from exc
    finally:
        stop.set()
        heartbeat.join(timeout=max(2.0, float(heartbeat_seconds) + 1.0))

    try:
        verify_asset(temporary, asset)
    except DatasetBridgeError as exc:
        # A complete but hash-invalid partial cannot be resumed safely. Remove
        # only this corrupt transfer; the next cycle restarts this asset cleanly.
        temporary.unlink(missing_ok=True)
        raise DatasetBridgeError(
            f"SHA-256 invalide après téléchargement de {asset.name}; .part corrompu supprimé."
        ) from exc
    temporary.replace(destination)
    elapsed = max(0.001, time.monotonic() - started)
    transferred = max(0, int(asset.size) - int(resumed_from))
    overall_done = min(total_bytes, completed_before + asset.size)
    overall_pct = 100.0 * overall_done / total_bytes if total_bytes else 100.0
    print(
        f"[SHA256 OK] {index}/{count} {asset.name} | {human_bytes(asset.size)} | "
        f"transféré_ce_cycle={human_bytes(transferred)} | moyenne={human_bytes(transferred / elapsed)}/s | "
        f"TOTAL={overall_pct:5.1f}%",
        flush=True,
    )
    return destination


def download_needed_assets_with_progress(
    root: Path,
    assets: Mapping[str, ReleaseAsset],
    names: Iterable[str],
    *,
    repository: str = DEFAULT_REPOSITORY,
    force: bool = False,
    heartbeat_seconds: float = 1.0,
) -> dict[str, Path]:
    ordered_names = tuple(dict.fromkeys(str(name) for name in names))
    plan = cache_transfer_plan(root, assets, ordered_names, force=force)
    selected = [assets[name] for name in ordered_names]
    total_bytes = int(plan["logical_asset_bytes"])
    cache_dir = root / "data" / "hypersmart_datasets" / "assets"
    cache_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"[PLAN TELECHARGEMENT] {len(selected)} asset(s) | logique={human_bytes(total_bytes)} | "
        f"cache_vérifié={human_bytes(int(plan['verified_cache_bytes']))} | "
        f"partiel={human_bytes(int(plan['partial_cache_bytes']))} | "
        f"réseau_restant={human_bytes(int(plan['remaining_network_bytes']))} | "
        f"cache_invalide={len(plan['invalid_cached_names'])}",
        flush=True,
    )
    result: dict[str, Path] = {}
    completed_bytes = 0
    for index, asset in enumerate(selected, 1):
        destination = cache_dir / asset.name
        result[asset.name] = _download_one_with_progress(
            asset,
            destination,
            repository=repository,
            index=index,
            count=len(selected),
            completed_before=completed_bytes,
            total_bytes=total_bytes,
            force=force,
            heartbeat_seconds=heartbeat_seconds,
        )
        completed_bytes += asset.size
        pct = 100.0 * completed_bytes / total_bytes if total_bytes else 100.0
        print(
            f"[TOTAL] {index}/{len(selected)} asset(s) vérifiés | "
            f"{human_bytes(completed_bytes)}/{human_bytes(total_bytes)} ({pct:.1f}%)",
            flush=True,
        )
    return result


__all__ = [
    "cache_transfer_plan",
    "resume_transfer_receipt",
    "downloader_preflight_receipt",
    "downloader_required_field_receipt",
    "downloader_null_field_receipt",
    "downloader_field_type_receipt",
    "downloader_finite_receipt",
    "downloader_cutoff_receipt",
    "downloader_age_receipt",
    "downloader_duplicate_receipt",
    "downloader_retry_receipt",
    "downloader_replay_receipt",
    "downloader_http_error_receipt",
    "downloader_range_receipt",
    "downloader_content_range_receipt",
    "downloader_etag_receipt",
    "downloader_disk_space_receipt",
    "downloader_zip_slip_receipt",
    "downloader_expansion_receipt",
    "downloader_lease_receipt",
    "downloader_done_receipt",
    "download_needed_assets_with_progress",
    "human_bytes",
    "human_eta",
]
