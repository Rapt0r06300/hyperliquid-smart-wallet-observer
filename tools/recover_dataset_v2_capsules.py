#!/usr/bin/env python3
"""Finish Dataset V2 publication from durable recovery capsules.

This is a cloud repair path for the case where the exact collection bundle was
safely uploaded first, but later per-shard Release publication hit GitHub API
rate limits. It never recollects or fabricates data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import publish_dataset_v2_release as publisher

DEFAULT_REPOSITORY = "Rapt0r06300/hyperliquid-smart-wallet-observer"
RECOVERY_PREFIX = "alina-recovery-"
INDEX_NAME = "ALINA_RECOVERY_INDEX.json"
COMPLETE_NAME = "CANONICAL_PUBLICATION.json"


class RecoveryError(RuntimeError):
    pass


def _gh(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("gh")
    if not executable:
        raise RecoveryError("GitHub CLI (gh) is required")
    if not (os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")):
        raise RecoveryError("GH_TOKEN/GITHUB_TOKEN is missing")

    # Only retry idempotent API GETs and replaceable Release downloads.
    # GitHub can intermittently return HTTP 502/503/504 while enumerating
    # historical Releases; failing once would strand recoverable capsules.
    retryable_read = (
        (bool(args) and args[0] == "api"
         and not any(arg in {"-X", "--method"} for arg in args))
        or args[:2] == ["release", "download"]
    )
    attempts = 4 if retryable_read else 1
    for attempt in range(attempts):
        result = subprocess.run(
            [executable, *args],
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode == 0:
            break
        detail = (result.stderr or result.stdout or "").lower()
        transient = (
            any(f"http {status}" in detail for status in (429, 502, 503, 504))
            or "timed out" in detail
            or "timeout" in detail
            or "couldn't respond" in detail
        )
        if not retryable_read or not transient or attempt + 1 == attempts:
            break
        time.sleep(min(2 ** attempt, 4))
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RecoveryError(f"gh {' '.join(args)} failed: {detail}")
    return result


def _json_api(path: str) -> Any:
    result = _gh(["api", path])
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RecoveryError(f"invalid JSON from GitHub API: {path}") from exc


def list_recovery_releases(repository: str) -> list[Mapping[str, Any]]:
    releases: list[Mapping[str, Any]] = []
    page = 1
    while True:
        payload = _json_api(f"repos/{repository}/releases?per_page=100&page={page}")
        if not isinstance(payload, list):
            raise RecoveryError("release listing is not an array")
        if not payload:
            break
        for row in payload:
            if isinstance(row, Mapping) and str(row.get("tag_name") or "").startswith(
                RECOVERY_PREFIX
            ):
                releases.append(row)
        if len(payload) < 100:
            break
        page += 1
    releases.sort(key=lambda row: str(row.get("created_at") or ""))
    return releases


def _download(repository: str, tag: str, pattern: str, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    _gh(
        [
            "release",
            "download",
            tag,
            "--repo",
            repository,
            "--pattern",
            pattern,
            "--dir",
            str(destination),
            "--clobber",
        ]
    )
    path = destination / pattern
    if not path.is_file():
        raise RecoveryError(f"downloaded asset missing: {tag}/{pattern}")
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_extract(archive_path: Path, destination: Path) -> None:
    destination = destination.resolve()
    with tarfile.open(archive_path, "r") as archive:
        for member in archive.getmembers():
            target = (destination / member.name).resolve()
            if destination != target and destination not in target.parents:
                raise RecoveryError(f"unsafe recovery archive member: {member.name}")
            if member.issym() or member.islnk():
                raise RecoveryError(f"links are forbidden in recovery archive: {member.name}")
        archive.extractall(destination)


def _canonical_complete(repository: str, requested_tag: str) -> bool:
    candidates = [requested_tag]
    result = _gh(
        ["api", f"repos/{repository}/releases/tags/{requested_tag}"],
        check=False,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").lower()
        if "http 404" in message:
            return False
        raise RecoveryError("cannot verify canonical Release status: " + message[:300])
    if result.returncode == 0:
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            return False
        assets = payload.get("assets") if isinstance(payload, Mapping) else None
        if isinstance(assets, list) and any(
            isinstance(asset, Mapping) and asset.get("name") == "RUN_MANIFEST.json"
            for asset in assets
        ):
            return True

    # Large/retry publications may finalize on a deterministic derived tag.
    # We deliberately do not guess every derived tag here: if the requested tag
    # is incomplete, replaying publish_bundle is idempotent and will resolve the
    # correct canonical/retry tag from the exact capsule contents.
    return False


def _candidate_canonical_tags(bundle_root: Path, requested_tag: str) -> list[str]:
    index_path = bundle_root / "BUNDLE_INDEX.json"
    try:
        bundle_index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RecoveryError("recovered BUNDLE_INDEX.json is invalid") from exc
    manifest_paths = [
        bundle_root / str(value)
        for value in bundle_index.get("manifests", [])
        if str(value).strip()
    ]
    manifests: list[Mapping[str, Any]] = []
    for path in manifest_paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RecoveryError(f"invalid recovered manifest: {path}") from exc
        if not isinstance(payload, Mapping):
            raise RecoveryError(f"invalid recovered manifest mapping: {path}")
        manifests.append(payload)
    retry = publisher.retry_release_tag(
        requested_tag,
        bundle_index.get("collection_run_id"),
        manifests,
    )
    return [
        requested_tag,
        publisher.manifest_release_tag(requested_tag),
        retry,
        publisher.manifest_release_tag(retry),
    ]


def _any_canonical_complete(repository: str, tags: list[str]) -> str | None:
    for tag in dict.fromkeys(tags):
        result = _gh(
            ["api", f"repos/{repository}/releases/tags/{tag}"],
            check=False,
        )
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "").lower()
            if "http 404" in message:
                continue
            raise RecoveryError("cannot verify canonical Release status: " + message[:300])
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            continue
        assets = payload.get("assets") if isinstance(payload, Mapping) else None
        if isinstance(assets, list) and any(
            isinstance(asset, Mapping) and asset.get("name") == "RUN_MANIFEST.json"
            for asset in assets
        ):
            return tag
    return None


def recover_one(repository: str, release: Mapping[str, Any], work_root: Path) -> dict[str, Any]:
    tag = str(release.get("tag_name") or "")
    if not tag.startswith(RECOVERY_PREFIX):
        raise RecoveryError("not an Alina recovery release")

    capsule_dir = work_root / tag
    index_path = _download(repository, tag, INDEX_NAME, capsule_dir)
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RecoveryError(f"invalid recovery index in {tag}") from exc
    if not isinstance(index, Mapping) or index.get("schema") != "alina.recovery_capsule.v1":
        raise RecoveryError(f"unsupported recovery index in {tag}")

    requested_tag = str(index.get("requested_release_tag") or "")
    if not requested_tag:
        raise RecoveryError(f"missing requested_release_tag in {tag}")
    if _canonical_complete(repository, requested_tag):
        return {"recovery_tag": tag, "requested_tag": requested_tag, "status": "ALREADY_COMPLETE"}

    parts = index.get("parts")
    if not isinstance(parts, list) or not parts:
        raise RecoveryError(f"recovery capsule {tag} has no parts")

    bundle_root = capsule_dir / "bundle"
    bundle_root.mkdir(parents=True, exist_ok=True)
    for part in parts:
        if not isinstance(part, Mapping):
            raise RecoveryError(f"invalid recovery part row in {tag}")
        name = str(part.get("name") or "")
        expected_sha = str(part.get("sha256") or "").lower()
        expected_bytes = int(part.get("bytes") or 0)
        if not name or len(expected_sha) != 64 or expected_bytes <= 0:
            raise RecoveryError(f"invalid recovery part identity in {tag}")
        path = _download(repository, tag, name, capsule_dir)
        if path.stat().st_size != expected_bytes:
            raise RecoveryError(f"size mismatch for {tag}/{name}")
        if _sha256(path) != expected_sha:
            raise RecoveryError(f"sha256 mismatch for {tag}/{name}")
        _safe_extract(path, bundle_root)

    bundle_index = bundle_root / "BUNDLE_INDEX.json"
    expected_index_sha = str(index.get("bundle_index_sha256") or "").lower()
    if not bundle_index.is_file() or len(expected_index_sha) != 64:
        raise RecoveryError(f"missing bundle index evidence in {tag}")
    if _sha256(bundle_index) != expected_index_sha:
        raise RecoveryError(f"BUNDLE_INDEX sha256 mismatch in {tag}")

    completed_tag = _any_canonical_complete(
        repository,
        _candidate_canonical_tags(bundle_root, requested_tag),
    )
    if completed_tag is not None:
        return {
            "recovery_tag": tag,
            "requested_tag": requested_tag,
            "status": "ALREADY_COMPLETE",
            "canonical_release_tag": completed_tag,
        }

    previous = os.getenv("ALINA_RECOVERY_CAPSULE")
    os.environ["ALINA_RECOVERY_CAPSULE"] = "0"
    try:
        result = publisher.publish_bundle(
            bundle_root,
            repository=repository,
            tag=requested_tag,
            target=str(index.get("target") or "main"),
            title=str(index.get("title") or f"Alina dataset V2 {requested_tag}"),
        )
    finally:
        if previous is None:
            os.environ.pop("ALINA_RECOVERY_CAPSULE", None)
        else:
            os.environ["ALINA_RECOVERY_CAPSULE"] = previous

    return {
        "recovery_tag": tag,
        "requested_tag": requested_tag,
        "status": "RECOVERED",
        "canonical_release_tag": result.get("release_tag"),
        "shard_count": result.get("shard_count"),
    }


def recover_pending(repository: str, *, limit: int) -> dict[str, Any]:
    releases = list_recovery_releases(repository)
    report: dict[str, Any] = {
        "schema": "alina.recovery_publication_report.v1",
        "repository": repository,
        "scanned": len(releases),
        "attempted": 0,
        "recovered": 0,
        "already_complete": 0,
        "failures": [],
        "results": [],
        "read_only_market_data": True,
        "real_execution": False,
    }
    with tempfile.TemporaryDirectory(prefix="alina-recovery-") as tmp:
        root = Path(tmp)
        for release in releases:
            assets = release.get("assets")
            if isinstance(assets, list) and any(
                isinstance(asset, Mapping) and asset.get("name") == COMPLETE_NAME
                for asset in assets
            ):
                report["already_complete"] += 1
                continue
            if report["attempted"] >= max(0, limit):
                break
            try:
                result = recover_one(repository, release, root)
                report["results"].append(result)
                if result["status"] == "ALREADY_COMPLETE":
                    report["already_complete"] += 1
                    continue
                report["attempted"] += 1
                report["recovered"] += 1
            except RecoveryError as exc:
                report["attempted"] += 1
                report["failures"].append(
                    {"tag": release.get("tag_name"), "error": str(exc)}
                )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--limit", type=int, default=2)
    args = parser.parse_args(argv)
    try:
        report = recover_pending(args.repository, limit=max(1, args.limit))
    except (RecoveryError, publisher.PublishError, OSError, ValueError) as exc:
        print(f"ALINA_RECOVERY_REPUBLISH_FAIL: {exc}")
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not report["failures"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
