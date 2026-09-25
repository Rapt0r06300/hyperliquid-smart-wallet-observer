"""Read-only consumer for Alina SmartFlow dataset V2 GitHub Releases."""
from __future__ import annotations

import json
import urllib.parse
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
        if not asset.sha256 or asset.sha256.lower() != expected_sha:
            raise DatasetBridgeError("Manifest SHA and GitHub asset digest disagree.")
        destination = root / f"{manifest.get('dataset_id')}.jsonl.gz"
        if destination.is_file() and not force:
            try:
                verify_asset(destination, asset)
            except DatasetBridgeError:
                destination.unlink(missing_ok=True)
        if not destination.is_file():
            temporary = destination.with_suffix(".gz.part")
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
        result[str(manifest.get("dataset_id"))] = destination
    return result


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None and not isinstance(value, bool) else None
    except (TypeError, ValueError, OverflowError):
        return None


__all__ = [
    "RUN_MANIFEST_NAME",
    "RUN_SCHEMA",
    "TAG_PREFIX",
    "discover_safe_manifests",
    "iter_safe_manifests",
    "list_run_releases",
    "load_run_manifest",
    "materialize_safe_shards",
]