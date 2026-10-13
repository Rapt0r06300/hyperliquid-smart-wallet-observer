#!/usr/bin/env python3
"""Restore the complete canonical Alina evidence set after a fresh git clone.

A plain git clone restores Git history and tracked files. Heavy immutable evidence
(trades, L2, replay inputs, recovery capsules and analysis assets) lives in GitHub
Releases of the same repository and is therefore restored separately by this tool.

The tool is read-only against GitHub. It uses only Python's standard library.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import http.client
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
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
            if (
                exc.code in {403, 429}
                and exc.headers.get("X-RateLimit-Remaining") == "0"
            ):
                raise RestoreError(
                    "GitHub API rate limit exhausted; run 'gh auth login' "
                    "or set GH_TOKEN/GITHUB_TOKEN and retry. Already-verified "
                    "downloads are reusable."
                ) from exc
            transient = exc.code in {403, 429, 500, 502, 503, 504}
            if not transient or attempt >= retries:
                detail = exc.read().decode("utf-8", errors="replace")[:800]
                raise RestoreError(f"HTTP {exc.code} for {url}: {detail}") from exc
            reset = exc.headers.get("X-RateLimit-Reset")
            delay = min(120.0, float(2 ** min(attempt, 6)))
            if reset and reset.isdigit():
                delay = max(delay, min(120.0, int(reset) - time.time() + 2.0))
            time.sleep(max(1.0, delay))
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
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
    max_bytes: int | None = None,
) -> tuple[int, str]:
    """Stream one Release asset; optional hard cap protects bounded recovery."""
    if max_bytes is not None and (type(max_bytes) is not int or max_bytes < 0):
        raise RestoreError("invalid bounded download byte limit")
    if max_bytes is not None and target.is_file() and target.stat().st_size > max_bytes:
        raise RestoreError("existing partial exceeds bounded download limit")
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
                if status == 206:
                    # A partial response must begin at the requested offset.
                    # Never append an unrelated range to an existing prefix.
                    content_range = getattr(response, "headers", {}).get("Content-Range")
                    match = re.fullmatch(
                        r"bytes (\d+)-(\d+)/(\d+|\*)", str(content_range or "")
                    )
                    if (
                        not existing_size or match is None
                        or int(match.group(1)) != existing_size
                        or int(match.group(2)) < existing_size
                        or (match.group(3) != "*"
                            and int(match.group(2)) >= int(match.group(3)))
                    ):
                        raise RestoreError(f"invalid HTTP Content-Range for {url}")
                elif status not in (200, None):
                    raise RestoreError(f"unexpected HTTP status {status} for {url}")
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
                        if max_bytes is not None and size + len(chunk) > max_bytes:
                            raise RestoreError("download exceeds bounded byte limit")
                        output.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
            return size, digest.hexdigest()
        except urllib.error.HTTPError as exc:
            if (
                exc.code in {403, 429}
                and exc.headers.get("X-RateLimit-Remaining") == "0"
            ):
                raise RestoreError(
                    "GitHub API rate limit exhausted; run 'gh auth login' "
                    "or set GH_TOKEN/GITHUB_TOKEN and retry. Already-verified "
                    "downloads are reusable."
                ) from exc
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
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
            if attempt >= retries:
                raise RestoreError(f"streaming download failure for {url}: {exc}") from exc
            time.sleep(min(60.0, float(2 ** attempt)))
    raise RestoreError(f"unreachable streaming retry state for {url}")



def _validate_release_asset(
    asset: Mapping[str, Any], release_id: int, ids: set[int], names: set[str],
    *, allow_incomplete: bool = False,
) -> None:
    """Apply identical strict identity, completeness and digest gates to all sources."""
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
    if _expected_digest(asset) is None and not allow_incomplete:
        raise RestoreError(f"missing/invalid SHA-256 for {name}")
    if asset.get("state") != "uploaded" and not allow_incomplete:
        raise RestoreError(f"asset not fully uploaded: {name}")
    ids.add(asset_id)
    names.add(name)


def _list_release_assets(
    repository: str, release_id: int, *, token: str | None = None,
    allow_incomplete: bool = False,
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
            _validate_release_asset(
                asset, release_id, ids, names, allow_incomplete=allow_incomplete,
            )
            assets.append(asset)
        if len(payload) < 100:
            return assets
        page += 1


def _read_restore_inventory_asset(
    asset: Mapping[str, Any], repository: str, *, token: str | None = None,
    allow_incomplete: bool = False,
    cache_path: Path | None = None,
) -> list[Mapping[str, Any]]:
    """Download and validate the GitHub-hosted inventory spanning the REST cap."""
    expected_size = asset.get("size")
    expected_sha = _expected_digest(asset)
    url = asset.get("browser_download_url")
    if type(expected_size) is not int or expected_size < 0 or expected_sha is None:
        raise RestoreError("invalid published restore inventory identity")
    if not isinstance(url, str) or not url.startswith("https://"):
        raise RestoreError("invalid published restore inventory URL")
    temporary = None
    if cache_path is None:
        temporary = tempfile.TemporaryDirectory(prefix="alina-restore-inventory-")
        path = Path(temporary.name) / "RESTORE_INVENTORY.json.gz"
    else:
        path = cache_path
        if path.parent.is_symlink() or path.is_symlink():
            raise RestoreError("symlinked published restore inventory cache")
        path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if not _asset_ok(path, asset):
            partial = path.with_suffix(path.suffix + ".partial")
            if partial.is_symlink():
                raise RestoreError("symlinked partial restore inventory cache")
            actual_size, actual_sha = _download_to_path(url, partial, token=token)
            if actual_size != expected_size or actual_sha != expected_sha:
                raise RestoreError(
                    "published restore inventory failed size/SHA-256 verification"
                )
            partial.replace(path)
        try:
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (gzip.BadGzipFile, json.JSONDecodeError, UnicodeError) as exc:
            raise RestoreError("published restore inventory is malformed") from exc
    finally:
        if temporary is not None:
            temporary.cleanup()
    if not isinstance(payload, Mapping):
        raise RestoreError("published restore inventory root is invalid")
    if payload.get("schema") != "alina.restore_inventory.v1":
        raise RestoreError("unsupported published restore inventory schema")
    if payload.get("repository") != repository:
        raise RestoreError("published restore inventory repository mismatch")
    releases = payload.get("releases")
    if not isinstance(releases, list):
        raise RestoreError("published restore inventory has no Release list")
    seen_release_ids: set[int] = set()
    seen_tags: set[str] = set()
    for release in releases:
        if not isinstance(release, Mapping):
            raise RestoreError("malformed Release in published restore inventory")
        release_id = release.get("id")
        tag = release.get("tag_name")
        assets = release.get("assets")
        if (
            type(release_id) is not int or release_id <= 0
            or release_id in seen_release_ids
            or not isinstance(tag, str) or not tag or tag in seen_tags
            or not isinstance(assets, list)
        ):
            raise RestoreError("duplicate or malformed published restore inventory Release")
        asset_ids: set[int] = set()
        asset_names: set[str] = set()
        for row in assets:
            _validate_release_asset(
                row, release_id, asset_ids, asset_names,
                allow_incomplete=allow_incomplete,
            )
        seen_release_ids.add(release_id)
        seen_tags.add(tag)
    return releases


def iter_releases(
    repository: str, *, token: str | None = None,
    allow_incomplete: bool = False,
    inventory_cache_root: Path | None = None,
) -> Iterable[Mapping[str, Any]]:
    """Read every Release and its documented embedded asset inventory."""
    # The list-Releases response contains each Release's asset array.  Reading
    # 100 Releases per page keeps large public repositories inside GitHub's
    # anonymous API allowance instead of issuing one extra request per Release.
    page_size = 100
    offset = 0
    seen_ids: dict[int, str] = {}
    seen_tags: set[str] = set()
    inventory_source: tuple[str, Mapping[str, Any]] | None = None
    while True:
        page = offset // page_size + 1
        url = f"https://api.github.com/repos/{repository}/releases?per_page={page_size}&page={page}"
        try:
            payload = _json(url, token=token)
        except RestoreError as exc:
            if "only the first 1000 results are available" in str(exc).lower():
                if inventory_source is None:
                    raise RestoreError(
                        "GitHub caps Release listing at 1000 and no published "
                        "RESTORE_INVENTORY.json.gz was found in the live window"
                    ) from exc
                inventory_tag, inventory_asset = inventory_source
                cache_path = (
                    inventory_cache_root / _safe_component(inventory_tag)
                    / _safe_component(str(inventory_asset["name"]))
                    if inventory_cache_root is not None else None
                )
                historical = _read_restore_inventory_asset(
                    inventory_asset, repository, token=token, cache_path=cache_path,
                    allow_incomplete=allow_incomplete,
                )
                for release in historical:
                    release_id = release["id"]
                    tag = release["tag_name"]
                    if release_id in seen_ids:
                        if seen_ids[release_id] != tag:
                            raise RestoreError(
                                "published restore inventory conflicts with live Release"
                            ) from exc
                        continue
                    if tag in seen_tags:
                        raise RestoreError(
                            "published restore inventory duplicates a live Release tag"
                        ) from exc
                    seen_ids[release_id] = tag
                    seen_tags.add(tag)
                    yield release
                return
            if offset and page_size > 1 and any(
                status in str(exc).lower() for status in ("http 502", "http 504")
            ):
                smaller = next((n for n in range(page_size // 2, 0, -1)
                                if offset % n == 0), None)
                if smaller is not None:
                    page_size = smaller
                    continue
            raise
        if not isinstance(payload, list):
            raise RestoreError("release listing is not a JSON array")
        if not payload:
            return
        page_ids: set[int] = set()
        for release in payload:
            if not isinstance(release, Mapping):
                raise RestoreError("malformed Release in listing")
            release_id = release.get("id")
            tag = release.get("tag_name")
            if type(release_id) is not int or release_id <= 0 or release_id in page_ids:
                raise RestoreError("missing or duplicated Release id within one page")
            page_ids.add(release_id)
            if not isinstance(tag, str) or not tag:
                raise RestoreError("missing Release tag")
            if release_id in seen_ids:
                # New Releases inserted at the front can repeat a previously seen
                # row on the next offset page. Preserve its first verified copy.
                if seen_ids[release_id] != tag:
                    raise RestoreError("Release id changed tag during pagination")
                continue
            if tag in seen_tags:
                raise RestoreError("duplicate Release tag across distinct ids")
            seen_ids[release_id] = tag
            seen_tags.add(tag)
            complete_release = dict(release)
            embedded = release.get("assets")
            if not isinstance(embedded, list):
                raise RestoreError(f"missing embedded asset array for release {release_id}")
            embedded_ids: set[int] = set()
            embedded_names: set[str] = set()
            for asset in embedded:
                _validate_release_asset(
                    asset, release_id, embedded_ids, embedded_names,
                    allow_incomplete=allow_incomplete,
                )
                if (
                    inventory_source is None
                    and tag.startswith("alina-restore-inventory-")
                    and asset.get("name") == "RESTORE_INVENTORY.json.gz"
                ):
                    inventory_source = (tag, asset)
            complete_release["assets"] = embedded
            yield complete_release
        if len(payload) < page_size:
            return
        offset += page_size


def _expected_digest(asset: Mapping[str, Any]) -> str | None:
    raw = str(asset.get("digest") or "")
    if re.fullmatch(r"sha256:[0-9a-fA-F]{64}", raw):
        return raw.split(":", 1)[1].lower()
    return None


def _source_asset_eligible(asset: Mapping[str, Any], *, salvage: bool) -> bool:
    """Never certify an unknown GitHub asset state in salvage mode.

    Legacy synthetic restore fixtures omit state; production enumeration has
    already checked state strictly before reaching ordinary restore.
    """
    return (
        _expected_digest(asset) is not None
        and asset.get("state", "missing" if salvage else "uploaded") == "uploaded"
    )


def _asset_ok(path: Path, asset: Mapping[str, Any]) -> bool:
    if path.is_symlink() or not path.is_file():
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

    def verified_result(status: str, calculated_sha256: str) -> dict[str, Any]:
        return {
            "name": name,
            "path": str(target),
            "destination": str(target),
            "status": status,
            "verification_status": "VERIFIED",
            "downloaded_size_bytes": target.stat().st_size,
            "expected_sha256": _expected_digest(asset),
            "calculated_sha256": calculated_sha256,
        }

    if target.is_symlink():
        raise RestoreError(f"symlinked Release asset target: {name}")
    if _asset_ok(target, asset):
        _verify_zip_archive(target, name)
        return verified_result("SKIPPED_VERIFIED", str(_expected_digest(asset)))

    tmp = target.with_suffix(target.suffix + ".partial")
    if tmp.is_symlink():
        raise RestoreError(f"symlinked Release asset partial: {name}")
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
            return verified_result("LFS_REUSED_VERIFIED", str(_expected_digest(asset)))
        except (OSError, RestoreError):
            tmp.unlink(missing_ok=True)
            raise
    if _asset_ok(tmp, asset):
        _verify_zip_archive(tmp, name)
        tmp.replace(target)
        return verified_result("RESUMED_VERIFIED", str(_expected_digest(asset)))
    actual_size, actual_sha = _download_to_path(
        url, tmp, token=token, max_bytes=asset["size"]
    )
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
    return verified_result("DOWNLOADED_VERIFIED", actual_sha)


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


ANALYSIS_WORKING_SET_CLASSES = {
    "replay": "replays",
    "backtest": "backtests",
    "oos": "oos",
    "forward_paper": "forward_paper",
    "module_pnl_proof": "economics",
    "scoreboard": "scoreboards",
}


def _canonical_json_sha256(value: Any) -> str:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def build_certified_working_set(
    releases: list[Mapping[str, Any]],
    *,
    raw_required: Mapping[tuple[str, str], tuple[int, str]],
    receipts_root: Path,
    campaigns_root: Path,
    repository: str,
) -> dict[str, Any]:
    """Build the fixed SAFE inputs + provenance-bound analysis asset plan."""
    required: dict[tuple[str, str], tuple[int, str]] = dict(raw_required)
    by_class: dict[str, dict[str, int]] = {
        "collections": {
            "asset_count": len(raw_required),
            "bytes": sum(size for size, _sha in raw_required.values()),
        }
    }
    for name in ANALYSIS_WORKING_SET_CLASSES.values():
        by_class[name] = {"asset_count": 0, "bytes": 0}
    release_lookup = {
        str(release.get("tag_name") or ""): release
        for release in releases
        if isinstance(release, Mapping)
    }
    evidence: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    excluded = 0
    sha64 = re.compile(r"[0-9a-f]{64}")
    sha40 = re.compile(r"[0-9a-f]{40}")
    for path in sorted(receipts_root.glob("*.json")) if receipts_root.is_dir() else []:
        try:
            receipt = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            excluded += 1
            failures.append({"receipt": str(path), "reason": "INVALID_RECEIPT_JSON", "error": str(exc)})
            continue
        kind = str(receipt.get("kind") or "") if isinstance(receipt, Mapping) else ""
        if kind not in ANALYSIS_WORKING_SET_CLASSES:
            continue
        campaign_id = str(receipt.get("campaign_id") or "")
        unit_id = str(receipt.get("unit_id") or "")
        evidence_tag = str(receipt.get("evidence_tag") or "")
        campaign_path = campaigns_root / f"{campaign_id}.json"
        valid = (
            receipt.get("schema") == "alina.publication_receipt.v2"
            and receipt.get("status") == "COMPLETE"
            and receipt.get("phase") == "ANALYZE"
            and receipt.get("publication_state") == "RELEASE_AND_RECEIPT_WRITTEN"
            and receipt.get("paper_only") is True
            and receipt.get("read_only") is True
            and receipt.get("real_execution") is False
            and type(receipt.get("source_collection_epoch")) is int
            and bool(receipt.get("collection_cutoff_at_utc"))
            and sha64.fullmatch(str(receipt.get("dataset_selection_id") or "")) is not None
            and sha40.fullmatch(str(receipt.get("code_sha") or "")) is not None
            and receipt.get("alina_head") == receipt.get("code_sha")
            and all(
                sha64.fullmatch(str(receipt.get(field) or "")) is not None
                for field in ("manifest_sha256", "checkpoint_id", "payload_digest", "result_sha256")
            )
            and evidence_tag == f"campaign-evidence-{campaign_id}-u{unit_id}"
            and campaign_path.is_file()
            and _sha256(campaign_path) == receipt.get("manifest_sha256")
        )
        if not valid:
            excluded += 1
            failures.append({"receipt": str(path), "reason": "INVALID_ANALYSIS_PROVENANCE"})
            continue
        release = release_lookup.get(evidence_tag)
        assets = release.get("assets") if isinstance(release, Mapping) else None
        if not isinstance(assets, list) or not assets:
            failures.append({"receipt": str(path), "reason": "EVIDENCE_RELEASE_MISSING"})
            continue
        selected_assets: list[dict[str, Any]] = []
        for asset in assets:
            if not isinstance(asset, Mapping):
                failures.append({"receipt": str(path), "reason": "INVALID_EVIDENCE_ASSET"})
                continue
            name = str(asset.get("name") or "")
            digest = _expected_digest(asset)
            size = asset.get("size")
            if not name or type(size) is not int or size < 0 or sha64.fullmatch(digest) is None:
                failures.append({"receipt": str(path), "reason": "UNVERIFIABLE_EVIDENCE_ASSET"})
                continue
            key = (evidence_tag, name)
            identity = (size, digest)
            if key in required and required[key] != identity:
                failures.append({"receipt": str(path), "reason": "CONFLICTING_EVIDENCE_ASSET"})
                continue
            required[key] = identity
            selected_assets.append({"name": name, "bytes": size, "sha256": digest})
            bucket = by_class[ANALYSIS_WORKING_SET_CLASSES[kind]]
            bucket["asset_count"] += 1
            bucket["bytes"] += size
        if selected_assets:
            evidence.append({
                "kind": kind,
                "class": ANALYSIS_WORKING_SET_CLASSES[kind],
                "campaign_id": campaign_id,
                "unit_id": unit_id,
                "evidence_tag": evidence_tag,
                "receipt": {**dict(receipt), "_source_repository": repository},
                "assets": selected_assets,
            })
    return {
        "schema": "alina.certified_working_set.v1",
        "repository": repository,
        "status": (
            "CERTIFIED_WORKING_SET_PLANNED" if not failures
            else "CERTIFIED_WORKING_SET_INCOMPLETE"
        ),
        "required_assets": required,
        "required_asset_count": len(required),
        "required_bytes": sum(size for size, _sha in required.values()),
        "by_class": by_class,
        "analysis_evidence": evidence,
        "excluded_receipts": excluded,
        "failures": failures,
    }


def materialize_analysis_evidence(
    archive_path: Path,
    receipt: Mapping[str, Any],
    destination_root: Path,
) -> dict[str, Any]:
    """Safely expand one remotely SHA-verified paper-analysis evidence tar."""
    tag = _safe_component(str(receipt.get("evidence_tag") or ""))
    kind = str(receipt.get("kind") or "")
    if kind not in ANALYSIS_WORKING_SET_CLASSES:
        raise RestoreError("unsupported analysis evidence kind")
    destination = destination_root / "artifacts" / _safe_component(kind) / tag
    if destination.exists():
        proof_path = destination / "CERTIFIED_EVIDENCE.json"
        try:
            proof = json.loads(proof_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RestoreError(
                f"analysis evidence destination is not certified: {destination}"
            ) from exc
        rows = proof.get("members") if isinstance(proof, Mapping) else None
        valid = (
            proof.get("schema") == "alina.materialized_analysis_evidence.v1"
            and proof.get("evidence_tag") == receipt.get("evidence_tag")
            and proof.get("archive_sha256") == _sha256(archive_path)
            and isinstance(rows, list)
        )
        total = 0
        for row in rows if isinstance(rows, list) else []:
            pure = PurePosixPath(str(row.get("path") or "")) if isinstance(row, Mapping) else PurePosixPath()
            target = destination.joinpath(*pure.parts)
            if (
                pure.is_absolute() or ".." in pure.parts or not pure.parts
                or not isinstance(row, Mapping) or not _verified_row_bytes(target, row)
            ):
                valid = False
                break
            total += int(row["bytes"])
        if not valid:
            raise RestoreError(f"analysis evidence destination verification failed: {destination}")
        return {
            "status": "SKIPPED_VERIFIED",
            "destination": str(destination),
            "file_count": len(rows),
            "bytes": total,
            "economic_result": proof.get("economic_result"),
        }
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{tag}.", dir=destination.parent))
    members: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        with tarfile.open(archive_path, "r:*") as archive:
            for member in archive.getmembers():
                pure = PurePosixPath(member.name)
                normalized = str(pure)
                # GNU tar emits an explicit root directory for `tar -C DIR .`.
                # It carries no bytes; descendants remain independently checked.
                if member.isdir() and normalized == ".":
                    continue
                if (
                    pure.is_absolute() or ".." in pure.parts or not pure.parts
                    or member.issym() or member.islnk()
                    or not (member.isfile() or member.isdir())
                    or normalized.casefold() in seen
                ):
                    raise RestoreError(f"unsafe analysis evidence member: {member.name}")
                seen.add(normalized.casefold())
                target = temporary.joinpath(*pure.parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    raise RestoreError(f"unreadable analysis evidence member: {member.name}")
                with source, target.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                members.append({
                    "path": normalized,
                    "bytes": target.stat().st_size,
                    "sha256": _sha256(target),
                })
        result_path = temporary / "result.json"
        if not result_path.is_file() or result_path.is_symlink():
            raise RestoreError("analysis evidence has no safe result.json")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        payload = result.get("payload") if isinstance(result, Mapping) else None
        direct_binding = (
            isinstance(result, Mapping)
            and result.get("status") == "COMPLETE"
            and isinstance(payload, Mapping)
            and _canonical_json_sha256(result) == receipt.get("result_sha256")
            and _canonical_json_sha256(payload) == receipt.get("payload_digest")
        )
        receipt_binding = "DIRECT"
        if not direct_binding and isinstance(result, Mapping) and isinstance(payload, Mapping):
            # Older evidence was archived immediately before annotate_evidence().
            # Reconstruct that exact deterministic mutation and require both
            # receipt hashes, rather than accepting an unexplained mismatch.
            repository = str(receipt.get("_source_repository") or "")
            legacy = json.loads(json.dumps(result))
            legacy_payload = legacy.get("payload")
            internal_ok = (
                result.get("status") == "COMPLETE"
                and isinstance(legacy_payload, dict)
                and result.get("sha256") == _canonical_json_sha256(payload)
                and bool(repository)
            )
            if internal_ok:
                legacy_payload.update({
                    "evidence_release_tag": str(receipt.get("evidence_tag") or ""),
                    "evidence_repository": repository,
                    "durable_persisted": True,
                })
                legacy["sha256"] = _canonical_json_sha256(legacy_payload)
                direct_binding = (
                    _canonical_json_sha256(legacy_payload) == receipt.get("payload_digest")
                    and _canonical_json_sha256(legacy) == receipt.get("result_sha256")
                )
                if direct_binding:
                    receipt_binding = "LEGACY_PREANNOTATION_RECONSTRUCTED"
        if not direct_binding:
            raise RestoreError("analysis result/receipt provenance mismatch")
        net = payload.get("net_usd")
        economic_result = (
            "VALID_NEGATIVE_RETAINED"
            if isinstance(net, (int, float)) and not isinstance(net, bool) and net < 0
            else "VALID_RESULT_RETAINED"
        )
        proof = {
            "schema": "alina.materialized_analysis_evidence.v1",
            "evidence_tag": receipt.get("evidence_tag"),
            "kind": kind,
            "dataset_selection_id": receipt.get("dataset_selection_id"),
            "code_sha": receipt.get("code_sha"),
            "manifest_sha256": receipt.get("manifest_sha256"),
            "archive_sha256": _sha256(archive_path),
            "receipt_binding": receipt_binding,
            "members": sorted(members, key=lambda row: row["path"]),
            "economic_result": economic_result,
            "paper_only": True,
            "real_execution": False,
        }
        (temporary / "CERTIFIED_EVIDENCE.json").write_text(
            json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        temporary.replace(destination)
        return {
            "status": "VERIFIED",
            "destination": str(destination),
            "file_count": len(members),
            "bytes": sum(int(row["bytes"]) for row in members),
            "economic_result": economic_result,
        }
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


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
        try:
            index = read_index(index_path)
        except ValueError as exc:
            # Preserve the canonical restore contract after the shared
            # partition reader detects an invalid identity earlier.
            if "PARTITION_PARITY_DUPLICATE_OR_MISSING_DATASET_ID" in str(exc):
                raise RestoreError("missing or duplicated dataset_id in canonical catalog") from exc
            raise RestoreError(f"invalid canonical DATA_INDEX integrity: {exc}") from exc
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


def _load_replay_ready_plan(
    index_path: Path,
    metrics_path: Path,
) -> tuple[dict[str, tuple[str, str]], dict[str, Any], list[Mapping[str, Any]], dict[tuple[str, str], tuple[int, str]]]:
    """Return the exact SAFE/replayable rows and their immutable outer assets."""
    safe, proof = _load_current_safe_catalog(index_path, metrics_path)
    try:
        index = read_index(index_path)
    except (OSError, ValueError) as exc:
        raise RestoreError(f"invalid canonical DATA_INDEX integrity: {exc}") from exc
    rows: list[Mapping[str, Any]] = []
    required: dict[tuple[str, str], tuple[int, str]] = {}
    logical_bytes = 0
    for row in index["shards"]:
        if str(row.get("dataset_id") or "") not in safe:
            continue
        tag = str(row.get("release_tag") or "")
        member = str(row.get("release_asset") or "")
        outer = str(row.get("release_container_asset") or member)
        if not tag or not member or not outer:
            raise RestoreError("SAFE catalog row has no immutable Release asset")
        zipped = bool(row.get("release_container_asset"))
        expected_size = row.get("release_remote_size") if zipped else row.get("bytes")
        expected_digest = (
            str(row.get("release_remote_digest") or "").removeprefix("sha256:")
            if zipped else str(row.get("sha256") or "")
        ).lower()
        if (
            type(expected_size) is not int or expected_size < 0
            or re.fullmatch(r"[0-9a-f]{64}", expected_digest) is None
        ):
            raise RestoreError("SAFE catalog row has invalid outer asset evidence")
        key = (tag, outer)
        evidence = (expected_size, expected_digest)
        if key in required and required[key] != evidence:
            raise RestoreError("conflicting SAFE catalog evidence for Release asset")
        required[key] = evidence
        rows.append(row)
        logical_bytes += int(row["bytes"])
    proof = dict(proof)
    proof.update({
        "profile": "replay-ready",
        "required_release_assets": len(required),
        "safe_logical_bytes": logical_bytes,
    })
    return safe, proof, rows, required


def _select_replay_ready_releases(
    releases: list[Mapping[str, Any]],
    required: Mapping[tuple[str, str], tuple[int, str]],
) -> list[dict[str, Any]]:
    lookup: dict[tuple[str, str], tuple[Mapping[str, Any], Mapping[str, Any]]] = {}
    for release in releases:
        tag = str(release.get("tag_name") or "")
        for asset in release.get("assets", []):
            if isinstance(asset, Mapping):
                lookup[(tag, str(asset.get("name") or ""))] = (release, asset)
    selected: dict[str, dict[str, Any]] = {}
    for key, (expected_size, expected_digest) in required.items():
        found = lookup.get(key)
        if found is None:
            raise RestoreError(f"SAFE catalog Release asset is missing: {key[0]}/{key[1]}")
        release, asset = found
        if asset.get("size") != expected_size or _expected_digest(asset) != expected_digest:
            raise RestoreError(f"SAFE catalog Release evidence mismatch: {key[0]}/{key[1]}")
        target = selected.setdefault(key[0], {**release, "assets": []})
        target["assets"].append(asset)
    return list(selected.values())


def _prune_verified_unselected_assets(
    releases: list[Mapping[str, Any]],
    selected: set[tuple[str, str]],
    releases_root: Path,
) -> dict[str, Any]:
    """Delete only recoverable cache copies proven identical to GitHub."""
    result: dict[str, Any] = {"assets": 0, "bytes": 0, "failures": []}
    for release in releases:
        tag = str(release.get("tag_name") or "")
        release_dir = releases_root / _safe_component(tag)
        for asset in release.get("assets", []):
            if not isinstance(asset, Mapping):
                continue
            name = str(asset.get("name") or "")
            key = (tag, name)
            # Keep the verified historical inventory: it avoids repeating the
            # 1,000-Release-cap control download on every synchronization.
            if key in selected or name == "RESTORE_INVENTORY.json.gz":
                continue
            target = release_dir / _safe_component(name)
            if target.is_symlink():
                result["failures"].append({
                    "tag": tag, "asset": name, "error": "SYMLINK_NOT_PRUNED",
                })
                continue
            try:
                if _asset_ok(target, asset):
                    size = target.stat().st_size
                    target.unlink()
                    result["assets"] += 1
                    result["bytes"] += size
            except OSError as exc:
                result["failures"].append({
                    "tag": tag, "asset": name, "error": str(exc),
                })
        try:
            if release_dir.is_dir() and not any(release_dir.iterdir()):
                release_dir.rmdir()
        except OSError:
            pass
    return result


def _staged_asset_receipt_path(
    destination: Path, tag: str, name: str,
) -> Path:
    identity = hashlib.sha256(f"{tag}\0{name}".encode("utf-8")).hexdigest()
    return destination / "control" / "staged_assets" / f"{identity}.json"


def _materialized_row_target(destination: Path, row: Mapping[str, Any]) -> Path:
    return (
        destination / "usable" / "shards"
        / _safe_component(str(row["release_tag"]))
        / f"{_safe_component(str(row['dataset_id']))}.jsonl.gz"
    )


def _staged_materialized_asset_ok(
    destination: Path,
    repository: str,
    tag: str,
    asset: Mapping[str, Any],
    rows: list[Mapping[str, Any]],
) -> bool:
    if not rows:
        return False
    path = _staged_asset_receipt_path(destination, tag, str(asset.get("name") or ""))
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    expected_rows = [
        {
            "dataset_id": str(row.get("dataset_id") or ""),
            "bytes": row.get("bytes"),
            "sha256": str(row.get("sha256") or "").lower(),
        }
        for row in rows
    ]
    if (
        not isinstance(receipt, Mapping)
        or receipt.get("schema") != "alina.staged_asset_materialization.v1"
        or receipt.get("release_tag") != tag
        or receipt.get("asset_name") != asset.get("name")
        or receipt.get("asset_bytes") != asset.get("size")
        or receipt.get("asset_sha256") != _expected_digest(asset)
        or receipt.get("source_repository") != repository
        or receipt.get("rows") != expected_rows
    ):
        return False
    return all(
        _verified_row_bytes(_materialized_row_target(destination, row), row)
        for row in rows
    )


def _write_staged_asset_receipt(
    destination: Path,
    repository: str,
    tag: str,
    asset: Mapping[str, Any],
    rows: list[Mapping[str, Any]],
) -> Path:
    if not all(
        _verified_row_bytes(_materialized_row_target(destination, row), row)
        for row in rows
    ):
        raise RestoreError("cannot seal staged asset before every member is verified")
    path = _staged_asset_receipt_path(destination, tag, str(asset.get("name") or ""))
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "alina.staged_asset_materialization.v1",
        "release_tag": tag,
        "asset_name": asset.get("name"),
        "asset_bytes": asset.get("size"),
        "asset_sha256": _expected_digest(asset),
        "rows": [
            {
                "dataset_id": str(row.get("dataset_id") or ""),
                "bytes": row.get("bytes"),
                "sha256": str(row.get("sha256") or "").lower(),
            }
            for row in rows
        ],
        "source_repository": repository,
        "remote_recoverable": True,
    }
    temporary = path.with_suffix(".json.partial")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)
    return path


def _materialize_catalog_safe_shards(
    rows: list[Mapping[str, Any]], releases_root: Path, destination: Path,
    *, prune_stale: bool = True,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "usable_shards": 0, "usable_bytes": 0, "quarantined_shards": 0,
        "quarantined_bytes": 0, "excluded_rows": 0,
        "missing_or_corrupt_rows": 0, "verified_zip_members": 0,
        "skipped_verified_shards": 0, "stale_usable_quarantined": 0,
        "stale_usable_quarantined_bytes": 0,
        "ignored_stale_release_manifests": 0, "failures": [],
    }
    expected: set[Path] = set()
    for row in rows:
        dataset_id = str(row["dataset_id"])
        tag = str(row["release_tag"])
        member = str(row["release_asset"])
        outer = str(row.get("release_container_asset") or member)
        source = releases_root / _safe_component(tag) / _safe_component(outer)
        target_root = destination / "usable" / "shards" / _safe_component(tag)
        if any(path.is_symlink() for path in (
            destination / "usable",
            destination / "usable" / "shards",
            target_root,
        )):
            report["failures"].append({
                "dataset_id": dataset_id,
                "error": "SYMLINKED_SHARD_DIRECTORY",
            })
            continue
        target_root.mkdir(parents=True, exist_ok=True)
        target = target_root / f"{_safe_component(dataset_id)}.jsonl.gz"
        if target.is_symlink():
            report["failures"].append({
                "dataset_id": dataset_id,
                "error": "SYMLINKED_MATERIALIZED_SHARD",
            })
            continue
        expected.add(target)
        if _verified_row_bytes(target, row):
            report["usable_shards"] += 1
            report["usable_bytes"] += int(row["bytes"])
            report["skipped_verified_shards"] += 1
            continue
        tmp = target.with_suffix(target.suffix + ".partial")
        tmp.unlink(missing_ok=True)
        try:
            if row.get("release_container_asset"):
                if Path(member).name != member or not source.is_file():
                    raise RestoreError("unsafe or missing ZIP member")
                with zipfile.ZipFile(source) as archive:
                    matches = [info for info in archive.infolist() if info.filename == member]
                    if len(matches) != 1 or matches[0].file_size != row["bytes"]:
                        raise RestoreError("ZIP member identity/size does not match catalog")
                    with archive.open(matches[0]) as inp, tmp.open("wb") as out:
                        shutil.copyfileobj(inp, out, length=8 * 1024 * 1024)
                report["verified_zip_members"] += 1
            else:
                if not source.is_file():
                    raise RestoreError("Release asset missing")
                try:
                    os.link(source, tmp)
                except OSError:
                    shutil.copy2(source, tmp)
            if not _verified_row_bytes(tmp, row):
                raise RestoreError("shard size/SHA-256 mismatch")
            tmp.replace(target)
            report["usable_shards"] += 1
            report["usable_bytes"] += int(row["bytes"])
        except (OSError, KeyError, zipfile.BadZipFile, RestoreError) as exc:
            tmp.unlink(missing_ok=True)
            report["missing_or_corrupt_rows"] += 1
            report["failures"].append({"dataset_id": dataset_id, "error": str(exc)})
    usable_root = destination / "usable" / "shards"
    if prune_stale and usable_root.is_dir():
        for previous in sorted(usable_root.glob("*/*.jsonl.gz")):
            if previous in expected:
                continue
            try:
                old_size = previous.stat().st_size
                old_digest = _sha256(previous)
                stale_root = destination / "quarantine" / "stale_usable" / previous.parent.name
                stale_root.mkdir(parents=True, exist_ok=True)
                stale = stale_root / f"{previous.name}.{old_digest[:20]}.stale"
                if stale.exists():
                    if _sha256(stale) != old_digest:
                        raise RestoreError("stale quarantine destination collision")
                    previous.unlink()
                else:
                    previous.replace(stale)
                report["stale_usable_quarantined"] += 1
                report["stale_usable_quarantined_bytes"] += old_size
            except (OSError, RestoreError) as exc:
                report["failures"].append({"path": str(previous), "error": str(exc)})
    return report


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
        "usable_bytes": 0,
        "quarantined_shards": 0,
        "quarantined_bytes": 0,
        "excluded_rows": 0,
        "missing_or_corrupt_rows": 0,
        "verified_zip_members": 0,
        "skipped_verified_shards": 0,
        "stale_usable_quarantined": 0,
        "stale_usable_quarantined_bytes": 0,
        "ignored_stale_release_manifests": 0,
        "failures": [],
    }
    expected_usable: set[Path] = set()
    restored_safe_ids: set[str] = set()
    diagnostics = destination / "diagnostics" / "run_manifests"
    for manifest_path in sorted(releases_root.glob("*/RUN_MANIFEST.json")):
        release_tag = manifest_path.parent.name
        if allowed_release_dirs is not None and release_tag not in allowed_release_dirs:
            report["ignored_stale_release_manifests"] += 1
            continue
        if manifest_path.is_symlink():
            report["failures"].append({
                "manifest": str(manifest_path),
                "error": "SYMLINKED_RUN_MANIFEST",
            })
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
            if any(part.is_symlink() for part in (
                target_root, target_root.parent, target_root.parent.parent
            )):
                report["failures"].append({
                    "dataset_id": dataset_id,
                    "error": "SYMLINKED_SHARD_DIRECTORY",
                })
                continue
            target_root.mkdir(parents=True, exist_ok=True)
            target = target_root / f"{_safe_component(dataset_id)}.jsonl.gz"
            if target.is_symlink():
                report["failures"].append({
                    "dataset_id": dataset_id,
                    "error": "SYMLINKED_MATERIALIZED_SHARD",
                })
                continue
            if _verified_row_bytes(target, row):
                # Repeated restores must not rewrite already-verified shards.
                if safe:
                    expected_usable.add(target)
                    restored_safe_ids.add(dataset_id)
                    report["usable_shards"] += 1
                    report["usable_bytes"] += int(row["bytes"])
                else:
                    report["quarantined_shards"] += 1
                    report["quarantined_bytes"] += int(row["bytes"])
                report["skipped_verified_shards"] += 1
                continue
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
                restored_safe_ids.add(dataset_id)
                report["usable_shards"] += 1
                report["usable_bytes"] += int(row["bytes"])
            else:
                report["quarantined_shards"] += 1
                report["quarantined_bytes"] += int(row["bytes"])

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
                old_size = previous.stat().st_size
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
                report["stale_usable_quarantined_bytes"] += old_size
            except (OSError, RestoreError) as exc:
                report["failures"].append({
                    "path": str(previous),
                    "error": f"STALE_USABLE_QUARANTINE_FAILED:{exc}",
                })
    if catalog_safe is not None:
        missing = sorted(set(catalog_safe) - restored_safe_ids)
        report["missing_catalog_safe_shards"] = len(missing)
        report["missing_catalog_safe_sample"] = missing[:50]
        if missing:
            report["failures"].append({
                "error": "CATALOG_SAFE_SHARDS_NOT_RESTORED",
                "count": len(missing),
                "sample": missing[:10],
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
    # Snapshot paths must be portable and may never overwrite Git internals.
    if "\\" in relative or ":" in relative:
        raise RestoreError(f"unsafe snapshot path: {relative!r}")
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts or not rel.parts:
        raise RestoreError(f"unsafe snapshot path: {relative!r}")
    if any(part.casefold() == ".git" for part in rel.parts):
        raise RestoreError("local snapshot may never write inside .git")
    root = workspace.resolve()
    candidate = root
    for part in rel.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise RestoreError(f"symlinked snapshot target: {relative!r}")
    target = candidate.resolve()
    if root != target and root not in target.parents:
        raise RestoreError(f"snapshot path escapes workspace: {relative!r}")
    return target


def _tracked_clone_paths(workspace: Path) -> set[str]:
    """Fail closed if an ignored-file snapshot could overwrite Git's HEAD."""
    root = workspace.resolve()
    if not (root / ".git").exists():
        return set()
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            capture_output=True, check=False,
        )
    except OSError as exc:
        raise RestoreError("cannot validate Git-tracked snapshot targets") from exc
    if result.returncode != 0:
        raise RestoreError("cannot enumerate Git-tracked snapshot targets")
    return {
        os.fsdecode(path).replace("\\", "/").casefold()
        for path in result.stdout.split(b"\x00") if path
    }


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
    *,
    allowed_release_dirs: set[str] | None = None,
    repository: str | None = None,
    refuse_existing_changes: bool = False,
) -> dict[str, Any] | None:
    """Restore a verified current-inventory snapshot, never a stale cached Release."""
    candidates: list[tuple[str, Path, Mapping[str, Any]]] = []
    for directory in releases_root.glob("alina-local-snapshot-*"):
        if allowed_release_dirs is not None and directory.name not in allowed_release_dirs:
            continue
        if directory.is_symlink() or not directory.is_dir():
            raise RestoreError("unsafe local snapshot Release directory")
        index_path = directory / "ALINA_LOCAL_SNAPSHOT_INDEX.json"
        if index_path.is_symlink():
            raise RestoreError("unsafe local snapshot index symlink")
        if not index_path.is_file():
            # An incomplete current Release must not cause silent restoration
            # of a previous local snapshot.
            raise RestoreError(f"missing current local snapshot index: {directory.name}")
        try:
            payload = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RestoreError(f"invalid current local snapshot index: {directory.name}") from exc
        if not isinstance(payload, Mapping) or payload.get("schema") != "alina.local_snapshot.v1":
            raise RestoreError(f"invalid current local snapshot schema: {directory.name}")
        if repository is not None and payload.get("repository") != repository:
            raise RestoreError("local snapshot source repository mismatch")
        if payload.get("tag") not in (None, directory.name):
            raise RestoreError("local snapshot index Release tag mismatch")
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
    chunk_casefold_names: set[str] = set()
    for row in chunk_rows:
        if not isinstance(row, Mapping):
            raise RestoreError("invalid local snapshot chunk row")
        name = str(row.get("name") or "")
        expected_sha = str(row.get("sha256") or "").lower()
        expected_size = row.get("bytes")
        safe_name = _safe_component(name) if name else ""
        if (not name or safe_name.casefold() in chunk_casefold_names
                or type(expected_size) is not int or expected_size < 0
                or re.fullmatch(r"[0-9a-f]{64}", expected_sha) is None):
            raise RestoreError(f"invalid or duplicate local snapshot chunk identity: {name}")
        path = directory / safe_name
        if path.is_symlink() or not path.is_file() or path.stat().st_size != expected_size:
            raise RestoreError(f"missing local snapshot chunk: {name}")
        if _sha256(path) != expected_sha:
            raise RestoreError(f"local snapshot chunk sha256 mismatch: {name}")
        chunks[name] = path
        chunk_casefold_names.add(safe_name.casefold())

    pending_materialization = 0
    seen_workspace_targets: set[str] = set()
    tracked_paths = _tracked_clone_paths(workspace)
    for row in file_rows:
        if not isinstance(row, Mapping):
            raise RestoreError("invalid local snapshot file row")
        relative = str(row.get("path") or "")
        expected_sha = str(row.get("sha256") or "").lower()
        expected_size = int(row.get("bytes") or 0)
        if not relative or len(expected_sha) != 64 or expected_size < 0:
            raise RestoreError("invalid local snapshot file identity")
        target = _safe_workspace_target(workspace, relative)
        # Duplicate or case-only-different paths would overwrite snapshot
        # evidence on Windows. Refuse the entire snapshot before any writes.
        target_key = target.relative_to(workspace.resolve()).as_posix().casefold()
        if not target_key or target_key == "." or target_key in seen_workspace_targets:
            raise RestoreError(f"duplicate or unsafe local snapshot target: {relative}")
        if target_key in tracked_paths:
            raise RestoreError(f"local snapshot would overwrite tracked Git file: {relative}")
        seen_workspace_targets.add(target_key)
        matches_snapshot = (
            not target.is_symlink()
            and target.is_file()
            and target.stat().st_size == expected_size
            and _sha256(target) == expected_sha
        )
        if not matches_snapshot:
            # A local synchronization must never overwrite unsaved ignored
            # workspace files. Only the explicit --materialize-local-snapshot
            # mode can replace them after the user chooses that behavior.
            if refuse_existing_changes and (target.exists() or target.is_symlink()):
                raise RestoreError(
                    f"local snapshot conflicts with existing file: {relative}"
                )
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
    preflight_only: bool = False,
    recover_verifiable: bool = False,
    optional_local_snapshot: bool = False,
    profile: str = "full-archive",
    prune_unselected: bool = False,
) -> dict[str, Any]:
    if profile not in {"full-archive", "replay-ready"}:
        raise RestoreError(f"unknown restore profile: {profile}")
    catalog_safe: dict[str, tuple[str, str]] | None = None
    catalog_verification: dict[str, Any] | None = None
    working_set: dict[str, Any] | None = None
    replay_rows: list[Mapping[str, Any]] = []
    replay_required: dict[tuple[str, str], tuple[int, str]] = {}
    if catalog_path is not None:
        if metrics_path is None:
            raise RestoreError("canonical DATA_METRICS is required with DATA_INDEX")
        if profile == "replay-ready":
            (catalog_safe, catalog_verification, replay_rows,
             replay_required) = _load_replay_ready_plan(catalog_path, metrics_path)
        else:
            catalog_safe, catalog_verification = _load_current_safe_catalog(
                catalog_path, metrics_path
            )
    elif profile == "replay-ready":
        raise RestoreError("replay-ready profile requires the canonical catalog")
    releases_root = destination / "releases"
    if releases_root.is_symlink():
        raise RestoreError("symlinked Release storage directory")
    releases_root.mkdir(parents=True, exist_ok=True)
    releases = list(iter_releases(
        repository, token=token, allow_incomplete=recover_verifiable,
        inventory_cache_root=releases_root,
    ))
    # Never start transferring data with a partial/malformed source inventory.
    seen_tags: set[str] = set()
    seen_windows_release_dirs: set[str] = set()
    unverified_source_assets: list[dict[str, Any]] = []
    unsafe_manifest_release_dirs: set[str] = set()
    for release in releases:
        tag = release.get("tag_name")
        assets = release.get("assets")
        if not isinstance(tag, str) or not tag or tag in seen_tags:
            raise RestoreError("duplicate or missing Release tag in source inventory")
        if not isinstance(assets, list):
            raise RestoreError(f"missing asset list for Release {tag}")
        seen_tags.add(tag)
        # Release and asset names are case-insensitive on Windows. Reject
        # ambiguous destinations before writing even one Release byte.
        windows_release_dir = _safe_component(tag).casefold()
        if windows_release_dir in seen_windows_release_dirs:
            raise RestoreError("case-insensitive Release directory collision")
        seen_windows_release_dirs.add(windows_release_dir)
        # Data-only Releases are intentional in oversized Dataset runs.
        # Preserve every SHA-verified byte and classify via canonical manifest.
        seen_names: set[str] = set()
        seen_windows_asset_names: set[str] = set()
        for asset in assets:
            if not isinstance(asset, Mapping):
                raise RestoreError(f"invalid asset record in Release {tag}")
            name = asset.get("name")
            if not isinstance(name, str) or not name or name in seen_names:
                raise RestoreError(f"duplicate or missing asset name in Release {tag}")
            if (not _source_asset_eligible(asset, salvage=recover_verifiable)):
                if not recover_verifiable:
                    raise RestoreError(f"unverifiable Release asset: {tag}/{name}")
                unverified_source_assets.append({
                    "release_tag": tag, "asset_id": asset.get("id"),
                    "name": name, "size_bytes": asset.get("size"),
                    "state": asset.get("state"),
                    "reason": "UNVERIFIABLE_SOURCE_ASSET",
                })
                # Never promote any asset from a Release with unresolved
                # source data into replay-usable material.
                unsafe_manifest_release_dirs.add(_safe_component(tag))
            if type(asset.get("size")) is not int or asset["size"] < 0:
                raise RestoreError(f"missing/invalid size for {tag}/{name}")
            if not isinstance(asset.get("browser_download_url"), str) or not asset["browser_download_url"].startswith("https://"):
                raise RestoreError(f"invalid download URL for {tag}/{name}")
            seen_names.add(name)
            windows_asset_name = _safe_component(name).casefold()
            if windows_asset_name in seen_windows_asset_names:
                raise RestoreError(f"case-insensitive asset name collision in Release {tag}")
            seen_windows_asset_names.add(windows_asset_name)

    # Bind the report to the exact, paginated immutable inventory read at
    # the start. Later Releases published during COLLECT are not certified.
    source_inventory = [
        {
            "release_id": release.get("id"),
            "tag": release["tag_name"],
            "assets": [
                {
                    "asset_id": asset.get("id"),
                    "name": asset["name"],
                    "size_bytes": asset["size"],
                    "sha256": _expected_digest(asset),
                    "state": asset.get("state"),
                }
                for asset in release["assets"]
            ],
        }
        for release in releases
    ]
    source_inventory_sha256 = hashlib.sha256(
        json.dumps(source_inventory, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    # Every published byte has an explicit, immutable source identity and size.
    # Prove parity at byte level as well as asset count. No floating estimates.
    full_releases = releases
    full_archive_release_count = len(full_releases)
    full_archive_asset_count = sum(len(release["assets"]) for release in releases)
    full_archive_asset_bytes = sum(
        int(asset["size"]) for release in full_releases for asset in release["assets"]
    )
    selected_keys: set[tuple[str, str]] = set()
    if profile == "replay-ready":
        assert catalog_path is not None
        working_set = build_certified_working_set(
            full_releases,
            raw_required=replay_required,
            receipts_root=catalog_path.parent / "receipts",
            campaigns_root=catalog_path.parent / "campaigns",
            repository=repository,
        )
        replay_required = dict(working_set["required_assets"])
        releases = _select_replay_ready_releases(full_releases, replay_required)
        selected_keys = {
            (str(release["tag_name"]), str(asset["name"]))
            for release in releases for asset in release["assets"]
        }
        unverified_source_assets = [
            row for row in unverified_source_assets
            if (str(row["release_tag"]), str(row["name"])) in selected_keys
        ]
    raw_rows_by_asset: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    if profile == "replay-ready":
        for row in replay_rows:
            key = (
                str(row.get("release_tag") or ""),
                str(row.get("release_container_asset") or row.get("release_asset") or ""),
            )
            raw_rows_by_asset.setdefault(key, []).append(row)
    source_asset_bytes = sum(
        int(asset["size"]) for release in releases for asset in release["assets"]
    )
    unverified_source_bytes = sum(
        int(row["size_bytes"]) for row in unverified_source_assets
    )
    prune_result: dict[str, Any] = {"assets": 0, "bytes": 0, "failures": []}
    if profile == "replay-ready" and prune_unselected and not preflight_only:
        prune_result = _prune_verified_unselected_assets(
            full_releases, selected_keys, releases_root,
        )
    clone_sources = _clone_lfs_sources(clone_root, repository, releases)

    # Old cached Releases must never be treated as part of the current GitHub
    # inventory or silently reintroduce formerly SAFE local materializations.
    allowed_release_dirs = {_safe_component(tag) for tag in seen_tags}
    if len(allowed_release_dirs) != len(seen_tags):
        raise RestoreError("Release tags collide after path normalization")

    pending_download_bytes = 0
    pending_retained_download_bytes = 0
    peak_staged_asset_bytes = 0
    staging_releases_root = destination / ".staging" / "releases"
    for release in releases:
        tag = str(release.get("tag_name") or "")
        if not tag:
            continue
        release_dir = releases_root / _safe_component(tag)
        if release_dir.is_symlink():
            raise RestoreError(f"symlinked Release directory: {tag}")
        assets = release.get("assets")
        for asset in assets if isinstance(assets, list) else []:
            if not isinstance(asset, Mapping):
                continue
            name = str(asset.get("name") or "")
            if not name:
                continue
            target = release_dir / _safe_component(name)
            partial = target.with_suffix(target.suffix + ".partial")
            if target.is_symlink() or partial.is_symlink():
                raise RestoreError(f"symlinked Release asset during preflight: {tag}/{name}")
            if recover_verifiable and (
                not _source_asset_eligible(asset, salvage=recover_verifiable)
            ):
                continue
            if not _asset_ok(target, asset):
                raw_rows = raw_rows_by_asset.get((tag, name), [])
                if raw_rows and _staged_materialized_asset_ok(
                    destination, repository, tag, asset, raw_rows
                ):
                    continue
                source = clone_sources.get((tag, name))
                # A verified LFS hardlink occupies no new payload space on
                # the same volume. A cross-volume copy still needs capacity.
                if source is not None and source.stat().st_dev == releases_root.stat().st_dev:
                    continue
                expected_size = max(0, int(asset.get("size") or 0))
                if raw_rows:
                    staged_target = (
                        staging_releases_root / _safe_component(tag)
                        / _safe_component(name)
                    )
                    partial = staged_target.with_suffix(staged_target.suffix + ".partial")
                partial_size = partial.stat().st_size if partial.is_file() else 0
                remaining = max(0, expected_size - partial_size)
                pending_download_bytes += remaining
                if raw_rows:
                    peak_staged_asset_bytes = max(peak_staged_asset_bytes, remaining)
                else:
                    pending_retained_download_bytes += remaining

    pending_materialization_bytes = 0
    if profile == "replay-ready":
        for row in replay_rows:
            if not row.get("release_container_asset"):
                continue
            target = (
                destination / "usable" / "shards"
                / _safe_component(str(row["release_tag"]))
                / f"{_safe_component(str(row['dataset_id']))}.jsonl.gz"
            )
            if not _verified_row_bytes(target, row):
                pending_materialization_bytes += int(row["bytes"])

    free_destination = shutil.disk_usage(destination).free
    safety_margin = 1024 * 1024 * 1024
    required_free_destination_bytes = (
        pending_retained_download_bytes
        + peak_staged_asset_bytes
        + pending_materialization_bytes
        + safety_margin
    )
    enough_disk = required_free_destination_bytes <= free_destination
    if preflight_only:
        # Planning never downloads assets and is not a recovery certificate.
        plan = {
            "schema": "alina.restore_preflight.v1",
            "status": (
                "PREFLIGHT_INSUFFICIENT_DISK" if not enough_disk
                else "PREFLIGHT_SOURCE_UNVERIFIABLE" if unverified_source_assets
                else "PREFLIGHT_WORKING_SET_INCOMPLETE"
                if working_set is not None and working_set["failures"]
                else "PREFLIGHT_READY_NOT_RESTORED"
            ),
            "repository": repository,
            "profile": profile,
            "source_inventory_sha256": source_inventory_sha256,
            "release_count": len(releases),
            "asset_count": sum(len(release["assets"]) for release in releases),
            "source_asset_bytes": source_asset_bytes,
            "full_archive_release_count": full_archive_release_count,
            "full_archive_asset_count": full_archive_asset_count,
            "full_archive_asset_bytes": full_archive_asset_bytes,
            "excluded_full_archive_bytes": full_archive_asset_bytes - source_asset_bytes,
            "prune_unselected_enabled": bool(prune_unselected),
            "pruned_unselected_assets": 0,
            "pruned_unselected_bytes": 0,
            "unverified_source_bytes": unverified_source_bytes,
            "unverified_source_asset_count": len(unverified_source_assets),
            "unverified_source_assets_sample": unverified_source_assets[:50],
            "pending_download_bytes": pending_download_bytes,
            "pending_retained_download_bytes": pending_retained_download_bytes,
            "peak_staged_asset_bytes": peak_staged_asset_bytes,
            "pending_materialization_bytes": pending_materialization_bytes,
            "required_free_destination_bytes": required_free_destination_bytes,
            "free_destination_bytes": free_destination,
            "safety_margin_bytes": safety_margin,
            "enough_disk_for_release_assets": enough_disk,
            "certified_working_set": (
                {
                    **{key: value for key, value in working_set.items()
                       if key != "required_assets"},
                    "required_assets": [
                        {"release_tag": tag, "asset_name": name,
                         "bytes": identity[0], "sha256": identity[1]}
                        for (tag, name), identity in sorted(
                            working_set["required_assets"].items()
                        )
                    ],
                }
                if working_set is not None else None
            ),
            "note": (
                "No payload assets downloaded; the SHA-256-verified restore "
                "inventory control asset is cached and reusable. SAFE shard "
                "materialization and optional local snapshots require additional "
                "disk space."
            ),
            "read_only": True,
            "real_execution": False,
        }
        plan_path = destination / "RESTORE_PREFLIGHT.json"
        plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True), encoding="utf-8")
        plan["report"] = str(plan_path)
        return plan
    if not enough_disk:
        raise RestoreError(
            "insufficient disk space for complete GitHub Release restore: "
            f"need_at_least={required_free_destination_bytes} "
            f"free={free_destination}"
        )

    report: dict[str, Any] = {
        "schema": "alina.full_restore_report.v1",
        "repository": repository,
        "profile": profile,
        "source_inventory_sha256": source_inventory_sha256,
        "destination": str(destination),
        "release_count": 0,
        "asset_count": 0,
        "source_asset_bytes": source_asset_bytes,
        "full_archive_release_count": full_archive_release_count,
        "full_archive_asset_count": full_archive_asset_count,
        "full_archive_asset_bytes": full_archive_asset_bytes,
        "excluded_full_archive_bytes": full_archive_asset_bytes - source_asset_bytes,
        "prune_unselected_enabled": bool(prune_unselected),
        "pruned_unselected_assets": prune_result["assets"],
        "pruned_unselected_bytes": prune_result["bytes"],
        "prune_failures": prune_result["failures"],
        "unverified_source_bytes": unverified_source_bytes,
        "verified_asset_bytes": 0,
        "verified_asset_count": 0,
        "failed_verification_source_bytes": 0,
        "retained_unverified_local_bytes": 0,
        "downloaded": 0,
        "resumed_verified": 0,
        "skipped_verified": 0,
        "lfs_reused_verified": 0,
        "pending_download_bytes_at_start": pending_download_bytes,
        "pending_retained_download_bytes_at_start": pending_retained_download_bytes,
        "peak_staged_asset_bytes_at_start": peak_staged_asset_bytes,
        "pending_materialization_bytes_at_start": pending_materialization_bytes,
        "required_free_destination_bytes_at_start": required_free_destination_bytes,
        "free_destination_bytes_at_start": free_destination,
        "failures": [],
        "releases": [],
        "read_only": True,
        "real_execution": False,
        "catalog_verification": catalog_verification,
        "certified_working_set": (
            {
                **{key: value for key, value in working_set.items()
                   if key != "required_assets"},
                "required_assets": [
                    {"release_tag": tag, "asset_name": name,
                     "bytes": identity[0], "sha256": identity[1]}
                    for (tag, name), identity in sorted(
                        working_set["required_assets"].items()
                    )
                ],
            }
            if working_set is not None else None
        ),
        "unverified_source_asset_count": len(unverified_source_assets),
        "unverified_source_assets_sample": unverified_source_assets[:50],
    }

    for release in releases:
        tag = str(release.get("tag_name") or "")
        if not tag:
            continue
        safe_tag = _safe_component(tag)
        release_dir = releases_root / safe_tag
        if release_dir.is_symlink():
            raise RestoreError(f"symlinked Release directory: {tag}")
        assets = release.get("assets")
        assets = assets if isinstance(assets, list) else []
        row = {
            "tag": tag,
            "release_id": release.get("id"),
            "asset_count": len(assets),
            "assets": [],
        }
        report["release_count"] += 1
        for asset in assets:
            if not isinstance(asset, Mapping):
                continue
            report["asset_count"] += 1
            identity = {
                "source_repository": repository,
                "release_tag": tag,
                "release_id": release.get("id"),
                "asset_id": asset.get("id"),
                "size_bytes": asset.get("size"),
                "sha256": _expected_digest(asset),
                "expected_sha256": _expected_digest(asset),
            }
            if recover_verifiable and (
                not _source_asset_eligible(asset, salvage=recover_verifiable)
            ):
                reason = "UNVERIFIABLE_SOURCE_ASSET"
                report["failures"].append({
                    "tag": tag, "asset": asset.get("name"), "error": reason,
                })
                row["assets"].append({
                    **identity, "name": asset.get("name"),
                    "status": "FAIL", "verification_status": "UNVERIFIABLE",
                    "downloaded_size_bytes": 0, "calculated_sha256": None,
                    "destination": None, "error": reason,
                })
                continue
            try:
                asset_name = str(asset.get("name") or "")
                raw_rows = raw_rows_by_asset.get((tag, asset_name), [])
                canonical_target = release_dir / _safe_component(asset_name)
                if raw_rows and _staged_materialized_asset_ok(
                    destination, repository, tag, asset, raw_rows
                ):
                    result = {
                        "name": asset_name,
                        "status": "MATERIALIZED_VERIFIED",
                        "verification_status": "VERIFIED",
                        "downloaded_size_bytes": int(asset["size"]),
                        "calculated_sha256": _expected_digest(asset),
                        "destination": str(_staged_asset_receipt_path(destination, tag, asset_name)),
                    }
                else:
                    use_staging = bool(raw_rows) and not _asset_ok(canonical_target, asset)
                    asset_root = staging_releases_root if use_staging else releases_root
                    asset_dir = asset_root / safe_tag
                    result = download_asset(
                        asset, asset_dir, token=token,
                        clone_candidate=clone_sources.get((tag, asset_name)),
                    )
                    if use_staging:
                        staged_classification = _materialize_catalog_safe_shards(
                            raw_rows, staging_releases_root, destination,
                            prune_stale=False,
                        )
                        if staged_classification["failures"]:
                            raise RestoreError(
                                "staged SAFE materialization failed: "
                                + str(staged_classification["failures"][:3])
                            )
                        receipt_path = _write_staged_asset_receipt(
                            destination, repository, tag, asset, raw_rows
                        )
                        staged_target = asset_dir / _safe_component(asset_name)
                        staged_target.unlink()
                        result = {
                            **result,
                            "status": "STAGED_MATERIALIZED_VERIFIED",
                            "destination": str(receipt_path),
                        }
                row["assets"].append({**identity, **result})
                report["verified_asset_bytes"] += int(asset["size"])
                report["verified_asset_count"] += 1
                if result["status"] == "DOWNLOADED_VERIFIED":
                    report["downloaded"] += 1
                elif result["status"] == "RESUMED_VERIFIED":
                    report["resumed_verified"] += 1
                elif result["status"] == "LFS_REUSED_VERIFIED":
                    report["lfs_reused_verified"] += 1
                else:
                    report["skipped_verified"] += 1
            except RestoreError as exc:
                failed_target = release_dir / _safe_component(
                    str(asset.get("name") or "")
                )
                failed_partial = failed_target.with_suffix(
                    failed_target.suffix + ".partial"
                )
                retained_unverified_bytes = sum(
                    candidate.stat().st_size
                    for candidate in (failed_target, failed_partial)
                    if candidate.is_file() and not candidate.is_symlink()
                )
                report["failed_verification_source_bytes"] += int(asset["size"])
                report["retained_unverified_local_bytes"] += retained_unverified_bytes
                failure = {"tag": tag, "asset": asset.get("name"), "error": str(exc)}
                report["failures"].append(failure)
                row["assets"].append({
                    **identity, "name": asset.get("name"),
                    "status": "FAIL", "verification_status": "FAILED",
                    "downloaded_size_bytes": retained_unverified_bytes,
                    "calculated_sha256": None,
                    "destination": str(failed_target),
                    "error": str(exc),
                })
        report["releases"].append(row)

    # Interrupted publications remain archived, but cannot claim a fully
    # qualified restore without a canonical manifest naming their data part.
    claimed_tags = _claimed_data_release_tags(releases_root, allowed_release_dirs)
    unclaimed = [] if profile == "replay-ready" else sorted(
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
    report["run_manifest_checks"] = (
        [] if profile == "replay-ready" else _verify_run_manifests(
            releases_root,
            allowed_release_dirs=allowed_release_dirs - unsafe_manifest_release_dirs,
        )
    )
    report["verification_failures"] = sum(
        1 for row in report["run_manifest_checks"] if row.get("status") != "OK"
    )
    report["classification"] = (
        _materialize_catalog_safe_shards(replay_rows, releases_root, destination)
        if profile == "replay-ready"
        else _materialize_classified_shards(
            repository, releases_root, destination, catalog_safe=catalog_safe,
            allowed_release_dirs=allowed_release_dirs - unsafe_manifest_release_dirs,
        )
    )
    report["analysis_evidence"] = {
        "required": 0,
        "materialized": 0,
        "verified_files": 0,
        "verified_bytes": 0,
        "results": [],
        "failures": [],
    }
    if working_set is not None:
        entries = working_set.get("analysis_evidence")
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, Mapping):
                continue
            receipt = entry.get("receipt")
            assets = entry.get("assets")
            if not isinstance(receipt, Mapping) or not isinstance(assets, list):
                continue
            report["analysis_evidence"]["required"] += 1
            if len(assets) != 1 or not str(assets[0].get("name") or "").endswith(".tgz"):
                failure = {
                    "evidence_tag": entry.get("evidence_tag"),
                    "error": "analysis evidence Release must contain exactly one .tgz asset",
                }
                report["analysis_evidence"]["failures"].append(failure)
                report["failures"].append({"stage": "analysis_evidence", **failure})
                continue
            archive = (
                releases_root / _safe_component(str(entry["evidence_tag"]))
                / _safe_component(str(assets[0]["name"]))
            )
            try:
                result = materialize_analysis_evidence(
                    archive, receipt, destination / "usable"
                )
                report["analysis_evidence"]["results"].append(result)
                report["analysis_evidence"]["materialized"] += 1
                report["analysis_evidence"]["verified_files"] += int(result["file_count"])
                report["analysis_evidence"]["verified_bytes"] += int(result["bytes"])
            except (OSError, ValueError, TypeError, json.JSONDecodeError, tarfile.TarError, RestoreError) as exc:
                failure = {"evidence_tag": entry.get("evidence_tag"), "error": str(exc)}
                report["analysis_evidence"]["failures"].append(failure)
                report["failures"].append({"stage": "analysis_evidence", **failure})
    report["expected_assets"] = sum(len(release["assets"]) for release in releases)
    report["all_source_assets_accounted_for"] = (
        report["asset_count"] == report["expected_assets"]
        and report["downloaded"]
        + report["resumed_verified"]
        + report["lfs_reused_verified"]
        + report["skipped_verified"]
        == report["expected_assets"]
        and not report["failures"]
        and report["verified_asset_count"] == report["expected_assets"]
        and report["verified_asset_bytes"] == report["source_asset_bytes"]
    )
    report["missing_asset_bytes"] = (
        report["source_asset_bytes"] - report["verified_asset_bytes"]
    )
    report["source_byte_parity"] = (
        report["all_source_assets_accounted_for"]
        and report["missing_asset_bytes"] == 0
        and report["unverified_source_asset_count"] == 0
    )
    report["local_snapshot"] = None
    if workspace is not None:
        try:
            report["local_snapshot"] = materialize_latest_local_snapshot(
                releases_root, workspace,
                allowed_release_dirs=allowed_release_dirs - unsafe_manifest_release_dirs,
                repository=repository,
                refuse_existing_changes=optional_local_snapshot,
            )
            if report["local_snapshot"] is None:
                if optional_local_snapshot:
                    # No local-only source was ever published in this inventory:
                    # there are no published snapshot bytes to reconstruct.
                    report["local_snapshot"] = {
                        "status": "NOT_PUBLISHED", "restored_files": 0,
                    }
                else:
                    raise RestoreError("no verified local snapshot available to materialize")
        except (RestoreError, OSError, ValueError, TypeError) as exc:
            # Preserve the verified Release inventory and a failure checkpoint.
            report["local_snapshot"] = {"status": "FAIL", "error": str(exc)}
            report["failures"].append({
                "stage": "local_snapshot", "error": str(exc),
            })
    complete = (
        report["source_byte_parity"]
        and report["all_source_assets_accounted_for"]
        and not report["failures"]
        and not report["verification_failures"]
        and not report["classification"]["failures"]
        and not report["unclaimed_dataset_release_count"]
        and (working_set is None or not working_set["failures"])
        and report["analysis_evidence"]["materialized"]
        == report["analysis_evidence"]["required"]
    )
    report["status"] = (
        "REPLAY_READY_COMPLETE" if complete and profile == "replay-ready"
        else "RESTORE_COMPLETE" if complete and catalog_verification is not None
        else "ASSETS_VERIFIED_ONLY" if complete
        else "RESTORE_INCOMPLETE"
    )
    snapshot = report.get("local_snapshot")
    snapshot_reconstructed = (
        isinstance(snapshot, Mapping)
        and "file_count" in snapshot
        and snapshot.get("status") not in {"FAIL", "NOT_PUBLISHED"}
    )
    report.update({
        "assets_verified": bool(report["source_byte_parity"]),
        "restore_complete": report["status"] in {"RESTORE_COMPLETE", "REPLAY_READY_COMPLETE"},
        "replay_ready_complete": report["status"] == "REPLAY_READY_COMPLETE",
        "full_archive_complete": report["status"] == "RESTORE_COMPLETE",
        "published_volume_bytes": report["source_asset_bytes"],
        "restored_volume_bytes": report["verified_asset_bytes"],
        "verified_volume_bytes": report["verified_asset_bytes"],
        "missing_volume_bytes": report["missing_asset_bytes"],
        "corrupt_volume_bytes": report["retained_unverified_local_bytes"],
        "non_verifiable_volume_bytes": report["unverified_source_bytes"],
        "quarantine_volume_bytes": (
            report["classification"]["quarantined_bytes"]
            + report["classification"]["stale_usable_quarantined_bytes"]
        ),
        "snapshots_reconstructed": 1 if snapshot_reconstructed else 0,
        "snapshot_files_reconstructed": (
            int(snapshot.get("restored_files", 0)) if snapshot_reconstructed else 0
        ),
        "snapshot_files_verified": (
            int(snapshot.get("restored_files", 0))
            + int(snapshot.get("skipped_verified_files", 0))
            if snapshot_reconstructed else 0
        ),
        "source_destination_match": bool(complete),
    })
    report_path = destination / "RESTORE_REPORT.json"
    report_partial = report_path.with_name(report_path.name + ".partial")
    report_partial.write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    report_partial.replace(report_path)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Restore every canonical Alina GitHub Release asset after cloning the repository."
    )
    profile_group = parser.add_mutually_exclusive_group(required=True)
    profile_group.add_argument(
        "--replay-ready", action="store_true",
        help="restore only catalog-bound SAFE/replayable data",
    )
    profile_group.add_argument(
        "--everything", action="store_true",
        help="restore the complete historical Release archive",
    )
    parser.add_argument(
        "--recover-verifiable", action="store_true",
        help="salvage valid SHA-256 assets despite incomplete Releases; never claim success",
    )
    parser.add_argument(
        "--preflight-only", action="store_true",
        help="inventory Releases and check space without downloading assets",
    )
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--destination", default="runtime/recovery/full")
    parser.add_argument("--clone-root", default=None,
                        help="legacy clone-payload compatibility only; disabled by default")
    parser.add_argument("--catalog", default="catalog/DATA_INDEX.json",
                        help="canonical index required to certify usable restored shards")
    parser.add_argument("--metrics", default="catalog/DATA_METRICS.json",
                        help="SHA-bound canonical metrics required for catalog verification")
    parser.add_argument(
        "--workspace",
        default=".",
        help="fresh clone root used only with --materialize-local-snapshot",
    )
    snapshot_group = parser.add_mutually_exclusive_group()
    snapshot_group.add_argument(
        "--materialize-local-snapshot",
        action="store_true",
        help="require and restore the latest published verified workspace snapshot",
    )
    snapshot_group.add_argument(
        "--materialize-available-local-snapshot",
        action="store_true",
        help="restore the latest published snapshot when available; refuse corrupt snapshots",
    )
    args = parser.parse_args(argv)

    token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    destination = Path(args.destination).resolve()
    try:
        report = restore_everything(
            args.repository,
            destination,
            token=token,
            catalog_path=Path(args.catalog).resolve(),
            metrics_path=Path(args.metrics).resolve(),
            clone_root=Path(args.clone_root).resolve() if args.clone_root else None,
            preflight_only=args.preflight_only,
            recover_verifiable=args.recover_verifiable,
            optional_local_snapshot=args.materialize_available_local_snapshot,
            profile="replay-ready" if args.replay_ready else "full-archive",
            # Preserve every existing cached source by default; never delete
            # local recovery evidence as a side effect of SAFE synchronization.
            prune_unselected=False,
            workspace=(
                Path(args.workspace).resolve()
                if args.materialize_local_snapshot or args.materialize_available_local_snapshot
                else None
            ),
        )
    except (RestoreError, OSError, ValueError, TypeError, zipfile.BadZipFile) as exc:
        # Expected filesystem, catalog and archive failures must never produce
        # a misleading success code or an unhandled Windows traceback.
        print(f"ALINA_RESTORE_FAIL: {exc}", file=sys.stderr)
        return 2

    if args.preflight_only:
        # The full, SHA-bound asset plan remains in RESTORE_PREFLIGHT.json.
        # Keep stdout bounded even when the plan contains thousands of assets.
        print(json.dumps({
            "status": report.get("status"),
            "report": report.get("report"),
            "source_inventory_sha256": report.get("source_inventory_sha256"),
            "release_count": report.get("release_count"),
            "asset_count": report.get("asset_count"),
            "source_asset_bytes": report.get("source_asset_bytes"),
            "full_archive_asset_count": report.get("full_archive_asset_count"),
            "full_archive_asset_bytes": report.get("full_archive_asset_bytes"),
            "excluded_full_archive_bytes": report.get("excluded_full_archive_bytes"),
            "pending_download_bytes": report.get("pending_download_bytes"),
            "pending_materialization_bytes": report.get("pending_materialization_bytes"),
            "required_free_destination_bytes": report.get("required_free_destination_bytes"),
            "free_destination_bytes": report.get("free_destination_bytes"),
            "enough_disk_for_release_assets": report.get("enough_disk_for_release_assets"),
            "unverified_source_asset_count": report.get("unverified_source_asset_count", 0),
        }, indent=2, sort_keys=True))
        # The status is the contract: available disk and valid asset hashes
        # alone cannot certify a plan with missing analysis provenance.
        return 0 if report.get("status") == "PREFLIGHT_READY_NOT_RESTORED" else 3

    failures = (
        len(report["failures"])
        + int(report["verification_failures"])
        + len(report["classification"]["failures"])
        + int(report["unclaimed_dataset_release_count"])
    )
    if not report["all_source_assets_accounted_for"]:
        failures += 1
    # Downloading every Release asset does not certify a SAFE restore.
    # No invocation may exit zero unless catalog-bound restore is complete.
    expected_status = (
        "REPLAY_READY_COMPLETE" if args.replay_ready else "RESTORE_COMPLETE"
    )
    if report.get("status") != expected_status:
        failures += 1
    print(
        json.dumps(
            {
                "status": "OK" if failures == 0 else "FAIL",
                "restoration_status": report["status"],
                "unverified_source_asset_count": report.get("unverified_source_asset_count", 0),
                "source_inventory_sha256": report["source_inventory_sha256"],
                "release_count": report["release_count"],
                "asset_count": report["asset_count"],
                "source_asset_bytes": report.get("source_asset_bytes"),
                "verified_asset_bytes": report.get("verified_asset_bytes"),
                "missing_asset_bytes": report.get("missing_asset_bytes"),
                "source_byte_parity": report.get("source_byte_parity", False),
                "downloaded": report["downloaded"],
                "resumed_verified": report["resumed_verified"],
                "skipped_verified": report["skipped_verified"],
                "lfs_reused_verified": report["lfs_reused_verified"],
                "usable_shards": report["classification"]["usable_shards"],
                "quarantined_shards": report["classification"]["quarantined_shards"],
                "missing_or_corrupt_rows": report["classification"]["missing_or_corrupt_rows"],
                "pruned_unselected_assets": report.get("pruned_unselected_assets", 0),
                "pruned_unselected_bytes": report.get("pruned_unselected_bytes", 0),
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

