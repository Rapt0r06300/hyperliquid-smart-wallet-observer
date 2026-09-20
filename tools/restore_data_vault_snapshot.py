from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from data_vault_core import (
    copy_stream,
    load_gzip_json,
    safe_output,
    sha256_file,
)
from publish_data_vault_snapshot import (
    DEFAULT_REPOSITORY,
    PublishError,
    api_json,
)

PRESETS: dict[str, tuple[str, ...]] = {
    "economic-core": (
        "bbo_",
        "market_ticks",
        "allmids",
        "vault_",
        "leader_fills",
        "userfills",
        "copy_",
        "cross_venue",
        "dispersion_venues",
        "carnet_venues",
        "feed_quality",
        "fills_",
    ),
    "copy-vault": (
        "vault",
        "leader",
        "userfills",
        "metaorder",
        "copy_",
    ),
    "lead-lag": (
        "bbo_",
        "lead_lag",
        "market_ticks",
        "allmids",
        "trade",
        "marks",
    ),
    "cross-venue": (
        "bbo_",
        "cross_venue",
        "dispersion",
        "carnet_venues",
        "market_ticks",
        "funding",
        "fee",
    ),
    "all": (),
}


class RestoreError(RuntimeError):
    pass


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/octet-stream",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Alina-Data-Vault-Restore",
    }


def _release_assets(
    repository: str,
    tag: str,
    token: str,
) -> dict[str, dict[str, Any]]:
    encoded = urllib.parse.quote(tag, safe="")
    release = api_json(
        "GET",
        f"/repos/{repository}/releases/tags/{encoded}",
        token,
    )
    if not release:
        raise RestoreError(f"release not found for tag: {tag}")
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise RestoreError(f"release has no assets: {tag}")
    return {
        str(item.get("name")): item
        for item in assets
        if isinstance(item, dict) and item.get("name")
    }


def _digest(asset: dict[str, Any]) -> str:
    raw = str(asset.get("digest") or "")
    return raw[7:] if raw.startswith("sha256:") else ""


def download_asset(
    *,
    repository: str,
    asset: dict[str, Any],
    destination: Path,
    token: str,
) -> Path:
    asset_id = int(asset.get("id") or 0)
    name = str(asset.get("name") or "")
    if asset_id <= 0 or not name:
        raise RestoreError("invalid release asset")

    destination.parent.mkdir(parents=True, exist_ok=True)
    expected_size = int(asset.get("size") or 0)
    expected_digest = _digest(asset).lower()

    if destination.is_file():
        if destination.stat().st_size == expected_size:
            if not expected_digest or sha256_file(destination).lower() == expected_digest:
                return destination
        destination.unlink(missing_ok=True)

    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/releases/assets/{asset_id}",
        headers=_headers(token),
        method="GET",
    )
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.unlink(missing_ok=True)

    try:
        with urllib.request.urlopen(request, timeout=180) as response, temporary.open("wb") as target:
            while True:
                chunk = response.read(8 * 1024 * 1024)
                if not chunk:
                    break
                target.write(chunk)
    except (urllib.error.HTTPError, urllib.error.URLError, OSError) as exc:
        temporary.unlink(missing_ok=True)
        raise RestoreError(f"download failed for {name}: {exc}") from exc

    if temporary.stat().st_size != expected_size:
        temporary.unlink(missing_ok=True)
        raise RestoreError(f"downloaded size mismatch for {name}")
    if expected_digest and sha256_file(temporary).lower() != expected_digest:
        temporary.unlink(missing_ok=True)
        raise RestoreError(f"downloaded digest mismatch for {name}")

    temporary.replace(destination)
    return destination


def select_records(
    index_payload: dict[str, Any],
    *,
    preset: str,
    contains: tuple[str, ...],
    prefixes: tuple[str, ...],
) -> dict[str, dict[str, Any]]:
    files = index_payload.get("files")
    if not isinstance(files, dict):
        raise RestoreError("file index has no files object")

    preset_patterns = PRESETS[preset]
    needles = tuple(
        value.casefold()
        for value in (*preset_patterns, *contains)
        if value
    )
    prefix_values = tuple(value.casefold() for value in prefixes if value)
    selected: dict[str, dict[str, Any]] = {}

    for path, raw in files.items():
        if not isinstance(raw, dict):
            continue
        relative = str(path).replace("\\", "/")
        lowered = relative.casefold()
        if preset == "all" and not needles and not prefix_values:
            selected[relative] = dict(raw)
            continue
        if prefix_values and any(lowered.startswith(prefix) for prefix in prefix_values):
            selected[relative] = dict(raw)
            continue
        if needles and any(needle in lowered for needle in needles):
            selected[relative] = dict(raw)

    return selected


def needed_assets(records: dict[str, dict[str, Any]]) -> dict[str, set[str]]:
    grouped: dict[str, set[str]] = defaultdict(set)
    for record in records.values():
        tag = str(record.get("release_tag") or "")
        if not tag:
            raise RestoreError("record without release_tag")
        storage = str(record.get("storage") or "")
        if storage == "zip_entry":
            name = str(record.get("asset") or "")
            if not name:
                raise RestoreError("zip record without asset")
            grouped[tag].add(name)
        elif storage == "raw_chunks":
            chunks = record.get("chunks")
            if not isinstance(chunks, list) or not chunks:
                raise RestoreError("chunked record without chunks")
            for chunk in chunks:
                if not isinstance(chunk, dict):
                    continue
                name = str(chunk.get("asset") or "")
                if name:
                    grouped[tag].add(name)
        else:
            raise RestoreError(f"unknown storage: {storage}")
    return grouped


def build_download_plan(
    *,
    repository: str,
    records: dict[str, dict[str, Any]],
    token: str,
) -> tuple[dict[str, dict[str, dict[str, Any]]], int]:
    grouped = needed_assets(records)
    releases: dict[str, dict[str, dict[str, Any]]] = {}
    total = 0
    for tag, names in grouped.items():
        assets = _release_assets(repository, tag, token)
        releases[tag] = assets
        for name in names:
            asset = assets.get(name)
            if asset is None:
                raise RestoreError(f"asset missing from {tag}: {name}")
            total += int(asset.get("size") or 0)
    return releases, total


def materialize(
    *,
    repository: str,
    records: dict[str, dict[str, Any]],
    releases: dict[str, dict[str, dict[str, Any]]],
    output_root: Path,
    cache_root: Path,
    token: str,
) -> list[Path]:
    output_root.mkdir(parents=True, exist_ok=True)
    cache_root.mkdir(parents=True, exist_ok=True)

    local_assets: dict[tuple[str, str], Path] = {}
    for tag, names in needed_assets(records).items():
        assets = releases[tag]
        for name in sorted(names):
            asset = assets[name]
            cache_name = f"{tag}__{name}".replace("/", "_")
            local_assets[(tag, name)] = download_asset(
                repository=repository,
                asset=asset,
                destination=cache_root / cache_name,
                token=token,
            )

    zip_groups: dict[tuple[str, str], list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    chunked: list[tuple[str, dict[str, Any]]] = []
    for relative, record in records.items():
        if record.get("storage") == "zip_entry":
            zip_groups[
                (str(record["release_tag"]), str(record["asset"]))
            ].append((relative, record))
        else:
            chunked.append((relative, record))

    created: list[Path] = []
    for key, group in zip_groups.items():
        archive_path = local_assets[key]
        with zipfile.ZipFile(archive_path, "r") as archive:
            names = set(archive.namelist())
            for relative, record in group:
                member = str(record.get("member") or relative)
                if member not in names:
                    raise RestoreError(f"zip member missing: {member}")
                destination = safe_output(output_root, relative)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member, "r") as source, destination.open("wb") as target:
                    copy_stream(source, target)
                if destination.stat().st_size != int(record.get("size") or 0):
                    raise RestoreError(f"restored size mismatch: {relative}")
                expected = str(record.get("sha256") or "").lower()
                if expected and sha256_file(destination).lower() != expected:
                    raise RestoreError(f"restored sha256 mismatch: {relative}")
                created.append(destination)

    for relative, record in chunked:
        destination = safe_output(output_root, relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        chunks = sorted(
            [item for item in record.get("chunks", []) if isinstance(item, dict)],
            key=lambda item: int(item.get("part") or 0),
        )
        with destination.open("wb") as target:
            for chunk in chunks:
                key = (str(record["release_tag"]), str(chunk["asset"]))
                source_path = local_assets[key]
                with source_path.open("rb") as source:
                    copy_stream(source, target)
        if destination.stat().st_size != int(record.get("size") or 0):
            raise RestoreError(f"restored size mismatch: {relative}")
        expected = str(record.get("sha256") or "").lower()
        if expected and sha256_file(destination).lower() != expected:
            raise RestoreError(f"restored sha256 mismatch: {relative}")
        created.append(destination)

    return created


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Restore a verified subset from the Alina continuous Data Vault."
    )
    parser.add_argument("--index", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--cache-root", type=Path, default=None)
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--preset", choices=tuple(PRESETS), default="economic-core")
    parser.add_argument("--contains", action="append", default=[])
    parser.add_argument("--prefix", action="append", default=[])
    parser.add_argument("--max-download-gib", type=float, default=12.0)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--token-env", default="GITHUB_TOKEN")
    args = parser.parse_args(argv)

    token = os.environ.get(args.token_env, "").strip()
    if not token:
        print(json.dumps({"ok": False, "error": f"missing token: {args.token_env}"}))
        return 2
    if args.repository != DEFAULT_REPOSITORY:
        print(json.dumps({"ok": False, "error": "unexpected repository"}))
        return 2

    try:
        payload = load_gzip_json(args.index.resolve())
        records = select_records(
            payload,
            preset=args.preset,
            contains=tuple(args.contains),
            prefixes=tuple(args.prefix),
        )
        if not records:
            raise RestoreError("selection is empty")
        releases, total_bytes = build_download_plan(
            repository=args.repository,
            records=records,
            token=token,
        )
        limit = int(max(0.0, args.max_download_gib) * 1024**3)
        if limit and total_bytes > limit:
            raise RestoreError(
                f"download plan is {total_bytes / (1024**3):.3f} GiB, "
                f"above limit {args.max_download_gib:.3f} GiB"
            )

        plan = {
            "schema": "alina.data_vault.restore_plan.v1",
            "preset": args.preset,
            "selected_files": len(records),
            "raw_selected_bytes": sum(int(row.get("size") or 0) for row in records.values()),
            "release_tags": sorted(releases),
            "download_bytes": total_bytes,
            "download_gib": round(total_bytes / (1024**3), 4),
        }
        if args.plan_only:
            print(json.dumps({"ok": True, **plan}, indent=2, sort_keys=True))
            return 0

        cache_root = (
            args.cache_root.resolve()
            if args.cache_root
            else args.output_root.resolve().parent / "vault_asset_cache"
        )
        created = materialize(
            repository=args.repository,
            records=records,
            releases=releases,
            output_root=args.output_root.resolve(),
            cache_root=cache_root,
            token=token,
        )
        result = {
            **plan,
            "restored_files": len(created),
            "output_root": str(args.output_root.resolve()),
        }
        print(json.dumps({"ok": True, **result}, indent=2, sort_keys=True))
        return 0
    except (
        RestoreError,
        PublishError,
        OSError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
