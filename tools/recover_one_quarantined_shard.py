#!/usr/bin/env python3
"""Conservatively hydrate ONE existing non-replay shard into quarantine.

Live GitHub Release SHA-256/size must match the authoritative DATA_INDEX,
then the logical member is checked against its own immutable SHA-256/size.
Never changes the canonical index, quality labels, collectors, or SAFE folder.
Requires --download to transfer any bytes, with strict source-size limits.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import urllib.parse
import zipfile
from pathlib import Path
from typing import Any, Mapping

try:
    from tools.partitioned_data_index import read_index
    from tools.preservation_inventory import summarize
    from tools.restore_alina import (
        RestoreError, _download_to_path, _json, _list_release_assets,
        _safe_component, _sha256,
    )
except ModuleNotFoundError:
    from partitioned_data_index import read_index
    from preservation_inventory import summarize
    from restore_alina import (
        RestoreError, _download_to_path, _json, _list_release_assets,
        _safe_component, _sha256,
    )

CANONICAL = "Rapt0r06300/hyperliquid-smart-wallet-observer"
SHA = re.compile(r"[0-9a-f]{64}\Z")
SOURCE_MAX = 256 * 1024 * 1024


def candidate_from_index(index: Mapping[str, Any], dataset_id: str) -> dict[str, Any]:
    matches = [row for row in index["shards"] if row.get("dataset_id") == dataset_id]
    if len(matches) != 1:
        raise ValueError("RECOVERY_CANDIDATE_NOT_UNIQUE_OR_MISSING")
    row = matches[0]
    if row.get("quality_status") not in ("PARTIAL", "REJECT", "STALE") and not (
        row.get("quality_status") == "SAFE" and row.get("replay_compatible") is not True
    ):
        raise ValueError("RECOVERY_CANDIDATE_ALREADY_REPLAY_READY")
    if (row.get("release_repository") or index.get("release_repository_default")) != CANONICAL:
        raise ValueError("RECOVERY_SOURCE_NOT_CANONICAL")
    tag = row.get("release_tag")
    member = row.get("release_asset")
    container = row.get("release_container_asset")
    outer = container if container else member
    logical_sha = row.get("sha256")
    logical_bytes = row.get("bytes")
    remote_size = row.get("release_remote_size") if container else logical_bytes
    remote_sha = row.get("release_remote_digest") if container else logical_sha
    remote_sha = remote_sha.removeprefix("sha256:").lower() if isinstance(remote_sha, str) else None
    if (not isinstance(tag, str) or not tag
            or not isinstance(member, str) or not member
            or Path(member).name != member or "\\" in member
            or not isinstance(outer, str) or not outer
            or type(logical_bytes) is not int or logical_bytes < 0
            or type(remote_size) is not int or remote_size < 0
            or not isinstance(logical_sha, str) or not SHA.fullmatch(logical_sha.lower())
            or not isinstance(remote_sha, str) or not SHA.fullmatch(remote_sha)):
        raise ValueError("RECOVERY_INCOMPLETE_IMMUTABLE_IDENTITY")
    return {
        "dataset_id": dataset_id, "quality_status": row["quality_status"],
        "release_tag": tag, "release_asset": member,
        "release_container_asset": container or None,
        "outer_asset": outer, "logical_bytes": logical_bytes,
        "logical_sha256": logical_sha.lower(), "outer_bytes": remote_size,
        "outer_sha256": remote_sha,
    }


def live_asset(candidate: Mapping[str, Any], *, token: str | None = None) -> dict[str, Any]:
    tag = candidate["release_tag"]
    quoted = urllib.parse.quote(tag, safe="")
    release = _json(
        f"https://api.github.com/repos/{CANONICAL}/releases/tags/{quoted}",
        token=token,
    )
    if not isinstance(release, dict) or release.get("tag_name") != tag:
        raise ValueError("RECOVERY_LIVE_RELEASE_TAG_MISMATCH")
    release_id = release.get("id")
    assets = _list_release_assets(CANONICAL, release_id, token=token)
    matches = [a for a in assets if a.get("name") == candidate["outer_asset"]]
    if len(matches) != 1:
        raise ValueError("RECOVERY_LIVE_ASSET_NOT_UNIQUE_OR_MISSING")
    asset = dict(matches[0])
    url = asset.get("browser_download_url")
    digest = asset.get("digest")
    if (asset.get("state") != "uploaded"
            or type(asset.get("size")) is not int
            or asset["size"] != candidate["outer_bytes"]
            or not isinstance(digest, str)
            or digest.lower() != "sha256:" + candidate["outer_sha256"]
            or not isinstance(url, str)
            or not url.startswith(
                f"https://github.com/{CANONICAL}/releases/download/"
            )):
        raise ValueError("RECOVERY_LIVE_ASSET_IDENTITY_MISMATCH")
    return asset


def _directory(path: Path) -> None:
    if path.is_symlink():
        raise ValueError("RECOVERY_SYMLINK_DIRECTORY")
    path.mkdir(parents=True, exist_ok=True)
    if not path.is_dir() or path.is_symlink():
        raise ValueError("RECOVERY_UNSAFE_DIRECTORY")


def _verified(path: Path, size: int, sha: str) -> bool:
    return (not path.is_symlink() and path.is_file()
            and path.stat().st_size == size and _sha256(path) == sha)


def _publish_verified_bytes(staged: Path, destination: Path, size: int, sha: str) -> None:
    if destination.is_symlink():
        raise ValueError("RECOVERY_SYMLINK_TARGET")
    if destination.exists():
        if not _verified(destination, size, sha):
            raise ValueError("RECOVERY_EXISTING_BYTES_CONFLICT")
        return
    if not _verified(staged, size, sha):
        raise ValueError("RECOVERY_STAGE_BYTES_NOT_VERIFIED")
    try:
        os.link(staged, destination)
    except FileExistsError:
        if not _verified(destination, size, sha):
            raise ValueError("RECOVERY_RACE_BYTES_CONFLICT")
    if not _verified(destination, size, sha):
        raise ValueError("RECOVERY_PUBLISHED_BYTES_MISMATCH")


def hydrate_candidate(
    candidate: Mapping[str, Any], asset: Mapping[str, Any], destination: Path, *,
    download: bool = False, token: str | None = None,
    max_source_bytes: int = SOURCE_MAX,
    catalog_index_sha256: str | None = None,
) -> dict[str, Any]:
    if download and (not isinstance(catalog_index_sha256, str)
                     or not SHA.fullmatch(catalog_index_sha256)):
        raise ValueError("RECOVERY_CATALOG_DIGEST_REQUIRED")
    if download and (type(asset.get("id")) is not int or asset["id"] <= 0):
        raise ValueError("RECOVERY_ASSET_ID_REQUIRED")
    if type(max_source_bytes) is not int or max_source_bytes < 1:
        raise ValueError("RECOVERY_INVALID_SIZE_BUDGET")
    outer_bytes = candidate["outer_bytes"]
    logical_bytes = candidate["logical_bytes"]
    if outer_bytes > max_source_bytes or logical_bytes > max_source_bytes:
        raise ValueError("RECOVERY_EXCEEDS_EXPLICIT_SIZE_BUDGET")
    if (asset.get("size") != outer_bytes
            or asset.get("digest", "").lower() != "sha256:" + candidate["outer_sha256"]):
        raise ValueError("RECOVERY_ASSET_NOT_CATALOG_BOUND")
    report: dict[str, Any] = {
        "schema": "alina.quarantined_candidate_recovery.v1",
        "catalog_index_sha256": catalog_index_sha256,
        "source_repository": CANONICAL,
        "source_asset_id": asset.get("id"),
        "dataset_id": candidate["dataset_id"],
        "original_quality_status": candidate["quality_status"],
        "release_tag": candidate["release_tag"],
        "outer_asset": candidate["outer_asset"],
        "outer_sha256": candidate["outer_sha256"],
        "outer_bytes": outer_bytes,
        "logical_sha256": candidate["logical_sha256"],
        "logical_bytes": logical_bytes,
        "validation_allowed": False, "replay_certified": False,
        "reclassified_safe": False, "paper_only": True,
    }
    if not download:
        return {**report, "status": "LIVE_ASSET_IDENTIFIED_NOT_DOWNLOADED"}
    root = Path(destination)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("RECOVERY_OUTPUT_ROOT_MISSING_OR_SYMLINKED")
    releases = root / "releases"
    tagdir = releases / _safe_component(candidate["release_tag"])
    quarantine = root / "quarantine"
    shards = quarantine / "source_verified_non_replay"
    for folder in (releases, tagdir, quarantine, shards):
        _directory(folder)
    outer = tagdir / _safe_component(candidate["outer_asset"])
    was_cached = outer.is_file()
    if not was_cached:
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=tagdir, prefix=".recovery-",
                                             suffix=".partial", delete=False) as stream:
                temporary = Path(stream.name)
            size, digest = _download_to_path(
                asset["browser_download_url"], temporary, token=token,
                max_bytes=max_source_bytes)
            if size != outer_bytes or digest != candidate["outer_sha256"]:
                raise ValueError("RECOVERY_REMOTE_BYTES_MISMATCH")
            _publish_verified_bytes(temporary, outer, outer_bytes, candidate["outer_sha256"])
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    elif not _verified(outer, outer_bytes, candidate["outer_sha256"]):
        raise ValueError("RECOVERY_EXISTING_OUTER_CONFLICT")
    name = _safe_component(candidate["dataset_id"]) + "." + candidate["logical_sha256"][:16] + ".jsonl.gz"
    target = shards / name
    temp = None
    if not _verified(target, logical_bytes, candidate["logical_sha256"]):
        if target.exists() or target.is_symlink():
            raise ValueError("RECOVERY_EXISTING_LOGICAL_CONFLICT")
        try:
            with tempfile.NamedTemporaryFile(dir=shards, prefix=".member-",
                                             suffix=".partial", delete=False) as stream:
                temp = Path(stream.name)
                if candidate["release_container_asset"]:
                    with zipfile.ZipFile(outer) as archive:
                        matches = [i for i in archive.infolist()
                                   if i.filename == candidate["release_asset"]]
                        if len(matches) != 1 or matches[0].file_size != logical_bytes:
                            raise ValueError("RECOVERY_ZIP_MEMBER_MISSING_OR_SIZE_MISMATCH")
                        with archive.open(matches[0]) as inp:
                            copied = 0
                            while chunk := inp.read(1024 * 1024):
                                copied += len(chunk)
                                if copied > logical_bytes:
                                    raise ValueError("RECOVERY_ZIP_MEMBER_TOO_LARGE")
                                stream.write(chunk)
                else:
                    with outer.open("rb") as inp:
                        while chunk := inp.read(1024 * 1024):
                            stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())
            _publish_verified_bytes(temp, target, logical_bytes, candidate["logical_sha256"])
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)
    receipt = {**report,
               "status": "BYTE_VERIFIED_QUARANTINED_NOT_REPLAY_CERTIFIED",
               "quarantine_file": str(target.relative_to(root)),
               "recovered_bytes": logical_bytes}
    receipt_path = shards / (name + ".receipt.json")
    receipt_bytes = (json.dumps(receipt, sort_keys=True, indent=2) + "\n").encode()
    if receipt_path.exists() or receipt_path.is_symlink():
        if receipt_path.is_symlink() or receipt_path.read_bytes() != receipt_bytes:
            raise ValueError("RECOVERY_RECEIPT_CONFLICT")
    else:
        tmp_receipt = None
        try:
            with tempfile.NamedTemporaryFile(dir=shards, prefix=".receipt-",
                                             suffix=".tmp", delete=False) as stream:
                tmp_receipt = Path(stream.name)
                stream.write(receipt_bytes)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(tmp_receipt, receipt_path)
            except FileExistsError:
                if receipt_path.is_symlink() or receipt_path.read_bytes() != receipt_bytes:
                    raise ValueError("RECOVERY_RECEIPT_RACE_CONFLICT")
        finally:
            if tmp_receipt is not None:
                tmp_receipt.unlink(missing_ok=True)
    return {**receipt, "source_cached_before_run": was_cached}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--index", type=Path, default=Path("catalog/DATA_INDEX.json"))
    parser.add_argument("--metrics", type=Path, default=Path("catalog/DATA_METRICS.json"))
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--max-source-bytes", type=int, default=SOURCE_MAX)
    parser.add_argument("--download", action="store_true",
                        help="Transfer ONE SHA-verified Release asset into quarantine")
    args = parser.parse_args(argv)
    try:
        raw = args.index.read_bytes()
        index = read_index(args.index)
        metrics = json.loads(args.metrics.read_text(encoding="utf-8"))
        summarize(index, metrics, hashlib.sha256(raw).hexdigest())
        candidate = candidate_from_index(index, args.dataset_id)
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        asset = live_asset(candidate, token=token)
        output = hydrate_candidate(
            candidate, asset, args.destination, download=args.download,
            token=token, max_source_bytes=args.max_source_bytes,
            catalog_index_sha256=hashlib.sha256(raw).hexdigest(),
        )
        print(json.dumps(output, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError, RestoreError, zipfile.BadZipFile) as exc:
        print(json.dumps({"status": "RECOVERY_FAIL_CLOSED", "reason": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
