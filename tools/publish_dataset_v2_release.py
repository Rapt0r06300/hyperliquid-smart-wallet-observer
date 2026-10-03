#!/usr/bin/env python3
"""Publish one Alina dataset V2 bundle to a GitHub Release.

Designed for a GitHub-hosted runner executing inside
Rapt0r06300/hyperliquid-smart-wallet-observer. The workflow token writes to the same Alina Smart Flow repository; no user PC and no cross-repository PAT is required.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Mapping

from hl_observer.datasets.replay_coverage import build_safe_coverage_matrix
from hl_observer.datasets.v2_pipeline import (
    V2_REPOSITORY,
    finalize_manifest,
    verify_remote_asset,
    write_manifest,
)


MAX_RELEASE_ASSETS = 1000
CONTROL_ASSET_SLOTS = 1
DATA_ASSETS_PER_RELEASE = MAX_RELEASE_ASSETS - CONTROL_ASSET_SLOTS


def overflow_release_tag(base_tag: str, part_index: int) -> str:
    """Stable non-production tag for overflow data assets.

    Only the canonical base tag carries RUN_MANIFEST.json and is discovered by
    the catalog reconciler. Overflow releases remain addressable through each
    embedded shard manifest without being mistaken for independent runs.
    """
    if int(part_index) <= 0:
        return str(base_tag)
    digest = hashlib.sha256(str(base_tag).encode("utf-8")).hexdigest()[:16]
    return f"alina-data-part-{digest}-{int(part_index):03d}"


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
    """Upload one asset with bounded retries for GitHub release visibility races."""
    if not path.is_file():
        raise PublishError(f"Missing upload file: {path}")

    args = [
        "release",
        "upload",
        tag,
        str(path),
        "--repo",
        repository,
        "--clobber",
    ]
    max_attempts = 6
    for attempt in range(1, max_attempts + 1):
        process = _run(args, check=False)
        if process.returncode == 0:
            return

        detail = (process.stderr or process.stdout or "").strip()
        lowered = detail.lower()
        transient = any(
            marker in lowered
            for marker in (
                "release not found",
                "http 404",
                "status 404",
                "502 bad gateway",
                "503 service unavailable",
                "timeout",
                "timed out",
                "connection reset",
                "api rate limit exceeded",
                "secondary rate limit",
            )
        )
        if not transient or attempt >= max_attempts:
            raise PublishError(f"gh {' '.join(args)} failed: {detail}")

        # GitHub can expose a newly created release through one endpoint before
        # the release-upload lookup sees its tag. Back off, then retry the exact
        # idempotent --clobber upload instead of failing an otherwise valid lane.
        rate_limited = "rate limit" in lowered
        time.sleep(
            min(60.0, 30.0 * attempt)
            if rate_limited
            else min(20.0, float(2 ** (attempt - 1)))
        )


def assert_existing_asset_compatible(
    manifest: Mapping[str, Any],
    remote: Mapping[str, Any],
) -> None:
    """Reject an identity collision when a release already contains another digest."""
    expected_sha = str(manifest.get("sha256") or "").lower()
    expected_size = int(manifest.get("bytes") or 0)
    remote_digest = str(remote.get("digest") or "")
    remote_sha = (
        remote_digest.split(":", 1)[1].lower()
        if remote_digest.lower().startswith("sha256:")
        else ""
    )
    remote_size = int(remote.get("size") or 0)
    if len(expected_sha) != 64 or expected_size <= 0:
        raise PublishError("Manifest lacks immutable bytes/sha256 identity.")
    if remote_size != expected_size or remote_sha != expected_sha:
        raise PublishError(
            "release asset identity conflict: "
            f"{manifest.get('release_asset')} already exists with a different "
            "size or digest"
        )


def publish_bundle(
    bundle_root: str | Path,
    *,
    repository: str,
    tag: str,
    target: str,
    title: str,
) -> dict[str, Any]:
    if repository != V2_REPOSITORY:
        raise PublishError(
            "dataset publication is locked to the single active Alina repository: "
            f"{V2_REPOSITORY}"
        )
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

    # GitHub caps each Release at 1000 assets. Large replay-grade market
    # windows can legitimately exceed that without being invalid. Keep one
    # canonical production Release (the requested tag) for RUN_MANIFEST.json
    # plus at most 999 data assets, and spill any remaining immutable data
    # assets into deterministic non-production overflow Releases. Every shard
    # manifest records the exact Release that owns its bytes, so replay/index
    # semantics remain unchanged while publication stays below GitHub's cap.
    if DATA_ASSETS_PER_RELEASE <= 0:
        raise PublishError("invalid GitHub release asset capacity")
    chunks = [
        manifests[offset : offset + DATA_ASSETS_PER_RELEASE]
        for offset in range(0, len(manifests), DATA_ASSETS_PER_RELEASE)
    ]
    if not chunks:
        chunks = [[]]

    notes = (
        "Alina SmartFlow dataset V2 collection run.\n\n"
        f"Collector SHA: {index.get('collector_version')}\n"
        f"Shards: {len(manifests)}\n"
        "Final shard manifests are consolidated in RUN_MANIFEST.json.\n"
        "Only manifests with quality_status=SAFE and validation_allowed=true "
        "may be used by validation replays/backtests."
    )

    final_manifests: list[dict[str, Any]] = []
    release_parts: list[dict[str, Any]] = []
    base_release: Mapping[str, Any] | None = None

    for part_index, chunk in enumerate(chunks):
        validate_release_capacity(len(chunk))
        part_tag = overflow_release_tag(tag, part_index)
        part_title = (
            title
            if part_index == 0
            else f"{title} overflow part {part_index + 1}/{len(chunks)}"
        )
        part_notes = (
            notes
            if part_index == 0
            else (
                "Alina SmartFlow immutable overflow data assets.\n\n"
                f"Canonical run tag: {tag}\n"
                f"Part: {part_index + 1}/{len(chunks)}\n"
                "This tag is intentionally outside production catalog discovery; "
                "the canonical RUN_MANIFEST.json references these verified assets."
            )
        )
        release = ensure_release(
            repository=repository,
            tag=part_tag,
            target=target,
            title=part_title,
            notes=part_notes,
        )
        release_id = int(release.get("id") or 0)
        if release_id <= 0:
            raise PublishError("Release id is missing.")
        if part_index == 0:
            base_release = release

        existing_assets = release_asset_map(release)
        for manifest in chunk:
            asset_name = str(manifest.get("release_asset") or "")
            existing = existing_assets.get(asset_name)
            if existing is not None:
                assert_existing_asset_compatible(manifest, existing)

        for manifest in chunk:
            asset_name = str(manifest.get("release_asset") or "")
            if asset_name in existing_assets:
                continue
            local = root / "assets" / asset_name
            upload_file(repository=repository, tag=part_tag, path=local)

        refreshed = _json(["api", f"repos/{repository}/releases/tags/{part_tag}"])
        if not isinstance(refreshed, Mapping):
            raise PublishError("Release payload after upload is invalid.")
        assets = release_asset_map(refreshed)

        for manifest in chunk:
            asset_name = str(manifest.get("release_asset") or "")
            remote = assets.get(asset_name)
            if remote is None:
                raise PublishError(f"Uploaded asset not visible in release: {asset_name}")
            verified = verify_remote_asset(
                manifest,
                repository=repository,
                release_tag=part_tag,
                release_id=release_id,
                asset_id=int(remote.get("id") or 0),
                asset_name=asset_name,
                remote_size=int(remote.get("size") or 0),
                remote_digest=str(remote.get("digest") or ""),
            )
            verified.pop("local_source_path", None)
            verified.pop("local_asset_path", None)
            final_manifests.append(verified)

        release_parts.append(
            {
                "release_tag": part_tag,
                "release_id": release_id,
                "shard_count": len(chunk),
                "catalog_discoverable": part_index == 0,
            }
        )

    if base_release is None:
        raise PublishError("Canonical release was not created.")
    base_release_id = int(base_release.get("id") or 0)
    if base_release_id <= 0:
        raise PublishError("Canonical release id is missing.")

    run_manifest = {
        "schema": "alina.dataset_run_manifest.v2",
        "repository": repository,
        "release_id": base_release_id,
        "release_tag": tag,
        "release_parts": release_parts,
        "collector_version": index.get("collector_version"),
        "collection_run_id": index.get("collection_run_id"),
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
        "safe_coverage_matrix": build_safe_coverage_matrix(final_manifests),
        "read_only": True,
        "real_execution": False,
    }
    run_path = root / "RUN_MANIFEST.json"
    write_manifest(run_manifest, run_path)
    run_identity = {
        "release_asset": "RUN_MANIFEST.json",
        "bytes": run_path.stat().st_size,
        "sha256": hashlib.sha256(run_path.read_bytes()).hexdigest(),
    }

    canonical_release = _json(["api", f"repos/{repository}/releases/tags/{tag}"])
    if not isinstance(canonical_release, Mapping):
        raise PublishError("Canonical release payload is invalid.")
    existing_run = release_asset_map(canonical_release).get("RUN_MANIFEST.json")
    if existing_run is not None:
        assert_existing_asset_compatible(run_identity, existing_run)
    upload_file(repository=repository, tag=tag, path=run_path)

    final_release = _json(["api", f"repos/{repository}/releases/tags/{tag}"])
    final_assets = release_asset_map(
        final_release if isinstance(final_release, Mapping) else {}
    )
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
