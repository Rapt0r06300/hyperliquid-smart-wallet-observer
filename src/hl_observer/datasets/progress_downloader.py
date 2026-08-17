from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Iterable, Mapping

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
    """Measure logical, verified-cache, partial and actual remaining network bytes."""

    ordered_names = tuple(dict.fromkeys(str(name) for name in names))
    missing = [name for name in ordered_names if name not in assets]
    if missing:
        raise DatasetBridgeError("Assets absents de la Release: " + ", ".join(missing[:20]))
    cache_dir = root / "data" / "hypersmart_datasets" / "assets"
    logical_bytes = verified_bytes = partial_bytes = remaining_bytes = 0
    verified_names: list[str] = []
    partial_names: list[str] = []
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
                pass
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
    }


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
        f"réseau_restant={human_bytes(int(plan['remaining_network_bytes']))}",
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
    "download_needed_assets_with_progress",
    "human_bytes",
    "human_eta",
]
