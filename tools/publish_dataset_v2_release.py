#!/usr/bin/env python3
"""Publish one Alina dataset V2 bundle to a GitHub Release.

Designed for a GitHub-hosted runner executing inside
Rapt0r06300/alina-smartflow-datasets-v2. The workflow token therefore writes only
to its own dataset repository; no user PC and no cross-repository PAT is required.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping

from hl_observer.datasets.v2_pipeline import (
    V2_REPOSITORY,
    finalize_manifest,
    verify_remote_asset,
    write_manifest,
)


MAX_RELEASE_ASSETS = 1000
CONTROL_ASSET_SLOTS = 1


class PublishError(RuntimeError):
    pass


def validate_release_capacity(shard_count: int) -> None:
    count = max(0, int(shard_count))
    maximum = MAX_RELEASE_ASSETS - CONTROL_ASSET_SLOTS
    if count > maximum:
        raise PublishError(
            f"bundle has {count} shards; maximum is {maximum} data assets "
            "per release when reserving one slot for RUN_MANIFEST.json"
        )


def _gh() -> str:
    executable = shutil.which("gh")
    if not executable:
        raise PublishError("GitHub CLI (gh) is required on the hosted runner.")
    if not (os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")):
        raise PublishError("GH_TOKEN/GITHUB_TOKEN is missing.")
    return executable


def _run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    process = subprocess.run(
        [_gh(), *args],
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and process.returncode != 0:
        detail = (process.stderr or process.stdout or "").strip()
        raise PublishError(f"gh {' '.join(args)} failed: {detail}")
    return process


def _json(args: list[str]) -> Any:
    raw = _run(args).stdout
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PublishError("GitHub returned invalid JSON.") from exc


def ensure_release(
    *,
    repository: str,
    tag: str,
    title: str,
    target: str,
    notes: str,
) -> Mapping[str, Any]:
    existing = _run(
        ["api", f"repos/{repository}/releases/tags/{tag}"],
        check=False,
    )
    if existing.returncode == 0:
        payload = json.loads(existing.stdout)
        if not isinstance(payload, Mapping):
            raise PublishError("Existing release payload is invalid.")
        return payload

    _run(
        [
            "release",
            "create",
            tag,
            "--repo",
            repository,
            "--target",
            target,
            "--title",
            title,
            "--notes",
            notes,
        ]
    )
    payload = _json(["api", f"repos/{repository}/releases/tags/{tag}"])
    if not isinstance(payload, Mapping):
        raise PublishError("Created release payload is invalid.")
    return payload


def release_asset_map(release: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    assets = release.get("assets")
    if not isinstance(assets, list):
        return result
    for raw in assets:
        if isinstance(raw, Mapping) and raw.get("name"):
            result[str(raw["name"])] = raw
    return result


def upload_file(*, repository: str, tag: str, path: Path) -> None:
    if not path.is_file():
        raise PublishError(f"Missing upload file: {path}")
    _run(
        [
            "release",
            "upload",
            tag,
            str(path),
            "--repo",
            repository,
            "--clobber",
        ]
    )


def publish_bundle(
    bundle_root: str | Path,
    *,
    repository: str,
    tag: str,
    target: str,
    title: str,
) -> dict[str, Any]:
    root = Path(bundle_root)
    index_path = root / "BUNDLE_INDEX.json"
    if not index_path.is_file():
        raise PublishError(f"Missing bundle index: {index_path}")
    index = json.loads(index_path.read_text(encoding="utf-8"))
    if not isinstance(index, Mapping):
        raise PublishError("Invalid bundle index.")

    manifest_paths = [
        root / str(value)
        for value in index.get("manifests", [])
        if str(value).strip()
    ]
    manifests: list[dict[str, Any]] = []
    for path in manifest_paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise PublishError(f"Invalid manifest: {path}")
        manifests.append(payload)

    # GitHub caps uploaded assets at 1000 per Release. Final shard manifests
    # are embedded in RUN_MANIFEST.json, so only data assets + one run manifest
    # are uploaded. Refuse oversized releases before spending time on uploads.
    validate_release_capacity(len(manifests))

    notes = (
        "Alina SmartFlow dataset V2 collection run.\n\n"
        f"Collector SHA: {index.get('collector_version')}\n"
        f"Shards: {len(manifests)}\n"
        "Final shard manifests are consolidated in RUN_MANIFEST.json.\n"
        "Only manifests with quality_status=SAFE and validation_allowed=true "
        "may be used by validation replays/backtests."
    )
    release = ensure_release(
        repository=repository,
        tag=tag,
        target=target,
        title=title,
        notes=notes,
    )
    release_id = int(release.get("id") or 0)
    if release_id <= 0:
        raise PublishError("Release id is missing.")

    # Upload immutable data assets first.
    for manifest in manifests:
        asset_name = str(manifest.get("release_asset") or "")
        local = root / "assets" / asset_name
        upload_file(repository=repository, tag=tag, path=local)

    # Re-read remote metadata after all uploads and verify exact digest + size.
    release = _json(["api", f"repos/{repository}/releases/tags/{tag}"])
    if not isinstance(release, Mapping):
        raise PublishError("Release payload after upload is invalid.")
    assets = release_asset_map(release)

    final_dir = root / "final_manifests"
    final_dir.mkdir(parents=True, exist_ok=True)
    final_manifests: list[dict[str, Any]] = []
    for manifest in manifests:
        asset_name = str(manifest.get("release_asset") or "")
        remote = assets.get(asset_name)
        if remote is None:
            raise PublishError(f"Uploaded asset not visible in release: {asset_name}")
        verified = verify_remote_asset(
            manifest,
            repository=repository,
            release_tag=tag,
            release_id=release_id,
            asset_id=int(remote.get("id") or 0),
            asset_name=asset_name,
            remote_size=int(remote.get("size") or 0),
            remote_digest=str(remote.get("digest") or ""),
        )
        # Local paths are ephemeral runner implementation details.
        verified.pop("local_source_path", None)
        verified.pop("local_asset_path", None)
        final_path = final_dir / f"{verified['dataset_id']}.json"
        write_manifest(verified, final_path)
        final_manifests.append(verified)

    run_manifest = {
        "schema": "alina.dataset_run_manifest.v2",
        "repository": repository,
        "release_id": release_id,
        "release_tag": tag,
        "collector_version": index.get("collector_version"),
        "shard_count": len(final_manifests),
        "safe_count": sum(
            1 for row in final_manifests if row.get("quality_status") == "SAFE"
        ),
        "partial_count": sum(
            1 for row in final_manifests if row.get("quality_status") == "PARTIAL"
        ),
        "reject_count": sum(
            1 for row in final_manifests if row.get("quality_status") == "REJECT"
        ),
        "manifests": final_manifests,
        "read_only": True,
        "real_execution": False,
    }
    run_path = root / "RUN_MANIFEST.json"
    write_manifest(run_manifest, run_path)
    upload_file(repository=repository, tag=tag, path=run_path)

    # Refresh once more so RUN_MANIFEST itself is visible before success.
    final_release = _json(["api", f"repos/{repository}/releases/tags/{tag}"])
    final_assets = release_asset_map(final_release if isinstance(final_release, Mapping) else {})
    if "RUN_MANIFEST.json" not in final_assets:
        raise PublishError("RUN_MANIFEST.json not visible after upload.")
    return run_manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle_root")
    parser.add_argument("--repository", default=V2_REPOSITORY)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--target", default="main")
    parser.add_argument("--title")
    args = parser.parse_args(argv)
    title = args.title or f"Alina dataset V2 {args.tag}"
    try:
        result = publish_bundle(
            args.bundle_root,
            repository=args.repository,
            tag=args.tag,
            target=args.target,
            title=title,
        )
    except (PublishError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"DATASET_V2_PUBLISH_NO_GO: {exc}")
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
