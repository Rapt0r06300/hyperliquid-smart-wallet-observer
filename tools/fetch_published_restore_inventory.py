#!/usr/bin/env python3
"""Download ONLY the latest published restore index, verifying GitHub SHA-256.

A small bounded metadata request, never historical market payloads. The output
is an inventory snapshot, not proof of replay safety or archive availability.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

try:
    from tools.restore_alina import _asset_ok, _download_to_path, _json, _expected_digest
except ModuleNotFoundError:
    from restore_alina import _asset_ok, _download_to_path, _json, _expected_digest

REPO = "Rapt0r06300/hyperliquid-smart-wallet-observer"
PREFIX = "alina-restore-inventory-"
ASSET = "RESTORE_INVENTORY.json.gz"
SHA = re.compile(r"[0-9a-f]{64}\Z")


def latest_inventory_asset(*, token: str | None = None, max_pages: int = 10) -> tuple[str, dict[str, Any]]:
    """Pick the newest inventory listed within GitHub's first 1,000 Releases."""
    if not 1 <= max_pages <= 10:
        raise ValueError("INVENTORY_INVALID_PAGE_BOUND")
    for page in range(1, max_pages + 1):
        url = f"https://api.github.com/repos/{REPO}/releases?per_page=100&page={page}"
        releases = _json(url, token=token)
        if not isinstance(releases, list):
            raise ValueError("INVENTORY_INVALID_RELEASE_LIST")
        for release in releases:
            if not isinstance(release, dict):
                raise ValueError("INVENTORY_INVALID_RELEASE_ENTRY")
            tag = release.get("tag_name")
            if not isinstance(tag, str) or not tag.startswith(PREFIX):
                continue
            assets = release.get("assets")
            if not isinstance(assets, list):
                raise ValueError("INVENTORY_RELEASE_MISSING_ASSETS")
            for asset in assets:
                if not isinstance(asset, dict) or asset.get("name") != ASSET:
                    continue
                digest = _expected_digest(asset)
                size = asset.get("size")
                download_url = asset.get("browser_download_url")
                if (type(asset.get("id")) is not int or asset["id"] <= 0
                        or type(size) is not int or size <= 0
                        or digest is None or not SHA.fullmatch(digest)
                        or asset.get("state") != "uploaded"
                        or not isinstance(download_url, str)
                        or not download_url.startswith(
                            f"https://github.com/{REPO}/releases/download/"
                        )):
                    raise ValueError("INVENTORY_RELEASE_ASSET_NOT_VERIFIABLE")
                return tag, asset
        if len(releases) < 100:
            break
    raise ValueError("INVENTORY_NOT_FOUND_WITHIN_GITHUB_RELEASE_WINDOW")


def obtain_verified_inventory(path: Path, *, token: str | None = None) -> dict[str, Any]:
    path = Path(path)
    if (path.is_symlink() or path.parent.is_symlink()
            or not path.parent.is_dir()):
        raise ValueError("INVENTORY_UNSAFE_TARGET")
    tag, asset = latest_inventory_asset(token=token)
    if path.exists() and not _asset_ok(path, asset):
        raise ValueError("INVENTORY_EXISTING_CACHE_DIGEST_CONFLICT")
    reused = path.is_file()
    if not reused:
        partial = path.with_name(path.name + ".partial")
        if partial.is_symlink():
            raise ValueError("INVENTORY_UNSAFE_PARTIAL")
        size, digest = _download_to_path(asset["browser_download_url"], partial, token=token)
        if size != asset["size"] or digest != _expected_digest(asset):
            raise ValueError("INVENTORY_DOWNLOAD_DIGEST_MISMATCH")
        # Never replace another file, even under concurrent invocations.
        os.link(partial, path)
        partial.unlink()
    if not _asset_ok(path, asset):
        raise ValueError("INVENTORY_FINAL_VERIFICATION_FAILED")
    return {
        "schema": "alina.published_inventory_fetch.v1",
        "status": "PUBLISHED_INVENTORY_ASSET_SHA256_VERIFIED_NOT_RESTORED",
        "source_repository": REPO,
        "release_tag": tag,
        "asset_id": asset["id"],
        "asset_name": ASSET,
        "asset_size_bytes": asset["size"],
        "asset_sha256": _expected_digest(asset),
        "cache_reused_verified": reused,
        "file": str(path),
        "raw_market_payloads_downloaded": 0,
        "replay_ready_certified": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        report = obtain_verified_inventory(
            args.output, token=os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"))
    except (OSError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "INVENTORY_FETCH_INCOMPLETE", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
