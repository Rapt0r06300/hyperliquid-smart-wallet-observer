#!/usr/bin/env python3
"""Mirror GitHub Release assets into the canonical Git-LFS clone payload.

This tool is intentionally bounded and idempotent. It never deletes Release
assets and never trades. A GitHub-hosted workflow can run it repeatedly until
every immutable Release asset is represented in clone_payload/ and therefore
available to a normal git clone with Git LFS installed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_REPOSITORY = "Rapt0r06300/hyperliquid-smart-wallet-observer"
MANIFEST_PATH = Path("clone_payload/MANIFEST.json")
PAYLOAD_ROOT = Path("clone_payload/releases")
USER_AGENT = "alina-clone-lfs-mirror/1"
DEFAULT_MAX_ASSETS = 1000
DEFAULT_MAX_BYTES = 1_500_000_000
FORBIDDEN = re.compile(
    r"(^|[._-])(env|secret|token|credential|private|mnemonic|seed|api[_-]?key)([._-]|$)",
    re.IGNORECASE,
)
SAFE = re.compile(r"[^A-Za-z0-9._-]+")


class MirrorError(RuntimeError):
    pass


def _safe_component(value: str, *, max_len: int = 150) -> str:
    raw = str(value)
    cleaned = SAFE.sub("_", raw).strip("._")
    if not cleaned:
        raise MirrorError(f"unsafe empty path component derived from {value!r}")
    if cleaned != raw or len(cleaned) > max_len:
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
        cleaned = f"{cleaned[:max_len]}--{digest}"
    return cleaned[: max_len + 14]


def _headers(token: str | None, *, accept: str = "application/vnd.github+json") -> dict[str, str]:
    headers = {
        "Accept": accept,
        "User-Agent": USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _without_authorization(request: urllib.request.Request) -> urllib.request.Request:
    headers = {
        key: value
        for key, value in request.header_items()
        if key.lower() != "authorization"
    }
    return urllib.request.Request(request.full_url, headers=headers)


def _open_with_retry(
    request: urllib.request.Request,
    *,
    retries: int = 8,
):
    active_request = request
    anonymous_fallback_used = False
    for attempt in range(1, retries + 1):
        try:
            return urllib.request.urlopen(active_request, timeout=120)
        except urllib.error.HTTPError as exc:
            # This repository is public. GitHub Actions installation tokens can
            # exhaust a shared API budget while anonymous public reads still
            # have an independent allowance. Use that allowance before sleeping.
            has_auth = any(
                key.lower() == "authorization"
                for key, _value in active_request.header_items()
            )
            if exc.code == 403 and has_auth and not anonymous_fallback_used:
                active_request = _without_authorization(active_request)
                anonymous_fallback_used = True
                continue

            transient = exc.code in {403, 429, 500, 502, 503, 504}
            if not transient or attempt >= retries:
                detail = exc.read().decode("utf-8", errors="replace")[:800]
                raise MirrorError(
                    f"HTTP {exc.code} for {active_request.full_url}: {detail}"
                ) from exc
            reset = exc.headers.get("X-RateLimit-Reset")
            delay = min(120.0, float(2 ** min(attempt, 6)))
            if reset and reset.isdigit():
                delay = max(delay, min(120.0, int(reset) - time.time() + 2.0))
            time.sleep(max(1.0, delay))
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt >= retries:
                raise MirrorError(
                    f"network failure for {active_request.full_url}: {exc}"
                ) from exc
            time.sleep(min(60.0, float(2 ** attempt)))
    raise MirrorError(f"unreachable retry state for {active_request.full_url}")


def _api_page(
    repository: str,
    *,
    page: int,
    per_page: int,
    token: str | None,
) -> tuple[list[Mapping[str, Any]], Mapping[str, str]]:
    url = (
        f"https://api.github.com/repos/{repository}/releases"
        f"?per_page={per_page}&page={page}"
    )
    request = urllib.request.Request(url, headers=_headers(token))
    with _open_with_retry(request) as response:
        raw = response.read()
        headers = dict(response.headers.items())
    try:
        payload = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise MirrorError(f"invalid GitHub release JSON on page {page}") from exc
    if not isinstance(payload, list):
        raise MirrorError("GitHub releases payload is not an array")
    return [row for row in payload if isinstance(row, Mapping)], headers


def _last_page_from_link(link: str | None, default: int = 1) -> int:
    if not link:
        return default
    for chunk in link.split(","):
        if 'rel="last"' not in chunk:
            continue
        match = re.search(r"[?&]page=(\d+)", chunk)
        if match:
            return max(1, int(match.group(1)))
    return default


def iter_releases_oldest_first(
    repository: str,
    *,
    token: str | None = None,
    per_page: int = 5,
) -> Iterable[Mapping[str, Any]]:
    # Some collection Releases carry hundreds of assets. Requesting 100 such
    # Releases per response repeatedly triggers GitHub API 504 timeouts.
    # Paginate in small, bounded responses and never silently truncate.
    if per_page < 1 or per_page > 10:
        raise MirrorError("Release pagination per_page must be between 1 and 10")
    first, headers = _api_page(
        repository,
        page=1,
        per_page=per_page,
        token=token,
    )
    link = headers.get("Link") or headers.get("link")
    if len(first) == per_page and not link:
        raise MirrorError(
            "GitHub omitted pagination metadata for a full Release page; "
            "refusing an incomplete source inventory"
        )
    last_page = _last_page_from_link(link, default=1)
    if len(first) == per_page and last_page == 1:
        raise MirrorError(
            "GitHub Release pagination is incomplete; refusing to report byte parity"
        )

    for page in range(last_page, 0, -1):
        rows = (
            first
            if page == 1
            else _api_page(
                repository,
                page=page,
                per_page=per_page,
                token=token,
            )[0]
        )
        for release in reversed(rows):
            yield release


def _expected_remote_sha(asset: Mapping[str, Any]) -> str | None:
    raw = str(asset.get("digest") or "")
    if raw.lower().startswith("sha256:"):
        value = raw.split(":", 1)[1].lower()
        if len(value) == 64:
            return value
    return None


def asset_target(asset: Mapping[str, Any], release: Mapping[str, Any]) -> Path:
    asset_id = int(asset.get("id") or 0)
    if asset_id <= 0:
        raise MirrorError("Release asset is missing its immutable GitHub asset id")
    name = str(asset.get("name") or "")
    tag = str(release.get("tag_name") or "")
    if not name or not tag:
        raise MirrorError("Release asset is missing name/tag identity")
    if FORBIDDEN.search(name) or FORBIDDEN.search(tag):
        raise MirrorError(f"secret-like Release identity refused: {tag}/{name}")
    safe_tag = _safe_component(tag, max_len=110)
    safe_name = _safe_component(name, max_len=150)
    return PAYLOAD_ROOT / safe_tag / f"{asset_id}--{safe_name}"


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    if not path.is_file():
        raise MirrorError(f"clone payload manifest missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise MirrorError(f"invalid clone payload manifest: {path}") from exc
    if not isinstance(payload, dict):
        raise MirrorError("clone payload manifest is not an object")
    if payload.get("schema") != "alina.clone_payload_manifest.v1":
        raise MirrorError("unsupported clone payload manifest schema")
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise MirrorError("clone payload manifest entries must be a list")
    return payload


def known_asset_ids(manifest: Mapping[str, Any]) -> set[int]:
    result: set[int] = set()
    for row in manifest.get("entries") or []:
        if isinstance(row, Mapping):
            asset_id = int(row.get("asset_id") or 0)
            if asset_id > 0:
                result.add(asset_id)
    return result


def select_pending_assets(
    releases: Iterable[Mapping[str, Any]],
    known_ids: set[int],
    *,
    max_assets: int,
    max_bytes: int,
) -> list[tuple[Mapping[str, Any], Mapping[str, Any]]]:
    selected: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    selected_bytes = 0

    if max_assets < 1 or max_bytes < 1:
        raise MirrorError("mirror limits must be positive")
    for release in releases:
        assets = release.get("assets")
        if not isinstance(assets, list):
            raise MirrorError("Release asset inventory is missing")
        for asset in assets:
            if not isinstance(asset, Mapping):
                raise MirrorError("Release asset inventory has an invalid row")
            asset_id = int(asset.get("id") or 0)
            if asset_id <= 0:
                raise MirrorError("Release asset missing immutable ID")
            if asset_id in known_ids:
                continue
            size = int(asset.get("size") or 0)
            if size < 0:
                raise MirrorError(f"negative Release asset size for id={asset_id}")
            if size > max_bytes:
                raise MirrorError(
                    f"Release asset id={asset_id} is {size} bytes, larger than "
                    f"this worker batch limit {max_bytes}; increase the per-run "
                    "limit rather than silently exceeding runner capacity"
                )
            if len(selected) >= max_assets or selected_bytes + size > max_bytes:
                return selected
            selected.append((release, asset))
            selected_bytes += size
            if len(selected) >= max_assets:
                return selected
    return selected


def _stream_download(
    asset: Mapping[str, Any],
    target: Path,
    *,
    token: str | None,
) -> tuple[int, str]:
    url = str(asset.get("browser_download_url") or "")
    if not url:
        raise MirrorError("Release asset is missing browser_download_url")
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".partial")
    tmp.unlink(missing_ok=True)

    request = urllib.request.Request(
        url,
        headers=_headers(token, accept="application/octet-stream"),
    )
    try:
        with _open_with_retry(request) as response:
            digest = hashlib.sha256()
            size = 0
            with tmp.open("wb") as output:
                while True:
                    chunk = response.read(8 * 1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise

    expected_size = int(asset.get("size") or 0)
    if expected_size != size:
        tmp.unlink(missing_ok=True)
        raise MirrorError(
            f"Release asset size mismatch id={asset.get('id')}: "
            f"expected={expected_size} actual={size}"
        )
    sha = digest.hexdigest()
    expected_sha = _expected_remote_sha(asset)
    if expected_sha and sha != expected_sha:
        tmp.unlink(missing_ok=True)
        raise MirrorError(
            f"Release asset SHA-256 mismatch id={asset.get('id')}"
        )
    tmp.replace(target)
    return size, sha


def _verify_existing_target(
    target: Path,
    *,
    expected_size: int,
    expected_sha: str,
) -> bool:
    if not target.is_file() or target.stat().st_size != expected_size:
        return False
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest() == expected_sha


def mirror_batch(
    repository: str,
    *,
    root: Path,
    max_assets: int,
    max_bytes: int,
    token: str | None,
) -> dict[str, Any]:
    manifest_path = root / MANIFEST_PATH
    manifest = load_manifest(manifest_path)
    known = known_asset_ids(manifest)
    selected = select_pending_assets(
        iter_releases_oldest_first(repository, token=token),
        known,
        max_assets=max_assets,
        max_bytes=max_bytes,
    )

    new_entries: list[dict[str, Any]] = []
    for release, asset in selected:
        relative = asset_target(asset, release)
        target = root / relative
        expected_size = int(asset.get("size") or 0)
        expected_remote_sha = _expected_remote_sha(asset)

        if (
            expected_remote_sha
            and _verify_existing_target(
                target,
                expected_size=expected_size,
                expected_sha=expected_remote_sha,
            )
        ):
            actual_size = expected_size
            sha = expected_remote_sha
        else:
            actual_size, sha = _stream_download(asset, target, token=token)

        new_entries.append(
            {
                "asset_id": int(asset["id"]),
                "release_id": int(release.get("id") or 0),
                "release_tag": str(release.get("tag_name") or ""),
                "release_name": str(release.get("name") or ""),
                "asset_name": str(asset.get("name") or ""),
                "bytes": actual_size,
                "sha256": sha,
                "source_digest": str(asset.get("digest") or ""),
                "clone_path": relative.as_posix(),
                "source_url": str(asset.get("browser_download_url") or ""),
                "mirrored_at_utc": datetime.now(timezone.utc).isoformat(),
            }
        )

    entries = [
        row for row in manifest.get("entries") or [] if isinstance(row, Mapping)
    ]
    entries.extend(new_entries)
    entries = sorted(entries, key=lambda row: int(row.get("asset_id") or 0))
    manifest["entries"] = entries
    manifest["total_assets"] = len(entries)
    manifest["total_bytes"] = sum(int(row.get("bytes") or 0) for row in entries)
    manifest["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    manifest["last_batch_assets"] = len(new_entries)
    manifest["last_batch_bytes"] = sum(
        int(row.get("bytes") or 0) for row in new_entries
    )
    manifest["read_only"] = True
    manifest["real_execution"] = False
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    return {
        "schema": "alina.clone_payload_mirror_report.v1",
        "repository": repository,
        "added_assets": len(new_entries),
        "added_bytes": manifest["last_batch_bytes"],
        "total_assets": manifest["total_assets"],
        "total_bytes": manifest["total_bytes"],
        "paths": [row["clone_path"] for row in new_entries],
        "read_only": True,
        "real_execution": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--root", default=".")
    parser.add_argument("--max-assets", type=int, default=DEFAULT_MAX_ASSETS)
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    parser.add_argument(
        "--confirm-lfs-costs",
        action="store_true",
        help=(
            "required: Git LFS storage/bandwidth can be billable once account "
            "allowances are exceeded"
        ),
    )
    args = parser.parse_args(argv)

    if not args.confirm_lfs_costs:
        print(
            "ALINA_CLONE_LFS_MIRROR_BLOCKED: --confirm-lfs-costs is required",
            file=sys.stderr,
        )
        return 4
    if args.max_assets < 1 or args.max_bytes < 1:
        print("ALINA_CLONE_LFS_MIRROR_FAIL: invalid batch bounds", file=sys.stderr)
        return 2

    root = Path(args.root).resolve()
    token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    try:
        report = mirror_batch(
            args.repository,
            root=root,
            max_assets=args.max_assets,
            max_bytes=args.max_bytes,
            token=token,
        )
    except (MirrorError, OSError, ValueError) as exc:
        print(f"ALINA_CLONE_LFS_MIRROR_FAIL: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
