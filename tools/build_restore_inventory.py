#!/usr/bin/env python3
"""Publishable inventory for repositories exceeding GitHub's 1000-Release cap."""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import gzip
import json
import os
import subprocess
import sys
import urllib.parse
from pathlib import Path
from typing import Any, Callable, Mapping

try:
    from tools.restore_alina import RestoreError, _json, _validate_release_asset
except ModuleNotFoundError:
    from restore_alina import RestoreError, _json, _validate_release_asset


INVENTORY_TAG_PREFIX = "alina-restore-inventory-"
INVENTORY_ASSET_NAME = "RESTORE_INVENTORY.json.gz"


def _minimal_release(release: Mapping[str, Any]) -> dict[str, Any]:
    release_id = release.get("id")
    tag = release.get("tag_name")
    assets = release.get("assets")
    if type(release_id) is not int or release_id <= 0:
        raise RestoreError("release has no valid id")
    if not isinstance(tag, str) or not tag:
        raise RestoreError("release has no valid tag")
    if not isinstance(assets, list):
        raise RestoreError(f"release {tag} has no embedded asset inventory")
    asset_ids: set[int] = set()
    asset_names: set[str] = set()
    minimized: list[dict[str, Any]] = []
    for asset in assets:
        _validate_release_asset(asset, release_id, asset_ids, asset_names)
        minimized.append({
            "id": asset["id"],
            "name": asset["name"],
            "size": asset["size"],
            "digest": asset["digest"],
            "state": asset["state"],
            "browser_download_url": asset["browser_download_url"],
        })
    return {"id": release_id, "tag_name": tag, "assets": minimized}


def build_inventory(
    repository: str,
    tags: list[str],
    fetch_release: Callable[[str], Mapping[str, Any]],
    *,
    generated_at: str,
) -> dict[str, Any]:
    releases: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    seen_tags: set[str] = set()
    for tag in sorted(set(tags)):
        if tag.startswith(INVENTORY_TAG_PREFIX):
            continue
        release = _minimal_release(fetch_release(tag))
        if release["tag_name"] != tag:
            raise RestoreError(f"release tag mismatch for {tag}")
        if release["id"] in seen_ids or tag in seen_tags:
            raise RestoreError(f"duplicate release identity for {tag}")
        seen_ids.add(release["id"])
        seen_tags.add(tag)
        releases.append(release)
    releases.sort(key=lambda row: (row["id"], row["tag_name"]))
    return {
        "schema": "alina.restore_inventory.v1",
        "repository": repository,
        "generated_at_utc": generated_at,
        "release_count": len(releases),
        "asset_count": sum(len(row["assets"]) for row in releases),
        "source_asset_bytes": sum(
            asset["size"] for row in releases for asset in row["assets"]
        ),
        "releases": releases,
    }


def _remote_tags(remote: str) -> list[str]:
    result = subprocess.run(
        ["git", "ls-remote", "--tags", remote],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    tags: set[str] = set()
    for line in result.stdout.splitlines():
        parts = line.split("\t", 1)
        if len(parts) != 2 or not parts[1].startswith("refs/tags/"):
            continue
        ref = parts[1][len("refs/tags/"):]
        if ref.endswith("^{}"):
            ref = ref[:-3]
        if ref:
            tags.add(ref)
    return sorted(tags)


def _fetch_all_releases(
    repository: str, tags: list[str], token: str, workers: int,
) -> dict[str, Mapping[str, Any]]:
    wanted = [tag for tag in tags if not tag.startswith(INVENTORY_TAG_PREFIX)]

    def fetch(tag: str) -> tuple[str, Mapping[str, Any]]:
        quoted = urllib.parse.quote(tag, safe="")
        payload = _json(
            f"https://api.github.com/repos/{repository}/releases/tags/{quoted}",
            token=token,
        )
        if not isinstance(payload, Mapping):
            raise RestoreError(f"invalid Release payload for {tag}")
        return tag, payload

    found: dict[str, Mapping[str, Any]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch, tag): tag for tag in wanted}
        for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
            tag, payload = future.result()
            found[tag] = payload
            if index % 100 == 0 or index == len(futures):
                print(f"inventory progress {index}/{len(futures)}", file=sys.stderr)
    return found


def _write_gzip_json(path: Path, payload: Mapping[str, Any]) -> None:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    partial = path.with_suffix(path.suffix + ".partial")
    with (
        partial.open("wb") as output,
        gzip.GzipFile(fileobj=output, mode="wb", mtime=0) as compressed,
    ):
        compressed.write(raw)
    partial.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--output", default=INVENTORY_ASSET_NAME)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args(argv)
    token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    if not token:
        parser.error("GH_TOKEN or GITHUB_TOKEN is required")
    if not 1 <= args.workers <= 16:
        parser.error("--workers must be between 1 and 16")
    tags = _remote_tags(args.remote)
    fetched = _fetch_all_releases(args.repository, tags, token, args.workers)
    generated_at = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    payload = build_inventory(
        args.repository, tags, fetched.__getitem__, generated_at=generated_at,
    )
    output = Path(args.output)
    _write_gzip_json(output, payload)
    print(json.dumps({
        "output": str(output),
        "release_count": payload["release_count"],
        "asset_count": payload["asset_count"],
        "source_asset_bytes": payload["source_asset_bytes"],
        "compressed_bytes": output.stat().st_size,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
