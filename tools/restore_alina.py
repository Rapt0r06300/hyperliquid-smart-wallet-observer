#!/usr/bin/env python3
"""Restore the complete canonical Alina evidence set after a fresh git clone.

A plain git clone restores Git history and tracked files. Heavy immutable evidence
(trades, L2, replay inputs, recovery capsules and analysis assets) lives in GitHub
Releases of the same repository and is therefore restored separately by this tool.

The tool is read-only against GitHub. It uses only Python's standard library.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

try:
    from tools.partitioned_data_index import read_index
except ModuleNotFoundError:
    from partitioned_data_index import read_index

DEFAULT_REPOSITORY = "Rapt0r06300/hyperliquid-smart-wallet-observer"
USER_AGENT = "alina-smartflow-disaster-restore/1"
SAFE_COMPONENT = re.compile(r"[^A-Za-z0-9._-]+")


class RestoreError(RuntimeError):
    pass


def _safe_component(value: str) -> str:
    raw = str(value)
    cleaned = SAFE_COMPONENT.sub("_", raw).strip("._")
    if not cleaned:
        raise RestoreError(f"unsafe empty path component derived from {value!r}")
    if cleaned != raw or len(cleaned) > 200:
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
        cleaned = f"{cleaned[:200]}--{digest}"
    return cleaned[:220]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _request(url: str, *, token: str | None = None, retries: int = 8) -> bytes:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    for attempt in range(1, retries + 1):
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            transient = exc.code in {403, 429, 500, 502, 503, 504}
            if not transient or attempt >= retries:
                detail = exc.read().decode("utf-8", errors="replace")[:800]
                raise RestoreError(f"HTTP {exc.code} for {url}: {detail}") from exc
            reset = exc.headers.get("X-RateLimit-Reset")
            delay = min(120.0, float(2 ** min(attempt, 6)))
            if reset and reset.isdigit():
                delay = max(delay, min(120.0, int(reset) - time.time() + 2.0))
            time.sleep(max(1.0, delay))
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt >= retries:
                raise RestoreError(f"network failure for {url}: {exc}") from exc
            time.sleep(min(60.0, float(2 ** attempt)))
    raise RestoreError(f"unreachable retry state for {url}")


def _json(url: str, *, token: str | None = None) -> Any:
    try:
        return json.loads(_request(url, token=token).decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RestoreError(f"GitHub returned invalid JSON for {url}") from exc

def _download_to_path(
    url: str,
    target: Path,
    *,
    token: str | None = None,
    retries: int = 8,
) -> tuple[int, str]:
    """Stream one potentially multi-GB Release asset without loading it into RAM."""
    headers = {"Accept": "application/octet-stream", "User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-GitHub-Api-Version"] = "2022-11-28"

    for attempt in range(1, retries + 1):
        existing_size = target.stat().st_size if target.is_file() else 0
        request_headers = dict(headers)
        if existing_size:
            request_headers["Range"] = f"bytes={existing_size}-"
        request = urllib.request.Request(url, headers=request_headers)
        try:
            digest = hashlib.sha256()
            with urllib.request.urlopen(request, timeout=120) as response:
                status = getattr(response, "status", None)
                append = existing_size > 0 and status == 206
                if append:
                    with target.open("rb") as prefix:
                        for chunk in iter(lambda: prefix.read(8 * 1024 * 1024), b""):
                            digest.update(chunk)
                    size = existing_size
                else:
                    size = 0
                with target.open("ab" if append else "wb") as output:
                    while True:
                        chunk = response.read(8 * 1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
            return size, digest.hexdigest()
        except urllib.error.HTTPError as exc:
            if exc.code == 416 and existing_size:
                # A stale or oversized partial cannot be resumed. Remove it and
                # retry from byte zero instead of trusting an invalid prefix.
                target.unlink(missing_ok=True)
                continue
            transient = exc.code in {403, 429, 500, 502, 503, 504}
            if not transient or attempt >= retries:
                detail = exc.read().decode("utf-8", errors="replace")[:800]
                raise RestoreError(f"HTTP {exc.code} for {url}: {detail}") from exc
            reset = exc.headers.get("X-RateLimit-Reset")
            delay = min(120.0, float(2 ** min(attempt, 6)))
            if reset and reset.isdigit():
                delay = max(delay, min(120.0, int(reset) - time.time() + 2.0))
            time.sleep(max(1.0, delay))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt >= retries:
                raise RestoreError(f"streaming download failure for {url}: {exc}") from exc
            time.sleep(min(60.0, float(2 ** attempt)))
    raise RestoreError(f"unreachable streaming retry state for {url}")



def _list_release_assets(
    repository: str, release_id: int, *, token: str | None = None
) -> list[Mapping[str, Any]]:
    """Enumerate every asset; the Releases list can truncate embedded assets at 30."""
    if type(release_id) is not int or release_id <= 0:
        raise RestoreError("release has no valid id")
    assets: list[Mapping[str, Any]] = []
    ids: set[int] = set()
    names: set[str] = set()
    page = 1
    while True:
        url = (
            f"https://api.github.com/repos/{repository}/releases/"
            f"{release_id}/assets?per_page=100&page={page}"
        )
        payload = _json(url, token=token)
        if not isinstance(payload, list):
            raise RestoreError(f"invalid asset listing for release {release_id} page {page}")
        for asset in payload:
            if not isinstance(asset, Mapping):
                raise RestoreError(f"invalid asset record in release {release_id}")
            asset_id = asset.get("id")
            name = asset.get("name")
            size = asset.get("size")
            url = asset.get("browser_download_url")
            if type(asset_id) is not int or asset_id <= 0 or asset_id in ids:
                raise RestoreError(f"missing or duplicated asset id in release {release_id}")
            if not isinstance(name, str) or not name or name in names:
                raise RestoreError(f"missing or duplicated asset name in release {release_id}")
            if type(size) is not int or size < 0:
                raise RestoreError(f"invalid asset size for {name}")
            if not isinstance(url, str) or not url.startswith("https://"):
                raise RestoreError(f"invalid download URL for {name}")
            if _expected_digest(asset) is None:
                raise RestoreError(f"missing/invalid SHA-256 for {name}")
            if asset.get("state") != "uploaded":
                raise RestoreError(f"asset not fully uploaded: {name}")
            ids.add(asset_id)
            names.add(name)
            assets.append(asset)
        if len(payload) < 100:
            return assets
        page += 1


def iter_releases(repository: str, *, token: str | None = None) -> Iterable[Mapping[str, Any]]:
    """Read complete historical Releases and their independently paged asset lists."""
    # Ten full Release objects per call avoids 504s when releases carry many assets.
    # Asset lists remain independently paginated and SHA-verified.
    page = 1
    seen_ids: set[int] = set()
    seen_tags: set[str] = set()
    while True:
        url = f"https://api.github.com/repos/{repository}/releases?per_page=10&page={page}"
        payload = _json(url, token=token)
        if not isinstance(payload, list):
            raise RestoreError("release listing is not a JSON array")
        if not payload:
            return
        for release in payload:
            if not isinstance(release, Mapping):
                raise RestoreError("malformed Release in listing")
            release_id = release.get("id")
            tag = release.get("tag_name")
            if type(release_id) is not int or release_id <= 0 or release_id in seen_ids:
                raise RestoreError("missing or duplicated Release id")
            if not isinstance(tag, str) or not tag or tag in seen_tags:
                raise RestoreError("missing or duplicated Release tag")
            seen_ids.add(release_id)
            seen_tags.add(tag)
            complete_release = dict(release)
            complete_release["assets"] = _list_release_assets(
                repository, release_id, token=token
            )
            yield complete_release
        if len(payload) < 10:
            return
        page += 1


def _expected_digest(asset: Mapping[str, Any]) -> str | None:
    raw = str(asset.get("digest") or "")
    if re.fullmatch(r"sha256:[0-9a-fA-F]{64}", raw):
        return raw.split(":", 1)[1].lower()
    return None


def _asset_ok(path: Path, asset: Mapping[str, Any]) -> bool:
    if not path.is_file():
        return False
    size = asset.get("size")
    digest = _expected_digest(asset)
    return (
        type(size) is int
        and size >= 0
        and path.stat().st_size == size
        and digest is not None
        and _sha256(path) == digest
    )



def _clone_lfs_sources(
    clone_root: Path | None,
    repository: str,
    releases: list[Mapping[str, Any]],
) -> dict[tuple[str, str], Path]:
    """Reuse only materialized LFS bytes bound to the current Release inventory.

    A Git LFS pointer, a stale mirror manifest or a corrupted blob is never
    accepted as data. Missing/corrupt objects fall back to verified Releases.
    """
    if clone_root is None:
        return {}
    clone_root = Path(clone_root).resolve()
    manifest_path = clone_root / "clone_payload" / "MANIFEST.json"
    if not manifest_path.exists():
        return {}
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise RestoreError("unsafe Git LFS clone manifest")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RestoreError(f"invalid Git LFS clone manifest: {exc}") from exc
    if (
        not isinstance(manifest, Mapping)
        or manifest.get("schema") != "alina.clone_payload_manifest.v1"
        or manifest.get("repository") != repository
        or not isinstance(manifest.get("entries"), list)
    ):
        raise RestoreError("Git LFS clone manifest provenance mismatch")

    rows: dict[int, tuple[Mapping[str, Any], Path]] = {}
    paths: set[str] = set()
    payload_root = clone_root / "clone_payload" / "releases"
    for row in manifest["entries"]:
        if not isinstance(row, Mapping):
            raise RestoreError("invalid Git LFS clone asset row")
        asset_id = row.get("asset_id")
        raw = row.get("clone_path")
        if type(asset_id) is not int or asset_id <= 0 or asset_id in rows:
            raise RestoreError("duplicate or invalid Git LFS asset id")
        if not isinstance(raw, str) or not raw or raw in paths or "\\" in raw or ":" in raw:
            raise RestoreError("invalid Git LFS clone asset path")
        parts = PurePosixPath(raw).parts
        if (
            len(parts) != 4
            or parts[:2] != ("clone_payload", "releases")
            or any(part in ("", ".", "..") for part in parts)
            or PurePosixPath(raw).as_posix() != raw
        ):
            raise RestoreError("unsafe Git LFS clone asset path")
        candidate = clone_root.joinpath(*parts)
        if any(part.is_symlink() for part in (candidate, *candidate.parents) if part != clone_root and clone_root in part.parents):
            raise RestoreError("symlink in Git LFS clone payload")
        if not candidate.resolve().is_relative_to(payload_root.resolve()):
            raise RestoreError("Git LFS clone asset path escapes repository")
        if (
            type(row.get("bytes")) is not int or row["bytes"] < 0
            or not isinstance(row.get("sha256"), str)
            or not re.fullmatch(r"[0-9a-fA-F]{64}", row["sha256"])
        ):
            raise RestoreError("invalid Git LFS asset size or SHA-256")
        paths.add(raw)
        rows[asset_id] = (row, candidate)

    if (
        type(manifest.get("total_assets")) is not int
        or manifest["total_assets"] != len(rows)
        or type(manifest.get("total_bytes")) is not int
        or manifest["total_bytes"] != sum(row["bytes"] for row, _ in rows.values())
    ):
        raise RestoreError("Git LFS clone manifest totals mismatch")

    verified: dict[tuple[str, str], Path] = {}
    for release in releases:
        tag = str(release.get("tag_name") or "")
        release_id = release.get("id")
        for asset in release.get("assets") or []:
            asset_id = asset.get("id")
            item = rows.get(asset_id) if type(asset_id) is int else None
            if item is None:
                continue
            row, source = item
            if (
                row.get("release_id") != release_id
                or row.get("release_tag") != tag
                or row.get("asset_name") != asset.get("name")
                or row.get("bytes") != asset.get("size")
                or row["sha256"].lower() != _expected_digest(asset)
            ):
                continue
            if not _asset_ok(source, asset):
                continue
            verified[(tag, str(asset["name"]))] = source
    return verified


def _verify_zip_archive(path: Path, name: str) -> None:
    """Refuse ambiguous or unsafe members even in a SHA-verified Release ZIP.

    The Release digest proves which bytes were published, not that every member
    is safe to materialize on Windows. Do not extract any member here.
    """
    if not name.lower().endswith(".zip"):
        return
    windows_reserved = {
        "CON", "PRN", "AUX", "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
    try:
        with zipfile.ZipFile(path) as archive:
            seen: set[str] = set()
            for info in archive.infolist():
                member = info.filename
                relative = member[:-1] if member.endswith("/") else member
                components = relative.split("/")
                if (
                    not relative
                    or member.startswith(("/", "\\"))
                    or "\\" in member
                    or ":" in relative
                    or any(ord(ch) < 32 for ch in member)
                    or any(
                        part in ("", ".", "..")
                        or part.endswith((" ", "."))
                        or part.split(".", 1)[0].upper() in windows_reserved
                        for part in components
                    )
                ):
                    raise RestoreError(f"unsafe ZIP member in {name}: {member!r}")
                # Windows targets are case-insensitive by default.
                normalized = relative.casefold()
                if normalized in seen:
                    raise RestoreError(f"ambiguous duplicate ZIP members: {name}")
                seen.add(normalized)
                mode = (info.external_attr >> 16) & 0xFFFF
                kind = stat.S_IFMT(mode)
                if kind not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise RestoreError(f"unsafe ZIP member type in {name}: {member!r}")
                if info.flag_bits & 1:
                    raise RestoreError(f"encrypted ZIP member in {name}: {member!r}")
            corrupt_member = archive.testzip()
    except RestoreError:
        # Preserve explicit unsafe-member and duplicate-member diagnostics.
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise RestoreError(f"invalid ZIP archive: {name}") from exc
    if corrupt_member is not None:
        raise RestoreError(f"corrupt ZIP member in {name}: {corrupt_member}")


def download_asset(
    asset: Mapping[str, Any],
    destination: Path,
    *,
    token: str | None = None,
    clone_candidate: Path | None = None,
) -> dict[str, Any]:
    name = str(asset.get("name") or "")
    url = str(asset.get("browser_download_url") or "")
    if not name or not url:
        raise RestoreError("release asset is missing name/browser_download_url")
    if _expected_digest(asset) is None:
        raise RestoreError(f"missing/invalid SHA-256 for {name}")
    if type(asset.get("size")) is not int or asset["size"] < 0:
        raise RestoreError(f"invalid size for {name}")
    target = destination / _safe_component(name)
    target.parent.mkdir(parents=True, exist_ok=True)
    if _asset_ok(target, asset):
        _verify_zip_archive(target, name)
        return {"name": name, "path": str(target), "status": "SKIPPED_VERIFIED"}

    tmp = target.with_suffix(target.suffix + ".partial")
    if clone_candidate is not None and _asset_ok(clone_candidate, asset):
        # A verified hardlink avoids a second multi-GB transfer when both
        # paths share a filesystem; cross-volume restores copy the bytes.
        tmp.unlink(missing_ok=True)
        try:
            try:
                os.link(clone_candidate, tmp)
            except OSError:
                shutil.copy2(clone_candidate, tmp)
            if not _asset_ok(tmp, asset):
                raise RestoreError(f"Git LFS restored bytes changed: {name}")
            _verify_zip_archive(tmp, name)
            tmp.replace(target)
            return {"name": name, "path": str(target),
                    "status": "LFS_REUSED_VERIFIED"}
        except (OSError, RestoreError):
            tmp.unlink(missing_ok=True)
            raise
    if _asset_ok(tmp, asset):
        _verify_zip_archive(tmp, name)
        tmp.replace(target)
        return {"name": name, "path": str(target), "status": "RESUMED_VERIFIED"}
    actual_size, actual_sha = _download_to_path(url, tmp, token=token)
    expected_size = asset["size"]
    if actual_size != expected_size:
        # A short file is a resumable prefix; an oversized file is unusable.
        if actual_size > expected_size:
            tmp.unlink(missing_ok=True)
        raise RestoreError(f"size mismatch for {name}")
    expected_sha = _expected_digest(asset)
    if actual_sha != expected_sha:
        tmp.unlink(missing_ok=True)
        raise RestoreError(f"sha256 mismatch for {name}")
    _verify_zip_archive(tmp, name)
    tmp.replace(target)
    return {"name": name, "path": str(target), "status": "DOWNLOADED_VERIFIED"}


def _verified_row_bytes(path: Path, row: Mapping[str, Any]) -> bool:
    expected_sha = str(row.get("sha256") or "").lower()
    expected_size = row.get("bytes")
    return (
        path.is_file()
        and type(expected_size) is int
        and expected_size >= 0
        and re.fullmatch(r"[0-9a-f]{64}", expected_sha) is not None
        and path.stat().st_size == expected_size
        and _sha256(path) == expected_sha
    )


def _load_current_safe_catalog(
    index_path: Path,
    metrics_path: Path,
) -> tuple[dict[str, tuple[str, str]], dict[str, Any]]:
    """Bind SAFE restoration to the latest index with SHA-matched metrics.

    A historical Release manifest may say SAFE although a later reconciliation
    downgraded the same shard. Immutable Release claims cannot override the
    current catalog's quality decision.
    """
    try:
        index_bytes = index_path.read_bytes()
        index = read_index(index_path)
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RestoreError(f"invalid or missing canonical catalog/metrics: {exc}") from exc
    if not isinstance(index, Mapping) or not isinstance(index.get("shards"), list):
        raise RestoreError("canonical DATA_INDEX has no valid shards array")
    if not isinstance(metrics, Mapping) or not isinstance(metrics.get("totals"), Mapping):
        raise RestoreError("canonical DATA_METRICS has no valid totals")
    digest = hashlib.sha256(index_bytes).hexdigest()
    if (
        metrics.get("schema_version") != "alina.data_metrics.v4"
        or metrics.get("source_index_sha256") != digest
        or type(metrics["totals"].get("TOTAL_SHARDS")) is not int
        or metrics["totals"]["TOTAL_SHARDS"] != len(index["shards"])
    ):
        raise RestoreError("canonical DATA_METRICS does not match current DATA_INDEX")
    safe: dict[str, tuple[str, str]] = {}
    seen: set[str] = set()
    for row in index["shards"]:
        if not isinstance(row, Mapping):
            raise RestoreError("malformed canonical catalog shard row")
        identity = str(row.get("dataset_id") or "")
        if not identity or identity in seen:
            raise RestoreError("missing or duplicated dataset_id in canonical catalog")
        seen.add(identity)
        sha = str(row.get("sha256") or "").lower()
        tag = str(row.get("release_tag") or "")
        if (
            row.get("quality_status") == "SAFE"
            and row.get("replay_compatible") is True
            and re.fullmatch(r"[0-9a-f]{64}", sha)
            and tag
        ):
            safe[identity] = (sha, tag)
    return safe, {
        "source_index_sha256": digest,
        "indexed_shards": len(seen),
        "safe_catalog_shards": len(safe),
    }


def _safe_replay_row(
    row: Mapping[str, Any],
    *,
    repository: str,
    release_tag: str,
) -> bool:
    release = row.get("release")
    release = release if isinstance(release, Mapping) else {}
    row_repository = str(
        release.get("repository") or row.get("release_repository") or ""
    )
    row_tag = str(
        release.get("release_tag")
        or release.get("tag")
        or row.get("release_tag")
        or ""
    )
    return (
        row.get("quality_status") == "SAFE"
        and row.get("validation_allowed") is True
        and row.get("replay_compatible") is True
        and row.get("asset_verified") is True
        and row_repository == repository
        and row_tag == release_tag
    )


def _materialize_classified_shards(
    repository: str,
    releases_root: Path,
    destination: Path,
    *,
    catalog_safe: Mapping[str, tuple[str, str]] | None = None,
    allowed_release_dirs: set[str] | None = None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "usable_shards": 0,
        "quarantined_shards": 0,
        "excluded_rows": 0,
        "missing_or_corrupt_rows": 0,
        "verified_zip_members": 0,
        "stale_usable_quarantined": 0,
        "ignored_stale_release_manifests": 0,
        "failures": [],
    }
    expected_usable: set[Path] = set()
    diagnostics = destination / "diagnostics" / "run_manifests"
    for manifest_path in sorted(releases_root.glob("*/RUN_MANIFEST.json")):
        release_tag = manifest_path.parent.name
        if allowed_release_dirs is not None and release_tag not in allowed_release_dirs:
            report["ignored_stale_release_manifests"] += 1
            continue
        diagnostic_dir = diagnostics / release_tag
        diagnostic_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(manifest_path, diagnostic_dir / "RUN_MANIFEST.json")
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            report["failures"].append({
                "manifest": str(manifest_path),
                "error": f"INVALID_RUN_MANIFEST:{exc}",
            })
            continue
        rows = payload.get("manifests") if isinstance(payload, Mapping) else None
        if not isinstance(rows, list):
            report["failures"].append({
                "manifest": str(manifest_path),
                "error": "INVALID_RUN_MANIFEST:missing manifests list",
            })
            continue
        # Ambiguous identities must never be allowed to overwrite one another.
        dataset_counts: dict[str, int] = {}
        for candidate in rows:
            if isinstance(candidate, Mapping):
                identity = str(candidate.get("dataset_id") or "")
                if identity:
                    dataset_counts[identity] = dataset_counts.get(identity, 0) + 1
        duplicates = {key for key, count in dataset_counts.items() if count > 1}
        for row in rows:
            if not isinstance(row, Mapping):
                report["excluded_rows"] += 1
                continue
            dataset_id = str(row.get("dataset_id") or "")
            if not dataset_id:
                report["excluded_rows"] += 1
                continue
            if dataset_id in duplicates:
                report["excluded_rows"] += 1
                report["failures"].append({
                    "dataset_id": dataset_id,
                    "error": "DUPLICATE_DATASET_ID_IN_MANIFEST",
                    "manifest": str(manifest_path),
                })
                continue
            release = row.get("release")
            release = release if isinstance(release, Mapping) else {}
            # Overflow run manifests live in a separate control Release.
            # Each row must resolve to its own immutable data Release.
            data_tag = str(
                release.get("release_tag") or release.get("tag")
                or row.get("release_tag")
                or payload.get("data_release_base_tag")
                or release_tag
            )
            safe = _safe_replay_row(
                row, repository=repository, release_tag=data_tag
            )
            if catalog_safe is not None:
                safe = safe and catalog_safe.get(dataset_id) == (
                    str(row.get("sha256") or "").lower(), data_tag
                )
            if (allowed_release_dirs is not None
                    and _safe_component(data_tag) not in allowed_release_dirs):
                report["missing_or_corrupt_rows"] += 1
                report["failures"].append({
                    "dataset_id": dataset_id,
                    "error": "RELEASE_TAG_NOT_IN_CURRENT_SOURCE",
                    "data_release_tag": data_tag,
                })
                continue
            storage = str(release.get("storage") or row.get("release_storage") or "")
            outer_name = str(
                release.get("asset_name")
                or row.get("release_container_asset")
                or row.get("release_asset")
                or ""
            )
            member_name = str(
                release.get("member_name") or row.get("release_member") or ""
            )
            if not outer_name:
                report["missing_or_corrupt_rows"] += 1
                report["failures"].append({
                    "dataset_id": dataset_id,
                    "error": "RELEASE_ASSET_MISSING",
                    "safe_candidate": safe,
                })
                continue
            source = releases_root / _safe_component(data_tag) / _safe_component(outer_name)
            target_root = (
                destination
                / ("usable" if safe else "quarantine")
                / "shards"
                / _safe_component(data_tag)
            )
            target_root.mkdir(parents=True, exist_ok=True)
            target = target_root / f"{_safe_component(dataset_id)}.jsonl.gz"
            tmp = target.with_suffix(target.suffix + ".partial")
            tmp.unlink(missing_ok=True)
            try:
                if storage == "zip_entry" or member_name:
                    if (
                        Path(member_name).name != member_name
                        or not member_name
                        or not source.is_file()
                    ):
                        raise RestoreError("unsafe or missing ZIP member")
                    with zipfile.ZipFile(source) as archive:
                        info = archive.getinfo(member_name)
                        expected_size = row.get("bytes")
                        if (
                            type(expected_size) is not int
                            or expected_size < 0
                            or info.file_size != expected_size
                        ):
                            raise RestoreError("ZIP member size does not match manifest")
                        with archive.open(member_name) as member, tmp.open("wb") as output:
                            shutil.copyfileobj(member, output, length=8 * 1024 * 1024)
                    report["verified_zip_members"] += 1
                else:
                    if not source.is_file():
                        raise RestoreError("release asset missing")
                    try:
                        os.link(source, tmp)
                    except OSError:
                        shutil.copy2(source, tmp)
                if not _verified_row_bytes(tmp, row):
                    raise RestoreError("shard member size/SHA-256 mismatch")
                tmp.replace(target)
            except (OSError, KeyError, zipfile.BadZipFile, RestoreError) as exc:
                tmp.unlink(missing_ok=True)
                report["missing_or_corrupt_rows"] += 1
                report["failures"].append({
                    "dataset_id": dataset_id,
                    "error": str(exc),
                    "safe_candidate": safe,
                })
                continue
            if safe:
                expected_usable.add(target)
                report["usable_shards"] += 1
            else:
                report["quarantined_shards"] += 1

    # Restores are repeatable: a previously SAFE shard must not remain under
    # usable/ after its latest manifest is downgraded, removed, or ambiguous.
    # Keep the original verified Release unchanged; preserve old materializations
    # separately for diagnosis rather than deleting potentially useful evidence.
    usable_root = destination / "usable" / "shards"
    if usable_root.is_dir():
        for previous in sorted(usable_root.glob("*/*.jsonl.gz")):
            if previous in expected_usable:
                continue
            if previous.is_symlink() or not previous.is_file():
                report["failures"].append({
                    "path": str(previous),
                    "error": "UNSAFE_PREVIOUS_USABLE_FILE",
                })
                continue
            try:
                old_digest = _sha256(previous)
                stale_root = destination / "quarantine" / "stale_usable" / previous.parent.name
                stale_root.mkdir(parents=True, exist_ok=True)
                stale_path = stale_root / f"{previous.name}.{old_digest[:20]}.stale"
                if stale_path.exists():
                    if _sha256(stale_path) != old_digest:
                        raise RestoreError("stale quarantine destination collision")
                    previous.unlink()  # identical preserved quarantine copy exists
                else:
                    previous.replace(stale_path)
                report["stale_usable_quarantined"] += 1
            except (OSError, RestoreError) as exc:
                report["failures"].append({
                    "path": str(previous),
                    "error": f"STALE_USABLE_QUARANTINE_FAILED:{exc}",
                })
    return report


def _verify_run_manifests(
    root: Path, *, allowed_release_dirs: set[str] | None = None
) -> list[dict[str, Any]]:
    asset_lookup: dict[tuple[str, str], Path] = {}
    for release_dir in root.iterdir() if root.exists() else []:
        if not release_dir.is_dir():
            continue
        if allowed_release_dirs is not None and release_dir.name not in allowed_release_dirs:
            continue
        for path in release_dir.iterdir():
            if path.is_file():
                asset_lookup[(release_dir.name, path.name)] = path

    checks: list[dict[str, Any]] = []
    for manifest_path in root.glob("*/RUN_MANIFEST.json"):
        if allowed_release_dirs is not None and manifest_path.parent.name not in allowed_release_dirs:
            continue
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            checks.append({"manifest": str(manifest_path), "status": "INVALID", "detail": str(exc)})
            continue
        rows = payload.get("manifests") if isinstance(payload, Mapping) else None
        if not isinstance(rows, list):
            checks.append({"manifest": str(manifest_path), "status": "INVALID", "detail": "missing manifests list"})
            continue
        missing = 0
        bad = 0
        verified = 0
        for row in rows:
            if not isinstance(row, Mapping):
                bad += 1
                continue
            release = row.get("release")
            release = release if isinstance(release, Mapping) else {}
            raw_tag = str(
                release.get("release_tag")
                or release.get("tag")
                or row.get("release_tag")
                or payload.get("data_release_base_tag")
                or payload.get("release_tag")
                or ""
            )
            storage = str(release.get("storage") or row.get("release_storage") or "")
            name = str(
                release.get("asset_name")
                or row.get("release_container_asset")
                or row.get("release_asset")
                or ""
            )
            member_name = str(
                release.get("member_name") or row.get("release_member") or ""
            )
            expected = str(row.get("sha256") or "").lower()
            tag = _safe_component(raw_tag) if raw_tag else ""
            safe_name = _safe_component(name) if name else ""
            path = asset_lookup.get((tag, safe_name)) if tag and safe_name else None
            if path is None:
                missing += 1
                continue
            if storage == "zip_entry" or member_name:
                if Path(member_name).name != member_name or not member_name:
                    bad += 1
                    continue
                try:
                    digest = hashlib.sha256()
                    member_size = 0
                    with zipfile.ZipFile(path) as archive, archive.open(member_name) as source:
                        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
                            digest.update(chunk)
                            member_size += len(chunk)
                except (OSError, KeyError, zipfile.BadZipFile):
                    bad += 1
                    continue
                expected_size = row.get("bytes")
                if (
                    re.fullmatch(r"[0-9a-f]{64}", expected) is None
                    or digest.hexdigest() != expected
                    or type(expected_size) is not int
                    or member_size != expected_size
                ):
                    bad += 1
                else:
                    verified += 1
            elif (
                re.fullmatch(r"[0-9a-f]{64}", expected) is None
                or type(row.get("bytes")) is not int
                or path.stat().st_size != row.get("bytes")
                or _sha256(path) != expected
            ):
                bad += 1
            else:
                verified += 1
        status = "OK" if missing == 0 and bad == 0 else "FAIL"
        checks.append(
            {
                "manifest": str(manifest_path),
                "status": status,
                "verified_assets": verified,
                "missing_assets": missing,
                "bad_assets": bad,
            }
        )
    return checks


def _safe_workspace_target(workspace: Path, relative: str) -> Path:
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        raise RestoreError(f"unsafe snapshot path: {relative!r}")
    target = (workspace / rel).resolve()
    root = workspace.resolve()
    if root != target and root not in target.parents:
        raise RestoreError(f"snapshot path escapes workspace: {relative!r}")
    if rel.parts[0] == ".git":
        raise RestoreError("local snapshot may never write inside .git")
    return target


def _copy_exact_segment(source: Any, output: Any, length: int) -> None:
    """Copy exactly one snapshot segment with bounded memory, even for multi-GB parts."""
    if type(length) is not int or length < 0:
        raise RestoreError("invalid snapshot segment length")
    remaining = length
    while remaining:
        chunk = source.read(min(remaining, 8 * 1024 * 1024))
        if not chunk:
            raise RestoreError("short chunk read for snapshot segment")
        if len(chunk) > remaining:
            raise RestoreError("snapshot segment exceeded declared length")
        output.write(chunk)
        remaining -= len(chunk)


def materialize_latest_local_snapshot(
    releases_root: Path,
    workspace: Path,
) -> dict[str, Any] | None:
    candidates: list[tuple[str, Path, Mapping[str, Any]]] = []
    for directory in releases_root.glob("alina-local-snapshot-*"):
        index_path = directory / "ALINA_LOCAL_SNAPSHOT_INDEX.json"
        if not index_path.is_file():
            continue
        try:
            payload = json.loads(index_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, Mapping) and payload.get("schema") == "alina.local_snapshot.v1":
            created_at = str(payload.get("created_at_utc") or directory.name)
            candidates.append((created_at, directory, payload))
    if not candidates:
        return None

    _created_at, directory, index = sorted(candidates, key=lambda row: row[0])[-1]
    chunk_rows = index.get("chunks")
    file_rows = index.get("files")
    if not isinstance(chunk_rows, list) or not isinstance(file_rows, list):
        raise RestoreError("latest local snapshot index is incomplete")

    chunks: dict[str, Path] = {}
    for row in chunk_rows:
        if not isinstance(row, Mapping):
            raise RestoreError("invalid local snapshot chunk row")
        name = str(row.get("name") or "")
        expected_sha = str(row.get("sha256") or "").lower()
        expected_size = int(row.get("bytes") or 0)
        path = directory / _safe_component(name)
        if not path.is_file() or path.stat().st_size != expected_size:
            raise RestoreError(f"missing local snapshot chunk: {name}")
        if len(expected_sha) != 64 or _sha256(path) != expected_sha:
            raise RestoreError(f"local snapshot chunk sha256 mismatch: {name}")
        chunks[name] = path

    pending_materialization = 0
    for row in file_rows:
        if not isinstance(row, Mapping):
            raise RestoreError("invalid local snapshot file row")
        relative = str(row.get("path") or "")
        expected_sha = str(row.get("sha256") or "").lower()
        expected_size = int(row.get("bytes") or 0)
        if not relative or len(expected_sha) != 64 or expected_size < 0:
            raise RestoreError("invalid local snapshot file identity")
        target = _safe_workspace_target(workspace, relative)
        if not (
            target.is_file()
            and target.stat().st_size == expected_size
            and _sha256(target) == expected_sha
        ):
            pending_materialization += expected_size

    free_workspace = shutil.disk_usage(workspace).free
    safety_margin = 1024 * 1024 * 1024
    if pending_materialization + safety_margin > free_workspace:
        raise RestoreError(
            "insufficient disk space to materialize latest local snapshot: "
            f"need_at_least={pending_materialization + safety_margin} "
            f"free={free_workspace}"
        )

    restored = 0
    skipped = 0
    for row in file_rows:
        if not isinstance(row, Mapping):
            raise RestoreError("invalid local snapshot file row")
        relative = str(row.get("path") or "")
        expected_sha = str(row.get("sha256") or "").lower()
        expected_size = int(row.get("bytes") or 0)
        segments = row.get("segments")
        if not relative or len(expected_sha) != 64 or expected_size < 0:
            raise RestoreError("invalid local snapshot file identity")
        if not isinstance(segments, list):
            raise RestoreError(f"missing segments for {relative}")
        target = _safe_workspace_target(workspace, relative)
        if (
            target.is_file()
            and target.stat().st_size == expected_size
            and _sha256(target) == expected_sha
        ):
            skipped += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".alina-restore-partial")
        tmp.unlink(missing_ok=True)
        with tmp.open("wb") as output:
            for segment in segments:
                if not isinstance(segment, Mapping):
                    raise RestoreError(f"invalid segment for {relative}")
                chunk_name = str(segment.get("chunk") or "")
                offset = int(segment.get("offset") or 0)
                length = int(segment.get("bytes") or 0)
                chunk = chunks.get(chunk_name)
                if chunk is None or offset < 0 or length < 0:
                    raise RestoreError(f"invalid chunk reference for {relative}")
                with chunk.open("rb") as source:
                    source.seek(offset)
                    _copy_exact_segment(source, output, length)
        if tmp.stat().st_size != expected_size or _sha256(tmp) != expected_sha:
            tmp.unlink(missing_ok=True)
            raise RestoreError(f"restored local file sha256 mismatch: {relative}")
        tmp.replace(target)
        restored += 1

    return {
        "tag": str(index.get("tag") or directory.name),
        "restored_files": restored,
        "skipped_verified_files": skipped,
        "file_count": len(file_rows),
    }


def _claimed_data_release_tags(
    releases_root: Path, allowed_release_dirs: set[str]
) -> set[str]:
    """Find data-only Releases claimed by canonical verified manifest files."""
    claimed: set[str] = set()
    for path in sorted(releases_root.glob("*/RUN_MANIFEST.json")):
        if path.parent.name not in allowed_release_dirs:
            continue
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(manifest, Mapping):
            continue
        parts = manifest.get("release_parts")
        for part in parts if isinstance(parts, list) else []:
            if isinstance(part, Mapping) and isinstance(part.get("release_tag"), str):
                claimed.add(_safe_component(part["release_tag"]))
        rows = manifest.get("manifests")
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, Mapping):
                continue
            release = row.get("release")
            release = release if isinstance(release, Mapping) else {}
            tag = (
                release.get("release_tag") or release.get("tag")
                or row.get("release_tag") or manifest.get("data_release_base_tag")
                or manifest.get("release_tag")
            )
            if isinstance(tag, str) and tag:
                claimed.add(_safe_component(tag))
    return claimed


def restore_everything(
    repository: str,
    destination: Path,
    *,
    token: str | None = None,
    workspace: Path | None = None,
    catalog_path: Path | None = None,
    metrics_path: Path | None = None,
    clone_root: Path | None = None,
) -> dict[str, Any]:
    catalog_safe: dict[str, tuple[str, str]] | None = None
    catalog_verification: dict[str, Any] | None = None
    if catalog_path is not None:
        if metrics_path is None:
            raise RestoreError("canonical DATA_METRICS is required with DATA_INDEX")
        catalog_safe, catalog_verification = _load_current_safe_catalog(
            catalog_path, metrics_path
        )
    releases_root = destination / "releases"
    releases_root.mkdir(parents=True, exist_ok=True)
    releases = list(iter_releases(repository, token=token))
    # Never start transferring data with a partial/malformed source inventory.
    seen_tags: set[str] = set()
    for release in releases:
        tag = release.get("tag_name")
        assets = release.get("assets")
        if not isinstance(tag, str) or not tag or tag in seen_tags:
            raise RestoreError("duplicate or missing Release tag in source inventory")
        if not isinstance(assets, list):
            raise RestoreError(f"missing asset list for Release {tag}")
        seen_tags.add(tag)
        # Data-only Releases are intentional in oversized Dataset runs.
        # Preserve every SHA-verified byte and classify via canonical manifest.
        seen_names: set[str] = set()
        for asset in assets:
            if not isinstance(asset, Mapping):
                raise RestoreError(f"invalid asset record in Release {tag}")
            name = asset.get("name")
            if not isinstance(name, str) or not name or name in seen_names:
                raise RestoreError(f"duplicate or missing asset name in Release {tag}")
            if _expected_digest(asset) is None:
                raise RestoreError(f"missing/invalid SHA-256 for {tag}/{name}")
            if type(asset.get("size")) is not int or asset["size"] < 0:
                raise RestoreError(f"missing/invalid size for {tag}/{name}")
            if not isinstance(asset.get("browser_download_url"), str) or not asset["browser_download_url"].startswith("https://"):
                raise RestoreError(f"invalid download URL for {tag}/{name}")
            seen_names.add(name)

    clone_sources = _clone_lfs_sources(clone_root, repository, releases)

    # Old cached Releases must never be treated as part of the current GitHub
    # inventory or silently reintroduce formerly SAFE local materializations.
    allowed_release_dirs = {_safe_component(tag) for tag in seen_tags}
    if len(allowed_release_dirs) != len(seen_tags):
        raise RestoreError("Release tags collide after path normalization")

    pending_download_bytes = 0
    for release in releases:
        tag = str(release.get("tag_name") or "")
        if not tag:
            continue
        release_dir = releases_root / _safe_component(tag)
        assets = release.get("assets")
        for asset in assets if isinstance(assets, list) else []:
            if not isinstance(asset, Mapping):
                continue
            name = str(asset.get("name") or "")
            if not name:
                continue
            target = release_dir / _safe_component(name)
            if not _asset_ok(target, asset):
                source = clone_sources.get((tag, name))
                # A verified LFS hardlink occupies no new payload space on
                # the same volume. A cross-volume copy still needs capacity.
                if source is not None and source.stat().st_dev == releases_root.stat().st_dev:
                    continue
                expected_size = max(0, int(asset.get("size") or 0))
                partial = target.with_suffix(target.suffix + ".partial")
                partial_size = partial.stat().st_size if partial.is_file() else 0
                pending_download_bytes += max(0, expected_size - partial_size)

    free_destination = shutil.disk_usage(destination).free
    safety_margin = 1024 * 1024 * 1024
    if pending_download_bytes + safety_margin > free_destination:
        raise RestoreError(
            "insufficient disk space for complete GitHub Release restore: "
            f"need_at_least={pending_download_bytes + safety_margin} "
            f"free={free_destination}"
        )

    report: dict[str, Any] = {
        "schema": "alina.full_restore_report.v1",
        "repository": repository,
        "destination": str(destination),
        "release_count": 0,
        "asset_count": 0,
        "downloaded": 0,
        "resumed_verified": 0,
        "skipped_verified": 0,
        "lfs_reused_verified": 0,
        "pending_download_bytes_at_start": pending_download_bytes,
        "free_destination_bytes_at_start": free_destination,
        "failures": [],
        "releases": [],
        "read_only": True,
        "real_execution": False,
        "catalog_verification": catalog_verification,
    }

    for release in releases:
        tag = str(release.get("tag_name") or "")
        if not tag:
            continue
        safe_tag = _safe_component(tag)
        release_dir = releases_root / safe_tag
        assets = release.get("assets")
        assets = assets if isinstance(assets, list) else []
        row = {"tag": tag, "asset_count": len(assets), "assets": []}
        report["release_count"] += 1
        for asset in assets:
            if not isinstance(asset, Mapping):
                continue
            report["asset_count"] += 1
            try:
                result = download_asset(
                    asset, release_dir, token=token,
                    clone_candidate=clone_sources.get((tag, str(asset.get("name") or ""))),
                )
                row["assets"].append(result)
                if result["status"] == "DOWNLOADED_VERIFIED":
                    report["downloaded"] += 1
                elif result["status"] == "RESUMED_VERIFIED":
                    report["resumed_verified"] += 1
                elif result["status"] == "LFS_REUSED_VERIFIED":
                    report["lfs_reused_verified"] += 1
                else:
                    report["skipped_verified"] += 1
            except RestoreError as exc:
                failure = {"tag": tag, "asset": asset.get("name"), "error": str(exc)}
                report["failures"].append(failure)
                row["assets"].append({"name": asset.get("name"), "status": "FAIL", "error": str(exc)})
        report["releases"].append(row)

    # Interrupted publications remain archived, but cannot claim a fully
    # qualified restore without a canonical manifest naming their data part.
    claimed_tags = _claimed_data_release_tags(releases_root, allowed_release_dirs)
    unclaimed = sorted(
        str(release["tag_name"])
        for release in releases
        if str(release["tag_name"]).lower().startswith(
            ("data-v2", "alina-data-v2", "alina-data-part-")
        )
        and not any(
            isinstance(asset, Mapping) and asset.get("name") == "RUN_MANIFEST.json"
            for asset in release["assets"]
        )
        and _safe_component(str(release["tag_name"])) not in claimed_tags
    )
    report["unclaimed_dataset_release_count"] = len(unclaimed)
    report["unclaimed_dataset_releases_sample"] = unclaimed[:50]
    report["run_manifest_checks"] = _verify_run_manifests(
        releases_root, allowed_release_dirs=allowed_release_dirs
    )
    report["verification_failures"] = sum(
        1 for row in report["run_manifest_checks"] if row.get("status") != "OK"
    )
    report["classification"] = _materialize_classified_shards(
        repository, releases_root, destination, catalog_safe=catalog_safe,
        allowed_release_dirs=allowed_release_dirs,
    )
    report["local_snapshot"] = (
        materialize_latest_local_snapshot(releases_root, workspace)
        if workspace is not None
        else None
    )
    report["expected_assets"] = sum(len(release["assets"]) for release in releases)
    report["all_source_assets_accounted_for"] = (
        report["asset_count"] == report["expected_assets"]
        and report["downloaded"]
        + report["resumed_verified"]
        + report["lfs_reused_verified"]
        + report["skipped_verified"]
        + len(report["failures"])
        == report["expected_assets"]
    )
    report_path = destination / "RESTORE_REPORT.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Restore every canonical Alina GitHub Release asset after cloning the repository."
    )
    parser.add_argument("--everything", action="store_true", help="restore all canonical release evidence")
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--destination", default="runtime/recovery/full")
    parser.add_argument("--clone-root", default=".",
                        help="fresh clone with optional verified clone_payload/ Git LFS assets")
    parser.add_argument("--catalog", default="catalog/DATA_INDEX.json",
                        help="canonical index required to certify usable restored shards")
    parser.add_argument("--metrics", default="catalog/DATA_METRICS.json",
                        help="SHA-bound canonical metrics required for catalog verification")
    parser.add_argument(
        "--workspace",
        default=".",
        help="fresh clone root used only with --materialize-local-snapshot",
    )
    parser.add_argument(
        "--materialize-local-snapshot",
        action="store_true",
        help=(
            "explicitly restore the latest whole-workspace snapshot; disabled by "
            "default because only catalog-proven SAFE shards enter usable/"
        ),
    )
    args = parser.parse_args(argv)

    if not args.everything:
        parser.error("--everything is required to make the destructive-looking intent explicit")

    token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    destination = Path(args.destination).resolve()
    try:
        report = restore_everything(
            args.repository,
            destination,
            token=token,
            catalog_path=Path(args.catalog).resolve(),
            metrics_path=Path(args.metrics).resolve(),
            clone_root=Path(args.clone_root).resolve(),
            workspace=(
                Path(args.workspace).resolve()
                if args.materialize_local_snapshot
                else None
            ),
        )
    except RestoreError as exc:
        print(f"ALINA_RESTORE_FAIL: {exc}", file=sys.stderr)
        return 2

    failures = (
        len(report["failures"])
        + int(report["verification_failures"])
        + len(report["classification"]["failures"])
        + int(report["unclaimed_dataset_release_count"])
    )
    if not report["all_source_assets_accounted_for"]:
        failures += 1
    print(
        json.dumps(
            {
                "status": "OK" if failures == 0 else "FAIL",
                "release_count": report["release_count"],
                "asset_count": report["asset_count"],
                "downloaded": report["downloaded"],
                "resumed_verified": report["resumed_verified"],
                "skipped_verified": report["skipped_verified"],
                "lfs_reused_verified": report["lfs_reused_verified"],
                "usable_shards": report["classification"]["usable_shards"],
                "quarantined_shards": report["classification"]["quarantined_shards"],
                "missing_or_corrupt_rows": report["classification"]["missing_or_corrupt_rows"],
                "unclaimed_dataset_release_count": report["unclaimed_dataset_release_count"],
                "failures": failures,
                "report": str(destination / "RESTORE_REPORT.json"),
            },
            indent=2,
        )
    )
    return 0 if failures == 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())

