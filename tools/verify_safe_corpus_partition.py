#!/usr/bin/env python3
"""Distributed, fail-closed byte verification for the complete SAFE corpus.

Each GitHub-hosted worker downloads a deterministic subset of the immutable
Release assets selected by the canonical SAFE/replay-ready catalog.  It checks
the outer asset and every selected logical member by size and SHA-256, deletes
the asset, and emits a compact receipt.  The aggregate mode proves exact,
duplicate-free coverage of the same SHA-bound catalog.

This is distributed verification, not a claim that one machine materialized
the entire corpus at once.  ALINA_SYNC_COMPLETE remains the sole restore path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import zipfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

try:
    from tools.restore_alina import (
        DEFAULT_REPOSITORY,
        RestoreError,
        _download_to_path,
        _expected_digest,
        _load_replay_ready_plan,
        _select_replay_ready_releases,
        iter_releases,
    )
except ModuleNotFoundError:  # pragma: no cover - direct tools/ execution
    from restore_alina import (  # type: ignore
        DEFAULT_REPOSITORY,
        RestoreError,
        _download_to_path,
        _expected_digest,
        _load_replay_ready_plan,
        _select_replay_ready_releases,
        iter_releases,
    )

SCHEMA = "alina.safe_corpus_partition_receipt.v1"
CERTIFICATE_SCHEMA = "alina.safe_corpus_distributed_certificate.v1"
HEX64 = re.compile(r"[0-9a-f]{64}")
REPOSITORY = DEFAULT_REPOSITORY


def _sha_lines(lines: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for line in lines:
        digest.update(line.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _member_line(row: Mapping[str, Any]) -> str:
    dataset_id = str(row.get("dataset_id") or "")
    member = str(row.get("release_asset") or "")
    size = row.get("bytes")
    digest = str(row.get("sha256") or "").lower()
    if (
        not dataset_id
        or not member
        or type(size) is not int
        or size < 0
        or HEX64.fullmatch(digest) is None
    ):
        raise RestoreError("SAFE member has invalid immutable identity")
    return f"{dataset_id}\0{member}\0{size}\0{digest}"


def build_outer_specs(
    rows: Iterable[Mapping[str, Any]],
    required: Mapping[tuple[str, str], tuple[int, str]],
) -> list[dict[str, Any]]:
    """Build compact expected evidence for each unique outer Release asset."""
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = {
        key: [] for key in required
    }
    for row in rows:
        tag = str(row.get("release_tag") or "")
        member = str(row.get("release_asset") or "")
        outer = str(row.get("release_container_asset") or member)
        key = (tag, outer)
        if key not in grouped:
            raise RestoreError("SAFE row is absent from required outer assets")
        grouped[key].append(row)

    specs: list[dict[str, Any]] = []
    for (tag, name), (size, digest) in sorted(required.items()):
        members = grouped[(tag, name)]
        if not members:
            raise RestoreError("required SAFE outer asset has no logical members")
        lines = sorted(_member_line(row) for row in members)
        specs.append({
            "release_tag": tag,
            "asset_name": name,
            "asset_bytes": size,
            "asset_sha256": digest,
            "member_rows": len(lines),
            "member_bytes": sum(int(row["bytes"]) for row in members),
            "member_set_sha256": _sha_lines(lines),
            "rows": members,
        })
    return specs


def assign_partitions(
    specs: Iterable[Mapping[str, Any]], partition_count: int,
) -> list[list[Mapping[str, Any]]]:
    """Stable largest-first byte balancing with deterministic tie breaks."""
    if type(partition_count) is not int or not 1 <= partition_count <= 64:
        raise ValueError("partition_count must be between 1 and 64")
    buckets: list[list[Mapping[str, Any]]] = [[] for _ in range(partition_count)]
    totals = [0] * partition_count
    ordered = sorted(
        specs,
        key=lambda item: (
            -int(item["asset_bytes"]),
            str(item["release_tag"]),
            str(item["asset_name"]),
        ),
    )
    for spec in ordered:
        index = min(range(partition_count), key=lambda value: (totals[value], value))
        buckets[index].append(spec)
        totals[index] += int(spec["asset_bytes"])
    for bucket in buckets:
        bucket.sort(key=lambda item: (str(item["release_tag"]), str(item["asset_name"])))
    return buckets


def _asset_summary(spec: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: spec[key]
        for key in (
            "release_tag", "asset_name", "asset_bytes", "asset_sha256",
            "member_rows", "member_bytes", "member_set_sha256",
        )
    }


def _verify_file(path: Path, spec: Mapping[str, Any]) -> dict[str, Any]:
    """Verify every selected logical member in one already-verified outer file."""
    rows = list(spec["rows"])
    zipped = any(row.get("release_container_asset") for row in rows)
    if zipped and not all(row.get("release_container_asset") for row in rows):
        raise RestoreError("outer asset mixes direct and ZIP member evidence")

    verified: dict[str, tuple[int, str]] = {}
    if zipped:
        try:
            with zipfile.ZipFile(path) as archive:
                entries: dict[str, zipfile.ZipInfo] = {}
                for info in archive.infolist():
                    if info.filename in entries:
                        raise RestoreError(f"duplicate ZIP member: {info.filename}")
                    entries[info.filename] = info
                for row in rows:
                    member = str(row["release_asset"])
                    expected = (int(row["bytes"]), str(row["sha256"]).lower())
                    previous = verified.get(member)
                    if previous is not None:
                        if previous != expected:
                            raise RestoreError("conflicting evidence for shared ZIP member")
                        continue
                    info = entries.get(member)
                    if info is None or info.is_dir() or info.file_size != expected[0]:
                        raise RestoreError(f"SAFE ZIP member missing/size mismatch: {member}")
                    digest = hashlib.sha256()
                    count = 0
                    with archive.open(info) as stream:
                        while chunk := stream.read(8 * 1024 * 1024):
                            count += len(chunk)
                            if count > expected[0]:
                                raise RestoreError(f"SAFE ZIP member overflow: {member}")
                            digest.update(chunk)
                    if count != expected[0] or digest.hexdigest() != expected[1]:
                        raise RestoreError(f"SAFE ZIP member SHA-256 mismatch: {member}")
                    verified[member] = expected
        except RestoreError:
            raise
        except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
            raise RestoreError(f"invalid SAFE ZIP asset: {spec['asset_name']}") from exc
    else:
        digest = hashlib.sha256()
        count = 0
        with path.open("rb") as stream:
            while chunk := stream.read(8 * 1024 * 1024):
                count += len(chunk)
                digest.update(chunk)
        actual = (count, digest.hexdigest())
        for row in rows:
            member = str(row["release_asset"])
            expected = (int(row["bytes"]), str(row["sha256"]).lower())
            if actual != expected:
                raise RestoreError(f"direct SAFE member SHA-256 mismatch: {member}")
            verified[member] = expected

    summary = _asset_summary(spec)
    summary["unique_members_verified"] = len(verified)
    summary["status"] = "OUTER_AND_SELECTED_MEMBERS_SHA256_VERIFIED"
    return summary


def _load_specs(index: Path, metrics: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    _safe, proof, rows, required = _load_replay_ready_plan(index, metrics)
    return proof, build_outer_specs(rows, required)


def write_plan(
    *, index: Path, metrics: Path, partitions: int, output: Path,
    max_asset_bytes: int,
) -> dict[str, Any]:
    proof, specs = _load_specs(index, metrics)
    buckets = assign_partitions(specs, partitions)
    largest = max((int(spec["asset_bytes"]) for spec in specs), default=0)
    if largest > max_asset_bytes:
        raise RestoreError(
            f"SAFE outer asset exceeds hosted-runner bound: {largest}>{max_asset_bytes}"
        )
    payload = {
        "schema": "alina.safe_corpus_distributed_plan.v1",
        "status": "READY_FOR_DISTRIBUTED_BYTE_VERIFICATION",
        "repository": REPOSITORY,
        "catalog_sha256": proof["source_index_sha256"],
        "partition_count": partitions,
        "outer_assets": len(specs),
        "outer_bytes": sum(int(spec["asset_bytes"]) for spec in specs),
        "logical_member_rows": sum(int(spec["member_rows"]) for spec in specs),
        "logical_member_bytes": sum(int(spec["member_bytes"]) for spec in specs),
        "largest_outer_asset_bytes": largest,
        "partitions": [
            {
                "partition": index,
                "outer_assets": len(bucket),
                "outer_bytes": sum(int(spec["asset_bytes"]) for spec in bucket),
                "member_rows": sum(int(spec["member_rows"]) for spec in bucket),
                "member_bytes": sum(int(spec["member_bytes"]) for spec in bucket),
            }
            for index, bucket in enumerate(buckets)
        ],
        "distributed_proof_only": True,
        "single_machine_full_restore": False,
        "paper_only": True,
        "real_execution": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return payload


def verify_partition(
    *, index: Path, metrics: Path, partitions: int, partition: int,
    output: Path, token: str | None, work_root: Path, git_sha: str,
    reserve_bytes: int,
) -> dict[str, Any]:
    if not 0 <= partition < partitions:
        raise ValueError("partition index is outside the configured matrix")
    proof, specs = _load_specs(index, metrics)
    selected_specs = assign_partitions(specs, partitions)[partition]
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "IN_PROGRESS_NOT_CERTIFIED",
        "repository": REPOSITORY,
        "git_sha": git_sha,
        "catalog_sha256": proof["source_index_sha256"],
        "partition": partition,
        "partition_count": partitions,
        "expected_outer_assets": len(selected_specs),
        "expected_outer_bytes": sum(int(spec["asset_bytes"]) for spec in selected_specs),
        "verified": [],
        "distributed_proof_only": True,
        "single_machine_full_restore": False,
        "paper_only": True,
        "real_execution": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    inventory_cache = work_root / "inventory-cache"
    releases = list(iter_releases(
        REPOSITORY, token=token, inventory_cache_root=inventory_cache,
    ))
    required = {
        (str(spec["release_tag"]), str(spec["asset_name"])):
        (int(spec["asset_bytes"]), str(spec["asset_sha256"]))
        for spec in selected_specs
    }
    selected = _select_replay_ready_releases(releases, required)
    live: dict[tuple[str, str], Mapping[str, Any]] = {}
    for release in selected:
        tag = str(release["tag_name"])
        for asset in release["assets"]:
            live[(tag, str(asset["name"]))] = asset

    downloads = work_root / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    try:
        for spec in selected_specs:
            key = (str(spec["release_tag"]), str(spec["asset_name"]))
            asset = live.get(key)
            if asset is None:
                raise RestoreError(f"SAFE Release asset absent from live inventory: {key}")
            if (
                asset.get("state") != "uploaded"
                or asset.get("size") != spec["asset_bytes"]
                or _expected_digest(asset) != spec["asset_sha256"]
            ):
                raise RestoreError(f"SAFE Release evidence changed: {key}")
            free = shutil.disk_usage(downloads).free
            needed = int(spec["asset_bytes"]) + reserve_bytes
            if free < needed:
                raise RestoreError(f"hosted runner disk insufficient: {free}<{needed}")
            identity = hashlib.sha256(f"{key[0]}\0{key[1]}".encode()).hexdigest()
            path = downloads / identity
            size, digest = _download_to_path(
                str(asset["browser_download_url"]), path,
                token=token, max_bytes=int(spec["asset_bytes"]),
            )
            if size != spec["asset_bytes"] or digest != spec["asset_sha256"]:
                raise RestoreError(f"SAFE outer asset SHA-256 mismatch: {key}")
            receipt["verified"].append(_verify_file(path, spec))
            path.unlink(missing_ok=True)
            output.write_text(
                json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8"
            )
    except Exception as exc:
        receipt["status"] = "FAILED_NOT_CERTIFIED"
        receipt["error"] = f"{type(exc).__name__}: {exc}"[:1000]
        output.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        raise
    finally:
        shutil.rmtree(downloads, ignore_errors=True)

    receipt["verified_outer_assets"] = len(receipt["verified"])
    receipt["verified_outer_bytes"] = sum(
        int(item["asset_bytes"]) for item in receipt["verified"]
    )
    receipt["verified_member_rows"] = sum(
        int(item["member_rows"]) for item in receipt["verified"]
    )
    receipt["verified_member_bytes"] = sum(
        int(item["member_bytes"]) for item in receipt["verified"]
    )
    if (
        receipt["verified_outer_assets"] != receipt["expected_outer_assets"]
        or receipt["verified_outer_bytes"] != receipt["expected_outer_bytes"]
    ):
        raise RestoreError("partition coverage changed during verification")
    receipt["status"] = "PARTITION_FULLY_BYTE_VERIFIED"
    output.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return receipt


def aggregate(
    *, index: Path, metrics: Path, partitions: int,
    receipts: Path, output: Path, git_sha: str,
) -> dict[str, Any]:
    proof, specs = _load_specs(index, metrics)
    buckets = assign_partitions(specs, partitions)
    expected = {
        (str(spec["release_tag"]), str(spec["asset_name"])): _asset_summary(spec)
        for spec in specs
    }
    files = sorted(receipts.glob("safe-corpus-partition-*.json"))
    if len(files) != partitions:
        raise RestoreError(f"expected {partitions} partition receipts, found {len(files)}")
    seen_partitions: set[int] = set()
    seen_assets: set[tuple[str, str]] = set()
    total_member_rows = total_member_bytes = total_outer_bytes = 0
    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        part = payload.get("partition")
        if (
            payload.get("schema") != SCHEMA
            or payload.get("status") != "PARTITION_FULLY_BYTE_VERIFIED"
            or payload.get("repository") != REPOSITORY
            or payload.get("git_sha") != git_sha
            or payload.get("catalog_sha256") != proof["source_index_sha256"]
            or payload.get("partition_count") != partitions
            or type(part) is not int
            or part in seen_partitions
        ):
            raise RestoreError(f"invalid partition receipt: {path.name}")
        expected_keys = {
            (str(spec["release_tag"]), str(spec["asset_name"])) for spec in buckets[part]
        }
        actual_keys: set[tuple[str, str]] = set()
        for item in payload.get("verified", []):
            key = (str(item.get("release_tag") or ""), str(item.get("asset_name") or ""))
            if key in actual_keys or key in seen_assets or expected.get(key) != {
                field: item.get(field) for field in expected[key]
            }:
                raise RestoreError(f"duplicate or mismatched SAFE receipt evidence: {key}")
            actual_keys.add(key)
            seen_assets.add(key)
            total_outer_bytes += int(item["asset_bytes"])
            total_member_rows += int(item["member_rows"])
            total_member_bytes += int(item["member_bytes"])
        if actual_keys != expected_keys:
            raise RestoreError(f"partition {part} does not exactly cover its assignment")
        seen_partitions.add(part)
    if seen_partitions != set(range(partitions)) or seen_assets != set(expected):
        raise RestoreError("distributed SAFE receipts do not cover the entire plan")

    certificate = {
        "schema": CERTIFICATE_SCHEMA,
        "status": "DISTRIBUTED_SAFE_CORPUS_BYTES_FULLY_VERIFIED",
        "repository": REPOSITORY,
        "git_sha": git_sha,
        "catalog_sha256": proof["source_index_sha256"],
        "partition_count": partitions,
        "verified_outer_assets": len(seen_assets),
        "verified_outer_bytes": total_outer_bytes,
        "verified_logical_member_rows": total_member_rows,
        "verified_logical_member_bytes": total_member_bytes,
        "exact_partition_coverage": True,
        "outer_size_sha256_verified": True,
        "selected_member_size_sha256_verified": True,
        "single_machine_full_restore": False,
        "distributed_proof_only": True,
        "paper_only": True,
        "real_execution": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(certificate, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return certificate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("plan", "verify", "aggregate"))
    parser.add_argument("--index", type=Path, default=Path("catalog/DATA_INDEX.json"))
    parser.add_argument("--metrics", type=Path, default=Path("catalog/DATA_METRICS.json"))
    parser.add_argument("--partitions", type=int, default=24)
    parser.add_argument("--partition", type=int)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipts", type=Path)
    parser.add_argument("--work-root", type=Path)
    parser.add_argument("--max-asset-bytes", type=int, default=10 * 1024**3)
    parser.add_argument("--reserve-bytes", type=int, default=2 * 1024**3)
    args = parser.parse_args(argv)
    try:
        if args.mode == "plan":
            payload = write_plan(
                index=args.index, metrics=args.metrics, partitions=args.partitions,
                output=args.output, max_asset_bytes=args.max_asset_bytes,
            )
        elif args.mode == "verify":
            if args.partition is None or args.work_root is None:
                parser.error("verify requires --partition and --work-root")
            token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
            if not token:
                raise RestoreError("authenticated GitHub token required")
            payload = verify_partition(
                index=args.index, metrics=args.metrics, partitions=args.partitions,
                partition=args.partition, output=args.output, token=token,
                work_root=args.work_root,
                git_sha=os.environ.get("GITHUB_SHA", ""),
                reserve_bytes=args.reserve_bytes,
            )
        else:
            if args.receipts is None:
                parser.error("aggregate requires --receipts")
            payload = aggregate(
                index=args.index, metrics=args.metrics, partitions=args.partitions,
                receipts=args.receipts, output=args.output,
                git_sha=os.environ.get("GITHUB_SHA", ""),
            )
        print(json.dumps(payload, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError, RestoreError) as exc:
        print(f"SAFE_CORPUS_VERIFY_FAIL: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
