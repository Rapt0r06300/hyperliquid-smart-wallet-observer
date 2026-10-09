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
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Iterable, Mapping

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
    page = 1
    seen_ids: set[int] = set()
    seen_tags: set[str] = set()
    while True:
        url = f"https://api.github.com/repos/{repository}/releases?per_page=100&page={page}"
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
        if len(payload) < 100:
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


def _verify_zip_archive(path: Path, name: str) -> None:
    if not name.lower().endswith(".zip"):
        return
    try:
        with zipfile.ZipFile(path) as archive:
            corrupt_member = archive.testzip()
    except (OSError, zipfile.BadZipFile) as exc:
        raise RestoreError(f"invalid ZIP archive: {name}") from exc
    if corrupt_member is not None:
        raise RestoreError(f"corrupt ZIP member in {name}: {corrupt_member}")


def download_asset(
    asset: Mapping[str, Any],
    destination: Path,
    *,
    token: str | None = None,
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
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "usable_shards": 0,
        "quarantined_shards": 0,
        "excluded_rows": 0,
        "missing_or_corrupt_rows": 0,
        "verified_zip_members": 0,
        "failures": [],
    }
    diagnostics = destination / "diagnostics" / "run_manifests"
    for manifest_path in sorted(releases_root.glob("*/RUN_MANIFEST.json")):
        release_tag = manifest_path.parent.name
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
        for row in rows:
            if not isinstance(row, Mapping):
                report["excluded_rows"] += 1
                continue
            dataset_id = str(row.get("dataset_id") or "")
            if not dataset_id:
                report["excluded_rows"] += 1
                continue
            safe = _safe_replay_row(
                row, repository=repository, release_tag=release_tag
            )
            release = row.get("release")
            release = release if isinstance(release, Mapping) else {}
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
            source = manifest_path.parent / _safe_component(outer_name)
            target_root = (
                destination
                / ("usable" if safe else "quarantine")
                / "shards"
                / _safe_component(release_tag)
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
                report["usable_shards"] += 1
            else:
                report["quarantined_shards"] += 1
    return report


def _verify_run_manifests(root: Path) -> list[dict[str, Any]]:
    asset_lookup: dict[tuple[str, str], Path] = {}
    for release_dir in root.iterdir() if root.exists() else []:
        if not release_dir.is_dir():
            continue
        for path in release_dir.iterdir():
            if path.is_file():
                asset_lookup[(release_dir.name, path.name)] = path

    checks: list[dict[str, Any]] = []
    for manifest_path in root.glob("*/RUN_MANIFEST.json"):
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
                    data = source.read(length)
                if len(data) != length:
                    raise RestoreError(f"short chunk read for {relative}")
                output.write(data)
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


def restore_everything(
    repository: str,
    destination: Path,
    *,
    token: str | None = None,
    workspace: Path | None = None,
) -> dict[str, Any]:
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
        "pending_download_bytes_at_start": pending_download_bytes,
        "free_destination_bytes_at_start": free_destination,
        "failures": [],
        "releases": [],
        "read_only": True,
        "real_execution": False,
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
                result = download_asset(asset, release_dir, token=token)
                row["assets"].append(result)
                if result["status"] == "DOWNLOADED_VERIFIED":
                    report["downloaded"] += 1
                elif result["status"] == "RESUMED_VERIFIED":
                    report["resumed_verified"] += 1
                else:
                    report["skipped_verified"] += 1
            except RestoreError as exc:
                failure = {"tag": tag, "asset": asset.get("name"), "error": str(exc)}
                report["failures"].append(failure)
                row["assets"].append({"name": asset.get("name"), "status": "FAIL", "error": str(exc)})
        report["releases"].append(row)

    report["run_manifest_checks"] = _verify_run_manifests(releases_root)
    report["verification_failures"] = sum(
        1 for row in report["run_manifest_checks"] if row.get("status") != "OK"
    )
    report["classification"] = _materialize_classified_shards(
        repository, releases_root, destination
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
                "usable_shards": report["classification"]["usable_shards"],
                "quarantined_shards": report["classification"]["quarantined_shards"],
                "missing_or_corrupt_rows": report["classification"]["missing_or_corrupt_rows"],
                "failures": failures,
                "report": str(destination / "RESTORE_REPORT.json"),
            },
            indent=2,
        )
    )
    return 0 if failures == 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())

